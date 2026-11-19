"""Bot API מקומי לפרובים שרצים מול python-telegram-bot האמיתי, בתת-תהליך.

משותף ל-``main_startup_probe.py``, ‏``polling_health_probe.py`` ו-``ptb_polling_contract_probe.py``. הפרובים רצים
כסקריפט מתוך ``tests/helpers``, ולכן מייבאים את המודול הזה בשמו (``import fake_bot_api``).

השרת עונה על ``127.0.0.1`` בפורט פנוי, ואין אף קריאה לטלגרם האמיתי. ברירות המחדל: ``getMe`` מחזיר בוט, ``getUpdates``
מחזיר רשימה ריקה אחרי long-poll קצר, וכל מתודה אחרת ``ok``. מעליהן:

- :meth:`FakeBotApi.script` — תשובות לפי הסדר לקריאות הבאות של מתודה; כשהתסריט נגמר, חוזרים לברירת המחדל.
- :attr:`FakeBotApi.always` — תשובה קבועה למתודה, בכל קריאה.

תשובה היא :class:`Reply`, או :data:`CLOSE` — השרת סוגר את החיבור בלי לכתוב תשובה, וזה מה ש-httpx מדווח כ-
``RemoteProtocolError: Server disconnected without sending a response`` (כמו ``CODEKEEPER-3Q``).
"""

from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Union

BOT_USER = {
    "id": 1,
    "is_bot": True,
    "first_name": "Probe",
    "username": "probe_bot",
    "can_join_groups": True,
    "can_read_all_group_messages": False,
    "supports_inline_queries": False,
}

#: הגוף ש-Bot API מחזיר על 502 — PTB 22.5 ממפה אותו ל-``NetworkError`` עם ה-description
#: (``telegram/request/_baserequest.py``, ``_request_wrapper``).
BAD_GATEWAY_PAYLOAD = {"ok": False, "error_code": 502, "description": "Bad Gateway"}


@dataclass(frozen=True)
class Reply:
    """תשובת HTTP: ``payload`` כ-JSON, או ``raw`` כמו שהוא (למשל עמוד HTML של proxy). ``delay`` — המתנה לפני התשובה."""

    status: int = 200
    # בדרך כלל מילון; כל ערך ש-``json.dumps`` מקבל — גם רשימה, כדי לבדוק תשובה שאינה אובייקט.
    payload: Optional[object] = None
    raw: Optional[bytes] = None
    content_type: str = "application/json"
    delay: float = 0.0


#: סגירת החיבור בלי תשובה.
CLOSE = "close"

Response = Union[Reply, str]


@dataclass
class FakeBotApi:
    """המצב של השרת: מה לענות, ומה קרה. ``calls`` ו-``server_errors`` מגיעים לדוחות של הפרובים."""

    long_poll_seconds: float = 0.2
    always: dict[str, Response] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    server_errors: list[str] = field(default_factory=list)
    _scripts: dict[str, list[Response]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def script(self, method: str, *responses: Response) -> None:
        with self._lock:
            self._scripts.setdefault(method, []).extend(responses)

    def _next(self, method: str) -> Response:
        with self._lock:
            self.calls.append(method)
            queued = self._scripts.get(method)
            if queued:
                return queued.pop(0)
        if method in self.always:
            return self.always[method]
        if method == "getMe":
            return Reply(payload={"ok": True, "result": BOT_USER})
        if method == "getUpdates":
            # long-poll קצר, כדי שלולאת ה-polling לא תסתובב על ריק.
            return Reply(payload={"ok": True, "result": []}, delay=self.long_poll_seconds)
        return Reply(payload={"ok": True, "result": True})

    def start(self) -> str:
        """מרים את השרת בחוט רקע, ומחזיר את ה-``base_url`` ל-``Bot`` / ``ApplicationBuilder``."""
        api = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args) -> None:  # noqa: A002 - החתימה של BaseHTTPRequestHandler
                # בלי שורה ב-stderr לכל בקשה. הקריאות נרשמות ב-``calls``.
                return

            def do_POST(self) -> None:  # noqa: N802 - השם ש-BaseHTTPRequestHandler מחפש
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                response = api._next(self.path.rsplit("/", 1)[-1])
                if response == CLOSE:
                    # בלי שורת סטטוס ובלי כותרות. ``BaseHTTPRequestHandler`` מדבר HTTP/1.0, ולכן החיבור נסגר מיד אחרי.
                    self.close_connection = True
                    return
                assert isinstance(response, Reply)
                if response.delay:
                    time.sleep(response.delay)
                body = response.raw if response.raw is not None else json.dumps(response.payload).encode()
                self.send_response(response.status)
                self.send_header("Content-Type", response.content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        class _Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address) -> None:
                error = sys.exc_info()[1]
                if isinstance(error, (BrokenPipeError, ConnectionResetError)):
                    # PTB סוגר חיבור long-poll פתוח כשהבוט נעצר, או כשהלקוח ויתר אחרי timeout, והתשובה שהשרת עוד כתב
                    # נופלת על צינור סגור. זה חלק רגיל מהסגירה, ולא תקלה בשרת.
                    return
                api.server_errors.append(repr(error))

        server = _Server(("127.0.0.1", 0), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{server.server_address[1]}/bot"


def point_application_builder_at(base_url: str) -> None:
    """כל ``ApplicationBuilder.build`` מכאן והלאה בונה אפליקציה מול ``base_url``.

    ``CodeKeeperBot`` בונה את האפליקציה בעצמו ואין לו פרמטר לכתובת ה-API, ולכן הכתובת נכנסת כאן, רגע לפני הבנייה. כל
    שאר התצורה — token, ‏defaults, ‏post_init, בקשת ``getUpdates`` — היא של ``main.py``.
    """
    from telegram.ext import ApplicationBuilder

    build = ApplicationBuilder.build

    def build_against_fake_bot_api(self):
        self.base_url(base_url)
        return build(self)

    setattr(ApplicationBuilder, "build", build_against_fake_bot_api)
