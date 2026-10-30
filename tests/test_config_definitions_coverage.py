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
import subprocess
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
    # הסוכן שכותב פואמה על PR: רץ ב-GitHub Actions (.github/workflows/pr-poem.yml), לא בשירות Render
    "POEM_MODEL": "repository variable של GitHub Actions, נקרא ב-.github/pr-poem/pr_poem.py",
    "GITHUB_REPOSITORY": "משתנה ברירת מחדל של GitHub Actions, נקרא ב-.github/pr-poem/pr_poem.py",
    "POEM_APP_TOKEN": "טוקן ההתקנה של ה-GitHub App, מצעד ב-.github/workflows/pr-poem.yml",
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


def test_no_variable_is_documented_twice():
    """אין שני שורות באותו רפרנס לאותו משתנה.

    שתי שורות לאותו משתנה סותרות זו את זו בלי שאיש ישים לב: הן נכתבות בזמנים
    שונים, ולכן הן נבדלות בדיפולט, ברכיב ובניסוח — והקורא מאמין לזו שמצא ראשונה.
    שם חלופי מתועד בשורה משולבת (``A`` / ``B``) או כ-"שם חלופי נתמך" בתוך תיאור,
    ולא בשורה משלו.
    """
    audit = _load_audit_module()
    text = audit.ENV_DOC_FILE.read_text(encoding="utf-8")

    seen: dict[str, int] = {}
    for row in audit.DOC_ROW_RE.findall(text):
        for key in audit.DOC_MENTION_RE.findall(row):
            seen[key] = seen.get(key, 0) + 1

    duplicated = sorted(key for key, count in seen.items() if count > 1)
    assert not duplicated, (
        "משתנים שמתועדים ביותר משורה אחת ב-docs/environment-variables.rst: "
        f"{duplicated}"
    )


def test_declared_vars_appear_in_the_env_reference():
    """כל משתנה מוצהר מופיע גם ברפרנס — שני מקורות האמת לא נפרדים.

    ``docs/environment-variables.rst`` הוא הרפרנס לאנשי DevOps, וההנחיה בראשו
    מחייבת לעדכן אותו בכל שינוי. הבדיקה סוגרת את הפער בכיוון השני: הצהרה בלי
    שורה בתיעוד.
    """
    audit = _load_audit_module()
    declared = audit.collect_declared()
    _, tabled = audit.documented_keys()

    missing = sorted(declared - tabled)
    assert not missing, (
        f"משתנים מוצהרים שאין להם שורה ב-docs/environment-variables.rst "
        f"({len(missing)}): {missing}"
    )


#: הכתובת של שירות ה-WebApp באורגון, שהייתה כתובה בקוד כברירת מחדל בשישה מקומות. מורכבת מחלקים כדי שהקובץ
#: הזה עצמו לא יכיל אותה ברצף.
_OLD_WEBAPP_HOST = "code-keeper-webapp" + ".onrender.com"

#: הקבצים שהוובאפ והבוט טוענים בזמן ריצה ואינם פייתון: תבניות, JS, קובץ הידע של היועץ (נכנס לפרומפט), ומדריך
#: המשתמש (מוגש כשיתוף מובנה). שאר הריפו — תיעוד, README, ``render.yaml`` — נבדק ב-
#: ``test_retired_hosts_appear_only_in_the_changelog``.
_RUNTIME_TEXT_GLOBS = (
    "webapp/templates/**/*.html",
    "webapp/static/**/*.js",
    "services/advisor_knowledge/*.md",
    "webapp/USER_GUIDE.md",
)


def test_webapp_url_has_one_reader():
    """``WEBAPP_URL`` נקרא רק ב-``webapp_url.py``, והמשתנים שאוחדו לתוכו לא נקראים בכלל.

    עד אוקטובר 2026 כתובת ה-WebApp חושבה בכעשרה מקומות, משלושה משתנים ובסדרי עדיפויות שונים. קורא שני — גם
    שדה ב-``BotConfig`` — הוא בדיוק מה שמחזיר ברירת מחדל שקטה למקום אחד ולא לאחרים.
    """
    consumed = _load_audit_module().collect_consumed()

    assert sorted(consumed["WEBAPP_URL"]["files"]) == ["webapp_url.py"], consumed["WEBAPP_URL"]
    for retired in ("PUBLIC_URL", "PUBLIC_BASE_URL"):
        assert retired not in consumed, (retired, consumed.get(retired))


def test_the_old_webapp_host_is_not_in_code_that_runs():
    """אין כתובת ברירת מחדל: הכתובת של השירות באורגון לא מופיעה בקוד הייצור ובקבצים שהוא טוען."""
    audit = _load_audit_module()
    files = list(audit.iter_python_files())
    for pattern in _RUNTIME_TEXT_GLOBS:
        files.extend(p for p in REPO_ROOT.glob(pattern) if ".bundle." not in p.name and ".min." not in p.name)

    offenders = sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in files
        if _OLD_WEBAPP_HOST in p.read_text(encoding="utf-8", errors="replace")
    )
    assert not offenders, offenders


#: הכתובות של השירותים שהושעו באורגון במעבר לפרנקפורט (אוקטובר 2026): הוובאפ ושרת ה-MCP. מורכבות מחלקים, כמו
#: ``_OLD_WEBAPP_HOST``, כדי שהקובץ הזה עצמו לא יכיל אותן ברצף.
_RETIRED_HOSTS = (_OLD_WEBAPP_HOST, "codekeeper-mcp" + ".onrender.com")

#: יומן השינויים מתאר את המעבר מהכתובות הישנות. רשומה היסטורית נכונה לתמיד, ולכן היא המקום היחיד שהן נשארות בו.
_RETIRED_HOSTS_KEPT_IN = frozenset({"docs/whats-new.rst"})


def test_retired_hosts_appear_only_in_the_changelog():
    """אחרי המעבר לפרנקפורט הכתובות של אורגון לא מופיעות בשום קובץ בריפו, חוץ מיומן השינויים.

    הטסט שלמעלה שומר על הקוד שרץ. כאן נבדק כל השאר: README, מדריכים, תיעוד, ``render.yaml`` וסקריפטים. מדריך
    שמעתיקים ממנו כתובת של webhook, או ``WEBAPP_URL`` לדוגמה, היה שולח אותה לשירות מושהה, בלי שום שגיאה. הרשימה
    היא של מה שגיט עוקב אחריו (``git ls-files -z``: בלי ``-z`` גיט מצטט שמות בעברית, וקובץ כזה היה מדלג על הבדיקה —
    ``tests/test_no_committed_pyc.py``). הקבצים נקראים כבתים, כדי שגם קובץ בינארי ייבדק.
    """
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True).stdout
    tracked = [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]
    assert "README.md" in tracked, "git ls-files לא החזיר את קבצי הריפו"

    needles = [host.encode("utf-8") for host in _RETIRED_HOSTS]
    offenders = []
    for rel in tracked:
        path = REPO_ROOT / rel
        if rel in _RETIRED_HOSTS_KEPT_IN or not path.is_file():
            continue
        data = path.read_bytes()
        offenders.extend(f"{rel}: {needle.decode('utf-8')}" for needle in needles if needle in data)
    assert not offenders, sorted(offenders)
