#!/usr/bin/env python3
"""ממיר צילום מסך מקורי לתמונה של הגלריה הציבורית (``/gallery``).

למה סקריפט: כל צילום עובר אותו מסלול — חיתוך של שורות הדפדפן והמערכת, הקטנה, ודחיסה **אחת** מהמקור. בלי סקריפט, כל החלפה של צילום הייתה מנחשת מחדש את הרוחב ואת האיכות, ועלולה לדחוס פעמיים (מ-WebP שכבר נדחס).

שימוש:
    python scripts/build_gallery_image.py SRC NAME --top 128 --bottom 96 [--share]

- ``--top``: כמה פיקסלים לחתוך מלמעלה — שורת הסטטוס של המכשיר ושורת הכרטיסיות של הדפדפן. נמדד מהקובץ עצמו, כי צילום בלי שורת סטטוס מתחיל ישר בכרטיסיות.
- ``--bottom``: כמה פיקסלים לחתוך מלמטה — סרגל הניווט של המערכת, כשהוא בצילום.
- הפלט נשמר ל-``webapp/static/gallery/NAME.webp``, ברוחב :data:`MAX_WIDTH` לכל היותר.
- ``--share``: שומר גם ``NAME.jpg`` — תמונת התצוגה המקדימה של הקישור (``og:image``), ב-:data:`SHARE_SIZE` בדיוק ומתחת ל-:data:`SHARE_MAX_BYTES`. הגלריה לוקחת אותה מהצילום הראשון ברשימה (``share_image`` ב-``webapp/gallery.py``), ולכן מריצים עם ``--share`` את הצילום שעומד ראשון. הצילום נחתך ליחס של :data:`SHARE_SIZE` בלי מתיחה: הרוחב מהמרכז, והגובה מלמטה, כך ששורת הכתובת שבראש הצילום נשארת.

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

# תמונת התצוגה המקדימה (``--share``). הגודל לפי ההמלצה של פייסבוק לתמונת שיתוף
# (https://developers.facebook.com/documentation/sharing/webmasters/images); וואטסאפ דורש פחות מ-600KB, רוחב 300 לפחות
# ויחס של עד 4:1 (https://developers.facebook.com/documentation/business-messaging/whatsapp/link-previews/), והתקרה כאן
# בכוונה בחצי ממנו, כדי שהתמונה תוצג בוודאות.
SHARE_SIZE = (1200, 630)
SHARE_MAX_BYTES = 300 * 1024
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


def _share_jpeg(im: Image.Image) -> bytes:
    """תמונת התצוגה המקדימה כ-JPEG, ב-:data:`SHARE_SIZE`. נכשל לפני כתיבה כשהיא מעל :data:`SHARE_MAX_BYTES`."""
    fitted = ImageOps.fit(im, SHARE_SIZE, method=Image.Resampling.LANCZOS, centering=(0.5, 0.0))
    buf = io.BytesIO()
    fitted.save(buf, "JPEG", quality=SHARE_QUALITY, optimize=True, progressive=True)
    data = buf.getvalue()
    if len(data) > SHARE_MAX_BYTES:
        raise SystemExit(f"תמונת התצוגה המקדימה {len(data) // 1024}KB, מעל התקרה של {SHARE_MAX_BYTES // 1024}KB — לא נכתבה")
    return data


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

    # התמונה לתצוגה המקדימה מוכנה לפני שנכתב משהו, כך שחריגה מהתקרה לא משאירה WebP חדש בלי JPEG תואם
    share_data = _share_jpeg(im) if share else None

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    webp_path = OUT_DIR / f"{name}.webp"
    _fit_width(im, MAX_WIDTH).save(webp_path, "WEBP", quality=WEBP_QUALITY, method=6)
    written = [webp_path]

    if share_data is not None:
        jpg_path = OUT_DIR / f"{name}.jpg"
        jpg_path.write_bytes(share_data)
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
