import types
from datetime import datetime, timezone

from services.shared_theme_service import BUILTIN_THEMES, SharedThemeService


class _MockCursor:
    def __init__(self, docs):
        self._docs = list(docs or [])

    def sort(self, *_args, **_kwargs):
        return self

    def __iter__(self):
        return iter(self._docs)


class _MockCollection:
    def __init__(self):
        self.docs = []
        self.calls = []

    def find(self, query, projection=None):
        self.calls.append(("find", query, projection))
        # simplistic: return all active docs
        out = []
        for d in self.docs:
            if query.get("is_active") and not d.get("is_active", False):
                continue
            out.append(d)
        return _MockCursor(out)

    def find_one(self, query, projection=None):
        self.calls.append(("find_one", query, projection))
        for d in self.docs:
            if d.get("_id") != query.get("_id"):
                continue
            if query.get("is_active") and not d.get("is_active", False):
                return None
            return d
        return None

    def insert_one(self, doc):
        self.calls.append(("insert_one", doc))
        self.docs.append(doc)
        return types.SimpleNamespace(inserted_id=doc.get("_id"))

    def update_one(self, query, update):
        self.calls.append(("update_one", query, update))
        return types.SimpleNamespace(modified_count=1)

    def delete_one(self, query):
        self.calls.append(("delete_one", query))
        for i, d in enumerate(list(self.docs)):
            if d.get("_id") == query.get("_id"):
                self.docs.pop(i)
                return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)


class _MockDB:
    def __init__(self):
        self.shared_themes = _MockCollection()


def test_validate_slug():
    svc = SharedThemeService(_MockDB())
    assert svc._validate_slug("cyber_purple") is True
    assert svc._validate_slug("a12") is True
    assert svc._validate_slug("ab") is False
    assert svc._validate_slug("123") is False
    assert svc._validate_slug("CamelCase") is False
    assert svc._validate_slug("with-dash") is False
    assert svc._validate_slug("a" * 31) is False


def test_create_success_filters_colors_and_saves_syntax_css():
    db = _MockDB()
    svc = SharedThemeService(db)
    ok, theme_id = svc.create(
        slug="cyber_purple",
        name="Cyber Purple",
        colors={"--primary": "#667eea", "--bg-primary": "#000000", "--not-allowed": "#ffffff"},
        created_by=123,
        # syntax_css חייב לעבור sanitize ולהתיישר לפורמט שמכסה גם shared (data-theme-type)
        syntax_css=':root[data-theme="custom"] .tok-keyword { color: #ffffff; }',
    )
    assert ok is True
    assert theme_id == "cyber_purple"
    assert len(db.shared_themes.docs) == 1
    assert db.shared_themes.docs[0]["_id"] == "cyber_purple"
    assert "--not-allowed" not in db.shared_themes.docs[0]["colors"]
    assert isinstance(db.shared_themes.docs[0].get("syntax_css"), str)
    assert 'data-theme-type="custom"' in db.shared_themes.docs[0].get("syntax_css", "")


def test_create_duplicate_slug_rejected():
    db = _MockDB()
    db.shared_themes.docs = [{"_id": "cyber_purple", "is_active": True}]
    svc = SharedThemeService(db)
    ok, err = svc.create(
        slug="cyber_purple",
        name="Cyber Purple 2",
        colors={"--primary": "#667eea"},
        created_by=123,
    )
    assert ok is False
    assert err == "slug_exists"


def test_get_all_themes_merged_includes_builtin_shared_custom():
    db = _MockDB()
    db.shared_themes.docs = [
        {"_id": "shared1", "name": "Shared 1", "is_active": True, "created_at": datetime.now(timezone.utc)}
    ]
    svc = SharedThemeService(db)
    merged = svc.get_all_themes_merged([{"id": "c1", "name": "Mine", "is_active": False}])
    assert len([t for t in merged if t.get("type") == "builtin"]) == len(BUILTIN_THEMES)
    assert len([t for t in merged if t.get("type") == "shared"]) >= 1
    assert len([t for t in merged if t.get("type") == "custom"]) == 1

