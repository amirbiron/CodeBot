"""``services/telegram_polling_health.py``: מתי היעדר של ``getUpdates`` מוצלח הופך להתראה, ומה נכנס אליה.

הרקע: כל כשל רשת רגעי ב-polling נפתח כ-issue ב-Sentry (``CODEKEEPER-D``, ‏``CODEKEEPER-3Q``). היום כשל בודד נרשם
ב-warning, והתראה יוצאת רק כשאף ``getUpdates`` לא הצליח לאורך הסף. הטסטים כאן מקבעים את ההחלטה של
:class:`PollingHealthMonitor` מול שעון ידני: פרץ קצר אינו מתריע, השבתה מתריעה פעם אחת, החזרה מדווחת, ואחריה השבתה
חדשה מתריעה שוב.

הסיווג של החריגות (:func:`is_transient_polling_error`) והבקשה (:class:`PollingHeartbeatRequest`) נשענים על
python-telegram-bot, ושם ה-stubs של ``tests/conftest.py`` אינם עדים נאמנים. הם נבדקים מול הספרייה האמיתית בתת-תהליך:
``tests/test_telegram_polling_ptb_contract.py`` ו-``tests/test_telegram_polling_health_e2e.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from services import telegram_polling_health as tph

# מבנה של טוקן אמיתי (מזהה, נקודתיים, 35 תווים) — בדוי. כך ``redact_bot_token`` מזהה אותו.
FAKE_TOKEN = "1234567890:AAH" + "x" * 32
THRESHOLD = 120


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def monitor(clock):
    watched = tph.PollingHealthMonitor(threshold_secs=THRESHOLD, clock=clock)
    watched.start_watch()
    return watched


# --- ההחלטה ---------------------------------------------------------------------------------------------------------


def test_polling_that_keeps_succeeding_never_alerts(monitor, clock):
    """polling שקט: ``getUpdates`` חוזר ריק כל 20 שניות (ה-long poll), לאורך שעה."""
    for _ in range(180):
        clock.advance(20)
        monitor.record_success()
        assert monitor.check() is None


def test_a_burst_shorter_than_the_threshold_does_not_alert(monitor, clock):
    """הפרץ של 18.11.2026 ב-``CODEKEEPER-D``: חמש שגיאות בתוך 8 שניות, ואז הצלחה."""
    monitor.record_success()
    for _ in range(5):
        clock.advance(2)
        monitor.note_polling_error(RuntimeError("Bad Gateway"))
        assert monitor.check() is None
    monitor.record_success()
    clock.advance(THRESHOLD - 1)
    assert monitor.check() is None


def test_an_outage_alerts_once_at_the_threshold(monitor, clock):
    monitor.record_success()
    clock.advance(THRESHOLD - 1)
    assert monitor.check() is None

    clock.advance(1)
    event = monitor.check()
    assert event is not None
    assert event.kind == tph.ALERT_STALLED
    assert event.stalled_seconds == THRESHOLD
    assert event.threshold_seconds == THRESHOLD

    # ההשבתה נמשכת שעתיים, כמו ב-3.11.2026 — ואין התראה שנייה.
    for _ in range(480):
        clock.advance(15)
        assert monitor.check() is None


def test_recovery_is_reported_once_with_the_outage_length(monitor, clock):
    monitor.record_success()
    clock.advance(THRESHOLD)
    assert monitor.check().kind == tph.ALERT_STALLED

    clock.advance(600)
    monitor.record_success()
    recovered = monitor.check()
    assert recovered is not None
    assert recovered.kind == tph.ALERT_RECOVERED
    assert recovered.stalled_seconds == THRESHOLD + 600

    clock.advance(15)
    assert monitor.check() is None


def test_a_second_outage_after_recovery_alerts_again(monitor, clock):
    """"מתי ההתראה הבאה כן תצא?" — אחרי שהחזרה דווחה, השבתה חדשה מתריעה מאפס."""
    monitor.record_success()
    clock.advance(THRESHOLD)
    assert monitor.check().kind == tph.ALERT_STALLED
    clock.advance(30)
    monitor.record_success()
    assert monitor.check().kind == tph.ALERT_RECOVERED

    clock.advance(THRESHOLD - 1)
    assert monitor.check() is None
    clock.advance(1)
    second = monitor.check()
    assert second is not None and second.kind == tph.ALERT_STALLED


def test_no_alert_before_the_watch_starts(clock):
    """בלי ``start_watch`` אין ממה למדוד — ולא מתריעים, גם אחרי זמן רב (הבוט בנוי, אבל עוד מחכה לנעילה)."""
    watched = tph.PollingHealthMonitor(threshold_secs=THRESHOLD, clock=clock)
    clock.advance(10 * THRESHOLD)
    assert watched.check() is None


def test_the_threshold_is_measured_from_the_watch_start_when_nothing_succeeded(monitor, clock):
    """בוט שעלה ואף ``getUpdates`` שלו לא הצליח — שבור, ומתריעים עליו מרגע תחילת המעקב."""
    clock.advance(THRESHOLD - 1)
    assert monitor.check() is None
    clock.advance(1)
    event = monitor.check()
    assert event is not None and event.kind == tph.ALERT_STALLED
    assert event.stalled_seconds == THRESHOLD


def test_a_restarted_watch_does_not_measure_from_an_older_success(clock):
    """הצלחה מריצה קודמת של ``run_polling`` אינה נקודת ההתחלה של הריצה החדשה."""
    watched = tph.PollingHealthMonitor(threshold_secs=THRESHOLD, clock=clock)
    watched.start_watch()
    watched.record_success()
    clock.advance(1000)
    watched.start_watch()
    clock.advance(THRESHOLD - 1)
    assert watched.check() is None


# --- מה נכנס להתראה --------------------------------------------------------------------------------------------------


def test_the_stall_alert_carries_the_last_polling_error(monitor, clock):
    monitor.record_success()
    clock.advance(10)
    monitor.note_polling_error(RuntimeError("first"))
    clock.advance(10)
    monitor.note_polling_error(ConnectionError("Bad Gateway"))
    clock.advance(THRESHOLD)
    event = monitor.check()
    assert event.last_error == "ConnectionError: Bad Gateway"


def test_an_error_from_before_the_last_success_is_not_this_outage(monitor, clock):
    """השגיאה האחרונה קרתה לפני ההצלחה האחרונה — ההשבתה הזו לא דיווחה על שגיאה, למשל timeouts בלבד."""
    monitor.note_polling_error(RuntimeError("old"))
    clock.advance(5)
    monitor.record_success()
    clock.advance(THRESHOLD)
    event = monitor.check()
    assert event.kind == tph.ALERT_STALLED
    assert event.last_error == ""


def test_the_recovery_alert_carries_the_error_of_that_outage(monitor, clock):
    monitor.record_success()
    clock.advance(THRESHOLD)
    assert monitor.check().kind == tph.ALERT_STALLED
    clock.advance(30)
    monitor.note_polling_error(RuntimeError("during"))
    clock.advance(30)
    monitor.record_success()
    assert monitor.check().last_error == "RuntimeError: during"


def test_the_bot_token_is_redacted_before_it_is_kept(monitor):
    url = f"https://api.telegram.org/bot{FAKE_TOKEN}/getUpdates"
    monitor.note_polling_error(RuntimeError(f"Invalid URL {url}"))
    assert FAKE_TOKEN not in monitor._last_error
    assert "<REDACTED>" in monitor._last_error


def test_an_error_whose_str_raises_is_kept_as_unredactable(monitor):
    class _Unprintable(Exception):
        def __str__(self) -> str:
            raise ValueError("no text")

    monitor.note_polling_error(_Unprintable())
    assert monitor._last_error == "_Unprintable: <UNREDACTABLE>"


# --- הסף והתדירות ---------------------------------------------------------------------------------------------------


def test_threshold_defaults_when_unset(monkeypatch):
    monkeypatch.delenv(tph.STALL_ALERT_SECS_ENV, raising=False)
    assert tph.read_stall_alert_secs() == tph.DEFAULT_STALL_ALERT_SECS == 120


@pytest.mark.parametrize("raw, expected", [("90", 90), (" 300 ", 300), ("1", 1)])
def test_threshold_from_env(monkeypatch, raw, expected):
    monkeypatch.setenv(tph.STALL_ALERT_SECS_ENV, raw)
    assert tph.read_stall_alert_secs() == expected


@pytest.mark.parametrize("raw", ["abc", "1.5", "0", "-5"])
def test_invalid_threshold_falls_back_with_a_warning(monkeypatch, caplog, raw):
    monkeypatch.setenv(tph.STALL_ALERT_SECS_ENV, raw)
    with caplog.at_level(logging.WARNING, logger=tph.__name__):
        assert tph.read_stall_alert_secs() == tph.DEFAULT_STALL_ALERT_SECS
    assert any(tph.STALL_ALERT_SECS_ENV in rec.getMessage() for rec in caplog.records)


@pytest.mark.parametrize("threshold, expected", [(120, 15.0), (1000, 15.0), (8, 2.0), (2, 1.0), (1, 1.0)])
def test_watchdog_interval_is_a_quarter_of_the_threshold_within_bounds(threshold, expected):
    assert tph.watchdog_interval_secs(threshold) == expected


# --- השליחה --------------------------------------------------------------------------------------------------------


@pytest.fixture
def sent_alerts(monkeypatch):
    import internal_alerts

    sent: list[dict] = []

    def _capture(name, severity="info", summary="", **details):
        sent.append({"name": name, "severity": severity, "summary": summary, **details})

    monkeypatch.setattr(internal_alerts, "emit_internal_alert", _capture)
    return sent


def test_the_stall_alert_is_an_error_with_the_last_error(sent_alerts):
    tph.report_polling_event(
        tph.PollingHealthEvent(
            kind=tph.ALERT_STALLED,
            stalled_seconds=130.4,
            last_error="NetworkError: Bad Gateway",
            threshold_seconds=120,
        )
    )
    (alert,) = sent_alerts
    assert alert["name"] == "telegram_polling_stalled"
    assert alert["severity"] == "error"
    assert "NetworkError: Bad Gateway" in alert["summary"]
    assert alert["details"] == {
        "alert_type": "telegram_polling_stalled",
        "stalled_seconds": 130,
        "last_error": "NetworkError: Bad Gateway",
        "threshold_seconds": 120,
    }


def test_a_stall_without_an_error_says_it_was_probably_timeouts(sent_alerts):
    tph.report_polling_event(tph.PollingHealthEvent(tph.ALERT_STALLED, 150, "", 120))
    (alert,) = sent_alerts
    assert "timeouts" in alert["summary"]


def test_the_recovered_alert_is_info(sent_alerts):
    tph.report_polling_event(tph.PollingHealthEvent(tph.ALERT_RECOVERED, 720, "NetworkError: Bad Gateway", 120))
    (alert,) = sent_alerts
    assert alert["name"] == "telegram_polling_recovered"
    assert alert["severity"] == "info"
    assert alert["details"]["alert_type"] == "telegram_polling_recovered"
    assert alert["details"]["stalled_seconds"] == 720


def test_a_failing_alert_sink_is_logged_and_does_not_raise(monkeypatch, caplog):
    import internal_alerts

    def _boom(*_a, **_k):
        raise RuntimeError("sink down")

    monkeypatch.setattr(internal_alerts, "emit_internal_alert", _boom)
    event = tph.PollingHealthEvent(tph.ALERT_STALLED, 130, "", 120)
    with caplog.at_level(logging.ERROR, logger=tph.__name__):
        tph.report_polling_event(event)
    assert any("telegram_polling_stalled" in rec.getMessage() and rec.exc_info for rec in caplog.records)


# --- עותקים שחייבים להישאר זהים -------------------------------------------------------------------------------------


def test_config_inspector_default_matches_the_code():
    from services.config_inspector_service import ConfigService

    definition = ConfigService.CONFIG_DEFINITIONS[tph.STALL_ALERT_SECS_ENV]
    assert definition.default == str(tph.DEFAULT_STALL_ALERT_SECS)


def test_the_stall_alert_has_a_runbook():
    path = Path(__file__).resolve().parents[1] / "config" / "observability_runbooks.yml"
    runbooks = yaml.safe_load(path.read_text(encoding="utf-8"))["runbooks"]
    assert tph.ALERT_STALLED in runbooks
