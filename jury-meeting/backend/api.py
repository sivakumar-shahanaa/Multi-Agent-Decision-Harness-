"""FastAPI backend connecting the mock-Zoom frontend to the jury meeting.

    uvicorn api:app --reload --port 8000   (run from backend/)

Endpoints:
  POST /meeting/init  {meeting_id?}            -> record summary + voiced openings
  POST /meeting/ask   {meeting_id?, question}  -> routed, voiced juror answer
  GET  /audio/<file>                           -> served mp3
  GET  /health
"""
from __future__ import annotations

import os
from pathlib import Path

import weave
from dotenv import load_dotenv
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import notify
import orchestrator
import voice
from llm import PROJECT_PATH

load_dotenv()

# Public origin used to build the applicant's join link in invite emails. Set it to
# the tunnel / Vercel URL in prod; falls back to the request's own origin (so a local
# `http://127.0.0.1:8000` invite still produces a working link in dev).
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
# Demo recipient: the Convene button doesn't collect an applicant address, so the
# invite goes here unless the request overrides it.
DEMO_APPLICANT_EMAIL = os.getenv("DEMO_APPLICANT_EMAIL", "")

# Init Weave once at import so every request is traced. Tolerate a missing key
# so the server still boots for a text-only / no-key smoke test.
try:
    weave.init(PROJECT_PATH)
except Exception as e:  # noqa: BLE001
    print(f"[warn] weave.init failed ({e}); continuing without tracing.")

app = FastAPI(title="Decision Harness — Jury Meeting")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/audio", StaticFiles(directory=voice.AUDIO_DIR), name="audio")


class InitReq(BaseModel):
    meeting_id: str | None = None


class AskReq(BaseModel):
    meeting_id: str | None = None
    question: str


class InviteReq(BaseModel):
    meeting_id: str | None = None
    email: str | None = None  # falls back to DEMO_APPLICANT_EMAIL


def _record(meeting_id: str | None) -> dict:
    # Reads the team DB (Supabase) by id, or the local sample when unset/unconfigured.
    return orchestrator.load_record(meeting_id)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "project": PROJECT_PATH}


@app.post("/meeting/init")
def meeting_init(req: InitReq) -> dict:
    record = _record(req.meeting_id)
    openings = [voice.voice_turn(t) for t in orchestrator.opening_statements(record)]
    return {
        "meeting_id": record.get("meeting_id"),
        "subject": record.get("subject"),
        "verdict": record.get("verdict"),
        "overall_score": record.get("overall_score"),
        "summary": record.get("summary"),
        "jurors": record.get("jurors"),
        "trace_url": record.get("trace_url"),
        "openings": openings,
    }


@app.post("/meeting/ask")
def meeting_ask(req: AskReq) -> dict:
    record = _record(req.meeting_id)
    turn = voice.voice_turn(orchestrator.ask(req.question, record))
    return turn


@app.post("/meeting/invite")
async def meeting_invite(req: InviteReq, request: Request) -> dict:
    """Email the applicant their decision + a link to join the feedback meeting.

    Operator-triggered (the /admin page). The join link is
    `<base>/?meeting_id=<session_id>`, base = PUBLIC_BASE_URL or this request's origin.
    """
    record = _record(req.meeting_id)
    base = PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    mid = req.meeting_id or record.get("meeting_id")
    join_url = f"{base}/?meeting_id={mid}" if mid else base + "/"
    recipient = req.email or DEMO_APPLICANT_EMAIL
    result = await notify.send_invite(record, recipient, join_url)
    return {"verdict": record.get("verdict"), "join_url": join_url, **result}


@app.post("/voice/transcribe")
async def voice_transcribe(audio: UploadFile = File(...)) -> dict:
    """Mic input -> ElevenLabs Scribe STT -> the question text the UI then asks."""
    data = await audio.read()
    text = voice.transcribe(data, filename=audio.filename or "question.webm")
    return {"text": text}


# Serve the single-file frontend from this same origin, mounted LAST so it never
# shadows the API routes or /audio above. One process + one tunnel
# (`cloudflared --url http://127.0.0.1:8000`) then exposes UI + API + audio
# together, so a remote applicant's join link just works.
_FRONTEND_DIR = Path(__file__).parents[1] / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="ui")
