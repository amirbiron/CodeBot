"""התגיות של קובץ — איך שורת טקסט נחתכת לתגיות, ואיך "עדכון מהיר" מנרמל אותן.

**למה המודול קיים.** בשדה התגיות מקלידים שורה אחת (``utils, #api``), ומישהו
צריך לחתוך אותה לתגיות נפרדות. עד שהמודול נכתב החיתוך היה כתוב **בכמה עותקים
שנסחפו**: עריכת קובץ, עריכת קובץ גדול וההעלאה חתכו לפי פסיק, ``#`` ושורה חדשה,
בעוד ש-``POST /api/file/<id>/quick-update`` חתך לפי פסיק בלבד, והדשבורד חתך
בעצמו ב-JS ושלח רשימה. אותו ``#python`` נשמר כך בעמוד העריכה כ-``python``,
ובעדכון המהיר כ-``#python`` — ועמוד הקובץ, שמוסיף ``#`` לפני כל תגית, הציג
``##python``. :func:`split_tags_text` הוא החיתוך היחיד, וכל המסלולים שמקבלים
טקסט קוראים לו (``RECURRING-PATTERNS.md`` R6 ב-``amir-bug-patterns``). התיוג
המרובה (``webapp/static/js/bulk-actions.js``) עדיין חותך בעצמו לפי פסיק ושולח
רשימה ל-``/api/files/bulk-tag`` — הוא לא אוחד כאן.

**הנרמול של העדכון המהיר יושב כאן לצד החיתוך,** ולא בראוט, כדי ששני חצאי
"מה נשמר כשמקלידים תגיות" ייקראו במקום אחד. הוא חל **רק** על העדכון המהיר:
עריכה, העלאה ותיוג מרובה שומרים את הרישיות כפי שהוקלדה, וזו התנהגות קיימת
שהמודול לא שינה. ההמרה לאותיות קטנות נשארה גם לתגיות ``repo:`` — הוחלט כך
במפורש כשהמודול נכתב (``docs/whats-new.rst``), למרות שעמוד הקבצים מקבץ
ומסנן לפי התגית הזו ברגישות לרישיות.

המודול טהור — ``re`` ו-``typing`` בלבד — מאותה סיבה כמו ``file_description``:
``webapp.app`` מייבא אותו ברמת המודול, וייבוא כזה אינו יכול לגרור מסד.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional

#: המפרידים בין תגיות בשורת טקסט: פסיק, ``#`` ושורה חדשה. ``#`` הוא מפריד
#: ולא חלק מהתגית, כי כך מקלידים תגיות ("``#utils, #api``" — זה גם ה-
#: placeholder של עמוד העריכה וההעלאה), והוא לעולם לא נשמר.
TAG_TEXT_SEPARATORS = re.compile(r'[,#\n]+')

#: כמה תגיות שונות העדכון המהיר שומר לכל היותר. מה שמעבר נזרק — ולא בשקט:
#: הראוט מחזיר את התגיות כפי שנשמרו, ועמוד הקובץ מציג את מה שחזר.
QUICK_UPDATE_MAX_TAGS = 20

#: אורך מרבי, בתווים, של תגית אחת בעדכון המהיר. ארוכה יותר נחתכת לאורך הזה.
QUICK_UPDATE_MAX_TAG_CHARS = 50


def split_tags_text(raw: str) -> List[str]:
    """שורת טקסט ← רשימת תגיות, לפי :data:`TAG_TEXT_SEPARATORS`.

    כל חלק עובר ``strip``, וחלקים ריקים נזרקים. הסדר נשמר, ו**כפילויות
    נשארות** — זה מה שעריכה והעלאה עשו מאז שנכתבו, וההסרה שלהן שייכת למי
    שמנרמל (:func:`normalize_quick_update_tags`), לא לחיתוך.
    """
    return [t.strip() for t in TAG_TEXT_SEPARATORS.split(raw) if t.strip()]


def normalize_quick_update_tags(raw: Any) -> Optional[List[str]]:
    """התגיות שהעדכון המהיר שומר, מתוך מה שהלקוח שלח בשדה ``tags``.

    ``raw`` הוא שורת טקסט (נחתכת ב-:func:`split_tags_text`) או רשימת
    מחרוזות. כל תגית עוברת ``strip``, אותיות קטנות וחיתוך ל-
    :data:`QUICK_UPDATE_MAX_TAG_CHARS`; ריקות וכפולות נזרקות, ונשמרות עד
    :data:`QUICK_UPDATE_MAX_TAGS` הראשונות. ``None`` מתקבל כמו רשימה ריקה,
    כלומר "בלי תגיות".

    **הכפילויות נזרקות לפני הספירה.** עד שהנרמול עבר לכאן הראוט חתך את
    הקלט הגולמי לעשרים פריטים ורק אחר כך זרק כפולות וריקות, כך שעשרים
    פריטים עם חזרות השאירו פחות מעשרים תגיות גם כשהיו עוד שונות אחריהן.

    מחזירה ``None`` כשהצורה אינה תקינה — לא טקסט ולא רשימה, או רשימה שיש בה
    פריט שאינו מחרוזת — **וזה ערוץ הכשל היחיד**: הקורא חייב לבדוק אותו
    (``CRITICAL-PATTERNS.md`` K11). עד שהנרמול עבר לכאן ערך כזה הומר בשקט
    (``str(t)``), ומילון במקום רשימה הפיל את הראוט ב-500
    (``bugbot-rules/external-input-isinstance.md``).
    """
    if raw is None:
        items: List[Any] = []
    elif isinstance(raw, str):
        items = split_tags_text(raw)
    elif isinstance(raw, list):
        items = raw
    else:
        return None
    if not all(isinstance(t, str) for t in items):
        return None

    clean: List[str] = []
    for item in items:
        tag = item.strip().lower()[:QUICK_UPDATE_MAX_TAG_CHARS]
        if tag and tag not in clean:
            clean.append(tag)
            if len(clean) == QUICK_UPDATE_MAX_TAGS:
                break
    return clean
