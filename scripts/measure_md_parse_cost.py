#!/usr/bin/env python3
"""כמה זיכרון עולה פרסור Markdown אחד — המספר שמאגר הקריאות של ה-MCP נגזר ממנו.

``mcp_server/server.py`` מגדיר את ``_PARSE_RSS_PER_INPUT_BYTE`` — שיא ה-RSS
שפרסור אחד מוסיף לכל בית קלט — ומחלק בו את תקציב הזיכרון של הקונטיינר כדי
לקבוע כמה קריאות רצות במקביל (#3391). הסקריפט הזה הוא הדרך למדוד את המספר
מחדש, למשל כשמחליפים גרסת ``markdown-it-py``, במקום להעתיק אותו מזיכרון.

מה נמדד, ולמה דווקא כך:

- **שיא** ה-RSS בזמן הפרסור (``VmHWM`` ב-``/proc/self/status``), ולא מה
  שנשאר אחריו — ``parse_document`` משחרר את רשימת הטוקנים ומחזיר ``Document``
  קטן בהרבה, אבל כמה פרסורים במקביל מחזיקים כל אחד את השיא שלו בו-זמנית.
- דרך ``services.md_parser`` עצמו, כלומר בדיוק בתצורה שהכלי הציבורי מריץ.
- כל פרסור בתהליך נקי משלו (``python -B``, בתיקייה זמנית), כדי שהמדידה לא
  תכלול זיכרון של פרסור קודם.
- על שלוש צורות: הקורפוס האמיתי של הריפו (כל קובצי ה-``.md``), המסמכים
  הצפופים ביותר בו כשהם משוכפלים עד תקרת הקריאה ``MAX_FILE_SIZE_FOR_DISPLAY``,
  וצורה עוינת — קובץ של שורות-תבליט בודדות — שהיא הגבול העליון של הפרסר.
  העלות נגזרת מ**צפיפות הטוקנים** של המסמך (טוקני בלוק ל-KB) ולא מגודלו,
  ולכן שלוש הצורות נותנות שלושה מספרים שונים מאוד.

הרצה מהשורש של הריפו::

    python scripts/measure_md_parse_cost.py

הפלט: שורת JSON לכל מדידה, ובסוף המספר שראוי להיכנס לקבוע — המסמך הצפוף
ביותר שהכלי באמת מגיש — לצד הגבול העוין שהקבוע במפורש אינו מכסה.
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

#: כמה מהמסמכים הצפופים ביותר לשכפל עד התקרה ולמדוד.
DENSEST_TO_MEASURE = 3
#: מסמכים קטנים מזה אינם מייצגים — צפיפות של קובץ בן שורה אחת היא רעש.
MIN_DOC_BYTES = 2_000
_SKIP_PARTS = {"node_modules", ".git", "_build", "venv", ".venv"}

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

    import markdown_it
    from services import md_parser

    text = open({path!r}, encoding="utf-8").read()
    md_parser.parse_document("# warm\\n\\ntext\\n")
    rss_before = status("VmRSS")
    doc = md_parser.parse_document(text)
    hwm_after, rss_after = status("VmHWM"), status("VmRSS")
    n = len(text.encode("utf-8"))
    print(json.dumps({{
        "markdown_it": markdown_it.__version__,
        "input_bytes": n,
        "sections": len(doc.sections),
        "peak_mb": round((hwm_after - rss_before) / 1024, 1),
        "peak_bytes_per_input_byte": round((hwm_after - rss_before) * 1024 / n, 1),
        "retained_bytes_per_input_byte": round((rss_after - rss_before) * 1024 / n, 1),
    }}))
    """
)


def peak_cost(path: pathlib.Path, workdir: pathlib.Path) -> dict:
    """פרסור אחד בתהליך נקי; מחזיר את שיא ה-RSS שהוא הוסיף, לכל בית קלט."""
    proc = subprocess.run(
        [sys.executable, "-B", "-c", _CHILD.format(repo=str(REPO), path=str(path))],
        capture_output=True,
        text=True,
        cwd=str(workdir),
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"the measuring child failed on {path.name}:\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def token_density(text: str) -> float:
    """טוקני בלוק ל-KB, באותה תצורת פרסר שהכלי מריץ (``md_parser``)."""
    from services import md_parser

    md = md_parser._build_parser()
    return len(md.parse(text)) * 1024 / max(1, len(text.encode("utf-8")))


def tiled_to_ceiling(text: str) -> str:
    """המסמך משוכפל עד תקרת הקריאה — הקלט הגדול ביותר שפרסור יכול לקבל."""
    copies = MAX_FILE_SIZE_FOR_DISPLAY // max(1, len(text.encode("utf-8"))) + 1
    return ((text + "\n\n") * copies).encode("utf-8")[:MAX_FILE_SIZE_FOR_DISPLAY].decode("utf-8", errors="ignore")


def real_markdown_files() -> list[pathlib.Path]:
    return sorted(
        p
        for p in REPO.rglob("*.md")
        if not (set(p.parts) & _SKIP_PARTS) and p.stat().st_size >= MIN_DOC_BYTES
    )


def main() -> int:
    files = real_markdown_files()
    ranked = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        ranked.append((token_density(text), p, text))
    ranked.sort(key=lambda r: r[0], reverse=True)
    print(json.dumps({
        "markdown_files": len(ranked),
        "median_tokens_per_kb": round(statistics.median(r[0] for r in ranked), 1),
        "read_ceiling_bytes": MAX_FILE_SIZE_FOR_DISPLAY,
    }))

    results = []
    with tempfile.TemporaryDirectory(prefix="md-parse-cost-") as tmp:
        work = pathlib.Path(tmp)
        # הקורפוס האמיתי, חתוך לתקרה — העלות הטיפוסית.
        corpus = work / "corpus.md"
        corpus.write_text(
            "\n\n".join(r[2] for r in sorted(ranked, key=lambda r: str(r[1]))).encode("utf-8")[
                :MAX_FILE_SIZE_FOR_DISPLAY
            ].decode("utf-8", errors="ignore"),
            encoding="utf-8",
        )
        results.append({"shape": "corpus", **peak_cost(corpus, work)})
        # המסמכים הצפופים ביותר, כל אחד משוכפל עד התקרה — מה שהכלי באמת מגיש, בגרוע ביותר.
        for density, path, text in ranked[:DENSEST_TO_MEASURE]:
            tiled = work / ("tiled_" + path.name)
            tiled.write_text(tiled_to_ceiling(text), encoding="utf-8")
            results.append({
                "shape": "densest_real",
                "source": str(path.relative_to(REPO)),
                "tokens_per_kb": round(density, 1),
                **peak_cost(tiled, work),
            })
        # הצורה העוינת — הגבול העליון של הפרסר, שהקבוע במפורש אינו מכסה.
        line = "- item\n"
        hostile = work / "hostile.md"
        hostile.write_text(
            (line * (MAX_FILE_SIZE_FOR_DISPLAY // len(line)))[:MAX_FILE_SIZE_FOR_DISPLAY], encoding="utf-8"
        )
        results.append({"shape": "hostile_one_line_bullets", **peak_cost(hostile, work)})

    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    densest = max(r["peak_bytes_per_input_byte"] for r in results if r["shape"] == "densest_real")
    hostile_cost = next(
        r["peak_bytes_per_input_byte"] for r in results if r["shape"] == "hostile_one_line_bullets"
    )
    print(json.dumps({
        "constant_candidate_bytes_per_input_byte": densest,
        "hostile_bound_bytes_per_input_byte": hostile_cost,
        "note": (
            "the constant is the densest document the tool actually serves; "
            "the hostile bound is not a pool problem"
        ),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
