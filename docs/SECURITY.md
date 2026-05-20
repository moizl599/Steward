# Security

Steward is positioned for regulated environments (healthcare, finance, government). This page documents what we protect, what we don't, and the v0.1 caveats.

If you find a security issue, please open a GitHub issue **without details** and email `moizlakdawala97@gmail.com` for the disclosure. We'll coordinate a fix before public disclosure.

---

## Threat model

### What Steward protects against

**1. Cluster cost data leaving customer infrastructure.**
The product's central security claim. Every component runs in the customer environment:

- Frontend, backend, worker, Redis, ChromaDB, and Ollama all run as containers in the customer's Docker host.
- The backend's only outbound network calls are to (a) the configured Kubecost endpoint (in the customer's cluster) and (b) the local Ollama daemon (loopback / Compose-internal).
- There is no telemetry. No usage analytics, no error reporting, no model-improvement pipeline. The code does not contain any third-party HTTP clients pointed at any vendor's domain.
- The LLM that analyzes the cost data is `qwen2.5:7b-instruct` (or whichever model is configured), running locally on the Ollama daemon. Cluster data is sent to the local Ollama HTTP API — never to OpenAI, Anthropic, or any cloud LLM provider.

If you grep the codebase for outbound HTTP, the only hostnames you'll find are user-configured (Kubecost URL) or loopback (`ollama:11434`, `chromadb:8000`, `redis:6379`).

**2. Kubecost auth tokens at rest in the database.**
Tokens are encrypted with Fernet (symmetric AES-128 + HMAC-SHA256) before being written to the `environments` table. The encryption key is `SECRET_KEY`, loaded from `.env` and never logged.

This means:
- A compromised database file alone is not enough to recover tokens.
- A compromised `.env` *plus* the database file gives full access.
- Backups should treat `.env` with the same care as the database itself.

**3. Frontend XSS from rendered LLM output.**
LLM-produced strings (`executive_summary`, `recommendation`, `rationale`, finding titles) are rendered as text in React, not as `dangerouslySetInnerHTML`. JSX text escapes HTML automatically. The model can't inject script tags into the UI even if it tried.

**4. SQL injection via Kubecost API responses.**
Kubecost responses are parsed into Pydantic models before reaching SQLAlchemy. Pydantic enforces types at the boundary. SQLAlchemy parameterizes all queries. There is no string concatenation into SQL anywhere in the backend.

### What Steward does NOT protect against (v0.1)

**1. Authentication.**
There is no auth layer. The frontend assumes a single trusted operator on `localhost`. **Do not expose the frontend or backend to a network without an authenticating reverse proxy in front of them.** Recommended setup:

- nginx with HTTP basic auth, or
- oauth2-proxy in front of the frontend container, or
- A VPN-only deployment where access to localhost ports is gated at the network layer.

Multi-user authentication with SSO is on the v0.2 roadmap.

**2. Multi-tenancy.**
Single-tenant by design. Every connected environment is visible to every operator. If you need per-team access controls, this is not the v0.1 release for you.

**3. Container escape, host compromise, supply chain.**
We pin Python and Node dependencies via `uv.lock` and `package-lock.json`, but we don't run automated CVE scanning, image signing, or SBOM generation in v0.1. If your security policy requires SLSA-level provenance, you'll need to build and sign images yourself.

**4. Resource exhaustion from a malicious user.**
A trusted operator can trigger unlimited scans, which will queue up in arq. There's no rate limiting. The arq worker runs `max_jobs=1` so scans serialize, but the queue can grow unbounded.

**5. Memory leaks from very large clusters.**
The digest preprocessor caps output at 8 KB and bounds list lengths, but the *input* (raw Kubecost responses) is not bounded. A cluster with 100,000 allocations might cause memory spikes in the worker. Tested on small/medium clusters only.

---

## What stays local — concrete list

| Data | Where it lives | Leaves the host? |
|---|---|---|
| Kubecost auth tokens | `environments.auth_token_encrypted` (Fernet-encrypted) | No |
| Namespace names | `scans.raw_data`, `scans.digest`, `reports.findings` | No |
| Workload identifiers (deployment names, etc.) | Same as above | No |
| Cost figures (USD per namespace/workload) | Same as above | No |
| Cluster efficiency ratios | `scans.digest` | No |
| Executive summary text (LLM-generated) | `reports.executive_summary` | No |
| LLM model weights | `ollama_data` volume | No (downloaded once from Ollama's CDN at install time) |
| RAG corpus content | `chroma_data` volume + `infra/chromadb/seed/` | No |
| Application logs | Container stdout (captured by Docker) | Depends on your log forwarder |
| `SECRET_KEY` | `.env` on the host filesystem | No (unless committed to a public repo — see [Operations](#operational-security)) |

The only data flowing **out** of the customer environment is:

- Initial Ollama model download (from `ollama.com` CDN — happens once at install).
- Initial container image pulls (from Docker Hub — happens once at install).
- Outbound HTTP from the backend to the configured Kubecost URL (which is in the customer's own cluster).

There is no "phone home" of any kind.

---

## Encryption at rest

`SECRET_KEY` must be a Fernet key (URL-safe base64 of 32 random bytes). Generate one:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The Fernet implementation comes from `cryptography>=43.0.0` (pinned in `backend/pyproject.toml`).

**If you lose `SECRET_KEY`:**
- All encrypted auth tokens become permanently unreadable.
- You must re-enter the auth tokens for every connected environment via the UI.
- Scan history and reports are preserved (they're not encrypted — they aren't secrets after the scan completes).

**If you suspect `SECRET_KEY` was exposed:**
1. Generate a new key.
2. Update `.env` with the new key.
3. The old tokens will fail to decrypt. Re-enter them via the UI's environment edit form.
4. Rotate the Kubecost tokens themselves (revoke the old ones in your auth system).
5. Restart `backend` and `worker` containers.

---

## Network surface

Default Compose exposes these ports to the Docker host:

| Service | Host port | Container port | Notes |
|---|---|---|---|
| `frontend` | 3000 | 3000 | Public-ish: this is what users hit. |
| `backend` | 8000 | 8000 | API. The frontend calls this. |
| `ollama` | 11434 | 11434 | Exposed for debugging. **Consider removing this mapping** in production to avoid letting other host processes hit the LLM. |
| `chromadb` | 8001 | 8000 | Same — exposed for debugging. |
| `redis` | (not exposed) | 6379 | Compose-internal only. Good. |

To lock down Ollama and ChromaDB, edit `docker-compose.yml` and remove the `ports:` mapping from those services. They'll still be reachable from other Compose services via the internal network.

---

## Reverse-proxy recommendation

A reasonable production-ish setup:

```
Internet → ALB / nginx → oauth2-proxy → frontend (port 3000)
                                      → backend (port 8000)
```

oauth2-proxy handles auth (against Google Workspace, Okta, etc.); the frontend and backend stay on a private network reachable only via the proxy. This adds the auth layer Steward intentionally doesn't ship in v0.1.

Set `CORS_ORIGINS` in `.env` to the *public* frontend URL (the one users hit), not `http://localhost:3000`.

---

## Operational security

Things that are easy to mess up:

- **Never commit `.env`.** The repo's `.gitignore` excludes it; the `setup-github.sh` script verifies it's not staged before pushing. Don't override either of those safeguards.
- **Don't paste `docker compose exec backend env` output anywhere public** — it includes `SECRET_KEY`.
- **Don't log Kubecost auth tokens.** The backend never logs them (the `decrypt()` helper is only called in scope of the Kubecost client construction). If you add custom logging, follow the same pattern.
- **Postgres credentials in `DATABASE_URL`** include the password in plain text. If you're using Postgres, treat `.env` accordingly.

---

## Reporting a security issue

For non-sensitive issues (e.g. "the docs say X but the code does Y"), open a regular GitHub issue.

For sensitive issues (data exposure, auth bypass, encryption flaws):

1. Open a GitHub issue titled "Security issue — details to follow privately." Don't include details in the public issue.
2. Email `moizlakdawala97@gmail.com` with the details.
3. Expect a reply within a few days. We'll coordinate a fix before any public disclosure.

There is no bug bounty in v0.1, but we'll credit reporters in release notes if you'd like.

---

## v0.2 security roadmap

In rough priority order:

1. **Multi-user authentication with SSO** (OIDC / SAML).
2. **Role-based access control** for multi-team installs.
3. **Audit log** of scan triggers, environment edits, token re-entries.
4. **SBOM and image signing** for the published Docker images (once images are published).
5. **Per-environment scan rate limits** so a runaway script can't queue unbounded jobs.

If your use case is blocked by any of these, open an issue describing the gap — concrete pressure helps prioritize.
