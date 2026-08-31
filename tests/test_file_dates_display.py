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
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId

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


def _render(fragment: str, *, was_edited: bool, updated_at: str = UPDATED) -> str:
    """‏``was_edited`` נקבע בשרת מהתאריכים הגולמיים — ראו file_dates.file_was_edited.

    התבנית לא משווה תאריכים בעצמה: השוואה בין המחרוזות המפורמטות הייתה
    מסתירה עריכה שקרתה באותה דקה שבה הקובץ נוצר, וגם קושרת החלטה סמנטית
    לפורמט התצוגה.
    """
    template = jinja2.Environment().from_string(fragment)
    return template.render(
        file={"created_at": CREATED, "updated_at": updated_at, "was_edited": was_edited}
    )


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


def test_files_card_hides_updated_when_the_file_was_never_edited(files_card):
    rendered = _render(files_card, was_edited=False, updated_at=CREATED)
    assert "נוצר" in rendered
    assert "עודכן" not in rendered


def test_files_card_shows_updated_after_a_real_edit(files_card):
    rendered = _render(files_card, was_edited=True)
    assert "עודכן" in rendered
    assert UPDATED in rendered
    assert CREATED in rendered


def test_files_card_shows_an_edit_made_within_the_same_minute(files_card):
    """שתי המחרוזות זהות, אבל השרת קבע שהייתה עריכה — והשורה חייבת להופיע.

    זה בדיוק המקרה שהשוואת המחרוזות בתבנית פספסה.
    """
    rendered = _render(files_card, was_edited=True, updated_at=CREATED)
    assert "עודכן" in rendered


def test_view_meta_hides_updated_but_keeps_it_in_the_dom(view_meta):
    """מוסתר, לא מוסר — עדכון AJAX עתידי צריך למצוא את האלמנט."""
    rendered = _render(view_meta, was_edited=False, updated_at=CREATED)
    assert "hidden" in rendered
    assert "metaUpdatedItem" in rendered
    assert "metaUpdatedValue" in rendered


def test_view_meta_shows_updated_after_a_real_edit(view_meta):
    rendered = _render(view_meta, was_edited=True)
    assert "hidden" not in rendered
    assert UPDATED in rendered


def test_view_meta_shows_an_edit_made_within_the_same_minute(view_meta):
    rendered = _render(view_meta, was_edited=True, updated_at=CREATED)
    assert "hidden" not in rendered


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


# --- הדגל מגיע מהראוט האמיתי, לא רק מהתבנית -----------------------------------
#
# הבדיקות שלמעלה מוכיחות שהתבנית מגיבה נכון לדגל. הן לא מוכיחות שהראוט
# באמת מספק אותו — נקודת בנייה שנשכחה הייתה מייצרת Undefined, שהוא falsy,
# והשורה הייתה נעלמת בלי שאף בדיקה תתפוס.

FILE_OID = ObjectId("0123456789abcdef01234567")
USER_ID = 4242
CREATED_RAW = datetime(2026, 8, 31, 11, 3, 10, tzinfo=timezone.utc)
SAME_MINUTE_EDIT = datetime(2026, 8, 31, 11, 3, 50, tzinfo=timezone.utc)


def _doc(updated_at):
    return {
        "_id": FILE_OID,
        "user_id": USER_ID,
        "file_name": "demo.py",
        "programming_language": "python",
        "code": "print('hi')\n",
        "description": "",
        "tags": [],
        "version": 1,
        "is_active": True,
        "created_at": CREATED_RAW,
        "updated_at": updated_at,
    }


def _view_file_html(monkeypatch, updated_at):
    from webapp import app as webapp_app

    doc = _doc(updated_at)
    monkeypatch.setattr(webapp_app, "get_db", lambda: object())
    monkeypatch.setattr(
        webapp_app,
        "_get_user_any_file_by_id",
        lambda db_ref, user_id, file_id: (doc, "regular"),
    )
    client = webapp_app.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "Test"}
    return client.get(f"/file/{FILE_OID}").get_data(as_text=True)


def _updated_cell(html: str) -> str:
    start = html.index('id="metaUpdatedItem"')
    return html[start - 40: start + 60]


def test_view_file_route_hides_updated_for_a_file_never_edited(monkeypatch):
    cell = _updated_cell(_view_file_html(monkeypatch, CREATED_RAW))
    assert "hidden" in cell, cell


def test_view_file_route_shows_an_edit_made_within_the_same_minute(monkeypatch):
    """שתי המחרוזות המוצגות זהות — 31/08/2026 14:03 — והשורה חייבת להופיע."""
    html = _view_file_html(monkeypatch, SAME_MINUTE_EDIT)
    assert "14:03" in html, "ציפינו ששתי המחרוזות יהיו זהות ברזולוציית דקה"
    cell = _updated_cell(html)
    assert "hidden" not in cell, cell
