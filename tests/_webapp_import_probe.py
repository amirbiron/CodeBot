"""ייבוא של ``webapp.app`` בתת-תהליך נקי, בתור תהליך מסוים — לבדיקה של מה שהייבוא עצמו מרים.

``webapp/app.py`` מרים בזמן הטעינה כמה תהליכוני רקע, ואת חלקם רק כש-``_is_webapp_runtime`` מזהה את שרת הוובאפ —
לפי ``sys.argv[0]`` בלבד. בתהליך הטסטים ``webapp.app`` כבר מיובא, ולכן כל טעינה כאן רצה בתת-תהליך עם ``-B`` (בלי
``__pycache__`` בריפו) ועם ``sys.argv[0]`` שנבחר. ההבדל בין המקרים הוא רק הערך הזה.

שני קבצים נשענים על זה: ``tests/test_push_sender_runs_only_in_the_webapp.py`` ו-
``tests/test_embedding_health_check_runs_only_in_the_webapp.py``. המנגנון והמקרים כאן, ולא עותק בכל קובץ.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: gunicorn כמו ש-``scripts/start_webapp.sh`` מריץ אותו ב-Render.
GUNICORN = "/opt/render/project/.venv/bin/gunicorn"

#: תהליכים שאינם שרת הוובאפ. שני האחרונים — שם של שרת בתוך הנתיב ולא כשם הקובץ: הזיהוי השווה פעם מילים כמו
#: "flask" לכל הנתיב, ולכן סקריפט שיושב בתיקייה בשם ``flask-migrations`` נחשב לשרת.
NOT_THE_SERVER = {
    "bot": "/srv/app/main.py",
    "script": "-c",
    "pytest": "/usr/bin/pytest",
    "script-in-a-flask-folder": "/srv/flask-migrations/reindex.py",
    "bot-in-a-gunicorn-folder": "/home/dev/gunicorn-tools/CodeBot/main.py",
}

#: שרת הוובאפ — גם ב-``python -m gunicorn``, שבו ``sys.argv[0]`` הוא ``gunicorn/__main__.py`` (נמדד ב-Python 3.13:
#: ``python -m <חבילה>`` מציב שם את הנתיב המלא ל-``__main__.py``).
THE_SERVER = {
    "gunicorn": GUNICORN,
    "python-m-gunicorn": "/opt/render/project/.venv/lib/python3.11/site-packages/gunicorn/__main__.py",
}

_PROBE = (
    "import logging, sys, threading, time\n"
    "logging.basicConfig(level=logging.INFO, stream=sys.stderr)\n"
    "sys.argv[0] = {argv0!r}\n"
    "{before}\n"
    "import webapp.app\n"
    "{after}\n"
)


def import_webapp_as(
    argv0: str, *, before: str = "", after: str = "", env: dict | None = None,
) -> subprocess.CompletedProcess:
    """מייבא את ``webapp.app`` בתת-תהליך שבו ``sys.argv[0]`` הוא ``argv0``.

    ``before`` ו-``after`` — קוד שרץ לפני הייבוא ואחריו (החלפת פונקציה בדמה, הדפסה של מה שקם). ``env`` — מעל
    ``os.environ``. הלוג של התת-תהליך יוצא ל-stderr, ברמת INFO.
    """
    return subprocess.run(
        [sys.executable, "-B", "-c", _PROBE.format(argv0=argv0, before=before, after=after)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=50,
        env={**os.environ, **(env or {})},
    )


def printed_flag(proc: subprocess.CompletedProcess, name: str) -> bool:
    """הערך של שורת ``NAME=True`` / ``NAME=False`` שהתת-תהליך הדפיס — ושהוא הסתיים בהצלחה והדפיס אותה פעם אחת."""
    lines = [line for line in proc.stdout.splitlines() if line.startswith(f"{name}=")]
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
    assert proc.returncode == 0 and len(lines) == 1, tail
    return lines[0].split("=", 1)[1] == "True"
