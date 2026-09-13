"""אף קובץ פייתון בריפו אינו נושא סדרת escape לא חוקית.

**זה באג תאימות-קדימה, לא קוסמטיקה.** מחרוזת לא-raw שמכילה ``\\ `` או
``\\s`` היא סדרת escape שאינה מוכרת לפייתון. עד 3.11 זו ``DeprecationWarning``,
מ-3.12 זו ``SyntaxWarning``, ובגרסה עתידית זו ``SyntaxError`` — כלומר
הקובץ פשוט לא ייטען. ריצת CI על 3.12 בריפו הזה כבר הדפיסה את האזהרה על
``mcp_server/redaction.py``.

**והמקור הנפוץ כאן הוא תיעוד בעברית עם RST.** ``\\ `` הוא "רווח מוברח"
של RST, שנחוץ כדי לחבר סימון inline לטקסט שצמוד לו — למשל
``**מודול נפרד ולא מתודה ב-**\\ ``Repository```. הכתיבה נכונה, מה שחסר
הוא ה-``r`` שלפני שלושת הגרשיים.

**ולפעמים זה גם משבש את הטקסט עצמו, לא רק מזהיר.** ב-
``tests/test_static_cache_busting.py`` ה-docstring הכיל גם ``\\n`` — וזו
סדרה **חוקית**, כלומר היא הפכה לירידת שורה אמיתית וחתכה משפט באמצע.
המשפט "ששתיהן בולעות ``\\n`` כברירת מחדל" נגמר אחרי המרכאות ההפוכות.

**הבדיקה מסננת לפי ההודעה ולא לפי הקטגוריה, וזאת טעות שכבר נעשתה כאן.**
סריקה ראשונה חיפשה ``SyntaxWarning`` בלבד, וב-3.11 — הגרסה שבה היא רצה
— הקטגוריה היא ``DeprecationWarning``. היא החזירה אפס ופספסה שני קבצים
מתוך שלושה. סריקה שנייה חיפשה ``\\`` צמוד למרכאות הפוכות, ופספסה את
ה-``\\s``. מה שקבוע בין הגרסאות ובין הצורות הוא נוסח ההודעה.
"""

from __future__ import annotations

import warnings
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: תיקיות שאינן קוד של הפרויקט. ``.restore`` הוא גיבוי, והשאר תלויות.
_SKIPPED_DIRECTORIES = frozenset(
    {".restore", "node_modules", "__pycache__", ".git", ".venv", "venv", "_build"}
)


def _python_sources() -> list[Path]:
    """כל קובצי הפייתון של הפרויקט. **רשימה ריקה היא כישלון ולא דילוג.**"""
    found = [
        path
        for path in sorted(_REPO_ROOT.rglob("*.py"))
        if not _SKIPPED_DIRECTORIES.intersection(path.parts)
    ]
    assert found, f"לא נמצא אף קובץ פייתון תחת {_REPO_ROOT}"
    return found


def _invalid_escapes(path: Path) -> list[str]:
    """הודעות ה-escape שהקומפילציה של הקובץ מייצרת.

    ``compile`` ולא ``ast.parse``, כי האזהרה נולדת בשלב שממיר את הליטרל
    לערך — ``ast.parse`` בלבד אינו מגיע לשם בכל הגרסאות.

    כשל תחביר אינו ממצא של הבדיקה הזאת: יש לו מי שיתפוס אותו, והצעד
    ``Smoke compile`` ב-CI עושה בדיוק את זה.
    """
    source = path.read_text(encoding="utf-8", errors="replace")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            compile(source, str(path), "exec")
        except SyntaxError:
            return []
        return [
            str(item.message)
            for item in caught
            if "escape" in str(item.message)
        ]


def test_no_python_source_carries_an_invalid_escape_sequence():
    """אפס מופעים בכל הריפו.

    שלושת הקבצים שנמצאו בסבב הזה — ``mcp_server/redaction.py``,
    ``tests/conftest.py`` ו-``tests/test_static_cache_busting.py`` —
    תוקנו ב-``r\"\"\"``, שאינו משנה אף תו בערך שנוצר בזמן ריצה בשני
    הראשונים, ובשלישי **מתקן** אותו.
    """
    offenders = [
        f"{path.relative_to(_REPO_ROOT).as_posix()}: {messages[0]}"
        for path in _python_sources()
        if (messages := _invalid_escapes(path))
    ]

    assert offenders == [], (
        "סדרת escape לא חוקית — ב-3.12 זו אזהרה ובגרסה עתידית שגיאה. "
        "התיקון הוא r לפני שלושת הגרשיים של ה-docstring, ולא הסרת "
        f"הלוכסן: {offenders}"
    )


def test_the_scan_can_actually_find_one():
    """מונה שאינו מסוגל למצוא דבר אינו ראיה.

    **בלי הבדיקה הזאת השומר שמעליה עובר גם על מימוש שבור לגמרי** — למשל
    כזה שמסנן לפי ``SyntaxWarning`` בגרסת פייתון שמדווחת
    ``DeprecationWarning``. זה לא היפותטי: זו הצורה הראשונה שנכתבה כאן,
    והיא החזירה אפס על ריפו שהיו בו שלושה מופעים.
    """
    planted = _REPO_ROOT / "tests" / "conftest.py"  # קובץ אמיתי, לא נכתב אליו
    source = planted.read_text(encoding="utf-8")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        compile(source + '\n_PLANTED = "\\ "\n', "planted", "exec")
        messages = [str(item.message) for item in caught if "escape" in str(item.message)]

    assert messages, "הסריקה אינה מוצאת escape לא חוקי שנשתל בכוונה"
