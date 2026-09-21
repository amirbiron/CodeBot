"""בדיקות מקור לבלוק הדגימה של בועת התזכורות — רצות גם ב-CI, שבו אין דפדפן.

קובצי ``*_browser.py`` מדולגים בשלמותם כשאין Chromium: ``test_browser_suite_is_gated_once``
אוכף שכל בדיקה שם מגיעה לשער ``chromium_executable``, ושריצה בלי דפדפן אינה מדווחת על
אף בדיקה כ-passed. לכן טענה על הטקסט של ``base.html`` שצריכה להיאכף ב-CI חיה כאן.
"""
from pathlib import Path

BASE_TEMPLATE = Path(__file__).resolve().parent.parent / "webapp" / "templates" / "base.html"

#: אותה שורה ש-``_with_fetch_timeout`` בקובץ הדפדפן מקצר בעותק; כאן נאכף הערך האמיתי.
FETCH_TIMEOUT_LINE = "const FETCH_TIMEOUT_MS = 15 * 1000;"


def test_the_real_fetch_timeout_is_fifteen_seconds():
    """הערך האמיתי של תקרת הבקשה נאכף כאן, כי טסטי ה-stall בדפדפן מקצרים אותו בעותק.

    15 שניות: פי כמעט שלושה מהמקסימום שנמדד ב-endpoint (5.32 שניות, worker
    טרי אחרי דיפלוי; המקור המלא בהערה מעל הקבוע ב-base.html).
    """
    assert BASE_TEMPLATE.read_text(encoding="utf-8").count(FETCH_TIMEOUT_LINE) == 1
