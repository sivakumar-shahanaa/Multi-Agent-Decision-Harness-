"""Fuse the extracted sources (deck text + slide visuals + demo transcript + demo
frames + website) into ONE structured Brief via a single W&B Inference text call,
then render it to the markdown that becomes session.context.

Orchestration runs as a background asyncio task (kicked off by the /projects router),
streaming progress over the same pub/sub the debate uses (keyed by project_id). Every
blocking repo/storage call is wrapped in asyncio.to_thread. With no keys (or empty
sources) it produces a deterministic mock brief so the council still convenes.
"""
from __future__ import annotations

import asyncio

import weave

from ...config import get_settings
from ...schemas import Brief, ProjectStatus, SourceKind
from ..llm import complete_json, resolve_backend
from ..stream import close as close_stream
from ..stream import publish
from . import asr, pdf, video, vision, web

_MAX_SLIDE_IMAGES = 20
_MAX_SOURCE_CHARS = 24000

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "one_liner": {"type": "string"},
        "problem": {"type": "string"},
        "solution": {"type": "string"},
        "market": {"type": "string"},
        "traction": {"type": "string"},
        "tech": {"type": "string"},
        "business_model": {"type": "string"},
        "team": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "asks": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["one_liner", "problem", "solution", "summary"],
}


def _emit(project_id: str, stage: str, detail: str = "", progress: float = 0.0) -> None:
    publish(project_id, {"type": "extraction", "content": {
        "stage": stage, "detail": detail, "progress": progress}})


@weave.op()
async def run_extraction(project_id: str, repo, storage) -> None:
    """Background pipeline: read every source → synthesize → persist brief → stream."""
    try:
        await asyncio.to_thread(repo.update_project, project_id, status=ProjectStatus.extracting)
        _emit(project_id, "started", "Reading your materials…", 0.05)
        sources = await asyncio.to_thread(repo.list_project_sources, project_id)

        deck_text, slide_imgs = "", []
        transcript, frame_imgs = "", []
        web_md = ""

        for src in sources:
            if src.kind == SourceKind.pdf and src.storage_path:
                _emit(project_id, "reading_slides", f"Reading {src.filename}…", 0.2)
                data = await asyncio.to_thread(storage.get, src.storage_path)
                res = await asyncio.to_thread(pdf.extract_pdf, data)
                deck_text += res.get("text", "")
                slide_imgs += [p["image"] for p in res.get("pages", []) if p.get("image")]
                await asyncio.to_thread(repo.update_project_source, src.id, extracted={
                    "n_pages": res.get("n_pages", 0), "chars": len(res.get("text", ""))})
            elif src.kind == SourceKind.video and src.storage_path:
                _emit(project_id, "transcribing", f"Transcribing {src.filename}…", 0.4)
                data = await asyncio.to_thread(storage.get, src.storage_path)
                transcript = await asr.transcribe(data, src.filename)
                _emit(project_id, "watching", "Sampling the demo…", 0.55)
                frame_imgs = await asyncio.to_thread(video.sample_frames, data)
                await asyncio.to_thread(repo.update_project_source, src.id, extracted={
                    "transcript_chars": len(transcript), "frames": len(frame_imgs)})
            elif src.kind == SourceKind.url:
                target = src.storage_path or src.filename
                _emit(project_id, "reading_site", f"Reading {target}…", 0.5)
                web_md = await web.scrape_url(target)
                await asyncio.to_thread(repo.update_project_source, src.id, extracted={
                    "chars": len(web_md)})

        slide_desc, frame_desc = "", ""
        if slide_imgs:
            _emit(project_id, "reading_slides", "Reading the slide visuals…", 0.65)
            slide_desc = await vision.describe_images(
                slide_imgs[:_MAX_SLIDE_IMAGES],
                "These are pages from a startup pitch deck. Describe in detail the "
                "product, the problem, the solution, the market, traction/metrics, the "
                "team, and anything shown in diagrams, charts, or screenshots.")
        if frame_imgs:
            _emit(project_id, "watching", "Reading the demo screen…", 0.72)
            frame_desc = await vision.describe_images(
                frame_imgs,
                "These are frames from a product demo video. Describe what the product "
                "is, what it does, and what is shown on screen.")

        _emit(project_id, "synthesizing", "Writing the brief…", 0.85)
        brief = await _synthesize(project_id, repo, deck_text, slide_desc,
                                  transcript, frame_desc, web_md)
        brief_text = render_brief(brief)
        await asyncio.to_thread(repo.update_project, project_id,
                                status=ProjectStatus.ready, brief=brief, brief_text=brief_text)
        _emit(project_id, "ready", "Brief ready for review.", 1.0)
    except Exception as exc:  # never crash the task — record + surface
        await asyncio.to_thread(repo.update_project, project_id,
                                status=ProjectStatus.failed, error=str(exc))
        _emit(project_id, "failed", str(exc), 1.0)
    finally:
        close_stream(project_id)


async def _synthesize(project_id: str, repo, deck_text: str, slide_desc: str,
                      transcript: str, frame_desc: str, web_md: str) -> Brief:
    proj = await asyncio.to_thread(repo.get_project, project_id)
    name = proj.name if proj else "this project"
    raw = "\n\n".join(s for s in [
        f"SLIDE DECK TEXT:\n{deck_text}" if deck_text else "",
        f"SLIDE VISUALS (read by a vision model):\n{slide_desc}" if slide_desc else "",
        f"DEMO VIDEO TRANSCRIPT:\n{transcript}" if transcript else "",
        f"DEMO VIDEO SCREEN (read by a vision model):\n{frame_desc}" if frame_desc else "",
        f"WEBSITE:\n{web_md}" if web_md else "",
    ] if s)

    backend = resolve_backend("wandb")
    if not raw.strip() or backend is None:
        return _mock_brief(name, raw)

    system = (
        "You are a diligence analyst preparing a council to evaluate a project. From "
        "the multimodal source material below, produce ONE clean, factual brief. Do not "
        "invent facts — if a field is unknown from the sources, leave it empty. Be concise "
        "and concrete.")
    prompt = (f"PROJECT NAME: {name}\n\nSOURCE MATERIAL:\n{raw[:_MAX_SOURCE_CHARS]}\n\n"
              "Produce the structured brief.")
    try:
        data = await asyncio.wait_for(
            complete_json(backend, get_settings().inference_model, system, prompt, BRIEF_SCHEMA),
            timeout=120)
        return _coerce_brief(data, name)
    except Exception:  # incl. TimeoutError — degrade to the deterministic mock
        return _mock_brief(name, raw)


def _coerce_brief(data: dict, name: str) -> Brief:
    def s(key: str) -> str:
        v = data.get(key, "")
        return v.strip() if isinstance(v, str) else ""

    def lst(key: str) -> list[str]:
        v = data.get(key) or []
        return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []

    return Brief(
        title=s("title") or name, one_liner=s("one_liner"), problem=s("problem"),
        solution=s("solution"), market=s("market"), traction=s("traction"),
        tech=s("tech"), business_model=s("business_model"), team=s("team"),
        risks=lst("risks"), asks=lst("asks"), summary=s("summary"))


def _mock_brief(name: str, raw: str) -> Brief:
    """Deterministic brief when no model is configured (or nothing was extracted)."""
    snippet = " ".join(raw.split())[:600]
    summary = (snippet or f"No source material could be extracted for {name}. The council "
               "will deliberate on the question with the project name only.")
    return Brief(title=name, one_liner=f"{name} (auto-summary; no model configured)",
                 summary=summary)


def render_brief(brief: Brief) -> str:
    """Render the structured brief to the markdown that becomes session.context."""
    lines: list[str] = [f"# {brief.title or 'Project Brief'}"]
    if brief.one_liner:
        lines.append(f"_{brief.one_liner}_")
    sections = [
        ("Problem", brief.problem), ("Solution", brief.solution),
        ("Market", brief.market), ("Traction", brief.traction),
        ("Technology", brief.tech), ("Business model", brief.business_model),
        ("Team", brief.team),
    ]
    for heading, body in sections:
        if body:
            lines.append(f"\n## {heading}\n{body}")
    if brief.risks:
        lines.append("\n## Risks\n" + "\n".join(f"- {r}" for r in brief.risks))
    if brief.asks:
        lines.append("\n## Asks\n" + "\n".join(f"- {a}" for a in brief.asks))
    if brief.summary:
        lines.append(f"\n## Summary\n{brief.summary}")
    return "\n".join(lines).strip()
