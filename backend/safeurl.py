"""SSRF guard for outbound fetches (ROADMAP §7.5 security).

Any server-side fetch of a URL that originated from a *request* (an agent's
`fetch_url` tool call, or a user-submitted project-source URL) is an SSRF surface:
a crafted URL can reach cloud metadata (169.254.169.254), loopback, or RFC1918
internal services. Guard every such fetch with these helpers.

- `validate_url_static(url)` — cheap, no DNS: enforces http(s), no userinfo, and
  rejects literal non-public IP hosts. Use at submission time.
- `safe_outbound_url(url)` — the full check: static + resolves the host and rejects
  if ANY resolved address is non-global. Use right before a direct fetch. Pair it
  with `follow_redirects=False` so a 30x can't bounce to an internal host post-check.

Fetches DELEGATED to a trusted scraping API (Firecrawl: our server only connects to
api.firecrawl.dev, which does its own SSRF defense) don't need the DNS check, but the
static check is still worthwhile to reject obviously-hostile input early.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """Raised when a URL is not safe to fetch server-side."""


def _reject_ip(host: str) -> None:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # not a literal IP — a hostname; DNS-checked in safe_outbound_url
    if not ip.is_global:
        raise UnsafeURLError(f"host resolves to non-public address {ip}")


def validate_url_static(url: str) -> str:
    """Scheme/userinfo/literal-IP checks without touching DNS. Returns url or raises."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise UnsafeURLError(f"scheme '{p.scheme or '(none)'}' not allowed; use http/https")
    if p.username or p.password or "@" in p.netloc:
        raise UnsafeURLError("userinfo (user:pass@host) is not allowed in a URL")
    if not p.hostname:
        raise UnsafeURLError("URL has no host")
    _reject_ip(p.hostname)
    return url


async def safe_outbound_url(url: str) -> str:
    """Full guard: static checks + resolve the host and reject if any address is
    non-global (loopback / private / link-local / multicast / reserved). Raises
    UnsafeURLError. Use `follow_redirects=False` on the actual request."""
    validate_url_static(url)
    p = urlparse(url)
    port = p.port or (443 if p.scheme == "https" else 80)
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(p.hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURLError(f"cannot resolve host: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise UnsafeURLError(f"host {p.hostname} resolves to non-public address {ip}")
    return url
