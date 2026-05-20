# Screenshots

The repo's main `README.md` and several `docs/` pages embed screenshots from this directory. Filenames are fixed — if you re-capture a screen, save with the same name and the references resolve automatically.

| File | What it shows |
|---|---|
| `01-dashboard.png` | Dashboard with at least one connected environment card. |
| `02-environments.png` | Environments list (table view). |
| `03-reports.png` | Reports / history page with trend chart and scan table. |
| `04-settings.png` | Settings page (Ollama model list, prompt template, RAG corpus). |
| `05-cost-analysis.png` | The Cost Analysis report — full page or at least header + at-a-glance + namespace bar + executive summary + first finding. This is the README hero shot. |

Recommended capture settings:

- Window width ~1440px. Desktop-only by design.
- Dark mode (the product's default). Light-mode shots will look out of place.
- Use a real completed scan with idle workloads visible — populated dials, populated tables, severity-colored finding borders. The trivial-scale dev scan with 2–3 idle workloads is fine.
- PNG, not JPEG. The interface has a lot of fine-grained text and table lines that JPEG compresses poorly.

If you change a filename, update the matching `![alt](docs/screenshots/...)` reference in the root `README.md`.
