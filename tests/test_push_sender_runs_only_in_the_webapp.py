"""שולח הפושים (``push-sender``) קם רק בתהליך השרת של הוובאפ — לא בכל מי שמייבא את ``webapp.app``.

**למה הקובץ הזה קיים.** ``start_sender_if_enabled`` נקרא בזמן הייבוא של ``webapp/app.py``, ולכן
השולח קם בכל תהליך שייבא ממנו סמל אחד: בבוט (ג'וב חימום הקאש ב-``main.py``), בסקריפטים ובתהליכי
הטסטים. בבוט הוא רץ כל דקה ונכשל על מפתח VAPID חסר — ``push_send_missing_vapid_private`` בלוג
של שירות הבוט ב-Render, אוקטובר 2026. בטסטים הוא החזיק את ``_DB_INIT_LOCK`` בזמן חיפוש שרת
מונגו, ונתקע לתמיד כשהחיפוש התחיל בתוך ``freeze_time`` (ראו
``tests/test_freezegun_leaves_the_mongo_driver_clock_alone.py``). ``docs/deployment/workers.rst``
קובע שהשולח הוא thread בתוך תהליך הוובאפ, ושתהליך נפרד אינו שולח.

**מה נבדק, ואיך.** כל טעינה רצה בתת-תהליך נקי עם ``-B`` (בלי ``__pycache__`` בריפו), כי השאלה
היא מה הייבוא עצמו מרים, ובתהליך הטסטים ``webapp.app`` כבר מיובא. ההבדל בין המקרים הוא רק
``sys.argv[0]`` — הדבר היחיד ש-``_is_webapp_runtime`` קורא: שם של שרת WSGI (כמו ש-gunicorn
נראה ב-``scripts/start_webapp.sh``) מול כל דבר אחר. ריצת הבקרה עם gunicorn היא מה שמוכיח שהבדיקה
מסוגלת לראות שולח בכלל.

**השם, לא התווים.** הזיהוי השווה פעם מילים כמו "flask" לכל הנתיב, ולכן סקריפט שיושב בתיקייה
בשם ``flask-migrations`` נחשב לשרת. המקרים כאן כוללים נתיב כזה, וגם את ``python -m gunicorn``,
שבו ``sys.argv[0]`` הוא ``gunicorn/__main__.py`` — נמדד ב-Python 3.13: ``python -m <חבילה>``
מציב שם את הנתיב המלא ל-``__main__.py``.

**ושולח שלא קם — נראה בלוג.** עד התיקון ``start_sender_if_enabled`` בלע כשל בהרמת ה-thread וגם
את סוף הלולאה, ושולח מושבת נראה כמו עלייה תקינה. לכן ה-probe מדפיס את הלוג ל-stderr, ויכול לגרום
להרמת ה-thread להיכשל.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GUNICORN = "/opt/render/project/.venv/bin/gunicorn"

_PROBE = (
    "import logging, sys, threading, time\n"
    "logging.basicConfig(level=logging.INFO, stream=sys.stderr)\n"
    "sys.argv[0] = {argv0!r}\n"
    "if {fail_thread_start!r}:\n"
    "    _real_start = threading.Thread.start\n"
    "    def _start(self):\n"
    "        if self.name == 'push-sender':\n"
    "            raise RuntimeError('cannot start new thread (probe)')\n"
    "        return _real_start(self)\n"
    "    threading.Thread.start = _start\n"
    "import webapp.app\n"
    "time.sleep(0.5)\n"
    "names = sorted(t.name for t in threading.enumerate())\n"
    "print('PUSH_SENDER_RUNNING=' + str('push-sender' in names))\n"
)


def _import_webapp_as(
    argv0: str, tmp_path: Path, *, fail_thread_start: bool = False, extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PUSH_NOTIFICATIONS_ENABLED": "true",
        # הנעילה של השולח בתוך tmp_path: כל תת-תהליך משיג אותה בעצמו, ולא מתחרה בתהליך אחר.
        "PUSH_SENDER_LOCK_FILE": str(tmp_path / "push-sender.lock"),
        # מתזמן הגיבויים נשען על אותו שומר, ובריצה עם gunicorn היה קם וכותב לדיסק.
        "DISABLE_BACKUP_SCHEDULER": "1",
        # בלי מפתח, ``_maybe_start_embedding_health_check`` לא פונה בייבוא ל-API של Gemini.
        "GEMINI_API_KEY": "",
        **(extra_env or {}),
    }
    return subprocess.run(
        [sys.executable, "-B", "-c", _PROBE.format(argv0=argv0, fail_thread_start=fail_thread_start)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=50,
        env=env,
    )


def _push_sender_running(proc: subprocess.CompletedProcess) -> bool:
    lines = [line for line in proc.stdout.splitlines() if line.startswith("PUSH_SENDER_RUNNING=")]
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
    assert proc.returncode == 0 and len(lines) == 1, tail
    return lines[0].split("=", 1)[1] == "True"


@pytest.mark.parametrize(
    "argv0",
    [
        "/srv/app/main.py",
        "-c",
        "/usr/bin/pytest",
        "/srv/flask-migrations/reindex.py",
        "/home/dev/gunicorn-tools/CodeBot/main.py",
    ],
    ids=["bot", "script", "pytest", "script-in-a-flask-folder", "bot-in-a-gunicorn-folder"],
)
def test_importing_the_webapp_outside_the_server_does_not_start_the_push_sender(tmp_path, argv0):
    assert not _push_sender_running(_import_webapp_as(argv0, tmp_path))


@pytest.mark.parametrize(
    "argv0",
    [GUNICORN, "/opt/render/project/.venv/lib/python3.11/site-packages/gunicorn/__main__.py"],
    ids=["gunicorn", "python-m-gunicorn"],
)
def test_the_webapp_server_still_starts_the_push_sender(tmp_path, argv0):
    """ריצת הבקרה: בלי שולח בתהליך הוובאפ אין תזכורות בכלל, לאף משתמש."""
    proc = _import_webapp_as(argv0, tmp_path)

    assert _push_sender_running(proc)
    assert "Push sender thread started" in proc.stderr


def test_a_push_sender_that_cannot_start_is_logged_not_swallowed(tmp_path):
    proc = _import_webapp_as(GUNICORN, tmp_path, fail_thread_start=True)

    assert not _push_sender_running(proc)
    assert "Failed to start push sender" in proc.stderr
    assert "cannot start new thread (probe)" in proc.stderr


def test_a_push_sender_loop_that_dies_is_logged(tmp_path):
    """ערך לא מספרי ב-``PUSH_SEND_INTERVAL_SECONDS`` מפיל את הלולאה לפני הסבב הראשון — שולח מת בשקט עד התיקון."""
    proc = _import_webapp_as(GUNICORN, tmp_path, extra_env={"PUSH_SEND_INTERVAL_SECONDS": "one-minute"})

    assert "push sender loop stopped" in proc.stderr
    assert "ValueError" in proc.stderr
