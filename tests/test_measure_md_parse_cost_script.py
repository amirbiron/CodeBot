"""``scripts/measure_md_parse_cost.py`` — נבדק, ולא רק נכתב (סקירת #3429, WARN-005).

הסקריפט הוא המקור של ``_PARSE_RSS_PER_INPUT_BYTE`` ב-``mcp_server/server.py``,
שממנו נגזר רוחב מאגר הקריאות של ה-MCP. באג בבחירת המספר — למשל לקיחת
המדידה הראשונה במקום הגבוהה ביותר, או הקורפוס במקום המסמך הצפוף — ידפיס
מספר סביר-למראה שייכנס לייצור, ואיש לא יידע. לכן רוב הטסטים כאן הם על הבחירה
ועל החיווט, בלי תת-תהליך; והמדידה האמיתית רצה על קבצים זעירים כדי להוכיח את
מה שאי אפשר לדמות: שהאיפוס של ``VmHWM`` קרה ושהשיא נספר ממנו, שכל כשל שלו או של
ההצמדה למעבד עוצר את המדידה בקול, ושהזרע מגיע לילד.

הטעינה לפי נתיב — ``scripts/`` אינה חבילה — היא אותה תבנית כמו
``tests/test_docs_section_zero_diff_script.py``. כל קלט ופלט תחת ``tmp_path``.
"""

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("markdown_it")

#: הקובץ כולו במסלול ``md-heavy`` של ``unit-tests`` ב-``.github/workflows/ci.yml``: הסקריפט
#: שהוא בודק מודד את שיא הזיכרון ואת זמן המעבד של פרסור, כולל הקלט היקר ביותר בתקרות.
#: הסימון מוגדר ב-``pytest.ini``.
pytestmark = pytest.mark.md_heavy

_REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _cpu_mask_restored():
    """כל טסט מתחיל מאותה מסכת מעבדים, ומה שטסט השאיר אחריו אינו עובר לבא.

    ``_pinned`` מצמיד את החוט הקורא לזמן יצירת הילד. אם הוא היה דולף, הטסט הראשון עם
    ילד אמיתי היה משאיר את כל התהליך על מעבד אחד — והבדיקה שהמסכה חוזרת הייתה משווה
    אחר כך מסכה מצומצמת לעצמה ועוברת. כך בדיוק מוטציה שמוחקת את ההחזרה שרדה (T3).
    """
    import os

    if not hasattr(os, "sched_getaffinity"):
        yield
        return
    before = os.sched_getaffinity(0)
    yield
    os.sched_setaffinity(0, before)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "measure_md_parse_cost_under_test", _REPO / "scripts" / "measure_md_parse_cost.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _measurement(parser, shape, peak_bytes, *, as_tool=True, per_input_byte=0.0, cpu=0.0,
                 lag=0, **extra):
    return {
        "parser": parser, "shape": shape, "as_tool": as_tool, "peak_bytes": peak_bytes,
        "peak_upper_bound_bytes": peak_bytes + lag,
        "peak_bytes_per_input_byte": per_input_byte, "cpu_seconds": cpu, **extra,
    }


#: פיגור מונה קבוע לטסטי החיווט: החסם האמיתי נגזר ממספר המעבדים של המכונה, וטסט
#: שמשווה מספרים מדויקים לא יכול להיות תלוי בו.
_LAG = 93 * 4096


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


def test_the_constant_candidate_is_the_upper_bound_and_not_the_maximum_alone():
    """המועמד לקבוע נשען על החסם העליון — המקסימום על הסידורים ועוד פיגור המונה.

    המקסימום לבדו נמוך מהשיא האמיתי בדיוק בפיגור של מוני הקרנל, ותמיד לכיוון "נכנס";
    מועמד שמתעלם ממנו נראה בדיוק כמו מועמד נכון. כאן המקסימום הוא בדיוק 66 בתים לבית
    תקרה, והמועמד — 66 ועוד הפיגור, שני מקומות אחרי הנקודה.
    """
    script = _load_script()
    ceiling = script.MAX_FILE_SIZE_FOR_DISPLAY
    results = [_measurement("md", "worst_memory", 66 * ceiling, lag=_LAG)]
    assert script.constant_candidate(results, "md") == round(66 + _LAG / ceiling, 2)
    assert script.constant_candidate(results, "md") > 66


def _fake_child(script, costs, seen_kwargs, outcomes, seen_seeds):
    """``peak_cost`` בלי תת-תהליך: העלות והתוצאה לפי תחילית שם הקובץ, והארגומנטים והזרעים נרשמים.

    עלות יכולה להיות פונקציה של הזרע — סידור זיכרון שעולה יותר מהאחרים — ותוצאה
    יכולה להיות מילון לפי זרע.
    """

    def fake_peak_cost(path, workdir, *, parser="md", kwargs=None, seed=0):
        prefix = next(prefix for prefix in costs if path.name.startswith(prefix))
        seen_kwargs.setdefault((parser, prefix), []).append(kwargs)
        seen_seeds.setdefault((parser, prefix), []).append(seed)
        cost = costs[prefix]
        peak_bytes, cpu = cost(seed) if callable(cost) else cost
        outcome = outcomes.get(prefix, "parsed")
        if isinstance(outcome, dict):
            outcome = outcome.get(seed, "parsed")
        return {
            "module": script.PARSERS[parser]["module"],
            "hash_seed": str(seed),
            "cpu": [0],
            "input_bytes": 1,
            "outcome": outcome,
            "line": None,
            "sections": 1,
            "headroom_kb_before_reset": 0,
            "reset_probe_kb": script.RESET_PROBE_BYTES // 1024,
            "headroom_kb_before_parse": 0,
            "peak_bytes": peak_bytes,
            "peak_mib": 0.0,
            "peak_bytes_per_input_byte": float(peak_bytes),
            "retained_bytes_per_input_byte": 0.0,
            "cpu_seconds": cpu,
        }

    return fake_peak_cost


def _wire_main(script, monkeypatch, tmp_path, costs, outcomes=None, seen_seeds=None):
    docs = {".md": tmp_path / "a.md", ".rst": tmp_path / "b.rst"}
    docs[".md"].write_text("# t\n\n- one\n- two\n" * 200, encoding="utf-8")
    docs[".rst"].write_text("T\n=\n\ntext\n\n" * 200, encoding="utf-8")
    monkeypatch.setattr(script, "REPO", tmp_path)
    monkeypatch.setattr(script, "real_files", lambda suffix: [docs[suffix]])
    monkeypatch.setattr(script, "density", lambda text, parser="md": 1.0)
    monkeypatch.setattr(script, "counter_lag_bound_bytes", lambda: _LAG)
    seen_kwargs: dict = {}
    fake = _fake_child(script, costs, seen_kwargs, outcomes or {},
                       {} if seen_seeds is None else seen_seeds)
    monkeypatch.setattr(script, "peak_cost", fake)
    return seen_kwargs


def _costs_within_the_constants(ceiling):
    """(שיא, מעבד) לכל תחילית של שם קובץ, וטסט משנה רק את מה שהוא בודק.

    כל מה שרץ כמו הכלי בתוך שני הקבועים; הצורה בלי תקרות וה-outline מעליהם, כמו
    במדידה האמיתית — הם אינם כמו הכלי, ולכן אינם נשפטים.
    """
    return {
        "corpus": (20 * ceiling, 0.1), "tiled_": (50 * ceiling, 0.2),
        "hostile": (290 * ceiling, 2.8),
        "outline_": (300 * ceiling, 0.5), "capped_": (30 * ceiling, 0.3),
        "worst_memory": (60 * ceiling, 0.3), "cpu_": (20 * ceiling, 0.5),
    }


def test_main_runs_every_markdown_shape_as_the_tool_and_the_hostile_bound_without_ceilings(
        monkeypatch, tmp_path, capsys):
    """החיווט, בלי תת-תהליכים: מה רץ כמו הכלי, מה רץ בלי תקרות, ומה נכנס לשורה האחרונה.

    כמו הכלי — בלי ארגומנטים — הקורפוס, המסמך הצפוף, כל צורה עוינת בתקרת הקריאה,
    הקלט הגרוע בזיכרון, וכל קלט מעבד. בלי תקרות — הצורה העוינת, בכל פרסר עם מה
    שמכבה את התקרות **שלו** (WARN-004 בסקירת שבעת ה-PRים: עם ברירת המחדל היא נעצרת
    על תקרה, והמספר מתאר עצירה ולא את הפרסר). ה-outline עם התקרה שלו. ובכל אחד —
    ריצה לכל זרע של ``LAYOUT_SEEDS``, גם בקלטי המעבד (סבב הסקירה השלישי של #3467).
    """
    script = _load_script()
    ceiling = script.MAX_FILE_SIZE_FOR_DISPLAY
    seen_seeds: dict = {}
    seen_kwargs = _wire_main(script, monkeypatch, tmp_path, _costs_within_the_constants(ceiling),
                             seen_seeds=seen_seeds)

    assert script.main([]) == 0

    last = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert last["md"]["constant_candidate_bytes_per_input_byte"] == round(60 + _LAG / ceiling, 2)
    assert last["md"]["hostile_bound_bytes_per_input_byte"] == 290 * ceiling
    assert last["rst"]["constant_candidate_bytes_per_input_byte"] == round(50 + _LAG / ceiling, 2)
    assert last["verdict"]["md_unmeasured"] == []
    assert last["verdict"]["every_input_measured"] is True
    assert last["verdict"]["md_undersampled"] == []
    assert last["verdict"]["every_input_on_every_layout"] is True
    assert last["verdict"]["md_worst_shape"] == "worst_memory"
    assert last["verdict"]["md_worst_upper_bound_bytes"] == 60 * ceiling + _LAG
    assert last["verdict"]["memory_within_budget"] is True
    assert last["verdict"]["cpu_within_constant"] is True
    assert last["verdict"]["passed"] is True
    assert last["verdict"]["md_worst_cpu_seconds"] == 0.5

    from mcp_server.outline_scanners._ceiling import MAX_SYMBOLS

    layouts = len(script.LAYOUT_SEEDS)
    assert seen_kwargs[("md", "hostile")] == [
        {"max_sections": None, "max_lines": None, "max_tokens": None}] * layouts
    assert seen_kwargs[("rst", "hostile")] == [{"max_sections": None}] * layouts
    assert seen_kwargs[("rst", "outline_")] == [{"max_sections": MAX_SYMBOLS}] * layouts
    for key in (("md", "corpus"), ("md", "tiled_"), ("rst", "corpus"), ("rst", "tiled_"),
                ("md", "capped_"), ("md", "worst_memory"), ("md", "cpu_")):
        assert set(map(repr, seen_kwargs[key])) == {"None"}, key
    assert len(seen_kwargs[("md", "capped_")]) == len(script.HOSTILE_SHAPES) * layouts
    assert seen_seeds[("md", "worst_memory")] == list(script.LAYOUT_SEEDS)
    assert seen_seeds[("md", "cpu_")] == list(script.LAYOUT_SEEDS) * len(script.CPU_SHAPES)


def test_every_memory_measurement_runs_once_per_layout_seed_and_the_rare_layout_decides(
        monkeypatch, tmp_path, capsys):
    """40 זרעים, והסידור היקר קובע — גם כשהוא אחד מארבעים (דרישה 1–3 בסבב של #3467).

    הזרעים הם בדיוק ``LAYOUT_SEEDS``, בסדר, ולא "40 ריצות" כלשהן: הרצה חוזרת על אותו
    קוד חייבת למדוד את אותם סידורים. כאן סידור אחד, זרע 27, עולה 1MB יותר מכל השאר —
    והמספר של השורה, החסם שלה ופסק הדין נשענים עליו; המינימום והפיזור נשארים בשורה.
    """
    script = _load_script()
    ceiling = script.MAX_FILE_SIZE_FOR_DISPLAY
    base, rare = 60 * ceiling, 60 * ceiling + 1024 * 1024
    costs = _costs_within_the_constants(ceiling) | {
        "worst_memory": lambda seed: (rare if seed == 27 else base, 0.3),
    }
    seen_seeds: dict = {}
    _wire_main(script, monkeypatch, tmp_path, costs, seen_seeds=seen_seeds)

    assert script.main([]) == 0

    lines = capsys.readouterr().out.strip().splitlines()
    worst = next(json.loads(line) for line in lines if '"shape": "worst_memory"' in line)
    assert seen_seeds[("md", "worst_memory")] == list(script.LAYOUT_SEEDS)
    assert worst["layout_runs"] == len(script.LAYOUT_SEEDS) == 40
    assert worst["peak_bytes"] == rare and worst["hash_seed"] == "27"
    assert worst["peak_bytes_min"] == base
    assert worst["peak_bytes_by_layout"][27] == rare
    assert worst["peak_bytes_by_layout"].count(base) == 39
    assert worst["peak_upper_bound_bytes"] == rare + _LAG
    verdict = json.loads(lines[-1])["verdict"]
    assert verdict["md_worst_peak_bytes"] == rare
    assert verdict["md_worst_peak_min_bytes"] == base
    assert verdict["md_worst_upper_bound_bytes"] == rare + _LAG


def test_an_outcome_that_changes_between_layouts_is_not_a_measurement(
        monkeypatch, tmp_path, capsys):
    """הפרסור דטרמיניסטי: תוצאה שונה בסידור אחד אומרת שקרה שם משהו אחר, והמקסימום אינו עלות.

    ``MemoryError`` בזרע אחד מתוך ארבעים, עם שיא נמוך — K11: בלי הבדיקה, המקסימום של
    השאר היה נכנס בתקציב, ופסק הדין היה עובר על ריצה שנפלה.
    """
    script = _load_script()
    costs = _costs_within_the_constants(script.MAX_FILE_SIZE_FOR_DISPLAY)
    outcomes = {"worst_memory": {seed: "too_many_tokens" for seed in script.LAYOUT_SEEDS} | {
        13: "memory_error"}}
    _wire_main(script, monkeypatch, tmp_path, costs, outcomes=outcomes)

    assert script.main([]) == 1

    lines = capsys.readouterr().out.strip().splitlines()
    worst = next(json.loads(line) for line in lines if '"shape": "worst_memory"' in line)
    assert worst["outcome"] == script.OUTCOME_DIFFERS_BY_LAYOUT
    assert worst["outcomes_by_layout"][13] == "memory_error"
    verdict = json.loads(lines[-1])["verdict"]
    assert verdict["md_unmeasured"] == [
        {"shape": "worst_memory", "outcome": script.OUTCOME_DIFFERS_BY_LAYOUT}]
    assert verdict["passed"] is False


def test_a_cpu_input_costly_in_memory_only_on_a_late_layout_decides_memory(
        monkeypatch, tmp_path, capsys):
    """קלט מעבד שיקר בזיכרון רק בסידור מאוחר הוא המכריע, ופסק הדין נופל.

    סבב הסקירה השלישי של #3467. עד אז קלטי המעבד רצו על ``CPU_REPEATS`` סידורים בלבד,
    והבדיקה שכל הסידורים נמדדו חלה רק על המדידה המכריעה. סידור יקר שלא הוגרל השאיר את
    הקלט נמוך — ולכן גם לא מכריע — ופסק הדין עבר על קלט שהזיכרון שלו מעל התקציב. כאן
    הסידור היקר הוא האחרון ב-``LAYOUT_SEEDS``, מחוץ ל-``CPU_REPEATS`` הראשונים.
    """
    from mcp_server.server import _PARSE_COST_BYTES

    script = _load_script()
    ceiling = script.MAX_FILE_SIZE_FOR_DISPLAY
    late = script.LAYOUT_SEEDS[-1]
    assert late not in range(script.CPU_REPEATS)
    over = _PARSE_COST_BYTES + 4096
    costs = _costs_within_the_constants(ceiling) | {
        "cpu_": lambda seed: (over if seed == late else 20 * ceiling, 0.5),
    }
    _wire_main(script, monkeypatch, tmp_path, costs)

    assert script.main([]) == 1

    verdict = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["verdict"]
    assert verdict["memory_within_budget"] is False
    assert verdict["md_worst_shape"].startswith("cpu:")
    assert verdict["md_worst_peak_bytes"] == over
    assert verdict["md_worst_upper_bound_bytes"] == over + _LAG
    assert verdict["every_input_on_every_layout"] is True
    assert verdict["passed"] is False


def test_every_run_as_the_tool_must_have_run_on_every_layout_not_only_the_deciding_one(
        monkeypatch):
    """מדידה שרצה על פחות סידורים מפילה את פסק הדין — גם כשהיא לא המכריעה.

    זו בדיוק הצורה שבה הבדיקה הקודמת, על המכריעה בלבד, לא נדלקה: מקסימום על פחות
    סידורים נמוך כשהסידור היקר לא הוגרל, ולכן הוא לא נבחר כמכריע. כאן השורה החסרה
    בתוך התקציב ורחוקה מהמכריעה, ופסק הדין בכל זאת נופל: מה שהיא לא מדדה אינו ידוע.
    """
    script = _load_script()
    monkeypatch.setattr(script, "counter_lag_bound_bytes", lambda: _LAG)
    ceiling = script.MAX_FILE_SIZE_FOR_DISPLAY
    layouts = len(script.LAYOUT_SEEDS)

    def row(shape, peak_bytes, layout_runs):
        return _measurement("md", shape, peak_bytes, cpu=0.3, lag=_LAG, outcome="parsed",
                            layout_runs=layout_runs, peak_bytes_min=peak_bytes)

    results = [
        row("corpus", 20 * ceiling, layouts),
        row("worst_memory", 60 * ceiling, layouts),
        row("cpu:lazy_quote_then_table", 20 * ceiling, script.CPU_REPEATS),
    ]

    verdict = script.verdict(results)

    assert verdict["passed"] is False
    assert verdict["md_undersampled"] == [
        {"shape": "cpu:lazy_quote_then_table", "layout_runs": script.CPU_REPEATS}]
    assert verdict["every_input_on_every_layout"] is False
    assert verdict["md_worst_shape"] == "worst_memory"
    assert verdict["every_input_measured"] is True
    assert verdict["memory_within_budget"] is True
    assert verdict["cpu_within_constant"] is True


def test_a_cpu_input_is_judged_on_its_first_cpu_repeats_runs_and_keeps_the_rest(
        monkeypatch, tmp_path, capsys):
    """קלטי המעבד רצים על כל ``LAYOUT_SEEDS``, והמעבד שלהם נשפט על ``CPU_REPEATS`` הראשונות.

    הבקשה בסבב הסקירה השלישי של #3467: לכסות את הזיכרון **בלי** לשנות את מספר החזרות
    שבודק את המעבד, כי ``WORST_CASE_CPU_SECONDS`` נגזר ממקסימום על ``CPU_REPEATS`` ריצות.
    כאן ריצה מאוחרת עוברת את הקבוע: היא נשמרת בשורה (``cpu_seconds_all``) ואינה נשפטת.
    """
    from services import md_parser

    script = _load_script()
    ceiling = script.MAX_FILE_SIZE_FOR_DISPLAY
    late = script.LAYOUT_SEEDS[-1]
    assert late not in range(script.CPU_REPEATS)
    slow = md_parser.WORST_CASE_CPU_SECONDS + 0.2
    costs = _costs_within_the_constants(ceiling) | {
        "cpu_": lambda seed: (20 * ceiling, slow if seed == late else 0.5),
    }
    _wire_main(script, monkeypatch, tmp_path, costs)

    assert script.main([]) == 0

    lines = capsys.readouterr().out.strip().splitlines()
    rows = [json.loads(line) for line in lines if '"shape": "cpu:' in line]
    assert len(rows) == len(script.CPU_SHAPES)
    for cpu_row in rows:
        assert cpu_row["layout_runs"] == len(script.LAYOUT_SEEDS)
        assert cpu_row["cpu_timed_runs"] == script.CPU_REPEATS
        assert cpu_row["cpu_seconds"] == 0.5
        assert len(cpu_row["cpu_seconds_all"]) == len(script.LAYOUT_SEEDS)
        assert cpu_row["cpu_seconds_all"][late] == slow
    verdict = json.loads(lines[-1])["verdict"]
    assert verdict["md_worst_cpu_seconds"] == 0.5
    assert verdict["cpu_within_constant"] is True
    assert verdict["passed"] is True


@pytest.mark.parametrize("breaks", ["memory", "memory_only_with_the_lag", "cpu"])
def test_main_exits_1_when_a_measurement_breaks_a_constant_it_feeds(
        monkeypatch, tmp_path, capsys, breaks):
    """החסם העליון מעל ``_PARSE_COST_BYTES``, או מעבד מעל ``WORST_CASE_CPU_SECONDS`` — קוד יציאה 1.

    אלה שני הקבועים שהמאגר, מגבלת הקצב והדדליין נגזרים מהם. מדידה שעוברת אחד מהם
    ויוצאת ב-0 הייתה משאירה את כל שלושת החשבונות על מספר שכבר אינו נכון. והזיכרון
    נשפט על החסם ולא על המקסימום: ``memory_only_with_the_lag`` הוא מקסימום שנכנס
    בתקציב, עם פיגור מונה שמעביר אותו — ופסק הדין נופל, כי זה מה שהשיא האמיתי יכול להיות.
    """
    from mcp_server.server import _PARSE_COST_BYTES
    from services import md_parser

    script = _load_script()
    ceiling = script.MAX_FILE_SIZE_FOR_DISPLAY
    over_memory = {
        "memory": _PARSE_COST_BYTES + 4096,
        "memory_only_with_the_lag": _PARSE_COST_BYTES - _LAG // 2,
    }.get(breaks, 30 * ceiling)
    over_cpu = md_parser.WORST_CASE_CPU_SECONDS + 0.01 if breaks == "cpu" else 0.1
    costs = _costs_within_the_constants(ceiling) | {
        "worst_memory": (over_memory, 0.3), "cpu_": (20 * ceiling, over_cpu),
    }
    _wire_main(script, monkeypatch, tmp_path, costs)

    assert script.main([]) == 1

    verdict = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["verdict"]
    assert verdict["every_input_measured"] is True
    assert verdict["memory_within_budget"] is (breaks == "cpu")
    assert verdict["cpu_within_constant"] is (breaks != "cpu")
    assert verdict["passed"] is False
    if breaks == "memory_only_with_the_lag":
        assert verdict["md_worst_peak_bytes"] <= _PARSE_COST_BYTES < verdict[
            "md_worst_upper_bound_bytes"]


@pytest.mark.parametrize("outcome", ["memory_error", "too_many_lines"])
def test_main_exits_1_when_a_run_as_the_tool_measured_no_parse(
        monkeypatch, tmp_path, capsys, outcome):
    """מדידה כמו הכלי שלא מדדה פרסור מפילה את פסק הדין — גם כשהמספרים שלה בתוך הקבועים.

    ``memory_error``: הפרסור נפל על ``RLIMIT_AS``, והשיא הוא רק מה שהספיק לתפוס לפני
    ההקצאה שנכשלה. כך נראתה הרצה אמיתית של הילד על הקלט הגרוע, עם ``RLIMIT_AS`` של
    12MB מעל מה שהייבוא תפס (סקירת #3467): ``memory_error`` עם שיא של כ-10.5MB, מתחת
    לתקציב — ופסק הדין אמר ``true`` בשתי השאלות (בילד עם האיפוס, 2026-09-27, חמישה
    סידורים: 10,612,736–10,969,088 בתים, ופסק הדין נופל). ``too_many_lines``: הקלט
    נדחה לפני הפרסור ונמדד אפס — כך נראתה ההרצה הראשונה על הקוד של #3391, לפני
    ``fit_to_the_tool``: 32 מתוך 38 המדידות כמו הכלי היו סירובים, ופסק הדין עבר.
    """
    script = _load_script()
    costs = _costs_within_the_constants(script.MAX_FILE_SIZE_FOR_DISPLAY) | {
        "worst_memory": (10_493_952, 0.3),
    }
    _wire_main(script, monkeypatch, tmp_path, costs, outcomes={"worst_memory": outcome})

    assert script.main([]) == 1

    verdict = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["verdict"]
    assert verdict["md_unmeasured"] == [{"shape": "worst_memory", "outcome": outcome}]
    assert verdict["every_input_measured"] is False
    assert verdict["memory_within_budget"] is True and verdict["cpu_within_constant"] is True
    assert verdict["passed"] is False


@pytest.mark.parametrize(
    "prefix, outcome",
    [("worst_memory", "too_many_tokens"), ("capped_", "too_many_sections"),
     ("hostile", "memory_error")],
)
def test_a_parse_stopped_by_a_ceiling_counts_and_a_run_without_ceilings_is_not_judged(
        monkeypatch, tmp_path, capsys, prefix, outcome):
    """עצירה בתקרה היא מדידה, ומדידה שלא רצה כמו הכלי אינה נשפטת.

    הקלט הגרוע בזיכרון **בנוי** להיעצר ב-``too_many_tokens`` — פסק דין שהיה דוחה את
    העצירה היה נכשל בכל הרצה אמיתית. ``too_many_sections`` אינו נגיש ב-Markdown היום
    (``MAX_SECTIONS`` גדול מ-``MAX_LINES``), אבל גם הוא נזרק מתוך הפרסור או אחריו,
    כלומר אחרי שהעלות שולמה. והצורה העוינת בלי תקרות היא מידע על הפרסר, לא טענה על הכלי.
    """
    script = _load_script()
    costs = _costs_within_the_constants(script.MAX_FILE_SIZE_FOR_DISPLAY)
    _wire_main(script, monkeypatch, tmp_path, costs, outcomes={prefix: outcome})

    assert script.main([]) == 0

    verdict = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["verdict"]
    assert verdict["md_unmeasured"] == []
    assert verdict["passed"] is True


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


@pytest.mark.parametrize("online, batch", [(4, 32), (16, 32), (17, 34), (64, 128)])
def test_the_counter_lag_bound_is_three_counters_short_of_one_batch_each(
        monkeypatch, online, batch):
    """החסם של פיגור המונה, לפי הקרנל: שלושה מונים, וכל אחד עד ``batch − 1`` עמודים בחוץ.

    ``batch = max(32, 2 × המעבדים המחוברים)`` (``compute_batch_value``), ולכן עד 16
    מעבדים הפיגור קבוע, ומעליהם הוא גדל. בלי מספר מעבדים אין חסם — והמדידה נעצרת.
    """
    import mmap
    import os

    script = _load_script()
    monkeypatch.setattr(os, "uname", lambda: _uname("Linux", "6.18.44-fc-v37"))
    monkeypatch.setattr(os, "cpu_count", lambda: online)
    assert script.counter_lag_bound_bytes() == 3 * (batch - 1) * mmap.PAGESIZE

    monkeypatch.setattr(os, "cpu_count", lambda: None)
    with pytest.raises(SystemExit, match="counter lag cannot be bounded"):
        script.counter_lag_bound_bytes()


def _uname(sysname, release):
    """``os.uname()`` של מערכת אחרת — רק ``sysname`` ו-``release`` נקראים בסקריפט."""
    import os

    return os.uname_result((sysname, "host", release, "#1", "x86_64"))


@pytest.mark.parametrize(
    "sysname, release, proven",
    [
        # הקרנל שהמספרים המתועדים נמדדו עליו (2026-09-27).
        ("Linux", "6.18.44-fc-v37", True),
        # ה-runner של GitHub ל-ubuntu-24.04, שה-CI מריץ עליו ילד אמיתי (לפי ה-README של
        # actions/runner-images, תמונה 20260920.314.1).
        ("Linux", "6.17.0-1022-azure", True),
        # הגרסה הראשונה שהחסם מוכח עליה, גם כגרסת מועמד.
        ("Linux", "6.16.0-rc3+", True),
        ("Linux", "7.0.1", True),
        # מונים לכל מעבד, אבל VmRSS נקרא משוער — השיא יכול לחסור עד פי שניים מהחסם.
        ("Linux", "6.15.11-200.fc42.x86_64", False),
        # מודל אחר של מונים (``SPLIT_RSS_COUNTING``), שהנוסחה אינה חלה עליו.
        ("Linux", "6.1.0-18-amd64", False),
        ("Linux", "5.15.0-1057-aws", False),
        # מספר גדול יותר, ובכל זאת לא לינוקס.
        ("Darwin", "23.1.0", False),
        ("Linux", "unknown", False),
    ],
)
def test_the_counter_lag_bound_exists_only_on_a_kernel_it_was_proven_on(
        monkeypatch, sysname, release, proven):
    """הנוסחה של הפיגור נגזרה מקוד הקרנל של גרסה מסוימת, ועל קרנל אחר היא אינה חסם (#3467).

    לפני 6.16 גם VmRSS נקרא משוער, ולפני 6.2 המונים בכלל אחרים — ושם "חסם עליון" היה
    מספר שנראה בדיוק כמו חסם ואינו. לכן בלי קרנל מוכח אין חסם, והמדידה נעצרת.
    """
    import mmap
    import os

    script = _load_script()
    monkeypatch.setattr(os, "uname", lambda: _uname(sysname, release))
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    if proven:
        assert script.counter_lag_bound_bytes() == 3 * 31 * mmap.PAGESIZE
    else:
        with pytest.raises(SystemExit, match="refusing to measure"):
            script.counter_lag_bound_bytes()


def test_a_measurement_on_a_kernel_the_bound_is_not_proven_on_stops_before_any_child(
        monkeypatch, tmp_path):
    """עצירה לפני הילד הראשון — לא אחרי שמדדנו, ולא בפסק הדין בלבד.

    אותו כלל כמו האיפוס וההצמדה: אין "נמדוד בכל זאת" עם חסם שאיש לא הוכיח.
    """
    import os

    script = _load_script()
    doc = tmp_path / "tiny.md"
    doc.write_text("# t\n", encoding="utf-8")
    monkeypatch.setattr(os, "uname", lambda: _uname("Linux", "6.15.11-200.fc42.x86_64"))

    def no_child(*args, **kwargs):
        pytest.fail("a measuring child was started on a kernel the bound is not proven on")

    monkeypatch.setattr(script.subprocess, "run", no_child)
    with pytest.raises(SystemExit, match="older than Linux"):
        script.peak_cost(doc, tmp_path)


@pytest.mark.parametrize("failure", ["platform_has_no_affinity", "setaffinity_refused"])
def test_a_measurement_that_cannot_pin_its_child_stops_loudly(monkeypatch, tmp_path, failure):
    """ההצמדה היא של המדידה, ובלעדיה הפיגור אינו חסום — ולכן אין "נמדוד בכל זאת" (דרישה 4).

    אותו כלל כמו האיפוס: לא נופלים בשקט למדידה על כמה מעבדים, שהייתה נראית בדיוק
    אותו דבר ומחזירה מספר עם פיגור שאיש לא חסם.
    """
    import os

    script = _load_script()
    doc = tmp_path / "tiny.md"
    doc.write_text("# t\n", encoding="utf-8")
    if failure == "platform_has_no_affinity":
        monkeypatch.delattr(os, "sched_setaffinity")
        expected = "sched_setaffinity is not available"
    else:
        def refuse(pid, mask):
            raise OSError(22, "Invalid argument")

        monkeypatch.setattr(os, "sched_setaffinity", refuse)
        expected = "cannot pin the measuring child"
    with pytest.raises(SystemExit, match=expected):
        script.peak_cost(doc, tmp_path)


def test_a_probe_too_small_to_tell_a_reset_from_none_stops_loudly(monkeypatch, tmp_path):
    """איפוס שקרה משאיר עד פיגור המונה, ושלא קרה — לפחות חצי probe. בלי פער ביניהם אין הוכחה."""
    script = _load_script()
    doc = tmp_path / "tiny.md"
    doc.write_text("# t\n", encoding="utf-8")
    monkeypatch.setattr(script, "counter_lag_bound_bytes", lambda: script.RESET_PROBE_BYTES // 2)
    with pytest.raises(SystemExit, match="raise RESET_PROBE_BYTES"):
        script.peak_cost(doc, tmp_path)


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
def test_the_measuring_child_reports_the_peak_since_the_reset(tmp_path, parser, text, kwargs):
    """המדידה האמיתית על קובץ זעיר: ה-probe הרים את השיא, האיפוס הוריד אותו, והשיא נספר מאז.

    ``reset_probe_kb`` — לפחות חצי ה-probe מעל ה-RSS לפני האיפוס; ``headroom_kb_before_parse``
    — לכל היותר פיגור המונה אחריו. ילד שלא איפס היה נעצר לפני שהגיע לכאן.
    """
    script = _load_script()
    doc = tmp_path / ("tiny" + script.PARSERS[parser]["suffix"])
    doc.write_text(text, encoding="utf-8", newline="")

    result = script.peak_cost(doc, tmp_path, parser=parser, kwargs=kwargs)

    assert result["module"] == script.PARSERS[parser]["module"]
    assert result["input_bytes"] == doc.stat().st_size
    assert result["input_lines"] == text.count("\n") + 1
    assert result["outcome"] == "parsed" and result["sections"] >= 1
    assert result["reset_probe_kb"] * 1024 >= script.RESET_PROBE_BYTES // 2
    assert 0 <= result["headroom_kb_before_parse"] <= script.counter_lag_bound_bytes() // 1024
    assert result["peak_bytes"] >= 0 and result["peak_bytes_per_input_byte"] >= 0
    assert result["peak_bytes"] < script.RESET_PROBE_BYTES // 2, "השיא אינו כולל את ה-probe"
    assert result["peak_mib"] >= 0
    assert result["cpu_seconds"] >= 0


def test_the_peak_counts_from_the_rss_before_the_parse_so_a_reset_residue_is_counted_not_dropped():
    """הנוסחה, בלי תת-תהליך: השיא הוא ``VmHWM`` שאחרי פחות ה-RSS **שלפני**, לא ``VmHWM`` שלפני.

    אחרי איפוס אמיתי שני אלה נבדלים רק בשארית שהאיפוס משאיר, ומדדנו אותה: 0 או
    100KB על אותו קלט. החיסור מה-RSS סופר את השארית — ספירת-יתר, הכיוון הבטוח; חיסור
    מ-``VmHWM`` שלפני הפרסור (הנוסחה של השיטה הישנה) היה מוריד אותה מהשיא — ספירת-חסר,
    הכיוון שהסבב הזה סוגר. בילד אמיתי השארית כמעט תמיד 0, ולכן רק כאן אפשר לראות את ההבדל.
    """
    script = _load_script()
    raw = {
        "input_bytes": 512_000, "rss_kb_before_parse": 10_000, "hwm_kb_before_parse": 10_100,
        "hwm_kb_after_parse": 15_000, "rss_kb_after_parse": 10_500,
    }
    derived = script._from_the_kernel(raw)
    assert derived["peak_bytes"] == 5_000 * 1024
    assert derived["headroom_kb_before_parse"] == 100
    assert derived["peak_bytes_per_input_byte"] == round(5_000 * 1024 / 512_000, 1)
    assert derived["retained_bytes_per_input_byte"] == round(500 * 1024 / 512_000, 1)
    assert derived["rss_kb_before_parse"] == 10_000, "הקריאות הגולמיות נשארות בשורה"


def test_the_reset_keeps_a_peak_reached_before_the_parse_out_of_the_measurement(
        monkeypatch, tmp_path):
    """תנאי 5: הקצאה גדולה ושחרורה לפני המדידה — והשיא הנמדד אינו כולל אותה, ואינו נבלע תחתיה.

    ההקצאה היא החימום של הילד — הפרסור שרץ לפני האיפוס — מוחלף בחימום גדול (7,000
    פריטי רשימה), שמשחרר את רוב מה שהקצה ומשאיר שיא גבוה מה-RSS
    (``headroom_kb_before_reset``). הקלט הנמדד (4,000 פריטים) עולה פחות מהשיא הזה.
    שלוש טענות: החימום באמת השאיר שיא — אחרת הטסט לא מוכיח כלום; השיא הנמדד קטן
    ממנו — בלי האיפוס הוא היה נספר מעליו ומכיל אותו; והשיא הנמדד אינו אפס — ובגלל
    שהוא קטן משיא החימום, השיטה שלפני #3467 (מעל הגבוה מבין ה-RSS ושיא-העבר) הייתה
    מחזירה כאן אפס. מתחת ל-4,000 פריטים הטענה השלישית אינה יציבה: הפרסור ממלא קודם
    זיכרון פנוי שהחימום השאיר בתהליך, ושם ה-RSS אינו גדל (בכיול, על שמונה זרעים:
    2,000 פריטים נמדדו 0.84–1.88MB, 4,000 — 4.85–5.90MB, מול שיא חימום של 10.8–11.9MB).
    """
    script = _load_script()
    doc = tmp_path / "measured.md"
    doc.write_text("- item\n" * 4_000, encoding="utf-8")
    monkeypatch.setitem(script.PARSERS["md"], "warm", "- item\n" * 7_000)

    result = script.peak_cost(doc, tmp_path)

    earlier_peak = result["headroom_kb_before_reset"] * 1024
    measured = result["peak_bytes"]
    assert earlier_peak >= 4 * 1024 * 1024, "החימום הגדול לא השאיר שיא — הטסט לא מוכיח כלום"
    assert measured < earlier_peak, "השיא הנמדד כולל את השיא שלפני הפרסור"
    assert measured >= 1024 * 1024, "השיא הנמדד נבלע מתחת לשיא שלפני הפרסור"


@pytest.mark.parametrize("target", ["missing", "not_proc"])
def test_a_reset_that_cannot_be_written_or_does_not_happen_stops_the_measurement(
        monkeypatch, tmp_path, target):
    """תנאי 3: קובץ שלא קיים, או כתיבה שמתקבלת בלי לאפס — עצירה עם הודעה, לא מדידה בשיטה הישנה.

    ``not_proc`` הוא קובץ רגיל: הכתיבה עוברת, ושום שיא לא יורד — בדיוק מה ש-
    ``proc_pid_clear_refs(5)`` מתאר לערך שהקרנל אינו מכיר ("has no effect").
    """
    script = _load_script()
    doc = tmp_path / "tiny.md"
    doc.write_text("# t\n", encoding="utf-8")
    if target == "missing":
        path, expected = tmp_path / "missing" / "clear_refs", "cannot reset VmHWM through"
    else:
        path, expected = tmp_path / "clear_refs.txt", "accepted the write but VmHWM was not reset"
        path.write_text("", encoding="utf-8")
    monkeypatch.setattr(script, "CLEAR_REFS_PATH", str(path))

    with pytest.raises(SystemExit, match=expected):
        script.peak_cost(doc, tmp_path)


def test_the_pin_belongs_to_the_measurement_and_the_seed_reaches_the_child(tmp_path):
    """דרישה 4 ו-3: הילד רץ על מעבד אחד ועם הזרע שביקשו — והחוט הקורא חוזר למסכה שלו.

    הילד מדווח מה **הוא** רואה (``sched_getaffinity``, ``PYTHONHASHSEED`` בסביבה שלו),
    לא מה שביקשו ממנו.
    """
    import os

    script = _load_script()
    doc = tmp_path / "tiny.md"
    doc.write_text("# t\n", encoding="utf-8")
    before = os.sched_getaffinity(0)

    result = script.peak_cost(doc, tmp_path, seed=7)

    assert result["cpu"] == [min(before)]
    assert result["hash_seed"] == "7"
    assert os.sched_getaffinity(0) == before


def test_a_child_that_is_not_pinned_refuses_to_measure(monkeypatch, tmp_path):
    """הילד קורא את ההצמדה שלו ולא מניח אותה: בלי ``_pinned`` הוא עוצר, ולא מודד עם פיגור לא חסום."""
    import contextlib
    import os

    if len(os.sched_getaffinity(0)) < 2:
        pytest.skip("על מעבד אחד כל ילד מוצמד ממילא")
    script = _load_script()
    doc = tmp_path / "tiny.md"
    doc.write_text("# t\n", encoding="utf-8")
    monkeypatch.setattr(script, "_pinned", lambda cpu: contextlib.nullcontext())

    with pytest.raises(SystemExit, match="is not pinned to CPU"):
        script.peak_cost(doc, tmp_path)


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
    """הגבול בין ליניארי לריבועי, על מספרים שנמדדו (``--doubling`` עם האיפוס, 4.2.0, 2026-09-27).

    הטבלאות מעל תקרת התאים הן היחס הגבוה ביותר באותה ריצה — 1.56 במעבד — ועדיין
    מתחת ל-``SUPERLINEAR_GROWTH``; ריבועי, מנקודת ההתחלה של התבליטים, הוא סביב 4.
    """
    script = _load_script()
    tables = [
        _run(136_826_880, 3_090, 0.897), _run(344_440_832, 7_725, 2.115),
        _run(690_663_424, 15_450, 7.014),
    ]
    bullets = [
        _run(37_150_720, 128_000, 0.539), _run(73_867_264, 256_000, 1.007),
        _run(150_167_552, 512_000, 2.026),
    ]
    quadratic_cpu = [
        _run(37_150_720, 128_000, 0.5), _run(74_301_440, 256_000, 2.0),
        _run(148_602_880, 512_000, 8.0),
    ]
    quadratic_memory = [
        _run(37_150_720, 128_000, 0.5), _run(148_602_880, 256_000, 1.0),
        _run(594_411_520, 512_000, 2.0),
    ]

    assert script.growth(tables) == {
        "memory_growth": 1.01, "cpu_growth": 1.56, "superlinear": False}
    assert script.growth(bullets) == {
        "memory_growth": 1.01, "cpu_growth": 0.94, "superlinear": False}
    assert script.growth(quadratic_cpu) == {
        "memory_growth": 1.0, "cpu_growth": 4.0, "superlinear": True}
    assert script.growth(quadratic_memory) == {
        "memory_growth": 4.0, "cpu_growth": 1.0, "superlinear": True}


def test_growth_checks_each_resource_only_above_its_noise_floor():
    """מתחת לרצפה היחס הוא רעש, ולכן הוא ``None`` — ורק גדילה שנמדדה מסמנת ``superlinear``.

    ``nested_bullets_10`` אמיתי (``--doubling`` עם האיפוס): מעבד של אלפיות בודדות בגודל
    הגדול אינו נבדק, והזיכרון שלו — 1.13MB בגודל הקטן, מעל ``MEMORY_NOISE_FLOOR_BYTES`` —
    כן. ושיא אפס בגודל הקטן, זיכרון שנבלע כולו מתחת לשיא-העבר של התהליך, היה הופך את
    השיא בגודל הגדול ליחס אינסופי ומסמן צורה ליניארית כריבועית (סקירת CodeRabbit ב-#3467). עכשיו
    הזיכרון שלה אינו נבדק, והמעבד, שמעל הרצפה שלו, כן — ומסמן לבדו כשהוא ריבועי.
    """
    script = _load_script()
    floor = script.MEMORY_NOISE_FLOOR_BYTES
    nested_bullets_10 = [
        _run(1_134_592, 128_000, 0.007), _run(2_666_496, 256_000, 0.016),
        _run(5_869_568, 512_000, 0.032),
    ]
    swallowed = [
        _run(0, 128_000, 0.2), _run(20_000_000, 256_000, 0.4), _run(40_000_000, 512_000, 0.8),
    ]
    swallowed_quadratic_cpu = [
        _run(0, 128_000, 0.2), _run(20_000_000, 256_000, 0.8), _run(40_000_000, 512_000, 3.2),
    ]
    # רצפת המעבד יושבת על הגודל הגדול: 50ms בגודל הקטן הם מתחת לה, אבל מה שנעשה יקר
    # רק בגודל הגדול הוא בדיוק מה שהבדיקה קיימת בשבילו.
    cheap_then_quadratic_cpu = [
        _run(36_859_904, 128_000, 0.05), _run(73_719_808, 256_000, 0.2),
        _run(147_439_616, 512_000, 0.8),
    ]

    assert script.growth(nested_bullets_10) == {
        "memory_growth": 1.29, "cpu_growth": None, "superlinear": False}
    assert script.growth(swallowed) == {
        "memory_growth": None, "cpu_growth": 1.0, "superlinear": False}
    assert script.growth(swallowed_quadratic_cpu) == {
        "memory_growth": None, "cpu_growth": 4.0, "superlinear": True}
    assert script.growth(cheap_then_quadratic_cpu) == {
        "memory_growth": 1.0, "cpu_growth": 4.0, "superlinear": True}
    # הגבול עצמו: ברצפה הזיכרון נבדק, ובית אחד מתחתיה — לא.
    for first, measured in ((floor, True), (floor - 1, False)):
        runs = [_run(first, 128_000, 0.2), _run(2 * floor, 256_000, 0.4),
                _run(4 * floor, 512_000, 0.8)]
        assert (script.growth(runs)["memory_growth"] is not None) is measured, first


def test_a_shape_under_the_memory_floor_fits_one_parse_even_if_quadratic():
    """הטענה ב-docstring של ``MEMORY_NOISE_FLOOR_BYTES``, מחושבת ולא מוקלדת.

    הזיכרון של צורה שמתחת לרצפה בגודל הקטן אינו נבדק לגדילה, וזה בטוח רק כי גם
    ריבועית היא נשארת בגודל הגדול של ``DOUBLING_SIZES`` — תקרת הקריאה — בתוך מה
    שהמאגר מקצה לפרסור אחד. רצפה שתעלה מעבר לזה תפיל את הטסט הזה.
    """
    from mcp_server.server import _PARSE_COST_BYTES

    script = _load_script()
    small, *_, large = script.DOUBLING_SIZES
    assert large == script.MAX_FILE_SIZE_FOR_DISPLAY
    assert script.MEMORY_NOISE_FLOOR_BYTES * (large / small) ** 2 <= _PARSE_COST_BYTES


@pytest.mark.parametrize("outcome", ["memory_error", "timeout"])
def test_growth_calls_a_blown_up_run_superlinear_by_name(outcome):
    script = _load_script()
    runs = [_run(10_000, 1_000, 0.5), {"outcome": outcome, "input_bytes": 2_000}]
    assert script.growth(runs) == {
        "memory_growth": None, "cpu_growth": None, "superlinear": True, "reason": outcome}


def test_the_memory_floor_outweighs_the_counter_lag_or_the_doubling_check_stops(monkeypatch):
    """הרצפה מגינה על היחס רק כשהיא מעל פי 2.25 מפיגור המונה; במכונה שבה לא — עוצרים, לא מנחשים.

    בגבול עצמו: פיגור שעבורו הרצפה היא בדיוק מה שצריך — עוצרים; פיגור קטן מזה בבית —
    ממשיכים. והפיגור של מכונה עם 64 מעבדים (1.5MB) עוצר, כי שם צורה ליניארית
    ברצפה הייתה נמדדת כריבועית.
    """
    import mmap

    script = _load_script()
    floor = script.MEMORY_NOISE_FLOOR_BYTES
    # F > L·(1 + g·r) / (r·(g − 1)) עם r = 4 ו-g = 2: הפיגור הגבולי הוא F·4/9.
    boundary = floor * 4 / 9
    monkeypatch.setattr(script, "counter_lag_bound_bytes", lambda: boundary)
    with pytest.raises(SystemExit, match="Refusing to run the doubling check"):
        script._require_a_memory_floor_above_the_counter_lag()
    monkeypatch.setattr(script, "counter_lag_bound_bytes", lambda: boundary - 1)
    script._require_a_memory_floor_above_the_counter_lag()
    monkeypatch.setattr(script, "counter_lag_bound_bytes", lambda: 3 * 127 * mmap.PAGESIZE)
    with pytest.raises(SystemExit, match="Refusing to run the doubling check"):
        script._require_a_memory_floor_above_the_counter_lag()
    # ודרך הכניסה האמיתית, לפני שמשהו נמדד: ``--doubling`` עוצר, ואף ילד לא נוצר.
    monkeypatch.setattr(script, "peak_cost", lambda *a, **k: pytest.fail("measured anyway"))
    with pytest.raises(SystemExit, match="Refusing to run the doubling check"):
        script.main(["--doubling"])


def test_doubling_runs_every_shape_uncapped_at_three_sizes_and_exits_1_on_a_superlinear_one(
        monkeypatch, tmp_path, capsys):
    """החיווט של ``--doubling``: כל צורה בשלושה גדלים, בלי אף תקרה, וקוד יציאה 1 על ריבועית.

    צורה אחת מדומה כריבועית (העלות לפי ריבוע הגודל) ואחת חורגת מהזמן — ושתיהן
    מסומנות בשמן בשורה האחרונה. זה מה שהיה תופס את upstream #367 מראש.
    """
    import subprocess

    script = _load_script()
    seen = []

    def fake_peak_cost(path, workdir, *, parser="md", kwargs=None, seed=0):
        size = len(path.read_bytes())
        seen.append((path.name, kwargs))
        if path.name.startswith("double_bullets_"):
            return _run(size * size, size, 0.5 * (size / 1000) ** 2)
        if path.name.startswith("double_ordered_list_") and size > 300_000:
            raise subprocess.TimeoutExpired(cmd="child", timeout=script.CHILD_TIMEOUT_SECONDS)
        return _run(40 * size, size, size / 100_000)

    monkeypatch.setattr(script, "peak_cost", fake_peak_cost)
    monkeypatch.setattr(script, "counter_lag_bound_bytes", lambda: _LAG)

    assert script.main(["--doubling"]) == 1

    last = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert set(last["superlinear"]) == {"bullets", "ordered_list"}
    assert len(seen) == 3 * len(script.HOSTILE_SHAPES)
    assert {repr(kwargs) for _name, kwargs in seen} == {
        repr({"max_sections": None, "max_lines": None, "max_tokens": None})}
    prefix = "double_tables_over_autocomplete_cap_"
    table_runs = [name for name, _kwargs in seen if name.startswith(prefix)]
    assert table_runs == [f"{prefix}{size}.md" for size in script.TABLE_DOUBLING_SIZES]
