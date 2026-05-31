"""THE FROZEN CONTRACT (ROADMAP §5-7).

Every workstream codes against these models. Do not change a field name without
announcing it to the team — this is the seam between backend, frontend, engine,
and voice. Mirrored in TypeScript at frontend/lib/types.ts.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ───────────────────────── enums ─────────────────────────
class EventType(str, Enum):
    position = "position"                 # round 0 independent stance
    thought = "thought"                   # private reasoning summary
    message = "message"                   # public argument (this is what gets spoken)
    peer_request = "peer_request"         # direct question to a peer
    peer_response = "peer_response"       # answer (parent_event = the request)
    tool_call = "tool_call"
    tool_result = "tool_result"           # parent_event = the call
    position_update = "position_update"   # carries influenced_by
    orchestrator = "orchestrator"         # control: start/continue/converge
    verdict = "verdict"                   # final verdict object
    extraction = "extraction"             # project-brief pipeline progress (pre-debate)


class Stance(str, Enum):
    YES = "YES"
    NO = "NO"
    CONDITIONAL = "CONDITIONAL"


class Provider(str, Enum):
    anthropic = "anthropic"
    wandb = "wandb"                       # W&B Inference (open models)


class SessionStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    error = "error"


class ProjectStatus(str, Enum):
    pending = "pending"        # created, files stored, extraction not started
    extracting = "extracting"  # pipeline running
    ready = "ready"            # brief available
    failed = "failed"          # extraction errored (brief may be partial/empty)


class SourceKind(str, Enum):
    pdf = "pdf"
    video = "video"
    url = "url"


# ───────────────────── core domain models ─────────────────────
class Position(BaseModel):
    stance: Stance
    score: float = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    rationale: str = ""


class Conflict(BaseModel):
    between: list[str]                    # agent_ids
    issue: str


class Dissent(BaseModel):
    agent_id: str
    stance: Stance
    why: str


class InfluenceScore(BaseModel):
    agent_id: str
    influence: float = Field(ge=0, le=1)


class Verdict(BaseModel):
    decision: Stance
    weighted_score: float = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    summary: str = ""
    key_agreements: list[str] = []
    key_conflicts: list[Conflict] = []
    dissenting_opinions: list[Dissent] = []
    influence_ranking: list[InfluenceScore] = []


class Agent(BaseModel):
    id: str
    org_id: str
    name: str
    role: str
    system_prompt: str
    model: str = "openai/gpt-oss-120b"
    provider: Provider = Provider.wandb
    weight: float = 1.0
    voice_id: Optional[str] = None
    tools: list[str] = []
    skills: list[str] = []                # skill-file names this agent may `use_skill` on
    position: int = 0                     # seat order in the boardroom
    structural: bool = False              # cannot be removed/re-weighted away (e.g. the Skeptic)
    veto: bool = False                    # blocks a clean YES unless it too is convinced
    conflict_partner: Optional[str] = None    # agent_id the moderator pits this agent against
    conflict_dimension: Optional[str] = None  # the axis of that disagreement
    created_at: Optional[datetime] = None


class Org(BaseModel):
    id: str
    owner_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    preset: Optional[str] = None          # 'vc' | 'board' | 'judges'
    created_at: Optional[datetime] = None


class Event(BaseModel):
    id: str
    session_id: str
    seq: int                              # global order within session
    round: int
    agent_id: Optional[str] = None        # null for orchestrator events
    type: EventType
    content: dict[str, Any]               # type-specific payload (see ROADMAP §5)
    parent_event: Optional[str] = None
    influenced_by: list[str] = []
    created_at: Optional[datetime] = None


class Session(BaseModel):
    id: str
    org_id: str
    created_by: Optional[str] = None
    question: str
    context: Optional[str] = None
    weights_override: Optional[dict[str, float]] = None
    status: SessionStatus = SessionStatus.pending
    rounds: int = 3
    final_verdict: Optional[Verdict] = None
    weave_trace_url: Optional[str] = None
    parent_session: Optional[str] = None
    project_id: Optional[str] = None       # the Project Brief that grounded this debate
    created_at: Optional[datetime] = None


# ───────────────────── project brief (multimodal context) ─────────────────────
class Brief(BaseModel):
    """The extracted understanding of a project, fused from deck + video + URL.

    Every field is optional so a partial extraction (one source, or a mock run)
    still produces a valid brief. `brief_text` (on Project) is the markdown
    rendering that actually flows into the agents' CONTEXT slot.
    """
    title: str = ""
    one_liner: str = ""
    problem: str = ""
    solution: str = ""
    market: str = ""
    traction: str = ""
    tech: str = ""
    business_model: str = ""
    team: str = ""
    risks: list[str] = []
    asks: list[str] = []
    summary: str = ""


class ProjectSource(BaseModel):
    id: str
    project_id: str
    kind: SourceKind
    filename: str = ""                     # original name, or the URL for kind=url
    content_type: Optional[str] = None
    storage_path: Optional[str] = None     # object key in the bucket / local path / url
    content_hash: Optional[str] = None     # sha256 — dedupe / re-extraction cache
    bytes: int = 0
    extracted: Optional[dict[str, Any]] = None  # per-source intermediate (inspectable)
    created_at: Optional[datetime] = None


class Project(BaseModel):
    id: str
    owner_id: Optional[str] = None
    name: str
    status: ProjectStatus = ProjectStatus.pending
    brief: Optional[Brief] = None
    brief_text: Optional[str] = None       # markdown — becomes session.context
    error: Optional[str] = None
    created_at: Optional[datetime] = None


# ───────────────────── API request / response ─────────────────────
class CreateOrgRequest(BaseModel):
    name: str
    description: Optional[str] = None
    preset: Optional[str] = None


class GenerateOrgRequest(BaseModel):
    prompt: str                           # "a biotech seed investment committee"


class AgentCreate(BaseModel):
    name: str
    role: str
    system_prompt: str
    # Default to W&B Inference; the council runs entirely on open models (no Anthropic).
    model: str = "openai/gpt-oss-120b"
    provider: Provider = Provider.wandb
    weight: float = 1.0
    voice_id: Optional[str] = None
    tools: list[str] = []
    skills: list[str] = []
    position: int = 0
    structural: bool = False
    veto: bool = False
    conflict_partner: Optional[str] = None
    conflict_dimension: Optional[str] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[Provider] = None
    weight: Optional[float] = None
    voice_id: Optional[str] = None
    tools: Optional[list[str]] = None
    skills: Optional[list[str]] = None
    position: Optional[int] = None
    structural: Optional[bool] = None
    veto: Optional[bool] = None
    conflict_partner: Optional[str] = None
    conflict_dimension: Optional[str] = None


class CreateSessionRequest(BaseModel):
    org_id: str
    question: str
    context: Optional[str] = None
    rounds: int = 3
    project_id: Optional[str] = None       # attach a finished Project Brief as context


class CreateSessionResponse(BaseModel):
    session_id: str


class CreateVideoSessionResponse(BaseModel):
    session_id: str
    transcript: str


# ───────────────────── project API request / response ─────────────────────
class CreateProjectResponse(BaseModel):
    project_id: str


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    brief_text: Optional[str] = None       # the user's reviewed/edited brief


class ProjectDetail(BaseModel):
    project: Project
    sources: list[ProjectSource] = []


class RerunRequest(BaseModel):
    weights_override: Optional[dict[str, float]] = None
    context: Optional[str] = None


class SessionDetail(BaseModel):
    session: Session
    events: list[Event] = []
    positions: list[dict[str, Any]] = []  # rows from `positions` table
    verdict: Optional[Verdict] = None


class InfluenceNode(BaseModel):
    agent_id: str
    name: str
    weight: float
    influence: float


class InfluenceEdge(BaseModel):
    from_agent: str = Field(alias="from")
    to_agent: str = Field(alias="to")
    weight: float

    model_config = {"populate_by_name": True}


class InfluenceGraph(BaseModel):
    nodes: list[InfluenceNode] = []
    edges: list[InfluenceEdge] = []
