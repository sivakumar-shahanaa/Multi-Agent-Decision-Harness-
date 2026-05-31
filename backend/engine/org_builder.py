"""AI org-builder (ROADMAP §9.4): turn a prompt into a panel of agents.

"a biotech seed investment committee" -> 3-5 distinct, weighted personas. Uses the
provider-routed LLM; falls back to a generic deterministic panel with no creds so
the route always returns a usable org.
"""
from __future__ import annotations

from ..schemas import AgentCreate, Provider
from .llm import complete_json, resolve_backend
from .prompts import ORG_BUILDER_PROMPT, ORG_BUILDER_SCHEMA

_DEFAULT_MODEL = "claude-sonnet-4-6"


def _to_agents(raw: list[dict]) -> list[AgentCreate]:
    total = sum(max(0.0, float(a.get("weight", 1))) for a in raw) or 1.0
    agents = []
    for i, a in enumerate(raw[:6]):
        agents.append(AgentCreate(
            name=str(a.get("name", f"Panelist {i+1}")),
            role=str(a.get("role", "Panelist")),
            system_prompt=str(a.get("system_prompt", "")),
            weight=round(max(0.0, float(a.get("weight", 1))) / total, 3),
            provider=Provider.anthropic, position=i, tools=["research"],
        ))
    return agents


def _fallback_team(prompt: str) -> dict:
    base = [
        ("The Optimist", "Opportunity-first evaluator",
         "You are an opportunity-first evaluator. You look for upside, momentum, and "
         "what could go right. You argue for action when the potential is large."),
        ("The Skeptic", "Risk & evidence evaluator",
         "You are a hard-nosed skeptic. You demand evidence, probe weak assumptions, "
         "and default to NO unless the case is strong. You are the dissenting voice."),
        ("The Pragmatist", "Execution & feasibility evaluator",
         "You judge feasibility and execution: can this actually be done, by whom, with "
         "what resources? You favor concrete plans over vision."),
    ]
    raw = [{"name": n, "role": r, "system_prompt": f"{sp} Context: {prompt}", "weight": 1}
           for n, r, sp in base]
    return {"org_name": f"Panel: {prompt[:48]}", "description": f"Auto-generated for: {prompt}",
            "agents": _to_agents(raw)}


async def generate_org_agents(prompt: str) -> dict:
    """Returns {org_name, description, agents: [AgentCreate]}."""
    backend = resolve_backend("anthropic")
    if backend is None:
        return _fallback_team(prompt)
    try:
        d = await complete_json(backend, _DEFAULT_MODEL, ORG_BUILDER_PROMPT, prompt,
                                ORG_BUILDER_SCHEMA)
        agents = _to_agents(d.get("agents") or [])
        if not agents:
            return _fallback_team(prompt)
        return {"org_name": str(d.get("org_name", f"Panel: {prompt[:48]}")),
                "description": str(d.get("description", "")), "agents": agents}
    except Exception:
        return _fallback_team(prompt)
