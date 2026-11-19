"""העובדות על python-telegram-bot ש-``services/telegram_polling_health.py`` נשען עליהן — מול הספרייה המותקנת.

הטסטים מריצים את ``tests/helpers/ptb_polling_contract_probe.py`` בתת-תהליך, פעם אחת למודול, ובודקים חלקים שונים של
הדוח. שם מוסבר למה תת-תהליך ומה כל חלק מודד. המטרה כפולה: שהסיווג והבקשה נבדקים מול חריגות ותשובות אמיתיות של
הספרייה, ושדרוג של python-telegram-bot שמשנה את אחת העובדות ייכשל כאן ולא בפרודקשן.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(120)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE = REPO_ROOT / "tests" / "helpers" / "ptb_polling_contract_probe.py"


@pytest.fixture(scope="module")
def report(tmp_path_factory) -> dict:
    work = tmp_path_factory.mktemp("ptb_polling_contract")
    home = work / "home"
    home.mkdir()
    result_path = work / "report.json"
    completed = subprocess.run(
        [sys.executable, "-B", str(PROBE), str(result_path)],
        cwd=work,
        # סביבה מפורשת ולא עותק של ``os.environ``, כמו ב-``tests/test_main_startup_with_real_ptb.py``.
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(home), "TMPDIR": str(work), "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        timeout=100,
    )
    assert completed.returncode == 0 and result_path.exists(), (
        f"הפרוב לא הסתיים כרגיל (קוד {completed.returncode}).\nstderr:\n{completed.stderr[-3000:]}"
    )
    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert data["fake_server_errors"] == [], data["fake_server_errors"]
    return data


# --- למה heartbeat ולא ספירת שגיאות ---------------------------------------------------------------------------------


def test_timeouts_never_reach_the_error_callback_of_the_polling_loop(report):
    """``TimedOut`` ו-``RetryAfter`` נבלעים בלולאה; רק ``NetworkError`` מגיע ל-callback, ומשם ל-``error_handler``."""
    assert report["retry_loop"] == {"NetworkError": True, "TimedOut": False, "RetryAfter": False}


def test_network_error_has_exactly_the_subclasses_the_classifier_knows(report):
    assert report["network_error_subclasses"] == ["BadRequest", "TimedOut"]


# --- הבקשה --------------------------------------------------------------------------------------------------------


def test_the_heartbeat_request_matches_what_the_builder_builds_by_default(report):
    shapes = report["request_vs_builder_default"]
    assert shapes["ours"] == shapes["default"]
    assert shapes["installed_is_ours"] is True


def test_only_a_successful_get_updates_counts_as_a_heartbeat(report):
    heartbeat = report["heartbeat"]
    assert heartbeat["after_200"] == 1
    assert heartbeat["502_raised"] == "NetworkError"
    assert heartbeat["after_502"] == 1


def test_a_failure_in_recording_the_success_does_not_reach_ptb(report):
    """כשל ברישום ההצלחה — מכל סיבה — לא שובר את התשובה: העדכון חוזר ל-PTB, והכשל נרשם עם traceback."""
    heartbeat = report["heartbeat"]
    assert heartbeat["broken_on_success_returned"] == [7]
    (logged,) = heartbeat["broken_on_success_logged"]
    assert logged["level"] == "ERROR"
    assert logged["has_traceback"] is True


# --- הסיווג ---------------------------------------------------------------------------------------------------------

TRANSIENT = [
    # ``CODEKEEPER-D``: ‏502 מ-``api.telegram.org``, וגם 502 של proxy עם גוף HTML.
    "502_json",
    "502_html",
    "500_json",
    # ``162169879``: ‏``httpx.ConnectError``.
    "connection_refused",
    # ``CODEKEEPER-3Q``: ‏``httpx.RemoteProtocolError``.
    "server_closed_without_response",
    "read_timeout",
]

NOT_TRANSIENT = [
    # 400 — אנחנו שלחנו פרמטר שגוי. ``BadRequest`` יורשת מ-``NetworkError``, ולכן היא מסוננת כאן במפורש.
    "400_bad_request",
    "409_conflict",
    "403_forbidden",
    # באג בשכבת ה-HTTP, שהספרייה עוטפת ב-``NetworkError``.
    "http_layer_bug",
    # אותו 502 בדיוק, מחוץ ל-polling.
    "502_json_from_a_job",
    "502_json_from_a_task",
    "502_json_while_handling_an_update",
]


@pytest.mark.parametrize("case", TRANSIENT)
def test_transient_polling_failures(report, case):
    assert report["classification"][case]["transient"] is True, report["classification"][case]


@pytest.mark.parametrize("case", NOT_TRANSIENT)
def test_failures_that_stay_errors(report, case):
    assert report["classification"][case]["transient"] is False, report["classification"][case]


def test_the_cases_are_the_ones_the_sentry_issues_showed(report):
    """הבדיקות למעלה מכסות את החריגות שנצפו ב-Sentry — ולא רק משהו שדומה להן."""
    classification = report["classification"]
    assert classification["502_json"]["message"] == "Bad Gateway"
    assert classification["connection_refused"]["message"] == "httpx.ConnectError: All connection attempts failed"
    assert (
        classification["server_closed_without_response"]["message"]
        == "httpx.RemoteProtocolError: Server disconnected without sending a response."
    )
    assert classification["400_bad_request"]["type"] == "telegram.error.BadRequest"
    http_layer_bug = classification["http_layer_bug"]["message"]
    assert http_layer_bug.startswith("Unknown error in HTTP implementation")
