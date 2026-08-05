"""
בדיקות לכרטיס "הריפוים שלי" בדשבורד (אדמין בלבד).

הכרטיס מחליף את כרטיס "מה חדש", נטען מ-config/admin_repos.yaml,
וכל קישור בו נפתח בטאב חדש כדי ש-CodeKeeper יישאר פתוח מאחור.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_TEMPLATE = REPO_ROOT / "webapp" / "templates" / "dashboard.html"
ADMIN_REPOS_YAML = REPO_ROOT / "config" / "admin_repos.yaml"


def _read_template() -> str:
    return DASHBOARD_TEMPLATE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# קובץ ההגדרות
# ---------------------------------------------------------------------------


def test_admin_repos_yaml_exists_and_is_valid():
    """קובץ ההגדרות חייב להתקיים ולהיות YAML תקין עם המבנה הצפוי."""
    yaml = pytest.importorskip("yaml")
    assert ADMIN_REPOS_YAML.exists(), "חסר config/admin_repos.yaml"

    data = yaml.safe_load(ADMIN_REPOS_YAML.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    repos = data.get("repos")
    assert isinstance(repos, list) and repos, "צריכה להיות רשימת repos לא ריקה"

    for repo in repos:
        assert repo.get("name"), "לכל ריפו חייב להיות name"
        url = repo.get("url", "")
        assert url.startswith(("http://", "https://")), f"url לא תקין: {url}"


# ---------------------------------------------------------------------------
# הרשאות – הכרטיס גלוי לאדמין בלבד
# ---------------------------------------------------------------------------


def test_card_is_wrapped_in_admin_condition():
    """
    ה-markup של הכרטיס חייב להיות בתוך תנאי user_is_admin,
    אחרת הרשימה תגיע ל-HTML של כל משתמש.
    """
    tpl = _read_template()
    match = re.search(
        r"\{%\s*if user_is_admin\s*%\}(.*?)\{%\s*endif\s*%\}",
        tpl,
        re.S,
    )
    assert match, "לא נמצא בלוק {% if user_is_admin %} סביב הכרטיס"
    assert "admin-repos-card" in match.group(1), "הכרטיס אינו בתוך תנאי האדמין"


def test_route_loads_repos_only_for_admin():
    """הראוט חייב לטעון את הרשימה רק כשהמשתמש אדמין."""
    route = (REPO_ROOT / "webapp" / "routes" / "dashboard_routes.py").read_text(
        encoding="utf-8"
    )
    assert "_load_admin_repos() if user_is_admin else []" in route, (
        "הרשימה חייבת להיטען רק לאדמין, לא תמיד"
    )
    assert "admin_repos=admin_repos" in route, "admin_repos לא מועבר לתבנית"


# ---------------------------------------------------------------------------
# הקישורים – חייבים להיפתח בטאב חדש
# ---------------------------------------------------------------------------


def test_repo_links_open_in_new_tab():
    """
    זו הדרישה המרכזית: לחיצה על ריפו לא אמורה להחליף את CodeKeeper.
    target="_blank" פותח טאב חדש, ו-rel מגן מפני tabnabbing.
    """
    tpl = _read_template()
    links = re.findall(r'<a\b[^>]*class="admin-repo-item"[^>]*>', tpl, re.S)
    assert links, "לא נמצא קישור ריפו בתבנית"

    for link in links:
        assert 'target="_blank"' in link, f"קישור ללא target=_blank: {link}"
        assert "noopener" in link, f"קישור ללא rel=noopener: {link}"
        assert "noreferrer" in link, f"קישור ללא rel=noreferrer: {link}"


# ---------------------------------------------------------------------------
# הפריסה – אסור שיישאר רווח ריק אצל משתמש רגיל
# ---------------------------------------------------------------------------


def test_grid_collapses_for_non_admin():
    """
    משתמש רגיל לא רואה את הכרטיס האמצעי, ולכן חייבת להיות מחלקת גריד
    שמסירה את האזור – אחרת נשאר חור בפריסה.
    """
    tpl = _read_template()
    assert "no-mid-widget" in tpl
    assert "{{ '' if user_is_admin else ' no-mid-widget' }}" in tpl, (
        "מחלקת הגריד לא נקבעת לפי user_is_admin"
    )
    # המחלקה חייבת להיות מוגדרת בכל שלושת גדלי המסך
    assert tpl.count(".dashboard-grid.no-mid-widget") == 3, (
        "no-mid-widget חייבת להיות מוגדרת ל-mobile, tablet ו-desktop"
    )


def test_grid_area_has_no_stale_whatsnew_references():
    """אחרי ההחלפה אסור שיישארו הפניות לאזור הישן, שאף ווידג'ט כבר לא תופס."""
    tpl = _read_template()
    assert "whatsnew" not in tpl, "נשארה הפניה לאזור הגריד הישן"
    assert "widget-whats-new" not in tpl
    assert ".widget-admin-repos { grid-area: midcard; }" in tpl


def test_grid_css_is_not_duplicated():
    """
    בלוק הגריד היה משוכפל בעבר, מה שגרם לכך שעריכה של אחד מהם נדרסה
    על ידי השני. הבדיקה מוודאת שהוא מוגדר פעם אחת בלבד.
    """
    tpl = _read_template()
    assert tpl.count("=== Dashboard grid layout ===") == 1
    assert tpl.count(".dashboard-grid {\n") == 1


# ---------------------------------------------------------------------------
# ניקיון – הכרטיס הישן הוסר לגמרי מהתצוגה
# ---------------------------------------------------------------------------


def test_whats_new_card_removed_from_dashboard():
    """כרטיס 'מה חדש' הוסר מהדשבורד, כולל ה-CSS וה-JS שלו."""
    tpl = _read_template()
    for token in ("whats-new", "whats_new", "load-more-whats-new"):
        assert token not in tpl, f"נשאר שריד של הכרטיס הישן: {token}"


def test_whats_new_backend_kept_for_future_use():
    """
    הלוגיקה בצד השרת נשארה, כדי שאפשר יהיה להחזיר את הכרטיס בקלות
    בלי לשחזר אותה מההיסטוריה.
    """
    app_src = (REPO_ROOT / "webapp" / "app.py").read_text(encoding="utf-8")
    assert "def _load_whats_new" in app_src
    assert (REPO_ROOT / "config" / "whats_new.yaml").exists()
