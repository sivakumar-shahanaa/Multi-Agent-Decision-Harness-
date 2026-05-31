"""SSRF guard: outbound fetches reject internal / non-http targets."""
import pytest

from backend.engine.tool_registry import ToolContext
from backend.engine.tools import execute_tool
from backend.safeurl import UnsafeURLError, safe_outbound_url, validate_url_static
from backend.schemas import Agent


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd",
    "ftp://example.com/x",
    "http://user:pass@example.com",
    "http://127.0.0.1/admin",
    "https://10.0.0.5/internal",
    "http://169.254.169.254/latest/meta-data/",
])
def test_validate_url_static_rejects(bad):
    with pytest.raises(UnsafeURLError):
        validate_url_static(bad)


def test_validate_url_static_allows_public():
    assert validate_url_static("https://example.com/path") == "https://example.com/path"


async def test_safe_outbound_url_rejects_loopback_hostname():
    with pytest.raises(UnsafeURLError):
        await safe_outbound_url("http://localhost:8000/")


async def test_fetch_url_tool_refuses_metadata_endpoint():
    agent = Agent(id="a", org_id="o", name="A", role="r", system_prompt="", tools=["fetch_url"])
    res = await execute_tool("fetch_url", {"url": "http://169.254.169.254/latest/meta-data/"},
                             ToolContext(agent=agent))
    assert "error" in res and "unsafe" in res["error"].lower()
