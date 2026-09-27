"""הסעיף של סל המיחזור בעמוד ``/admin/verify-indexes``.

זה המקום שבו אפשר לראות מהדפדפן — בלי טרמינל ובלי Atlas — אם אינדקס ה-TTL
שמרוקן את הסל קיים. הבדיקות עוברות דרך בקשת HTTP, כמו המשתמש, ובודקות את
ה-JSON שחוזר.
"""

from __future__ import annotations

from datetime import datetime

import pytest

SPEC_ROW = {
    "v": 2,
    "key": {"deleted_expires_at": 1},
    "name": "deleted_ttl",
    "expireAfterSeconds": 0,
    "partialFilterExpression": {"is_active": False},
}


class _Coll:
    def __init__(self, indexes=(), overdue=0):
        self._indexes = [dict(row) for row in indexes]
        self._overdue = overdue
        self.count_queries: list[dict] = []

    def list_indexes(self):
        return [dict(row) for row in self._indexes]

    def count_documents(self, query, *args, **kwargs):
        self.count_queries.append(query)
        return self._overdue


class _DB:
    def __init__(self, collections):
        self._collections = dict(collections)

    def __getitem__(self, name):
        return self._collections.setdefault(name, _Coll())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def command(self, *args, **kwargs):
        return {"inprog": []}


@pytest.fixture
def admin(monkeypatch):
    import webapp.app as app_mod

    monkeypatch.setattr(app_mod.app, "testing", True)
    monkeypatch.setitem(app_mod.app.config, "SECRET_KEY", "test")
    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    with app_mod.app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["user_data"] = {"id": 1, "is_admin": True, "is_premium": False}
        yield client, app_mod


def _get(admin, monkeypatch, db):
    client, app_mod = admin
    monkeypatch.setattr(app_mod, "get_db", lambda: db)
    response = client.get("/admin/verify-indexes")
    assert response.status_code == 200
    return response.get_json()


def test_the_index_in_both_collections_is_reported_as_present(admin, monkeypatch):
    db = _DB({
        "code_snippets": _Coll([SPEC_ROW]),
        "large_files": _Coll([SPEC_ROW]),
    })
    data = _get(admin, monkeypatch, db)

    section = data["recycle_bin_ttl"]
    for coll in ("code_snippets", "large_files"):
        assert section[coll]["ttl_index_present"] is True
        assert section[coll]["ttl_index_names"] == ["deleted_ttl"]
        assert section[coll]["overdue_still_in_trash"] == 0
    assert not [w for w in data["summary"]["warnings"] if "סל המיחזור" in w]


def test_a_missing_index_is_a_warning_with_the_overdue_count(admin, monkeypatch):
    """כך נראה הפרודקשן ב-2026-09-27: אין אינדקס, ומסמכים שתאריכם עבר עדיין בסל."""
    db = _DB({
        "code_snippets": _Coll([], overdue=109),
        "large_files": _Coll([SPEC_ROW]),
    })
    data = _get(admin, monkeypatch, db)

    section = data["recycle_bin_ttl"]["code_snippets"]
    assert section["ttl_index_present"] is False
    assert section["overdue_still_in_trash"] == 109
    assert "חסר אינדקס TTL לסל המיחזור ב-code_snippets" in data["summary"]["warnings"]
    assert data["summary"]["all_critical_indexes_present"] is False


def test_an_old_ttl_without_the_filter_is_shown_but_not_counted_as_present(admin, monkeypatch):
    old = {k: v for k, v in SPEC_ROW.items() if k != "partialFilterExpression"}
    db = _DB({"code_snippets": _Coll([old]), "large_files": _Coll([SPEC_ROW])})
    data = _get(admin, monkeypatch, db)

    section = data["recycle_bin_ttl"]["code_snippets"]
    assert section["ttl_index_present"] is False
    assert [row["name"] for row in section["indexes_on_field"]] == ["deleted_ttl"]


def test_the_overdue_count_asks_only_for_trash_with_a_past_date(admin, monkeypatch):
    """``$lt`` מול ``datetime`` מודע-אזור (R7): נאיבי היה מושווה כאילו הוא UTC
    במקרה הטוב, ובמקרה הרע נשבר מול ערכים מודעים."""
    snippets = _Coll([SPEC_ROW])
    db = _DB({"code_snippets": snippets, "large_files": _Coll([SPEC_ROW])})
    _get(admin, monkeypatch, db)

    assert len(snippets.count_queries) == 1
    query = snippets.count_queries[0]
    assert query["is_active"] is False
    cutoff = query["deleted_expires_at"]["$lt"]
    assert isinstance(cutoff, datetime) and cutoff.tzinfo is not None


def test_a_failed_check_is_not_reported_as_a_missing_index(admin, monkeypatch):
    """"לא הצלחתי לבדוק" אינו "חסר" — ערבוב ביניהם שולח לתקן את הדבר הלא נכון."""

    class _Broken(_Coll):
        def list_indexes(self):
            raise RuntimeError("boom")

    db = _DB({"code_snippets": _Broken(), "large_files": _Coll([SPEC_ROW])})
    data = _get(admin, monkeypatch, db)

    assert "error" in data["recycle_bin_ttl"]["code_snippets"]
    warnings = data["summary"]["warnings"]
    assert "לא ניתן לבדוק את אינדקס ה-TTL של סל המיחזור ב-code_snippets" in warnings
    assert "חסר אינדקס TTL לסל המיחזור ב-code_snippets" not in warnings
