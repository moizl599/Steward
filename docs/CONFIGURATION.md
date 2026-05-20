# Configuration

All configuration is via environment variables loaded from `.env`. The backend uses Pydantic Settings, so anything in `.env` overrides the defaults baked into `backend/app/config.py`.

This page is the complete reference. For the getting-started subset, see [INSTALL.md](INSTALL.md).

---

## Environment variables

### Required

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | *required* | Fernet key for encrypting Kubecost auth tokens at rest in the database. Generate with `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **Treat this like a database password.** Losing it means losing access to stored tokens. |

### Database

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/app.db` | SQLAlchemy async URL. For Postgres: `postgresql+asyncpg://user:pass@db:5432/steward`. |

The SQLite default is fine for single-operator installs. SQLite is also what the test suite uses. Postgres is supported but the v0.1 codebase has not been exercised against a real production-scale Postgres install — file an issue if you hit something.

### Ollama (the local LLM)

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_HOST` | `http://ollama:11434` | URL of the Ollama daemon. The default targets the Compose-internal `ollama` service. To run Ollama on the Docker host instead, use `http://host.docker.internal:11434`. |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct` | Default model name. Must be pulled separately via `docker compose exec ollama ollama pull <name>`. See [Model selection](#model-selection) below. |

### ChromaDB (RAG corpus)

| Variable | Default | Purpose |
|---|---|---|
| `CHROMA_HOST` | `chromadb` | Hostname of the ChromaDB service. |
| `CHROMA_PORT` | `8000` | Port (inside the container — externally mapped to `8001` in compose so it doesn't collide with the backend). |

### Redis (job queue)

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379/0` | URL used by the arq job queue. The worker container connects here to pick up scan jobs. |

### Frontend → Backend wiring

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Browser-visible URL of the backend. Used by the frontend's API client. When deploying behind a reverse proxy, set to the externally reachable backend URL. |

### CORS

| Variable | Default | Purpose |
|---|---|---|
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowlist for browser origins. Lock this down in production — leaving it permissive lets any site call the backend from a user's browser. |

### Logging

| Variable | Default | Purpose |
|---|---|---|
| `LOG_LEVEL` | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. Backend and worker both honor this. `INFO` is fine for production. `DEBUG` is verbose — useful when triaging a stuck scan. |

---

## Model selection

The default `qwen2.5:7b-instruct` handles most clusters but occasionally trips the post-LLM consistency validator when asked to satisfy multiple cascading rules at once (e.g. cluster-scale ceiling + structured-field requirements). When that happens, you'll see `ollama_report_inconsistent_after_repair` warnings in the worker logs — the report still persists but with the validator's residual violations recorded.

Tested alternatives:

| Model | Size | RAM needed | Notes |
|---|---|---|---|
| `qwen2.5:7b-instruct` | 4.4 GB | ~8 GB Docker allocation | Default. Fast (~90s per scan), good single-rule compliance. |
| `qwen2.5:14b-instruct` | 9 GB | ~14 GB Docker allocation | Better cascading-rule compliance. ~3× slower per scan. Recommended if your hardware allows. |
| `llama3.1:8b` | 4.9 GB | ~8 GB Docker allocation | Comparable to qwen 7b. Slightly slower (~260s observed); we found it regressed on boilerplate-recommendation detection. Not recommended. |

To switch:

```bash
docker compose exec ollama ollama pull qwen2.5:14b-instruct
# edit .env: OLLAMA_MODEL=qwen2.5:14b-instruct
docker compose restart backend worker
```

The Settings page in the UI lists all pulled models. The default is the one matching `OLLAMA_MODEL`.

---

## Customizing the system prompt

The LLM contract lives in `backend/app/prompts/system.md`. This file is bind-mounted from your host into the backend and worker containers — edits take effect after restarting the worker:

```bash
docker compose restart worker
```

> **The prompt is load-bearing.** It defines the digest grounding contract, the severity rules, the trivial-cluster behaviors, and the self-consistency check. Random edits will break the report quality. If you customize it, run a few test scans on a known cluster afterward and watch the worker logs for new `ollama_report_inconsistent_after_repair` warnings.

The prompt is also viewable read-only from the **Settings → System prompt template** page in the UI so operators can see what the model is being told without needing shell access.

---

## RAG corpus

ChromaDB indexes FinOps reference material that the worker retrieves alongside the digest on every scan. Each scan pulls 2 snippets per finding category (idle workloads, over-provisioning, PVC waste, anomalies, savings signals), capped at 6 total snippets.

The seed corpus lives in `infra/chromadb/seed/`. To add or modify reference material:

1. Drop markdown files into `infra/chromadb/seed/`.
2. Delete the ChromaDB data volume to force re-indexing:
   ```bash
   docker compose down
   docker volume rm steward_chroma_data   # adjust prefix if your compose project name differs
   docker compose up -d
   ```
3. Watch the backend logs — you should see embedding chunks being indexed on first startup.

Re-ingestion from the UI is **not** implemented in v0.1 (the button is hidden). The volume-delete dance above is the supported path.

---

## Per-service overrides

If you need to point Steward at services running outside Compose:

**External Ollama:**
```
OLLAMA_HOST=http://host.docker.internal:11434  # Docker Desktop
OLLAMA_HOST=http://172.17.0.1:11434            # Linux Docker
```

**External Redis:**
```
REDIS_URL=redis://your-redis-host:6379/0
```

**External Postgres:**
```
DATABASE_URL=postgresql+asyncpg://user:pass@your-pg-host:5432/steward
```

After any of these changes:
```bash
docker compose up -d --force-recreate backend worker
```

---

## Where is each setting read from?

If you're tracing a config issue, the order of precedence:

1. Environment variables passed at container start (Compose `environment:` block, if any).
2. `.env` file in the repo root (the canonical path — almost always what you want to edit).
3. Defaults in `backend/app/config.py`.

Frontend env vars (`NEXT_PUBLIC_*`) are baked in at build time. After changing `NEXT_PUBLIC_API_URL`, rebuild the frontend image:

```bash
docker compose build frontend
docker compose up -d frontend
```

---

## Reading config from a running container

To verify what config a service actually loaded:

```bash
docker compose exec backend env | grep -E "(SECRET|OLLAMA|DATABASE|REDIS|CHROMA|CORS|LOG)"
```

Never paste the output anywhere public — it includes `SECRET_KEY`.
