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


async def test_no_repo_backend_registers_no_repo_browser_tools():
    """**דפדפן** הריפו נשען על המראה, ולכן בלי ``repo_backend`` אין לו מה לקרוא.

    האסרשן על ``_REPO_BROWSER_TOOLS`` ולא על ``_ADMIN_TOOLS``, וזה ההבדל
    שהצריך את פיצול הקבוצה: כלי פתקי הריפו חסומים-לאדמין בדיוק כמוהם, אבל
    קוראים ל-``sticky_notes`` בלבד ולכן נרשמים תמיד.
    """
    from mcp_server.server import _REPO_BROWSER_TOOLS

    mcp = build_mcp(_FakeBackend())  # repo_backend omitted
    mcp._request_is_admin = lambda: True
    names = {t.name for t in await mcp.list_tools()}
    assert not (names & _REPO_BROWSER_TOOLS)


async def test_repo_note_tools_need_no_repo_backend():
    """הצד השני של אותו מטבע — ובלעדיו הפיצול הוא שינוי שם ריק.

    נופל אם כלי פתקי הריפו יועברו ל-``_register_repo_tools``, כלומר אם
    ההרשמה שלהם תותנה במראה. פריסה בלי דפדפן ריפו עדיין מחזיקה פתקים.
    """
    from mcp_server.server import _REPO_NOTE_TOOLS

    mcp = build_mcp(_FakeBackend())  # repo_backend omitted
    mcp._request_is_admin = lambda: True
    names = {t.name for t in await mcp.list_tools()}
    assert _REPO_NOTE_TOOLS <= names


async def test_repo_note_tools_are_hidden_from_a_non_admin():
    """ההסתרה היא UX; האכיפה היא ``require_admin`` בגוף — ושתיהן חייבות לחול.

    נופל אם שמות פתקי הריפו יישמטו מ-``_ADMIN_TOOLS`` בעת הפיצול.
    """
    from mcp_server.server import _ADMIN_TOOLS, _REPO_NOTE_TOOLS

    assert _REPO_NOTE_TOOLS <= _ADMIN_TOOLS

    mcp = build_mcp(_FakeBackend())
    # בלי request context ← fail-closed non-admin
    names = {t.name for t in await mcp.list_tools()}
    assert not (names & _REPO_NOTE_TOOLS)


async def test_note_search_is_visible_to_a_plain_user():
    """החיפוש אינו אדמין: הוא ``user_id``-scoped ולכן מחזיר רק פתקים של הקורא.

    נופל אם השם ייכנס ל-``_ADMIN_TOOLS`` "לשם עקביות" עם שאר פתקי הריפו.
    """
    from mcp_server.server import _ADMIN_TOOLS

    mcp = build_mcp(_FakeBackend())
    names = {t.name for t in await mcp.list_tools()}
    assert "codekeeper_search_notes" in names
    assert "codekeeper_search_notes" not in _ADMIN_TOOLS


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


def test_repo_note_creation_checks_admin_before_write(monkeypatch):
    """**אדמין ראשון, כתיבה שנייה** — וזה לא סדר שרירותי.

    בסדר ההפוך משתמש רגיל עם טוקן קריאה-בלבד היה מקבל "צריך הרשאת
    כתיבה", כלומר רמז שטוקן אחר יפתח לו את הכלי. זה שקר: הכלי חסום לו
    בכל טוקן שהוא.

    הטסט גם מוודא שהמזהה שנשלח ל-handler הוא **ערך ההחזרה** של
    ``require_admin`` — כך אי אפשר שהזהות ששימשה לשער תיבדל מזו ששימשה
    לשאילתה. נופל אם מחליפים אותו בקריאה שנייה ל-``current_user_id``.
    """
    import mcp_server.server as srv

    order: list[str] = []
    seen: dict = {}

    monkeypatch.setattr(srv, "require_admin", lambda ctx=None: (order.append("admin"), 4242)[1])
    monkeypatch.setattr(srv, "require_write", lambda ctx=None: order.append("write"))
    monkeypatch.setattr(
        srv.handlers, "create_repo_note",
        lambda backend, user_id, **kw: seen.update(user_id=user_id, **kw) or {"ok": True},
    )

    mcp = build_mcp(_FakeBackend())
    tool = mcp._tool_manager.get_tool("codekeeper_create_repo_note")
    tool.fn(ctx=None, repo_name="CodeBot", repo_path="a.py", content="שלום")

    assert order == ["admin", "write"]
    assert seen["user_id"] == 4242          # המזהה מהשער, לא קריאה נוספת
    assert seen["repo_name"] == "CodeBot"


def test_repo_note_listing_uses_the_identity_the_gate_returned(monkeypatch):
    import mcp_server.server as srv

    seen: dict = {}
    monkeypatch.setattr(srv, "require_admin", lambda ctx=None: 4242)
    monkeypatch.setattr(
        srv.handlers, "list_repo_notes",
        lambda backend, user_id, **kw: seen.update(user_id=user_id, **kw) or {"ok": True},
    )

    mcp = build_mcp(_FakeBackend())
    tool = mcp._tool_manager.get_tool("codekeeper_list_repo_notes")
    tool.fn(ctx=None, repo_name="CodeBot", repo_path="a.py")

    assert seen["user_id"] == 4242
