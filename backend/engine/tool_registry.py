"""Per-agent tool registry (ROADMAP §7.5) — finally WIRES `agent.tools`.

Each tool is a `ToolSpec` (name, description, input_schema, kind, async handler).
An agent may only call tools in its allowlist (`agent.tools`, plus `use_skill` when
it has skills). The agent's prompt is built from `manifest_for(agent)` so the model
knows exactly which tools it has and how to call them — today it's told "call a tool
you have access to" but never which. Dispatch (in tools.py) validates against this
allowlist and routes by `kind`.

Builtins (web research + skills) register synchronously. Live MCP tools are added
asynchronously by mcp_manager.ensure_mcp_registered() at the start of a debate, so
this stays import-cheap and keyless-safe.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, Optional

from ..schemas import Agent
from . import skills as skills_mod
from . import web_research as web

ToolKind = Literal["builtin", "web", "skill", "mcp"]


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    kind: ToolKind
    handler: Callable[[dict, "ToolContext"], Awaitable[dict]]


@dataclass
class ToolContext:
    agent: Agent
    session_id: str = ""
    round: int = 0


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def effective_tool_names(self, agent: Agent) -> set[str]:
        """An agent's allowlist: its declared tools, plus use_skill if it has skills."""
        allowed = {t for t in (agent.tools or []) if t in self._tools}
        if getattr(agent, "skills", None) and "use_skill" in self._tools:
            allowed.add("use_skill")
        return allowed

    def allowed_for(self, agent: Agent) -> list[ToolSpec]:
        return [self._tools[n] for n in self.names() if n in self.effective_tool_names(agent)]

    def manifest_for(self, agent: Agent) -> str:
        """The `- name(args): description` lines injected into the agent's prompt."""
        lines = []
        for spec in self.allowed_for(agent):
            args = ", ".join((spec.input_schema.get("properties") or {}).keys())
            lines.append(f"- {spec.name}({args}): {spec.description}")
        return "\n".join(lines)


_WEB_TOOLS = [
    ("web_search", "Search the web for current evidence; returns titled results with snippets.",
     {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
      "required": ["query"]}, web.web_search),
    ("fetch_url", "Fetch and read one URL as text/markdown to ground a specific claim.",
     {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}, web.fetch_url),
    ("market_research", "Market size, funding, valuation and revenue signals for a company/market.",
     {"type": "object", "properties": {"company": {"type": "string"}}, "required": ["company"]},
     web.market_research),
    ("competitor_scan", "Find competitors and alternatives and how the subject differs.",
     {"type": "object", "properties": {"product": {"type": "string"}}, "required": ["product"]},
     web.competitor_scan),
    ("product_research", "Product traction, reviews, pricing and launch signals (Product Hunt angle).",
     {"type": "object", "properties": {"product": {"type": "string"}}, "required": ["product"]},
     web.product_research),
]


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for name, desc, schema, handler in _WEB_TOOLS:
        reg.register(ToolSpec(name=name, description=desc, input_schema=schema,
                              kind="web", handler=handler))
    # `research` is the legacy alias every persona declares — keep it working.
    reg.register(ToolSpec(name="research", description="Search the web for evidence (alias of web_search).",
                          input_schema={"type": "object", "properties": {"query": {"type": "string"}},
                                        "required": ["query"]},
                          kind="web", handler=web.web_search))
    reg.register(ToolSpec(name="use_skill",
                          description="Open the full text of one of your assigned skill rubrics on demand.",
                          input_schema={"type": "object", "properties": {"name": {"type": "string"}},
                                        "required": ["name"]},
                          kind="skill", handler=skills_mod.use_skill))
    return reg


_registry: Optional[ToolRegistry] = None


def default_registry() -> ToolRegistry:
    """The process-wide registry (builtins). MCP tools are added later, async."""
    global _registry
    if _registry is None:
        _registry = build_registry()
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None
