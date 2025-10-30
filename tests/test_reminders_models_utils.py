from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from reminders.models import Reminder, ReminderConfig
from reminders.validators import ReminderValidator
from reminders.utils import parse_time


def test_reminder_validate_success():
    r = Reminder(
        reminder_id="r1",
        user_id=1,
        title="כותרת תקינה",
        remind_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    ok, err = r.validate()
    assert ok is True
    assert err == ""


def test_reminder_validate_failures():
    # Empty title
    r = Reminder(reminder_id="r2", user_id=1, title="", remind_at=datetime.now(timezone.utc) + timedelta(hours=1))
    ok, err = r.validate()
    assert ok is False
    assert "כותרת" in err

    # Past time
    r = Reminder(reminder_id="r3", user_id=1, title="t", remind_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    ok, err = r.validate()
    assert ok is False
    assert "בעתיד" in err


def test_validator_text():
    val = ReminderValidator()
    assert val.validate_text("שלום עולם 123") is True
    assert val.validate_text("") is True
    assert val.validate_text("a" * 2001) is False


def test_parse_time_variants():
    # ISO-like
    dt = parse_time("2025-12-25 14:00", "Asia/Jerusalem")
    assert dt is not None and dt.tzinfo is not None

    # Tomorrow HH:MM
    dt2 = parse_time("tomorrow 10:00", "Asia/Jerusalem")
    assert dt2 is not None

    # HH:MM today or tomorrow
    dt3 = parse_time("15:30", "Asia/Jerusalem")
    assert dt3 is not None

    # Hebrew hours
    dt4 = parse_time("בעוד 3 שעות", "Asia/Jerusalem")
    assert dt4 is not None

    # Hebrew minutes
    dt5 = parse_time("בעוד 2 דקות", "Asia/Jerusalem")
    assert dt5 is not None

    # Quarter/Half hour
    dt6 = parse_time("בעוד רבע שעה", "Asia/Jerusalem")
    assert dt6 is not None
    dt7 = parse_time("בעוד חצי שעה", "Asia/Jerusalem")
    assert dt7 is not None


def test_parse_time_relative_deltas_and_compound_inputs():
    tz = "Asia/Jerusalem"
    now_local = datetime.now(ZoneInfo(tz))

    # phrase -> expected minutes
    cases = [
        ("בעוד דקה", 1),
        ("בעוד 2 דקות", 2),
        ("בעוד רבע שעה", 15),
        ("בעוד חצי שעה", 30),
        ("בעוד שעה", 60),
        ("in 2 minutes", 2),
        ("in 3 hours", 180),
    ]

    for phrase, expected_minutes in cases:
        dt = parse_time(phrase, tz)
        assert dt is not None, f"failed to parse: {phrase}"
        delta_sec = (dt - now_local).total_seconds()
        expected_sec = expected_minutes * 60
        # within ±45 seconds tolerance
        assert abs(delta_sec - expected_sec) < 45, f"unexpected delta for '{phrase}': got {delta_sec}s, expected ~{expected_sec}s"

    # Compound inputs should not be loosely parsed
    assert parse_time("בעוד 2 שעות ו-30 דקות", tz) is None
    assert parse_time("in 1 hour and 5 minutes", tz) is None


def test_parse_time_empty_and_invalid_inputs():
    tz = "Asia/Jerusalem"
    # empty / whitespace
    assert parse_time("", tz) is None
    assert parse_time("   ", tz) is None
    # 'tomorrow' without time should not parse
    assert parse_time("tomorrow", tz) is None
    # malformed phrases should not parse
    assert parse_time("in minutes", tz) is None
    assert parse_time("בעוד זמן", tz) is None


def test_parse_time_hhmm_rollover_and_future():
    tz = "Asia/Jerusalem"
    now_local = datetime.now(ZoneInfo(tz))
    # 00:00 should roll to next day and still be in the future
    dt_midnight = parse_time("00:00", tz)
    assert dt_midnight is not None
    assert dt_midnight.hour == 0 and dt_midnight.minute == 0
    assert dt_midnight > now_local
    
    # 23:59 typically later today; ensure parsed and not rolled over in most times
    dt_last = parse_time("23:59", tz)
    assert dt_last is not None
    assert dt_last.hour == 23 and dt_last.minute == 59


def test_parse_time_english_case_insensitive():
    tz = "Asia/Jerusalem"
    now_local = datetime.now(ZoneInfo(tz))
    dt_a = parse_time("IN 5 MINUTES", tz)
    dt_b = parse_time("In 1 Hours", tz)
    assert dt_a is not None and dt_b is not None
    assert 4*60 <= (dt_a - now_local).total_seconds() <= 6*60
    assert 59*60 <= (dt_b - now_local).total_seconds() <= 61*60
