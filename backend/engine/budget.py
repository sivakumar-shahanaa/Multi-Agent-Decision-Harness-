"""Tiny char/token budgeting helpers for context optimization (ROADMAP §7.2).

No tokenizer dependency — a ~4 chars/token heuristic is plenty for keeping the
per-turn board and the orchestrator transcript inside a sane window. Used so the
ReAct loop's growing evidence ledger and the multi-round board never blow up the
prompt. Pure functions, no I/O.
"""
from __future__ import annotations


def est_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token). Good enough for budgeting."""
    return max(1, len(text) // 4)


def fit_to_budget(text: str, char_budget: int) -> str:
    """Hard-cap a single string, appending a visible truncation marker."""
    if len(text) <= char_budget:
        return text
    return text[: max(0, char_budget - 24)].rstrip() + "\n…[truncated for budget]"


def pack_lines(lines: list[str], char_budget: int, keep: str = "tail") -> str:
    """Join `lines` newest-first or oldest-first until the char budget is hit.

    keep="tail" prefers the most recent lines (debate board: latest matters most);
    keep="head" prefers the earliest. Dropped lines are summarized in a marker.
    """
    if not lines:
        return ""
    ordered = list(reversed(lines)) if keep == "tail" else list(lines)
    out: list[str] = []
    used = 0
    dropped = 0
    for ln in ordered:
        cost = len(ln) + 1
        if used + cost > char_budget and out:
            dropped = len(ordered) - len(out)
            break
        out.append(ln)
        used += cost
    if keep == "tail":
        out.reverse()
    if dropped:
        marker = f"…[{dropped} earlier line(s) omitted for budget]"
        out.insert(0, marker) if keep == "tail" else out.append(marker)
    return "\n".join(out)
