"""אריזת תיקייה אחת מתוך zipball של GitHub — בתהליך נפרד מהבוט.

**למה תהליך נפרד.** תהליך הבוט מריץ ``monkey.patch_all()`` של gevent (``main.py``),
ואחרי זה ``asyncio.to_thread`` מריץ את העבודה בגרינלט באותו OS thread, לא בחוט
אמיתי (``docs/observability/asyncio-loop-safety.rst``). דחיסה היא עבודת CPU שלא
מחזירה את השליטה, ולכן לולאת הבוט עמדה לכל אורך האריזה. נמדד ב-15.11.2026 תחת
gevent, על zipball של הריפו הזה: אריזת ``webapp`` (368 קבצים, 16.8MB) עצרה את
הלולאה לשנייה שלמה, ובתהליך נפרד הפער הגדול בלולאה היה 0.03 שניות. תהליך-בן לא
יורש את ה-patching ורץ במקביל — אותו פתרון כמו Playwright ב-
``services/image_generator.py``.

**איך מריצים.** ``GitHubMenuHandler._pack_folder_from_archive`` מריץ את הקובץ הזה
כסקריפט, ``python -I <path>``: בלי ``sys.path`` של הריפו ובלי משתני ``PYTHON*``,
ולכן הוא מייבא רק מהספרייה הסטנדרטית. הקלט JSON ב-stdin, והפלט JSON ב-stdout:
``{"ok": true, "stats": {...}}``, או ``{"ok": false, "error": "unexpected_archive",
"reason": "..."}`` לארכיון במבנה לא צפוי. חריגה אחרת יוצאת עם traceback ל-stderr
וקוד יציאה שאינו אפס, כמו כל סקריפט פייתון. התקרות מגיעות בקלט ולא מוגדרות כאן,
כדי שמקור האמת יישאר ``github_menu_handler.py``. את תקרת הזמן אוכף ההורה: הוא
הורג את התהליך כשהזמן נגמר.
"""

from __future__ import annotations

import json
import stat
import sys
import zipfile


class UnexpectedArchive(Exception):
    """הארכיון אינו במבנה של zipball של GitHub כפי שאנחנו מכירים אותו."""


def is_symlink(info: zipfile.ZipInfo) -> bool:
    """האם רשומה בארכיון של GitHub היא קישור סימבולי.

    ה-zipball שומר קישור כרשומה עם ``create_system == 3`` (Unix) ו-``S_IFLNK`` בחצי
    העליון של ``external_attr``, ותוכן הרשומה הוא יעד הקישור. נמדד על zipball אמיתי
    של הריפו הזה (``node_modules/.bin/*`` יצאו ``0o120777``), וזו גם הצורה ש-
    ``git archive --format=zip`` מייצר.
    """
    return info.create_system == 3 and stat.S_ISLNK(info.external_attr >> 16)


def pack_folder(
    archive_path: str,
    folder_path: str,
    dest_path: str,
    *,
    max_files: int,
    max_file_bytes: int,
    max_total_bytes: int,
) -> dict:
    """אורז תיקייה אחת מתוך ה-zipball שבדיסק, לתוך ``dest_path``.

    כותב ישר לקובץ היעד, כך שבזיכרון יושב בכל רגע קובץ אחד לכל היותר — ו-
    ``max_file_bytes`` נבדק לפני הקריאה שלו.

    **מבנה ה-zipball (נמדד על zipball אמיתי של הריפו הזה):** תיקיית שורש אחת בשם
    ``{owner}-{repo}-{sha}/`` שכל הרשומות תחתיה, ורשומות תיקייה שמסתיימות ב-``/``.
    את השורש גוזרים מכל הרשומות ולא מהראשונה, ושורש שאינו יחיד הוא ארכיון שאיננו
    מכירים — עוצרים ולא מנחשים.

    התקרות נבדקות לפי הסדר: ``max_files`` קודם (דילוג נספר ב-``skipped_limits``),
    אחריה ``max_file_bytes`` (``skipped_large``), ואחריה ``max_total_bytes``
    (``skipped_limits``). קישורים סימבוליים לא נכללים (``skipped_symlinks``): בארכיון
    התוכן שלהם הוא רק נתיב היעד ולא הקובץ, וקישור שמצביע אל מחוץ לתיקייה ממילא לא
    היה עובד.

    מחזירה dict עם ``total_files``, ``total_bytes``, ``skipped_large``,
    ``skipped_limits`` ו-``skipped_symlinks``. ארכיון במבנה לא צפוי זורק
    ``UnexpectedArchive``.
    """
    folder = (folder_path or "").strip("/")
    zip_root = folder.split("/")[-1]
    total_files = total_bytes = skipped_large = skipped_limits = skipped_symlinks = 0

    with zipfile.ZipFile(archive_path, "r") as zin:
        infos = zin.infolist()
        roots = {info.filename.split("/", 1)[0] for info in infos}
        if len(roots) != 1:
            raise UnexpectedArchive(f"expected one root folder in the zipball, found {len(roots)}")
        # המפריד בסוף הקידומת הוא הגבול: בלעדיו "skills" היה תופס גם את "skills-old/"
        prefix = f"{roots.pop()}/{folder}/"

        with zipfile.ZipFile(dest_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
            for info in infos:
                if not info.filename.startswith(prefix) or info.is_dir():
                    continue
                if is_symlink(info):
                    skipped_symlinks += 1
                    continue
                rel = info.filename[len(prefix):]
                if any(part in ("", ".", "..") for part in rel.split("/")):
                    # git לא מתיר רכיבים כאלה בנתיב, אז זה לא ארכיון של GitHub כפי שאנחנו מכירים
                    raise UnexpectedArchive("zipball entry with an empty or dot path component")
                # התקרה נבדקת לפני הקריאה: ארכיון שהגיע לתקרה לא צריך לפרוס עוד קבצים
                if total_files >= max_files:
                    skipped_limits += 1
                    continue
                if info.file_size > max_file_bytes:
                    skipped_large += 1
                    continue
                # דילוגים בגלל תקרת הארכיון נספרים גם הם: בלי זה המשתמש מקבל ZIP חסר
                # בלי שום סימן שמשהו נחתך
                if total_bytes + info.file_size > max_total_bytes:
                    skipped_limits += 1
                    continue
                # ``file_size`` מגיע מהארכיון, אבל הוא חסם אמיתי: ``ZipExtFile`` לא מחזיר
                # יותר ממנו (``data = data[:self._left]`` ב-Lib/zipfile.py, גם ב-3.11)
                # ובודק CRC בסוף הקריאה.
                data = zin.read(info)
                out = zipfile.ZipInfo(f"{zip_root}/{rel}", date_time=info.date_time)
                # שומרים את ההרשאות כמו שהן ב-git, כולל סקריפט שמסומן להרצה
                out.create_system = info.create_system
                out.external_attr = info.external_attr
                zout.writestr(out, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
                total_files += 1
                total_bytes += len(data)

    return {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "skipped_large": skipped_large,
        "skipped_limits": skipped_limits,
        "skipped_symlinks": skipped_symlinks,
    }


def main() -> int:
    """נקודת הכניסה כסקריפט: JSON ב-stdin, JSON ב-stdout."""
    request = json.loads(sys.stdin.read())
    try:
        stats = pack_folder(
            request["archive_path"],
            request["folder"],
            request["dest_path"],
            max_files=request["max_files"],
            max_file_bytes=request["max_file_bytes"],
            max_total_bytes=request["max_total_bytes"],
        )
    except UnexpectedArchive as e:
        sys.stdout.write(json.dumps({"ok": False, "error": "unexpected_archive", "reason": str(e)}))
        return 0
    sys.stdout.write(json.dumps({"ok": True, "stats": stats}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
