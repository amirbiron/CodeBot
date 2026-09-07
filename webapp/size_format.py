"""עיצוב גדלי קבצים לתצוגה — מקור אמת אחד לוובאפ.

הכלל: ספרה אחת אחרי הנקודה, **ורק אם היא אומרת משהו**. ``105.0 KB`` ו-``582.0 B``
מוסיפים תו לכל כרטיס קובץ בלי להוסיף מידע, ו-``27.9 KB`` כן — ולכן החיתוך הוא
של ``.0`` בלבד ולא של כל השבר.

המודול הזה הוא עלה: הוא אינו מייבא דבר מהוובאפ, ולכן אפשר לייבא אותו מכל מקום
בלי מעגל ייבוא. הוא נוצר אחרי שהכלל היה משוכפל בין ``webapp/app.py`` ל-
``webapp/collections_api.py``, ושתי העותקים היו יכולים להיסחף זה מזה.
"""

from __future__ import annotations

#: סדר היחידות. האחרונה היא גם התקרה: מעליה הערך פשוט גדל.
UNITS: tuple[str, ...] = ("B", "KB", "MB", "GB", "TB")


def format_size_number(value: float) -> str:
    """מספר לתצוגה: ספרה אחת אחרי הנקודה, בלי ``.0`` מיותר.

    ``105.0`` ← ``"105"``, ``27.94`` ← ``"27.9"``, ``0.0`` ← ``"0"``.
    """
    text = f"{float(value):.1f}"
    return text[:-2] if text.endswith(".0") else text


def format_file_size(size_bytes: float | int) -> str:
    """גודל בבייטים ← מחרוזת לתצוגה, למשל ``"27.9 KB"`` או ``"582 B"``."""
    size = float(size_bytes)
    for unit in UNITS:
        if size < 1024.0 or unit == UNITS[-1]:
            return f"{format_size_number(size)} {unit}"
        size /= 1024.0
    # לא מגיעים לכאן: הלולאה תמיד מחזירה ביחידה האחרונה
    return f"{format_size_number(size)} {UNITS[-1]}"
