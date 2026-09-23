#!/usr/bin/env python3
"""כמה עולה ``codekeeper_read_batch`` — בתים, זמן קיר וזיכרון — מעל מראה אמיתית.

``docs/mcp-server.rst`` (הסעיף על ``codekeeper_read_batch``) מצטט את המספרים
שהסקריפט הזה מדפיס, ושלוש החלטות של הכלי נשענות עליהם:

- **כמה מהתקציב ומהדדליין סבב ריוויו אמיתי תופס.** זה הנימוק לכך שפריטים
  שלא נקראו אינם מחזירים את יחידות הקצב שלהם: המקרה נדיר מכדי להצדיק מנגנון
  שני. הסבב הוא :data:`REVIEW_ROUND` — הקריאות של סבב הריוויו שהוליד את הכלי.
- **שבאץ' מחזיק מסמך אחד בכל רגע.** הפריטים מקובצים לפי הקובץ שהם קוראים,
  וכל קבוצה משתחררת לפני שהבאה נקראת. לכן השיא של באץ' מלא שמדלג בין הקבצים
  הגדולים בריפו צריך להיות השיא של קריאה בודדת של הגדול שבהם — ולא סכום.
- **שבאץ' שחוצה את התקציב נעצר, והזיכרון אינו גדל איתו.** מה שנכנס, ועוד כל
  תשובה שמחכה לתורה, אינם עוברים יחד את התקציב (``read_batch._keep``).

מה נמדד, ולמה דווקא כך:

- **בתים** — ``read_batch._wire``: בדיוק מה שה-SDK שולח, ובדיוק מה שהכלי
  עצמו מודד מול ``OUTPUT_BYTE_BUDGET``. לא נוסחה מקבילה. **מה שכן שונה
  מהפרודקשן הוא ``ref``:** כל פריט שנקרא נושא את שם הענף, ובלי מונגו
  ``RepoBackend._default_ref`` מחזיר ``HEAD`` במקום ``refs/heads/<ענף>``
  מ-``repo_metadata`` — 11 בתים פחות בכל פריט כשהענף הוא ``main``. עם
  ``refs/heads/main`` הסבב יוצא בית-בית כמו בפרודקשן (נבדק ב-2026-09-23).
- **זמן קיר** — ``time.perf_counter`` סביב הפונקציה עצמה
  (``read_batch.read_batch`` או ``docs_get_section``), בתהליך שאינו מריץ
  ``tracemalloc`` (שמאט כל הקצאה). זה קטע קצר יותר מ-``$mcp_duration_ms``
  שהפרודקשן רושם ב-PostHog, שעוטף את ``ToolManager.call_tool`` כולו — ולכן
  שני המספרים אינם אותה מדידה (``docs/mcp-server.rst``, בסעיף על
  ``codekeeper_read_batch``).
- **זיכרון** — שיא ההקצאות של פייתון (``tracemalloc``), בתהליך נקי משלו לכל
  מדידה, כדי ששיא של מדידה אחת לא יסתיר שיא של אחרת. זו אינה היחידה שמאגר
  הקריאות מתומחר בה — שם זה שיא RSS לכל בית קלט (``scripts/measure_md_parse_cost.py``)
  — **ובכוונה**: השאלה כאן אינה כמה עולה פרסור, את זה המאגר כבר יודע, אלא
  האם באץ' עולה יותר מהקריאה היקרה שבו. זו השוואה בתוך יחידה אחת.
- **לפני כל מדידה, אותו חימום בכל תהליך:** תוכן העניינים של הקובץ הגדול
  ביותר, דרך הכלי. ההשוואה בין הקריאה הבודדת לבאץ' היא בין שני תהליכים
  באותו מצב.
- דרך ``read_batch.read_batch`` ו-``docs_handlers.docs_get_section`` עצמם,
  מעל ``RepoBackend`` אמיתי ובלי מונגו, כך ש-``HEAD`` של המראה הוא הענף
  הראשי. השכבה של ``call_tool`` (הזהות והקצב) אינה כאן, כי אף אחד מהמספרים
  אינו תלוי בה.

**הכלי הוא שקובע מה הוא מגיש, ולא עותק של הכלל.** "הקבצים הגדולים" הם
הגדולים שהכלי **עונה** עליהם: הסקריפט עובר על קובצי המראה מהגדול לקטן ושואל
את ``docs_get_section`` על כל אחד. סיומת שהריפו אינו מגיש, נתיב חסום, או קובץ
מעל התקרה — נדחים שם ומדווחים ב-stderr, בלי עותק שלישי של מדיניות הנתיבים.

**והפריטים נבחרים פעם אחת.** תהליך ראשון בוחר את הקבצים והכותרות, וכל
המדידות מקבלות את אותה בחירה — כך ששתיים מהן אינן יכולות למדוד שני דברים
שונים. מה שכן יכול לזוז הוא המראה עצמו, אם autosync מושך באמצע ההרצה; לכן
כל שורה נושאת את ה-commit שנקרא, והסקריפט נכשל כשיש יותר מאחד.

הרצה מהשורש של הריפו, מול התיקייה שמחזיקה את ``<repo>.git``::

    python scripts/measure_read_batch.py --mirror-root "$REPO_MIRROR_PATH"

הפלט: שורת JSON לבחירה, שורה לכל מדידה, ובסוף שורה אחת עם היחסים שהתיעוד
מצטט. **פריט שנענה בסירוב — קובץ ששמו השתנה, סעיף שנמחק — מדווח בשמו,
והסקריפט יוצא בקוד 1:** מדידה של תשובת ``not_found`` אינה מדידה של הסבב,
ומספר שנראה סביר היה נכנס לתיעוד בלי שאיש יידע.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp_server import docs_handlers, read_batch  # noqa: E402
from mcp_server.repo_handlers import OUTPUT_BYTE_BUDGET  # noqa: E402

#: הריפו שהסבב קרא ממנו — ברירת המחדל של ``--repo``.
DEFAULT_REPO = "amir-bug-patterns"

#: סבב הריוויו שהוליד את הכלי, כפי ש-PostHog רשם אותו: סשן ``ses_01a0cd48``,
#: ‏2026-09-23 בין 11:41:33 ל-11:43:49 UTC. כל ``codekeeper_docs_get_section``
#: עם ``section`` הוא פריט סעיף, וכל ``codekeeper_get_repo_file`` הוא פריט
#: קובץ. הקריאה שאינה כאן היא תוכן העניינים של ``TESTING-PATTERNS``: היא
#: שאלה איפה הסעיפים, ולא קראה אחד מהם.
REVIEW_ROUND: tuple[dict[str, Any], ...] = (
    {"kind": "section", "path": "CRITICAL-PATTERNS", "section": "K11"},
    {"kind": "section", "path": "RECURRING-PATTERNS", "section": "R6"},
    {"kind": "section", "path": "CORE-PATTERNS", "section": "U3"},
    {"kind": "section", "path": "CRITICAL-PATTERNS", "section": "K13"},
    {"kind": "section", "path": "TESTING-PATTERNS", "section": "T1"},
    {"kind": "section", "path": "TESTING-PATTERNS", "section": "T3"},
    {"kind": "file", "path": "bugbot-rules/logical-entity-vs-version-document.md"},
    {"kind": "file", "path": "bugbot-rules/return-value-failure-unchecked.md"},
    {"kind": "file", "path": "bugbot-rules/widened-exception-scope.md"},
    {"kind": "file", "path": "bugbot-rules/prose-restates-code-fact.md"},
    {"kind": "file", "path": "bugbot-rules/line-number-coupling.md"},
    {"kind": "file", "path": "bugbot-rules/external-input-isinstance.md"},
    {"kind": "file", "path": "bugbot-rules/secret-in-derived-text.md"},
    {"kind": "file", "path": "BY-STACK/browser-policy.md"},
    {"kind": "file", "path": "claude-md-snippets/testing.md"},
)

#: בין כמה קבצים גדולים הבאץ' המלא מדלג. חמישה, כדי שבבאץ' של
#: ``MAX_BATCH_ITEMS`` יהיו כמה סעיפים מכל קובץ — כלומר קבוצות אמיתיות, שכל
#: אחת עונה על פריטים שמחכים לתורם בזמן שהקבוצות האחרות נקראות.
LARGEST_FILES = 5

#: המדידות, בסדר שבו הן רצות ומודפסות.
#:
#: - ``round`` — :data:`REVIEW_ROUND` בבאץ' אחד.
#: - ``single_largest`` — קריאה בודדת של ``docs_get_section``, סעיף מהקובץ
#:   הגדול ביותר שהכלי מגיש: קו הבסיס של הזיכרון.
#: - ``interleaved_largest`` — באץ' מלא של סעיפים מ-:data:`LARGEST_FILES`
#:   הקבצים הגדולים, בסבב: קובץ אחר בכל פריט.
#: - ``files_largest`` — באץ' של פריטי קובץ, מהגדולים ביותר: התקציב נגמר לפני
#:   הרשימה, והזיכרון צריך להישאר בגובה של קובץ אחד.
CASES = ("round", "single_largest", "interleaved_largest", "files_largest")


def _backend(mirror_root: Path) -> Any:
    """``RepoBackend`` אמיתי מעל ``<mirror_root>/<repo>.git``, בלי מונגו.

    בלי ``db`` הענף הראשי הוא ``HEAD`` של המראה ואין בדיקת סנכרון — אותה
    בנייה כמו ``_mirror_backend`` ב-``scripts/docs_section_zero_diff.py``.
    """
    from mcp_server.repo_backend import RepoBackend
    from services.git_mirror_service import GitMirrorService

    return RepoBackend(db=None, mirror=GitMirrorService(base_path=str(mirror_root)))


def largest_served(backend: Any, repo: str, count: int) -> list[dict[str, Any]]:
    """עד ``count`` הקבצים הגדולים שהכלי עונה עליהם, עם הכותרות שאפשר לבקש בהם.

    כל רשומה: ``{"path", "size", "sections"}``, כש-``sections`` הן כותרות
    מתחת לכותרת העליונה שמופיעות **פעם אחת** בקובץ — כותרת כפולה הייתה עונה
    ``ambiguous_section``, ומודדת את הסירוב במקום את הסעיף. קובץ שהכלי מסרב
    לו, או שאין בו כותרת כזו, מדווח ב-stderr ומדולג.
    """
    files = backend._require_mirror().list_all_files_with_sizes(repo, "HEAD")
    if not files:
        # ``None`` הוא כשל של git, ורשימה ריקה היא מראה ריקה; בשני המקרים אין מה למדוד.
        raise SystemExit(f"no files listed in the mirror of {repo!r} (git failed, or the mirror is empty)")
    chosen: list[dict[str, Any]] = []
    for entry in sorted(files, key=lambda e: (-(e["size"] or 0), e["path"])):
        if len(chosen) == count:
            break
        toc = docs_handlers.docs_get_section(backend, path=entry["path"], repo=repo)
        if toc.get("ok") is not True:
            print(json.dumps({"skipped": entry["path"], "reason": toc.get("error")}), file=sys.stderr)
            continue
        titles = [item["title"] for item in toc.get("toc", []) if item.get("level", 0) >= 2]
        unique = [title for title in titles if titles.count(title) == 1]
        if not unique:
            print(json.dumps({"skipped": entry["path"], "reason": "no unique heading below the top one"}),
                  file=sys.stderr)
            continue
        chosen.append({"path": entry["path"], "size": entry["size"], "sections": unique})
    if not chosen:
        raise SystemExit(f"the docs tool serves no file with a unique heading in {repo!r}")
    return chosen


def items_for(case: str, repo: str, largest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """הפריטים של מדידת באץ' — עם ``repo`` מפורש בכל פריט."""
    if case == "round":
        return [dict(item, repo=repo) for item in REVIEW_ROUND]
    if case == "interleaved_largest":
        items: list[dict[str, Any]] = []
        depth = 0
        while len(items) < read_batch.MAX_BATCH_ITEMS:
            layer = [doc for doc in largest if depth < len(doc["sections"])]
            if not layer:
                break
            for doc in layer[: read_batch.MAX_BATCH_ITEMS - len(items)]:
                items.append({"kind": "section", "repo": repo, "path": doc["path"],
                              "section": doc["sections"][depth]})
            depth += 1
        return items
    if case == "files_largest":
        return [{"kind": "file", "repo": repo, "path": doc["path"]}
                for doc in largest[: read_batch.MAX_BATCH_ITEMS]]
    raise ValueError(f"not a batch case: {case!r}")


def _failures(answer: dict[str, Any]) -> list[dict[str, Any]]:
    """הפריטים שנענו בסירוב — ``index``, מה נשלח, והקוד. בלי תוכן."""
    return [
        {"index": entry["index"], "request": entry.get("request"), "error": entry["result"].get("error")}
        for entry in answer.get("items", [])
        if entry["result"].get("ok") is not True
    ]


def measure(case: str, mirror_root: Path, repo: str, largest: list[dict[str, Any]],
            *, peak: bool) -> dict[str, Any]:
    """מדידה אחת, בתהליך הנוכחי. ``peak`` — שיא ``tracemalloc`` בלבד; בלעדיו — כל השאר."""
    backend = _backend(mirror_root)
    # החימום: אותה קריאה בכל תהליך, לפני כל מדידה — ראו את ה-docstring של המודול.
    docs_handlers.docs_get_section(backend, path=largest[0]["path"], repo=repo)

    if case == "single_largest":
        target = largest[0]

        def run() -> dict[str, Any]:
            return docs_handlers.docs_get_section(
                backend, path=target["path"], repo=repo, section=target["sections"][0])
    else:
        items = items_for(case, repo, largest)

        def run() -> dict[str, Any]:
            return read_batch.read_batch(backend, items, item_cap=read_batch.MAX_BATCH_ITEMS)

    if peak:
        tracemalloc.start()
        try:
            run()
            _, top = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        return {"case": case, "peak_mib": round(top / 2**20, 2)}

    started = time.perf_counter()
    answer = run()
    wall = time.perf_counter() - started
    sent = len(read_batch._wire(answer))
    result: dict[str, Any] = {
        "case": case,
        "wall_ms": round(wall * 1000, 1),
        "share_of_deadline": round(wall / read_batch.DEADLINE_SECONDS, 4),
        "wire_bytes": sent,
        "share_of_budget": round(sent / OUTPUT_BYTE_BUDGET, 4),
    }
    if case == "single_largest":
        commit = answer.get("resolved_commit")
        result.update(path=target["path"], file_bytes=target["size"],
                      commits=[commit] if isinstance(commit, str) else [],
                      failed=[] if answer.get("ok") is True else [{"error": answer.get("error")}])
        return result
    result.update(
        requested=len(items),
        count=answer["count"],
        unread=answer.get("unread"),
        unread_reason=answer.get("unread_reason"),
        commits=sorted({entry["resolved_commit"] for entry in answer["items"] if "resolved_commit" in entry}),
        failed=_failures(answer),
    )
    return result


def _spawn(arguments: list[str], mirror_root: Path, repo: str, workdir: str) -> dict[str, Any]:
    """תהליך נקי (``python -B``) של הסקריפט הזה; מחזיר את שורת ה-JSON האחרונה שלו.

    **מה שהילד כותב ל-stderr עובר הלאה, ולא נבלע:** קבצים שהבחירה דילגה
    עליהם, ואזהרות מהכלי עצמו — למשל קיבוע commit שנכשל, שאומר שהמדידה
    נקראה לפי שם הענף. ``MCP_DOCS_REPO`` מקובע לריפו הנמדד **בסביבה של הילד
    בלבד**: פריטי הסעיף עוברים את אותה רשימת היתר של הכלי, ובלעדיה ריפו שאינו
    ברירת המחדל היה נדחה ב-``repo_not_allowed``; ההורה אינו נוגע בסביבה של
    עצמו, כי טסטים קוראים ל-:func:`main` מתוך התהליך שלהם.
    """
    command = [sys.executable, "-B", str(Path(__file__).resolve()), *arguments,
               "--mirror-root", str(mirror_root), "--repo", repo]
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=workdir,
        env=dict(os.environ, MCP_DOCS_REPO=repo, PYTHONDONTWRITEBYTECODE="1"),
        timeout=600,
        check=False,
    )
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"the measuring child failed: {' '.join(arguments)}")
    # הפלט עבר גבול של תהליך (U3): הילד הוא הסקריפט הזה, אבל ספרייה שכותבת
    # ל-stdout הייתה דוחקת את שורת ה-JSON, והמדידה הייתה נופלת ב-KeyError רחוק
    # מכאן. הסירוב נוקב במה שהילד הדפיס בפועל.
    lines = proc.stdout.strip().splitlines()
    try:
        line = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError:
        line = None
    if not isinstance(line, dict):
        raise SystemExit(f"the measuring child printed no JSON object ({' '.join(arguments)}): "
                         f"{proc.stdout[-500:]!r}")
    return line


def main(argv: list[str] | None = None) -> int:
    """נקודת הכניסה. ``argv`` כרשימה ולא ``sys.argv``, כדי שטסט יוכל להריץ אותה.

    זו המוסכמה של ``scripts/docs_section_zero_diff.py``: שער שאי אפשר להריץ
    מטסט הוא שער שאיש לא בודק.
    """
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mirror-root", required=True,
                    help="התיקייה שמחזיקה את <repo>.git — מה ש-REPO_MIRROR_PATH מצביע עליו.")
    ap.add_argument("--repo", default=DEFAULT_REPO,
                    help=f"הריפו הנמדד (ברירת מחדל: {DEFAULT_REPO}, שממנו הסבב קרא).")
    ap.add_argument("--case", action="append", choices=CASES,
                    help="מדידה אחת בלבד; אפשר לחזור עליו. בלעדיו — כולן.")
    # שני המצבים של הילד. הבחירה מודפסת ל-stdout; מדידה מקבלת אותה כקובץ.
    ap.add_argument("--child-select", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--child", choices=CASES, help=argparse.SUPPRESS)
    ap.add_argument("--plan", help=argparse.SUPPRESS)
    ap.add_argument("--peak", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    mirror_root = Path(args.mirror_root).resolve()
    if not (mirror_root / f"{args.repo}.git").is_dir():
        print(f"no mirror of {args.repo!r} under {mirror_root} (expected {args.repo}.git)", file=sys.stderr)
        return 2

    if args.child_select:
        largest = largest_served(_backend(mirror_root), args.repo, LARGEST_FILES)
        print(json.dumps({"largest": largest}, ensure_ascii=False))
        return 0
    if args.child:
        largest = json.loads(Path(args.plan).read_text(encoding="utf-8"))["largest"]
        line = measure(args.child, mirror_root, args.repo, largest, peak=args.peak)
        print(json.dumps(line, ensure_ascii=False))
        return 0

    cases = [case for case in CASES if not args.case or case in args.case]
    results: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as workdir:
        plan = _spawn(["--child-select"], mirror_root, args.repo, workdir)
        print(json.dumps({"largest": [{"path": doc["path"], "size": doc["size"]} for doc in plan["largest"]]},
                         ensure_ascii=False))
        plan_path = Path(workdir) / "plan.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        for case in cases:
            child = ["--child", case, "--plan", str(plan_path)]
            line = _spawn(child, mirror_root, args.repo, workdir)
            line.update(_spawn([*child, "--peak"], mirror_root, args.repo, workdir))
            results[case] = line
            print(json.dumps(line, ensure_ascii=False))

    summary: dict[str, Any] = {
        "summary": True,
        "repo": args.repo,
        "budget_bytes": OUTPUT_BYTE_BUDGET,
        "deadline_seconds": read_batch.DEADLINE_SECONDS,
    }
    if "round" in results:
        summary["round_share_of_budget"] = results["round"]["share_of_budget"]
        summary["round_share_of_deadline"] = results["round"]["share_of_deadline"]
    if "single_largest" in results and "interleaved_largest" in results:
        single = results["single_largest"]["peak_mib"]
        summary["interleaved_peak_over_single"] = (
            round(results["interleaved_largest"]["peak_mib"] / single, 3) if single else None
        )
    commits = sorted({commit for line in results.values() for commit in line["commits"]})
    summary["commits"] = commits
    # ``files_largest`` נעצר בתקציב בכוונה, ומה שב-``unread`` אינו כשל. אבל
    # פריט שנענה בסירוב אינו מדידה של קובץ, ומראה שזזה באמצע ההרצה פירושה
    # שהמדידות תיארו שני מצבים — שני המקרים מפילים את קוד היציאה, בשמם.
    failed = {case: line["failed"] for case, line in results.items() if line["failed"]}
    if failed:
        summary["failed"] = failed
    if len(commits) > 1:
        summary["mirror_moved"] = True
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if failed or len(commits) > 1 else 0


if __name__ == "__main__":
    raise SystemExit(main())
