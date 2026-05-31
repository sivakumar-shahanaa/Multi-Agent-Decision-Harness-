"""Request dependencies: authenticated user + resource-ownership guards.

Auth posture (default-deny once configured):
  • A presented Bearer token is ALWAYS cryptographically verified. We never decode
    a token we can't verify — if no JWT secret is set, a presented token is rejected.
  • A missing token is accepted as the demo user ONLY in local dev
    (`dev_unauthenticated` True AND auth not configured). The moment a JWT secret is
    set (`auth_enabled`), a valid token is required.

Ownership guards return 404 (not 403) so we don't leak the existence of resources.
"""
from typing import Optional

from fastapi import Header, HTTPException

from ..config import get_settings

DEMO_USER_ID = "00000000-0000-0000-0000-000000000000"


def get_current_user(authorization: Optional[str] = Header(default=None)) -> str:
    s = get_settings()

    if authorization:
        token = authorization.removeprefix("Bearer ").strip()
        if not s.auth_enabled:
            # We have no secret to verify with — refuse rather than trust blindly.
            raise HTTPException(status_code=401, detail="token verification not configured")
        try:
            import jwt  # PyJWT

            claims = jwt.decode(token, s.supabase_jwt_secret, algorithms=["HS256"],
                                audience="authenticated")
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from exc
        sub = claims.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="token missing subject")
        return sub

    # No Authorization header.
    if s.dev_unauthenticated and not s.auth_enabled:
        return DEMO_USER_ID
    raise HTTPException(status_code=401, detail="authentication required")


def require_org_access(repo, org_id: str, user: str):
    """Return the org iff `user` owns it, else 404."""
    org = repo.get_org(org_id)
    if not org or org.owner_id != user:
        raise HTTPException(status_code=404, detail="org not found")
    return org


def require_session_access(repo, session_id: str, user: str):
    """Return the session iff `user` owns its org, else 404."""
    sess = repo.get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    org = repo.get_org(sess.org_id)
    if not org or org.owner_id != user:
        raise HTTPException(status_code=404, detail="session not found")
    return sess
