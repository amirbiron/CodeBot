"""תצוגת "נוצר"/"עודכן" בתבניות הקובץ.

התאריכים מגיעים לתבנית כמחרוזות מפורמטות מראש (``format_datetime_display``),
ולכן ההשוואה בתבנית היא בין שתי מחרוזות — בדיוק השאלה שמעניינת: האם שתי
השורות מציגות את אותו הדבר. קובץ שמעולם לא נערך מציג אותו תאריך פעמיים,
וזו שורה בלי מידע.

הבדיקות מרנדרות קטע מתוך קובץ התבנית **האמיתי** ולא מהעתקה, כדי שלא ייווצר
מצב שהבדיקה עוברת על טקסט שכבר לא נשלח לדפדפן.
"""

import io
import re
from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")

TEMPLATES = Path(__file__).resolve().parents[1] / "webapp" / "templates"

CREATED = "01/01/2020 08:30"
UPDATED = "31/08/2026 14:03"


def _slice(path: Path, start: str, end: str) -> str:
    text = io.open(path, encoding="utf-8").read()
    start_at = text.index(start)
    end_at = text.index(end, start_at) + len(end)
    return text[start_at:end_at]


def _render(fragment: str, created_at: str, updated_at: str) -> str:
    template = jinja2.Environment().from_string(fragment)
    return template.render(file={"created_at": created_at, "updated_at": updated_at})


@pytest.fixture()
def files_card() -> str:
    """שורת התאריכים בכרטיס הקובץ ברשימה."""
    return _slice(
        TEMPLATES / "files.html",
        '<span><i class="fas fa-calendar"></i> נוצר:',
        "</div>",
    )


@pytest.fixture()
def view_meta() -> str:
    """שני תאי המטא-דאטה בעמוד הקובץ."""
    return _slice(
        TEMPLATES / "view_file.html",
        '<i class="fas fa-calendar-plus"></i> נוצר',
        '{{ file.updated_at }}</div>',
    )


def test_files_card_hides_updated_when_it_repeats_created(files_card):
    rendered = _render(files_card, CREATED, CREATED)
    assert "נוצר" in rendered
    assert "עודכן" not in rendered


def test_files_card_shows_updated_after_a_real_edit(files_card):
    rendered = _render(files_card, CREATED, UPDATED)
    assert "עודכן" in rendered
    assert UPDATED in rendered
    assert CREATED in rendered


def test_view_meta_hides_updated_but_keeps_it_in_the_dom(view_meta):
    """מוסתר, לא מוסר — עדכון AJAX עתידי צריך למצוא את האלמנט."""
    rendered = _render(view_meta, CREATED, CREATED)
    assert "hidden" in rendered
    assert "metaUpdatedItem" in rendered
    assert "metaUpdatedValue" in rendered


def test_view_meta_shows_updated_after_a_real_edit(view_meta):
    rendered = _render(view_meta, CREATED, UPDATED)
    assert "hidden" not in rendered
    assert UPDATED in rendered


# --- שומר על החלטה שנמדדה בדפדפן ---------------------------------------------
#
# ‏`global_search.css` מגדיר `.meta-item{display:flex}` על כל העמוד, ו-base.html
# טוען אותו בכל תבנית. כלל של המחבר גובר על ברירת המחדל של הדפדפן
# ל-`[hidden]`, ולכן בלי כלל נגדי התכונה `hidden` אינה מסתירה כלום.
# נמדד בכרומיום לפני התיקון: hidden=True אבל display=flex ותיבה של 283x56.
#
# Playwright אינו בתלויות הפרויקט, ולכן זו אינה מדידה חוזרת אלא שומר: הוא
# נופל אם מישהו יסיר את הכלל בזמן שהוא עדיין נחוץ.

STYLESHEETS_LOADED_ON_EVERY_PAGE = [
    Path(__file__).resolve().parents[1] / "webapp" / "static" / "css" / "global_search.css",
]


def _sets_display_on_meta_item(css: str) -> bool:
    for block in re.finditer(r"\.meta-item\s*(?:,[^{]*)?\{([^}]*)\}", css):
        if re.search(r"(^|;)\s*display\s*:", block.group(1)):
            return True
    return False


def test_hidden_meta_item_still_beats_the_page_wide_display_rule():
    view_file = io.open(TEMPLATES / "view_file.html", encoding="utf-8").read()

    conflicting = [p for p in STYLESHEETS_LOADED_ON_EVERY_PAGE
                   if p.exists() and _sets_display_on_meta_item(io.open(p, encoding="utf-8").read())]
    if not conflicting:
        pytest.skip("אף גיליון סגנונות כלל-עמודי לא קובע display על .meta-item")

    override = re.search(r"\.meta-item\[hidden\]\s*\{([^}]*)\}", view_file)
    assert override, (
        "‏.meta-item[hidden] חסר ב-view_file.html, בעוד "
        f"{[p.name for p in conflicting]} עדיין קובע display על .meta-item — "
        "התכונה hidden לא תסתיר כלום בדפדפן"
    )
    assert re.search(r"display\s*:\s*none", override.group(1)), \
        "‏.meta-item[hidden] קיים אבל אינו קובע display: none"
