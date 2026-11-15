"""תהליך פייתון שטסט מריץ לא כותב ``__pycache__`` — ``_child_pythons_do_not_write_bytecode``.

הפיקסצ'ר יושב ב-``conftest.py`` שבשורש הריפו, ומגדיר ``PYTHONDONTWRITEBYTECODE`` לכל
תהליך-בן. הטסט כאן מריץ תהליך-בן **בלי** ``-B`` בכוונה: אם הפיקסצ'ר יוסר או יפסיק
לעבוד, תהליך-הבן יכתוב ``__pycache__`` ליד המודול שהוא ייבא. כל הכתיבה תחת
``tmp_path``.
"""

from __future__ import annotations

import os
import subprocess
import sys


def test_child_python_process_does_not_write_bytecode(tmp_path):
    (tmp_path / "probe_module.py").write_text("VALUE = 1\n", encoding="utf-8")

    # בלי ``-B`` ובלי ``env``: מה שנבדק הוא מה שתהליך-בן רגיל יורש מהסוויטה
    proc = subprocess.run(
        [sys.executable, "-c", "import probe_module, sys; print(sys.dont_write_bytecode)"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "True", proc.stdout
    assert not (tmp_path / "__pycache__").exists(), sorted(os.listdir(tmp_path / "__pycache__"))
