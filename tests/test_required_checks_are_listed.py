"""שמות הסטטוסים של ``unit-tests`` כתובים בכל רשימה של בדיקות החובה — ורק הם.

הבעלים הוא ``.github/workflows/ci.yml``: כל מסלול של הג'וב ``unit-tests`` מדווח סטטוס
חובה, ושמו נבנה מהמטריצה (``STATUS_CONTEXT`` בצעדי "Report required status"). אותם
שמות כתובים ביד ברשימות שאנשים וסוכנים קוראים לפני מיזוג, ורשימה שלא עודכנה אומרת
ש-PR מוכן בזמן שמסלול שלם עוד לא דיווח. לכן הטסט גוזר את השמות מהמטריצה עצמה — גם
את התבנית שלהם — ובודק כל רשימה בשני הכיוונים: שכל שם מופיע בה, ושאין בה שם של
``Unit Tests`` שהמטריצה כבר לא מייצרת.

``docs/testing.rst`` אינו ברשימת הקבצים בכוונה: הוא מפנה ל-``docs/ci-cd.rst`` במקום
להחזיק עותק משלו.
"""

from __future__ import annotations

import itertools
import re
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
)

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


def test_the_status_names_come_from_the_matrix_of_unit_tests():
    """הבסיס לשני הטסטים שאחריו: כל מסלול מקבל שם משלו, ושמות של ``Unit Tests``."""
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
