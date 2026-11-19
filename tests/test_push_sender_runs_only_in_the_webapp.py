"""שולח הפושים (``push-sender``) קם רק בתהליך השרת של הוובאפ — לא בכל מי שמייבא את ``webapp.app``.

**למה הקובץ הזה קיים.** ``start_sender_if_enabled`` נקרא בזמן הייבוא של ``webapp/app.py``, ולכן
השולח קם בכל תהליך שייבא ממנו סמל אחד: בבוט (ג'וב חימום הקאש ב-``main.py``), בסקריפטים ובתהליכי
הטסטים. בבוט הוא רץ כל דקה ונכשל על מפתח VAPID חסר — ``push_send_missing_vapid_private`` בלוג
של שירות הבוט ב-Render, אוקטובר 2026. בטסטים הוא החזיק את ``_DB_INIT_LOCK`` בזמן חיפוש שרת
מונגו, ונתקע לתמיד כשהחיפוש התחיל בתוך ``freeze_time`` (ראו
``tests/test_freezegun_leaves_the_mongo_driver_clock_alone.py``). ``docs/deployment/workers.rst``
קובע שהשולח הוא thread בתוך תהליך הוובאפ, ושתהליך נפרד אינו שולח.

**מה נבדק, ואיך.** כל טעינה רצה בתת-תהליך נקי, וההבדל בין המקרים הוא רק ``sys.argv[0]`` — המנגנון
והמקרים ב-``tests/_webapp_import_probe.py``. ריצת הבקרה עם gunicorn היא מה שמוכיח שהבדיקה מסוגלת
לראות שולח בכלל.

**ושולח שלא קם — נראה בלוג.** עד התיקון ``start_sender_if_enabled`` בלע כשל בהרמת ה-thread וגם
את סוף הלולאה, ושולח מושבת נראה כמו עלייה תקינה. לכן ה-probe מדפיס את הלוג ל-stderr, ויכול לגרום
להרמת ה-thread להיכשל.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _webapp_import_probe import GUNICORN, NOT_THE_SERVER, THE_SERVER, import_webapp_as, printed_flag

_FAIL_PUSH_SENDER_START = (
    "_real_start = threading.Thread.start\n"
    "def _start(self):\n"
    "    if self.name == 'push-sender':\n"
    "        raise RuntimeError('cannot start new thread (probe)')\n"
    "    return _real_start(self)\n"
    "threading.Thread.start = _start\n"
)

_PRINT_PUSH_SENDER_RUNNING = (
    "time.sleep(0.5)\n"
    "names = sorted(t.name for t in threading.enumerate())\n"
    "print('PUSH_SENDER_RUNNING=' + str('push-sender' in names))\n"
)


def _import_webapp_as(
    argv0: str, tmp_path: Path, *, fail_thread_start: bool = False, extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    env = {
        "PUSH_NOTIFICATIONS_ENABLED": "true",
        # הנעילה של השולח בתוך tmp_path: כל תת-תהליך משיג אותה בעצמו, ולא מתחרה בתהליך אחר.
        "PUSH_SENDER_LOCK_FILE": str(tmp_path / "push-sender.lock"),
        # מתזמן הגיבויים נשען על אותו שומר, ובריצה עם gunicorn היה קם וכותב לדיסק.
        "DISABLE_BACKUP_SCHEDULER": "1",
        # גם בדיקת מודל ה-embedding נשענת על אותו שומר, ובריצה עם gunicorn הייתה פונה ל-API של Gemini.
        # בלי מפתח ``_maybe_start_embedding_health_check`` לא מרים אותה.
        "GEMINI_API_KEY": "",
        **(extra_env or {}),
    }
    before = _FAIL_PUSH_SENDER_START if fail_thread_start else ""
    return import_webapp_as(argv0, before=before, after=_PRINT_PUSH_SENDER_RUNNING, env=env)


def _push_sender_running(proc: subprocess.CompletedProcess) -> bool:
    return printed_flag(proc, "PUSH_SENDER_RUNNING")


@pytest.mark.parametrize("argv0", list(NOT_THE_SERVER.values()), ids=list(NOT_THE_SERVER))
def test_importing_the_webapp_outside_the_server_does_not_start_the_push_sender(tmp_path, argv0):
    assert not _push_sender_running(_import_webapp_as(argv0, tmp_path))


@pytest.mark.parametrize("argv0", list(THE_SERVER.values()), ids=list(THE_SERVER))
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
