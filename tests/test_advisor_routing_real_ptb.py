"""הניתוב של מצב היועץ באפליקציה האמיתית של הבוט, מול python-telegram-bot האמיתי.

טקסט חופשי בבוט הוא קוד לשמירה, ולכן כל הנכונות של היועץ היא בשאלה איזה
handler תופס כל עדכון: ``ApplicationHandlerStop`` בקבוצה של היועץ, ``allow_reentry``
של ``ConversationHandler``, והסדר מול השיחה הראשית של ``/start``. אף אחד מאלה אינו קיים ב-stubs של הסוויטה, ולכן
הטסטים כאן מריצים את ``tests/helpers/advisor_routing_probe.py`` בתת-תהליך —
שם מוסבר מה אמיתי ומה מדומה.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(150)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE = REPO_ROOT / "tests" / "helpers" / "advisor_routing_probe.py"

#: תקרה לתת-התהליך. גבוהה מ-``DEADLINE_SECONDS`` של הפרוב, כדי שבדרך כלל הוא יספיק לכתוב דוח.
PROBE_TIMEOUT_SECONDS = 100

#: ``ADVISOR_CONTEXT_EXCHANGES`` של הפרוב — שונה מברירת המחדל, כדי שקוד שמתעלם מהמשתנה ייתפס.
PROBE_CONTEXT_EXCHANGES = 3


def _probe_env(tmp_path: Path) -> dict[str, str]:
    """הסביבה של תת-התהליך — מפורשת, ולא עותק של ``os.environ`` (ראו ``test_main_startup_with_real_ptb.py``)."""
    home = tmp_path / "home"
    home.mkdir()
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "TMPDIR": str(tmp_path),
        "PYTHONIOENCODING": "utf-8",
        "BOT_TOKEN": "0:probe",
        "MONGODB_URL": "mongodb://127.0.0.1:1/probe",
        "DISABLE_DB": "1",
        "SEMANTIC_SEARCH_ENABLED": "false",
        "DISABLE_ACTIVITY_REPORTER": "1",
        "CODEBOT_DISABLE_GEVENT_PATCH": "1",
        # הגדרות תקינות, כדי שהיועץ יעלה. מודל השפה עצמו מוחלף בפרוב, ואין פנייה לכתובת.
        "ADVISOR_API_KEY": "probe-key",
        "ADVISOR_BASE_URL": "http://127.0.0.1:9/v1/",
        "ADVISOR_MODEL": "probe-model",
        "ADVISOR_CONTEXT_EXCHANGES": str(PROBE_CONTEXT_EXCHANGES),
    }


def _run_probe(tmp_path: Path, scenario: str, env: dict[str, str] | None = None) -> dict:
    result_path = tmp_path / f"advisor_{scenario}.json"
    completed = subprocess.run(
        [sys.executable, "-B", str(PROBE), str(result_path), scenario],
        cwd=tmp_path,
        env=env if env is not None else _probe_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    report = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    assert completed.returncode == 0 and report is not None, (
        f"הפרוב לא הסתיים כרגיל (קוד {completed.returncode}).\nstderr:\n{completed.stderr[-3000:]}"
    )
    assert report["outcome"] == "done", report.get("traceback")
    # נבדקה האפליקציה של הפרודקשן, ולא אחד ממסלולי ה-fallback של ``CodeKeeperBot``
    assert report["application"] == "telegram.ext._application.Application"
    assert report["fake_server_errors"] == []
    return report


def _sent(step: dict) -> list[dict]:
    return [call["params"] for call in step["bot_api"] if call["method"] == "sendMessage"]


def _buttons(params: dict) -> list[str]:
    markup = params.get("reply_markup") or {}
    return [button.get("callback_data") or button.get("url") for row in markup.get("inline_keyboard", []) for button in row]


@pytest.fixture(scope="module")
def main_report(tmp_path_factory):
    return _run_probe(tmp_path_factory.mktemp("advisor_routing"), "main")


@pytest.fixture(scope="module")
def disabled_report(tmp_path_factory):
    """אותה אפליקציה בלי ``ADVISOR_*`` — היועץ כבוי."""
    tmp_path = tmp_path_factory.mktemp("advisor_disabled")
    env = {k: v for k, v in _probe_env(tmp_path).items() if not k.startswith("ADVISOR_")}
    return _run_probe(tmp_path, "disabled", env=env)


def _steps(report: dict) -> dict[str, dict]:
    return {step["name"]: step for step in report["steps"]}


def test_a_brand_new_user_from_the_deep_link_lands_in_the_advisor(main_report):
    """גולש שמעולם לא פתח את הבוט ונכנס ישר מ-``start=advisor``: פתיחת היועץ, לא הפתיחה של CodeKeeper."""
    steps = _steps(main_report)
    assert main_report["known_users_before"] == [] and main_report["brand_new_user_had_history"] is False

    entry = steps["u1_deep_link"]
    assert [m["text"] for m in _sent(entry)] == [main_report["welcome_text"]]
    assert "advisor_exit" in _buttons(_sent(entry)[0])
    assert entry["llm"] == [] and entry["text_handler"] == []

    question = steps["u1_question"]
    # השאלה הגיעה למודל — עם הפתיחה בזיכרון — ולא לשמירת קוד
    assert question["llm"] == [{"text": "אני עובד עם Claude Code", "history": ["/start advisor", main_report["welcome_text"]]}]
    assert question["text_handler"] == []
    answer, follow_ups = _sent(question)
    assert answer["text"] == "תשובה ל: אני עובד עם Claude Code" and "advisor_exit" in _buttons(answer)
    assert all(data.startswith("advisor_q:") for data in _buttons(follow_ups))


def test_follow_up_click_and_edit_stay_in_the_advisor(main_report):
    steps = _steps(main_report)
    follow_up = steps["u1_follow_up"]
    assert [c["text"] for c in follow_up["llm"]] == ["מה עם גיבוי?"]
    assert "advisor_exit" in _buttons(_sent(follow_up)[0])
    edit = steps["u1_edit"]
    assert edit["llm"] == [] and edit["text_handler"] == [] and edit["bot_api"] == []


def test_exit_button_returns_text_to_the_regular_bot(main_report):
    steps = _steps(main_report)
    assert [m["text"] for m in _sent(steps["u1_exit_button"])] == [main_report["texts"]["exit"]]
    after = steps["u1_text_after_exit"]
    assert after["text_handler"] == [{"user": 1001, "text": "def f(): pass"}] and after["llm"] == []
    stale = steps["u1_stale_exit"]
    assert [c["params"].get("text") for c in stale["bot_api"]] == [main_report["texts"]["already_out"]]


def test_cancel_exits_once_and_main_menu_buttons_leave_the_advisor(main_report):
    steps = _steps(main_report)
    assert [m["text"] for m in _sent(steps["u2_cancel"])] == [main_report["texts"]["exit"]]
    assert steps["u2_text_after_cancel"]["text_handler"] == [{"user": 1002, "text": "print('hi')"}]

    menu = steps["u3_main_menu_button"]
    sent = [m["text"] for m in _sent(menu)]
    # קודם ההודעה שהיועץ נסגר, ואחריה התפריט של הבוט — הכפתור עשה את מה שהוא עושה תמיד
    assert sent[0] == main_report["texts"]["left"] and len(sent) == 2
    assert menu["llm"] == []
    assert steps["u3_text_after_menu"]["text_handler"] == [{"user": 1003, "text": "x = 1"}]


def test_plain_start_and_text_outside_the_advisor_are_untouched(main_report):
    steps = _steps(main_report)
    start = _sent(steps["u4_plain_start"])
    assert len(start) == 1 and start[0]["text"] != main_report["welcome_text"]
    assert steps["u4_text"]["text_handler"] == [{"user": 1004, "text": "שלום"}]
    assert steps["u4_text"]["llm"] == []


def test_over_the_daily_limit_the_model_is_not_called(main_report):
    over = _steps(main_report)["u5_question_over_limit"]
    assert over["llm"] == []
    (reply,) = _sent(over)
    assert reply["text"] == main_report["texts"]["limit"] and "advisor_exit" in _buttons(reply)


def test_the_advisor_has_no_idle_exit(main_report):
    """אין יציאה אוטומטית אחרי זמן בלי פעילות — יוצאים בכפתור, ב-``/cancel`` או בכל פעולה אחרת."""
    assert main_report["conversation_timeouts"] == [None]


def test_the_history_limit_comes_from_the_environment(main_report):
    """``ADVISOR_CONTEXT_EXCHANGES`` עובר מהסביבה, דרך הרישום האמיתי, עד השאילתה של זיכרון השיחה."""
    assert main_report["history_limits"] and set(main_report["history_limits"]) == {PROBE_CONTEXT_EXCHANGES}


def test_without_configuration_the_link_and_text_reach_the_regular_bot(disabled_report):
    """בלי ``ADVISOR_*`` היועץ כבוי: הקישור מגיע ל-``/start`` הרגיל, ו-``/advisor`` אומר שאינו זמין."""
    steps = _steps(disabled_report)
    deep_link = _sent(steps["u7_deep_link"])
    assert [m["text"] for m in deep_link] == [disabled_report["texts"]["regular_welcome"]]
    assert [m["text"] for m in _sent(steps["u7_advisor_command"])] == [disabled_report["texts"]["unavailable"]]
    assert steps["u7_text"]["text_handler"] == [{"user": 1007, "text": "y = 2"}]


def test_without_configuration_old_advisor_buttons_are_answered(disabled_report):
    """כפתור יציאה או שאלת המשך מתקופה שבה היועץ היה פעיל: תשובה קצרה, ולא גלגל טעינה.

    ה-handler הכללי של הלחיצות (``handle_callback_query``) לא מכיר אותם, ומסיים בלי ``query.answer()``.
    """
    steps = _steps(disabled_report)
    for name in ("u7_old_exit_button", "u7_old_follow_up_button"):
        calls = [(c["method"], c["params"].get("text")) for c in steps[name]["bot_api"]]
        assert calls == [("answerCallbackQuery", disabled_report["texts"]["unavailable"])], name


def test_button_answers_fit_the_callback_answer_limit(main_report):
    """הטקסטים שנשלחים ב-``query.answer`` נכנסים למגבלה של טלגרם, כפי ש-PTB המותקן מגדיר אותה."""
    limit = main_report["callback_answer_limit"]
    for key in ("already_out", "unavailable"):
        text = main_report["texts"][key]
        # ביחידות UTF-16, המדידה המחמירה — PTB אינו אומר באיזו יחידה (ראו split_message ב-handlers/advisor_text.py)
        assert len(text.encode("utf-16-le")) // 2 <= limit, key
