"""גודל קובץ בתצוגה — הכלל, וההסכמה בין שני המימושים.

הכלל: ספרה אחת אחרי הנקודה ורק אם היא אומרת משהו, יחידה מתאימה, והערך עטוף
בבידוד דו-כיווני כדי שייקרא בסדר לטיני גם בתוך טקסט בעברית.

הבדיקות נוגעות בכל הצרכנים בצד השרת — הפונקציה המשותפת, זו של ``webapp/app.py``
שמזינה את כרטיסי הקבצים, וזו של האוספים — וגם מריצות את התאום ב-JS ומשוות.
**"שני הקבצים כתובים אותו דבר" אינו ראיה שהם מתנהגים אותו דבר:** ההשוואה הזו
תפסה פער אמיתי, שבו 1280 בתים הוצגו ``1.2 KB`` מהשרת ו-``1.3 KB`` מהדפדפן.

מה שהבדיקות כאן **לא** מוכיחות: שהערך באמת מצויר בסדר הנכון על המסך. סדר bidi
הוא משהו שהדפדפן אוכף ו-Python אינו רואה — את זה מוכיחה
``tests/test_size_format_bidi_browser.py``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from webapp.size_format import LRI, PDI, format_file_size, format_size_number

KB = 1024
MB = 1024 * 1024
GB = 1024 * 1024 * 1024

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_MODULE = REPO_ROOT / "webapp" / "static" / "js" / "utils" / "size-format.js"


def wrapped(text: str) -> str:
    """הצורה המלאה שהפונקציה מחזירה — הערך בתוך תווי הבידוד."""
    return f"{LRI}{text}{PDI}"


@pytest.mark.parametrize(
    "size_bytes, expected",
    [
        # ערך שלם — בלי נקודה ובלי אפס אחריה
        (0, "0 B"),
        (3, "3 B"),
        (582, "582 B"),
        (4 * KB, "4 KB"),
        (105 * KB, "105 KB"),
        (MB, "1 MB"),
        (5 * GB, "5 GB"),
        # שבר אמיתי — נשאר
        (28569, "27.9 KB"),
        (1536 * KB, "1.5 MB"),
        # חצי מדויק עולה. 1280 בתים הם 1.25 KB בדיוק, וזה הערך שחשף את הפער
        # בין ``:.1f`` (חצי לזוגי) ל-``toFixed`` (חצי כלפי מעלה).
        (1280, "1.3 KB"),
        # התקרה: מעל TB הערך גדל ואינו מקבל יחידה חדשה
        (2 * 1024 * GB, "2 TB"),
        (3 * 1024 * 1024 * GB, "3072 TB"),
    ],
)
def test_size_is_formatted_by_the_shared_rule(size_bytes, expected):
    assert format_file_size(size_bytes) == wrapped(expected)


def test_value_is_wrapped_in_bidi_isolation():
    """בלי העטיפה הזו ``105 KB`` מתהפך ל-``KB 105`` בתוך כרטיס בעברית."""
    result = format_file_size(105 * KB)

    assert result.startswith(LRI), "חסר תו פתיחה של בידוד"
    assert result.endswith(PDI), "חסר תו סגירה של בידוד"
    assert ord(LRI) == 0x2066 and ord(PDI) == 0x2069
    # החיפוש הנפוץ ביותר על הערך עדיין עובד — העטיפה אינה שוברת ``in``
    assert "105 KB" in result


def test_non_finite_size_is_treated_as_zero():
    """בלי זה ``nan`` היה נופל דרך כל היחידות ומגיע כ-``"nan TB"``."""
    assert format_file_size(float("nan")) == wrapped("0 B")
    assert format_file_size(float("inf")) == wrapped("0 B")


def test_number_helper_trims_only_a_zero_fraction():
    assert format_size_number(105.0) == "105"
    assert format_size_number(27.94) == "27.9"
    # חצי מדויק עולה, בשתי השפות. נמדד, לא הונח.
    assert format_size_number(1.25) == "1.3"
    assert format_size_number(2.5) == "2.5"
    # 0.95 הוא בפועל 0.9499..., אבל הכפל ב-10 מחזיר בדיוק 9.5 ולכן הוא עולה.
    # בפועל אינו מגיע: ערך קטן מ-1 נכנס לכאן רק כשהגודל קטן מ-1024, ואז הוא
    # מספר שלם של בתים.
    assert format_size_number(0.95) == "1"


def test_negative_size_keeps_its_sign():
    assert format_size_number(-5.0) == "-5"
    assert format_size_number(-0.0) == "0"


def test_files_page_formatter_uses_the_shared_rule():
    """``webapp/app.py`` הוא מה שמזין את כרטיסי הקבצים בתבנית."""
    from webapp.app import format_file_size as page_formatter

    assert page_formatter(105 * KB) == wrapped("105 KB")
    assert page_formatter(582) == wrapped("582 B")
    assert page_formatter(28569) == wrapped("27.9 KB")


def test_collection_item_formatter_uses_the_shared_rule_and_keeps_none():
    """באוספים ``None`` הוא חוזה של הקוראים ולא כלל תצוגה — הוא נשמר."""
    from webapp.collections_api import _format_size

    assert _format_size(105 * KB) == wrapped("105 KB")
    assert _format_size(28569) == wrapped("27.9 KB")
    assert _format_size(None) is None
    assert _format_size("not-a-number") is None


# ---------------------------------------------------------------------------
# ההסכמה בין שני המימושים
# ---------------------------------------------------------------------------

#: הווקטור מכסה גבולות יחידה, חצאים מדויקים (שם שתי השפות נוטות להיפרד),
#: ערכים שליליים, וכל סדרי הגודל עד מעבר לתקרה.
PARITY_VALUES = (
    [0, 1, 2, 512, 582, 1023, 1024, 1025, 1280, 4096, 107520, 28569]
    + [MB - 1, MB, 1536 * KB, GB - 1, GB, 2 * GB, 1024 * GB, 3 * 1024 * 1024 * GB]
    + [int((1 + half / 100) * KB) for half in range(5, 100, 10)]
    + [(1 + half / 100) * MB for half in range(5, 100, 10)]
    + [-5, -1024]
)


@pytest.mark.skipif(shutil.which("node") is None, reason="node לא זמין להרצת קוד הצד-לקוח")
def test_javascript_twin_returns_exactly_the_same_strings():
    """מריץ את ``utils/size-format.js`` האמיתי ומשווה ערך מול ערך.

    הקובץ נטען כמו בדפדפן — script קלאסי שמגדיר ``window.SizeFormat`` — כי
    ``package.json`` מוגדר ``"type": "module"`` ולכן ``require`` רגיל עליו
    לא היה עובד.

    ``process.argv[1]`` ולא ``[2]``: ב-``node -e`` אין משבצת לשם קובץ סקריפט,
    ולכן הארגומנטים מתחילים מיד אחרי נתיב ה-node. אומת בהרצה
    (``node -e '...' -- foo bar`` מחזיר ``[node, foo, bar]``).
    """
    harness = """
      const fs = require('fs'), vm = require('vm');
      const sandbox = { window: {} };
      vm.createContext(sandbox);
      vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
      const values = JSON.parse(process.argv[2]);
      console.log(JSON.stringify(values.map(sandbox.window.SizeFormat.formatFileSize)));
    """
    result = subprocess.run(
        ["node", "-e", harness, "--", str(JS_MODULE), json.dumps(PARITY_VALUES)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"node נכשל:\n{result.stderr}"

    from_js = json.loads(result.stdout)
    from_py = [format_file_size(v) for v in PARITY_VALUES]

    mismatches = [
        f"  {value!r}: python={py!r} js={js!r}"
        for value, py, js in zip(PARITY_VALUES, from_py, from_js)
        if py != js
    ]
    assert not mismatches, (
        "שני המימושים נפרדו — אותו קובץ יוצג אחרת מהשרת ומהדפדפן:\n"
        + "\n".join(mismatches)
    )
