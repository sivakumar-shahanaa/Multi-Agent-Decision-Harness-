"""Live MCP client manager (ROADMAP §7.5 / WS-A).

Connects to external MCP servers declared in `mcp_servers.json` and surfaces their
tools through the SAME tool registry agents already use — so an agent calling
`weave_query` (or any exposed MCP tool) is indistinguishable, to the engine, from
calling `web_search`. Every MCP call flows through `execute_tool` and is Weave-traced.

100% optional and lazy: if `settings.mcp_enabled` is false (no config file) NOTHING
here runs and no MCP tools are registered — the council still works keyless. All
connection/exposure failures are logged and swallowed; a broken server never breaks
a debate.

Config shape (mcp_servers.json):
{
  "servers": [
    {
      "name": "wandb",
      "transport": "stdio",                 # or "http"
      "command": "uvx", "args": ["wandb-mcp-server"], "env": {"WANDB_API_KEY": "..."},
      # "url": "https://…/mcp"              # when transport == "http"
      "expose": [                            # which tools agents may call, and under what name
        {"as": "weave_query", "tool": "query_wandb_gql_tool",
         "description": "Query real W&B/Weave trace + run data as evidence.",
         "defaults": {"entity": "…", "project": "…"}}
      ]
    }
  ]
}
If "expose" is omitted, every tool the server lists is exposed under its own name.
"""
from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from typing import Optional

from ..config import get_settings

log = logging.getLogger("mcp")


def _result_to_dict(result) -> dict:
    """Flatten an MCP CallToolResult into a JSON-able dict."""
    parts: list[str] = []
    structured = getattr(result, "structuredContent", None)
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    out: dict = {"text": "\n".join(parts)} if parts else {}
    if structured:
        out["data"] = structured
    if getattr(result, "isError", False):
        out["error"] = out.get("text") or "mcp tool error"
    return out or {"text": ""}


class McpManager:
    def __init__(self) -> None:
        self._stack: Optional[AsyncExitStack] = None
        self._sessions: dict[str, object] = {}            # server name -> ClientSession
        # exposed tool name -> (server, real_tool, defaults, description, input_schema)
        self._exposed: dict[str, dict] = {}
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect_all(self, config_path) -> None:
        if self._connected:
            return
        self._connected = True  # mark first so we never retry a broken config in a loop
        try:
            cfg = json.loads(open(config_path, encoding="utf-8").read())
        except Exception as e:                              # noqa: BLE001
            log.warning("mcp: cannot read %s: %s", config_path, e)
            return
        self._stack = AsyncExitStack()
        for spec in cfg.get("servers", []):
            try:
                await self._connect_one(spec)
            except Exception as e:                          # noqa: BLE001
                log.warning("mcp: server %s failed to connect: %s", spec.get("name"), e)

    async def _connect_one(self, spec: dict) -> None:
        from mcp import ClientSession  # lazy: don't hard-require mcp at import time

        name = spec["name"]
        transport = spec.get("transport", "stdio")
        if transport == "http":
            from mcp.client.streamable_http import streamablehttp_client
            read, write, _ = await self._stack.enter_async_context(
                streamablehttp_client(spec["url"]))
        else:
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(command=spec["command"],
                                           args=spec.get("args", []),
                                           env=spec.get("env") or None)
            read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[name] = session

        listed = {t.name: t for t in (await session.list_tools()).tools}
        expose = spec.get("expose")
        if expose:
            for e in expose:
                real = e["tool"]
                tool = listed.get(real)
                self._exposed[e["as"]] = {
                    "server": name, "tool": real, "defaults": e.get("defaults") or {},
                    "description": e.get("description") or (getattr(tool, "description", "") or real),
                    "input_schema": getattr(tool, "inputSchema", {"type": "object"}),
                }
        else:
            for real, tool in listed.items():
                self._exposed[real] = {
                    "server": name, "tool": real, "defaults": {},
                    "description": getattr(tool, "description", "") or real,
                    "input_schema": getattr(tool, "inputSchema", {"type": "object"}),
                }
        log.info("mcp: connected %s, exposed %d tool(s)", name, len(expose or listed))

    async def call(self, exposed_name: str, args: dict) -> dict:
        meta = self._exposed.get(exposed_name)
        if not meta:
            return {"error": f"mcp tool '{exposed_name}' not connected"}
        session = self._sessions.get(meta["server"])
        if session is None:
            return {"error": f"mcp server '{meta['server']}' unavailable"}
        merged = {**meta["defaults"], **(args or {})}
        try:
            result = await session.call_tool(meta["tool"], arguments=merged)
            return _result_to_dict(result)
        except Exception as e:                              # noqa: BLE001
            return {"error": str(e), "tool": exposed_name}

    def exposed(self) -> dict[str, dict]:
        return self._exposed

    async def aclose(self) -> None:
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except Exception:                               # noqa: BLE001
                pass
        self._stack = None
        self._sessions.clear()
        self._exposed.clear()
        self._connected = False


_manager: Optional[McpManager] = None


def get_mcp_manager() -> McpManager:
    global _manager
    if _manager is None:
        _manager = McpManager()
    return _manager


async def ensure_mcp_registered(registry) -> None:
    """Connect MCP servers (once) and register their tools into `registry`.

    No-op unless settings.mcp_enabled. Idempotent and failure-tolerant.
    """
    s = get_settings()
    if not s.mcp_enabled:
        return
    mgr = get_mcp_manager()
    if mgr.connected:
        return
    from .tool_registry import ToolSpec

    await mgr.connect_all(str(s.mcp_config_file))

    def _make_handler(exposed_name: str):
        async def _handler(args: dict, ctx) -> dict:
            return await get_mcp_manager().call(exposed_name, args)
        return _handler

    for name, meta in mgr.exposed().items():
        registry.register(ToolSpec(
            name=name, description=meta["description"],
            input_schema=meta.get("input_schema") or {"type": "object"},
            kind="mcp", handler=_make_handler(name)))
