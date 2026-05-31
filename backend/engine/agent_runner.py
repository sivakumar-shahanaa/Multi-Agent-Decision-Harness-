"""One agent's turn (ROADMAP §7.3).

Real path: each agent is driven by an LLM (provider-routed in llm.py) and returns
structured JSON. In a deliberation turn the agent runs a BOUNDED ReAct loop — it may
call a tool from its allowlist, SEE the result in an evidence ledger, and then REVISE
its message and position before finalizing. That "fetch real evidence → change your
mind" loop is the marquee behavior; it's the difference between a panel and a pipeline.

If no model credentials are configured — or a call fails — we fall back to a
deterministic MOCK so the pipeline always completes (keyless dev/demo). Event
emission (tool_call/tool_result) is delegated to a callback passed in by debate.py,
so persistence + streaming stay centralized there.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional

import weave

from ..config import get_settings
from ..schemas import Agent, EventType, Position, Stance
from .budget import fit_to_budget
from .llm import complete_json, resolve_backend
from .prompts import (
    AGENT_TURN_SCHEMA,
    DEBATE_RUBRIC,
    PEER_ANSWER_PROMPT,
    PEER_ANSWER_SCHEMA,
    POSITION_SCHEMA,
    REACT_FOLLOWUP,
)
from .scoring import decision_from_score
from .skills import skill_manifest
from .tool_registry import ToolContext, default_registry
from .tools import execute_tool


@dataclass
class TurnResult:
    message: str
    position: Position
    influenced_by: list[str] = field(default_factory=list)
    peer_request: Optional[dict] = None
    tool_call: Optional[dict] = None      # retained for back-compat; tools run in-loop now
    thought: Optional[str] = None


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16)


def _coerce_position(data: dict) -> Position:
    return Position(
        stance=Stance(str(data["stance"]).upper()),
        score=max(0.0, min(10.0, float(data["score"]))),
        confidence=max(0.0, min(1.0, float(data["confidence"]))),
        rationale=str(data.get("rationale", "")),
    )


# ───────────────────────── round 0 ─────────────────────────
@weave.op()
async def agent_position(agent: Agent, question: str, context: Optional[str]) -> Position:
    backend = resolve_backend(agent.provider)
    if backend is None:
        return _mock_position(agent, question)
    system = agent.system_prompt + (
        "\n\nYou are forming your INITIAL position on the decision below, before "
        "hearing the other panelists. Stay fully in character.")
    prompt = (f"DECISION QUESTION:\n{question}\n\n"
              f"CONTEXT:\n{context or '(none provided)'}\n\nGive your initial position.")
    try:
        data = await complete_json(backend, agent.model, system, prompt, POSITION_SCHEMA)
        return _coerce_position(data)
    except Exception:
        return _mock_position(agent, question)


# ───────────────────────── rounds 1..N (ReAct loop) ─────────────────────────
def _short_result(result: dict) -> str:
    if not isinstance(result, dict):
        return str(result)[:160]
    if result.get("error"):
        return f"error: {result['error']}"
    if "evidence" in result or "results" in result:
        hits = result.get("evidence") or result.get("results") or []
        bits = [f"{h.get('title', '')[:60]} ({h.get('url', '')})" for h in hits[:3]]
        return "; ".join(b for b in bits if b.strip(" ()")) or "(no hits)"
    if "body" in result:                       # use_skill
        return f"opened skill '{result.get('skill', '')}'"
    if "markdown" in result:                   # fetch_url
        return f"{result.get('title', '')[:60]}: {result['markdown'][:120]}"
    if "text" in result:                       # mcp
        return str(result["text"])[:160]
    return str(result)[:160]


def _ledger_block(ledger: list[dict]) -> str:
    if not ledger:
        return ""
    lines = [f"• {it['tool']} → {_short_result(it.get('result', {}))}" for it in ledger]
    body = fit_to_budget("\n".join(lines), get_settings().evidence_char_budget)
    return "EVIDENCE LEDGER (tool results gathered so far):\n" + body


def _turn_prompt(agent: Agent, prev: Position, board: str, peers: list[Agent],
                 rnd: int, reg, ledger: list[dict], followup: Optional[str] = None) -> str:
    peer_list = "\n".join(f"- {p.name} (id={p.id}): {p.role}"
                          for p in peers if p.id != agent.id)
    tool_manifest = reg.manifest_for(agent) or "(no tools available this turn)"
    skill_block = ""
    if getattr(agent, "skills", None):
        sm = skill_manifest(agent.skills)
        if sm:
            skill_block = ("SKILLS YOU CAN OPEN (call use_skill with the name to read the full "
                           f"rubric):\n{sm}")
    parts = [
        DEBATE_RUBRIC,
        f"TOOLS YOU MAY CALL (use the exact name in tool_call.tool):\n{tool_manifest}",
        skill_block,
        _ledger_block(ledger),
        f"THE PANEL SO FAR (round {rnd}):\n{board}",
        f"PEERS YOU MAY ADDRESS (use their id in peer_request.to_agent_id):\n{peer_list}",
        f"YOUR PREVIOUS POSITION: {prev.stance.value} {prev.score}/10 "
        f"(confidence {prev.confidence}).",
        followup or "",
        "Take your deliberation turn now.",
    ]
    return "\n\n".join(p for p in parts if p)


def _valid_tool_call(d: dict, agent: Agent, reg) -> Optional[dict]:
    tc = d.get("tool_call") or None
    if not isinstance(tc, dict):
        return None
    tool = tc.get("tool")
    if not tool or tool not in reg.effective_tool_names(agent):
        return None
    return {"tool": tool, "args": tc.get("args") or {}}


def _coerce_turn(d: dict, agent: Agent, peers: list[Agent]) -> TurnResult:
    peer_ids = {p.id for p in peers if p.id != agent.id}
    influenced = [i for i in (d.get("influenced_by") or []) if i in peer_ids]
    pr = d.get("peer_request") or None
    if pr and pr.get("to_agent_id") not in peer_ids:
        pr = None
    pos_data = d.get("position") or {}
    if not isinstance(pos_data, dict) or "stance" not in pos_data:
        raise ValueError(f"agent response missing valid 'position': {str(d)[:200]}")
    return TurnResult(message=str(d.get("message", "")),
                      position=_coerce_position(pos_data),
                      influenced_by=influenced, peer_request=pr,
                      thought=(d.get("thought") or None))


@weave.op()
async def agent_turn(agent: Agent, prev: Position, board: str, peers: list[Agent],
                     rnd: int, *, emit=None, session_id: str = "",
                     evidence: Optional[list[dict]] = None,
                     max_calls: Optional[int] = None) -> TurnResult:
    backend = resolve_backend(agent.provider)
    if backend is None:
        return _mock_turn(agent, prev, peers, rnd)

    reg = default_registry()
    k = max_calls if max_calls is not None else get_settings().tool_max_calls
    ledger: list[dict] = list(evidence or [])
    calls = 0
    while True:
        followup = REACT_FOLLOWUP.format(remaining=k - calls) if calls > 0 else None
        prompt = _turn_prompt(agent, prev, board, peers, rnd, reg, ledger, followup)
        try:
            d = await complete_json(backend, agent.model, agent.system_prompt,
                                    prompt, AGENT_TURN_SCHEMA)
        except Exception:
            return _mock_turn(agent, prev, peers, rnd)
        tc = _valid_tool_call(d, agent, reg) if calls < k else None
        if tc:
            ctx = ToolContext(agent=agent, session_id=session_id, round=rnd)
            ev = emit(rnd, EventType.tool_call, tc, agent_id=agent.id) if emit else None
            result = await execute_tool(tc["tool"], tc["args"], ctx)
            if emit:
                emit(rnd, EventType.tool_result, {"tool": tc["tool"], "result": result},
                     agent_id=agent.id, parent=getattr(ev, "id", None))
            ledger.append({"tool": tc["tool"], "args": tc["args"], "result": result})
            calls += 1
            continue
        # LLM requested a tool call but used an unregistered name — surface the error
        # in the evidence ledger so it can self-correct on the next iteration.
        tc_raw = d.get("tool_call") if isinstance(d.get("tool_call"), dict) else None
        if tc_raw and tc_raw.get("tool") and calls < k:
            bad_tool = str(tc_raw["tool"])
            available = sorted(reg.effective_tool_names(agent))
            result = {"error": f"Unknown tool '{bad_tool}'. Available tools: {available}"}
            payload = {"tool": bad_tool, "args": tc_raw.get("args") or {}}
            if emit:
                ev = emit(rnd, EventType.tool_call, payload, agent_id=agent.id)
                emit(rnd, EventType.tool_result, {"tool": bad_tool, "result": result},
                     agent_id=agent.id, parent=getattr(ev, "id", None))
            ledger.append({"tool": bad_tool, "args": tc_raw.get("args") or {}, "result": result})
            calls += 1
            continue
        try:
            return _coerce_turn(d, agent, peers)
        except Exception:
            return _mock_turn(agent, prev, peers, rnd)


@weave.op()
async def agent_answer_peer(agent: Agent, question: str, asker_name: str) -> str:
    """A short, direct spoken answer to a peer's question (emits as peer_response)."""
    backend = resolve_backend(agent.provider)
    if backend is None:
        r = _seed(agent.name, question)
        held = "I'll concede that point" if r % 2 else "I hold my read"
        return f"[mock] {agent.name}: {held} — the evidence is what decides this for me."
    prompt = PEER_ANSWER_PROMPT.format(name=agent.name, asker=asker_name, question=question)
    try:
        d = await complete_json(backend, agent.model, agent.system_prompt, prompt,
                                PEER_ANSWER_SCHEMA)
        return str(d.get("answer", "")).strip() or f"{agent.name}: (no answer)"
    except Exception:
        return f"[mock] {agent.name}: (couldn't answer just now)."


# ───────────────────────── deterministic mock fallback ─────────────────────────
def _mock_position(agent: Agent, question: str) -> Position:
    r = _seed(agent.name, question)
    score = round(4.0 + (r % 60) / 10.0, 1)
    return Position(stance=decision_from_score(score), score=score,
                    confidence=round(0.5 + (r % 40) / 100.0, 2),
                    rationale=f"[mock] {agent.role}: initial read (no model configured).")


def _short_role(role: str) -> str:
    return role.split("—")[0].strip()[:32]


def _mock_turn(agent: Agent, prev: Position, peers: list[Agent], rnd: int) -> TurnResult:
    r = _seed(agent.name, str(rnd))
    pull = (6.5 - prev.score) * 0.25
    new_score = max(0.0, min(10.0, round(prev.score + pull, 1)))
    others = [p for p in peers if p.id != agent.id]
    cand = others[r % len(others)] if others else None
    influenced = [cand.id] if (cand and abs(pull) > 0.4) else []
    # Sometimes ask a peer directly so the peer-response loop runs even keyless.
    peer_request = None
    if cand and r % 2 == 0:
        peer_request = {"to_agent_id": cand.id,
                        "question": f"How do you square your read with the {_short_role(agent.role)} view?"}
    return TurnResult(
        message=f"[mock] {agent.name}: after round {rnd} I "
                f"{'hold' if abs(pull) < 0.4 else 'adjust'} my position.",
        position=Position(stance=decision_from_score(new_score), score=new_score,
                          confidence=min(1.0, round(prev.confidence + 0.05, 2)),
                          rationale=f"[mock] {agent.role}: updated after the debate."),
        influenced_by=influenced, peer_request=peer_request,
        thought=f"[mock] {agent.name}: weighing the board.")
