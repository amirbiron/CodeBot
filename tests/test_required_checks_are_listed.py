"""שמות הסטטוסים של ``unit-tests`` כתובים בכל רשימה של בדיקות החובה — ורק הם.

הבעלים הוא ``.github/workflows/ci.yml``: כל מסלול של הג'וב ``unit-tests`` מדווח סטטוס
חובה, ושמו נבנה מהמטריצה (``STATUS_CONTEXT`` בצעדי "Report required status"). אותם
שמות כתובים ביד ברשימות שאנשים וסוכנים קוראים לפני מיזוג, ורשימה שלא עודכנה אומרת
ש-PR מוכן בזמן שמסלול שלם עוד לא דיווח. לכן הטסט גוזר את השמות מהמטריצה עצמה — גם
את התבנית שלהם — ובודק כל רשימה בשני הכיוונים: שכל שם מופיע בה, ושאין בה שם של
``Unit Tests`` שהמטריצה כבר לא מייצרת.

עמוד שרק צריך להזכיר את הרשימה מפנה ל-``docs/ci-cd.rst`` במקום להחזיק עותק, ולכן
אינו כאן. קובץ שכן מחזיק עותק בלי להיות ב-``LISTS`` נתפס ב-
``test_every_file_that_names_a_unit_tests_status_is_checked``, שמחפש שמות של סטטוסים
בכל הקבצים שבמעקב של git — כי גם ``LISTS`` נכתבת ביד, ועותק שנשכח ממנה לא היה נבדק.

ובנוסף, מה שהמסלולים עצמם נשענים עליו:

- **הביטויים של המסלולים משלימים זה את זה** (``marker`` במטריצה). טסט שאף מסלול לא
  בוחר אינו רץ ב-CI בכלל, ואיש לא מקבל על כך הודעה.
- **מסלול שלא נבחר בו אף טסט נכשל.** זה מה שתופס שם סימון ששונה ב-``ci.yml`` בלי
  הטסטים, או בכל הטסטים בלי ``ci.yml``: המסלול הכבד היה בוחר אפס טסטים. pytest יוצא אז
  בקוד ``ExitCode.NO_TESTS_COLLECTED``, וה-CI נשען על זה, ולכן זה מקובע כאן ולא רק כתוב.
  טסט בודד שהסימון שלו חסר או שגוי אינו נתפס כך, וגם לא צריך: הוא רץ במסלול הרגיל.
- **לכל מסלול יש גרסה שמודדת coverage**, ודגלי ה-coverage וההעלאה ל-Codecov תלויים שניהם
  במפתח ``coverage`` של המטריצה. Codecov אינו בדיקת חובה, ולכן כיסוי שנעלם לא היה מפיל דבר.
"""

from __future__ import annotations

import itertools
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

#: כל קובץ שמחזיק רשימה של בדיקות החובה, יחסית לשורש הריפו.
LISTS = (
    Path("docs") / "ci-cd.rst",
    Path(".github") / "pull_request_template.md",
    Path(".github") / "CONTRIBUTING.md",
    Path(".github") / "agents" / "my-agent.agent.md",
    Path(".cursorrules"),
)

#: קבצים שמזכירים שמות של סטטוסים בלי להיות רשימה שפועלים לפיה, ולכן אינם נבדקים מול
#: המטריצה. לכל קובץ הסיבה שלו.
SNAPSHOTS = {
    Path("FEATURE_SUGGESTIONS") / "DOCUMENTATION_NEEDS.md": (
        "מסמך הצעות לתוכן של אתר התיעוד: הרשימות בו הן הטקסט שהוצע בזמנו, לא מקור שפועלים לפיו"
    ),
}

#: ביטוי של GitHub Actions שקורא ערך מהמטריצה, כמו ``${{ matrix.label }}``.
_MATRIX_EXPRESSION = re.compile(r"\$\{\{\s*matrix\.([\w-]+)\s*\}\}")

#: שם סטטוס של ``Unit Tests`` עם גרסת פייתון אחת. הצורה המסכמת ``Unit Tests (3.11/3.12)``
#: אינה שם של סטטוס, ולכן אינה נתפסת כאן.
_UNIT_STATUS = re.compile(r"Unit Tests(?: [\w-]+)? \(\d+\.\d+\)")

#: השורה בסקריפט של צעד דיווח ששולחת את ``STATUS_CONTEXT`` כשם הסטטוס.
_SENDS_STATUS_CONTEXT = re.compile(r"\bcontext:\s*process\.env\.STATUS_CONTEXT\b")

#: ביטוי ``-m`` שהוא שם של סימון אחד, בלי ``not``, ``and`` או סוגריים.
_BARE_MARKER = re.compile(r"\w+")

#: הביטוי בפקודת ה-pytest שמוסיף את דגלי ה-coverage רק כש-``matrix.coverage`` דלוק.
_COVERAGE_FLAGS = re.compile(r"\$\{\{\s*matrix\.coverage\s*&&\s*'([^']*)'\s*\|\|\s*''\s*\}\}")


def _unit_tests_job() -> dict:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["unit-tests"]


def _status_template(job: dict) -> str:
    """התבנית של שם הסטטוס, כפי שכתובה ב-``STATUS_CONTEXT`` של צעדי הדיווח.

    כל צעדי הדיווח חייבים להשתמש באותה תבנית, ובתבנית של ``name`` של הג'וב: אחרת
    מסלול אחד היה מדווח בשם שהרשימות אינן מכירות. וכל צעד חייב גם לשלוח אותה:
    ``STATUS_CONTEXT`` ב-env שהסקריפט לא קורא הוא קישוט, וסקריפט שבונה את השם בעצמו מגרסת
    הפייתון בלבד (כמו שהיה כאן לפני המסלולים) היה כותב מכל המסלולים של אותה גרסה על אותו
    סטטוס. צעד שחסר לו אחד מהשניים נכשל בהודעה שאומרת מה חסר בו, ולא ב-``KeyError``.
    """
    steps = [
        step for step in job["steps"] if str(step.get("name", "")).startswith("Report required status")
    ]
    assert steps, "לא נמצאו צעדי 'Report required status' ב-unit-tests"
    templates = set()
    for step in steps:
        env = step.get("env") or {}
        assert "STATUS_CONTEXT" in env, f"לצעד {step['name']!r} אין STATUS_CONTEXT ב-env"
        script = str((step.get("with") or {}).get("script", ""))
        assert _SENDS_STATUS_CONTEXT.search(script), (
            f"הצעד {step['name']!r} אינו שולח את STATUS_CONTEXT כשם הסטטוס "
            "(context: process.env.STATUS_CONTEXT)"
        )
        templates.add(env["STATUS_CONTEXT"])
    assert len(templates) == 1, f"צעדי הדיווח בונים את שם הסטטוס בתבניות שונות: {sorted(templates)}"
    template = templates.pop()
    assert template == job["name"], (
        f"שם הסטטוס ({template!r}) ושם הג'וב ({job['name']!r}) אמורים להיבנות באותה תבנית"
    )
    return template


def _matrix_combinations(job: dict) -> list[dict]:
    """כל צירוף של המטריצה, עם המפתחות ש-``include`` מוסיף לו.

    לפי הכלל של GitHub (``jobs.<job_id>.strategy.matrix.include`` ב-``workflow-syntax.md``):
    רשומה מתווספת לכל צירוף שאף זוג מפתח-ערך שלה אינו דורס בו ערך מקורי של המטריצה, ומפתח
    שרשומה קודמת הוסיפה מותר לדרוס. רשומה שאינה מתאימה לאף צירוף יוצרת אצל GitHub צירוף
    חדש — מסלול שלם, שאין לו שם ברשימות של בדיקות החובה — ולכן כאן היא נכשלת ולא נפרשת
    בניחוש. מאותה סיבה הטסט גם אינו פורש ``exclude``, ונכשל עליו.
    """
    matrix = job["strategy"]["matrix"]
    assert "exclude" not in matrix, (
        "המטריצה של unit-tests משתמשת ב-exclude, והטסט אינו יודע לפרוש אותו. לפני שמוסיפים "
        "exclude, הוסיפו ל-_matrix_combinations את הכלל של GitHub: הצירופים ש-exclude מתאר מוסרים, "
        "ורק אחר כך include מעובד"
    )
    axes = {key: values for key, values in matrix.items() if key != "include"}
    for key, values in axes.items():
        assert isinstance(values, list), f"ציר המטריצה {key!r} אינו רשימה של ערכים: {values!r}"
    combinations = [dict(zip(axes, values)) for values in itertools.product(*axes.values())]
    for entry in matrix.get("include", []):
        targets = [
            combination
            for combination in combinations
            if all(combination[key] == value for key, value in entry.items() if key in axes)
        ]
        assert targets, f"רשומת include שאינה מתאימה לאף צירוף, ולכן הייתה יוצרת מסלול חדש: {entry!r}"
        for combination in targets:
            combination.update({key: value for key, value in entry.items() if key not in axes})
    return combinations


def _expected_statuses() -> set[str]:
    job = _unit_tests_job()
    template = _status_template(job)
    names = set()
    for combination in _matrix_combinations(job):
        missing = sorted(set(_MATRIX_EXPRESSION.findall(template)) - set(combination))
        assert not missing, f"למסלול {combination!r} אין במטריצה את מה ששם הסטטוס בנוי ממנו: {missing}"
        name = _MATRIX_EXPRESSION.sub(lambda match: combination[match.group(1)], template)
        assert "${{" not in name, f"נשאר ביטוי שהטסט אינו יודע לפרוש: {name!r}"
        names.add(name)
    return names


def _lane_markers() -> dict[str, str]:
    """ביטוי ה-``-m`` של כל מסלול (``matrix.marker``), לפי ``suite``."""
    markers = {}
    for combination in _matrix_combinations(_unit_tests_job()):
        assert "marker" in combination, f"למסלול {combination['suite']!r} אין marker במטריצה"
        markers[combination["suite"]] = combination["marker"]
    return markers


def _bare_lane_markers(markers: dict[str, str]) -> list[str]:
    """הביטויים שהם סימון אחד בלבד — כלומר מסלול שבוחר טסטים לפי סימון, ולא לפי היעדרו."""
    return sorted({marker for marker in markers.values() if _BARE_MARKER.fullmatch(marker)})


def _tracked_files_naming_a_unit_tests_status() -> set[Path]:
    """כל קובץ במעקב של git שמופיע בו שם של סטטוס ``Unit Tests``.

    ``git grep`` על הקידומת שמשותפת לכל השמות רק בוחר מועמדים, וההכרעה היא של
    ``_UNIT_STATUS`` — כך שהצורה של שם סטטוס מוגדרת במקום אחד, ולא פעם בפייתון ופעם
    בתחביר של git. הדגלים, לפי ``Documentation/git-grep.txt`` ב-git 2.43: ``-l`` שמות
    הקבצים בלבד, ``-z`` כל שם מסתיים ב-``\\0`` ומודפס כמו שהוא, ``-I`` בלי קבצים בינאריים,
    ``-F`` מחרוזת ולא ביטוי. קוד היציאה הוא ``!hit`` (``builtin/grep.c``), כלומר 1 הוא
    "אף קובץ". כל קוד אחר — למשל 128 מחוץ לעבודה של git — הוא כשל ולא תשובה. וכש-git
    לא מותקן בכלל, ``subprocess`` מעלה ``FileNotFoundError`` עם שם התוכנה (``_execute_child``
    ב-``Lib/subprocess.py`` של CPython 3.12). בשני המקרים הטסט נכשל ולא מדלג, בהודעה
    שאומרת מה חסר: בלי git הוא לא בדק כלום.
    """
    try:
        proc = subprocess.run(
            ["git", "grep", "-z", "-l", "-I", "-F", "Unit Tests"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise AssertionError(
            f"git לא נמצא ({exc}). הטסט מוצא את העותקים של הרשימה דרך git grep, ובלעדיו לא בדק כלום"
        ) from exc
    assert proc.returncode in (0, 1), f"git grep נכשל (קוד {proc.returncode}): {proc.stderr.strip()}"
    found = set()
    for name in proc.stdout.split("\0"):
        # errors="replace": מחפשים שם שכולו ASCII, ובית שאינו UTF-8 במקום אחר בקובץ לא
        # משנה את ההתאמה.
        if name and _UNIT_STATUS.search((ROOT / name).read_text(encoding="utf-8", errors="replace")):
            found.add(Path(name))
    return found


def test_the_status_names_come_from_the_matrix_of_unit_tests():
    """הבסיס לטסטים שאחריו: כל מסלול מקבל שם משלו, ו-``_UNIT_STATUS`` מזהה כל שם."""
    job = _unit_tests_job()
    names = _expected_statuses()
    assert len(names) == len(_matrix_combinations(job)), f"שני מסלולים מדווחים באותו שם: {sorted(names)}"
    assert all(_UNIT_STATUS.fullmatch(name) for name in names), (
        f"שם סטטוס שהביטוי של הטסט אינו מזהה, ולכן לא היה נבדק ברשימות: {sorted(names)}"
    )


def test_every_list_of_required_checks_names_every_unit_tests_status():
    """רשימה שחסר בה מסלול אומרת ש-PR מוכן בזמן שהמסלול הזה לא נבדק."""
    expected = _expected_statuses()
    missing = []
    for relative in LISTS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        missing.extend(f"{relative.as_posix()}: {name}" for name in sorted(expected) if name not in text)
    assert not missing, "חסרים ברשימות של בדיקות החובה:\n" + "\n".join(missing)


def test_no_list_of_required_checks_names_a_unit_tests_status_that_ci_does_not_report():
    """שם שהמטריצה כבר לא מייצרת הוא בדיקה שלעולם לא תדווח — ו-PR שמחכה לה לא יתמזג."""
    expected = _expected_statuses()
    stale = []
    for relative in LISTS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        stale.extend(
            f"{relative.as_posix()}: {match.group(0)}"
            for match in _UNIT_STATUS.finditer(text)
            if match.group(0) not in expected
        )
    assert not stale, "שמות שה-CI אינו מדווח:\n" + "\n".join(stale)


def test_every_file_that_names_a_unit_tests_status_is_checked():
    """עותק של הרשימה בקובץ שאינו ב-``LISTS`` היה מתיישן בלי שאיש ידע.

    כך בדיוק קרה כשהמסלול ``md-heavy`` נוסף: הקבצים של ``LISTS`` נאספו בחיפוש ידני,
    וחלק מהעותקים לא עלו בו. לכן הטסט מחפש בעצמו, בכל הקבצים שבמעקב. קובץ שנמצא צריך
    אחד משלושה: להיכנס ל-``LISTS`` ולהיבדק, להפנות ל-``docs/ci-cd.rst`` במקום להחזיק
    עותק, או — כשהוא תמונת מצב ולא רשימה שפועלים לפיה — להיכנס ל-``SNAPSHOTS`` עם
    הסיבה. ובכיוון ההפוך: פטור לקובץ שכבר לא מזכיר אף סטטוס הוא פטור מת.
    """
    found = _tracked_files_naming_a_unit_tests_status()
    unchecked = sorted(path.as_posix() for path in found - set(LISTS) - set(SNAPSHOTS))
    assert not unchecked, (
        "קבצים שמזכירים סטטוס של Unit Tests ואינם נבדקים מול המטריצה. הוסיפו אותם ל-LISTS, "
        "החליפו את העותק בהפניה ל-docs/ci-cd.rst, או — אם זו תמונת מצב — הוסיפו אותם "
        "ל-SNAPSHOTS עם הסיבה:\n" + "\n".join(unchecked)
    )
    dead = sorted(path.as_posix() for path in set(SNAPSHOTS) - found)
    assert not dead, "פטורים לקבצים שכבר לא מזכירים אף סטטוס — הסירו אותם מ-SNAPSHOTS:\n" + "\n".join(dead)


def test_the_lanes_split_the_suite_into_two_complementary_halves():
    """טסט שאף מסלול לא בוחר אינו רץ ב-CI בכלל, ואיש לא מקבל על כך הודעה.

    לכן נדרשת הצורה היחידה שהטסט יודע לבדוק: שני מסלולים, אחד בוחר סימון אחד והשני בוחר
    בדיוק ``not`` אותו סימון. כך כל טסט נבחר במסלול אחד בדיוק. מי שמשנה את הצורה — מסלול
    שלישי, ביטוי מורכב — מעדכן כאן את בדיקת החלוקה, ולא רק את ``ci.yml``.
    """
    markers = _lane_markers()
    bare = _bare_lane_markers(markers)
    assert len(markers) == 2 and len(bare) == 1 and set(markers.values()) == {bare[0], f"not {bare[0]}"}, (
        "הביטויים של המסלולים אינם שני חצאים משלימים (X ו-not X), ולכן טסט יכול להישאר בלי "
        f"מסלול ולא לרוץ ב-CI בכלל: {markers}"
    )


def test_coverage_is_measured_in_every_suite_and_only_where_the_matrix_says():
    """coverage נמדד רק בחלק מהמסלולים, ו-Codecov אינו בדיקת חובה — כיסוי שנעלם לא מפיל דבר.

    המפתח ``coverage`` במטריצה קובע איפה הוא נמדד, ושני צעדים קוראים אותו: פקודת ה-pytest
    (הדגלים ``--cov``) וההעלאה ל-Codecov. הטסט בודק את שלושתם יחד: שלכל suite יש מסלול
    שמודד coverage, אחרת הטסטים שלו אינם בדוח; שהדגלים נמצאים רק בתוך הביטוי שתלוי
    ב-``matrix.coverage``; ושההעלאה תלויה בו. ערך שאינו ``true``/``false`` נכשל גם הוא: מחרוזת
    כמו ``'false'`` אינה בין הערכים ש-GitHub מחשיב כשקר (expressions בתיעוד של GitHub
    Actions), ולכן הייתה מדליקה את ה-coverage.
    """
    job = _unit_tests_job()
    combinations = _matrix_combinations(job)
    for combination in combinations:
        assert isinstance(combination.get("coverage", False), bool), (
            f"coverage במטריצה אינו true/false: {combination!r}"
        )
    suites = {combination["suite"] for combination in combinations}
    covered = {combination["suite"] for combination in combinations if combination.get("coverage")}
    assert covered == suites, f"מסלולים שאין להם אף גרסה שמודדת coverage: {sorted(suites - covered)}"

    runs = [str(step["run"]) for step in job["steps"] if "pytest" in str(step.get("run", ""))]
    assert len(runs) == 1, f"צפוי צעד אחד שמריץ pytest ב-unit-tests, נמצאו {len(runs)}"
    flags = _COVERAGE_FLAGS.findall(runs[0])
    assert len(flags) == 1 and "--cov=" in flags[0] and "--cov-report=xml" in flags[0], (
        f"דגלי ה-coverage אינם בביטוי אחד שתלוי ב-matrix.coverage ומפיק coverage.xml:\n{runs[0]}"
    )
    assert "--cov" not in _COVERAGE_FLAGS.sub("", runs[0]), (
        f"--cov מחוץ לביטוי של matrix.coverage, ולכן נמדד בכל המסלולים:\n{runs[0]}"
    )

    uploads = [step for step in job["steps"] if str(step.get("uses", "")).startswith("codecov/codecov-action")]
    assert len(uploads) == 1, f"צפוי צעד העלאה אחד ל-Codecov ב-unit-tests, נמצאו {len(uploads)}"
    assert "matrix.coverage" in str(uploads[0].get("if", "")), (
        f"ההעלאה ל-Codecov אינה תלויה ב-matrix.coverage: {uploads[0].get('if')!r}"
    )


#: ``1 deselected`` בסיכום של ריצה בלי ``-n`` מראה שהטסט נאסף ואז סונן, ולכן קוד היציאה
#: בא מהסינון ולא מקובץ שאין בו טסטים. תחת ``-n`` ה-controller מסכם ``no tests ran`` בלי
#: לספור את מה שסונן ב-workers (נמדד ב-pytest-xdist 3.8.0), ושם אותו קובץ ואותו ביטוי
#: מספיקים: הריצה בלי ``-n`` כבר הראתה שיש בו טסט שנאסף.
_SERIAL_SUMMARY = "1 deselected"


@pytest.mark.parametrize(
    ("workers", "summary"), [([], _SERIAL_SUMMARY), (["-n", "2"], None)], ids=["serial", "xdist"]
)
def test_a_lane_whose_marker_selects_no_test_fails(tmp_path, workers, summary):
    """pytest יוצא ב-``ExitCode.NO_TESTS_COLLECTED`` כש-``-m`` סינן את כל הטסטים, וגם תחת ``-n``.

    על זה נשען ה-CI כשהמסלול הכבד בוחר אפס טסטים. נמדד ב-pytest 8.4.2: ``_main`` ב-
    ``_pytest/main.py`` מחזיר את הקוד הזה כש-``testscollected`` הוא 0, והוא נקבע אחרי הסינון
    (ותחת ``-n`` ב-``xdist/dsession.py``, ממה שה-workers אספו). הסימון נלקח מהמטריצה, כך שזה
    הביטוי שהמסלול באמת מריץ. הריצה הפנימית היא ב-``tmp_path`` עם ``pytest.ini`` משלה, ולכן
    ה-``conftest`` וה-``addopts`` של הריפו אינם נטענים בה.
    """
    if workers:
        pytest.importorskip("xdist")
    bare = _bare_lane_markers(_lane_markers())
    assert len(bare) == 1, f"אין למסלול הכבד סימון אחד שבוחרים בו לבד: {bare}"
    marker = bare[0]
    (tmp_path / "pytest.ini").write_text(f"[pytest]\nmarkers =\n    {marker}: inner\n", encoding="utf-8")
    (tmp_path / "test_inner.py").write_text("def test_unmarked():\n    pass\n", encoding="utf-8")

    finished = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *workers, "-m", marker, "test_inner.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = finished.stdout + finished.stderr

    assert finished.returncode == pytest.ExitCode.NO_TESTS_COLLECTED, (
        f"מסלול שלא נבחר בו אף טסט יצא בקוד {finished.returncode}, ולכן היה עובר ריק:\n{output}"
    )
    if summary is not None:
        assert summary in output, f"הטסט הפנימי לא נאסף ואז סונן, ולכן הקוד לא הוכיח כלום:\n{output}"
