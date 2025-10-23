from datetime import datetime, timezone, timedelta

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
