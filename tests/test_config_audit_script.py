"""בדיקות ל-``scripts/audit_config_definitions.py`` עצמו.

הסקריפט נושא משקל: ``tests/test_config_definitions_coverage.py`` נשען עליו כדי
לאכוף שכל משתנה סביבה מוצהר. כשל שקט בסקריפט — משתנה שהוא לא רואה — מייצר
בדיקה שעוברת על קוד שאינו מכוסה, וזה גרוע מאין בדיקה בכלל.

שלוש הבדיקות כאן נכתבו על שלושה כשלים אמיתיים שנתפסו בריוויו:

1. ``import os as _os`` — הדפוס שב-``main.py`` לפני ה-monkey patch של gevent.
   כל קריאת סביבה דרכו הייתה בלתי-נראית.
2. ייבוא יחסי בתוך ``__init__.py`` — ``from .manager import ...`` לא נפתר, ולכן
   הבוט נראה כאילו אינו טוען את ``database.manager``.
3. נקודות כניסה של סקריפטים — לא היו כלל, ולכן משתנה שנצרך רק בסקריפט קיבל
   רשימת שירותים ריקה.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "audit_config_definitions.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("_config_audit_script", AUDIT_SCRIPT)
    assert spec and spec.loader, f"cannot load {AUDIT_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit():
    return _load_audit_module()


def _env_names_in(audit, source: str) -> set[str]:
    """שמות משתני הסביבה שהסקריפט מזהה בקטע קוד נתון."""
    tree = ast.parse(source)
    os_names, environ_names = audit._os_binding_names(tree)

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name, _, _ = audit._env_read_from_call(node, os_names, environ_names)
        elif isinstance(node, ast.Subscript):
            name = audit._env_read_from_subscript(node, os_names, environ_names)
        else:
            continue
        if name:
            found.add(name)
    return found


# --------------------------------------------------------------------------
# 1. קריאת סביבה דרך שמות שונים של os
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source, expected",
    [
        ('import os\nx = os.getenv("PLAIN")', {"PLAIN"}),
        # main.py עושה בדיוק את זה לפני ה-monkey patch של gevent
        ('import os as _os\nx = _os.getenv("ALIASED")', {"ALIASED"}),
        ('import os as _os\nx = _os.environ.get("ALIASED_ENVIRON")', {"ALIASED_ENVIRON"}),
        ('import os as _os\nx = _os.environ["ALIASED_SUBSCRIPT"]', {"ALIASED_SUBSCRIPT"}),
        # import os.path קושר את השם "os" — כך get-pip.py קורא את הסביבה
        ('import os.path\nx = os.environ.get("VIA_SUBMODULE")', {"VIA_SUBMODULE"}),
        ('from os import environ\nx = environ.get("FROM_IMPORT")', {"FROM_IMPORT"}),
        ('from os import environ as e\nx = e["FROM_IMPORT_ALIASED"]', {"FROM_IMPORT_ALIASED"}),
    ],
)
def test_env_reads_are_found_through_every_os_binding(audit, source, expected):
    assert _env_names_in(audit, source) == expected


@pytest.mark.parametrize(
    "source",
    [
        # אובייקט אחר שיש לו במקרה getenv/environ — אינו os
        'import settings\nx = settings.getenv("NOT_ENV")',
        'x = config.environ.get("NOT_ENV")',
        # import os.path as p אינו קושר את השם os (סמנטיקת פייתון)
        'import os.path as p\nx = os.environ.get("NOT_BOUND")',
    ],
)
def test_non_os_reads_are_not_counted(audit, source):
    assert _env_names_in(audit, source) == set()


# --------------------------------------------------------------------------
# 2. ייבוא יחסי — ``__init__.py`` הוא החבילה עצמה
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "module_name, is_package, level, imported, expected",
    [
        # database/__init__.py: from .manager import DatabaseManager
        ("database", True, 1, "manager", "database.manager"),
        # database/repository.py: from .manager import ...
        ("database.repository", False, 1, "manager", "database.manager"),
        # pkg/sub/mod.py: from ..other import x
        ("pkg.sub.mod", False, 2, "other", "pkg.other"),
        # pkg/__init__.py: from . import mod
        ("database", True, 1, None, "database"),
    ],
)
def test_relative_imports_resolve_to_the_right_package(
    audit, module_name, is_package, level, imported, expected
):
    assert (
        audit.resolve_relative_import(
            module_name, is_package=is_package, level=level, imported=imported
        )
        == expected
    )


def test_package_init_edges_reach_the_real_repo_graph(audit):
    """הבאג המקורי, על הריפו האמיתי: הבוט טוען את database.manager.

    ``main.py`` מייבא את החבילה ``database``, וה-``__init__`` שלה מייבא את
    ``manager`` בייבוא יחסי. לפני התיקון הקשת הזו נעלמה, ו-database.manager
    נראה כאילו הוא של הוובאפ בלבד.
    """
    certain, _ = audit.service_closures()
    assert "database.manager" in certain["bot"]
    assert "database.manager" in certain["webapp"]


# --------------------------------------------------------------------------
# 3. נקודות הכניסה של הסקריפטים
# --------------------------------------------------------------------------

def test_scripts_have_entry_points(audit):
    entries = audit.service_entry_modules()
    assert "scripts" in entries, "אין שירות scripts — משתנה שנצרך רק בסקריפט יקבל רשימה ריקה"
    assert entries["scripts"], "רשימת שורשי הסקריפטים ריקה"
    # כל קובץ תחת scripts/ הוא שורש, וגם הסקריפטים העצמאיים שברשימה המפורשת
    assert "scripts.dev_seed" in entries["scripts"]
    for extra in audit.EXTRA_SCRIPT_ROOTS:
        assert audit._module_name(audit.REPO_ROOT / extra) in entries["scripts"]


def test_script_only_variable_is_attributed_to_scripts(audit):
    """משתנה שנצרך רק בסקריפט מקבל ``scripts`` ולא רשימה ריקה."""
    certain, _ = audit.service_closures()
    consumed = audit.collect_consumed()

    key = "ALLOW_SEED_NON_LOCAL"  # נצרך רק ב-scripts/dev_seed.py
    assert key in consumed, "המשתנה נעלם מהסקריפט — עדכנו את הבדיקה למשתנה אחר שנצרך רק בסקריפט"
    modules = {audit._module_name(audit.REPO_ROOT / f) for f in consumed[key]["files"]}
    services = {service for service, closure in certain.items() if modules & closure}
    assert services == {"scripts"}
