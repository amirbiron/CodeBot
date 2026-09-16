#!/usr/bin/env python3
"""תצלום דטרמיניסטי של כל מה ש-``codekeeper_docs_get_section`` מחזיר על קורפוס RST.

**למה סקריפט ולא טסט עם ערך מקובע.** הראיה שריפקטור לא שינה התנהגות היא
*אפס-דיף*: אותו פלט בדיוק לפני ואחרי. טסט שמקבע digest בקוד היה נשבר בכל
פעם שמישהו עורך עמוד תחת ``docs/`` — כלומר הוא היה מודד את התיעוד ולא את
הפארסר, והיה הופך לרעש שמישהו יעדכן בלי להסתכל. הסקריפט הזה מריץ את אותה
סוללה על שני עצי-קוד ומשווה ביניהם, ולכן הוא תקף גם כשהקורפוס משתנה.

**והקורפוס נמסר כארגומנט בכוונה.** שתי ההרצות חייבות לפרסר את אותם בייטים;
אם כל הרצה תקרא את ``docs/`` של העץ שלה, הבדל בתיעוד בין הענפים היה נראה
בדיוק כמו שינוי התנהגות. ``--corpus`` מצביע על עץ אחד לשתיהן.

**מה הסוללה מכסה** — כל ארבעת מסלולי התשובה של הכלי, ולא רק המסלול המרכזי:

============================  ==================================================
המסלול                        איך הוא נדלק
============================  ==================================================
``mode: toc``                 קריאה בלי ``section``
``mode: section``             כל כותרת בקובץ, עם תת-סקשנים ובלעדיהם
``error: ambiguous_section``  כותרת ששמה חוזר באותו קובץ — נדלק מעצמו
``error: section_not_found``  שאילתה שאינה קיימת, ועוד אחת שנגזרת מכותרת
                              אמיתית כדי ש-``difflib`` יחזיר הצעות בפועל
``truncated``                 ``max_chars`` מינימלי, ואז עמוד שני ב-``next_offset``
============================  ==================================================

**ורשימת השאילתות נרשמת בפלט, לא רק התשובות.** היא נגזרת מה-TOC של אותה
הרצה, ולכן שינוי ב-TOC משנה גם את מה שנשאל — ובלי לרשום אותה, שתי הרצות
שנשאלו שאלות שונות היו יכולות להיראות זהות. הרישום הוא מה שהופך את זה
לראיה ולא להשוואה של שני דברים שאינם אותו דבר.

שימוש::

    python scripts/docs_section_zero_diff.py --corpus docs --out before.jsonl
    # ... הריפקטור ...
    python scripts/docs_section_zero_diff.py --corpus docs --out after.jsonl
    diff before.jsonl after.jsonl && echo "אפס דיף"

הסקריפט אינו כותב לשום מקום מלבד ``--out``, ואינו מוחק דבר.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp_server import docs_handlers  # noqa: E402

# שאילתה שאין ולא יכולה להיות לה כותרת תואמת בקורפוס — כדי לקבע את מסלול
# ה-not-found גם בקובץ שכל כותרת בו נמצאת.
_ABSENT_QUERY = "זזזז לא קיימת זזזז"


class _CorpusBackend:
    """מחקה את החוזה של ``RepoBackend.get_file`` מול עץ קבצים נתון.

    השדות שמוחזרים הם בדיוק אלה ש-``docs_get_section`` קורא: ``ok``,
    ``status``, ``content`` ו-``file``. ``resolved_commit`` קבוע ולא נגזר
    מגיט — הוא נכנס לתשובה כמו שהוא, וערך שמשתנה בין ההרצות היה מייצר דיף
    שאינו התנהגות.
    """

    def __init__(self, corpus_root: Path) -> None:
        self._root = corpus_root

    def get_file(self, *, repo: str, path: str, ref: str | None = None,
                 lines: Any = None) -> dict[str, Any]:
        # ``path`` מגיע מנורמל כ-``docs/<name>.rst``; הקורפוס הוא אותה תיקייה.
        rel = path[len("docs/"):] if path.startswith("docs/") else path
        f = self._root / rel
        if not f.is_file():
            return {"ok": False, "error": "not_found"}
        text = f.read_text(encoding="utf-8")
        return {
            "ok": True,
            "status": "ok",
            "file": {"path": path, "ref": ref or "refs/heads/main",
                     "resolved_commit": "fixed-for-snapshot"},
            "content": text,
        }


def _call(backend: Any, **kwargs: Any) -> dict[str, Any]:
    """קריאה אחת לכלי, עם השאילתה עצמה שמורה לצד התשובה."""
    out = docs_handlers.docs_get_section(backend, **kwargs)
    return {"query": dict(sorted(kwargs.items())), "response": out}


def _normalization_variants(title: str) -> list[str]:
    """צורות של אותה כותרת שרק ``normalize_title`` אמור להשוות אליה.

    **בלי אלה הסוללה עיוורת ל-``normalize_title`` לגמרי, וזה נמדד ולא הונח.**
    הגרסה הראשונה שאלה כל כותרת בדיוק כפי שה-TOC החזיר אותה — ואז שני הצדדים
    של ההשוואה עוברים את אותו נרמול, כך ש**ביטול ה-``casefold`` לא שינה את
    ה-digest בכלל**. כלומר מוטציה אמיתית בפונקציה עברה את ההוכחה בשקט, וזה
    הופך אותה מראיה להרגשה.

    שלוש הצורות מכסות את שלושת הכללים שהפונקציה מיישמת, כל אחת את שלה:
    ``swapcase`` את ה-``casefold``, הרווחים את כיווץ הרווחים ואת ה-``strip``,
    והמקף הארוך את איחוד המקפים.
    """
    variants = [
        title.swapcase(),
        f"  {re.sub(r'[ ]+', '   ', title)}  ",
        title.replace("-", "—"),
    ]
    # צורה שיוצאת זהה למקור אינה בודקת כלום, ורק מנפחת את התצלום.
    return [v for v in dict.fromkeys(variants) if v != title]


def _battery(backend: Any, doc_path: str) -> Iterator[dict[str, Any]]:
    """כל הקריאות לקובץ אחד, בסדר קבוע."""
    toc_rec = _call(backend, path=doc_path)
    yield toc_rec

    toc = toc_rec["response"].get("toc") or []
    titles = [item["title"] for item in toc]

    for title in titles:
        yield _call(backend, path=doc_path, section=title, include_subsections=True)
        yield _call(backend, path=doc_path, section=title, include_subsections=False)
        for variant in _normalization_variants(title):
            yield _call(backend, path=doc_path, section=variant)

    # not-found: אחת שלא קיימת בכלל, ואחת שנגזרת מכותרת אמיתית כדי
    # ש-``suggest`` יחזיר משהו ולא רשימה ריקה.
    yield _call(backend, path=doc_path, section=_ABSENT_QUERY)
    if titles and len(titles[0]) > 3:
        yield _call(backend, path=doc_path, section=titles[0][:-2])

    # truncation: העמוד הראשון בתקרה המינימלית, ואז העמוד שאחריו.
    if titles:
        first = _call(backend, path=doc_path, section=titles[0],
                      max_chars=docs_handlers.MAX_CHARS_MIN)
        yield first
        nxt = first["response"].get("next_offset")
        if nxt:
            yield _call(backend, path=doc_path, section=titles[0],
                        max_chars=docs_handlers.MAX_CHARS_MIN, offset=nxt)


def _edge_inputs(backend: Any) -> Iterator[dict[str, Any]]:
    """מסלולי הדחייה שאינם תלויים בקובץ — פעם אחת לכל ההרצה."""
    yield _call(backend, path="")
    yield _call(backend, path="../etc/passwd")
    yield _call(backend, path="webapp/app")
    yield _call(backend, path="environment-variables", repo="not-in-allowlist")
    yield _call(backend, path="does-not-exist-at-all")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default=str(_ROOT / "docs"),
                    help="תיקיית קובצי ה-RST. אותה תיקייה לשתי ההרצות.")
    ap.add_argument("--out", required=True, help="קובץ הפלט (JSONL).")
    args = ap.parse_args()

    corpus = Path(args.corpus).resolve()
    if not corpus.is_dir():
        print(f"אין תיקיית קורפוס: {corpus}", file=sys.stderr)
        return 2

    backend = _CorpusBackend(corpus)
    files = sorted(p.relative_to(corpus).as_posix()
                   for p in corpus.rglob("*.rst"))
    if not files:
        print(f"אין קובצי .rst תחת {corpus}", file=sys.stderr)
        return 2

    digest = hashlib.sha256()
    tally: Counter[str] = Counter()
    records = 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in _edge_inputs(backend):
            line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
            fh.write(line + "\n")
            digest.update(line.encode("utf-8"))
            records += 1
            tally[str(rec["response"].get("error") or rec["response"].get("mode"))] += 1

        for rel in files:
            # הנתיב המלא ולא ה-slug הקצר: ``_resolve_docs_path`` מוסיף את
            # התחילית ``docs/`` רק כשאין ב-קלט ``/`` בכלל, ולכן קובץ בתת-תיקייה
            # (``observability/error_codes``) היה נדחה כ-``missing_path``.
            for rec in _battery(backend, f"docs/{rel}"):
                line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
                fh.write(line + "\n")
                digest.update(line.encode("utf-8"))
                records += 1
                resp = rec["response"]
                tally[str(resp.get("error") or resp.get("mode"))] += 1

    print(f"קבצים:   {len(files)}")
    print(f"רשומות:  {records}")
    print(f"sha256:  {digest.hexdigest()}")
    print("פילוח מסלולי התשובה:")
    for key, count in sorted(tally.items()):
        print(f"  {key}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
