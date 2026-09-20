#!/usr/bin/env python3
"""כמה זיכרון עולה פרסור מסמך אחד — המספר שמאגר הקריאות של ה-MCP נגזר ממנו.

``mcp_server/server.py`` מגדיר את ``_PARSE_RSS_PER_INPUT_BYTE`` — שיא ה-RSS
שפרסור אחד מוסיף לכל בית קלט — ומחלק בו את תקציב הזיכרון של הקונטיינר כדי
לקבוע כמה קריאות רצות במקביל (#3391). הסקריפט מודד את המספר מחדש **לשני
הפרסרים**: ``services.md_parser`` (markdown-it-py), שעליו הקבוע נמדד ושהכלי
של PR 5 יריץ, ו-``services.rst_parser``, שהכלי הציבורי
``codekeeper_docs_get_section`` מריץ היום. מריצים אותו כשאחד משניהם משתנה,
במקום להעתיק מספר מזיכרון.

מה נמדד, ולמה דווקא כך:

- **שיא** ה-RSS בזמן הפרסור (``VmHWM`` ב-``/proc/self/status``), ולא מה
  שנשאר אחריו — ``parse_document`` משחרר את הטוקנים ומחזיר ``Document`` קטן
  בהרבה, אבל כמה פרסורים במקביל מחזיקים כל אחד את השיא שלו בו-זמנית.
  ``VmHWM`` נקרא גם **לפני** הפרסור, ומה שנזקף לפרסור הוא רק מה שמעל הגבוה
  מבין ה-RSS ושיא-העבר; בלי זה זיכרון שהייבוא כבר הגיע אליו ושחרר היה נספר
  כאילו הפרסור הוסיף אותו. ``headroom_kb_before_parse`` בפלט אומר כמה זה היה.
- דרך ``services.md_parser`` ו-``services.rst_parser`` עצמם, כלומר בדיוק
  בתצורה שהכלים מריצים.
- כל פרסור בתהליך נקי משלו (``python -B``, בתיקייה זמנית), כדי שהמדידה לא
  תכלול זיכרון של פרסור קודם.
- לכל פרסר שלוש צורות: הקורפוס האמיתי של הריפו (כל הקבצים בסיומת שלו, חתוכים
  לתקרת הקריאה ``MAX_FILE_SIZE_FOR_DISPLAY``); המסמך הצפוף ביותר בו משוכפל עד
  התקרה — זה המועמד לקבוע, כי זה הגרוע ביותר שהכלי באמת מגיש; וצורה עוינת
  (Markdown: שורות-תבליט בודדות, RST: כותרת בת תו אחד בכל שורה) שהיא הגבול
  העליון של הפרסר ושהקבוע במפורש אינו מכסה. שלוש הצורות רצות על ברירת
  המחדל של ``max_sections`` — ``MAX_SECTIONS`` בשני הפרסרים מאז #3420 — כלומר
  בדיוק כמו הכלי; הצורה העוינת של RST נעצרת לכן על התקרה, והמחיר בלי
  התקרה נמדד רק אם מעבירים ``max_sections=None`` במפורש. ל-RST נמדד גם מסלול ה-outline
  של ``codekeeper_get_repo_file``: המסמך הצפוף ביותר משוכפל עד
  ``RANGE_READ_MAX_BYTES`` ומפורסר עם ``max_sections`` של ``MAX_SYMBOLS``,
  כי זו ההחזקה הגדולה ביותר שחוט קריאה נושא היום, והיא גדולה מעלות הפרסור
  שהמאגר מתומחר לפיה (ראו ``_PARSE_COST_BYTES``).
- העלות נגזרת מ**צפיפות** המסמך — טוקני בלוק ל-KB ב-Markdown, סקשנים ל-KB
  ב-RST — ולא מגודלו, ולכן הצורות נותנות מספרים שונים מאוד.

הרצה מהשורש של הריפו::

    python scripts/measure_md_parse_cost.py

הפלט: שורת JSON לכל מדידה ב-stdout, שורת ``skipped`` ב-stderr לכל קובץ
שאינו UTF-8, ובסוף לכל פרסר המספר שראוי להיכנס לקבוע — המסמך הצפוף ביותר
שהכלי באמת מגיש — לצד הגבול העוין. אם אין בריפו אף קובץ בסיומת המבוקשת
בגודל ``MIN_DOC_BYTES`` ומעלה, הסקריפט יוצא עם הודעה שאומרת זאת.
"""

from __future__ import annotations

import json
import pathlib
import statistics
import subprocess
import sys
import tempfile
import textwrap

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from services.git_mirror_service import MAX_FILE_SIZE_FOR_DISPLAY  # noqa: E402

# חיתוך לתקרה בבתים על גבול תו — אותה פונקציה שהכלים עצמם משתמשים בה, ולא
# עותק מקומי (יש כבר שלושה בריפו; R6: מאחדים, לא מוסיפים רביעי).
from mcp_server.handlers import clip_to_bytes  # noqa: E402

#: מסמכים קטנים מזה אינם מייצגים — צפיפות של קובץ בן שורה אחת היא רעש.
MIN_DOC_BYTES = 2_000
_SKIP_PARTS = {"node_modules", ".git", "_build", "venv", ".venv"}

#: שני הפרסרים שהמאגר צריך לדעת את עלותם: השם ב-``services``, הסיומת שהכלי
#: מגיש דרכו, טקסט חימום קטן, והצורה העוינת של כל אחד.
PARSERS = {
    "md": {
        "module": "md_parser",
        "suffix": ".md",
        "warm": "# warm\n\ntext\n",
        "hostile_unit": "- item\n",
    },
    "rst": {
        "module": "rst_parser",
        "suffix": ".rst",
        "warm": "Warm\n====\n\ntext\n",
        "hostile_unit": "a\n=\n\n",
    },
}

_CHILD = textwrap.dedent(
    """
    import json, sys
    sys.path.insert(0, {repo!r})

    def status(key):
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith(key + ":"):
                    return int(line.split()[1])
        raise SystemExit("no " + key + " in /proc/self/status")

    from services import {module} as parser

    text = open({path!r}, encoding="utf-8").read()
    parser.parse_document({warm!r})
    rss_before, hwm_before = status("VmRSS"), status("VmHWM")
    # מה שהתהליך כבר הגיע אליו לפני הפרסור אינו של הפרסור — הבסיס הוא הגבוה
    # מבין ה-RSS הנוכחי ושיא-העבר, ולא ה-RSS לבדו.
    baseline = max(rss_before, hwm_before)
    outcome, sections = "parsed", None
    try:
        doc = parser.parse_document(text, **{kwargs!r})
        sections = len(doc.sections)
    except parser.TooManySections:
        outcome = "too_many_sections"
    hwm_after, rss_after = status("VmHWM"), status("VmRSS")
    n = len(text.encode("utf-8"))
    print(json.dumps({{
        "module": {module!r},
        "input_bytes": n,
        "outcome": outcome,
        "sections": sections,
        "headroom_kb_before_parse": hwm_before - rss_before,
        "peak_mib": round((hwm_after - baseline) / 1024, 1),
        "peak_bytes_per_input_byte": round((hwm_after - baseline) * 1024 / n, 1),
        "retained_bytes_per_input_byte": round((rss_after - rss_before) * 1024 / n, 1),
    }}))
    """
)


def peak_cost(
    path: pathlib.Path,
    workdir: pathlib.Path,
    *,
    parser: str = "md",
    kwargs: dict | None = None,
) -> dict:
    """פרסור אחד בתהליך נקי; מחזיר את שיא ה-RSS שהוא הוסיף מעל הבסיס, לכל בית קלט."""
    spec = PARSERS[parser]
    program = _CHILD.format(
        repo=str(REPO),
        path=str(path),
        module=spec["module"],
        warm=spec["warm"],
        kwargs=dict(kwargs or {}),
    )
    proc = subprocess.run(
        [sys.executable, "-B", "-c", program],
        capture_output=True,
        text=True,
        cwd=str(workdir),
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"the measuring child failed on {path.name}:\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def density(text: str, parser: str = "md") -> float:
    """צפיפות ל-KB: טוקני בלוק בתצורת ``md_parser``, סקשנים ב-``rst_parser``."""
    size = max(1, len(text.encode("utf-8")))
    if parser == "md":
        from services import md_parser

        return len(md_parser._build_parser().parse(text)) * 1024 / size
    from services import rst_parser

    return len(rst_parser.parse_document(text).sections) * 1024 / size


def tiled_to_ceiling(text: str, limit: int = MAX_FILE_SIZE_FOR_DISPLAY) -> str:
    """המסמך משוכפל עד התקרה — הקלט הגדול ביותר שפרסור יכול לקבל בה."""
    copies = limit // max(1, len(text.encode("utf-8"))) + 1
    return clip_to_bytes((text + "\n\n") * copies, limit)


def real_files(suffix: str) -> list[pathlib.Path]:
    """כל קובצי ``suffix`` בריפו שאינם vendored ואינם קטנים מ-``MIN_DOC_BYTES``."""
    return sorted(
        p
        for p in REPO.rglob("*" + suffix)
        if not (set(p.parts) & _SKIP_PARTS) and p.stat().st_size >= MIN_DOC_BYTES
    )


def rank(files: list[pathlib.Path], parser: str) -> list[tuple[float, pathlib.Path, str]]:
    """הקבצים לפי צפיפות, מהצפוף ביותר; קובץ שאינו UTF-8 מדולג בקול ב-stderr."""
    ranked = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            # הכלל ב-CLAUDE.md: except שמדלג אומר זאת — אחרת המסמך הצפוף
            # ביותר יכול לצאת מהדירוג בלי שאיש יידע.
            print(json.dumps({"skipped": str(p), "reason": f"not utf-8: {exc.reason}"}), file=sys.stderr)
            continue
        ranked.append((density(text, parser), p, text))
    if not ranked:
        suffix = PARSERS[parser]["suffix"]
        raise SystemExit(f"no {suffix} file of at least {MIN_DOC_BYTES} bytes under {REPO} — nothing to measure")
    ranked.sort(key=lambda r: r[0], reverse=True)
    return ranked


def constant_candidate(results: list[dict], parser: str) -> float:
    """המועמד לקבוע: הגבוה מבין מדידות ``densest_real`` של הפרסר — לא הראשון ולא הצפוף ביותר בדירוג."""
    return max(
        r["peak_bytes_per_input_byte"] for r in results if r["parser"] == parser and r["shape"] == "densest_real"
    )


def hostile_bound(results: list[dict], parser: str) -> float:
    """הגבול העוין של הפרסר — מה שהקבוע במפורש אינו מכסה."""
    return next(r["peak_bytes_per_input_byte"] for r in results if r["parser"] == parser and r["shape"] == "hostile")


def measure(parser: str, work: pathlib.Path) -> list[dict]:
    """שלוש הצורות של פרסר אחד, ול-RST גם מסלול ה-outline."""
    spec = PARSERS[parser]
    ranked = rank(real_files(spec["suffix"]), parser)
    print(json.dumps({
        "parser": parser,
        "files": len(ranked),
        "median_density_per_kb": round(statistics.median(r[0] for r in ranked), 1),
        "read_ceiling_bytes": MAX_FILE_SIZE_FOR_DISPLAY,
    }))
    results = []
    # הקורפוס האמיתי, חתוך לתקרה — העלות הטיפוסית.
    corpus = work / ("corpus" + spec["suffix"])
    corpus.write_text(
        clip_to_bytes("\n\n".join(r[2] for r in sorted(ranked, key=lambda r: str(r[1]))), MAX_FILE_SIZE_FOR_DISPLAY),
        encoding="utf-8",
    )
    results.append({"parser": parser, "shape": "corpus", **peak_cost(corpus, work, parser=parser)})
    # המסמך הצפוף ביותר, משוכפל עד התקרה — הגרוע ביותר שהכלי באמת מגיש.
    top_density, top_path, top_text = ranked[0]
    tiled = work / ("tiled_" + top_path.name)
    tiled.write_text(tiled_to_ceiling(top_text), encoding="utf-8")
    results.append({
        "parser": parser,
        "shape": "densest_real",
        "source": str(top_path.relative_to(REPO)),
        "density_per_kb": round(top_density, 1),
        **peak_cost(tiled, work, parser=parser),
    })
    # הצורה העוינת — הגבול העליון של הפרסר, שהקבוע במפורש אינו מכסה.
    unit = spec["hostile_unit"]
    hostile = work / ("hostile" + spec["suffix"])
    hostile.write_text(
        clip_to_bytes(unit * (MAX_FILE_SIZE_FOR_DISPLAY // len(unit) + 1), MAX_FILE_SIZE_FOR_DISPLAY),
        encoding="utf-8",
    )
    results.append({"parser": parser, "shape": "hostile", **peak_cost(hostile, work, parser=parser)})
    if parser == "rst":
        # מסלול ה-outline של codekeeper_get_repo_file: קריאה עד RANGE_READ_MAX_BYTES,
        # פרסור עם תקרת סקשנים — ההחזקה הגדולה ביותר של חוט קריאה היום.
        from mcp_server.outline_scanners._ceiling import MAX_SYMBOLS
        from mcp_server.repo_backend import RANGE_READ_MAX_BYTES

        outline = work / ("outline_" + top_path.name)
        outline.write_text(tiled_to_ceiling(top_text, RANGE_READ_MAX_BYTES), encoding="utf-8")
        results.append({
            "parser": parser,
            "shape": "outline_densest_real",
            "source": str(top_path.relative_to(REPO)),
            **peak_cost(outline, work, parser=parser, kwargs={"max_sections": MAX_SYMBOLS}),
        })
    return results


def main() -> int:
    import markdown_it

    print(json.dumps({"markdown_it": markdown_it.__version__, "python": sys.version.split()[0]}))
    results = []
    with tempfile.TemporaryDirectory(prefix="parse-cost-") as tmp:
        work = pathlib.Path(tmp)
        for parser in PARSERS:
            results.extend(measure(parser, work))
    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    print(json.dumps({
        parser: {
            "constant_candidate_bytes_per_input_byte": constant_candidate(results, parser),
            "hostile_bound_bytes_per_input_byte": hostile_bound(results, parser),
        }
        for parser in PARSERS
    } | {
        "note": (
            "the constant is the densest document the tool actually serves; "
            "the hostile bound is not a pool problem"
        ),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
