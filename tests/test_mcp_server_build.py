"""Smoke tests for the FastMCP wiring (tools registered, health route present)."""

import re
from pathlib import Path

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
    "codekeeper_get_note",
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


async def test_get_note_is_a_plain_user_tool_declared_read_only():
    """``codekeeper_get_note`` גלוי לכל משתמש ומוצהר קריאה — ולכן במאגר הקריאות.

    אינו ב-``_ADMIN_TOOLS`` בכוונה: פתק ריפו חסום לאדמין **בגוף**, ומי שאינו
    אדמין מקבל ``not_found`` — לא ``require_admin`` שזורק ומגלה שהמזהה קיים.
    ``readOnlyHint`` הוא מה ש-``_declares_write`` קורא, ולכן הוא מה שמוציא
    את הכלי מתור הכתיבה.
    """
    from mcp_server.server import _ADMIN_TOOLS

    mcp = build_mcp(_FakeBackend())
    by_name = {t.name: t for t in await mcp.list_tools()}  # תצוגת non-admin

    tool = by_name["codekeeper_get_note"]
    assert "codekeeper_get_note" not in _ADMIN_TOOLS
    assert tool.annotations.readOnlyHint is True
    assert tool.inputSchema["required"] == ["note_id"]


@pytest.mark.parametrize("admin", [True, False])
async def test_get_note_derives_the_admin_flag_from_the_identity_it_queries_with(
    monkeypatch, admin
):
    """זהות אחת לשער ולשאילתה.

    ``is_admin`` נגזר מאותו ``user_id`` שנשלח ל-handler, ולא מקריאה שנייה
    ל-``current_user_id`` — אותה הכרעה שמאחורי ערך ההחזרה של ``require_admin``
    ב-``list_repo_notes``. הקריאה עוברת דרך ``mcp.call_tool`` הציבורי, המסלול
    שהלקוח באמת מפעיל.
    """
    import mcp_server.server as srv

    asked: list[int] = []
    seen: dict = {}
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: 4242)
    monkeypatch.setattr(srv, "is_admin_user", lambda uid: (asked.append(uid), admin)[1])
    monkeypatch.setattr(
        srv.handlers, "get_note",
        lambda backend, user_id, **kw: seen.update(user_id=user_id, **kw) or {"ok": True},
    )

    mcp = build_mcp(_FakeBackend())
    await mcp.call_tool("codekeeper_get_note", {"note_id": "a" * 24})

    assert seen == {"user_id": 4242, "note_id": "a" * 24, "is_admin": admin}
    assert asked == [4242]


async def test_the_note_tool_descriptions_close_the_read_edit_loop():
    """שרשור שלם, ואף תיאור לא אמר אותו: חיפוש ← ``get_note`` ← עריכה ← ``conflict`` ← ``get_note``.

    כמו ``test_the_descriptions_name_the_search_to_range_chain``: הפער היה
    בתיאורים ולא ביכולת. ``search_notes`` שלח לקרוא "בכלי הרשימה" — לוח של
    18 פתקים בכ-65,000 תווים כדי להגיע לפתק אחד — ו-``note_str_replace``
    אמר ``conflict`` בלי לומר מה לקרוא כדי לנסות שוב. ההחלטה שפגיעת חיפוש
    לעולם אינה נושאת תוכן **נשארת**, ולכן גם היא נאכפת כאן.
    """
    mcp = build_mcp(_FakeBackend())
    by_name = {t.name: t for t in mcp._tool_manager.list_tools()}

    def desc(name):
        return by_name[name].description

    # חיפוש ← קריאה: את הפתק קוראים ב-get_note, לא בכלי הרשימה.
    search = desc("codekeeper_search_notes")
    assert "codekeeper_get_note;" in search
    assert "hits never carry content" in search
    assert "read the note itself with that tool" not in search

    # עריכה ← conflict ← get_note ← ניסיון חוזר, בסדר הזה. ``get_note`` מוזכר
    # גם בפתיח (מאיפה לוקחים note_id), ולכן מחפשים את האזכור שאחרי conflict.
    replace = desc("codekeeper_note_str_replace")
    assert "conflict" in replace and "codekeeper_get_note" in replace
    conflict_at = replace.index("conflict")
    assert (
        conflict_at
        < replace.index("codekeeper_get_note", conflict_at)
        < replace.index("call this tool again")
    )

    # ההווה מול העבר: השניים מצביעים זה על זה, כדי שלא ייווצר ספק מי מחזיר את ההווה.
    current, previous = desc("codekeeper_get_note"), desc("codekeeper_get_note_version")
    assert "codekeeper_get_note_version" in current and "CURRENT" in current
    assert "codekeeper_get_note" in previous and "PREVIOUS" in previous

    # ההרשאה נאמרת: לא בעלים, או פתק ריפו בלי אדמין ← not_found.
    assert "not_found" in current and "admin" in current

    # רשימה קטנה ואחריה get_note — בשני כלי הרשימה, והפרמטר יושב בסכימה
    # עם ברירת מחדל ששומרת על ההתנהגות הישנה ועם היחידה נקובה.
    for name in ("codekeeper_list_notes", "codekeeper_list_board_notes"):
        assert "include_content=false" in desc(name) and "codekeeper_get_note" in desc(name)
        prop = by_name[name].parameters["properties"]["include_content"]
        assert prop["type"] == "boolean" and prop["default"] is True
        assert "content_bytes" in prop["description"] and "BYTES" in prop["description"]
        assert "codekeeper_get_note" in prop["description"]


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


async def test_repo_note_creation_checks_admin_before_write(monkeypatch):
    """**אדמין ראשון, כתיבה שנייה** — וזה לא סדר שרירותי.

    בסדר ההפוך משתמש רגיל עם טוקן קריאה-בלבד היה מקבל "צריך הרשאת
    כתיבה", כלומר רמז שטוקן אחר יפתח לו את הכלי. זה שקר: הכלי חסום לו
    בכל טוקן שהוא.

    הטסט גם מוודא שהמזהה שנשלח ל-handler הוא **ערך ההחזרה** של
    ``require_admin`` — כך אי אפשר שהזהות ששימשה לשער תיבדל מזו ששימשה
    לשאילתה. נופל אם מחליפים אותו בקריאה שנייה ל-``current_user_id``.

    הקריאה עוברת דרך ``mcp.call_tool`` הציבורי ולא דרך ``_tool_manager``:
    הפנימיות תלויות-גרסה, והמסלול הציבורי הוא זה שהלקוח באמת מפעיל.
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
    await mcp.call_tool(
        "codekeeper_create_repo_note",
        {"repo_name": "CodeBot", "repo_path": "a.py", "content": "שלום"},
    )

    assert order == ["admin", "write"]
    assert seen["user_id"] == 4242          # המזהה מהשער, לא קריאה נוספת
    assert seen["repo_name"] == "CodeBot"


async def test_repo_note_listing_uses_the_identity_the_gate_returned(monkeypatch):
    import mcp_server.server as srv

    seen: dict = {}
    monkeypatch.setattr(srv, "require_admin", lambda ctx=None: 4242)
    monkeypatch.setattr(
        srv.handlers, "list_repo_notes",
        lambda backend, user_id, **kw: seen.update(user_id=user_id, **kw) or {"ok": True},
    )

    mcp = build_mcp(_FakeBackend())
    await mcp.call_tool(
        "codekeeper_list_repo_notes", {"repo_name": "CodeBot", "repo_path": "a.py"}
    )

    assert seen["user_id"] == 4242


async def test_an_identifier_query_reaches_the_section_through_the_public_tool(monkeypatch):
    """התאמת המזהה, דרך הממשק שהלקוח באמת מפעיל.

    **למה הטסט הזה קיים בנפרד מ-``tests/test_mcp_docs_handlers.py``.** שם
    נקראת ``docs_handlers.docs_get_section`` ישירות — וזה מוכיח שהפונקציה
    עובדת, לא שה**כלי** עובד. הצרכן של ``codekeeper_docs_get_section`` הוא
    לקוח MCP, ובינו לבין ה-handler יושבים הרישום ב-``AdminAwareFastMCP``,
    ולידציית הפרמטרים של pydantic, ``current_user_id``, וההסבה של ערך
    ההחזרה לבלוק תוכן. טסט שאינו עובר דרכם מאמת את המפרט ולא את הצרכן —
    זה ``T1`` ב-``TESTING-PATTERNS.md``, ובאותו נימוק בדיוק ``call_tool``
    הציבורי נבחר כאן על פני ``_tool_manager``, כמו בטסטי הפתקים למעלה.

    צורת ההחזרה **נמדדה ולא הונחה**: ב-``mcp==1.28.1`` החתימה היא
    ``Sequence[ContentBlock] | dict``, ובפועל חוזר בלוק טקסט יחיד שגופו
    ה-JSON — כלומר בדיוק הבייטים שהלקוח מקבל.
    """
    import json

    import mcp_server.server as srv

    title = "K11. כשל שמדווח בערך החזרה נבלע"
    rst = f"Doc\n===\n\n{title}\n{'-' * 60}\n\nגוף הסעיף\n"

    class _RstRepoBackend(_FakeRepoBackend):
        def get_file(self, **k):
            return {"ok": True, "status": "ok",
                    "file": {"path": k.get("path"), "ref": "HEAD",
                             "resolved_commit": "c0ffee"},
                    "content": rst}

    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: 7)

    mcp = build_mcp(_FakeBackend(), repo_backend=_RstRepoBackend())
    blocks = await mcp.call_tool(
        "codekeeper_docs_get_section", {"path": "x", "section": "K11"}
    )

    (block,) = blocks          # בלוק אחד, ולא "הראשון מתוך כמה"
    payload = json.loads(block.text)
    assert payload["ok"] is True and payload["mode"] == "section"
    assert payload["section"] == title
    assert "גוף הסעיף" in payload["content"]


async def test_a_markdown_section_reaches_the_caller_through_the_public_tool(monkeypatch):
    """הפיצ'ר של ה-PR הזה, דרך הממשק שהלקוח באמת מפעיל.

    התאום של הטסט שמעליו, ומאותו נימוק (``T1``): ``tests/test_mcp_docs_handlers.py``
    מוכיח שה-handler מנתב נכון, וזה מוכיח שה**כלי** עושה זאת — דרך
    הרישום, ולידציית הפרמטרים, ``current_user_id`` וההסבה ל-JSON.

    הקלט הוא הצורה שבה הפיצ'ר באמת ייקרא: מזהה ``K11`` בעמוד Markdown של
    ``amir-bug-patterns``, עם בקטיקים בכותרת — כלומר גם הניתוב לפי סיומת,
    גם התאמת המזהה, וגם "הכותרת חוזרת כטקסט מקור" באותה קריאה.
    """
    import json

    import mcp_server.server as srv

    monkeypatch.setenv("MCP_DOCS_REPO", "CodeBot,amir-bug-patterns")
    title = "K11. כשל שמדווח ב-`return` נבלע"
    md = f"# דפוסים\n\n## {title}\n\nגוף הסעיף\n\n## K12. משהו אחר\n"

    class _MdRepoBackend(_FakeRepoBackend):
        def get_file(self, **k):
            self.asked = dict(k)
            return {"ok": True, "status": "ok",
                    "file": {"path": k.get("path"), "ref": "HEAD",
                             "resolved_commit": "c0ffee"},
                    "content": md}

    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: 7)

    repo_backend = _MdRepoBackend()
    mcp = build_mcp(_FakeBackend(), repo_backend=repo_backend)
    blocks = await mcp.call_tool("codekeeper_docs_get_section", {
        "path": "CRITICAL-PATTERNS", "section": "K11",
        "repo": "amir-bug-patterns",
    })

    (block,) = blocks
    payload = json.loads(block.text)
    assert payload["ok"] is True and payload["mode"] == "section"
    assert payload["section"] == title           # טקסט מקור, עם הבקטיקים
    assert "גוף הסעיף" in payload["content"]
    assert "K12" not in payload["content"]       # הסעיף נגמר לפני הבא באותה רמה
    assert payload["includes"] == []             # שדה של RST, ריק ב-Markdown
    # והשורש והסיומת הגיעו מהמדיניות של הריפו, לא מזו של CodeBot.
    assert repo_backend.asked["path"] == "CRITICAL-PATTERNS.md"


async def test_str_replace_is_not_advertised_as_idempotent():
    """``note_str_replace`` דורס אבל **אינו** אידמפוטנטי, ולכן אינו יכול
    לשאת את האנוטציה של ``update_note``.

    נמדד מול ``_apply_edit`` האמיתי: גוף ``"a"`` עם ``old="a"``/``new="aa"``
    ו-``replace_all`` נותן ``"aa"`` ← ``"aaaa"`` ← ``"aaaaaaaa"``. הסכנה
    המעשית ב-``idempotentHint`` שגוי היא לקוח שמנסה שוב אחרי timeout
    ומכפיל את ההחלפה על גוף שכבר הוחלף.
    """
    from mcp_server.handlers import _apply_edit

    body = "a"
    for _ in range(2):
        body, _n, err = _apply_edit(body, "a", "aa", True)
        assert err is None
    assert body == "aaaa", body  # ראיה: קריאה חוזרת משנה את המצב שוב

    mcp = build_mcp(_FakeBackend())
    by_name = {t.name: t for t in await mcp.list_tools()}
    ann = by_name["codekeeper_note_str_replace"].annotations
    assert ann.idempotentHint is False
    assert ann.destructiveHint is True
    # ``update_note`` כן אידמפוטנטי (אותו קלט פעמיים ⇒ אותו מצב סופי)
    assert by_name["codekeeper_update_note"].annotations.idempotentHint is True


async def test_save_file_description_matches_what_the_tool_actually_does():
    """התיאור הוא מה שהלקוח קורא כדי לבחור כלי — ולכן הוא חלק מהחוזה.

    הוא הבטיח "create a new file **or update an existing one**" גם אחרי
    שהכלי התחיל לסרב לשם תפוס, כלומר שלח את הלקוח לקריאה שתידחה. אותה
    טעות בכיוון ההפוך של ``TESTING-PATTERNS`` T1: המפרט אינו הצרכן, אבל
    כשהמפרט **הוא** מה שהצרכן קורא — הוא חייב להיות נכון.
    """
    mcp = build_mcp(_FakeBackend())
    tool = {t.name: t for t in await mcp.list_tools()}["codekeeper_save_file"]
    text = (tool.description or "").lower()

    assert "update an existing" not in text, tool.description
    # ומה שכן צריך להיות שם: לאן פונים כשהשם תפוס
    assert "codekeeper_edit_file" in text
    assert "codekeeper_append_file" in text


async def test_the_description_names_both_size_ceilings():
    """התיאור הוא מה שהסוכן קורא כדי להחליט איך לקרוא לכלי.

    בגרסה הקודמת ``(max 500KB)`` ישב במשפט הראשון, ומיד אחריו הופיע
    "read only that range **instead of the whole file**", ומזה השתמעה
    מסקנה שלא הייתה נכונה אז: שהטווח עוקף את התקרה.

    היום הוא **כן** עוקף — אבל לתקרה אחרת, לא לאין-תקרה. ולכן שני
    המספרים חייבים להופיע: סוכן שקיבל ``too_large`` צריך לדעת אם ``lines``
    יעזור לו (קובץ בין 500KB ל-10MB) או שהקובץ מעבר לגבול בכל מקרה.
    תיאור שמזכיר רק אחד מהם מחזיר בדיוק את הניחוש שהוא נועד למנוע.
    """
    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    description = mcp._tool_manager.get_tool("codekeeper_get_repo_file").description

    assert "500KB for a whole file" in description
    assert "10MB with lines or outline" in description
    assert description.index("500KB") > description.index("lines=[start, end]")
    assert "Binary files return metadata only" in description


async def test_the_description_tells_the_agent_which_languages_have_a_map():
    """סוכן שיבקש מפה של סיומת שאין לה סורק ויקבל ``no_outline`` צריך לדעת
    שזו התנהגות מוצהרת ולא תקלה — אחרת הוא ינסה שוב.

    **הפרוזה כאן נשאה פעם את ``.rst`` כדוגמה, והיא התיישנה** ברגע שנוספה לו
    תמיכה — בדיוק אותה סחיפה שהטסט הזה קיים כדי למנוע בתיאור עצמו. הטענות
    עמדו בה, והניסוח לא, ולכן הוא נוקב עכשיו בקטגוריה ולא בסיומת.

    התיאור אמר ``Python only`` עד שנוספה תמיכה ב-HTML/Jinja; המשפט הזה
    הפך לשגוי באותו PR שהוסיף אותה, וזו הסיבה שהטסט נוקב במה שכן נתמך
    ולא במה שאינו.

    **פירוט השפות עבר לתיאור הפרמטר ``outline``**, כי תיאור הכלי הגיע
    ל-2,482 תווים ונחתך אצל הלקוח בדיוק שם. הטענות לא נחלשו — הן נבדקות
    במקום שבו הטקסט יושב עכשיו. מה שנשאר על תיאור הכלי הוא ההודעה
    ש-``outline=true`` קיים ומה קורה לסיומת שאין לה מפה, כי זו ההחלטה
    שסוכן מקבל לפני שהוא פותח את סכמת הפרמטרים.
    """
    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    tool = mcp._tool_manager.get_tool("codekeeper_get_repo_file")
    description = tool.description
    outline_doc = tool.parameters["properties"]["outline"]["description"]

    assert "outline=true" in description
    assert "no_outline" in description
    assert "Python" in outline_doc
    assert "Jinja" in outline_doc
    # הבדל מהותי לסוכן: פייתון נותן שמות מנוקדים, HTML שטוחים.
    assert "dotted" in outline_doc and "flat" in outline_doc

    # ``page/per_page`` היה המשפט היחיד בתיאור **בלי שום טסט**, ולכן הוא
    # נשמט בטיוטה הראשונה של הפיצול הזה בלי שאף בדיקה שמה לב — הכשל
    # שבדיוק נמנע כאן. עמוד ראשון שנראה כמו כל המפה הוא כשל שקט:
    # ``OUTLINE_PER_PAGE_DEFAULT`` הוא 100, ולכן 486 הסימבולים שנמדדו על
    # הקובץ הצפוף בקורפוס מתפרסים על חמישה עמודים.
    assert "page/per_page" in outline_doc


async def test_the_description_says_symbol_works_on_the_non_python_names():
    """פיצ'ר שאף אחד לא קורא לו הוא פיצ'ר שאינו קיים.

    ``symbol=`` עובד על כל שם שהמפה מחזירה, אבל בתיאור הוא ישב בתוך
    המשפט של פייתון — "Names are fully qualified with dots (Class.method,
    outer.inner), symbol= filters on that full name" — ומיד אחריו בא
    המשפט שאומר ש-HTML נותן שמות **שטוחים**. סוכן שקורא את זה קושר את
    הפילטר לשמות מנוקדים ולא ינסה אותו על ``@media``.

    **וזה לא היפותטי:** נמדד שעל הקובץ הצפוף בקורפוס ``symbol="@media"``
    מצמצם 486 סימבולים בחמישה עמודים לשישה בעמוד אחד — ובכל זאת הפילטר
    נשכח בסשן שבו הוא תועד. הדוגמאות בפסוקית הן מה שגורם לסוכן להשתמש
    בזה, ולכן הן נבדקות ולא רק המילה ``symbol=``.

    ההתנהגות שהפסוקית מבטיחה נאכפת ב-``tests/test_mcp_outline.py``, ב-
    ``test_symbol_narrows_a_css_file_to_its_at_rules`` וב-
    ``test_symbol_narrows_a_template_to_the_names_that_carry_the_term`` —
    כאן נבדק רק שהיא **נאמרת**. שניהם נדרשים: פסוקית בלי טסט היא הבטחה
    שאין מי שאוכף, וטסט בלי פסוקית הוא התנהגות שאף אחד לא ימצא.

    **הפסוקית עברה לתיאור הפרמטר ``symbol``**, כי תיאור הכלי נחתך אצל
    הלקוח בדיוק במשפט הזה — כלומר הפילטר שוב לא נקרא, מסיבה חדשה.
    ההודעה שהוא קיים נשארת על תיאור הכלי ונאכפת ב-
    ``test_the_tool_description_points_at_the_parameters_that_carry_the_detail``.
    """
    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    tool = mcp._tool_manager.get_tool("codekeeper_get_repo_file")
    symbol_doc = tool.parameters["properties"]["symbol"]["description"]

    assert 'symbol="@media"' in symbol_doc
    assert "not just the dotted Python ones" in symbol_doc

    # **והפסוקית חייבת לומר שהסינון הוא בהכלה, לא בתחילית.** ניסוח קודם
    # הבטיח ש-``symbol="_"`` מחזיר "only the RST label targets", ונמדד
    # שהוא מחזיר 29 תוויות ו-133 שורות שאינן תוויות ב-79 קבצים. הבטחה
    # שהקוד אינו מקיים גרועה מהיעדר הבטחה, כי סוכן בונה עליה.
    assert "Matching is by substring in every language" in symbol_doc
    assert "also any heading containing an underscore" in symbol_doc

    # **והאיסור חל על שלושת השדות ולא על אחד.** כשהטקסט ישב במחרוזת אחת
    # די היה לבדוק אותה; עכשיו ההבטחה השגויה יכולה לחזור דרך כל אחד
    # משלושת המקומות, ובדיקה על אחד בלבד הייתה נותנת כיסוי מדומה.
    for field in (tool.description, symbol_doc,
                  tool.parameters["properties"]["outline"]["description"]):
        assert "only the RST label targets" not in field

    # ושהטקסט הגולמי של כותרת RST נאמר, כי הוא מה שמונע מ-
    # ``symbol="backup_service"`` למצוא את העמוד ששמו כך.
    assert "the source text rather than the rendered text" in symbol_doc
    assert 'symbol="backup_service"' in symbol_doc

    # **וה-escape עצמו נבדק, ולא רק השם בלי הלוכסן.** ``symbol="backup_service"``
    # לבדו עובר גם על טקסט שאיבד את ה-``\\``, וזה בדיוק מה שקורה כשמעתיקים
    # את המחרוזת דרך Markdown או דרך שכבת escaping נוספת — הדוגמה הופכת
    # לשקר שקט: היא טוענת שהשם לא נמצא, בזמן שהיא מציגה שם שכן היה נמצא.
    assert r"services.backup\_service" in symbol_doc
    assert r"services.backup\\_service" not in symbol_doc


async def test_the_description_names_every_suffix_the_outline_router_supports():
    """``_SCANNERS`` מצהיר על עצמו כמקור האמת היחיד — כאן זה נאכף.

    התיאור הוא מה שלקוח MCP קורא כדי להחליט אם בכלל לשלוח
    ``outline=true``. סיומת שתתווסף לטבלה בלי שהתיאור יעודכן היא פיצ'ר
    שעובד ואף אחד לא קורא לו — כשל שקט לגמרי, ובדיוק הדריפט שההערה מעל
    הטבלה טוענת שהיא מונעת. בלי הטסט הזה, ההערה מבטיחה יותר ממה שקיים.

    הכיוון הוא מהטבלה אל התיאור בלבד: התיאור מותר לו לפרט דברים נוספים,
    אבל אסור לו להשמיט סיומת שהראוטר כן מקבל.

    **ההתאמה היא על אסימון שלם ולא על תת-מחרוזת**, אחרת הטסט חלש ממה
    שהוא מתיימר: ``".py" in "(.pyi)"`` הוא ``True``, ולכן מחיקת ``.py``
    מהתיאור הייתה עוברת בשקט. אותו כשל בדיוק חוזר ב-PR הבא, שבו ``.j2``
    ו-``.html.j2`` יחיו זה לצד זה. הגבולות משני הצדדים חוסמים גם ``\\w``
    וגם נקודה, כך ש-``.j2`` אינו מתאים בתוך ``.html.j2``.

    **היעד הוא תיאור הפרמטר ``outline`` ולא תיאור הכלי**, כי רשימת
    הסיומות עברה לשם כשתיאור הכלי קוצר. ההערה מעל ``_SCANNERS`` מנוסחת
    לפי אותו מיקום — שתי הרשימות עדיין חייבות לא להיסחף זו מזו.
    """
    import re

    from mcp_server.outline import _SCANNERS

    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    tool = mcp._tool_manager.get_tool("codekeeper_get_repo_file")
    outline_doc = tool.parameters["properties"]["outline"]["description"]

    for suffix in _SCANNERS:
        token = re.compile(rf"(?<![\w.]){re.escape(suffix)}(?![\w.])")

        assert token.search(
            outline_doc
        ), f"{suffix} בטבלת הראוטר אבל לא בתיאור הפרמטר outline"


async def test_the_descriptions_name_the_search_to_range_chain():
    """שני הכלים מרכיבים שרשור שלם, ואף אחד מהם לא אמר את זה.

    ``codekeeper_search_repo`` מחזיר ``line`` לכל פגיעה (ראו
    ``repo_backend.search``, שבונה את השורה מתוך ``r.get("line")``), ומשם
    ``codekeeper_get_repo_file`` עם ``lines=`` קורא בדיוק את הקטע שההתאמה
    הצביעה עליו. מי שיודע את זה לא מושך קובץ שלם כדי להפנות לכלל בודד.

    **הפער היה בתיאור ולא ביכולת:** סוכן שעבד מול המראה יום שלם ביקש כלי
    אאוטליין שכבר היה קיים, כי שני התיאורים תיארו *מה חוזר* ולא *מה הצעד
    הבא*. ``path+line`` הופיע בתיאור החיפוש מההתחלה, והוא לא הספיק — ולכן
    הטסט הזה נוקב במשפט שמתאר פעולה, לא בהזכרה של השדה.

    שני הכיוונים נאכפים, כי תיאור אחד בלבד סוגר חצי שרשור: מי שהתחיל
    בחיפוש צריך לדעת לאן להמשיך, ומי שהתחיל בקריאת קובץ צריך לדעת מאיפה
    להשיג מספר שורה במקום לנחש טווח.
    """
    import re

    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())

    search = mcp._tool_manager.get_tool("codekeeper_search_repo").description
    read = mcp._tool_manager.get_tool("codekeeper_get_repo_file").description

    # חיפוש ← קריאת טווח. שתי טענות נפרדות, ושתיהן חייבות לשרוד כל
    # ניסוח מחדש של התיאור: **מה** חוזר בכל פגיעה, ו**מה הצעד הבא** איתו.
    # המחרוזות עצמן ישתנו ביום שהתיאור ייכתב מחדש — מה שלא ישתנה הוא
    # שתיאור שמפרט רק את השדות, בלי משפט שמתאר פעולה, מחזיר בדיוק את
    # הפער שהטסט הזה נולד ממנו.
    assert "path, line" in search
    assert "The next step on a hit is" in search
    assert "codekeeper_get_repo_file" in search
    # ``lines=[line`` ולא ``lines=`` בלבד: שני התיאורים נקראים בנפרד, וסוכן
    # שראה רק את תיאור החיפוש צריך ללמוד מכאן גם את **צורת** הפרמטר.
    assert "lines=[line" in search

    # קריאת טווח ← חיפוש (הכיוון ההפוך).
    assert "codekeeper_search_repo" in read
    assert "`line` for every match" in read

    # המשפט החדש חייב לשבת לפני תקרות הגודל ולא להקדים את ``lines=[start,
    # end]``, אחרת הוא מזיז את הסדר ששלושת הטסטים שמעליו אוכפים. הגבול
    # העליון הוא ``outline=true`` ולא ``500KB``: שני המשפטים הם שתי
    # התשובות לאותה שאלה, ותיאור שמפריד ביניהם בפסקת האאוטליין כולה
    # מאבד בדיוק את הסמיכות שבגללה המשפט נכתב.
    assert read.index("codekeeper_search_repo") > read.index("lines=[start, end]")
    assert read.index("codekeeper_search_repo") < read.index("outline=true")
    assert read.index("codekeeper_search_repo") < read.index("500KB")

    # **וכל דוגמת טווח בתיאור חייבת להיות חוקית מול המקור.** ``line`` שחוזר
    # מהחיפוש הוא מספר בודד, ו-``normalize_line_range`` דוחה כל אורך שאינו
    # 2 (נמדד: גם ``172`` וגם ``[172]`` מחזירים ``invalid_line_range``) —
    # ולכן תיאור שקורא לשורה החוזרת "הטווח" שולח את הקורא לקריאה שנדחית,
    # ומבטיח שרשור שלא עובד. זה היה הנוסח הראשון של המשפט הזה, ונתפס
    # בריוויו. האכיפה היא על **צורת הדוגמה**, לא על ניסוח, כי כל ניסוח
    # שיחזור לטעות הזו יפר גם אותה.
    # הכלל הגנרי לבדו אינו מספיק: הניסוח שנתפס בריוויו ("that line **is**
    # the lines= range") לא הכיל סוגריים בכלל, ולכן היה חומק ממנו. הדוגמה
    # שבונה טווח מתוך ``line`` היא מה שסוגר את הפער, והיא נדרשת במפורש.
    assert "lines=[line" in read

    # **הסריקה כוללת את תיאורי הפרמטרים, לא רק את תיאורי הכלים.** מאז
    # שהפירוט על האאוטליין ועל ``symbol=`` עבר לשם, דוגמת טווח שתיכתב
    # באחד מהם לא הייתה נבדקת — וכיסוי שממשיך לעבור בזמן שהטקסט שהוא
    # שומר עליו זז למקום אחר הוא בדיוק הכשל השקט שהטסט הזה קיים למנוע.
    # היום אין בהם אף דוגמת ``lines=``, כלומר הלולאה רצה עליהם ריקה —
    # וזה המצב שהיא נועדה לשמר.
    repo_file = mcp._tool_manager.get_tool("codekeeper_get_repo_file")
    scanned = (
        search,
        read,
        repo_file.parameters["properties"]["outline"]["description"],
        repo_file.parameters["properties"]["symbol"]["description"],
    )
    for description in scanned:
        for example in re.findall(r"lines=\[([^\]]*)\]", description):
            assert len(example.split(",")) == 2, f"lines=[{example}] אינו זוג"
        # הצורה הסקלרית (``lines=42``) אינה מתקבלת בכלל, אז היא לא תופיע.
        assert not re.search(r"lines=\s*\d", description), description


async def test_the_tool_description_points_at_the_parameters_that_carry_the_detail():
    """הפירוט על המפה ועל הסינון עבר לתיאורי הפרמטרים — והכלי חייב להפנות.

    תיאור הכלי הגיע ל-2,482 תווים ונחתך אצל הלקוח באמצע המשפט על RST ועל
    ``symbol=``. הפיצול מרפא את החיתוך ופותח כשל אחר, מאותה משפחה בדיוק:
    סוכן שקורא רק את תיאור הכלי לא יֵדע ש-``symbol=`` קיים אם התיאור אינו
    נוקב בו. זה אותו "פיצ'ר שאף אחד לא קורא לו הוא פיצ'ר שאינו קיים"
    שהוליד את ``test_the_description_says_symbol_works_on_the_non_python_names``,
    רק במיקום חדש. לכן נאכפים כאן **שני קצות השרשרת**: שהכלי מפנה,
    ושהיעד באמת נושא את הפירוט ואינו שדה ריק.

    **וזה מחליף טענה שאיבדה משמעות, ולא טענה שנמחקה.** הגלגול הקודם אכף
    ש-``symbol="@media"`` מופיע **לפני** ``500KB`` באותה מחרוזת, כדי
    שהפילטר לא ייקרא כמדיניות גודל אלא כדרך לחתוך את המפה. אחרי הפיצול
    השניים אינם באותה מחרוזת כלל — הסכנה ההיא נמנעת מבנית, והטענה על
    הסדר לא הייתה יכולה לרוץ.
    """
    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    tool = mcp._tool_manager.get_tool("codekeeper_get_repo_file")
    props = tool.parameters["properties"]

    # קצה ראשון: הכלי אומר שהפירוט קיים, ונוקב בשמות הפרמטרים שנושאים אותו.
    assert "outline" in tool.description
    assert "symbol" in tool.description
    assert "parameters" in tool.description

    # קצה שני: היעד נושא את הפירוט בפועל.
    assert 'symbol="@media"' in props["symbol"]["description"]
    assert "not just the dotted Python ones" in props["symbol"]["description"]
    assert "page/per_page" in props["outline"]["description"]


#: תקרת תווים לתיאור כלי. **המספר נמדד ולא נבחר כי הוא נראה עגול.**
#:
#: מה שהוא מונע: לקוח MCP שחותך תיאור ארוך חותך את **הסוף**, כלומר את
#: הפסקאות האחרונות. ``codekeeper_get_repo_file`` הגיע ל-2,482 תווים והגיע
#: לסוכן חתוך באמצע המשפט על RST ועל ``symbol=`` — שני פיצ'רים שעבדו ואף
#: לקוח לא קרא עליהם.
#:
#: הבחירה ב-1,400: הכלי הארוך ביותר מבין 32 הכלים הוא
#: ``codekeeper_get_repo_file`` ב-1,125 תווים. כלומר המספר נותן מרווח
#: למשפט-שניים של גדילה טבעית, ונשאר הרבה מתחת לאזור שבו החיתוך נצפה
#: בפועל.
#:
#: **שלושת המספרים בשורות האלה אינם פרוזה — הם מושווים לקוד בכל ריצה**
#: ב-``test_the_ceiling_rationale_matches_what_the_tools_actually_carry``.
#: הנוסח הקודם מנה שלושה מספרים אחרים, ו**שלושתם התיישנו בלי שאיש ידע**:
#: הוא טען שהשני אחרי הארוך ביותר הוא ``codekeeper_docs_get_section``
#: ב-652 — בזמן שהוא כבר היה 823, והשני בפועל היה כלי אחר לגמרי. מספר
#: שמתאר מצב ומתעדכן בנפרד ממנו הוא ``state-record-without-state-change``,
#: והתרופה היא לא לעדכן אותו אלא לקשור אותו. **והתקדים כבר בריפו:**
#: ``services/md_parser.py`` משווה את שני המספרים שבפרוזה שלו למחוללים
#: ב-``tests/test_md_parser_oracle.py::test_the_generated_shape_count_matches_the_prose``,
#: מאותו נימוק בדיוק.
#:
#: .. warning::
#:
#:    **התקרה חלה על ``description`` בלבד, וזו הכרעה ולא שלמות.** מה
#:    שנמדד הוא שהשרת שולח תיאור פרמטר במלואו ב-``inputSchema``
#:    (``mcp==1.28.1``, עם ריצת בקרה שבלי ``Field`` השדה חוזר ``None``) —
#:    **לא** מה שלקוח מציג ממנו. נצפה לקוח שמקצר תיאור פרמטר לכ-120 תווים
#:    בשורת סיכום, ובאותו לקוח תיאור כלי בן 2,482 תווים הגיע שלם. כלומר
#:    התקרה שומרת על השדה שנחתך, ואינה מבטיחה דבר על תיאורי הפרמטרים אצל
#:    כל לקוח.
_TOOL_DESCRIPTION_MAX_CHARS = 1_400


async def test_no_tool_description_exceeds_the_truncation_budget():
    """אף תיאור כלי אינו ארוך מכדי שלקוח יגיש אותו במלואו.

    **``_tool_manager.list_tools()`` ולא ``mcp.list_tools()``, וזה העיקר
    כאן.** ``AdminAwareFastMCP`` מסנן את ``_ADMIN_TOOLS`` מבקשה שאינה של
    אדמין, ובטסט אין request context — ולכן fail-closed מחזיר את תצוגת
    ה-non-admin. נמדד: 22 כלים מול 29, ו**שבעת החסרים כוללים את
    ``codekeeper_get_repo_file`` עצמו**, הכלי שבגללו התקרה הזאת קיימת.
    טסט שהיה רץ על התצוגה המסוננת היה ירוק בלי לכסות את המקרה היחיד
    שהפיל אותנו — כיסוי מדומה שנראה רחב יותר ממה שהוא.

    התקרה היא על כל הכלים ולא על אחד, כי זו מחלקת בעיה ולא מופע: כל תיאור
    שיגדל מעבר לה ייחתך אצל הלקוח באותה צורה בדיוק.
    """
    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())

    over = {
        tool.name: len(tool.description or "")
        for tool in mcp._tool_manager.list_tools()
        if len(tool.description or "") > _TOOL_DESCRIPTION_MAX_CHARS
    }

    assert not over, (
        f"תיאור כלי מעל {_TOOL_DESCRIPTION_MAX_CHARS} תווים — לקוח יחתוך את "
        f"סופו: {over}. העבירו את העודף ל-Field(description=...) של הפרמטר "
        f"שהוא מתאר, במקום למחוק אותו."
    )


#: שלושת המספרים שההנמקה מעל :data:`_TOOL_DESCRIPTION_MAX_CHARS` נוקבת
#: בהם, בסדר שבו הם מופיעים שם: כמה כלים, מי הארוך ביותר, וכמה תווים יש בו.
_CEILING_RATIONALE_RE = re.compile(
    r"הכלי הארוך ביותר מבין (?P<tools>[\d,]+) הכלים הוא\s*\n"
    r"#: ``(?P<name>[a-z_]+)`` ב-(?P<chars>[\d,]+) תווים"
)


def _int(text: str) -> int:
    """מספר מהפרוזה, בלי הפסיקים שמפרידים אלפים."""
    return int(text.replace(",", ""))


async def test_the_ceiling_rationale_matches_what_the_tools_actually_carry():
    """ההנמקה שמעל התקרה מתארת את המצב **של היום**, ולא של יום שעבר.

    **זה שומר על נימוק, לא על התנהגות — וזו בדיוק הסיבה שהוא נחוץ.** מספר
    בפרוזה אינו מפיל שום דבר כשהוא מתיישן: הוא פשוט הופך למשפט שקרי שהקורא
    הבא בונה עליו. הנוסח שקדם לטסט הזה טען ש-``codekeeper_docs_get_section``
    הוא השני באורכו ב-652 תווים; במדידה הוא היה 823, והשני בפועל היה כלי
    אחר. אף בדיקה לא צעקה, כי לא היה מה שיצעק.

    **ולמה דווקא שלושת המספרים האלה ולא גם החציון.** הם אלה שנושאים את
    הטיעון — "התקרה גבוהה מהארוך ביותר, עם מרווח" — ולכן דווקא הם חייבים
    להיות נכונים. החציון היה קישוט, והוא גם הפריט הרגיש ביותר: כל עריכת
    תיאור שמזיזה את הכלי האמצעי הייתה מפילה את ה-CI בלי שאיש למד משהו.
    שומר שצועק על רעש מאומן להתעלם ממנו.

    **ואותה רשימת כלים בדיוק כמו התקרה עצמה** — ``_tool_manager.list_tools()``
    ולא ``mcp.list_tools()``, מהנימוק שכתוב ב-
    ``test_no_tool_description_exceeds_the_truncation_budget``. הכלי שבגללו
    התקרה קיימת נעדר מהתצוגה המסוננת.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    stated = _CEILING_RATIONALE_RE.search(source)
    assert stated, "ההנמקה מעל התקרה שינתה צורה — הטסט הזה איבד את מה שהוא משווה"

    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    lengths = {tool.name: len(tool.description or "")
               for tool in mcp._tool_manager.list_tools()}
    longest = max(lengths, key=lambda name: (lengths[name], name))

    assert _int(stated["tools"]) == len(lengths), (
        f"ההנמקה אומרת {stated['tools']} כלים, ובפועל יש {len(lengths)}")
    assert stated["name"] == longest, (
        f"ההנמקה אומרת שהארוך ביותר הוא {stated['name']}, ובפועל {longest}")
    assert _int(stated["chars"]) == lengths[longest], (
        f"ההנמקה אומרת {stated['chars']} תווים, ובפועל {lengths[longest]}")
    assert lengths[longest] < _TOOL_DESCRIPTION_MAX_CHARS, (
        "הטיעון שההנמקה נושאת — שהתקרה גבוהה מהארוך ביותר — כבר אינו נכון")


async def test_get_file_description_points_at_the_query_parameter():
    """אותה שרשרת גילוי, על ``codekeeper_get_file``.

    ‏``query`` נוסף ב-#3385 עם תיאור בן 1,376 תווים שצורף לתיאור הכלי,
    והביא אותו מ-349 ל-1,726 — מעל התקרה, כלומר סופו נחתך אצל הלקוח.
    **וזה נתפס על ידי ``test_no_tool_description_exceeds_the_truncation_budget``
    יומיים אחרי שנכתב**, מה שהופך את התקרה ממופע בודד למחלקת בעיה: הפירוט
    עבר ל-``Field`` של ``query``, בדיוק כמו ב-``codekeeper_get_repo_file``.

    ‏``_RANGE_DOC`` **נשאר בתיאור הכלי ולא זז**, כי הוא משותף ל-
    ``codekeeper_get_repo_file`` ו-``docs/mcp-server.rst`` מחייב שהשניים
    יתארו את ``lines=`` באותן מילים בדיוק.

    שני הקצוות נאכפים כאן, כמו בכלי האח: שהכלי מפנה ל-``query``, ושהפרמטר
    נושא את הפירוט בפועל.
    """
    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    tool = mcp._tool_manager.get_tool("codekeeper_get_file")
    query_doc = tool.parameters["properties"]["query"]["description"]

    # קצה ראשון: הכלי מפנה **לפרמטר** ולא רק מזכיר את המילה.
    #
    # **``"query" in description`` לבדו אינו מספיק, וזה נמדד:** התיאור נושא
    # ממילא את הדוגמה ``query="..."``, ולכן מוטציה שמחקה את ההפניה עברה את
    # הבדיקה החלשה בשקט — כלומר טסט שאינו מסוגל ליפול על מה שהוא אמור
    # לשמור עליו. ההפניה לשם הפרמטר היא מה שאומר לסוכן איפה לחפש.
    assert "query parameter" in tool.description

    # קצה שני: הפירוט באמת שם.
    assert "query_and_lines" in query_doc
    assert "context_lines" in query_doc
    assert "max_results" in query_doc

    # ``_RANGE_DOC`` נשאר בתיאור הכלי — הסימטריה מול get_repo_file נשמרת.
    assert "lines=[start, end]" in tool.description
    assert "lines=[start, end]" in (
        mcp._tool_manager.get_tool("codekeeper_get_repo_file").description
    )


async def test_docs_get_section_description_points_at_the_section_parameter():
    """אותה שרשרת גילוי, על ``codekeeper_docs_get_section``.

    שני הדברים שמפתיעים קורא — שמזהה כמו ``K11`` נתפס, ושכותרת עם בקטיקים
    דורשת אותם בשאילתה — יושבים בתיאור הפרמטר ולא בתיאור הכלי, כי התקרה
    שלמעלה חלה על ``description`` בלבד. ולכן נאכפים **שני הקצוות**:
    שהכלי מפנה לפרמטר בשמו, ושהפרמטר באמת נושא את הפירוט.

    ‏``"section" in description`` לבדו אינו מספיק — התיאור נושא ממילא את
    המילה חמש פעמים, ולכן הבדיקה היא על ההפניה המפורשת.
    """
    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    tool = mcp._tool_manager.get_tool("codekeeper_docs_get_section")
    section_doc = tool.parameters["properties"]["section"]["description"]

    # קצה ראשון: הכלי מפנה **לפרמטר**, ונוקב בשתי ההפתעות בשמן.
    assert "`section` parameter" in tool.description
    assert "identifier" in tool.description and "backticks" in tool.description

    # קצה שני: הפירוט באמת שם — שני הכללים, והגבול שביניהם.
    assert "K1 " in section_doc and "K10-K15" in section_doc
    assert "ambiguous_section" in section_doc
    assert "``literal``" in section_doc
    assert "suggestions_truncated" in section_doc


def test_the_colour_param_doc_is_derived_from_the_palette():
    """מה שהסוכן קורא על הצבע נגזר מהפלטה, ולא מוקלד לצידה.

    הפלטה חיה ב-``sticky_notes_target.NOTE_COLORS``. טקסט שמונה את
    הצבעים ביד היה מתיישן בשקט בצבע הבא שיתווסף — הסוכן היה ממשיך לראות
    רשימה חלקית, בלי שגיאה ובלי שאף בדיקה תשים לב. זה בדיוק הכשל שכבר
    תועד בריפו על מפת תוויות שהוחזקה פעמיים.

    נופלת אם מישהו יחליף את הגזירה ברשימה מוקלדת, ברגע שהפלטה תשתנה.
    """
    from sticky_notes_target import NOTE_COLOR_ORDER

    from mcp_server.server import _build_note_color_doc

    doc = _build_note_color_doc()
    for color_id in NOTE_COLOR_ORDER:
        assert color_id in doc, color_id

    # ושני השדות שחוזרים מוסברים, אחרת סוכן שמקבל ``color_id`` ריק אינו
    # יודע שזו התשובה הנכונה ל"הצבע אינו בפלטה" ולא תקלה.
    assert "color_id" in doc
    # ושהדחייה מוצהרת — סוכן שאינו יודע שערך פסול נדחה יניח שהוא הוחל.
    assert "refused" in doc


def test_the_lean_field_list_in_the_descriptions_is_derived_from_the_backend():
    """מה שהסוכן קורא על השורה הרזה נגזר מ-``LEAN_NOTE_FIELDS``, ולא מוקלד לצידה.

    אותו נימוק בדיוק שמעל ``test_the_colour_param_doc_is_derived_from_the_palette``:
    הרשימה הייתה מוקלדת בשלושה נוסחים, ואחד מהם כבר אמר "colour, size" על
    שדות ששמם ``color`` ו-``content_bytes``. נופלת אם מישהו יחליף את הגזירה
    ברשימה מוקלדת, ברגע שהרשימה תשתנה.
    """
    from mcp_server.backend import LEAN_NOTE_FIELDS
    from mcp_server.server import _INCLUDE_CONTENT_PARAM_DOC

    joined = ", ".join(LEAN_NOTE_FIELDS)
    assert joined in _INCLUDE_CONTENT_PARAM_DOC

    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    board_desc = mcp._tool_manager.get_tool("codekeeper_list_board_notes").description
    assert joined in board_desc
    # ואין נוסח שני של הרשימה במילים אחרות.
    assert "colour, size" not in board_desc


async def test_the_path_param_doc_names_every_repo_and_suffix_the_policy_knows():
    """מה שהסוכן קורא על ``path`` נגזר מטבלת המדיניות, ולא מוקלד לצידה.

    אותו נימוק בדיוק שמעל ``test_the_colour_param_doc_is_derived_from_the_palette``:
    ריפו שיתווסף לטבלה בלי שהתיאור יעודכן היה הופך לפיצ'ר שאף לקוח קורא
    עליו, ולהפך — ריפו שיוסר היה משאיר הבטחה שקרית.

    **ההתאמה היא על הערך המלא ולא על תת-מחרוזת.** ``".md" in doc`` היה
    עובר גם על ``".mdx"``, ו-``"CodeBot" in doc`` עובר גם כשהתיאור מדבר
    על ריפו אחר שהשם שלו מכיל אותו.
    """
    from mcp_server import docs_handlers

    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    tool = mcp._tool_manager.get_tool("codekeeper_docs_get_section")
    doc = tool.parameters["properties"]["path"]["description"]

    for repo, policy in docs_handlers.DOCS_PATH_POLICY.items():
        assert re.search(rf"(?<![\w-]){re.escape(repo)}(?![\w-])", doc), repo
        assert re.search(rf"(?<!\w){re.escape(policy.suffix)}(?!\w)", doc), policy.suffix
        root = policy.root
        assert (f"{root}/" in doc) if root else ("repo root" in doc), repo

    # ושני קודי הסירוב שהפרמטר הזה מייצר מוצהרים, אחרת סוכן שמקבל אותם
    # אינו יודע אם הוא טעה בנתיב או שהפריסה אינה מכירה את הריפו.
    assert "suffix_not_allowed" in doc and "repo_not_configured" in doc


async def test_the_docs_tool_description_names_both_formats_and_points_at_path():
    """תיאור הכלי אומר שיש שני פורמטים, ומפנה לפרמטר שמסביר מי מהם היכן.

    ‏``"path" in description`` לבדו אינו מספיק — המילה מופיעה שם ממילא —
    ולכן הבדיקה היא על ההפניה המפורשת, בדיוק כמו בטסט המקביל על
    ``section``.
    """
    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeRepoBackend())
    description = mcp._tool_manager.get_tool("codekeeper_docs_get_section").description

    assert "Markdown" in description and "RST" in description
    assert "`path` parameter" in description
    # ומה שכבר לא נכון אסור שיחזור: הכלי אינו מוגבל ל-docs/*.rst.
    assert "docs/*.rst" not in description


async def test_the_section_param_doc_covers_markdown_inline_markup_too():
    """הכלל "הכותרת חוזרת כטקסט מקור" נאמר לשני הפורמטים ולא רק ל-RST.

    הניסוח הקודם דיבר על ``literal`` בלבד, שהוא סימון של RST. קורא של
    עמוד Markdown שכותרתו נכתבה ``**K11**`` היה מקבל אפס התאמות ומייחס
    את זה לבאג — וזו אותה מחלקת הפתעה בדיוק שבגללה סעיף הבקטיקים נכתב
    מלכתחילה.
    """
    from mcp_server.server import _SECTION_PARAM_DOC

    assert "Markdown" in _SECTION_PARAM_DOC
    assert "``literal``" in _SECTION_PARAM_DOC  # והכלל ל-RST לא נמחק בדרך


#: שלושת המשטחים שמתארים לקורא מתי ``suggestions`` מחזיר מזהים.
#:
#: **הם התפצלו כבר פעם אחת, וזה מה שהטסט שמתחתם קיים בשבילו.** הקוד עבר
#: לסדר "difflib קודם" בקומיט שלישי, ושלושת המשטחים המשיכו לתאר את הכלל
#: שהיה לפניו — כלומר סוכן שקרא את תיאור הכלי למד חוק שהקוד כבר אינו
#: מקיים. זו בדיוק המחלקה שהסתירה את הבאג ב-#3379: הצהרה שהייתה נכונה
#: ביום שנכתבה, ושקטה ביום שהתיישנה.
#:
#: לכל משטח **סמן נדרש** אחד לכל כלל שהוא חייב לשאת. הסמן אינו הניסוח
#: המלא אלא הפסוקית שנושאת את המשמעות — מי שינסח מחדש ויפיל אותה מפיל
#: את הטסט, ומי שרק ישפר סגנון סביבה אינו.
#:
#: **והסמן הוא הכלל ולא מונח שמופיע בהסבר שלו, וזה נמדד.** הגרסה הראשונה
#: חיפשה את המחרוזת ``K11.1``, ומוטציה שמחקה את **הכלל** מ-``whats-new``
#: שרדה אותה — כי המונח ממשיך להופיע במשפט שמסביר למה הנקודה מפרידה.
#: כלומר האסרשן לא היה מסוגל ליפול, וזה אותו כשל שהוא נועד לתפוס.
_SUGGESTION_RULE_SURFACES = (
    ("תיאור הפרמטר section", "ONLY when nothing is close", "K11 never returns K11.1"),
    ("docs/mcp-server.rst", "ורק כשאין אף כותרת קרובה",
     "נקודה שפותחת תת-מספור אינה גבול"),
    ("docs/whats-new.rst", "ורק כשאין אף כותרת קרובה",
     "אינו מחזיר את ``K11.1``"),
)


def _suggestion_rule_texts() -> dict[str, str]:
    """הטקסט של שלושת המשטחים, בשמות של :data:`_SUGGESTION_RULE_SURFACES`."""
    from pathlib import Path

    from mcp_server.server import _SECTION_PARAM_DOC

    docs = Path(__file__).resolve().parent.parent / "docs"
    texts = {
        "תיאור הפרמטר section": _SECTION_PARAM_DOC,
        "docs/mcp-server.rst": (docs / "mcp-server.rst").read_text(encoding="utf-8"),
        "docs/whats-new.rst": (docs / "whats-new.rst").read_text(encoding="utf-8"),
    }
    # משטח שנקרא ריק אינו "עובר" — הוא אומר שהטסט איבד את מה שהוא מודד.
    for name, text in texts.items():
        assert text.strip(), f"משטח ריק: {name}"
    return texts


def test_the_suggestion_rule_says_the_same_thing_in_the_code_and_in_all_three_surfaces():
    """הקוד ושלושת המשטחים שמתארים אותו אומרים אותו דבר — ולא יכולים להתפצל בשקט.

    **שני חצאים, ושניהם חייבים להסכים.** החצי הראשון מריץ את ההתנהגות
    עצמה: בעמוד שיש בו גם מזהה וגם כותרת קרובה, שאילתה בצורת מזהה חוזרת
    עם ה**כותרת**. מי שיהפוך את הסדר ב-:func:`services.doc_sections.suggest`
    מפיל אותו. החצי השני קורא את שלושת המשטחים ודורש שכל אחד נושא את
    שתי הפסוקיות — התנאי על ``difflib``, וכלל תת-המספור. מי שיערוך משטח
    אחד ויפיל ממנו פסוקית מפיל אותו.

    **ולמה שניהם ביחד ולא שני טסטים.** טסט התנהגות לבדו עובר גם כשהתיעוד
    משקר; טסט טקסט לבדו עובר גם כשהקוד השתנה תחתיו. מה שצריך להיאכף הוא
    ה**הסכמה** ביניהם, וזה אובייקט אחד.
    """
    from services import rst_parser

    # עמוד שיש בו מזהה, ולצידו כותרת שאינה מזהה אבל **קרובה** לשאילתה.
    # ``H2`` מול ``H2O`` הוא יחס דמיון 0.8, כלומר מעל ה-cutoff של 0.5 —
    # וזה המקרה היחיד שמבדיל בין שני הסדרים. נמדד, לא שוער.
    doc = rst_parser.parse_document(
        "Doc\n===\n\n"
        "K11. כשל שמדווח בערך החזרה נבלע ואינו נבדק\n"
        "-------------------------------------------\n\nגוף\n\n"
        "H2O\n---\n\nגוף\n"
    )
    assert rst_parser.find_sections(doc, "H2") == [], "ההנחה של הטסט נשברה"
    assert rst_parser.suggest(doc, "H2").titles == ["H2O"], (
        "difflib אינו קודם לרשימת המזהים — הקוד חזר לסדר שהמשטחים כבר אינם מתארים"
    )

    texts = _suggestion_rule_texts()

    # **והמספר נקשר יחד איתם, כי הוא התפצל בדיוק כאן.** הכמות שסוכן מקבל
    # נגזרת ב-``server.py`` מ-``DEFAULT_SUGGESTIONS``, אבל שני קובצי ה-RST
    # אינם יכולים לגזור דבר — הם מחרוזות. נמדד: ברגע שהתקרה בפועל ירדה
    # מ-50 ל-5, שניהם המשיכו לומר 50 בלי ששום בדיקה תשים לב. לכן המחרוזת
    # המצופה **מחושבת כאן מהקבוע**, ולא מוקלדת לצד שלושת המשטחים.
    from services import doc_sections

    count = doc_sections.MAX_IDENTIFIER_SUGGESTIONS
    numbers = {
        "תיאור הפרמטר section": f"at most {count};",
        "docs/mcp-server.rst": f"**והכמות: עד {count} הצעות.**",
        "docs/whats-new.rst": f"המזהים שכן קיימים — עד {count},",
    }
    stale = [f"{name}: חסר {marker!r}" for name, marker in numbers.items()
             if marker not in texts[name]]
    assert not stale, (
        f"משטח שמצהיר על כמות ההצעות אינו אומר {count} — המספר בקוד זז "
        f"והתיעוד נשאר:\n  " + "\n  ".join(stale)
    )

    missing = [
        f"{name}: חסר {marker!r}"
        for name, *markers in _SUGGESTION_RULE_SURFACES
        for marker in markers
        if marker not in texts[name]
    ]
    assert not missing, (
        "משטח שמתאר את ``suggestions`` איבד פסוקית שהקוד כן מקיים:\n  "
        + "\n  ".join(missing)
        + "\nשלושתם מתארים את אותו כלל, ולכן עריכה של אחד היא עריכה של שלושה."
    )


def test_the_section_param_doc_derives_the_count_from_the_constant():
    """מה שסוכן קורא על כמות ההצעות נגזר מהקוד, ולא מוקלד לצידו.

    אותה צורה בדיוק כמו :func:`test_the_colour_param_doc_is_derived_from_the_palette`,
    ומאותה סיבה: מספר שמוקלד ביד ליד הקבוע שאוכף אותו מתיישן בשקט ברגע
    שמישהו משנה את הקבוע. הסוכן ימשיך לקרוא את הישן, בלי שגיאה ובלי
    שאף בדיקה תשים לב.

    **והמספר שנגזר הוא ``MAX_IDENTIFIER_SUGGESTIONS`` ולא
    ``DEFAULT_SUGGESTIONS``, וזו הכרעה שהתהפכה פעם אחת.** גרסה קודמת גזרה
    את ברירת המחדל, בנימוק ש"זה מה שהסוכן מקבל בפועל" — נכון כל עוד
    ה-handler לא ביקש כמות. מאז הוא מבקש את התקרה במפורש, כי רשימת מזהים
    היא מלאי ולא דירוג, ולכן **התקרה היא המספר שהסוכן חווה**.

    נופלת ברגע שמישהו יחליף את הגזירה במספר מוקלד, כשהקבוע ישתנה.
    """
    from mcp_server.server import _SECTION_PARAM_DOC
    from services import doc_sections

    assert f"at most {doc_sections.MAX_IDENTIFIER_SUGGESTIONS};" in _SECTION_PARAM_DOC
