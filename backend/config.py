"""Central settings, read from backend/.env and the process environment.

Everything degrades gracefully: the app boots even when keys are missing so
the team can run `GET /health` on day one before all accounts are provisioned.
"""
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always read backend/.env, even when uvicorn is launched from the repo root
# (per START_HERE: `uvicorn backend.main:app`). A bare ".env" would resolve
# against the launch CWD and miss this file. Process env still overrides it.
_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    # --- W&B / Weave (already provisioned, see main repo .env) ---
    wandb_api_key: str = ""
    wandb_entity: str = ""
    wandb_project: str = "company-brain-harness"  # existing Weave project

    # --- Models ---
    anthropic_api_key: str = ""                    # Claude Agent SDK
    inference_base_url: str = "https://api.inference.wandb.ai/v1"
    # Fallback W&B Inference model for any agent whose own model isn't a W&B id.
    inference_model: str = "openai/gpt-oss-120b"

    # --- Tools / web research (all degrade to deterministic mocks when no key) ---
    web_search_provider: str = "auto"              # auto | firecrawl | tavily | mock
    firecrawl_api_key: str = ""
    tavily_api_key: str = ""
    tool_max_calls: int = 3                         # ReAct loop cap per agent per turn
    tool_timeout_s: float = 12.0

    # --- MCP (optional live integration) ---
    # Absolute or repo-relative path to an mcp_servers.json. Empty => no MCP tools.
    mcp_config_path: str = ""

    # --- Context budgeting (chars; ~4 chars/token heuristic) ---
    board_char_budget: int = 4000
    evidence_char_budget: int = 1600
    transcript_char_budget: int = 8000

    # --- Supabase (Postgres + Auth) ---
    supabase_url: str = ""
    supabase_service_key: str = ""                 # server-side only

    # --- ElevenLabs (Scribe STT for pitch-video analysis) ---
    elevenlabs_api_key: str = ""
    elevenlabs_stt_model: str = "scribe_v1"

    # --- Project-brief ingestion (deck + demo video → reusable context) ---
    # Groq is used for AUDIO TRANSCRIPTION ONLY (never the council agents).
    # The user's key lives in .env as GROQ; also accept the SDK-default name.
    groq_api_key: str = Field("", validation_alias=AliasChoices("GROQ", "GROQ_API_KEY"))
    groq_model: str = "whisper-large-v3-turbo"     # cheapest/fastest Whisper on Groq
    # Vision model for slide pages + sampled video frames (W&B Inference, OpenAI-compat).
    # Separate from inference_model (text-only) — must be a vision-capable catalog id.
    vision_model: str = "google/gemma-4-31B-it"
    vision_model_fallback: str = "moonshotai/Kimi-K2.6"
    storage_bucket: str = "project-briefs"          # Supabase Storage bucket for uploads

    # --- CORS ---
    frontend_origin: str = "http://localhost:3000"
    # Vercel project + team slugs used to pin the CORS origin regex (see
    # cors_origin_regex). The team slug is reserved to us by Vercel, so pinning
    # it stops a look-alike third-party project from matching.
    frontend_vercel_slug: str = "decisive"
    frontend_vercel_team: str = "yamanns"

    # --- Auth posture ---
    # Local dev only: allow requests with no Authorization header (treated as the
    # demo user). IGNORED once auth_enabled (Supabase is configured) — then a valid
    # token is always required. Set False in any shared/hosted environment.
    dev_unauthenticated: bool = True

    @property
    def project_path(self) -> str:
        return f"{self.wandb_entity}/{self.wandb_project}" if self.wandb_entity else self.wandb_project

    @property
    def weave_enabled(self) -> bool:
        return bool(self.wandb_api_key)

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def transcription_enabled(self) -> bool:
        # Gates POST /sessions/from-video. Without a key the app still boots and
        # every other route works — only video upload returns 503.
        return bool(self.elevenlabs_api_key)

    @property
    def groq_enabled(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def vision_enabled(self) -> bool:
        # Slide/frame vision runs on W&B Inference, so it's gated on the W&B key.
        return bool(self.wandb_api_key)

    @property
    def asr_enabled(self) -> bool:
        # Any speech-to-text path available (Groq primary, ElevenLabs Scribe fallback).
        return self.groq_enabled or self.transcription_enabled

    @property
    def brief_ingestion_enabled(self) -> bool:
        # The brief pipeline always runs (it degrades to a deterministic mock with
        # no keys); this flag just tells the UI whether *real* extraction is wired.
        return self.vision_enabled or self.asr_enabled or self.web_search_enabled

    @property
    def web_search_backend(self) -> str:
        """Which web provider to actually use. 'mock' when no key (graceful degradation)."""
        if self.web_search_provider != "auto":
            return self.web_search_provider
        if self.firecrawl_api_key:
            return "firecrawl"
        if self.tavily_api_key:
            return "tavily"
        return "mock"

    @property
    def web_search_enabled(self) -> bool:
        return self.web_search_backend != "mock"

    @property
    def mcp_config_file(self) -> Optional[Path]:
        """Resolve mcp_config_path (absolute, or relative to the repo root)."""
        if not self.mcp_config_path:
            return None
        p = Path(self.mcp_config_path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[1] / self.mcp_config_path
        return p

    @property
    def mcp_enabled(self) -> bool:
        p = self.mcp_config_file
        return bool(p and p.exists())

    @property
    def jwks_url(self) -> str:
        # Supabase publishes its asymmetric (ES256) public signing keys here.
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"

    @property
    def auth_enabled(self) -> bool:
        # Verification is keyed off the project URL: tokens are checked against
        # the project's published JWKS (no shared secret needed).
        return bool(self.supabase_url)

    @property
    def cors_origins(self) -> list[str]:
        return list({self.frontend_origin, "http://localhost:3000", "http://127.0.0.1:3000"})

    @property
    def cors_origin_regex(self) -> str:
        # Vercel preview / per-deploy URLs look like
        #   <project>-<hash>-<team>.vercel.app   (e.g. decisive-3hpw9j94q-yamanns.vercel.app)
        # Pin BOTH the project slug and the team slug. The team slug is reserved
        # to us by Vercel, so an attacker who registers a `decisive-*` project
        # under their own team can't produce a matching origin (credentials are
        # allowed, so a loose `*.vercel.app` regex would be a real CORS hole).
        # The clean production alias (e.g. decisiveai.vercel.app, which carries
        # no team segment) is allow-listed exactly via frontend_origin instead.
        slug = re.escape(self.frontend_vercel_slug)
        team = re.escape(self.frontend_vercel_team)
        return rf"https://{slug}[a-z0-9-]*-{team}\.vercel\.app"


@lru_cache
def get_settings() -> Settings:
    return Settings()
