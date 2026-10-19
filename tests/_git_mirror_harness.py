"""ריפו git אמיתי תחת ``tmp_path``, ומראה שלו בצורה שדפדפן הקוד קורא (``<שם>.git`` בתיקיית המראות).

פונקציות ומחלקה ולא fixtures (T3), כמו ``_docs_index_harness.py``. משמש את הבדיקות שבהן הקומיט שהמסד
או האינדקס מצביעים עליו חייב להיות קומיט אמיתי במראה — למשל השוואת התוכן של קובץ בין שני קומיטים
(``tests/test_repo_browser_docs_page.py``, ``tests/test_repo_browser_docs_page_browser.py``).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict

GIT = shutil.which("git")


def git(*args: str, cwd: Path) -> str:
    """git עם זהות קבועה, כדי שקומיט יעבוד גם בסביבה בלי הגדרות git."""
    assert GIT is not None, "מי שקורא לכאן מדלג כשאין git"
    done = subprocess.run(
        (GIT, "-c", "user.email=t@t", "-c", "user.name=t", *args),
        cwd=str(cwd), check=True, capture_output=True, text=True,
    )
    return done.stdout.strip()


class RepoWithMirror:
    """ריפו עבודה ומראה שלו. ``commit`` כותב קבצים, מקמט, ומעדכן את המראה — ומחזיר את ה-sha."""

    def __init__(self, root: Path, name: str) -> None:
        self.work = root / f"work-{name}"
        self.work.mkdir()
        self.mirrors = root / "mirrors"
        self.mirrors.mkdir(exist_ok=True)
        self.mirror = self.mirrors / f"{name}.git"
        git("init", "-q", "-b", "main", ".", cwd=self.work)

    def commit(self, files: Dict[str, str]) -> str:
        for name, text in files.items():
            target = self.work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            # בתים ולא ``write_text``: במצב טקסט כל ``\n`` נכתב כ-``os.linesep``.
            target.write_bytes(text.encode("utf-8"))
        git("add", "-A", cwd=self.work)
        git("commit", "-qm", "change", cwd=self.work)
        sha = git("rev-parse", "HEAD", cwd=self.work)
        if self.mirror.exists():
            git("--git-dir", str(self.mirror), "fetch", "-q", "origin", cwd=self.work)
        else:
            git("clone", "-q", "--mirror", str(self.work), str(self.mirror), cwd=self.work)
        return sha
