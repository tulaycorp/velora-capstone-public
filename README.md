# Velora

Velora is a provider-first SaaS workspace for creating and managing print-on-demand products through POD providers such as Printify and Gelato.

The MVP focuses on the product creation workflow:

```text
Design/artwork
-> Product Blueprint
-> Provider/store-specific draft
-> AI-assisted listing content
-> Provider-side product publishing
```

New product publishing flows through POD provider-connected stores rather than directly to Etsy, Shopify, Amazon, or other storefront APIs. For already-published Etsy listings, Product Detail supports a narrow direct-edit path for approved listing metadata and inventory fields.

Authentication is handled by Clerk, but organization access is owned inside Velora. Users sign in first, then create an organization or request access by join code before the workspace unlocks.

## Stack

- Frontend / BFF: Next.js, Clerk, shadcn/ui, Zod, Arcjet
- Backend API: FastAPI, SQLAlchemy, Alembic, Neon Postgres, Clerk JWT verification, Pydantic
- Storage: Cloudflare R2
- Workers: Redis + Dramatiq workers with an APScheduler process for enqueue, recovery, and snapshot refresh

## Run Frontend

```bash
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:3000/dashboard
```

## Run Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/health
```

## Run The Integrated Stack

Use the checked-in env files and start both services together:

```bash
./run.sh
```

The launcher now expects real Clerk and Supabase env files and will fail fast if placeholders are still present.

## Environment

Start from:

```text
.env.local.example
backend/.env.example
```

The recommended backend auth mode is:

```text
VELORA_AUTH_MODE=auto
```

That mode enables Clerk verification when `VELORA_CLERK_JWKS_URL` is present and falls back to the seeded local actor only in explicit development/test environments. Staging and production fail startup unless Clerk verification is fully configured.

This repository currently uses Next.js `15.x`, so the active Clerk route-protection file is `middleware.ts`. When the app upgrades to Next.js `16+`, rename it to `proxy.ts`.

## Verification

Frontend:

```bash
npm run lint
npm run build
```

Backend:

```bash
cd backend
.venv/bin/python -m pytest
```

## Current Routes

Frontend:

- `/onboarding`
- `/dashboard`
- `/product-studio`
- `/blueprints`
- `/products`
- `/orders`
- `/analytics`
- `/settings`

Backend:

- `GET /health`
- `GET /blueprints`
- `GET /products`
- `GET /product-studio`
- `GET /pod-providers`
- `GET /provider-store-connections`
- `GET /ai/capabilities`
- `POST /products/{id}/ai-generations`
- `GET /products/{id}/ai-generations`
- `POST /products/{id}/ai-generations/{generation_id}/apply`
- `GET /publishing-jobs`
- `GET /orders`
- `GET /sync-jobs`

## Documentation

See [SETUP.md](SETUP.md) for install, run, and test instructions.

## Notes

- Browser code should call the Next.js BFF at `/api/backend/*`, not the FastAPI origin directly.
- Public database tables use explicit deny policies for `anon` and `authenticated`; direct Data API access is intentionally off for now.
- On IPv4-only networks, use the session pooler DSN instead of the direct database host.
