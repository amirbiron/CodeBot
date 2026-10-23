#!/usr/bin/env python3
"""ממיר צילום מסך מקורי לתמונה של הגלריה הציבורית (``/gallery``).

למה סקריפט: כל צילום עובר אותו מסלול — חיתוך של שורות הדפדפן והמערכת, הקטנה, ודחיסה **אחת** מהמקור. בלי סקריפט, כל החלפה של צילום הייתה מנחשת מחדש את הרוחב ואת האיכות, ועלולה לדחוס פעמיים (מ-WebP שכבר נדחס).

שימוש:
    python scripts/build_gallery_image.py SRC NAME --top 128 --bottom 96 [--share]

- ``--top``: כמה פיקסלים לחתוך מלמעלה — שורת הסטטוס של המכשיר ושורת הכרטיסיות של הדפדפן. נמדד מהקובץ עצמו, כי צילום בלי שורת סטטוס מתחיל ישר בכרטיסיות.
- ``--bottom``: כמה פיקסלים לחתוך מלמטה — סרגל הניווט של המערכת, כשהוא בצילום.
- הפלט נשמר ל-``webapp/static/gallery/NAME.webp``, ברוחב :data:`MAX_WIDTH` לכל היותר.
- ``--share``: שומר גם ``NAME.jpg`` ברוחב :data:`SHARE_WIDTH` — תמונת התצוגה המקדימה של הקישור (``og:image``). היא JPEG ולא WebP, כי העמוד של וואטסאפ על תצוגה מקדימה (https://developers.facebook.com/documentation/business-messaging/whatsapp/link-previews/, נקרא באוקטובר 2026) לא מציין אילו פורמטים נתמכים. הגלריה לוקחת אותה מהצילום הראשון ברשימה (``webapp/gallery.py``), ולכן מריצים עם ``--share`` את הצילום שעומד ראשון.

המטא-דאטה של המקור לא עוברת: EXIF של צילום מסך באנדרואיד נושא את מזהה הקושחה של המכשיר. פרופיל צבע, כשיש, מומר ל-sRGB לפני השמירה, כי התמונה נשמרת בלי פרופיל.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

from PIL import Image, ImageCms, ImageOps

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "webapp" / "static" / "gallery"

# רוחב מקסימלי לתמונה בגלריה. מספיק למסך מחשב ברוחב מלא ולפתיחה בגודל מלא, ובכל זאת צילום ממוצע יוצא כ-100KB.
MAX_WIDTH = 1920
WEBP_QUALITY = 85

# וואטסאפ מבקש תמונה מתחת ל-600KB, ברוחב 300px לפחות וביחס של עד 4:1 (העמוד שבראש הקובץ); פייסבוק ממליץ על 1200 רוחב לפחות
# (https://developers.facebook.com/documentation/sharing/webmasters/images).
SHARE_WIDTH = 1200
SHARE_QUALITY = 85

_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _to_srgb(im: Image.Image) -> Image.Image:
    """מחזיר עותק RGB בלי פרופיל צבע — מומר ל-sRGB כשלמקור יש פרופיל."""
    icc = im.info.get("icc_profile")
    if icc:
        src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        dst_profile = ImageCms.createProfile("sRGB")
        return ImageCms.profileToProfile(im.convert("RGB"), src_profile, dst_profile, outputMode="RGB")
    return im.convert("RGB")


def _fit_width(im: Image.Image, width: int) -> Image.Image:
    """מקטין לרוחב ``width`` בשמירה על היחס. תמונה צרה יותר נשארת כמו שהיא — לא מגדילים."""
    if im.width <= width:
        return im
    height = round(im.height * width / im.width)
    return im.resize((width, height), Image.Resampling.LANCZOS)


def build(src: Path, name: str, top: int, bottom: int, share: bool) -> list[Path]:
    if not _NAME_RE.fullmatch(name):
        raise SystemExit(f"שם לא חוקי: {name!r} — אותיות לטיניות קטנות, ספרות ומקפים בלבד")
    if top < 0 or bottom < 0:
        raise SystemExit("--top ו---bottom לא יכולים להיות שליליים")

    with Image.open(src) as opened:
        im = ImageOps.exif_transpose(opened)
        im = _to_srgb(im)
    if top + bottom >= im.height:
        raise SystemExit(f"החיתוך ({top}+{bottom}) גדול מגובה התמונה ({im.height})")
    im = im.crop((0, top, im.width, im.height - bottom))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    webp_path = OUT_DIR / f"{name}.webp"
    _fit_width(im, MAX_WIDTH).save(webp_path, "WEBP", quality=WEBP_QUALITY, method=6)
    written.append(webp_path)

    if share:
        jpg_path = OUT_DIR / f"{name}.jpg"
        _fit_width(im, SHARE_WIDTH).save(jpg_path, "JPEG", quality=SHARE_QUALITY, optimize=True, progressive=True)
        written.append(jpg_path)

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ממיר צילום מסך לתמונה של הגלריה הציבורית")
    parser.add_argument("src", type=Path, help="קובץ הצילום המקורי")
    parser.add_argument("name", help="שם הקובץ בגלריה, בלי סיומת (למשל sticky-notes)")
    parser.add_argument("--top", type=int, required=True, help="פיקסלים לחתוך מלמעלה")
    parser.add_argument("--bottom", type=int, default=0, help="פיקסלים לחתוך מלמטה")
    parser.add_argument("--share", action="store_true", help="לשמור גם JPEG לתצוגה המקדימה של הקישור")
    args = parser.parse_args(argv)

    for path in build(args.src, args.name, args.top, args.bottom, args.share):
        with Image.open(path) as out:
            print(f"{path.relative_to(REPO_ROOT)}  {out.width}x{out.height}  {path.stat().st_size // 1024}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
