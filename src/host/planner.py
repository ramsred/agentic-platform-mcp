import json
from typing import Any, Dict, List


SYSTEM_RULES = """You are a tool-routing planner inside an agentic platform.

Hard rules:
- You MUST respond with ONLY valid JSON (no markdown, no extra text).
- You must choose exactly ONE of:
  1) {"type":"call_tool","server":"<server>","tool":"<tool>","args":{...}}
  2) {"type":"final_answer","answer":"...","needs_more_info":true}

Tool use rules:
- You may ONLY choose tools that appear in the provided TOOL_CATALOG.
- Tool arguments MUST match the tool's inputSchema (keys and types).
- If you cannot answer without tool output, choose final_answer with needs_more_info=true.
- Do NOT hallucinate facts. Do NOT invent tools. Do NOT guess IDs. Use search tools first when needed.
"""

def build_tool_catalog(servers_to_tools: Dict[str, Any]) -> str:
    """
    servers_to_tools:
      { server_name: {"tools":[...]} } where tools come from tools/list.
    """
    # Keep it compact but complete enough for argument correctness.
    catalog = {}
    for server, resp in servers_to_tools.items():
        tools = resp.get("result", {}).get("tools", [])
        catalog[server] = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": t.get("inputSchema", {}),
            }
            for t in tools
        ]
    return json.dumps(catalog, ensure_ascii=False)


def build_planner_messages(user_query: str, servers_to_tools: Dict[str, Any]) -> List[Dict[str, str]]:
    catalog_json = build_tool_catalog(servers_to_tools)

    user_msg = f"""USER_QUERY:
{user_query}

TOOL_CATALOG (JSON):
{catalog_json}

Return ONLY one JSON object following the schema.
"""

    return [
        {"role": "system", "content": SYSTEM_RULES},
        {"role": "user", "content": user_msg},
    ]