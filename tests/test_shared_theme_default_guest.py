"""ערכה ציבורית כברירת מחדל (``DEFAULT_UI_THEME=shared:<slug>``) חלה גם על מבקר שאינו מחובר.

עד התיקון ``inject_globals`` פתח את המסד רק כשיש ``user_id``, והטעינה של ערכה ציבורית דרשה את החיבור הזה — ולכן מבקר קיבל ``classic`` גם כשברירת המחדל הייתה ערכה ציבורית קיימת. ערכה ציבורית היא מידע ציבורי, ועכשיו מבקר מקבל אותה דרך קאש קצר בזיכרון (``_get_shared_theme_cached``), ומשתמש מחובר ממשיך לקבל אותה בשליפה טרייה.

הבדיקות של המבקר עוברות דרך ה-HTML של ``/`` — המקום שבו ``base.html`` מעביר את הערכה לסקריפט שקובע את ``data-theme`` ולבלוק ``shared-theme-override`` שמגדיר את משתני הצבע. של המשתמש המחובר עוברות דרך ``inject_globals`` ישירות, כמו ב-``tests/test_custom_theme_context.py``.
"""

from __future__ import annotations

import logging
import re

import pytest
from pymongo.errors import ServerSelectionTimeoutError

pytest.importorskip("flask")

from webapp import app as webapp_app  # noqa: E402

SLUG = "morass"
COLORS = {"--bg-primary": "#1b2a1f", "--primary": "#7fae6b"}

_SERVER_THEME_RE = re.compile(r"var serverTheme = '([^']*)';")
_HAS_SHARED_RE = re.compile(r"var hasSharedTheme = (true|false);")


def _theme_doc(slug: str = SLUG, *, active: bool = True) -> dict:
    return {"_id": slug, "name": slug.title(), "colors": dict(COLORS), "is_active": active}


class _Coll:
    """דמה של אוסף שמכבדת את **כל** שדות המסנן, כולל ``is_active``.

    מקבלת גם ארגומנטים נוספים (היטלה) — דמה שמקבלת רק ``query`` נופלת ברגע שמישהו מוסיף היטלה, והנפילה נבלעת ב-``except`` של הקוד הנבדק.
    """

    def __init__(self, docs=(), *, errors=()):
        self.docs = {d.get("_id", d.get("user_id")): d for d in docs}
        self.errors = list(errors)
        self.calls: list[dict] = []

    def find_one(self, query, *args, **kwargs):
        self.calls.append(dict(query))
        if self.errors:
            raise self.errors.pop(0)
        for doc in self.docs.values():
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None


class _DB:
    def __init__(self, themes=(), users=(), *, theme_errors=()):
        self.shared_themes = _Coll(themes, errors=theme_errors)
        self.users = _Coll(users)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    # הקאש הוא מצב של התהליך — כל טסט מתחיל מקאש ריק ולא משאיר אחריו כלום.
    # ``raising=False``: כך הטסטים רצים גם על הקוד שלפני התיקון ונכשלים שם באסרט.
    monkeypatch.setattr(webapp_app, "_SHARED_THEME_CACHE", {}, raising=False)
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: False)
    monkeypatch.setattr(webapp_app, "is_premium", lambda *_: False)


def _install_db(monkeypatch, db):
    """``get_db`` שמחזיר את הדמה וסופר כמה פעמים נקרא."""
    calls = {"n": 0}

    def _get_db():
        calls["n"] += 1
        return db

    monkeypatch.setattr(webapp_app, "get_db", _get_db)
    return calls


def _guest_home(*, cookies: dict | None = None) -> str:
    client = webapp_app.app.test_client()
    for name, value in (cookies or {}).items():
        client.set_cookie(name, value)
    resp = client.get("/")
    assert resp.status_code == 200, resp.status_code
    return resp.get_data(as_text=True)


def _rendered_theme(html: str) -> tuple[str, str]:
    server_theme = _SERVER_THEME_RE.search(html)
    has_shared = _HAS_SHARED_RE.search(html)
    assert server_theme and has_shared, "הסקריפט שקובע את data-theme לא נמצא ב-HTML"
    return server_theme.group(1), has_shared.group(1)


def _logged_in_ctx(user_doc: dict) -> dict:
    with webapp_app.app.test_request_context("/"):
        from flask import session

        session["user_id"] = user_doc["user_id"]
        return webapp_app.inject_globals()


# ─── מבקר שאינו מחובר ────────────────────────────────────────────────────


def test_guest_gets_the_public_default_theme(monkeypatch):
    monkeypatch.setenv("DEFAULT_UI_THEME", f"shared:{SLUG}")
    db = _DB(themes=[_theme_doc()])
    _install_db(monkeypatch, db)

    html = _guest_home()

    assert _rendered_theme(html) == (f"shared:{SLUG}", "true")
    assert 'id="shared-theme-override"' in html
    for var_name, value in COLORS.items():
        assert f"{var_name}: {value};" in html


def test_guest_shared_theme_from_cookie_is_applied(monkeypatch):
    """מי שבחר ערכה ציבורית והתנתק נשאר עם ה-cookie שלה — כמו שקורה כבר היום לערכה מובנית."""
    monkeypatch.delenv("DEFAULT_UI_THEME", raising=False)
    _install_db(monkeypatch, _DB(themes=[_theme_doc("tide")]))

    html = _guest_home(cookies={"ui_theme": "shared:tide"})

    assert _rendered_theme(html) == ("shared:tide", "true")


@pytest.mark.parametrize(
    "default_slug, theme_doc",
    [
        pytest.param("nope", _theme_doc(), id="slug-not-found"),
        pytest.param(SLUG, _theme_doc(active=False), id="theme-inactive"),
    ],
)
def test_guest_gets_classic_when_the_public_theme_is_missing_or_inactive(monkeypatch, default_slug, theme_doc):
    monkeypatch.setenv("DEFAULT_UI_THEME", f"shared:{default_slug}")
    _install_db(monkeypatch, _DB(themes=[theme_doc]))

    html = _guest_home()

    assert _rendered_theme(html) == ("classic", "false")
    assert 'id="shared-theme-override"' not in html


def test_missing_theme_is_not_remembered(monkeypatch):
    """"לא נמצא" אינו נשמר בקאש: ערכה שנוצרה מגיעה לבקשה הבאה מיד, בלי לחכות שרשומה תפוג.

    זה גם מה שמגביל את גודל הקאש — ה-slug יכול להגיע מ-cookie שהלקוח שולט בו.
    """
    monkeypatch.setenv("DEFAULT_UI_THEME", f"shared:{SLUG}")
    db = _DB()
    _install_db(monkeypatch, db)

    assert _rendered_theme(_guest_home()) == ("classic", "false")

    db.shared_themes.docs[SLUG] = _theme_doc()
    assert _rendered_theme(_guest_home()) == (f"shared:{SLUG}", "true")


def test_guest_theme_is_read_once_until_the_cache_expires(monkeypatch):
    monkeypatch.setenv("DEFAULT_UI_THEME", f"shared:{SLUG}")
    db = _DB(themes=[_theme_doc()])
    _install_db(monkeypatch, db)

    for _ in range(3):
        assert _rendered_theme(_guest_home()) == (f"shared:{SLUG}", "true")
    assert len(db.shared_themes.calls) == 1

    # רשומה שפגה נקראת מחדש מהמסד
    monkeypatch.setattr(webapp_app, "_SHARED_THEME_CACHE_TTL_SECONDS", 0.0)
    webapp_app._SHARED_THEME_CACHE.clear()
    _guest_home()
    _guest_home()
    assert len(db.shared_themes.calls) == 3


def test_cached_theme_is_a_copy(monkeypatch):
    """מי שמשנה את מה שקיבל אינו משנה את מה שהבקשה הבאה תקבל."""
    monkeypatch.setenv("DEFAULT_UI_THEME", f"shared:{SLUG}")
    _install_db(monkeypatch, _DB(themes=[_theme_doc()]))

    first = webapp_app._get_shared_theme_cached(SLUG)
    first["colors"]["--bg-primary"] = "#000000"

    assert webapp_app._get_shared_theme_cached(SLUG)["colors"] == COLORS


def test_db_failure_falls_back_to_classic_and_is_not_remembered(monkeypatch, caplog):
    monkeypatch.setenv("DEFAULT_UI_THEME", f"shared:{SLUG}")
    db = _DB(themes=[_theme_doc()], theme_errors=[ServerSelectionTimeoutError("no primary")])
    _install_db(monkeypatch, db)

    with caplog.at_level(logging.WARNING, logger="webapp.app"):
        assert _rendered_theme(_guest_home()) == ("classic", "false")
    failures = [r for r in caplog.records if "shared theme" in r.getMessage()]
    assert [r.levelno for r in failures] == [logging.WARNING]
    assert "DB read failed (ServerSelectionTimeoutError)" in failures[0].getMessage()

    # הכשל לא נזכר: הבקשה הבאה מנסה שוב ומקבלת את הערכה
    assert _rendered_theme(_guest_home()) == (f"shared:{SLUG}", "true")


def test_unexpected_error_is_logged_apart_from_db_failures(monkeypatch, caplog):
    """חריגה שאינה תקלת מסד נופלת ל-classic בתווית משלה ועם traceback, ולא נספרת כ"המסד לא ענה"."""
    monkeypatch.setenv("DEFAULT_UI_THEME", f"shared:{SLUG}")

    def _broken_get_db():
        raise Exception("MONGODB_URL is not configured")

    monkeypatch.setattr(webapp_app, "get_db", _broken_get_db)

    with caplog.at_level(logging.WARNING, logger="webapp.app"):
        assert _rendered_theme(_guest_home()) == ("classic", "false")
    failures = [r for r in caplog.records if "shared theme" in r.getMessage()]
    assert [r.levelno for r in failures] == [logging.ERROR]
    assert "unexpected error" in failures[0].getMessage()
    assert failures[0].exc_info is not None


def test_db_in_cooldown_gives_classic(monkeypatch):
    """``get_db()`` מחזיר ``None`` בחלון הצינון שאחרי כשל התחברות."""
    monkeypatch.setenv("DEFAULT_UI_THEME", f"shared:{SLUG}")
    monkeypatch.setattr(webapp_app, "get_db", lambda: None)

    assert _rendered_theme(_guest_home()) == ("classic", "false")


@pytest.mark.parametrize("default_theme", ["ocean", "classic", None])
def test_builtin_default_does_not_touch_the_db(monkeypatch, default_theme):
    if default_theme is None:
        monkeypatch.delenv("DEFAULT_UI_THEME", raising=False)
    else:
        monkeypatch.setenv("DEFAULT_UI_THEME", default_theme)
    calls = _install_db(monkeypatch, _DB(themes=[_theme_doc()]))

    html = _guest_home()

    assert _rendered_theme(html) == (default_theme or "classic", "false")
    assert calls["n"] == 0


def test_guest_builtin_cookie_over_shared_default_does_not_touch_the_db(monkeypatch):
    monkeypatch.setenv("DEFAULT_UI_THEME", f"shared:{SLUG}")
    calls = _install_db(monkeypatch, _DB(themes=[_theme_doc()]))

    html = _guest_home(cookies={"ui_theme": "ocean"})

    assert _rendered_theme(html) == ("ocean", "false")
    assert calls["n"] == 0


# ─── משתמש מחובר ─────────────────────────────────────────────────────────


def test_logged_in_user_with_own_builtin_theme_is_unchanged(monkeypatch):
    monkeypatch.setenv("DEFAULT_UI_THEME", f"shared:{SLUG}")
    user = {"user_id": 42, "ui_prefs": {"theme": "ocean"}}
    db = _DB(themes=[_theme_doc()], users=[user])
    _install_db(monkeypatch, db)

    ctx = _logged_in_ctx(user)

    assert ctx["ui_theme"] == "ocean"
    assert ctx["shared_theme"] is None
    assert db.shared_themes.calls == []


def test_logged_in_user_with_own_shared_theme_reads_it_fresh_every_time(monkeypatch):
    """למחובר אין קאש: ה-ETag בעמודי הקובץ נבנה מ-``updated_at`` טרי, והגוף חייב להתאים לו."""
    monkeypatch.setenv("DEFAULT_UI_THEME", f"shared:{SLUG}")
    user = {"user_id": 42, "ui_prefs": {"theme": "shared:tide"}}
    db = _DB(themes=[_theme_doc(), _theme_doc("tide")], users=[user])
    _install_db(monkeypatch, db)

    for _ in range(2):
        ctx = _logged_in_ctx(user)
        assert ctx["ui_theme"] == "shared:tide"
        assert ctx["shared_theme"]["id"] == "tide"
        assert ctx["shared_theme"]["colors"] == COLORS

    assert db.shared_themes.calls == [{"_id": "tide", "is_active": True}] * 2
    assert webapp_app._SHARED_THEME_CACHE == {}
