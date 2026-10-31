"""העורך הציבורי (``/markdown-editor``), ושני הקבצים שמנועי חיפוש קוראים: ``robots.txt`` ו-``sitemap.xml``.

העמוד נועד לגולשים שמגיעים מחיפוש, כלומר מבקר בלי סשן הוא המקרה הרגיל, והטסטים מבקשים אותו מ-client חדש. מה
שנבדק כאן הוא מה שהשרת מגיש: הערכה שהעמוד מוצג בה, טקסט ההדגמה, והתגיות שמנועי חיפוש ורשתות חברתיות קוראים.
ההתנהגות בדפדפן — העורך, התצוגה החיה, הטיוטה והכפתורים — נבדקת ב-``tests/test_markdown_editor_browser.py``.
הרקע: ``docs/webapp/markdown-editor.rst``.
"""

from __future__ import annotations

import html
import json
import logging
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

import pytest

pytest.importorskip("flask")

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"

#: ערכה ציבורית מינימלית, בצורה ש-``_fetch_shared_theme`` מחזיר. ``colors`` לא ריק, כי ``base.html``
#: מחיל ערכה ציבורית רק כשיש לה צבעים (``hasSharedTheme``).
FAKE_THEME = {
    "id": "everforest_dark",
    "name": "Everforest Dark",
    "description": "",
    "colors": {"--bg-primary": "#2d353b"},
    "syntax_css": "",
    "syntax_colors": {},
    "is_featured": False,
}


class _Head(HTMLParser):
    """אוסף את מה שסורק רואה: ``<meta>``, ``<link rel=canonical>``, ה-JSON-LD, וה-textarea של העורך."""

    def __init__(self) -> None:
        super().__init__()
        self.props: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.canonical: str | None = None
        self.ld_json: list[str] = []
        self.textarea: str | None = None
        self._in = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("property"):
            self.props[a["property"]] = a.get("content") or ""
        if tag == "meta" and a.get("name"):
            self.names[a["name"]] = a.get("content") or ""
        if tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        if tag == "script" and a.get("type") == "application/ld+json":
            self._in, self._buf = "ld", []
        if tag == "textarea" and a.get("id") == "codeTextarea":
            self._in, self._buf = "textarea", []

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if self._in == "ld" and tag == "script":
            self.ld_json.append("".join(self._buf))
            self._in = None
        elif self._in == "textarea" and tag == "textarea":
            self.textarea = "".join(self._buf)
            self._in = None


@pytest.fixture
def wa():
    import webapp.app as webapp_app

    return webapp_app


@pytest.fixture
def theme_available(wa, monkeypatch):
    """הערכה הציבורית קיימת. ``_load_shared_theme_for_request`` קורא ל-``_get_shared_theme_cached`` לפי שם
    בזמן הקריאה, ולכן ההחלפה במודול חלה עליו; monkeypatch מחזיר את המקור בסוף הטסט."""
    calls: list[str] = []

    def fake(theme_id):
        calls.append(theme_id)
        return dict(FAKE_THEME) if theme_id == "everforest_dark" else None

    monkeypatch.setattr(wa, "_get_shared_theme_cached", fake)
    return calls


def _get(wa, path="/markdown-editor"):
    # client חדש, בלי session_transaction — כמו גולש שהגיע מחיפוש
    return wa.app.test_client().get(path)


def _head(resp) -> _Head:
    parser = _Head()
    parser.feed(resp.get_data(as_text=True))
    return parser


# ---------------------------------------------------------------------------
# העמוד
# ---------------------------------------------------------------------------


def test_the_editor_answers_without_login(wa, theme_available):
    resp = _get(wa)

    # 200 ישיר ולא הפניה ל-/login
    assert resp.status_code == 200, resp.status_code
    assert resp.mimetype == "text/html"


def test_the_editor_is_exempt_from_the_global_rate_limit(wa):
    """מגבלה גורפת לפי IP חלה גם על הסורק של גוגל; עמוד שנועד לחיפוש לא יכול להיחסם לו
    (``bugbot-rules/blanket-policy-silent-block.md`` §7). אותה בדיקה גם ל-robots.txt ול-sitemap.xml.

    ``exemption_scope`` הוא מה שהמגביל עצמו שואל על כל בקשה, ולכן הבדיקה לא תלויה באחסון שלו
    (כמו ב-``tests/test_docs_index_routes.py``).
    """
    from flask_limiter import ExemptionScope

    assert wa.limiter is not None
    manager = wa.limiter.limit_manager
    for endpoint in ("markdown_editor", "robots_txt", "sitemap_xml"):
        assert manager.exemption_scope(wa.app, endpoint, None) & ExemptionScope.DEFAULT, endpoint
    # בקרה: endpoint רגיל אינו פטור, כלומר הבדיקה מסוגלת להיכשל
    assert (
        not manager.exemption_scope(wa.app, "api_docs_index_status", None) & ExemptionScope.DEFAULT
    )


def test_the_page_is_shown_in_the_shared_theme(wa, theme_available):
    """הסקריפט המוקדם ב-``base.html`` הוא שקובע את ``data-theme``, ולכן נבדק מה שהוא מקבל."""
    body = _get(wa).get_data(as_text=True)

    assert "var serverTheme = 'shared:everforest_dark';" in body
    assert "var hasSharedTheme = true;" in body
    assert theme_available == ["everforest_dark"]


def test_the_route_overrides_the_theme_of_a_member_with_a_custom_theme(wa, monkeypatch):
    """ערך שמועבר ל-``render_template`` גובר על מה ש-``inject_globals`` מחזיר. הבדיקה רואה את ההקשר
    שהתבנית קיבלה בפועל, אצל משתמש מחובר שיש לו ערכה מותאמת פעילה: ``custom_theme`` חייב להיות מאופס,
    אחרת צבעי התחביר של הערכה שלו היו חלים על העמוד דרך ``[data-theme-type="custom"]``.

    מסמך המשתמש מגיע מ-``_request_user_doc``, ש-``inject_globals`` קורא אחרי ``get_db`` — ושניהם מוחלפים,
    כדי לא לגעת במסד. ההרצה הראשונה היא בקרה: בלי הערכה הציבורית הראוט לא דורס כלום, והערכה של המשתמש
    כן מגיעה לתבנית. בלעדיה, טסט שההקמה שלו לא יוצרת ערכה מותאמת היה עובר גם בלי האיפוס."""
    import types

    from flask import template_rendered

    member_doc = {
        "user_id": 1,
        "ui_prefs": {"theme": "custom:mine"},
        "custom_themes": [
            {
                "id": "mine",
                "name": "Mine",
                "is_active": True,
                "variables": {"--bg-primary": "#ffffff"},
                "syntax_css": ".tok{}",
            }
        ],
    }
    monkeypatch.setattr(wa, "get_db", lambda: types.SimpleNamespace())
    monkeypatch.setattr(wa, "_request_user_doc", lambda user_id: member_doc)

    def render_as_member() -> dict:
        seen: list[dict] = []

        def record(sender, template, context, **extra):
            if template.name == "markdown_editor.html":
                seen.append(context)

        client = wa.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["user_data"] = {"id": 1, "first_name": "חבר"}
        with template_rendered.connected_to(record, wa.app):
            resp = client.get("/markdown-editor")
        assert resp.status_code == 200, resp.status_code
        assert len(seen) == 1
        return seen[0]

    monkeypatch.setattr(wa, "_get_shared_theme_cached", lambda theme_id: None)
    control = render_as_member()
    assert (
        control["custom_theme"] and control["custom_theme"]["id"] == "mine"
    ), "ההקמה לא יצרה ערכה מותאמת"

    monkeypatch.setattr(
        wa,
        "_get_shared_theme_cached",
        lambda theme_id: dict(FAKE_THEME) if theme_id == "everforest_dark" else None,
    )
    ctx = render_as_member()
    assert ctx["ui_theme"] == "shared:everforest_dark"
    assert ctx["shared_theme"]["id"] == "everforest_dark"
    assert ctx["custom_theme"] is None
    assert ctx["ui_theme_custom_id"] == ""


def test_a_missing_theme_renders_the_site_theme_and_warns(wa, monkeypatch, caplog):
    """ערכה שנמחקה או מסד שלא זמין — העמוד עולה בערכה הרגילה, ולא נופל. והאזהרה נרשמת, כי עמוד בערכה הלא
    נכונה הוא תקלה שמישהו צריך לראות."""
    monkeypatch.setattr(wa, "_get_shared_theme_cached", lambda theme_id: None)

    with caplog.at_level(logging.WARNING):
        resp = _get(wa)

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "var hasSharedTheme = false;" in body
    assert "shared:everforest_dark" not in body
    assert any(
        "markdown_editor" in r.getMessage() and "everforest_dark" in r.getMessage()
        for r in caplog.records
    )


def test_the_demo_text_reaches_the_editor_unchanged(wa, theme_available):
    """טקסט ההדגמה עובר כמשתנה ש-Jinja מברח, ולא כתבנית. הוא כולל ``{{ __html: html }}``: ב-include היה
    נשבר הרינדור, ובלי בריחה תגית בטקסט הייתה הופכת ל-HTML של העמוד."""
    from webapp.markdown_editor import DEMO_PATH

    demo = DEMO_PATH.read_text(encoding="utf-8")
    assert "{{ __html: html }}" in demo, "הטסט נשען על התבנית הזו שבטקסט; אם הוסרה, צריך עוגן אחר"

    parser = _head(_get(wa))
    assert parser.textarea is not None, "ה-textarea של העורך לא נמצא"
    # HTMLParser מפענח את הישויות, כמו הדפדפן. הדפדפן גם משמיט שורה ריקה אחת בתחילת textarea — אין כזו כאן.
    assert not demo.startswith("\n")
    assert html.unescape(parser.textarea) == demo


def test_search_and_share_tags_point_to_the_absolute_url(wa, theme_available):
    parser = _head(_get(wa))

    url = parser.canonical
    assert url and re.match(r"^https?://[^/]+/markdown-editor$", url), url
    assert parser.props.get("og:url") == url
    for key in ("og:title", "og:description", "og:type", "og:site_name", "og:locale"):
        assert parser.props.get(key), key
    assert parser.names.get("description")

    assert len(parser.ld_json) == 1
    data = json.loads(parser.ld_json[0])
    assert data["@type"] == "WebApplication"
    assert data["url"] == url
    assert data["description"] == parser.names["description"]


def test_the_demo_is_read_on_first_use_and_a_failure_is_not_remembered(monkeypatch, tmp_path):
    """``demo_text`` לא קורא את הקובץ בזמן ייבוא (``bugbot-rules/import-time-side-effects.md``), ו-``lru_cache``
    לא שומר חריגה: קובץ שחסר בבקשה אחת יימצא בבאה. הקאש מאופס לפני ואחרי, כדי שהטסט לא ישאיר ערך משלו.
    """
    from webapp import markdown_editor as me

    me.demo_text.cache_clear()
    try:
        monkeypatch.setattr(me, "DEMO_PATH", tmp_path / "missing.md")
        with pytest.raises(FileNotFoundError):
            me.demo_text()
        (tmp_path / "missing.md").write_text("# שלום\n", encoding="utf-8")
        assert me.demo_text() == "# שלום\n"
    finally:
        me.demo_text.cache_clear()


# ---------------------------------------------------------------------------
# robots.txt ו-sitemap.xml
# ---------------------------------------------------------------------------


def test_robots_points_to_the_sitemap_and_does_not_block_static_files(wa):
    resp = _get(wa, "/robots.txt")

    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    lines = resp.get_data(as_text=True).splitlines()
    sitemap = [line for line in lines if line.startswith("Sitemap:")]
    assert len(sitemap) == 1
    assert re.match(r"^Sitemap: https?://[^/]+/sitemap\.xml$", sitemap[0]), sitemap[0]
    # גוגל מרנדר עמוד עם ה-CSS וה-JS שלו; חסימה של /static הייתה מראה לו עמוד שבור
    disallowed = [line.split(":", 1)[1].strip() for line in lines if line.startswith("Disallow:")]
    # כלל Disallow חוסם כל נתיב שמתחיל בו, ולכן נבדק נתיב אמיתי של קובץ סטטי
    static_file = "/static/js/markdown-editor.js"
    assert not any(static_file.startswith(path) for path in disallowed if path), disallowed


def test_the_sitemap_lists_every_public_page_with_an_absolute_url(wa):
    resp = _get(wa, "/sitemap.xml")

    assert resp.status_code == 200
    assert resp.mimetype == "application/xml"
    root = ET.fromstring(resp.get_data())
    assert root.tag == f"{{{SITEMAP_NS}}}urlset"
    locs = [el.text for el in root.iter(f"{{{SITEMAP_NS}}}loc")]

    with wa.app.test_request_context("/"):
        from flask import url_for

        paths = [url_for(endpoint) for endpoint in wa.SITEMAP_ENDPOINTS]
    assert len(locs) == len(paths)
    for loc, path in zip(locs, paths):
        assert re.match(r"^https?://[^/]+/", loc), loc
        assert loc.endswith(path), (loc, path)
    assert any(loc.endswith("/markdown-editor") for loc in locs)


def test_the_sitemap_escapes_the_url(wa, monkeypatch):
    """``<loc>`` חייב להיות מבורח (sitemaps.org). כתובת עם ``&`` הייתה הופכת את הקובץ ל-XML שבור."""
    monkeypatch.setattr(wa, "_webapp_base_url", lambda: "https://example.test/a&b")

    body = _get(wa, "/sitemap.xml").get_data(as_text=True)

    assert "a&amp;b" in body
    locs = [el.text for el in ET.fromstring(body).iter(f"{{{SITEMAP_NS}}}loc")]
    assert all(loc.startswith("https://example.test/a&b/") for loc in locs), locs
