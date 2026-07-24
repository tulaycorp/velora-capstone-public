# Velora

**A provider-first SaaS workspace for creating, publishing, and managing print-on-demand (POD) products.**

Velora turns finished artwork into provider-ready product listings. Sellers move through a structured workflow — design → blueprint → provider draft → AI-assisted listing content → storefront publishing — while Velora coordinates Printify and Gelato behind a single calm workspace.

<p align="center">
  <em>Design/artwork → Product Blueprint → Provider/store draft → AI-assisted listing → Provider-side publishing</em>
</p>

---

## Overview

Print-on-demand sellers juggle artwork, provider templates, marketplace mockups, listing copy, pricing, and store context — often across more than one storefront. Velora reduces that repetitive work into one workspace: upload or reference artwork, pick a provider-backed blueprint, prepare mockups, generate and edit listing content, set pricing, save drafts, and push to connected storefronts through POD provider APIs.

New product publishing flows through provider-connected stores rather than directly to Etsy, Shopify, or Amazon. For already-published Etsy listings, a narrow direct-edit path supports approved listing metadata and inventory fields.

Authentication is handled by Clerk, but organization access is owned inside Velora. Users sign in first, then create an organization or request access by join code before the workspace unlocks.

## Key Features

- **Product Studio** — Author product drafts from blueprints, attach design assets and mockups, and prepare provider-ready listings with dirty-state tracking and publish-readiness checks.
- **Blueprints** — Reusable product concepts with provider-reference validation and snapshots, so a single blueprint seeds many store-specific drafts.
- **AI Listing Generation** — A backend-only, review-first assistant that drafts Etsy-compliant titles, descriptions, tags, and SEO fields from a saved design image and product context. Nothing is published without an explicit apply.
- **Provider Publishing** — Durable, leased publishing jobs that push drafts to Printify and Gelato with idempotent enqueue, snapshot policy, and a transactional outbox for multi-replica dispatch.
- **Orders & Sync** — Server-paginated orders workspace with a five-hour server-enforced sync cadence, manual cooldown bypass, active-job reuse, and explicit partial/failed/last-success status.
- **Business Analytics** — Marketplace-first sales attribution with adaptive comparison charts, KPI coverage, lazy server-paginated tables, CSV export, configurable reporting currency, and a normalized expense ledger.
- **Etsy Integration** — PKCE OAuth, seller-identity checks, token refresh, shop discovery, receipt/transaction/ledger reads, and direct listing/inventory/gallery synchronization.
- **Multi-tenant & Secure** — Organization-scoped data with forced row-level security, separate non-owner runtime/worker database roles, encrypted provider credentials, and S3-compatible private asset storage.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend / BFF** | Next.js 15 (App Router), React 19, Clerk, shadcn/ui, Tailwind CSS, Recharts, Zod |
| **Backend API** | FastAPI, SQLAlchemy 2.0, Alembic, Pydantic |
| **Database** | PostgreSQL (Neon) with forced RLS and tenant-scoped access |
| **Storage** | Cloudflare R2 (S3-compatible) for design assets and mockups |
| **Workers** | Redis + Dramatiq workers with APScheduler for enqueue, recovery, and snapshot refresh |
| **Auth** | Clerk (JWT verification on the backend; route protection via `middleware.ts`) |
| **AI** | OpenRouter adapter with strict JSON-schema output, vision-capable listing generation |

## System Architecture

Velora is a split monolith: a Next.js frontend with a backend-for-frontend (BFF) proxy, and a FastAPI service backed by Postgres, Redis, and S3-compatible storage.

```text
Browser
  │
  ▼
Next.js (App Router + middleware.ts)
  │── Workspace UI (shadcn/ui)
  └── BFF proxy (/api/backend/*)  ──►  FastAPI
                                          │
        ┌─────────────────────────────────┼──────────────────────────┐
        ▼                                 ▼                          ▼
   PostgreSQL (Neon)                 Redis broker              Cloudflare R2
   tenant-scoped, RLS                Dramatiq + APScheduler     design assets,
                                     workers / scheduler         mockups
                                          │
                                          ▼
                              Provider adapters (Printify, Gelato, Etsy)
```

- **BFF boundary** — Browser code calls the Next.js BFF at `/api/backend/*`, never the FastAPI origin directly. The BFF streams uploads and enforces known-length request limits.
- **Background jobs** — Order sync, publishing dispatch, and analytics snapshots run as leased Dramatiq actors with atomic lease claims, heartbeat, and multi-replica-safe expired-lease recovery.
- **Tenant isolation** — Every tenant table carries organization foreign keys and forced RLS; the API rejects owner/superuser/BYPASSRLS credentials at startup.

## Workspace Routes

| Route | Purpose |
|-------|---------|
| `/onboarding` | Post-auth organization onboarding and pending-access |
| `/dashboard` | Workspace overview |
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
