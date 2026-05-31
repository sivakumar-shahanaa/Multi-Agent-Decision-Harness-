"""Project-brief ingestion: repository, storage, and the extraction pipeline in
deterministic MOCK mode (no network). Mirrors test_engine.py's offline approach."""
import pytest
from fastapi.testclient import TestClient

from backend.db import repository, storage
from backend.db.repository import InMemoryRepository
from backend.db.storage import LocalStorage
from backend.engine.ingest import brief as briefmod
from backend.schemas import Brief, ProjectStatus, SourceKind


# ───────────────────────── repository ─────────────────────────
def test_project_repo_crud():
    repo = InMemoryRepository()
    p = repo.create_project("user-1", "Acme AI")
    assert p.status == ProjectStatus.pending and p.owner_id == "user-1"

    src = repo.add_project_source(p.id, SourceKind.pdf, filename="deck.pdf",
                                  content_type="application/pdf", storage_path="k/deck.pdf",
                                  content_hash="abc", bytes=1234)
    assert src.kind == SourceKind.pdf
    repo.update_project_source(src.id, extracted={"n_pages": 3})
    assert repo.list_project_sources(p.id)[0].extracted == {"n_pages": 3}

    repo.update_project(p.id, status=ProjectStatus.ready, brief=Brief(problem="x"),
                        brief_text="# Brief")
    got = repo.get_project(p.id)
    assert got.status == ProjectStatus.ready and got.brief_text == "# Brief"
    assert [pp.name for pp in repo.list_projects("user-1")] == ["Acme AI"]
    assert repo.list_projects("someone-else") == []


# ───────────────────────── storage ─────────────────────────
def test_local_storage_roundtrip(tmp_path):
    store = LocalStorage(root=tmp_path / "uploads")
    store.ensure()
    path = store.put("user-1/proj/deck.pdf", b"%PDF-bytes", "application/pdf")
    assert store.get(path) == b"%PDF-bytes"
    store.remove(path)
    with pytest.raises(Exception):
        store.get(path)


def test_local_storage_rejects_path_escape(tmp_path):
    store = LocalStorage(root=tmp_path / "uploads")
    store.ensure()
    with pytest.raises(ValueError):
        store.put("../../etc/evil", b"x", "text/plain")


# ───────────────────────── pipeline (mock) ─────────────────────────
async def test_extraction_no_sources_yields_mock_brief(tmp_path):
    repo, store = InMemoryRepository(), LocalStorage(root=tmp_path)
    store.ensure()
    p = repo.create_project("u", "Empty Co")
    await briefmod.run_extraction(p.id, repo, store)
    got = repo.get_project(p.id)
    assert got.status == ProjectStatus.ready
    assert got.brief_text and "Empty Co" in got.brief_text


async def test_extraction_pdf_mock(monkeypatch, tmp_path):
    repo, store = InMemoryRepository(), LocalStorage(root=tmp_path)
    store.ensure()
    # Stub the PDF reader + force synthesis to the deterministic mock (no network).
    monkeypatch.setattr(briefmod.pdf, "extract_pdf",
                        lambda data, **k: {"n_pages": 2, "text": "InvoiceBot automates SMB billing. 3000 users.", "pages": []})
    monkeypatch.setattr(briefmod, "resolve_backend", lambda *_: None)

    p = repo.create_project("u", "InvoiceBot")
    path = store.put("u/p/deck.pdf", b"%PDF-fake", "application/pdf")
    src = repo.add_project_source(p.id, SourceKind.pdf, filename="deck.pdf", storage_path=path)
    await briefmod.run_extraction(p.id, repo, store)

    got = repo.get_project(p.id)
    assert got.status == ProjectStatus.ready
    assert "invoicebot" in (got.brief_text or "").lower()
    assert repo.list_project_sources(p.id)[0].extracted["n_pages"] == 2


def test_render_brief_markdown():
    b = Brief(title="Acme", one_liner="AI for X", problem="P", solution="S",
              risks=["r1", "r2"], asks=["a1"], summary="sum")
    md = briefmod.render_brief(b)
    assert md.startswith("# Acme")
    for token in ("## Problem", "## Solution", "## Risks", "- r1", "## Asks", "## Summary"):
        assert token in md


# ───────────────────────── endpoints ─────────────────────────
@pytest.fixture
def client(monkeypatch):
    # Force the in-memory repo + local storage and stub auth to a fixed user.
    monkeypatch.setattr(repository, "get_supabase", lambda: None)
    monkeypatch.setattr(storage, "get_supabase", lambda: None)
    repository.get_repo.cache_clear()
    storage.get_storage.cache_clear()

    async def _noop(*a, **k):  # don't run real extraction (no network) in endpoint tests
        return None
    monkeypatch.setattr("backend.api.projects.run_extraction", _noop)
    from backend import main
    from backend.api.deps import get_current_user, get_current_user_sse
    holder = {"id": "user-1"}
    main.app.dependency_overrides[get_current_user] = lambda: holder["id"]
    main.app.dependency_overrides[get_current_user_sse] = lambda: holder["id"]
    with TestClient(main.app) as c:
        c.holder = holder  # type: ignore[attr-defined]
        yield c
    main.app.dependency_overrides.clear()
    repository.get_repo.cache_clear()
    storage.get_storage.cache_clear()


def test_create_project_requires_input(client):
    assert client.post("/projects", data={"name": "x"}).status_code == 400


def test_create_project_rejects_bad_type(client):
    r = client.post("/projects", files={"files": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_create_project_url_only(client):
    r = client.post("/projects", data={"url": "https://example.com", "name": "Site"})
    assert r.status_code == 200
    pid = r.json()["project_id"]
    detail = client.get(f"/projects/{pid}").json()
    assert detail["project"]["name"] == "Site"
    assert any(s["kind"] == "url" for s in detail["sources"])


def test_project_idor_returns_404(client):
    from backend.db.repository import get_repo
    proj = get_repo().create_project("user-1", "Private")
    assert client.get(f"/projects/{proj.id}").status_code == 200
    client.holder["id"] = "user-2"  # type: ignore[attr-defined]
    assert client.get(f"/projects/{proj.id}").status_code == 404
    assert client.patch(f"/projects/{proj.id}", json={"name": "hax"}).status_code == 404
