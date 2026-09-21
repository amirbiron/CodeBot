"""``scripts/migrate_reminder_acked_status.py`` — מדווח בלי דגל, כותב רק עם ``--apply``, ואומר על מה הוא רץ.

הגרסה הראשונה כתבה כברירת מחדל ודילגה רק עם ``--dry-run`` — הפוך מכל סקריפט
מיגרציה אחר בתיקייה (WARN-012 בסקירת #3430). וגם: ``DATABASE_NAME`` שגוי הדפיס
"אין מה לעדכן" והצליח (SUGG-003), ואישור שנחת באמצע הריצה מפוד ישן נספר ככשל
של הריצה (SUGG-004). הסקריפט נטען מהקובץ ורץ עם ``get_db`` מזויף.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from _fake_mongo import FakeDB

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "migrate_reminder_acked_status.py"
NOW = datetime(2026, 9, 21, 8, 0, 0, tzinfo=timezone.utc)


def _load_script():
    spec = importlib.util.spec_from_file_location("migrate_reminder_acked_status", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db(monkeypatch):
    """``get_db`` של הסקריפט מחזיר את הדמה; חבילת ``services`` האמיתית אינה נטענת."""
    fake = FakeDB(name="code_keeper_test")
    monkeypatch.setitem(sys.modules, "services.db_provider", types.SimpleNamespace(get_db=lambda: fake))
    return fake


def _seed_stale(db, note_id="n1"):
    """תזכורת שאושרה לפני שהמצב הסופי היה קיים: ``ack_at`` מלא, ``status`` עדיין פעיל."""
    db.note_reminders.insert_one({
        "user_id": 1, "note_id": note_id, "status": "pending",
        "remind_at": NOW - timedelta(days=1), "ack_at": NOW - timedelta(hours=1),
    })


def _run(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["migrate_reminder_acked_status.py", *argv])
    module = _load_script()
    code = 0
    try:
        module.main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    return code, capsys.readouterr().out


def test_without_a_flag_it_only_reports(db, monkeypatch, capsys):
    _seed_stale(db)
    code, out = _run(monkeypatch, capsys)
    assert code == 0, out
    assert db.note_reminders.docs[0]["status"] == "pending", "הסקריפט כתב בלי --apply"
    assert "--apply" in out, out


def test_with_apply_it_writes_and_verifies_from_the_database(db, monkeypatch, capsys):
    _seed_stale(db)
    code, out = _run(monkeypatch, capsys, "--apply")
    assert code == 0, out
    assert db.note_reminders.docs[0]["status"] == "acked"
    assert "הושלמה" in out, out


def test_it_names_the_database_and_counts_the_collection_before_anything_else(db, monkeypatch, capsys):
    """SUGG-003: ``DATABASE_NAME`` שגוי נותן אוסף אמיתי וריק — ובלי השורה הזו הפלט
    היה "אין מה לעדכן" עם קוד יציאה 0, כאילו הכול טוב."""
    code, out = _run(monkeypatch, capsys)
    assert code == 0, out
    first = out.strip().splitlines()[0]
    assert "code_keeper_test" in first and "0" in first, first
    assert "אין תזכורות" in out, out


def test_an_ack_that_lands_during_the_run_is_not_this_runs_failure(db, monkeypatch, capsys):
    """SUGG-004: פוד ישן מאשר באמצע הריצה וכותב ``ack_at`` בלי ``status`` — מסמך
    "ישן" חדש בין הכתיבה לספירה החוזרת. הספירה החוזרת תחומה לאישורים שהיו
    קיימים כשהריצה התחילה; המסמך החדש שייך לריצה הבאה, והפלט אומר שהיא בטוחה."""
    _seed_stale(db)
    coll = db.note_reminders
    real_update_many = coll.update_many

    def _update_then_old_pod_acks(q, u):
        result = real_update_many(q, u)
        coll.insert_one({
            "user_id": 1, "note_id": "n2", "status": "pending",
            "remind_at": NOW, "ack_at": datetime.now(timezone.utc) + timedelta(seconds=5),
        })
        return result

    monkeypatch.setattr(coll, "update_many", _update_then_old_pod_acks)
    code, out = _run(monkeypatch, capsys, "--apply")
    assert code == 0, out
    assert "הרצה חוזרת" in out, out
