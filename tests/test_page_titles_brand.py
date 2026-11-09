"""השם בכותרות העמודים של הוובאפ הוא ``CodeKeeper``.

הכותרת של העמוד (``<title>``) היא מה שמופיע בלשונית של הדפדפן, וגם מה שמופיע בתצוגה המקדימה של קישור ששותף (וואטסאפ, טלגרם): לעמודים שדורשים התחברות אין תגיות ``og:``, ולכן התצוגה המקדימה לוקחת את ה-``<title>``. מי שבונה את התצוגה המקדימה אינו מחובר, ולכן קישור לכל עמוד כזה מפנה אותו לעמוד ההתחברות (``login_required`` ב-``webapp/app.py``), והכותרת שהוא רואה היא זו של ``login.html``. עד נובמבר 2026 היה כתוב שם, וברוב הכותרות, ``Code Keeper Bot``.

השם עם הרווח, ``Code Keeper``, נשאר בכוונה בסרגל העליון של ``base.html`` ובטקסטים של שיתוף. הבדיקה כאן היא רק על כותרות העמודים.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

pytest.importorskip("flask")

TEMPLATES = Path(__file__).resolve().parents[1] / "webapp" / "templates"

# השם הישן, בשתי הצורות שהופיעו בכותרות: "Code Keeper Bot" ו-"Code Keeper".
OLD_NAME_RE = re.compile(r"Code\s+Keeper")

# שלוש הדרכים שבהן תבנית קובעת את כותרת העמוד. ``endblock`` יכול להישבר לשורה הבאה, כמו ב-``settings.html``.
TITLE_SOURCES_RE = re.compile(
    r"{%-?\s*block\s+title\s*-?%}(?P<block>.*?){%-?\s*endblock"
    r"|<title\b[^>]*>(?P<tag>.*?)</title>"
    r"|document\.title\s*=(?P<js>[^;\n]*)",
    re.S,
)


class _Title(HTMLParser):
    """הטקסט של ``<title>`` בעמוד שהשרת החזיר, כמו שסורק של תצוגה מקדימה קורא אותו."""

    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self._inside = False
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "title" and self.title is None:
            self._inside = True
            self._text = []

    def handle_data(self, data):
        if self._inside:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "title" and self._inside:
            self._inside = False
            self.title = " ".join("".join(self._text).split())


def _anonymous_client():
    from webapp import app as webapp_app

    # client חדש, בלי session — כמו הסורק שבונה את התצוגה המקדימה
    return webapp_app.app.test_client()


# ``/boards`` מפנה בעצמו (``boards_page`` ב-``webapp/boards_ui.py``) ולא דרך ``login_required``, ומגיע לאותו עמוד.
@pytest.mark.parametrize("page", ["/files", "/dashboard", "/boards"])
def test_a_shared_link_to_a_page_behind_login_previews_the_codekeeper_name(page):
    resp = _anonymous_client().get(page, follow_redirects=True)

    assert resp.history, f"{page} answered without a redirect — it is no longer behind login, pick another page"
    assert resp.request.path == "/login", (page, resp.request.path)
    assert resp.status_code == 200, (page, resp.status_code)
    parser = _Title()
    parser.feed(resp.get_data(as_text=True))
    assert parser.title == "התחברות - CodeKeeper", parser.title


def test_no_template_titles_a_page_with_the_old_name():
    found = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        for match in TITLE_SOURCES_RE.finditer(text):
            title = next(group for group in match.groups() if group is not None)
            if OLD_NAME_RE.search(title):
                line = text.count("\n", 0, match.start()) + 1
                found.append(f"{path.relative_to(TEMPLATES)}:{line}: {' '.join(title.split())}")
    assert not found, "page titles must say CodeKeeper:\n" + "\n".join(found)
