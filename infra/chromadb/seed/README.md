# RAG seed corpus

Markdown files in this directory are ingested into ChromaDB on first boot to give the LLM grounding in FinOps and Kubernetes cost optimization knowledge.

See `TASKS.md` → **B4** and **B4a** for the files to add and the chunking strategy.

When you add or update content here, re-run ingestion from the Settings page (or `POST /settings/rag/reingest`).
