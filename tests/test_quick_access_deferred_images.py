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


# העוגנים. ה-``{`` בסוף ``OPEN_BRANCH_HEAD`` אינו קישוט — הוא הנקודה
# שממנה מתחילה התאמת הסוגריים.
TOGGLE_FN = "function toggleQuickAccess("
LOADER_FN = "function loadDeferredImages("
OPEN_BRANCH_HEAD = "if (dropdown.classList.contains('active')) {"
CALL = "loadDeferredImages(dropdown);"


def _block_after(html: str, anchor: str, start: int = 0) -> tuple[int, int]:
    """טווח הבלוק ``{...}`` שאחרי ``anchor``, כולל שני הסוגריים.

    **התאמת סוגריים ולא חיתוך טקסט.** חיתוך לפי מחרוזת — ``split`` על
    הזחה, או הצמדה לגוף מדויק — קושר את הבדיקה לעימוד ולנוסח הערות
    במקום לאינווריאנטה. נמדד: ריווד ההערה בענף הפתיחה, בלי לגעת בקריאה,
    הפיל ניסוח קודם של הבדיקה. הבלוקים כאן מכילים פונקציה מקוננת
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
    """טווח ענף הפתיחה — **מעוגן בתוך ``toggleQuickAccess``**.

    העיגון אינו קישוט. חיפוש גלובלי של ``OPEN_BRANCH_HEAD`` היה יכול
    לתפוס ענף של תפריט אחר שנוסח באותה צורה; ``toggleFunModeMenu`` באותו
    קובץ כבר מחזיקה משתנה בשם ``dropdown``. היום יש מופע אחד בקובץ, אז
    זו סכנה רדומה ולא באג חי — אבל כל מי שקורא כאן את הענף חייב לעבור
    דרך הפונקציה הזו, כדי שלא ייווצר שוב עוגן שני שאינו מוגבל.
    """
    fn = html.find(TOGGLE_FN)
    assert fn != -1, "לא נמצאה ``toggleQuickAccess``"
    return _block_after(html, OPEN_BRANCH_HEAD, start=fn)


def test_loader_exists_and_is_called_on_open():
    """מי שמציב את ה-``src``, ומאיפה בדיוק הוא נקרא.

    **על הענף, לא על הפונקציה כולה.** ניסוח ראשון כאן בדק רק שהקריאה
    מופיעה איפשהו ב-``toggleQuickAccess``, וזה חלש מדי: נמדד בדפדפן
    שהעלאתה אל מעל ``const dropdown`` מפילה את הפונקציה כולה על
    ``ReferenceError`` — החלונית לא נפתחת ו-``naturalWidth`` נשאר 0 —
    והבדיקה הישנה עברה.
    """
    html = BASE_HTML.read_text(encoding="utf-8")
    assert LOADER_FN in html, "חסרה הפונקציה ``loadDeferredImages``"
    assert "img[data-src]" in html, "הפונקציה חייבת לסרוק ``img[data-src]``"

    a, b = _open_branch(html)
    assert CALL in html[a:b], (
        f"``{CALL}`` אינה בענף הפתיחה של ``toggleQuickAccess``. שם היא "
        "חייבת לשבת: אחרי ש-``dropdown`` הוגדר, ורק כשהחלונית נפתחת."
    )


def test_loader_is_one_shot():
    """``data-src`` מוסר לפני ההצבה, ולכן פתיחה חוזרת אינה מציבה שוב."""
    html = BASE_HTML.read_text(encoding="utf-8")
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


def test_open_branch_guard_can_actually_fail(tmp_path, monkeypatch):
    """מוטציה אחת, והיא המבחינה: הקריאה יוצאת מהענף ונשארת בקובץ.

    זה המקרה היחיד שמפריד בין הטענה הנכונה לבין ``CALL in html`` —
    הניסוח החלש שהיה כאן בסבב הראשון ועבר על מיקום שגוי. מחיקת הקריאה
    לגמרי לא הייתה מפרידה, כי גם הניסוח החלש היה נופל עליה.

    **מוטציה אחת ולא שתיים.** נמדד שגם "הקריאה מעל ``const dropdown``"
    (שבור לגמרי בדפדפן) וגם "הקריאה מחוץ ל-``if``" (בלתי מזיק) נופלות על
    אותה טענה בדיוק. שנייה מהן היא חזרה, לא כיסוי.

    הכול נגזר מ-``_open_branch`` המעוגן — כולל בניית המוטציה — כדי שלא
    ייווצר עוגן שני עם היקף אחר.
    """
    html = BASE_HTML.read_text(encoding="utf-8")

    a, b = _open_branch(html)
    without = html[:a] + html[a:b].replace(CALL, "", 1) + html[b:]
    branch_at, _ = _open_branch(without)
    line_start = without.rfind("\n", 0, branch_at) + 1
    mutated = without[:line_start] + "            " + CALL + "\n" + without[line_start:]

    # תנאי מקדים, לא בדיקה נפרדת: מוטציה שלא הוחלה מרוקנת את מה שאחריה.
    assert CALL in mutated, "המוטציה מחקה את הקריאה במקום להזיז אותה"
    ma, mb = _open_branch(mutated)
    assert CALL not in mutated[ma:mb], "המוטציה לא הוציאה את הקריאה מהענף"

    fake = tmp_path / "base.html"
    fake.write_text(mutated, encoding="utf-8")
    monkeypatch.setattr(f"{__name__}.BASE_HTML", fake)
    with pytest.raises(AssertionError):
        test_loader_exists_and_is_called_on_open()
