"""קישורי השיתוף של ייצוא ה-HTML המעוצב: האינדקסים של ``styled_shares`` ושיתוף של קובץ גדול.

- **האינדקסים** הם של התנהגות (``styled_shares.py``): ה-TTL הוא היחיד שמוחק קישור שפקע, והייחודי מבטיח
  ש-``token`` מוביל למסמך אחד. הם מוצהרים ב-``DatabaseManager._create_indexes``, שהוובאפ — הכותב היחיד —
  עובר בעלייה, וכשל שלהם יוצא כאירוע ברמת error (``BY-STACK/mongodb.md`` דפוס 9).
- **קובץ גדול** שומר את הטקסט ב-``content`` ולא ב-``code``; שיתוף שלו שמר עמוד ריק.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest

from database.manager import DatabaseManager


class _Coll:
    def create_indexes(self, indexes):
        return None

    def list_indexes(self):
        return []


class _DB:
    def __getitem__(self, name):
        return _Coll()


def _fake_self(safe_create_index) -> SimpleNamespace:
    """``self`` מדומה ל-``DatabaseManager._create_indexes`` — אותה צורה של ``tests/test_mcp_uploads.py``."""
    return SimpleNamespace(
        collection=_Coll(), large_files_collection=_Coll(), db=_DB(),
        backup_ratings_collection=_Coll(), internal_shares_collection=_Coll(),
        community_library_collection=_Coll(), snippets_collection=_Coll(),
        safe_create_index=safe_create_index,
    )


@pytest.fixture
def events(monkeypatch) -> list[tuple]:
    """מה שההצהרה פולטת, במקום ``emit_event`` האמיתי — במילון שהפונקציה באמת קוראת ממנו."""
    recorded: list[tuple] = []
    monkeypatch.setitem(
        DatabaseManager._create_styled_shares_indexes.__globals__,
        "emit_event",
        lambda event, severity="info", **fields: recorded.append((event, severity, fields)),
    )
    return recorded


def test_startup_declares_the_styled_share_indexes():
    """המפרט כתוב כאן במפורש ולא נקרא מ-``styled_shares.py``: טסט שגוזר את הציפייה מאותו מקום שהוא בודק לא
    יתפוס שינוי מקרי בו. ובמסלול העלייה (``_create_indexes``), שהוובאפ עובר."""
    requested: list[tuple] = []

    def _safe_create_index(coll, keys, **kwargs):
        requested.append((coll, list(keys), kwargs))
        return True

    DatabaseManager._create_indexes(_fake_self(_safe_create_index))

    declared = {kwargs["name"]: (keys, kwargs) for coll, keys, kwargs in requested if coll == "styled_shares"}
    assert set(declared) == {"styled_shares_ttl", "styled_shares_token", "styled_shares_by_file"}

    keys, ttl = declared["styled_shares_ttl"]
    assert keys == [("expires_at", 1)]
    # ``is not None`` ולא אמיתות: חלון של 0 שניות הוא בדיוק הערך המבוקש, והוא שקרי.
    assert ttl["expire_after_seconds"] == 0 and ttl["expire_after_seconds"] is not None
    assert ttl["enforce"] is True and ttl["unique"] is False

    keys, token = declared["styled_shares_token"]
    assert keys == [("token", 1)]
    assert token["unique"] is True and token["enforce"] is True and token.get("expire_after_seconds") is None

    # רשימת הקישורים של קובץ: שוויון על המשתמש ושם הקובץ, ואחריו המיון מהחדש לישן (ESR). אינדקס ביצועים, בלי TTL ובלי ייחודיות
    keys, by_file = declared["styled_shares_by_file"]
    assert keys == [("user_id", 1), ("file_name", 1), ("created_at", -1)]
    assert by_file["unique"] is False and by_file.get("expire_after_seconds") is None


def test_a_failed_styled_share_index_is_an_error_event(events):
    """``safe_create_index`` אינו זורק; כשל חוזר כ-``False`` (K11). שני האינדקסים הם הבטחה, ולכן כשל של כל
    אחד מהם יוצא ברמת error — ולא נבלע כמו אינדקס ביצועים."""
    results = DatabaseManager._create_styled_shares_indexes(
        SimpleNamespace(), lambda coll, keys, **kwargs: coll != "styled_shares"
    )

    assert results == {"styled_shares_ttl": False, "styled_shares_token": False, "styled_shares_by_file": False}
    # אינדקס הביצועים נכשל גם הוא, ואינו אירוע error: בלעדיו הרשימה איטית, לא שבורה
    missing = sorted(f["index_name"] for e, s, f in events if e == "db_styled_shares_index_missing" and s == "error")
    assert missing == ["styled_shares_token", "styled_shares_ttl"]


def test_a_successful_declaration_sends_no_event(events):
    DatabaseManager._create_styled_shares_indexes(SimpleNamespace(), lambda coll, keys, **kwargs: True)
    assert [e for e, _s, _f in events if e == "db_styled_shares_index_missing"] == []


# ---------------------------------------------------------------------------
# שיתוף של קובץ גדול
# ---------------------------------------------------------------------------

_USER_IDS = itertools.count(910_000)
FILE_ID = "a" * 24


class _Collection:
    def __init__(self, find_result=None):
        self.find_result = find_result
        self.inserted: list[dict] = []

    def find_one(self, *args, **kwargs):
        return self.find_result

    def insert_one(self, doc):
        self.inserted.append(doc)
        return SimpleNamespace(inserted_id="x")


class _ShareDb:
    def __init__(self):
        self.users = _Collection(find_result={"custom_themes": []})
        self.styled_shares = _Collection()

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.fixture
def wa():
    import webapp.app as webapp_app

    return webapp_app


def _member_client(wa):
    """client של משתמש מחובר. מזהה משתמש חדש לכל client: המגביל הגורף סופר לפי ``session['user_id']``,
    והאחסון שלו משותף לכל הטסטים בתהליך (TESTING-PATTERNS T3)."""
    c = wa.app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = next(_USER_IDS)
    return c


@pytest.mark.parametrize("browser_render, field", [(True, "markdown"), (False, "styled_html")])
def test_sharing_a_large_file_stores_its_text(wa, monkeypatch, browser_render, field):
    """הקובץ מ-``large_files``: הטקסט ב-``content`` ואין ``code``. עד התיקון נשמר עמוד בלי התוכן — בשתי הצורות של
    קישור: הטקסט עצמו (ברירת המחדל), וה-HTML שהשרת בונה כש-``STYLED_EXPORT_BROWSER_RENDER`` כבוי."""
    fake_db = _ShareDb()
    large = {"file_name": "big.md", "programming_language": "markdown", "content": "# כותרת\n\nתוכן מהקובץ הגדול"}
    monkeypatch.setattr(wa, "STYLED_EXPORT_BROWSER_RENDER", browser_render)
    monkeypatch.setattr(wa, "is_admin", lambda uid: True)
    monkeypatch.setattr(wa, "get_db", lambda: fake_db)
    monkeypatch.setattr(wa, "_get_user_any_file_by_id", lambda db, uid, fid: (dict(large), "large"))

    resp = _member_client(wa).post(f"/api/export/styled/{FILE_ID}/share", json={"theme": "tech-guide-dark"})

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["ok"] is True
    [stored] = fake_db.styled_shares.inserted
    assert "תוכן מהקובץ הגדול" in stored[field]
