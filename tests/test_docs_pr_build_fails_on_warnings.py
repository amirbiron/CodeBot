"""הבנייה של ה-PR ב-``documentation.yml`` נכשלת על אזהרה בתיעוד; הבנייה של ``main`` מפרסמת גם עם אזהרות.

עד 12.11.2026 הבנייה של ה-PR רצה בלי ``-W`` והציגה ✅ גם כשהיו אזהרות, והבדיקה היחידה שהכשילה PR על אזהרה
הייתה של Read the Docs (``fail_on_warning`` ב-``.readthedocs.yml``). כשהבנייות שלהם נקטעו ("Build terminated due
to inactivity"), לא היה מי שיאמר לפני מיזוג אם יש בתיעוד אזהרה. הטסט הזה נועל את שתי ההחלטות, והנימוק — בהערה
שמעל הצעד ``sphinx_pr`` ב-workflow וב-``docs/doc-authoring.rst`` ("טיפים מהירים").

``-E`` נדרש בנוסף ל-``-W``: בנייה מצטברת קוראת רק עמודים שהשתנו, ולכן לא מדווחת על קישור שנשבר בעמוד שלא
השתנה. ב-Sphinx 8.2.3 נמדד: קישור לתווית שנמחקה מעמוד אחר עבר בלי ``-E`` ונכשל איתו.

**הפקודה נקראת כמו ש-bash מבצע אותה, ולא כמו שהיא כתובה.** ``shlex.split`` בברירת המחדל משאיר את ``#`` ואת מה
שאחריו כמילים, ולכן ``... --keep-going # -W -E`` היה עובר את הבדיקה בזמן שה-shell מתעלם מהדגלים; ו-``|| true``
אחרי הפקודה מבטל את הכשל שלה. ``_effective_sphinx_args`` מפרק עם ``punctuation_chars``, שמוריד הערות ומפריד
אופרטורים, ופוסל כל דרך להסתיר את קוד היציאה של Sphinx.
"""

from __future__ import annotations

import shlex

import pytest
import yaml

from test_docs_export_sections import WORKFLOW, _build_docs_steps

#: כל טוקן ש-``punctuation_chars`` מפריד הוא אופרטור של shell. אחרי פקודת Sphinx כל אחד מהם משנה את מה שקובע את
#: קוד היציאה של הצעד (``||``, ``;``, ``|``, ``&``) או את הפקודה עצמה (``>``, ``(``).
_OPERATOR_CHARS = frozenset("|&;()<>")


def _effective_sphinx_args(step: dict, job: dict | None = None) -> list[str]:
    """הארגומנטים שאחרי ``python -m sphinx``, כמו ש-bash מבצע את השורה — או ``AssertionError`` כשהכשל של Sphinx
    לא יכשיל את הצעד."""
    assert not step.get("continue-on-error"), f"{step.get('id')}: continue-on-error מבטל את הכשל של הצעד"
    if job is not None:
        assert not job.get("continue-on-error"), "continue-on-error על ה-job מבטל את הכשל של הבנייה"

    lines = [line.strip() for line in step["run"].splitlines() if line.strip()]
    sphinx_lines = [line for line in lines if "-m sphinx" in line]
    assert len(sphinx_lines) == 1, f"expected one Sphinx command in {step.get('id')}, found {sphinx_lines}"
    assert lines[-1] == sphinx_lines[0], (
        f"{step.get('id')}: Sphinx אינה הפקודה האחרונה — קוד היציאה של מה שאחריה יקבע את תוצאת הצעד"
    )

    lexer = shlex.shlex(sphinx_lines[0], posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    tokens = list(lexer)
    operators = [token for token in tokens if set(token) <= _OPERATOR_CHARS]
    assert not operators, f"{step.get('id')}: אופרטור של shell בשורת Sphinx ({operators}) עלול להסתיר את הכשל שלה"
    return tokens[tokens.index("sphinx") + 1 :]


def _step(step_id: str) -> tuple[dict, dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return _build_docs_steps()[step_id], workflow["jobs"]["build-docs"]


def test_the_pr_build_fails_on_any_warning():
    args = _effective_sphinx_args(*_step("sphinx_pr"))
    assert "-W" in args or "--fail-on-warning" in args, args


def test_the_pr_build_reads_every_page():
    """בלי ``-E`` אזהרה מעמוד שלא השתנה ב-PR — למשל קישור לתווית שה-PR מחק מעמוד אחר — לא מדווחת."""
    args = _effective_sphinx_args(*_step("sphinx_pr"))
    assert "-E" in args or "--fresh-env" in args, args


def test_the_main_build_publishes_even_with_warnings():
    """בנייה של ``main`` שנכשלת על אזהרה הייתה עוצרת את הפרסום, והאתר היה נשאר על הגרסה הקודמת."""
    args = _effective_sphinx_args(*_step("sphinx_main"))
    assert "-W" not in args and "--fail-on-warning" not in args, args


_GOOD = "DISABLE_DB=1 python -m sphinx -b html . _build/html -W -E --keep-going -j auto"


def test_flags_in_a_shell_comment_do_not_count():
    """``#`` מתחיל הערה: הדגלים שאחריו לא מגיעים ל-Sphinx, ולכן גם לא לבדיקה."""
    args = _effective_sphinx_args({"id": "x", "run": "cd docs\n" + _GOOD.replace("-W -E ", "") + " # -W -E"})
    assert "-W" not in args and "-E" not in args, args


@pytest.mark.parametrize(
    "run, step_extra",
    [
        ("cd docs\n" + _GOOD + " || true", {}),
        ("cd docs\n" + _GOOD + "||true", {}),
        ("cd docs\n" + _GOOD + "; true", {}),
        ("cd docs\n" + _GOOD + " | tee build.log", {}),
        ("cd docs\n" + _GOOD + "\necho done", {}),
        ("cd docs\n" + _GOOD, {"continue-on-error": True}),
    ],
    ids=["or-true", "or-true-no-spaces", "semicolon", "pipe", "a-line-after", "continue-on-error"],
)
def test_a_masked_exit_status_is_rejected(run, step_extra):
    with pytest.raises(AssertionError):
        _effective_sphinx_args({"id": "x", "run": run, **step_extra})


def test_continue_on_error_on_the_job_is_rejected():
    with pytest.raises(AssertionError):
        _effective_sphinx_args({"id": "x", "run": "cd docs\n" + _GOOD}, {"continue-on-error": True})


# ---------------------------------------------------------------------------
# docs/conf.py — שמה ש--W רואה הוא באמת מה שבתיעוד
# ---------------------------------------------------------------------------

DOCS = WORKFLOW.parents[2] / "docs"


def _conf_value(name: str):
    """ערך של השמה ברמה העליונה ב-``docs/conf.py``, בלי להריץ את הקובץ (הוא קובע משתני סביבה ומוסיף נתיבים)."""
    import ast

    tree = ast.parse((DOCS / "conf.py").read_text(encoding="utf-8"))
    values = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
    ]
    assert len(values) == 1, f"expected one assignment to {name} in docs/conf.py, found {len(values)}"
    return ast.literal_eval(values[0])


def test_no_warning_type_is_suppressed_as_a_whole():
    """ערך בלי נקודה (``'autodoc'``) משתיק כל אזהרה מהסוג, כל subtype (``is_suppressed_warning`` ב-
    ``sphinx/util/logging.py``, 8.2.3) — וכך ``-W`` לא רואה חתימה לא תקינה או תכונה חסרה. מותר רק subtype מוגדר."""
    for entry in _conf_value("suppress_warnings"):
        assert "." in entry and not entry.endswith(".*"), f"{entry!r} משתיק סוג אזהרה שלם"


def test_every_intersphinx_inventory_falls_back_to_a_saved_copy():
    """בלי עותק, אתר תיעוד חיצוני שלא זמין לרגע מכשיל את הבנייה של ה-PR: אזהרת "failed to reach any of the
    inventories" נכתבת בלי type, ו-``suppress_warnings`` לא משתיק אותה. עם עותק — רק הודעת INFO."""
    mapping = _conf_value("intersphinx_mapping")
    assert mapping, "intersphinx_mapping ריק"
    for name, (_uri, locations) in mapping.items():
        assert isinstance(locations, tuple) and locations[0] is None, f"{name}: הרשת קודם, כדי שהקישורים יהיו עדכניים"
        local = [loc for loc in locations[1:] if loc and "://" not in loc]
        assert local, f"{name}: אין עותק שמור"
        for path in local:
            inventory = DOCS / path
            assert inventory.is_file(), f"{name}: {path} לא קיים"
            assert inventory.read_bytes().startswith(b"# Sphinx inventory version 2"), f"{name}: {path} אינו מלאי"
