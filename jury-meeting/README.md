# Jury Feedback Meeting (jury-meeting/)

A standalone package in the Decision Harness monorepo. After the decision engine produces a
verdict, the team/founder behind the subject joins a **Zoom-style meeting** with the **AI
jury**. The jurors explain, *out loud*, the decision; the user asks live follow-ups — each
**routed (MAS-style) to the juror who owns it**, who answers in voice. Every turn is **traced
and graded in W&B Weave**.

**Why:** kill vague, black-box decisions. They become *weighted, evaluated, and auditable* —
and the subject gets a real conversation instead of a silent verdict.

> Independent from the engine — our only coupling is **reading the finished decision from the
> team's Supabase** (see [DB_NEEDS.md](DB_NEEDS.md)). No engine code is shared.

## Architecture

```
team Supabase  ──►  db.get_record(session_id)   (sample_decision.json offline fallback)
                         │  maps sessions.final_verdict + positions + agents
                         ▼
   record = { subject, verdict, overall_score, summary, confidence, agreements, conflicts,
              jurors:[{name, role, weight, voice_id, stance, score, rationale, influence}], trace_url }
                         │
   opening_statements ───┤ each juror voices its position (most influential first)   @weave.op
                         ▼
   orchestrator.route(question) ──► the juror who owns it ──► answer (grounded)      @weave.op
                         ▼
   each turn → ElevenLabs TTS (per voice_id) → played in the mock-Zoom room
                         └─ whole meeting Weave-traced; scorers grade routing + faithfulness
```

## Stack
W&B Inference (reasoning, auto-traced) · W&B Weave (trace/scorers/eval) · ElevenLabs (TTS/STT)
· FastAPI · single-file React (CDN) frontend · Supabase (read-only decision source).

## Setup
```bash
# from repo root (shared .venv already has deps)
source .venv/bin/activate
pip install -r jury-meeting/backend/requirements.txt
cp jury-meeting/backend/.env.example jury-meeting/backend/.env   # fill keys
```
`.env`: `WANDB_API_KEY` (+ `WANDB_ENTITY`/`WANDB_PROJECT` match the team), `ELEVENLABS_API_KEY`,
and optionally `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` (blank → runs on the sample offline).

## Run
```bash
cd jury-meeting/backend
python main.py                       # CLI meeting end-to-end → Weave trace URL
python scorers.py                    # Weave Evaluation: routing relevance + faithfulness
uvicorn api:app --reload --port 8000 # serves API + audio + the UI at http://127.0.0.1:8000/
```
The frontend is served from FastAPI at `/`, so one origin covers UI + API + audio.
Open `http://127.0.0.1:8000/?meeting_id=<session_id>` to replay a real decision;
no `meeting_id` → the offline MealMind sample.

## Inviting an applicant (tunnel, no deploy)
The mp3s are streamed over HTTP, so a tunnel forwards them like any request — nothing
extra to host. Expose the single port and send the link:
```bash
cloudflared tunnel --url http://127.0.0.1:8000      # prints https://<sub>.trycloudflare.com
```
Join link → `https://<sub>.trycloudflare.com/?meeting_id=<session_id>`.

**Next phase (not built yet):** a `POST /meeting/invite {meeting_id, email}` endpoint that
emails this link via a provider (Resend/SMTP), so the applicant is notified automatically
once the engine finishes their decision.

## Files
| Path | Role |
|------|------|
| `backend/db.py` | reads the team's Supabase → record (sample fallback) |
| `backend/sample_decision.json` | offline decision record (a VC panel declining "MealMind") |
| `backend/llm.py` | W&B Inference client |
| `backend/agents.py` | persona-driven juror `explain`/`answer`, `@weave.op` |
| `backend/orchestrator.py` | routing + meeting flow, `@weave.op` |
| `backend/scorers.py` | Weave scorers + Evaluation |
| `backend/voice.py` | ElevenLabs TTS/STT |
| `backend/api.py` | FastAPI `/meeting/init`, `/meeting/ask` |
| `frontend/index.html` | mock-Zoom UI |
| `DB_NEEDS.md` | the fields we read from the team DB (feedback for the engine owner) |
