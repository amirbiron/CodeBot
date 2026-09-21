"""``scripts/measure_md_parse_cost.py`` — נבדק, ולא רק נכתב (סקירת #3429, WARN-005).

הסקריפט הוא המקור של ``_PARSE_RSS_PER_INPUT_BYTE`` ב-``mcp_server/server.py``,
שממנו נגזר רוחב מאגר הקריאות של ה-MCP. באג בבחירת המספר — למשל לקיחת
המדידה הראשונה במקום הגבוהה ביותר, או הקורפוס במקום המסמך הצפוף — ידפיס
מספר סביר-למראה שייכנס לייצור, ואיש לא יידע. לכן הטסטים הראשונים כאן הם על
הבחירה ועל החיווט, ולא על המדידה עצמה; המדידה האמיתית (תת-תהליך) רצה פעם
אחת על קובץ זעיר, כדי להוכיח שהילד מדווח את השיא מעל הבסיס הנכון.

הטעינה לפי נתיב — ``scripts/`` אינה חבילה — היא אותה תבנית כמו
``tests/test_docs_section_zero_diff_script.py``. כל קלט ופלט תחת ``tmp_path``.
"""

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("markdown_it")

_REPO = Path(__file__).resolve().parent.parent


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "measure_md_parse_cost_under_test", _REPO / "scripts" / "measure_md_parse_cost.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _measurement(parser, shape, cost, **extra):
    return {"parser": parser, "shape": shape, "peak_bytes_per_input_byte": cost, **extra}


def test_the_constant_candidate_is_the_largest_densest_real_measurement_not_the_first():
    """הבחירה: הגבוה מבין מדידות המסמך הצפוף — לא הראשון, לא הצפוף ביותר בדירוג, לא הקורפוס ולא הגבול העוין."""
    script = _load_script()
    results = [
        _measurement("md", "corpus", 25.5),
        # הראשון ברשימה, וגם הצפוף ביותר בדירוג — ובכל זאת לא הגבוה במדידה.
        _measurement("md", "densest_real", 50.0, density_per_kb=170.0),
        _measurement("md", "densest_real", 72.2, density_per_kb=120.0),
        _measurement("md", "densest_real", 61.0, density_per_kb=150.0),
        _measurement("md", "hostile", 291.9),
        _measurement("rst", "densest_real", 6.9),
        _measurement("rst", "hostile", 90.9),
        _measurement("rst", "outline_densest_real", 7.7),
    ]
    assert script.constant_candidate(results, "md") == 72.2
    assert script.hostile_bound(results, "md") == 291.9
    assert script.constant_candidate(results, "rst") == 6.9
    assert script.hostile_bound(results, "rst") == 90.9


def test_main_reports_each_parsers_candidate_from_its_densest_shape(monkeypatch, tmp_path, capsys):
    """החיווט: השורה האחרונה נושאת לכל פרסר את המועמד מהצורה ``densest_real`` — בלי תת-תהליכים."""
    script = _load_script()
    docs = {".md": tmp_path / "a.md", ".rst": tmp_path / "b.rst"}
    docs[".md"].write_text("# t\n\n- one\n- two\n" * 200, encoding="utf-8")
    docs[".rst"].write_text("T\n=\n\ntext\n\n" * 200, encoding="utf-8")
    monkeypatch.setattr(script, "REPO", tmp_path)
    monkeypatch.setattr(script, "real_files", lambda suffix: [docs[suffix]])
    monkeypatch.setattr(script, "density", lambda text, parser="md": 1.0)
    costs = {"corpus": 25.0, "tiled_": 70.7, "hostile": 290.0, "outline_": 7.7}
    seen_kwargs = {}

    def fake_peak_cost(path, workdir, *, parser="md", kwargs=None):
        prefix = next(prefix for prefix in costs if path.name.startswith(prefix))
        seen_kwargs[(parser, prefix)] = kwargs
        cost = costs[prefix]
        return {
            "module": script.PARSERS[parser]["module"],
            "input_bytes": 1,
            "outcome": "parsed",
            "sections": 1,
            "headroom_kb_before_parse": 0,
            "peak_mib": 0.0,
            "peak_bytes_per_input_byte": cost,
            "retained_bytes_per_input_byte": 0.0,
        }

    monkeypatch.setattr(script, "peak_cost", fake_peak_cost)

    assert script.main() == 0

    last = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert last["md"]["constant_candidate_bytes_per_input_byte"] == 70.7
    assert last["md"]["hostile_bound_bytes_per_input_byte"] == 290.0
    assert last["rst"]["constant_candidate_bytes_per_input_byte"] == 70.7
    assert last["rst"]["hostile_bound_bytes_per_input_byte"] == 290.0

    # WARN-004 (סקירת שבעת ה-PRים): הצורה העוינת מודדת את הפרסר בלי התקרה —
    # עם ברירת המחדל היא נעצרת על MAX_SECTIONS והמספר מתאר עצירה. הקורפוס
    # והמסמך הצפוף רצים כמו הכלי, בלי kwargs; ה-outline עם התקרה שלו.
    from mcp_server.outline_scanners._ceiling import MAX_SYMBOLS

    for parser in ("md", "rst"):
        assert seen_kwargs[(parser, "hostile")] == {"max_sections": None}, parser
        assert seen_kwargs[(parser, "corpus")] is None and seen_kwargs[(parser, "tiled_")] is None
    assert seen_kwargs[("rst", "outline_")] == {"max_sections": MAX_SYMBOLS}
    assert "max_sections=None" in last["note"]


def test_a_checkout_with_no_document_of_the_minimum_size_fails_with_a_named_message():
    """בלי קובץ מתאים הסקריפט אומר זאת — לא ``StatisticsError`` גולמי מהחציון."""
    script = _load_script()
    with pytest.raises(SystemExit) as exc:
        script.rank([], "md")
    assert "no .md file of at least 2000 bytes" in str(exc.value)


def test_a_file_that_is_not_utf8_is_reported_on_stderr_and_skipped(tmp_path, capsys):
    """הכלל ב-CLAUDE.md: except שמדלג אומר זאת — שורת ``skipped`` ב-stderr עם שם הקובץ."""
    script = _load_script()
    good = tmp_path / "good.md"
    good.write_text("# ok\n\ntext\n", encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"# bad\n\n\xff\xfe text\n")

    ranked = script.rank([bad, good], "md")

    assert [p for _, p, _ in ranked] == [good]
    skipped = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert skipped["skipped"] == str(bad)
    assert skipped["reason"].startswith("not utf-8")


def test_tiling_stops_at_the_ceiling_and_is_longer_than_its_input():
    """השכפול נעצר בתקרה בבתים (תו חלקי בקצה נזרק) והתוצאה ארוכה מהקלט."""
    script = _load_script()
    text = "# heading\n\nשורה בעברית עם טקסט\n" * 5

    tiled = script.tiled_to_ceiling(text)

    size = len(tiled.encode("utf-8"))
    assert script.MAX_FILE_SIZE_FOR_DISPLAY - 3 <= size <= script.MAX_FILE_SIZE_FOR_DISPLAY
    assert size > len(text.encode("utf-8"))
    assert 997 <= len(script.tiled_to_ceiling(text, 1000).encode("utf-8")) <= 1000


def test_density_goes_through_the_public_token_count_and_not_the_private_builder(monkeypatch):
    """הסקריפט אינו קורא ל-``md_parser._build_parser`` (#3433, SUGG-010): התלות היא ``token_count``."""
    from services import md_parser

    script = _load_script()

    def _forbidden():
        raise AssertionError("הסקריפט קרא ל-_build_parser הפרטית")

    monkeypatch.setattr(md_parser, "_build_parser", _forbidden)
    assert script.density("- a\n" * 10, "md") > 0


def test_density_ranks_a_dense_document_above_a_sparse_one_of_the_same_size():
    """הצפיפות היא מה שמדרג: טוקני בלוק ל-KB ב-Markdown, סקשנים ל-KB ב-RST."""
    script = _load_script()
    assert script.density("- a\n" * 100, "md") > script.density("a" * 400, "md")
    assert script.density("a\n=\n\n" * 100, "rst") > script.density("a" * 500, "rst")


def test_real_files_skip_vendored_directories_and_undersized_documents(tmp_path, monkeypatch):
    script = _load_script()
    monkeypatch.setattr(script, "REPO", tmp_path)
    keep = tmp_path / "docs" / "keep.md"
    keep.parent.mkdir()
    keep.write_text("x" * 2000, encoding="utf-8")
    vendored = tmp_path / "node_modules" / "vendored.md"
    vendored.parent.mkdir()
    vendored.write_text("x" * 2000, encoding="utf-8")
    (tmp_path / "small.md").write_text("x" * 100, encoding="utf-8")

    assert script.real_files(".md") == [keep]


@pytest.mark.parametrize(
    "parser, text, kwargs",
    [("md", "# t\n\n- a\n- b\n", None), ("rst", "T\n=\n\ntext\n", {"max_sections": 50})],
)
def test_the_measuring_child_reports_the_peak_above_the_pre_parse_high_water_mark(tmp_path, parser, text, kwargs):
    """המדידה האמיתית, פעם אחת על קובץ זעיר: הפלט נושא את המרווח שלפני הפרסור ואת השיא שמעליו."""
    script = _load_script()
    doc = tmp_path / ("tiny" + script.PARSERS[parser]["suffix"])
    doc.write_text(text, encoding="utf-8")

    result = script.peak_cost(doc, tmp_path, parser=parser, kwargs=kwargs)

    assert result["module"] == script.PARSERS[parser]["module"]
    assert result["input_bytes"] == doc.stat().st_size
    assert result["outcome"] == "parsed" and result["sections"] >= 1
    assert result["headroom_kb_before_parse"] >= 0
    assert result["peak_bytes_per_input_byte"] >= 0
    assert result["peak_mib"] >= 0
