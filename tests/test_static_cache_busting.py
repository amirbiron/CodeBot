"""נכסי הפתקים חייבים לשאת cache-buster בכל תבנית שטוענת אותם.

**למה הבדיקה הזו קיימת:** ``SEND_FILE_MAX_AGE_DEFAULT`` הוא שנה, בלי
``must-revalidate``. תבנית שטוענת ``sticky-notes.js`` בכתובת קבועה תמשיך
להגיש לדפדפן את העותק שנשמר לפני הדיפלוי — עד שנה. הכשל שקט לחלוטין:
השרת מגיש את הקוד החדש, הבדיקות עוברות, וה-PR נראה ממוזג — והמשתמש רואה
את ההתנהגות הישנה. זה בדיוק מה שקרה עם רינדור המארקדאון בפתקי קבצים,
בזמן שאותו קוד בדיוק עבד בלוחות ובדפדפן הריפו כי שם הכתובת נושאת ``?v=``.
"""

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "webapp" / "templates"

# ``url_for('static', filename='...')`` ואחריו ``}}`` ואז מה שנשאר עד סוף התגית.
ASSET_RE = re.compile(
    r"url_for\(\s*'static'\s*,\s*filename\s*=\s*'([^']+\.(?:js|css))'\s*\)\s*\}\}([^\"'>]*)"
)

# הנכסים שחייבים cache-buster. הרשימה מכוונת ולא גורפת: היא מכסה את מה
# שהוכח שנשבר, ואפשר להרחיב אותה כשמשטח נוסף נדרס באותו אופן.
GUARDED = ("js/sticky-notes.js", "css/sticky-notes.css")


def _offenders():
    out = []
    for tpl in sorted(TEMPLATES.rglob("*.html")):
        text = tpl.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for filename, tail in ASSET_RE.findall(line):
                if filename in GUARDED and "?v=" not in tail:
                    out.append(f"{tpl.relative_to(TEMPLATES.parent.parent)}:{lineno} → {filename}")
    return out


def test_sticky_notes_assets_are_cache_busted():
    offenders = _offenders()
    assert not offenders, (
        "נכסי פתקים בלי ?v={{ static_version }} — הדפדפן ימשיך להגיש עותק "
        "ישן עד שנה:\n  " + "\n  ".join(offenders)
    )


def test_the_check_can_actually_fail():
    """בדיקה שהבדיקה מסוגלת ליפול.

    בלי זה, ביטוי רגולרי שבור היה נותן רשימה ריקה תמיד — ירוק לנצח על
    לא כלום, שזה בדיוק המצב שהקובץ הזה נועד למנוע.
    """
    sample = "<script src=\"{{ url_for('static', filename='js/sticky-notes.js') }}\"></script>"
    found = ASSET_RE.findall(sample)
    assert found, "הביטוי לא זיהה תגית ללא cache-buster"
    assert found[0][0] == "js/sticky-notes.js"
    assert "?v=" not in found[0][1]

    ok = "<script src=\"{{ url_for('static', filename='js/sticky-notes.js') }}?v={{ static_version }}\"></script>"
    found_ok = ASSET_RE.findall(ok)
    assert found_ok and "?v=" in found_ok[0][1], "הביטוי לא זיהה תגית תקינה"
