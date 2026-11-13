"""כיוון הטקסט בהתראת פוש — נמדד במנוע תצוגה, ולא נקרא מהמחרוזת.

**למה בדפדפן.** סדר התצוגה של טקסט מעורב הוא תוצאה של אלגוריתם ה-bidi (UAX #9), ובדיקת
יחידה על המחרוזת אינה רואה אותו: היא תעבור בשמחה גם על סימנים במקום הלא נכון.
``tests/test_push_text_direction.py`` בודק **מה** הבונים מוציאים; כאן נבדק **איך זה מוצג**.

**מה בדיוק משוחזר כאן.** אנדרואיד קובע את כיוון השורה בהתראה לפי האות החזקה הראשונה, ומדלג
על מה שבתוך בידוד (``TextDirectionHeuristics.FirstStrong`` ב-AOSP), ומסדר את השורה ב-ICU
(``android.icu.text.Bidi`` ב-``AndroidBidi``). ``unicode-bidi: plaintext`` ב-CSS קובע את כיוון
השורה בדיוק לפי אותם כללים — P2 ו-P3 של UAX #9 — ו-Chromium מסדר את השורה ב-ICU. זה **קירוב**
של מגש ההתראות ולא המגש עצמו: הבדיקה האמיתית היא על מכשיר, אחרי הפריסה.

**ריצות הבקרה.** אותן מדידות רצות גם על הטקסט **בלי** הסימנים (הצורה שלפני התיקון), ועל
שם קובץ שבודד ב-FSI במקום RLI — ושם הן דורשות שהסדר כן יישבר. בלי זה, שינוי בדפדפן או בעמוד
היה יכול להפוך את הבדיקה לחסרת משמעות בשקט.

מדולג כשאין Chromium. ``chromium_executable`` מגיע מ-``tests/conftest.py``; pytest מוצא אותו לבד.
"""

from __future__ import annotations

import importlib

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")
pytest.importorskip("flask")

from playwright.sync_api import sync_playwright  # noqa: E402

push = importlib.import_module("webapp.push_api")
nt = importlib.import_module("note_threads")

#: כתובים כרצף escape ולא כתו עצמו: bandit ו-ruff מסמנים תו כיווניות בקוד המקור כ-Trojan Source.
RLM = "\u200f"
RLI = "\u2067"
FSI = "\u2068"
PDI = "\u2069"
MARKS = (RLM, RLI, FSI, PDI)

NOTE = "64b7f1d2e3a4b5c6d7e8f901"
THREAD = "64b7f1d2e3a4b5c6d7e8f902"

FB_LEADS_TITLE = "שלב 3/3 — חיבור וואטסאפ לצינור של FB Leads"
HANDOFF_NAME = "Handoff: שרשורי תגובות על פתקים — סשן 2.md"
MARKDOWN_REMINDER = "# `is_latest` בקריאה לפי איידי…"

#: שורה אחת, בלי גלישה, שהכיוון שלה נקבע לפי האות החזקה הראשונה. בלי ``dir`` על המסמך: כשאין
#: אות חזקה בכלל הכיוון נופל לשמאל-לימין, כמו ``FIRSTSTRONG_LTR``.
PAGE = """<!doctype html>
<html lang="he"><head><meta charset="utf-8">
<style>
  body { margin: 0; font: 16px sans-serif; }
  #line { unicode-bidi: plaintext; white-space: nowrap; width: 1600px; }
</style></head>
<body><div id="line"></div></body></html>
"""

#: הקצה השמאלי והימני שבו הדפדפן צייר בפועל כל תת-מחרוזת, ובמפתח ``__line`` — השורה כולה
#: והמכל שלה, כדי לדעת לאיזה צד השורה נצמדה (``text-align: start``): זה כיוון השורה עצמה.
MEASURE_JS = """
([text, subs]) => {
  const el = document.getElementById('line');
  el.textContent = text;
  const node = el.firstChild;
  const out = {};
  const whole = document.createRange();
  whole.selectNodeContents(el);
  const lineBox = whole.getBoundingClientRect();
  const boxOf = el.getBoundingClientRect();
  out.__line = { left: lineBox.left, right: lineBox.right, boxLeft: boxOf.left, boxRight: boxOf.right };
  for (const sub of subs) {
    const i = text.indexOf(sub);
    if (i < 0) { out[sub] = null; continue; }
    const range = document.createRange();
    range.setStart(node, i);
    range.setEnd(node, i + sub.length);
    const box = range.getBoundingClientRect();
    out[sub] = { left: box.left, right: box.right };
  }
  return out;
}
"""


def _comment_title(*, title: str, client: str = "claude-code") -> str:
    author = nt.agent_author(client=client, working_on="תיקון כיוון קוד")
    event = {"note_id": NOTE, "thread_id": THREAD, "comment_id": "c1"}
    comments = {(THREAD, "c1"): {"note_id": NOTE, "author": author, "body": "x"}}
    payload = push._build_note_comment_payload(event, note_titles={NOTE: title}, comments=comments)
    assert payload is not None
    return payload["notification"]["title"]


class _OneNote:
    def find_one(self, filt, projection=None, *args, **kwargs):
        return {"_id": filt.get("_id"), "user_id": 1, "title": MARKDOWN_REMINDER}


class _OneNoteDB:
    sticky_notes = _OneNote()


def _strip_marks(text: str) -> str:
    """הטקסט בצורה שלפני התיקון — בלי אף סימן כיוון."""
    return "".join(ch for ch in text if ch not in MARKS)


#: כל מקרה: הטקסט שהבונה האמיתי מוציא, ותתי-המחרוזות שמודדים בו.
TEXTS = {
    "fb_leads_title": (_comment_title(title=FB_LEADS_TITLE), ("CC", "הגיב", "של", "FB", "Leads")),
    "latin_title": (_comment_title(title="Fix the build!", client="Gemini"), ("Gemini", "הגיב", "Fix", "build", "!")),
    "handoff_body": (
        push._build_file_saved_payload({"file_name": HANDOFF_NAME, "file_id": "f1"})["notification"]["body"],
        ("Handoff", "שרשורי", "סשן", "md"),
    ),
    "markdown_reminder": (
        push._build_reminder_payload(_OneNoteDB(), {"note_id": NOTE, "user_id": 1})["notification"]["body"],
        ("#", "is_latest", "בקריאה"),
    ),
}


@pytest.fixture(scope="module")
def measure(chromium_executable):
    """פותח דפדפן אחד למודול, ומחזיר פונקציה שמודדת טקסט.

    ``chromium_executable`` הוא ``None`` כשאין דפדפן תחת ``PLAYWRIGHT_BROWSERS_PATH``, ו-``None``
    פירושו "תן ל-Playwright לחפש בעצמו" ולא "אין דפדפן". מדלגים רק אם ההשקה עצמה נכשלת.
    """
    with sync_playwright() as p:
        try:
            browser = (
                p.chromium.launch(executable_path=chromium_executable)
                if chromium_executable
                else p.chromium.launch()
            )
        except Exception as exc:  # noqa: BLE001 — כל כשל השקה פירושו אין דפדפן
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            page = browser.new_page()
            page.set_content(PAGE)

            def _measure(text: str, subs: tuple[str, ...]) -> dict:
                boxes = page.evaluate(MEASURE_JS, [text, list(subs)])
                for sub in subs:
                    assert boxes[sub] is not None, f"{sub!r} לא נמצא בטקסט"
                return boxes

            yield _measure
        finally:
            browser.close()


def _right_of(boxes: dict, a: str, b: str) -> bool:
    """``a`` צויר כולו מימין ל-``b`` — כלומר בקריאה מימין לשמאל, ``a`` בא קודם."""
    return boxes[a]["left"] >= boxes[b]["right"] - 0.5


def _line_is_rtl(boxes: dict) -> bool:
    """השורה נצמדה לקצה הימני של המכל — כלומר כיוון השורה עצמה מימין לשמאל.

    סדר המילים לבדו אינו מספיק: גוף שכולו בידוד RLI מסודר נכון מבפנים גם בלי RLM, כי כלל P2
    מדלג על מה שבתוך בידוד — אבל אז אין בשורה אות חזקה, והכיוון שלה נופל לברירת המחדל.
    """
    line = boxes["__line"]
    return abs(line["right"] - line["boxRight"]) < 1 and line["left"] - line["boxLeft"] > 1


# -- הטקסט שהבונים מוציאים -------------------------------------------------------------


def test_the_author_comes_first_and_the_second_half_is_not_reversed(measure):
    """צילום המסך: ``CC`` בתחילת השורה מימין, ו-"לצינור של FB Leads" נקרא בסדר."""
    text, subs = TEXTS["fb_leads_title"]
    boxes = measure(text, subs)
    assert _line_is_rtl(boxes), boxes["__line"]
    assert _right_of(boxes, "CC", "הגיב"), boxes
    assert _right_of(boxes, "של", "FB"), boxes
    assert _right_of(boxes, "Leads", "FB"), "FB Leads עצמו נקרא משמאל לימין"


def test_an_english_note_title_keeps_its_punctuation_inside_its_isolate(measure):
    """שם פתק באנגלית שמסתיים ב-"!": הסימן נשאר אחרי ``build``, ולא קופץ לפני ``Fix``."""
    text, subs = TEXTS["latin_title"]
    boxes = measure(text, subs)
    assert _line_is_rtl(boxes), boxes["__line"]
    assert _right_of(boxes, "Gemini", "הגיב"), boxes
    assert _right_of(boxes, "!", "build"), boxes


def test_a_file_name_that_starts_in_english_reads_right_to_left(measure):
    """``Handoff:`` בקצה הימני ו-``.md`` בקצה השמאלי — ולא צמוד ל"שרשורי"."""
    text, subs = TEXTS["handoff_body"]
    boxes = measure(text, subs)
    assert _line_is_rtl(boxes), boxes["__line"]
    assert _right_of(boxes, "Handoff", "שרשורי"), boxes
    assert _right_of(boxes, "סשן", "md"), boxes


def test_a_reminder_that_starts_with_a_markdown_heading_reads_right_to_left(measure):
    """הסולמית בתחילת השורה מימין, והמילה באנגלית לפני העברית שאחריה."""
    text, subs = TEXTS["markdown_reminder"]
    boxes = measure(text, subs)
    assert _line_is_rtl(boxes), boxes["__line"]
    assert _right_of(boxes, "#", "is_latest"), boxes
    assert _right_of(boxes, "is_latest", "בקריאה"), boxes


# -- ריצות בקרה: המדידה יודעת להיכשל ----------------------------------------------------


def test_control_without_the_marks_the_screenshot_bug_is_measured(measure):
    """הטקסט בלי הסימנים — כמו לפני התיקון — באמת נשבר. אחרת הבדיקות שמעל אינן מוכיחות דבר."""
    text, subs = TEXTS["fb_leads_title"]
    boxes = measure(_strip_marks(text), subs)
    assert not _line_is_rtl(boxes), boxes["__line"]
    assert _right_of(boxes, "הגיב", "CC"), boxes
    assert _right_of(boxes, "FB", "של"), boxes

    text, subs = TEXTS["handoff_body"]
    boxes = measure(_strip_marks(text), subs)
    assert not _line_is_rtl(boxes), boxes["__line"]
    assert _right_of(boxes, "שרשורי", "Handoff"), boxes
    assert _right_of(boxes, "md", "סשן"), boxes

    text, subs = TEXTS["markdown_reminder"]
    boxes = measure(_strip_marks(text), subs)
    assert _right_of(boxes, "is_latest", "#"), boxes


def test_control_an_fsi_around_the_file_name_keeps_it_left_to_right(measure):
    """למה RLI ולא FSI: ב-FSI הכיוון בתוך הבידוד נקבע לפי ה-H, והשם נשאר משמאל לימין."""
    text, subs = TEXTS["handoff_body"]
    assert RLI in text
    boxes = measure(text.replace(RLI, FSI), subs)
    assert _right_of(boxes, "שרשורי", "Handoff"), boxes


def test_control_a_body_isolate_without_the_rlm_leaves_the_line_left_to_right(measure):
    """למה RLM גם לפני גוף מבודד: בלעדיו אין בשורה אות חזקה מחוץ לבידוד, והשורה נצמדת לשמאל."""
    text, subs = TEXTS["handoff_body"]
    assert text.startswith(RLM)
    boxes = measure(text[len(RLM):], subs)
    assert not _line_is_rtl(boxes), boxes["__line"]


def test_control_without_the_isolate_the_punctuation_jumps(measure):
    """למה מבודדים גם שם באנגלית: עם RLM בלבד, ה-"!" של ``Fix the build!`` קופץ לפני ``Fix``."""
    text, subs = TEXTS["latin_title"]
    rlm_only = RLM + _strip_marks(text)
    boxes = measure(rlm_only, subs)
    assert _right_of(boxes, "Fix", "!"), boxes
