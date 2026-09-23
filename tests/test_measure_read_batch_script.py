"""``scripts/measure_read_batch.py`` — נבדק, ולא רק נכתב.

הסקריפט הוא המקור של המספרים ש-``docs/mcp-server.rst`` מצטט על
``codekeeper_read_batch``: כמה מהתקציב ומהדדליין הסבב האמיתי תופס, ושבאץ'
אינו מחזיק יותר מהמסמך היקר שבו. באג במדידה — בתים שנספרים בנוסחה אחרת מזו
שהכלי שולח, או פריט שנענה ב-``not_found`` ונמדד כאילו נקרא — היה מדפיס מספר
סביר-למראה שנכנס לתיעוד, ואיש לא היה יודע. לכן:

- המדידה האמיתית רצה פעם אחת מקצה לקצה (כל התהליכים, מעל מראת git אמיתית),
  והבתים שלה מושווים לתשובה שהכלי עצמו בונה על אותם פריטים.
- פריט של הסבב שנענה בסירוב מפיל את ההרצה, בשמו ובקוד של הכלי הבודד.
- מראה שזזה באמצע ההרצה מפילה אותה, כי המדידות תיארו שני מצבים.

הטעינה לפי נתיב — ``scripts/`` אינה חבילה — היא אותה תבנית כמו
``tests/test_docs_section_zero_diff_script.py``. כל קלט ופלט תחת ``tmp_path``.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

_REPO = Path(__file__).resolve().parent.parent
_GIT = shutil.which("git")
requires_git = pytest.mark.skipif(_GIT is None, reason="git is not installed")
_NAME = "amir-bug-patterns"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "measure_read_batch_under_test", _REPO / "scripts" / "measure_read_batch.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _git(*args: str, cwd: Path) -> str:
    done = subprocess.run((_GIT, *args), cwd=str(cwd), check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _round_files(script: Any, *, skip: set[int] = frozenset()) -> dict[str, str]:
    """קבצים שעונים על כל פריט של ``REVIEW_ROUND`` — נגזרים מהרשימה, ולא עותק שלה.

    פריט סעיף מקבל כותרת שנפתחת במזהה שלו (``## K11. ...``), כמו בריפו
    האמיתי; פריט קובץ מקבל קובץ קטן. אינדקס ב-``skip`` אינו מקבל דבר.
    """
    files: dict[str, str] = {}
    for index, item in enumerate(script.REVIEW_ROUND):
        if index in skip:
            continue
        if item["kind"] == "section":
            name = f"{item['path']}.md"
            files.setdefault(name, f"# {item['path']}\n\n")
            files[name] += f"## {item['section']}. כותרת של {item['section']}\n\nגוף של {item['section']}.\n\n"
        else:
            files[item["path"]] = f"# {item['path']}\n\nתוכן.\n"
    return files


def _big_files() -> dict[str, str]:
    """קבצים גדולים משל הסבב, שהבחירה של ``largest_served`` צריכה לעבור דרכם.

    חמישה מסמכים עם כותרות ייחודיות — מספיק לבאץ' מלא — ולצידם שני קבצים
    גדולים עוד יותר שהכלי מסרב להם: סיומת שהריפו אינו מגיש, ונתיב שמדיניות
    הסודות חוסמת. הבחירה חייבת לדלג על שניהם ולומר זאת. ובכל מסמך כותרת
    שחוזרת פעמיים, **ראשונה**: פריט עליה היה עונה ``ambiguous_section``, ולכן
    הבחירה חייבת לדלג גם עליה.
    """
    body = "שורה ארוכה בעברית. " * 60 + "\n\n"
    files = {f"docs/big-{n}.md": f"## כפול\n\n{body}## כפול\n\n{body}"
             + "".join(f"## סעיף {n}.{k}\n\n{body}" for k in range(6))
             for n in range(5)}
    files["data.json"] = json.dumps({"x": "y" * 40_000})
    files["secrets.md"] = "# סוד\n\n" + "z" * 40_000
    return files


def _mirror(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    """ריפו עובד ו-``clone --mirror`` שלו תחת ``tmp_path``; מחזיר את התיקייה ואת ה-SHA."""
    work = tmp_path / "work"
    for name, body in files.items():
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body.encode("utf-8"))
    _git("init", "-q", "-b", "main", ".", cwd=work)
    _git("add", "-A", cwd=work)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init", cwd=work)
    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    _git("clone", "-q", "--mirror", str(work), str(mirrors / f"{_NAME}.git"), cwd=tmp_path)
    return mirrors, _git("rev-parse", "HEAD", cwd=work)


def _lines(out: str) -> dict[str, dict[str, Any]]:
    by_case: dict[str, dict[str, Any]] = {}
    for raw in out.strip().splitlines():
        line = json.loads(raw)
        key = line.get("case") or ("summary" if line.get("summary") else "largest")
        by_case[key] = line
    return by_case


@requires_git
def test_every_measurement_runs_end_to_end_and_the_bytes_are_what_the_tool_sends(tmp_path, capsys, monkeypatch):
    """כל התהליכים, מעל מראה אמיתית: הסבב נקרא שלם, והבתים הם בדיוק מה שהכלי בונה."""
    script = _load_script()
    mirrors, head = _mirror(tmp_path, {**_round_files(script), **_big_files()})

    code = script.main(["--mirror-root", str(mirrors), "--repo", _NAME])
    captured = capsys.readouterr()

    assert code == 0, captured.err
    lines = _lines(captured.out)

    # הבחירה דילגה על שני הקבצים הגדולים שהכלי מסרב להם — ואמרה זאת. חמשת
    # המסמכים שווים בגודלם, ולכן הסדר ביניהם הוא סדר הנתיבים.
    chosen = [doc["path"] for doc in lines["largest"]["largest"]]
    assert chosen == [f"docs/big-{n}.md" for n in range(5)]
    # הסיבה היא מה שהכלי עצמו עונה על אותו נתיב — לא מחרוזת שהטסט ניחש.
    # (``data.json`` בלי ``/`` הוא slug, ולכן הכלי מחפש ``data.json.md``.)
    from mcp_server import docs_handlers, read_batch
    from mcp_server.repo_handlers import OUTPUT_BYTE_BUDGET

    monkeypatch.setenv("MCP_DOCS_REPO", _NAME)
    backend = script._backend(mirrors)
    skipped = {json.loads(raw)["skipped"]: json.loads(raw)["reason"]
               for raw in captured.err.strip().splitlines() if raw.startswith('{"skipped"')}
    assert set(skipped) == {"data.json", "secrets.md"}
    for path, reason in skipped.items():
        assert reason == docs_handlers.docs_get_section(backend, path=path, repo=_NAME)["error"], path
    assert skipped["secrets.md"] == "path_denied"

    round_line = lines["round"]
    assert round_line["requested"] == round_line["count"] == len(script.REVIEW_ROUND)
    assert round_line["unread"] is None and round_line["failed"] == []
    assert round_line["commits"] == [head]

    # הבתים שהסקריפט מדווח הם התשובה שהכלי עצמו בונה על אותם פריטים, בצורה שנשלחת.
    answer = read_batch.read_batch(
        backend, script.items_for("round", _NAME, []), item_cap=read_batch.MAX_BATCH_ITEMS)
    assert round_line["wire_bytes"] == len(read_batch._wire(answer))
    assert round_line["share_of_budget"] == round(round_line["wire_bytes"] / OUTPUT_BYTE_BUDGET, 4)

    interleaved = lines["interleaved_largest"]
    assert interleaved["requested"] == interleaved["count"] == read_batch.MAX_BATCH_ITEMS
    assert interleaved["failed"] == [] and interleaved["unread"] is None

    for case in script.CASES:
        assert lines[case]["peak_mib"] > 0, case
    summary = lines["summary"]
    assert summary["commits"] == [head]
    assert summary["round_share_of_budget"] == round_line["share_of_budget"]
    assert summary["interleaved_peak_over_single"] == round(
        interleaved["peak_mib"] / lines["single_largest"]["peak_mib"], 3)
    assert "failed" not in summary and "mirror_moved" not in summary


@requires_git
def test_a_round_item_answered_with_a_refusal_is_named_and_fails_the_run(tmp_path, capsys, monkeypatch):
    """K11: פריט שנענה בסירוב אינו נמדד כאילו נקרא — הוא מדווח בשמו, והקוד 1."""
    script = _load_script()
    missing = next(i for i, item in enumerate(script.REVIEW_ROUND) if item["kind"] == "file")
    mirrors, _ = _mirror(tmp_path, {**_round_files(script, skip={missing}), **_big_files()})

    code = script.main(["--mirror-root", str(mirrors), "--repo", _NAME, "--case", "round"])
    lines = _lines(capsys.readouterr().out)

    assert code == 1
    failed = lines["summary"]["failed"]["round"]
    assert [entry["index"] for entry in failed] == [missing]
    # הקוד הוא זה שהכלי הבודד מחזיר על אותו נתיב — לא מחרוזת שהטסט ניחש.
    from mcp_server import repo_handlers

    monkeypatch.setenv("MCP_DOCS_REPO", _NAME)
    single = repo_handlers.get_repo_file(
        script._backend(mirrors), repo=_NAME, path=script.REVIEW_ROUND[missing]["path"])
    assert single["ok"] is False
    assert failed[0]["error"] == single["error"]
    assert failed[0]["request"]["path"] == script.REVIEW_ROUND[missing]["path"]


def test_a_mirror_that_moved_between_measurements_fails_the_run(tmp_path, capsys, monkeypatch):
    """שתי מדידות שקראו commits שונים תיארו שני מצבים — ההרצה נכשלת ואומרת למה."""
    script = _load_script()
    (tmp_path / f"{_NAME}.git").mkdir()
    selection = {"largest": [{"path": "a.md", "size": 1, "sections": ["x"]}]}

    def fake_spawn(arguments, mirror_root, repo, workdir):
        if arguments == ["--child-select"]:
            return selection
        case = arguments[1]
        if "--peak" in arguments:
            return {"case": case, "peak_mib": 1.0}
        commit = "a" * 40 if case == "round" else "b" * 40
        return {"case": case, "share_of_budget": 0.1, "share_of_deadline": 0.01,
                "commits": [commit], "failed": []}

    monkeypatch.setattr(script, "_spawn", fake_spawn)

    code = script.main(["--mirror-root", str(tmp_path), "--repo", _NAME,
                        "--case", "round", "--case", "single_largest"])
    summary = _lines(capsys.readouterr().out)["summary"]

    assert code == 1
    assert summary["mirror_moved"] is True
    assert summary["commits"] == ["a" * 40, "b" * 40]


@pytest.mark.parametrize("stdout", ["", "a log line, not json\n", "[1, 2]\n"])
def test_a_child_that_prints_no_json_object_is_refused_by_name(tmp_path, monkeypatch, stdout):
    """U3: שורת הפלט של הילד עוברת גבול של תהליך — שורה שאינה אובייקט JSON נדחית בשמה, לא ב-KeyError."""
    script = _load_script()

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(script.subprocess, "run", fake_run)

    with pytest.raises(SystemExit, match="printed no JSON object"):
        script._spawn(["--child-select"], tmp_path, _NAME, str(tmp_path))


def test_a_missing_mirror_is_refused_by_name_before_anything_runs(tmp_path, capsys):
    script = _load_script()

    code = script.main(["--mirror-root", str(tmp_path), "--repo", _NAME])

    assert code == 2
    assert f"{_NAME}.git" in capsys.readouterr().err


def test_the_documented_gap_to_production_is_the_ref_label():
    """התיעוד מסביר את הפער בין הסבב בפרודקשן לסבב של הסקריפט ב-``ref`` בלבד.

    ``docs/mcp-server.rst`` מצטט שני מספרים לאותו סבב — מה שהפרודקשן שלח ומה
    שהסקריפט מודד — ואומר שההפרש הוא שם הענף שכל פריט שנקרא נושא: ``HEAD``
    בלי מונגו, ו-``refs/heads/main`` בפרודקשן. כאן ההפרש לפריט נגזר מ-
    ``RepoBackend._default_ref`` עצמו, ומספר הפריטים מ-``REVIEW_ROUND``. מי
    שמוסיף פריט לסבב, או משנה את מה ש-``_default_ref`` מחזיר, מפיל את הטסט —
    כי אז שני המספרים המתוארכים בתיעוד כבר אינם של הסבב הזה, וצריך למדוד שוב.
    """
    import re

    from mcp_server.repo_backend import RepoBackend

    class _Metadata:
        def find_one(self, query: dict[str, Any]) -> dict[str, Any]:
            return {"default_branch": "main"}

    script = _load_script()
    page = (_REPO / "docs" / "mcp-server.rst").read_text(encoding="utf-8")

    def number(pattern: str) -> int:
        found = re.search(pattern, page)
        assert found, f"המשפט {pattern!r} אינו בצורה שהטסט קורא"
        return int(found.group(1).replace(",", ""))

    in_production = number(r"בפרודקשן הסבב האמיתי היה ([\d,]+) בתים")
    by_the_script = number(r"\*\*אותו סבב במדידה המקומית\.\*\*.*?ומודד ([\d,]+) בתים")
    per_item = number(r"(\d+) בתים פחות בכל פריט שנקרא")

    production_ref = RepoBackend(db={"repo_metadata": _Metadata()})._default_ref(_NAME)
    local_ref = RepoBackend(db=None)._default_ref(_NAME)
    assert (production_ref, local_ref) == ("refs/heads/main", "HEAD")
    assert per_item == len(production_ref) - len(local_ref)
    assert in_production - by_the_script == len(script.REVIEW_ROUND) * per_item
