"""רשימת המכולות של הייצוא היא עותק של הרשימה בוובאפ — והטסט הזה משווה ביניהן.

הייצוא ל-HTML מעוצב (``services/styled_export_service.py``) רץ בשרת, ב-Python-Markdown,
ומחזיק את סוגי התיבות ב-``ADMONITION_TYPES`` ואת הכותרת של ``::: details``
ב-``DETAILS_DEFAULT_TITLE``. בוובאפ אותו מידע חי ב-JS, בשלושה מקומות:

* ``webapp/static/js/admonition-icons.js`` — ``ADMONITION_TITLES`` (הסוגים והתוויות שלהם)
  ו-``DETAILS_DEFAULT_TITLE``;
* ``webapp/templates/md_preview.html`` — ``const types``, הסוגים ש-``markdown-it-container``
  נרשם להם בתצוגת הקובץ;
* ``webapp/static/js/live-preview.js`` — ``containerTypes``, אותו רישום ב-Live Preview.

ההשוואה היא גם לרישום ולא רק ל-``ADMONITION_TITLES``: סוג שמופיע בתוויות ולא נרשם
אינו מוצג כתיבה בתצוגה (``TESTING-PATTERNS.md`` T1 ב-amir-bug-patterns — הצרכן, לא
המפרט). זו הסחיפה שהטסט הזה נכתב בגללה: הוובאפ הציג כתיבות סוגים שהייצוא לא הכיר,
וגם את ``details``, ובייצוא הם יצאו כטקסט גולמי (``RECURRING-PATTERNS.md`` R6).
"""

import re
from pathlib import Path

import pytest

from services.styled_export_service import ADMONITION_TYPES, DETAILS_DEFAULT_TITLE

ROOT = Path(__file__).resolve().parent.parent
ICONS_JS = ROOT / "webapp" / "static" / "js" / "admonition-icons.js"
MD_PREVIEW = ROOT / "webapp" / "templates" / "md_preview.html"
LIVE_PREVIEW = ROOT / "webapp" / "static" / "js" / "live-preview.js"


def _literal_after(path: Path, anchor: str, opener: str, closer: str) -> str:
    """התוכן שבין ``opener`` ל-``closer`` הראשונים אחרי ``anchor``, שמופיע בקובץ פעם אחת בדיוק."""
    source = path.read_text(encoding="utf-8")
    assert source.count(anchor) == 1, f"{path.name}: {anchor!r} צריך להופיע פעם אחת בדיוק"
    start = source.index(opener, source.index(anchor))
    return source[start + 1 : source.index(closer, start)]


def _webapp_titles(path: Path = ICONS_JS) -> dict[str, str]:
    """סוג ← תווית, מתוך ``ADMONITION_TITLES``."""
    body = _literal_after(path, "var ADMONITION_TITLES = {", "{", "}")
    return dict(re.findall(r"(\w+)\s*:\s*'([^']*)'", body))


def _webapp_details_title(path: Path = ICONS_JS) -> str:
    source = path.read_text(encoding="utf-8")
    found = re.findall(r"var DETAILS_DEFAULT_TITLE = '([^']*)';", source)
    assert len(found) == 1, f"{path.name}: DETAILS_DEFAULT_TITLE צריך להופיע פעם אחת בדיוק"
    return found[0]


def _registered(path: Path, anchor: str) -> list[str]:
    """הסוגים במערך שהקובץ רושם עבורם את ``markdown-it-container``."""
    return re.findall(r"'([^']*)'", _literal_after(path, anchor, "[", "]"))


def _webapp_registrations(
    md_preview: Path = MD_PREVIEW,
    live_preview: Path = LIVE_PREVIEW,
) -> dict[str, list[str]]:
    return {
        "md_preview.html": _registered(md_preview, "const types = ["),
        "live-preview.js": _registered(live_preview, "const containerTypes = ["),
    }


def _drift(
    titles: dict[str, str],
    details_title: str,
    registrations: dict[str, list[str]],
) -> list[str]:
    """כל הפערים בין הייצוא לוובאפ, בניסוח שאומר מה לתקן."""
    problems: list[str] = []
    for kind in sorted(titles.keys() - ADMONITION_TYPES.keys()):
        problems.append(f"בוובאפ (ADMONITION_TITLES) ואין בייצוא: {kind!r}")
    for kind in sorted(ADMONITION_TYPES.keys() - titles.keys()):
        problems.append(f"בייצוא ואין בוובאפ (ADMONITION_TITLES): {kind!r}")
    for kind in sorted(ADMONITION_TYPES.keys() & titles.keys()):
        export_title = ADMONITION_TYPES[kind].title
        if export_title != titles[kind]:
            problems.append(
                f"תווית שונה עבור {kind!r}: בייצוא {export_title!r}, בוובאפ {titles[kind]!r}"
            )
    if DETAILS_DEFAULT_TITLE != details_title:
        problems.append(
            f"DETAILS_DEFAULT_TITLE שונה: בייצוא {DETAILS_DEFAULT_TITLE!r}, "
            f"בוובאפ {details_title!r}"
        )
    for name, kinds in registrations.items():
        if "details" not in kinds:
            problems.append(f"{name} לא רושם את 'details'")
        alerts = set(kinds) - {"details"}
        for kind in sorted(alerts - ADMONITION_TYPES.keys()):
            problems.append(f"{name} רושם {kind!r} ואין אותו בייצוא")
        for kind in sorted(ADMONITION_TYPES.keys() - alerts):
            problems.append(f"{kind!r} בייצוא ו-{name} לא רושם אותו")
    return problems


def test_the_export_knows_every_container_the_webapp_renders():
    """כל סוג שהוובאפ מציג כתיבה הוא תיבה גם בייצוא, עם אותה כותרת ברירת מחדל."""
    titles = _webapp_titles()
    registrations = _webapp_registrations()

    # רשימה ריקה היא כישלון ולא מעבר: החילוץ איבד את מה שהוא מודד.
    assert titles, (
        "לא נמצאו תוויות ב-ADMONITION_TITLES — החילוץ מ-admonition-icons.js איבד את הרשימה"
    )
    for name, kinds in registrations.items():
        assert kinds, f"לא נמצאו סוגים ברישום של {name} — החילוץ איבד את המערך"

    problems = _drift(titles, _webapp_details_title(), registrations)
    assert not problems, (
        "המכולות בייצוא (ADMONITION_TYPES / DETAILS_DEFAULT_TITLE "
        "ב-services/styled_export_service.py) אינן תואמות את הוובאפ:\n  " + "\n  ".join(problems)
    )


def _mutate(src: Path, dst_dir: Path, old: str, new: str) -> Path:
    text = src.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"המוטציה צריכה מופע יחיד של {old!r} ב-{src.name}"
    dst = dst_dir / src.name
    dst.write_text(text.replace(old, new), encoding="utf-8")
    return dst


@pytest.mark.parametrize(
    "target, old, new, expected",
    [
        # סוג חדש בוובאפ, שלא נכנס לייצוא
        (
            "icons",
            "abstract: 'תקציר',",
            "abstract: 'תקציר',\n    summary: 'סיכום',",
            "בוובאפ (ADMONITION_TITLES) ואין בייצוא: 'summary'",
        ),
        # תווית ששונתה בוובאפ בלבד
        ("icons", "quote: 'ציטוט',", "quote: 'מובאה',", "תווית שונה עבור 'quote'"),
        # הכותרת של details ששונתה בוובאפ בלבד
        (
            "icons",
            "var DETAILS_DEFAULT_TITLE = 'לחץ להצגה';",
            "var DETAILS_DEFAULT_TITLE = 'הצג';",
            "DETAILS_DEFAULT_TITLE שונה",
        ),
        # סוג שנרשם בתצוגת הקובץ ואין לו מקבילה בייצוא
        (
            "md_preview",
            "'todo','abstract'];",
            "'todo','abstract','summary'];",
            "md_preview.html רושם 'summary'",
        ),
        # details שירד מהרישום
        (
            "md_preview",
            "const types = ['details','note',",
            "const types = ['note',",
            "md_preview.html לא רושם את 'details'",
        ),
        # סוג שירד מהרישום ב-Live Preview
        (
            "live_preview",
            "      'abstract',\n",
            "",
            "'abstract' בייצוא ו-live-preview.js לא רושם אותו",
        ),
    ],
    ids=[
        "type-added-to-webapp",
        "label-renamed-in-webapp",
        "details-title-changed",
        "type-registered-in-md-preview",
        "details-unregistered",
        "type-dropped-from-live-preview",
    ],
)
def test_the_comparison_catches_each_kind_of_drift(tmp_path, target, old, new, expected):
    """אותה השוואה, על עותק שסחף — חייבת לדווח עליו.

    בלי זה אין הבדל בין "הייצוא תואם" לבין "ההשוואה לא מסוגלת לראות פער".
    """
    icons, md_preview, live_preview = ICONS_JS, MD_PREVIEW, LIVE_PREVIEW
    if target == "icons":
        icons = _mutate(ICONS_JS, tmp_path, old, new)
    elif target == "md_preview":
        md_preview = _mutate(MD_PREVIEW, tmp_path, old, new)
    else:
        live_preview = _mutate(LIVE_PREVIEW, tmp_path, old, new)

    problems = _drift(
        _webapp_titles(icons),
        _webapp_details_title(icons),
        _webapp_registrations(md_preview, live_preview),
    )

    assert any(expected in p for p in problems), problems
