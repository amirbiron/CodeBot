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
