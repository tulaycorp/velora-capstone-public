# Velora

**A product operations workspace for Print-on-Demand (POD) businesses.**

Velora turns finished artwork into provider-ready products. Small e-commerce teams move through one structured workflow — design → blueprint → provider draft → AI-assisted listing content → storefront publishing — while Velora coordinates Printify and Gelato behind a single calm interface. The focus is product creation, not storefront management: new products flow through POD provider APIs rather than directly to Etsy, Shopify, or Amazon.

<p align="center">
  <em>Design/artwork → Product Blueprint → Provider/store draft → AI-assisted listing → Provider-side publishing</em>
</p>

---

## The Problem

POD businesses reuse the same artwork across products, providers, and storefronts. But every product still demands repetitive preparation — titles, descriptions, tags, SEO fields, SKU, pricing, margins, provider templates, store-specific formatting, listing images, and provider-side product creation — followed by tracking whether publishing succeeded or failed and keeping order state visible.

As designs, providers, and stores multiply, this work becomes slow, inconsistent, and hard to track. Velora centralizes it while preserving provider-specific rules and human review. The core value is the **product creation and listing workflow**: converting finished designs into complete, optimized, provider-ready products without re-doing manual setup for each storefront.

## What Velora Is — and Isn't

Velora is a **product creation system**, not a generic analytics dashboard or a direct storefront manager.

```text
Velora  →  Printify / Gelato  →  Provider-connected storefront listing
```

- New products are created and published through POD provider APIs — Velora does **not** publish directly to Etsy, Shopify, or Amazon in its current scope.
- Etsy has a narrow direct path for shop discovery, analytics totals, and supported edits to *already-published* listings.
- The publishing target is owned by the selected **Product Blueprint** (one provider + one connected store + one template reference), not selected ad hoc in the editor.

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
                                     workers / scheduler          mockups
                                          │
                                          ▼
                              Provider adapters (Printify, Gelato, Etsy)
```

**Key boundaries:**

- **BFF boundary** — The browser calls the Next.js BFF at `/api/backend/*`, never the FastAPI origin, Postgres, R2, or provider APIs directly. The BFF streams uploads and enforces known-length request limits.
- **Modular domain** — Dashboard, Product Studio, Blueprints, Products, Providers, Store Connections, Store Context, AI Generation, Publishing Jobs, Orders, Analytics, and Settings are distinct internal modules.
- **Background jobs** — Order sync, publishing dispatch, and analytics snapshots run as leased Dramatiq actors with atomic lease claims, heartbeat, ownership-guarded transitions, and multi-replica-safe expired-lease recovery.
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

- **Product Studio** — The central feature. Author product drafts from a blueprint, upload design sources and listing images, edit title/description/tags/SKU/pricing, and prepare provider-ready listings with dirty-state tracking and publish-readiness checks.
- **Product Blueprints** — Reusable, store-bound provider template references (Printify product URL or Gelato template ID) with provider validation and stored configuration snapshots. One blueprint seeds many store-specific drafts.
- **AI Listing Generation** — A backend-only, review-first assistant that drafts Etsy-compliant titles, descriptions, tags, and SEO fields from a saved design image and product context. Nothing is saved or published without an explicit, revision-checked apply.
- **Provider Publishing** — Durable, leased publishing jobs push drafts to Printify and Gelato with idempotent enqueue, immutable revision snapshots, a transactional outbox for multi-replica dispatch, and provider deep links.
- **Orders & Sync** — Server-paginated orders workspace with a five-hour server-enforced sync cadence, manual cooldown bypass, active-job reuse, and explicit partial/failed/last-success status.
- **Business Analytics** — Marketplace-first sales attribution with adaptive comparison charts, KPI coverage, lazy server-paginated tables, CSV export, configurable reporting currency, and a normalized expense ledger.
- **Store Context** — A store switcher controls workspace scope (`All Stores` or a single provider-connected store), remembered across reloads, filtering products, jobs, orders, and analytics.
- **Etsy Integration** — PKCE OAuth, seller-identity checks, token refresh, shop discovery, automatic mapping to Printify/Gelato storefronts, receipt/transaction/ledger reads, and direct listing/inventory/gallery synchronization.
- **Multi-tenant & Secure** — Organization-scoped data with encrypted provider credentials, runtime nonce-based CSP, browser security headers, structured request-correlated logging with redaction, and BFF upstream-response guards.

## Workspace Routes

| Route | Purpose |
|-------|---------|
| `/onboarding` | Post-auth organization onboarding and pending-access |
| `/dashboard` | Store-aware overview, summaries, and recent activity |
| `/product-studio` | Product authoring with AI listing generation |
| `/blueprints` | Reusable product blueprint management |
| `/products` | Product catalog with store-context filtering |
| `/products/[id]` | Product detail, mockups, and publishing |
| `/orders` | Server-paginated orders with sync status |
| `/analytics` | Business analytics, expenses, and SEO tables |
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
