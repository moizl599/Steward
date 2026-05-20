# Architecture

This is how Steward turns Kubecost API data into a prioritized executive report. The interesting parts aren't the boxes-and-arrows (those are standard) — they're the **digest grounding contract** between the preprocessor and the LLM, and the **judgment-vs-identity split** between the model and the worker.

If you're skimming, the [System overview](#system-overview) and [The grounded-LLM pattern](#the-grounded-llm-pattern) are the parts worth reading.

---

## System overview

```
┌─────────────────────┐        ┌──────────────────┐        ┌─────────────────┐
│  Next.js frontend   │ ─────► │  FastAPI backend │ ─────► │  Kubecost API   │
│  (TS + shadcn/ui)   │        │  (async)         │        │  (per env)      │
└─────────────────────┘        └────────┬─────────┘        └─────────────────┘
                                        │
                       ┌────────────────┼────────────────┐
                       ▼                ▼                ▼
               ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
               │   SQLite/PG  │  │    Ollama    │  │   ChromaDB   │
               │  (history)   │  │   (LLM)      │  │   (RAG)      │
               └──────────────┘  └──────────────┘  └──────────────┘
                       ▲
                       │
               ┌───────┴──────┐
               │  arq worker  │
               │  (Redis-backed)
               └──────────────┘
```

**Six services in Compose:**
- `frontend` — Next.js 15 (App Router, TypeScript, Tailwind v4, shadcn/ui).
- `backend` — FastAPI + Pydantic v2 + SQLAlchemy 2.0 async + arq job queue.
- `worker` — arq worker that runs the scan pipeline.
- `ollama` — Local LLM daemon (HTTP API on :11434).
- `chromadb` — Vector store seeded with FinOps reference material.
- `redis` — Job queue + cache.

The browser talks only to the FastAPI backend. The backend never makes outbound calls except to the configured Kubecost endpoint (per environment) and the local Ollama daemon. There is no telemetry.

---

## The scan pipeline

When the user clicks **Scan**, the request flow is:

1. `POST /environments/{id}/scan` creates a `Scan` row with status `queued` and enqueues an arq job.
2. The worker picks up the job and runs `_run_pipeline` (in `backend/app/workers/scan_worker.py`):

```
Phase 1: status=RUNNING, started_at=now, progress="Connecting to Kubecost"
Phase 2: concurrent fetches from Kubecost — allocation, prior_allocation, assets, savings
Phase 3: progress="Building digest" → preprocessor.build_digest()
Phase 4: progress="Retrieving knowledge" → RagService.retrieve() per finding category
Phase 5: progress="Analyzing (model: <name>)" → OllamaService.analyze()
Phase 6: enricher resolves digest_reference pointers → impact_usd and affected_resource
Phase 7: status=COMPLETED, persist Report + truncated raw_data + digest
```

Each phase commits to the database so the frontend's polling sees live progress.

Failures are caught and persisted as `status=FAILED` with `error_message`. The worker never re-raises — failed scans stay failed; the user retries with a new scan (one click in the UI).

---

## The grounded-LLM pattern

This is the architecturally distinctive piece. The preprocessor produces a digest with **grounding fields** that the LLM cannot override, and the validator catches contradictions before they reach the user.

### Step 1: The preprocessor builds a structured digest

`backend/app/services/preprocessor.py` transforms raw Kubecost allocation/assets/savings into a bounded JSON digest with these top-level keys:

```jsonc
{
  "window": "24h",
  "total_cost_usd": 1.47,
  "monthly_run_rate_usd": 44.10,
  "cluster_scale": "trivial",          // trivial | small | production
  "efficiency_grade": "critical",      // healthy | mediocre | poor | critical
  "analysis_hints": {                  // counts the validator checks against
    "idle_workload_count": 3,
    "over_provisioned_count": 0,
    "pvc_waste_count": 0,
    "anomaly_count": 0,
    "efficiency_grade": "critical",
    "cluster_scale": "trivial"
  },
  "cluster_efficiency": { "cpu": 0.037, "memory": 0.825, "overall": 0.126 },
  "top_namespaces_by_cost": [...],
  "idle_workloads": [...],             // each has a `name` used as digest_reference target
  "over_provisioned": [...],
  "pvc_waste": [...],
  "anomalies": [...],
  "savings_signals": {...}
}
```

The digest is capped at 8 KB. If a list overflows, the preprocessor caps to the top 10 entries by impact and adds a `truncated_counts` field so the LLM knows what was dropped.

`cluster_scale` and `efficiency_grade` are bucketed thresholds, not free-floating numbers. They become the words the LLM is required to use verbatim in prose.

### Step 2: The grounded system prompt

`backend/app/prompts/system.md` is the load-bearing LLM contract. It establishes:

- **Read the digest before writing** — the model must consult `cluster_scale`, `efficiency_grade`, `monthly_run_rate_usd`, and `analysis_hints` as ground truth.
- **Cluster scale rules** — trivial / small / production each get different behavior. Trivial-scale clusters have a hard severity ceiling of `low`, regardless of dollar bands.
- **Efficiency rules** — a grade table that ties `efficiency_grade` to a minimum severity per scale.
- **Recommendation quality** — every recommendation must name a specific workload, namespace, or controller. Vague verbs are forbidden.
- **Required `digest_reference`** — findings that map to a digest entry must include a pointer like `"idle_workloads/default/deployment/nginx"`. The model is explicitly told *not* to populate `impact_usd` or `affected_resource` directly — the worker handles that.
- **Self-consistency check** — a 7-item checklist the model is told to apply before returning.
- **Forbidden phrases** — `leverage`, `synergy`, `best-in-class`, `within a reasonable range`, etc. Generic AI filler that erodes trust.

### Step 3: The validator catches contradictions

`backend/app/services/report_validator.py` runs after the model returns a structurally valid response. It's a deterministic string-and-counts check (no LLM in this step):

- **Negation contradictions** — "no idle workloads" while `analysis_hints.idle_workload_count > 0`.
- **Healthy-downplay** — "looks healthy" / "within reasonable range" when `efficiency_grade` is `poor`/`critical`.
- **Boilerplate recommendations** — regex matches for the exact lazy phrases the model has produced in practice.
- **Trivial-scale ceiling** — refuses `medium`/`high`/`critical` severities on trivial clusters.
- **Trivial savings consistency** — refuses non-zero `estimated_monthly_savings_usd` on trivial clusters.
- **Dollar-band severity requires impact** — refuses `low`+ severity with `impact_usd: null`, *unless* the finding has a `digest_reference` (in which case the worker will resolve it).
- **Workload reference requires affected_resource** — same exemption.
- **`digest_reference` must resolve** — refuses pointers that don't match any digest entry.

Violations are sent back to the model in a single repair round. If the model can't fix them, the violations are logged as `ollama_report_inconsistent_after_repair` for operator review and the report persists with whatever the model produced. A flawed report with a warning is more useful than no report.

### Step 4: The enricher backfills structured fields

`backend/app/services/finding_enricher.py` is the "identity" half of the judgment-vs-identity split. For each finding with a `digest_reference`, it looks up the matching digest entry and copies `impact_usd` and `affected_resource` from there. The model never has to do mechanical data transcription — it just has to point at the right entry.

This shape removed an entire class of model failures we hit before adding the enricher: 7b-class models reliably wrote correct prose but unreliably copied numbers from JSON into structured fields. Now the model never touches those fields.

---

## Data model

All scan/report data is stored in the relational DB (SQLite or Postgres). The schema is small:

```
Environment
  id, name, kubecost_url, aws_region, cluster_name (nullable)
  auth_token_encrypted (Fernet-encrypted bytes)
  last_connection_ok, last_connection_check, last_connection_error
  created_at, updated_at

Scan
  id, environment_id, window, status, progress_message
  started_at, completed_at, error_message
  total_cost_usd
  raw_data (JSON — full Kubecost responses, truncated if > 256 KB)
  digest (JSON — the preprocessor output)
  created_at

Report
  id, scan_id
  executive_summary (text)
  findings (JSON list — enriched after model output)
  estimated_monthly_savings_usd
  model_used, prompt_tokens, completion_tokens, duration_ms
  created_at
```

`findings` and `digest` are stored as JSON columns. The first migration creates the schema; future migrations use Alembic.

---

## Frontend architecture

Standard Next.js 15 App Router. Notable pieces:

- **`frontend/src/lib/digest.ts`** — Zod schemas that mirror the backend's digest shape. The page validates API responses at the boundary, so a digest-shape change on the backend is caught at the type level.
- **`frontend/src/components/scan-report/`** — All the report-page components: at-a-glance dials, namespace breakdown bar, workload tables, finding cards, raw data tabs, footer. Each has its own test file.
- **`frontend/src/lib/api.ts`** — Single API client with Zod-validated responses. TanStack Query for all server state.

The frontend never talks to anything but the backend. No client-side LLM calls, no third-party analytics, no fonts loaded from non-Google CDNs (Geist and JetBrains Mono come from Google Fonts via Next.js's font loader).

---

## What lives where

```
backend/app/
├── api/                Route handlers (environments, scans, reports, settings)
├── models/             SQLAlchemy ORM (Environment, Scan, Report)
├── schemas/            Pydantic request/response shapes
├── services/
│   ├── kubecost.py         Kubecost HTTP client
│   ├── ollama_client.py    Ollama wrapper + structured-output schema enforcement
│   ├── preprocessor.py     Raw Kubecost → structured digest
│   ├── rag.py              ChromaDB embedding + retrieval
│   ├── report_validator.py Post-LLM contradiction check
│   └── finding_enricher.py digest_reference → impact_usd / affected_resource
├── workers/
│   └── scan_worker.py  arq job: end-to-end scan pipeline
├── prompts/
│   └── system.md       The LLM contract (read this to understand model behavior)
└── main.py             FastAPI app entry
```

---

## What's deliberately not in v0.1

- **Multi-cloud.** AWS/EKS only. GCP/Azure are coherent backends to add but they're out of scope.
- **Multi-user / auth.** Single trusted operator on localhost. Multi-user + SSO is v2.
- **Real-time scan progress via websockets.** The frontend polls every 2s while a scan is `queued`/`running`. Simple, works, no socket plumbing.
- **A separate "alerts" service.** The Report rows are queryable; an alerts layer can be a future cron or external workflow.

See [LIMITATIONS.md](LIMITATIONS.md) for the complete honest list.
