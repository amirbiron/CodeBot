#!/usr/bin/env python3
"""נכשל כשגיט עוקב אחרי קובץ ``.pyc`` או נתיב תחת ``__pycache__/``.

**למה זה קיים, ולמה ``.gitignore`` אינו מספיק.**

``.gitignore`` מכיל ``__pycache__/`` מזמן, והוא עובד — בדיוק במקרה אחד:
קובץ **untracked** ש-``git add`` מדלג עליו. הוא **אינו** מגן על שני
המסלולים שבהם קובץ כזה נכנס בכל זאת:

1. **``git checkout <ref> -- .``** מעתיק את מה שיש ב-``<ref>`` אל העץ
   **ואל ה-index**, בלי להתייעץ עם ``.gitignore`` — הוא חל על הוספה של
   קבצים חדשים, לא על שחזור מ-ref. אם ה-``<ref>`` מיושן, כל מה שהיה בו
   חוזר. זה מה שקרה כאן: ``git checkout origin/main -- .`` בסשן של
   PR #3401, כשה-``origin/main`` המקומי היה snapshot מלפני #3395, החזיר
   **11 קבצי ``.pyc``** ל-index — בדיוק אלה ש-#3395 הסיר. ``git add -A``
   שאחריו קומיט אותם, כי קובץ שכבר ב-index אינו "חדש" ו-``.gitignore``
   אינו נשאל עליו יותר.
2. **``git add -f``**, או קובץ שנכנס לפני שהדפוס נוסף ל-``.gitignore``.

בשני המסלולים אין שגיאה, אין אזהרה, ושום בדיקה קיימת לא מתריעה — הדיף
פשוט גדל בכמה קבצים בינאריים שאיש לא קורא. הבדיקה הזו היא ההתרעה.

**מה נבדק:** ``git ls-files``, כלומר מה שגיט עוקב אחריו *עכשיו*. זה מכסה
גם קובץ שנוסף בקומיט הזה וגם קובץ שנכנס לפני שנים ונשכח — ובשני המקרים
התשובה זהה, כי הבעיה זהה.

הרצה::

    python scripts/check_no_committed_pyc.py            # העץ הנוכחי
    python scripts/check_no_committed_pyc.py --ref main # ref אחר

יוצא ב-0 כשנקי, וב-1 עם רשימת הנתיבים כשלא.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

#: סיומות של בייטקוד מהודר. ``.pyo`` הוסר ב-Python 3.5 לטובת ``.pyc``,
#: והוא כאן כי ריפו בן כמה שנים יכול לשאת אחד כזה מגרסה ישנה — ועלות
#: הבדיקה היא מחרוזת אחת.
BYTECODE_SUFFIXES = (".pyc", ".pyo")

#: תיקיית המטמון של CPython. נבדקת כרכיב נתיב מלא ולא כתת-מחרוזת, אחרת
#: תיקייה בשם ``my__pycache__helpers`` הייתה נתפסת.
CACHE_DIR = "__pycache__"


def offending_paths(paths: list[str]) -> list[str]:
    """הנתיבים שאסור שיהיו במעקב, מתוך רשימה נתונה.

    פונקציה טהורה ונפרדת מהריצה של git, כדי שהבדיקה של הכלל עצמו לא
    תדרוש ריפו — ראו ``tests/test_no_committed_pyc.py``.
    """
    bad = []
    for path in paths:
        if path.endswith(BYTECODE_SUFFIXES) or CACHE_DIR in path.split("/"):
            bad.append(path)
    return sorted(bad)


def tracked_files(ref: str | None = None) -> list[str]:
    """הקבצים שגיט עוקב אחריהם — ב-index, או ב-``ref`` אם נמסר.

    **NUL-delimited (``-z``), ולא שורות.** בלי ``-z`` גיט **מצטט** נתיב
    שמכיל תו מיוחד — שורה חדשה, או כל תו שאינו ASCII כש-``core.quotePath``
    בברירת המחדל — בסגנון C: ``"line\\nbreak.pyc"``, עם המירכאות כחלק
    מהפלט. ``splitlines()`` החזיר אז מחרוזת שמסתיימת ב-``"`` ולא ב-``.pyc``,
    והבדיקה פספסה אותה: אומת על שני קבצים כאלה, שעברו את הגרסה הקודמת
    בשקט. עם ``-z`` אין ציטוט ואין escape — נתיב הוא מה שיושב בין שני NUL,
    שורה חדשה כלולה.

    הפענוח ב-``surrogateescape``, כדי ששם קובץ שאינו UTF-8 תקין יגיע
    ל-:func:`offending_paths` במקום להפיל את הבדיקה ב-``UnicodeDecodeError``
    — כשל בקריאה אינו "נקי", אבל גם אינו סיבה לא לבדוק את השאר.

    זורק ``subprocess.CalledProcessError`` כשגיט נכשל. **בכוונה לא נבלע:**
    בדיקה שלא הצליחה לרוץ אינה בדיקה שעברה, וכאן זה ההבדל בין "אין
    קבצים אסורים" לבין "לא הצלחתי לבדוק".
    """
    if ref:
        cmd = ["git", "ls-tree", "-r", "-z", "--name-only", ref]
    else:
        cmd = ["git", "ls-files", "-z"]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    return [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref",
        default=None,
        help="ref לבדיקה (ברירת מחדל: ה-index הנוכחי)",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help=(
            "נתיבים לבדיקה במקום לשאול את git. pre-commit מעביר כך את "
            "הקבצים ב-staging."
        ),
    )
    args = parser.parse_args()

    if args.paths:
        candidates = args.paths
    else:
        try:
            candidates = tracked_files(args.ref)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode("utf-8", "replace").strip() or str(exc)
            print(f"✗ לא הצלחתי לקרוא את רשימת הקבצים מגיט: {detail}", file=sys.stderr)
            return 2

    bad = offending_paths(candidates)
    if not bad:
        return 0

    print("✗ קבצי bytecode במעקב גיט:", file=sys.stderr)
    for path in bad:
        # נתיב עם שורה חדשה היה נשבר לשתי שורות ברשימה ומטעה; ``repr`` מציג
        # אותו כפי שהוא, בשורה אחת. נתיב רגיל נשאר קריא כמות שהוא.
        shown = path if path.isprintable() else repr(path)
        print(f"    {shown}", file=sys.stderr)
    print(
        "\n"
        ".gitignore אינו מונע את זה. הוא חל על קובץ untracked שמנסים\n"
        "להוסיף — ולא על קובץ שכבר נמצא ב-index. שני המסלולים שמכניסים\n"
        "אותו בכל זאת:\n"
        "\n"
        "  • git checkout <ref> -- .  מעתיק מה-ref אל העץ ואל ה-index בלי\n"
        "    להתייעץ עם .gitignore. אם ה-ref מיושן, כל מה שהיה בו חוזר.\n"
        "    כך נכנסו כאן 11 קבצים שכבר הוסרו — ראו את הפירוט ב-\n"
        "    scripts/check_no_committed_pyc.py.\n"
        "  • git add -f, או קובץ שנכנס לפני שהדפוס נוסף ל-.gitignore.\n"
        "\n"
        "התיקון:\n"
        "    git rm -r --cached <path>   # להסיר מהמעקב, להשאיר על הדיסק\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
