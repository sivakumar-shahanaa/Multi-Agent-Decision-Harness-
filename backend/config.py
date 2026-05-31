"""Central settings, read from backend/.env and the process environment.

Everything degrades gracefully: the app boots even when keys are missing so
the team can run `GET /health` on day one before all accounts are provisioned.
"""
from functools import lru_cache
from pathlib import Path

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
    inference_model: str = "meta-llama/Llama-3.1-8B-Instruct"

    # --- Supabase (Postgres + Auth) ---
    supabase_url: str = ""
    supabase_service_key: str = ""                 # server-side only

    # --- CORS ---
    frontend_origin: str = "http://localhost:3000"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
