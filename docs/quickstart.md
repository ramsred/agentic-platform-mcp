# Quickstart (Phase 0)

This repo runs a **Multi-MCP Host** that connects to multiple MCP servers (SSE transport) and can:
- list tools
- call tools
- run a single-step `ask` flow using a local LLM planner (vLLM OpenAI-compatible)

## Prereqs

- Docker + Docker Compose (v2)
- If running the `llm` service with GPU:
  - NVIDIA drivers + NVIDIA Container Toolkit installed
- `curl` installed

> Note: Compose v2 ignores `version:` in docker-compose.yml (safe to remove).

---

## 1) Start everything

From repo root:

```bash
docker compose up -d --build
docker compose ps


2) Verify LLM health (vLLM)
curl -s http://localhost:8008/v1/models | jq
You should see the configured model id.

Test chat:
curl -s http://localhost:8008/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "messages": [{"role":"user","content":"Reply with only the number: 12*17"}],
    "max_tokens": 20
  }' | jq -r '.choices[0].message.content'


  3) Run the host (local dev mode)

If you run host locally (not inside compose), set:
export LLM_BASE_URL=http://localhost:8008/v1
export LLM_MODEL=Qwen/Qwen2.5-7B-Instruct

export MCP_SP_URL=http://localhost:5101/sse
export MCP_SN_URL=http://localhost:5102/sse
export MCP_KB_URL=http://localhost:5103/sse

Then:
python -m src.host.multi_mcp_host

4) Try the CLI
List tools

mcp> tools

Direct tool call
mcp> call mcp-sharepoint search_sharepoint '{"query":"PII Logging","top_k":5}'

Single-step ask
mcp> ask "Find the PII Logging policy"
mcp> ask "Fetch policy sp-001"
mcp> ask "Summarize policy sp-001"

Summarization is enabled if SAFE_SUMMARIZE=1

5) Common pitfalls

LLM DNS failure: Temporary failure in name resolution

This happens when LLM_BASE_URL points to http://llm:8000/v1 but you are running host locally.

Fix:export LLM_BASE_URL=http://localhost:8008/v1

Model files accidentally committed

Never commit models/ to Git. We ignore it in .gitignore.

Shutdown
docker compose down
To remove volumes too:
docker compose down -v