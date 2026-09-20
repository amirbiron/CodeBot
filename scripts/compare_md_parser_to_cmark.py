#!/usr/bin/env python3
"""משווה את ``services/md_parser`` מול cmark-gfm על **כל** קובצי ה-``.md``
בריפו שמעבירים לו.

**מה מושווה, כדי שהתוצאה לא תיקרא רחבה ממה שהיא:** לכל כותרת ברמת
המסמך — **הרמה ומספר השורה**. טקסט הכותרת אינו מושווה כאן, כי אצלנו
הוא המקור הגולמי ומ-cmark חוזר HTML מרונדר. הצד הזה נבדק בנפרד ועל
תת-קבוצה, ב-``tests/test_md_parser_oracle.py``.

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
# לפני כל ייבוא מ-``services``: הסקריפט רץ כנקודת כניסה עצמאית,
# ו-``scripts`` אינה חבילה.
sys.path.insert(0, str(_REPO))

from services.doc_sections import InconsistentLineEndings, TooManySections  # noqa: E402


def _load_oracle():
    """טוען את האורקל מקובץ הטסטים — הגדרה אחת לשני המריצים."""
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
    skipped: list[str] = []
    mismatched = 0
    compared = 0
    total_headings = 0
    for path in files:
        name = path.relative_to(root)
        # **``read_bytes().decode`` ולא ``read_text``.** האחרון פותח את
        # הקובץ במצב טקסט עם universal newlines וממיר כל ``\r`` ל-
        # ``\n`` לפני שהמחרוזת מגיעה לפארסר — כלומר
        # ``InconsistentLineEndings`` לא הייתה יכולה להידלק כאן על שום
        # קובץ, והסקריפט היה מדווח "אפס אי-הסכמות" גם על מחלקת קלט
        # שבורה לגמרי. ``newline=""`` אינו פתרון: הפרמטר נוסף ל-
        # ``Path.read_text`` רק בפייתון 3.13, וה-CI רץ על 3.11 ו-3.12.
        #
        # **וכל קובץ עומד בפני עצמו.** הסקריפט מכוון על ריפו זר, ולכן
        # קובץ מוזר הוא המקרה הצפוי ולא החריג — נפילה עליו הייתה מוחקת
        # גם את התוצאות של כל מה שכבר נסרק, כי הדוח נבנה אחרי הלולאה.
        # **``utf-8`` ולא ``utf-8-sig`` — בכוונה.** הסקריפט הוא בדיקה של
        # הפארסר, ו-``parse_document`` הוא זה שמסיר BOM. אילו הפענוח כאן
        # היה מסיר אותו קודם, רגרסיה בדיוק בהתנהגות הזאת הייתה בלתי
        # נראית מכאן. הייצור מפענח אחרת — ``git_mirror_service.
        # _try_decode_content`` משתמש ב-``utf-8-sig`` — וזה בסדר: שם
        # המטרה היא תוכן נקי, כאן המטרה היא לראות מה הפארסר עושה.
        try:
            text = path.read_bytes().decode("utf-8")
            ours = oracle._ours(text)
            theirs = oracle._oracle_sections(text)
        except UnicodeDecodeError:
            skipped.append(f"⊘ {name} — אינו UTF-8")
            continue
        except OSError as exc:
            skipped.append(f"⊘ {name} — לא ניתן לקריאה: {exc.strerror}")
            continue
        except InconsistentLineEndings:
            skipped.append(f"⊘ {name} — ‏\\r בודד, הפארסר סירב")
            continue
        except TooManySections as exc:
            skipped.append(f"⊘ {name} — מעל התקרה, הפארסר סירב בשורה {exc.args[0]}")
            continue

        compared += 1
        total_headings += len(theirs)
        if ours != theirs:
            mismatched += 1
            lines.append(f"✘ {name}")
            lines.append(f"    שלנו : {ours}")
            lines.append(f"    cmark: {theirs}")

    header = [
        f"ריפו:       {root}",
        f"קבצים:      {len(files)} (הושוו {compared}, סורבו {len(skipped)})",
        f"כותרות:     {total_headings} (לפי cmark-gfm, ברמת המסמך)",
        f"אי-הסכמות:  {mismatched} — ההשוואה היא על **רמה ומספר שורה** בלבד,",
        "            ולא על טקסט הכותרת. ההנמקה בראש קובץ האורקל.",
        "",
    ]
    if skipped:
        header.extend(skipped)
        header.append("")
    report = "\n".join(header + lines) + "\n"
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"הדוח נכתב ל-{args.out}")
    print(report)

    # **"אפס אי-הסכמות" על אפס קבצים שהושוו אינו הצלחה.** מאותו נימוק
    # בדיוק שכתוב למעלה על ריפו בלי קובצי ``.md``: מספר שנראה טוב כי
    # לא נבדק דבר הוא אישור שקרי, ומי שיראה ``exit 0`` יסיק שהפארסר
    # מסכים עם cmark על הקורפוס הזה.
    if not compared:
        print("כל הקבצים סורבו — לא הושווה דבר, וזה כישלון ולא ריצה נקייה.")
        return 1
    return 1 if mismatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
