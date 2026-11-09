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
    ok, theme_id, _dropped = svc.create(
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
    ok, err, _dropped = svc.create(
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



# ============= syntax_css בפרסום ובעדכון =============
# עד התיקון הפרסום השאיר רק את כללי CodeMirror: highlight.js ו-Pygments נזרקו בשקט, CSS ארוך נחתך באמצע, וסוג שאינו
# מחרוזת נשמר כ-CSS ריק. ``tests/services/test_sanitize_syntax_css.py`` בודק את הניקוי עצמו; כאן — מה שנשמר.


def _morass_syntax_css() -> str:
    """ה-``syntax_css`` שערכה אישית מקבלת בייבוא של morass — אותו מסלול של ``themes_api.import_theme``."""
    from services.styled_export_service import _MORASS_TOKEN_COLORS
    from services.theme_parser_service import parse_vscode_theme

    theme = {
        "name": "morass",
        "colors": {
            "editor.background": "#313a36",
            "editor.foreground": "#e4e3e1",
            "sideBar.background": "#485650",
        },
        "tokenColors": _MORASS_TOKEN_COLORS,
    }
    return parse_vscode_theme(theme)["syntax_css"]


def test_publish_keeps_highlightjs_and_pygments_rules():
    db = _MockDB()
    svc = SharedThemeService(db)
    outcome = svc.create(
        slug="morass",
        name="morass",
        colors={"--primary": "#fdec5a"},
        created_by=1,
        syntax_css=_morass_syntax_css(),
    )
    assert outcome.ok is True
    assert outcome.syntax_rules_dropped == 0
    saved = db.shared_themes.docs[0]["syntax_css"]
    assert ':root[data-theme-type="custom"] .hljs-attr { color: #9cdcfe !important; }' in saved
    assert ':root[data-theme-type="custom"] .hljs-string { color: #ce9178 !important; }' in saved
    assert (
        ':root[data-theme-type="custom"] .hljs { color: #e4e3e1 !important; background: #313a36 !important; }'
        in saved
    )
    assert ".highlight .nt { color: #569cd6 !important; }" in saved
    assert ".tok-" in saved


def test_publish_rejects_syntax_css_that_is_not_a_string():
    db = _MockDB()
    svc = SharedThemeService(db)
    outcome = svc.create(
        slug="morass",
        name="morass",
        colors={"--primary": "#fdec5a"},
        created_by=1,
        syntax_css=["x"],
    )
    assert outcome == (False, "invalid_syntax_css", 0)
    assert db.shared_themes.docs == []


def test_publish_rejects_syntax_css_over_the_ceiling_instead_of_cutting_it():
    from services.shared_theme_service import MAX_SYNTAX_CSS_LENGTH

    db = _MockDB()
    svc = SharedThemeService(db)
    rule = ':root[data-theme-type="custom"] .hljs-string { color: #ce9178 !important; }\n'
    too_long = rule * (MAX_SYNTAX_CSS_LENGTH // len(rule) + 1)
    outcome = svc.create(
        slug="morass",
        name="morass",
        colors={"--primary": "#fdec5a"},
        created_by=1,
        syntax_css=too_long,
    )
    assert outcome == (False, "syntax_css_too_long", 0)
    assert db.shared_themes.docs == []


def test_publish_reports_and_logs_rules_that_did_not_pass(caplog):
    db = _MockDB()
    svc = SharedThemeService(db)
    legacy = (
        ':root[data-theme-type="custom"] .tok-keyword { color: #c586c0 !important; }\n'
        ':root[data-theme-type="custom"] .source .k { color: #c586c0 !important; }'
    )
    with caplog.at_level("WARNING", logger="services.shared_theme_service"):
        outcome = svc.create(
            slug="old_theme",
            name="Old",
            colors={"--primary": "#fdec5a"},
            created_by=1,
            syntax_css=legacy,
        )
    assert outcome == (True, "old_theme", 1)
    assert (
        db.shared_themes.docs[0]["syntax_css"]
        == ':root[data-theme-type="custom"] .tok-keyword { color: #c586c0 !important; }'
    )
    assert any(
        "old_theme" in r.getMessage() and "1 syntax_css rules" in r.getMessage()
        for r in caplog.records
    )


def test_update_with_syntax_css_that_is_not_a_string_does_not_wipe_it():
    db = _MockDB()
    db.shared_themes.docs = [{"_id": "morass", "is_active": True, "syntax_css": "kept"}]
    svc = SharedThemeService(db)
    outcome = svc.update("morass", syntax_css={"not": "css"})
    assert outcome == (False, "invalid_syntax_css", 0)
    assert not any(call[0] == "update_one" for call in db.shared_themes.calls)


def test_update_keeps_every_family_and_reports_the_count():
    db = _MockDB()
    db.shared_themes.docs = [{"_id": "morass", "is_active": True}]
    svc = SharedThemeService(db)
    outcome = svc.update("morass", syntax_css=_morass_syntax_css())
    assert outcome == (True, "ok", 0)
    update = next(call for call in db.shared_themes.calls if call[0] == "update_one")[2]
    assert ".hljs-attr" in update["$set"]["syntax_css"]
    assert ".highlight .s2" in update["$set"]["syntax_css"]
