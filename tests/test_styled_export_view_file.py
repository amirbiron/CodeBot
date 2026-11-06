"""הייצוא המעוצב מעמוד הקובץ, כשהמסמך מרונדר בדפדפן — מה שהשרת מגיש לו.

- **השלד** (``/export/styled/<file_id>/skeleton``): תחת אותן הרשאות של הייצוא שבשרת (התחברות, פרימיום או אדמין, קובץ
  Markdown של המשתמש), עם הערכה לפי הבקשה — preset, ערכת משתמש מהמסד, או ערכת VS Code ב-POST — ועם ה-CSS של KaTeX רק
  כש-``math=1``.
- **עמוד הקובץ**: חלון הייצוא נושא את המתג ואת טקסט ההערה, והמנוע יושב ב-``<template>``. המתג נכנס ל-ETag, אחרת עמוד
  שמור היה מקבל 304 ונשאר במסלול שכובה. בקובץ שגדול מכדי שהעמוד יציג אותו אין ``#rawCode``, והדפדפן מביא את הטקסט
  מ-``/download``.
- **ההכרעות המשותפות**: ערכת ה-Mermaid לפי הערכה, הכותרת ושם הקובץ.

הזרימה בדפדפן עצמו — ב-``tests/test_styled_export_browser.py``.
"""

from __future__ import annotations

import itertools
import json
import re
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

pytest.importorskip("flask")

from services.styled_export_service import (  # noqa: E402
    EDITOR_EXPORT_CONTENT_MARKER,
    EDITOR_EXPORT_CONTENT_MARKER_TEXT,
    EXPORT_PRESETS,
    export_mermaid_theme,
    styled_export_filename,
    styled_export_title,
)

FILE_ID = "b" * 24
# מזהה משתמש חדש לכל client: המגביל הגורף סופר לפי ``session['user_id']``, והאחסון שלו משותף לכל הטסטים בתהליך
# (TESTING-PATTERNS T3)
_USER_IDS = itertools.count(920_000)

MD_FILE = {
    "_id": FILE_ID,
    "file_name": "מדריך.md",
    "programming_language": "markdown",
    "code": "# כותרת\n\nטקסט עם $x^2$\n",
    "version": 1,
    "is_active": True,
}

# ערכת משתמש: ``--bg-primary`` בהיר (ולכן Mermaid בהיר), וכלל highlight.js תחת הקידומת של האתר — כמו ערכה מיובאת
USER_THEME = {
    "id": "my-light",
    "name": "שלי",
    "variables": {"--bg-primary": "#fbfaf5", "--text-primary": "#222222", "--primary": "#3366aa"},
    "syntax_css": ':root[data-theme-type="custom"] .hljs-keyword { color: #c0ffee; }',
}

VSCODE_THEME = {
    "name": "Tiny Light",
    "type": "light",
    "colors": {"editor.background": "#fdfdfd", "editor.foreground": "#101010", "editorLineNumber.foreground": "#999999"},
    "tokenColors": [{"scope": ["keyword"], "settings": {"foreground": "#ab0000"}}],
}


class _Cursor(list):
    def sort(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def skip(self, *a, **k):
        return self


class _Coll:
    """אוסף מתירני: עמוד הקובץ קורא מכמה אוספים (מועדפים, נפתחו לאחרונה, גרסאות), ואף אחד מהם אינו הנושא כאן."""

    def __init__(self, find_one_result=None):
        self.find_one_result = find_one_result

    def find_one(self, *a, **k):
        return self.find_one_result

    def find(self, *a, **k):
        return _Cursor()

    def aggregate(self, *a, **k):
        return _Cursor()

    def count_documents(self, *a, **k):
        return 0

    def distinct(self, *a, **k):
        return []

    def update_one(self, *a, **k):
        return SimpleNamespace(modified_count=0, matched_count=0, upserted_id=None)

    def insert_one(self, *a, **k):
        return SimpleNamespace(inserted_id="x")

    def create_index(self, *a, **k):
        return "x"

    def find_one_and_update(self, *a, **k):
        return None


class _Db:
    def __init__(self):
        self.users = _Coll({"custom_themes": [USER_THEME]})

    def __getattr__(self, name):
        return _Coll()

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.fixture
def wa(monkeypatch):
    import webapp.app as webapp_app

    monkeypatch.setattr(webapp_app, "get_db", lambda: _Db())
    monkeypatch.setattr(webapp_app, "is_admin", lambda uid: False)
    monkeypatch.setattr(webapp_app, "is_premium", lambda uid: True)
    return webapp_app


def _serve(wa, monkeypatch, doc):
    """הקובץ שהראוטים מוצאים לפי המזהה, דרך אותה פונקציה שהם קוראים לה."""
    monkeypatch.setattr(wa, "_get_user_any_file_by_id", lambda db, uid, fid: (dict(doc) if doc else None, "regular"))


def _client(wa):
    c = wa.app.test_client()
    uid = next(_USER_IDS)
    with c.session_transaction() as sess:
        sess["user_id"] = uid
        # ``view_file`` מרנדר את ``session['user_data']`` ישירות
        sess["user_data"] = {"id": uid, "first_name": "בדיקה", "is_admin": False, "is_premium": True}
    return c


SKELETON = f"/export/styled/{FILE_ID}/skeleton"


# ---------------------------------------------------------------------------
# השלד
# ---------------------------------------------------------------------------

def test_the_skeleton_requires_a_login(wa, monkeypatch):
    _serve(wa, monkeypatch, MD_FILE)
    resp = wa.app.test_client().get(SKELETON)
    assert resp.status_code in (301, 302, 401)
    assert EDITOR_EXPORT_CONTENT_MARKER not in resp.get_data(as_text=True)


def test_the_skeleton_requires_premium_or_admin(wa, monkeypatch):
    _serve(wa, monkeypatch, MD_FILE)
    monkeypatch.setattr(wa, "is_premium", lambda uid: False)
    assert _client(wa).get(SKELETON).status_code == 403


def test_the_skeleton_of_a_missing_file_is_404(wa, monkeypatch):
    _serve(wa, monkeypatch, None)
    assert _client(wa).get(SKELETON).status_code == 404


def test_the_skeleton_is_only_for_markdown(wa, monkeypatch):
    _serve(wa, monkeypatch, dict(MD_FILE, file_name="main.py", programming_language="python"))
    assert _client(wa).get(SKELETON).status_code == 400


@pytest.mark.parametrize("math", ["0", "true", ""])
def test_math_is_either_1_or_absent(wa, monkeypatch, math):
    _serve(wa, monkeypatch, MD_FILE)
    assert _client(wa).get(SKELETON, query_string={"math": math}).status_code == 404


def test_the_skeleton_carries_the_file_name_and_its_headers(wa, monkeypatch):
    _serve(wa, monkeypatch, MD_FILE)
    resp = _client(wa).get(SKELETON, query_string={"theme": "morass"})

    assert resp.status_code == 200, resp.get_data(as_text=True)[:500]
    html = resp.get_data(as_text=True)
    assert html.count(EDITOR_EXPORT_CONTENT_MARKER) == 1
    assert "<title>מדריך</title>" in html
    # שם הקובץ בכותרת HTTP — מקודד ב-URL, כי כותרת היא latin-1
    assert unquote(resp.headers["X-Export-Filename"]) == "מדריך.html"
    assert resp.headers["X-Export-Filename"].isascii()
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["Content-Security-Policy"] == wa._MARKDOWN_EDITOR_SKELETON_CSP
    # הערכה שנבחרה: הרקע של morass
    assert EXPORT_PRESETS["morass"]["variables"]["--bg-primary"] in html


def test_katex_css_only_with_math(wa, monkeypatch):
    _serve(wa, monkeypatch, MD_FILE)
    katex_css = wa.markdown_editor_katex_css()
    client = _client(wa)

    without = client.get(SKELETON).get_data(as_text=True)
    with_math = client.get(SKELETON, query_string={"math": "1"}).get_data(as_text=True)

    assert katex_css not in without
    assert katex_css in with_math


def test_a_user_theme_comes_from_the_database_with_its_hljs_rules(wa, monkeypatch):
    _serve(wa, monkeypatch, MD_FILE)
    html = _client(wa).get(SKELETON, query_string={"theme": USER_THEME["id"]}).get_data(as_text=True)

    assert USER_THEME["variables"]["--bg-primary"] in html
    assert "#c0ffee" in html
    # הכלל עבר לקידומת של הייצוא, ולא נשאר תחת הקידומת של האתר
    assert ':root[data-theme-type="custom"] .hljs-keyword' not in html
    # והפלטה שנגזרת מהמשתנים יושבת מתחת לכללים
    assert "main.container .hljs-keyword" in html


def test_a_one_off_vscode_theme_is_posted(wa, monkeypatch):
    _serve(wa, monkeypatch, MD_FILE)
    resp = _client(wa).post(SKELETON, data={"vscode_json": json.dumps(VSCODE_THEME), "math": "1"})

    assert resp.status_code == 200, resp.get_data(as_text=True)[:500]
    html = resp.get_data(as_text=True)
    assert "#fdfdfd" in html.lower()
    assert "#ab0000" in html.lower()
    assert wa.markdown_editor_katex_css() in html


# ---------------------------------------------------------------------------
# עמוד הקובץ
# ---------------------------------------------------------------------------

def _modal_tag(html: str) -> str:
    match = re.search(r'<div id="exportThemeModal"[^>]*>', html)
    assert match, "חלון הייצוא לא הוצג"
    return match.group(0)


def test_the_file_page_hands_the_modal_its_switch_and_marker(wa, monkeypatch):
    _serve(wa, monkeypatch, MD_FILE)
    html = _client(wa).get(f"/file/{FILE_ID}").get_data(as_text=True)

    modal = _modal_tag(html)
    assert 'data-browser-render="1"' in modal
    assert f'data-content-marker="{EDITOR_EXPORT_CONTENT_MARKER_TEXT}"' in modal

    # המנוע ב-``<template>``: הסקריפטים שם אינם רצים עד הייצוא
    engine = re.search(r'<template id="styledExportEngine">(.*?)</template>', html, re.S)
    assert engine, "אין את המנוע של הייצוא"
    assert "js/live-preview.js" in engine.group(1) and "js/md_preview.bundle.js" in engine.group(1)
    outside = html.replace(engine.group(0), "")
    assert "js/live-preview.js" not in outside, "המנוע נטען בעמוד עצמו, ולא רק בייצוא"

    core = html.index("js/utils/styled-export-core.js")
    assert core < html.index("js/export-modal.js")
    assert html.index("js/utils/editor-page-utils.js") < core
    assert html.count("js/utils/editor-page-utils.js") == 1


def test_the_switch_off_returns_the_modal_to_the_server(wa, monkeypatch):
    _serve(wa, monkeypatch, MD_FILE)
    monkeypatch.setattr(wa, "STYLED_EXPORT_BROWSER_RENDER", False)
    html = _client(wa).get(f"/file/{FILE_ID}").get_data(as_text=True)
    assert 'data-browser-render="0"' in _modal_tag(html)


def test_flipping_the_switch_is_not_served_from_a_304(wa, monkeypatch):
    """הוולידטור עובד (304 כשכלום לא השתנה), ואחרי היפוך המתג אותו ETag מקבל עמוד חדש עם הערך החדש."""
    _serve(wa, monkeypatch, MD_FILE)
    client = _client(wa)
    etag = client.get(f"/file/{FILE_ID}").headers["ETag"]
    assert client.get(f"/file/{FILE_ID}", headers={"If-None-Match": etag}).status_code == 304

    monkeypatch.setattr(wa, "STYLED_EXPORT_BROWSER_RENDER", False)
    after = client.get(f"/file/{FILE_ID}", headers={"If-None-Match": etag})

    assert after.status_code == 200, "הוחזר 304 עם המתג הישן"
    assert 'data-browser-render="0"' in _modal_tag(after.get_data(as_text=True))


def test_a_file_too_large_to_show_has_the_modal_but_no_raw_text(wa, monkeypatch):
    """``export-modal.js`` מביא את הטקסט מ-``/download`` כשאין ``#rawCode`` — וזה המצב בקובץ מעל 1MB."""
    big = dict(MD_FILE, code="# גדול\n\n" + "שורה ארוכה של טקסט\n" * 60_000)
    assert len(big["code"].encode("utf-8")) > 1024 * 1024
    _serve(wa, monkeypatch, big)
    html = _client(wa).get(f"/file/{FILE_ID}").get_data(as_text=True)

    assert 'data-browser-render="1"' in _modal_tag(html)
    assert 'id="rawCode"' not in html


def test_download_returns_the_same_text_the_export_reads(wa, monkeypatch):
    _serve(wa, monkeypatch, MD_FILE)
    resp = _client(wa).get(f"/download/{FILE_ID}")
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == MD_FILE["code"]


# ---------------------------------------------------------------------------
# ההכרעות המשותפות
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("theme", "expected"),
    [
        ({"category": "light", "variables": {"--bg-primary": "#000000"}}, "default"),
        ({"category": "dark", "variables": {"--bg-primary": "#ffffff"}}, "dark"),
        ({"variables": {"--bg-primary": "#f8f6f1"}}, "default"),
        ({"variables": {"--bg-primary": "#2d353b"}}, "dark"),
        # הסף: בהירות 128 בדיוק היא עדיין כהה, 129 בהירה (``> 128`` כמו ב-``pageMermaidTheme``)
        ({"variables": {"--bg-primary": "#808080"}}, "dark"),
        ({"variables": {"--bg-primary": "#818181"}}, "default"),
        ({"variables": {"--bg-primary": "#ffffffcc"}}, "default"),
        ({"variables": {"--bg-primary": "rgb(255, 255, 255)"}}, "dark"),
        ({"variables": {}}, "dark"),
        ({}, "dark"),
    ],
)
def test_the_mermaid_theme_of_an_export(theme, expected):
    assert export_mermaid_theme(theme) == expected


@pytest.mark.parametrize("variables", [["--bg-primary", "#ffffff"], "#ffffff", None])
def test_variables_that_are_not_a_dict_count_as_none(variables):
    """ערכת משתמש מגיעה מהמסד; רשומה פגומה אינה מפילה את רשימת הערכות."""
    assert export_mermaid_theme({"variables": variables}) == "dark"


def test_the_threshold_and_formula_are_those_of_the_live_preview():
    """ההכרעה בשרת היא עותק של ``pageMermaidTheme`` ב-``live-preview.js``, והתרשימים של התצוגה ושל הקובץ אמורים לצאת
    באותה ערכה. שני עותקים בשתי שפות — והטסט קורא את שניהם ומשווה (RECURRING-PATTERNS R6)."""
    from pathlib import Path

    import services.styled_export_service as ses

    live = (Path(__file__).resolve().parent.parent / "webapp" / "static" / "js" / "live-preview.js").read_text(encoding="utf-8")
    body = live[live.index("function pageMermaidTheme()"):]
    body = body[:body.index("\n    }\n")]
    js = re.search(r"brightness = \(r \* (\d+) \+ g \* (\d+) \+ b \* (\d+)\) / (\d+);\s*"
                   r"mermaidTheme = brightness > (\d+) \? 'default' : 'dark';", body)
    assert js, "המבנה של pageMermaidTheme השתנה — עדכנו את הטסט ואת export_mermaid_theme יחד"

    py = Path(ses.__file__).read_text(encoding="utf-8")
    assert f"brightness = (r * {js.group(1)} + g * {js.group(2)} + b * {js.group(3)}) / {js.group(4)}" in py
    assert int(js.group(5)) == ses._LIGHT_BACKGROUND_BRIGHTNESS


@pytest.mark.parametrize(
    ("file_name", "title"),
    [("Guide.MD", "Guide"), ("notes.markdown", "notes"), ("a.md.txt", "a.md.txt"), (None, "Untitled"), ("", "Untitled")],
)
def test_the_title_is_the_file_name_without_the_extension(file_name, title):
    assert styled_export_title(file_name) == title


@pytest.mark.parametrize(
    ("title", "filename"),
    [
        ("מדריך שלי", "מדריך שלי.html"),
        ('a"b\r\nc/d', "abcd.html"),
        ("x" * 80, "x" * 50 + ".html"),
        ("  ", "document.html"),
        ("???", "document.html"),
    ],
)
def test_the_downloaded_file_name(title, filename):
    assert styled_export_filename(title) == filename


def test_the_themes_api_gives_every_theme_its_mermaid_theme(wa, monkeypatch):
    data = _client(wa).get("/api/export/themes").get_json()

    assert data["ok"] is True
    by_id = {p["id"]: p["mermaid_theme"] for p in data["presets"]}
    assert by_id["pen-paper-coffee"] == "default"
    assert by_id["tech-guide-dark"] == "dark"
    assert set(by_id.values()) <= {"default", "dark"}
    [user] = data["user_themes"]
    assert user["mermaid_theme"] == "default"


def test_parsing_a_vscode_theme_gives_its_mermaid_theme(wa, monkeypatch):
    resp = _client(wa).post("/api/export/parse-vscode", json={"json_content": json.dumps(VSCODE_THEME)})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["mermaid_theme"] == "default"
