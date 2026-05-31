"""Optional URL/website source: scrape a landing page to markdown via Firecrawl and
fold it into the brief. Reuses settings.firecrawl_api_key; calls the Firecrawl v1 API
directly over httpx (already a dependency) — no new package, no coupling to the
agent web-research module. Returns '' (mock/skip) when no key or on any failure.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import weave

from ...config import get_settings

_FIRECRAWL_SCRAPE = "https://api.firecrawl.dev/v1/scrape"
_MAX_CHARS = 8000


def is_safe_url(url: str) -> bool:
    """http(s) only, and the host must not resolve to a private/loopback/link-local
    address — defense-in-depth against SSRF even though the fetch runs on Firecrawl."""
    try:
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            return False
        for *_, sockaddr in socket.getaddrinfo(u.hostname, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast):
                return False
        return True
    except Exception:
        return False


@weave.op()
async def scrape_url(url: str) -> str:
    s = get_settings()
    if not url or not s.firecrawl_api_key:
        return ""
    if not await asyncio.to_thread(is_safe_url, url):
        return ""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                _FIRECRAWL_SCRAPE,
                headers={"Authorization": f"Bearer {s.firecrawl_api_key}"},
                json={"url": url, "formats": ["markdown"], "onlyMainContent": True})
            r.raise_for_status()
            data = r.json().get("data", {}) or {}
            return (data.get("markdown") or "").strip()[:_MAX_CHARS]
    except Exception:
        return ""
