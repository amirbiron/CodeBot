"""מריץ את ``scripts/start_webapp.sh`` עצמו, כמו ש-Render מריץ אותו: ``bash scripts/start_webapp.sh``.

רק ``gunicorn`` מוחלף, בסקריפט קטן ב-``PATH`` שמדפיס את הארגומנטים שקיבל ואת תיקיית העבודה שלו,
ויוצא בקוד שהטסט בוחר. ``python3`` מצביע על המפרש של הטסט, כי הסקריפט מריץ בעזרתו את ניקוי המראות
ברקע. כל מה שנכתב — הסקריפט המזויף, ``HOME`` והמראות — יושב תחת ``tmp_path``.

``subprocess.run`` מחכה ל-EOF על הפלט, והניקוי רץ ברקע עם אותו stdout — כך שהקורא מקבל את הפלט
המלא, כולל של הניקוי, בלי שינה ובלי ניחוש זמנים.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "start_webapp.sh"

#: קידומת השורה שבה gunicorn המזויף מדפיס את כל הארגומנטים שלו, בשורה אחת לקריאה.
STUB_ARGS_PREFIX = "stub gunicorn args: "
#: קידומת השורות שבהן הוא מדפיס כל ארגומנט בנפרד, לפי הסדר — כך נתיב עם רווח לא מתפרק.
STUB_ARG_PREFIX = "stub gunicorn arg: "
#: קידומת השורה שבה הוא מדפיס את תיקיית העבודה שלו.
STUB_CWD_PREFIX = "stub gunicorn cwd: "


def run_start_script(
    tmp_path: pathlib.Path, mirrors: pathlib.Path, gunicorn_exit: int = 0
) -> subprocess.CompletedProcess:
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    gunicorn = stubs / "gunicorn"
    gunicorn.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "{STUB_ARGS_PREFIX}$*"\n'
        f'for arg in "$@"; do echo "{STUB_ARG_PREFIX}$arg"; done\n'
        f'echo "{STUB_CWD_PREFIX}$(pwd -P)"\n'
        f"exit {gunicorn_exit}\n",
        encoding="utf-8",
    )
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


def stub_invocation(output: str) -> tuple[list[str], str]:
    """הארגומנטים ש-gunicorn המזויף קיבל, לפי הסדר, ותיקיית העבודה שבה הוא רץ."""
    lines = output.splitlines()
    args = [line[len(STUB_ARG_PREFIX):] for line in lines if line.startswith(STUB_ARG_PREFIX)]
    cwds = [line[len(STUB_CWD_PREFIX):] for line in lines if line.startswith(STUB_CWD_PREFIX)]
    assert len(cwds) == 1, f"gunicorn המזויף הופעל {len(cwds)} פעמים, לא פעם אחת:\n{output}"
    return args, cwds[0]
