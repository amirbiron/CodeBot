"""אכיפה: משתנה סביבה שנצרך בקוד חייב להיות מוצהר ב-Config Inspector.

הטבלה ב-``services/config_inspector_service.py`` נכתבת ביד, ולכן היא נסחפת:
מישהו מוסיף ``os.getenv`` חדש, שוכח להצהיר עליו, והמשתנה חי בפרודקשן בלי
שאפשר לראות אותו בשום מקום. מעבר ידני חד-פעמי לא פותר את זה — הוא נסחף שוב.

הבדיקה מריצה את אותו ניתוח שב-``scripts/audit_config_definitions.py`` ונכשלת
על כל משתנה שנצרך בקוד המוצר ואינו מוצהר, למעט ה-allowlist שלמטה.

**מה שהניתוח הזה לא יכול לתפוס:** קריאה דינמית (``os.getenv(name)`` עם משתנה
ולא מחרוזת) אינה נראית בניתוח סטטי, וכך גם ייבוא דינמי. הבדיקה מונעת סחיפה
של המקרה הנפוץ; היא אינה מוכיחה שהטבלה מלאה.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "audit_config_definitions.py"

#: משתנים שנצרכים בקוד ובכוונה **אינם** מוצהרים ב-Config Inspector.
#: הדף מציג את הקונפיגורציה של שירותי Render; משתנה שאינו כזה רק מוסיף רעש.
#: כל כניסה כאן חייבת נימוק — allowlist בלי נימוקים הופך לפח אשפה.
ALLOWED_UNDECLARED = {
    # תשתית בדיקות — pytest וה-conftest מגדירים אותם, לא DevOps
    "PYTEST_CURRENT_TEST": "מוגדר אוטומטית על ידי pytest",
    "PYTEST_RUNNING": "דגל בדיקות; מתועד בטבלת דגלי הבדיקות",
    "UI_TEST_RUN": "דגל של conftest להרצת בדיקות UI",
    "ONLY_LIGHT_PERF": "דגל של תוסף הביצועים ב-conftest",
    "PERF_HEAVY_PERCENTILE": "דגל של תוסף הביצועים ב-conftest",
    "TEST_USER_ID": "פרמטר לסקריפט scripts/profile_dashboard.py",
    # קוד צד-שלישי שנשמר בריפו
    "PIP_NO_SETUPTOOLS": "דגל של get-pip.py, קובץ צד-שלישי",
    "PIP_NO_WHEEL": "דגל של get-pip.py, קובץ צד-שלישי",
    "PLAYWRIGHT_BROWSERS_PATH": "משתנה תקני של Playwright, לא של המערכת",
    # פנימיים של הפריימוורק ושל מערכת ההפעלה
    "FLASK_RUN_FROM_CLI": "מוגדר על ידי Flask עצמו כשמריצים flask run",
    "WERKZEUG_RUN_MAIN": "מוגדר על ידי Werkzeug ב-reloader",
    "USERPROFILE": "משתנה מערכת של Windows, נקרא רק כ-fallback לנתיב",
    # בניית התיעוד
    "SPHINX_LANGUAGE": "נקרא ב-docs/conf.py בזמן בניית התיעוד",
}


def _load_audit_module():
    """טוען את סקריפט הניתוח כמודול, בלי להוסיף את scripts/ ל-sys.path."""
    spec = importlib.util.spec_from_file_location("_config_audit", AUDIT_SCRIPT)
    assert spec and spec.loader, f"cannot load {AUDIT_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report():
    return _load_audit_module().build_report()


def test_every_consumed_env_var_is_declared(report):
    """כל משתנה שנצרך בקוד מוצהר, או נמצא ב-allowlist עם נימוק."""
    undeclared = {row["key"] for row in report["rows"]}
    missing = sorted(undeclared - set(ALLOWED_UNDECLARED))

    details = []
    for row in report["rows"]:
        if row["key"] in missing:
            files = ", ".join(row["files"][:3])
            details.append(f"  {row['key']}  ←  {files}")

    assert not missing, (
        "משתני סביבה שנצרכים בקוד ואינם מוצהרים ב-CONFIG_DEFINITIONS "
        f"({len(missing)}):\n" + "\n".join(details) + "\n\n"
        "הוסיפו הצהרה ב-services/config_inspector_service.py ושורה ב-"
        "docs/environment-variables.rst (ראו docs/webapp/config-inspector.rst), "
        "או הוסיפו ל-ALLOWED_UNDECLARED עם נימוק אם אין זו קונפיגורציה של שירות."
    )


def test_allowlist_has_no_stale_entries(report):
    """כל כניסה ב-allowlist עדיין נצרכת בקוד ועדיין אינה מוצהרת."""
    undeclared = {row["key"] for row in report["rows"]}
    stale = sorted(set(ALLOWED_UNDECLARED) - undeclared)

    assert not stale, (
        "כניסות מיותרות ב-ALLOWED_UNDECLARED — המשתנים האלה כבר מוצהרים או "
        f"שאינם נצרכים יותר: {stale}"
    )


def test_declared_vars_appear_in_the_env_reference():
    """כל משתנה מוצהר מופיע גם ברפרנס — שני מקורות האמת לא נפרדים.

    ``docs/environment-variables.rst`` הוא הרפרנס לאנשי DevOps, וההנחיה בראשו
    מחייבת לעדכן אותו בכל שינוי. הבדיקה סוגרת את הפער בכיוון השני: הצהרה בלי
    שורה בתיעוד.
    """
    audit = _load_audit_module()
    declared = audit.collect_declared()
    _, tabled = audit._documented()

    missing = sorted(declared - tabled)
    assert not missing, (
        f"משתנים מוצהרים שאין להם שורה ב-docs/environment-variables.rst "
        f"({len(missing)}): {missing}"
    )
