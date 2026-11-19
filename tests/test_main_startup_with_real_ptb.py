"""העלייה של הבוט מול מסד בלי primary, ומה שעולה כשהעלייה נכשלת — מול PTB ו-APScheduler אמיתיים.

רקע: CODEKEEPER-3M (9.10.2026). בתחזוקה של Atlas לא היה primary. הבוט עלה, ``JobQueue.start`` הפעיל את
ה-jobstore ``persistent`` של APScheduler, והוא ניסה ליצור אינדקס — כתיבה, שדורשת primary — ונכשל ב-
``ServerSelectionTimeoutError``. בסגירה שאחרי זה PTB העתיק את ``bot_data`` בשביל ``PicklePersistence``,
נפל על לקוח ה-pymongo של אותו jobstore (``cannot pickle 'SSLContext' object``), וה-TypeError הזה הסתיר
את השגיאה האמיתית. שניהם הוסרו; הפירוט ב-``docs/whats-new.rst``.

שני הטסטים מריצים את ``tests/helpers/main_startup_probe.py`` בתת-תהליך. שם מוסבר למה, ומה אמיתי ומה מדומה.

**המסד.** ``MONGODB_URL`` מצביע על פורט שאיש אינו מאזין בו. לכתיבה זה אותו כשל כמו "No primary available
for writes": ב-pymongo 4.15.3 שניהם ``ServerSelectionTimeoutError`` מאותה לולאת בחירת שרת
(``Topology._select_servers_loop``), ורק תיאור הטופולוגיה בהודעה שונה. ``tls=true`` כמו החיבור ל-Atlas
בפרודקשן, כך שללקוח יש ``SSLContext`` — האובייקט שה-``deepcopy`` נפל עליו שם.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# תת-התהליך מייבא את ``main`` ומריץ עלייה וסגירה שלמות. התקרה גבוהה מ-``PROBE_TIMEOUT_SECONDS``, כדי
# שתקלה תיכשל כאן עם הדוח של הפרוב, ולא בתקרה הכללית של ``pytest.ini``.
pytestmark = pytest.mark.timeout(150)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE = REPO_ROOT / "tests" / "helpers" / "main_startup_probe.py"

#: תקרה לתת-התהליך. גבוהה מ-``DEADLINE_SECONDS`` של הפרוב, כדי שבדרך כלל הוא יספיק לכתוב דוח.
PROBE_TIMEOUT_SECONDS = 100


def _run_probe(tmp_path: Path, env: dict[str, str], failing_bot_api_method: str | None = None) -> dict:
    """``env`` — ה-fixture ``real_ptb_probe_env`` מ-``tests/conftest.py``: סביבה מפורשת, ומסד שלא עונה."""
    result_path = tmp_path / "startup_report.json"
    command = [sys.executable, "-B", str(PROBE), str(result_path)]
    if failing_bot_api_method:
        command.append(failing_bot_api_method)
    completed = subprocess.run(
        command,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    report = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    assert completed.returncode == 0 and report is not None, (
        f"הפרוב לא הסתיים כרגיל (קוד {completed.returncode}).\n"
        f"דוח: {report}\nstderr:\n{completed.stderr[-3000:]}"
    )
    # הפרוב בדק את האפליקציה של הפרודקשן, ולא אחד ממסלולי ה-fallback ש-``CodeKeeperBot`` בונה כשהבנייה
    # הרגילה נכשלת — בלי post_init ובלי persistence, כלומר בלי שני הדברים שהטסטים כאן בודקים.
    assert report["application"] == "telegram.ext._application.Application", _describe(report)
    assert report["post_init"] == "main.setup_bot_data", _describe(report)
    assert report["fake_server_errors"] == [], _describe(report)
    return report


def _describe(report: dict) -> str:
    """הדוח בשורות קריאות, להודעת הכשל: מה קרה, ואיזו שרשרת חריגות עלתה."""
    lines = [
        f"outcome={report.get('outcome')} post_init_completed={report.get('post_init_completed')} "
        f"job_queue_ran_a_job={report.get('job_queue_ran_a_job')} persistence={report.get('persistence')}"
    ]
    for depth, error in enumerate(report.get("exception") or []):
        indent = "  " * depth
        frames = error["frames"]
        shown = " > ".join(frames[:8]) + (f" > ... (+{len(frames) - 8})" if len(frames) > 8 else "")
        lines.append(f"{indent}{error['type']}: {error['message'][:300]}")
        lines.append(f"{indent}  at {shown}")
    lines.append(f"bot_api_calls={report.get('bot_api_calls')}")
    return "\n".join(lines)


def test_startup_with_db_without_primary_reaches_a_running_job_queue(tmp_path, real_ptb_probe_env):
    """עלייה מול מסד בלי primary מגיעה עד job queue שמריץ ג'ובים, ולא נופלת ב-``JobQueue.start``.

    על הקוד שלפני התיקון ``JobQueue.start`` הפעיל את ה-jobstore ``persistent``, ה-``create_index`` שלו נכשל
    ב-``ServerSelectionTimeoutError``, ו-``run_polling`` זרק — את ה-TypeError של ה-deepcopy, שהסתיר אותו.
    """
    report = _run_probe(tmp_path, real_ptb_probe_env)

    assert report["outcome"] == "stopped", _describe(report)
    assert report["job_queue_ran_a_job"] is True, _describe(report)


def test_failed_startup_raises_the_original_error_not_cannot_pickle(tmp_path, real_ptb_probe_env):
    """כשהעלייה נכשלת אחרי ה-post_init, השגיאה שעולה מ-``run_polling`` היא השגיאה האמיתית.

    הכשל המוזרק: ``deleteWebhook`` מחזיר 502. זו הקריאה הראשונה ל-Bot API אחרי ה-post_init (ב-PTB 22.5,
    ``Updater._bootstrap`` שבתוך ``start_polling``), כלומר החלון שבו ``bot_data`` כבר מחזיק את מה ש-
    ``CodeKeeperBot`` ו-``setup_bot_data`` שמו בו. על הקוד שלפני התיקון ``shutdown`` העתיק אותו בשביל
    ``PicklePersistence``, נפל על ``cannot pickle 'SSLContext' object``, וה-``NetworkError`` נבלע.
    """
    report = _run_probe(tmp_path, real_ptb_probe_env, failing_bot_api_method="deleteWebhook")

    assert report["post_init_completed"] is True, _describe(report)
    assert report["outcome"] == "raised", _describe(report)
    raised = report["exception"][0]
    assert (raised["type"], raised["message"]) == ("telegram.error.NetworkError", "Bad Gateway"), _describe(report)
    assert not any("cannot pickle" in error["message"] for error in report["exception"]), _describe(report)
