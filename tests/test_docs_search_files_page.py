"""החיפוש בתיעוד בעמוד הקבצים: מי רואה אותו, לאן הוא שולח, וכמה זמן הדפדפן מחכה לו.

**מה כאן ומה בדפדפן.** כאן נבדק מה שהשרת מגיש: האפשרות "תיעוד" ב-``#searchType`` והנכסים של
הרינדור מוגשים רק לאדמין אפקטיבי, והכתובות שהדפדפן ישלח אליהן מגיעות מ-``url_for`` של הראוטים
הרשומים (``TESTING-PATTERNS.md`` T1: הכתובת נגזרת מה-HTML שנוצר ומושווית לנתיב הרשום). מה
שהדפדפן עושה עם התשובה — הכרטיס, הרינדור, ההעתקה, שומר הרצף — נבדק ב-
``tests/test_docs_search_card_browser.py``.

**למה מונגו אמיתי.** ``/files`` מריץ צינורות ``aggregate``, והדמה של המסד אינה מכירה אותם. בלי
מונגו בדיקות הרינדור מדולגות (``wired_mongo``), ובדיקת הדדליין רצה תמיד.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from services import docs_search_service as docs_search

ROOT = Path(__file__).resolve().parent.parent
GLOBAL_SEARCH_JS = ROOT / "webapp" / "static" / "js" / "global_search.js"

#: הנכסים שמרנדרים את כרטיסי התיעוד, ושרק אדמין צריך.
DOCS_ASSETS = (
    "js/admonition-icons.js",
    "js/utils/rtl-code.js",
    "js/utils/safe-highlight.js",
    "js/md-anchors.js",
    "js/md-mark-plugin.js",
    "js/live-preview.js",
    "js/markdown-deps.js",
    "css/markdown-preview.css",
)


def test_the_client_deadline_outlasts_the_server_waits():
    """הדפדפן מחכה יותר מסכום ההמתנות שהשרת מגביל לעצמו.

    שני החלקים מול המסד והטמעת השאלה רצים בזה אחר זה. דדליין קצר מסכומם היה מבטל בדפדפן
    חיפוש שהשרת עוד עונה עליו, ומציג "לא הסתיים בזמן" על בקשה תקינה.
    """
    match = re.search(r"const DOCS_SEARCH_DEADLINE_MS = (\d+);", GLOBAL_SEARCH_JS.read_text(encoding="utf-8"))
    assert match, "לא נמצא DOCS_SEARCH_DEADLINE_MS ב-global_search.js"
    server_worst_case_ms = 1000 * (
        2 * docs_search.SEARCH_DB_TIMEOUT_SECONDS + docs_search.QUERY_EMBED_DEADLINE_SECONDS
    )
    assert int(match.group(1)) > server_worst_case_ms


class _Page(HTMLParser):
    """האפשרויות של ``#searchType`` עם המאפיינים שלהן, והכתובות של התגיות שטוענות נכסים."""

    def __init__(self) -> None:
        super().__init__()
        self.options: dict[str, dict] = {}
        self.assets: list[str] = []
        self._in_select = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select" and attrs.get("id") == "searchType":
            self._in_select = True
        elif tag == "option" and self._in_select:
            self.options[attrs.get("value")] = attrs
        elif tag == "script" and attrs.get("src"):
            self.assets.append(attrs["src"])
        elif tag == "link" and attrs.get("rel") == "stylesheet" and attrs.get("href"):
            self.assets.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "select":
            self._in_select = False


@pytest.fixture
def files_page(wired_mongo, monkeypatch):
    """``/files`` כפי שהשרת מגיש אותו, למשתמש שנבחר. 1 הוא האדמין."""
    wa = wired_mongo
    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    monkeypatch.setitem(wa.app.config, "SECRET_KEY", "docs-search-files-page")
    client = wa.app.test_client()

    def render(user_id: int, *, impersonating: bool = False) -> _Page:
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_data"] = {"id": user_id, "is_admin": user_id == 1, "is_premium": False}
        if impersonating:
            assert client.post("/admin/impersonate/start").status_code == 200
        response = client.get("/files")
        assert response.status_code == 200, response.status_code
        page = _Page()
        page.feed(response.get_data(as_text=True))
        assert page.options, "לא נמצאו אפשרויות ב-#searchType — הפרסור איבד את הרשימה"
        return page

    return wa, render


def _served(assets: list[str], name: str) -> list[str]:
    return [src for src in assets if src.split("?", 1)[0] == f"/static/{name}"]


def test_an_admin_gets_the_docs_option_with_the_registered_urls(files_page):
    wa, render = files_page
    page = render(1)

    option = page.options.get("docs")
    assert option is not None, sorted(page.options)
    rules = {rule.endpoint: rule for rule in wa.app.url_map.iter_rules()}
    assert option["data-search-url"] == rules["api_search_docs"].rule
    assert "POST" in rules["api_search_docs"].methods
    assert option["data-admin-url"] == rules["admin_docs_index_page"].rule


def test_an_admin_gets_the_rendering_assets_with_a_version_id(files_page):
    wa, render = files_page
    page = render(1)

    for name in DOCS_ASSETS:
        served = _served(page.assets, name)
        assert served, f"{name} אינו נטען בעמוד הקבצים של אדמין"
        assert all(src.endswith(f"?v={wa._STATIC_VERSION}") for src in served), served


@pytest.mark.parametrize("who", ["a user", "an admin viewing as a user"])
def test_without_an_effective_admin_there_is_no_docs_search(files_page, who):
    """בלי האפשרות ובלי הנכסים: משתמש רגיל לא מוריד את מה שרק אדמין צריך."""
    _wa, render = files_page
    page = render(2) if who == "a user" else render(1, impersonating=True)

    assert "docs" not in page.options, sorted(page.options)
    for name in DOCS_ASSETS:
        assert not _served(page.assets, name), f"{name} נטען בלי אדמין אפקטיבי"
