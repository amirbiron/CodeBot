"""עוזר לטסט: הבוט האמיתי מול תקלה של getUpdates — מה נרשם בלוג, ואילו התראות יוצאות.

הטסט שמריץ אותו, ושם גם הסביבה: ``tests/test_telegram_polling_health_e2e.py``. בתת-תהליך מאותה סיבה כמו
``main_startup_probe.py``: ``tests/conftest.py`` מחליף את ``telegram`` ב-stubs, ומה שנבדק כאן הוא המסלול של
python-telegram-bot עצמו — ``run_polling`` ← ``network_retry_loop`` ← ``process_error`` ← ``error_handler``.

**מה אמיתי:** ה-``Application`` ש-``CodeKeeperBot`` בונה, עם ה-post_init שלו (``setup_bot_data``), בקשת ה-``getUpdates``
שלו ו-``error_handler`` שלו; ו-``run_polling`` של PTB. **מה מדומה:** טלגרם (``fake_bot_api.py``), ושליחת ההתראות —
``internal_alerts.emit_internal_alert`` מוחלף ברשימה, כדי שלא תצא הודעה לשום מקום.

**התסריט.** ``getUpdates`` מחזיר 502 שלוש פעמים, אחר כך 400, ואז מצליח. PTB 22.5 ממתין בין כישלונות 1, 1.5, 2.25 ו-3.375
שניות (``network_retry_loop``), כלומר כשמונה שניות בלי הצלחה. הסף שהטסט קובע (``TELEGRAM_POLLING_STALL_ALERT_SECS``)
קצר מזה, ולכן ההשבתה צריכה להתריע, ואחרי ההצלחה — לדווח חזרה. במקביל רצים שני כשלים מחוץ ל-polling: ג'וב שזורק
``NetworkError``, ומשימה של ``application.create_task`` בלי ``update`` שזורקת ``NetworkError`` (כמו ``_milestones_job``).

**הפלט:** קובץ JSON — הרשומות ש-``error_handler`` כתב (רמה והודעה), כל ההתראות שנשלחו ל-``emit_internal_alert``, האם הבקשה
רשמה הצלחה, והג'וב שנרשם. הפרוב כותב אותו ויוצא כשהגיעה התראת החזרה (``outcome: done``), או אחרי ``STOP_AFTER_SECONDS``
(``stopped_after_timeout``) — מה שקודם.

שימוש: ``python -B polling_health_probe.py <result.json>``
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time

from fake_bot_api import BAD_GATEWAY_PAYLOAD, FakeBotApi, Reply, point_application_builder_at

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: תקרה לריצה כולה, כולל הייבוא של ``main``.
DEADLINE_SECONDS = 60.0

#: אחרי כמה שניות של polling הפרוב עוצר גם בלי התראת חזרה — פי שניים בערך מהתסריט. כך קוד שלא מתריע נכשל בטסט על
#: ההתראות, ולא על ה-deadline.
STOP_AFTER_SECONDS = 20.0


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def main() -> int:
    result_path = sys.argv[1]
    report: dict = {"outcome": None}
    alerts: list[dict] = []
    handler_records = _ListHandler()

    api = FakeBotApi()
    api.script(
        "getUpdates",
        Reply(status=502, payload=BAD_GATEWAY_PAYLOAD),
        Reply(status=502, payload=BAD_GATEWAY_PAYLOAD),
        Reply(status=502, payload=BAD_GATEWAY_PAYLOAD),
        Reply(status=400, payload={"ok": False, "error_code": 400, "description": "Bad Request: wrong offset"}),
    )

    def write_report() -> None:
        report["error_handler_records"] = [
            {"level": rec.levelname, "message": rec.getMessage(), "has_traceback": rec.exc_info is not None}
            for rec in handler_records.records
            if rec.getMessage().startswith(("telegram polling:", "שגיאה:"))
        ]
        # כל מה שנשלח ל-``emit_internal_alert``, גם התראות שאינן של ה-polling (למשל של העלייה). הטסט מסנן לפי שם.
        report["alerts"] = list(alerts)
        report["get_updates_calls"] = api.calls.count("getUpdates")
        report["fake_server_errors"] = list(api.server_errors)
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False)

    def on_deadline() -> None:
        report["outcome"] = "deadline"
        write_report()
        os._exit(3)

    watchdog = threading.Timer(DEADLINE_SECONDS, on_deadline)
    watchdog.daemon = True
    watchdog.start()

    base_url = api.start()
    sys.path.insert(0, REPO_ROOT)
    point_application_builder_at(base_url)

    import internal_alerts

    def capture_alert(name, severity="info", summary="", **details):
        alerts.append({"name": name, "severity": severity, "summary": summary, **details})

    internal_alerts.emit_internal_alert = capture_alert

    import main as bot_main
    from services import telegram_polling_health as tph
    from telegram.error import NetworkError

    logging.getLogger(bot_main.__name__).addHandler(handler_records)

    bot = bot_main.CodeKeeperBot()
    app = bot.application
    production_post_init = app.post_init
    polling_alert_names = {tph.ALERT_STALLED, tph.ALERT_RECOVERED}
    outside_polling = {"job": False, "task": False}

    async def job_that_fails(_context) -> None:
        outside_polling["job"] = True
        raise NetworkError("probe: a job failed to reach Telegram")

    async def task_that_fails() -> None:
        outside_polling["task"] = True
        raise NetworkError("probe: a background task failed to reach Telegram")

    async def start_task_without_update(context) -> None:
        # כמו ``_milestones_job`` ב-``main.py``: ג'וב שמפעיל משימת רקע, בלי ``update``.
        context.application.create_task(task_that_fails())

    # נכתב ב-post_init, לפני שהג'וב הראשון של ``stop_when_done`` רץ.
    started: dict[str, float] = {}

    def finish(outcome: str) -> None:
        report["outcome"] = outcome
        # ``getattr``: על קוד בלי המוניטור הפרוב עדיין כותב דוח, והטסט נכשל על ההתנהגות ולא על חוסר במאפיין.
        monitor = getattr(bot, "polling_health", None)
        report["heartbeat_recorded"] = monitor is not None and monitor._last_success_at is not None
        write_report()
        # יציאה בלי הכיבוי המסודר של PTB: הוא אינו הנושא כאן (``main_startup_probe.py`` בודק אותו), והוא מחכה לכל ג'וב
        # שרץ (``JobQueue.stop(wait=True)``). מול מסד שלא עונה, ``pending_job_triggers`` — שמתחיל כעשר שניות אחרי
        # העלייה — מחזיק את הכיבוי עד שהניסיונות החוזרים שלו למסד נגמרים, וזה היה הופך את הטסט לתלוי בתזמון.
        os._exit(0)

    async def stop_when_done(_context) -> None:
        names = [alert["name"] for alert in alerts if alert["name"] in polling_alert_names]
        if tph.ALERT_RECOVERED in names and all(outside_polling.values()):
            finish("done")
        elif time.monotonic() - started["at"] > STOP_AFTER_SECONDS:
            finish("stopped_after_timeout")

    async def post_init_then_schedule(application) -> None:
        await production_post_init(application)
        started["at"] = time.monotonic()
        jobs = application.job_queue.get_jobs_by_name(tph.WATCHDOG_JOB_NAME)
        report["watchdog_jobs"] = [
            {"name": job.name, "interval_seconds": job.job.trigger.interval.total_seconds()} for job in jobs
        ]
        application.job_queue.run_once(job_that_fails, when=0.5, job_kwargs={"misfire_grace_time": None})
        application.job_queue.run_once(start_task_without_update, when=0.7, job_kwargs={"misfire_grace_time": None})
        application.job_queue.run_repeating(stop_when_done, interval=0.5, first=0.5)

    app.post_init = post_init_then_schedule

    try:
        app.run_polling(drop_pending_updates=True)
        # ``finish`` יוצא מהתהליך, ולכן הגעה לכאן פירושה שה-polling נעצר בלי שהפרוב עצר אותו.
        report["outcome"] = "polling_returned_on_its_own"
    except BaseException as error:  # noqa: BLE001 - הפרוב מדווח, והטסט מחליט
        report["outcome"] = f"raised {type(error).__name__}: {error}"
    write_report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
