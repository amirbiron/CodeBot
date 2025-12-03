import pytest


@pytest.mark.parametrize(
    "prefs,expected",
    [
        ({"schedule": "daily"}, "daily"),
        ({"schedule": {"key": "weekly"}}, "weekly"),
        ({"schedule": {"value": "biweekly"}}, "biweekly"),
        ({"schedule": {"name": "monthly"}}, "monthly"),
        ({"schedule_key": "every3"}, "every3"),
        ({"scheduleKey": "daily"}, "daily"),
        ({"schedule": "  daily  "}, "daily"),
        ({"schedule": {"key": "  weekly  "}}, "weekly"),
        ({}, None),
        ({"schedule": None}, None),
        ({"schedule": {"key": ""}}, None),
    ],
)
def test_drive_rescheduler_extract_key_variants(prefs, expected):
    from handlers.drive.utils import extract_schedule_key  # noqa: WPS433

    assert extract_schedule_key(prefs) == expected
