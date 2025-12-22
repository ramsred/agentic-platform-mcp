"""
Multi MCP Host (SSE) - connects to multiple FastMCP servers via SSE transport,
performs MCP initialization handshake, lists tools, and calls tools.

Usage:
  python -m src.host.multi_mcp_host

Commands:
  tools
  call <server> <tool> '<json_args>'
  quit
"""

from __future__ import annotations

import json
import shlex
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from urllib.parse import urlparse


class MCPProtocolError(RuntimeError):
    pass


def _now_ms() -> int:
    return int(time.time() * 1000)


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"

def _join_url(base_or_origin: str, path: str) -> str:
    base = base_or_origin.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


@dataclass
class MCPEvent:
    event: str
    data: str


class SSEReader(threading.Thread):
    """
    Minimal SSE client that parses event/data lines.
    Calls callbacks on event reception.
    """

    def __init__(self, url: str, on_event, name: str = "SSEReader"):
        super().__init__(daemon=True, name=name)
        self.url = url
        self.on_event = on_event
        self._stop = threading.Event()
        self._session = requests.Session()

    def stop(self):
        self._stop.set()
        try:
            self._session.close()
        except Exception:
            pass

    def run(self):
        headers = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        }
        try:
            with self._session.get(self.url, headers=headers, stream=True, timeout=(5, None)) as resp:
                resp.raise_for_status()

                event_type = "message"
                data_lines = []

                for raw in resp.iter_lines(decode_unicode=True):
                    if self._stop.is_set():
                        return
                    if raw is None:
                        continue

                    line = raw.strip("\r")
                    # blank line => dispatch event
                    if line == "":
                        if data_lines:
                            data = "\n".join(data_lines)
                            ev = MCPEvent(event=event_type, data=data)
                            try:
                                self.on_event(ev)
                            except Exception:
                                # don't kill the reader thread on callback errors
                                pass
                        # reset
                        event_type = "message"
                        data_lines = []
                        continue

                    if line.startswith(":"):
                        # comment / keepalive ping
                        continue
                    if line.startswith("event:"):
                        event_type = line.split(":", 1)[1].strip()
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line.split(":", 1)[1].lstrip())
                        continue
        except Exception as e:
            # Reader dying is fatal for request/response because MCP replies arrive on SSE
            try:
                self.on_event(MCPEvent(event="__error__", data=str(e)))
            except Exception:
                pass


class MCPSSESession:
    def __init__(self, name: str, sse_url: str):
        self.name = name
        self.sse_url = sse_url.rstrip("/")

        self.messages_url: Optional[str] = None

        self._reader: Optional[SSEReader] = None
        self._lock = threading.Lock()
        self._inbox: Dict[int, Dict[str, Any]] = {}
        self._errors: list[str] = []

        self._http = requests.Session()

    def connect(self):
        """
        1) Start SSE reader
        2) Wait until we receive the "endpoint" event and build messages_url
        3) Perform MCP handshake (initialize + notifications/initialized)
        """
        def on_event(ev: MCPEvent):
            if ev.event == "__error__":
                with self._lock:
                    self._errors.append(ev.data)
                return

            if ev.event == "endpoint":
                rel = ev.data.strip()
                self.messages_url = _join_url(_origin(self.sse_url), rel)
                return

            if ev.event == "message":
                # JSON-RPC response/event
                try:
                    msg = json.loads(ev.data)
                except Exception:
                    return

                # store by id if present
                if isinstance(msg, dict) and "id" in msg:
                    try:
                        rid = int(msg["id"])
                    except Exception:
                        return
                    with self._lock:
                        self._inbox[rid] = msg

        self._reader = SSEReader(self.sse_url, on_event, name=f"SSEReader[{self.name}]")
        self._reader.start()

        # wait for messages_url from "endpoint"
        deadline = time.time() + 10
        while self.messages_url is None and time.time() < deadline:
            time.sleep(0.05)

        if self.messages_url is None:
            raise TimeoutError(f"[{self.name}] did not receive endpoint event from {self.sse_url}")

        print(f"  -> messages_url: {self.messages_url}")

        # IMPORTANT: do MCP initialization handshake BEFORE tools/list or tools/call
        self.initialize_handshake()

    def close(self):
        try:
            if self._reader:
                self._reader.stop()
        finally:
            try:
                self._http.close()
            except Exception:
                pass

    def rpc(self, method: str, params: Optional[dict] = None) -> int:
        if self.messages_url is None:
            raise MCPProtocolError(f"[{self.name}] Not connected (messages_url missing).")

        rid = _now_ms()
        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
        }
        # MCP expects params to exist for most methods, even if empty {}
        payload["params"] = params if params is not None else {}

        r = self._http.post(
            self.messages_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        # For MCP SSE, server replies on SSE stream; POST usually returns 202
        if r.status_code not in (200, 202):
            raise MCPProtocolError(f"[{self.name}] POST {method} failed: {r.status_code} {r.text}")
        return rid

    def wait_for_id(self, rpc_id: int, timeout_s: float = 10) -> Dict[str, Any]:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            with self._lock:
                if rpc_id in self._inbox:
                    return self._inbox.pop(rpc_id)
                if self._errors:
                    # surface latest error
                    err = self._errors[-1]
                    raise MCPProtocolError(f"[{self.name}] SSE reader error: {err}")
            time.sleep(0.05)
        raise TimeoutError(f"[{self.name}] Timed out waiting for response id={rpc_id}")

    def initialize_handshake(self):
        """
        MCP handshake:
          1) initialize
          2) wait for initialize result
          3) notifications/initialized
        """
        init_id = self.rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {},
                },
                "clientInfo": {
                    "name": "agentic-platform-mcp",
                    "version": "0.1.0",
                },
            },
        )
        init_resp = self.wait_for_id(init_id, timeout_s=10)
        if "error" in init_resp:
            raise MCPProtocolError(f"[{self.name}] initialize failed: {init_resp}")

        # Must notify initialized (no response expected, but we send it anyway)
        self.rpc("notifications/initialized", {})

    # ---- convenience wrappers ----

    def list_tools(self) -> Dict[str, Any]:
        rid = self.rpc("tools/list", {})
        return self.wait_for_id(rid, timeout_s=10)

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        rid = self.rpc("tools/call", {"name": tool_name, "arguments": arguments})
        return self.wait_for_id(rid, timeout_s=20)


class MultiMCPHost:
    def __init__(self, servers: Dict[str, str]):
        self.sessions: Dict[str, MCPSSESession] = {
            name: MCPSSESession(name, url) for name, url in servers.items()
        }

    def connect_all(self):
        for name, sess in self.sessions.items():
            print(f"Connecting to {name} ({sess.sse_url})...")
            sess.connect()

    def close(self):
        for sess in self.sessions.values():
            sess.close()

    def tools_all(self) -> Dict[str, Any]:
        out = {}
        for name, sess in self.sessions.items():
            try:
                out[name] = sess.list_tools()
            except Exception as e:
                out[name] = {"error": str(e)}
        return out

    def call(self, server: str, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if server not in self.sessions:
            raise KeyError(f"Unknown server '{server}'. Available: {list(self.sessions.keys())}")
        return self.sessions[server].call_tool(tool, args)


def main():
    # docker-compose mapped ports (your current setup)
    servers = {
        "mcp-sharepoint": "http://localhost:5101/sse",
        "mcp-servicenow": "http://localhost:5102/sse",
    }

    host = MultiMCPHost(servers)
    try:
        host.connect_all()

        print("\nCommands:")
        print("  tools")
        print("  call <server> <tool> '<json_args>'")
        print("  quit\n")

        while True:
            try:
                line = input("mcp> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not line:
                continue
            if line in ("quit", "exit"):
                break
            if line == "tools":
                print(json.dumps(host.tools_all(), indent=2))
                continue

            if line.startswith("call "):
                # Use shlex so quoted JSON stays intact
                parts = shlex.split(line)
                # parts: ["call", "<server>", "<tool>", "<json_args>"]
                if len(parts) != 4:
                    print("Usage: call <server> <tool> '<json_args>'")
                    continue
                _, server, tool, json_args = parts
                try:
                    args = json.loads(json_args)
                    if not isinstance(args, dict):
                        raise ValueError("args must be a JSON object")
                except Exception as e:
                    print(f"Invalid JSON args: {e}")
                    continue

                resp = host.call(server, tool, args)
                print(json.dumps(resp, indent=2))
                continue

            print("Unknown command. Try: tools | call ... | quit")
    finally:
        host.close()


if __name__ == "__main__":
    main()