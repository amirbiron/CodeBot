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


def _measurement(parser, shape, peak_bytes, *, as_tool=True, per_input_byte=0.0, cpu=0.0, **extra):
    return {
        "parser": parser, "shape": shape, "as_tool": as_tool, "peak_bytes": peak_bytes,
        "peak_bytes_per_input_byte": per_input_byte, "cpu_seconds": cpu, **extra,
    }


def test_the_constant_candidate_is_the_costliest_parse_run_as_the_tool_per_ceiling_byte():
    """הבחירה: השיא הגבוה מבין המדידות **כמו הכלי**, בבתים לכל בית של תקרת הקריאה.

    לא הראשונה, לא הצפופה ביותר בדירוג, לא הצורה בלי תקרות ולא ה-outline. **וקלט
    קטן ויקר נמדד לפי מה שהוא עולה**: מאז #3391 הקלט הגרוע ב-Markdown יכול להיות
    טבלה של כמה KB שנעצרת בתקרת הטוקנים, והעלות לבית **שלה** הייתה ענקית ולא
    רלוונטית — מה שהמאגר מקצה הוא ``_PARSE_RSS_PER_INPUT_BYTE × MAX_FILE_SIZE_FOR_DISPLAY``.
    """
    script = _load_script()
    ceiling = script.MAX_FILE_SIZE_FOR_DISPLAY
    results = [
        _measurement("md", "corpus", 20 * ceiling, per_input_byte=20.0),
        # הראשון ברשימה, וגם הצפוף ביותר בדירוג — ובכל זאת לא הגבוה במדידה.
        _measurement("md", "densest_real", 50 * ceiling, per_input_byte=50.0, density_per_kb=170.0),
        # קלט של 17KB שעולה 30MB: 1,800 בתים לבית שלו, 61.4 לבית של התקרה.
        _measurement("md", "cpu:lazy_quote_then_table", 31_436_800, per_input_byte=1800.0),
        _measurement("md", "worst_memory", int(66.6 * ceiling), per_input_byte=66.7),
        _measurement("md", "hostile", 290 * ceiling, as_tool=False, per_input_byte=290.6),
        _measurement("rst", "densest_real", int(6.4 * ceiling), per_input_byte=6.4),
        _measurement("rst", "hostile", 90 * ceiling, as_tool=False, per_input_byte=90.2),
        _measurement(
            "rst", "outline_densest_real", 300 * ceiling, as_tool=False, per_input_byte=7.7
        ),
    ]
    assert script.constant_candidate(results, "md") == 66.6
    assert script.hostile_bound(results, "md") == 290.6
    assert script.constant_candidate(results, "rst") == 6.4
    assert script.hostile_bound(results, "rst") == 90.2


def _fake_child(script, costs, seen_kwargs):
    """``peak_cost`` בלי תת-תהליך: העלות לפי תחילית שם הקובץ, והארגומנטים נרשמים."""

    def fake_peak_cost(path, workdir, *, parser="md", kwargs=None):
        prefix = next(prefix for prefix in costs if path.name.startswith(prefix))
        seen_kwargs.setdefault((parser, prefix), []).append(kwargs)
        peak_bytes, cpu = costs[prefix]
        return {
            "module": script.PARSERS[parser]["module"],
            "input_bytes": 1,
            "outcome": "parsed",
            "line": None,
            "sections": 1,
            "headroom_kb_before_parse": 0,
            "peak_bytes": peak_bytes,
            "peak_mib": 0.0,
            "peak_bytes_per_input_byte": float(peak_bytes),
            "retained_bytes_per_input_byte": 0.0,
            "cpu_seconds": cpu,
        }

    return fake_peak_cost


def _wire_main(script, monkeypatch, tmp_path, costs):
    docs = {".md": tmp_path / "a.md", ".rst": tmp_path / "b.rst"}
    docs[".md"].write_text("# t\n\n- one\n- two\n" * 200, encoding="utf-8")
    docs[".rst"].write_text("T\n=\n\ntext\n\n" * 200, encoding="utf-8")
    monkeypatch.setattr(script, "REPO", tmp_path)
    monkeypatch.setattr(script, "real_files", lambda suffix: [docs[suffix]])
    monkeypatch.setattr(script, "density", lambda text, parser="md": 1.0)
    seen_kwargs: dict = {}
    monkeypatch.setattr(script, "peak_cost", _fake_child(script, costs, seen_kwargs))
    return seen_kwargs


def test_main_runs_every_markdown_shape_as_the_tool_and_the_hostile_bound_without_ceilings(
        monkeypatch, tmp_path, capsys):
    """החיווט, בלי תת-תהליכים: מה רץ כמו הכלי, מה רץ בלי תקרות, ומה נכנס לשורה האחרונה.

    כמו הכלי — בלי ארגומנטים — הקורפוס, המסמך הצפוף, כל צורה עוינת בתקרת הקריאה,
    הקלט הגרוע בזיכרון, וכל קלט מעבד ``CPU_REPEATS`` פעמים. בלי תקרות — הצורה
    העוינת, בכל פרסר עם מה שמכבה את התקרות **שלו** (WARN-004 בסקירת שבעת
    ה-PRים: עם ברירת המחדל היא נעצרת על תקרה, והמספר מתאר עצירה ולא את הפרסר).
    ה-outline עם התקרה שלו.
    """
    script = _load_script()
    ceiling = script.MAX_FILE_SIZE_FOR_DISPLAY
    costs = {
        "corpus": (20 * ceiling, 0.1), "tiled_": (50 * ceiling, 0.2),
        "hostile": (290 * ceiling, 2.8),
        "outline_": (300 * ceiling, 0.5), "capped_": (30 * ceiling, 0.3),
        "worst_memory": (60 * ceiling, 0.3), "cpu_": (20 * ceiling, 0.5),
    }
    seen_kwargs = _wire_main(script, monkeypatch, tmp_path, costs)

    assert script.main([]) == 0

    last = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert last["md"]["constant_candidate_bytes_per_input_byte"] == 60.0
    assert last["md"]["hostile_bound_bytes_per_input_byte"] == 290 * ceiling
    assert last["rst"]["constant_candidate_bytes_per_input_byte"] == 50.0
    assert last["verdict"]["memory_within_budget"] is True
    assert last["verdict"]["cpu_within_constant"] is True
    assert last["verdict"]["md_worst_cpu_seconds"] == 0.5

    from mcp_server.outline_scanners._ceiling import MAX_SYMBOLS

    assert seen_kwargs[("md", "hostile")] == [
        {"max_sections": None, "max_lines": None, "max_tokens": None}]
    assert seen_kwargs[("rst", "hostile")] == [{"max_sections": None}]
    assert seen_kwargs[("rst", "outline_")] == [{"max_sections": MAX_SYMBOLS}]
    for key in (("md", "corpus"), ("md", "tiled_"), ("rst", "corpus"), ("rst", "tiled_"),
                ("md", "capped_"), ("md", "worst_memory"), ("md", "cpu_")):
        assert set(map(repr, seen_kwargs[key])) == {"None"}, key
    assert len(seen_kwargs[("md", "capped_")]) == len(script.HOSTILE_SHAPES)
    assert len(seen_kwargs[("md", "cpu_")]) == len(script.CPU_SHAPES) * script.CPU_REPEATS


@pytest.mark.parametrize("breaks", ["memory", "cpu"])
def test_main_exits_1_when_a_measurement_breaks_a_constant_it_feeds(
        monkeypatch, tmp_path, capsys, breaks):
    """השיא מעל ``_PARSE_COST_BYTES``, או מעבד מעל ``WORST_CASE_CPU_SECONDS`` — קוד יציאה 1.

    אלה שני הקבועים שהמאגר, מגבלת הקצב והדדליין נגזרים מהם. מדידה שעוברת אחד מהם
    ויוצאת ב-0 הייתה משאירה את כל שלושת החשבונות על מספר שכבר אינו נכון.
    """
    from mcp_server.server import _PARSE_COST_BYTES
    from services import md_parser

    script = _load_script()
    ceiling = script.MAX_FILE_SIZE_FOR_DISPLAY
    over_memory = _PARSE_COST_BYTES + 4096 if breaks == "memory" else 30 * ceiling
    over_cpu = md_parser.WORST_CASE_CPU_SECONDS + 0.01 if breaks == "cpu" else 0.1
    costs = {
        "corpus": (20 * ceiling, 0.1), "tiled_": (50 * ceiling, 0.2),
        "hostile": (290 * ceiling, 2.8),
        "outline_": (300 * ceiling, 0.5), "capped_": (30 * ceiling, 0.3),
        "worst_memory": (over_memory, 0.3), "cpu_": (20 * ceiling, over_cpu),
    }
    _wire_main(script, monkeypatch, tmp_path, costs)

    assert script.main([]) == 1

    verdict = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["verdict"]
    assert verdict["memory_within_budget"] is (breaks != "memory")
    assert verdict["cpu_within_constant"] is (breaks != "cpu")


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
    [
        ("md", "# t\n\n- a\n- b\n", None),
        # ``\r\n`` חייב להגיע לפרסר כמו שנכתב: קריאה בלי ``newline=""`` הייתה מתרגמת
        # אותו, ו-``input_bytes`` היה קטן מגודל הקובץ.
        ("md", "# t\r\n\r\n- a\r\n- b\r\n", None),
        ("rst", "T\n=\n\ntext\n", {"max_sections": 50}),
    ],
)
def test_the_measuring_child_reports_the_peak_above_the_pre_parse_high_water_mark(tmp_path, parser, text, kwargs):
    """המדידה האמיתית, פעם אחת על קובץ זעיר: הפלט נושא את המרווח שלפני הפרסור ואת השיא שמעליו."""
    script = _load_script()
    doc = tmp_path / ("tiny" + script.PARSERS[parser]["suffix"])
    doc.write_text(text, encoding="utf-8", newline="")

    result = script.peak_cost(doc, tmp_path, parser=parser, kwargs=kwargs)

    assert result["module"] == script.PARSERS[parser]["module"]
    assert result["input_bytes"] == doc.stat().st_size
    assert result["input_lines"] == text.count("\n") + 1
    assert result["outcome"] == "parsed" and result["sections"] >= 1
    assert result["headroom_kb_before_parse"] >= 0
    assert result["peak_bytes"] >= 0 and result["peak_bytes_per_input_byte"] >= 0
    assert result["peak_mib"] >= 0
    assert result["cpu_seconds"] >= 0


@pytest.mark.parametrize(
    "kwargs, outcome, line",
    [({"max_lines": 2}, "too_many_lines", None), ({"max_tokens": 4}, "too_many_tokens", 3)],
)
def test_the_measuring_child_records_a_refusal_as_an_outcome(tmp_path, kwargs, outcome, line):
    """סירוב של הפרסר הוא תוצאה שנרשמת, עם השורה כשיש — לא חריגה שמפילה את הריצה."""
    script = _load_script()
    doc = tmp_path / "refused.md"
    doc.write_text("# t\n\n- a\n- b\n", encoding="utf-8")

    result = script.peak_cost(doc, tmp_path, parser="md", kwargs=kwargs)

    assert (result["outcome"], result["line"], result["sections"]) == (outcome, line, None)


# ─── הצורות של Markdown והקלטים הגרועים ───


def test_fitting_to_the_tool_cuts_markdown_at_the_line_ceiling_and_rst_only_at_the_bytes():
    """512KB בשורות באורך רגיל עוברים את ``MAX_LINES`` — בלי החיתוך, המדידה הייתה של סירוב.

    זה מה שקרה בהרצה הראשונה על הקוד הזה: הקורפוס, המסמך הצפוף וכל הצורות העוינות
    נדחו ב-``too_many_lines`` ונמדדו באפס.
    """
    from services import md_parser

    script = _load_script()
    text = "שורה בעברית\n" * 60_000
    markdown = script.fit_to_the_tool(text, "md")
    assert markdown.count("\n") + 1 == md_parser.MAX_LINES
    assert len(markdown.encode("utf-8")) <= script.MAX_FILE_SIZE_FOR_DISPLAY
    md_parser.parse_document(markdown)  # מפורסר, לא נדחה

    rst = script.fit_to_the_tool(text, "rst")
    assert rst.count("\n") + 1 > md_parser.MAX_LINES
    ceiling = script.MAX_FILE_SIZE_FOR_DISPLAY
    assert ceiling - 3 <= len(rst.encode("utf-8")) <= ceiling


def test_a_cut_through_a_crlf_does_not_leave_a_lone_cr_for_the_parser_to_refuse():
    """חיתוך בין ``\\r`` ל-``\\n`` השאיר ``\\r`` בודד — והפרסר דחה את הצורה, ותהליך המדידה נפל.

    כך זה נמצא בהרצה האמיתית: ``blank_lines_crlf`` חתוך לתקרת השורות. עכשיו כל
    צורה, חתוכה לכלי, עוברת את שער הכניסה של הפרסר; ו-``tile`` מתקציב אי-זוגי של
    ``\\r\\n`` נגמר בלי ``\\r``.
    """
    from services import md_parser

    script = _load_script()
    for build in script.HOSTILE_SHAPES.values():
        fitted = script.fit_to_the_tool(build(script.MAX_FILE_SIZE_FOR_DISPLAY), "md")
        md_parser._entry_checks(fitted)
    assert not script.tile("\r\n", 1_001).endswith("\r")


def test_every_hostile_shape_fits_the_read_ceiling_so_the_tool_would_parse_it():
    """צורה מעל ``MAX_FILE_SIZE_FOR_DISPLAY`` הייתה נדחית ב-``too_large`` לפני הפרסור, ולא נמדדת."""
    script = _load_script()
    for name, build in script.HOSTILE_SHAPES.items():
        size = len(build(script.MAX_FILE_SIZE_FOR_DISPLAY).encode("utf-8"))
        assert 0 < size <= script.MAX_FILE_SIZE_FOR_DISPLAY, name
    assert len(script.HOSTILE_SHAPES) == 30


def test_the_table_token_count_is_the_parsers_and_the_table_passes_any_ceiling():
    """``_table_tokens`` מול הפרסר (בלי שתי הסגירות שבסוף), ו-``_table_past`` עובר כל תקרה."""
    from services import md_parser

    script = _load_script()
    for rows in (1, 3, 10):
        table = script.table_over_autocomplete_cap(rows)
        assert md_parser.token_count(table) == script._table_tokens(rows) + 2
    for ceiling in (0, 10, 777, 1_550, md_parser.MAX_TOKENS):
        table = "\n".join(script._table_past(ceiling)) + "\n"
        assert md_parser.token_count(table) > ceiling, ceiling


def test_the_worst_memory_input_sits_at_both_ceilings_with_the_table_inside_the_quote():
    """הקלט הגרוע: בתקרת הקריאה, בדיוק בתקרת השורות, והטבלה בתוכו עוברת את תקרת הטוקנים.

    ‏``\\r\\n`` ותו אסטרלי בכל שורה, והפרסור נעצר בתוך הטבלה — כלומר בזמן שרשימות
    הציטוט עוד חיות, וזה כל העניין.
    """
    from services import doc_sections, md_parser

    script = _load_script()
    text = script.worst_memory_input(md_parser.MAX_LINES, md_parser.MAX_TOKENS)

    assert len(text.encode("utf-8")) <= script.MAX_FILE_SIZE_FOR_DISPLAY
    assert text.count("\n") + 1 == md_parser.MAX_LINES
    assert text.count("\r\n") == text.count("\n")
    content_lines = text.split("\r\n")[:-len(script._table_past(md_parser.MAX_TOKENS))]
    assert all("\U0001F600" in line for line in content_lines)
    with pytest.raises(doc_sections.TooManyTokens) as caught:
        md_parser.parse_document(text)
    assert caught.value.line > md_parser.MAX_LINES - 70, "העצירה בטבלה שבסוף הציטוט"
    with pytest.raises(ValueError):
        script.worst_memory_input(10, md_parser.MAX_TOKENS)


def test_every_cpu_shape_is_parsed_and_not_refused_before_the_parse():
    """קלט מעבד שנדחה בתקרת השורות לא היה מודד כלום: כולם בתוך ``MAX_LINES``."""
    from services import md_parser

    script = _load_script()
    for name, build in script.CPU_SHAPES.items():
        text = build(md_parser.MAX_LINES, md_parser.MAX_TOKENS)
        assert text.count("\n") + 1 <= md_parser.MAX_LINES, name


# ─── בדיקת ההכפלה ───


def _run(peak_bytes, input_bytes, cpu, outcome="parsed"):
    return {
        "peak_bytes": peak_bytes, "input_bytes": input_bytes,
        "cpu_seconds": cpu, "outcome": outcome,
    }


def test_growth_calls_a_linear_shape_linear_and_a_quadratic_one_superlinear():
    """הגבול בין ליניארי לריבועי, על מספרים שנמדדו: עד 1.45 ברעש, סביב 4 בריבועי."""
    script = _load_script()
    linear = [_run(10_000, 1_000, 0.5), _run(20_100, 2_000, 1.1), _run(40_200, 4_000, 2.9)]
    quadratic_cpu = [_run(10_000, 1_000, 0.5), _run(20_000, 2_000, 2.0), _run(40_000, 4_000, 8.0)]
    quadratic_memory = [
        _run(10_000, 1_000, 0.5), _run(40_000, 2_000, 1.0), _run(160_000, 4_000, 2.0),
    ]

    assert script.growth(linear)["superlinear"] is False
    assert script.growth(quadratic_cpu) == {
        "memory_growth": 1.0, "cpu_growth": 4.0, "superlinear": True,
    }
    assert script.growth(quadratic_memory)["superlinear"] is True


def test_growth_ignores_cpu_noise_below_the_floor_but_never_memory():
    script = _load_script()
    tiny = [_run(10_000, 1_000, 0.001), _run(20_000, 2_000, 0.004), _run(40_000, 4_000, 0.03)]
    assert script.growth(tiny) == {"memory_growth": 1.0, "cpu_growth": None, "superlinear": False}


@pytest.mark.parametrize("outcome", ["memory_error", "timeout"])
def test_growth_calls_a_blown_up_run_superlinear_by_name(outcome):
    script = _load_script()
    runs = [_run(10_000, 1_000, 0.5), {"outcome": outcome, "input_bytes": 2_000}]
    assert script.growth(runs) == {
        "memory_growth": None, "cpu_growth": None, "superlinear": True, "reason": outcome}


def test_doubling_runs_every_shape_uncapped_at_three_sizes_and_exits_1_on_a_superlinear_one(
        monkeypatch, tmp_path, capsys):
    """החיווט של ``--doubling``: כל צורה בשלושה גדלים, בלי אף תקרה, וקוד יציאה 1 על ריבועית.

    צורה אחת מדומה כריבועית (העלות לפי ריבוע הגודל) ואחת חורגת מהזמן — ושתיהן
    מסומנות בשמן בשורה האחרונה. זה מה שהיה תופס את upstream #367 מראש.
    """
    import subprocess

    script = _load_script()
    seen = []

    def fake_peak_cost(path, workdir, *, parser="md", kwargs=None):
        size = len(path.read_bytes())
        seen.append((path.name, kwargs))
        if path.name.startswith("double_bullets_"):
            return _run(size * size, size, 0.5 * (size / 1000) ** 2)
        if path.name.startswith("double_ordered_list_") and size > 300_000:
            raise subprocess.TimeoutExpired(cmd="child", timeout=script.CHILD_TIMEOUT_SECONDS)
        return _run(40 * size, size, size / 100_000)

    monkeypatch.setattr(script, "peak_cost", fake_peak_cost)

    assert script.main(["--doubling"]) == 1

    last = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert set(last["superlinear"]) == {"bullets", "ordered_list"}
    assert len(seen) == 3 * len(script.HOSTILE_SHAPES)
    assert {repr(kwargs) for _name, kwargs in seen} == {
        repr({"max_sections": None, "max_lines": None, "max_tokens": None})}
    prefix = "double_tables_over_autocomplete_cap_"
    table_runs = [name for name, _kwargs in seen if name.startswith(prefix)]
    assert table_runs == [f"{prefix}{size}.md" for size in script.TABLE_DOUBLING_SIZES]
