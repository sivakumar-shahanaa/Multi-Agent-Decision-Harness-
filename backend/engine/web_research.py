"""Web-research tool backends (ROADMAP §7.5).

A small pluggable provider so agents can ground claims in real evidence and then
change their minds. The default live backend is Firecrawl (search + scrape, which
covers Crunchbase / Product Hunt / news WITHOUT a per-site API). Tavily is a drop-in
alternative. With no key we fall back to a RICH, deterministic mock so the whole
ReAct loop still runs end-to-end keyless (the repo's #1 constraint).

Persona-specialized tools (`market_research`, `competitor_scan`, `product_research`)
are thin prompted wrappers over the same primitive — they just shape the query and
label the lens, so a VC's "market-cap lookup" and a PM's "Product Hunt scan" reuse
one backend.

Every handler has signature `(args: dict, ctx) -> dict` and is `@weave.op()` traced.
"""
from __future__ import annotations

import hashlib
from typing import Optional, Protocol

import weave

from ..config import get_settings


# ───────────────────────── provider interface ─────────────────────────
class WebProvider(Protocol):
    async def search(self, query: str, limit: int = 5) -> list[dict]: ...   # [{title,url,snippet}]
    async def fetch(self, url: str) -> dict: ...                            # {url,title,markdown}


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


class MockProvider:
    """Deterministic offline stand-in. Same query → same results (testable)."""

    name = "mock"

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        r = _seed(query)
        n = max(1, min(limit, 3))
        return [
            {
                "title": f"[mock] Source {i + 1} on “{query[:48]}”",
                "url": f"https://example.com/{(r + i) % 9973}",
                "snippet": ("Deterministic offline evidence so the council runs without a "
                            f"web key. Signal {(r + i) % 100}/100 relevant to the query."),
            }
            for i in range(n)
        ]

    async def fetch(self, url: str) -> dict:
        return {"url": url, "title": "[mock] page",
                "markdown": f"Deterministic offline page body for {url}."}


class FirecrawlProvider:
    """Firecrawl v1 search + scrape (https://docs.firecrawl.dev)."""

    name = "firecrawl"
    BASE = "https://api.firecrawl.dev/v1"

    def __init__(self, key: str) -> None:
        self.key = key

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        import httpx

        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{self.BASE}/search", headers=self._headers(),
                             json={"query": query, "limit": min(limit, 6)})
            r.raise_for_status()
            data = (r.json() or {}).get("data") or []
        out = []
        for d in data[:limit]:
            out.append({"title": d.get("title") or d.get("url", ""),
                        "url": d.get("url", ""),
                        "snippet": (d.get("description") or d.get("markdown") or "")[:400]})
        return out

    async def fetch(self, url: str) -> dict:
        import httpx

        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.post(f"{self.BASE}/scrape", headers=self._headers(),
                             json={"url": url, "formats": ["markdown"]})
            r.raise_for_status()
            d = (r.json() or {}).get("data") or {}
        return {"url": url, "title": (d.get("metadata") or {}).get("title", ""),
                "markdown": (d.get("markdown") or "")[:4000]}


class TavilyProvider:
    """Tavily search API. Search-only; fetch degrades to a raw GET."""

    name = "tavily"

    def __init__(self, key: str) -> None:
        self.key = key

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        import httpx

        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post("https://api.tavily.com/search",
                             json={"api_key": self.key, "query": query,
                                   "max_results": min(limit, 6)})
            r.raise_for_status()
            results = (r.json() or {}).get("results") or []
        return [{"title": d.get("title", ""), "url": d.get("url", ""),
                 "snippet": (d.get("content") or "")[:400]} for d in results[:limit]]

    async def fetch(self, url: str) -> dict:
        import httpx

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            r = await c.get(url)
            return {"url": url, "title": "", "markdown": r.text[:4000]}


_provider: Optional[WebProvider] = None


def get_web_provider() -> WebProvider:
    """Select the provider from settings.web_search_backend (cached per process)."""
    global _provider
    if _provider is not None:
        return _provider
    s = get_settings()
    backend = s.web_search_backend
    if backend == "firecrawl" and s.firecrawl_api_key:
        _provider = FirecrawlProvider(s.firecrawl_api_key)
    elif backend == "tavily" and s.tavily_api_key:
        _provider = TavilyProvider(s.tavily_api_key)
    else:
        _provider = MockProvider()
    return _provider


def reset_web_provider() -> None:
    """Drop the cached provider (used by tests after monkeypatching settings)."""
    global _provider
    _provider = None


# ───────────────────────── tool handlers ─────────────────────────
@weave.op()
async def web_search(args: dict, ctx) -> dict:
    provider = get_web_provider()
    query = str(args.get("query", "")).strip()
    if not query:
        return {"error": "web_search needs a 'query'"}
    results = await provider.search(query, int(args.get("limit", 5) or 5))
    return {"provider": getattr(provider, "name", "?"), "query": query, "results": results}


@weave.op()
async def fetch_url(args: dict, ctx) -> dict:
    provider = get_web_provider()
    url = str(args.get("url", "")).strip()
    if not url:
        return {"error": "fetch_url needs a 'url'"}
    return await provider.fetch(url)


async def _lensed(query: str, lens: str, limit: int = 5) -> dict:
    provider = get_web_provider()
    hits = await provider.search(query, limit)
    return {"lens": lens, "query": query, "provider": getattr(provider, "name", "?"),
            "evidence": hits[:limit]}


@weave.op()
async def market_research(args: dict, ctx) -> dict:
    """Market size / funding / valuation lens (the 'Crunchbase' angle, via search)."""
    subject = str(args.get("company") or args.get("market") or args.get("query", "")).strip()
    return await _lensed(f"{subject} market size funding valuation revenue customers", "market")


@weave.op()
async def competitor_scan(args: dict, ctx) -> dict:
    """Who else is doing this — alternatives and differentiation."""
    subject = str(args.get("product") or args.get("company") or args.get("query", "")).strip()
    return await _lensed(f"{subject} competitors alternatives vs comparison market share", "competitive")


@weave.op()
async def product_research(args: dict, ctx) -> dict:
    """Product traction / reviews / launch lens (the 'Product Hunt' angle, via search)."""
    subject = str(args.get("product") or args.get("query", "")).strip()
    return await _lensed(f"{subject} product reviews adoption pricing launch Product Hunt", "product")
