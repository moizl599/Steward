# Seed corpus to-dos (B4a)

This directory holds the Markdown knowledge base that the RAG layer
ingests on startup. Each file should follow the section structure below
so the chunker (`backend/app/services/rag.py`) produces well-bounded
chunks (50–512 approximate tokens per H2 section).

## Required files (B4a)

- `finops-framework.md` — FinOps Foundation principles (inform/optimize/operate)
- `k8s-rightsizing.md` — requests/limits guidance, VPA recommendations, common patterns
- `aws-eks-cost.md` — node group strategies, spot instances, savings plans for EKS
- `pvc-waste.md` — common EBS waste patterns (gp2→gp3, unmounted volumes, oversize)
- `idle-workloads.md` — how to identify and remediate idle workloads

`SEED_TODO.md` (this file) is excluded from ingestion.

## Per-file template

```markdown
# <Title>

One-paragraph summary, plain prose. No bullet points up here.

## When this matters

When does this concern come up? What's the typical signal in Kubecost or
the cluster?

## What to look for

Specific Kubernetes / AWS / Kubecost signals: idle CPU < 5%, request:usage
ratio > 4, gp2 volumes that should be gp3, etc. Use real numbers.

## Remediation

Concrete actions, in priority order. Cite real commands, manifest changes,
or config knobs. Avoid vague verbs ("consider", "may want to"). Each
recommendation should be something an SRE can act on this week.

## Pitfalls

Common ways the remediation goes wrong: setting requests too low and hitting
OOM, choosing spot for a stateful workload, downsizing a Postgres PVC, etc.

## References

Plain text references. No Markdown links — they don't help retrieval and they
clutter the chunks.
```

## Authoring notes

- Keep H2 sections between 50–512 approximate tokens. The chunker will
  sub-split larger sections on paragraph boundaries and merge tiny sections
  into the next sibling, but the result will be cleaner if each section is
  already inside the cap.
- One topic per file. Don't combine "rightsizing" and "spot instances" —
  retrieval works better when files are narrowly scoped.
- The LLM is told never to invent figures. Cite real numbers in the text so
  the model can quote them.
