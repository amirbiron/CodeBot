"""``webapp/app.py`` נטען בשם אחד, ``webapp.app`` — בגוניקורן, בהרצה ישירה, ובטסטים.

**למה זה חשוב:** פייתון מזהה מודול לפי השם שלו ולא לפי הקובץ. עד אוקטובר 2026 גוניקורן טען
``app:app`` מתוך ``webapp/``, כלומר את הקובץ בשם ``app``, וכל הקוד מייבא ``from webapp.app import
...`` — ולכן הבקשה הראשונה לשם הזה, מתהליך שליחת התזכורות ב-``webapp/push_api.py``, טענה את כל
הקובץ פעם שנייה, עם כל מה שרץ בו בזמן טעינה: התראת העלייה, רישום ה-jobs, תהליכי הרקע. כך גם
``python app.py``, בשם ``__main__``.

**מה מחזיק את זה היום:** ``scripts/start_webapp.sh`` מפעיל את גוניקורן עם ``webapp.app:app``
ועם ``--pythonpath`` לשורש הריפו, מתוך ``webapp/``. בלוק השם שבראש ``app.py`` עוצר טעינה בכל שם
אחר, ובהרצה ישירה טוען את הקובץ פעם אחת בשמו ומריץ ממנו את שרת הפיתוח.

**ומה קרה למחלקת הבאגים שהקובץ הזה נכתב בשבילה במקור** (#3260: ייבוא ממודול שבשורש שהוצב לפני
``sys.path.insert(0, ROOT_DIR)`` הפיל את גוניקורן בלולאת boot): בפרודקשן השורש כבר בנתיב לפני
שהקובץ מתחיל לרוץ, ושורת ההכנה הוסרה. בהרצה ישירה השורש נכנס לנתיב בתוך בלוק השם, וייבוא כזה
שיוצב מעליו יפיל את ``test_running_the_file_directly_serves_from_the_one_module``.

כל טעינה כאן רצה בתת-תהליך עם ``-B``, כדי לא לכתוב ``__pycache__`` לתוך הריפו.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from _start_webapp_harness import run_start_script, stub_invocation

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBAPP_DIR = REPO_ROOT / "webapp"


def _python(args: list[str], *, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", *args],
        cwd=str(WEBAPP_DIR),
        capture_output=True,
        text=True,
        timeout=280,
        env=env,
    )


def _tail(proc: subprocess.CompletedProcess, lines: int = 15) -> str:
    return "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-lines:])


def _json_lines(output: str, prefix: str) -> list:
    return [json.loads(line[len(prefix):]) for line in output.splitlines() if line.startswith(prefix)]


def test_the_webapp_loads_under_one_name_the_way_gunicorn_starts_it():
    """בדיוק מה שגוניקורן 23.0.0 עושה עם הפקודה ש-``scripts/start_webapp.sh`` מריץ.

    ‏``chdir()`` ב-``gunicorn/app/base.py`` מכניס את תיקיית העבודה לראש ``sys.path``, ‏``run()``
    באותו קובץ מכניס לפניה כל נתיב מ-``--pythonpath`` עוד לפני הטעינה, ו-``import_app`` ב-
    ``gunicorn/util.py`` טוען את המודול ב-``importlib.import_module``. כאן קוראים ל-``import_app``
    עצמו, ולא לחיקוי שלו. (‏``gunicorn --check-config`` אינו תחליף: הוא טוען את האפליקציה לפני
    ש-``run()`` מגיע ל-``--pythonpath``.)
    """
    code = textwrap.dedent(
        f"""
        import os, sys
        from gunicorn.util import import_app
        sys.path.insert(0, os.getcwd())
        sys.path.insert(0, {str(REPO_ROOT)!r})
        application = import_app("webapp.app:app")
        print("LOADED", application.import_name, "app" in sys.modules)
        """
    )
    proc = _python(["-c", code])

    assert proc.returncode == 0, "‏app.py אינו נטען כמו שגוניקורן טוען אותו בפרודקשן:\n" + _tail(proc)
    assert "LOADED webapp.app False" in proc.stdout, _tail(proc)


def test_loading_it_under_the_short_name_stops_before_anything_runs():
    """``import app`` מתוך ``webapp/`` — מה שגוניקורן עשה עם ``app:app`` — נעצר בבלוק השם.

    הסוג נבדק ולא רק הכישלון: ``ModuleNotFoundError`` פירושו שמשהו מעל הבלוק כבר ניסה לייבא
    מודול מהשורש, כלומר שקוד רץ בעותק שנטען בשם הלא נכון.
    """
    code = textwrap.dedent(
        """
        try:
            import app
        except ImportError as exc:
            print("REFUSED", type(exc).__name__)
            print(exc)
        else:
            print("LOADED", app.__name__)
        """
    )
    proc = _python(["-c", code])

    assert "REFUSED ImportError" in proc.stdout, _tail(proc)
    assert "webapp.app:app" in proc.stdout, "ההודעה צריכה לומר עם מה כן להפעיל:\n" + _tail(proc)


#: מוחלף ל-``python app.py``: ``Flask.run`` רושם במה הוא נקרא ולא מעלה שרת, ובסוף התהליך
#: נרשמים שמות המודולים שבנו אפליקציית Flask.
_RECORD_FLASK = '''
import atexit
import json

import flask

_built_by = []
_original_init = flask.Flask.__init__


def _init(self, import_name, *args, **kwargs):
    _built_by.append(import_name)
    _original_init(self, import_name, *args, **kwargs)


def _run(self, host=None, port=None, debug=None, **kwargs):
    call = {"import_name": self.import_name, "host": host, "port": port, "debug": debug}
    print("FLASK_RUN " + json.dumps(call), flush=True)


flask.Flask.__init__ = _init
flask.Flask.run = _run
atexit.register(lambda: print("FLASK_BUILT_BY " + json.dumps(_built_by), flush=True))
'''


def test_running_the_file_directly_serves_from_the_one_module(tmp_path):
    """``python app.py`` מתוך ``webapp/``, כמו ב-``docs/quickstart.rst``.

    השרת חייב לרוץ מהאפליקציה של ``webapp.app``, ורק היא נבנית: עותק ``__main__`` שממשיך לרוץ
    היה בונה אפליקציה משלו, וכל ``from webapp.app import`` היה טוען עוד אחת.
    """
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(_RECORD_FLASK, encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(p for p in (str(hook), os.environ.get("PYTHONPATH", "")) if p),
        # ‏_is_webapp_runtime מזהה הרצה ישירה ומעלה את מתזמן הגיבויים — שכותב לדיסק, מחוץ ל-tmp_path
        "DISABLE_BACKUP_SCHEDULER": "1",
        "PUSH_SENDER_LOCK_FILE": str(tmp_path / "push-sender.lock"),
        "PORT": "5099",
    }
    env.pop("WEBAPP_DEV_HOST", None)
    env.pop("DEBUG", None)

    proc = _python(["app.py"], env=env)

    assert proc.returncode == 0, _tail(proc)
    runs = _json_lines(proc.stdout, "FLASK_RUN ")
    assert runs == [{"import_name": "webapp.app", "host": "127.0.0.1", "port": 5099, "debug": False}], runs
    built = _json_lines(proc.stdout, "FLASK_BUILT_BY ")
    assert len(built) == 1, _tail(proc)
    assert [name for name in built[0] if name in ("__main__", "app", "webapp.app")] == ["webapp.app"], built


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, "127.0.0.1"),
        ("", "127.0.0.1"),
        ("   ", "127.0.0.1"),
        ("0.0.0.0", "0.0.0.0"),
        (" 0.0.0.0 ", "0.0.0.0"),
    ],
)
def test_the_dev_server_opens_to_the_network_only_when_asked(monkeypatch, raw, expected):
    """K5: שרת הפיתוח מגיש עם ``DEBUG=true`` את הדיבאגר של Werkzeug, ולכן ברירת המחדל היא ``127.0.0.1``."""
    import webapp.app as webapp_app

    calls = []
    monkeypatch.setattr(webapp_app.app, "run", lambda **kwargs: calls.append(kwargs))
    # בדיקת הקונפיגורציה פונה למונגו עם תקרה של 5 שניות; היא לא הנושא כאן
    monkeypatch.setattr(webapp_app, "check_configuration", lambda: True)
    if raw is None:
        monkeypatch.delenv("WEBAPP_DEV_HOST", raising=False)
    else:
        monkeypatch.setenv("WEBAPP_DEV_HOST", raw)
    monkeypatch.setenv("PORT", "5099")
    monkeypatch.delenv("DEBUG", raising=False)

    webapp_app.run_dev_server()

    assert calls == [{"host": expected, "port": 5099, "debug": False}]


@pytest.mark.skipif(shutil.which("bash") is None, reason="הסקריפט הוא bash")
def test_the_start_script_loads_the_module_by_its_one_name_from_inside_webapp(tmp_path):
    """``scripts/start_webapp.sh`` עצמו, כמו ש-Render מריץ אותו; רק gunicorn מזויף.

    תיקיית העבודה נשארת ``webapp/`` בכוונה: ``BotConfig`` קורא ``.env`` יחסית אליה, וה-``.env``
    שבשורש הריפו נמצא בגיט.
    """
    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()

    proc = run_start_script(tmp_path, mirrors)

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    args, cwd = stub_invocation(out)
    assert args[:1] == ["webapp.app:app"], args
    assert "--pythonpath" in args, args
    assert args[args.index("--pythonpath") + 1] == str(REPO_ROOT), args
    assert cwd == str(WEBAPP_DIR)
