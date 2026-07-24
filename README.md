# Velora

**A centralized operations platform for Print-on-Demand (POD) businesses.**

Velora runs the full POD business process from one workspace — organization and team access, provider and store connections, product creation and publishing, order synchronization, and business analytics. Small e-commerce teams use it to turn finished artwork into provider-ready products, push them to storefronts through Printify and Gelato, track orders, and measure profitability across stores, currencies, and time periods.

Product creation is the primary workflow, but Velora is not only a product tool. It is the central system that coordinates the people, providers, products, orders, and money of a POD business — closer to an ecommerce management platform than a single-purpose listing generator.

<p align="center">
  <em>Organization & teams → Providers & stores → Product creation → Publishing → Orders → Analytics</em>
</p>

---

## The Problem

POD businesses reuse the same artwork across products, providers, and storefronts, but running the operation is fragmented. Every day brings repetitive work spread across many systems:

- **Product creation** — titles, descriptions, tags, SEO fields, SKU, pricing, margins, provider templates, store-specific formatting, and listing images.
- **Publishing** — creating products in Printify/Gelato, tracking whether the storefront listing was created, and recovering from failures.
- **Orders** — pulling orders from providers, keeping them current, and viewing fulfillment status.
- **Finance** — reconciling revenue, marketplace fees, production costs, expenses, and profit across stores and currencies.
- **Access** — managing who in the team can do what across multiple stores.

As designs, providers, and stores multiply, this work becomes slow, inconsistent, and hard to track. Velora centralizes it behind one authenticated, multi-tenant workspace while preserving provider-specific rules and human review.

## What Velora Coordinates

```text
Velora  →  Printify / Gelato  →  Provider-connected storefront listing
```

Velora coordinates the **entire business process**, not just one slice of it:

| Area | What Velora does |
|------|------------------|
| **Access** | Clerk authentication + Velora-owned organizations, memberships, roles, and join-by-code access |
| **Connections** | Encrypted Printify/Gelato credentials, provider-store discovery, and Etsy OAuth shop mapping |
| **Product creation** | Provider-backed blueprints, Product Studio authoring, listing images, pricing, and AI-assisted content |
| **Publishing** | Durable, leased jobs that push products to providers and hand off to storefronts |
| **Orders** | Incremental, resumable provider order sync with fulfillment visibility |
| **Analytics** | Marketplace-first business performance: revenue, fees, costs, profit, rankings, SEO, and an expense ledger |
| **Store context** | A global store switcher that scopes every page to all stores or one provider-connected store |

New products are created and published **through POD provider APIs** — Velora does not publish directly to Etsy, Shopify, or Amazon in its current scope. Etsy has a narrow direct path for shop discovery, analytics totals, and supported edits to *already-published* listings.

## Architecture

Velora is a **modular monolith**. The frontend, API, and workers are separate runtime processes but remain one application, one repository, and one domain model — deliberately not microservices. The backend uses **adapter-based provider integrations** so future providers can be added without rewriting the application.

```text
Browser
  │
  ▼
Next.js 15 (App Router + middleware.ts)
  │── Workspace UI (shadcn/ui, Tailwind, Recharts)
  └── BFF proxy (/api/backend/*)  ──►  FastAPI
                                          │
        ┌─────────────────────────────────┼───────────────────────────┐
        ▼                                 ▼                           ▼
   PostgreSQL (Neon)                 Redis broker               Cloudflare R2
   tenant-scoped, forced RLS         Dramatiq + APScheduler      design assets,
                                     workers / scheduler          listing images
                                          │
                                          ▼
                              Provider adapters (Printify, Gelato, Etsy)
```

**Key boundaries:**

- **BFF boundary** — The browser calls the Next.js BFF at `/api/backend/*`, never the FastAPI origin, Postgres, R2, or provider APIs directly. The BFF streams uploads and enforces known-length request limits.
- **Modular domain** — Dashboard, Product Studio, Blueprints, Products, Providers, Store Connections, Store Context, AI Generation, Publishing Jobs, Orders, Analytics, and Settings are distinct internal modules sharing one domain model.
- **Background jobs** — Order sync, publishing dispatch, analytics snapshot refresh, and expired-lease recovery run as leased Dramatiq actors with atomic lease claims, heartbeat, ownership-guarded transitions, and a transactional outbox for durable multi-replica dispatch.
- **Tenant isolation** — Every tenant table carries organization foreign keys and forced row-level security; the API rejects owner/superuser/`BYPASSRLS` credentials at startup and uses separate non-owner `velora_runtime` and `velora_worker` database roles.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Web & BFF** | Next.js 15 (App Router), React 19, TypeScript, Clerk, shadcn/ui/Radix, Tailwind CSS 3, Recharts, Motion, Lucide |
| **Domain API** | FastAPI, Pydantic, SQLAlchemy 2.0, Alembic (22 migrations) |
| **Database** | PostgreSQL on Neon — forced RLS, tenant-scoped access, expand/contract migrations |
| **Object storage** | Cloudflare R2 (S3-compatible) for design assets and listing images |
| **Async runtime** | Redis + Dramatiq workers, APScheduler, leased job lifecycle with outbox dispatch |
| **Auth** | Clerk — JWT verification on the backend; route protection via `middleware.ts` |
| **Provider adapters** | Printify, Gelato, Etsy (PKCE OAuth) |
| **AI** | Backend-only OpenRouter adapter (Qwen3-VL-8B-Instruct) — review-first, disabled by default |

## Key Features

- **Organization & Access** — Velora-owned organizations, memberships, admin/member roles, and join-by-code access requests reviewed by admins. Clerk handles identity; Velora owns workspace authorization.
- **Provider & Store Connections** — Encrypted, labeled Printify/Gelato credentials, provider-store discovery, Etsy OAuth with multi-account shop mapping, and a five-connection Etsy limit per organization.
- **Product Blueprints** — Reusable, store-bound provider template references (Printify product URL or Gelato template ID) with provider validation and stored configuration snapshots. One blueprint seeds many store-specific drafts.
- **Product Studio** — The central authoring surface: upload design sources and listing images, edit title/description/tags/SKU/pricing/margins, and prepare provider-ready listings with dirty-state tracking and publish-readiness checks.
- **AI Listing Generation** — A backend-only, review-first assistant that drafts Etsy-compliant titles, descriptions, tags, and SEO fields from a saved design image and product context. Nothing is saved or published without an explicit, revision-checked apply.
- **Provider Publishing** — Durable, leased publishing jobs push drafts to Printify and Gelato with idempotent enqueue, immutable revision snapshots, a transactional outbox for multi-replica dispatch, provider deep links, and recovery of abandoned jobs.
- **Orders & Sync** — Server-paginated orders workspace with incremental, resumable per-store synchronization, a five-hour server-enforced sync cadence, manual cooldown bypass, active-job reuse, and explicit partial/failed/last-success status.
- **Business Analytics** — Marketplace-first sales attribution with revenue, marketplace fees, provider costs, gross/net profit, period comparison, product/store rankings, SEO visibility, a manual expense ledger, configurable reporting currency (PHP/USD/EUR/JPY) with dated exchange rates, CSV export, and explicit data-coverage disclosure.
- **Store Context** — A global store switcher controls workspace scope (`All Stores` or a single provider-connected store), remembered across reloads, filtering products, jobs, orders, and analytics.
- **Multi-tenant & Secure** — Organization-scoped data with encrypted provider credentials, runtime nonce-based CSP, browser security headers, structured request-correlated logging with redaction, and BFF upstream-response guards.

## Workspace Routes

| Route | Purpose |
|-------|---------|
| `/onboarding` | Post-auth organization onboarding and pending-access |
| `/dashboard` | Store-aware overview, summaries, and recent activity |
| `/product-studio` | Product authoring with AI listing generation |
| `/blueprints` | Reusable product blueprint management |
| `/products` | Product catalog with store-context filtering |
| `/products/[id]` | Product detail, listing images, and publishing |
| `/orders` | Server-paginated orders with sync status |
| `/analytics` | Business performance, expenses, and SEO tables |
| `/account` | Profile, email, password, and session settings |
| `/settings` | Organization, members, providers, and store connections |

## Getting Started

See **[SETUP.md](SETUP.md)** for full prerequisites, environment configuration, and run instructions.

Quick start:

```bash
# Frontend
npm install && npm run dev          # http://127.0.0.1:3000

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./.venv/bin/alembic upgrade head
./.venv/bin/uvicorn app.main:app --reload   # http://127.0.0.1:8000

# Or run the full stack together
./run.sh
```

## Verification

```bash
# Frontend
npm run lint && npm run build && npm run test:e2e

# Backend
cd backend && ./.venv/bin/pytest
```

## Team

**tulaycorp**

- **Paul Wendell Angulo** — Project Manager
- **Angelo David Macayran** — Developer
- **John Lloyd Borigas** — QA / Documentarian

## License

© 2026 tulaycorp. All Rights Reserved.

No part of this repository may be reproduced, distributed, or transmitted in any form or by any means, without the prior written permission of the copyright holder.
