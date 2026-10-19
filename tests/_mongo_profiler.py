"""ה-profiler של mongod בבדיקות מול מונגו אמיתי (``wired_mongo``): מה השרת באמת עשה בזמן בלוק.

דמה (``tests/_fake_mongo.py``) עונה על השאלה **מה** חוזר, ולא **כמה** השרת קרא כדי להחזיר את
זה: שאילתה שעוברת על כל השורות של המשתמש ושאילתה שעוצרת במסמך הראשון מחזירות לה אותה תשובה.
את זה רושם ה-profiler — כל פקודה, עם ``keysExamined`` ו-``docsExamined``.

``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
"""

from __future__ import annotations

import contextlib


@contextlib.contextmanager
def profiled(db):
    """ה-profiler של mongod על מסד הבדיקה, מאופס. ביציאה הרשימה מתמלאת במה שנרשם בזמן הבלוק."""
    db.command("profile", 0)
    db["system.profile"].drop()
    db.command("profile", 2)
    entries: list[dict] = []
    try:
        yield entries
    finally:
        db.command("profile", 0)
        entries.extend(db["system.profile"].find(
            {}, {"ns": 1, "op": 1, "command": 1, "keysExamined": 1, "docsExamined": 1},
        ))
