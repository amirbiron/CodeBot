"""נכסי הפתקים חייבים לשאת cache-buster דינמי בכל תבנית שטוענת אותם.

**למה הבדיקה הזו קיימת:** ``SEND_FILE_MAX_AGE_DEFAULT`` הוא שנה, בלי
``must-revalidate``. תבנית שטוענת ``sticky-notes.js`` בכתובת קבועה תמשיך
להגיש לדפדפן את העותק שנשמר לפני הדיפלוי — עד שנה. הכשל שקט לחלוטין:
השרת מגיש את הקוד החדש, הבדיקות עוברות, וה-PR נראה ממוזג — והמשתמש רואה
את ההתנהגות הישנה. זה בדיוק מה שקרה עם רינדור המארקדאון בפתקי קבצים,
בזמן שאותו קוד עבד בלוחות ובדפדפן הריפו כי שם הכתובת נושאת ``?v=``.

**ולמה היא מנוסחת כך:** שומר שהתוצאה השלילית שלו אינה אמינה גרוע משומר
שאינו קיים, כי הוא קונה ביטחון בלי לספק אותו. לכן:

- **שתי צורות הכתיבה** — ``url_for`` וגם נתיב ``/static/`` קשיח. הצורה
  השנייה כבר קיימת בריפו (``snippets.html``, ``community_library.html``),
  ולכן מי שיכתוב כך גם עבור פתקים היה עובר בשקט.
- **שני סוגי מרכאות**, ו**סריקה על הטקסט המלא** ולא שורה-שורה: תגית
  ``url_for`` שנשברת לשתי שורות היא עדיין אותה תגית. חציית השורות עובדת
  דרך ``\s*`` ומחלקות תווים שוללות, ששתיהן בולעות ``\n`` כברירת מחדל —
  **לא** דרך ``re.S``, שאין לו מה לעשות כאן כי אין בביטוי נקודה מחוץ
  למחלקת תווים. הדגל נוסה והוסר: הוא לא שינה דבר.
- **דרישה ל-``static_version`` ולא רק ל-``?v=``**: ``?v=1`` הוא מחרוזת
  קבועה שאינה משתנה בין דיפלוים, כלומר בדיוק המצב שהקובץ נועד למנוע.
"""

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "webapp" / "templates"
REPO = TEMPLATES.parent.parent

# ``{{ url_for('static', filename='...') }}`` — שני סוגי מרכאות, ו-``\s*``
# בכל מפרק כדי שתגית שנשברה לשורות תיתפס כמו תגית בשורה אחת.
# ה-``tail`` נאסף עד המרכאה הסוגרת של האטריביוט, ולכן הוא כולל ביטויי
# Jinja עם רווחים בתוכם — ``?v={{ static_version }}``.
URL_FOR_RE = re.compile(
    r"""url_for\(\s*(['"])static\1\s*,\s*filename\s*=\s*(['"])"""
    r"""(?P<name>[^'"]+\.(?:js|css))\2\s*\)\s*\}\}(?P<tail>[^"']*)""",
)

# ``src="/static/js/x.js..."`` — הצורה הקשיחה, שאינה עוברת דרך ``url_for``.
HARDCODED_RE = re.compile(
    r"""(?:src|href)\s*=\s*(['"])/static/(?P<name>[^'"?]+\.(?:js|css))(?P<tail>[^'"]*)\1"""
)

# הנכסים שחייבים cache-buster. הרשימה מכוונת ולא גורפת: היא מכסה את מה
# שהוכח שנשבר, ואפשר להרחיב אותה כשמשטח נוסף נדרס באותו אופן.
GUARDED = ("js/sticky-notes.js", "css/sticky-notes.css")


def scan_text(text):
    """מחזיר ``(name, tail, offset)`` לכל נכס שמור ללא cache-buster דינמי.

    זהו מסלול הקוד היחיד — גם הסריקה על התבניות וגם הבדיקה-העצמית עוברות
    כאן. אחרת הבדיקה-העצמית הייתה מאמתת ביטוי אחר מזה שרץ בפועל.
    """
    out = []
    for rx in (URL_FOR_RE, HARDCODED_RE):
        for m in rx.finditer(text):
            name = m.group("name")
            if name not in GUARDED:
                continue
            # **``static_version`` ולא ``?v=``.** מחרוזת קבועה אחרי ``?v=``
            # אינה משתנה בין דיפלוים, ולכן אינה מבטלת שום קאש.
            if "static_version" in m.group("tail"):
                continue
            out.append((name, m.group("tail"), m.start()))
    return out


def _offenders():
    out = []
    for tpl in sorted(TEMPLATES.rglob("*.html")):
        text = tpl.read_text(encoding="utf-8")
        for name, _tail, offset in scan_text(text):
            lineno = text.count("\n", 0, offset) + 1
            out.append(f"{tpl.relative_to(REPO)}:{lineno} → {name}")
    return out


def test_sticky_notes_assets_are_cache_busted():
    offenders = _offenders()
    assert not offenders, (
        "נכסי פתקים בלי ?v={{ static_version }} — הדפדפן ימשיך להגיש עותק "
        "ישן עד שנה:\n  " + "\n  ".join(offenders)
    )


# כל מקרה: (תיאור, טקסט, האם אמור להיתפס)
CASES = [
    (
        "url_for במרכאות בודדות, בלי buster",
        """<script src="{{ url_for('static', filename='js/sticky-notes.js') }}"></script>""",
        True,
    ),
    (
        "url_for במרכאות כפולות, בלי buster",
        """<script src='{{ url_for("static", filename="js/sticky-notes.js") }}'></script>""",
        True,
    ),
    (
        "url_for שנשבר לשתי שורות",
        """<script src="{{ url_for('static',\n    filename='js/sticky-notes.js') }}"></script>""",
        True,
    ),
    (
        "נתיב /static קשיח",
        """<script src="/static/js/sticky-notes.js"></script>""",
        True,
    ),
    (
        "buster קבוע — לא משתנה בין דיפלוים",
        """<script src="{{ url_for('static', filename='js/sticky-notes.js') }}?v=1"></script>""",
        True,
    ),
    (
        "CSS בלי buster",
        """<link rel="stylesheet" href="{{ url_for('static', filename='css/sticky-notes.css') }}">""",
        True,
    ),
    (
        "תקין — url_for עם static_version",
        """<script src="{{ url_for('static', filename='js/sticky-notes.js') }}?v={{ static_version }}"></script>""",
        False,
    ),
    (
        "תקין — נתיב קשיח עם static_version",
        """<script src="/static/js/sticky-notes.js?v={{ static_version }}"></script>""",
        False,
    ),
    (
        "נכס אחר לגמרי — לא בתחום השמירה",
        """<script src="{{ url_for('static', filename='js/md-anchors.js') }}"></script>""",
        False,
    ),
]


def test_the_check_can_actually_fail():
    """בדיקה שהשומר מסוגל ליפול, ובכל צורת כתיבה.

    בלי זה, ביטוי רגולרי שבור היה מחזיר רשימה ריקה תמיד — ירוק לנצח על
    לא כלום, שזה בדיוק המצב שהקובץ הזה נועד למנוע.
    """
    failures = []
    for label, text, should_flag in CASES:
        flagged = bool(scan_text(text))
        if flagged != should_flag:
            failures.append(
                f"{label}: ציפיתי ל-{'זיהוי' if should_flag else 'מעבר'}, קיבלתי ההפך"
            )
    assert not failures, "השומר אינו מזהה נכון:\n  " + "\n  ".join(failures)
