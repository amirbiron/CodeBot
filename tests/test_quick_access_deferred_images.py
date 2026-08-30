"""שומר על דחיית טעינת התמונות בחלונית קיצורי הדרך.

אייקון דפדפן הקוד הוא 6MB, והוא ירד ב**כל טעינת עמוד** בוובאפ — לכל
אדמין, בכל דף. הסתרת החלונית לא מנעה את זה: היא מוסתרת ב-``opacity``
ו-``visibility``, ואפילו ``display: none`` לא מונע הורדה של ``<img src>``.
נמדד בכרומיום: בקשה אחת בטעינת העמוד, ``content-length`` 5.90MB,
ו-``img.complete === true`` עוד לפני שנגעו בכפתור.

הפתרון: ``data-src`` במקום ``src``, ו-``loadDeferredImages`` שמציב את
ה-``src`` בפתיחה הראשונה של החלונית. ``<img>`` בלי ``src`` אינו שולח בקשה.

הבדיקה טקסטואלית — היא שומרת על ההחלטה, לא מודדת אותה מחדש. אותה גישה
כמו ``test_note_boards_api`` שקורא את קובץ ה-JS כטקסט.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

BASE_HTML = Path(__file__).resolve().parent.parent / "webapp/templates/base.html"

# ה-``<img>`` היחיד בחלונית קיצורי הדרך. אם ייווספו עוד — ``loadDeferredImages``
# גנרי על ``img[data-src]`` ויטפל גם בהם, והבדיקה כאן תמשיך לתפוס ``src`` נוקשה.
DEFERRED_ICON = "icons/repo-browser-icon.png"

_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)


def _html_without_jinja_comments() -> str:
    """ההערה בתבנית מזכירה את ``src`` בכוונה, כדי להסביר למה הוא לא שם.

    בלי ההסרה הזו הבדיקה הייתה נכשלת על התיעוד של עצמה — בדיוק המלכודת
    שכבר נפלתי בה בשומר ה-CSS.
    """
    return _JINJA_COMMENT.sub("", BASE_HTML.read_text(encoding="utf-8"))


def _img_tags_with(fragment: str, html: str):
    return re.findall(r"<img\b[^>]*" + re.escape(fragment) + r"[^>]*>", html)


def test_base_html_exists():
    assert BASE_HTML.is_file(), f"לא נמצא {BASE_HTML}"


def test_heavy_icon_is_deferred_not_eager():
    """הקובץ הכבד חייב להגיע כ-``data-src``, ולא כ-``src``."""
    html = _html_without_jinja_comments()
    tags = _img_tags_with(DEFERRED_ICON, html)
    assert tags, f"לא נמצא <img> שמפנה ל-{DEFERRED_ICON} — האם הנתיב השתנה?"
    # ``(?<![-\w])`` ולא ``\b``: מקף הוא גבול מילה, ולכן ``\bsrc`` תופס גם
    # את ``data-src`` — כלומר הבדיקה הייתה נכשלת דווקא על התיקון.
    eager = [t for t in tags if re.search(r"(?<![-\w])src\s*=", t)]
    assert not eager, (
        f"``{DEFERRED_ICON}`` הוא 6MB. עם ``src`` הוא יורד בכל טעינת עמוד "
        f"בוובאפ, גם כשהחלונית סגורה — הסתרה ב-CSS אינה מונעת הורדה. "
        f"השתמשו ב-``data-src``. התגיות שנמצאו: {eager}"
    )
    assert any("data-src=" in t for t in tags), "חסר ``data-src`` על התגית"


# ה-``{`` בסוף אינו קישוט: הוא העוגן שממנו מתחילה התאמת הסוגריים.
OPEN_BRANCH_HEAD = "if (dropdown.classList.contains('active')) {"
CALL = "loadDeferredImages(dropdown);"
TOGGLE_FN = "function toggleQuickAccess("
LOADER_FN = "function loadDeferredImages("

# שורה שכל תוכנה הוא הקריאה — הזחה חופשית, כי הזחה אינה האינווריאנטה.
_CALL_LINE = re.compile(r"^[ \t]*" + re.escape(CALL) + r"[ \t]*\r?\n", re.M)


def _block_after(html: str, anchor: str, start: int = 0) -> tuple[int, int]:
    """טווח הבלוק ``{...}`` שאחרי ``anchor``, כולל שני הסוגריים.

    **התאמת סוגריים ולא חיתוך טקסט.** כל ניסיון לחתוך לפי מחרוזת —
    ``split`` על ``"\n        function "``, או הצמדה לגוף מדויק —
    קושר את הבדיקה להזחה ולנוסח הערות, ואז שינוי תמים בתבנית מפיל
    אותה עם הודעה מבלבלת. נמדד: ריווד ההערה בענף הפתיחה, בלי לגעת
    בקריאה, הפיל את הבדיקה. הבלוקים כאן מכילים פונקציות מקוננות
    (``closer``), ולכן חיפוש נאיבי של ``}`` היה מחזיר בלוק חלקי.
    """
    i = html.find(anchor, start)
    assert i != -1, f"לא נמצא בתבנית: {anchor}"
    open_at = html.index("{", i + len(anchor) - 1)
    depth = 0
    for j in range(open_at, len(html)):
        if html[j] == "{":
            depth += 1
        elif html[j] == "}":
            depth -= 1
            if depth == 0:
                return open_at, j + 1
    raise AssertionError(f"הבלוק שאחרי {anchor} אינו נסגר")


def _open_branch(html: str) -> tuple[int, int]:
    """טווח ענף הפתיחה, מחופש בתוך ``toggleQuickAccess`` בלבד."""
    fn = html.find(TOGGLE_FN)
    assert fn != -1, "לא נמצאה ``toggleQuickAccess``"
    return _block_after(html, OPEN_BRANCH_HEAD, start=fn)


def test_loader_exists_and_is_called_on_open():
    """מי שמציב את ה-``src``, ומאיפה בדיוק הוא נקרא.

    **הבדיקה על הענף, לא על הפונקציה כולה.** ניסוח קודם כאן בדק רק
    ש-``loadDeferredImages(dropdown)`` מופיע איפשהו ב-``toggleQuickAccess``,
    וזה חלש מדי: נמדד בדפדפן שהעלאת הקריאה אל מעל ``const dropdown``
    מפילה את הפונקציה כולה על ``ReferenceError`` — החלונית לא נפתחת
    (``dropdownActive: false``) והאייקון לא נטען כלל — והבדיקה הישנה עברה.

    (העברה מתונה יותר, אל מחוץ ל-``if`` אבל אחרי ההגדרה, נמדדה כבלתי
    מזיקה: הלחיצה הראשונה תמיד פותחת, ולכן הטעינה קורית בכל מקרה. הבדיקה
    כאן פוסלת גם אותה — בכוונה, כי המיקום בענף הוא מה שההערה בקוד
    מצהירה, וקוד שסותר את ההערה שלו הוא ממצא בפני עצמו.)
    """
    html = BASE_HTML.read_text(encoding="utf-8")
    assert "function loadDeferredImages(" in html, "חסרה הפונקציה ``loadDeferredImages``"
    assert "img[data-src]" in html, "הפונקציה חייבת לסרוק ``img[data-src]``"

    a, b = _open_branch(html)
    assert CALL in html[a:b], (
        "``loadDeferredImages(dropdown)`` אינה בענף הפתיחה של "
        "``toggleQuickAccess``. שם היא חייבת לשבת: אחרי ש-``dropdown`` "
        "הוגדר, ורק כשהחלונית נפתחת."
    )


def test_loader_is_one_shot():
    """``data-src`` מוסר לפני ההצבה, ולכן פתיחה חוזרת אינה מציבה שוב."""
    html = BASE_HTML.read_text(encoding="utf-8")
    # ``split`` על ``"\\n        function "`` היה תלוי בהזחה של הפונקציה
    # הבאה בקובץ — קשר שרירותי בין הבדיקה לעימוד. התאמת סוגריים במקום.
    a, b = _block_after(html, LOADER_FN)
    fn = html[a:b]
    remove_at = fn.find("removeAttribute('data-src')")
    assign_at = fn.find("img.src = src")
    assert remove_at != -1, "חסר ``removeAttribute('data-src')``"
    assert assign_at != -1, "חסרה ההצבה ``img.src = src``"
    assert remove_at < assign_at, "ההסרה חייבת לקדום להצבה, אחרת הבדיקה החד-פעמית מיותרת"


@pytest.mark.parametrize(
    "bad_html",
    [
        # הצורה שהייתה בקוד לפני התיקון
        '<img src="{{ url_for(\'static\', filename=\'icons/repo-browser-icon.png\') }}" alt="">',
        # ניסוח שמחזיק גם data-src וגם src — נראה תקין, ומוריד בכל זאת
        '<img data-src="x" src="{{ url_for(\'static\', filename=\'icons/repo-browser-icon.png\') }}">',
    ],
)
def test_the_guard_can_actually_fail(bad_html, tmp_path, monkeypatch):
    """בדיקה שלא מסוגלת להיכשל אינה בדיקה."""
    fake = tmp_path / "base.html"
    fake.write_text(BASE_HTML.read_text(encoding="utf-8") + "\n" + bad_html, encoding="utf-8")
    monkeypatch.setattr(f"{__name__}.BASE_HTML", fake)
    with pytest.raises(AssertionError):
        test_heavy_icon_is_deferred_not_eager()


# ---- מוטציות ----
#
# **המוטציות נבנות מבנית, לא מהצמדת טקסט.** ניסוח קודם כאן החזיק את הגוף
# המדויק של ענף הפתיחה כמחרוזת קבועה — כולל הזחה ונוסח ההערה בעברית —
# ואימת ``count == 1``. נמדד: ריווד ההערה בתבנית, בלי לגעת בקריאה, הפיל
# את הבדיקה עם ההודעה "עדכנו את המוטציה", בעוד האינווריאנטה שלמה. זו
# בדיוק אותה טעות מהכיוון ההפוך: קודם בדיקה חלשה מדי, אחר כך שבירה מדי.
#
# מה שנשאר קשור: שם הקריאה, כותרת הענף, ושמות שתי הפונקציות. אלה
# האינווריאנטה עצמה — אם הם משתנים, הבדיקה **צריכה** ליפול.

def _strip_call_from_open_branch(html: str) -> str:
    """מסיר את שורת הקריאה מענף הפתיחה, ומחזיר את ה-HTML בלעדיה."""
    a, b = _open_branch(html)
    stripped, n = _CALL_LINE.subn("", html[a:b], count=1)
    assert n == 1, (
        f"``{CALL}`` אינה בענף הפתיחה, ולכן אין מה להזיז. "
        "אם היא הועברה בכוונה — זו בדיוק הרגרסיה שהבדיקה הזו שומרת עליה."
    )
    return html[:a] + stripped + html[b:]


def _call_above_dropdown_declaration(html: str) -> str:
    """מוטציה: הקריאה בראש הפונקציה, לפני ש-``dropdown`` הוגדר.

    נמדד בדפדפן: ``ReferenceError`` מפיל את ``toggleQuickAccess`` כולה —
    ``dropdownActive: false``, ``naturalWidth: 0``, ו-``data-src`` נשאר
    על התגית. 5/8 בהארנס. שבור לגמרי.
    """
    html = _strip_call_from_open_branch(html)
    open_at, _ = _block_after(html, TOGGLE_FN)
    return html[: open_at + 1] + "\n            " + CALL + html[open_at + 1 :]


def _call_outside_open_branch(html: str) -> str:
    """מוטציה: הקריאה אחרי ההגדרה, אבל מחוץ ל-``if``.

    נמדד בדפדפן: 8/8 — בלתי מזיק, כי הלחיצה הראשונה תמיד פותחת. נפסל
    בכל זאת, כי ההערה בקוד מצהירה שהקריאה בענף, וקוד שסותר את ההערה
    שלו הוא ממצא בפני עצמו.
    """
    html = _strip_call_from_open_branch(html)
    head = html.index(OPEN_BRANCH_HEAD)
    line_start = html.rfind("\n", 0, head) + 1
    indent = html[line_start:head]
    return html[:line_start] + indent + CALL + "\n" + html[line_start:]


@pytest.mark.parametrize(
    "label,mutate",
    [
        ("הקריאה מעל ההגדרה של dropdown", _call_above_dropdown_declaration),
        ("הקריאה מחוץ לענף הפתיחה", _call_outside_open_branch),
    ],
)
def test_open_branch_guard_can_actually_fail(label, mutate, tmp_path, monkeypatch):
    """הבדיקה חייבת ליפול על שני המיקומים. הניסוח הראשון עבר את שניהם."""
    mutated = mutate(BASE_HTML.read_text(encoding="utf-8"))
    fake = tmp_path / "base.html"
    fake.write_text(mutated, encoding="utf-8")
    monkeypatch.setattr(f"{__name__}.BASE_HTML", fake)
    with pytest.raises(AssertionError):
        test_loader_exists_and_is_called_on_open()


def test_mutations_are_actually_applied():
    """מוטציה שלא הוחלה הופכת את הבדיקה שמעליה לחסרת ערך.

    כבר קרה לי: מוטציה "עברה" רק מפני שמחרוזת ההחלפה לא תפסה כלל.
    """
    html = BASE_HTML.read_text(encoding="utf-8")
    for mutate in (_call_above_dropdown_declaration, _call_outside_open_branch):
        mutated = mutate(html)
        assert mutated != html, f"{mutate.__name__} לא שינתה דבר"
        assert mutated.count(CALL) == html.count(CALL), (
            f"{mutate.__name__} שינתה את מספר הקריאות — היא אמורה להזיז, לא להוסיף"
        )
        a, b = _open_branch(mutated)
        assert CALL not in mutated[a:b], f"{mutate.__name__} השאירה את הקריאה בענף"
