"""טוען את ``.github/pr-poem/pr_poem.py`` לטסטים — מקום אחד לשני קובצי הטסטים שלו.

הסקריפט רץ ב-GitHub Actions ואינו חבילה (בשם התיקייה יש מקף), ולכן הוא נטען לפי נתיב. הוא נרשם
ב-``sys.modules`` לפני ההרצה, כמו ש-``import`` רגיל עושה, דרך ``monkeypatch`` שמסיר אותו בסוף הטסט
(``load-by-path-without-import-bookkeeping`` ב-amir-bug-patterns).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "pr-poem" / "pr_poem.py"


def load_pr_poem(monkeypatch) -> ModuleType:
    """הסקריפט, טעון מחדש בכל קריאה."""
    spec = importlib.util.spec_from_file_location("_pr_poem_under_test", SCRIPT)
    assert spec and spec.loader, f"לא נמצא {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module
