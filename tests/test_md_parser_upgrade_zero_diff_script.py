"""שער היציאה של ``scripts/md_parser_upgrade_zero_diff.py`` — נבדק, ולא רק נכתב.

הסקריפט הוא הראיה ששדרוג של ``markdown-it-py`` לא שינה דבר מלבד מה שהוכרז מראש, והוא אינו
רץ ב-CI: הערך שלו הוא הדיף בין שתי סביבות, ו-CI רץ באחת. הטסט הזה בודק את המנגנון — שתצלום
נכתב ונושא את מה שפסק הדין קורא, ששני תצלומים זהים יוצאים ב-0, ושכל סוג של הבדל, הכרזה שגויה
או תצלום פגום מפיל את ההשוואה בקוד הנכון ובהודעה שאומרת מה.

**ההבדלים נוצרים בעריכה של תצלום אמיתי**, ולא בפארסר מזויף: ``compare`` רואה רק JSON, ומה
שנבדק כאן הוא שהוא רואה כל שינוי ב-JSON — בדיוק מה ששדרוג אמיתי היה מייצר. התצלום עצמו נכתב
פעם אחת לכל המודול, דרך ``main`` כמו בשורת הפקודה, על קורפוס קטן ועל שתי משפחות.
"""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("cmarkgfm")

_REPO = Path(__file__).resolve().parent.parent

#: משפחה אחת מ-``_COMPARED_FAMILIES`` ומשפחה אחת של שורה ב-``_KNOWN_DIVERGENCES`` —
#: אחת מכל סוג, והקטנות שבהן.
_FAMILIES = ("html_edge_cases", "type7_glued_to_container")


def _load_script():
    """טעינה לפי נתיב — ``scripts/`` אינה חבילה.

    אותה תבנית כמו ב-``tests/test_docs_section_zero_diff_script.py``.
    """
    spec = importlib.util.spec_from_file_location(
        "md_parser_upgrade_zero_diff_under_test",
        _REPO / "scripts" / "md_parser_upgrade_zero_diff.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _corpus(base: Path, **files: str) -> Path:
    corpus = base / "corpus"
    corpus.mkdir()
    for name, text in files.items():
        (corpus / name).write_text(text, encoding="utf-8", newline="")
    return corpus


def _snapshot_argv(corpus: Path, out: Path) -> list[str]:
    argv = ["snapshot", "--root", f"c={corpus}", "--out", str(out)]
    for family in _FAMILIES:
        argv += ["--family", family]
    return argv


@pytest.fixture(scope="module")
def script():
    return _load_script()


@pytest.fixture(scope="module")
def taken(script, tmp_path_factory):
    """תצלום אמיתי אחד, והתיקייה שבה נכתב: קובץ md, קובץ rst, ושתי משפחות."""
    base = tmp_path_factory.mktemp("zero_diff")
    corpus = _corpus(base, **{"a.md": "# א\n\n## ב\n", "b.rst": "Doc\n===\n\nSec\n---\n"})
    out = base / "snapshot.json"
    assert script.main(_snapshot_argv(corpus, out)) == 0
    return json.loads(out.read_text(encoding="utf-8")), base


@pytest.fixture
def snapshot(taken):
    """עותק לכל טסט — טסט שעורך את התצלום לא ישנה אותו לטסט הבא."""
    return copy.deepcopy(taken[0])


def _compare(script, tmp_path: Path, old, new, *expected: str) -> int:
    paths = []
    for name, data in (("old.json", old), ("new.json", new)):
        (tmp_path / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        paths.append(str(tmp_path / name))
    argv = ["compare", *paths]
    for family in expected:
        argv += ["--expected-change", family]
    return script.main(argv)


def test_the_snapshot_holds_every_group_the_verdict_reads(snapshot):
    """התצלום נושא את התוצאות עצמן — לא רק את המפתחות שלהן."""
    assert snapshot["format"] == 1
    assert "markdown-it-py" in snapshot["versions"]
    assert [s["title"] for s in snapshot["maps"]["c:a.md"]["sections"]] == ["א", "ב"]
    assert snapshot["maps"]["c:a.md"]["front_matter_end"] == 0
    assert [s["title"] for s in snapshot["maps"]["c:b.rst"]["sections"]] == ["Doc", "Sec"]
    assert snapshot["refusals"]["md_too_many_lines"]["answer"]["error"] == "too_many_lines"
    assert snapshot["refusals"]["md_too_many_tokens"]["answer"]["error"] == "too_many_tokens"
    assert snapshot["refusals"]["rst_too_many_sections"]["answer"]["error"] == "too_many_sections"
    lone_cr = snapshot["refusals"]["md_lone_cr_middle"]["answer"]
    assert lone_cr["error"] == "inconsistent_line_endings"
    assert snapshot["hostile"]["bullets_1000"]["sections"] == []
    assert sorted(snapshot["oracle"]) == sorted(_FAMILIES)
    assert all(snapshot["oracle"][family] for family in _FAMILIES)
    # מטריצת ההקשר לא צולמה, ולכן גם טקסט הכותרות שלה לא
    assert snapshot["oracle_titles"] == []
    assert isinstance(snapshot["info_token_count"]["c:a.md"], int)


def test_a_corpus_file_over_a_markdown_ceiling_is_recorded_as_a_refusal_and_not_a_crash(
        script, tmp_path):
    """``_REFUSALS`` כולל את שתי התקרות של #3391: קובץ בקורפוס שעובר אחת מהן נרשם כסירוב.

    בלעדיהן ``_parse`` היה מעלה את החריגה, והתצלום כולו היה נופל על קובץ אחד — כלומר
    שדרוג לא היה יכול להיבדק על ריפו שיש בו קובץ כזה. ``front_matter_end`` רץ בלי תקרות,
    בכוונה (ראו ``md_parser``), ולכן הוא נרשם גם על קובץ שהפרסור מסרב לו.
    """
    from services import md_parser

    columns = 16
    dense = (
        "|" + "|".join(" h " for _ in range(columns)) + "|\n"
        + "|" + "|".join("---" for _ in range(columns)) + "|\n"
        + ("|" + "|".join(" x " for _ in range(columns)) + "|\n") * 1_000
    )
    corpus = _corpus(tmp_path, **{"long.md": "a\n" * md_parser.MAX_LINES, "dense.md": dense})
    out = tmp_path / "snapshot.json"

    assert script.main(_snapshot_argv(corpus, out)) == 0

    maps = json.loads(out.read_text(encoding="utf-8"))["maps"]
    assert maps["c:long.md"] == {
        "raised": "TooManyLines",
        "args": [md_parser.MAX_LINES + 1, md_parser.MAX_LINES],
        "front_matter_end": 0,
    }
    assert maps["c:dense.md"]["raised"] == "TooManyTokens"
    assert maps["c:dense.md"]["args"][1] == md_parser.MAX_TOKENS


def test_the_snapshot_writes_nothing_but_out(taken):
    """הסקריפט מצהיר שהוא אינו כותב לשום קובץ מלבד ``--out`` — וזה נבדק על התיקייה."""
    _data, base = taken
    written = sorted(
        path.relative_to(base).as_posix() for path in base.rglob("*") if path.is_file()
    )
    assert written == ["corpus/a.md", "corpus/b.rst", "snapshot.json"]


def test_two_identical_snapshots_are_a_zero_diff(script, snapshot, tmp_path, capsys):
    assert _compare(script, tmp_path, snapshot, copy.deepcopy(snapshot)) == 0
    assert "פסק דין: אפס דיף" in capsys.readouterr().out


@pytest.mark.parametrize(
    "group, key",
    [("maps", "c:a.md"), ("refusals", "md_too_many_tokens"), ("hostile", "bullets_1000")],
)
def test_a_change_in_an_exact_group_is_a_difference_and_names_the_key(
    script, snapshot, tmp_path, capsys, group, key
):
    """מפה, תשובת סירוב וצורה עוינת — אין הכרזה שפוטרת אותן."""
    new = copy.deepcopy(snapshot)
    new[group][key] = {"changed": True}

    assert _compare(script, tmp_path, snapshot, new, *_FAMILIES) == 1
    report = capsys.readouterr().out
    assert f"[{group}] רק בישן=0 רק בחדש=0 שונים=1" in report
    assert key in report
    assert "פסק דין: הבדל" in report


def test_a_changed_shape_fails_unless_its_family_was_declared(script, snapshot, tmp_path, capsys):
    """הלב של ההכרזה: אותו שינוי אדום בלעדיה וירוק איתה — ורק במשפחה שהוכרזה."""
    new = copy.deepcopy(snapshot)
    new["oracle"]["type7_glued_to_container"][0].update(ours=[[9, 9]], agree=False)

    assert _compare(script, tmp_path, snapshot, new) == 1
    report = capsys.readouterr().out
    assert "[oracle:type7_glued_to_container] צורות=" in report and "השתנו=1" in report
    assert "#0 ישן:" in report and "#0 חדש:" in report

    assert _compare(script, tmp_path, snapshot, new, "type7_glued_to_container") == 0
    assert "שינוי מוכרז" in capsys.readouterr().out

    assert _compare(script, tmp_path, snapshot, new, "html_edge_cases") == 1


def test_a_declared_change_that_did_not_happen_fails(script, snapshot, tmp_path, capsys):
    """הכרזה שלא התקיימה היא הנחה שגויה — ואם תישאר בפקודה, היא תסתיר את השינוי הבא."""
    assert _compare(script, tmp_path, snapshot, copy.deepcopy(snapshot), "html_edge_cases") == 1
    report = capsys.readouterr().out
    assert "[oracle:html_edge_cases] הוכרז כמשתנה ולא השתנה" in report


def test_shapes_from_different_generators_are_not_compared_one_by_one(
    script, snapshot, tmp_path, capsys
):
    """צורה אחרת באותו אינדקס אינה "שינוי בתוצאה" — המחוללים עצמם שונים, וגם הכרזה לא פוטרת."""
    new = copy.deepcopy(snapshot)
    new["oracle"]["html_edge_cases"][0]["text_sha"] = "0" * 64

    assert _compare(script, tmp_path, snapshot, new, "html_edge_cases") == 1
    report = capsys.readouterr().out
    assert "[oracle:html_edge_cases] הצורות עצמן שונות" in report
    assert "הוכרז כמשתנה ולא השתנה" not in report


def test_snapshots_of_different_families_fail(script, snapshot, tmp_path, capsys):
    new = copy.deepcopy(snapshot)
    del new["oracle"]["html_edge_cases"]

    assert _compare(script, tmp_path, snapshot, new) == 1
    assert "[oracle] לא אותן משפחות" in capsys.readouterr().out


@pytest.mark.parametrize(
    "malform",
    [
        pytest.param(lambda data: [], id="not_an_object"),
        pytest.param(lambda data: {**data, "format": 2}, id="other_format"),
        pytest.param(lambda data: {**data, "maps": []}, id="maps_is_a_list"),
        pytest.param(
            lambda data: {k: v for k, v in data.items() if k != "refusals"}, id="missing_group"
        ),
        pytest.param(lambda data: {**data, "oracle_titles": {}}, id="titles_is_an_object"),
        pytest.param(lambda data: {**data, "oracle": {"x": {}}}, id="family_is_not_a_list"),
        pytest.param(
            lambda data: {**data, "oracle": {"x": [{"ours": []}]}}, id="shape_without_text_sha"
        ),
    ],
)
def test_a_malformed_snapshot_is_refused_by_file_name(script, snapshot, tmp_path, capsys, malform):
    """הקובץ הגיע מחוץ לתהליך: מבנה שגוי נענה ב-2 ובשם הקובץ, לא ב-traceback באמצע הדוח."""
    with pytest.raises(SystemExit) as exc:
        _compare(script, tmp_path, snapshot, malform(copy.deepcopy(snapshot)))

    assert exc.value.code == 2
    assert "new.json" in capsys.readouterr().err


def test_a_file_that_is_not_json_is_refused_by_file_name(script, snapshot, tmp_path, capsys):
    (tmp_path / "old.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "new.json").write_text('{"format": 1, "maps": ', encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        script.main(["compare", str(tmp_path / "old.json"), str(tmp_path / "new.json")])

    assert exc.value.code == 2
    assert "new.json" in capsys.readouterr().err


def test_declaring_a_family_that_is_not_in_the_snapshots_is_an_input_error(
    script, snapshot, tmp_path, capsys
):
    with pytest.raises(SystemExit) as exc:
        _compare(script, tmp_path, snapshot, copy.deepcopy(snapshot), "no_such_family")

    assert exc.value.code == 2
    assert "no_such_family" in capsys.readouterr().err


def test_an_unknown_family_is_refused_before_anything_is_written(script, tmp_path, capsys):
    out = tmp_path / "snapshot.json"
    corpus = _corpus(tmp_path, **{"a.md": "# א\n"})

    with pytest.raises(SystemExit) as exc:
        script.main(["snapshot", "--root", f"c={corpus}", "--out", str(out), "--family", "nope"])

    assert exc.value.code == 2
    assert "nope" in capsys.readouterr().err
    assert not out.exists()


def test_a_missing_out_directory_is_refused_before_the_work(script, tmp_path, capsys):
    """תיקייה חסרה הייתה נגלית רק בכתיבה — אחרי כל הפרסור, כלומר אחרי הדקות שלו."""
    corpus = _corpus(tmp_path, **{"a.md": "# א\n"})

    with pytest.raises(SystemExit) as exc:
        script.main(_snapshot_argv(corpus, tmp_path / "missing" / "snapshot.json"))

    assert exc.value.code == 2
    assert "--out" in capsys.readouterr().err


def test_a_root_without_markdown_or_rst_is_not_a_snapshot(script, tmp_path, capsys):
    """תצלום של כלום אינו ראיה — ושתי ריצות על כלום היו "אפס דיף"."""
    out = tmp_path / "snapshot.json"
    corpus = _corpus(tmp_path, **{"notes.txt": "# לא Markdown\n"})

    with pytest.raises(SystemExit) as exc:
        script.main(_snapshot_argv(corpus, out))

    assert exc.value.code == 2
    assert "אפס קובצי .md ו-.rst" in capsys.readouterr().err
    assert not out.exists()


def test_a_refused_file_is_recorded_and_does_not_stop_the_snapshot(script, tmp_path):
    """‏``\\r`` בודד: ``parse_document``, ``front_matter_end`` ו-``token_count`` מסרבים שלושתם.

    הסירוב הוא תוצאה שנרשמת — עם השורה — ולא חריגה שמפילה את התצלום באמצע הקורפוס.
    """
    out = tmp_path / "snapshot.json"
    corpus = _corpus(tmp_path, **{"lone_cr.md": "# א\n\nfoo\rbar\n", "fine.md": "# ב\n"})

    assert script.main(_snapshot_argv(corpus, out)) == 0

    data = json.loads(out.read_text(encoding="utf-8"))
    refused = {"raised": "InconsistentLineEndings", "args": [3]}
    assert data["maps"]["c:lone_cr.md"] == {**refused, "front_matter_end": refused}
    assert data["info_token_count"]["c:lone_cr.md"] == refused
    assert [s["title"] for s in data["maps"]["c:fine.md"]["sections"]] == ["ב"]


def test_loading_the_oracle_leaves_scripts_out_of_sys_path(script):
    """הטוען נלקח מהסקריפט האח, והתיקייה ``scripts/`` נכנסת ל-``sys.path`` לזמן הייבוא בלבד."""
    scripts = str(_REPO / "scripts")
    before = sys.path.count(scripts)

    oracle = script._load_oracle()

    assert sys.path.count(scripts) == before
    assert set(script._oracle_families(oracle)) >= set(_FAMILIES)
