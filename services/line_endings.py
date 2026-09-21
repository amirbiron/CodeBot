"""כלל אחד ל-``\\r`` בודד — סיומת שורה שאינה חד-משמעית — לשני הצרכנים שלו (#3419).

**למה מודול משלו.** הכלל נכתב פעמיים: ``mcp_server/outline.py`` (המנתב מחזיר
``no_outline`` עם ``inconsistent_line_endings``) ו-``services/md_parser.py``
(הפארסר מרים ``InconsistentLineEndings``). שני העותקים היו נכונים, וטסט השווה
אותם מול ``markdown-it-py`` — אבל עותק שני של כלל הוא מה שנסחף בתיקון הבא
(R6, ``duplicate-rule-second-copy``). ``services`` אינו מייבא מ-``mcp_server``,
הכיוון חד-סטרי, ולכן ההגדרה יושבת כאן ושני הצרכנים קוראים לה — אותו תקדים
כמו ``webapp/size_format.py``, שנולד אחרי שפורמוט גודל נמצא בחמישה מקומות.

**מה הכלל אומר.** ה-lookahead השלילי הוא כל ההבחנה: CRLF הוא המקרה הנפוץ
ושתי ספירות השורות מסכימות עליו, ולכן הוא חייב להמשיך לעבוד. רק CR בודד —
הפורמט של Mac שלפני 2001 — מפריד ביניהן: ``markdown-it-py`` מנרמל
``\\r\\n?|\\n`` (``rules_core/normalize.py``), כלומר ``\\r`` בודד הוא אצלו שורה
חדשה, בעוד שדות ה-``lines`` של ה-MCP נספרים ב-``split("\\n")``. בקובץ כזה
המפה מצביעה לשורה שקריאת טווח לא מגיעה אליה — ומפה שמצביעה לשומקום גרועה
ממפה שאין. ``tests/test_md_parser.py::test_the_lone_cr_rule_matches_markdown_it``
מריץ את הכלל מול הספרייה עצמה על טבלת קלטים.

**``search`` ולא ``replace``**: עוצר על ההתאמה הראשונה ואינו מקצה עותק של
הטקסט, שיכול להיות 10MB לפי ``RANGE_READ_MAX_BYTES``.

ייבוא קל בלבד — ``re``; בזמן ייבוא רצה רק קומפילציה של הביטוי.
"""

from __future__ import annotations

import re
from typing import Optional

#: ``\\r`` שאינו חלק מ-``\\r\\n``.
CR_WITHOUT_LF = re.compile(r"\r(?!\n)")


def find_lone_cr(text: str) -> Optional["re.Match[str]"]:
    """ההתאמה הראשונה של ``\\r`` בודד, או ``None`` כשאין.

    מחזירה את ההתאמה ולא ``bool``, כי הצרכן שמרים חריגה גוזר ממנה את מספר
    השורה (``text.count("\\n", 0, match.start()) + 1``), והצרכן שמחזיר סירוב
    צריך רק לדעת שיש.
    """
    return CR_WITHOUT_LF.search(text)
