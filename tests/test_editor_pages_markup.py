"""שלושת עמודי העורך — העורך הציבורי, העריכה וההעלאה — בצד השרת: הכיתוב של הלשונית, והתווית של שדה הקוד.

- **"תצוגה חיה".** בטלפון יש מעל העורך לשוניות "עורך" / "תצוגה חיה". עד נובמבר 2026 השנייה נקראה "תצוגה", בשלוש
  התבניות.
- **"קוד".** בעמודי העריכה וההעלאה הייתה מעל העורך שורה שכתוב בה "קוד" — התווית של ה-textarea. היא נשארה, ומוסתרת
  מהעין (``sr-only``), כמו התווית "Markdown" בעורך הציבורי: קורא מסך עדיין מקריא את שם השדה, ו-
  ``addSwitcherButton`` ב-``editor-manager.js`` מציב את שורת הכפתורים מיד אחריה.

ההתנהגות בדפדפן — שהתווית באמת לא נראית, ושהלשוניות מוצגות רק עם התצוגה החיה — נבדקת ב-
``tests/test_edit_page_frame_browser.py`` וב-``tests/test_markdown_editor_browser.py``. כאן נבדק מה שהשרת מגיש,
גם בלי Chromium, ובכלל זה עמוד ההעלאה, שאין לו בדיקת דפדפן.
"""

from __future__ import annotations

from html.parser import HTMLParser

import pytest

pytest.importorskip("flask")

USER = {"id": 1, "first_name": "x", "username": "x"}

#: ערכה ציבורית מינימלית, כמו ב-``tests/test_markdown_editor_page.py``: ``colors`` לא ריק, כי ``base.html``
#: מחיל ערכה ציבורית רק כשיש לה צבעים.
FAKE_THEME = {
    "id": "everforest_dark",
    "name": "Everforest Dark",
    "description": "",
    "colors": {"--bg-primary": "#2d353b"},
    "syntax_css": "",
    "syntax_colors": {},
    "is_featured": False,
}


class _Markup(HTMLParser):
    """הלשוניות (``data-panel-target``) והתווית של ``#codeTextarea``: הטקסט וה-``class``."""

    def __init__(self) -> None:
        super().__init__()
        self.tabs: dict[str, str] = {}
        self.label: tuple[str, str] | None = None
        self._in: tuple[str, str] | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "button" and a.get("data-panel-target"):
            self._in, self._buf = ("tab", a["data-panel-target"]), []
        elif tag == "label" and a.get("for") == "codeTextarea":
            self._in, self._buf = ("label", a.get("class") or ""), []

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if not self._in:
            return
        kind, key = self._in
        text = "".join(self._buf).strip()
        if kind == "tab" and tag == "button":
            self.tabs[key] = text
            self._in = None
        elif kind == "label" and tag == "label":
            self.label = (text, key)
            self._in = None


def _parse(html: str) -> _Markup:
    m = _Markup()
    m.feed(html)
    return m


@pytest.fixture
def wa(monkeypatch):
    import webapp.app as webapp_app

    def _no_db(*args, **kwargs):
        raise RuntimeError("no database in this test")

    monkeypatch.setattr(webapp_app, "get_db", _no_db)
    return webapp_app


def _render(wa, template: str, path: str, **context) -> str:
    from flask import render_template, session

    with wa.app.test_request_context(path):
        session["user_id"] = USER["id"]
        session["user_data"] = USER
        return render_template(template, user=USER, error=None, success=None, **context)


def _edit_page(wa) -> str:
    file = {
        "id": "1",
        "file_name": "notes.md",
        "language": "markdown",
        "description": "",
        "tags": [],
        "is_large": False,
        "source_url": "",
    }
    return _render(
        wa,
        "edit_file.html",
        "/edit/1",
        file=file,
        code_value="# x",
        languages=["markdown"],
        existing_images=[],
    )


def _upload_page(wa) -> str:
    return _render(wa, "upload.html", "/upload", languages=["markdown"], bot_username="x")


def _public_page(wa, monkeypatch) -> str:
    monkeypatch.setattr(
        wa,
        "_get_shared_theme_cached",
        lambda theme_id: dict(FAKE_THEME) if theme_id == "everforest_dark" else None,
    )
    response = wa.app.test_client().get("/markdown-editor")
    assert response.status_code == 200
    return response.get_data(as_text=True)


@pytest.mark.parametrize("page", ["edit", "upload", "public"])
def test_the_preview_tab_is_called_live_preview(wa, monkeypatch, page):
    if page == "public":
        html = _public_page(wa, monkeypatch)
    else:
        html = {"edit": _edit_page, "upload": _upload_page}[page](wa)
    assert _parse(html).tabs == {"editor": "עורך", "preview": "תצוגה חיה"}


@pytest.mark.parametrize("page", ["edit", "upload"])
def test_the_code_label_is_for_screen_readers_only(wa, page):
    html = {"edit": _edit_page, "upload": _upload_page}[page](wa)
    assert _parse(html).label == ("קוד", "sr-only")
