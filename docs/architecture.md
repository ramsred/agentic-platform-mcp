# Architecture

## Components
### 1) Host
The outer application boundary (CLI/API/UI). Responsibilities:
- Accept user requests
- Manage sessions, state, and security controls
- Provide the LLM with curated context (resources) and tool schemas
- Mediate approvals (human-in-the-loop) and enforce policies

### 2) Agent Orchestrator
A **control loop** (LangGraph later) that:
- Maintains state (messages, tool results, intermediate decisions)
- Calls the LLM for planning/tool selection
- Executes tools via MCP clients (with gating)
- Synthesizes final response

**Mental model:**  
LLM = “reasoning”  
Agent = “state + loop + enforcement + tool execution”

### 3) LLM (local)
Used for:
- selecting tools + producing arguments
- synthesizing outputs from tool results/resources
- optional: routing (later), and summarization

Initial plan: local open-source LLM (7B/8B) that supports tool/function calling.

### 4) MCP Client(s)
Protocol handler(s) in the host. 1:1 relationship:
- One MCP client session per MCP server
- Handles handshake, capability discovery (tools/resources/prompts), and calls

### 5) MCP Server(s)
Tool/data providers:
- Tools: actions (may have side effects)
- Resources: read-only contextual data
- Prompts: reusable workflows/templates

Transport: **SSE only** (per current build target), later upgrade to Streamable HTTP.

---

## Request lifecycle (end-to-end)
1. User sends query to Host (CLI/API).
2. Host/Agent calls LLM with:
   - user message
   - available MCP tool schemas
   - (optional) selected resources/prompts
3. LLM returns either:
   - direct answer, or
   - tool call(s) with name + arguments
4. Host enforces policy:
   - approval gate (human-in-loop)
   - allow/deny tool calls
   - roots/scope restrictions (server-side enforcement)
5. MCP Client sends JSON-RPC request to MCP Server.
6. MCP Server executes and returns result (and optionally notifications/progress).
7. Host adds tool results back into message history.
8. Host calls LLM again for grounded final response.
9. Host returns final answer to user.

---

## Security & Controls (baseline)
- Tool approval prompts (human in loop)
- PII logging policy checks before tool execution
- Roots-like scope enforcement for filesystem/document access
- Strict tool schema validation
- Container sandboxing for servers (Docker → K3s)

---

## Observability (baseline)
- OpenTelemetry tracing across:
  - host request
  - LLM calls
  - tool calls per server
- Metrics: latency, tool usage rate, errors, token usage
- Logs: structured JSON logs with correlation IDs
