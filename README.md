
![CI](https://github.com/ramsred/agentic-platform-mcp/actions/workflows/ci.yml/badge.svg)

# agentic-platform-mcp

A production-grade **agentic AI platform** built on the **Model Context Protocol (MCP)**:
- Multi-server MCP host (SharePoint / ServiceNow / KB + more later)
- Full MCP capabilities: **Tools, Resources, Prompts** (and later Sampling/Elicitation where needed)
- Local open-source LLM inference (vLLM or alternative) with tool/function calling
- **LangGraph** orchestration layer
- Retrieval routing layer (dual-encoder + cross-encoder rerank)
- Kubernetes deployment on **K3s (DGX Spark)**
- Observability: OpenTelemetry traces/metrics/logs + dashboards

## Why this exists
Most “agent demos” break when you add:
- multiple tool providers,
- policy controls (PII, permissions),
- scaling/deployment,
- and monitoring.

This repo is designed as a **staff-level system**: modular, secure-by-default, and deployable.

## High-level architecture (MCP-centric)
User → Host API/UI → Agent Orchestrator (LangGraph) → MCP Clients (1 per server) → MCP Servers  
The LLM is the reasoning engine; the agent is the control loop + state manager.

## Scope (initial)
### MCP Servers (phase 1)
- `mcp-kb`: internal knowledge base (policies, runbooks) via resources + search tool
- `mcp-sharepoint`: document retrieval + metadata resources + search tool
- `mcp-servicenow`: incident/query tools + read-only resources for tickets

### Host + Agent (phase 1)
- MultiServer MCP host with dynamic discovery
- Tool approval + policy gating (PII logging checks)
- Conversation loop (CLI first; API later)

## Quickstart (will be filled as we build)
- Local dev: Python + uv
- Run servers (SSE) and host (CLI)
- Deploy to K3s

## Repo map
- `src/host/` — multi-MCP host + agent loop + LLM adapter
- `src/servers/` — MCP servers (KB/SharePoint/ServiceNow)
- `src/common/` — shared auth, schemas, policies, utilities
- `deploy/` — Docker + K3s manifests/helm
- `observability/` — OpenTelemetry + dashboards
- `docs/` — architecture, decisions, roadmap

## Roadmap
See `docs/roadmap-14-days.md`.

## License
Apache-2.0 (recommended for industry-friendly reuse).# agentic-platform-mcp
A production-grade, open-source agentic AI platform built on Model Context Protocol (MCP). Supports multi-MCP servers, local LLM inference, agent orchestration (LangGraph), retrieval-augmented generation, Kubernetes deployment, and full observability.
