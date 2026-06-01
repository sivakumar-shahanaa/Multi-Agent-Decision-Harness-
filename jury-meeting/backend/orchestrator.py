"""Meeting orchestrator (the MAS layer).

All @weave.op so the whole meeting is one auditable trace:
  - load_record:        pull the pre-made decision (DB via db.get_record; sample fallback).
  - opening_statements: each juror voices its position, most weighted first.
  - route:              given a live question, delegate to the juror who owns it.
  - ask:                route + have that juror answer.
  - run_meeting:        end-to-end (openings + a list of questions).
"""
from __future__ import annotations

import weave

import agents
import db
from llm import ROUTER_MODEL, chat


@weave.op
def load_record(meeting_id: str | None = None) -> dict:
    """Decision source. The other team writes it; we read it at meeting init."""
    return db.get_record(meeting_id)


def _indexed(record: dict) -> list[tuple[int, dict]]:
    """Stable seat index per juror (drives default voice assignment)."""
    return list(enumerate(record.get("jurors", [])))


def _importance(juror: dict) -> tuple:
    """Panel weights are all 1.0, so rank by the verdict's influence_ranking,
    then by score, then weight as a last resort (covers the sample, which has
    no influence data)."""
    return (juror.get("influence", 0) or 0, juror.get("score") or 0, juror.get("weight") or 0)


@weave.op
def opening_statements(record: dict) -> list[dict]:
    """Each juror delivers its verdict; the most pivotal juror speaks first."""
    order = sorted(_indexed(record), key=lambda iv: _importance(iv[1]), reverse=True)
    return [agents.explain(juror, record, index=i) for i, juror in order]


@weave.op
def route(question: str, record: dict) -> int:
    """The chair agent delegates the question to the juror who owns it.

    Returns a seat index. The agent decides; parsing only translates its answer
    back to an index. If the agent's reply is unusable we default to the most
    influential juror (general — no hardcoded topics).
    """
    jurors = record.get("jurors", [])
    if not jurors:
        return 0
    catalog = "\n".join(
        f"{i}. {j['name']} — {j.get('role', '')} (stance {j.get('stance')}, "
        f"score {j.get('score')}/10)"
        for i, j in _indexed(record)
    )
    sys = (
        "You are the chair of a decision jury. Route the question to the single juror best "
        "suited to answer it, based on their role and stated position. Reply with ONLY the "
        "juror's number (e.g. `2`), nothing else."
    )
    user = f"Jurors:\n{catalog}\n\nQuestion: {question}\n\nAnswer with one number:"
    # Fast instruct model answers the classification directly (no reasoning preamble).
    raw = chat(sys, user, model=ROUTER_MODEL, temperature=0.0, max_tokens=8)
    for tok in raw.replace(".", " ").replace("#", " ").split():
        if tok.isdigit() and int(tok) < len(jurors):
            return int(tok)
    # The agent named the juror instead of numbering it.
    low = raw.lower()
    for i, j in _indexed(record):
        if j.get("name", "").lower() in low:
            return i
    # Unusable reply -> most influential juror (general fallback).
    return max(_indexed(record), key=lambda iv: _importance(iv[1]))[0]


@weave.op
def ask(question: str, record: dict) -> dict:
    """Route a live question and have the chosen juror answer it."""
    idx = route(question, record)
    juror = record["jurors"][idx]
    turn = agents.answer(question, juror, record, index=idx)
    turn["routed_to"] = juror["name"]
    turn["question"] = question
    return turn


@weave.op
def run_meeting(record: dict, questions: list[str] | None = None) -> dict:
    """End-to-end meeting: openings followed by any applicant questions."""
    openings = opening_statements(record)
    qa = [ask(q, record) for q in (questions or [])]
    return {
        "meeting_id": record.get("meeting_id"),
        "subject": record.get("subject", {}).get("title"),
        "verdict": record.get("verdict"),
        "overall_score": record.get("overall_score"),
        "summary": record.get("summary"),
        "openings": openings,
        "qa": qa,
        "trace_url": record.get("trace_url"),
    }
