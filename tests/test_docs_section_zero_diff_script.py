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
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("docutils")

_REPO = Path(__file__).resolve().parent.parent
_GIT = shutil.which("git")


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


@pytest.mark.parametrize("before", [None, "amir-bug-patterns,CodeBot"])
def test_the_script_restores_the_env_it_pinned(tmp_path, monkeypatch, capsys, before):
    """``main`` מקבע ``MCP_DOCS_REPO`` להרצה, ומחזיר בדיוק את מה שהיה.

    **הקיבוע עצמו נכון, וההחזרה היא מה שהיה חסר.** ברירת המחדל של
    ``MCP_DOCS_REPO`` קובעת מאז מדיניות הנתיבים גם את **הפורמט** שהסוללה
    שואלת עליו, ולכן הסקריפט חייב לקבע אותה — אחרת "אפס דיף" יכול לתאר
    שתי הרצות שכולן ``suffix_not_allowed``. אבל ``main`` נקרא מתוך תהליך
    של טסטים, שלוש פעמים בקובץ הזה, ומשתנה שנדרס ולא מוחזר הוא
    ``test-infra-shared-state`` §2.

    נמדד לפני התיקון: קורא שהגדיר ``"amir-bug-patterns,CodeBot"`` מצא
    ``"CodeBot"`` אחרי הקריאה.

    **ושני הכיוונים נבדקים**, כי הם אינם אותו דבר: "לא היה מוגדר" דורש
    **מחיקה**, ו-``""`` אינו תחליף — ``os.getenv`` מבדיל ביניהם.
    """
    monkeypatch.delenv("MCP_DOCS_REPO", raising=False)
    if before is not None:
        monkeypatch.setenv("MCP_DOCS_REPO", before)

    script = _load_script()
    code = script.main(["--corpus", str(_corpus(tmp_path, _CLEAN)),
                        "--out", str(tmp_path / "snapshot.jsonl")])
    capsys.readouterr()

    assert code == 0
    assert os.environ.get("MCP_DOCS_REPO") == before


def test_the_script_pins_the_repo_while_it_runs(tmp_path, monkeypatch, capsys):
    """ובתוך ההרצה הקיבוע אכן חל, גם כשהקורא הגדיר משהו אחר.

    ריצת הבקרה לטסט שמעליו: בלעדיה "הערך חזר למה שהיה" היה יכול להיות
    נכון גם אם הקיבוע הוסר לגמרי.
    """
    monkeypatch.setenv("MCP_DOCS_REPO", "amir-bug-patterns,CodeBot")
    script = _load_script()

    seen = []
    original = script.docs_handlers.docs_get_section

    def spy(*args, **kwargs):
        seen.append(os.environ.get("MCP_DOCS_REPO"))
        return original(*args, **kwargs)

    monkeypatch.setattr(script.docs_handlers, "docs_get_section", spy)
    script.main(["--corpus", str(_corpus(tmp_path, _CLEAN)),
                 "--out", str(tmp_path / "snapshot.jsonl")])
    capsys.readouterr()

    assert seen, "אף קריאה לכלי לא נצפתה — הבדיקה איבדה את הנושא שלה"
    assert set(seen) == {script.docs_handlers.DEFAULT_DOCS_REPO}


def _records(out: Path) -> list[dict]:
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]


def test_the_battery_runs_under_another_repos_path_policy(tmp_path, capsys):
    """``--repo amir-bug-patterns``: קורפוס ``.md`` ששורשו שורש הריפו, כולל תת-תיקייה.

    הנתיבים בתצלום הם יחסיים לשורש הריפו (``sub/page.md``), ולא ``docs/...``,
    ו-``suffix_not_allowed`` נשאל על הסיומת **האחרת** — ``.rst``.
    """
    script = _load_script()
    corpus = tmp_path / "corpus"
    (corpus / "sub").mkdir(parents=True)
    (corpus / "sub" / "page.md").write_text("# עמוד\n\n## סעיף\n\nגוף\n", encoding="utf-8")
    out = tmp_path / "snapshot.jsonl"

    code = script.main(["--corpus", str(corpus), "--repo", "amir-bug-patterns", "--out", str(out)])
    capsys.readouterr()

    assert code == 0
    records = _records(out)
    sections = [r for r in records if r.get("query", {}).get("path") == "sub/page.md"]
    assert sections and all(r["response"]["repo"] == "amir-bug-patterns" for r in sections)
    wrong_suffix = [r for r in records if r.get("query", {}).get("path") == "x.rst"]
    assert wrong_suffix[0]["response"]["error"] == "suffix_not_allowed"


@pytest.mark.skipif(_GIT is None, reason="git is not installed")
def test_through_the_real_backend_the_read_path_refusals_are_in_the_snapshot(tmp_path, capsys):
    """``--mirror-root``: ``RepoBackend`` אמיתי מעל מראת git, ולכן גם ``path_denied`` ו-``not_found``.

    אלה שתי תשובות הסירוב שנולדות במסלול הקריאה ולא בשער של ``docs_get_section``,
    ו-``_CorpusBackend`` אינו מסוגל לייצר את הראשונה. ``resolved_commit`` הוא ה-SHA
    של המראה.
    """
    script = _load_script()
    work = tmp_path / "work"
    work.mkdir()
    (work / "page.md").write_text("# עמוד\n\n## סעיף\n\nגוף\n", encoding="utf-8")
    (work / "secrets.md").write_text("# לא לקרוא\n", encoding="utf-8")

    def git(*args, cwd):
        return subprocess.run((_GIT, *args), cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q", "-b", "main", ".", cwd=work)
    git("add", "-A", cwd=work)
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init", cwd=work)
    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    git("clone", "-q", "--mirror", str(work), str(mirrors / "amir-bug-patterns.git"), cwd=tmp_path)
    out = tmp_path / "snapshot.jsonl"

    script.main(["--mirror-root", str(mirrors), "--repo", "amir-bug-patterns", "--out", str(out)])
    capsys.readouterr()

    by_path = {r["query"].get("path"): r["response"] for r in _records(out) if "query" in r}
    assert by_path["secrets"]["error"] == "path_denied"
    assert by_path["does-not-exist-at-all"]["error"] == "not_found"
    assert by_path["page.md"]["resolved_commit"] == git("rev-parse", "main", cwd=work)
    # קובץ שקיים במראה ושמדיניות הסודות חוסמת: הסוללה רצה עליו כמו על כל קובץ,
    # והכלי עונה ``path_denied`` — סירוב אמיתי על קובץ אמיתי, לא רק על קלט דחייה.
    assert by_path["secrets.md"]["error"] == "path_denied"
