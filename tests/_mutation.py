"""החלפה על עותק בזיכרון, לבדיקות מוטציה של סקריפט שנחלץ מהמקור.

עותק אחד לשלושת קובצי בדיקות הדפדפן, במקום שלוש הגדרות זהות. ``assert``
כפול: העוגן חייב להימצא פעם אחת בדיוק — אחרת המוטציה נחתה במקום אחר או
בשום מקום — והתוצאה חייבת להיות שונה מהמקור, אחרת "ריצת הבקרה" בדקה כלום.
"""
from __future__ import annotations


def mutate(script: str, anchor: str, replacement: str) -> str:
    assert script.count(anchor) == 1, f"העוגן נמצא {script.count(anchor)} פעמים: {anchor[:70]!r}"
    mutated = script.replace(anchor, replacement)
    assert mutated != script, "המוטציה לא שינתה כלום"
    return mutated
