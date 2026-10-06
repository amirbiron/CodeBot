"""‏``scripts/measure_recycle_bin_pipeline.py`` רץ לבד, ולא מדליף את הכתובת.

שני הכשלים שנתפסו בריוויו, ושניהם קורים **לפני** שהמדידה מתחילה:

- **הייבוא דרש את התצורה של הבוט.** ``database.manager`` טוען את ``config``,
  שדורש ``BOT_TOKEN``. בתיקייה בלי ``.env`` הסקריפט קרס — וההודעה של pydantic
  על שדה חסר מדפיסה את ערכי השדות שכן נמסרו, כלומר גם את ``MONGODB_URL``.
  הסקריפט הכניס לשם את הכתובת הנמדדת, וכתובת יכולה לשאת סיסמה.
- **הודעת הכשל הדפיסה את הכתובת** כשהשרת לא ענה.

לכן הבדיקה מריצה את הסקריפט כמו מי שמשתמש בו: תת-תהליך, סביבה נקייה בלי
``BOT_TOKEN``, תיקייה זמנית בלי ``.env``, וכתובת עם סיסמה לפורט שאין מאחוריו
שרת. בלי מונגו, ולכן היא רצה גם ב-CI.
"""

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_recycle_bin_pipeline.py"
#: קצרה בכוונה: pydantic מקצר באמצע ערך ארוך, ואז דליפה בקוד הישן לא הייתה
#: נראית בפלט — והבדיקה הייתה עוברת עליו.
SECRET = "pw9zq"
URI = f"mongodb://u:{SECRET}@127.0.0.1:1/"


def test_runs_without_the_bot_config_and_never_prints_the_uri(tmp_path):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)}

    proc = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), URI],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=50,
    )
    output = proc.stdout + proc.stderr

    assert SECRET not in output, "הסיסמה שבכתובת הודפסה"
    # 2 הוא "אין חיבור" — כלומר הייבוא עבר בלי ``BOT_TOKEN`` והגיע עד ה-ping.
    # קריסה בייבוא יוצאת ב-1.
    assert proc.returncode == 2, output[-2000:]
    assert "אין חיבור למונגו" in proc.stdout, output[-2000:]
