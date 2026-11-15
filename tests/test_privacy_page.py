"""עמוד מדיניות הפרטיות (``/privacy``) — ציבורי, מקושר מעמוד הבית ומעמוד ההתחברות, ונכון לגבי הקוד.

הכתובת רשומה כקישור למדיניות הפרטיות בפרויקט ה-Google Cloud של חיבור ה-Drive. גוגל ניגש אליה בלי סשן, ולכן העמוד חייב לענות 200 בלי התחברות, ועמוד הבית חייב לקשר אליו.

רוב הטסטים כאן מצמידים **עובדות על הקוד** שהעמוד מצהיר עליהן בפרוזה (``bugbot-rules/prose-restates-code-fact.md``): מי שמשנה את ה-scope, מוסיף הורדה מ-Drive, או מוסיף לעמוד טענה על הצפנה בזמן שהקוד עדיין שומר טוקנים בלי הצפנה — מפיל טסט כאן, ומגיע לעמוד. הרקע: הסעיף ``drive-privacy-page`` ב-``docs/services/google_drive_service.rst``.

מה **לא** כאן: שהניתוק מוחק את הטוקנים — זה כבר נבדק ב-``tests/test_drive_connection_separation.py`` (``delete_drive_tokens``) וב-``tests/test_webapp_drive_auth_required.py`` (הניתוק של הוובאפ דרך Flask).
"""

from __future__ import annotations

import ast
import os
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

pytest.importorskip("flask")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCOPE_URL_RE = re.compile(r"https://www\.googleapis\.com/auth/[A-Za-z0-9._-]+")


class _Anchors(HTMLParser):
    """אוסף ``(href, טקסט)`` לכל ``<a>`` בעמוד — הקישור נגזר מה-HTML שנוצר, כמו שדפדפן או הסורק של גוגל רואים אותו."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def _anonymous_client():
    from webapp import app as webapp_app

    # client חדש, בלי session_transaction — כמו מבקר שלא התחבר
    return webapp_app.app.test_client()


def _privacy_text() -> str:
    """גוף המדיניות בלבד (ה-``article``), בלי ``base.html`` שסביבו — כדי שטענה על העמוד תיבדק על מה שכתוב בו, ולא על סקריפט או קישור של התבנית הכללית."""
    resp = _anonymous_client().get("/privacy")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    match = re.search(r"<article\b[^>]*\bprivacy-policy\b[^>]*>(.*?)</article>", html, re.S)
    assert match, "the privacy article is missing"
    return match.group(1)


def test_privacy_page_answers_without_login():
    resp = _anonymous_client().get("/privacy")

    assert resp.status_code == 200, resp.status_code
    assert "Location" not in resp.headers
    assert resp.mimetype == "text/html"
    article = _privacy_text()
    assert "Privacy Policy" in article
    assert "Limited Use requirements" in article


@pytest.mark.parametrize("page", ["/", "/login"])
def test_home_and_login_link_to_the_privacy_page(page):
    client = _anonymous_client()
    resp = client.get(page)
    assert resp.status_code == 200, (page, resp.status_code)

    parser = _Anchors()
    parser.feed(resp.get_data(as_text=True))
    hrefs = [href for href, text in parser.links if text == "Privacy Policy"]
    assert hrefs, f"no 'Privacy Policy' link on {page}"

    # הקישור שבעמוד, ולא נתיב שהטסט מכיר מראש — כך נבדק מה שהמבקר באמת לוחץ עליו
    target = client.get(hrefs[0])
    assert target.status_code == 200, (hrefs[0], target.status_code)
    assert "Limited Use requirements" in target.get_data(as_text=True)


def _module_ast(relative: str) -> ast.Module:
    return ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))


def _bot_config_scope_default() -> str:
    """``default=`` של ``Field`` בשדה ``GOOGLE_OAUTH_SCOPES`` במחלקה ``BotConfig`` ב-``config.py``."""
    for node in ast.walk(_module_ast("config.py")):
        if isinstance(node, ast.ClassDef) and node.name == "BotConfig":
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == "GOOGLE_OAUTH_SCOPES":
                    assert isinstance(stmt.value, ast.Call)
                    defaults = [kw.value for kw in stmt.value.keywords if kw.arg == "default"]
                    assert len(defaults) == 1
                    return ast.literal_eval(defaults[0])
    raise AssertionError("BotConfig.GOOGLE_OAUTH_SCOPES not found in config.py")


def _webapp_scope_default() -> str:
    """הארגומנט השני של ``os.getenv("GOOGLE_OAUTH_SCOPES", ...)`` ב-``webapp/drive_auth.py``."""
    for node in _module_ast("webapp/drive_auth.py").body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "GOOGLE_OAUTH_SCOPES" for t in node.targets):
            call = node.value
            assert isinstance(call, ast.Call) and len(call.args) == 2, ast.dump(call)
            assert ast.literal_eval(call.args[0]) == "GOOGLE_OAUTH_SCOPES"
            return ast.literal_eval(call.args[1])
    raise AssertionError("GOOGLE_OAUTH_SCOPES not found in webapp/drive_auth.py")


def test_the_scope_the_page_names_is_the_one_both_connections_request():
    """העמוד אומר שהבוט והוובאפ מבקשים רק ``drive.file``, ומסביר מה זה מתיר. כאן הוא מושווה לכל מקום בקוד שקובע את ה-scope.

    המקומות שקובעים אותו היום, כולם ב-``requested``: ``BotConfig.GOOGLE_OAUTH_SCOPES`` (``config.py``), ש-``start_device_authorization`` של הבוט קורא; ‏``DEFAULT_GOOGLE_OAUTH_SCOPES`` (``services/google_drive_service.py``), ה-fallback שלו; ו-``GOOGLE_OAUTH_SCOPES`` ב-``webapp/drive_auth.py``, שהוובאפ שולח בהפניה לגוגל.

    הקונפיג והוובאפ נקראים מ-ENV, ולכן ברירת המחדל שלהם נקראת מקוד המקור (``ast``) ולא מהערך שנטען — אחרת הטסט היה משווה לסביבה ולא לקוד. וגם כי תחת pytest ``import config`` מגיע ל-``tests/config.py``, שאין בו את השדה.
    """
    from services.google_drive_service import DEFAULT_GOOGLE_OAUTH_SCOPES

    requested = {
        "config.BotConfig.GOOGLE_OAUTH_SCOPES": set(_bot_config_scope_default().split()),
        "services.google_drive_service.DEFAULT_GOOGLE_OAUTH_SCOPES": set(DEFAULT_GOOGLE_OAUTH_SCOPES.split()),
        "webapp.drive_auth.GOOGLE_OAUTH_SCOPES": set(_webapp_scope_default().split()),
    }
    named_on_page = set(SCOPE_URL_RE.findall(_privacy_text()))

    assert named_on_page == {"https://www.googleapis.com/auth/drive.file"}, named_on_page
    for owner, scopes in requested.items():
        assert scopes == named_on_page, f"{owner} requests {scopes}; update webapp/templates/privacy.html"


# קריאות שמורידות תוכן של קובץ מ-Drive ב-google-api-python-client: ``files().get_media`` ו-``files().export_media`` (או ``alt=media`` ידני), ו-``MediaIoBaseDownload`` שמזרים אותן לקובץ.
_DRIVE_DOWNLOAD_RE = re.compile(r"\.get_media\(|\.export_media\(|MediaIoBaseDownload|\.export\(\s*fileId|alt\s*=\s*['\"]media['\"]")
_NOT_PRODUCT_CODE = {"tests", "docs", "node_modules", "__pycache__"}


def _drive_download_calls(root: Path) -> list[str]:
    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _NOT_PRODUCT_CODE]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if _DRIVE_DOWNLOAD_RE.search(line):
                    hits.append(f"{path.relative_to(root)}:{lineno}: {line.strip()}")
    return hits


def test_no_code_downloads_file_content_from_drive():
    """העמוד אומר ש-CodeKeeper אף פעם לא מוריד או קורא תוכן של קובץ ב-Drive. היום הקוד רק יוצר תיקיות ומעלה קבצים (``files().create``), וקורא מטא-דאטה של מה שהוא יצר (``files().list`` / ``files().get``).

    קוד שמוסיף הורדה — למשל שחזור מגיבוי שב-Drive — מפיל את הטסט הזה, ואז צריך לעדכן את העמוד ("How we use it") לפני שמשנים את הטסט.
    """
    assert "files().create" in (REPO_ROOT / "services" / "google_drive_service.py").read_text(encoding="utf-8")
    assert _drive_download_calls(REPO_ROOT) == []
    assert "never downloads or reads the content" in _privacy_text()


def test_the_page_does_not_claim_encryption_while_tokens_can_be_saved_unencrypted(monkeypatch):
    """בלי ``TOKEN_ENC_KEY`` (או עם מפתח פסול) ``encrypt_secret`` מחזיר ``None``, ו-``Repository.save_drive_tokens`` שומר אז את הטוקנים כמו שהם. המפתח אינו חובה בהגדרות, ולכן העמוד לא אומר שהטוקנים מוצפנים.

    אם שמירה בלי מפתח תיחסם (encrypt_secret יזרוק, או השמירה תסרב), הבדיקה הראשונה כאן תיפול — ואז אפשר להוסיף לעמוד את ההצהרה ולעדכן את הטסט.
    """
    import secret_manager

    monkeypatch.delenv("TOKEN_ENC_KEY", raising=False)
    assert secret_manager.encrypt_secret("token") is None

    assert "encrypt" not in _privacy_text().lower()


# ---------------------------------------------------------------------------
# הסעיף של המחבר (``<section id="mcp">``) — אותה שיטה: כל עובדה שהעמוד נוקב בה מוצמדת לקוד שקובע אותה.
#
# הכתובת של העמוד נמסרת גם בהגשה לספריית המחברים של Anthropic, ומדיניות הספרייה דורשת מדיניות פרטיות שמתארת "accurately" מה נאסף ואיך משתמשים בזה. מי שמשנה את אורך החיים של טוקן, את אופן השמירה שלו, את מה ש-PostHog מקבל, או מוסיף כלי מחיקה — מפיל טסט כאן ומגיע לעמוד. הרקע: הסעיף ``mcp-privacy-page`` ב-``docs/mcp-server.rst``.
#
# מה **לא** כאן, כי כבר מוצמד במקום אחר: שהארגומנטים והתוצאות של הכלים לא יוצאים ל-PostHog, ושקריאת כלי לא נושאת משפט כוונה (``tests/test_mcp_analytics_privacy.py``, ובפרט ``test_a_real_instrumented_tool_call_reaches_posthog_with_no_content``).
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"\b(\d+) (minute|hour|day)s?\b")
_UNIT_SECONDS = {"day": 86400, "hour": 3600, "minute": 60}


def _mcp_section() -> str:
    """הטקסט של הסעיף ``mcp`` — בלי תגיות ועם רווחים מכווצים, כמו שקורא רואה אותו."""
    import html

    match = re.search(r'<section id="mcp">(.*?)</section>', _privacy_text(), re.S)
    assert match, "the mcp section is missing from the privacy page"
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))).split())


def _as_words(seconds: int) -> str:
    """משך בשניות כפי שהעמוד כותב אותו — ביחידה הגדולה ביותר שמחלקת אותו בלי שארית."""
    for unit, size in _UNIT_SECONDS.items():
        if seconds % size == 0:
            count = seconds // size
            return f"{count} {unit}{'' if count == 1 else 's'}"
    raise AssertionError(f"{seconds} seconds is not a whole number of minutes")


def test_the_lifetimes_the_mcp_section_states_are_the_ones_in_the_code():
    """הטוקנים, וההעלאה שממתינה לשמירה: כל משך שהסעיף נוקב בו נגזר כאן מהקבוע שאוכף אותו.

    הבדיקה השנייה תופסת גם משך שלישי שמישהו יוסיף לסעיף בלי קבוע מאחוריו, או מספר ישן שנשאר במשפט אחר.
    """
    from mcp_server.oauth_store import ACCESS_TTL_SECONDS, REFRESH_TTL_SECONDS
    from mcp_uploads import UPLOAD_TTL_SECONDS

    access, refresh, upload = (_as_words(s) for s in (ACCESS_TTL_SECONDS, REFRESH_TTL_SECONDS, UPLOAD_TTL_SECONDS))
    section = _mcp_section()

    assert f"An access token expires after {access} and a refresh token after {refresh}" in section
    assert f"({access} for an access token, {refresh} for a refresh token)" in section
    assert f"It can be used for up to {upload}" in section

    stated = {count * _UNIT_SECONDS[unit] for count, unit in ((int(c), u) for c, u in _DURATION_RE.findall(section))}
    assert stated == {ACCESS_TTL_SECONDS, REFRESH_TTL_SECONDS, UPLOAD_TTL_SECONDS}, stated


class _FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []
        self.indexes: list[tuple] = []

    def create_index(self, keys, **kwargs):
        self.indexes.append((keys, kwargs))

    def insert_one(self, doc):
        self.docs.append(dict(doc))


class _FakeDb(dict):
    def __missing__(self, name):
        coll = self[name] = _FakeCollection()
        return coll


def test_connector_tokens_are_stored_only_as_a_hash_and_expire_out_of_the_database():
    """העמוד אומר שנשמר רק SHA-256 של כל טוקן, ושרשומות שפג תוקפן נמחקות לבד.

    שלושת הסודות של OAuth (קוד, טוקן גישה, טוקן רענון) והטוקן האישי של הבוט נכתבים כאן דרך הקוד האמיתי, והטוקן הגולמי לא אמור להופיע בשום מקום במסמך שנכתב. ה"נמחקות לבד" הוא אינדקס TTL על ``expires_at`` באוסף הטוקנים, ש-``OAuthStore`` מצהיר עליו בבנאי — אותו אובייקט ש-``save_token`` שלו כותב, כך שאין כותב שעוקף את ההצהרה.
    """
    import hashlib

    from mcp_server.oauth_store import TOKENS_COLLECTION, OAuthStore
    from mcp_server.token_store import COLLECTION_NAME, MCPTokenStore

    db = _FakeDb()
    store = OAuthStore(db)
    raw = {"access": "ckoat_raw-access-value", "refresh": "ckort_raw-refresh-value"}
    for kind, value in raw.items():
        store.save_token(value, kind=kind, data={"subject": "7", "client_id": "c", "scopes": ["read"]})
    store.save_code("ckoc_raw-code-value", {"subject": "7", "client_id": "c"})

    written = db[TOKENS_COLLECTION].docs + db["mcp_oauth_codes"].docs
    for value in [*raw.values(), "ckoc_raw-code-value"]:
        assert all(value not in repr(doc) for doc in written), value
    assert {doc["token_hash"] for doc in db[TOKENS_COLLECTION].docs} == {
        hashlib.sha256(value.encode("utf-8")).hexdigest() for value in raw.values()
    }
    assert ("expires_at", {"expireAfterSeconds": 0}) in db[TOKENS_COLLECTION].indexes

    pat = MCPTokenStore(db).issue(7, label="Claude")
    (pat_doc,) = db[COLLECTION_NAME].docs
    assert pat not in repr(pat_doc)
    assert pat_doc["token_hash"] == hashlib.sha256(pat.encode("utf-8")).hexdigest()
    # "its first few characters so that tokens can be told apart"
    assert pat.startswith(pat_doc["token_prefix"]) and len(pat_doc["token_prefix"]) < len(pat) // 2

    section = _mcp_section()
    assert "We store only a SHA-256 hash of each token, never the token itself." in section
    assert "Expired token records are deleted automatically." in section


def test_posthog_gets_no_user_identity_and_no_intent_option(monkeypatch):
    """העמוד אומר שהאירועים לא נושאים את מזהה המשתמש, ושהמחבר לא מוסיף לכלים פרמטר שמבקש מהסוכן לתאר את הקריאה.

    שניהם הם אופציות של ``posthog.mcp`` ש-``instrument_mcp_server`` מעביר: בלי ``identify`` ה-``distinct_id`` הוא מזהה הסשן ואין פרופיל (``_posthog_events.py``, posthog 7.45.3); ו-``context=False`` — ברירת המחדל של ה-SDK היא ``True``, ולכן הבדיקה היא על ``is False`` ולא על "לא הועבר". כאן נלכדות האופציות שהשרת באמת מעביר. הפרמטר היחיד שכן מבקש תיאור משימה הוא ``working_on`` של תגובה על פתק — :func:`test_the_only_task_description_the_connector_asks_for_is_working_on_on_a_comment`.
    """
    pytest.importorskip("mcp")
    posthog_mcp = pytest.importorskip("posthog.mcp")
    from mcp.server.fastmcp import FastMCP

    from mcp_server import analytics

    captured = {}

    def fake_instrument(server, client, options):
        captured["options"] = options

    monkeypatch.setattr(posthog_mcp, "instrument", fake_instrument)
    monkeypatch.setattr(analytics, "_CLIENT", object())
    monkeypatch.setattr(analytics, "_ANALYTICS", None)

    analytics.instrument_mcp_server(FastMCP("privacy-page-test"))

    options = captured["options"]
    assert options.identify is None
    assert options.context is False
    assert options.intent_fallback is None

    assert "It does not include your CodeKeeper user ID" in _mcp_section()


class _NoBody:
    """backend שאף גוף כלי לא מגיע אליו — כאן רק נבנית רשימת הכלים."""

    def __getattr__(self, _name):
        raise AssertionError("a tool body ran while only the tool list was needed")


def _registered_tools(monkeypatch) -> list:
    """הכלים שהשרת האמיתי רושם (``build_mcp``), כולל כלי האדמין.

    ``ENVIRONMENT=production``: בלי קונפיגורציית PostHog, ``instrument_mcp_server`` זורק מחוץ לפרודקשן — כמו ב-``tests/test_mcp_pre_parse_json.py``.
    """
    pytest.importorskip("mcp")
    monkeypatch.setenv("ENVIRONMENT", "production")
    import mcp_server.server as srv

    return srv.build_mcp(_NoBody(), repo_backend=_NoBody())._tool_manager.list_tools()


def test_the_only_task_description_the_connector_asks_for_is_working_on_on_a_comment(monkeypatch):
    """העמוד אומר שהמחבר מבקש מהסוכן לתאר את המשימה במקום אחד בלבד: ``working_on`` בתגובה על פתק, עד ``MAX_WORKING_ON_CHARS`` תווים, והמשפט נשמר עם התגובה.

    כאן נבדקות הסכימות של כל הכלים הרשומים: ``working_on`` רק ב-``codekeeper_comment_note``, ו-``context`` (מה ש-``posthog.mcp`` מזריק כשהאופציה דלוקה) באף כלי. הבדיקה היא לפי שם הפרמטר: פרמטר חדש בשם אחר שמבקש תיאור משימה לא ייתפס כאן, ומי שמוסיף כזה צריך לעדכן את העמוד ואת הטסט.
    """
    from note_threads import MAX_WORKING_ON_CHARS

    tools = _registered_tools(monkeypatch)
    asking = {tool.name for tool in tools if "working_on" in (tool.parameters.get("properties") or {})}
    injected = {tool.name for tool in tools if "context" in (tool.parameters.get("properties") or {})}

    assert asking == {"codekeeper_comment_note"}, asking
    assert injected == set(), injected

    section = _mcp_section()
    assert "The connector asks the assistant to describe its task in one place only: when the assistant comments on a sticky note" in section
    assert f"up to {MAX_WORKING_ON_CHARS} characters, what it is working on" in section
    assert "and with the sentence the assistant wrote about what it is working on" in section


def test_the_connector_has_no_tool_that_deletes(monkeypatch):
    """העמוד אומר שלמחבר אין דרך למחוק קבצים, פתקים או אוספים. כאן נבנה השרת האמיתי, עם כלי האדמין, ושמות כל הכלים הרשומים נבדקים."""
    names = {tool.name for tool in _registered_tools(monkeypatch)}

    # הרשימה האמיתית, ולא רשימה ריקה שעוברת כל בדיקה
    assert {"codekeeper_save_file", "codekeeper_update_note", "codekeeper_list_repos"} <= names
    deleting = {name for name in names if re.search(r"delete|remove|purge|trash|destroy|erase|drop", name)}
    assert deleting == set(), deleting
    assert "The connector has no way to delete your files, notes or collections." in _mcp_section()
