"""כל סיבה ש-``raw_withheld_reason`` יכול לשאת חייבת תרגום בדשבורד.

**למה טסט ולא ערנות:** הסיבות מוגדרות בפייתון (``services/query_profiler_service.py``)
ומתורגמות לעברית ב-JS (``webapp/templates/profiler_dashboard.html``). שני מקומות,
בלי שום דבר שמחבר ביניהם — ולכן סיבה חדשה נוספת בקוד ונשכחת בתבנית. אז האדמין
רואה מחרוזת אנגלית גולמית כמו ``malformed_stage:$limit`` במקום הסבר. ברירה בטוחה
שמוצגת בשפה שאיש לא קורא היא חצי ברירה.

**איך נשמרת האמת:** הרשימה לא נכתבת כאן ביד — היא **נחלצת מקוד המקור**. סיבה
חדשה נכנסת לטסט אוטומטית ברגע שהיא נכתבת בשירות, בלי שאיש יזכור לעדכן משהו.
זה מה שהופך את זה לפתרון שורש ולא לרשימה נוספת שתסחף גם היא.

הטסט קורא קבצים בלבד — בלי DB, בלי רשת, בלי דפדפן.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SERVICE = _ROOT / "services" / "query_profiler_service.py"
_TEMPLATE = _ROOT / "webapp" / "templates" / "profiler_dashboard.html"

#: ``RAW_WITHHELD_X = "..."`` — הסיבות הקבועות, בלי שם אחרי נקודתיים.
_BARE_IN_SERVICE = re.compile(r'^RAW_WITHHELD_[A-Z_]+ = "([a-z_]+)"$', re.MULTILINE)
#: ``_RawQueryWithheld(f"prefix:{...}")`` — הסיבות שנושאות שם אחרי נקודתיים.
_PREFIXED_IN_SERVICE = re.compile(r'_RawQueryWithheld\(f?"([a-z_]+):')


def _js_map_keys(name: str) -> set:
    """מפתחות של מילון JS מהתבנית. המילונים שטוחים, ולכן די בסוגר המסולסל הראשון."""
    body = re.search(rf"const {name} = \{{(.*?)\n  \}};", _TEMPLATE.read_text(encoding="utf-8"), re.DOTALL)
    assert body is not None, f"המילון {name} לא נמצא בתבנית — כנראה שונה שמו"
    return set(re.findall(r"^\s*([A-Za-z_]+):", body.group(1), re.MULTILINE))


def _service_source() -> str:
    return _SERVICE.read_text(encoding="utf-8")


def test_the_extraction_actually_found_reasons():
    """שומר על הטסטים שמתחת: רגקס שהפסיק להתאים היה הופך אותם לריקים ולעוברים."""
    assert len(set(_BARE_IN_SERVICE.findall(_service_source()))) >= 5
    assert len(set(_PREFIXED_IN_SERVICE.findall(_service_source()))) >= 4


@pytest.mark.parametrize("reason", sorted(set(_BARE_IN_SERVICE.findall(_service_source()))))
def test_every_fixed_reason_has_hebrew_text(reason):
    assert reason in _js_map_keys("RAW_WITHHELD_TEXT"), (
        f"הסיבה {reason!r} נוצרת בשירות ואין לה תרגום ב-RAW_WITHHELD_TEXT שבדשבורד"
    )


@pytest.mark.parametrize("prefix", sorted(set(_PREFIXED_IN_SERVICE.findall(_service_source()))))
def test_every_named_reason_has_hebrew_text(prefix):
    assert prefix in _js_map_keys("RAW_WITHHELD_NAMED"), (
        f"הסיבה {prefix!r}:<שם> נוצרת בשירות ואין לה תרגום ב-RAW_WITHHELD_NAMED שבדשבורד"
    )
