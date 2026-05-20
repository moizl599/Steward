# Operations

Day-2 stuff for running Steward beyond first install: where logs go, what warnings mean, how to back up data, how to update the model, how to upgrade between versions.

For first-time setup see [INSTALL.md](INSTALL.md). For diagnosing specific failures see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## Logs

All three services log JSON via `structlog` to stdout. Compose captures them:

```bash
# Tail everything
docker compose logs -f

# Just the worker (where scan execution happens)
docker compose logs -f worker

# Just the backend (API requests)
docker compose logs -f backend

# Last 100 lines of all services
docker compose logs --tail=100
```

If you ship logs to an aggregator (Datadog, Loki, CloudWatch), point your collector at the container stdout. The output is one JSON object per line — no parsing tricks needed.

### Key log events to watch

| Event | What it means | Action |
|---|---|---|
| `scan_started` | A scan job has begun. | Informational. |
| `kubecost_data_fetched` | All four Kubecost endpoints returned successfully. | Informational. |
| `digest_built` | Preprocessor finished. Includes `total_cost_usd` and `truncated`. | Informational. |
| `rag_retrieved` | RAG queries completed. Includes `queries` and `snippets` counts. | Informational. |
| `ollama_analyzed` | The LLM returned a structurally valid response. Includes token counts and duration_ms. | Informational. |
| `scan_completed` | Full pipeline succeeded; Report persisted. | Informational. |
| `scan_failed_kubecost` | Kubecost call failed (network, auth, 5xx). | Check the environment's `last_connection_error`; verify the URL and auth token. |
| `scan_failed_ollama` | Ollama call failed (model not found, timeout, OOM). | See [TROUBLESHOOTING.md](TROUBLESHOOTING.md#ollama-errors). |
| `ollama_report_inconsistent_attempting_repair` | The validator caught a contradiction; sending repair prompt. | Informational — this is the system working. The repair attempt usually fixes it. |
| `ollama_report_inconsistent_after_repair` | **Warning.** Model couldn't fix violations even after one repair round. Report persists with violations attached. | See [Inconsistent reports](#inconsistent-reports) below. |
| `scan_unexpected_error` | Something else broke. Stack trace included. | Open an issue with the trace. |

---

## Inconsistent reports

The `ollama_report_inconsistent_after_repair` warning is the most common operational signal. It means the LLM produced a report that contradicts its own digest in some specific way (e.g. claimed "no idle workloads" while the digest has four).

When it fires:

1. The report **is still saved and visible to the user.** A flawed report with a warning is more useful than no report.
2. The specific violations are listed in the log entry's `violations` field.
3. The user is not shown the violations in the UI in v0.1 (a follow-up item).

What to do:

- **Once or twice on a small cluster** — ignore. 7b-class models occasionally trip on cascading rules.
- **On every scan** — the cluster is probably tripping a specific rule. Read the violations and decide:
  - If it's a rule worth tightening: edit `backend/app/prompts/system.md`, restart the worker.
  - If it's a digest shape the validator is too strict about: open an issue.
  - Try a larger model: `qwen2.5:14b-instruct` is more reliable on multi-rule compliance (needs ~14 GB RAM). See [CONFIGURATION.md](CONFIGURATION.md#model-selection).

---

## Stuck scans

If a scan stays in `running` status indefinitely, the worker container probably crashed mid-scan. v0.1 does not have an orphaned-scan reconciliation loop.

To clear:

```bash
# Find the stuck scan ID from the UI or:
docker compose exec backend python3 -c "
import asyncio
from sqlalchemy import select
from app.db import AsyncSessionLocal
from app.models.scan import Scan, ScanStatus

async def main():
    async with AsyncSessionLocal() as s:
        result = await s.execute(select(Scan).where(Scan.status == ScanStatus.RUNNING))
        for scan in result.scalars():
            print(scan.id, scan.environment_id, scan.started_at)

asyncio.run(main())
"

# Then mark it failed (replace <ID>):
docker compose exec backend python3 -c "
import asyncio
from app.db import AsyncSessionLocal
from app.models.scan import Scan, ScanStatus

async def main():
    async with AsyncSessionLocal() as s:
        scan = await s.get(Scan, <ID>)
        scan.status = ScanStatus.FAILED
        scan.error_message = 'Worker crashed; marked failed manually.'
        await s.commit()

asyncio.run(main())
"
```

Adding an automated reconciliation loop is on the roadmap.

---

## Backups

### What to back up

Two volumes hold all user data:

- `backend_data` — SQLite database (or Postgres data if you migrated). Contains environments, scans, reports, encrypted auth tokens.
- `chroma_data` — Vector embeddings of the RAG corpus. Recreatable from `infra/chromadb/seed/` if lost.
- `ollama_data` — Pulled model weights. Recreatable via `ollama pull`. Large (~5 GB per model) but not worth backing up.

Practically: back up `backend_data` and you can recover everything else from the repo.

### SQLite backup

```bash
# Snapshot to a host-side file
docker compose exec backend sqlite3 /app/data/app.db ".backup '/tmp/snapshot.db'"
docker compose cp backend:/tmp/snapshot.db ./backup-$(date +%F).db
docker compose exec backend rm /tmp/snapshot.db
```

Or use the SQLite `.dump` approach if you want plain SQL:

```bash
docker compose exec backend sqlite3 /app/data/app.db .dump > backup-$(date +%F).sql
```

### Postgres backup

```bash
# Compose-managed Postgres
docker compose exec db pg_dump -U kubecost steward > backup-$(date +%F).sql

# External Postgres
pg_dump postgresql://user:pass@host:5432/steward > backup-$(date +%F).sql
```

Schedule via cron / launchd / your preferred scheduler.

### Restore

```bash
# SQLite
docker compose down
cat backup-2026-05-20.sql | docker compose run --rm backend sqlite3 /app/data/app.db
docker compose up -d

# Postgres
psql postgresql://user:pass@host:5432/steward < backup-2026-05-20.sql
```

---

## Updating the model

```bash
# Pull a new model
docker compose exec ollama ollama pull qwen2.5:14b-instruct

# List what's available
docker compose exec ollama ollama list

# Switch the default (edit .env, then)
docker compose restart backend worker

# Remove an old model
docker compose exec ollama ollama rm qwen2.5:7b-instruct
```

The Settings page in the UI shows pulled models. The one matching `OLLAMA_MODEL` is marked **default**.

---

## Re-ingesting the RAG corpus

There's no UI button for this in v0.1 (deferred — the button is hidden in Settings). The supported path is:

```bash
docker compose down
docker volume rm steward_chroma_data  # the volume prefix matches your compose project name
docker compose up -d
```

On startup, the backend re-indexes everything in `infra/chromadb/seed/`. First-boot indexing takes ~30 seconds for the default corpus.

To add new content, drop markdown files into `infra/chromadb/seed/` *before* the re-ingest.

---

## Upgrading Steward versions

v0.1 has no formal release versioning — `main` is the only branch. To upgrade:

```bash
cd /path/to/Steward
git pull
docker compose build       # rebuild local images from updated source
docker compose up -d
```

The backend auto-applies Alembic migrations on startup. If something goes wrong with a migration:

```bash
# View current migration version
docker compose exec backend alembic current

# View history
docker compose exec backend alembic history

# Downgrade if needed
docker compose exec backend alembic downgrade -1
```

For future versions with breaking schema changes, the release notes will spell out the migration path. **Back up before upgrading** (see above) — v0.1 hasn't been pressure-tested across version bumps.

---

## Container resource sizing

Default Compose has no resource limits. If you're running on a constrained host, add limits per service:

```yaml
services:
  ollama:
    deploy:
      resources:
        limits:
          memory: 8G
  backend:
    deploy:
      resources:
        limits:
          memory: 1G
  worker:
    deploy:
      resources:
        limits:
          memory: 1G
```

Ollama is the only service that benefits from generous memory. The rest are happy with 512 MB–1 GB.

For Docker Desktop on macOS/Windows, also bump the VM-level allocation: Docker Desktop → Settings → Resources. The 7b model needs at least 8 GB allocated; 14b needs at least 14 GB.

---

## Restarting individual services

```bash
docker compose restart backend         # picks up env changes (uvicorn hot-reload also works in dev compose)
docker compose restart worker          # picks up prompt changes (the prompt is @lru_cache'd in memory)
docker compose restart frontend        # picks up new sidebar text / branding changes
docker compose up -d --force-recreate backend  # recreate the container if env_file changed
```

After editing `.env`, `restart` is *not* enough — you need `up -d --force-recreate` so the container re-reads the env file.

---

## When to call something an incident

The dividing line for a single-operator install:

- **Not an incident:** A single scan failed. A model produced a wonky report. A `ollama_report_inconsistent_after_repair` warning fired. Connection to a Kubecost environment showed `stale`.
- **Incident:** All services are down. The backend can't reach Postgres/SQLite. Every scan against every environment has been failing for >24h. The Ollama container won't start.

For real incidents, the recovery path is usually `docker compose down && docker compose up -d`. If that doesn't help, check `docker compose logs` for the panicking service and search [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
