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
import os
import socket
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


def _port_nobody_listens_on() -> int:
    """פורט ב-127.0.0.1 שאיש אינו מאזין בו: נפתח כדי לקבל מספר, ונסגר מיד."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _probe_env(tmp_path: Path) -> dict[str, str]:
    """הסביבה של תת-התהליך — מפורשת, ולא עותק של ``os.environ``.

    עותק היה מעביר לבוט כל מפתח שנמצא בסביבה של מי שמריץ (ב-CI, למשל, ``GITHUB_TOKEN``), והבוט פונה
    איתם בעלייה לשירותים אמיתיים. מאותה סיבה ``cwd`` של תת-התהליך הוא ``tmp_path``: ``config`` קורא
    את ``.env`` מהתיקייה הנוכחית.
    """
    home = tmp_path / "home"
    home.mkdir()
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "TMPDIR": str(tmp_path),
        "PYTHONIOENCODING": "utf-8",
        "BOT_TOKEN": "0:probe",
        # ``DISABLE_DB`` אינו מוגדר, כמו בפרודקשן. ``tests/conftest.py`` מגדיר אותו לסוויטה, ותת-התהליך
        # אינו יורש ממנה.
        "MONGODB_URL": f"mongodb://127.0.0.1:{_port_nobody_listens_on()}/?tls=true",
        # המתנות קצרות לרכיבים שנוגעים במסד בעלייה ואינם הנושא כאן: מנהל המסד הגלובלי
        # (``database/manager.py``) ו-``services/db_provider.py``.
        "MONGODB_SERVER_SELECTION_TIMEOUT_MS": "300",
        "MONGODB_CONNECT_MAX_RETRIES": "1",
        # ``setup_bot_data`` בודק בעלייה את מודל ה-embedding (``maybe_upgrade_embedding_model_on_startup``),
        # וזה פונה למסד ול-Gemini — שוב לא הנושא כאן, ומאריך את העלייה.
        "SEMANTIC_SEARCH_ENABLED": "false",
        "DISABLE_ACTIVITY_REPORTER": "1",
        "CODEBOT_DISABLE_GEVENT_PATCH": "1",
    }


def _run_probe(tmp_path: Path, failing_bot_api_method: str | None = None) -> dict:
    result_path = tmp_path / "startup_report.json"
    command = [sys.executable, "-B", str(PROBE), str(result_path)]
    if failing_bot_api_method:
        command.append(failing_bot_api_method)
    completed = subprocess.run(
        command,
        cwd=tmp_path,
        env=_probe_env(tmp_path),
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


def test_startup_with_db_without_primary_reaches_a_running_job_queue(tmp_path):
    """עלייה מול מסד בלי primary מגיעה עד job queue שמריץ ג'ובים, ולא נופלת ב-``JobQueue.start``.

    על הקוד שלפני התיקון ``JobQueue.start`` הפעיל את ה-jobstore ``persistent``, ה-``create_index`` שלו נכשל
    ב-``ServerSelectionTimeoutError``, ו-``run_polling`` זרק — את ה-TypeError של ה-deepcopy, שהסתיר אותו.
    """
    report = _run_probe(tmp_path)

    assert report["outcome"] == "stopped", _describe(report)
    assert report["job_queue_ran_a_job"] is True, _describe(report)


def test_failed_startup_raises_the_original_error_not_cannot_pickle(tmp_path):
    """כשהעלייה נכשלת אחרי ה-post_init, השגיאה שעולה מ-``run_polling`` היא השגיאה האמיתית.

    הכשל המוזרק: ``deleteWebhook`` מחזיר 502. זו הקריאה הראשונה ל-Bot API אחרי ה-post_init (ב-PTB 22.5,
    ``Updater._bootstrap`` שבתוך ``start_polling``), כלומר החלון שבו ``bot_data`` כבר מחזיק את מה ש-
    ``CodeKeeperBot`` ו-``setup_bot_data`` שמו בו. על הקוד שלפני התיקון ``shutdown`` העתיק אותו בשביל
    ``PicklePersistence``, נפל על ``cannot pickle 'SSLContext' object``, וה-``NetworkError`` נבלע.
    """
    report = _run_probe(tmp_path, failing_bot_api_method="deleteWebhook")

    assert report["post_init_completed"] is True, _describe(report)
    assert report["outcome"] == "raised", _describe(report)
    raised = report["exception"][0]
    assert (raised["type"], raised["message"]) == ("telegram.error.NetworkError", "Bad Gateway"), _describe(report)
    assert not any("cannot pickle" in error["message"] for error in report["exception"]), _describe(report)
