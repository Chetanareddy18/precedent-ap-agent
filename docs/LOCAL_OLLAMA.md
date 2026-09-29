# Running Precedent fully locally (no API keys)

Both Hindsight and the agent can run on [Ollama](https://ollama.com).

```bash
ollama pull qwen2.5:14b            # or llama3.1:8b on smaller machines

docker run -d --name hindsight -p 8888:8888 -p 9999:9999 \
  -e HINDSIGHT_API_LLM_PROVIDER=ollama \
  -e HINDSIGHT_API_LLM_BASE_URL=http://host.docker.internal:11434/v1 \
  -e HINDSIGHT_API_LLM_MODEL=qwen2.5:14b \
  -v hindsight-data:/home/hindsight/.pg0 \
  ghcr.io/vectorize-io/hindsight:latest
```

`.env`:

```
HINDSIGHT_BASE_URL=http://localhost:8888
HINDSIGHT_API_KEY=
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:14b
LLM_FALLBACK_MODEL=llama3:instruct
```

Local models are slower. Each retain runs fact extraction, so expect several seconds per invoice. The Hindsight UI at
http://localhost:9999 lets you browse the bank, memories, directives and mental models while the agent runs.
