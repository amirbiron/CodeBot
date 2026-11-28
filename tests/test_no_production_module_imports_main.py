"""שום מודול של קוד הייצור לא מייבא את ``main``.

הבוט רץ כ-``python main.py``, כלומר המודול שלו נקרא ``__main__``, ו-``sys.modules`` אינו מכיר את השם ``main``. לכן
``from main import ...`` מתוך הבוט שרץ אינו מוצא את מה שכבר נטען — הוא טוען את ``main.py`` שוב, כמודול חדש, ומריץ את כל
הרמה העליונה שלו בתוך הטיפול בעדכון. חלק מזה עוצר את עצמו (``init_sentry`` ו-``setup_telemetry`` זוכרים שכבר רצו), וחלק
לא: ה-event loop policy מוחלפת במופע חדש בזמן שהלולאה רצה, ``atexit`` מקבל פונקציית סגירה שנייה, ואירוע ``bot_start``
מדווח על הפעלה שלא הייתה. זה קרה בפרודקשן ב-20.11.2026 (הלוגר ``main`` במקום ``__main__``, באמצע ריצה):
``database/blocked_users_manager.py`` ייבא ``get_admin_ids`` מ-``main`` בשביל בדיקת אדמין. מי שצריך לדעת מי אדמין מייבא
את ``user_roles``.

הבדיקה סטטית, על עץ ה-AST של כל קובץ ``.py`` בריפו מחוץ ל-``tests/`` ולקובצי טסט: ``import main``, ``from main import``,
``importlib.import_module("main")`` ו-``__import__("main")``.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: תיקיות שאינן קוד שרץ בתהליך של הבוט: הטסטים עצמם, תיקיות כלים וסביבות, ו-``tmp/`` — סקריפטי שחזור שרצים כתהליך
#: משלהם (למשל ``tmp/repro_cache_test.py``), ושם ``import main`` טוען את הקובץ פעם אחת בלבד.
_SKIPPED_DIRS = {"tests", "tmp", ".git", "node_modules", ".venv", "venv", "__pycache__", "_build"}


def _is_test_file(path: Path) -> bool:
    return path.name.startswith("test_") or path.name == "conftest.py"


def _production_python_files() -> list[Path]:
    files = []
    for path in REPO_ROOT.rglob("*.py"):
        relative = path.relative_to(REPO_ROOT)
        if _SKIPPED_DIRS.intersection(relative.parts[:-1]):
            continue
        if _is_test_file(path) or relative == Path("main.py"):
            continue
        files.append(path)
    return files


def _imports_of_main(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(alias.name == "main" for alias in node.names):
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "main":
            lines.append(node.lineno)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"import_module", "__import__"} and node.args[0].value == "main":
                lines.append(node.lineno)
    return lines


def test_the_scan_sees_the_production_tree():
    """רצפה: בלי זה, שינוי בנתיבים שמשאיר את הסריקה ריקה היה עובר בשקט."""
    files = {path.relative_to(REPO_ROOT).as_posix() for path in _production_python_files()}
    assert "database/blocked_users_manager.py" in files
    assert "services/telegram_observability_scope.py" in files
    assert len(files) > 100, len(files)


def test_no_production_module_imports_main():
    offenders = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(f"{path.relative_to(REPO_ROOT).as_posix()}:{line}" for line in _imports_of_main(tree))
    assert offenders == [], (
        "קוד ייצור מייבא את main — בבוט שרץ כ-__main__ זה טוען את main.py פעם שנייה. "
        f"מזהי אדמין: user_roles. המקומות: {offenders}"
    )
