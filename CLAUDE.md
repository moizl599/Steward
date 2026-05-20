# Steward

Local-first FinOps for Kubernetes. (Project formerly tracked as "K8s Kubecost Analyzer".)

## What this product is

A modern web app that analyzes Kubernetes cost data from **Kubecost** running in **AWS EKS** clusters, then uses a **local Ollama LLM** to produce executive-grade FinOps reports — prioritized findings, recommended actions, estimated savings — instead of the dense raw data Kubecost normally outputs.

The differentiator vs. Kubecost's own UI: **prioritization and narrative**. Kubecost tells you *what* costs are. This product tells you *which problems matter most, why, and what to do next* — in language a platform/SRE/FinOps team can act on.

The differentiator vs. SaaS competitors (CAST AI, Spot.io, Vantage): **everything runs locally**. No cluster cost data, namespace names, or workload identifiers ever leave the customer's environment. Critical for regulated industries (healthcare, finance, gov).

## Core user flow

1. **Onboarding** — User adds an Environment (name, Kubecost API URL, auth token, AWS region). Backend pings Kubecost; UI shows a live connection status indicator (green = reachable, red = error, with detail).
2. **Dashboard** — Cards for each Environment showing last-scanned timestamp, top-line monthly cost, status. Each card has a prominent **Scan** button.
3. **Scan** — Triggers an async backend job. UI shows progress. Backend pulls allocation + assets + savings data from Kubecost, pre-processes into a structured digest, runs RAG retrieval, sends to Ollama, parses the structured response.
4. **Report** — Executive summary at top. Prioritized findings list (severity badge + estimated $ impact + recommended action). Drilldowns into raw Kubecost data underneath. Raw data is collapsed by default — the LLM analysis is the headline.
5. **History** — Trends over time, scan-to-scan diffs, week-over-week changes.
6. **Settings** — Ollama model picker (with VRAM/RAM hints), prompt template editor, RAG corpus management, environment management.

## Architecture

```
┌─────────────────────┐        ┌──────────────────┐        ┌─────────────────┐
│  Next.js frontend   │ ─────► │  FastAPI backend │ ─────► │  Kubecost API   │
│  (TS + shadcn/ui)   │        │  (async workers) │        │  (per env)      │
└─────────────────────┘        └────────┬─────────┘        └─────────────────┘
                                        │
                       ┌────────────────┼────────────────┐
                       ▼                ▼                ▼
               ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
               │   SQLite/PG  │  │    Ollama    │  │   ChromaDB   │
               │  (history)   │  │   (LLM)      │  │   (RAG)      │
               └──────────────┘  └──────────────┘  └──────────────┘
```

**Data flow on a scan:**

1. `POST /environments/:id/scan` → creates a `Scan` row (status: `queued`), returns scan ID
2. Background worker picks up the scan
3. Calls Kubecost: `/model/allocation` (window=7d, aggregate=namespace,workload), `/model/assets`, `/model/savings`
4. **Pre-processor** transforms raw data into a structured digest:
   - Top-N namespaces by cost
   - Idle workloads (low CPU/mem utilization but provisioned)
   - Over-provisioned (high request, low usage)
   - PVC waste (unmounted, oversized)
   - Anomalies (>20% week-over-week growth)
   - Cluster-level efficiency metrics
5. **RAG retrieval** — query ChromaDB with each finding for relevant FinOps/SRE guidance
6. **Ollama call** — system prompt + digest + retrieved guidance → structured JSON response
7. Response stored as `Report`, scan marked `completed`
8. Frontend polls or websockets to refresh

## Tech stack (locked in)

### Frontend
- **Next.js 15** (App Router, RSC where it makes sense)
- **TypeScript**, strict mode
- **Tailwind v4** (no config file, CSS-first config)
- **shadcn/ui** for components — install on demand via `npx shadcn@latest add <component>`
- **Recharts** for cost charts
- **Lucide** for icons
- **react-query (TanStack Query)** for server state
- **Zod** for runtime validation of API responses

### Backend
- **FastAPI** + **Pydantic v2**
- **SQLAlchemy 2.0** (async)
- **Alembic** for migrations
- **httpx** for Kubecost calls (async)
- **arq** for the job queue (Redis-backed) — simpler than Celery, async-native
- **ChromaDB** Python client
- **sentence-transformers** for embeddings (`all-MiniLM-L6-v2` is fine)
- **ollama** Python SDK
- **pytest** + **pytest-asyncio** for tests

### Infra
- **Docker Compose** for local dev — frontend, backend, Redis, Ollama, ChromaDB
- **Postgres** in production, **SQLite** in local dev
- **Ollama** runs as a container with a persistent volume for model weights
- **uv** as the Python package manager (fast, modern)
- **npm** as the Node package manager

## Design principles (the look and feel)

This is a **product**, not a portfolio piece. Treat it like one.

- **Modern, dense, opinionated.** Take aesthetic cues from Linear, Vercel, Stripe, Cron. NOT generic AI dashboards (no purple gradients, no Inter as the default body font, no rounded-3xl cards everywhere).
- **Dark mode default.** Light mode supported but secondary. FinOps people work in dark terminals all day.
- **Information density matters.** Don't whitespace the interface to death. A FinOps engineer looking at cost data wants to see numbers, not vibes.
- **Color discipline.** Greens for savings/efficiency. Reds for waste/overspend. Yellows for warnings. Neutrals for everything else. Never decorative color.
- **Typography.** Geist or Geist Mono for code/numbers. A tasteful display font for headlines (think JetBrains Mono Bold, or IBM Plex Sans for headings, or Inter Display — NOT plain Inter). Numbers should feel deliberate, monospaced where appropriate.
- **Motion.** Subtle. Easing curves should feel mechanical, not bouncy. Page transitions should be near-instant.
- **Loading states.** Skeleton screens with reasonable animation. Never spinners alone.
- **Empty states.** Always include a clear CTA. "No environments yet — connect your first Kubecost instance" with a button.

The `frontend-design` skill is installed. Use it on every UI-building task.

## File layout

```
K8s_Kubecostanalyzer/
├── CLAUDE.md                # This file. Read first.
├── TASKS.md                 # Active task list. Pick from here.
├── README.md                # Public project overview.
├── docker-compose.yml       # All services for local dev.
├── .env.example             # Required env vars.
├── frontend/                # Next.js app.
│   ├── src/app/             # Routes (App Router).
│   ├── src/components/      # React components.
│   ├── src/lib/             # API client, utils.
│   └── ...
├── backend/                 # FastAPI app.
│   ├── app/
│   │   ├── main.py
│   │   ├── api/             # Route handlers.
│   │   ├── models/          # SQLAlchemy models.
│   │   ├── schemas/         # Pydantic schemas.
│   │   ├── services/        # Kubecost, Ollama, RAG, preprocessor.
│   │   └── workers/         # Async job handlers.
│   └── alembic/             # DB migrations.
└── infra/
    ├── ollama/              # Model selection guidance.
    └── chromadb/seed/       # FinOps knowledge corpus to ingest at startup.
```

## Coding standards

### Python
- Format with **ruff format**. Lint with **ruff check**. Strict.
- Type-hint everything. Use modern syntax: `dict[str, int]`, `list[Foo]`, `Foo | None`.
- Pydantic models for ALL request/response shapes.
- Async by default. Use `async def` for I/O routes.
- Service classes get DI'd into routes via FastAPI dependencies.
- Errors: raise typed exceptions, map to HTTP errors via exception handlers in `main.py`.
- Logging: structured (JSON) via `structlog`. Never `print`.

### TypeScript
- Strict mode. No `any` without a comment explaining why.
- Components: function declarations, not arrow consts, for top-level exports.
- File naming: kebab-case for routes, PascalCase for components.
- Server actions and route handlers explicitly typed.
- TanStack Query for any server state. Never raw `useEffect + fetch`.
- Zod schemas mirror backend Pydantic models. Validate API responses at the edge.

### General
- Don't comment what the code does. Comment why, where it isn't obvious.
- Tests live next to code: `foo.py` ↔ `foo_test.py`, `Foo.tsx` ↔ `Foo.test.tsx`.
- Conventional commits: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`.

## Security posture

- **No telemetry.** This product runs on customer infrastructure. No outbound calls except to the configured Kubecost endpoint and the local Ollama.
- **Secrets** in `.env` (gitignored). Never commit. Token storage encrypted at rest in DB (use `cryptography` library, key from env).
- **CORS** locked to the frontend origin in production. Permissive in dev.
- **Input validation** at every boundary — Pydantic on the way in, Zod on the way out (frontend).
- **Auth (v2)** — single-user / no auth in v1. Multi-user with SSO planned for v2. Document this clearly.

## Out of scope for v1

- GCP and Azure cost integration (AWS only)
- Multi-user auth and RBAC (single-user)
- Slack/email alerts (later)
- Cost forecasting (later)
- Direct Kubernetes manifest editing / proposing PRs (later)
- Mobile responsive (desktop only is fine — this is a working tool)

## How to work in this repo

1. **Read this file first.** Always.
2. Read `TASKS.md` and pick a task.
3. Use the `frontend-design` skill for any UI work.
4. Run `docker compose up` to bring up the dev environment.
5. Backend hot-reloads. Frontend hot-reloads. Ollama and ChromaDB run as long-lived containers.
6. Before marking a task done: tests pass, types check, linter clean.

## Decisions log

These decisions are sticky. Don't relitigate without explicit user direction.

| Decision | Rationale |
|---|---|
| FastAPI over Node backend | Better LLM tooling, simpler async, mature Kubecost client patterns. |
| Ollama over hosted LLMs | Compliance — cost data must not leave customer infra. |
| Default model: `qwen2.5:7b-instruct` | Good quality-to-size ratio, runs on most laptops. Swappable in settings. |
| RAG with ChromaDB | Local, no service, easy to seed. Replaceable with pgvector if Postgres is already running. |
| arq over Celery | Async-native, simpler config, sufficient for our job profile. |
| shadcn/ui over MUI/Chakra | Modern aesthetic, full control, no runtime CSS-in-JS overhead. |
| Tailwind v4 (CSS-first) | Latest, faster, less config sprawl. |
| AWS-only v1 | Focus. Multi-cloud is its own product surface. |
