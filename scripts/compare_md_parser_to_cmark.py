#!/usr/bin/env python3
"""משווה את ``services/md_parser`` מול cmark-gfm על **כל** קובצי ה-``.md``
בריפו שמעבירים לו.

**למה הוא קיים, ולמה זה לא טסט.** ``tests/test_md_parser_oracle.py`` רץ
ב-CI על **צורות מחוללות** ולא על קבצים אמיתיים, וזו החלטה: קורפוס
אמיתי הוא בדיקת שפיות חד-פעמית ולא רשת שתופסת רגרסיה עתידית, והוא היה
דורש להחזיק בריפו הזה עותק של תוכן שאינו שלו — עותק שמתיישן ברגע
שהמקור זז. הסקריפט הוא מה שמחליף אותו: אותה השוואה בדיוק, על הקורפוס
החי, **על פי דרישה**.

**שלוש הנקודות בזמן שבהן כדאי להריץ אותו:** לפני שלב 2 (האאוטליין
ל-``.md``), אחרי שדרוג של ``markdown-it-py``, וכשנוגעים ב-
``services/md_parser.py``.

**ואותה השוואה פירושה אותו קוד.** האורקל אינו נכתב כאן מחדש אלא נטען
מקובץ הטסטים, כי שני עותקים של "מה נחשב הסכמה" היו נסחפים זה מזה —
והראשון שהיה נשבר הוא זה שרץ לעיתים רחוקות, כלומר הסקריפט.

שימוש::

    python scripts/compare_md_parser_to_cmark.py /path/to/amir-bug-patterns
    python scripts/compare_md_parser_to_cmark.py /path/to/repo --out /tmp/report.txt

דורש ``cmarkgfm``, שנעוץ ב-``requirements/development.txt``.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _load_oracle():
    """טוען את האורקל מקובץ הטסטים — הגדרה אחת לשני המריצים."""
    sys.path.insert(0, str(_REPO))
    spec = importlib.util.spec_from_file_location(
        "md_parser_oracle", _REPO / "tests" / "test_md_parser_oracle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    # הנתיב הוא ארגומנט **חובה** ובלי ברירת מחדל: ברירת מחדל ל-``.``
    # הייתה גורמת לסקריפט לסרוק את הריפו שהוא עצמו יושב בו, ולדווח
    # "אפס פערים" על קורפוס שאינו הקורפוס.
    parser.add_argument("repo", type=Path, help="שורש הריפו שקובצי ה-.md שלו ייסרקו")
    parser.add_argument("--out", type=Path, default=None, help="קובץ דוח (ברירת מחדל: stdout)")
    args = parser.parse_args(argv)

    root: Path = args.repo.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"אינו תיקייה: {root}")

    oracle = _load_oracle()
    files = sorted(p for p in root.rglob("*.md") if ".git" not in p.parts)
    if not files:
        parser.error(f"אפס קובצי .md תחת {root} — זה כישלון, לא ריצה ריקה")

    lines: list[str] = []
    mismatched = 0
    total_headings = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        ours = oracle._ours(text)
        theirs = oracle._oracle_sections(text)
        total_headings += len(theirs)
        if ours != theirs:
            mismatched += 1
            lines.append(f"✘ {path.relative_to(root)}")
            lines.append(f"    שלנו : {ours}")
            lines.append(f"    cmark: {theirs}")

    header = [
        f"ריפו:      {root}",
        f"קבצים:     {len(files)}",
        f"כותרות:    {total_headings} (לפי cmark-gfm, ברמת המסמך)",
        f"אי-הסכמות: {mismatched}",
        "",
    ]
    report = "\n".join(header + lines) + "\n"
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"הדוח נכתב ל-{args.out}")
    print(report)
    return 1 if mismatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
