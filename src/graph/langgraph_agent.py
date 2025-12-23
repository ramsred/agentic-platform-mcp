"""
LangGraph Agent (Option A - single tool call)

Deterministic safety-first graph:
  1) Policy gate (block unsafe input)
  2) Discover tools (live)
  3) Deterministic ID router (if ID present, bypass LLM planner)
  4) Otherwise: Planner (LLM -> strict JSON plan)
  5) Allowlist + schema validation
  6) Execute exactly one MCP tool call
  7) Typed parsing
  8) Optional grounded summarization (SAFE_SUMMARIZE=1 or user asks "summarize")
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, TypedDict

from langgraph.graph import StateGraph, END

from src.host.llm_client import LLMClient
from src.host.planner import build_planner_messages, build_tool_catalog
from src.host.validator import validate_plan, ValidationError

from src.host.safety import (
    policy_check_user_query,
    parse_strict_json_plan,
    enforce_tool_allowlist,
    PlanParseError,
    ToolNotAllowed,
)

from src.host.typed_parser import parse_typed_tool_output, ToolOutputParseError

from src.host.summarizer import (
    _to_source_text,
    build_summarizer_messages,
    validate_grounded_summary,
    GroundingError,
)

from src.host.multi_mcp_host import MultiMCPHost


class AgentState(TypedDict, total=False):
    user_query: str

    tools_payload: Dict[str, Any]
    allowlist: Dict[str, set[str]]
    catalog_dict: Dict[str, Any]

    raw_plan: Any
    plan: Dict[str, Any]
    server: str
    tool: str
    args: Dict[str, Any]

    raw_tool_result: Dict[str, Any]
    typed: Dict[str, Any]

    summary: Dict[str, Any]
    output: Dict[str, Any]

    blocked: bool
    reason: str


def _wants_summary(q: str) -> bool:
    return "summarize" in q.lower()


def _summarize_enabled() -> bool:
    return os.getenv("SAFE_SUMMARIZE", "0").strip() == "1"


def _deterministic_plan_from_ids(user_query: str) -> Dict[str, Any] | None:
    """
    If user_query contains a concrete ID, deterministically pick the correct fetch tool.
    This prevents LLM mis-routing (e.g., sp-001 accidentally treated as a policy_id).
    """
    q = user_query.strip()

    sp = re.search(r"\b(sp-\d+)\b", q, re.IGNORECASE)
    pol = re.search(r"\b(policy-\d+)\b", q, re.IGNORECASE)
    sn = re.search(r"\b((?:INC|RITM|TASK|CHG)\d+)\b", q, re.IGNORECASE)

    if sp:
        doc_id = sp.group(1)
        return {
            "type": "call_tool",
            "server": "mcp-sharepoint",
            "tool": "fetch_sharepoint_doc",
            "args": {"doc_id": doc_id},
        }

    if pol:
        policy_id = pol.group(1)
        return {
            "type": "call_tool",
            "server": "mcp-policy-kb",
            "tool": "fetch_policy_entry",
            "args": {"policy_id": policy_id},
        }

    if sn:
        ticket_id = sn.group(1)
        return {
            "type": "call_tool",
            "server": "mcp-servicenow",
            "tool": "get_ticket",
            "args": {"ticket_id": ticket_id},
        }

    return None


# -------------------------
# Nodes
# -------------------------

def node_policy_gate(state: AgentState) -> AgentState:
    q = state["user_query"]
    ok, reason = policy_check_user_query(q)
    if not ok:
        state["blocked"] = True
        state["reason"] = reason
        state["output"] = {"type": "blocked", "reason": reason}
    return state


def node_discover_tools(state: AgentState, host: MultiMCPHost) -> AgentState:
    tools_payload = host.tools_all()
    ok_tools = {srv: resp for srv, resp in tools_payload.items()
                if isinstance(resp, dict) and "result" in resp}

    allowlist: Dict[str, set[str]] = {}
    for srv, resp in ok_tools.items():
        tools = resp["result"].get("tools", [])
        allowlist[srv] = {t["name"] for t in tools if isinstance(t, dict) and "name" in t}

    catalog_dict = json.loads(build_tool_catalog(ok_tools))

    state["tools_payload"] = ok_tools
    state["allowlist"] = allowlist
    state["catalog_dict"] = catalog_dict
    return state


def node_plan(state: AgentState) -> AgentState:
    """
    Deterministic first: if query contains an ID, bypass LLM and force correct fetch tool.
    Otherwise, use the LLM planner.
    """
    if state.get("blocked"):
        return state

    q = state["user_query"]

    forced = _deterministic_plan_from_ids(q)
    if forced is not None:
        state["raw_plan"] = {"forced": True, "plan": forced}
        state["plan"] = forced
        return state

    llm = LLMClient()
    ok_tools = state["tools_payload"]

    messages = build_planner_messages(q, ok_tools)
    raw_plan = llm.chat_json(messages=messages, max_tokens=256, temperature=0.0)
    state["raw_plan"] = raw_plan

    try:
        plan = parse_strict_json_plan(raw_plan)
    except PlanParseError as e:
        state["blocked"] = True
        state["reason"] = f"Planner output rejected: {str(e)}"
        state["output"] = {"type": "blocked", "reason": state["reason"], "raw": str(raw_plan)[:400]}
        return state

    state["plan"] = plan
    return state


def node_validate_and_select(state: AgentState) -> AgentState:
    if state.get("blocked"):
        return state

    plan = state["plan"]
    catalog_dict = state["catalog_dict"]
    allowlist = state["allowlist"]

    try:
        server, tool, args = validate_plan(plan, catalog_dict)
    except ValidationError as e:
        state["blocked"] = True
        state["reason"] = f"Plan validation failed: {str(e)}"
        state["output"] = {"type": "blocked", "reason": state["reason"], "plan": plan}
        return state

    try:
        enforce_tool_allowlist(server, tool, allowlist)
    except ToolNotAllowed as e:
        state["blocked"] = True
        state["reason"] = str(e)
        state["output"] = {"type": "blocked", "reason": state["reason"], "plan": plan}
        return state

    state["server"] = server
    state["tool"] = tool
    state["args"] = args
    return state


def node_call_tool(state: AgentState, host: MultiMCPHost) -> AgentState:
    if state.get("blocked"):
        return state

    server = state["server"]
    tool = state["tool"]
    args = state["args"]

    raw = host.call(server, tool, args)
    state["raw_tool_result"] = raw

    try:
        typed_obj = parse_typed_tool_output(server, tool, raw)
        state["typed"] = typed_obj.model_dump()
    except ToolOutputParseError as e:
        state["output"] = {
            "type": "tool_result",
            "plan": state["plan"],
            "note": f"Typed parsing blocked: {str(e)}",
            "raw": raw,
        }
        return state

    state["output"] = {
        "type": "tool_result",
        "plan": state["plan"],
        "typed": state["typed"],
        "raw": raw,
    }
    return state


def node_grounded_summarize(state: AgentState) -> AgentState:
    if state.get("blocked"):
        return state

    # Only summarize if enabled or requested
    wants = _wants_summary(state["user_query"])
    enabled = _summarize_enabled()
    if not (enabled or wants):
        return state

    # Prefer typed payload as the source (schema-validated)
    typed = state.get("typed")
    if not typed:
        return state

    # Heuristic: don't summarize NOT_FOUND payloads
    if isinstance(typed, dict) and typed.get("content") == "NOT_FOUND":
        out = state.get("output", {})
        out["note"] = "Summary skipped: content is NOT_FOUND."
        state["output"] = out
        return state

    # Heuristic: for search tools, summarize only if the user explicitly asked
    tool = state.get("tool", "")
    if tool.startswith("search_") and not wants:
        out = state.get("output", {})
        out["note"] = "Summary skipped: search results (set SAFE_SUMMARIZE=1 + ask 'summarize' if needed)."
        state["output"] = out
        return state

    llm = LLMClient()
    source_text = json.dumps(typed, ensure_ascii=False, indent=2)

    msgs = build_summarizer_messages(source_text)
    raw = llm.chat_json(messages=msgs, max_tokens=512, temperature=0.0)

    try:
        summary = parse_strict_json_plan(raw)
        validate_grounded_summary(summary, source_text)

        state["summary"] = summary
        out = state.get("output", {})
        out["type"] = "tool_result_with_summary"
        out["summary"] = summary
        state["output"] = out

    except (PlanParseError, GroundingError) as e:
        out = state.get("output", {})
        out["note"] = f"Summary blocked (grounding failed): {str(e)}"
        state["output"] = out

    return state


# -------------------------
# Routers
# -------------------------

def route_after_policy(state: AgentState) -> str:
    return END if state.get("blocked") else "discover_tools"


def route_after_plan(state: AgentState) -> str:
    return END if state.get("blocked") else "validate_and_select"


def route_after_validate(state: AgentState) -> str:
    return END if state.get("blocked") else "call_tool"


# -------------------------
# Build graph
# -------------------------

def build_graph(host: MultiMCPHost):
    g = StateGraph(AgentState)

    g.add_node("policy_gate", node_policy_gate)
    g.add_node("discover_tools", lambda s: node_discover_tools(s, host))
    g.add_node("plan", node_plan)
    g.add_node("validate_and_select", node_validate_and_select)
    g.add_node("call_tool", lambda s: node_call_tool(s, host))
    g.add_node("grounded_summarize", node_grounded_summarize)

    g.set_entry_point("policy_gate")

    g.add_conditional_edges("policy_gate", route_after_policy, {
        END: END,
        "discover_tools": "discover_tools",
    })

    g.add_edge("discover_tools", "plan")

    g.add_conditional_edges("plan", route_after_plan, {
        END: END,
        "validate_and_select": "validate_and_select",
    })

    g.add_conditional_edges("validate_and_select", route_after_validate, {
        END: END,
        "call_tool": "call_tool",
    })

    g.add_edge("call_tool", "grounded_summarize")
    g.add_edge("grounded_summarize", END)

    return g.compile()


def run_once(host: MultiMCPHost, user_query: str) -> Dict[str, Any]:
    app = build_graph(host)
    state: AgentState = {"user_query": user_query}
    final_state = app.invoke(state)
    return final_state.get("output", {"type": "error", "reason": "no output"})


def main():
    if len(sys.argv) < 2:
        print('Usage: python -m src.graph.langgraph_agent "your question"')
        raise SystemExit(2)

    user_query = " ".join(sys.argv[1:]).strip().strip('"').strip("'")

    servers = {
        "mcp-sharepoint": os.getenv("MCP_SP_URL", "http://localhost:5101/sse"),
        "mcp-servicenow": os.getenv("MCP_SN_URL", "http://localhost:5102/sse"),
        "mcp-policy-kb": os.getenv("MCP_KB_URL", "http://localhost:5103/sse"),
    }
    servers = {k: v for k, v in servers.items() if v}

    host = MultiMCPHost(servers)
    try:
        host.connect_all()
        out = run_once(host, user_query)
        print(json.dumps(out, indent=2))
    finally:
        host.close()


if __name__ == "__main__":
    main()