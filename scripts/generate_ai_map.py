#!/usr/bin/env python3
"""מחולל AI-MAP.md — מפת ניווט של אתר התיעוד, נגזרת מהקבצים עצמם.

הבעיה שהקובץ פותר: באתר יש כ-240 עמודים, וסוכן שמחפש תשובה גורר את
כולם או מוותר. המפה נותנת שורה אחת לכל עמוד ידני — נתיב, כותרת, ותקציר
שנשלף מהפסקה הראשונה — כדי שהחיפוש יתחיל מקובץ אחד.

עקרונות, לפי תוכנית עיגון התיעוד (אוגוסט 2026):

- **נגזר, לא נכתב.** ההיררכיה נלקחת מה-toctree של Sphinx (מקור האמת),
  והתקצירים מהעמודים עצמם. עריכה ידנית של הפלט תידרס בריצה הבאה.
- **דטרמיניסטי.** אותו קלט ← אותו פלט, בייט בבייט: סדר ה-toctree נשמר,
  אין חותמות זמן, קידוד UTF-8 קבוע. בלי זה כל השוואה הופכת לרעש.
- **מסונן מכנית.** עמודים שהם פיגום autodoc בלבד (הוראת automodule בלי
  פרוזה) לא נכללים — התוכן שלהם נוצר רק בזמן בנייה, ומהריפו אין בהם
  כלום. הם נספרים בשורת סיכום כדי שההשמטה תהיה גלויה.
- **שליפת תקציר עמידה.** לא "השורה הראשונה" באופן עיוור: מדלגים על
  directives, admonitions, הערות, שדות ו-toctree, ולוקחים את פסקת
  הפרוזה הראשונה, קצוצה לתקרת תווים.

בלי --out המפה מודפסת ל-stdout ושום קובץ לא נכתב; --out קובע מתי ולאן.
ה-workflow מעביר --out AI-MAP.md בשורש הריפו ולא ב-docs/, כי MyST פעיל
וכל .md בתוך docs/ נכנס לבניית Sphinx — עמוד שאינו ב-toctree מפיל את
RTD על אזהרת יתום.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUTPUT = ROOT / "AI-MAP.md"
SUMMARY_CAP = 220

# שורת directive של RST (.. name::) או תחילת בלוק הערה (.. בלי ::)
_DIRECTIVE_RE = re.compile(r"^\.\. ")
_UNDERLINE_RE = re.compile(r"^([=\-~^\"'#*+.`:_])\1{2,}\s*$")
_FIELD_RE = re.compile(r"^:[\w-]+:")
_TOCTREE_ENTRY_RE = re.compile(r"^\s{3,}(\S.*)$")
# שורת המפריד של טבלת Markdown: ---|--- , :--|--: וכד'. שורת הכותרת
# שמעליה עשויה להיות בלי pipe חיצוני ("שם | ערך") ואז היא נראית כמו
# פרוזה — המפריד הוא מה שמסגיר אותה.
_MD_DELIM_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
# שורת גבול של grid table ב-RST: +----+====+ וכד'. ה-+ מותר רק
# כמפריד בין מקטעי [=-], לא בתוך מחלקת התווים: '+' שחופף בין המחלקה
# לקבוצה החוזרת יוצר backtracking אקספוננציאלי (נמדד: ×2.6 לכל תו)
# על שורה ארוכה של פלוסים שאינה מתאימה.
_GRID_ROW_RE = re.compile(r"^\+(?:[=-]+\+)+$")
_AUTODOC_RE = re.compile(r"^\.\. auto(module|class|function)::")


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split("\n")


def _resolve(base_dir: Path, entry: str) -> Path | None:
    """ערך toctree ← קובץ קיים (rst או md), או None לקישור חיצוני/חסר."""
    if entry.startswith(("http://", "https://")):
        return None
    # תמיכה בצורת "כותרת <נתיב>"
    m = re.match(r".*<(.+)>\s*$", entry)
    if m:
        entry = m.group(1)
    for suffix in (".rst", ".md", ""):
        p = (base_dir / f"{entry}{suffix}").resolve()
        if p.is_file():
            return p
    return None


def _toctree_blocks(lines: list[str]):
    """מחזיר (caption, [ערכים]) לכל בלוק toctree, בסדר הופעתם."""
    i = 0
    while i < len(lines):
        if lines[i].strip() == ".. toctree::":
            caption = ""
            entries = []
            i += 1
            while i < len(lines):
                line = lines[i]
                stripped = line.strip()
                if stripped.startswith(":caption:"):
                    caption = stripped.split(":caption:", 1)[1].strip().rstrip(":")
                elif stripped.startswith(":"):
                    pass  # אופציה אחרת (maxdepth וכו')
                elif not stripped:
                    # שורה ריקה בתוך הבלוק מותרת רק בין האופציות לערכים
                    if entries:
                        break
                elif _TOCTREE_ENTRY_RE.match(line):
                    entries.append(stripped)
                else:
                    break
                i += 1
            yield caption, entries
        else:
            i += 1


def _title(lines: list[str], path: Path) -> str:
    if path.suffix == ".md":
        for idx, ln in enumerate(lines):
            if ln.startswith("# "):
                return ln[2:].strip()
            if ln.strip() and idx + 1 < len(lines) and _UNDERLINE_RE.match(lines[idx + 1]):
                return ln.strip()  # כותרת setext: טקסט ומתחתיו ====
        return path.stem
    for idx in range(len(lines) - 1):
        text, under = lines[idx].strip(), lines[idx + 1]
        is_heading = text and not _DIRECTIVE_RE.match(lines[idx]) and _UNDERLINE_RE.match(under)
        if is_heading and len(under.strip()) >= len(text) - 2:
            return text
    return path.stem


def _first_prose_paragraph(lines: list[str], path: Path) -> str:
    """פסקת הפרוזה הראשונה — מדלגים על כל מה שאינו טקסט רץ."""
    md = path.suffix == ".md"
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if md:
            if i + 1 < n and _UNDERLINE_RE.match(lines[i + 1]):
                i += 2  # כותרת setext: הטקסט + קו המתחת
                continue
            if stripped.startswith(("#", "```", ":::", "---", "|", ">", "![", "[!")):
                # כותרת / קוד / הערת MyST / חוקק / טבלה / ציטוט / תמונה
                if stripped.startswith(("```", ":::")):
                    fence = stripped[:3]
                    i += 1
                    while i < n and not lines[i].strip().startswith(fence):
                        i += 1
                i += 1
                continue
        else:
            if _DIRECTIVE_RE.match(line) or stripped == "..":
                # directive/הערה: דילוג על הגוף המוזח כולו
                i += 1
                while i < n and (not lines[i].strip() or lines[i].startswith((" ", "\t"))):
                    i += 1
                continue
            if _FIELD_RE.match(stripped) or _UNDERLINE_RE.match(line):
                i += 1
                continue
            if i + 1 < n and _UNDERLINE_RE.match(lines[i + 1]):
                i += 2  # כותרת + קו
                continue
            if line.startswith((" ", "\t")):
                i += 1  # המשך בלוק מוזח שלא זוהה
                continue
        if (
            stripped.startswith(("- ", "* ", "#. "))
            or re.match(r"^\d+\. ", stripped)
            or _GRID_ROW_RE.match(stripped)
            or _MD_DELIM_RE.match(stripped)
            or (i + 1 < n and "|" in stripped and _MD_DELIM_RE.match(lines[i + 1]))
        ):
            i += 1  # רשימה, גבול grid, או שורת טבלת Markdown — לא תקציר
            continue
        # פסקת פרוזה: איסוף עד שורה ריקה, בלוק מוזח או תחילת רשימה
        para = []
        while i < n and lines[i].strip() and not lines[i].startswith((" ", "\t")):
            cur = lines[i].strip()
            is_list = cur.startswith(("- ", "* ", "#. ")) or re.match(r"^\d+\. ", cur)
            is_table = (
                cur.startswith("|")
                or _GRID_ROW_RE.match(cur)
                # כותרת טבלת Markdown בלי pipe חיצוני, שהמפריד מתחתיה
                or (i + 1 < n and "|" in cur and _MD_DELIM_RE.match(lines[i + 1]))
            )
            if is_list or is_table or cur.startswith(("```", ":::")) or _UNDERLINE_RE.match(lines[i]):
                break  # רשימה / טבלה / גדר קוד — לא חלק מהתקציר
            para.append(cur)
            i += 1
        text = re.sub(r"\s+", " ", " ".join(para))
        # `תווית <כתובת>`_ ← תווית (לפני הסרת ה-backticks, אחרת נשאר _ יתום)
        text = re.sub(r"`([^`<]+?)\s*<[^`>]+>`_{1,2}", r"\1", text)
        text = re.sub(r"``([^`]*)``", r"\1", text)
        text = re.sub(r":[\w:+-]+:`([^`]*)`", r"\1", text)  # :doc:`x` ← x
        text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
        # "::" בסוף פסקה הוא פתיח לבלוק literal של RST, לא חלק מהתקציר
        text = text.rstrip(":").strip()
        # backtick יתום (מספר אי-זוגי) שובר את ה-Markdown של שורת המפה;
        # אבל זוגות מאוזנים הם inline-code לגיטימי (GITHUB_TOKEN,
        # POST /api/...) ששווה לשמר — מסירים רק כשאין איזון.
        if text.count("`") % 2:
            text = text.replace("`", "")
        if len(text) > SUMMARY_CAP:
            text = text[: SUMMARY_CAP - 1].rsplit(" ", 1)[0] + "…"
        # פסקה שהתרוקנה או קצרה מכדי לומר משהו (פתיח כמו "טיפים:",
        # "Development::") — לנסות את הפסקה הבאה. אם לא נאסף כלום
        # (למשל עמוד שנפתח בטבלה: "|" עוצר את האיסוף לפני קידום i),
        # חובה לקדם את i ידנית — אחרת אותה שורה נבדקת שוב לנצח.
        if len(text) < 20:
            if not para:
                i += 1
            continue
        return text
    return ""


def _is_autodoc_scaffold(lines: list[str], path: Path) -> bool:
    return any(_AUTODOC_RE.match(ln) for ln in lines) and not _first_prose_paragraph(lines, path)


def build_map() -> str:
    index = DOCS / "index.rst"
    visited: set[Path] = set()
    out: list[str] = []
    scaffold_count = 0

    out.append("# מפת התיעוד לסוכני AI")
    out.append("")
    out.append("<!-- קובץ זה נוצר אוטומטית על ידי scripts/generate_ai_map.py — אל תערכו ידנית; עריכה תידרס. -->")
    out.append("")
    out.append(
        "שורה לכל עמוד ידני באתר התיעוד: נתיב, כותרת ותקציר מהפסקה "
        "הראשונה. ההיררכיה נגזרת מה-toctree. עמודי פיגום של autodoc "
        "(ללא פרוזה) מסוננים — התוכן שלהם נוצר רק בזמן בנייה; "
        "לחתימות קראו את הקוד עצמו."
    )
    out.append("")

    def walk(path: Path, depth: int) -> None:
        nonlocal scaffold_count
        if path in visited:
            return
        visited.add(path)
        lines = _read(path)
        for caption, entries in _toctree_blocks(lines):
            children = []
            for entry in entries:
                child = _resolve(path.parent, entry)
                if child is None or child in visited:
                    continue
                children.append(child)
            if not children:
                continue
            if caption and depth == 0:
                out.append(f"## {caption}")
                out.append("")
            for child in children:
                # ערך שמופיע פעמיים באותו בלוק: שניהם עוברים את הסינון של
                # בניית children (אף אחד עוד לא ב-visited), והשני היה נכתב
                # שוב. walk מעדכן את visited רק אחרי שהלולאה כאן כבר רצה.
                if child in visited:
                    continue
                clines = _read(child)
                rel = child.relative_to(ROOT).as_posix()
                if _is_autodoc_scaffold(clines, child):
                    # מדלגים על שורת הפיגום עצמו, אבל יורדים לילדיו:
                    # עמודי אינדקס של autodoc (api/handlers.rst וכד')
                    # מחזיקים toctree לעמודים שחלקם כן ידניים.
                    # לא מוסיפים ל-visited כאן — walk פותח בבדיקת visited
                    # והוספה מוקדמת הייתה הופכת את הירידה ל-no-op.
                    scaffold_count += 1
                    # באותו עומק, לא depth+1: שורת הפיגום לא נכתבה,
                    # והילדים תופסים את מקומו — אחרת ההזחה קופצת רמה.
                    walk(child, depth)
                    continue
                title = _title(clines, child)
                summary = _first_prose_paragraph(clines, child)
                if summary.rstrip("…") and summary.rstrip("…") in title:
                    summary = ""
                indent = "  " * depth
                line = f"{indent}- `{rel}` — **{title}**"
                if summary:
                    line += f": {summary}"
                out.append(line)
                walk(child, depth + 1)
            if depth == 0:
                out.append("")

    walk(index, 0)
    out.append("---")
    out.append("")
    out.append(f"עמודי פיגום autodoc שסוננו: {scaffold_count}. עמודים שנסרקו: {len(visited)}.")
    out.append("")
    return "\n".join(out)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=None,
        help="נתיב לכתיבת המפה. בלי הדגל שום קובץ לא נכתב (המפה מודפסת "
             "ל-stdout) — לפי מדיניות הריפו סקריפט לא כותב ב-root אלא "
             "בהוראה מפורשת. ה-workflow מעביר --out AI-MAP.md בכוונה.",
    )
    parser.add_argument(
        "--check", type=Path, nargs="?", const=OUTPUT, default=None,
        metavar="PATH",
        help="לא כותב; קוד יציאה 1 אם הקובץ (ברירת מחדל: AI-MAP.md בשורש) "
             "אינו תואם את מה שהיה נוצר.",
    )
    args = parser.parse_args()
    if args.check is not None and args.out is not None:
        # קבלה שקטה של שניהם הייתה מתעלמת מהכתיבה: הקורא ביקש קובץ
        # וקיבל רק השוואה, בלי שום רמז שהקובץ לא נוצר.
        parser.error("אי אפשר לשלב את --check עם --out — בחרו אחד")
    content = build_map()
    if args.check is not None:
        existing = args.check.read_text(encoding="utf-8") if args.check.exists() else None
        if existing == content:
            print(f"{args.check.name}: עדכני")
            return 0
        print(f"{args.check.name}: אינו תואם את התיעוד הנוכחי")
        return 1
    if args.out is None:
        sys.stdout.write(content)
        return 0
    existing = args.out.read_text(encoding="utf-8") if args.out.exists() else None
    if existing == content:
        print(f"{args.out.name}: ללא שינוי")
        return 0
    args.out.write_text(content, encoding="utf-8")
    print(f"{args.out.name}: נכתב ({len(content.splitlines())} שורות)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
