import pytest

from webapp import app as webapp_app


def test_inject_globals_exposes_active_custom_theme_for_non_admin(monkeypatch):
    """
    רגרסיה: בעבר custom_theme הוזרק רק לאדמינים וגם theme=custom הוחזר בכוח ל-classic.
    הבדיקה מוודאת שלמשתמש רגיל עם custom_theme פעילה ב-DB, התבניות יקבלו:
    - custom_theme
    - ui_theme='custom'
    """

    class _StubUsers:
        def find_one(self, _query):
            return {
                "user_id": 42,
                "ui_prefs": {"theme": "custom"},
                "custom_themes": [
                    {
                        "id": "abc",
                        "name": "My Theme",
                        "is_active": True,
                        "variables": {"--bg-primary": "#123456"},
                    }
                ],
            }

    class _StubDB:
        def __init__(self):
            self.users = _StubUsers()

    monkeypatch.setattr(webapp_app, "get_db", lambda: _StubDB())
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: False)

    webapp_app.app.testing = True
    with webapp_app.app.test_request_context("/"):
        # simulate logged-in user
        from flask import session

        session["user_id"] = 42
        ctx = webapp_app.inject_globals()

    assert ctx["ui_theme"] == "custom"
    assert isinstance(ctx.get("custom_theme"), dict)
    assert ctx["custom_theme"].get("is_active") is True


def test_inject_globals_fallbacks_to_old_custom_theme_schema(monkeypatch):
    """תאימות לאחור: אם אין custom_themes, משתמשים ב-custom_theme הישן."""

    class _StubUsers:
        def find_one(self, _query):
            return {
                "user_id": 42,
                "ui_prefs": {"theme": "custom"},
                "custom_theme": {
                    "name": "Old Theme",
                    "is_active": True,
                    "variables": {"--bg-primary": "#123456"},
                },
            }

    class _StubDB:
        def __init__(self):
            self.users = _StubUsers()

    monkeypatch.setattr(webapp_app, "get_db", lambda: _StubDB())
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: False)

    webapp_app.app.testing = True
    with webapp_app.app.test_request_context("/"):
        from flask import session

        session["user_id"] = 42
        ctx = webapp_app.inject_globals()

    assert ctx["ui_theme"] == "custom"
    assert isinstance(ctx.get("custom_theme"), dict)
    assert ctx["custom_theme"].get("is_active") is True


def test_inject_globals_blocks_custom_theme_when_inactive(monkeypatch):
    class _StubUsers:
        def find_one(self, _query):
            return {
                "user_id": 42,
                "ui_prefs": {"theme": "custom"},
                "custom_themes": [
                    {
                        "id": "abc",
                        "name": "Inactive Theme",
                        "is_active": False,
                        "variables": {"--bg-primary": "#123456"},
                    }
                ],
            }

    class _StubDB:
        def __init__(self):
            self.users = _StubUsers()

    monkeypatch.setattr(webapp_app, "get_db", lambda: _StubDB())
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: False)

    webapp_app.app.testing = True
    with webapp_app.app.test_request_context("/"):
        from flask import session

        session["user_id"] = 42
        ctx = webapp_app.inject_globals()

    # Safety: אם custom לא פעילה, לא נאפשר ui_theme=custom
    assert ctx["ui_theme"] == "classic"
