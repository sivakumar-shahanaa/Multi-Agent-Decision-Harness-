"""Object storage for uploaded project sources (PDFs, videos).

Two interchangeable backends behind one interface, mirroring repository.py:
  • SupabaseStorage — a private Supabase Storage bucket (the S3 equivalent),
    used when SUPABASE_* is configured.
  • LocalStorage    — writes under a gitignored ./.uploads/ dir, so the app
    still boots and uploads still work with ZERO keys (graceful degradation).

All calls are SYNCHRONOUS (supabase-py is sync). Callers inside async tasks
wrap them in asyncio.to_thread so they don't block the event loop.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from ..config import get_settings
from .client import get_supabase

# Local fallback root: <repo>/.uploads (gitignored). config.py lives at backend/config.py,
# so parents[1] of this file is the backend dir; parents[2] is the repo root.
_LOCAL_ROOT = Path(__file__).resolve().parents[2] / ".uploads"


class LocalStorage:
    """Disk-backed store for keyless dev/demo. Paths are bucket-relative keys."""

    def __init__(self, root: Path = _LOCAL_ROOT) -> None:
        self.root = root

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _abs(self, path: str) -> Path:
        # Keep keys inside the root (defense-in-depth against '..' in a key).
        p = (self.root / path).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("invalid storage path")
        return p

    def put(self, path: str, data: bytes, content_type: Optional[str] = None) -> str:
        dest = self._abs(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return path

    def get(self, path: str) -> bytes:
        return self._abs(path).read_bytes()

    def signed_url(self, path: str, ttl: int = 3600) -> Optional[str]:
        return None  # no public URL for local files; the pipeline reads bytes via get()

    def remove(self, path: str) -> None:
        p = self._abs(path)
        if p.exists():
            p.unlink()


class SupabaseStorage:
    """A private Supabase Storage bucket. Service key bypasses RLS — ownership is
    enforced in the API layer (deps.py), never via Storage policies."""

    def __init__(self, client, bucket: str) -> None:
        self.c = client
        self.bucket = bucket
        self._ensured = False

    def ensure(self) -> None:
        if self._ensured:
            return
        try:
            names = {b.name for b in self.c.storage.list_buckets()}
        except Exception:
            names = set()
        if self.bucket in names:
            self._ensured = True
            return
        try:
            self.c.storage.create_bucket(self.bucket, options={
                "public": False,
                "allowed_mime_types": ["application/pdf", "video/mp4"],
                "file_size_limit": 52428800,  # 50 MB — Supabase's default standard-upload ceiling
            })
        except Exception:
            # Created concurrently / already exists / insufficient perms — uploads
            # will surface a clearer error if the bucket truly isn't there.
            pass
        self._ensured = True

    def put(self, path: str, data: bytes, content_type: Optional[str] = None) -> str:
        opts = {"upsert": "true"}
        if content_type:
            opts["content-type"] = content_type
        self.c.storage.from_(self.bucket).upload(path, data, opts)
        return path

    def get(self, path: str) -> bytes:
        return self.c.storage.from_(self.bucket).download(path)

    def signed_url(self, path: str, ttl: int = 3600) -> Optional[str]:
        try:
            res = self.c.storage.from_(self.bucket).create_signed_url(path, ttl)
            return res.get("signedURL") or res.get("signedUrl")
        except Exception:
            return None

    def remove(self, path: str) -> None:
        try:
            self.c.storage.from_(self.bucket).remove([path])
        except Exception:
            pass


@lru_cache
def get_storage():
    """SupabaseStorage when Supabase is configured, else LocalStorage. Bucket is
    ensured lazily on first use by the caller (api startup calls .ensure())."""
    s = get_settings()
    client = get_supabase()
    store = SupabaseStorage(client, s.storage_bucket) if client else LocalStorage()
    return store
