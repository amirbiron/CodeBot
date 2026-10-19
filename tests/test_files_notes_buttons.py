"""כפתורי הפתקים בעמוד הקבצים: חיפוש בפתקים, לוחות הפתקים, ו"סטיקי נוטס" בשורת הקטגוריות.

שלושת הכפתורים מציירים את אותו דף ב-SVG. בחיפוש הזכוכית המגדלת נחתכת מתוכו
ב-``mask``. שם ה-``mask`` מופיע פעמיים — בהגדרה וב-``url(#...)`` שמפנה
אליה — ושגיאת הקלדה ביניהם אינה מייצרת שום שגיאה: האייקון פשוט נראה אחרת
או נעלם. הבדיקה הזו טקסטואלית, על התבנית; מה שהחיתוך באמת עושה על המסך
נמדד בדפדפן כשהכפתורים נוספו.

שורת הקטגוריות והאייקונים נבדקים על ה-HTML שהראוט ``/files`` מגיש — מה
שהדפדפן מקבל — ולא על קובץ התבנית: אייקון הלוחות מגיע מהמאקרו
``note_sheet_icon``, ורק הרינדור מראה מה הוא הפיק.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

FILES_HTML = Path(__file__).resolve().parent.parent / "webapp/templates/files.html"


def _refs_and_ids(html: str) -> tuple[set[str], set[str]]:
    refs = set(re.findall(r"url\(#([\w-]+)\)", html))
    ids = set(re.findall(r'\bid="([\w-]+)"', html))
    return refs, ids


def test_every_svg_reference_points_at_an_id_in_the_template():
    refs, ids = _refs_and_ids(FILES_HTML.read_text(encoding="utf-8"))
    assert refs, "לא נמצא אף ``url(#...)`` — האם אייקון החיפוש בפתקים הוסר?"
    missing = refs - ids
    assert not missing, f"הפניות ל-id שאינו קיים בתבנית: {sorted(missing)}"


def test_both_note_buttons_are_on_the_page():
    html = FILES_HTML.read_text(encoding="utf-8")
    assert 'href="/notes/search"' in html
    assert 'href="/boards"' in html


def test_the_reference_guard_can_actually_fail(tmp_path, monkeypatch):
    """מוטציה: שם ה-``mask`` בהגדרה משתנה, וההפניה נשארת."""
    html = FILES_HTML.read_text(encoding="utf-8")
    refs, _ = _refs_and_ids(html)
    name = sorted(refs)[0]
    needle = f'id="{name}"'
    assert html.count(needle) == 1, "המוטציה מניחה הגדרה אחת בדיוק"
    mutated = html.replace(needle, f'id="{name}-typo"', 1)
    fake = tmp_path / "files.html"
    fake.write_text(mutated, encoding="utf-8")
    monkeypatch.setattr(f"{__name__}.FILES_HTML", fake)
    with pytest.raises(AssertionError):
        test_every_svg_reference_points_at_an_id_in_the_template()


# ---------------------------------------------------------------------------
# הרינדור — דרך הראוט ``/files``, על ה-HTML שהדפדפן מקבל
# ---------------------------------------------------------------------------

USER_ID = 123


class _EmptySnippets:
    """דמה בלי קבצים.

    **מה זה אומר על הכיסוי:** שורת הקטגוריות ושורת הכלים מרונדרות גם בעמוד
    ריק, ולכן הבדיקות כאן מכסות את שכבת התבנית בלבד. הדמה מתעלמת מצינור
    ה-``aggregate`` של ``/files``, וכשל שם לא ייתפס כאן.
    """

    def aggregate(self, _pipeline, **_kwargs):
        return []

    def distinct(self, _field, _query=None):
        return []


class _Users:
    def find_one(self, _query, _projection=None):
        return {"user_id": USER_ID, "ui_prefs": {}}


class _DB:
    def __init__(self):
        self.code_snippets = _EmptySnippets()
        self.users = _Users()


class _CacheDisabled:
    """``/files`` שומר את ה-HTML המרונדר בקאש; כאן כל בקשה מרנדרת מחדש."""

    is_enabled = False


class _Anchors(HTMLParser):
    """כל ``<a>`` בעמוד, לפי הסדר: המאפיינים, הטקסט, ונתיבי ה-SVG שבתוכו.

    ``in_categories`` — האם הקישור יושב בתוך ``div.categories-section``. נתיב
    שבתוך ``<mask>`` אינו חלק מהציור אלא מהחיתוך, ולכן הוא לא נאסף. תוכן
    ``<script>`` אינו מפוענח כתגיות, כך ש-``<a`` במחרוזת JS לא נספר.
    """

    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[dict] = []
        self._current: dict | None = None
        self._divs: list[bool] = []
        self._mask_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            self._divs.append("categories-section" in (attrs.get("class") or "").split())
        elif tag == "a":
            self._current = {"attrs": attrs, "text": "", "paths": [], "in_categories": any(self._divs)}
            self.anchors.append(self._current)
        elif tag == "mask":
            self._mask_depth += 1
        elif tag == "path" and self._current is not None and not self._mask_depth:
            self._current["paths"].append(attrs.get("d"))

    def handle_endtag(self, tag):
        if tag == "div" and self._divs:
            self._divs.pop()
        elif tag == "a":
            self._current = None
        elif tag == "mask" and self._mask_depth:
            self._mask_depth -= 1

    def handle_data(self, data):
        if self._current is not None:
            self._current["text"] += data


@pytest.fixture
def files_page(monkeypatch):
    """מחזיר ``render(url)`` ← ``(html, anchors)``, ואת הכתובת הרשומה של עמוד הלוחות."""
    pytest.importorskip("flask")
    from flask import url_for

    from webapp import app as webapp_app

    monkeypatch.setattr(webapp_app, "get_db", lambda: _DB(), raising=True)
    monkeypatch.setattr(webapp_app, "cache", _CacheDisabled(), raising=True)

    def render(url: str = "/files"):
        with webapp_app.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = USER_ID
                sess["user_data"] = {"id": USER_ID, "first_name": "Test"}
            response = client.get(url)
        assert response.status_code == 200, url
        html = response.get_data(as_text=True)
        parser = _Anchors()
        parser.feed(html)
        for anchor in parser.anchors:
            anchor["text"] = " ".join(anchor["text"].split())
        return html, parser.anchors

    with webapp_app.app.test_request_context():
        boards_url = url_for("boards_ui.boards_page")
    return render, boards_url


def _one(anchors, **attrs):
    found = [a for a in anchors if all(a["attrs"].get(k) == v for k, v in attrs.items())]
    assert len(found) == 1, f"ציפיתי לקישור אחד עם {attrs}, נמצאו {len(found)}"
    return found[0]


def test_the_categories_row_has_sticky_notes_and_no_repo_or_other_buttons(files_page):
    """השורה, לפי סדר ה-DOM — כלומר מימין ← לשמאל, כי העמוד RTL.

    "לפי ריפו" ו"שאר קבצים" יצאו מהשורה, "מועדפים" עבר למקום של "לפי ריפו",
    ו"סטיקי נוטס" נכנס למקום של "מועדפים". הכתובת של "סטיקי נוטס" נגזרת
    מהראוט הרשום של עמוד הלוחות, ולא מוקלדת כאן.
    """
    render, boards_url = files_page
    _html, anchors = render()

    row = [(a["attrs"].get("href"), a["text"]) for a in anchors if a["in_categories"]]
    assert row == [
        ("/files", "כל הקבצים"),
        ("/files?category=recent", "נפתחו לאחרונה"),
        ("/files?category=favorites", "מועדפים"),
        (boards_url, "סטיקי נוטס"),
        ("#", "שולחן עבודה"),
        ("/files?category=large", "קבצים גדולים"),
    ]


def test_the_sticky_notes_button_draws_the_boards_icon(files_page):
    """"סטיקי נוטס" מצייר את אותו פתק כמו כפתור הלוחות בשורת הכלים שמתחת לחיפוש."""
    render, boards_url = files_page
    _html, anchors = render()

    sticky = [a for a in anchors if a["in_categories"] and a["attrs"].get("href") == boards_url]
    assert len(sticky) == 1, sticky
    toolbar = _one(anchors, href=boards_url, **{"aria-label": "לוחות פתקים"})
    assert toolbar["paths"], "כפתור הלוחות בשורת הכלים מרונדר בלי ציור"
    assert sticky[0]["paths"] == toolbar["paths"]


def test_the_notes_search_icon_cuts_the_same_sheet(files_page):
    """אייקון החיפוש בפתקים הוא עותק בכתב יד של ``note_sheet_icon``, עם חיתוך.

    החיתוך יושב ב-``<mask>`` ולא נספר; מה שנשאר חייב להיות אותו דף. בלי
    ההשוואה הזו, שינוי בציור של המאקרו היה משאיר את החיפוש עם הדף הישן.
    """
    render, boards_url = files_page
    _html, anchors = render()

    search = _one(anchors, **{"aria-label": "חיפוש בפתקים"})
    toolbar = _one(anchors, href=boards_url, **{"aria-label": "לוחות פתקים"})
    assert search["paths"] and search["paths"] == toolbar["paths"]


@pytest.mark.parametrize(
    "category, label",
    [("repo", "קטגוריה: לפי ריפו"), ("other", "קטגוריה: שאר הקבצים")],
    ids=["repo", "other"],
)
def test_a_category_without_a_button_still_works_by_direct_url(files_page, category, label):
    """רק הכפתור הוסר: הקטגוריה עדיין מוגשת, ושורת המידע אומרת באיזו קטגוריה מדובר."""
    render, _boards_url = files_page
    html, anchors = render(f"/files?category={category}")

    assert label in html
    assert not [
        a for a in anchors if a["in_categories"] and f"category={category}" in (a["attrs"].get("href") or "")
    ]
