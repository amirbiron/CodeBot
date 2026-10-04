"""``scripts/start_webapp.sh`` מריץ את ניקוי ה-credentials של המראות (#3480) — באמת, ובלי להפיל את השירות.

זה הטריגר היחיד של הניקוי בוובאפ בפרודקשן, ולכן הסקריפט עצמו רץ כאן, כמו ש-Render
מריץ אותו: ``bash scripts/start_webapp.sh``. רק ``gunicorn`` מוחלף בסקריפט קטן
ב-``PATH`` שיוצא בקוד שהטסט בוחר, ו-``python3`` מצביע על המפרש של הטסט. הניקוי עצמו
אמיתי: git אמיתי, מראות אמיתיות ב-``tmp_path``. הוא מקומי בלבד ואינו פונה לרשת.

``subprocess.run`` מחכה ל-EOF על הפלט, והניקוי רץ ברקע עם אותו stdout — כך שהטסט
מחכה גם לו, בלי שינה ובלי ניחוש זמנים.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "start_webapp.sh"
TOKEN = "ghp_TESTSTART0123456789abcdefghijABCDEFG"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="הסקריפט הוא bash")


def _git(*args: str, cwd: pathlib.Path | None = None, env: dict | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _run_start_script(tmp_path: pathlib.Path, mirrors: pathlib.Path, gunicorn_exit: int = 0):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    gunicorn = stubs / "gunicorn"
    gunicorn.write_text(f"#!/usr/bin/env bash\necho \"stub gunicorn $*\"\nexit {gunicorn_exit}\n", encoding="utf-8")
    gunicorn.chmod(0o755)
    (stubs / "python3").symlink_to(sys.executable)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "REPO_MIRROR_PATH": str(mirrors),
        "WEBAPP_ENABLE_WARMUP": "0",
        "ASSET_VERSION": "test",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=120, env=env)


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

    proc = _run_start_script(tmp_path, mirrors)

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "stub gunicorn app:app" in out, "Gunicorn הופעל לפני הניקוי ולא נחסם בגללו"
    assert "mirror credential sweep: checked=1 had_credentials=1 cleaned=1 failed=0" in out, out
    assert "Mirror credential sweep finished" in out, out
    assert TOKEN not in (target / "config").read_text()
    assert TOKEN not in out


def test_a_failed_sweep_is_reported_and_does_not_stop_the_service(tmp_path):
    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    (mirrors / "junk.git").mkdir()  # תיקייה שאינה ריפו: הניקוי שלה נכשל

    proc = _run_start_script(tmp_path, mirrors, gunicorn_exit=0)

    out = proc.stdout + proc.stderr
    assert "failed=1" in out, out
    assert "Mirror credential sweep reported failures" in out, out
    # קוד היציאה של הסקריפט הוא של Gunicorn — כשל בניקוי אינו מפיל את השירות
    assert proc.returncode == 0, out
