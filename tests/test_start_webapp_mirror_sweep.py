"""``scripts/start_webapp.sh`` מריץ את ניקוי ה-credentials של המראות (#3480) — באמת, ובלי להפיל את השירות.

זה הטריגר היחיד של הניקוי בוובאפ בפרודקשן, ולכן הסקריפט עצמו רץ כאן, כמו ש-Render
מריץ אותו — דרך ``tests/_start_webapp_harness.py``, שמחליף רק את ``gunicorn``. הניקוי עצמו
אמיתי: git אמיתי, מראות אמיתיות ב-``tmp_path``. הוא מקומי בלבד ואינו פונה לרשת.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

import pytest

from _start_webapp_harness import STUB_ARGS_PREFIX, run_start_script

TOKEN = "ghp_TESTSTART0123456789abcdefghijABCDEFG"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="הסקריפט הוא bash")


def _git(*args: str, cwd: pathlib.Path | None = None, env: dict | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _legacy_mirror(tmp_path: pathlib.Path, mirrors: pathlib.Path, name: str) -> pathlib.Path:
    """מראה כמו שהקוד יצר עד #3480: הטוקן בתוך ``remote.origin.url``."""
    env = {**os.environ, "HOME": str(tmp_path / "home"), "GIT_CONFIG_NOSYSTEM": "1"}
    (tmp_path / "home").mkdir(exist_ok=True)
    target = mirrors / f"{name}.git"
    _git("init", "-q", "--bare", str(target), env=env)
    _git("remote", "add", "origin", f"https://oauth2:{TOKEN}@github.com/someorg/{name}.git", cwd=target, env=env)
    return target


def test_start_script_cleans_mirrors_and_logs_the_sweep(tmp_path):
    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    target = _legacy_mirror(tmp_path, mirrors, "legacy")

    proc = run_start_script(tmp_path, mirrors)

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    # עם מה בדיוק הוא הופעל — בטסט של נקודת הכניסה (tests/test_webapp_import_paths.py)
    assert STUB_ARGS_PREFIX in out, "Gunicorn הופעל לפני הניקוי ולא נחסם בגללו"
    assert "mirror credential sweep: checked=1 had_credentials=1 cleaned=1 failed=0" in out, out
    assert "Mirror credential sweep finished" in out, out
    assert TOKEN not in (target / "config").read_text()
    assert TOKEN not in out


def test_a_failed_sweep_is_reported_and_does_not_stop_the_service(tmp_path):
    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    (mirrors / "junk.git").mkdir()  # תיקייה שאינה ריפו: הניקוי שלה נכשל

    proc = run_start_script(tmp_path, mirrors, gunicorn_exit=0)

    out = proc.stdout + proc.stderr
    assert "failed=1" in out, out
    assert "Mirror credential sweep reported failures" in out, out
    # קוד היציאה של הסקריפט הוא של Gunicorn — כשל בניקוי אינו מפיל את השירות
    assert proc.returncode == 0, out
