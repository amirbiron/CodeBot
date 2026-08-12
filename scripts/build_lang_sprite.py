#!/usr/bin/env python3
"""בונה את ספרייט אייקוני השפות מתוך קבצי ה-SVG הבודדים.

למה זה סקריפט ולא קובץ שנכתב ביד: הספרייט הוא שכפול של 28 קבצים נפרדים,
וכל עדכון ידני שלו הוא הזדמנות לשכוח אייקון או להשאיר גרסה ישנה. כאן הוא
נגזר מהמקור בכל הרצה.

שימוש:
    python scripts/build_lang_sprite.py           # בונה ומעדכן
    python scripts/build_lang_sprite.py --check   # רק בודק אם מעודכן

מקור:  FEATURE_SUGGESTIONS/New_Icons/*.svg
יעדים: FEATURE_SUGGESTIONS/New_Icons/sprite.svg
       webapp/templates/components/lang_sprite.html
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = REPO_ROOT / "FEATURE_SUGGESTIONS" / "New_Icons"
SPRITE_PATH = ICONS_DIR / "sprite.svg"
TEMPLATE_PATH = REPO_ROOT / "webapp" / "templates" / "components" / "lang_sprite.html"

# ההסתרה חייבת להיות position:absolute ולא display:none — עם display:none
# הדפדפן לא מרנדר את הגרדיאנטים שב-defs והאריחים יוצאים שקופים לגמרי.
SPRITE_OPEN = (
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'style="position:absolute;width:0;height:0;overflow:hidden" aria-hidden="true">'
)

TEMPLATE_HEADER = """{# ============================================
   ספרייט אייקוני שפות התכנות
   ============================================

   נוצר אוטומטית על ידי scripts/build_lang_sprite.py — אין לערוך ידנית.
   כדי להוסיף או לשנות אייקון: ערכו את הקובץ הבודד תחת
   FEATURE_SUGGESTIONS/New_Icons/ והריצו את הסקריפט מחדש.

   מוזרק פעם אחת ב-base.html, וכל אייקון נשלף ממנו לפי המזהה lang-<slug>.
   ראו lang_icon() ב-webapp/app.py ו-window.langIcon() ב-base.html.
#}
"""

DEFS_RE = re.compile(r"<defs>(.*?)</defs>", re.DOTALL)
BODY_RE = re.compile(r"</defs>(.*?)</svg>\s*$", re.DOTALL)


def build_sprite() -> tuple[str, list[str]]:
    """מחזיר את תוכן הספרייט ואת רשימת השפות שנכללו בו"""
    sources = sorted(p for p in ICONS_DIR.glob("*.svg") if p.name != "sprite.svg")
    if not sources:
        raise SystemExit(f"לא נמצאו אייקונים תחת {ICONS_DIR}")

    defs_parts: list[str] = []
    symbols: list[str] = []
    slugs: list[str] = []

    for path in sources:
        slug = path.stem
        content = path.read_text(encoding="utf-8").strip()

        defs_match = DEFS_RE.search(content)
        body_match = BODY_RE.search(content)
        if not defs_match or not body_match:
            raise SystemExit(f"מבנה לא צפוי ב-{path.name}: חסר <defs> או גוף")

        body = body_match.group(1).strip()
        if not body:
            raise SystemExit(f"{path.name}: גוף האייקון ריק")

        defs_parts.append(defs_match.group(1).strip())
        symbols.append(f'<symbol id="lang-{slug}" viewBox="0 0 64 64">{body}</symbol>')
        slugs.append(slug)

    sprite = SPRITE_OPEN + "<defs>" + "".join(defs_parts) + "</defs>" + "".join(symbols) + "</svg>"
    return sprite, slugs


def safe_write(path: Path, content: str) -> None:
    """כותב קובץ שנוצר אוטומטית, אחרי אימות שהיעד הוא אחד משני המותרים.

    הסקריפט הזה מייצר קוד מקור, ולכן הוא חייב לכתוב לעץ הפרויקט ולא
    לתיקייה זמנית — אחרת התוצר לא היה נכנס לגרסה. מה שכן נדרש הוא
    שהכתיבה תהיה מצומצמת ומוכחת: כל יעד נבדק מול רשימה סגורה ומול שורש
    הריפו, ואף פעם לא נגזר מקלט חיצוני. אין כאן מחיקה של דבר.

    הכתיבה אטומית — לקובץ זמני ואז החלפה — כדי שהפסקה באמצע לא תשאיר
    ספרייט חתוך שיישבר בזמן רינדור.
    """
    resolved = path.resolve()
    allowed = {SPRITE_PATH.resolve(), TEMPLATE_PATH.resolve()}
    if resolved not in allowed:
        raise SystemExit(f"סירוב לכתוב ליעד שאינו ברשימה המותרת: {resolved}")
    if REPO_ROOT.resolve() not in resolved.parents:
        raise SystemExit(f"סירוב לכתוב מחוץ לשורש הריפו: {resolved}")

    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(resolved)
    finally:
        if tmp.exists():
            tmp.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="בונה את ספרייט אייקוני השפות")
    parser.add_argument(
        "--check",
        action="store_true",
        help="בודק שהקבצים מעודכנים בלי לכתוב, ומחזיר קוד שגיאה אם לא",
    )
    args = parser.parse_args()

    sprite, slugs = build_sprite()
    template = TEMPLATE_HEADER + sprite

    targets = {SPRITE_PATH: sprite, TEMPLATE_PATH: template}
    stale = [
        p for p, expected in targets.items()
        if not p.exists() or p.read_text(encoding="utf-8") != expected
    ]

    if args.check:
        if stale:
            print("הקבצים אינם מעודכנים:")
            for p in stale:
                print(f"  - {p.relative_to(REPO_ROOT)}")
            print("\nהריצו: python scripts/build_lang_sprite.py")
            return 1
        print(f"הספרייט מעודכן — {len(slugs)} אייקונים")
        return 0

    for path, content in targets.items():
        safe_write(path, content)
        print(f"נכתב: {path.relative_to(REPO_ROOT)}")

    print(f"\n{len(slugs)} אייקונים: {', '.join(slugs)}")
    print("\nאל תשכחו לעדכן את LANG_ICON_SLUGS ב-webapp/app.py אם נוספו שפות.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
