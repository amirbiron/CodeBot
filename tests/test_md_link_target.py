"""קישור שמוביל לעמוד נפתח בלשונית חדשה גם ברנדררים של צד השרת — ``services/md_link_target.py``.

**מה נבדק:**

- הכלל (``opens_in_new_tab``) מול ``tests/fixtures/md_link_target_cases.json`` — אותה טבלה
  ש-``tests/md-link-target-plugin.test.js`` מריץ מול ``opensInNewTab`` של הדפדפן. כך העותק השני של הכלל לא
  נסחף בשקט (R6).
- שני הרנדררים של השרת, דרך הממשק של הצרכן: ``POST /api/preview/live`` (מסלול הגיבוי של התצוגה החיה,
  ``_render_markdown_preview``, שגם מצב הקריאה קורא לו) ו-``markdown_to_html`` (הייצוא המעוצב
  כש-``STYLED_EXPORT_BROWSER_RENDER`` כבוי). בשניהם הקישורים לעמודים יוצאים עם ``target="_blank"``
  ו-``rel="noopener noreferrer"`` גם אחרי המסנן, ועוגנים ומייל יוצאים בלי.
- שני המקרים שבהם העץ של Python-Markdown אינו הכתובת שהדפדפן יקרא (ההסבר ב-docstring של המודול): קישור מייל אוטומטי
  (``<a@b.c>``), שה-``href`` שלו מקודד תו-תו, ועוגן שנכתב עם ``\\#``. שניהם נשארים בלי ``target``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from services.md_link_target import opens_in_new_tab
from services.styled_export_service import markdown_to_html
from webapp import app as webapp_app

CASES_PATH = Path(__file__).parent / "fixtures" / "md_link_target_cases.json"
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]

#: קישור לכל צורה ש-Python-Markdown מייצר, ועוגנים. ``\\#`` — עוגן שנכתב עם תו בריחה.
MARKDOWN = (
    "# פתיחה\n\n"
    "קישור [מדריך](https://example.com/docs), <https://example.com/auto>, [בהפניה][ref] ו-[קובץ](docs/a.md).\n\n"
    "מייל <someone@example.com>, [מייל מפורש](mailto:other@example.com), [פנימי](#section) ו-[בריחה](\\#escaped).\n\n"
    "[ref]: https://example.com/ref\n"
)
NEW_TAB = ["https://example.com/docs", "https://example.com/auto", "https://example.com/ref", "docs/a.md"]
SAME_TAB = ["mailto:someone@example.com", "mailto:other@example.com", "#section", "#escaped"]


@pytest.mark.parametrize("href,expected,why", CASES, ids=[repr(case[0]) for case in CASES])
def test_the_rule_matches_the_shared_table(href, expected, why):
    assert opens_in_new_tab(href) is expected, why


def test_non_strings_do_not_open_a_tab():
    assert opens_in_new_tab(None) is False
    assert opens_in_new_tab(42) is False


def _links(html: str) -> dict:
    """``href`` → ``(target, rel)`` של כל קישור, כמו שהדפדפן יקרא את ה-HTML (גם ``&#109;...`` מפוענח)."""
    soup = BeautifulSoup(html, "html.parser")
    return {a.get("href"): (a.get("target"), " ".join(a.get("rel") or []) or None) for a in soup.find_all("a")}


def _assert_rule_applied(links: dict) -> None:
    missing = [href for href in NEW_TAB + SAME_TAB if href not in links]
    assert not missing, f"הדגימה לא ייצרה את הקישורים {missing}: {links}"
    for href in NEW_TAB:
        assert links[href] == ("_blank", "noopener noreferrer"), href
    for href in SAME_TAB:
        assert links[href] == (None, None), href


@pytest.fixture
def client():
    client = webapp_app.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 42
        sess["user_data"] = {"id": 42, "first_name": "Tester"}
    return client


def test_live_preview_server_fallback_opens_page_links_in_a_new_tab(client):
    resp = client.post("/api/preview/live", json={"content": MARKDOWN, "language": "markdown"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["mode"] == "markdown"
    _assert_rule_applied(_links(data["html"]))


def test_server_styled_export_opens_page_links_in_a_new_tab():
    html, _toc = markdown_to_html(MARKDOWN)
    _assert_rule_applied(_links(html))
