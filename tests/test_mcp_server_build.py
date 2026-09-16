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

    # חיפוש ← קריאת טווח.
    assert "Every result carries a `line`" in search
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
#: הבחירה ב-1,400: אחרי הפיצול הכלי הארוך ביותר הוא 1,125, השני אחריו
#: ``codekeeper_docs_get_section`` ב-652, והחציון של 29 הכלים הוא 303.
#: כלומר המספר נותן מרווח למשפט-שניים של גדילה טבעית, ונשאר הרבה מתחת
#: לאזור שבו החיתוך נצפה בפועל.
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


def test_the_colour_param_doc_is_derived_from_the_palette():
    """מה שהסוכן קורא על הצבע נגזר מהפלטה, ולא מוקלד לצידה.

    הפלטה חיה ב-``sticky_notes_target.NOTE_COLORS``. טקסט שמונה את
    הצבעים ביד היה מתיישן בשקט בצבע הבא שיתווסף — הסוכן היה ממשיך לראות
    רשימה חלקית, בלי שגיאה ובלי שאף בדיקה תשים לב. זה בדיוק הכשל שכבר
    תועד בריפו על מפת תוויות שהוחזקה פעמיים.

    נופלת אם מישהו יחליף את הגזירה ברשימה מוקלדת, ברגע שהפלטה תשתנה.
    """
    from sticky_notes_target import NOTE_COLORS, NOTE_COLOR_ORDER

    from mcp_server.server import _build_note_color_doc

    doc = _build_note_color_doc()
    for color_id in NOTE_COLOR_ORDER:
        assert color_id in doc, color_id
        assert NOTE_COLORS[color_id]["hex"] in doc, color_id

    # ושני השדות שחוזרים מוסברים, אחרת סוכן שמקבל ``color_id`` ריק אינו
    # יודע שזו התשובה הנכונה ל"הצבע אינו בפלטה" ולא תקלה.
    assert "color_id" in doc
