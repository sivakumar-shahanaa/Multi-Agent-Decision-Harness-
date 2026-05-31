"""Tool executor for agent `tool_call`s (ROADMAP §7.5).

Hour-1 stubs so the tool_call → tool_result loop is REAL end to end. WS-A swaps
each stub for an MCP server call (research/web-search, company_data, the W&B MCP).
"""
from __future__ import annotations

TOOLS = ["research", "company_data"]


async def execute_tool(tool: str, args: dict) -> dict:
    if tool == "research":
        return {"query": args.get("query", ""),
                "summary": "[research stub] connect a web-search MCP here.",
                "sources": []}
    if tool == "company_data":
        return {"metric": args.get("metric"), "value": None,
                "note": "[company_data stub] connect the company-data MCP here."}
    return {"error": f"unknown tool '{tool}'"}
