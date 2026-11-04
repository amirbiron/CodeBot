"""``note_label`` — השם שבו פתק מוצג בהתראת התזכורת ובחלונית הפעמון.

שם הפתק כשיש לו; בלעדיו — תחילת התוכן, כמו שהיה לפני שלפתקים היו שמות; ובלי תוכן — טקסט
העוגן. אותה פונקציה מזינה את שני המקומות (``push_api._reminder_label`` ו-``reminders_list``).
"""
from __future__ import annotations

import pytest

from sticky_notes_target import (
    MAX_NOTE_TITLE,
    NOTE_LABEL_FIELDS,
    NOTE_LABEL_MAX_CHARS,
    NOTE_LABEL_WORDS,
    note_label,
)

#: יותר מילים ממה שמוצג — כך שאפשר לראות גם את החיתוך וגם את "…".
LONG_CONTENT = "אחת שתיים שלוש ארבע חמש שש שבע שמונה"


def test_the_name_wins_over_the_content():
    assert note_label({"title": "שם הפתק", "content": LONG_CONTENT}) == "שם הפתק"


def test_without_a_name_the_start_of_the_content_is_shown():
    words = LONG_CONTENT.split()
    assert note_label({"content": LONG_CONTENT}) == " ".join(words[:NOTE_LABEL_WORDS]) + "…"


def test_a_short_content_is_shown_whole_without_an_ellipsis():
    assert note_label({"content": "שלום עולם"}) == "שלום עולם"


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
    """כמו בשני העותקים שהפונקציה החליפה (``content or anchor_text``): רווחים אינם תוכן ריק."""
    assert note_label({"content": "   \n ", "anchor_text": "התקנה"}) == ""


def test_nothing_to_show_is_an_empty_string():
    assert note_label({}) == ""


def test_one_long_word_is_cut_to_the_name_ceiling():
    """"מילה" היא כל רצף בלי רווח — קישור, או מחרוזת ארוכה. בלי תקרה היא הייתה מגיעה שלמה
    לגוף התראת הפוש. החיתוך בתווים, ולכן אות עברית אינה נחתכת באמצע."""
    label = note_label({"content": "א" * (NOTE_LABEL_MAX_CHARS * 3)})
    assert label == "א" * NOTE_LABEL_MAX_CHARS + "…"


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
