"""עוזר לטסט: מקבע מול python-telegram-bot האמיתי את העובדות ש-``services/telegram_polling_health.py`` נשען עליהן.

הטסט שמריץ אותו: ``tests/test_telegram_polling_ptb_contract.py``. בתת-תהליך, כי ``tests/conftest.py`` מחליף את
``telegram`` ב-stubs בכל הסוויטה — ושם, למשל, ``BadRequest`` לא תמיד ירשה מ-``NetworkError``.

מה נבדק, וכל בדיקה כותבת מפתח משלה לדוח:

- ``retry_loop`` — אילו חריגות ``network_retry_loop`` מעביר ל-callback של השגיאות. ‏``TimedOut`` לא: זו הסיבה שההתראה על
  השבתה נשענת על heartbeat ולא על ספירת שגיאות ב-``error_handler``.
- ``network_error_subclasses`` — הסיווג מבחין ב-``NetworkError`` לפי הטיפוס המדויק; תת-מחלקה חדשה בשדרוג צריכה החלטה.
- ``request_vs_builder_default`` — הבקשה שהבוט מעביר ל-``get_updates_request`` זהה למה שה-builder היה בונה בעצמו.
- ``heartbeat`` — הבקשה מדווחת על 200, לא על 502, וכשל ברישום ההצלחה לא נוגע בתשובה ש-PTB מקבל.
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
        "classification": await _classification(api, base_url),
        "fake_server_errors": list(api.server_errors),
    }
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1]))
