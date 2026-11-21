"""עוזר לטסט: הבוט האמיתי מקבל שני עדכונים, וג'וב רץ אחריהם — איזה הקשר לוגים, ואילו תגיות Sentry, יש לכל אחד.

הטסט שמריץ אותו: ``tests/test_observability_scope_e2e.py``. בתת-תהליך מאותה סיבה כמו ``polling_health_probe.py``:
``tests/conftest.py`` מחליף את ``telegram`` ב-stubs, ומה שנבדק כאן הוא מה ש-python-telegram-bot ו-APScheduler עושים בפועל
עם ההקשר.

**התסריט — מה שקרה בפרודקשן ב-20.11.2026.** ``getUpdates`` מחזיר שני עדכונים מאותו משתמש:

1. **לחיצה על כפתור** (``callback_query`` עם ``probe_button``) — ``command`` נכרך, ושום ג'וב לא מתוזמן.
2. **הודעת טקסט בלי פקודה** — ``handle_text_message`` ← ``log_user_activity`` ← ``run_once``. עד התיקון: ה-``command`` של
   הלחיצה עוד היה בהקשר של משימת העדכונים, ו-``add_job`` של APScheduler צילם את ההקשר הזה בשביל כל הג'ובים שאחריו.

**מה אמיתי:** ה-``Application`` ש-``CodeKeeperBot`` בונה, עם כל ה-handlers שלו, ``run_polling`` של PTB, ו-APScheduler.
**מה מדומה:** טלגרם (``fake_bot_api.py``), והשליחה של Sentry — ``sentry_sdk.init`` עם transport שאוסף את האירועים לרשימה.

**מה נרשם:** ``probe_update_recorder``, handler בקבוצה ``-99`` (אחרי ``_pre_update`` של ``-100``, לפני השערים), רושם לכל
עדכון את ההקשר של structlog ושולח אירוע Sentry. ``probe_job``, ג'וב חוזר שנרשם ב-post_init, עושה אותו דבר בכל ריצה. הפרוב
עוצר אחרי שתי ריצות של ``probe_job`` מאז שהעדכון השני תזמן את הג'וב שלו (השורה ``Added job "<lambda>"`` של APScheduler),
או אחרי ``STOP_AFTER_SECONDS``.

שימוש: ``python -B observability_scope_probe.py <result.json>``
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time

from fake_bot_api import FakeBotApi, Reply, point_application_builder_at

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: תקרה לריצה כולה, כולל הייבוא של ``main``.
DEADLINE_SECONDS = 60.0
#: אחרי כמה שניות של polling הפרוב עוצר גם בלי שראה את מה שחיכה לו — כך הטסט נכשל על מה שחסר, ולא על ה-deadline.
STOP_AFTER_SECONDS = 20.0

#: המשתמש ששולח את שני העדכונים. לא אדמין: ``ADMIN_USER_IDS`` אינו מוגדר בסביבה של הפרוב.
USER_ID = 501

_CHAT = {"id": USER_ID, "type": "private"}
_FROM = {"id": USER_ID, "is_bot": False, "first_name": "Probe"}

CALLBACK_UPDATE = {
    "update_id": 1,
    "callback_query": {
        "id": "cb-1",
        "from": _FROM,
        "chat_instance": "probe",
        "data": "probe_button",
        "message": {"message_id": 10, "date": 0, "chat": _CHAT, "text": "menu"},
    },
}
TEXT_UPDATE = {
    "update_id": 2,
    "message": {"message_id": 11, "date": 0, "chat": _CHAT, "from": _FROM, "text": "hello"},
}


class _AddedJobHandler(logging.Handler):
    """מסמן כשהעדכון השני תזמן את הג'וב של ``log_user_activity`` — זה התנאי שהדליפה לג'ובים נשענה עליו."""

    def __init__(self, state: dict) -> None:
        super().__init__(logging.INFO)
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage().startswith('Added job "<lambda>"') and self.state.get("text_update_seen"):
            self.state["lambda_added_at"] = time.monotonic()


def main() -> int:
    result_path = sys.argv[1]
    report: dict = {"outcome": None, "updates": {}, "jobs": [], "sentry_events": [], "errors": []}
    state: dict = {}

    def write_report() -> None:
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

    api = FakeBotApi()
    api.script(
        "getUpdates",
        Reply(payload={"ok": True, "result": [CALLBACK_UPDATE]}),
        Reply(payload={"ok": True, "result": [TEXT_UPDATE]}),
    )
    base_url = api.start()
    sys.path.insert(0, REPO_ROOT)
    point_application_builder_at(base_url)

    import main as bot_main
    import sentry_sdk
    import structlog
    from sentry_sdk.transport import Transport
    from telegram import Update
    from telegram.ext import TypeHandler

    class _CollectingTransport(Transport):
        """אוסף את האירועים במקום לשלוח. ה-``message`` מזהה מי שלח, ו-``tags`` הן מה שנבדק."""

        def capture_envelope(self, envelope) -> None:
            event = envelope.get_event()
            if event is not None:
                report["sentry_events"].append(
                    {"message": event.get("message") or (event.get("logentry") or {}).get("message"), "tags": event.get("tags") or {}}
                )

    # אחרי ``import main``: שם ``init_sentry`` מדלג (אין DSN בסביבה), וכאן ה-client עם ה-transport שאוסף.
    sentry_sdk.init(dsn="https://public@127.0.0.1/1", transport=_CollectingTransport(), default_integrations=False)

    logging.getLogger("apscheduler.scheduler").addHandler(_AddedJobHandler(state))

    bot = bot_main.CodeKeeperBot()
    app = bot.application
    production_post_init = app.post_init

    async def probe_update_recorder(update, _context) -> None:
        update_id = update.update_id
        report["updates"][str(update_id)] = dict(structlog.contextvars.get_contextvars())
        sentry_sdk.capture_message(f"probe:update:{update_id}")
        if update_id == TEXT_UPDATE["update_id"]:
            state["text_update_seen"] = True

    def finish(outcome: str) -> None:
        report["outcome"] = outcome
        write_report()
        # יציאה בלי הכיבוי המסודר של PTB, מאותה סיבה כמו ב-``polling_health_probe.py``: הכיבוי מחכה לג'ובים שפונים למסד
        # שלא עונה, והוא אינו הנושא כאן.
        os._exit(0)

    async def probe_job(_context) -> None:
        run = len(report["jobs"])
        report["jobs"].append(
            {
                "after_text_update_job": state.get("lambda_added_at") is not None,
                "context": dict(structlog.contextvars.get_contextvars()),
            }
        )
        sentry_sdk.capture_message(f"probe:job:{run}")
        sentry_sdk.flush()
        if state.get("lambda_added_at") is not None:
            state["runs_after_lambda"] = state.get("runs_after_lambda", 0) + 1
        # שתי ריצות ולא אחת: הטיימר שתוזמן לפני ה-``add_job`` עלול לירות לפני ש-``wakeup`` מחליף אותו, ואז הריצה הראשונה
        # עוד בהקשר הישן. השנייה כבר נוצרה ב-``wakeup`` — לפני התיקון, בהקשר של העדכון השני.
        if state.get("runs_after_lambda", 0) >= 2:
            finish("done")
        elif time.monotonic() - state["started_at"] > STOP_AFTER_SECONDS:
            finish("stopped_after_timeout")

    async def post_init_then_schedule(application) -> None:
        await production_post_init(application)
        state["started_at"] = time.monotonic()
        application.job_queue.run_repeating(probe_job, interval=0.3, first=0.3)

    app.add_handler(TypeHandler(Update, probe_update_recorder), group=-99)
    app.post_init = post_init_then_schedule

    try:
        app.run_polling(drop_pending_updates=True)
        report["outcome"] = "polling_returned_on_its_own"
    except BaseException as error:  # noqa: BLE001 - הפרוב מדווח, והטסט מחליט
        report["outcome"] = f"raised {type(error).__name__}: {error}"
    write_report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
