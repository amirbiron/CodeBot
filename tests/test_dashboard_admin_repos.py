"""
בדיקות לכרטיס "הריפוים שלי" בדשבורד (אדמין בלבד).

הכרטיס מחליף את כרטיס "מה חדש", נטען מ-config/admin_repos.yaml,
וכל קישור בו נפתח בטאב חדש כדי ש-CodeKeeper יישאר פתוח מאחור.

הבדיקות עובדות בשתי רמות:
1. יחידה – על webapp/admin_repos.py (טעינה, cache וסינון קישורים).
2. רינדור – מרנדרות את התבנית עם נתונים אמיתיים ובודקות את ה-HTML שיוצא,
   במקום להסתמך על התאמות מחרוזת לקוד המקור.
"""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
jinja2 = pytest.importorskip("jinja2")

from webapp import admin_repos as admin_repos_module  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "webapp" / "templates"
DASHBOARD_TEMPLATE = TEMPLATES_DIR / "dashboard.html"
ADMIN_REPOS_YAML = REPO_ROOT / "config" / "admin_repos.yaml"


@pytest.fixture(autouse=True)
def _clear_cache():
    """כל בדיקה מתחילה עם cache נקי, אחרת בדיקות ידלפו זו לזו."""
    admin_repos_module.reset_cache()
    yield
    admin_repos_module.reset_cache()


# ---------------------------------------------------------------------------
# סינון קישורים
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/amirbiron/CodeBot",
        "http://example.com",
        "https://example.com/path?query=1#frag",
        "  https://example.com  ",  # רווחים מסביב
    ],
)
def test_safe_url_accepts_http_and_https(url):
    assert admin_repos_module.is_safe_external_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html;base64,SGVsbG8=",
        "file:///etc/passwd",
        "ftp://example.com",
        "https://",  # אין netloc
        "not-a-url",
        "",
        "   ",
        None,
        123,
        [],
    ],
)
def test_safe_url_rejects_unsafe_and_malformed(url):
    assert admin_repos_module.is_safe_external_url(url) is False


# ---------------------------------------------------------------------------
# טעינה מה-YAML
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, monkeypatch, content: str) -> Path:
    """כותב קובץ הגדרות זמני ומפנה אליו את המודול (ב-tmp בלבד)."""
    cfg = tmp_path / "admin_repos.yaml"
    cfg.write_text(content, encoding="utf-8")
    monkeypatch.setattr(admin_repos_module, "ADMIN_REPOS_PATH", cfg)
    admin_repos_module.reset_cache()
    return cfg


def test_load_skips_invalid_entries(tmp_path, monkeypatch):
    """רשומות שאינן dict, או בלי name/url, מדולגות בשקט."""
    _write_config(tmp_path, monkeypatch, """
repos:
  - "not-a-dict"
  - null
  - name: ""
    url: "https://example.com/empty-name"
  - name: "no-url"
  - name: "ok"
    url: "https://example.com/ok"
""")
    repos = admin_repos_module.load_admin_repos()
    assert [r["name"] for r in repos] == ["ok"]


def test_load_drops_unsafe_urls(tmp_path, monkeypatch):
    """
    קישור עם סכמה מסוכנת לא מגיע לדף. זו ההגנה המרכזית –
    הקובץ נערך ידנית ואסור שטעות בו תהפוך לקוד שרץ בדפדפן.
    """
    _write_config(tmp_path, monkeypatch, """
repos:
  - name: "evil"
    url: "javascript:alert(document.cookie)"
  - name: "good"
    url: "https://github.com/amirbiron/CodeBot"
""")
    repos = admin_repos_module.load_admin_repos()
    assert [r["name"] for r in repos] == ["good"]
    assert not any("javascript" in r["url"] for r in repos)


def test_load_applies_defaults(tmp_path, monkeypatch):
    """שדות אופציונליים מקבלים ברירת מחדל ולא נשארים None."""
    _write_config(tmp_path, monkeypatch, """
repos:
  - name: "minimal"
    url: "https://example.com"
""")
    repo = admin_repos_module.load_admin_repos()[0]
    assert repo["icon"] == admin_repos_module.DEFAULT_ICON
    assert repo["description"] == ""
    assert repo["badge"] == ""


@pytest.mark.parametrize(
    "content",
    [
        "repos: []",  # רשימה ריקה
        "repos:\n  - name: x\n    url: 'javascript:x'",  # הכל מסונן
        "{ this is: [broken yaml",  # YAML פגום
        "",  # קובץ ריק
        "- just\n- a list",  # מבנה לא צפוי (לא dict)
    ],
)
def test_load_returns_empty_list_without_raising(tmp_path, monkeypatch, content):
    """כל קלט חריג מחזיר רשימה ריקה – הדשבורד לא אמור ליפול בגלל הקובץ."""
    _write_config(tmp_path, monkeypatch, content)
    assert admin_repos_module.load_admin_repos() == []


def test_load_returns_empty_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_repos_module, "ADMIN_REPOS_PATH", tmp_path / "nope.yaml")
    admin_repos_module.reset_cache()
    assert admin_repos_module.load_admin_repos() == []


def test_caller_cannot_mutate_the_cache(tmp_path, monkeypatch):
    """שינוי הרשימה שהוחזרה לא אמור להשפיע על הקריאה הבאה."""
    _write_config(tmp_path, monkeypatch, """
repos:
  - name: "a"
    url: "https://example.com/a"
""")
    first = admin_repos_module.load_admin_repos()
    first.append({"name": "injected", "url": "https://evil.example"})
    assert [r["name"] for r in admin_repos_module.load_admin_repos()] == ["a"]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def test_cache_avoids_rereading_the_file(tmp_path, monkeypatch):
    cfg = _write_config(tmp_path, monkeypatch, """
repos:
  - name: "a"
    url: "https://example.com/a"
""")
    assert [r["name"] for r in admin_repos_module.load_admin_repos()] == ["a"]

    # שינוי הקובץ בלי לאפס cache – התוצאה צריכה להישאר הישנה
    cfg.write_text("repos:\n  - name: 'b'\n    url: 'https://example.com/b'\n", encoding="utf-8")
    assert [r["name"] for r in admin_repos_module.load_admin_repos()] == ["a"]

    # ואחרי איפוס – הקובץ נקרא מחדש
    admin_repos_module.reset_cache()
    assert [r["name"] for r in admin_repos_module.load_admin_repos()] == ["b"]


def test_empty_result_is_cached_too(tmp_path, monkeypatch):
    """
    רגרסיה: פעם ה-cache נבדק לפי truthiness, ולכן רשימה ריקה לעולם לא
    נחשבה cache hit – מה שגרם לקריאת דיסק ולאזהרה בלוג בכל בקשת דשבורד.
    """
    cfg = _write_config(tmp_path, monkeypatch, "repos: []")
    assert admin_repos_module.load_admin_repos() == []

    # הקובץ השתנה, אבל התוצאה הריקה אמורה עדיין להיות ב-cache
    cfg.write_text("repos:\n  - name: 'x'\n    url: 'https://example.com/x'\n", encoding="utf-8")
    assert admin_repos_module.load_admin_repos() == [], "תוצאה ריקה לא נשמרה ב-cache"


def test_broken_file_is_cached_to_avoid_log_spam(tmp_path, monkeypatch):
    """גם כישלון פענוח נשמר, אחרת כל בקשה הייתה מייצרת אזהרה חדשה."""
    cfg = _write_config(tmp_path, monkeypatch, "{ broken: [yaml")
    assert admin_repos_module.load_admin_repos() == []

    cfg.write_text("repos:\n  - name: 'x'\n    url: 'https://example.com/x'\n", encoding="utf-8")
    assert admin_repos_module.load_admin_repos() == []


# ---------------------------------------------------------------------------
# רינדור התבנית
# ---------------------------------------------------------------------------


class _StubLoader(jinja2.FileSystemLoader):
    """base.html ותבניות משנה לא רלוונטיות כאן – מוחלפות ב-stub."""

    def get_source(self, environment, template):
        if template != "dashboard.html":
            return ("{% block content %}{% endblock %}", template, lambda: True)
        return super().get_source(environment, template)


def _render(**overrides) -> str:
    env = jinja2.Environment(loader=_StubLoader(str(TEMPLATES_DIR)), autoescape=True)
    env.globals["url_for"] = lambda *a, **k: "#"
    env.globals["static_version"] = "1"
    env.filters["urlencode"] = lambda s: str(s)

    ctx = dict(
        user={"first_name": "test"},
        stats={"total_files": 0, "total_size": "0 B", "top_languages": [], "recent_files": []},
        activity_timeline={"groups": [], "feed": [], "has_more": False, "settings": {}},
        push_card={},
        notes_snapshot={},
        whats_new={"features": [], "has_features": False, "total": 0},
        files_need_attention={"items": [], "total": 0, "settings": {}},
        bot_username="bot",
        pinned_files=[],
        max_pinned=8,
        last_commit=None,
        repo_name="CodeBot",
        user_is_admin=False,
        admin_repos=[],
    )
    ctx.update(overrides)
    return env.get_template("dashboard.html").render(**ctx)


SAMPLE_REPOS = [
    {
        "name": "CodeBot",
        "url": "https://github.com/amirbiron/CodeBot",
        "description": "הריפו הראשי",
        "icon": "🤖",
        "badge": "ראשי",
    },
    {
        "name": "Second",
        "url": "https://github.com/amirbiron/Second",
        "description": "",
        "icon": "📦",
        "badge": "",
    },
]


def _repo_links(html: str):
    return re.findall(r'<a\b[^>]*class="admin-repo-item"[^>]*>', html)


def _grid_div(html: str) -> str:
    match = re.search(r'<div class="dashboard-grid[^"]*"', html)
    return match.group(0) if match else ""


def test_admin_sees_the_card_with_repos():
    html = _render(user_is_admin=True, admin_repos=SAMPLE_REPOS)
    assert 'class="glass-card admin-repos-card' in html
    assert "CodeBot" in html
    assert 'href="https://github.com/amirbiron/CodeBot"' in html
    assert "ראשי" in html
    assert len(_repo_links(html)) == 2


def test_every_repo_link_opens_in_a_new_tab():
    """
    זו הדרישה המרכזית של הפיצ'ר: לחיצה על ריפו לא אמורה להחליף את
    CodeKeeper – במיוחד באפליקציה המותקנת, שרצה ב-display: standalone.
    """
    html = _render(user_is_admin=True, admin_repos=SAMPLE_REPOS)
    links = _repo_links(html)
    assert links, "לא נמצא קישור ריפו"
    for link in links:
        assert 'target="_blank"' in link, f"קישור ללא target=_blank: {link}"
        assert "noopener" in link, f"קישור ללא rel=noopener: {link}"
        assert "noreferrer" in link, f"קישור ללא rel=noreferrer: {link}"


def test_non_admin_gets_no_card_and_no_repo_data():
    """
    ההגנה חייבת להיות בצד השרת: לא מספיק להסתיר את הכרטיס אם הכתובות
    כבר נמצאות ב-HTML שנשלח למשתמש.
    """
    html = _render(user_is_admin=False, admin_repos=[])
    assert 'class="glass-card admin-repos-card' not in html
    assert "github.com/amirbiron" not in html


def test_repo_urls_never_reach_non_admin_even_if_passed():
    """אפילו אם הרשימה תגיע בטעות לתבנית, תנאי האדמין חוסם אותה."""
    html = _render(user_is_admin=False, admin_repos=SAMPLE_REPOS)
    assert "github.com/amirbiron" not in html
    assert not _repo_links(html)


def test_admin_without_repos_sees_a_hint():
    html = _render(user_is_admin=True, admin_repos=[])
    assert 'class="glass-card admin-repos-card' in html
    assert "admin_repos.yaml" in html


def test_grid_collapses_for_non_admin_only():
    """משתמש רגיל לא אמור לקבל רווח ריק במקום הכרטיס."""
    assert "no-mid-widget" in _grid_div(_render(user_is_admin=False))
    assert "no-mid-widget" not in _grid_div(
        _render(user_is_admin=True, admin_repos=SAMPLE_REPOS)
    )


def test_repo_name_is_escaped():
    """שם ריפו הוא קלט מקובץ – חייב להיות escaped ולא לייצר HTML."""
    html = _render(
        user_is_admin=True,
        admin_repos=[{
            "name": '<img src=x onerror=alert(1)>',
            "url": "https://example.com",
            "description": "", "icon": "📦", "badge": "",
        }],
    )
    assert "<img src=x" not in html
    assert "&lt;img" in html


# ---------------------------------------------------------------------------
# קובץ ההגדרות והפריסה
# ---------------------------------------------------------------------------


def test_shipped_config_is_valid():
    """קובץ ההגדרות שנשלח עם הריפו חייב להיטען בלי אזהרות."""
    assert ADMIN_REPOS_YAML.exists()
    data = yaml.safe_load(ADMIN_REPOS_YAML.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and isinstance(data.get("repos"), list)
    for repo in data["repos"]:
        assert repo.get("name")
        assert admin_repos_module.is_safe_external_url(repo.get("url"))


def test_grid_css_is_defined_once_per_breakpoint():
    """
    בלוק הגריד היה משוכפל בעבר, כך שעריכה של אחד מהעותקים נדרסה בשקט
    על ידי השני. הבדיקה מוודאת שהוא מוגדר פעם אחת, ושמצב ה-non-admin
    מכוסה בשלושת גדלי המסך.
    """
    tpl = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    assert tpl.count("=== Dashboard grid layout ===") == 1
    assert tpl.count(".dashboard-grid.no-mid-widget") == 3


def test_no_stale_whats_new_markup_left():
    """הכרטיס הישן הוסר מהתצוגה, כולל ה-CSS וה-JS שלו."""
    tpl = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    for token in ("whats-new", "whats_new", "whatsnew"):
        assert token not in tpl, f"נשאר שריד של הכרטיס הישן: {token}"


def test_whats_new_backend_kept_for_future_use():
    """
    הלוגיקה בצד השרת נשארה, כדי שאפשר יהיה להחזיר את הכרטיס בקלות
    בלי לשחזר אותה מההיסטוריה.
    """
    app_src = (REPO_ROOT / "webapp" / "app.py").read_text(encoding="utf-8")
    assert "def _load_whats_new" in app_src
    assert (REPO_ROOT / "config" / "whats_new.yaml").exists()


def test_templates_are_protected_from_prettier():
    """
    CLAUDE.md אוסר להריץ Prettier על תבניות Jinja כי הוא שובר
    בלוקים של {% ... %}. הקובץ מגן מפני הרצה בטעות.
    """
    ignore_file = REPO_ROOT / ".prettierignore"
    assert ignore_file.exists(), "חסר .prettierignore"
    assert "webapp/templates/" in ignore_file.read_text(encoding="utf-8")
