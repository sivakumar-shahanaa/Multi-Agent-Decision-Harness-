from fastapi import APIRouter, Depends, HTTPException

from ..db.repository import get_repo
from ..schemas import Agent, AgentCreate, CreateOrgRequest, GenerateOrgRequest, Org
from .deps import get_current_user, require_org_access

router = APIRouter(prefix="/orgs", tags=["orgs"])


@router.get("", response_model=list[Org])
def list_orgs(user: str = Depends(get_current_user)):
    return get_repo().list_orgs(user)


@router.post("", response_model=Org)
def create_org(body: CreateOrgRequest, user: str = Depends(get_current_user)):
    return get_repo().create_org(user, body.name, body.description, body.preset)


@router.post("/generate", response_model=Org)
def generate_org(body: GenerateOrgRequest, user: str = Depends(get_current_user)):
    # TODO(WS-B, H4): call an LLM to synthesize a full agent team from body.prompt
    # and create each agent. Hour-0 stub returns an empty org so the route exists.
    return get_repo().create_org(user, name=f"Generated: {body.prompt[:40]}", preset="generated")


@router.get("/{org_id}/agents", response_model=list[Agent])
def list_org_agents(org_id: str, user: str = Depends(get_current_user)):
    repo = get_repo()
    require_org_access(repo, org_id, user)
    return repo.list_agents(org_id)


@router.post("/{org_id}/agents", response_model=Agent)
def create_org_agent(org_id: str, body: AgentCreate, user: str = Depends(get_current_user)):
    repo = get_repo()
    require_org_access(repo, org_id, user)
    return repo.create_agent(org_id, body)
