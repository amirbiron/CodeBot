"""הבוט האמיתי: לכל עדכון, ולכל ריצה של ג'וב, הקשר לוגים ותגיות Sentry משלו — ושום דבר לא עובר מאחד לשני.

רקע (20.11.2026): בלוגים של הבוט כל שורה של ג'וב מתוזמן נשאה את ה-``request_id``, ה-``user_id`` וה-``command`` של לחיצה
של משתמש מלפני שעה, וב-Sentry כל אירוע נשא את התגיות של המשתמש האחרון. שלושה מנגנונים, כולם ב-docstring של
``observability.isolated_observability_scope``. הטסט מריץ את ``tests/helpers/observability_scope_probe.py`` בתת-תהליך —
``CodeKeeperBot`` האמיתי, ``run_polling`` של PTB ו-APScheduler — מול Bot API מדומה. שם מוסבר התסריט.

הפרוב רץ בלי ``monkey.patch_all`` של gevent (``CODEBOT_DISABLE_GEVENT_PATCH`` ב-``real_ptb_probe_env``), כמו שאר הפרובים
של PTB. ההקשר של משימות asyncio זהה עם הטלאי ובלעדיו: gevent 24.11.1 משאיר את ``contextvars`` המקורי של פייתון
(``contextvars.ContextVar.__module__`` הוא ``_contextvars`` גם אחרי הטלאי).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from observability import _hash_identifier

pytestmark = pytest.mark.timeout(150)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE = REPO_ROOT / "tests" / "helpers" / "observability_scope_probe.py"

#: אותו משתמש כמו ב-``USER_ID`` של הפרוב.
USER_ID = 501


@pytest.fixture
def report(tmp_path, real_ptb_probe_env) -> dict:
    result_path = tmp_path / "observability_scope_report.json"
    completed = subprocess.run(
        [sys.executable, "-B", str(PROBE), str(result_path)],
        cwd=tmp_path,
        env=dict(real_ptb_probe_env),
        capture_output=True,
        text=True,
        timeout=100,
    )
    data = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    assert completed.returncode == 0 and data is not None, (
        f"הפרוב לא הסתיים כרגיל (קוד {completed.returncode}).\nדוח: {data}\nstderr:\n{completed.stderr[-3000:]}"
    )
    assert data["fake_server_errors"] == [], data["fake_server_errors"]
    # הפרוב ראה את מה שחיכה לו: שני העדכונים, והג'וב שהעדכון השני תזמן. אחרת אין כאן שחזור של התנאי.
    assert data["outcome"] == "done", data
    return data


def test_each_update_and_each_job_run_has_its_own_context(report):
    """טסט אחד על ריצה אחת של הפרוב, וכל בדיקה עם הודעה משלה."""
    user_hash = _hash_identifier(USER_ID)
    callback = report["updates"]["1"]
    text = report["updates"]["2"]

    # 1. הלחיצה: ההקשר שלה — request_id, המשתמש, והפקודה.
    assert callback.get("request_id"), callback
    assert callback.get("user_id") == user_hash, callback
    assert callback.get("command") == "bot:probe_button", callback

    # 2. ההודעה שאחריה: request_id חדש — לא אחד לכל משתמש — ובלי ה-command של הלחיצה, שלפני התיקון נשאר בהקשר.
    assert text.get("request_id") and text["request_id"] != callback["request_id"], (callback, text)
    assert "command" not in text, text
    assert text.get("user_id") == user_hash, text

    # 3. הג'וב: כל ריצה בהקשר משלה — לא של אף עדכון, ולא של הריצה הקודמת. לפני התיקון, מהרגע שההודעה תזמנה את הג'וב של
    #    ``log_user_activity``, הריצות נשאו את ה-request_id שלה, את המשתמש, ואת ה-command של הלחיצה.
    runs = report["jobs"]
    assert sum(run["after_text_update_job"] for run in runs) >= 2, runs
    update_request_ids = {callback["request_id"], text["request_id"]}
    for run in runs:
        context = run["context"]
        assert context.get("command") == "job:probe_job", run
        assert "user_id" not in context and "chat_id" not in context, run
        assert context.get("request_id") and context["request_id"] not in update_request_ids, run
    job_request_ids = [run["context"]["request_id"] for run in runs]
    assert len(set(job_request_ids)) == len(job_request_ids), job_request_ids

    # 4. Sentry: אותן תגיות כמו ההקשר. לפני התיקון ה-isolation scope היה אחד לכל התהליך — התגיות של הלחיצה הופיעו על
    #    האירוע של ההודעה, ו-user_id על האירועים של הג'וב.
    events = {event["message"]: event["tags"] for event in report["sentry_events"]}
    assert events["probe:update:1"].get("command") == "bot:probe_button", events
    text_tags = events["probe:update:2"]
    assert text_tags.get("request_id") == text["request_id"], text_tags
    assert text_tags.get("user_id") == user_hash, text_tags
    assert "command" not in text_tags, text_tags
    job_events = {name: tags for name, tags in events.items() if name.startswith("probe:job:")}
    assert len(job_events) == len(runs), (job_events, runs)
    for name, tags in job_events.items():
        assert tags.get("command") == "job:probe_job", (name, tags)
        assert "user_id" not in tags and "chat_id" not in tags, (name, tags)
