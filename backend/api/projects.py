"""Project-brief endpoints: upload a deck/demo/URL, watch extraction stream, review
and edit the brief, then attach it to a debate (POST /sessions {project_id}).

Multipart is isolated to this router so the frozen POST /sessions JSON contract stays
intact. Ownership is enforced here (404-not-403) since the service key bypasses RLS.
"""
import asyncio
import hashlib
import json

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile)
from sse_starlette.sse import EventSourceResponse

from ..db.repository import get_repo
from ..db.storage import get_storage
from ..engine import stream
from ..engine.ingest.brief import run_extraction
from ..safeurl import UnsafeURLError, validate_url_static
from ..schemas import (CreateProjectResponse, Project, ProjectDetail,
                       ProjectStatus, SourceKind, UpdateProjectRequest)
from .deps import (get_current_user, get_current_user_sse,
                   require_project_access)

router = APIRouter(prefix="/projects", tags=["projects"])

_CT_TO_KIND = {"application/pdf": SourceKind.pdf, "video/mp4": SourceKind.video}
_EXT_TO_KIND = {".pdf": SourceKind.pdf, ".mp4": SourceKind.video}
# Caps: PDF 25 MB; MP4 50 MB (Supabase's default standard-upload ceiling).
_MAX_BYTES = {SourceKind.pdf: 25 * 1024 * 1024, SourceKind.video: 50 * 1024 * 1024}
_EXT = {SourceKind.pdf: "pdf", SourceKind.video: "mp4"}


def _kind_for(file: UploadFile):
    ct = (file.content_type or "").lower()
    if ct in _CT_TO_KIND:
        return _CT_TO_KIND[ct]
    name = (file.filename or "").lower()
    for ext, kind in _EXT_TO_KIND.items():  # browsers send '' / octet-stream for .mp4
        if name.endswith(ext):
            return kind
    return None


async def _read_capped(file: UploadFile, cap: int) -> bytes:
    """Stream-read in 1 MB chunks, rejecting once the running total exceeds cap."""
    chunks, size = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > cap:
            raise HTTPException(413, f"{file.filename or 'file'} exceeds {cap // (1024 * 1024)}MB")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("", response_model=CreateProjectResponse)
async def create_project(
    name: str = Form(""),
    url: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    user: str = Depends(get_current_user),
):
    url = url.strip()
    if not files and not url:
        raise HTTPException(400, "attach at least one PDF/MP4 file or a URL")
    if url:  # SSRF/defense-in-depth: reject file://, userinfo, internal hosts
        try:
            validate_url_static(url)
        except UnsafeURLError as e:
            raise HTTPException(400, f"unsafe URL: {e}")

    # Validate + read every file UP FRONT, before any persistence — so a rejected
    # file (415/413) can't orphan a half-created project + uploaded bytes.
    staged: list[tuple] = []
    for f in files:
        kind = _kind_for(f)
        if kind is None:
            raise HTTPException(415, f"unsupported file type: {f.filename}")
        data = await _read_capped(f, _MAX_BYTES[kind])
        staged.append((kind, data, f.filename, f.content_type))

    repo, storage = get_repo(), get_storage()
    default_name = (name.strip() or (staged[0][2] if staged else "") or url or "Untitled project")
    # supabase-py is sync — keep blocking repo/storage writes off the event loop.
    proj = await asyncio.to_thread(repo.create_project, user, default_name)
    await asyncio.to_thread(storage.ensure)

    for i, (kind, data, filename, content_type) in enumerate(staged):
        path = f"{user}/{proj.id}/{kind.value}-{i}.{_EXT[kind]}"
        await asyncio.to_thread(storage.put, path, data, content_type)
        await asyncio.to_thread(
            repo.add_project_source, proj.id, kind, filename=filename or path,
            content_type=content_type, storage_path=path,
            content_hash=hashlib.sha256(data).hexdigest(), bytes=len(data))

    if url:
        await asyncio.to_thread(repo.add_project_source, proj.id, SourceKind.url,
                                filename=url, storage_path=url)

    asyncio.create_task(run_extraction(proj.id, repo, storage))
    return CreateProjectResponse(project_id=proj.id)


@router.get("", response_model=list[Project])
def list_projects(user: str = Depends(get_current_user)):
    return get_repo().list_projects(user)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str, user: str = Depends(get_current_user)):
    repo = get_repo()
    proj = require_project_access(repo, project_id, user)
    return ProjectDetail(project=proj, sources=repo.list_project_sources(project_id))


@router.patch("/{project_id}", response_model=Project)
def update_project(project_id: str, body: UpdateProjectRequest,
                   user: str = Depends(get_current_user)):
    repo = get_repo()
    require_project_access(repo, project_id, user)
    fields = body.model_dump(exclude_none=True)
    return repo.update_project(project_id, **fields) if fields else repo.get_project(project_id)


@router.get("/{project_id}/stream")
async def stream_project(project_id: str, request: Request,
                         user: str = Depends(get_current_user_sse)):
    repo = get_repo()
    require_project_access(repo, project_id, user)
    q = stream.subscribe(project_id)

    def _snapshot(status: ProjectStatus) -> dict:
        terminal = status in (ProjectStatus.ready, ProjectStatus.failed)
        return {"type": "extraction", "content": {
            "stage": status.value, "detail": "", "progress": 1.0 if terminal else 0.1}}

    async def gen():
        try:
            cur = repo.get_project(project_id)
            yield {"event": "extraction", "data": json.dumps(_snapshot(cur.status))}
            if cur.status in (ProjectStatus.ready, ProjectStatus.failed):
                yield {"event": "done", "data": "{}"}
                return
            while True:
                if await request.is_disconnected():
                    break
                item = await q.get()
                if item is None:
                    yield {"event": "done", "data": "{}"}
                    break
                yield {"event": item.get("type", "extraction"), "data": json.dumps(item)}
        finally:
            stream.unsubscribe(project_id, q)

    return EventSourceResponse(gen())
