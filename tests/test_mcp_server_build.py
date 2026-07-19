"""Smoke tests for the FastMCP wiring (tools registered, health route present)."""

import pytest

pytest.importorskip("mcp")
pytest.importorskip("starlette")

from mcp_server.server import build_app, build_mcp  # noqa: E402

_EXPECTED_TOOLS = {
    "list_files",
    "search_code",
    "get_file",
    "list_versions",
    "list_collections",
    "get_collection",
    "get_collection_items",
}


class _FakeBackend:
    def list_files(self, *a, **k):
        return {}

    def search_code(self, *a, **k):
        return []

    def get_file(self, *a, **k):
        return None

    def list_versions(self, *a, **k):
        return []

    def list_collections(self, *a, **k):
        return {}

    def get_collection(self, *a, **k):
        return {}

    def get_collection_items(self, *a, **k):
        return {}


class _FakeStore:
    def verify(self, token):
        return None


async def test_all_tools_are_registered():
    mcp = build_mcp(_FakeBackend())
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert _EXPECTED_TOOLS <= names


def test_build_app_exposes_healthz_route():
    app = build_app(_FakeBackend(), _FakeStore())
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/healthz" in paths


def test_transport_security_off_by_default(monkeypatch):
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)
    from mcp_server.server import _transport_security

    ts = _transport_security()
    # Public token-gated server: DNS-rebinding host check must be off so a real
    # domain (e.g. *.onrender.com) is not rejected with HTTP 421.
    assert ts.enable_dns_rebinding_protection is False


def test_transport_security_locks_down_via_env(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "a.com, *.b.com")
    from mcp_server.server import _transport_security

    ts = _transport_security()
    assert ts.enable_dns_rebinding_protection is True
    assert ts.allowed_hosts == ["a.com", "*.b.com"]
