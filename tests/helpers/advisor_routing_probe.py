"""עוזר לטסט: מריץ את הניתוב של מצב היועץ באפליקציה האמיתית של הבוט, עם python-telegram-bot האמיתי, בתת-תהליך.

הטסט שמריץ אותו, ושם גם הסביבה שהוא רץ בה: ``tests/test_advisor_routing_real_ptb.py``.

**למה תת-תהליך.** ``tests/conftest.py`` מחליף את ``telegram`` ב-stubs בכל הסוויטה, ומה שנבדק כאן יושב
בדיוק בקוד של PTB שאין ב-stubs: איזה handler בכל קבוצה תופס את העדכון, מה ``ApplicationHandlerStop``
עוצר, ``ConversationHandler`` עם ``allow_reentry`` ו-``conversation_timeout``, ו-``create_task``. כמו
``tests/helpers/main_startup_probe.py``.

**מה אמיתי ומה מדומה.**

- אמיתי: ה-``Application`` ש-``CodeKeeperBot`` בונה ב-``main.py``, עם כל ה-handlers שלו בסדר ובקבוצות של
  הפרודקשן — שער מגבלת הקצב, השיחה הראשית של ``/start`` ושמירת הקוד, וה-handler הכללי של טקסט.
  העדכונים עוברים ב-``Application.process_update``, המסלול ש-polling מזין.
- מדומה: טלגרם (Bot API מקומי על ``127.0.0.1``, דרך ``base_url``), מודל השפה
  (``advisor_service.generate_answer``), והמסד של היועץ (הפונקציות של ``advisor_store``, בזיכרון).
  ``handle_text_message`` — שמירת הקוד — מוחלף ברשם, כדי לדעת בדיוק אילו הודעות הגיעו לבוט הרגיל.

**הפלט** הוא קובץ JSON: לכל צעד, הקריאות ל-Bot API שהוא גרם, הקריאות למודל, וההודעות שהגיעו לשמירת קוד.

שימוש: ``python -B advisor_routing_probe.py <result.json> <main|idle|disabled>``
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: תקרה לריצה כולה. אם משהו נתקע, הטסט מקבל דוח עם ``outcome: deadline`` במקום תהליך תקוע.
DEADLINE_SECONDS = 60.0

_BOT_USER = {
    "id": 1,
    "is_bot": True,
    "first_name": "Probe",
    "username": "probe_bot",
    "can_join_groups": True,
    "can_read_all_group_messages": False,
    "supports_inline_queries": False,
}

_FAKE_SERVER_ERRORS: list[str] = []


class _FakeBotApi(BaseHTTPRequestHandler):
    """Bot API מקומי שרושם כל קריאה עם הפרמטרים שלה."""

    calls: list[dict] = []
    lock = threading.Lock()
    next_message_id = 5000

    def log_message(self, format, *args) -> None:  # noqa: A002 - החתימה של BaseHTTPRequestHandler
        return

    def do_POST(self) -> None:  # noqa: N802 - השם ש-BaseHTTPRequestHandler מחפש
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        method = self.path.rsplit("/", 1)[-1]
        params = {key: values[0] for key, values in parse_qs(raw.decode("utf-8")).items()}
        if "reply_markup" in params:
            params["reply_markup"] = json.loads(params["reply_markup"])
        result: object = True
        with type(self).lock:
            if method == "getMe":
                result = _BOT_USER
            elif method in ("sendMessage", "editMessageText"):
                type(self).next_message_id += 1
                result = {
                    "message_id": int(params.get("message_id") or type(self).next_message_id),
                    "date": int(time.time()),
                    "chat": {"id": int(params.get("chat_id") or 0), "type": "private"},
                    "text": params.get("text", ""),
                }
            type(self).calls.append({"method": method, "params": params, "result": result})
        body = json.dumps({"ok": True, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _FakeBotApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        _FAKE_SERVER_ERRORS.append(repr(sys.exc_info()[1]))


def _start_fake_bot_api() -> str:
    server = _FakeBotApiServer(("127.0.0.1", 0), _FakeBotApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/bot"


def _user(user_id: int) -> dict:
    return {"id": user_id, "is_bot": False, "first_name": "Dana"}


class _Updates:
    """בונה עדכונים כמו שטלגרם שולח אותם."""

    def __init__(self) -> None:
        self.update_id = 100
        self.message_id = 1

    def _next(self) -> tuple[int, int]:
        self.update_id += 1
        self.message_id += 1
        return self.update_id, self.message_id

    def text(self, user_id: int, text: str) -> dict:
        update_id, message_id = self._next()
        message = {
            "message_id": message_id,
            "date": int(time.time()),
            "chat": {"id": user_id, "type": "private"},
            "from": _user(user_id),
            "text": text,
        }
        if text.startswith("/"):
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        return {"update_id": update_id, "message": message}

    def edited(self, user_id: int, message_id: int, text: str) -> dict:
        update_id, _ = self._next()
        return {
            "update_id": update_id,
            "edited_message": {
                "message_id": message_id,
                "date": int(time.time()) - 5,
                "edit_date": int(time.time()),
                "chat": {"id": user_id, "type": "private"},
                "from": _user(user_id),
                "text": text,
            },
        }

    def click(self, user_id: int, message_id: int, data: str) -> dict:
        update_id, _ = self._next()
        return {
            "update_id": update_id,
            "callback_query": {
                "id": f"cq{update_id}",
                "from": _user(user_id),
                "chat_instance": "ci",
                "data": data,
                "message": {
                    "message_id": message_id,
                    "date": int(time.time()),
                    "chat": {"id": user_id, "type": "private"},
                    "from": _BOT_USER,
                    "text": "x",
                },
            },
        }


async def _drain() -> None:
    """מחכה למשימות הרקע של היועץ (``create_task`` עם שם ``advisor:*``) עד שלא נשארה אף אחת."""
    for _ in range(200):
        pending = [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and task.get_name().startswith("advisor:") and not task.done()
        ]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


async def _run(scenario: str, report: dict) -> None:
    sys.path.insert(0, REPO_ROOT)
    from telegram import Update
    from telegram.constants import CallbackQueryLimit
    from telegram.ext import ApplicationBuilder

    base_url = _start_fake_bot_api()
    build = ApplicationBuilder.build

    def build_against_fake_bot_api(self):
        self.base_url(base_url)
        return build(self)

    setattr(ApplicationBuilder, "build", build_against_fake_bot_api)

    import main as bot_main
    from handlers import advisor
    from i18n.strings_he import MESSAGES
    from services import advisor_service, advisor_store

    # ── הכפילים ──
    llm_calls: list[dict] = []
    text_handler_calls: list[dict] = []
    exchanges: dict[int, list[tuple[str, str]]] = {}
    limited_users = {1005}

    def get_history(user_id, now=None):
        messages = []
        for question, answer in exchanges.get(user_id, [])[-advisor_store.CONTEXT_EXCHANGES:]:
            messages += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        return messages

    def take_daily_question(user_id, now=None):
        return user_id not in limited_users

    def save_exchange(user_id, question, answer, now=None):
        exchanges.setdefault(user_id, []).append((question, answer))

    async def generate_answer(history, text):
        llm_calls.append({"text": text, "history": [m["content"] for m in history]})
        return advisor_service.Answer(text=f"תשובה ל: {text}", ok=True, follow_up_questions=["מה עם גיבוי?"])

    advisor_store.get_history = get_history
    advisor_store.take_daily_question = take_daily_question
    advisor_store.save_exchange = save_exchange
    advisor_service.generate_answer = generate_answer

    async def record_text_message(self, update, context):
        message = update.effective_message
        text_handler_calls.append({"user": update.effective_user.id, "text": message.text if message else None})

    bot_main.CodeKeeperBot.handle_text_message = record_text_message
    if scenario == "idle":
        advisor.IDLE_TIMEOUT_SECONDS = 1

    app = bot_main.CodeKeeperBot().application
    report["application"] = f"{type(app).__module__}.{type(app).__qualname__}"
    report["advisor_group_handlers"] = [
        type(handler).__name__ for handler in app.handlers.get(advisor.ADVISOR_HANDLER_GROUP, [])
    ]
    report["known_users_before"] = sorted(int(k) for k in app.user_data)
    report["welcome_text"] = advisor.WELCOME_TEXT
    report["texts"] = {
        "exit": advisor.EXIT_TEXT, "left": advisor.LEFT_TEXT, "idle": advisor.IDLE_EXIT_TEXT,
        "already_out": advisor.ALREADY_OUT_TEXT, "limit": advisor.LIMIT_TEXT,
        "unavailable": advisor.UNAVAILABLE_TEXT,
        # מה ש-/start הרגיל שולח לגולשים של הפרוב (start_command ב-conversation_handlers.py)
        "regular_welcome": MESSAGES["welcome"].format(name=_user(0)["first_name"]),
    }
    report["callback_answer_limit"] = int(CallbackQueryLimit.ANSWER_CALLBACK_QUERY_TEXT_LENGTH)

    updates = _Updates()
    steps: list[dict] = []

    async def step(name: str, update_dict: dict) -> dict:
        calls_before = len(_FakeBotApi.calls)
        llm_before, text_before = len(llm_calls), len(text_handler_calls)
        await app.process_update(Update.de_json(update_dict, app.bot))
        await _drain()
        record = {
            "name": name,
            "bot_api": [
                {"method": c["method"], "params": c["params"], "result": c["result"]}
                for c in _FakeBotApi.calls[calls_before:]
                if c["method"] not in ("sendChatAction",)
            ],
            "llm": llm_calls[llm_before:],
            "text_handler": text_handler_calls[text_before:],
        }
        steps.append(record)
        return record

    await app.initialize()
    await app.start()
    try:
        if scenario == "main":
            # גולש שמעולם לא פתח את הבוט, ונכנס ישר מהקישור t.me/<bot>?start=advisor
            report["brand_new_user_had_history"] = 1001 in exchanges
            await step("u1_deep_link", updates.text(1001, "/start advisor"))
            answered = await step("u1_question", updates.text(1001, "אני עובד עם Claude Code"))
            sent = [c for c in answered["bot_api"] if c["method"] == "sendMessage"]
            answer_message_id = sent[0]["result"]["message_id"]
            follow_up = sent[-1]
            follow_up_data = follow_up["params"]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
            await step("u1_follow_up", updates.click(1001, follow_up["result"]["message_id"], follow_up_data))
            await step("u1_edit", updates.edited(1001, answer_message_id, "ערכתי את ההודעה"))
            await step("u1_exit_button", updates.click(1001, answer_message_id, "advisor_exit"))
            await step("u1_text_after_exit", updates.text(1001, "def f(): pass"))
            await step("u1_stale_exit", updates.click(1001, answer_message_id - 1, "advisor_exit"))

            await step("u2_enter", updates.text(1002, "/advisor"))
            await step("u2_cancel", updates.text(1002, "/cancel"))
            await step("u2_text_after_cancel", updates.text(1002, "print('hi')"))

            await step("u3_enter", updates.text(1003, "/advisor"))
            await step("u3_main_menu_button", updates.text(1003, "📚 הצג את כל הקבצים שלי"))
            await step("u3_text_after_menu", updates.text(1003, "x = 1"))

            await step("u4_plain_start", updates.text(1004, "/start"))
            await step("u4_text", updates.text(1004, "שלום"))

            await step("u5_enter", updates.text(1005, "/advisor"))
            await step("u5_question_over_limit", updates.text(1005, "שאלה"))
        elif scenario == "disabled":
            # בלי ADVISOR_*: הקישור מגיע ל-/start הרגיל, ו-/advisor עונה שאינו זמין
            await step("u7_deep_link", updates.text(1007, "/start advisor"))
            await step("u7_advisor_command", updates.text(1007, "/advisor"))
            await step("u7_text", updates.text(1007, "y = 2"))
            # כפתורים בהודעות שהיועץ שלח כשעוד היה פעיל (למשל לפני שכובה בהסרת ADVISOR_API_KEY)
            await step("u7_old_exit_button", updates.click(1007, 3, "advisor_exit"))
            await step("u7_old_follow_up_button", updates.click(1007, 4, "advisor_q:gone"))
        else:
            await step("u6_enter", updates.text(1006, "/advisor"))
            # IDLE_TIMEOUT_SECONDS הוא שנייה בתרחיש הזה; הג'וב של ה-JobQueue צריך לרוץ בזמן הזה
            await asyncio.sleep(2.5)
            report["idle_calls"] = [
                {"method": c["method"], "params": c["params"]} for c in _FakeBotApi.calls if c["method"] == "sendMessage"
            ]
            await step("u6_text_after_idle", updates.text(1006, "def g(): pass"))
    finally:
        await app.stop()
        await app.shutdown()

    report["steps"] = steps
    report["exchanges"] = {str(k): v for k, v in exchanges.items()}


def main() -> int:
    result_path, scenario = sys.argv[1], sys.argv[2]
    report: dict = {"scenario": scenario}

    def write_report() -> None:
        report["fake_server_errors"] = list(_FAKE_SERVER_ERRORS)
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False)

    def on_deadline() -> None:
        report["outcome"] = "deadline"
        write_report()
        os._exit(3)

    watchdog = threading.Timer(DEADLINE_SECONDS, on_deadline)
    watchdog.daemon = True
    watchdog.start()
    try:
        asyncio.run(_run(scenario, report))
        report["outcome"] = "done"
    except BaseException:  # noqa: BLE001 - הפרוב מדווח כל מה שעלה, והטסט מחליט
        report["outcome"] = "raised"
        report["traceback"] = traceback.format_exc()[-4000:]
    write_report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
