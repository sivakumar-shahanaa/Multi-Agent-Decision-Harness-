"""Prompt fragments + the structured-output schema for an agent turn (ROADMAP §7.3).

WS-A: these feed the Claude Agent SDK calls. The JSON schema is what each agent
must return so we can persist typed events and build the influence graph.
"""

DEBATE_RUBRIC = """
You are one member of a decision-making panel. You have already stated an initial
position. You can now SEE what every other member said. Do exactly one deliberation turn:

1. Optionally jot ONE line of private reasoning (`thought`) — not shown to peers.
2. If a claim needs grounding, CALL A TOOL from your allowlist (`tool_call`: {tool, args}).
   Prefer real evidence over assertion — you will see the result and may then revise.
3. Make ONE public argument (`message`) — concise, in your own voice, addressing the
   strongest opposing point. Cite tool evidence when you have it.
4. Optionally ask ONE peer a direct question (`peer_request`) by their agent_id.
5. Re-state your position (`position`): stance (YES/NO/CONDITIONAL), score 0-10,
   confidence 0-1, and a one-line rationale.
6. If a peer's argument OR tool evidence changed your score, list the agent_ids in
   `influenced_by`. Be honest — a static panel is a useless panel.

Stay in character. Do not invent facts; use tools or say you're uncertain.
""".strip()

# Shown after a tool returns, asking the agent to finalize (or call once more).
REACT_FOLLOWUP = """
You called a tool and the result is in your EVIDENCE LEDGER above. Finalize your turn now:
if the evidence changed your read, MOVE your score and cite the evidence in `rationale`.
You may call at most {remaining} more tool(s); otherwise set tool_call to null.
""".strip()

# A peer was asked a direct question and gives a SHORT spoken answer.
PEER_ANSWER_PROMPT = """
You are {name}, on a decision panel. {asker} asked you directly:
"{question}"
Answer in 1-2 sentences, in your own voice and from your expertise. Be specific and
direct — concede a fair point or hold your ground, but actually answer the question.
Return JSON: {{"answer": "..."}}.
""".strip()

PEER_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}

# The orchestrator moderates between rounds: who moved, where the live conflict is,
# and a directive for the next round.
MODERATOR_PROMPT = """
You are the orchestrator moderating a live decision panel between rounds. Given who
moved and the current split, write a SHORT moderator note (1-2 sentences) naming the
real tension and DIRECTING the next round — e.g. ask the two most-split members to
resolve a specific disagreement. Be neutral, surface conflict, don't smooth it over.
Return JSON: {"note": "...", "directive": "..."}.
""".strip()

MODERATOR_SCHEMA = {
    "type": "object",
    "properties": {"note": {"type": "string"}, "directive": {"type": "string"}},
    "required": ["note"],
}

ORCHESTRATOR_PROMPT = """
You are the orchestrator of a decision panel. You are given the full transcript of a
multi-round debate. Produce a structured verdict:
- summary: 2-3 sentences capturing the panel's collective judgment.
- key_agreements: points (nearly) everyone shared.
- key_conflicts: the real disagreements, naming the agents on each side.
- dissenting_opinions: any agent whose final stance differs from the majority, and why.
Do NOT compute the numeric score yourself — that is calculated from weighted votes.
Be neutral and precise; surface conflict rather than smoothing it over.
""".strip()

ORG_BUILDER_PROMPT = """
You design panels of expert AI agents that evaluate decisions together. Given a
domain or panel description, invent 3-5 DISTINCT panelists who would productively
disagree. For each: a realistic name, a specific role/title, and a rich first-person
system_prompt (3-5 sentences) defining their expertise, biases, what they optimize
for, and their voice. Make at least one a skeptic. Assign each a relative weight
(they need not sum to 1 — they'll be normalized). Return JSON only.
""".strip()

ORG_BUILDER_SCHEMA = {
    "type": "object",
    "properties": {
        "org_name": {"type": "string"},
        "description": {"type": "string"},
        "agents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "system_prompt": {"type": "string"},
                    "weight": {"type": "number"},
                },
                "required": ["name", "role", "system_prompt", "weight"],
            },
        },
    },
    "required": ["org_name", "agents"],
}

# Initial (round 0) position.
POSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "stance": {"enum": ["YES", "NO", "CONDITIONAL"]},
        "score": {"type": "number", "minimum": 0, "maximum": 10},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
    },
    "required": ["stance", "score", "confidence", "rationale"],
}

# Orchestrator's natural-language summary (numbers are computed, not asked for).
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_agreements": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "key_agreements"],
}

# Structured output each agent must return per deliberation turn.
AGENT_TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": ["string", "null"]},   # private reasoning (optional)
        "message": {"type": "string"},
        "peer_request": {
            "type": ["object", "null"],
            "properties": {
                "to_agent_id": {"type": "string"},
                "question": {"type": "string"},
            },
            "required": ["to_agent_id", "question"],
        },
        "tool_call": {
            "type": ["object", "null"],
            "properties": {
                "tool": {"type": "string"},
                "args": {"type": "object"},
            },
            "required": ["tool", "args"],
        },
        "position": {
            "type": "object",
            "properties": {
                "stance": {"enum": ["YES", "NO", "CONDITIONAL"]},
                "score": {"type": "number", "minimum": 0, "maximum": 10},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "rationale": {"type": "string"},
            },
            "required": ["stance", "score", "confidence", "rationale"],
        },
        "influenced_by": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["message", "position", "influenced_by"],
}
