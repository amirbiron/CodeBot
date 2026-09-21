"""``_job_run_doc_to_dict`` — מה ה-API של הדשבורד מחזיר על הרצה.

הסריאלייזר קיבל שני שדות חדשים (``failure_reason``, ``owner_id``) בלי טסט.
כאן מוודאים שהם עוברים כמו שהם, שהרצה שלא נסגרה אינה מקבלת משך, ושהלוגים
נכנסים רק כשביקשו.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from webapp import app as app_mod

NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)


def test_a_reconciled_run_is_serialized_with_its_attribution_and_duration():
    doc = {
        "run_id": "r1",
        "job_id": "cache_warming",
        "started_at": NOW - timedelta(seconds=90),
        "ended_at": NOW,
        "status": "failed",
        "error_message": "closed by reconcile",
        "failure_reason": "orphaned",
        "owner_id": "srv-1:7",
        "logs": [{"timestamp": NOW, "level": "error", "message": "orphan-audit", "details": None}],
    }

    out = app_mod._job_run_doc_to_dict(doc, include_logs=True)

    assert out["failure_reason"] == "orphaned"
    assert out["owner_id"] == "srv-1:7"
    assert out["duration_seconds"] == 90.0
    assert out["logs"] == [{"timestamp": NOW.isoformat(), "level": "error", "message": "orphan-audit"}]


def test_a_run_that_never_ended_has_no_duration_no_attribution_and_no_logs_unless_asked():
    doc = {"run_id": "r2", "job_id": "cache_warming", "started_at": NOW, "status": "running"}

    out = app_mod._job_run_doc_to_dict(doc)

    assert out["duration_seconds"] is None
    assert out["failure_reason"] is None
    assert out["owner_id"] is None
    assert "logs" not in out
