# Ollama setup

After `docker compose up -d`, pull the default model:

```bash
docker exec -it $(docker compose ps -q ollama) ollama pull qwen2.5:7b-instruct
```

## Model selection guide

| Model | Size | RAM/VRAM | Quality | When to use |
|---|---|---|---|---|
| `qwen2.5:7b-instruct` | ~5 GB | 8 GB | Good | Default. Runs on most laptops. |
| `qwen2.5:14b-instruct` | ~9 GB | 16 GB | Better | Better analysis on bigger laptops / desktops. |
| `qwen2.5:32b-instruct` | ~20 GB | 24 GB | Great | Workstations with a 4090 or M3 Max 64 GB. |
| `llama3.3:70b` | ~40 GB | 48 GB | Best | Servers / multi-GPU. |

Swap the model from the **Settings** page in the UI once it's pulled.

## GPU acceleration

NVIDIA on Linux: uncomment the `deploy.resources` block in `docker-compose.yml` and install the NVIDIA Container Toolkit on the host.

Apple Silicon: Ollama uses Metal automatically when run natively on macOS, but inside Docker Desktop on macOS you'll get CPU-only. For best Mac performance, install Ollama natively (`brew install ollama`), comment out the `ollama` service in compose, and set `OLLAMA_HOST=http://host.docker.internal:11434` in `.env`.
