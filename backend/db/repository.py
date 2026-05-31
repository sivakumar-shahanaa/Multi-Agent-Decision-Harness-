"""Data access for orgs/agents/sessions/events/positions.

Two interchangeable backends behind one interface:
  • SupabaseRepository  — used when SUPABASE_* is configured (production path)
  • InMemoryRepository  — automatic fallback so the API is fully functional in
    dev before Supabase is wired (lets frontend/voice build immediately).

Routers call `get_repo()` and never care which backend is live.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional

from ..schemas import (
    Agent,
    AgentCreate,
    AgentUpdate,
    Brief,
    Event,
    EventType,
    Org,
    Position,
    Project,
    ProjectSource,
    ProjectStatus,
    Session,
    SessionStatus,
    SourceKind,
    Verdict,
)
from .client import get_supabase


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryRepository:
    """Dict-backed store. Not persistent across restarts — fine for dev/demo."""

    def __init__(self) -> None:
        self.orgs: dict[str, Org] = {}
        self.agents: dict[str, Agent] = {}
        self.sessions: dict[str, Session] = {}
        self.events: list[Event] = []
        self.positions: list[dict[str, Any]] = []
        self.projects: dict[str, Project] = {}
        self.project_sources: list[ProjectSource] = []
        self._seq = 0

    # --- orgs ---
    def create_org(self, owner_id: Optional[str], name: str, description=None, preset=None) -> Org:
        org = Org(id=_uid(), owner_id=owner_id, name=name, description=description,
                  preset=preset, created_at=_now())
        self.orgs[org.id] = org
        return org

    def list_orgs(self, owner_id: Optional[str]) -> list[Org]:
        return [o for o in self.orgs.values() if o.owner_id == owner_id]

    def get_org(self, org_id: str) -> Optional[Org]:
        return self.orgs.get(org_id)

    # --- agents ---
    def create_agent(self, org_id: str, a: AgentCreate) -> Agent:
        agent = Agent(id=_uid(), org_id=org_id, created_at=_now(), **a.model_dump())
        self.agents[agent.id] = agent
        return agent

    def list_agents(self, org_id: str) -> list[Agent]:
        return sorted([a for a in self.agents.values() if a.org_id == org_id],
                      key=lambda a: a.position)

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        return self.agents.get(agent_id)

    def update_agent(self, agent_id: str, patch: AgentUpdate) -> Optional[Agent]:
        agent = self.agents.get(agent_id)
        if not agent:
            return None
        data = agent.model_dump()
        data.update({k: v for k, v in patch.model_dump(exclude_none=True).items()})
        agent = Agent(**data)
        self.agents[agent_id] = agent
        return agent

    # --- sessions ---
    def create_session(self, org_id: str, question: str, context=None, rounds=3,
                       created_by=None, parent_session=None,
                       weights_override=None) -> Session:
        sess = Session(id=_uid(), org_id=org_id, question=question, context=context,
                       rounds=rounds, created_by=created_by, parent_session=parent_session,
                       weights_override=weights_override, status=SessionStatus.pending,
                       created_at=_now())
        self.sessions[sess.id] = sess
        return sess

    def get_session(self, session_id: str) -> Optional[Session]:
        return self.sessions.get(session_id)

    def update_session(self, session_id: str, **fields) -> Optional[Session]:
        sess = self.sessions.get(session_id)
        if not sess:
            return None
        data = sess.model_dump()
        data.update(fields)
        sess = Session(**data)
        self.sessions[session_id] = sess
        return sess

    # --- events ---
    def append_event(self, session_id: str, round: int, type: EventType,
                     content: dict, agent_id=None, parent_event=None,
                     influenced_by=None) -> Event:
        self._seq += 1
        ev = Event(id=_uid(), session_id=session_id, seq=self._seq, round=round,
                   agent_id=agent_id, type=type, content=content,
                   parent_event=parent_event, influenced_by=influenced_by or [],
                   created_at=_now())
        self.events.append(ev)
        return ev

    def list_events(self, session_id: str) -> list[Event]:
        return [e for e in self.events if e.session_id == session_id]

    # --- positions ---
    def save_position(self, session_id: str, round: int, agent_id: str, p: Position) -> None:
        self.positions = [r for r in self.positions
                          if not (r["session_id"] == session_id and r["round"] == round
                                  and r["agent_id"] == agent_id)]
        self.positions.append({"session_id": session_id, "round": round,
                               "agent_id": agent_id, **p.model_dump()})

    def list_positions(self, session_id: str) -> list[dict]:
        return [r for r in self.positions if r["session_id"] == session_id]

    # --- projects ---
    def create_project(self, owner_id: Optional[str], name: str) -> Project:
        proj = Project(id=_uid(), owner_id=owner_id, name=name,
                       status=ProjectStatus.pending, created_at=_now())
        self.projects[proj.id] = proj
        return proj

    def get_project(self, project_id: str) -> Optional[Project]:
        return self.projects.get(project_id)

    def list_projects(self, owner_id: Optional[str]) -> list[Project]:
        return sorted([p for p in self.projects.values() if p.owner_id == owner_id],
                      key=lambda p: p.created_at or _now(), reverse=True)

    def update_project(self, project_id: str, **fields) -> Optional[Project]:
        proj = self.projects.get(project_id)
        if not proj:
            return None
        data = proj.model_dump()
        data.update(fields)
        proj = Project(**data)
        self.projects[project_id] = proj
        return proj

    def add_project_source(self, project_id: str, kind, filename="", content_type=None,
                           storage_path=None, content_hash=None, bytes=0) -> ProjectSource:
        src = ProjectSource(id=_uid(), project_id=project_id,
                            kind=kind if isinstance(kind, SourceKind) else SourceKind(kind),
                            filename=filename, content_type=content_type,
                            storage_path=storage_path, content_hash=content_hash,
                            bytes=bytes, created_at=_now())
        self.project_sources.append(src)
        return src

    def list_project_sources(self, project_id: str) -> list[ProjectSource]:
        return [s for s in self.project_sources if s.project_id == project_id]

    def update_project_source(self, source_id: str, **fields) -> Optional[ProjectSource]:
        for i, s in enumerate(self.project_sources):
            if s.id == source_id:
                data = s.model_dump()
                data.update(fields)
                self.project_sources[i] = ProjectSource(**data)
                return self.project_sources[i]
        return None


class SupabaseRepository:
    """Maps the same interface onto Supabase tables. The service-key client bypasses RLS."""

    def __init__(self, client) -> None:
        self.c = client

    def _t(self, name: str):
        return self.c.table(name)

    # --- orgs ---
    def create_org(self, owner_id, name, description=None, preset=None) -> Org:
        row = self._t("orgs").insert({"owner_id": owner_id, "name": name,
                                      "description": description, "preset": preset}
                                     ).execute().data[0]
        return Org(**row)

    def list_orgs(self, owner_id) -> list[Org]:
        rows = self._t("orgs").select("*").eq("owner_id", owner_id).order("created_at").execute().data
        return [Org(**r) for r in rows]

    def get_org(self, org_id) -> Optional[Org]:
        rows = self._t("orgs").select("*").eq("id", org_id).execute().data
        return Org(**rows[0]) if rows else None

    # --- agents ---
    def create_agent(self, org_id, a: AgentCreate) -> Agent:
        payload = {"org_id": org_id, **a.model_dump()}
        payload["provider"] = a.provider.value
        row = self._t("agents").insert(payload).execute().data[0]
        return Agent(**row)

    def list_agents(self, org_id) -> list[Agent]:
        rows = self._t("agents").select("*").eq("org_id", org_id).order("position").execute().data
        return [Agent(**r) for r in rows]

    def get_agent(self, agent_id) -> Optional[Agent]:
        rows = self._t("agents").select("*").eq("id", agent_id).execute().data
        return Agent(**rows[0]) if rows else None

    def update_agent(self, agent_id, patch: AgentUpdate) -> Optional[Agent]:
        data = patch.model_dump(exclude_none=True)
        if "provider" in data:
            data["provider"] = data["provider"].value
        rows = self._t("agents").update(data).eq("id", agent_id).execute().data
        return Agent(**rows[0]) if rows else None

    # --- sessions ---
    def create_session(self, org_id, question, context=None, rounds=3, created_by=None,
                       parent_session=None, weights_override=None) -> Session:
        row = self._t("sessions").insert({
            "org_id": org_id, "question": question, "context": context, "rounds": rounds,
            "created_by": created_by, "parent_session": parent_session,
            "weights_override": weights_override, "status": "pending",
        }).execute().data[0]
        return Session(**row)

    def get_session(self, session_id) -> Optional[Session]:
        rows = self._t("sessions").select("*").eq("id", session_id).execute().data
        return Session(**rows[0]) if rows else None

    def update_session(self, session_id, **fields) -> Optional[Session]:
        if isinstance(fields.get("final_verdict"), Verdict):
            fields["final_verdict"] = fields["final_verdict"].model_dump()
        if isinstance(fields.get("status"), SessionStatus):
            fields["status"] = fields["status"].value
        rows = self._t("sessions").update(fields).eq("id", session_id).execute().data
        return Session(**rows[0]) if rows else None

    # --- events ---
    def append_event(self, session_id, round, type, content, agent_id=None,
                     parent_event=None, influenced_by=None) -> Event:
        t = type.value if isinstance(type, EventType) else type
        row = self._t("events").insert({
            "session_id": session_id, "round": round, "type": t, "content": content,
            "agent_id": agent_id, "parent_event": parent_event,
            "influenced_by": influenced_by or [],
        }).execute().data[0]
        return Event(**row)

    def list_events(self, session_id) -> list[Event]:
        rows = self._t("events").select("*").eq("session_id", session_id).order("seq").execute().data
        return [Event(**r) for r in rows]

    # --- positions ---
    def save_position(self, session_id, round, agent_id, p: Position) -> None:
        self._t("positions").upsert({
            "session_id": session_id, "round": round, "agent_id": agent_id, **p.model_dump(),
        }, on_conflict="session_id,round,agent_id").execute()

    def list_positions(self, session_id) -> list[dict]:
        return self._t("positions").select("*").eq("session_id", session_id).execute().data

    # --- projects ---
    def create_project(self, owner_id, name) -> Project:
        row = self._t("projects").insert({
            "owner_id": owner_id, "name": name, "status": "pending",
        }).execute().data[0]
        return Project(**row)

    def get_project(self, project_id) -> Optional[Project]:
        rows = self._t("projects").select("*").eq("id", project_id).execute().data
        return Project(**rows[0]) if rows else None

    def list_projects(self, owner_id) -> list[Project]:
        rows = (self._t("projects").select("*").eq("owner_id", owner_id)
                .order("created_at", desc=True).execute().data)
        return [Project(**r) for r in rows]

    def update_project(self, project_id, **fields) -> Optional[Project]:
        if isinstance(fields.get("status"), ProjectStatus):
            fields["status"] = fields["status"].value
        if isinstance(fields.get("brief"), Brief):
            fields["brief"] = fields["brief"].model_dump()
        rows = self._t("projects").update(fields).eq("id", project_id).execute().data
        return Project(**rows[0]) if rows else None

    def add_project_source(self, project_id, kind, filename="", content_type=None,
                           storage_path=None, content_hash=None, bytes=0) -> ProjectSource:
        row = self._t("project_sources").insert({
            "project_id": project_id,
            "kind": kind.value if isinstance(kind, SourceKind) else kind,
            "filename": filename, "content_type": content_type,
            "storage_path": storage_path, "content_hash": content_hash, "bytes": bytes,
        }).execute().data[0]
        return ProjectSource(**row)

    def list_project_sources(self, project_id) -> list[ProjectSource]:
        rows = (self._t("project_sources").select("*").eq("project_id", project_id)
                .order("created_at").execute().data)
        return [ProjectSource(**r) for r in rows]

    def update_project_source(self, source_id, **fields) -> Optional[ProjectSource]:
        rows = self._t("project_sources").update(fields).eq("id", source_id).execute().data
        return ProjectSource(**rows[0]) if rows else None


@lru_cache
def get_repo():
    client = get_supabase()
    return SupabaseRepository(client) if client else InMemoryRepository()
