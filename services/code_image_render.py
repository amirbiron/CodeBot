"""יצירת תמונת קוד (PNG) בתהליך נפרד, כדי שהעבודה לא תעצור את לולאת הבוט.

**למה תהליך.** ``CodeImageGenerator.generate_image`` נמשך שניות, וגדל עם אורך הקוד; המספרים, ומתי נמדדו, ב-``docs/whats-new/2026-11.rst``.
תהליך הבוט מריץ gevent ``monkey.patch_all()``, ושם ``asyncio.to_thread`` הוא גרינלט באותו OS thread: עבודת CPU בתוך התהליך — בניית
ה-HTML, העיבוד של צילום המסך ב-PIL, ובמסלול החלופי של PIL כל הציור — עוצרת את הלולאה לכל אורכה
(``docs/observability/asyncio-loop-safety.rst``). כאן היא רצה בתהליך נפרד, והקורא רק מחכה לו: ``subprocess`` תחת gevent ממתין בלי
לחסום את הלולאה, כמו ``services/github_zip_packer.py``. גם הזיכרון של הרינדור נשאר בתהליך הנפרד ומשתחרר איתו.

**הפרוטוקול.** בקשה כ-JSON ב-stdin, עם השדות של ``build_request``. בהצלחה ה-PNG ב-stdout וקוד יציאה ``0``. בכשל קוד יציאה ``2``, ושורה
אחרונה ב-stderr שהיא JSON עם ``error_type`` ו-``message`` (לפניה ה-traceback).

**ערוץ הכשל.** ``render_png`` זורקת ולא מחזירה ערך ריק: ``CodeImageRenderError`` עם ההודעה של החריגה שבתהליך — למשל
``Code too large (max 100KB)`` — ו-``ImportError`` כשחסרה שם ספרייה, כמו כשהיצירה רצה בתוך תהליך הבוט.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_WORKER = Path(__file__).resolve()
_REPO_ROOT = _WORKER.parent.parent

#: תקרה לתהליך כולו. מעל ה-``timeout=60`` שבו ``CodeImageGenerator`` מריץ את Playwright, כדי שהנפילה שלו ל-PIL תספיק לרוץ.
RENDER_TIMEOUT_SECONDS = 90.0

#: כמה זמן בקשה מחכה לתור לפני שהיא מוותרת (``CodeImageRenderBusy``), כך שהמתנה לא נמשכת בלי סוף כשתהליך אחר נתקע.
SLOT_WAIT_SECONDS = 30.0

#: כמה רינדורים רצים יחד: אחד, כמו שרצו עד שהעבודה עברה לתהליך — הבוט מעבד עדכון אחד בכל פעם (אין ``concurrent_updates``),
#: והיצירה חסמה אותו. כל רינדור מרים תהליך פייתון ודפדפן, ולכן רוחב גדול יותר צריך תקציב זיכרון שנמדד, לא מספר שנבחר.
#: ``threading`` ולא ``asyncio``: ההמתנה רצה ב-``asyncio.to_thread``. נוצר בייבוא, ו-``main.py`` מייבא את הבוט אחרי
#: ``monkey.patch_all()``, ולכן בבוט זה סמפור של gevent, וההמתנה עליו לא חוסמת את הלולאה.
_RENDER_SLOTS = threading.BoundedSemaphore(1)


class CodeImageRenderError(RuntimeError):
    """התהליך לא החזיר PNG. ההודעה היא של החריגה שבתהליך, כשהיא ידועה."""


class CodeImageRenderBusy(CodeImageRenderError):
    """רינדור אחר תפס את התור יותר מ-``SLOT_WAIT_SECONDS``."""


class CodeImageRenderTimeout(CodeImageRenderError):
    """התהליך עבר את ``RENDER_TIMEOUT_SECONDS`` ונהרג, יחד עם התהליכים שהוא הריץ."""


def build_request(
    *,
    code: str,
    language: str,
    filename: str,
    style: str,
    theme: str,
    font_family: str,
    width: int,
    note: Optional[str],
) -> Dict[str, Any]:
    """הבקשה לתהליך — הארגומנטים של ``CodeImageGenerator`` ושל ``generate_image``."""
    return {
        "code": code,
        "language": language,
        "filename": filename,
        "style": style,
        "theme": theme,
        "font_family": font_family,
        "width": int(width),
        "note": note,
    }


def render_png(request: Dict[str, Any]) -> bytes:
    """יוצר את ה-PNG בתהליך נפרד ומחזיר את הבייטים. פונקציה חוסמת — הקורא בבוט מריץ אותה ב-``asyncio.to_thread``."""
    if not _RENDER_SLOTS.acquire(timeout=SLOT_WAIT_SECONDS):
        raise CodeImageRenderBusy("⏳ יצירת תמונה אחרת עדיין רצה — נסה שוב בעוד רגע.")
    try:
        return _run_worker(request)
    finally:
        _RENDER_SLOTS.release()


def _run_worker(request: Dict[str, Any]) -> bytes:
    payload = json.dumps(request).encode("utf-8")
    # ``-I``: בלי משתני ``PYTHON*`` ובלי התיקייה של הסקריפט ב-``sys.path`` — ה-worker מוסיף את שורש הריפו בעצמו. ``-B`` כי ``-I``
    # מתעלם מ-``PYTHONDONTWRITEBYTECODE``. ``start_new_session``: קבוצת תהליכים משלו, כדי שבחריגה מהזמן ייהרגו גם Playwright
    # והדפדפן שהוא הריץ, ולא רק הוא.
    proc = subprocess.Popen(
        [sys.executable, "-I", "-B", str(_WORKER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(payload, timeout=RENDER_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        proc.communicate()
        raise CodeImageRenderTimeout(f"code image render exceeded {RENDER_TIMEOUT_SECONDS:g}s")
    err_text = err.decode("utf-8", "replace")
    if proc.returncode != 0:
        info = _error_line(err_text)
        logger.warning("code_image_render_failed returncode=%s error_type=%s", proc.returncode, info.get("error_type"))
        message = str(info.get("message") or f"code image render exited with {proc.returncode}")
        if info.get("error_type") in ("ImportError", "ModuleNotFoundError"):
            raise ImportError(message)
        raise CodeImageRenderError(message)
    if err_text.strip():
        # אזהרות של ``CodeImageGenerator`` — למשל נפילה מ-Playwright ל-PIL — היו נרשמות בלוג של הבוט כשהיצירה רצה בתוכו
        logger.warning("code_image_render_stderr %s", err_text.strip()[-2000:])
    if not out.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CodeImageRenderError("code image render returned no PNG")
    return out


def _kill_process_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        # הקבוצה כבר יצאה בין ה-timeout להריגה — אין מה להרוג
        pass


def _error_line(stderr_text: str) -> Dict[str, Any]:
    """שורת ה-JSON האחרונה שה-worker כותב ב-stderr בכשל, או ``{}`` כשאין כזו (למשל כשהתהליך נהרג מבחוץ)."""
    for line in reversed(stderr_text.strip().splitlines()):
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _worker_main() -> int:
    """הכניסה של התהליך: בקשה מ-stdin, PNG ל-stdout."""
    try:
        request = json.loads(sys.stdin.buffer.read())
        sys.path.insert(0, str(_REPO_ROOT))
        from services.image_generator import CodeImageGenerator

        generator = CodeImageGenerator(style=request["style"], theme=request["theme"], font_family=request["font_family"])
        try:
            png = generator.generate_image(
                code=request["code"],
                language=request["language"],
                filename=request["filename"],
                max_width=int(request["width"]),
                note=request["note"],
            )
        finally:
            # כמו כל מי שבונה ``CodeImageGenerator`` (``docs/troubleshooting.rst``)
            generator.cleanup()
    except BaseException as error:  # noqa: BLE001 - גבול התהליך: כל כשל מדווח לקורא ביציאה 2
        sys.stderr.write(traceback.format_exc())
        sys.stderr.write("\n" + json.dumps({"error_type": type(error).__name__, "message": str(error)[:1000]}) + "\n")
        sys.stderr.flush()
        return 2
    sys.stdout.buffer.write(png)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(_worker_main())
