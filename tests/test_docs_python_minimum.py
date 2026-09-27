"""גרסת הפייתון המינימלית שבתיעוד היא הגרסה הנמוכה ביותר שה-CI בודק.

הבאג שהבדיקות כאן מונעות: ``docs/installation.rst``, ``docs/index.rst`` ו-``docs/README.md``
אמרו "Python 3.9", בזמן שהקוד כבר ייבא ``datetime.UTC`` (שנוסף בפייתון 3.11) והג'וב
``unit-tests`` ב-``.github/workflows/ci.yml`` לא בדק אף גרסה מתחת ל-3.11. אף שורת קוד לא נגעה
במספר כשהוא התיישן, ולכן רק בדיקה שגוזרת אותו ומשווה יכולה לתפוס את זה —
``prose-restates-code-fact`` ב-amir-bug-patterns. נתפס בסקירה של CodeRabbit על PR #3465.

שני כללים נאכפים:

1. המספר כתוב ב-``docs/installation.rst`` פעם אחת, והוא הגרסה הנמוכה ביותר במטריצה של
   ``unit-tests`` — כלומר הגרסה הנמוכה ביותר שבאמת נבדקת.
2. אף עמוד אחר תחת ``docs/`` אינו כותב גרסת פייתון בפריט של רשימה. הם מפנים ל-
   ``installation.rst``, כמו השורה של MongoDB ב-``docs/index.rst``.

מה לא מכוסה כאן, בכוונה: גרסת פייתון בתוך פסקה ("``asyncio.to_thread`` נוסף ב-3.9") היא
עובדה על פייתון ולא דרישה של הפרויקט, ולכן הסריקה מסתכלת רק על פריטי רשימה שמתחילים
ב-"Python".
"""

import re
from pathlib import Path

import yaml
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
#: עמוד הבעלים, יחסית ל-``docs/``: המקום היחיד שבו המספר כתוב, יחד עם הסיבה לו
OWNER = Path("installation.rst")

#: השורה בעמוד הבעלים שמצהירה על המינימום
_DECLARED_RE = re.compile(r"^\* Python (\d+\.\d+) או גרסה חדשה יותר", re.MULTILINE)
#: פריט ברשימה (``*`` ב-rst, ``-`` ב-md) שמתחיל בגרסת פייתון — הצורה שבה 3.9 היה כתוב.
#: ``[ \t]*`` ולא ``\s*``: עם MULTILINE, ``\s*`` בולע גם שורה ריקה שלפני הפריט, ההתאמה
#: מתחילה בשורה הריקה, ומספר השורה בהודעה מצביע עליה ולא על הפריט.
_RESTATED_RE = re.compile(r"^[ \t]*[*-][ \t]+Python[ \t]+\d+\.\d+", re.MULTILINE)


def _ci_python_versions() -> list[str]:
    """הגרסאות שהג'וב ``unit-tests`` רץ עליהן, כפי שהן כתובות ב-``ci.yml``."""
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    versions = workflow["jobs"]["unit-tests"]["strategy"]["matrix"]["python-version"]
    assert isinstance(versions, list) and versions, f"המטריצה אינה רשימה עם ערכים: {versions!r}"
    # מחרוזות בלבד: ``yaml.safe_load`` קורא ``3.10`` בלי מרכאות כמספר 3.1. בלי הבדיקה הזו הטסט
    # היה נופל בתוך ``Version`` על הערך 3.1, בלי לומר שבקובץ כתוב 3.10.
    not_strings = [version for version in versions if not isinstance(version, str)]
    assert not not_strings, (
        f"במטריצה יש גרסאות שאינן מחרוזות: {not_strings!r}. ‏3.10 בלי מרכאות נקרא כמספר 3.1 — "
        "כתבו '3.10'."
    )
    return versions


def _restated(root: Path) -> list[str]:
    """כל פריט רשימה תחת ``root`` שכותב גרסת פייתון בעצמו, חוץ מעמוד הבעלים."""
    found = []
    for page in sorted([*root.rglob("*.rst"), *root.rglob("*.md")]):
        relative = page.relative_to(root)
        if relative == OWNER or "_build" in relative.parts:
            continue
        text = page.read_text(encoding="utf-8")
        for match in _RESTATED_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append(f"{relative.as_posix()}:{line}: {match.group(0).strip()}")
    return found


def test_the_documented_minimum_is_the_lowest_python_that_ci_tests():
    """המספר ב-``installation.rst`` שווה לגרסה הנמוכה ביותר במטריצה של ``unit-tests``."""
    declared = _DECLARED_RE.findall((DOCS / OWNER).read_text(encoding="utf-8"))
    assert len(declared) == 1, (
        "ב-docs/installation.rst צריכה להיות שורה אחת בדיוק בצורה "
        f"'* Python X.Y או גרסה חדשה יותר', ונמצאו {len(declared)}"
    )
    lowest = min(_ci_python_versions(), key=Version)
    assert Version(declared[0]) == Version(lowest), (
        f"docs/installation.rst אומר Python {declared[0]}, והגרסה הנמוכה ביותר ש-unit-tests "
        f"ב-.github/workflows/ci.yml בודק היא {lowest}. עדכנו את העמוד ואת הסיבה שכתובה בו, "
        "או את המטריצה — אחד מהם אינו מתאר את הפרויקט."
    )


def test_no_other_docs_page_restates_the_python_minimum():
    """שאר העמודים תחת ``docs/`` מפנים ל-``installation.rst`` ולא כותבים את המספר בעצמם."""
    restated = _restated(DOCS)
    assert not restated, (
        "עמודים שכותבים גרסת פייתון בעצמם — כך 3.9 התיישן בשלושה עמודים. הפנו ל-installation.rst, "
        "כמו השורה של MongoDB ב-docs/index.rst:\n" + "\n".join(restated)
    )


def test_the_scan_catches_the_shapes_that_went_stale(tmp_path):
    """הסריקה תופסת את הצורות שבהן 3.9 היה כתוב, ופוטרת רק את עמוד הבעלים.

    .. note::

       **הטסט הזה אינו נופל על התיעוד שלפני התיקון, וזה מכוון.** הוא שומר על
       ``_RESTATED_RE`` ועל ``_restated``: סריקה שאינה תופסת דבר הייתה משאירה את
       ``test_no_other_docs_page_restates_the_python_minimum`` ירוק על כל תיעוד שהוא.
    """
    (tmp_path / "installation.rst").write_text(
        "* Python 3.11 או גרסה חדשה יותר\n", encoding="utf-8"
    )
    (tmp_path / "index.rst").write_text("דרישות\n------\n\n* Python 3.9+\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("### דרישות\n\n- Python 3.9+\n", encoding="utf-8")
    (tmp_path / "guide").mkdir()
    (tmp_path / "guide" / "setup.rst").write_text(
        "משתמש ב-asyncio.to_thread (Python 3.9+).\n\n  * Python 3.9 או גרסה חדשה יותר\n",
        encoding="utf-8",
    )

    # עמוד הבעלים לא מופיע, אותה צורה בעמוד אחר כן, והפסקה עם 3.9 לא
    assert _restated(tmp_path) == [
        "README.md:3: - Python 3.9",
        "guide/setup.rst:3: * Python 3.9",
        "index.rst:4: * Python 3.9",
    ]
