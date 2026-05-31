from fastapi import APIRouter, Depends, HTTPException

from ..db.repository import get_repo
from ..schemas import Agent, AgentUpdate
from .deps import get_current_user, require_org_access

router = APIRouter(prefix="/agents", tags=["agents"])


@router.patch("/{agent_id}", response_model=Agent)
def update_agent(agent_id: str, body: AgentUpdate, user: str = Depends(get_current_user)):
    repo = get_repo()
    existing = repo.get_agent(agent_id)
    if not existing:
        raise HTTPException(404, "agent not found")
    require_org_access(repo, existing.org_id, user)  # owner of the agent's org only
    return repo.update_agent(agent_id, body)
