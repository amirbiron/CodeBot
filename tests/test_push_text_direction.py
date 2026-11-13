"""כיוון הטקסט בהתראת פוש: כותרת וגוף מוצגים מימין לשמאל גם כשהם מתחילים באנגלית.

אנדרואיד קובע את כיוון השורה לפי האות החזקה הראשונה בטקסט, ומדלג על מה שבתוך בידוד. כותרת
כמו ``💬 CC הגיב על "…"`` מתחילה באימוג'י ואחריו ``C``, ולכן הוצגה כולה משמאל לימין. הפתרון
(``push_api._notification_text``): RLM בתחילת כל טקסט שיש בו עברית, וכל שם — כותב, פתק, קובץ —
מבודד. שם עם עברית ב-RLI, ושם בלי עברית ב-FSI.

כאן נבדקות **המחרוזות** שהבונים האמיתיים מוציאים. שהמחרוזות האלה אכן מוצגות בסדר הנכון — זה
משהו שרק מנוע תצוגה רואה, ולכן הוא נבדק בדפדפן: ``tests/test_push_text_direction_browser.py``.

התווים כתובים כאן כרצף escape ולא כתו עצמו: bandit ו-ruff מסמנים תו כיווניות בקוד המקור
כ-Trojan Source.
"""

from __future__ import annotations

import hashlib
import importlib
from datetime import datetime, timezone

import pytest

pytest.importorskip("flask")

push = importlib.import_module("webapp.push_api")
nt = importlib.import_module("note_threads")

RLM = "\u200f"
RLI = "\u2067"
FSI = "\u2068"
PDI = "\u2069"

NOTE = "64b7f1d2e3a4b5c6d7e8f901"
THREAD = "64b7f1d2e3a4b5c6d7e8f902"

#: הכותרת מצילום המסך שבו התקלה נראתה.
FB_LEADS_TITLE = "שלב 3/3 — חיבור וואטסאפ לצינור של FB Leads"
#: שם קובץ אמיתי מהתראה שנבדקה: H קובעת שורה משמאל לימין, ו-``.md`` נצמד ל"שרשורי".
HANDOFF_NAME = "Handoff: שרשורי תגובות על פתקים — סשן 2.md"
#: גוף תזכורת אמיתי: סולמית, גרש הפוך ומילה באנגלית לפני העברית.
MARKDOWN_REMINDER = "# `is_latest` בקריאה לפי איידי…"


def _comment_payload(*, body: str, title: str | None = "כיוון טקסט בבלוקי קוד", client: str = "claude-code"):
    """הבונה האמיתי של ``note_comment``, עם מה ש-``_note_comment_builder`` היה קורא מהמסד."""
    author = nt.agent_author(client=client, working_on="תיקון כיוון קוד")
    event = {"note_id": NOTE, "thread_id": THREAD, "comment_id": "c1"}
    comments = {(THREAD, "c1"): {"note_id": NOTE, "author": author, "body": body}}
    payload = push._build_note_comment_payload(event, note_titles={NOTE: title or ""}, comments=comments)
    assert payload is not None
    for key in ("title", "body"):
        assert payload["notification"][key] == payload["data"][key], key
    return payload["notification"]


def _isolate_depths(text: str) -> list[int]:
    """עומק הבידוד אחרי כל תו — כדי לבדוק שכל בידוד נסגר, ושהמרכאה הסוגרת מחוץ לכולם."""
    depth = 0
    depths = []
    for ch in text:
        if ch in (RLI, FSI, "\u2066"):
            depth += 1
        elif ch == PDI and depth:
            depth -= 1
        depths.append(depth)
    return depths


# -- הכותרת ---------------------------------------------------------------------------


def test_the_comment_title_starts_with_rlm_and_isolates_both_names():
    """הכותרת שבצילום המסך: RLM בהתחלה, ``CC`` מבודד ב-FSI ושם הפתק העברי ב-RLI."""
    title = _comment_payload(body="x", title=FB_LEADS_TITLE)["title"]
    assert title == f'{RLM}💬 {FSI}CC{PDI} הגיב על "{RLI}{FB_LEADS_TITLE}{PDI}"'


def test_a_latin_author_and_an_english_note_title_are_isolated_ltr():
    """כותב בשם לטיני ושם פתק באנגלית: שניהם ב-FSI — הם נקראים משמאל לימין בתוך שורה שמימין לשמאל."""
    title = _comment_payload(body="x", title="Fix the build!", client="Gemini")["title"]
    assert title == f'{RLM}💬 {FSI}Gemini{PDI} הגיב על "{FSI}Fix the build!{PDI}"'


def test_a_note_without_a_title_still_gets_the_rlm():
    title = _comment_payload(body="x", title=None)["title"]
    assert title == f"{RLM}💬 {FSI}CC{PDI} הגיב על פתק"


@pytest.mark.parametrize("created, text", [(True, "📄 קובץ חדש נשמר"), (False, "✏️ קובץ עודכן")])
def test_the_file_saved_titles_start_with_rlm(created, text):
    payload = push._build_file_saved_payload({"file_name": "notes.md", "file_id": "f1", "created": created})
    assert payload["notification"]["title"] == RLM + text
    assert payload["data"]["title"] == RLM + text


def test_the_reminder_title_starts_with_rlm():
    payload = push._build_reminder_payload(_NoNotesDB(), {"note_id": "n1", "file_id": "f1"})
    assert payload["notification"]["title"] == RLM + "🔔 יש פתק ממתין"


# -- הגוף -----------------------------------------------------------------------------


def test_a_comment_body_that_starts_in_english_and_has_hebrew_is_rtl():
    body = _comment_payload(body="is_latest הוא שדה שמחושב בקריאה")["body"]
    assert body == f"{RLM}{RLI}is_latest הוא שדה שמחושב בקריאה{PDI}"


def test_a_comment_body_without_hebrew_is_left_as_it_is():
    """טקסט שכולו בלי עברית חוזר כמו שהוא — בלי אף תו נוסף."""
    assert _comment_payload(body="LGTM, merged in 3f2a1c")["body"] == "LGTM, merged in 3f2a1c"


def test_the_marks_are_added_after_the_cut_and_are_not_counted():
    """התקרה נשארת בתווי התוכן: ``_PUSH_COMMENT_PREVIEW_MAX_CHARS`` תווים, "…", ושלושת הסימנים סביבם."""
    cap = push._PUSH_COMMENT_PREVIEW_MAX_CHARS
    body = _comment_payload(body="א" * (cap + 40))["body"]
    assert body == f"{RLM}{RLI}{'א' * cap}…{PDI}"


def test_a_file_name_that_starts_in_english_and_has_hebrew_is_rtl_inside_the_isolate():
    """RLI ולא FSI: ב-FSI הכיוון בתוך הבידוד נקבע לפי ה-H, והשם היה נשאר משמאל לימין."""
    payload = push._build_file_saved_payload({"file_name": HANDOFF_NAME, "file_id": "f1", "created": False})
    assert payload["notification"]["body"] == f"{RLM}{RLI}{HANDOFF_NAME}{PDI}"
    assert payload["data"]["body"] == payload["notification"]["body"]


def test_an_english_file_name_is_left_as_it_is():
    payload = push._build_file_saved_payload({"file_name": "morass-Tech-theme.json", "file_id": "f1", "created": True})
    assert payload["notification"]["body"] == "morass-Tech-theme.json"


def test_the_tag_is_still_derived_from_the_bare_file_name():
    """הסימנים הם תצוגה בלבד: ה-``tag`` שמזהה את הקובץ במגש נגזר מהשם בלעדיהם."""
    payload = push._build_file_saved_payload({"file_name": HANDOFF_NAME, "file_id": "f1", "created": False})
    expected = "mcp-file-" + hashlib.sha256(HANDOFF_NAME.encode("utf-8")).hexdigest()[:16]
    assert payload["notification"]["tag"] == expected


class _NoNotes:
    def find_one(self, *args, **kwargs):
        return None


class _NoNotesDB:
    sticky_notes = _NoNotes()


class _OneNote:
    def __init__(self, title):
        self.title = title

    def find_one(self, filt, projection=None, *args, **kwargs):
        return {"_id": filt.get("_id"), "user_id": 1, "title": self.title}


class _OneNoteDB:
    def __init__(self, title):
        self.sticky_notes = _OneNote(title)


def _reminder_body(title: str) -> str:
    reminder = {"note_id": NOTE, "user_id": 1, "remind_at": datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)}
    payload = push._build_reminder_payload(_OneNoteDB(title), reminder)
    assert payload["notification"]["body"] == payload["data"]["body"]
    return payload["notification"]["body"]


def test_a_reminder_body_that_starts_with_a_markdown_heading_and_code_is_rtl():
    assert _reminder_body(MARKDOWN_REMINDER) == f"{RLM}{RLI}{MARKDOWN_REMINDER}{PDI}"


def test_the_reminder_label_itself_carries_no_marks():
    """הסימנים נוספים רק בבניית ה-payload: :func:`_reminder_label` מחזיר את השם בלעדיהם."""
    reminder = {"note_id": NOTE, "user_id": 1}
    assert push._reminder_label(_OneNoteDB(MARKDOWN_REMINDER), reminder) == MARKDOWN_REMINDER


def test_an_empty_reminder_body_stays_empty():
    payload = push._build_reminder_payload(_NoNotesDB(), {"note_id": "n1", "user_id": 1})
    assert payload["notification"]["body"] == ""


# -- שום בידוד לא נשאר פתוח -------------------------------------------------------------


def test_an_isolate_opened_inside_a_cut_note_title_is_closed_before_the_quote():
    """שם פתק שנושא RLI משלו, ונחתך אחרי הפותח ולפני הסוגר: הבידוד נסגר בתוך השם.

    בלי זה הבידוד הפתוח היה בולע את המרכאה הסוגרת — והיא הייתה זזה עם הטקסט שבתוכו.
    """
    cap = push._PUSH_NOTE_TITLE_MAX_CHARS
    raw_title = "א" * (cap - 5) + RLI + "ב" * 20 + PDI
    title = _comment_payload(body="x", title=raw_title)["title"]
    assert title.endswith('"')
    depths = _isolate_depths(title)
    assert depths[-1] == 0, "נשאר בידוד פתוח בסוף הכותרת"
    assert depths[-2] == 0, "המרכאה הסוגרת בתוך בידוד"


def test_an_orphan_pdi_in_a_name_does_not_close_the_isolate_around_it():
    """PDI בלי פותח בתוך שם היה סוגר את הבידוד של השם עצמו מוקדם מדי, ולכן הוא מוסר."""
    title = _comment_payload(body="x", title="שלום" + PDI + " Leads")["title"]
    assert title == f'{RLM}💬 {FSI}CC{PDI} הגיב על "{RLI}שלום Leads{PDI}"'


def test_every_payload_text_has_balanced_isolates():
    """כל מחרוזת שהבונים מוציאים — בכותרת ובגוף — מסתיימת בעומק אפס."""
    texts = [
        _comment_payload(body="תגובה " + RLI + "פתוחה", title=FB_LEADS_TITLE)["title"],
        _comment_payload(body="תגובה " + RLI + "פתוחה")["body"],
        _reminder_body(MARKDOWN_REMINDER),
        push._build_file_saved_payload({"file_name": HANDOFF_NAME, "file_id": "f1"})["notification"]["body"],
    ]
    for text in texts:
        assert _isolate_depths(text)[-1] == 0, text.encode("unicode_escape")
