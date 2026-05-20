# Troubleshooting

Common failure modes and how to fix them. If your problem isn't here, check [OPERATIONS.md](OPERATIONS.md) for general log-reading guidance, then open a GitHub issue with the relevant `docker compose logs` output.

---

## Install issues

### `docker compose up` fails with "no matching manifest" or "exec format error"

You're on Apple Silicon (M1/M2/M3) and one of the images doesn't have an ARM build. Usually it's `chromadb/chroma`.

**Fix:** Add `platform: linux/amd64` to the chromadb service in `docker-compose.yml`. It'll run under Rosetta. Slower, but works.

### Ollama container won't start: "Error: model 'qwen2.5:7b-instruct' not found"

The model wasn't pulled. The Ollama container starts empty.

**Fix:**
```bash
docker compose exec ollama ollama pull qwen2.5:7b-instruct
```

This downloads ~5 GB. Run once; the model persists in the `ollama_data` volume.

### Backend won't start: "ValueError: SECRET_KEY must be set"

The `.env` file is missing or doesn't have `SECRET_KEY`.

**Fix:**
```bash
cp .env.example .env
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Paste the output into .env as SECRET_KEY=...
docker compose restart backend worker
```

### Frontend shows "Failed to load environments" on the dashboard

The frontend can't reach the backend. Either the backend is down or `NEXT_PUBLIC_API_URL` points at the wrong host.

**Fix:**
1. `docker compose ps backend` — confirm it's running.
2. `curl http://localhost:8000/` — should return `{"service": "steward", "docs": "/docs"}`.
3. If the backend's healthy but the frontend can't reach it, you probably changed `NEXT_PUBLIC_API_URL` and didn't rebuild the frontend image. Rebuild:
   ```bash
   docker compose build frontend && docker compose up -d frontend
   ```

---

## Connection issues

### "Connection failed: connection refused" when adding an environment

The backend container can't reach the Kubecost URL you provided. The URL is relative to the *backend container*, not your laptop.

**Fix per scenario:**

- **Kubecost runs on your laptop (port-forwarded to `localhost:9090`):** Use `http://host.docker.internal:9090` instead. The `host.docker.internal` hostname is Docker Desktop's way to reach the host from inside a container.
- **Kubecost runs in an EKS cluster, exposed via Ingress:** Use the Ingress URL. Confirm the backend container can resolve and reach it: `docker compose exec backend curl -v https://your-kubecost-url/healthz`.
- **Kubecost runs in an EKS cluster, kept private:** You need to expose it somehow (port-forward, Tailscale, AWS PrivateLink) or run Steward inside the same cluster.

### Connection pill says "stale · checked Xd ago"

The connection was last verified more than 24 hours ago. Either the periodic re-check isn't running, or there's no periodic re-check in v0.1 (correct — there isn't).

**Fix:** Re-trigger by clicking **Test connection** on the environment edit form, or just trigger a scan — that re-tests as part of the pipeline.

### "Connection failed: 401 Unauthorized" / "403 Forbidden"

The auth token is wrong, expired, or doesn't have read permission on Kubecost's API.

**Fix:**
1. Test the token directly: `curl -H "Authorization: Bearer <TOKEN>" https://your-kubecost-url/model/allocation?window=24h`.
2. If that fails too, rotate the token in your auth system and re-enter it via the environment edit form.

---

## Scan issues

### Scan stays "queued" forever

The worker isn't picking up jobs. Either the worker container is down or Redis is unreachable.

**Fix:**
```bash
docker compose ps worker redis
# Both should show running

docker compose logs --tail=50 worker
# Look for "Connection refused" or similar Redis errors

docker compose restart worker
```

### Scan stays "running" forever

The worker container crashed mid-scan. v0.1 doesn't have an orphaned-scan reconciliation loop.

**Fix:** Manually mark the scan failed. See [OPERATIONS.md → Stuck scans](OPERATIONS.md#stuck-scans).

### Scan fails: "Ollama: model not found"

`OLLAMA_MODEL` in `.env` points at a model that hasn't been pulled.

**Fix:**
```bash
docker compose exec ollama ollama list   # see what's actually there
docker compose exec ollama ollama pull <whatever OLLAMA_MODEL is set to>
```

### Scan fails: "Ollama: requires more system memory"

The model needs more RAM than Docker has allocated.

**Fix:**
- On Docker Desktop (macOS/Windows): Settings → Resources → Memory. Bump to 8 GB minimum for the 7b model, 14 GB for the 14b model. Apply, then `docker compose up -d`.
- On Linux: there's no Docker VM; the limit is your host RAM. Free up memory or switch to a smaller model.

### Scan fails: "Ollama: timeout"

The model is taking too long. Usually because the host is starved for CPU or another big LLM call is in flight.

**Fix:**
- Check if anything else heavy is running: `docker stats`.
- Restart Ollama: `docker compose restart ollama`.
- If it happens consistently, switch to a smaller/faster model.

### `ollama_report_inconsistent_after_repair` warning on every scan

The model is failing the validator's consistency checks even after the repair round. This means the LLM produced a report that contradicts its own digest.

**Fix:**
1. Read the violations field in the log entry to see exactly what failed.
2. Try a larger model (`qwen2.5:14b-instruct`) if RAM allows. See [CONFIGURATION.md → Model selection](CONFIGURATION.md#model-selection).
3. If the violations point at a real bug in the prompt or validator, open an issue with the violations + a sample digest.

The report still persists when this fires — the warning means "this report is flawed, here's how" rather than "the scan failed."

### Scan completes but the report is empty / says "no findings worth surfacing"

This is correct behavior on a healthy cluster (low efficiency grade `healthy`, no idle workloads, no over-provisioning, no anomalies). The prompt explicitly tells the model to emit a single `info` finding in that case rather than invent things.

If you expected findings and didn't get any:

1. Open the **Raw Kubecost data** tabs at the bottom of the report.
2. Check the **Full digest** tab. If `idle_workloads` and `over_provisioned` arrays are empty there, the preprocessor genuinely found nothing — the cluster is well-tuned, or the window is too short to surface waste.
3. Try a longer window (`7d` instead of `24h`) — the trigger endpoint doesn't expose this in v0.1, but you can hit the API directly: `POST /environments/{id}/scan` with `{"window": "7d"}`.

---

## UI issues

### Idle workloads table shows `__idle__/__idle__/__idle__` rows

You're on an older version. v0.1 includes a fix that filters these sentinel namespace rows out of `idle_workloads` and `over_provisioned`. Pull latest:

```bash
git pull
docker compose build backend worker
docker compose up -d
```

### "Estimated monthly savings: $X" shows on a trivial cluster

The frontend hides this block when `cluster_scale === "trivial"` AND the savings value is null/zero. If you're seeing a non-zero value on a trivial cluster, the validator caught it (you'll see `ollama_report_inconsistent_after_repair` in worker logs) but didn't reject the report. The frontend should still hide it; if it's showing, open an issue with the report ID.

### Sidebar still says `kubecost.analyzer` instead of `steward`

You're running a frontend image built before the rename. Rebuild:

```bash
docker compose build frontend
docker compose up -d frontend
```

If you're in dev mode and the change still isn't picking up, hard-refresh the browser (Cmd+Shift+R / Ctrl+Shift+F5) to flush the cached JS bundle.

### Raw data tabs show "unavailable"

The `GET /scans/{id}/raw-data` endpoint isn't reachable. Probably the backend container is on an older image that doesn't include that route.

**Fix:** Rebuild the backend:
```bash
docker compose build backend
docker compose up -d backend
```

The Full digest tab works even when raw data is unavailable (it uses a different endpoint).

---

## Database / migration issues

### Backend fails to start: "Alembic upgrade failed"

The database schema is out of sync with what the code expects. Either you downgraded to a version that doesn't have the latest migration, or a migration failed partway through.

**Fix:**
```bash
docker compose exec backend alembic current      # what version is the DB on?
docker compose exec backend alembic history      # what versions are available?
docker compose exec backend alembic upgrade head # apply pending migrations
```

If `upgrade head` fails with a real error (column conflict, type mismatch), back up the DB first, then ask in an issue.

### Lost SECRET_KEY, can't decrypt auth tokens

The encrypted tokens are unrecoverable without the key — that's the point of Fernet.

**Fix:**
1. Generate a new `SECRET_KEY` and put it in `.env`.
2. Restart `backend` and `worker`.
3. Open each environment in the UI, click edit, paste the auth token again, save. The new token gets encrypted with the new key.
4. Old encrypted tokens will fail to decrypt silently (the connection-test pill will show "Connection failed" because there's no usable auth header).

---

## Performance issues

### Scan takes 5+ minutes

Either the model is too big for your hardware, or Kubecost is slow to respond.

**Diagnose:**
- Look at the worker log entry for `ollama_analyzed`. The `duration_ms` field is the model's wall time. If that's >180000 (3 minutes), the model is the bottleneck.
- If the log shows the model finished quickly but the overall scan was slow, Kubecost itself is slow — check the `kubecost_data_fetched` log entry timing.

**Fix:**
- Model bottleneck: switch to `qwen2.5:7b-instruct` (smaller, faster).
- Kubecost bottleneck: use a smaller window (`24h` instead of `30d`), or warm up Kubecost's Prometheus by hitting it directly first.

### Frontend is slow / laggy

Probably because the report page is rendering large `raw_data` JSON in the tabs. The tabs lazy-render via `useMemo`, but the first click on a tab still has to stringify the slice.

**Fix:** None needed if you're on the latest version — the lazy rendering means only the active tab gets stringified. If a single tab is truly massive (>1 MB of JSON), the raw data was probably truncated already; the warning note at the top of the affected tabs will say so.

---

## When to give up and reset

If multiple things are broken at once and you've spent more than ~30 minutes triaging, a full reset is faster than continuing:

```bash
docker compose down -v          # WARNING: deletes all scan history and tokens
docker compose up -d
docker compose exec ollama ollama pull qwen2.5:7b-instruct
# Re-add your environments via the UI
```

Yes, you lose history. Yes, that's annoying. But on a v0.1 install, history is rarely worth more than the time spent triaging a corrupted state. Take a backup first if any of the data matters.

---

## Still stuck?

Open a GitHub issue with:

1. What you ran / what you saw / what you expected.
2. Output of `docker compose ps`.
3. Last ~50 lines of `docker compose logs --tail=50` for the relevant service.
4. The contents of `.env` **with `SECRET_KEY` redacted**.
5. Your OS and Docker version (`docker --version`, `docker compose version`).

Issues without logs take much longer to diagnose. Issues with the secret key included will be deleted and need to be re-filed after you rotate the key.
