# Company Brain — Build Roadmap & Technical Spec
**Multi-Agent Orchestration Build Day · May 31, 2026 · 5-hour build · 4 engineers**

Working title: **Company Brain** (alt names to vote on: *Quorum*, *Council*, *Conclave*).
One-liner: *Assemble a board of AI specialists, pose a decision, watch them debate in a live voice "boardroom," and get a weighted, fully-inspectable verdict you can replay, audit, and re-run.*

---

## 0. What this is (and how it differs from the developer brief)

The developer brief (`developer_brief.md.pdf`) describes a **stateless single-question toy**. The real product (`product_specs.md`) is a **configurable agent organization** that debates and whose every reasoning step is inspectable. The brief is wrong on several points — corrected here:

| Developer brief says | Reality (this roadmap) | Why |
|---|---|---|
| "No database" | **Supabase Postgres** | You cannot inspect/replay/compare a decision that was never stored. The transcript *is* the product. |
| "No auth" | **Supabase Auth + RLS** | "Easy to create new agents for a new company" = multi-org, multi-user. Each org's agents/sessions are private. |
| "No persistence needed" | **Full event log persisted** | The inspector, influence graph, re-runs, and side-by-side comparison all read from persisted events. |
| "5 agents, fixed" | **N configurable agents per org** | Product is a *team builder*: VC committee, board, judge panel — user-defined roles, weights, voices. |
| "One question → one verdict" | **Multi-round debate w/ peer messaging** | Spec requires "which agent influenced others." That only exists if agents can see & rebut each other across rounds. |
| Frontend calls Claude API directly | **Next.js → FastAPI → agents** | Auth, persistence, streaming, Weave tracing all live server-side. |

What we **keep** from the brief: the weighted-scoring idea, the human-in-the-loop weight/context override + live re-run, and full W&B Weave instrumentation (already set up — see `main.py`).

---

## 1. Judging alignment (design every feature to hit these)

| Criterion | How we win it |
|---|---|
| **Agent Orchestration** | Claude Agent SDK subagents debating over N rounds, peer-to-peer questions, MCP tool calls, a weighted orchestrator that detects conflict and converges. The orchestrator is itself exposable as an MCP server. |
| **Utility** | Real decision tool: investment committees, hiring panels, board votes, hackathon judging. Demo question: *"Should this project win Most Sophisticated Harness?"* |
| **Technical Execution** | FastAPI + Next.js + Supabase + Weave + live voice. Streaming, persistence, auth, replay. |
| **Creativity** | A *configurable* AI org + a **live voice boardroom** where agents argue out loud in a Zoom/Meet, plus a visual **influence graph** of who swayed whom. |
| **Sponsor Usage** | **W&B Weave** (tracing + evals + monitors), **W&B Inference** (some agents run on open models for a genuinely diverse panel), **Claude Agent SDK**, **MCP** (tools + W&B MCP as an agent tool). |
| **Best Use of Weave ($1k)** | Every op traced; 4 custom scorers; `weave.Evaluation` across org configs; online monitor on live sessions; deep-link from each session to its Weave trace. |

---

## 2. Architecture

```
                         ┌──────────────────────────────────────────────┐
                         │                Next.js (Vercel)               │
                         │  Auth · Org Builder · Boardroom(live) ·        │
                         │  Inspector · Influence Graph · Verdict/HITL    │
                         └───────────────┬───────────────┬──────────────┘
                          REST + SSE     │               │  Supabase JS (auth + realtime)
                                         ▼               ▼
                         ┌──────────────────────────┐  ┌─────────────────────────────┐
                         │      FastAPI backend      │  │     Supabase (Postgres)     │
                         │  /orgs /agents /sessions  │──│  orgs agents sessions       │
                         │  SSE event stream         │  │  events positions (RLS)     │
                         │  Supabase JWT auth        │  │  Auth · Realtime            │
                         └────────────┬──────────────┘  └─────────────────────────────┘
                                      │ writes events
                                      ▼
                    ┌─────────────────────────────────────────┐        ┌────────────────────┐
                    │   Debate Engine (Python, @weave.op)      │ traces │   W&B Weave         │
                    │   Claude Agent SDK subagents + rounds    │───────▶│  traces · evals ·   │
                    │   peer requests · MCP tools · orchestr.  │        │  monitors           │
                    └───────────────┬───────────┬─────────────┘        └────────────────────┘
                       MCP tools     │           │ model calls
                          ▼          │           ▼
              ┌────────────────┐     │   ┌──────────────────────────┐
              │ MCP servers    │     │   │ Models                   │
              │ research/search│     │   │ Claude (Agent SDK) +      │
              │ company-data   │     │   │ W&B Inference (open mdls) │
              │ W&B MCP        │     │   └──────────────────────────┘
              └────────────────┘     │
                                     │ event stream (agent utterances)
                                     ▼
                    ┌─────────────────────────────────────────┐
                    │  Voice Bridge (WS-D)                     │
                    │  events → TTS (ElevenLabs) → bot joins    │
                    │  Zoom/Meet (Recall.ai) · STT for human   │
                    └─────────────────────────────────────────┘
```

**The integration seam is the `events` table + the API contract (§5–6).** Lock those in Hour 0; then all four workstreams build against them independently.

---

## 3. Workstreams (4 engineers)

| WS | Owner | Scope | Primary dirs |
|---|---|---|---|
| **WS-A Debate Engine** | **You** | Claude Agent SDK orchestration, rounds, peer requests, MCP tools, weighted verdict, Weave ops | `backend/engine/` |
| **WS-B Backend/API + DB** | Eng 2 | FastAPI, Supabase schema + auth, SSE streaming, persistence layer, scorers/evals | `backend/api/`, `backend/db/` |
| **WS-C Frontend** | Eng 3 | Next.js: auth, org builder, boardroom, inspector, influence graph, verdict/HITL | `frontend/` |
| **WS-D Voice/Meeting** | Eng 4 | TTS per agent, virtual-meeting bot (Zoom/Meet), STT for human, audio routing | `voice/` |

Decoupling rule: **WS-D and WS-C both consume the `events` stream**; if voice or any panel isn't done, the rest still demos. WS-A writes events; WS-B persists + streams them; WS-C renders; WS-D speaks them.

---

## 4. Data model (Supabase Postgres — run as migration in Hour 0)

```sql
-- USERS come from Supabase Auth (auth.users). We reference auth.uid().

create table orgs (
  id          uuid primary key default gen_random_uuid(),
  owner_id    uuid not null references auth.users(id),
  name        text not null,
  description text,
  preset      text,                      -- 'vc' | 'board' | 'judges' | null
  created_at  timestamptz default now()
);

create table agents (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid not null references orgs(id) on delete cascade,
  name          text not null,           -- "Dana — CFO"
  role          text not null,           -- "Financial Due Diligence"
  system_prompt text not null,
  model         text not null default 'claude-sonnet-4-6',  -- or W&B Inference model id
  provider      text not null default 'anthropic',          -- 'anthropic' | 'wandb'
  weight        numeric not null default 1.0,                -- voting weight
  voice_id      text,                    -- ElevenLabs voice id (WS-D)
  tools         jsonb default '[]',      -- ["research","company_data","wandb"]
  position      int default 0,           -- seat order in boardroom
  created_at    timestamptz default now()
);

create table sessions (
  id              uuid primary key default gen_random_uuid(),
  org_id          uuid not null references orgs(id) on delete cascade,
  created_by      uuid references auth.users(id),
  question        text not null,
  context         text,                  -- injected docs/notes
  weights_override jsonb,                -- {agent_id: weight} for HITL re-run
  status          text not null default 'pending', -- pending|running|done|error
  rounds          int default 3,
  final_verdict   jsonb,                 -- see §7 verdict shape
  weave_trace_url text,
  parent_session  uuid references sessions(id), -- for re-runs / comparison
  created_at      timestamptz default now()
);

-- The inspectable transcript. Append-only, ordered by seq.
create table events (
  id            uuid primary key default gen_random_uuid(),
  session_id    uuid not null references sessions(id) on delete cascade,
  seq           bigint generated always as identity,  -- global order
  round         int not null,
  agent_id      uuid references agents(id),           -- null for orchestrator
  type          text not null,   -- see Event Taxonomy §5
  content       jsonb not null,  -- type-specific payload
  parent_event  uuid references events(id),           -- threading (peer Q→A, tool call→result)
  influenced_by jsonb default '[]',  -- [agent_id,...] peers that moved this agent
  created_at    timestamptz default now()
);
create index on events(session_id, seq);

-- Denormalized per-round stance for charts + influence graph.
create table positions (
  id          uuid primary key default gen_random_uuid(),
  session_id  uuid not null references sessions(id) on delete cascade,
  round       int not null,
  agent_id    uuid not null references agents(id),
  stance      text not null,    -- 'YES' | 'NO' | 'CONDITIONAL'
  score       numeric not null, -- 0..10
  confidence  numeric not null, -- 0..1
  rationale   text,
  unique (session_id, round, agent_id)
);
```

**RLS:** enable on all tables; policy `owner_id = auth.uid()` (orgs) and join-based for children. For the hackathon a single permissive "authenticated users" policy is acceptable if time is short — but keep `owner_id` populated.

---

## 5. Event taxonomy (the heart of "inspectable")

Every reasoning step is one `events` row. `type` ∈:

| type | emitted by | `content` shape |
|---|---|---|
| `position` | agent | `{stance, score, confidence, rationale}` (initial, round 0) |
| `thought` | agent | `{text}` — private chain-of-thought / reasoning summary |
| `message` | agent | `{text, to:"all"}` — public argument in the debate |
| `peer_request` | agent | `{to_agent_id, question}` — direct question to a peer |
| `peer_response` | agent | `{to_agent_id, answer}` (parent_event = the request) |
| `tool_call` | agent | `{tool, args}` |
| `tool_result` | agent | `{tool, result}` (parent_event = the call) |
| `position_update` | agent | `{stance, score, confidence, rationale}` + `influenced_by:[ids]` |
| `orchestrator` | orchestrator | `{action:"continue"|"converge", conflict_level, note}` |
| `verdict` | orchestrator | full verdict object (§7) |

Frontend renders the timeline by `seq`; threads via `parent_event`; the influence graph reads `position_update.influenced_by` weighted by score delta.

---

## 6. API contract (FastAPI)

Base: `http://localhost:8000`. All routes require `Authorization: Bearer <supabase_jwt>` except `/health`.

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| GET | `/health` | — | `{ok:true}` |
| GET | `/orgs` | — | `[Org]` |
| POST | `/orgs` | `{name, description, preset?}` | `Org` |
| POST | `/orgs/generate` | `{prompt}` | `Org` + seeded `[Agent]` (AI org-builder, §9.4) |
| GET | `/orgs/{id}/agents` | — | `[Agent]` |
| POST | `/orgs/{id}/agents` | `Agent` (no id) | `Agent` |
| PATCH | `/agents/{id}` | partial `Agent` | `Agent` |
| POST | `/sessions` | `{org_id, question, context?, rounds?}` | `{session_id}` (starts async debate) |
| GET | `/sessions/{id}` | — | `{session, events, positions, verdict}` |
| GET | `/sessions/{id}/stream` | SSE | `event: <type>\ndata: <event json>` live |
| POST | `/sessions/{id}/rerun` | `{weights_override?, context?}` | `{session_id}` (new child session) |
| GET | `/sessions/{id}/influence` | — | `{nodes:[...], edges:[{from,to,weight}]}` |

**Streaming:** the debate engine writes each event to Postgres AND pushes onto an in-process `asyncio.Queue` per session; `/stream` drains the queue as SSE. (Alternative: subscribe the frontend directly to Supabase Realtime on `events` — pick whichever WS-B gets working first; SSE is the safe default.)

CORS: allow the Next.js origin. Env: see §11.

---

## 7. Debate engine (WS-A) — algorithm + Claude Agent SDK + MCP

### 7.1 Verdict shape
```jsonc
{
  "decision": "YES" | "NO" | "CONDITIONAL",
  "weighted_score": 7.4,          // Σ(wᵢ·sᵢ)/Σwᵢ over final positions
  "confidence": 0.81,             // consensus(1-normVariance) blended w/ avg agent confidence
  "summary": "…",
  "key_agreements": ["…"],
  "key_conflicts": [{"between": ["a1","a2"], "issue": "…"}],
  "dissenting_opinions": [{"agent_id": "a3", "stance": "NO", "why": "…"}],
  "influence_ranking": [{"agent_id": "a1", "influence": 0.42}, ...]
}
```

### 7.2 Loop (pseudocode — all steps are `@weave.op()`)
```python
@weave.op()
async def run_debate(session, org, agents):
    emit(session, round=0, type="orchestrator",
         content={"action":"start","question":session.question})

    # Round 0 — independent positions (parallel)
    positions = await asyncio.gather(*[
        agent_position(a, session.question, session.context) for a in agents
    ])
    for a, p in zip(agents, positions):
        save_position(session, 0, a, p)
        emit(session, 0, a, "position", p)

    # Rounds 1..N — debate
    for r in range(1, session.rounds + 1):
        board = transcript_so_far(session)          # all public messages + positions
        conflict = stance_variance(positions)
        emit(session, r, None, "orchestrator",
             {"action": "continue", "conflict_level": conflict})
        if conflict < CONVERGE_THRESHOLD and r > 1:
            break

        # Each agent, in parallel, may: argue, ask a peer, call tools, update position
        updates = await asyncio.gather(*[
            agent_turn(a, board, agents) for a in agents   # see 7.3
        ])
        for a, u in zip(agents, updates):
            for ev in u.events: emit(session, r, a, ev.type, ev.content,
                                     influenced_by=ev.influenced_by)
            save_position(session, r, a, u.position)
        positions = [u.position for u in updates]

    verdict = await orchestrate_verdict(session, org, agents, positions)
    emit(session, session.rounds+1, None, "verdict", verdict)
    finalize_session(session, verdict, weave_url=weave.get_current_call().ui_url)
    return verdict
```

### 7.3 One agent turn — Claude Agent SDK
Each agent = a Claude Agent SDK subagent with its `system_prompt`, allowed MCP tools, and the running board state as input. The SDK ↔ Weave integration auto-traces the model + tool calls; we additionally emit our typed events.

```python
@weave.op()
async def agent_turn(agent, board, peers):
    # claude_agent_sdk: configure subagent with role prompt + MCP servers for its tools
    response = await claude_query(
        system=agent.system_prompt + DEBATE_RUBRIC,
        prompt=render_board(board, peers),     # "Here's what others said. Rebut, ask, or update."
        model=agent.model,                     # claude-sonnet-4-6, or W&B Inference via provider
        mcp_servers=tools_for(agent),          # research / company_data / wandb
        output_schema=AGENT_TURN_SCHEMA,       # {message, peer_request?, position, influenced_by[]}
    )
    return parse_turn(response)
```
- **`influenced_by`** is produced by the agent itself: the rubric instructs each agent, when it updates its score, to list which peers' arguments moved it. This is the raw signal for the influence graph (§8).
- **W&B Inference agents:** for `provider=="wandb"`, route the call through the OpenAI-compatible client in `main.py` (base `https://api.inference.wandb.ai/v1`) instead of the Anthropic SDK — gives a genuinely multi-model panel (e.g., a Llama "skeptic" vs Claude "optimist").

### 7.4 Orchestrator verdict
```python
@weave.op()
async def orchestrate_verdict(session, org, agents, positions):
    weights = session.weights_override or {a.id: a.weight for a in agents}
    weighted = sum(weights[a.id]*p.score for a,p in zip(agents,positions)) / sum(weights.values())
    consensus = 1 - normalized_variance([p.score for p in positions])
    # LLM orchestrator summarizes agreements/conflicts/dissent from the transcript:
    summary = await claude_query(system=ORCHESTRATOR_PROMPT, prompt=transcript(session),
                                 output_schema=VERDICT_SCHEMA)
    decision = "YES" if weighted>=7 else "CONDITIONAL" if weighted>=5 else "NO"
    return {**summary, "decision": decision, "weighted_score": weighted,
            "confidence": 0.5*consensus + 0.5*avg_conf(positions),
            "influence_ranking": influence_ranking(session)}
```

### 7.5 MCP tools (sponsor + protocol story)
- `research` — web search (Firecrawl/Tavily or a stub) so agents ground claims.
- `company_data` — mock CRM/financials JSON, exposed as an MCP server, so a "CFO" agent can pull numbers.
- `wandb` — the **already-configured W&B MCP**; lets agents query past decisions/traces. Double sponsor use.
- Stretch: expose the **whole orchestrator as an MCP server** (`evaluate_decision(question, org)`), so Company Brain is callable from Claude Desktop — a clean A2A/MCP narrative.

---

## 8. Influence graph (WS-A emits, WS-C renders)

- Nodes = agents. Edge `A → B` when B's `position_update.influenced_by` contains A.
- Edge weight = |Δ score of B that round| (how much B moved), summed across rounds.
- `influence(A) = Σ outgoing edge weights / total movement` → normalized 0..1, drives `influence_ranking`.
- Render: force-directed graph (react-force-graph / d3). Node size = voting weight; edge thickness = influence. This directly satisfies the spec's "which got more weight and influenced other agents."

---

## 9. W&B Weave instrumentation (WS-B owns evals; WS-A owns op decoration)

We already have `weave.init` + a traced op + W&B Inference working (`main.py`). Extend:

### 9.1 Tracing
- Decorate `run_debate`, `agent_turn`, `agent_position`, `orchestrate_verdict` with `@weave.op()`.
- Claude Agent SDK calls auto-trace via the Weave integration; tool calls appear as children.
- Attach `weave.get_current_call().ui_url` to `sessions.weave_trace_url` → deep-link from each session.

### 9.2 Scorers (`@weave.op()` each)
```python
def score_confidence(output):       return output["confidence"]                 # 0..1
def score_verdict_strength(output): return {"YES":1.0,"CONDITIONAL":0.5,"NO":0.0}[output["decision"]]
def score_consensus(output):        return 1 - normalized_variance(scores_of(output))
def score_groundedness(output):     return min(1.0, tool_calls(output)/len(agents))  # did agents use tools?
```

### 9.3 Evaluation
- Dataset: ~8 decision questions × 2–3 org presets (VC / board / judges) as a `weave.Dataset`.
- `weave.Evaluation(dataset, scorers=[...])` → leaderboard. This is the **"have a coding agent hill-climb a metric"** story: tweak prompts/weights, re-run eval, watch scores rise.
- **Online monitor** (`weave ... monitors`) on the live `/sessions` op for the demo.

### 9.4 AI org-builder (`/orgs/generate`)
LLM call: prompt → a JSON team of agents (name, role, system_prompt, weight, suggested voice). Traced. Lets the demo show "spin up a biotech investment committee in 5 seconds."

---

## 10. Voice / virtual meeting (WS-D) — own this end-to-end

**Goal:** agents speak aloud and attend a real Zoom/Google Meet; the human can talk and agents respond.

**Tiered plan (ship the lowest tier first, climb if time):**
1. **Tier 1 — Browser TTS (always works):** WS-C boardroom subscribes to `events`; for each `message`, call ElevenLabs streaming TTS with the agent's `voice_id`, play in-browser. Distinct voice per agent. *This alone makes the demo sing and needs no meeting integration.*
2. **Tier 2 — Bot joins the meeting:** use **Recall.ai** (meeting-bot API) to send a bot into Google Meet/Zoom and play the TTS audio into the call. Agents are now "in the room."
3. **Tier 3 — Two-way:** STT (Deepgram or Whisper) on the meeting audio → transcribe the human → POST as `context`/`peer_request` into the running session → agents respond live. Full conversational boardroom.

**Pipeline:** `events(message)` → ElevenLabs TTS (per-agent voice) → audio buffer → (Tier 2) Recall.ai output / virtual mic → meeting. **STT** path: meeting audio → Deepgram → text → `/sessions/{id}` context injection.
**Decoupling:** WS-D reads the same SSE/Realtime stream as the frontend, so it integrates without touching WS-A/B internals. If Tier 2/3 slip, Tier 1 in the browser is the fallback and still demos voice.

---

## 11. Environment, accounts & keys (Hour 0 — do in parallel)

```bash
# backend/.env
WANDB_API_KEY=...                 # done (yamanbicer-mindra)
WANDB_ENTITY=yamanbicer-mindra
WANDB_PROJECT=company-brain-harness
ANTHROPIC_API_KEY=...             # request via hackathon API form (Claude Agent SDK)
SUPABASE_URL=...                  # new Supabase project
SUPABASE_SERVICE_KEY=...          # server-side (backend)
SUPABASE_JWT_SECRET=...           # to verify frontend JWTs
TAVILY_API_KEY=...                # or Firecrawl — research MCP (optional)

# frontend/.env.local
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
NEXT_PUBLIC_API_URL=http://localhost:8000

# voice/.env
ELEVENLABS_API_KEY=...
RECALL_API_KEY=...                # Tier 2 (meeting bot)
DEEPGRAM_API_KEY=...              # Tier 3 (STT)
```
**Accounts to create now:** Supabase project (1 person), ElevenLabs (WS-D), Recall.ai (WS-D), Anthropic credits via `https://forms.gle/rj1tGQK6cBeYmvq38`. W&B already done. **Rotate the W&B key post-event** (it appeared in a transcript).

---

## 12. Repo structure

```
decision_harness/
├── backend/
│   ├── main.py                 # FastAPI app + CORS + weave.init  (evolve current main.py)
│   ├── api/                    # routers: orgs, agents, sessions, stream
│   ├── engine/                 # debate loop, agent_turn, orchestrator, influence, prompts/
│   ├── db/                     # supabase client, queries, migrations.sql
│   ├── scorers.py              # Weave scorers + evaluation.py
│   └── mcp_servers/            # research, company_data stubs
├── frontend/                   # Next.js app router
│   ├── app/(auth)/ login/
│   ├── app/orgs/  [orgBuilder] ├── app/session/[id]/  # boardroom + inspector
│   ├── components/ Boardroom/ Inspector/ InfluenceGraph/ VerdictPanel/
│   └── lib/ supabase.ts  api.ts  useEventStream.ts
├── voice/                      # WS-D: tts.py, meeting_bot.py, stt.py
├── ROADMAP.md
└── requirements.txt / package.json
```

---

## 13. Hour-by-hour timeline (build start ≈ 11:30am; draft 7pm, final 8pm)

> Times are relative build-hours H0–H5 (~5 hrs core + buffer to 7pm). **Bold = integration checkpoint, whole team syncs.**

### H0 (0:00–0:30) — Contracts & scaffolding (ALL)
- **Agree & freeze: `events` taxonomy (§5) + API contract (§6) + verdict shape (§7.1).** This is the seam.
- Create Supabase project; run `migrations.sql` (§4); enable Auth; share keys.
- Scaffold: WS-A `backend/engine/`, WS-B `backend/api/` + FastAPI hello, WS-C `npx create-next-app` + Supabase auth, WS-D ElevenLabs "hello voice".
- Distribute `.env` files. **Checkpoint: `GET /health` returns 200; frontend loads; DB reachable.**

### H1 (0:30–1:30) — Vertical slice
- **WS-A:** Round-0 only: 3 agents → independent `position` events, hard-coded org. Wrap in `@weave.op()`. Print + write events to DB.
- **WS-B:** `POST /sessions` (creates row, kicks off engine), `GET /sessions/{id}`, Supabase persistence layer, JWT auth middleware.
- **WS-C:** Auth flow; "New Decision" form (pick org, question) → calls `POST /sessions`; raw event list view.
- **WS-D:** Tier 1 browser TTS proof: speak a hard-coded line in 3 distinct voices.
- **Checkpoint (1:30): one question → 3 positions persisted → visible in UI.** Vertical slice alive.

### H2 (1:30–2:30) — Debate + streaming
- **WS-A:** Rounds 1..N: `agent_turn` with peer visibility, `message` + `position_update` + `influenced_by`; conflict detection + converge. Claude Agent SDK subagents wired.
- **WS-B:** SSE `/sessions/{id}/stream`; engine pushes events to per-session queue. Persist positions per round.
- **WS-C:** `useEventStream` hook (SSE) → live-rendering Boardroom (agent seats + streaming bubbles + round indicator).
- **WS-D:** Tier 1 wired to the real event stream — agents speak as messages arrive. Begin Recall.ai bot (Tier 2).
- **Checkpoint (2:30): live multi-round debate streams into the boardroom and is spoken aloud.**

### H3 (2:30–3:30) — Verdict, influence, MCP tools
- **WS-A:** `orchestrate_verdict` (weighted score, agreements/conflicts/dissent); influence graph computation; add `research` + `wandb` MCP tools so agents call tools (visible `tool_call` events).
- **WS-B:** persist verdict + `weave_trace_url`; `/sessions/{id}/influence`; start scorers + `weave.Dataset`.
- **WS-C:** VerdictPanel; Inspector (per-agent thought/tool/peer tree, threaded by `parent_event`); InfluenceGraph component.
- **WS-D:** Tier 2 — bot joins a real Google Meet and plays agent audio.
- **Checkpoint (3:30): full run = debate → tools → verdict → influence graph, deep-linked to Weave.**

### H4 (3:30–4:30) — Config, HITL, evals, polish
- **WS-A:** AI org-builder `/orgs/generate`; multi-model panel (1–2 agents on W&B Inference).
- **WS-B:** `weave.Evaluation` across presets → leaderboard; HITL `/sessions/{id}/rerun` (new weights/context → child session).
- **WS-C:** Org Builder UI (CRUD agents, weights, voices); HITL weight sliders + context box + "Re-run"; side-by-side compare (parent vs child session).
- **WS-D:** Tier 3 (STT) if on track, else harden Tier 2; pick the demo meeting setup.
- **Checkpoint (4:30): preset orgs, generated org, re-run, eval leaderboard all working.**

### H5 (4:30–5:30) — Demo hardening + submission (overlaps dinner 6pm)
- Freeze features. Seed the **demo org + demo question** ("Should this project win Most Sophisticated Harness?").
- Dry-run the 3-min demo twice. Record the <2-min screen video (friend/non-tech lead).
- Write submission: summary, problem, "how it's built" (A2A/MCP/Claude Agent SDK/Weave), sponsor-tool list, Weave URL, team names/socials.
- Push public GitHub repo. **Submit draft by 7pm, final by 8pm.**

---

## 14. Demo script (3 min)
1. (20s) "Company Brain — assemble an AI board, ask a decision, watch them argue." Show preset **VC Committee**.
2. (30s) Generate a *new* org from a prompt ("biotech seed investors") → instant team. (sponsor: shows configurability)
3. (60s) Ask the live question; **boardroom debates out loud** in the Meet; bubbles stream; an agent calls the `research` tool; another asks a peer a direct question; positions shift.
4. (30s) **Verdict** with weighted score + the **influence graph** ("the CFO swung the room"). Open the **Weave trace**.
5. (20s) Judge HITL: drag the "Skeptic" weight up + inject "assume a recession" → **Re-run** → verdict flips. Show eval leaderboard.

---

## 15. Risk register & fallbacks

| Risk | Mitigation / Fallback |
|---|---|
| Meeting-bot (Tier 2/3) eats the clock | Tier 1 browser TTS is the demo fallback; WS-D is fully decoupled. |
| Claude Agent SDK unfamiliarity | Start with plain Anthropic SDK calls behind `agent_turn`; swap to Agent SDK once green. Interface unchanged. |
| SSE/streaming flakiness | Fall back to Supabase Realtime subscription on `events`, or 1s polling of `GET /sessions/{id}`. |
| Supabase auth/RLS friction | Ship with a single demo user + permissive RLS; keep `owner_id` for later. |
| 4 people, merge chaos | Frozen contracts (§5–6) + separate dirs + feature branches; integrate only at checkpoints. |
| Weave eval not done | Tracing alone (already working) is a valid Best-of-Weave entry; evals are the upgrade. |
| Anthropic credits delayed | W&B Inference (already funded, $100) runs every agent if needed. |

---

## 16. Critical path (if we fall behind, ship in this order)
1. H1 vertical slice (positions persisted + visible) + Weave traces → **minimum viable**.
2. H2 live streaming debate + boardroom + Tier-1 voice → **strong**.
3. H3 verdict + influence graph + tools + Weave deep-link → **winning**.
4. H4 config/HITL/evals + Tier-2 meeting bot → **exceptional**.
Do not start H4 polish until H3's full run works end to end.

---

## 17. Submission checklist (due 8pm)
- [ ] Public GitHub repo (all code)
- [ ] Weave project URL (shareable) — `https://wandb.ai/yamanbicer-mindra/company-brain-harness/weave`
- [ ] <2-min screen recording
- [ ] Project description: summary · problem · how-built (Claude Agent SDK, MCP, A2A story, FastAPI/Next/Supabase) · **every sponsor tool + how used** (Weave tracing+evals+monitors, W&B Inference, MCP, W&B MCP)
- [ ] Team names, emails, socials (X/LinkedIn)
- [ ] Rotate W&B API key
