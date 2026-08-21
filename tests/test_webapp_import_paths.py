"""שומר על סדר הטעינה של ``webapp/app.py``.

**למה הקובץ הזה קיים:** גוניקורן טוען בפרודקשן ``app:app`` **מתוך
``webapp/``**, ולכן ``sys.path[0]`` הוא ``webapp/`` ולא שורש הפרויקט.
מודולים כמו ``sticky_notes_target`` יושבים בשורש, וניתן לייבא אותם רק אחרי
ש-``app.py`` מוסיף את ``ROOT_DIR`` ל-``sys.path``.

ייבוא כזה שהוצב בראש הקובץ הפיל את כל השירות ב-``ModuleNotFoundError``,
בלולאת boot. הבדיקה שלא תפסה את זה הרצה ``import webapp.app`` **משורש
הריפו** — ושם השורש כבר בנתיב, אז היא עברה.

הבדיקה כאן מריצה בדיוק כמו שגוניקורן מריץ, ולכן היא היחידה שיכולה ליפול
על סדר ייבוא שגוי.

**למה לא ``ensure_project_root_in_path()``:** נשקל ונבדק. helper כזה אינו
ניתן לייבוא בנקודה שבה הוא נחוץ — מתוך ``webapp/`` גם ``import
project_root`` וגם ``from webapp import _bootstrap`` נכשלים, כי בדיוק זה
המצב שהוא בא לתקן. הוא היה מחייב ``try/except ImportError`` כפול בכל אתר
קריאה, וזה שביר יותר משורת ``noqa`` אחת ליד בלוק שכבר מתועד. מה שכן סוגר
את מחלקת הבאגים הוא בדיקה שנכשלת ב-CI במקום בפרודקשן — כלומר הקובץ הזה.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBAPP_DIR = REPO_ROOT / "webapp"


def test_app_imports_the_way_gunicorn_loads_it():
    """``cd webapp && python -c "import app"`` — בדיוק פקודת הטעינה בפרודקשן.

    נופלת על כל ייבוא של מודול-שורש שהוצב לפני ``sys.path.insert(0,
    ROOT_DIR)`` ב-``app.py``.
    """
    proc = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=str(WEBAPP_DIR),
        capture_output=True,
        text=True,
        timeout=280,
    )

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-12:]
        pytest.fail(
            "‏app.py אינו נטען מתוך webapp/ — כך גוניקורן טוען אותו בפרודקשן.\n"
            "‏ייבוא של מודול משורש הפרויקט חייב לשבת **אחרי** "
            "‏sys.path.insert(0, ROOT_DIR), עם # noqa: E402.\n\n" + "\n".join(tail)
        )


def test_root_module_imports_come_after_the_path_setup():
    """הבדיקה הסטטית שמסבירה **למה** נפל, כשהראשונה אומרת **ש**נפל.

    היא זולה, רצה בלי תת-תהליך, ומצביעה על השורה המדויקת.
    """
    source = (WEBAPP_DIR / "app.py").read_text(encoding="utf-8")
    lines = source.splitlines()

    setup_line = next(
        (i for i, ln in enumerate(lines) if "sys.path.insert(0, ROOT_DIR)" in ln),
        None,
    )
    assert setup_line is not None, "‏הכנת ה-sys.path נעלמה מ-app.py"

    # מודולים שיושבים בשורש הריפו ואינם נגישים מ-webapp/ בלי ההכנה
    root_modules = ("sticky_notes_target", "sticky_notes_scope", "user_roles", "note_boards")
    offenders = [
        (i + 1, ln.strip())
        for i, ln in enumerate(lines[:setup_line])
        if ln.startswith(("from ", "import "))
        and any(f"{m} import" in ln or ln.endswith(m) for m in root_modules)
    ]

    assert not offenders, (
        "‏ייבוא ממודול-שורש לפני הכנת ה-sys.path (שורה "
        f"{setup_line + 1}) — יפיל את גוניקורן: {offenders}"
    )
