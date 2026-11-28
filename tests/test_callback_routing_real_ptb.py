"""לחיצה אחת על כפתור נכנסת ל-``AdvancedBotHandlers.handle_callback_query`` פעם אחת לכל היותר — מול python-telegram-bot האמיתי.

``handle_callback_query`` רשום בשלושה handlers מוקדמים בקבוצה ‎-5 (מועדפים, שיתוף, תמונה) וב-catch-all בקבוצה 5. ב-PTB כל
קבוצה מפעילה handler תואם אחד, והעיבוד ממשיך לקבוצה הבאה. אילו ה-catch-all של המחלקה היה מקבל גם את הקידומות של
ה-handlers המוקדמים, לחיצה על "⬇️ הורד כקובץ" הייתה רצה פעמיים — שני PNG, או שתי העלאות ל-Drive. אף אחד מאלה אינו קיים
ב-stubs של הסוויטה, ולכן הטסטים כאן מריצים את ``tests/helpers/callback_routing_probe.py`` בתת-תהליך — שם מוסבר מה אמיתי
ומה מדומה.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(150)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE = REPO_ROOT / "tests" / "helpers" / "callback_routing_probe.py"


def _run_probe(tmp_path: Path, env: dict, scenario: str) -> dict:
    result_path = tmp_path / f"callback_routing_{scenario}.json"
    probe_env = dict(env)
    # המסד אינו הנושא כאן: השיתוף לפי ObjectId פונה אליו, ו-``DISABLE_DB`` עונה מיד "לא נמצא"
    probe_env["DISABLE_DB"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", str(PROBE), str(result_path), scenario],
        cwd=tmp_path,
        env=probe_env,
        capture_output=True,
        text=True,
        timeout=100,
    )
    data = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    assert completed.returncode == 0 and data is not None, (
        f"הפרוב לא הסתיים כרגיל (קוד {completed.returncode}).\nדוח: {data}\nstderr:\n{completed.stderr[-3000:]}"
    )
    assert data["outcome"] == "done", data
    assert data["fake_server_errors"] == [], data["fake_server_errors"]
    return data


def _by_data(report: dict) -> dict:
    return {click["data"]: click for click in report["clicks"]}


def test_in_the_real_application_each_click_enters_once_and_still_reaches_the_conversation_catch_all(tmp_path, real_ptb_probe_env):
    clicks = _by_data(_run_probe(tmp_path, real_ptb_probe_env, "app"))

    for data in (
        "img_download:-:a.py", "img_drive:-:a.py", "save_to_drive_a.py", "regenerate_image_a.py", "edit_image_settings_a.py",
        "img_set_theme:dark:a.py", "img_settings_done:a.py", "img_section:hq", "fav_toggle_id:abc", "share_gist_a.py", "cancel_share",
    ):
        assert clicks[data]["advanced_calls"] == 1, (data, clicks[data])
        # ה-catch-all של ``conversation_handlers`` בקבוצה 5 עדיין מקבל את הלחיצה — הוא זה שמוציא ממצב חיפוש
        assert clicks[data]["left_search_mode"], (data, clicks[data])

    # שיתוף לפי ObjectId שייך ל-``conversation_handlers``. כשה-handler המוקדם של השיתוף תפס אותו, ``_share_to_gist``
    # חיפש קובץ בשם ``id:<מזהה>`` וערך את ההודעה ל"לא נמצא" לפני השיתוף האמיתי.
    for data in ("share_gist_id:65a1b2c3d4e5f60718293a4b", "share_pastebin_id:65a1b2c3d4e5f60718293a4b"):
        assert clicks[data]["advanced_calls"] == 0, (data, clicks[data])
        assert clicks[data]["left_search_mode"], (data, clicks[data])


def test_without_the_conversation_catch_all_an_image_click_still_enters_once(tmp_path, real_ptb_probe_env):
    # בלי ה-catch-all של ``conversation_handlers`` שתופס היום את קבוצה 5 ראשון, ה-catch-all של המחלקה הוא הבא בתור —
    # והוא היה מקבל שוב כל לחיצה שה-handler המוקדם כבר טיפל בה
    report = _run_probe(tmp_path, real_ptb_probe_env, "alone")
    clicks = _by_data(report)

    for data, click in clicks.items():
        assert click["advanced_calls"] == 1, (data, click, report["groups"])
