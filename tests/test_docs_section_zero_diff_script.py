"""שער היציאה של ``scripts/docs_section_zero_diff.py`` — נבדק, ולא רק נכתב.

הסקריפט הוא המכשיר שכל הטענה "ההתנהגות על התיעוד לא זזה" נשענת עליו, והוא
מחזיר ``1`` כשההנחות שהוא מקודד אינן מתארות את העץ. **שער שאיש לא מריץ הוא
שער שאיש לא יודע אם הוא עובד**: ביום שיפסיק לתפוס, הרגרסיה הבאה תעבור דרכו
בשקט, והצוות ימשיך לסמוך עליו. שמונה מתוך 27 הסקריפטים בריפו כבר מכוסים
בטסטים — זו המוסכמה כאן, לא ייבוא מבחוץ.

**והסקריפט עצמו אינו רץ ב-CI, בכוונה** — הנימוק כתוב ב-docstring שלו: הערך
שלו הוא הדיף בין שני עצים, ועל עץ הבסיס הוא **אמור** לצאת ב-1. הטסט הזה
בודק את המנגנון; ההנחה עצמה מוגנת ב-``tests/test_docs_headings_carry_no_identifier.py``.
"""

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("docutils")

_REPO = Path(__file__).resolve().parent.parent


def _load_script():
    """טעינה לפי נתיב — ``scripts/`` אינה חבילה.

    אותה תבנית כמו ``_load_compare_script`` ב-``tests/test_md_parser.py``.
    """
    spec = importlib.util.spec_from_file_location(
        "docs_section_zero_diff_under_test",
        _REPO / "scripts" / "docs_section_zero_diff.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _corpus(tmp_path: Path, *files: tuple[str, str]) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for name, text in files:
        (corpus / name).write_text(text, encoding="utf-8")
    return corpus


_CLEAN = ("plain.rst", "Doc\n===\n\nרגיל לגמרי\n----------\n\nגוף\n")
#: כותרת autodoc אמיתית: ``md5`` הוא שלוש אותיות וספרה, כלומר מזהה תקף.
_CARRIES_IDENTIFIER = ("autodoc.rst", "md5 package\n===========\n\nגוף\n")


def test_a_clean_corpus_exits_zero_and_writes_the_snapshot(tmp_path, capsys):
    """הכיוון הבסיסי: אין מזהים בקורפוס, הבקרות תואמות, קוד יציאה 0."""
    script = _load_script()
    out = tmp_path / "snapshot.jsonl"

    code = script.main(["--corpus", str(_corpus(tmp_path, _CLEAN)), "--out", str(out)])
    report = capsys.readouterr().out

    assert code == 0, report
    assert "מזהים שנמצאו בקורפוס: 0" in report
    assert out.is_file() and out.read_text(encoding="utf-8").strip(), "התצלום ריק"


def test_a_heading_that_carries_an_identifier_breaks_the_premise_and_exits_one(tmp_path, capsys):
    """הכיוון שסוגר את WARN-003: הצורה שאיש לא ניחש **כן** נתפסת.

    הגרסה הקודמת שאלה שלוש-עשרה מחרוזות קבועות, ו-``md5`` לא היה ביניהן —
    כלומר בדיוק הקורפוס הזה היה עובר ומחזיר 0. היום הפרובים נגזרים
    מהכותרות עצמן, ולכן אין צורה שאפשר לפספס.

    **והתצלום נכתב גם בריצה שנכשלה**, כי בלעדיו אי אפשר להשוות ולראות
    *מה* השתנה — רק לדעת שמשהו השתנה.
    """
    script = _load_script()
    out = tmp_path / "snapshot.jsonl"

    code = script.main(["--corpus", str(_corpus(tmp_path, _CLEAN, _CARRIES_IDENTIFIER)),
                        "--out", str(out)])
    report = capsys.readouterr().out

    assert code == 1, report
    assert "מזהים שנמצאו בקורפוס: 1" in report
    assert "md5" in report
    assert out.is_file(), "ה-JSONL לא נכתב בריצה שנכשלה"

    # והפרוב הנגזר אכן נשאל, ונרשם בתצלום
    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    probes = [r for r in records if "identifier_probe" in r]
    assert [p["identifier_probe"]["section"] for p in probes] == ["md5"]
    assert probes[0]["outcome"] == "section"


def test_a_control_that_stops_flipping_exits_one(tmp_path, capsys, monkeypatch):
    """הכיוון השלישי: הבקרות בודקות את עצמן.

    זה מה ש-CodeRabbit תפס בסבב קודם — הלולאה **הדפיסה** את המצופה לצד
    מה שהתקבל ולא השוותה, כך שבקרה שתפסיק להתהפך הייתה מדפיסה שורה
    שנראית כמעט נכונה וסומכת על כך שאדם ישים לב.

    הבקרה מוחלפת כאן בערך השוואה שגוי במקום לשבור את הקוד — כי מה שנבדק
    הוא **ההשוואה**, לא ההתאמה עצמה.
    """
    script = _load_script()
    broken = tuple(
        (name, text, probe, "outcome_that_cannot_happen", why)
        for name, text, probe, _expected, why in script._CONTROLS
    )
    monkeypatch.setattr(script, "_CONTROLS", broken)
    out = tmp_path / "snapshot.jsonl"

    code = script.main(["--corpus", str(_corpus(tmp_path, _CLEAN)), "--out", str(out)])
    report = capsys.readouterr().out

    assert code == 1, report
    assert "לא תואם" in report
    assert "outcome_that_cannot_happen" in report
