"""תקרת הזמן חייבת להפיל את הבדיקה בשמה, לא להרוג את התהליך שמריץ אותה.

**למה יש קובץ שלם על שורה שאינה קיימת ב-``pytest.ini``.** עד לתיקון היה
כתוב שם ``timeout_method = thread``, ובשיטה הזאת ``pytest_timeout`` קורא
``os._exit(1)``. כלומר בדיקה שחורגת אינה נכשלת אלא הורגת את התהליך —
ותחת ``xdist`` ה-controller רק רואה תהליך שנעלם ומדפיס
``node down: Not properly terminated``, בלי שם הבדיקה ובלי מחסנית, כי
ה-worker כותב אותן ל-stderr שלו ויוצא לפני שהפלט נשטף.

**וזה קרה פעמיים בפרודקשן של ה-CI הזה.** פעם אחת על ``gw5``, מתועדת
ב-``tests/test_get_db_publishes_after_connect.py``, ופעם שנייה על ``gw0``:
ריצה נתקעה על 99% ונשרפו בה עשרים דקות עד ביטול ידני. בשני המקרים
ההודעה לא נקבה בשם הבדיקה, ובשני המקרים היה צריך לחפור בלוג כדי לדעת
מי חרג.

**הקובץ הזה קיים כדי שהשורה לא תחזור בשקט**, ולכן הוא בודק את שני
הצדדים: שהתצורה בריפו אינה בוחרת את השיטה ההרסנית, ושההתנהגות בפועל
היא כישלון עם שם ולא מוות של תהליך.
"""

from __future__ import annotations

import configparser
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: התקרה בבדיקות שלהלן. קטנה בכוונה — המנגנון זהה לזה של 60 השניות
#: שב-``pytest.ini``, והבדיקה לא אמורה להיות זו שתולה את הסוויטה.
_INNER_TIMEOUT = 2

#: תקציב לתת-התהליך. גדול מ-``_INNER_TIMEOUT`` בהרבה כדי שהוא ימות
#: מהתקרה הפנימית ולא מהחיתוך הזה — אחרת הבדיקה הייתה מודדת את
#: ``subprocess`` ולא את ``pytest-timeout``.
_OUTER_BUDGET = 90


def _resolved_timeout_method() -> str:
    """השיטה ש-``pytest-timeout`` ייקח בפועל לריצה בריפו הזה.

    **נגזרת מהקובץ ומהתוסף, ולא מהשוואה למחרוזת.** בדיקה שרק מאמתת
    ש-``timeout_method`` נעדר מ-``pytest.ini`` מקבעת את האות ולא את
    המשמעות, והיא תעבור בשקט גם אם יום אחד ברירת המחדל של התוסף תשתנה
    ל-``thread``. כאן נשאלת השאלה שבאמת חשובה: מה ירוץ.
    """
    pytest_timeout = pytest.importorskip("pytest_timeout")

    parser = configparser.ConfigParser()
    parser.read(_REPO_ROOT / "pytest.ini", encoding="utf-8")
    declared = parser.get("pytest", "timeout_method", fallback="").strip()

    return declared or pytest_timeout.DEFAULT_METHOD


def test_the_repository_does_not_choose_the_method_that_kills_the_process():
    """התצורה בריפו אינה בוחרת ``thread``, וגם יש לה תקרה בכלל.

    שתי הטענות נחוצות: תקרה בלי שיטה בטוחה מוחקת את הראיה, ושיטה בטוחה
    בלי תקרה אינה עוצרת תקיעה בכלל.
    """
    parser = configparser.ConfigParser()
    parser.read(_REPO_ROOT / "pytest.ini", encoding="utf-8")

    assert parser.get("pytest", "timeout", fallback="").strip(), (
        "אין תקרת זמן ב-pytest.ini — תקיעה ב-CI תרוץ עד תקציב ה-job"
    )
    assert _resolved_timeout_method() != "thread", (
        "השיטה שתרוץ היא thread, וזו זו שקוראת os._exit ומוחקת את שם הבדיקה"
    )


@pytest.mark.skipif(
    _resolved_timeout_method() != "signal",
    reason="ההתנהגות שנבדקת כאן היא של שיטת signal בלבד",
)
def test_a_test_that_exceeds_the_ceiling_fails_by_name_and_the_next_one_still_runs(
    tmp_path,
):
    """הראיה ההתנהגותית, בתת-תהליך: כישלון עם שם, והריצה ממשיכה.

    **תת-תהליך ולא ``pytest.raises``**, כי מה שנבדק הוא מה שקורה
    לריצה **כולה** כשבדיקה חורגת — האם יש שורת סיכום, והאם הבדיקה
    שאחריה בכלל רצה. שתי השאלות אינן ניתנות לשאילה מתוך אותה ריצה.

    כל הכתיבה תחת ``tmp_path``, ואין נגיעה בשורש הפרויקט. ``rootdir``
    של הריצה הפנימית הוא ``tmp_path``, ולכן ``addopts`` ו-``conftest``
    של הריפו אינם נטענים והבדיקה מודדת את המנגנון בלבד.
    """
    (tmp_path / "pytest.ini").write_text(
        f"[pytest]\ntimeout = {_INNER_TIMEOUT}\n", encoding="utf-8"
    )
    (tmp_path / "test_inner.py").write_text(
        "import time\n"
        "\n"
        "def test_that_hangs():\n"
        f"    time.sleep({_INNER_TIMEOUT * 5})\n"
        "\n"
        "def test_that_comes_after():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    finished = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_inner.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=_OUTER_BUDGET,
    )
    output = finished.stdout + finished.stderr

    assert "test_that_hangs" in output, f"שם הבדיקה שחרגה אינו בפלט:\n{output}"
    assert "1 failed" in output, f"החריגה לא דווחה ככישלון:\n{output}"
    assert "1 passed" in output, (
        f"הבדיקה שאחרי החורגת לא רצה — כלומר התהליך מת:\n{output}"
    )


def test_the_destructive_method_is_what_this_file_protects_against(tmp_path):
    """אותו קלט תחת ``thread`` — התהליך מת, ואין שורת סיכום.

    **זו המוטציה, והיא חלק מהבדיקה ולא הערה בצד.** בלי הבדיקה הזאת אין
    ראיה שהבדיקה שמעליה מסוגלת להיכשל: היא הייתה עוברת גם אילו
    ``pytest-timeout`` לא היה מותקן בכלל, כי אז שום דבר לא חורג ושתי
    הבדיקות הפנימיות היו עוברות — ואז ``1 passed`` היה מתקיים ו-
    ``1 failed`` לא. כאן נמדד ההפרש בין שתי השיטות על אותו קלט בדיוק.
    """
    (tmp_path / "pytest.ini").write_text(
        f"[pytest]\ntimeout = {_INNER_TIMEOUT}\ntimeout_method = thread\n",
        encoding="utf-8",
    )
    (tmp_path / "test_inner.py").write_text(
        "import time\n"
        "\n"
        "def test_that_hangs():\n"
        f"    time.sleep({_INNER_TIMEOUT * 5})\n"
        "\n"
        "def test_that_comes_after():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    finished = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_inner.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=_OUTER_BUDGET,
    )
    output = finished.stdout + finished.stderr

    assert "1 failed" not in output, (
        f"שיטת thread כן דיווחה כישלון — ההנחה שכל הקובץ נשען עליה שגויה:\n{output}"
    )
    assert "1 passed" not in output, (
        f"הבדיקה שאחרי החורגת כן רצה תחת thread — התהליך לא מת:\n{output}"
    )
