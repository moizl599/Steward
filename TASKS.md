# Active task list

> **For Claude Code:** Read `CLAUDE.md` first. Pick the lowest-numbered open task. Mark in progress, ship it, mark done. Always run tests + lint before marking a task done. The `frontend-design` skill should be used on every UI task.

## Conventions

- Prefix commits with the task ID, e.g. `feat(B1): implement Kubecost client`.
- Tests: backend uses `pytest`, frontend uses Vitest (set up in T1).
- Don't mark a task complete if anything is half-done. Open follow-ups instead.

---

## Phase 0 — Tooling and verification

### T0. Bring up the dev environment
- `docker compose up -d` should start everything cleanly
- After Ollama is up: `docker exec -it <ollama_container> ollama pull qwen2.5:7b-instruct`
- Verify endpoints: http://localhost:3000, http://localhost:8000/docs, http://localhost:8001 (chroma), http://localhost:11434 (ollama)
- **Acceptance:** All four healthchecks green; `/health` and `/health/ready` return 200.

### T1. Set up backend test infra
- Add `pytest` config (already in `pyproject.toml`)
- Create `backend/app/conftest.py` with an in-memory SQLite fixture and a `httpx.AsyncClient` fixture for the FastAPI app
- Add a smoke test: `GET /health` → 200
- **Acceptance:** `pytest` runs green from inside the backend container.

### T2. Set up frontend test + lint
- Install Vitest + React Testing Library + jsdom
- Add `vitest.config.ts` with path aliases mirroring `tsconfig.json`
- Add a smoke test for `formatUSD` in `lib/utils.ts`
- Configure ESLint via `next lint`
- **Acceptance:** `npm run lint`, `npm run typecheck`, `npm test` all green.

---

## Phase 1 — Backend feature work

### B1. Implement the Kubecost client
File: `backend/app/services/kubecost.py`

- Implement `get_allocation`, `get_assets`, `get_savings`
- `get_allocation`:
  - Endpoint: `GET /model/allocation`
  - Params: `window=<window>`, `aggregate=namespace,controllerKind,controller`, `accumulate=true`, `step=1d`
  - Return shape: dict with `data` array of allocation records (cpuCost, ramCost, gpuCost, pvCost, networkCost, etc.)
- `get_assets`:
  - Endpoint: `GET /model/assets`
  - Params: `window=<window>`, `aggregate=type,cluster`, `accumulate=true`
- `get_savings`: aggregate Kubecost's savings endpoints. At minimum:
  - `GET /model/savings/requestSizing` (rightsizing recommendations)
  - `GET /model/savings/clusterSizing`
  - `GET /model/abandonedWorkloads`
- Add tests with `httpx.MockTransport` for happy path + auth-required + 5xx + timeout
- **Acceptance:** ≥90% line coverage on `kubecost.py`. All four error modes tested.

### B2. Build the pre-processor
File: `backend/app/services/preprocessor.py`

- Implement `build_digest(allocation, assets, savings, window) -> dict`
- Required digest keys (see schema in file header): `total_cost_usd`, `cluster_efficiency`, `top_namespaces_by_cost`, `idle_workloads`, `over_provisioned`, `pvc_waste`, `anomalies`, `savings_signals`
- "Idle" rule: avg CPU < 5% AND avg memory < 10% over the window
- "Over-provisioned" rule: requested CPU/mem ≥ 4× actual usage AND cost ≥ $20/mo
- "Anomaly" rule: namespace cost up >20% week-over-week (compare 7d window to prior 7d via a second Kubecost call when window=7d)
- Strict cap: digest must serialize to ≤ 8 KB JSON. Truncate top-N lists to keep under the cap.
- Tests: feed in fixture JSON files (`backend/tests/fixtures/kubecost_*.json`) and assert digest shape + truncation
- **Acceptance:** Tests pass with realistic sample data. Digest never exceeds 8 KB.

### B3. Implement the Ollama integration
File: `backend/app/services/ollama_client.py`

- Implement `OllamaService.analyze(digest, rag_context) -> dict`
- Use `ollama.AsyncClient.chat` with:
  - System prompt: persona = senior SRE + FinOps practitioner. Constraints: be specific, cite numbers, prioritize ruthlessly. (Draft in `backend/app/prompts/system.md`, load at runtime.)
  - User message: structured digest + retrieved RAG snippets
  - `format` parameter: JSON schema derived from `Report` Pydantic model (excecutive_summary + findings list + estimated_monthly_savings_usd)
  - `options.temperature = 0.2`
- Capture `prompt_eval_count`, `eval_count`, `total_duration` from response → store on Report row
- Implement `list_models` (already done in scaffold)
- Add a `pull_model(name)` method that streams progress
- Tests: mock the Ollama client; assert prompt structure and JSON parsing
- **Acceptance:** Given a fixture digest, returns a parseable structured Report. Token usage captured.

### B4. Build the RAG layer
File: `backend/app/services/rag.py`

- Implement `retrieve(query, k=4)`: query ChromaDB collection `finops_kb`, return list of strings
- Implement `ingest_seed_corpus(seed_dir)`: walk all `.md` files, chunk by H2 sections (max 512 tokens per chunk), embed with `sentence-transformers/all-MiniLM-L6-v2`, upsert into ChromaDB
- Add startup hook in `main.py` lifespan: if collection is empty, ingest from `/app/seed`
- Mount `infra/chromadb/seed/` to `/app/seed` in the worker container (update docker-compose.yml)
- **Seed content to write** (separate task, B4a):
  - `infra/chromadb/seed/finops-framework.md` — summarize FinOps Foundation principles (inform/optimize/operate)
  - `infra/chromadb/seed/k8s-rightsizing.md` — requests/limits guidance, VPA recommendations, common patterns
  - `infra/chromadb/seed/aws-eks-cost.md` — node group strategies, spot instances, savings plans for EKS
  - `infra/chromadb/seed/pvc-waste.md` — common EBS waste patterns, gp2→gp3, unmounted volumes
  - `infra/chromadb/seed/idle-workloads.md` — how to identify and remediate idle workloads
- **Acceptance:** Seed ingestion runs on first boot; retrieval returns relevant snippets for sample queries. Tests use a temp Chroma collection.

### B5. Implement the scan worker
File: `backend/app/workers/scan_worker.py`

- Implement `run_scan(ctx, scan_id)` per the pipeline in the file header:
  1. Open DB session, load Scan + Environment
  2. Update Scan.status = RUNNING, started_at = now, progress_message = "Connecting to Kubecost"
  3. Instantiate KubecostClient with decrypted token; call all three data endpoints concurrently with `asyncio.gather`
  4. progress_message = "Building digest" — call `build_digest`
  5. progress_message = "Retrieving knowledge" — call `RagService.retrieve` per category
  6. progress_message = "Analyzing" — call `OllamaService.analyze`
  7. Persist Report row, set Scan.status = COMPLETED, completed_at = now, total_cost_usd = digest['total_cost_usd']
  8. On any exception: Scan.status = FAILED, error_message = str(e), log with structlog, do not re-raise
- Tests: mock all services; verify state transitions and error handling
- **Acceptance:** Happy path + each failure mode (Kubecost down, Ollama timeout, ChromaDB error) covered by tests.

### B6. Add Alembic migrations
- Initialize Alembic: `alembic init alembic`
- Configure `alembic/env.py` to use `app.db.Base.metadata` and async URL from settings
- Generate initial migration from current models
- Document Postgres-vs-SQLite caveats in a comment
- **Acceptance:** `alembic upgrade head` works on a fresh DB. `alembic downgrade base` reverses cleanly.
- **Follow-up (CI/ops):** the production deploy job must run
  `alembic upgrade head` against the Postgres DB before starting the API
  process. The API's `lifespan` only calls `Base.metadata.create_all` for
  SQLite (dev). Bake this into the deploy runbook + CI pipeline once P3 lands.

---

## Phase 2 — Frontend feature work

> **Use the `frontend-design` skill on every task in this phase.** It will push back on generic AI aesthetics.

### F1. Install shadcn/ui base components
Run inside `frontend/`:
```bash
npx shadcn@latest add button input label card badge dialog tabs dropdown-menu skeleton toast
```
- Verify they land in `src/components/ui/`
- Add a global `<Toaster />` to the layout
- **Acceptance:** Components render with the dark theme defined in `globals.css`.

### F2. Build the "New environment" form
File: `frontend/src/app/environments/new/page.tsx`

- Use `react-hook-form` + Zod resolver
- Fields: name, kubecost_url (URL validation), aws_region (select with all AWS regions), cluster_name (optional), auth_token (optional, password input with show/hide toggle)
- Submit: `api.createEnvironment` → `api.testConnection` → on success, redirect to `/environments/[id]`
- After creation, show a live-updating connection status pill (green dot + latency + Kubecost version, or red dot + error)
- Apply `frontend-design` skill — bold typography, real layout, no generic AI form
- **Acceptance:** Form validates, submits, shows live connection status. Mobile is acceptable (not great).

### F3. Build the dashboard with environment cards
File: `frontend/src/app/page.tsx` (replace placeholder)

- Fetch `api.listEnvironments` with TanStack Query
- Empty state when none (already in placeholder — keep)
- Card per env showing: name, region, cluster_name, last connection status (colored dot), last-scanned timestamp, last total cost, big Scan button
- Click card → navigate to `/environments/[id]`
- Click Scan → call `api.triggerScan` → navigate to `/scans/[id]`
- **Acceptance:** Renders environments. Scan button enqueues a scan and navigates.

### F4. Build the environment detail page
File: `frontend/src/app/environments/[id]/page.tsx`

- Two columns: left = env metadata + connection control + Scan button; right = scan history list
- Scan history: paginated, each row clickable
- Edit env button → modal with same form as new (B2)
- Delete env button → confirmation dialog → call `DELETE /environments/:id`
- **Acceptance:** Full CRUD works. Scans list updates when new scans complete.

### F5. Build the scan/report view
File: `frontend/src/app/scans/[id]/page.tsx` (replace placeholder)

- Poll `api.getScan` every 2s while status is queued/running. Show progress with `progress_message`.
- When completed: fetch `api.getReport` and render:
  1. **Executive summary** block at top — large readable text, decorative quote-mark accent, model used + scan window in muted caption
  2. **Total estimated savings** — prominent USD figure with subtitle "if all recommendations applied"
  3. **Findings list** — sorted by severity then impact_usd. Each row: severity badge (color-coded), title, impact $, recommendation. Clickable to expand rationale.
  4. **Raw Kubecost data** — collapsible section at bottom with the digest pretty-printed
- When failed: error state with the error_message and a Retry button
- **Acceptance:** End-to-end scan → readable report. Severity badges color-correct.

### F6. Reports / history page
File: `frontend/src/app/reports/page.tsx` (replace placeholder)

- Across all environments: list of past reports
- Filters: by environment, by date range, by minimum severity
- Cost-over-time chart with Recharts (line chart, x = scan date, y = total_cost_usd, one line per environment)
- **Acceptance:** Filters work, chart updates reactively.

### F7. Settings page
File: `frontend/src/app/settings/page.tsx` (replace placeholder)

- Section 1: **Ollama** — current model dropdown, list of pulled models, "Pull new model" input with progress bar
- Section 2: **Prompts** — textarea editor for the system prompt, save/reset
- Section 3: **RAG knowledge base** — list of ingested documents with chunk counts, re-ingest button
- Backend endpoints needed (B7): `GET/POST /settings/ollama-model`, `GET/PUT /settings/system-prompt`, `GET/POST /settings/rag/reingest`
- **Acceptance:** Model swap works end-to-end (next scan uses new model).

### B7. Settings backend endpoints (paired with F7)
- `GET /settings/ollama-model` — return current model from settings
- `POST /settings/ollama-model` `{model: string}` — update Settings + pull model via Ollama
- `GET /settings/system-prompt` / `PUT /settings/system-prompt` — read/write `backend/app/prompts/system.md`
- `POST /settings/rag/reingest` — re-run `RagService.ingest_seed_corpus`
- **Acceptance:** Each endpoint has tests.

---

## Phase 3 — Polish and ship

### P1. Empty/loading/error states everywhere
- Skeletons for every list view
- Empty states with CTAs
- Error boundaries with retry
- **Acceptance:** Disconnect Kubecost mid-scan, kill Ollama, etc. — UI degrades gracefully.

### P2. Streaming Ollama output (stretch)
- Switch the Ollama call to streaming mode
- WebSocket endpoint `/ws/scans/:id` that pushes partial output
- Frontend renders partial summary as it arrives during a scan
- **Acceptance:** User sees text streaming in during analysis instead of a spinner.

### P3. Production Dockerfile + docker-compose.prod.yml
- Multi-stage builds for frontend + backend
- Postgres in production compose
- Nginx reverse proxy
- **Acceptance:** `docker compose -f docker-compose.prod.yml up` works on a fresh machine.

### P4. README polish
- Screenshots of the dashboard, scan in progress, and a finished report
- "How it works" architecture diagram
- Hardware recommendations for Ollama
- **Acceptance:** Project README reads like a real product page.

---

## Future / out of scope for v1

- GCP and Azure integration
- Multi-user auth (SSO)
- Slack / email alert routing
- Cost forecasting
- Direct PR proposals to k8s manifests
- Mobile-responsive layout
