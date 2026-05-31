"""Tool executor for agent `tool_call`s (ROADMAP §7.5).

Routes a requested tool through the per-agent registry with a hard allowlist:
an agent can only call tools in `agent.tools` (plus `use_skill` when it has
skills). Real backends live in web_research.py / skills.py / mcp_manager.py and
each degrades to a deterministic mock with no key, so this loop is REAL end-to-end
even keyless. Every call is timeout-guarded and never raises — a failure comes
back as an `{"error": ...}` dict that still flows as a `tool_result` event.
"""
from __future__ import annotations

import asyncio

import weave

from ..config import get_settings
from .tool_registry import ToolContext, default_registry


@weave.op()
async def execute_tool(tool: str, args: dict, ctx: ToolContext) -> dict:
    reg = default_registry()
    if tool not in reg.effective_tool_names(ctx.agent):
        return {"error": f"tool '{tool}' is not in your allowlist",
                "allowed": sorted(reg.effective_tool_names(ctx.agent))}
    spec = reg.get(tool)
    if spec is None:
        return {"error": f"unknown tool '{tool}'"}
    try:
        return await asyncio.wait_for(spec.handler(args or {}, ctx),
                                      timeout=get_settings().tool_timeout_s)
    except asyncio.TimeoutError:
        return {"error": f"tool '{tool}' timed out", "tool": tool}
    except Exception as e:  # noqa: BLE001 — surface as a result, never crash the turn
        return {"error": str(e), "tool": tool}
