"""בדיקת מודל ה-embedding (``_maybe_start_embedding_health_check``) קמה רק בתהליך השרת של הוובאפ — לא בכל ייבוא.

**למה הקובץ הזה קיים.** הבדיקה פונה ל-Gemini, וכשהמודל מחזיר 404 היא גם משדרגת את הגדרות ה-embedding במסד ומסמנת
את כל הקבצים לאינדוקס מחדש (``sync_probe_and_upgrade`` ב-``services/semantic_embedding_health.py``). עד נובמבר 2026
היא נקראה בזמן הייבוא של ``webapp/app.py``, ולכן קמה בכל תהליך שייבא ממנו סמל אחד: בבוט, שמריץ בעלייה בדיקה משלו
(``maybe_upgrade_embedding_model_on_startup`` ב-``main.py``), בסקריפטים שמייבאים רק את ``get_db``, ובתהליך הטסטים —
שם נמדד שהרצה של טסט בודד שלחה בקשה ל-Gemini, כשהמפתח מוגדר בסביבה.

**מה נבדק, ואיך.** ``sync_probe_and_upgrade`` מוחלף בתת-התהליך בדמה שמדפיסה סימן, כך שאין בקשת רשת. המפתח מוגדר
(ערך מזויף), כדי שהבדיקה תיחסם רק בשומר ``_is_webapp_runtime`` ולא בתנאי של המפתח. המנגנון והמקרים —
``tests/_webapp_import_probe.py``. ריצת הבקרה עם gunicorn היא מה שמוכיח שהבדיקה מסוגלת לראות את ה-thread בכלל.
"""

from __future__ import annotations

import subprocess

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _webapp_import_probe import GUNICORN, NOT_THE_SERVER, THE_SERVER, import_webapp_as, printed_flag

#: הדמה במקום הבדיקה: ``_runner`` מייבא את ``sync_probe_and_upgrade`` מהמודול רק כשהוא רץ, ולכן מקבל אותה.
_STUB_THE_PROBE = (
    "import services.semantic_embedding_health as _health\n"
    "_health.sync_probe_and_upgrade = lambda: print('EMBEDDING_PROBE_CALLED', flush=True)\n"
)

_PRINT_PROBE_STARTED = (
    "_thread = webapp.app._EMBEDDING_HEALTH_THREAD\n"
    "if _thread is not None:\n"
    "    _thread.join(10)\n"
    "print('EMBEDDING_THREAD_STARTED=' + str(_thread is not None))\n"
)

_ENV = {
    "GEMINI_API_KEY": "not-a-real-key",
    "SEMANTIC_SEARCH_ENABLED": "true",
    # שאר המפעילים שנשענים על אותו שומר — כבויים, כדי שריצת הבקרה עם gunicorn לא תכתוב לדיסק ולא תשלח.
    "DISABLE_BACKUP_SCHEDULER": "1",
    "PUSH_NOTIFICATIONS_ENABLED": "false",
}


def _import(argv0: str) -> subprocess.CompletedProcess:
    return import_webapp_as(argv0, before=_STUB_THE_PROBE, after=_PRINT_PROBE_STARTED, env=_ENV)


@pytest.mark.parametrize("argv0", list(NOT_THE_SERVER.values()), ids=list(NOT_THE_SERVER))
def test_importing_the_webapp_outside_the_server_does_not_start_the_health_check(argv0):
    proc = _import(argv0)

    assert not printed_flag(proc, "EMBEDDING_THREAD_STARTED")
    assert "EMBEDDING_PROBE_CALLED" not in proc.stdout
    # ולא בשקט: שורה בלוג אומרת למה לא קמה.
    assert "Skipping embedding health-check: webapp.app imported from non-webapp process" in proc.stderr


@pytest.mark.parametrize("argv0", list(THE_SERVER.values()), ids=list(THE_SERVER))
def test_the_webapp_server_still_runs_the_health_check(argv0):
    """ריצת הבקרה: בלי הבדיקה בשרת, מודל שירד מהמדף לא היה מתגלה בוובאפ."""
    proc = _import(argv0)

    assert printed_flag(proc, "EMBEDDING_THREAD_STARTED")
    assert "EMBEDDING_PROBE_CALLED" in proc.stdout
    assert "Skipping embedding health-check" not in proc.stderr


def test_a_health_check_that_fails_is_logged_with_its_traceback():
    """``_runner`` הוא גבול ה-thread: חריגה בבדיקה נרשמת, ולא נעלמת יחד עם ה-thread."""
    failing = (
        "import services.semantic_embedding_health as _health\n"
        "def _boom():\n"
        "    raise RuntimeError('probe exploded (test)')\n"
        "_health.sync_probe_and_upgrade = _boom\n"
    )
    proc = import_webapp_as(GUNICORN, before=failing, after=_PRINT_PROBE_STARTED, env=_ENV)

    assert printed_flag(proc, "EMBEDDING_THREAD_STARTED")
    assert "Embedding health-check thread failed" in proc.stderr
    assert "Traceback" in proc.stderr
    assert "probe exploded (test)" in proc.stderr
