# Velora technical documentation

Velora is a multi-tenant workspace for creating, publishing, and analyzing print-on-demand products. It currently uses Printify and Gelato as fulfillment providers, Etsy as the implemented marketplace integration, with Shopify as a future planned integration, Clerk for identity, Neon Postgres for application data, S3-compatible storage for private media, and Redis with Dramatiq for background work.

## Contents

- [System overview](#system-overview)
- [Architecture](#architecture)
- [Repository structure](#repository-structure)
- [Frontend](#frontend)
- [Backend API](#backend-api)
- [Core workflows](#core-workflows)
- [Data model](#data-model)
- [External integrations](#external-integrations)
- [Background work and reliability](#background-work-and-reliability)
- [Analytics](#analytics)
- [Security and privacy](#security-and-privacy)
- [Configuration](#configuration)
- [Local development](#local-development)
- [Testing and continuous integration](#testing-and-continuous-integration)
- [Deployment and operations](#deployment-and-operations)
- [Known implementation and operations gaps](#known-implementation-and-operations-gaps)
- [Current product boundaries](#current-product-boundaries)
- [Implementation reference](#implementation-reference)
- [Glossary](#glossary)

## System overview

Velora is a modular monolith with separately deployed web, API, worker, and scheduler processes. It supports these current capabilities:

- Clerk sign-in and sign-up with Velora-owned organization access.
- One active organization membership per user, with `admin` and `member` roles.
- Labeled, encrypted Printify and Gelato credentials.
- Multiple provider store connections and an organization-wide store context.
- Etsy OAuth connections, seller-account discovery, and store mapping.
- Provider-backed product blueprints.
- Revisioned product drafts with private design assets and ordered marketplace images.
- Review-first AI listing suggestions through an optional OpenRouter integration.
- Durable, idempotent publishing jobs.
- Incremental Printify and Gelato order synchronization.
- Observable Etsy marketplace-sales ingestion, expense and foreign-exchange data, and business analytics.
- Organization-scoped PostgreSQL row-level security.

Velora follows a provider-first publishing rule:

```text
Velora product
  -> Printify or Gelato product
  -> provider-connected storefront listing
  -> Etsy metadata and gallery completion, when applicable
```

Velora doesn't create a new Etsy listing independently of a POD provider. After a listing exists, an explicit send can update supported Etsy fields directly.

### Current technology stack

| Layer | Implementation |
| --- | --- |
| Web application and BFF | Next.js 15.5.20, React 19, TypeScript 5.x, and the App Router |
| Identity UI | Clerk for Next.js 7.4.2 |
| UI | Tailwind CSS 3.4.17, local shadcn/ui primitives, Radix UI, Lucide icons, Motion 11.15.0, and Recharts 2.15.4 |
| API | FastAPI 0.115.6, Pydantic 2.x, and pydantic-settings 2.7.0 |
| Persistence | SQLAlchemy 2.0.36, Alembic 1.14.0, psycopg 3.2.13, and Neon Postgres |
| Local and default tests | SQLite |
| Private media | Boto3 1.35.81 against an S3-compatible service, such as Cloudflare R2 |
| Queue and distributed coordination | Redis or Valkey and Dramatiq 1.17.1 |
| Scheduling | APScheduler 3.11.0 |
| AI | OpenRouter, disabled by default |
| Deployment baseline | DigitalOcean App Platform |
| Browser tests | Playwright 1.61.1 with Google Chrome |

## Architecture

### Component responsibilities

| Component | Responsibilities |
| --- | --- |
| Browser | Renders the workspace, keeps unsaved editor state, selects store context, and polls jobs. |
| Next.js web service | Renders server and client components, integrates Clerk, protects routes, applies browser security headers, and proxies API traffic. |
| FastAPI API service | Verifies identity, resolves membership, applies tenant context, validates requests, manages domain records, and enqueues work. |
| PostgreSQL | Stores identity mappings, tenant data, product state, jobs, analytics, and audit-like AI acceptance records. |
| S3-compatible storage | Stores private design files and marketplace images and returns short-lived signed download URLs. |
| Redis or Valkey | Transports Dramatiq messages, supports shared Etsy request limiting, and supports AI burst limits. |
| Dramatiq worker | Runs publishing, order synchronization, Etsy sales ingestion, and analytics refresh actors. |
| APScheduler | Periodically finds due work, dispatches outbox rows, and recovers expired jobs. |

### Request path

1. Clerk establishes the browser session.
2. `middleware.ts` protects workspace and BFF routes.
3. Browser code calls `/api/backend/*` on the Next.js origin.
4. The BFF obtains the active Clerk token and forwards it as a bearer token.
5. FastAPI verifies the token, resolves the app-owned user and membership, and sets transaction-local tenant variables.
6. The service executes tenant-filtered application logic.
7. PostgreSQL RLS provides a second tenant boundary in non-test PostgreSQL environments.

Browser code doesn't call FastAPI, PostgreSQL, provider APIs, OpenRouter, or object storage credentials directly.

### Architectural boundaries

- The frontend calls typed functions in `lib/backend-api.ts`; it doesn't contain provider API clients.
- FastAPI routes translate HTTP requests into service calls.
- Services own domain rules and persistence changes.
- Provider adapters implement a common Printify/Gelato contract.
- Alembic migrations, not ORM auto-creation, define deployed database changes.
- Long-running and retryable work uses durable database records plus queue messages.
- Operational logs and durable business audit logs are separate concerns. Durable general audit logging isn't implemented yet.

## Repository structure

| Path | Purpose |
| --- | --- |
| `app/` | Next.js routes, layouts, middleware-facing pages, and the BFF route |
| `components/` | Authentication, workspace, and local shadcn/ui components |
| `hooks/` | Cached-resource, window-focus, and responsive hooks |
| `lib/` | Typed API client, security helpers, page cache, editor logic, logging, and unit tests |
| `backend/app/api/` | FastAPI router, dependencies, and route modules |
| `backend/app/services/` | Domain and integration orchestration |
| `backend/app/providers/` | Printify, Gelato, and provider-interface code |
| `backend/app/db/` | Engine setup, ORM models, RLS context, and runtime-role checks |
| `backend/app/jobs/` | Dramatiq actors |
| `backend/app/storage/` | S3-compatible object storage |
| `backend/alembic/` | Migration environment and ordered migration revisions |
| `backend/tests/` | Backend unit, route, migration, concurrency, and integration-style tests |
| `e2e/` | Playwright contracts and a mock backend |

## Frontend

### Route map

| Route | Access | Purpose |
| --- | --- | --- |
| `/` | Public | Redirects to `/dashboard`; downstream protection handles authentication. |
| `/sign-in/[[...sign-in]]` | Public | Clerk sign-in, recovery routes, and password-reset handoff. |
| `/sign-up/[[...sign-up]]` | Public | Clerk sign-up and verification. |
| `/onboarding` | Signed-in identity | Creates an organization or submits a join-code request. |
| `/dashboard` | Approved member | Shows products, blueprints, providers, stores, and publishing activity. |
| `/product-studio` | Approved member | Creates a blueprint-backed product draft. |
| `/blueprints` | Approved member | Creates, validates, edits, and deletes provider-backed blueprints. |
| `/products` | Approved member | Shows draft and published products for the current store scope. |
| `/products/[productId]` | Approved member | Edits a saved product and starts sends. |
| `/orders` | Approved member | Shows paginated orders and order-sync state. |
| `/analytics` | Approved member | Shows operational and business analytics. |
| `/settings` | Admin | Manages the organization, members, Etsy, provider credentials, and stores. |
| `/settings/etsy/callback` | OAuth callback | Completes the Etsy popup flow and reports to the opener. |
| `/account/[[...account]]` | Approved member | Manages profile, email, password, sessions, and workspace access. |
| `/api/backend/[...path]` | Protected BFF | Proxies browser requests to FastAPI. |

The sidebar intentionally omits separate pages for providers, publishing, mockups, and product templates. Their operations live in Settings, Products, Product Detail, Product Studio, and Blueprints.

### Authentication and route protection

`middleware.ts` uses Clerk middleware when frontend Clerk variables are present. It protects:

- Onboarding routes.
- Workspace routes.
- Settings routes.
- BFF routes.

The workspace layout fetches the current Velora session context on the server. It redirects identities without approved membership to `/onboarding`. The Settings layout redirects non-admin members to `/dashboard`.

Development can use a local auth fallback only when the frontend and backend resolve to local-safe configuration. Non-development backend validation rejects missing Clerk verification, unsafe auth mode, unsafe CORS, non-TLS database URLs, and insecure API origins.

### Browser-to-API proxy

The catch-all BFF route:

- Builds the FastAPI URL from `VELORA_API_BASE_URL`.
- Gets a Clerk token when Clerk is active.
- Forwards the request method, query string, body stream, content type, authorization, and request ID.
- Uses `cache: "no-store"`.
- Performs an early known-length check for media uploads.
- Streams the upstream response.
- Converts unexpected upstream HTML into a JSON `502` error.
- Converts connection failures into a JSON `503` error.
- Doesn't expose the FastAPI origin to normal browser application code.

Backend errors use a `detail` field. `lib/backend-api.ts` converts them into `BackendApiError` objects and retains structured field-level readiness failures where available.

### Workspace state and caching

The workspace keeps several kinds of state:

- The selected provider-store connection is persisted to both a cookie and browser storage.
- The special all-store scope is available throughout the workspace.
- Product Studio uses the selected blueprint as the publishing target; the global store switcher doesn't replace that target.
- Page resource data uses an in-memory cache scoped by user and organization.
- The default page-cache maximum age is 60 seconds.
- Concurrent requests for the same key share one in-flight promise.
- Mutations clear related cache prefixes.
- Focus and visibility events refetch eligible resources only when their minimum interval has passed.
- Orders use a five-hour server-enforced synchronization freshness interval.
- Analytics keeps GET and focus refreshes read-only. A connected organization with no prior marketplace-sales attempt issues one explicit background-sync POST on its first Analytics visit.

### Major workspace pages

#### Dashboard

The Dashboard loads products, blueprints, providers, publishing jobs, store connections, and Product Studio state. It derives counts and recent activity for the active store scope and links users to the relevant product and setup flows.

#### Product Studio

Product Studio:

1. Requires an individual store and a compatible blueprint.
2. Accepts one design image and a design description.
3. Accepts up to 10 marketplace images.
4. Edits title, description, up to 13 tags, SKU, retail price, and currency, and shows provider cost and derived margin.
5. Saves the local draft before using AI or publishing.
6. Uploads private media after the product has an organization-scoped identity.
7. Routes to Product Detail after the draft exists.

The editor tracks dirty state separately from the last saved revision. Publishing always submits the exact saved revision.

#### Product Detail

Product Detail provides the saved-product version of Product Studio. It supports:

- Optimistic revision updates.
- Design, listing, pricing, and SEO edits.
- Marketplace image upload, reorder, hero selection, and deletion.
- AI generation, field regeneration, review, and selective apply.
- Readiness guidance.
- Durable send creation and job polling.
- Product deletion from Velora.

Saving a published Etsy product changes only Velora. The seller must select **Send to Etsy** to update the external listing.

#### Orders

Orders:

- Uses server pagination with 15 rows by default.
- Applies the global store scope before local status filters.
- Shows current or latest synchronization state.
- Starts an automatic synchronization only when backend freshness permits it.
- Supports a force refresh that still reuses active work.
- Polls active jobs and reloads orders after `completed` or `partial` results.

#### Analytics

Analytics supports:

- Presets for recent periods, current month or year, all time, and custom dates.
- PHP, USD, EUR, and JPY reporting.
- Organization reporting timezone.
- Revenue, expenses, gross profit, net profit, orders, and coverage.
- Profit-and-loss, order, and margin trends.
- Product, store, expense, SEO, and operations workspaces.
- Server-paginated detail tables.
- Formula-injection-safe CSV export.
- Admin-only expense mutations and unmatched-line mapping.
- Latest Etsy sales attempt, last successful import, processed-record counts, and actionable blocker details.
- A manual **Sync Etsy** action that bypasses terminal freshness but still reuses active work.

The first Analytics visit starts an Etsy sales import only when Etsy is connected and the organization has no previous marketplace-sales attempt. Normal Analytics reads and focus refreshes never perform marketplace HTTP or implicitly create jobs.

#### Settings and account

Settings is admin-only and covers:

- Organization name and join code.
- Pending join requests.
- Approved members and member removal.
- Etsy OAuth accounts and discovered shops.
- Printify and Gelato credential groups.
- Provider-store discovery and connection lifecycle.
- Manual Gelato store seeds.
- Per-connection Etsy shop ID overrides.

Account settings uses Clerk for identity features and Velora for leaving the current organization.

## Backend API

### Access levels

| Access level | Meaning |
| --- | --- |
| Public | No actor or workspace dependency |
| Identity | Authenticated or local actor; approved membership isn't required |
| Workspace | Actor must have an approved Velora membership |
| Admin | Actor must have an approved membership with role `admin` |

In Clerk mode, FastAPI validates RS256 JWTs against the configured JWKS. It requires expiration, honors not-before and clock skew, validates issuer when configured, and requires `azp` to match an authorized party when that allowlist is configured. A changed key ID triggers one JWKS refresh.

### Common behavior

- JSON is the default request and response format.
- Upload endpoints use multipart form data.
- IDs are strings generated by application services.
- Domain validation usually returns `400`, `409`, `413`, `415`, or `422`.
- Missing tenant-scoped resources return `404`.
- Missing authentication returns `401`; missing role or membership returns `403`.
- Provider and worker errors are sanitized before they enter API responses or job records.
- `X-Request-ID` correlates BFF, API, and log events.
- CORS allows only configured origins, methods, and headers.

### Health and session endpoints

| Method and path | Access | Behavior |
| --- | --- | --- |
| `GET /health` | Public | Returns process liveness, application name, and version. |
| `GET /health/ready` | Public | Returns ready only after a database query and Redis ping succeed. |
| `GET /session-context` | Identity | Resolves the user, onboarding state, organization, membership, role, and pending join request. |

### Organization endpoints

| Method and path | Access | Behavior |
| --- | --- | --- |
| `POST /organizations` | Identity | Creates an organization and its initial admin membership. |
| `PATCH /organizations` | Admin | Updates the organization name. |
| `POST /organizations/join-requests` | Identity | Creates a pending request from a normalized join code. |
| `POST /organizations/leave` | Identity | Leaves the organization; transfers admin to the oldest eligible member or blocks the sole admin. |
| `GET /organizations/members` | Admin | Lists approved members. |
| `POST /organizations/members/{member_user_id}/remove` | Admin | Removes a non-admin member. |
| `GET /organizations/join-requests` | Admin | Lists pending requests. |
| `POST /organizations/join-requests/{join_request_id}/approve` | Admin | Approves a pending request and creates membership. |
| `POST /organizations/join-requests/{join_request_id}/reject` | Admin | Rejects a pending request. |

The database enforces one membership per user, so the current product supports one active organization per user.

### Analytics endpoints

| Method and path | Access | Behavior |
| --- | --- | --- |
| `GET /analytics` | Workspace | Returns operational workspace analytics and Etsy snapshot freshness. Accepts optional `store_connection_id`. |
| `GET /analytics/business` | Workspace | Returns KPIs, comparison, trends, coverage, and optional details. |
| `GET /analytics/business/details` | Workspace | Returns a page of `products`, `expenses`, `seo`, or `unmatched` records. |
| `POST /analytics/expenses` | Admin | Creates a manual expense. |
| `PATCH /analytics/expenses/{expense_id}` | Admin | Updates a manual expense. |
| `DELETE /analytics/expenses/{expense_id}` | Admin | Deletes a manual expense. |
| `POST /analytics/unmatched/{line_id}/map` | Admin | Maps an unmatched marketplace line to a Velora product. |
| `PATCH /analytics/preferences` | Admin | Updates reporting currency and IANA timezone. |

`GET /analytics/business` accepts `store_connection_id`, `preset`, `start`, `end`, `currency`, `timezone`, and `include_details`. Custom periods require both dates. The details endpoint accepts page sizes from 10 through 100 and defaults to 25.

### Blueprint endpoints

| Method and path | Access | Behavior |
| --- | --- | --- |
| `GET /blueprints` | Workspace | Lists organization blueprints. |
| `POST /blueprints` | Workspace | Validates the provider reference, captures a provider snapshot, and creates a blueprint. |
| `GET /blueprints/{blueprint_id}` | Workspace | Gets one blueprint. |
| `PATCH /blueprints/{blueprint_id}` | Workspace | Updates blueprint metadata and provider reference. |
| `DELETE /blueprints/{blueprint_id}` | Workspace | Deletes an unused blueprint; products referencing it cause a conflict. |
| `POST /blueprints/{blueprint_id}/validate-reference` | Workspace | Refreshes reference validation and provider-derived configuration. |

Supported references are a Printify product URL or product ID and a Gelato template ID.

### Product and media endpoints

| Method and path | Access | Behavior |
| --- | --- | --- |
| `POST /design-assets` | Workspace | Validates and stores one private design image. |
| `GET /products` | Workspace | Lists organization products. |
| `POST /products` | Workspace | Creates a revision-1 product from a valid blueprint and design asset. |
| `GET /products/{product_id}` | Workspace | Returns the product, blueprint, store, media, POD product, and status. |
| `PATCH /products/{product_id}` | Workspace | Applies an optimistic revision update. |
| `DELETE /products/{product_id}` | Workspace | Deletes the Velora product and unshared media but doesn't delete external provider records. |
| `POST /products/{product_id}/mockups` | Workspace | Uploads one marketplace image. |
| `PATCH /products/{product_id}/mockups/order` | Workspace | Reorders all product images. |
| `DELETE /products/{product_id}/mockups/{mockup_id}` | Workspace | Deletes one product image. |
| `POST /products/{product_id}/publish` | Workspace | Validates an expected revision and creates or reuses a durable publishing job. |
| `GET /product-studio` | Workspace | Returns providers, stores, blueprints, and constraints needed by Product Studio. |

Image uploads accept PNG, JPEG, or WebP. The backend checks declared type, internal file structure, dimensions, length, and checksum. SVG isn't accepted.

### Provider and Etsy endpoints

| Method and path | Access | Behavior |
| --- | --- | --- |
| `GET /pod-providers` | Workspace | Lists supported provider definitions. |
| `PUT /pod-providers/{provider}/credentials` | Admin | Creates or updates a labeled encrypted credential group. |
| `DELETE /pod-providers/{provider}/credentials/{credential_key}` | Admin | Deletes one credential group and its eligible connections. |
| `GET /pod-providers/{provider}/credentials/status` | Admin | Returns safe credential status and store counts. |
| `GET /provider-store-connections` | Workspace | Lists active provider stores without opaque discovery payloads. |
| `POST /provider-store-connections/sync/{provider}` | Admin | Discovers stores for the provider's applicable credentials. |
| `POST /provider-store-connections/sync/{provider}/{credential_key}` | Admin | Discovers stores for one credential group. |
| `PATCH /provider-store-connections/{connection_id}` | Admin | Updates safe fields, such as label and Etsy shop mapping. |
| `DELETE /provider-store-connections/{connection_id}` | Admin | Deletes an unreferenced connection or soft-deletes one with retained history. |
| `GET /etsy/connection` | Admin | Returns safe Etsy account and shop status. |
| `POST /etsy/oauth/start` | Admin | Creates a one-time PKCE OAuth state and authorization URL. |
| `POST /etsy/oauth/callback` | Admin | Consumes the state, stores encrypted tokens, discovers shops, and auto-maps stores. |
| `POST /etsy/connection/sync` | Admin | Refreshes all connected Etsy seller accounts and shop mappings. |

The application reserves at most five active Etsy-backed provider-store rows per organization. It doesn't separately cap stored Etsy seller accounts.

### AI endpoints

| Method and path | Access | Behavior |
| --- | --- | --- |
| `GET /ai/capabilities` | Workspace | Reports whether AI is enabled and which storefront and fields it supports. |
| `POST /products/{product_id}/ai-generations` | Workspace | Generates a full or field-targeted suggestion for an expected product revision. |
| `GET /products/{product_id}/ai-generations` | Workspace | Lists safe generation history. |
| `POST /products/{product_id}/ai-generations/{generation_id}/apply` | Workspace | Applies selected reviewed fields if the product revision still matches. |

The generation request includes `client_request_id`, `expected_product_revision`, and optional `regenerate_fields`. Idempotency is scoped by organization and client request ID.

### Job and order endpoints

| Method and path | Access | Behavior |
| --- | --- | --- |
| `GET /publishing-jobs` | Workspace | Lists jobs, optionally filtered by `product_id`. |
| `GET /publishing-jobs/{job_id}` | Workspace | Gets one organization-scoped publishing job. |
| `GET /orders` | Workspace | Returns a paginated, privacy-minimized order page and available filters. |
| `GET /sync-jobs` | Workspace | Lists organization synchronization jobs. |
| `GET /sync-jobs/orders/latest` | Workspace | Gets the latest order-sync attempt or `null`. |
| `GET /sync-jobs/etsy-sales/status` | Workspace | Gets the latest marketplace-sales attempt and the latest useful success timestamp. |
| `GET /sync-jobs/{job_id}` | Workspace | Gets one synchronization job. |
| `POST /sync-jobs/orders/run` | Workspace | Creates, reuses, or redispatches order-sync work. `force=true` bypasses only terminal freshness. |
| `POST /sync-jobs/etsy-sales/run` | Workspace | Creates, reuses, or redispatches Etsy sales ingestion. `force=true` bypasses only terminal freshness. |

`GET /orders` accepts `page`, `page_size`, `store_connection_id`, `provider`, and `fulfillment_status`. Page size defaults to 15 and is capped at 100.

The Etsy sales status response contains `latest_job` and `last_successful_at`. The job exposes lifecycle status, timestamps, a sanitized error, and result counts for accounts, shops, receipts, line items, expenses, exchange rates, skipped shops, and total imported records.

## Core workflows

### Organization onboarding

1. The user signs in through Clerk.
2. FastAPI creates or resolves the app-owned `users` record.
3. `/session-context` returns `needs_organization`, `pending_approval`, or `approved`.
4. The user creates an organization or enters a join code.
5. A new organization gives its creator an admin membership.
6. A join code creates a pending request.
7. An admin approves or rejects the request in Settings.
8. Approved users enter the workspace.

Join-code lookup uses a narrow transaction-local RLS context instead of opening organization-wide reads.

### Provider and Etsy setup

The implemented Settings flow is Etsy-first for Etsy stores:

1. An admin connects one or more Etsy seller accounts through PKCE OAuth.
2. Velora encrypts refresh tokens and stores safe discovered-shop metadata.
3. The admin saves one or more labeled Printify or Gelato credentials.
4. Velora discovers provider stores.
5. Store names and provider metadata auto-map compatible Etsy shop IDs.
6. The admin can correct a per-store Etsy shop ID.

Printify lists shops directly. Gelato primarily discovers store IDs from order data and can use admin-provided manual seeds when discovery is empty or retryably unavailable.

### Blueprint lifecycle

1. A member selects a connected provider store.
2. The member enters a Printify product reference or Gelato template ID.
3. The adapter validates the reference against the provider.
4. Velora stores a provider snapshot, display name, product type, variant count, configuration summary, and available base content or cost.
5. The blueprint becomes available to Product Studio.
6. Later validation can refresh the snapshot.
7. A blueprint can't be deleted while a product draft references it.

### Product lifecycle

1. Product Studio uploads a private design asset.
2. The user selects a compatible blueprint.
3. Velora creates a revision-1 provider product draft.
4. The user uploads and orders marketplace images.
5. Each meaningful saved change increments the product revision.
6. AI suggestions remain separate until explicitly applied.
7. A send validates the exact saved revision.
8. Successful publishing creates or updates a `pod_products` record and marks the local product published.
9. Later edits remain local until another explicit send.

Deletion removes the Velora product, its owned marketplace images, jobs, and unshared design asset. It intentionally leaves external Printify, Gelato, and marketplace records untouched.

### Upload lifecycle

1. The Next.js BFF rejects a known request length above its configured limit.
2. FastAPI's upload middleware bounds the complete request while streaming it to a spooled temporary file.
3. The media service bounds the file and computes SHA-256.
4. It verifies PNG chunks and CRCs, JPEG structure and dimensions, or WebP structure and dimensions.
5. The storage service uploads with a safe file name, private cache policy, content metadata, and organization-rooted key.
6. FastAPI persists the media row.
7. If persistence fails, it compensates by deleting the object.
8. An operator script can find and remove aged orphaned objects.

Canonical object paths are:

```text
organizations/<organization_id>/design-assets/<design_asset_id>/...
organizations/<organization_id>/draft-mockups/<product_id>/<mockup_id>/...
```

### AI listing lifecycle

1. The seller saves an Etsy product with a design image and design description.
2. The browser sends a stable client request ID and expected product revision.
3. The backend checks configuration, tenant scope, quotas, product state, and store type.
4. It reads the private image with a hard source bound and creates a bounded derivative.
5. It sends minimized product context and, for a vision-capable model, the derivative to OpenRouter.
6. It validates structured output and deterministic Etsy rules.
7. A malformed response gets one structure repair; invalid fields get bounded field repairs.
8. The UI keeps the suggestion separate from manual content.
9. The seller edits, selects, and applies fields.
10. The backend rejects apply if the product revision changed.

AI never starts a publishing job. The current deterministic contract requires:

- A 130-to-140-character comma-separated title with restricted characters.
- Exactly 13 unique tags, each no more than 20 characters.
- A description of at least 600 characters in four to six paragraphs.
- A 40-to-70-character SEO title.
- A 120-to-160-character SEO description.
- Exactly five SEO keywords.

### Publishing lifecycle

Publishing readiness requires:

- A valid blueprint and provider variant.
- A connected store.
- A nonblank title.
- A positive price and currency.
- A saved design asset.
- At least one marketplace image.
- The current saved revision.

The enqueue transaction creates or reuses:

- A `sync_jobs` execution envelope.
- A `publishing_jobs` domain record.
- A `publishing_outbox` row.

The idempotency key includes organization, product, provider, store, operation, and revision. A partial unique index prevents simultaneous active work for the same scope.

The worker follows these resumable stages:

```text
queued
  -> provider_product_saved
  -> etsy_listing_created
  -> etsy_metadata_synced
  -> etsy_images_synced
  -> completed
```

For a new product:

1. The adapter creates or reconciles a provider product.
2. Printify explicitly publishes and polls for a connected listing ID. Gelato's create-from-template flow creates the connected product and its publish method resolves current status.
3. Velora requires an Etsy listing ID for an Etsy target.
4. Velora updates supported Etsy metadata.
5. Velora replaces the Etsy gallery with the saved order of up to 10 marketplace images.

For an existing Etsy listing, Velora bypasses provider product creation and performs the supported direct Etsy update.

Failures retain a sanitized stage. Retryable execution reuses, updates, or reconciles provider products before it creates another one.

### Order synchronization lifecycle

1. A manual request or the scheduler calls the shared enqueue service.
2. The service reuses active work and enforces a five-hour interval for recent terminal work unless forced.
3. The worker atomically claims a lease and moves the job to `running`.
4. It processes each active provider-store connection.
5. Each provider returns a bounded page, next cursor, and observed watermark.
6. Velora normalizes and bulk-upserts orders by organization, provider, and external order ID.
7. Each page commits its order changes and cursor together.
8. The worker renews the lease between units of work.
9. It reports `completed`, `partial`, or `failed` truthfully.

Defaults are 50 records per page, at most 100 pages per connection, a 24-hour overlap window, and five concurrent detail requests. The overlap plus uniqueness key handles provider updates at a previous watermark.

`partial` means useful work completed but at least one connection, page, or item failed, or the page cap stopped bounded progress. `failed` means connected scope existed but no connection completed useful work.

### Etsy sales and foreign-exchange lifecycle

Four entry points converge on the same organization-scoped `marketplace_sales_sync` job:

```text
usable Etsy connection or shop mapping ─┐
first connected Analytics visit ────────┼─> idempotent enqueue -> leased worker
manual Sync Etsy action ────────────────┤
15-minute scheduler due scan ───────────┘
```

- Connection and mapping events force a new terminal attempt when no active job exists.
- The first Analytics visit uses normal five-hour freshness and runs only when no attempt exists.
- The manual **Sync Etsy** action uses `force=true`.
- The scheduler uses the configurable five-hour minimum interval.
- Every path reuses an existing `queued`, `leased`, or `running` job.

The worker then:

1. Claims the persisted job lease before provider work.
2. Checks for an Etsy connection, usable refresh token, `transactions_r`, discovered shops, and at least one connected Velora-store mapping.
3. Fetches receipt and transaction data for eligible shops.
4. Uses bounded concurrent 30-day ledger windows.
5. Stores canonical marketplace orders, normalized line items, and marketplace expenses.
6. Commits marketplace data before refreshing dated Frankfurter reference rates.
7. Persists counts, a semantic outcome, and any sanitized blocker.

The generic database lifecycle remains `completed`, `partial`, `failed`, or `cancelled`. Etsy sales adds a domain outcome in `result_json`:

| Domain outcome | Stored job status | Meaning |
| --- | --- | --- |
| `completed` | `completed` | The import ran and processed marketplace data. |
| `completed_no_data` | `completed` | Etsy returned no records for a valid import window. |
| `partial` | `partial` | Useful marketplace work completed, but a shop mapping or FX stage remained incomplete. |
| `blocked` | `failed` | Configuration prevents ingestion; the blocker is actionable and isn't retried as a transient provider failure. |
| unexpected worker failure | `failed` after retries | Provider, network, or application execution failed after the leased retry policy. |

For duplicate marketplace and POD representations, the Etsy receipt is the canonical sale.

## Data model

### Entity summary

| Table | Purpose and important relationships |
| --- | --- |
| `organizations` | Tenant root, unique join code, name, reporting currency, and reporting timezone |
| `users` | App-owned identity mapped from Clerk or local auth |
| `memberships` | One user-to-organization membership with `admin` or `member` role |
| `organization_join_requests` | Pending, approved, or rejected access request |
| `provider_credentials` | Labeled encrypted key groups per organization and provider |
| `oauth_request_states` | Hashed, one-time, expiring OAuth state bound to organization and actor |
| `provider_store_connections` | Provider store, storefront type, label, Etsy mapping, sync cursor, watermark, freshness, and soft-delete state |
| `product_blueprints` | Store-bound provider reference, validation snapshot, product configuration, and base listing data |
| `design_assets` | Private design object key, type, size, checksum, and signed display URL |
| `provider_product_drafts` | Revisioned Velora product, listing, pricing, SEO, provider input, store, and publishing state |
| `ai_generations` | Idempotent generation request, safe provider usage, validated suggestion, warnings, status, and accepted fields |
| `mockups` | Ordered private marketplace images attached to one product |
| `pod_products` | Provider-side product and external listing identity for one Velora product |
| `publishing_jobs` | Immutable send snapshot, stage, operation, idempotency key, result, and error |
| `publishing_outbox` | Transactional broker-dispatch record for one publishing job |
| `orders` | Normalized provider or marketplace order and operational status |
| `order_line_items` | Normalized product attribution, quantity, revenue, cost, fee, and mapping state |
| `expenses` | Imported or manual dated costs with optional direct product/store attribution |
| `exchange_rates` | Dated positive rates by base, quote, and source |
| `sync_jobs` | Generic leased execution envelope for order, publishing, sales, and analytics work |
| `analytics_snapshots` | Last-known-good provider analytics payload with expiry and failure state |
| `sync_events` | Sanitized synchronization progress and failure events |

### Tenant integrity

Tenant-owned rows carry `organization_id`. Important relationships use composite organization-and-ID foreign keys so a valid object ID from one tenant can't be attached to another tenant's row.

Database checks constrain:

- Membership roles.
- Join-request state.
- Storefront and connection state.
- Blueprint provider and reference types.
- Product status, publishing status, and positive revision.
- AI generation status and accepted state.
- Publishing operation, status, stage, and retry count.
- Nonnegative media size and mockup position.
- Positive line-item quantity and nonnegative money fields where applicable.
- Synchronization status, lease consistency, and bounded attempts.
- Analytics snapshot status and timestamps.

### Row-level security

The migration chain creates:

- `velora_runtime`, a non-login API role.
- `velora_worker`, a non-login worker role.
- Forced RLS policies for tenant tables.
- API policies based on `app.current_actor_id`, `app.current_organization_id`, and `app.current_join_code`.
- Worker policies for organization-scoped background work.
- Explicit rejection behavior for legacy public client roles.

The API and worker connection users must be members of the appropriate role but must not own tenant tables, be superusers, or have `BYPASSRLS`. Startup role checks reject unsafe PostgreSQL credentials.

`tenant_context.py` stores the active context on the SQLAlchemy session and reapplies transaction-local PostgreSQL settings after every new transaction. This matters because services sometimes commit partway through a workflow.

## External integrations

### Integration summary

| Integration | Purpose | Credential source | Failure and rate behavior |
| --- | --- | --- | --- |
| Clerk | Browser identity and JWT verification | Frontend and backend environment | JWKS cache, key refresh, issuer and authorized-party checks |
| Neon Postgres | Durable application state and RLS | Separate runtime, worker, and migration URLs | Bounded pools, TLS outside development, role preflight |
| Redis or Valkey | Queue transport and distributed limits | `REDIS_URL` | Required by readiness; manual order sync has in-process dispatch fallback |
| S3-compatible storage | Private design and marketplace media | Backend environment | Bounded read/write, signed GET, compensation, orphan cleanup |
| Printify | Store discovery, source-product cloning, publishing, and orders | Encrypted organization credential | Internal request limits, retry, asynchronous publish polling |
| Gelato | Store discovery, template product creation, and orders | Encrypted organization credential | Backoff, template/product polling, manual discovery seeds |
| Etsy | OAuth accounts, shops, listing edits, images, receipts, transactions, and ledger | Encrypted OAuth refresh tokens or fallback environment | Shared Redis sliding-window limiter with local fallback and `Retry-After` support |
| OpenRouter | Review-first listing generation | Backend environment only | Disabled by default, timeout, bounded retry, database quota, Redis burst limit |
| Frankfurter | Historical reference exchange rates | No API key | Bounded timeout; analytics exposes missing FX coverage |

### Printify adapter

The Printify adapter:

- Discovers `/v1/shops.json`.
- Accepts a Printify product URL or ID as a blueprint reference.
- Fetches and stores the source product snapshot.
- Uploads the Velora design to Printify.
- Recreates variants and print-area placements from the source product.
- Creates the target product as not visible.
- Repairs tags or shipping metadata if the create/update response omitted them.
- Reconciles uncertain creation by title, blueprint, print provider, and a recent time window.
- Publishes asynchronously and polls until an external listing ID appears.
- Fetches paginated orders and normalizes provider data.

The adapter doesn't modify the source Printify product.

### Gelato adapter

The Gelato adapter:

- Discovers stores from order data.
- Supports unique manual Etsy store seeds.
- Accepts a Gelato template ID as a blueprint reference.
- Reads template variants and image placeholder names.
- Creates a product from the template with Velora's design URL.
- Polls until expected connected variants exist.
- Reconciles uncertain creation by recent matching title.
- Fetches order pages, then concurrently fetches details and production status.
- Uses offset cursors and observed timestamps.

### Etsy service

The Etsy service:

- Implements PKCE OAuth with one-time hashed state.
- Supports multiple seller accounts per organization.
- Rotates and persists refresh tokens.
- Resolves the account that owns a target shop.
- Discovers and auto-maps shops.
- Applies a shared request-rate boundary.
- Updates supported listing metadata and inventory.
- Replaces the ordered listing image gallery.
- Imports receipts, transactions, and payment-ledger data.
- Builds seller-editor links instead of customer-facing listing links for edit actions.

Etsy tokens and discovered account data use the encrypted provider-credential store.

### OpenRouter adapter

The OpenRouter integration:

- Runs only on the backend.
- Requires `VELORA_AI_PROVIDER=openrouter`, an API key, and a model.
- Supports provider-specific privacy and capability preferences.
- Requests strict structured JSON output.
- Omits image input for text-only configured models.
- Stores safe request ID, token, cost, latency, retry, warning, and acceptance data.
- Doesn't store image bytes, presigned URLs, raw provider responses, authorization headers, or chain-of-thought.

## Background work and reliability

### Generic job lifecycle

Active synchronization states are `queued`, `leased`, and `running`. Terminal states are `completed`, `partial`, `failed`, and `cancelled`.

Domain-specific result metadata can refine a generic terminal state. Etsy sales uses this to distinguish a valid no-data completion from a configuration blocker without changing the shared database constraint or lease machinery.

A worker:

1. Claims a queued row with a unique lease owner.
2. Sets a lease expiry and increments its attempt count.
3. Moves the row to running.
4. Heartbeats during bounded work.
5. Finishes only if it still owns the lease.
6. Requeues a retryable expired row or fails an exhausted row.

PostgreSQL uses row locks and partial unique indexes to make concurrent enqueue, claim, OAuth-state consumption, and reaping converge safely.

### Scheduler intervals

| Interval | Scheduled action |
| --- | --- |
| 1 minute | Dispatch committed publishing outbox rows |
| 5 minutes | Reap expired order-sync jobs |
| 5 minutes | Reap expired Etsy sales jobs |
| 5 minutes | Reap expired publishing jobs |
| 5 minutes | Find expired analytics snapshots |
| 5 minutes | Reap expired analytics refreshes |
| 15 minutes | Find organizations due for provider order sync |
| 15 minutes | Find organizations due for Etsy sales sync |

The scheduler acquires a process-level lock at the operating-system temporary path. A second scheduler in the same filesystem namespace exits without registering jobs.

### Publishing outbox

Publishing enqueue commits its database state before queue dispatch. If immediate dispatch fails:

- The outbox row remains pending.
- The scheduler retries pending rows.
- A fast worker can acknowledge the row without losing a race with the API sender.
- A stale outbox claim becomes available again.

This outbox is specific to publishing. Manual order and Etsy sales synchronization write their `sync_jobs` rows before dispatch and use an in-process FastAPI background task if Redis dispatch fails. Connection and mapping triggers do not perform ingestion inside their requests; if broker dispatch fails, they leave the job queued, and the Etsy due scanner redispatches queued work on a later scheduler tick.

### Pool and transaction behavior

The default API and worker pools are intentionally small:

- Pool size: 3.
- Max overflow: 0.
- Checkout timeout: 10 seconds.
- Connection recycle: 300 seconds.
- Idle pool purge: 300 seconds.

Provider I/O should occur outside long-lived database transactions. Order pages commit before the next provider page and before lease renewal. Worker and API processes can use separate database URLs.

### Logging

Frontend server and backend processes emit structured events to standard output. Logging supports `pretty` and `json` formats and an additional verbose flag.

Logs:

- Include request or job correlation IDs.
- Redact fields with secret-like names.
- Sanitize authorization and bearer-token text.
- Avoid response bodies and provider content by default.
- Record error type and safe stage instead of raw external payloads.

Logs are operational telemetry, not a durable audit trail.

## Analytics

Velora has two related analytics surfaces.

### Operational workspace analytics

`GET /analytics` combines bounded organization SQL with a saved Etsy analytics snapshot. It reports workspace-level product, publishing, order, provider, and marketplace panels.

Etsy snapshots:

- Are organization-scoped.
- Default to a 30-minute TTL.
- Refresh asynchronously.
- Preserve the last successful payload after a refresh failure.
- Expose freshness and sanitized failure metadata.
- Keep request latency independent of live Etsy HTTP.

### Business analytics

`GET /analytics/business` calculates:

- Revenue.
- Marketplace fees.
- Provider cost.
- Direct expenses.
- Gross profit.
- Net profit.
- Orders and units.
- Comparison-period change.
- Day, week, or month trends.
- Product and store performance.
- Explicit data-coverage ratios.

The service:

- Converts local date ranges to UTC with an IANA timezone.
- Builds an equal-length preceding comparison period.
- Uses PHP, USD, EUR, or JPY as reporting currency.
- Finds the latest exchange-rate observation on or before each transaction date.
- Supports direct and inverse pairs and triangulates non-EUR pairs through EUR.
- Doesn't rewrite native monetary values.
- Doesn't claim profit when required cost coverage is incomplete.
- Treats Etsy marketplace receipts as canonical over duplicate POD orders.
- Keeps unmatched line items visible until an admin maps them.
- Includes only directly attributed expenses in product-level profit.

Analytics reads only normalized database records. Marketplace ingestion is observable separately through the Etsy sales sync status contract, so refreshing a report cannot hide provider work or turn a missing connection, permission, token, or shop mapping into an empty successful dataset.

SEO scoring is a deterministic listing-completeness heuristic, not an Etsy keyword-rank claim. The implemented score weights title, description, tags, image, price, and SKU completeness.

## Security and privacy

### Defense layers

| Layer | Current control |
| --- | --- |
| Browser routing | Clerk middleware and server-side session-context redirects |
| Browser API boundary | Same-origin BFF with bearer-token attachment |
| API identity | RS256 JWT verification or explicit local development mode |
| Authorization | App-owned membership and role dependencies |
| Tenant isolation | Organization filters, composite foreign keys, and forced PostgreSQL RLS |
| Database roles | Non-owner runtime and worker role preflight |
| Provider secrets | Fernet encryption with active and previous key IDs |
| OAuth | PKCE, hashed state, expiry, actor binding, and single consumption |
| Browser headers | Runtime nonce CSP, HSTS, frame denial, MIME-sniff prevention, and hidden `X-Powered-By` |
| Uploads | Bounded request and file sizes, spooling, structural validation, and safe metadata |
| Object access | Private bucket objects and short-lived signed GET URLs |
| Jobs | Stable idempotency, active-scope uniqueness, leases, and bounded retry |
| Logs | Correlation, redaction, sanitization, and limited provider detail |

### Browser security policy

Next.js applies static security headers and a runtime nonce-based content security policy to HTML documents. Public authentication pages use a stricter profile than the workspace. The policy allows required Clerk and Cloudflare Turnstile origins without a global static `script-src 'unsafe-inline'`.

### Order privacy

The database retains provider order detail needed for synchronization and analytics. The public Orders endpoint selects an explicit safe column list and excludes:

- Raw provider payload.
- Full customer details.
- Address fields.
- Destination details.
- Tracking fields from the user-facing contract.

It also masks 13-to-19-digit substrings that pass a Luhn check before returning public string fields.

### Provider metadata privacy

Migration `20260718_0018` clears legacy opaque provider-store metadata while preserving only the allowlisted Etsy shop ID. On PostgreSQL, a trigger converts later non-null raw metadata writes to SQL `NULL`. API schemas don't expose the raw field.

### AI privacy

AI input excludes provider credentials, raw metadata, pricing, orders, customer data, unrelated tenant data, and permanent object URLs. It sends a bounded image derivative only when the model supports vision.

Unaccepted and failed generation content can be pruned after 30 days by an operator script. Accepted content remains as an application review record. Velora doesn't automatically collect or export training data.

## Configuration

Start with `.env.local.example` for Next.js and `backend/.env.example` for FastAPI and workers. Never commit populated environment files.

### Frontend variables

| Variable | Purpose |
| --- | --- |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Enables Clerk browser integration |
| `CLERK_SECRET_KEY` | Enables Clerk server operations |
| `NEXT_PUBLIC_CLERK_SIGN_IN_URL` | Sign-in route, normally `/sign-in` |
| `NEXT_PUBLIC_CLERK_SIGN_UP_URL` | Sign-up route, normally `/sign-up` |
| `VELORA_API_BASE_URL` | FastAPI origin used only by server-side code |
| `VELORA_UPLOAD_MAX_REQUEST_BYTES` | BFF early rejection limit for media uploads |
| `VELORA_ENVIRONMENT` | Environment name |
| `VELORA_LOG_FORMAT` | Server log format |
| `VELORA_VERBOSE_LOGGING` | Enables additional safe diagnostics |
| `VELORA_NEXT_DIST_DIR` | Optional Next.js build-output override |

### Backend configuration groups

| Group | Important variables and defaults |
| --- | --- |
| Runtime | `VELORA_ENVIRONMENT=development`, `VELORA_LOG_LEVEL=INFO`, `VELORA_LOG_FORMAT=pretty`, `VELORA_VERBOSE_LOGGING=false` |
| Database | `VELORA_DATABASE_URL`, `VELORA_WORKER_DATABASE_URL`, `VELORA_DATABASE_MIGRATION_URL`, `VELORA_DATABASE_RUNTIME_ROLE=velora_runtime`, pool settings |
| Projects | `VELORA_NEON_PROJECT_ID`; `VELORA_SUPABASE_PROJECT_ID` remains a legacy compatibility setting |
| Auth | `VELORA_AUTH_MODE=auto`, Clerk JWKS URL, issuer, authorized parties, clock skew, and `CLERK_SECRET_KEY` |
| CORS and BFF | `VELORA_CORS_ORIGINS`, `VELORA_API_BASE_URL` |
| Encryption | `VELORA_SECRET_ENCRYPTION_KEY`, active key ID, and previous key JSON |
| Storage | Endpoint, access key, secret key, bucket, region, signed-URL TTL, and orphan age |
| Upload | 95 MiB file maximum, 100 MiB request maximum, 1,000,000-byte in-memory spool, and 10 mockups |
| Redis and jobs | `REDIS_URL`, 1,800-second lease, 3 attempts, 100-row reaper batch |
| Order sync | 50-row pages, 100 pages, 24-hour overlap, concurrency 5, and five-hour cadence |
| Analytics | 1,800-second snapshot TTL and Frankfurter URL/timeout |
| AI | Provider disabled, OpenRouter URL/model/key, 45-second timeout, 2,400 output tokens, image bounds, and quotas |
| Etsy | API and OAuth settings, 5 requests per second, 4 ledger requests, 2 retries, and image bound |
| Printify | Base URL, request limits, and 5-to-20-second polling for up to 900 seconds |
| Gelato | Ecommerce and order URLs, `slice` image fit, 5 retries, and polling for up to 900 seconds |

Pydantic adds the `VELORA_` prefix to backend setting names except explicitly aliased variables such as `REDIS_URL` and `CLERK_SECRET_KEY`.

### Environment safety rules

Outside development and test:

- Use `VELORA_AUTH_MODE=clerk`.
- Configure Clerk JWKS URL, issuer, and authorized HTTPS parties.
- Use exact HTTPS CORS origins.
- Use an HTTPS BFF API origin.
- Use PostgreSQL URLs with TLS.
- Use a real Fernet-compatible encryption key.
- Keep runtime and worker users separate from the migration owner.
- Configure Redis, because readiness and scheduled processing require it.
- Configure private S3-compatible storage before accepting uploads.

AI remains unavailable unless its provider, API key, and model are all configured.

## Local development

### Prerequisites

Install:

- Node.js 20 or a compatible current Node.js release.
- npm.
- Python 3.11 for parity with CI and deployment.
- PostgreSQL access.
- Redis, Valkey, or Docker.
- Chrome for Playwright.

### Prepare the environment

1. Install frontend dependencies:

   ```bash
   npm install
   ```

2. Create the backend virtual environment:

   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cd ..
   ```

3. Copy the environment examples:

   ```bash
   cp .env.local.example .env.local
   cp backend/.env.example backend/.env
   ```

4. Replace every placeholder with development credentials.

5. Apply migrations with the owner-capable migration URL:

   ```bash
   cd backend
   alembic upgrade head
   cd ..
   ```

### Run the integrated stack

Run:

```bash
./run.sh
```

The launcher:

- Rejects missing dependencies, missing environment files, and placeholder secrets.
- Reuses a reachable Redis instance or starts local Redis, Valkey, or a Docker container.
- Stops only stale Velora processes whose working directory matches this checkout.
- Starts Uvicorn on port 8000.
- Starts one Dramatiq process with four threads.
- Starts APScheduler.
- Starts Next.js on port 3000.
- Cleans up processes it started when it exits.

Open `http://127.0.0.1:3000`.

### Run services separately

Run the API:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

Run the local worker:

```bash
cd backend
source .venv/bin/activate
dramatiq app.jobs.broker:broker app.jobs.orders app.jobs.publishing app.jobs.analytics app.jobs.etsy_sales
```

Run the scheduler:

```bash
cd backend
source .venv/bin/activate
python -m app.scheduler
```

Run the web application:

```bash
npm run dev
```

Next.js uses `.next-dev` for normal development and `.next-e2e` for browser tests, avoiding output-directory contention.

## Testing and continuous integration

### Test inventory

The repository currently contains:

- 275 Python test functions.
- 13 Playwright browser tests.
- TypeScript and JavaScript tests beside frontend helpers and components.
- Optional PostgreSQL concurrency and RLS tests.

Backend coverage includes:

- Authentication, organizations, roles, and RLS context.
- Provider credentials, discovery, adapters, and safe errors.
- Blueprint, product, media, AI, publish, order, and analytics routes.
- Durable outbox, leases, retries, reapers, and concurrent claims.
- Migration upgrade and downgrade behavior.
- PostgreSQL tenant constraints and runtime roles.
- Security configuration and header contracts.
- Operator script safety.

Playwright covers:

- Product publish readiness and exact-revision submission.
- Existing Etsy edit behavior.
- AI generate, retry, regenerate, review, apply, and stale-revision behavior.
- Analytics request caching, filter refresh, tabs, pagination, dialogs, and CSV export.
- Automatic first Etsy sales ingestion and an honest completed-no-data status.

External Printify, Gelato, Etsy, OpenRouter, storage, and exchange-rate boundaries are mocked in automated tests. Passing CI doesn't prove live provider credentials or provider behavior.

### Run the standard checks

Run frontend checks:

```bash
npm run lint
npm run typecheck
npm run build
npm run test:e2e
npm run audit:prod
```

Run backend checks:

```bash
cd backend
./.venv/bin/pytest
```

Run focused Node tests with the commands listed in `docs/testing.md` when you change a corresponding helper.

### Run PostgreSQL lifecycle tests

Use only a disposable database with the complete migration chain:

```bash
cd backend
VELORA_POSTGRES_TEST_URL=postgresql+psycopg://user:password@127.0.0.1:5432/velora_test \
  ./.venv/bin/pytest -q tests/test_postgres_sync_job_lifecycle.py
```

Don't point this test at a shared or production-like database. It creates and transitions test rows and exercises concurrency.

### CI behavior

CI runs for pull requests and pushes to `staging` and `main`.

| Job | Checks |
| --- | --- |
| Frontend | `npm ci`, lint, strict TypeScript typecheck, build, Playwright, and production dependency audit |
| Backend | Python 3.11 install and the complete pytest suite twice to detect order dependence |
| Deployment scaffolding | Shell syntax, verification-script help, rendered app specs, runtime commands, roles, and health path |

The production audit fails for high or critical dependency findings. Lower-severity exceptions require an owned, reasoned, expiring record in `.github/npm-audit-exceptions.json`.

## Deployment and operations

### Intended DigitalOcean topology

The checked-in App Platform templates define:

- One Next.js `web` service.
- One FastAPI `api` service.
- One `orders-worker` Dramatiq process.
- One `orders-scheduler` APScheduler process.
- External Neon Postgres.
- External Redis or managed Valkey.
- External S3-compatible storage.
- Clerk, Etsy, provider, OpenRouter, and Frankfurter services.

The web service builds with:

```text
npm ci && npm run build
```

It runs with:

```text
npm run start -- --hostname 0.0.0.0 --port 8080
```

The API entrypoint validates imports before starting Uvicorn. Worker and scheduler commands run the database-role preflight before their long-lived process.

### Staging release

The staging workflow:

1. Waits for successful CI on the `staging` branch.
2. Verifies that the tested commit is still the branch head.
3. Requires API and web smoke-test domains.
4. Renders App Platform specifications.
5. Deploys the backward-compatible backend.
6. Verifies liveness, readiness, and unauthenticated boundaries.
7. Applies expand-only Alembic migrations.
8. Verifies the backend again.
9. Deploys the frontend.
10. Verifies public BFF and security boundaries.
11. Optionally runs a non-applying AI canary.

### Production promotion

Production is a manual workflow that accepts a commit SHA. It verifies:

- The same SHA completed a successful staging deployment.
- The SHA is still the `main` branch head.
- Required domains and environment values exist.

It then follows the backend-first, migration, frontend, and verification sequence under the protected production environment.

### Deployment verification

`scripts/verify_deployment.sh` checks:

- API liveness.
- Database and Redis readiness.
- Unauthenticated API and BFF boundaries.
- Frontend HSTS.
- Content security policy.
- Frame denial.
- MIME-sniff protection.

It avoids logging response bodies, headers, or credentials.

### Operator scripts

Backend scripts support:

- Provider metadata scrubbing.
- Provider credential rotation with project and active-key confirmation.
- Orphaned media cleanup.
- AI retention cleanup.
- AI generation smoke checks.

Use dry-run modes first. Credential rotation apply requires exact environment confirmation.

## Known implementation and operations gaps

These items come from the current source and configuration, not from planned behavior.

### The deployed worker doesn't register the Etsy sales actor

`backend/app/scheduler.py` sends `app.jobs.etsy_sales` messages every 15 minutes. The local launcher registers that actor, but `infra/digitalocean/templates/api-app.yaml.tmpl` registers only orders, publishing, and analytics modules. The deployment CI explicitly expects the shorter command.

The repository now creates Etsy sales jobs from connection/mapping events, the first connected Analytics visit, the manual action, and the scheduler. Until the deployed worker command includes `app.jobs.etsy_sales`, those queued messages and scheduled exchange-rate ingestion can't be assumed to run in the DigitalOcean topology. This reliability change intentionally did not alter deployment configuration.

### Deployment metadata still uses legacy Supabase variables

The repository database workflow identifies Neon as the current runtime and `backend/.env.example` uses `VELORA_NEON_PROJECT_ID`. The DigitalOcean render script still requires `VELORA_SUPABASE_PROJECT_ID`, and the deploy workflows pass that legacy variable. They don't pass `VELORA_NEON_PROJECT_ID`.

The runtime database URL can still point to Neon, but project-confirmation scripts and deployment metadata aren't fully aligned with the Neon cutover.

### Upload examples use different limits

The backend example config allows a 100 MiB request containing a file of at most 95 MiB. The frontend example and DigitalOcean render default set `VELORA_UPLOAD_MAX_REQUEST_BYTES=11000000`, about 10.5 MiB.

The BFF and backend use the same variable and should receive the same value in a deployed environment. Operators must choose and document the intended environment-specific limit.

### One deployment variable is unused by application code

The deployment workflows provide `VELORA_STORAGE_PUBLIC_BASE_URL`, but the current storage service always creates signed GET URLs and doesn't read that variable. Treat signed URLs as the implementation contract.

### Live integration proof is outside CI

Automated tests mock paid and remote services. Live Printify, Gelato, Etsy, OpenRouter, R2, Neon, Redis, and Frankfurter behavior requires environment-specific canaries and operator evidence.

### AI remains release-gated

The complete review workflow exists, but `VELORA_AI_PROVIDER` defaults to `disabled`. No repository test proves a deployed model, provider privacy policy, latency, cost, or quality. Keep AI disabled until an approved non-sensitive canary passes.

### Durable general audit records aren't implemented

Structured logs and AI acceptance fields provide operational and feature-specific evidence, but there is no general tenant-scoped audit-log table for administrative and business mutations.

### Deployment promotion isn't artifact-immutable

The workflows verify commit SHAs and branch heads, but App Platform deploys connected branch sources. The repository doesn't yet create and promote one immutable release artifact.

### The lint command is deprecated upstream

`npm run lint` currently passes with Next.js 15.5, but Next.js reports that `next lint` is deprecated and will be removed in Next.js 16. Migrate the script to the ESLint CLI during the Next.js 16 upgrade.

## Current product boundaries

Velora currently doesn't implement:

- Direct creation of new Etsy listings without Printify or Gelato.
- Direct Shopify or Amazon APIs.
- Provider-generated or AI-generated marketplace images.
- Bulk product creation or bulk publishing.
- Full fulfillment exception, cancellation, return, or customer-service workflows.
- Billing, plans, entitlements, or subscription management.
- Advanced organization roles beyond admin and member.
- Membership in multiple organizations.
- A public API or outbound webhooks.
- A native mobile or desktop application.
- Automatic AI saving or publishing.
- Automatic training-data collection.
- A QLoRA training pipeline, fine-tuned model artifact, or self-hosted model serving.
- A general durable audit log.
- Proven production capacity or immutable release promotion.

Current AI model references in docs describe a target or configured hosted model, not a fine-tuned artifact. Current analytics provides substantial business reporting, but missing attribution, cost, or FX remains explicit rather than estimated.

## Implementation reference

Use these files as the primary entry points for future analysis:

| Area | Source |
| --- | --- |
| Next.js routes | [`../app/`](../app/) |
| Route protection | [`../middleware.ts`](../middleware.ts) |
| BFF | [`../app/api/backend/[...path]/route.ts`](../app/api/backend/%5B...path%5D/route.ts) |
| Typed frontend API | [`../lib/backend-api.ts`](../lib/backend-api.ts) |
| Frontend sync outcomes and polling | [`../lib/sync-job-status.ts`](../lib/sync-job-status.ts) |
| Analytics workspace | [`../app/(workspace)/analytics/page.tsx`](../app/(workspace)/analytics/page.tsx) |
| Workspace cache | [`../lib/workspace-page-cache.ts`](../lib/workspace-page-cache.ts) |
| FastAPI application | [`../backend/app/main.py`](../backend/app/main.py) |
| API router | [`../backend/app/api/router.py`](../backend/app/api/router.py) |
| API dependencies | [`../backend/app/api/deps.py`](../backend/app/api/deps.py) |
| Request and response models | [`../backend/app/models/schemas.py`](../backend/app/models/schemas.py) |
| ORM models | [`../backend/app/db/models.py`](../backend/app/db/models.py) |
| Database setup | [`../backend/app/db/database.py`](../backend/app/db/database.py) |
| Tenant context | [`../backend/app/db/tenant_context.py`](../backend/app/db/tenant_context.py) |
| Migrations | [`../backend/alembic/versions/`](../backend/alembic/versions/) |
| Provider interface | [`../backend/app/providers/base.py`](../backend/app/providers/base.py) |
| Printify adapter | [`../backend/app/providers/printify.py`](../backend/app/providers/printify.py) |
| Gelato adapter | [`../backend/app/providers/gelato.py`](../backend/app/providers/gelato.py) |
| Publishing service | [`../backend/app/services/publishing.py`](../backend/app/services/publishing.py) |
| Order service | [`../backend/app/services/orders.py`](../backend/app/services/orders.py) |
| Etsy service | [`../backend/app/services/etsy.py`](../backend/app/services/etsy.py) |
| Etsy sales ingestion | [`../backend/app/services/etsy_sales.py`](../backend/app/services/etsy_sales.py) |
| Etsy sales API dispatch | [`../backend/app/api/etsy_sales_sync.py`](../backend/app/api/etsy_sales_sync.py) |
| Etsy sales worker | [`../backend/app/jobs/etsy_sales.py`](../backend/app/jobs/etsy_sales.py) |
| Business analytics | [`../backend/app/services/business_analytics.py`](../backend/app/services/business_analytics.py) |
| AI service | [`../backend/app/services/ai_generation.py`](../backend/app/services/ai_generation.py) |
| Scheduler | [`../backend/app/scheduler.py`](../backend/app/scheduler.py) |
| Backend configuration | [`../backend/app/core/config.py`](../backend/app/core/config.py) |
| Local launcher | [`../run.sh`](../run.sh) |
| CI | [`../.github/workflows/ci.yml`](../.github/workflows/ci.yml) |
| DigitalOcean templates | [`../infra/digitalocean/templates/`](../infra/digitalocean/templates/) |
| Backend tests | [`../backend/tests/`](../backend/tests/) |
| Browser tests | [`../e2e/`](../e2e/) |

## Glossary

| Term | Meaning |
| --- | --- |
| BFF | Backend for frontend. The same-origin Next.js proxy between the browser and FastAPI. |
| Blueprint | A reusable, validated provider template bound to one provider-store connection. |
| Design asset | The private source artwork uploaded for a product. |
| Marketplace image | A user-uploaded product gallery image stored in the `mockups` table. |
| POD | Print on demand. |
| POD product | The Printify or Gelato product created from a Velora draft. |
| Product draft | The revisioned Velora listing, pricing, design, and store configuration. |
| Provider store connection | A Printify or Gelato store available to one organization. |
| Store context | The all-store or one-store workspace filter selected by the user. |
| Publishing job | The durable domain record for one exact product revision and target. |
| Outbox | The committed database record that makes later queue dispatch recoverable. |
| Sync job | The generic leased execution envelope used by background workflows. |
| Watermark | The latest provider update timestamp committed after a successful order page. |
| RLS | PostgreSQL row-level security. |
