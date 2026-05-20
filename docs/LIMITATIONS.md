# Limitations

What Steward v0.1 explicitly is **not**. We'd rather over-disclose than have you discover gaps during onboarding.

---

## Single-user, no authentication

There is no auth layer. The frontend and backend both assume a single trusted operator on `localhost`. Anyone who can reach `http://localhost:3000` has full access to:

- Add and edit environments (including pasting Kubecost auth tokens).
- Trigger scans.
- View all reports.
- Read the system prompt and the RAG corpus.

**Do not expose Steward to a network without an authenticating reverse proxy in front of it.** See [SECURITY.md → Reverse-proxy recommendation](SECURITY.md#reverse-proxy-recommendation).

Multi-user with SSO is on the v0.2 roadmap. If your use case requires it before then, the practical workaround is one Steward install per user, each on their own machine.

---

## AWS / EKS only

The cost-analysis pipeline assumes Kubecost is configured for AWS EKS — specifically the EC2 instance pricing, EBS volume pricing, and ELB/NLB attribution. The digest preprocessor doesn't have GCP- or Azure-specific logic.

Kubecost itself supports GCP (GKE) and Azure (AKS). If you point Steward at a Kubecost install backed by one of those, the analysis will mostly work but:

- Savings-plan / reserved-instance recommendations are AWS-framed.
- Cluster-sizing recommendations assume EC2 instance families.
- Some prompt examples reference EBS specifically.

GCP and Azure support are coherent additions but explicitly out of scope for v0.1. Open an issue if you'd like to drive that work.

---

## Single-node, no high availability

The Compose deployment runs one of each service. Specifically:

- **One backend instance.** No leader election. Fine because the backend is stateless (state lives in Postgres/SQLite + Redis).
- **One worker instance.** Has `max_jobs=1`, so scans serialize. A worker crash mid-scan leaves the scan in `running` status forever (no reconciliation loop yet — manual fix per [OPERATIONS.md](OPERATIONS.md#stuck-scans)).
- **One Redis, one ChromaDB, one Ollama.** All single-instance.

For a multi-node HA deployment you'd need to:

- Replace SQLite with an external Postgres (or use the Compose Postgres in a real DB cluster).
- Replace the Compose Redis with a managed Redis (Elasticache, Redis Cloud).
- Run multiple worker replicas (arq supports this — `max_jobs` per worker stays at 1; concurrency grows by replica count).
- Run ChromaDB in client-server mode or swap for pgvector.
- Run Ollama externally with model weights on shared storage.

None of that is exercised in v0.1.

---

## No production-grade observability

Worker and backend log structured JSON to stdout via `structlog`. Compose captures it. That's the full observability story in v0.1.

**Specifically missing:**

- No `/health` or `/ready` endpoint. Operators have nothing to scrape for liveness checks.
- No `/metrics` endpoint. No Prometheus scrape target.
- No distributed tracing (OpenTelemetry, etc.).
- No exception tracker (Sentry, Rollbar).
- No log shipping. Logs stay in Docker. If the container restarts, recent logs are gone unless you forwarded them yourself.

For a single-operator dev install, this is fine. For anything else, plumb your own observability before going to production.

---

## Model quality varies

The default `qwen2.5:7b-instruct` is fast and handles single-rule compliance reliably, but occasionally trips the validator's cascading-rule checks (e.g. trivial-scale severity ceiling + impact_usd requirement + savings consistency, all at once).

When this happens, you see `ollama_report_inconsistent_after_repair` in worker logs. The report still persists; the validator's flagged violations are recorded. It's a v0.1 quality ceiling, not a bug.

**Mitigations available today:**
- Use a larger model (`qwen2.5:14b-instruct`) if your hardware allows. Better cascading-rule compliance, ~3× slower per scan, needs ~14 GB RAM.
- Inspect the violations and tighten the prompt for whatever the model keeps tripping on.

**Mitigations on the roadmap:**
- More post-LLM enrichment so the model never needs to satisfy multiple structured-field rules at once.
- Fine-tuning a small model on Steward's specific output schema (medium-term).

---

## Database upgrades untested

The schema works for fresh installs. Cross-version migrations (e.g. upgrading from an early v0.1 to a hypothetical v0.2) have not been pressure-tested against real customer data.

**Implication:** Back up before upgrading. The first time someone hits a migration bug, it'll probably be a real customer.

We use Alembic, so individual migrations are revertible. Schema-breaking releases will spell out the migration path in release notes.

---

## Mobile responsive is out of scope

Desktop-only by design. The product is for FinOps engineers reviewing reports at a real workstation, not for "check on my phone during dinner" use cases. The CSS uses fixed widths in places (the sidebar, the report's max-width container) that would need rework for a true responsive design.

We don't plan to address this in v0.x.

---

## No real edit / delete flows for environments

The UI shows neither Edit nor Delete buttons on environment rows in v0.1 — they were intentionally hidden after we removed the placeholder "coming soon" toast.

Today, to delete an environment, you'd run:

```bash
docker compose exec backend python3 -c "
import asyncio
from app.db import AsyncSessionLocal
from app.models.environment import Environment

async def main():
    async with AsyncSessionLocal() as s:
        env = await s.get(Environment, <ID>)
        await s.delete(env)
        await s.commit()

asyncio.run(main())
"
```

To edit, you'd update the row in the database directly, or delete and re-create. Not great. The real write flows + UI are an obvious v0.2 priority.

---

## No scan-to-scan diffs

The Reports page shows a trend chart and a flat table of historical scans, but the report page itself has no "vs. last scan" diff column. You can't see "findings ↑2, efficiency ↓1.4 pts since scan #12" without manually comparing two reports side by side.

The history is preserved correctly — the diff feature is just unbuilt. Comes when there's a real cluster with enough history to design against.

---

## No alerting

If a scan finds something critical, nothing happens automatically. There's no Slack notification, no email, no PagerDuty trigger, no webhook. The operator has to actively open Steward to see findings.

A simple alerting layer (cron + Slack webhook checking for findings above a severity threshold) is on the roadmap but unbuilt.

---

## No cost forecasting

Steward analyzes *current* cost data and points out waste. It doesn't project forward ("at this growth rate, you'll be spending $X/mo by Q3"). The history would support a basic forecast — the feature just isn't built.

---

## Anomaly visualization is unbuilt

The preprocessor detects week-over-week namespace cost growth above a threshold (`ANOMALY_GROWTH = 0.20` = 20%) and includes anomalies in the digest. They surface in finding cards.

But there's no dedicated anomaly visualization in the report page — no time-series chart of the anomalous namespace's cost over time, no comparison to baseline. The signal-counts card for anomalies is non-interactive.

This will be addressed when a real cluster fires real anomalies. The kubecost-test dev cluster never does.

---

## Limited to AWS-style cluster scales

The `cluster_scale` thresholds (`trivial < $50/mo < small < $1000/mo < production`) assume USD costs at AWS-ish prices. They'll behave sensibly on GCP/Azure too but the threshold breakpoints might want tweaking for non-AWS price points. Configurable thresholds (per-environment) would help — not in v0.1.

---

## Single-language UI

English only. No internationalization layer. Easy to add later (the UI uses very little text) but not done.

---

## When these limitations bite, what to do

The honest answer for any of these: **open an issue.** Most of the unbuilt features above are unbuilt because no real user has asked for them yet. Concrete pressure ("I need X to deploy this at $WORKPLACE") is what moves things up the roadmap.

For limitations that are blocking your evaluation (specifically: no auth, no GCP/Azure, no HA), be aware that the work to add them is non-trivial and won't happen in a v0.1.x patch — it's a v0.2+ conversation.
