"""הבוט האמיתי מול תקלה של ``getUpdates``: כשל חולף נרשם ב-warning, תקלה אמיתית נשארת error, והשבתה מתריעה פעם אחת.

רקע: ``CODEKEEPER-D``, ‏``CODEKEEPER-3Q`` ו-``162169879`` — כל כשל רשת רגעי ב-polling נפתח כ-issue ב-Sentry, כי
``error_handler`` ב-``main.py`` רשם כל שגיאה ב-``logger.error``. הטסט מריץ את ``tests/helpers/polling_health_probe.py``
בתת-תהליך — ה-``Application`` ש-``CodeKeeperBot`` בונה, ``run_polling`` של PTB האמיתי, ו-Bot API מדומה. שם מוסבר התסריט.

"error" כאן הוא בדיוק מה ש-Sentry הופך ל-issue: ``LoggingIntegration(event_level=logging.ERROR)`` ב-
``observability.init_sentry``. ‏warning נשאר breadcrumb.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(150)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE = REPO_ROOT / "tests" / "helpers" / "polling_health_probe.py"

#: סף קצר מהתסריט של הפרוב (כשמונה שניות בלי הצלחה), כדי שההשבתה תתריע. הג'וב בודק כל שנייה (רבע מהסף, לא פחות משנייה).
STALL_ALERT_SECS = "2"


@pytest.fixture
def report(tmp_path, real_ptb_probe_env) -> dict:
    env = dict(real_ptb_probe_env, TELEGRAM_POLLING_STALL_ALERT_SECS=STALL_ALERT_SECS)
    result_path = tmp_path / "polling_report.json"
    completed = subprocess.run(
        [sys.executable, "-B", str(PROBE), str(result_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=100,
    )
    data = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    # כאן רק שיש דוח. אם הפרוב עצר בלי התראת חזרה, הטסט נכשל על ההתנהגות שחסרה — ולא כאן, על ה-outcome.
    assert completed.returncode == 0 and data is not None, (
        f"הפרוב לא הסתיים כרגיל (קוד {completed.returncode}).\nדוח: {data}\nstderr:\n{completed.stderr[-3000:]}"
    )
    assert data["fake_server_errors"] == [], data["fake_server_errors"]
    return data


def _records(report: dict, level: str, text: str) -> list[dict]:
    return [rec for rec in report["error_handler_records"] if rec["level"] == level and text in rec["message"]]


def test_polling_through_the_real_bot(report):
    """טסט אחד על ריצה אחת: הריצה לוקחת כ-15 שניות, ולכן כל הבדיקות של אותה ריצה כאן, כל אחת עם הודעה משלה."""
    records = report["error_handler_records"]

    # 1. שלושת ה-502 של ``getUpdates``: warning, בלי traceback — ואף אחד מהם לא ב-error.
    transient = _records(report, "WARNING", "telegram polling: transient getUpdates failure")
    assert len(transient) == 3, records
    assert all("NetworkError: Bad Gateway" in rec["message"] and not rec["has_traceback"] for rec in transient), records
    assert not _records(report, "ERROR", "Bad Gateway"), records

    # 2. 400 על ``getUpdates`` הוא באג אצלנו, לא רשת: נשאר error, עם traceback.
    (bad_request,) = _records(report, "ERROR", "Wrong offset")
    assert bad_request["has_traceback"], records

    # 3. ``NetworkError`` מחוץ ל-polling — מג'וב, וממשימת רקע בלי ``update`` — נשאר error.
    assert _records(report, "ERROR", "probe: a job failed to reach Telegram"), records
    assert _records(report, "ERROR", "probe: a background task failed to reach Telegram"), records

    # 4. השבתה של כשמונה שניות מול סף של שתיים: התראה אחת, ואחריה התראת חזרה אחת. התראות אחרות (למשל של העלייה) לא בדיון.
    alerts = [alert for alert in report["alerts"] if alert["name"].startswith("telegram_polling_")]
    assert [(alert["name"], alert["severity"]) for alert in alerts] == [
        ("telegram_polling_stalled", "error"),
        ("telegram_polling_recovered", "info"),
    ], alerts
    stalled, recovered = alerts
    assert stalled["details"]["last_error"] == "NetworkError: Bad Gateway", stalled
    assert stalled["details"]["threshold_seconds"] == int(STALL_ALERT_SECS), stalled
    assert recovered["details"]["stalled_seconds"] >= stalled["details"]["stalled_seconds"], alerts

    # 5. החיווט: הבקשה של הבוט רשמה הצלחה, והג'וב נרשם בתדירות שנגזרת מהסף.
    assert report["heartbeat_recorded"] is True
    assert report["watchdog_jobs"] == [{"name": "telegram_polling_watchdog", "interval_seconds": 1.0}]

    # 6. הפרוב עצר כי כל מה שחיכה לו קרה, ולא בגלל התקרה.
    assert report["outcome"] == "done", report["outcome"]
