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
"""

from __future__ import annotations

import itertools
import re
import subprocess
from pathlib import Path

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


def _unit_tests_job() -> dict:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["unit-tests"]


def _status_template(job: dict) -> str:
    """התבנית של שם הסטטוס, כפי שכתובה ב-``STATUS_CONTEXT`` של צעדי הדיווח.

    כל צעדי הדיווח חייבים להשתמש באותה תבנית, ובתבנית של ``name`` של הג'וב: אחרת
    מסלול אחד היה מדווח בשם שהרשימות אינן מכירות.
    """
    templates = {
        step["env"]["STATUS_CONTEXT"]
        for step in job["steps"]
        if str(step.get("name", "")).startswith("Report required status")
    }
    assert templates, "לא נמצאו צעדי 'Report required status' עם STATUS_CONTEXT ב-unit-tests"
    assert len(templates) == 1, f"צעדי הדיווח בונים את שם הסטטוס בתבניות שונות: {sorted(templates)}"
    template = templates.pop()
    assert template == job["name"], (
        f"שם הסטטוס ({template!r}) ושם הג'וב ({job['name']!r}) אמורים להיבנות באותה תבנית"
    )
    return template


def _matrix_combinations(job: dict) -> list[dict]:
    """כל צירוף של המטריצה, עם המפתחות ש-``include`` מוסיף לו.

    ב-``include`` כל רשומה נקשרת למסלול אחד לפי ``suite`` ומוסיפה לו מפתחות. זה
    המקרה היחיד שהטסט יודע לפרוש, ולכן הוא מוודא שזה המבנה ולא מנחש.
    """
    matrix = job["strategy"]["matrix"]
    versions = matrix["python-version"]
    suites = matrix["suite"]
    by_suite = {}
    for entry in matrix["include"]:
        assert entry.get("suite") in suites, f"רשומת include בלי suite מוכר: {entry!r}"
        assert "python-version" not in entry, f"רשומת include שמשנה גרסה: {entry!r}"
        assert entry["suite"] not in by_suite, f"שתי רשומות include לאותו suite: {entry!r}"
        by_suite[entry["suite"]] = entry
    assert set(by_suite) == set(suites), (
        f"לכל suite צריכה להיות רשומת include: יש {sorted(by_suite)}, צריך {sorted(suites)}"
    )
    return [
        {**by_suite[suite], "python-version": version, "suite": suite}
        for version, suite in itertools.product(versions, suites)
    ]


def _expected_statuses() -> set[str]:
    job = _unit_tests_job()
    template = _status_template(job)
    names = set()
    for combination in _matrix_combinations(job):
        name = _MATRIX_EXPRESSION.sub(lambda match: combination[match.group(1)], template)
        assert "${{" not in name, f"נשאר ביטוי שהטסט אינו יודע לפרוש: {name!r}"
        names.add(name)
    return names


def _tracked_files_naming_a_unit_tests_status() -> set[Path]:
    """כל קובץ במעקב של git שמופיע בו שם של סטטוס ``Unit Tests``.

    ``git grep`` על הקידומת שמשותפת לכל השמות רק בוחר מועמדים, וההכרעה היא של
    ``_UNIT_STATUS`` — כך שהצורה של שם סטטוס מוגדרת במקום אחד, ולא פעם בפייתון ופעם
    בתחביר של git. הדגלים, לפי ``Documentation/git-grep.txt`` ב-git 2.43: ``-l`` שמות
    הקבצים בלבד, ``-z`` כל שם מסתיים ב-``\\0`` ומודפס כמו שהוא, ``-I`` בלי קבצים בינאריים,
    ``-F`` מחרוזת ולא ביטוי. קוד היציאה הוא ``!hit`` (``builtin/grep.c``), כלומר 1 הוא
    "אף קובץ". כל קוד אחר — למשל 128 מחוץ לעבודה של git — הוא כשל ולא תשובה, ולכן
    הטסט נכשל ולא מדלג: בלי git הוא לא בדק כלום.
    """
    proc = subprocess.run(
        ["git", "grep", "-z", "-l", "-I", "-F", "Unit Tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
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
