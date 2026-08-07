"""Smoke tests for the FastMCP wiring (tools registered, health route present)."""

import pytest

pytest.importorskip("mcp")
pytest.importorskip("starlette")

from mcp_server.server import build_app, build_mcp  # noqa: E402

_EXPECTED_TOOLS = {
    "codekeeper_list_files",
    "codekeeper_search_code",
    "codekeeper_get_file",
    "codekeeper_save_file",
    "codekeeper_edit_file",
    "codekeeper_append_file",
    "codekeeper_list_notes",
    "codekeeper_create_note",
    "codekeeper_update_note",
    "codekeeper_list_versions",
    "codekeeper_list_collections",
    "codekeeper_get_collection",
    "codekeeper_get_collection_items",
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

    def save_file(self, *a, **k):
        return {"ok": True, "created": True, "file": {}}

    def list_notes(self, *a, **k):
        return {"ok": True, "notes": [], "count": 0}

    def create_note(self, *a, **k):
        return {"ok": True, "note": {}}

    def update_note(self, *a, **k):
        return {"ok": True, "note": {}}


class _FakeStore:
    def verify(self, token):
        return None


class _FakeRepoBackend:
    def list_repos(self, **k):
        return {"ok": True}

    def list_tree(self, **k):
        return {"ok": True}

    def get_file(self, **k):
        return {"ok": True}

    def search(self, **k):
        return {"ok": True}


async def test_all_tools_are_registered():
    mcp = build_mcp(_FakeBackend())
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert _EXPECTED_TOOLS <= names


async def test_repo_tools_hidden_from_non_admin_tools_list():
    from mcp_server.server import _ADMIN_TOOLS

    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    # Outside a request there is no auth context => fail-closed non-admin view.
    names = {t.name for t in await mcp.list_tools()}
    assert _EXPECTED_TOOLS <= names
    assert not (names & _ADMIN_TOOLS)


async def test_docs_tool_is_public_and_not_admin_gated():
    """codekeeper_docs_get_section ציבורי: מופיע ל-non-admin ואינו ב-_ADMIN_TOOLS."""
    from mcp_server.server import _ADMIN_TOOLS

    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    # תצוגת non-admin (בלי request context → fail-closed non-admin)
    names = {t.name for t in await mcp.list_tools()}
    assert "codekeeper_docs_get_section" in names
    assert "codekeeper_docs_get_section" not in _ADMIN_TOOLS


async def test_repo_tools_visible_to_admin():
    from mcp_server.server import _ADMIN_TOOLS

    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    mcp._request_is_admin = lambda: True  # simulate a verified admin request
    names = {t.name for t in await mcp.list_tools()}
    assert _ADMIN_TOOLS <= names


async def test_no_repo_backend_registers_no_repo_tools():
    from mcp_server.server import _ADMIN_TOOLS

    mcp = build_mcp(_FakeBackend())  # repo_backend omitted
    mcp._request_is_admin = lambda: True
    names = {t.name for t in await mcp.list_tools()}
    assert not (names & _ADMIN_TOOLS)


def test_build_app_exposes_healthz_route():
    app = build_app(_FakeBackend(), _FakeStore())
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/healthz" in paths


def test_build_app_exposes_agent_primer_route():
    app = build_app(_FakeBackend(), _FakeStore())
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/agent/primer" in paths


# ---------------------------------------------------------------------------
# הרגרסיה החשובה: הפריימר חייב להיות מאומת בשני מצבי האימות.
#
# ב-PAT-only מצב ה-PATAuthMiddleware עוטף את כל האפליקציה, ולכן כל ראוט מוגן
# "בחינם". ב-OAuth mode (הפרודקשן) המידלוור לא מותקן בכלל, וה-SDK עוטף רק את
# ה-mount של /mcp — כך שראוט שנרשם ידנית ל-app.router.routes יוצא ציבורי לגמרי,
# בדיוק כמו /healthz. הטסטים כאן נכשלים אם מישהו יסיר את האימות מגוף הראוט.
# ---------------------------------------------------------------------------
def _oauth_parts():
    """provider + settings מינימליים שמדליקים את מצב ה-OAuth ב-build_app."""
    from mcp.server.auth.settings import AuthSettings
    from pydantic import AnyHttpUrl

    class _Provider:
        async def load_access_token(self, token):
            return None  # שום טוקן אינו תקף בטסט הזה

        async def get_client(self, client_id):
            return None

    settings = AuthSettings(
        issuer_url=AnyHttpUrl("https://mcp.example.com"),
        resource_server_url=AnyHttpUrl("https://mcp.example.com"),
        required_scopes=[],
    )
    return _Provider(), settings


def _primer_status(app):
    from starlette.testclient import TestClient

    return TestClient(app).get("/api/agent/primer").status_code


def test_primer_requires_auth_in_pat_mode():
    app = build_app(_FakeBackend(), _FakeStore())
    assert _primer_status(app) == 401


def test_primer_requires_auth_in_oauth_mode():
    """אם זה נכשל — האנדפוינט פתוח לאינטרנט בפרודקשן."""
    provider, settings = _oauth_parts()
    app = build_app(
        _FakeBackend(),
        auth_provider=provider,
        auth_settings=settings,
        consent_routes=[],
    )
    assert _primer_status(app) == 401


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
