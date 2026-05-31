# Project Brief Ingestion — Design Spec

**Date:** 2026-06-01
**Status:** Approved design, pending implementation plan
**Author:** Brainstormed with the user; external contracts hardened by the `harden-ingest-pipeline` validation workflow (run `wf_99e14534-f1c`).

---

## 1. Problem & goal

Today, agents are given the **question** but almost never real **context** — the `CONTEXT:` slot in [agent_runner.py:56-57](../../../backend/engine/agent_runner.py) is usually `(none provided)`. A council asked "Should this project win Most Sophisticated Harness?" is judging a project it has never seen.

The project's substance lives in two artifacts founders already have: a **slide deck (PDF)** and a **demo video (MP4)**. The goal: let a user attach those in the composer; before the council convenes, a pipeline **extracts the whole idea** (problem, solution, traction, tech, risks, asks) from both — text, slide visuals, spoken narration, and on-screen frames — and a **single synthesis model fuses it all into one clean, structured brief**. That brief is reusable across many questions/councils, human-reviewable/editable, and flows into the agents through the **existing `context` seam with zero debate-engine changes**.

### Non-goals (v1)
- Real-time / streaming transcription during recording.
- Editing the council from this flow (unchanged).
- Multi-process SSE fan-out (still single-process pub/sub; ROADMAP's Supabase Realtime swap is out of scope).
- OCR tuning, scene-graph extraction, or speaker diarization beyond what Whisper/the vision model give for free.

---

## 2. Key decisions (locked)

| Decision | Choice | Why |
|---|---|---|
| Extraction fidelity | **Full multimodal** | PDF text + slide vision + video transcript + sampled keyframes. |
| Third source (added) | **Website URL via Firecrawl** | Optional `kind="url"` source — scrape a landing page to markdown (reuses `firecrawl_api_key`, called over httpx) and fold it into the same brief. Added because the user provisioned a Firecrawl key. Degrades to '' with no key. |
| Relationship to debates | **Reusable, first-class Project Brief** | One project, many questions/councils. Pay extraction once; re-ask freely. Fits the "fully-inspectable" ethos. |
| Vision (slides + frames) | **W&B Inference `google/gemma-4-31B-it`** (primary), `moonshotai/Kimi-K2.6` (fallback) | Llama-4-Scout is **gone** from the live catalog (verified: 25 models, 404 on Scout). Both chosen models read base64 images + JSON-mode cleanly through the installed `openai 2.38.0`. **Qwen vision avoided** — it trips a `NoneType` parse bug in that SDK version. |
| Audio transcription (ASR) | **Groq Whisper `whisper-large-v3-turbo`** (primary) → **ElevenLabs Scribe** (existing, fallback) → mock | User added a `GROQ` key. Groq = audio **only**; never touches agents. Scribe is already built ([transcription.py](../../../backend/engine/transcription.py)) — kept free as a no-ffmpeg fallback. |
| Synthesis | **One model fuses all sources → one clean structured brief** | Per user: not mechanical concatenation — a single LLM pass produces one coherent context. |
| Object storage | **Supabase Storage** bucket `project-briefs` (private) → local-disk/in-memory fallback | S3-equivalent, already wired (service key). Zero-keys boot preserved. |
| PDF library | **pypdfium2 + Pillow** (permissive Apache/BSD) | DecisiveAI is a deployed SaaS with signups → avoid PyMuPDF's AGPL network-clause obligation. (Override to `pymupdf` only if the repo goes open-source or a commercial license is held.) |
| Video ffmpeg | **`imageio-ffmpeg`** (bundled static binary) | Audio extraction + keyframe sampling with **no `apt-get`** — Dockerfile stays system-package-free. |
| Upload transport | **One-step multipart `POST /projects`** (new router) | Isolates multipart to the projects router; the frozen `POST /sessions` JSON contract is untouched. |
| Convene UX | **Review-the-brief-then-Convene** (human-in-the-loop) | User edits/trims the extracted brief before agents see it. |

### Central invariant (must hold)
**The entire stack still boots and runs with zero API keys.** Every new subsystem is lazy-imported and gated behind a `settings.*_enabled` property. No key → that stage no-ops and the council runs on the question alone (current behavior).

---

## 3. Architecture: generalize the proven seam

The repo **already** does file → transcript → `context` → debate in [sessions.py:54-87](../../../backend/api/sessions.py) (`POST /sessions/from-video`, ElevenLabs Scribe). This feature **generalizes that seam** to: multiple files, PDF decks, video vision, Groq ASR, and a persisted, editable, reusable brief. The existing single-video endpoint keeps working unchanged.

```
Composer (deck.pdf + demo.mp4 + name)
        │  multipart
        ▼
POST /projects ──► store bytes (Supabase Storage | local)  +  projects row (status=extracting)
        │                                                      + project_sources rows
        │  asyncio.create_task(_extract_brief(project_id))
        ▼
Extraction pipeline  (@weave.op, progress via stream.publish(project_id, …))
  PDF   ─► pypdfium2 text  + page→PNG ─► vision(gemma-4) ─┐
  MP4   ─► imageio-ffmpeg: audio→FLAC ─► Groq Whisper ────┤─► SYNTHESIZE (one W&B text call)
          imageio-ffmpeg: keyframes  ─► vision(gemma-4) ──┘        │
        ▼                                                          ▼
GET /projects/{id}/stream (SSE)  ──►  brief_ready          brief (jsonb) + brief_text (md)
        ▼
User reviews/edits brief  ──► PATCH /projects/{id}
        ▼
POST /sessions { …, project_id }  ──► context = project.brief_text  ──► existing run_debate (UNCHANGED)
```

---

## 4. Data model

### New table `projects`
| column | type | notes |
|---|---|---|
| `id` | uuid pk | |
| `owner_id` | uuid | plain uuid (like `sessions.created_by`) so DEMO_USER works; **not** an FK to `auth.users`. |
| `name` | text | defaults from first filename. |
| `status` | text | `pending` → `extracting` → `ready` / `failed`. |
| `brief` | jsonb | structured: `{problem, solution, market, traction, tech, risks, asks, summary}`. |
| `brief_text` | text | the brief rendered to markdown — **this becomes `session.context`** (editable). |
| `error` | text null | failure detail for the UI. |
| `created_at` | timestamptz | default `now()`. |

### New table `project_sources`
| column | type | notes |
|---|---|---|
| `id` | uuid pk | |
| `project_id` | uuid | FK → `projects(id)` **`on delete cascade`** (per the FK rule in CLAUDE.md). |
| `kind` | text | `pdf` \| `video`. |
| `filename` | text | original name. |
| `content_type` | text | `application/pdf` \| `video/mp4`. |
| `storage_path` | text | object key in the bucket (or local path). |
| `content_hash` | text | sha256 — dedupe / future re-extraction cache. |
| `bytes` | int | size. |
| `extracted` | jsonb null | per-source intermediate (transcript, page texts, vision notes) — for inspection/Weave. |
| `created_at` | timestamptz | |

### Changed table `sessions`
- Add **`project_id uuid references projects(id) on delete set null`** (provenance: which brief grounded this debate). `set null` keeps the FK rule consistent with `parent_session`.

### Migrations
- Add the DDL to **both** [backend/db/migrations.sql](../../../backend/db/migrations.sql) (with the self-healing `ALTER` for the new FK rule) **and** a new timestamped file under [supabase/migrations/](../../../supabase/migrations/). Keep them in sync (CLAUDE.md §Database).

### Contract (frozen seam — update all three together)
- [backend/schemas.py](../../../backend/schemas.py): `Project`, `ProjectSource`, `Brief`, `CreateProjectResponse`, `UpdateProjectRequest`; add `project_id: Optional[str] = None` to `CreateSessionRequest` and `Session`; add the new extraction `EventType` (below).
- [frontend/lib/types.ts](../../../frontend/lib/types.ts): mirror exactly.
- [docs/CONTRACT.md](../../../docs/CONTRACT.md): document the new models + event taxonomy.

---

## 5. Storage layer

A new `Storage` abstraction mirroring `get_repo()`:

- `get_storage()` → `SupabaseStorage` when `settings.supabase_enabled`, else `LocalStorage` (writes under a gitignored `./.uploads/`), and in tests an in-memory variant.
- Interface: `put(path, data: bytes, content_type) -> path`, `get(path) -> bytes`, `signed_url(path, ttl) -> str | None`, `remove(path)`.
- **SupabaseStorage** uses the existing sync `get_supabase()` client (supabase-py 2.30.1):
  - Ensure the **private** bucket `project-briefs` once at startup, idempotently (`list_buckets()` then `create_bucket(..., {"public": False, "allowed_mime_types": ["application/pdf","video/mp4"], "file_size_limit": ...})` — `create_bucket` raises if it exists).
  - `upload(path, bytes, {"content-type": ct, "upsert": "true"})` — **hyphenated, string-valued** file_options.
  - `download(path) -> bytes`; `create_signed_url(path, ttl)["signedURL"]` (canonical key is uppercase `signedURL`).
  - Object keys are **server-derived**: `{owner_id}/{project_id}/{kind}-{n}.{ext}` — never trust a client path.
- **Security:** the service key **bypasses Storage RLS**, so ownership is enforced in the app (`deps.py`, 404-not-403), exactly like the repository.
- **Async safety:** supabase-py is sync; all Storage/repo calls inside the async extraction task go through `asyncio.to_thread(...)` (copy [sessions.py:77](../../../backend/api/sessions.py)).
- **Size ceiling:** Supabase's default global standard-upload limit is **50 MB**. For v1, cap MP4 at 50 MB (see §10 product params); larger needs the global limit raised (per-bucket can only lower it).

---

## 6. Extraction pipeline

New module(s) under `backend/engine/` — each function `@weave.op()`-decorated and routed through a resolver so tests mock it offline.

### 6.1 PDF (`pdf.py`)
- `pypdfium2.PdfDocument(bytes)`; per page: `get_textpage().get_text_bounded()` for embedded text, `page.render(scale=dpi/72).to_pil()` → JPEG bytes (q70, long side ~1024px) via Pillow.
- Render **one page at a time**, encode, discard (RAM control). Cap at ~20-25 pages. Empty text on scanned decks is expected — the rendered image is the vision fallback.
- Wrap import + parse in `try/except` so a malformed PDF degrades (skip) rather than crashing the keyless boot path.

### 6.2 Video (`video.py`)
- `FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()`.
- **Audio:** write bytes to a `NamedTemporaryFile(suffix=".mp4")` (mp4 needs a seekable input — no stdin piping), then `ffmpeg -y -i in.mp4 -ar 16000 -ac 1 -map 0:a -c:a flac out.flac` (Groq's documented preprocessing; 2-5 min talk ≈ 5-15 MB FLAC, under the 25 MB Groq cap). A slide-only screen-recording with **no audio stream** → ffmpeg exits non-zero → treat as "no transcript", degrade.
- **Frames:** shell the same binary: `ffmpeg -y -i in.mp4 -vf "fps=1/20,scale=768:-1" -q:v 3 f_%03d.jpg` (one frame / 20 s). Hard-cap ~10-12 frames. (Single-dependency: no PyAV — saves a redundant bundled ffmpeg.)
- Always set a subprocess **timeout** so a malformed upload can't hang the task.

### 6.3 ASR (`asr.py`) — provider resolver
- `transcribe(data, filename) -> str` picks: **Groq** if `settings.groq_enabled` → else **ElevenLabs Scribe** (`transcribe_media`) if `settings.transcription_enabled` → else `""` (mock/empty).
- Groq: `AsyncGroq(api_key=settings.groq_api_key)` (read from `GROQ`), `await client.audio.transcriptions.create(file=(name, flac_bytes), model="whisper-large-v3-turbo", response_format="text", language="en", temperature=0)`. Pass the key **explicitly** (the SDK's default env name is `GROQ_API_KEY`, ours is `GROQ`).
- Refactor `transcription.py` so Scribe lives behind this resolver; the existing `/sessions/from-video` keeps working.

### 6.4 Vision (`vision.py`) — **separate** from `complete_json`
- `describe_images(images: list[bytes], instruction, schema) -> dict` using the existing `_wandb_client` (`AsyncOpenAI`, base_url `https://api.inference.wandb.ai/v1`).
- One text instruction + N `image_url` base64 blocks in a single user message; `response_format={"type":"json_object"}`; `max_tokens >= 1500` (a low cap yields `finish_reason="length"` and empty JSON that looks like a vision failure).
- Model = `settings.vision_model` (`google/gemma-4-31B-it`) with fallback `moonshotai/Kimi-K2.6`. **Do not** route vision through `complete_json` — that path is pinned to the text-only `inference_model` (gpt-oss-120b). Never resolve to a Qwen id (SDK parse bug).
- Routed through `resolve_backend()` → deterministic **mock brief** (filename + first-line text) when `wandb_api_key` is absent.

### 6.5 Synthesis (`brief.py`) — one clean context
- Inputs: PDF text, slide-vision JSON, video transcript, frame-vision JSON.
- **One** W&B text call (`complete_json`, `temperature=0`, JSON schema) fuses everything into the structured `brief` dict, then renders `brief_text` markdown (mirrors `full_context = "PITCH VIDEO TRANSCRIPT:\n…"`). Mock path returns a deterministic brief offline.
- `_extract_brief(project_id)` orchestrates: load sources → run PDF/video branches (gather) → synthesize → persist `brief`/`brief_text`/`status=ready` → `stream.publish` progress throughout → `stream.close`.

---

## 7. API surface

New router `backend/api/projects.py`, mounted in [main.py](../../../backend/main.py).

| Endpoint | Body | Purpose |
|---|---|---|
| `POST /projects` | **multipart**: `name?` (Form), `files: list[UploadFile]` (`.pdf`/`.mp4`) | Validate type/size (415/413), stream-read in 1 MB chunks, store bytes, create `projects` + `project_sources`, `asyncio.create_task(_extract_brief)`, return `{project_id}`. |
| `GET /projects/{id}/stream` | — | SSE: replay progress history, then live (`source_received` → `transcribing` → `reading_slides` → `synthesizing` → `brief_ready`/`failed`). Same pub/sub as debates, keyed by `project_id`. |
| `GET /projects/{id}` | — | Project + `brief` + `brief_text`. |
| `PATCH /projects/{id}` | JSON `{name?, brief_text?}` | Persist the user's reviewed/edited brief. |
| `GET /projects` | — | List owner's projects (the "reuse a past project" dropdown). |
| `POST /sessions` | JSON, **+ optional `project_id`** | If set: `context = project.brief_text`; record `project_id` on the session. Otherwise unchanged. |

- Ownership on every route via `deps.py` (404-not-403). `GET …/stream` uses `get_current_user_sse` like sessions.
- Server-side validation re-checks `content_type` ∈ {`application/pdf`,`video/mp4`} with a **filename-extension fallback** (browsers send `""`/`application/octet-stream` for `.mp4`) and enforces `MAX_BYTES`.

### Progress events
- New `EventType.extraction` (value `"extraction"`) carrying `{stage, detail, progress}`. Add to `schemas.py`, `frontend/lib/types.ts` `EVENT_NAMES`, and `CONTRACT.md`. (Alternative considered: reuse `orchestrator` to avoid touching the contract — rejected for clarity/inspectability.)
- Progress is **streamed**; durable replay is via the `projects.status` snapshot on (re)connect (full per-event persistence for extraction is out of scope for v1).

---

## 8. Frontend

- [Composer.tsx](../../../frontend/components/Composer.tsx): a file input (`accept=".pdf,.mp4"`, multiple) + a "reuse a past project" `<select>` populated from `GET /projects`. Client-side validation (type + extension regex + per-type size cap) as a UX hint only.
- New `postForm()` helper in [api.ts](../../../frontend/lib/api.ts) that sets **only** `Authorization` (never `Content-Type` — the browser sets the multipart boundary). The existing `j()` JSON helper is **not** reused for uploads. Add `createProject`, `streamProject`, `getProject`, `updateProject`, `listProjects`.
- **Brief-review surface:** after upload, a "Preparing the brief…" phase streams extraction events; then the structured brief renders with an **editable `brief_text`** box. **Convene** is gated until the user accepts; on accept → `PATCH /projects/{id}` then `POST /sessions {project_id}`.
- [useEventStream.ts](../../../frontend/lib/useEventStream.ts): handle the `extraction` event (or a small `useProjectStream`).

---

## 9. Config, deps, deploy

### `backend/config.py`
```python
groq_api_key: str = Field("", validation_alias=AliasChoices("GROQ", "GROQ_API_KEY"))
groq_model: str = "whisper-large-v3-turbo"
vision_model: str = "google/gemma-4-31B-it"
vision_model_fallback: str = "moonshotai/Kimi-K2.6"
storage_bucket: str = "project-briefs"
# properties:
groq_enabled        -> bool(groq_api_key)
vision_enabled      -> bool(wandb_api_key)
asr_enabled         -> groq_enabled or transcription_enabled   # transcription_enabled already exists (ElevenLabs)
```
- **Move `GROQ` into `backend/.env`** (today it's only in the root `.env`, which `get_settings()` does not read).

### `backend/requirements.txt` (add)
- `groq` — Whisper SDK (provides `AsyncGroq`).
- `pypdfium2>=5.8.0` + `pillow` (pin; already transitively present).
- `imageio-ffmpeg` — bundled static ffmpeg (audio + frames).
- `python-multipart` — **pin explicitly** (currently only transitive; FastAPI `Form()/File()` routes fail at startup without it, and the Dockerfile installs only this file — the existing from-video silently relies on it too).

### Dockerfile
- **No new `apt` lines.** `imageio-ffmpeg`, `pypdfium2`, and `pillow` all ship manylinux wheels that install on `python:3.11-slim` with plain pip. The only change is the expanded `requirements.txt` it already installs. (Note: ~30 MB image growth from the bundled ffmpeg — acceptable.)

### `.gitignore`
- Add `.uploads/` (local-storage fallback dir). `.env`/`.env.local` already ignored.

---

## 10. Product parameters (sensible defaults; tune later)
- **Size caps:** PDF ≤ 25 MB, MP4 ≤ 50 MB (Supabase global standard-upload ceiling). Surface a friendly 413 over the cap. Verify no smaller Railway/proxy body limit truncates uploads.
- **Page cap:** first ~20-25 slides to the vision model.
- **Frame cap:** ~10-12 keyframes @ 768px.
- **Video length:** tuned for ≤ ~5 min demos (FLAC stays under Groq's 25 MB). Longer → audio chunking (future).

---

## 11. Graceful-degradation matrix

| Missing | Behavior |
|---|---|
| `GROQ` | ASR falls back to ElevenLabs Scribe; if that's also unset → no transcript, brief uses slides + frames only. |
| `WANDB_API_KEY` | Vision + synthesis mock → deterministic brief (filenames + extracted text). |
| `SUPABASE_*` | `LocalStorage` (`./.uploads/`) + `InMemoryRepository`; brief lives in memory. Boots fine. |
| `ELEVENLABS_API_KEY` | Only matters if Groq is also unset. |
| ffmpeg binary | Shipped by `imageio-ffmpeg`; if even that fails, video degrades to "no transcript/frames" and PDF still works. |
| **All keys absent** | Whole pipeline no-ops; council runs on the question alone (today's behavior). |

---

## 12. Testing (keep the "no-network" suite green)
- Force offline by monkeypatching `resolve_backend → None` (existing pattern) **and** the ASR/vision resolvers → mock. Extraction code must call resolvers by module attribute so tests can patch them.
- `InMemoryRepository` project CRUD tests.
- `LocalStorage` round-trip test (put/get/remove).
- `POST /projects` multipart endpoint test (type/size validation, source rows).
- Mock extraction → deterministic brief; assert `brief_text` populated and `status=ready`.
- End-to-end happy path: create project (mock) → `POST /sessions {project_id}` → debate uses `brief_text` as context → verdict.
- IDOR: another user can't read/patch/stream a project (404).

---

## 13. Risks & mitigations
- **Vision catalog drift** — model ids change (Scout already vanished). Mitigate: `vision_model` is a setting with a fallback; resolver mocks when absent; a startup log warns if `vision_model` isn't in `models.list`.
- **`python-multipart` only transitive** — pin it, or all Form/File routes (new **and** existing from-video) 500 at startup.
- **supabase-py is sync inside async tasks** — every Storage/repo call wrapped in `asyncio.to_thread`, or the live SSE stream stalls.
- **mp4 with no audio / non-seekable input** — caught; degrade, don't crash.
- **Cost/quota** — Groq free tier 2 hr/hr & 25 MB/file; vision bills each image against a 262K window. Downscale frames to 768px JPEG, cap counts; Weave logs the spend.
- **In-process pub/sub** — extraction progress only reaches subscribers on the same process (single-instance Railway today; ROADMAP's Realtime swap covers scale-out).

---

## 14. Out of scope / future
- Audio chunking for long videos; scene-change frame selection.
- Content-hash extraction cache (the `content_hash` column is laid down now for it).
- Per-event durable extraction history (vs. status snapshot).
- Injecting the brief into later rounds (currently round-0 only, matching today's `context` behavior).
