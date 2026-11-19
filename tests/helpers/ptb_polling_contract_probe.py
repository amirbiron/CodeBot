"""עוזר לטסט: מקבע מול python-telegram-bot האמיתי את העובדות ש-``services/telegram_polling_health.py`` נשען עליהן.

הטסט שמריץ אותו: ``tests/test_telegram_polling_ptb_contract.py``. בתת-תהליך, כי ``tests/conftest.py`` מחליף את
``telegram`` ב-stubs בכל הסוויטה — ושם, למשל, ``BadRequest`` לא תמיד ירשה מ-``NetworkError``.

מה נבדק, וכל בדיקה כותבת מפתח משלה לדוח:

- ``retry_loop`` — אילו חריגות ``network_retry_loop`` מעביר ל-callback של השגיאות. ‏``TimedOut`` לא: זו הסיבה שההתראה על
  השבתה נשענת על heartbeat ולא על ספירת שגיאות ב-``error_handler``.
- ``network_error_subclasses`` — הסיווג מבחין ב-``NetworkError`` לפי הטיפוס המדויק; תת-מחלקה חדשה בשדרוג צריכה החלטה.
- ``request_vs_builder_default`` — הבקשה שהבוט מעביר ל-``get_updates_request`` זהה למה שה-builder היה בונה בעצמו.
- ``heartbeat`` — הבקשה מדווחת על תשובה תקינה של Bot API, לא על 502 ולא על 2xx שאינו תשובה תקינה (HTML, JSON בלי
  ``result``), וכשל ברישום ההצלחה לא נוגע בתשובה ש-PTB מקבל.
- ``ptb_error_logs`` — רשומות ERROR של ה-loggers של PTB עצמו: על 5xx עם גוף HTML אין (אחרת Sentry פותח issue לפני
  הסיווג), על כל תשובה אחרת יש — בהשוואה לבקשה של PTB, שמראה שהשורה נכתבת בלעדינו.
- ``classification`` — :func:`is_transient_polling_error` על חריגות שהספרייה עצמה זרקה מול Bot API מדומה, ולא על
  חריגות שנבנו ביד.

שימוש: ``python -B ptb_polling_contract_probe.py <result.json>``
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys

from fake_bot_api import BAD_GATEWAY_PAYLOAD, CLOSE, FakeBotApi, Reply

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from telegram import Bot  # noqa: E402
from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut  # noqa: E402
from telegram.ext import ApplicationBuilder, CallbackContext, Job  # noqa: E402
from telegram.ext._utils.networkloop import network_retry_loop  # noqa: E402
from telegram.request import HTTPXRequest  # noqa: E402

from services import telegram_polling_health as tph  # noqa: E402

TOKEN = "0:probe"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _port_nobody_listens_on() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _retry_loop_passes() -> dict[str, bool]:
    """לכל חריגה: האם ``network_retry_loop`` קרא ל-``on_err_cb`` כשהפעולה זרקה אותה פעם אחת."""
    passed: dict[str, bool] = {}
    for name, error in {
        "NetworkError": NetworkError("Bad Gateway"),
        "TimedOut": TimedOut(),
        "RetryAfter": RetryAfter(0),
    }.items():
        calls = {"action": 0, "on_err": 0}

        async def action(error: TelegramError = error, calls: dict[str, int] = calls) -> None:
            calls["action"] += 1
            raise error

        def on_err(_exc: TelegramError, calls: dict[str, int] = calls) -> None:
            calls["on_err"] += 1

        # ``is_running`` אמת עד שהפעולה רצה פעם אחת: הלולאה מריצה אותה, מטפלת בחריגה, ויוצאת.
        await network_retry_loop(
            action_cb=action,
            on_err_cb=on_err,
            description="probe",
            interval=0,
            is_running=lambda calls=calls: calls["action"] == 0,
            max_retries=-1,
            repeat_on_success=True,
        )
        passed[name] = calls["on_err"] > 0
    return passed


def _request_vs_builder_default() -> dict:
    default_request = ApplicationBuilder().token(TOKEN).build().bot._request[0]
    ours = tph.PollingHeartbeatRequest(lambda: None, connection_pool_size=1)
    installed = ApplicationBuilder().token(TOKEN).get_updates_request(ours).build().bot._request[0]

    def shape(request: HTTPXRequest) -> dict:
        kwargs = request._client_kwargs
        return {
            "class_is_httpx_request": isinstance(request, HTTPXRequest),
            "timeout": repr(kwargs["timeout"]),
            "limits": repr(kwargs["limits"]),
            "proxy": repr(kwargs["proxy"]),
            "transport": repr(kwargs["transport"]),
            "http1": kwargs["http1"],
            "http2": kwargs["http2"],
            "http_version": request.http_version,
            "read_timeout": request.read_timeout,
        }

    return {"default": shape(default_request), "ours": shape(ours), "installed_is_ours": installed is ours}


async def _heartbeat(api: FakeBotApi, base_url: str, log: _ListHandler) -> dict:
    successes: list[int] = []
    request = tph.PollingHeartbeatRequest(lambda: successes.append(1), connection_pool_size=1)
    bot = Bot(TOKEN, base_url=base_url, get_updates_request=request)
    result: dict = {}
    async with bot:
        api.script("getUpdates", Reply(payload={"ok": True, "result": []}))
        await bot.get_updates(timeout=0)
        result["after_200"] = len(successes)

        api.script("getUpdates", Reply(status=502, payload=BAD_GATEWAY_PAYLOAD))
        try:
            await bot.get_updates(timeout=0)
            result["502_raised"] = None
        except NetworkError as exc:
            result["502_raised"] = type(exc).__name__
        result["after_502"] = len(successes)

        # 2xx שאינו תשובה תקינה של Bot API: PTB לא מוסר עדכונים, ולכן גם לא heartbeat. לכל מקרה — מה PTB עשה, והאם נרשם.
        result["malformed_2xx"] = {}
        for name, reply in {
            "html_body": Reply(raw=b"<html>proxy error</html>", content_type="text/html"),
            "json_without_result": Reply(payload={"ok": True}),
            "ok_false": Reply(payload={"ok": False, "description": "not ok"}),
            "ok_false_with_a_result": Reply(payload={"ok": False, "result": []}),
            "result_not_a_list": Reply(payload={"ok": True, "result": {"update_id": 1}}),
            "json_array": Reply(payload=[]),
        }.items():
            before = len(successes)
            api.script("getUpdates", reply)
            try:
                await bot.get_updates(timeout=0)
                ptb = "returned"
            except Exception as exc:  # noqa: BLE001 - הפרוב מדווח, והטסט מחליט
                ptb = f"raised {type(exc).__name__}"
            result["malformed_2xx"][name] = {"ptb": ptb, "heartbeat": len(successes) > before}

    # כשל ברישום ההצלחה: התשובה חוזרת ל-PTB כרגיל, והכשל נרשם עם traceback.
    def broken_on_success() -> None:
        raise RuntimeError("heartbeat bookkeeping is broken")

    broken = tph.PollingHeartbeatRequest(broken_on_success, connection_pool_size=1)
    bot = Bot(TOKEN, base_url=base_url, get_updates_request=broken)
    async with bot:
        update = {"update_id": 7, "message": {"message_id": 1, "date": 0, "chat": {"id": 1, "type": "private"}, "text": "hi"}}
        api.script("getUpdates", Reply(payload={"ok": True, "result": [update]}))
        try:
            updates = await bot.get_updates(timeout=0)
            result["broken_on_success_returned"] = [u.update_id for u in updates]
        except Exception as exc:  # noqa: BLE001 - הפרוב מדווח, והטסט מחליט
            result["broken_on_success_returned"] = f"raised {type(exc).__name__}: {exc}"
    result["broken_on_success_logged"] = [
        {"level": rec.levelname, "message": rec.getMessage(), "has_traceback": rec.exc_info is not None}
        for rec in log.records
        if rec.name == tph.__name__
    ]
    return result


async def _ptb_error_logs(api: FakeBotApi, base_url: str) -> dict:
    """אילו רשומות ERROR ה-loggers של PTB עצמו (``telegram.*``) כותבים על תשובה, דרך הבקשה שלנו ודרך הבקשה של PTB.

    רשומה כזו נפתחת כ-issue ב-Sentry (``LoggingIntegration`` עם ``event_level=ERROR``) בלי קשר לסיווג שאחריה, ולכן אותו
    502 עם גוף HTML שהסיווג מוריד ל-warning לא יכול להשאיר אותה. הבקשה של PTB היא הבקרה: היא מראה שהשורה נכתבת בלעדינו,
    כלומר שהבדיקה מסוגלת לראות אותה.
    """
    captured = _ListHandler()
    ptb_logger = logging.getLogger("telegram")
    ptb_logger.addHandler(captured)

    async def run(request: HTTPXRequest, reply: Reply) -> dict:
        captured.records.clear()
        api.script("getUpdates", reply)
        bot = Bot(TOKEN, base_url=base_url, get_updates_request=request)
        raised: dict = {"type": None}
        try:
            await bot.get_updates(timeout=0)
        except Exception as exc:  # noqa: BLE001 - הפרוב מדווח, והטסט מחליט
            # השרשרת עד שתי רמות: ה-``NetworkError``, הסיבה שלו (``TelegramError`` של הפענוח) והסיבה שלה — כדי ש"זהה ל-PTB"
            # ייבדק גם בתוך השרשרת, ולא רק בהודעה שבראשה.
            cause = exc.__cause__
            cause_of_cause = None if cause is None else cause.__cause__
            raised = {
                "type": f"{type(exc).__module__}.{type(exc).__qualname__}",
                "message": str(exc)[:300],
                "cause": None if cause is None else f"{type(cause).__module__}.{type(cause).__qualname__}",
                "cause_message": None if cause is None else str(cause),
                "cause_of_cause": None
                if cause_of_cause is None
                else f"{type(cause_of_cause).__module__}.{type(cause_of_cause).__qualname__}",
            }
        finally:
            await request.shutdown()
        errors = [
            {"logger": rec.name, "level": rec.levelname, "message": rec.getMessage()[:200]}
            for rec in captured.records
            if rec.levelno >= logging.ERROR and rec.name.startswith("telegram")
        ]
        return {"raised": raised, "ptb_error_records": errors}

    def ours() -> HTTPXRequest:
        return tph.PollingHeartbeatRequest(lambda: None, connection_pool_size=1)

    def html(status: int) -> Reply:
        return Reply(status=status, raw=b"<html>Bad Gateway</html>", content_type="text/html")

    async def stale_status_is_not_reused() -> dict:
        # אחרי 502 באותו task, פענוח שלא קדם לו ``do_request`` משלו חוזר לפענוח של PTB, עם השורה שלו — הסטטוס לא נשאר.
        request = ours()
        await run(request, html(502))
        captured.records.clear()
        try:
            request.parse_json_payload(b"<html>not json</html>")
            raised = None
        except Exception as exc:  # noqa: BLE001
            raised = type(exc).__name__
        errors = [rec.name for rec in captured.records if rec.levelno >= logging.ERROR]
        return {"raised": raised, "ptb_error_loggers": errors}

    try:
        return {
            "stale_status": await stale_status_is_not_reused(),
            "502_html_ours": await run(ours(), html(502)),
            "502_html_ptb": await run(HTTPXRequest(connection_pool_size=1), html(502)),
            "503_html_ours": await run(ours(), html(503)),
            "502_json_ours": await run(ours(), Reply(status=502, payload=BAD_GATEWAY_PAYLOAD)),
            "502_json_ptb": await run(HTTPXRequest(connection_pool_size=1), Reply(status=502, payload=BAD_GATEWAY_PAYLOAD)),
            "200_html_ours": await run(ours(), html(200)),
            "400_html_ours": await run(ours(), html(400)),
        }
    finally:
        ptb_logger.removeHandler(captured)


class _BrokenTransport(HTTPXRequest):
    """שכבת HTTP עם באג: PTB עוטף את החריגה ב-``NetworkError("Unknown error in HTTP implementation")``."""

    async def do_request(self, *args, **kwargs):
        raise RuntimeError("bug in the HTTP layer")


async def _classification(api: FakeBotApi, base_url: str) -> dict:
    application = ApplicationBuilder().token(TOKEN).build()

    async def raised_by(request: HTTPXRequest, url: str, *script) -> BaseException:
        if script:
            api.script("getUpdates", *script)
        bot = Bot(TOKEN, base_url=url, get_updates_request=request)
        # בלי ``initialize``: הוא קורא ל-``getMe`` דרך הבקשה השנייה, ולא נוגע במה שנבדק כאן.
        try:
            await bot.get_updates(timeout=0)
        except Exception as exc:  # noqa: BLE001
            return exc
        finally:
            await request.shutdown()
        raise AssertionError("get_updates did not raise")

    def plain(read_timeout: float = 5.0) -> HTTPXRequest:
        return HTTPXRequest(connection_pool_size=1, read_timeout=read_timeout)

    errors = {
        "502_json": await raised_by(plain(), base_url, Reply(status=502, payload=BAD_GATEWAY_PAYLOAD)),
        "502_html": await raised_by(
            plain(), base_url, Reply(status=502, raw=b"<html>Bad Gateway</html>", content_type="text/html")
        ),
        "500_json": await raised_by(
            plain(), base_url, Reply(status=500, payload={"ok": False, "error_code": 500, "description": "Internal"})
        ),
        "connection_refused": await raised_by(plain(), f"http://127.0.0.1:{_port_nobody_listens_on()}/bot"),
        "server_closed_without_response": await raised_by(plain(), base_url, CLOSE),
        "read_timeout": await raised_by(
            plain(read_timeout=0.2), base_url, Reply(payload={"ok": True, "result": []}, delay=1.0)
        ),
        "400_bad_request": await raised_by(
            plain(), base_url, Reply(status=400, payload={"ok": False, "error_code": 400, "description": "Bad Request"})
        ),
        "409_conflict": await raised_by(
            plain(),
            base_url,
            Reply(status=409, payload={"ok": False, "error_code": 409, "description": "Conflict: terminated by other getUpdates request"}),
        ),
        "403_forbidden": await raised_by(
            plain(), base_url, Reply(status=403, payload={"ok": False, "error_code": 403, "description": "Forbidden"})
        ),
        "http_layer_bug": await raised_by(_BrokenTransport(connection_pool_size=1), base_url),
    }

    def describe(error: BaseException, **origin) -> dict:
        context = CallbackContext.from_error(update=origin.get("update"), error=error, application=application, **{
            k: v for k, v in origin.items() if k in {"job", "coroutine"}
        })
        cause = error.__cause__
        return {
            "type": f"{type(error).__module__}.{type(error).__qualname__}",
            "message": str(error)[:200],
            "cause": None if cause is None else f"{type(cause).__module__}.{type(cause).__qualname__}",
            "transient": tph.is_transient_polling_error(origin.get("update"), context),
        }

    result = {name: describe(error) for name, error in errors.items()}
    bad_gateway = errors["502_json"]

    async def _noop_job(_context) -> None:
        return None

    async def _noop() -> None:
        return None

    coroutine = _noop()
    result["502_json_from_a_job"] = describe(bad_gateway, job=Job(_noop_job))
    result["502_json_from_a_task"] = describe(bad_gateway, coroutine=coroutine)
    coroutine.close()
    result["502_json_while_handling_an_update"] = describe(bad_gateway, update=object())
    return result


async def _main(result_path: str) -> None:
    log = _ListHandler()
    logging.getLogger(tph.__name__).addHandler(log)
    api = FakeBotApi()
    base_url = api.start()
    report = {
        "retry_loop": await _retry_loop_passes(),
        "network_error_subclasses": sorted(cls.__name__ for cls in NetworkError.__subclasses__()),
        "request_vs_builder_default": _request_vs_builder_default(),
        "heartbeat": await _heartbeat(api, base_url, log),
        "ptb_error_logs": await _ptb_error_logs(api, base_url),
        "classification": await _classification(api, base_url),
        "fake_server_errors": list(api.server_errors),
    }
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1]))
