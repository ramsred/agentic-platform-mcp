import os
from fastmcp import FastMCP

mcp = FastMCP(os.getenv("MCP_NAME", "mcp-policy-kb"))

POLICIES = {
    "PII Logging": {
        "id": "policy-001",
        "content": (
            "# PII Logging Policy\n"
            "- Never log secrets\n"
            "- Mask emails and identifiers\n"
            "- Hash user identifiers\n"
        )
    }
}

@mcp.tool()
def search_policies(query: str, top_k: int = 5) -> dict:
    results = [
        {"policy_id": v["id"], "title": k}
        for k, v in POLICIES.items()
        if query.lower() in k.lower()
    ]
    return {"query": query, "results": results[:top_k]}

@mcp.tool()
def get_policy(policy_id: str) -> dict:
    for v in POLICIES.values():
        if v["id"] == policy_id:
            return {"policy_id": policy_id, "content": v["content"]}
    return {"policy_id": policy_id, "content": "NOT_FOUND"}

if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8000)