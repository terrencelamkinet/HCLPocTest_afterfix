# NEXUS CRM (PenguinCRM) — POC build

Multi-tenant CRM SaaS: React 19 + Vite + TypeScript frontend, FastAPI (async SQLAlchemy) backend, PostgreSQL.

## Layout

| Path | What |
|---|---|
| `src/` | Frontend (React + Vite) — repo root is the frontend root |
| `backend/app/` | FastAPI app (routers, services, models, AI layer) |
| `backend/migrations/` | Raw SQL migrations |
| `admin/` | Internal admin console (separate Vite app) |
| `public/` | Static assets |
| `scripts/` | Dev helper scripts |

## Prerequisites

- Node.js 20+ and npm
- Python 3.12 + venv
- PostgreSQL 15+ (with `pgbouncer` optional)

## Setup — backend

```bash
cd backend
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env          # fill in every value — no defaults are shipped
```

Generate the JWT signing keypair (RS256) — **keys are per-deployment and not in this repo**:

```bash
cd backend && mkdir -p keys
openssl genpkey -algorithm RSA -out keys/private.pem -pkeyopt rsa_keygen_bits:2048
openssl rsa -in keys/private.pem -pubout -out keys/public.pem
chmod 600 keys/private.pem
```

Run the API:

```bash
./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001
```

## Setup — frontend

```bash
npm install
npm run dev      # Vite dev server
npm run build    # tsc -b && vite build
```

## Setup — admin console

```bash
cd admin && npm install
npm run dev      # expects backend admin API on VITE_API_BASE (see admin/.env.development)
```

## Notes

- Database schema values, seed data and provider API keys are supplied separately for this POC.
- All tenant data access is row-level-secured (RLS) — every query must run with the application
  role and a tenant context set, not as a superuser.
- Use `postgresql+asyncpg://` URLs in `backend/.env`.
