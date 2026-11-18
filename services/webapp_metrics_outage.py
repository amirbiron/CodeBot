"""זמינות ``/metrics`` של הוובאפ, כפי שהדגימה של הבוט רואה אותה — ומתי זה שווה התראה.

הדגימה התקופתית ``predictive_sampler`` ב-``main.py`` קוראת את ``/metrics`` של הוובאפ פעם בכמה שניות (``PREDICTIVE_SAMPLER_INTERVAL_SECS``)
ומזינה ממנו את המנוע החזוי. בכל דיפלוי של הוובאפ הקריאה נכשלת: לשירות מחובר דיסק קבוע, ולכן Render מכבה את המופע הישן לפני
שהחדש עולה. ב-18.11.2026 החור נמדד בלוגים של Render — 58 שניות בין כיבוי הישן להאזנה של החדש. עד היום כל כישלון כזה יצא
כ-``external_request_failure`` בחומרת ``error``, נפתח עליו issue ב-Sentry, וההתראה הגיעה לטלגרם בכל דיפלוי.

המודול מפריד בין שני דברים:

- **כישלון בודד** — נרשם בלוג בחומרת ``warning`` (``failure_severity`` של ``http_async.request``) ונספר כאן.
- **השבתה** — ``/metrics`` לא נקרא לאורך :data:`OUTAGE_ALERT_SECS_ENV` שניות ברצף. רק אז יוצאת התראה, :data:`ALERT_UNREACHABLE`,
  פעם אחת לכל השבתה; וכשהקריאה מצליחה שוב יוצאת :data:`ALERT_RECOVERED`.

מה נספר ככישלון — רק מה ש-:func:`scrape_metrics` מחזיר ככזה: תשובה שאינה 200, או חריגה ש-``http_async.is_transport_error``
מזהה (timeout, ``aiohttp.ClientError``, מעגל פתוח). חריגה אחרת היא באג, והיא עולה הלאה ולא נספרת כ"הוובאפ לא זמין".
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

#: שם ההתראה כש-``/metrics`` לא נקרא לאורך הסף. גם ``alert_type`` בפרטים, וגם שם ה-runbook ב-``config/observability_runbooks.yml``.
ALERT_UNREACHABLE = "webapp_metrics_unreachable"
#: שם ההתראה כשהקריאה מצליחה שוב אחרי :data:`ALERT_UNREACHABLE`.
ALERT_RECOVERED = "webapp_metrics_recovered"

#: משתנה הסביבה של הסף, בשניות.
OUTAGE_ALERT_SECS_ENV = "PREDICTIVE_SAMPLER_OUTAGE_ALERT_SECS"
#: ברירת המחדל של הסף: פי שניים בערך מהחור שנמדד בדיפלוי, כדי שדיפלוי רגיל לא יגיע אליו.
DEFAULT_OUTAGE_ALERT_SECS = 120


def read_outage_alert_secs() -> int:
    """הסף מ-:data:`OUTAGE_ALERT_SECS_ENV`, או :data:`DEFAULT_OUTAGE_ALERT_SECS` כשהוא חסר או לא תקין.

    ``0`` פירושו התראה כבר בכישלון הראשון. ערך שאינו מספר שלם, או שלילי, נרשם באזהרה ומוחלף בברירת המחדל — זה ערך
    תצורה ולא סוד, ולכן הוא נכנס לשורת הלוג כמו שהוא.
    """
    raw = (os.getenv(OUTAGE_ALERT_SECS_ENV) or "").strip()
    if not raw:
        return DEFAULT_OUTAGE_ALERT_SECS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "invalid %s=%r (not an integer); using the default %d",
            OUTAGE_ALERT_SECS_ENV,
            raw,
            DEFAULT_OUTAGE_ALERT_SECS,
        )
        return DEFAULT_OUTAGE_ALERT_SECS
    if value < 0:
        logger.warning(
            "invalid %s=%r (negative); using the default %d",
            OUTAGE_ALERT_SECS_ENV,
            raw,
            DEFAULT_OUTAGE_ALERT_SECS,
        )
        return DEFAULT_OUTAGE_ALERT_SECS
    return value


def required_failures(threshold_secs: int, interval_secs: float) -> int:
    """כמה בדיקות כושלות ברצף מכסות ``threshold_secs``: הראשונה בזמן 0, והאחרונה בזמן ``threshold_secs`` או אחריו.

    בדיקה כל 60 שניות וסף של 120 — שלוש בדיקות (0, 60, 120). הספירה נגזרת מהתדירות ולא נקבעת כמספר, כדי ששינוי של
    ``PREDICTIVE_SAMPLER_INTERVAL_SECS`` לא ישנה את הסף בזמן. ספירה ולא השוואת שעונים, כי בין הבדיקה הראשונה לשלישית
    עוברות 120 שניות ועוד או פחות כמה אלפיות, ו-119.99 היה דוחה את ההתראה בבדיקה שלמה.
    """
    if interval_secs <= 0:
        raise ValueError(f"interval_secs must be positive, got {interval_secs!r}")
    if threshold_secs < 0:
        raise ValueError(f"threshold_secs must not be negative, got {threshold_secs!r}")
    return math.ceil(threshold_secs / interval_secs) + 1


@dataclass(frozen=True)
class ScrapeResult:
    """תוצאה של קריאה אחת: ``text`` בהצלחה, ``failure_reason`` בכישלון — תמיד בדיוק אחד מהם."""

    text: Optional[str] = None
    failure_reason: Optional[str] = None

    @classmethod
    def success(cls, text: str) -> "ScrapeResult":
        return cls(text=text, failure_reason=None)

    @classmethod
    def failure(cls, reason: str) -> "ScrapeResult":
        return cls(text=None, failure_reason=reason)

    @property
    def ok(self) -> bool:
        return self.failure_reason is None


async def scrape_metrics(url: str) -> ScrapeResult:
    """קריאה אחת של ``url`` (ה-``/metrics`` של הוובאפ) דרך ``http_async``, עם הניסיונות החוזרים הרגילים שלו.

    כישלון סופי של הבקשה נרשם שם בחומרת ``warning`` ולא ``error``: כישלון בודד אינו תקלה, ו-:class:`OutageTracker`
    מחליט מתי הוא כן. הסיבה בתוצאה: ``HTTP <קוד>`` לתשובה שאינה 200, ``circuit_open`` כשהמעגל פתוח ולא נשלחה בקשה,
    או שם המחלקה של חריגת התחבורה. חריגה ש-``is_transport_error`` לא מזהה עולה הלאה.
    """
    from http_async import CircuitOpenError, is_transport_error, request

    try:
        async with request(
            "GET", url, service="webapp", endpoint="/metrics", failure_severity="warning"
        ) as resp:
            if resp.status != 200:
                return ScrapeResult.failure(f"HTTP {resp.status}")
            # ``read`` ולא ``text``: הוובאפ מצהיר ``charset=utf-8`` (``metrics.metrics_content_type``), ופענוח עם
            # ``replace`` לא יכול להיכשל — כך אין מסלול חלופי. גם קריאת הגוף חסומה בתקרת הזמן הכוללת של הסשן
            # (``AIOHTTP_TIMEOUT_TOTAL``): ב-aiohttp 3.13.1 ה-timeout הכולל מכסה גם את צריכת הגוף, ומבוטל רק כשהחיבור
            # משתחרר (``client.py``, ``ClientSession._request``: ``resp.connection.add_callback(handle.cancel)``).
            body = await resp.read()
    except Exception as exc:
        if not is_transport_error(exc):
            raise
        if isinstance(exc, CircuitOpenError):
            return ScrapeResult.failure("circuit_open")
        return ScrapeResult.failure(type(exc).__name__)
    return ScrapeResult.success(body.decode("utf-8", "replace"))


@dataclass(frozen=True)
class OutageEvent:
    """מה ש-:class:`OutageTracker` מבקש לדווח: תחילת השבתה (:data:`ALERT_UNREACHABLE`) או סופה (:data:`ALERT_RECOVERED`)."""

    kind: str
    consecutive_failures: int
    outage_seconds: float
    last_reason: str
    threshold_seconds: int


class OutageTracker:
    """סופר כישלונות רצופים של :func:`scrape_metrics`, ומחליט מתי להתריע.

    התראה יוצאת פעם אחת, בכישלון ה-:attr:`required_failures` ברצף. אחריה אין התראה נוספת עד שקריאה מצליחה: ההצלחה
    מחזירה :data:`ALERT_RECOVERED` ומאפסת את הכול, והשבתה הבאה מתחילה לספור מאפס ותתריע שוב. הצלחה בלי התראה קודמת
    מאפסת בשקט — זה המקרה של דיפלוי רגיל.

    ``outage_seconds`` נמדד מהבדיקה הכושלת הראשונה, ולכן הוא חסם תחתון: ההשבתה עצמה יכלה להתחיל עד בדיקה אחת קודם.
    """

    def __init__(
        self,
        *,
        threshold_secs: int,
        interval_secs: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold_secs = threshold_secs
        self.required_failures = required_failures(threshold_secs, interval_secs)
        self._clock = clock
        self._consecutive = 0
        self._first_failure_at: Optional[float] = None
        self._last_reason = ""
        self._alerted = False

    def record(self, result: ScrapeResult) -> Optional[OutageEvent]:
        """רושם תוצאה של קריאה אחת, ומחזיר אירוע לדיווח או ``None``."""
        now = self._clock()
        if result.ok:
            return self._record_success(now)
        return self._record_failure(str(result.failure_reason), now)

    def _record_failure(self, reason: str, now: float) -> Optional[OutageEvent]:
        # תחילת ההשבתה נקבעת רק בכישלון הראשון ברצף. כישלון שאחרי ההתראה לא מזיז אותה, אחרת משך ההשבתה בהתראת
        # החזרה היה נמדד מהכישלון האחרון.
        if self._consecutive == 0:
            self._first_failure_at = now
        self._consecutive += 1
        self._last_reason = reason
        if self._alerted or self._consecutive < self.required_failures:
            return None
        self._alerted = True
        return self._event(ALERT_UNREACHABLE, now)

    def _record_success(self, now: float) -> Optional[OutageEvent]:
        event = self._event(ALERT_RECOVERED, now) if self._alerted else None
        self._consecutive = 0
        self._first_failure_at = None
        self._last_reason = ""
        self._alerted = False
        return event

    def _event(self, kind: str, now: float) -> OutageEvent:
        started = self._first_failure_at if self._first_failure_at is not None else now
        return OutageEvent(
            kind=kind,
            consecutive_failures=self._consecutive,
            outage_seconds=max(0.0, now - started),
            last_reason=self._last_reason,
            threshold_seconds=self.threshold_secs,
        )


async def scrape_and_track(url: str, tracker: Optional[OutageTracker]) -> ScrapeResult:
    """הבדיקה של הרצה אחת של הסמפלר: קריאה של ``url``, רישום התוצאה ב-``tracker``, ודיווח אם הגיע הזמן.

    ``tracker`` הוא ``None`` כשאין "ברצף" — הסמפלר רץ פעם אחת כי התזמון נכשל — ואז רק קוראים. חריגה ש-:func:`scrape_metrics`
    מעלה (באג, לא תקלת תחבורה) עולה מכאן בלי לגעת במונה.
    """
    result = await scrape_metrics(url)
    if tracker is not None:
        event = tracker.record(result)
        if event is not None:
            report_outage_event(event)
    return result


def report_outage_event(event: OutageEvent) -> None:
    """שולח את האירוע כהתראה פנימית: :data:`ALERT_UNREACHABLE` בחומרת ``error``, ו-:data:`ALERT_RECOVERED` בחומרת ``info``.

    ``emit_internal_alert`` שולח לטלגרם ולמסך ה-Observability, ואינו פותח issue ב-Sentry. הוא גם אינו זורק (הוא תופס
    הכול בעצמו); ה-``try`` כאן הוא על הייבוא ועל בניית ההודעה, והתראה שלא יצאה נרשמת עם traceback ולא עוצרת את הדגימה.
    """
    try:
        from internal_alerts import emit_internal_alert

        minutes = max(1, round(event.outage_seconds / 60))
        if event.kind == ALERT_UNREACHABLE:
            severity = "error"
            summary = (
                f"הבוט לא מצליח לקרוא את /metrics של הוובאפ כבר {minutes} דק' "
                f"({event.consecutive_failures} בדיקות ברצף). הסיבה האחרונה: {event.last_reason}. "
                f"עד שזה יחזור, המנוע החזוי לא מקבל מדידות מהוובאפ."
            )
        else:
            severity = "info"
            summary = (
                f"הבוט שוב קורא את /metrics של הוובאפ, אחרי {minutes} דק' של כישלונות "
                f"({event.consecutive_failures} בדיקות ברצף)."
            )
        emit_internal_alert(
            event.kind,
            severity=severity,
            summary=summary,
            details={
                "alert_type": event.kind,
                "consecutive_failures": event.consecutive_failures,
                "outage_seconds": round(event.outage_seconds),
                "last_reason": event.last_reason,
                "threshold_seconds": event.threshold_seconds,
            },
        )
    except Exception:
        logger.exception("webapp metrics outage: could not send the %s alert", event.kind)
