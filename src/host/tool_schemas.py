from __future__ import annotations
from typing import Dict, Tuple, Type
from pydantic import BaseModel

from .typed_models import (
    SharePointSearchResult, SharePointDoc,
    ServiceNowSearchResult, ServiceNowTicket,
    PolicyKBSearchResult, PolicyDoc,
)

ToolKey = Tuple[str, str]  # (server_name, tool_name)

TOOL_OUTPUT_MODELS: Dict[ToolKey, Type[BaseModel]] = {
    ("mcp-sharepoint", "search_sharepoint"): SharePointSearchResult,
    ("mcp-sharepoint", "fetch_sharepoint_doc"): SharePointDoc,

    ("mcp-servicenow", "search_servicenow_tickets"): ServiceNowSearchResult,
    ("mcp-servicenow", "get_ticket"): ServiceNowTicket,

    # If your mcp-policy-kb has these tools; adjust names as needed:
    ("mcp-policy-kb", "search_policies"): PolicyKBSearchResult,
    ("mcp-policy-kb", "get_policy"): PolicyDoc,
}