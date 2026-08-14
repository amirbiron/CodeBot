"""טסטים להצגת תאריכים בשעון ישראל.

מונגו שומר זמנים כ-UTC בלי תווית אזור זמן. כל תצוגה למשתמש חייבת לעבור
המרה, אחרת רואים שעה מוקדמת בשעתיים (חורף) או בשלוש (קיץ).
"""

from datetime import datetime, timedelta, timezone

from bson import ObjectId

from utils import TimeUtils
from webapp import app as webapp_app

# 14/08 הוא שעון קיץ בישראל (UTC+3), 14/01 הוא שעון חורף (UTC+2)
SUMMER_UTC = datetime(2026, 8, 14, 0, 58)
WINTER_UTC = datetime(2026, 1, 14, 0, 58)


# --- פונקציית ההמרה המשותפת -------------------------------------------------


def test_to_israel_time_adds_three_hours_in_summer():
    out = TimeUtils.to_israel_time(SUMMER_UTC)
    assert (out.hour, out.minute) == (3, 58)
    assert out.day == 14
    assert out.utcoffset() == timedelta(hours=3)


def test_to_israel_time_adds_two_hours_in_winter():
    out = TimeUtils.to_israel_time(WINTER_UTC)
    assert (out.hour, out.minute) == (2, 58)
    assert out.utcoffset() == timedelta(hours=2)


def test_to_israel_time_treats_naive_input_as_utc():
    """תאריך בלי תווית אזור זמן מגיע ממונגו והוא תמיד UTC."""
    naive = TimeUtils.to_israel_time(SUMMER_UTC)
    aware = TimeUtils.to_israel_time(SUMMER_UTC.replace(tzinfo=timezone.utc))
    assert naive == aware


def test_to_israel_time_converts_other_timezones():
    """קלט שכבר נושא אזור זמן אחר מומר, ולא מפורש מחדש."""
    tokyo = datetime(2026, 8, 14, 12, 0, tzinfo=timezone(timedelta(hours=9)))
    out = TimeUtils.to_israel_time(tokyo)
    # 12:00 בטוקיו = 03:00 UTC = 06:00 בישראל בקיץ
    assert (out.hour, out.minute) == (6, 0)


def test_to_israel_time_passes_through_non_datetime():
    assert TimeUtils.to_israel_time(None) is None
    assert TimeUtils.to_israel_time("not a date") == "not a date"


# --- הפורמטים של הוובאפ -----------------------------------------------------


def test_format_datetime_display_uses_israel_time():
    assert webapp_app.format_datetime_display(SUMMER_UTC) == "14/08/2026 03:58"
    assert webapp_app.format_datetime_display(WINTER_UTC) == "14/01/2026 02:58"


def test_format_datetime_display_accepts_iso_strings():
    assert webapp_app.format_datetime_display("2026-08-14T00:58:00") == "14/08/2026 03:58"


def test_format_datetime_display_returns_empty_for_bad_input():
    assert webapp_app.format_datetime_display(None) == ""
    assert webapp_app.format_datetime_display("") == ""
    assert webapp_app.format_datetime_display("not a date") == ""


def test_hhmm_filter_uses_israel_time():
    assert webapp_app.format_time_hhmm(SUMMER_UTC) == "03:58"
    assert webapp_app.format_time_hhmm(WINTER_UTC) == "02:58"
    assert webapp_app.format_time_hhmm(None) == ""


def test_day_hhmm_decides_today_by_israel_date():
    """אחרי חצות בישראל עדיין 'אתמול' ב-UTC – ובלי תיקון היה מוצג התאריך."""
    now_israel = TimeUtils.to_israel_time(datetime.now(timezone.utc))
    # רגע מלפני דקה: תמיד "היום" בשעון ישראל, ולכן שעה בלבד
    just_now = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert webapp_app.format_day_hhmm(just_now) == TimeUtils.to_israel_time(just_now).strftime(
        "%H:%M"
    )
    # לפני שלושה ימים: תאריך ושעה
    older = datetime.now(timezone.utc) - timedelta(days=3)
    assert webapp_app.format_day_hhmm(older) == TimeUtils.to_israel_time(older).strftime(
        "%d/%m %H:%M"
    )
    assert now_israel.tzinfo is not None


# --- המסכים שהמשתמש ביקש ----------------------------------------------------

FILE_OID = ObjectId("0123456789abcdef01234567")
FILE_ID = str(FILE_OID)


def _doc():
    return {
        "_id": FILE_OID,
        "user_id": 123,
        "file_name": "demo.py",
        "programming_language": "python",
        "code": "print('hi')",
        "created_at": SUMMER_UTC,
        "updated_at": SUMMER_UTC,
        "is_active": True,
        "version": 1,
    }


def _client(monkeypatch, doc):
    monkeypatch.setattr(webapp_app, "get_db", lambda: object())
    monkeypatch.setattr(
        webapp_app,
        "_get_user_any_file_by_id",
        lambda db_ref, user_id, file_id: ((doc, "regular") if doc else (None, "")),
    )
    client = webapp_app.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 123
        sess["user_data"] = {"id": 123, "first_name": "Test"}
    return client


def test_view_file_page_shows_israel_time(monkeypatch):
    client = _client(monkeypatch, _doc())
    html = client.get(f"/file/{FILE_ID}").get_data(as_text=True)
    assert "14/08/2026 03:58" in html
    # השעה הגולמית מ-UTC לא מופיעה יותר
    assert "14/08/2026 00:58" not in html


def test_file_history_api_returns_israel_time(monkeypatch):
    """מודאל היסטוריית הגרסאות מציג את המחרוזות שה-API בונה."""
    versions = [dict(_doc(), version=2), dict(_doc(), version=1)]

    class _Snippets:
        def aggregate(self, pipeline):
            return list(versions)

    class _DB:
        code_snippets = _Snippets()

    monkeypatch.setattr(webapp_app, "get_db", lambda: _DB())
    monkeypatch.setattr(
        webapp_app,
        "_get_user_file_by_id",
        lambda db_ref, user_id, file_id: versions[0],
    )
    client = webapp_app.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 123
        sess["user_data"] = {"id": 123, "first_name": "Test"}

    resp = client.get(f"/api/file/{FILE_ID}/history")
    assert resp.status_code == 200
    payload = resp.get_json() or {}
    entries = payload.get("versions") or []
    assert entries, "ציפינו לפחות לגרסה אחת"
    for entry in entries:
        assert entry["created_at"] == "14/08/2026 03:58"
        assert entry["updated_at"] == "14/08/2026 03:58"
