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


@pytest.mark.parametrize(
    "case",
    ["html_body", "json_without_result", "ok_false", "ok_false_with_a_result", "result_not_a_list", "json_array"],
)
def test_a_2xx_that_is_not_a_valid_bot_api_answer_is_not_a_heartbeat(report, case):
    """proxy שמחזיר 200 עם דף HTML, או JSON בלי ``result``: הבוט לא מקבל עדכונים, ולכן זה גם לא heartbeat.

    אילו זה היה נספר, תשובות כאלה היו מאפסות את המוניטור שוב ושוב, ו-``telegram_polling_stalled`` לא היה יוצא לעולם.
    ``ok`` שקר עם רשימה נכלל כאן כי Bot API מגדיר אותו ככישלון, אף ש-PTB מחזיר בו את הרשימה בלי לבדוק את ``ok``.
    """
    outcome = report["heartbeat"]["malformed_2xx"][case]
    assert outcome["heartbeat"] is False, outcome


def test_ptb_delivers_no_updates_on_those_2xx_answers(report):
    """הצד של PTB: על התשובות האלה הוא זורק, ולכן ``getUpdates`` באמת לא הצליח — ו-``parse_json_payload`` שלנו לא משנה איזו
    חריגה הוא זורק. ``json_array`` נועל בדיוק את זה: בלי בדיקת ה-``dict`` לפני ``.get``, הקוד שלנו היה זורק
    ``AttributeError`` במקום ה-``TypeError`` של PTB. ‏``result`` שאינו רשימה ו-``ok`` שקר עם רשימה לא נבדקים כאן — מה PTB
    עושה בהם אינו מה שהבוט נשען עליו."""
    malformed = report["heartbeat"]["malformed_2xx"]
    assert malformed["html_body"]["ptb"] == "raised TelegramError", malformed
    assert malformed["json_without_result"]["ptb"] == "raised KeyError", malformed
    assert malformed["ok_false"]["ptb"] == "raised KeyError", malformed
    assert malformed["json_array"]["ptb"] == "raised TypeError", malformed


def test_a_failure_in_recording_the_success_does_not_reach_ptb(report):
    """כשל ברישום ההצלחה — מכל סיבה — לא שובר את התשובה: העדכון חוזר ל-PTB, והכשל נרשם עם traceback."""
    heartbeat = report["heartbeat"]
    assert heartbeat["broken_on_success_returned"] == [7]
    (logged,) = heartbeat["broken_on_success_logged"]
    assert logged["level"] == "ERROR"
    assert logged["has_traceback"] is True


# --- רשומות הלוג של PTB עצמו ----------------------------------------------------------------------------------------


def test_ptb_logs_an_error_on_a_502_html_body_without_us(report):
    """הבקרה: דרך הבקשה של PTB, 502 עם גוף HTML כותב רשומת ERROR ב-``telegram.request.BaseRequest`` — כלומר issue ב-Sentry.
    בלי זה, הטסט הבא היה עובר גם אילו הבדיקה פשוט לא ראתה את הרשומות."""
    logged = report["ptb_error_logs"]["502_html_ptb"]["ptb_error_records"]
    assert [rec["level"] for rec in logged] == ["ERROR"], logged


@pytest.mark.parametrize("case", ["502_html_ours", "503_html_ours", "502_json_ours"])
def test_a_transient_5xx_leaves_no_ptb_error_record(report, case):
    """5xx הוא תקלה חולפת, ו-``error_handler`` רושם אותו ב-warning. גם PTB עצמו לא כותב עליו ERROR, ולכן אין issue."""
    outcome = report["ptb_error_logs"][case]
    assert outcome["ptb_error_records"] == [], outcome


def test_the_502_html_failure_is_the_same_exception_as_without_us(report):
    """הפענוח בלי שורת הלוג אינו משנה את מה ש-PTB זורק: אותו טיפוס, אותה הודעה (כולל גוף התשובה), ואותה סיבה — ולכן גם
    אותו סיווג (``502_html`` בבדיקות הסיווג)."""
    logs = report["ptb_error_logs"]
    assert logs["502_html_ours"]["raised"] == logs["502_html_ptb"]["raised"], logs
    assert logs["502_json_ours"]["raised"] == logs["502_json_ptb"]["raised"], logs
    assert "<html>Bad Gateway</html>" in logs["502_html_ours"]["raised"]["message"]


def test_the_status_of_one_answer_is_not_reused_for_the_next_parse(report):
    """הסטטוס נשמר לפענוח של אותה תשובה בלבד. פענוח אחר באותו task חוזר לפענוח של PTB, עם השורה שלו."""
    stale = report["ptb_error_logs"]["stale_status"]
    assert stale == {"raised": "TelegramError", "ptb_error_loggers": ["telegram.request.BaseRequest"]}, stale


@pytest.mark.parametrize("case", ["200_html_ours", "400_html_ours"])
def test_other_unparsable_answers_keep_the_ptb_error_record(report, case):
    """רק 5xx מפוענח בלי השורה של PTB. ‏200 עם HTML — הבוט לא מקבל עדכונים; 400 — אנחנו שלחנו משהו שגוי. שניהם לא חולפים."""
    logged = report["ptb_error_logs"][case]["ptb_error_records"]
    assert [rec["logger"] for rec in logged] == ["telegram.request.BaseRequest"], logged


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
