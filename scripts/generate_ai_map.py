#!/usr/bin/env python3
"""מחולל AI-MAP.md — מפת ניווט של אתר התיעוד, נגזרת מהקבצים עצמם.

הבעיה שהקובץ פותר: באתר יש כ-240 עמודים, וסוכן שמחפש תשובה גורר את
כולם או מוותר. המפה נותנת שורה אחת לכל עמוד ידני — נתיב, כותרת, והתקציר
שהעמוד מצהיר עליו בראשו — כדי שהחיפוש יתחיל מקובץ אחד.

עקרונות, לפי תוכנית עיגון התיעוד (אוגוסט 2026):

- **נגזר, לא נכתב.** ההיררכיה נלקחת מה-toctree של Sphinx (מקור האמת),
  והתקצירים מהצהרת העמוד. עריכה ידנית של הפלט תידרס בריצה הבאה.
- **דטרמיניסטי.** אותו קלט ← אותו פלט, בייט בבייט: סדר ה-toctree נשמר,
  אין חותמות זמן, קידוד UTF-8 קבוע. בלי זה כל השוואה הופכת לרעש.
- **מסונן מכנית.** עמודים שהם פיגום autodoc בלבד (הוראת automodule בלי
  שום תוכן משלהם) לא נכללים — התוכן שלהם נוצר רק בזמן בנייה, ומהריפו
  אין בהם כלום. הם נספרים בשורת סיכום כדי שההשמטה תהיה גלויה.
- **התקציר מוצהר, לא מנוחש.** ב-``.rst`` שדה ``:summary:`` ברשימת השדות
  שמיד אחרי הכותרת; ב-``.md`` המפתח ``summary`` ב-front matter. אין
  הצהרה — שורת המפה מציגה כותרת בלבד, ו-``--check`` מתריע. הגרסה
  הקודמת חילצה את פסקת הפרוזה הראשונה, וכדי לעשות זאת מימשה חלקים
  מ-GFM ומ-RST ביד; ארבעה סבבי ריוויו מצאו שם מקרי קצה.

בלי --out המפה מודפסת ל-stdout ושום קובץ לא נכתב; --out קובע מתי ולאן.
ה-workflow מעביר --out AI-MAP.md בשורש הריפו ולא ב-docs/, כי MyST פעיל
וכל .md בתוך docs/ נכנס לבניית Sphinx — עמוד שאינו ב-toctree מפיל את
RTD על אזהרת יתום.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUTPUT = ROOT / "AI-MAP.md"
SUMMARY_CAP = 220

# שורת directive של RST (.. name::) או תחילת בלוק הערה (.. בלי ::)
_DIRECTIVE_RE = re.compile(r"^\.\. ")
_UNDERLINE_RE = re.compile(r"^([=\-~^\"'#*+.`:_])\1{2,}\s*$")
_FIELD_RE = re.compile(r"^:[\w-]+:")
# שדה ההצהרה, בעמודה 0 בדיוק — שדה מוזח שייך לבלוק שמעליו
_SUMMARY_FIELD_RE = re.compile(r"^:summary:[ \t]*(.*)$")
# מה מדלגים עליו בדרך אל ההצהרה, ולמה זה כלל אחד ולא רשימת שמות.
#
# גרסה קודמת כאן מידלה את ``DocInfo`` של docutils — הטרנספורם שמקדם
# רשימת שדות ל-``<docinfo>`` ומתעלם בדרך מ-``nodes.PreBibliographic``.
# אימות מול הצרכן הראה שהטרנספורם הזה כלל אינו רץ כאן: Sphinx מכבה
# ``doctitle_xform`` (``sphinx/environment/__init__.py``, שורה 66:
# ``'doctitle_xform': False``), הכותרת נשארת בתוך ``<section>``,
# ``DocInfo`` לא מוצא רשימת שדות כילד ראשון של המסמך — ואין קידום. בבנייה
# מלאה של האתר יש **אפס** בלוקי ``docinfo``, ו-``:summary:`` מרונדר כמו
# שהוא: ``<dl class="field-list simple">`` במקום שבו הוא כתוב.
#
# מהמודל המת ההוא נולדה שאלה שאין לה תשובה יציבה: "אילו directives
# שקופים?". שלושה סבבי ריוויו רצופים נפלו עליה — פעם ``.. note::``, פעם
# ``.. py:function::``, פעם ``.. raw::``, פעם ``.. default-role::``. כל
# תשובה הייתה רשימת שמות שמישהו ניחש, וכל directive חדש בסביבה הפיל
# אותה שוב.
#
# הכלל כאן מוותר על השאלה. אין קידום ל-docinfo, ולכן אין הבדל בין
# "שקוף" ל"מרנדר": בשני המקרים השדה מרונדר בעמוד, והוא ההצהרה של הכותב.
# מדלגים על **כל** explicit markup — הערה, יעד, directive, על גופו המוזח
# — וההצהרה היא רשימת השדות הראשונה שנפגשת. תוכן שאינו explicit markup
# ואינו שדה (פרוזה, רשימה, טבלה) עוצר את החיפוש, כי ממנו והלאה כבר לא
# מדובר בראש העמוד.
#
# ``Body.patterns['explicit_markup']`` ב-``docutils/parsers/rst/states.py``
# הוא ``\.\.( +|$)`` — רווחים בלבד, לא טאב.
_EXPLICIT_MARKUP_RE = re.compile(r"^\.\.( +|$)")
_TOCTREE_ENTRY_RE = re.compile(r"^\s{3,}(\S.*)$")

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


def _body_start(lines: list[str]) -> int:
    """האינדקס שאחרי ה-front matter, או 0 אם אין.

    לפי ``markdown_it``/MyST, front matter הוא בלוק שנפתח ב-``---`` בשורה
    הראשונה ממש ונסגר ב-``---`` או ``...``.
    """
    if not lines or lines[0].strip() != "---":
        return 0
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return i + 1
    return 0  # לא נסגר — MyST גם לא היה מזהה אותו כ-front matter


def _title(lines: list[str], path: Path) -> str:
    if path.suffix == ".md":
        # מדלגים על front matter לפני חיפוש הכותרת: ה-``---`` הסוגר שלו
        # הוא קו-תחתון חוקי לפי ``_UNDERLINE_RE``, ולכן שורת ``summary:``
        # שמעליו נקראה ככותרת setext והכותרת של העמוד יצאה "summary: ...".
        for idx, ln in enumerate(lines[_body_start(lines):], start=_body_start(lines)):
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


def _declared_summary(lines: list[str], path: Path) -> str:
    """התקציר שהעמוד מצהיר עליו בראשו, או מחרוזת ריקה אם אין.

    שני תחבירים, כל אחד הסטנדרטי בפורמט שלו — ולא שלישי:

    * ``.rst`` — שדה ``:summary:`` מתחת לכותרת. ב-Sphinx אין קידום
      ל-``<docinfo>`` (ראו ההסבר ליד :data:`_EXPLICIT_MARKUP_RE`), והשדה
      מרונדר בדיוק במקומו: ``<dl class="field-list simple">`` מתחת ל-H1.
      זה מה שרואים בעמוד, וזה מה שנכנס למפה.
    * ``.md`` — ``summary`` ב-front matter. נקרא ב-``yaml.safe_load``,
      בדיוק כמו ש-MyST קורא אותו (``myst_parser/mdit_to_docutils/base.py``:
      ``data = yaml.safe_load(token.content)``).

    למה הצהרה ולא חילוץ מהגוף: הגרסה הקודמת ניסתה לזהות את פסקת הפרוזה
    הראשונה, וכדי לעשות זאת נאלצה לממש חלקים מ-GFM ומ-RST ביד — טבלאות,
    גדרות, תחילות בלוק. ארבעה סבבי ריוויו רצופים מצאו שם מקרי קצה, כולל
    תקציר שיצא הטבלה עצמה ותקציר שיצא ריק. מי שכתב את העמוד יודע מה
    התקציר; אין צורך לנחש.
    """
    raw = _front_matter_summary(lines) if path.suffix == ".md" else _rst_field_summary(lines)
    return _cap(raw)


def _cap(text: str) -> str:
    """חיתוך לאורך שורת מפה. שורה ארוכה מדי מבטלת את התועלת של מפה.

    ההצהרה עצמה נשארת מלאה בעמוד; רק שורת המפה נחתכת. פונקציה נפרדת כדי
    שגם ``tests/test_doc_summary_style.py`` יוכל להחיל את אותו חיתוך
    כשהוא משווה את מה שהוא בודק מול מה שכתוב ב-``AI-MAP.md``.
    """
    if len(text) <= SUMMARY_CAP:
        return text
    return text[: SUMMARY_CAP - 1].rsplit(" ", 1)[0] + "…"


def _front_matter_summary(lines: list[str]) -> str:
    """``summary`` מתוך front matter של MyST, אם יש."""
    end = _body_start(lines) - 1
    if end < 1:
        return ""  # אין front matter, או שהוא לא נסגר
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return ""
    if not isinstance(data, dict):
        return ""
    value = data.get("summary")
    return " ".join(str(value).split()) if value else ""


def _consume_indented_body(lines: list[str], i: int) -> int:
    """מדלג על הגוף המוזח של explicit markup שהתחיל בשורה הקודמת.

    זה בדיוק המקום שבו כבר היה באג פעם אחת: קידום של שורה אחת נעצר על
    הגוף המוזח, הכותרת לא נמצאה, והתקציר יצא ריק.

    למה רק כאן ולא גם ב-:func:`_is_autodoc_scaffold`: שם הלולאה מדלגת
    ממילא על כל שורה מוזחת, בשומר ``raw[:1].isspace()`` שבראשה. קריאה
    לפרימיטיב הזה משם הייתה נכונה אבל חסרת השפעה — מוטציה שביטלה אותה
    לא הפילה אף בדיקה — וקוד שאי אפשר להפיל אי אפשר גם לשמור עליו.
    """
    n = len(lines)
    while i < n and (not lines[i].strip() or lines[i][:1].isspace()):
        i += 1
    return i


def _skip_explicit_markup(lines: list[str], i: int) -> int:
    """מדלג על שורות ריקות ועל כל explicit markup — כולל הגוף המוזח.

    הגוף המוזח הוא העיקר: directive או הערה רב-שורות נפרסים על כמה
    שורות, וקידום של שורה אחת בלבד נעצר על הגוף המוזח — ואז הכותרת לא
    נמצאת והתקציר יוצא ריק.
    """
    n = len(lines)
    while i < n:
        if not lines[i].strip():
            i += 1
            continue
        if not _EXPLICIT_MARKUP_RE.match(lines[i]):
            return i
        i = _consume_indented_body(lines, i + 1)
    return i


def _rst_field_summary(lines: list[str]) -> str:
    """שדה ``:summary:`` מרשימת השדות הראשונה שאחרי כותרת המסמך.

    ההצהרה היא מה שרואים בראש העמוד. לכן מדלגים על explicit markup —
    לפני הכותרת ואחריה — ולוקחים את רשימת השדות הראשונה שנפגשת. פרוזה,
    רשימה או טבלה עוצרות: ``:summary:`` שמופיע אחריהן או בתוך סעיף כבר
    אינו הצהרה בראש העמוד, וחיפוש בכל הקובץ היה מציג אותו ככזה במפה.
    """
    i, n = 0, len(lines)
    i = _skip_explicit_markup(lines, i)
    # הכותרת עצמה: טקסט + קו, או קו + טקסט + קו
    if i < n and _UNDERLINE_RE.match(lines[i]):
        i += 1  # overline
    if i + 1 < n and lines[i].strip() and _UNDERLINE_RE.match(lines[i + 1]):
        i += 2
    else:
        return ""  # אין כותרת מסמך — אין מיקום להצהרה
    # גם **אחרי** הכותרת מדלגים: יעד, הערה או directive בין הכותרת לשדה
    # אינם מזיזים את ההצהרה מראש העמוד, והקוד כאן דילג פעם רק על שורות
    # ריקות — כך שהם הסתירו תקציר תקין לגמרי.
    i = _skip_explicit_markup(lines, i)
    summary = ""
    while i < n:
        line = lines[i]
        if not line.strip():
            break  # שורה ריקה סוגרת את רשימת השדות
        if not _FIELD_RE.match(line):
            break  # תוכן רגיל — רשימת השדות נגמרה
        m = _SUMMARY_FIELD_RE.match(line)
        parts = [m.group(1)] if m else []
        i += 1
        while i < n and lines[i].strip() and lines[i][:1].isspace():
            if m:
                parts.append(lines[i].strip())
            i += 1
        if m:
            summary = " ".join(" ".join(parts).split())
            break
    return summary


def _is_autodoc_scaffold(lines: list[str], path: Path) -> bool:
    """עמוד שכולו הוראת autodoc — כותרת, directives, וכלום מעבר.

    הבדיקה מבנית ולא תוכנית: קודם היא שאלה "יש autodoc ואין פסקת פרוזה",
    ולכן גררה את כל מנגנון חילוץ הפרוזה. עכשיו היא שואלת אם נשארה ולו
    שורת תוכן אחת בעמודה 0 שאינה כותרת, קו, שדה או directive. אומת:
    שתי הנוסחאות מסווגות את אותם 92 עמודים בדיוק.
    """
    if not any(_AUTODOC_RE.match(ln) for ln in lines):
        return False
    if _declared_summary(lines, path):
        # הצהרת תקציר היא תוכן שמישהו כתב, וזה בדיוק מה שהמסנן מחפש.
        # בלי הכלל הזה עמוד שכל הפרוזה שלו הייתה כפילות של ההצהרה
        # והוסרה — כמו docs/modules/index.rst — נשר מהמפה בשקט.
        return False
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or raw[:1].isspace():
            i += 1  # שורה ריקה או גוף מוזח של directive
            continue
        if _DIRECTIVE_RE.match(raw) or stripped == "..":
            # כאן מדלגים על **כל** explicit markup (כולל ``automodule``),
            # ולא רק על הצורות השקופות — זו שאלה אחרת: האם נשאר תוכן
            # שנכתב ביד. הגוף המוזח נצרך ממילא בשומר שבראש הלולאה.
            i += 1
            continue
        if _UNDERLINE_RE.match(raw):
            i += 1  # קו של כותרת
            continue
        if i + 1 < n and _UNDERLINE_RE.match(lines[i + 1]):
            i += 2  # כותרת + קו
            continue
        if _FIELD_RE.match(stripped):
            i += 1  # שדה הצהרה, למשל :summary:
            continue
        return False
    return True


#: מתמלא בכל הרצה של :func:`build_map` — העמודים הידניים שאין להם הצהרת
#: תקציר. ``--check`` מתריע עליהם ולא מפיל: עמוד בלי תקציר עדיין מופיע
#: במפה עם הכותרת שלו, וזו הידרדרות הדרגתית ולא שבירה.
undeclared: list[str] = []


def build_map() -> str:
    undeclared.clear()
    index = DOCS / "index.rst"
    visited: set[Path] = set()
    out: list[str] = []
    scaffold_count = 0

    out.append("# מפת התיעוד לסוכני AI")
    out.append("")
    out.append("<!-- קובץ זה נוצר אוטומטית על ידי scripts/generate_ai_map.py — אל תערכו ידנית; עריכה תידרס. -->")
    out.append("")
    out.append(
        "שורה לכל עמוד ידני באתר התיעוד: נתיב, כותרת, והתקציר שהעמוד "
        "מצהיר עליו בראשו (`:summary:` ב-rst, `summary` ב-front matter). "
        "עמוד בלי הצהרה מופיע עם הכותרת בלבד. ההיררכיה נגזרת מה-toctree. "
        "עמודי פיגום של autodoc מסוננים — התוכן שלהם נוצר רק בזמן בנייה; "
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
                summary = _declared_summary(clines, child)
                if not summary:
                    undeclared.append(rel)
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
        if undeclared:
            print(f"התרעה: {len(undeclared)} עמודים ידניים בלי הצהרת תקציר "
                  f"(:summary: ב-rst, summary ב-front matter):")
            for rel in undeclared:
                print(f"  - {rel}")
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
