"""שולח הפושים (``push-sender``) קם רק בתהליך השרת של הוובאפ — לא בכל מי שמייבא את ``webapp.app``.

**למה הקובץ הזה קיים.** ``start_sender_if_enabled`` נקרא בזמן הייבוא של ``webapp/app.py``, ולכן
השולח קם בכל תהליך שייבא ממנו סמל אחד: בבוט (ג'וב חימום הקאש ב-``main.py``), בסקריפטים ובתהליכי
הטסטים. בבוט הוא רץ כל דקה ונכשל על מפתח VAPID חסר — ``push_send_missing_vapid_private`` בלוג
של שירות הבוט ב-Render, אוקטובר 2026. בטסטים הוא החזיק את ``_DB_INIT_LOCK`` בזמן חיפוש שרת
מונגו, ונתקע לתמיד כשהחיפוש התחיל בתוך ``freeze_time`` (ראו
``tests/test_freezegun_leaves_the_mongo_driver_clock_alone.py``). ``docs/deployment/workers.rst``
קובע שהשולח הוא thread בתוך תהליך הוובאפ, ושתהליך נפרד אינו שולח.

**מה נבדק, ואיך.** כל טעינה רצה בתת-תהליך נקי עם ``-B`` (בלי ``__pycache__`` בריפו), כי השאלה
היא מה הייבוא עצמו מרים, ובתהליך הטסטים ``webapp.app`` כבר מיובא. ההבדל בין שני המקרים הוא רק
``sys.argv[0]`` — הדבר היחיד ש-``_is_webapp_runtime`` קורא: שם של שרת WSGI (כמו ש-gunicorn
נראה ב-``scripts/start_webapp.sh``) מול כל דבר אחר. ריצת הבקרה עם gunicorn היא מה שמוכיח שהבדיקה
מסוגלת לראות שולח בכלל.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_PROBE = (
    "import sys\n"
    "sys.argv[0] = {argv0!r}\n"
    "import threading\n"
    "import webapp.app\n"
    "names = sorted(t.name for t in threading.enumerate())\n"
    "print('PUSH_SENDER_RUNNING=' + str('push-sender' in names))\n"
)


def _import_webapp_as(argv0: str, tmp_path: Path) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PUSH_NOTIFICATIONS_ENABLED": "true",
        # הנעילה של השולח בתוך tmp_path: כל תת-תהליך משיג אותה בעצמו, ולא מתחרה בתהליך אחר.
        "PUSH_SENDER_LOCK_FILE": str(tmp_path / "push-sender.lock"),
        # מתזמן הגיבויים נשען על אותו שומר, ובריצה עם gunicorn היה קם וכותב לדיסק.
        "DISABLE_BACKUP_SCHEDULER": "1",
    }
    return subprocess.run(
        [sys.executable, "-B", "-c", _PROBE.format(argv0=argv0)],
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


@pytest.mark.parametrize("argv0", ["/srv/app/main.py", "-c", "/usr/bin/pytest"], ids=["bot", "script", "pytest"])
def test_importing_the_webapp_outside_the_server_does_not_start_the_push_sender(tmp_path, argv0):
    assert not _push_sender_running(_import_webapp_as(argv0, tmp_path))


def test_the_webapp_server_still_starts_the_push_sender(tmp_path):
    """ריצת הבקרה: בלי שולח בתהליך הוובאפ אין תזכורות בכלל, לאף משתמש."""
    assert _push_sender_running(_import_webapp_as("/opt/render/project/.venv/bin/gunicorn", tmp_path))
