"""עוזר לטסט: מריץ את העלייה האמיתית של הבוט, עם python-telegram-bot ו-APScheduler האמיתיים, בתת-תהליך.

הטסט שמריץ אותו, ושם גם הסביבה שהוא רץ בה: ``tests/test_main_startup_with_real_ptb.py``.

**למה תת-תהליך.** ``tests/conftest.py`` מחליף את ``telegram`` ב-stubs בכל הסוויטה, ומה שהפרוב בודק יושב
בדיוק בקוד של PTB שאין ב-stubs: ``JobQueue.start`` מפעיל את ה-jobstores של APScheduler, ו-
``Application.shutdown`` מעתיק (``deepcopy``) את ``bot_data`` כשמוגדר persistence (נקרא ב-python-telegram-bot
22.5, ``telegram/ext/_application.py``).

**מה אמיתי ומה מדומה.**

- אמיתי: ה-``Application`` ש-``CodeKeeperBot`` בונה ב-``main.py``, עם ה-post_init שלו (``setup_bot_data``),
  ו-``run_polling`` של PTB — כלומר אותו סדר עלייה וסגירה כמו בפרודקשן.
- מדומה: טלגרם. הפרוב מרים Bot API מקומי על ``127.0.0.1`` ומכוון אליו את ``ApplicationBuilder`` דרך
  ``base_url``, ולכן אין אף קריאה לטלגרם האמיתי. כתובת המסד מגיעה מהטסט, דרך ``MONGODB_URL``.
- תוספת אחת לעלייה: אחרי שה-post_init של הפרודקשן מסתיים, הפרוב מתזמן ג'וב אחד שעוצר את הבוט. ג'וב רץ רק
  אחרי ש-``JobQueue.start`` הצליח, ולכן "העלייה הושלמה" נמדד בג'וב שרץ בפועל, ולא בהיעדר חריגה.
- כמו בכל הסוויטה, בלי ה-monkey patching של gevent (``CODEBOT_DISABLE_GEVENT_PATCH``). מבנה הכשל של
  CODEKEEPER-3M, כפי שנרשם בלוגים של הפרודקשן, זהה צעד אחר צעד למה שהפרוב מקבל על הקוד שלפני התיקון.

**הפלט** הוא קובץ JSON בנתיב שהטסט מעביר: ``outcome`` (``stopped`` / ``raised`` / ``deadline``), שרשרת
החריגות כשעלתה חריגה, האם ה-post_init הסתיים והאם הג'וב רץ, ואיזו אפליקציה נבנתה — כדי שהטסט יוודא
שנבדקה האפליקציה של הפרודקשן ולא אחד ממסלולי ה-fallback של ``CodeKeeperBot``.

שימוש: ``python -B main_startup_probe.py <result.json> [<מתודת Bot API שתיכשל>]``
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: תקרה לריצה כולה, כולל הייבוא של ``main``. אם העלייה נתקעת — למשל ג'וב שלא רץ לעולם — הטסט מקבל
#: דוח עם ``outcome: deadline`` במקום תהליך תקוע.
DEADLINE_SECONDS = 60.0

#: כמה זמן אחרי סוף ה-post_init רץ הג'וב שעוצר את הבוט.
STOP_JOB_DELAY_SECONDS = 0.5

_BOT_USER = {
    "id": 1,
    "is_bot": True,
    "first_name": "Probe",
    "username": "probe_bot",
    "can_join_groups": True,
    "can_read_all_group_messages": False,
    "supports_inline_queries": False,
}

#: שגיאות של השרת המדומה עצמו. ריקה בריצה תקינה, והטסט בודק את זה: תקלה בתשתית הבדיקה הייתה
#: מגיעה לבוט כשגיאת רשת, ונראית כמו בדיוק מה שהטסט מחפש.
_FAKE_SERVER_ERRORS: list[str] = []


class _FakeBotApi(BaseHTTPRequestHandler):
    """Bot API מקומי: ``ok`` לכל מתודה, ו-502 למתודה שהטסט ביקש להכשיל."""

    failing_method: str | None = None
    calls: list[str] = []

    def log_message(self, format, *args) -> None:  # noqa: A002 - החתימה של BaseHTTPRequestHandler
        # בלי שורה ב-stderr לכל בקשה. הקריאות נרשמות ב-``calls`` ומגיעות לדוח.
        return

    def do_POST(self) -> None:  # noqa: N802 - השם ש-BaseHTTPRequestHandler מחפש
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        method = self.path.rsplit("/", 1)[-1]
        type(self).calls.append(method)
        status = 200
        payload: dict[str, object] = {"ok": True, "result": True}
        if method == type(self).failing_method:
            # תקלה חולפת בצד של טלגרם. PTB 22.5 ממפה 502 ל-``NetworkError`` עם ה-description
            # (``telegram/request/_baserequest.py``).
            status = 502
            payload = {"ok": False, "error_code": 502, "description": "Bad Gateway"}
        elif method == "getMe":
            payload["result"] = _BOT_USER
        elif method == "getUpdates":
            # long-poll קצר, כדי שלולאת ה-polling לא תסתובב על ריק.
            time.sleep(0.2)
            payload["result"] = []
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _FakeBotApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionResetError)):
            # PTB סוגר את חיבור ה-long-poll הפתוח כשהבוט נעצר, והתשובה שהשרת המדומה עוד כתב נופלת על
            # צינור סגור. זה חלק רגיל מהסגירה, ולא תקלה בשרת.
            return
        _FAKE_SERVER_ERRORS.append(repr(error))


def _start_fake_bot_api() -> str:
    server = _FakeBotApiServer(("127.0.0.1", 0), _FakeBotApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/bot"


def _exception_chain(error: BaseException | None) -> list[dict]:
    """החריגה ומה שהיא הסתירה, באותו סדר שפייתון מדפיס: ``__cause__``, ובלעדיו ``__context__``."""
    chain: list[dict] = []
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        chain.append(
            {
                "type": f"{type(error).__module__}.{type(error).__qualname__}",
                "message": str(error)[:600],
                "frames": [
                    f"{os.path.basename(frame.filename)}:{frame.name}"
                    for frame in traceback.extract_tb(error.__traceback__)
                ],
            }
        )
        if error.__cause__ is not None:
            error = error.__cause__
        elif error.__suppress_context__:
            error = None
        else:
            error = error.__context__
    return chain


def _qualified_name(obj) -> str | None:
    if obj is None:
        return None
    return f"{getattr(obj, '__module__', '?')}.{getattr(obj, '__qualname__', type(obj).__qualname__)}"


def main() -> int:
    result_path = sys.argv[1]
    _FakeBotApi.failing_method = sys.argv[2] if len(sys.argv) > 2 else None
    report: dict = {"post_init_completed": False, "job_queue_ran_a_job": False}

    def write_report() -> None:
        report["bot_api_calls"] = list(_FakeBotApi.calls)
        report["fake_server_errors"] = list(_FAKE_SERVER_ERRORS)
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False)

    def on_deadline() -> None:
        report["outcome"] = "deadline"
        write_report()
        # יציאה מיידית מהחוט של הטיימר: החוט הראשי תקוע, ואין דרך מסודרת להוציא אותו.
        os._exit(3)

    watchdog = threading.Timer(DEADLINE_SECONDS, on_deadline)
    watchdog.daemon = True
    watchdog.start()

    base_url = _start_fake_bot_api()

    sys.path.insert(0, REPO_ROOT)
    from telegram.ext import ApplicationBuilder

    build = ApplicationBuilder.build

    def build_against_fake_bot_api(self):
        # ``CodeKeeperBot`` בונה את האפליקציה בעצמו ואין לו פרמטר לכתובת ה-API, ולכן הכתובת נכנסת כאן,
        # רגע לפני הבנייה. כל שאר התצורה — token, ‏defaults, ‏persistence, ‏post_init — היא של main.py.
        self.base_url(base_url)
        return build(self)

    setattr(ApplicationBuilder, "build", build_against_fake_bot_api)

    import main as bot_main

    app = bot_main.CodeKeeperBot().application
    production_post_init = getattr(app, "post_init", None)
    report["application"] = _qualified_name(type(app))
    report["post_init"] = _qualified_name(production_post_init)
    persistence = getattr(app, "persistence", None)
    report["persistence"] = None if persistence is None else type(persistence).__name__

    async def stop_after_first_job(context) -> None:
        report["job_queue_ran_a_job"] = True
        context.application.stop_running()

    async def post_init_then_schedule_stop(application) -> None:
        if production_post_init is not None:
            await production_post_init(application)
        report["post_init_completed"] = True
        # ``misfire_grace_time=None``: הג'וב ירוץ גם אם ``JobQueue.start`` מתעכב. ברירת המחדל של APScheduler
        # 3.11.3 היא שנייה אחת, ואחריה ג'וב שאיחר מדולג בשקט — והפרוב היה מחכה עד ה-deadline.
        application.job_queue.run_once(
            stop_after_first_job,
            when=STOP_JOB_DELAY_SECONDS,
            job_kwargs={"misfire_grace_time": None},
        )

    app.post_init = post_init_then_schedule_stop

    try:
        # ``drop_pending_updates=True`` כמו ב-``main()``. בלעדיו ובלי webhook, PTB 22.5 עדיין קורא ל-
        # ``deleteWebhook`` בשלב ה-bootstrap (``Updater._bootstrap``), כך שהמסלול זהה.
        app.run_polling(drop_pending_updates=True)
        report["outcome"] = "stopped"
    except BaseException as error:  # noqa: BLE001 - הפרוב מדווח כל מה שעלה מהעלייה, והטסט מחליט
        report["outcome"] = "raised"
        report["exception"] = _exception_chain(error)
    write_report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
