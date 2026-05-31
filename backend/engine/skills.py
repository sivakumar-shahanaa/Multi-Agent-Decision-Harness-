"""Skill files — persona-attachable evaluation frameworks (ROADMAP §7.5).

A skill is a `skills/*.md` file: YAML frontmatter (`name`, `description`) + a
markdown body that is a rubric/checklist. We inject only the short MANIFEST
(name + one-line description) into an agent's prompt every turn; the full body
enters context ONLY when the agent calls `use_skill(name)` — progressive
disclosure, so a long rubric costs tokens just-in-time, not every round.

Reuses the persona frontmatter parser in db/seed.py. Degrades to empty when the
skills/ directory is absent.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import weave

from ..db.seed import _clean_body, _split_frontmatter

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


@dataclass
class Skill:
    name: str
    description: str
    body: str


_cache: Optional[dict[str, Skill]] = None


def load_skills() -> dict[str, Skill]:
    """Parse skills/*.md into {name: Skill}. Cached; safe when the dir is missing."""
    global _cache
    if _cache is not None:
        return _cache
    out: dict[str, Skill] = {}
    if SKILLS_DIR.exists():
        for path in sorted(SKILLS_DIR.glob("*.md")):
            fm, body = _split_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
            name = fm.get("name") or path.stem
            out[name] = Skill(name=name, description=fm.get("description", ""),
                              body=_clean_body(body))
    _cache = out
    return out


def reset_skills() -> None:
    global _cache
    _cache = None


def skill_manifest(names: list[str]) -> str:
    """Short `- name: description` lines for an agent's assigned skills (always shown)."""
    skills = load_skills()
    lines = [f"- {s.name}: {s.description}" for n in names if (s := skills.get(n))]
    return "\n".join(lines)


@weave.op()
async def use_skill(args: dict, ctx) -> dict:
    """Expand one skill's full rubric on demand (kind='skill' registry handler)."""
    name = str(args.get("name") or args.get("skill", "")).strip()
    sk = load_skills().get(name)
    if not sk:
        return {"error": f"unknown skill '{name}'", "available": list(load_skills())}
    return {"skill": sk.name, "description": sk.description, "body": sk.body}
