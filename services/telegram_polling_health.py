"""בריאות ה-polling של הבוט מול טלגרם — מה רעש חולף, ומתי זו תקלה ששווה התראה.

הבוט מקבל עדכונים ב-long polling: ``run_polling`` של python-telegram-bot קורא ל-``getUpdates`` שוב ושוב. רשת חיצונית
נכשלת לפעמים לרגע — ניתוק של חיבור קיים, ``ConnectError``, או ``502 Bad Gateway`` מ-``api.telegram.org`` — והספרייה
מנסה שוב לבד. עד היום כל כשל כזה הגיע ל-``error_handler`` ב-``main.py``, נרשם ב-``logger.error``, ונפתח עליו issue
ב-Sentry (``LoggingIntegration`` עם ``event_level=ERROR`` ב-``observability.init_sentry``). ההיסטוריה והמדידות:
``docs/whats-new.rst``, 2026-11-19.

המודול מפריד בין שני דברים:

- **כשל בודד** — :func:`is_transient_polling_error` מזהה אותו, ו-``error_handler`` רושם אותו ב-``warning``: נשאר בלוג,
  ולא נפתח עליו issue.
- **השבתה** — אף ``getUpdates`` לא הצליח לאורך :data:`STALL_ALERT_SECS_ENV` שניות. :class:`PollingHealthMonitor` מחליט
  מתי זה קורה, והג'וב :data:`WATCHDOG_JOB_NAME` שולח :data:`ALERT_STALLED` פעם אחת לכל השבתה, ו-:data:`ALERT_RECOVERED`
  כשה-polling חוזר.

**למה זמן מאז ההצלחה האחרונה, ולא ספירת כשלים ב-``error_handler``.** שתי עובדות על python-telegram-bot 22.5
(``telegram/ext/_utils/networkloop.py``, ``network_retry_loop``): ``TimedOut`` ו-``RetryAfter`` נתפסים שם לפני שה-callback
של השגיאות נקרא, ולכן השבתה שמתבטאת ב-timeouts בלבד לא מגיעה ל-``error_handler`` אף פעם; ואין שום callback על הצלחה,
ולכן אין מי שיאפס מונה. האות היחיד שמכסה כל סוג של השבתה הוא ``getUpdates`` שהצליח — :class:`PollingHeartbeatRequest`
רושם אותו. ``tests/helpers/ptb_polling_contract_probe.py`` מקבע את שתי העובדות מול הספרייה המותקנת, כדי ששדרוג שמשנה
אותן ייכשל ב-CI.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Callable, Optional

import httpx
from telegram.error import NetworkError, TelegramError, TimedOut
from telegram.request import HTTPXRequest

from telegram_api import redact_bot_token

logger = logging.getLogger(__name__)

#: שם ההתראה כשאף ``getUpdates`` לא הצליח לאורך הסף. גם ``alert_type`` בפרטים, וגם שם ה-runbook ב-``config/observability_runbooks.yml``.
ALERT_STALLED = "telegram_polling_stalled"
#: שם ההתראה כש-``getUpdates`` מצליח שוב אחרי :data:`ALERT_STALLED`.
ALERT_RECOVERED = "telegram_polling_recovered"

#: משתנה הסביבה של הסף, בשניות.
STALL_ALERT_SECS_ENV = "TELEGRAM_POLLING_STALL_ALERT_SECS"
#: ברירת המחדל של הסף. פרץ רגיל נגמר בפחות מ-10 שניות, וההשבתה האמיתית ב-3.11.2026 נמשכה יותר משעתיים (שניהם נמדדו
#: באירועי ``CODEKEEPER-D``). בין שתי הצלחות תקינות עוברות עד ``TELEGRAM_LONG_POLL_TIMEOUT_SECS`` ועוד ה-read timeout של
#: בקשת ``getUpdates`` — 20 ועוד 5 בברירות המחדל — כך שגם polling שקט לגמרי לא מתקרב לסף.
DEFAULT_STALL_ALERT_SECS = 120

#: שם הג'וב שבודק את הסף (נרשם ב-``setup_bot_data`` ב-``main.py``).
WATCHDOG_JOB_NAME = "telegram_polling_watchdog"
#: התדירות המרבית של הג'וב. בפועל רבע מהסף, ולא פחות משנייה — ראו :func:`watchdog_interval_secs`.
WATCHDOG_MAX_INTERVAL_SECS = 15.0

#: חריגות httpx שהן תקלת רשת חולפת כשהן ה-``__cause__`` של ``NetworkError``: כשל בחיבור, בקריאה, בכתיבה או בסגירה
#: (``httpx.NetworkError``), ושרת שניתק בלי תשובה (``httpx.RemoteProtocolError``). שאר העץ של ``httpx.HTTPError`` אינו
#: כאן בכוונה — ``UnsupportedProtocol`` ו-``LocalProtocolError`` הן תצורה שגויה או באג אצלנו, ו-``ProxyError`` היא
#: תצורה של proxy. ‏timeouts אינם צריכים להיות כאן: PTB ממפה אותם ל-``TimedOut`` (``telegram/request/_httpxrequest.py``).
_TRANSIENT_TRANSPORT_CAUSES = (httpx.NetworkError, httpx.RemoteProtocolError)


def is_polling_origin(update: object, context: Any) -> bool:
    """האם השגיאה הגיעה מלולאת ה-polling — ולא מטיפול בעדכון של משתמש, מג'וב או ממשימת רקע.

    ב-python-telegram-bot 22.5 יש חמישה מסלולים ל-``Application.process_error``, וכל אחד ממלא שדה אחר ב-context:

    - טיפול בעדכון — ``update`` קיים.
    - ג'וב של ה-JobQueue — ``context.job`` (``telegram/ext/_jobqueue.py``, ``Job._run``).
    - ``application.create_task`` — ``context.coroutine`` (``Application.__create_task_callback``). כך רצים למשל
      ``_milestones_job`` ב-``main.py`` והמתזמן של התזכורות, בלי ``update``.
    - ``run_polling`` — ``process_error(error=exc, update=None)``, בלי ג'וב ובלי coroutine (``Application.run_polling``).
    - persistence — גם הוא בלי שלושתם, אבל לבוט אין persistence (ההערה ליד בניית האפליקציה ב-``main.py``).
    """
    return update is None and context.job is None and context.coroutine is None


def is_transient_polling_error(update: object, context: Any) -> bool:
    """האם זו תקלת רשת חולפת ב-``getUpdates``, שהספרייה כבר מנסה שוב בעצמה.

    כל התנאים יחד:

    1. השגיאה הגיעה מה-polling (:func:`is_polling_origin`).
    2. היא ``TimedOut``, או ``NetworkError`` בדיוק — לא תת-מחלקה אחרת. ב-PTB 22.5 ל-``NetworkError`` יש שתי תת-מחלקות,
       ``TimedOut`` ו-``BadRequest``; ‏``BadRequest`` היא תשובת 400, כלומר אנחנו שלחנו פרמטר שגוי — באג ולא רשת. תת-מחלקה חדשה בשדרוג תישאר ``error`` עד שמישהו יחליט אחרת (ה-probe בודק שהרשימה לא השתנתה).
    3. ל-``NetworkError`` יש סיבה של רשת. ``BaseRequest._request_wrapper`` עוטף **כל** חריגה משכבת ה-HTTP ב-
       ``NetworkError("Unknown error in HTTP implementation: ...")`` — וזה באג, לא תקלה חולפת. לכן: בלי ``__cause__``
       (תשובת סטטוס מטלגרם שאין לה מחלקה משלה, בפועל 5xx), עם ``TelegramError`` כסיבה (אותה תשובה, כשגוף התשובה לא
       נקרא כ-JSON), או עם אחת מ-:data:`_TRANSIENT_TRANSPORT_CAUSES`.
    """
    if not is_polling_origin(update, context):
        return False
    error = context.error
    if isinstance(error, TimedOut):
        return True
    if type(error) is not NetworkError:
        return False
    cause = error.__cause__
    if cause is None or isinstance(cause, TelegramError):
        return True
    return isinstance(cause, _TRANSIENT_TRANSPORT_CAUSES)


def read_stall_alert_secs() -> int:
    """הסף מ-:data:`STALL_ALERT_SECS_ENV`, או :data:`DEFAULT_STALL_ALERT_SECS` כשהוא חסר או לא תקין.

    מספר שלם, 1 ומעלה. ``0`` אינו "התראה מיד" כמו בסף של ``/metrics`` (``services/webapp_metrics_outage.py``): כאן הסף
    נמדד מההצלחה האחרונה, ו-0 היה מתריע בכל בדיקה. ערך לא תקין נרשם באזהרה ומוחלף בברירת המחדל — זה ערך תצורה ולא
    סוד, ולכן הוא נכנס לשורת הלוג כמו שהוא.
    """
    raw = (os.getenv(STALL_ALERT_SECS_ENV) or "").strip()
    if not raw:
        return DEFAULT_STALL_ALERT_SECS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "invalid %s=%r (not an integer); using the default %d",
            STALL_ALERT_SECS_ENV,
            raw,
            DEFAULT_STALL_ALERT_SECS,
        )
        return DEFAULT_STALL_ALERT_SECS
    if value < 1:
        logger.warning(
            "invalid %s=%r (must be at least 1); using the default %d",
            STALL_ALERT_SECS_ENV,
            raw,
            DEFAULT_STALL_ALERT_SECS,
        )
        return DEFAULT_STALL_ALERT_SECS
    return value


def watchdog_interval_secs(threshold_secs: int) -> float:
    """כל כמה שניות הג'וב בודק: רבע מהסף, בין שנייה אחת ל-:data:`WATCHDOG_MAX_INTERVAL_SECS`.

    ההתראה יוצאת בבדיקה הראשונה שאחרי הסף, כלומר באיחור של עד בדיקה אחת. עם ברירת המחדל זה עד 15 שניות אחרי 120.
    """
    return min(WATCHDOG_MAX_INTERVAL_SECS, max(1.0, threshold_secs / 4))


@dataclass(frozen=True)
class PollingHealthEvent:
    """מה ש-:class:`PollingHealthMonitor` מבקש לדווח: תחילת השבתה (:data:`ALERT_STALLED`) או סופה (:data:`ALERT_RECOVERED`).

    ``stalled_seconds`` — בהשבתה: מההצלחה האחרונה (או מתחילת המעקב) ועד הבדיקה; בחזרה: עד ההצלחה הראשונה. ``last_error``
    — השגיאה האחרונה שה-polling דיווח עליה בזמן ההשבתה, מנוקה מסודות; ריק כשלא דווחה אף אחת, ואז זו בדרך כלל השבתה של
    timeouts בלבד.
    """

    kind: str
    stalled_seconds: float
    last_error: str
    threshold_seconds: int


class PollingHealthMonitor:
    """זוכר מתי ``getUpdates`` הצליח לאחרונה, ומחליט מתי להתריע.

    שלושה כותבים, כולם על אותה לולאת asyncio ובלי ``await`` באמצע, ולכן בלי מנעול: :class:`PollingHeartbeatRequest`
    קורא ל-:meth:`record_success`, ``error_handler`` קורא ל-:meth:`note_polling_error`, והג'וב קורא ל-:meth:`check`.

    התראה יוצאת פעם אחת, בבדיקה הראשונה שבה עברו :attr:`threshold_secs` שניות מההצלחה האחרונה. אחריה אין התראה נוספת עד
    שמגיעה הצלחה: הבדיקה שאחריה מחזירה :data:`ALERT_RECOVERED` ומשחררת את הנעילה, והשבתה הבאה תתריע שוב.

    **נקודת ההתחלה** נקבעת ב-:meth:`start_watch`, רגע לפני שה-polling מתחיל (``setup_bot_data``), ולא כשהבוט נבנה: בין
    הבנייה ל-polling הבוט עלול לחכות דקות לנעילה, ומדידה מהבנייה הייתה מתריעה על השבתה שלא הייתה. בלי ``start_watch``
    :meth:`check` לא מתריע כלל.
    """

    def __init__(self, *, threshold_secs: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.threshold_secs = threshold_secs
        self._clock = clock
        self._watch_started_at: Optional[float] = None
        self._last_success_at: Optional[float] = None
        self._last_error = ""
        self._last_error_at: Optional[float] = None
        self._alerted_at: Optional[float] = None
        self._outage_started_at: Optional[float] = None

    def start_watch(self) -> None:
        """מתחיל (או מתחיל מחדש) את המעקב מעכשיו. השבתה שכבר דווחה נשארת פתוחה עד ההצלחה הבאה."""
        self._watch_started_at = self._clock()

    def record_success(self) -> None:
        """``getUpdates`` הצליח עכשיו."""
        self._last_success_at = self._clock()

    def note_polling_error(self, error: BaseException) -> None:
        """שגיאה שה-polling דיווח עליה — רק כדי שההתראה תאמר מה קרה. הטקסט מנוקה מסודות כבר כאן, לפני שהוא נשמר.

        טקסט של חריגת רשת יכול לשאת את כתובת ה-API, ובה את טוקן הבוט; ההתראה נשלחת לטלגרם ונשמרת במסד. החריגה עצמה עוברת
        ל-``redact_bot_token`` ולא מחרוזת שכבר נבנתה ממנה: אם ``str()`` שלה נכשל, משם חוזר ``<UNREDACTABLE>`` ולא חריגה.
        """
        self._last_error = f"{type(error).__name__}: {redact_bot_token(error)}"[:500]
        self._last_error_at = self._clock()

    def check(self) -> Optional[PollingHealthEvent]:
        """בודק את המצב עכשיו, ומחזיר אירוע לדיווח או ``None``."""
        if self._watch_started_at is None:
            return None
        if self._alerted_at is not None and self._outage_started_at is not None:
            return self._check_recovery(self._alerted_at, self._outage_started_at)
        reference = self._reference(self._watch_started_at)
        now = self._clock()
        stalled = now - reference
        if stalled < self.threshold_secs:
            return None
        self._alerted_at = now
        self._outage_started_at = reference
        return PollingHealthEvent(
            kind=ALERT_STALLED,
            stalled_seconds=stalled,
            last_error=self._error_between(reference, now),
            threshold_seconds=self.threshold_secs,
        )

    def _check_recovery(self, alerted_at: float, outage_started_at: float) -> Optional[PollingHealthEvent]:
        if self._last_success_at is None or self._last_success_at <= alerted_at:
            return None
        event = PollingHealthEvent(
            kind=ALERT_RECOVERED,
            stalled_seconds=self._last_success_at - outage_started_at,
            last_error=self._error_between(outage_started_at, self._last_success_at),
            threshold_seconds=self.threshold_secs,
        )
        self._alerted_at = None
        self._outage_started_at = None
        return event

    def _reference(self, watch_started_at: float) -> float:
        # ההצלחה האחרונה, אבל לא מוקדם מתחילת המעקב: הצלחה מריצה קודמת של ``run_polling`` אינה מתארת את הנוכחית.
        if self._last_success_at is None:
            return watch_started_at
        return max(self._last_success_at, watch_started_at)

    def _error_between(self, start: float, end: float) -> str:
        if self._last_error_at is None or not (start <= self._last_error_at <= end):
            return ""
        return self._last_error


class PollingHeartbeatRequest(HTTPXRequest):
    """בקשת ה-HTTP של ``getUpdates``, שמדווחת על כל תשובה מוצלחת.

    נכנסת לאפליקציה דרך ``ApplicationBuilder.get_updates_request``. ב-python-telegram-bot 22.5 ה-``Bot`` מחזיק שתי בקשות,
    ומשתמש בזו רק ל-``getUpdates`` (``telegram/_bot.py``, ``Bot._do_post``); לכן כל תשובה מוצלחת שעוברת כאן היא
    ``getUpdates`` שהצליח. "מוצלחת" — אותו כלל ש-PTB משתמש בו כדי להחליט אם לזרוק (``BaseRequest._request_wrapper``):
    סטטוס 200 עד 299.

    הדריסה היא של ``do_request`` — המתודה ש-``BaseRequest`` מגדיר כנקודת ההרחבה. ``post`` ו-``_request_wrapper`` מסומנים
    ``@final``. רישום ההצלחה עטוף ב-``try``: כשל בו לעולם לא מגיע ל-PTB, והתשובה חוזרת כמו שהיא. בלי זה, באג ב-heartbeat
    היה נעטף כ-``NetworkError`` (``_request_wrapper``) ומשבית את ה-polling כולו. הכשל נרשם עם traceback, ואם הוא חוזר, הג'וב
    יתריע על השבתה — כי בעיני המוניטור אין הצלחות.
    """

    __slots__ = ("_on_success",)

    def __init__(self, on_success: Callable[[], None], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._on_success = on_success

    async def do_request(self, *args: Any, **kwargs: Any) -> tuple[int, bytes]:
        code, payload = await super().do_request(*args, **kwargs)
        if HTTPStatus.OK <= code <= 299:
            try:
                self._on_success()
            except Exception:
                logger.exception(
                    "telegram polling heartbeat: recording a successful getUpdates failed; "
                    "the response goes back to PTB unchanged"
                )
        return code, payload


def report_polling_event(event: PollingHealthEvent) -> None:
    """שולח את האירוע כהתראה פנימית: :data:`ALERT_STALLED` בחומרת ``error``, ו-:data:`ALERT_RECOVERED` בחומרת ``info``.

    ``emit_internal_alert`` שולח לטלגרם ולמסך ה-Observability, ואינו פותח issue ב-Sentry. בזמן השבתה של טלגרם השליחה
    לטלגרם עצמה כנראה תיכשל, אבל ההתראה נשמרת במסד; התראת החזרה מגיעה לטלגרם עם משך ההשבתה. ``emit_internal_alert`` אינו
    זורק (הוא תופס הכול בעצמו); ה-``try`` כאן הוא על הייבוא ועל בניית ההודעה, והתראה שלא יצאה נרשמת עם traceback. הפונקציה
    סינכרונית ועושה I/O — הג'וב מריץ אותה ב-``asyncio.to_thread``.
    """
    try:
        from internal_alerts import emit_internal_alert

        minutes = max(1, round(event.stalled_seconds / 60))
        if event.kind == ALERT_STALLED:
            severity = "error"
            if event.last_error:
                cause = f"השגיאה האחרונה: {event.last_error}."
            else:
                cause = (
                    "לא דווחה שגיאה מפורשת — כנראה timeouts, ש-python-telegram-bot מנסה שוב בלי להעביר ל-error handler."
                )
            summary = (
                f"הבוט לא מקבל עדכונים מטלגרם כבר {minutes} דק': אף getUpdates לא הצליח מאז. {cause} "
                f"עד שזה יחזור, הבוט לא עונה למשתמשים."
            )
        else:
            severity = "info"
            summary = f"הבוט שוב מקבל עדכונים מטלגרם, אחרי {minutes} דק' בלי getUpdates מוצלח."
        emit_internal_alert(
            event.kind,
            severity=severity,
            summary=summary,
            details={
                "alert_type": event.kind,
                "stalled_seconds": round(event.stalled_seconds),
                "last_error": event.last_error,
                "threshold_seconds": event.threshold_seconds,
            },
        )
    except Exception:
        logger.exception("telegram polling health: could not send the %s alert", event.kind)
