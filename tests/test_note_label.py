"""``note_label`` — השם שבו פתק מוצג בהתראת התזכורת, בחלונית הפעמון ובדשבורד.

שם הפתק כשיש לו; בלעדיו — השורה הראשונה של התוכן, עד ``NOTE_LABEL_MAX_CHARS`` תווים; ובלי
תוכן — טקסט העוגן. אותה פונקציה מזינה את כל המקומות (``push_api._reminder_label``,
``reminders_list`` ו-``app._dashboard_note_title``).
"""
from __future__ import annotations

import pytest

from sticky_notes_target import (
    MAX_NOTE_TITLE,
    NOTE_LABEL_FIELDS,
    NOTE_LABEL_MAX_CHARS,
    note_label,
)

#: פתק בלי שם, כמה שורות — כדי לראות שרק הראשונה מוצגת.
CONTENT = "# שורה ראשונה של הפתק\nשורה שנייה\nשלישית"


def test_the_name_wins_over_the_content():
    assert note_label({"title": "שם הפתק", "content": CONTENT}) == "שם הפתק"


def test_without_a_name_the_whole_first_line_is_shown():
    """השורה הראשונה כולה — לא מספר מילים. עד נובמבר 2026 הפוש והפעמון הציגו שש מילים."""
    content = "אחת שתיים שלוש ארבע חמש שש שבע שמונה תשע\nשורה שנייה"
    assert note_label({"content": content}) == "אחת שתיים שלוש ארבע חמש שש שבע שמונה תשע"


def test_the_first_line_is_the_first_one_with_text():
    assert note_label({"content": "\n\n   \n  # כותרת  \nגוף"}) == "# כותרת"


def test_the_first_line_is_one_line_with_single_spaces():
    """כמו שם (``canonical_title_text``): טאבים ורווחים כפולים מתכווצים לרווח אחד."""
    assert note_label({"content": "א\t\tב   ג\nד"}) == "א ב ג"


def test_a_first_line_longer_than_the_ceiling_is_cut_with_an_ellipsis():
    line = "ש" * (NOTE_LABEL_MAX_CHARS + 30)
    assert note_label({"content": line + "\nשורה שנייה"}) == "ש" * NOTE_LABEL_MAX_CHARS + "…"


def test_a_first_line_exactly_at_the_ceiling_is_shown_whole():
    line = "ש" * NOTE_LABEL_MAX_CHARS
    assert note_label({"content": line + "\nשורה שנייה"}) == line


@pytest.mark.parametrize("title", ["", "   ", None, ["רשימה"], 7])
def test_a_title_that_is_not_a_name_falls_back_to_the_content(title):
    """רק מחרוזת עם תוכן היא שם — כמו ``normalize_note_title``, שקובעת מה נשמר כשם."""
    assert note_label({"title": title, "content": "שלום עולם"}) == "שלום עולם"


def test_an_empty_note_shows_the_anchor_text():
    """פתק שנוצר ונשאר ריק (``content: ''``) — הכותרת בקובץ שהוא נצמד אליה, כמו לפני האיחוד."""
    assert note_label({"content": "", "anchor_text": "התקנה"}) == "התקנה"


def test_a_note_with_content_never_shows_the_anchor_text():
    assert note_label({"content": "שלום", "anchor_text": "התקנה"}) == "שלום"


def test_whitespace_only_content_does_not_fall_back_to_the_anchor():
    """כמו בעותקים שהפונקציה החליפה (``content or anchor_text``): רווחים אינם תוכן ריק."""
    assert note_label({"content": "   \n ", "anchor_text": "התקנה"}) == ""


def test_nothing_to_show_is_an_empty_string():
    assert note_label({}) == ""


def test_a_name_longer_than_the_ceiling_is_cut_with_an_ellipsis():
    """שם ארוך מהתקרה מקבל "…" כמו תוכן — ולא נחתך בשקט."""
    title = "ש" * (NOTE_LABEL_MAX_CHARS + 20)
    assert note_label({"title": title, "content": "x"}) == "ש" * NOTE_LABEL_MAX_CHARS + "…"


def test_a_name_exactly_at_the_ceiling_is_shown_whole():
    title = "ש" * NOTE_LABEL_MAX_CHARS
    assert note_label({"title": title}) == title


def test_the_ceiling_is_the_name_ceiling():
    """מה שעומד במקום השם מקבל את הגבול של שם — מספר אחד, לא שניים שמסונכרנים בתקווה."""
    assert NOTE_LABEL_MAX_CHARS == MAX_NOTE_TITLE


def test_a_multiline_name_from_an_old_document_is_one_line():
    assert note_label({"title": "שורה\nשנייה", "content": "x"}) == "שורה שנייה"


def test_the_projection_carries_every_field_the_label_reads():
    """``push_api`` שולף את הפתק עם ``NOTE_LABEL_FIELDS`` בלבד. שדה שהפונקציה קוראת ולא נמצא
    בהיטלה לא היה מגיע מהמסד — והתווית הייתה נופלת לתוכן גם כשלפתק יש שם."""
    note = {"title": "שם", "content": "", "anchor_text": "עוגן"}
    projected = {k: v for k, v in note.items() if k in NOTE_LABEL_FIELDS}
    assert note_label(projected) == note_label(note) == "שם"
    projected = {k: v for k, v in {"content": "", "anchor_text": "עוגן"}.items() if k in NOTE_LABEL_FIELDS}
    assert note_label(projected) == "עוגן"
