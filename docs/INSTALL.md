# Installation

Steward runs entirely from Docker Compose. The default deployment uses SQLite, an embedded ChromaDB, and a local Ollama daemon — no external services required. Postgres is supported for installs that already run one.

This is the detailed walkthrough. For the 30-second version, see the [Quickstart in the main README](../README.md#quickstart).

---

## Prerequisites

- **Docker** with Compose v2. Tested on Docker Desktop 4.30+ and Docker Engine 24+.
- **8 GB RAM minimum** allocated to Docker. The default `qwen2.5:7b-instruct` model needs ~5 GB of activation buffers during inference, on top of the backend/frontend/Redis/ChromaDB containers.
- **~10 GB free disk** for the Ollama model weights, ChromaDB indexes, and Postgres data (if used).
- A reachable **Kubecost** install on an AWS EKS cluster (any v2.x version). You'll need:
  - The Kubecost API URL (e.g. `http://kubecost.acme.internal:9090`)
  - An auth token if your install gates access
  - The AWS region the cluster runs in (e.g. `us-east-1`)
- macOS, Linux, or WSL2 on Windows.

If you don't have a Kubecost install handy, you can run one locally for testing — see the [Kubecost install docs](https://docs.kubecost.com/install-and-configure/install).

---

## Steps

### 1. Clone the repo

```bash
git clone https://github.com/moizl599/Steward.git
cd Steward
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`. The only required field is `SECRET_KEY` — the Fernet key used to encrypt Kubecost auth tokens at rest. Generate one:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste the output into `.env` as the value of `SECRET_KEY`. Don't reuse keys across environments; if you ever lose this key, the encrypted tokens become unrecoverable and you'll need to re-enter them via the UI.

For all other variables — Ollama host, database URL, CORS origins — the defaults work for local development. See [CONFIGURATION.md](CONFIGURATION.md) for the full reference.

### 3. Start the stack

```bash
docker compose up -d
```

This starts six services:

| Service | Purpose | Port |
|---|---|---|
| `frontend` | Next.js UI | 3000 |
| `backend` | FastAPI app | 8000 |
| `worker` | arq job runner for scans | (internal) |
| `ollama` | Local LLM daemon | 11434 |
| `chromadb` | Vector store for RAG | 8001 (internal as 8000) |
| `redis` | Job queue + cache | 6379 (internal) |

First boot takes ~60 seconds — Ollama is the slowest because it allocates its model cache.

Check that all services are healthy:

```bash
docker compose ps
```

All should show `running` or `healthy` status.

### 4. Pull the default model

The Ollama container starts empty. Pull the model the backend expects:

```bash
docker compose exec ollama ollama pull qwen2.5:7b-instruct
```

This downloads ~5 GB. It runs once; the model persists in the `ollama_data` volume across container restarts.

If you have ≥14 GB RAM allocated to Docker, you can pull a stronger model instead (better cascading-rule compliance, ~3× slower per scan):

```bash
docker compose exec ollama ollama pull qwen2.5:14b-instruct
# then edit .env to set OLLAMA_MODEL=qwen2.5:14b-instruct
# then: docker compose restart backend worker
```

### 5. Open the UI

Navigate to **http://localhost:3000**. You should see the dashboard with the empty state ("No environments yet — connect your first Kubecost instance").

### 6. Add your first environment

Click **+ New environment**. Fill in:

- **Name** — anything human-readable (e.g. `prod-eks`)
- **Kubecost URL** — the URL the *backend container* can reach. If Kubecost runs in your cluster, you'll need it exposed via Ingress, LoadBalancer, or a port-forward you keep open. If you're testing locally, `http://host.docker.internal:9090` works on Docker Desktop.
- **AWS region** — pick from the dropdown
- **Auth token** — paste your Kubecost bearer token. Leave blank if your install is unauthenticated.

The form calls Kubecost's `/healthz` endpoint when you submit, and shows a pill indicating success or failure. Green dot = good to go.

### 7. Trigger your first scan

From the dashboard, click **Scan** on your environment card. The page navigates to the scan view, which polls for progress. A scan typically takes 60–120 seconds depending on cluster size and model.

When complete you'll see:

- An at-a-glance strip (cluster scale, efficiency dials, signal counts)
- A namespace cost breakdown bar
- An executive summary
- Severity-graded finding cards
- Tables for idle workloads, over-provisioned resources, and PVC waste
- Raw Kubecost data tabs at the bottom

If the scan failed, click the scan to see the error message. Most common causes: Kubecost URL unreachable from the backend container, or the auth token doesn't have read permission. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## Postgres backend (optional)

SQLite is fine for single-operator installs. If you already run Postgres (or want backup-friendly storage), switch:

1. Add a Postgres container to `docker-compose.yml`, or point at an existing one.
2. Set in `.env`:
   ```
   DATABASE_URL=postgresql+asyncpg://kubecost:password@db:5432/steward
   ```
3. Recreate the backend so it picks up the new env:
   ```bash
   docker compose up -d --force-recreate backend worker
   ```

The backend runs Alembic migrations on first startup. No manual schema setup required.

> **Note:** Cross-database migration (SQLite → Postgres) is not exercised in v0.1. If you have history in SQLite you want to keep, export with `docker compose exec backend sqlite3 /app/data/app.db .dump` and load it into Postgres manually.

---

## Production-ish considerations

This is a research-preview v0.1. If you're putting it on something other than a developer laptop, also:

- **Put an authenticating reverse proxy in front of the frontend.** The UI assumes one trusted user — there's no auth layer. nginx + basic auth or oauth2-proxy are reasonable.
- **Set `CORS_ORIGINS`** in `.env` to your actual frontend URL, not `http://localhost:3000`.
- **Back up the data volume.** `docker compose exec backend tar -czf /tmp/backup.tar.gz /app/data && docker compose cp backend:/tmp/backup.tar.gz ./backup-$(date +%F).tar.gz`. See [OPERATIONS.md](OPERATIONS.md).
- **Restrict the Ollama port.** Port 11434 is exposed on host by default for debugging. Lock it down with firewall rules or remove the port mapping in `docker-compose.yml`.

See [SECURITY.md](SECURITY.md) for the full threat model and what we explicitly do and don't protect against.

---

## Updating

```bash
git pull
docker compose pull          # if you ever build/publish your own images
docker compose up -d --build # rebuild local images from updated source
```

The backend auto-applies migrations on startup. The frontend hot-reloads in dev compose.

---

## Uninstalling

```bash
docker compose down -v       # stops everything, removes data volumes
```

This deletes scan history, the RAG corpus, and all encrypted auth tokens. Keep a backup first if any of that matters.
