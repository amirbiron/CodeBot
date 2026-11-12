"""הבנייה של ה-PR ב-``documentation.yml`` נכשלת על אזהרה בתיעוד; הבנייה של ``main`` מפרסמת גם עם אזהרות.

עד 12.11.2026 הבנייה של ה-PR רצה בלי ``-W`` והציגה ✅ גם כשהיו אזהרות, והבדיקה היחידה שהכשילה PR על אזהרה
הייתה של Read the Docs (``fail_on_warning`` ב-``.readthedocs.yml``). כשהבנייות שלהם נקטעו ("Build terminated due
to inactivity"), לא היה מי שיאמר לפני מיזוג אם יש בתיעוד אזהרה. הטסט הזה נועל את שתי ההחלטות, והנימוק — בהערה
שמעל הצעד ``sphinx_pr`` ב-workflow וב-``docs/doc-authoring.rst`` ("טיפים מהירים").

``-E`` נדרש בנוסף ל-``-W``: בנייה מצטברת קוראת רק עמודים שהשתנו, ולכן לא מדווחת על קישור שנשבר בעמוד שלא
השתנה. ב-Sphinx 8.2.3 נמדד: קישור לתווית שנמחקה מעמוד אחר עבר בלי ``-E`` ונכשל איתו.
"""

from __future__ import annotations

import shlex

from test_docs_export_sections import _build_docs_steps


def _sphinx_args(step: dict) -> list[str]:
    """הארגומנטים שאחרי ``python -m sphinx`` בשורה היחידה של הצעד שמריצה את Sphinx."""
    lines = [line for line in step["run"].splitlines() if "-m sphinx" in line]
    assert len(lines) == 1, f"expected one Sphinx command in {step['id']}, found {lines}"
    tokens = shlex.split(lines[0])
    return tokens[tokens.index("sphinx") + 1 :]


def test_the_pr_build_fails_on_any_warning():
    args = _sphinx_args(_build_docs_steps()["sphinx_pr"])
    assert "-W" in args or "--fail-on-warning" in args, args


def test_the_pr_build_reads_every_page():
    """בלי ``-E`` אזהרה מעמוד שלא השתנה ב-PR — למשל קישור לתווית שה-PR מחק מעמוד אחר — לא מדווחת."""
    args = _sphinx_args(_build_docs_steps()["sphinx_pr"])
    assert "-E" in args or "--fresh-env" in args, args


def test_the_main_build_publishes_even_with_warnings():
    """בנייה של ``main`` שנכשלת על אזהרה הייתה עוצרת את הפרסום, והאתר היה נשאר על הגרסה הקודמת."""
    args = _sphinx_args(_build_docs_steps()["sphinx_main"])
    assert "-W" not in args and "--fail-on-warning" not in args, args
