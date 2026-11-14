"""רינדור של ``webapp/templates/dashboard.html`` מהדיסק, בלי אפליקציה — לבדיקות של הכרטיסים בדשבורד.

רק ``dashboard.html`` נטען כמו שהוא; ``base.html`` ושאר התבניות מוחלפות ב-stub שמרנדר את בלוק
התוכן בלבד. בלוק ה-``<style>`` של הדשבורד יושב בתוך בלוק התוכן, ולכן הוא חלק מה-HTML שיוצא —
וטסט דפדפן יכול למדוד אותו.

``render_dashboard`` מקבל ערכים שמחליפים את ההקשר המינימלי שהתבנית צריכה. עד נובמבר 2026 הרינדור
הזה היה כתוב בתוך ``tests/test_dashboard_admin_repos.py``; הוא עבר לכאן כשגם הבדיקות של
"פתקים אחרונים" נזקקו לו.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import jinja2

from webapp.file_name_display import TEMPLATE_FILTERS

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "webapp" / "templates"


class _StubLoader(jinja2.FileSystemLoader):
    """``base.html`` ותבניות משנה לא רלוונטיות כאן — מוחלפות ב-stub."""

    def get_source(self, environment, template):
        if template != "dashboard.html":
            return ("{% block content %}{% endblock %}", template, lambda: True)
        return super().get_source(environment, template)


def render_dashboard(*, filters: dict | None = None, **overrides) -> str:
    """``filters`` מחליף את הפילטרים של האפליקציה — לריצת בקרה של טסט דפדפן, שבודקת מה התבנית מציגה בלעדיהם."""
    env = jinja2.Environment(loader=_StubLoader(str(TEMPLATES_DIR)), autoescape=True)
    env.globals["url_for"] = lambda *a, **k: "#"
    env.globals["static_version"] = "1"
    # כרטיס הקבצים הנעוצים מצייר אייקון שפה; האייקון עצמו אינו מה שנבדק כאן.
    env.globals["lang_icon"] = lambda *a, **k: ""
    env.globals["LANG_ICON_SIZES"] = SimpleNamespace(file_row=16)
    env.filters["urlencode"] = lambda s: str(s)
    # הפילטרים של האפליקציה שהתבנית משתמשת בהם (``file_name``), מאותו מקום שהאפליקציה רושמת אותם.
    env.filters.update(TEMPLATE_FILTERS if filters is None else filters)

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
