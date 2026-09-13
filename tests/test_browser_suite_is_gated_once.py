"""בדיקות הדפדפן מכריעות **פעם אחת** אם יש דפדפן, ואומרות בקול שדילגו.

**מה זה בא למנוע.** "יש דפדפן או אין" היא עובדה אחת על הסביבה, קבועה
לאורך כל הריצה. עד לתיקון היא נגזרה מחדש בכל בדיקה, וכל גזירה עברה דרך
הרמת תהליך דרייבר של Playwright ותפיסת חריגה. נמדד על שבעת קובצי
הדפדפן כשאין דפדפן: **66 בדיקות, 28.50 שניות, 66 הרמות של תהליך
דרייבר, ואפס בדיקות שרצו.** אחרי התיקון: 0.85 שניות והרמה אחת.

**והצורה ההיא לא רק בזבזה זמן.** מסלול שנשען על חריגה מטופל היטב
כשהחריגה נזרקת, ואינו מטופל בכלל כשהמסלול פשוט **אינו חוזר** — וזה
קרה: בריצת CI על פייתון 3.12 עשר בדיקות בקובץ אחד דולגו כרגיל ואחת לא
חזרה, חצתה את התקרה והרגה עובד xdist שלם. אותה בדיקה בדיוק דולגה על
פייתון 3.11 באותה ריצה ועל אותו קוד.

**שתי הבדיקות הראשונות כאן הן בדיקות מקור, וזה מכוון.** התנהגות אפשר
לבדוק רק על מסלול שכבר קיים, ומה שצריך לתפוס הוא בדיוק הקובץ שעוד לא
נכתב: בדיקת דפדפן חדשה שתרים Chromium בעצמה ותעקוף את השער. זו אותה
צורה של הבדיקה ששומרת על מכל התקרה ב-``mcp_server/outline_scanners``.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TESTS_DIR = _REPO_ROOT / "tests"

#: שם הפיקסצ'ר שמכריע. כל בדיקת דפדפן חייבת להגיע אליו, ישירות או דרך
#: פיקסצ'ר שמבקש אותו.
_GATE = "chromium_executable"

#: הקריאה שמרימה דפדפן. מורכבת מחלקים כדי שהקובץ הזה לא יכיל אותה
#: כמחרוזת שלמה — אחרת הוא מתאים לעצמו בסריקה שלמטה, וזה נראה כמו
#: ממצא ואינו ממצא. ההחרגה המפורשת שם היא ההגנה השנייה.
_LAUNCH_CALL = "chromium" + ".launch"

#: תקציב לתת-התהליך בבדיקה ההתנהגותית. נמדד ב-0.85 שניות, והתקציב כאן
#: רחב פי כמה כדי שהבדיקה לא תהיה רועשת על ראנר עמוס — היא בודקת מה
#: נאמר, לא כמה זמן זה לקח.
_SUBPROCESS_BUDGET = 180


def _browser_test_files() -> list[Path]:
    """קובצי בדיקות הדפדפן. **תיקייה ריקה היא כישלון ולא דילוג.**"""
    found = sorted(_TESTS_DIR.glob("test_*_browser.py"))
    assert found, f"לא נמצאו קובצי בדיקות דפדפן תחת {_TESTS_DIR}"
    return found


def _gate_scope_in_conftest() -> str | None:
    """ה-``scope`` שהוכרז על הפיקסצ'ר, כפי שהוא כתוב במקור.

    **נקרא מה-AST ולא מתכונה של pytest, וזה מכוון.** ל-``scope`` יש
    תכונה פרטית על אובייקט הפיקסצ'ר, אבל שמה השתנה בין גרסאות pytest
    (``_pytestfixturefunction`` מול ``_fixture_function_marker``). בדיקה
    שנשענת עליה נשברת בשדרוג גרסה, ובמקרה הרע מחזירה ``None`` ונופלת
    בהודעה שאינה מסבירה דבר. המקור אינו זז.
    """
    tree = ast.parse((_TESTS_DIR / "conftest.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != _GATE:
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            for keyword in decorator.keywords:
                if keyword.arg != "scope":
                    continue
                # ``ast.Constant.value`` יכול להיות כל ליטרל, ולכן ההצרה
                # מפורשת: ``scope`` שאינו מחרוזת אינו scope תקין, וגם
                # ``mypy`` פוסל החזרה רחבה מהחתימה — וזו שגיאה חוסמת ב-CI.
                if isinstance(keyword.value, ast.Constant) and isinstance(
                    keyword.value.value, str
                ):
                    return keyword.value.value
        return None
    raise AssertionError(f"{_GATE} אינו מוגדר ב-tests/conftest.py")


def test_the_gate_is_decided_once_for_the_whole_session():
    """ה-``scope`` הוא ``session``, ובלעדיו כל התיקון מתאדה **בשקט**.

    זו הנקודה הרגישה: שינוי ה-``scope`` ל-``function`` אינו מפיל שום
    בדיקה קיימת ואינו משנה אף תוצאה — הוא רק מחזיר את 66 ההרמות ואת
    החלון שבו תקיעה יכולה לקרות. כלומר הרגרסיה הזאת אינה נראית בשום
    מקום אחר, ולכן היא נקבעת כאן.
    """
    assert _gate_scope_in_conftest() == "session", (
        "השער אינו session-scoped — ההכרעה חזרה להיות פעם לכל בדיקה"
    )


def test_every_browser_test_actually_requests_the_gate(tmp_path):
    """כל בדיקת דפדפן מגיעה לשער — נשאל **מ-pytest**, לא מהטקסט.

    **וזאת גרסה שנייה, אחרי שהראשונה נמצאה חסרת שיניים.** הניסוח
    הראשון סרק את המקור וחיפש את שם השער כמחרוזת. המוטציה — הסרת
    ``chromium_executable`` מהחתימה של ``live_server`` — **עברה אותו**,
    כי השם נשאר בקובץ בתוך הערה ובתוך ה-docstring. סורק נוכחות אינו
    מבדיל בין "מגיע" לבין "מוזכר".

    ``item.fixturenames`` הוא הסגור הטרנזיטיבי של הפיקסצ'רים, כלומר
    התשובה על "מה באמת יורץ" ולא על "מה כתוב". נמדד על הקובץ עם
    השרשרת העמוקה ביותר: כל 18 הבדיקות שם מגיעות לשער דרך
    ``page`` ← ``live_server`` ← ``chromium_executable``.

    ``--collect-only``, ולכן שום דפדפן אינו מורם והבדיקה זולה.
    """
    dump = tmp_path / "fixtures.json"
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "_dump_fixture_closure.py").write_text(
        "import json, os\n"
        "\n"
        "\n"
        "def pytest_collection_modifyitems(session, config, items):\n"
        "    closure = {\n"
        "        item.nodeid: sorted(getattr(item, 'fixturenames', []))\n"
        "        for item in items\n"
        "    }\n"
        "    with open(os.environ['FIXTURE_CLOSURE_DUMP'], 'w', encoding='utf-8') as fh:\n"
        "        json.dump(closure, fh)\n",
        encoding="utf-8",
    )

    environment = dict(
        os.environ,
        FIXTURE_CLOSURE_DUMP=str(dump),
        PYTHONPATH=str(plugin_dir) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    )
    finished = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-o", "addopts=",
            "--collect-only", "-q", "-p", "_dump_fixture_closure",
        ]
        + [path.relative_to(_REPO_ROOT).as_posix() for path in _browser_test_files()],
        cwd=_REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_BUDGET,
    )
    assert dump.exists(), (
        "האיסוף לא הגיע לתוסף:\n"
        f"{(finished.stdout + finished.stderr)[-3000:]}"
    )

    closure = json.loads(dump.read_text(encoding="utf-8"))
    assert closure, "לא נאספה אף בדיקת דפדפן"

    bypassing = sorted(node for node, fixtures in closure.items() if _GATE not in fixtures)
    assert bypassing == [], (
        f"בדיקות דפדפן שאינן מגיעות ל-{_GATE}, כלומר יכולות להרים דפדפן "
        f"בלי שההכרעה נעשתה: {bypassing}"
    )


def test_no_other_file_under_tests_launches_a_browser():
    """ואין מרים Chromium שאינו קובץ דפדפן ואינו השער עצמו.

    הבדיקה שמעליה מכסה את הקבצים ש**נאספים** כבדיקות דפדפן; זו תופסת
    קובץ חדש שיִיכתב במקום אחר לגמרי ולא ייקרא ``*_browser.py``, ולכן
    לא ייכנס לרשימה שם.
    """
    # הקובץ הזה מוחרג מהסריקה כי הוא **נוקב בדפוס שהוא מחפש**, ולכן הוא
    # מתאים לעצמו. זו אינה נוחות: אותה מלכודת בדיוק נתפסה כאן כבר פעם
    # אחת, בסריקת המקור ששומרת על מכל התקרה — שם הרג'קס מצא את ה-docstring
    # של עצמו. סורק שמוצא את עצמו נראה כמו ממצא ואינו ממצא.
    myself = Path(__file__).resolve()
    launchers = sorted(
        path.relative_to(_REPO_ROOT).as_posix()
        for path in _TESTS_DIR.rglob("*.py")
        if path.resolve() != myself
        and not path.name.endswith("_browser.py")
        and _LAUNCH_CALL in path.read_text(encoding="utf-8")
    )
    assert launchers == ["tests/conftest.py"], (
        "יש מרים Chromium שאינו קובץ דפדפן ואינו השער עצמו: "
        f"{launchers}"
    )


def test_a_run_without_a_browser_skips_everything_and_says_so_out_loud(tmp_path):
    """הצד ההתנהגותי: הכול מדולג, והריצה **אומרת** שהכיסוי אפס.

    **הדיווח הוא מה שנבדק כאן, ולא הדילוג.** גם לפני התיקון כל 66
    הבדיקות דולגו, ולכן ספירת הדילוגים לבדה אינה מבדילה בין לפני ואחרי.
    מה שכן מבדיל הוא שהריצה אומרת את זה: דילוג שקט של סוויטה שלמה נראה
    זהה לדילוג של בדיקה בודדת, ואי אפשר לענות על "האם בדיקות הדפדפן
    רצו בכלל?".

    ``PLAYWRIGHT_BROWSERS_PATH`` מכוון לתיקייה ריקה תחת ``tmp_path``,
    וזה משחזר את המצב ב-CI — שם אין שלב שמתקין דפדפן. אין כתיבה מחוץ
    ל-``tmp_path``, והריצה הפנימית היא תת-תהליך כדי שהדיווח ייבדק כפי
    שמשתמש רואה אותו.
    """
    empty_browsers = tmp_path / "no-browsers"
    empty_browsers.mkdir()

    environment = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(empty_browsers))
    finished = subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "-q"]
        + [path.relative_to(_REPO_ROOT).as_posix() for path in _browser_test_files()],
        cwd=_REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_BUDGET,
    )
    output = finished.stdout + finished.stderr

    assert " passed" not in output, (
        f"בדיקת דפדפן רצה למרות שאין דפדפן:\n{output[-3000:]}"
    )
    assert "skipped" in output, f"שום דבר לא דולג:\n{output[-3000:]}"
    assert "הכיסוי שלהן בריצה הזאת הוא אפס" in output, (
        f"הריצה לא אמרה שבדיקות הדפדפן דולגו:\n{output[-3000:]}"
    )
