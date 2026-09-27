"""אינדקס ה-TTL של סל המיחזור חייב להיבנות בכל עלייה, בשתי הקולקציות.

הרקע: כל מחיקה רכה כותבת ``deleted_expires_at``, ועמוד ``/trash`` מציג אותו
בעמודה "נמחק סופית ב-". אף שורת קוד שלנו לא מוחקת — את העבודה עושה אינדקס
TTL בצד השרת. ב-PR #2525 (2026-01-01) רשימת האינדקסים שבעלייה נכתבה מחדש
כרשימה "מינימלית" של אינדקסי ביצועים, והאינדקס הזה לא נכנס אליה. האשכול
שהוקם אחר כך קיבל רק את מה שהעלייה יוצרת, ולכן מעולם לא היה בו TTL: ב-
2026-09-27 לא היה בו אף אינדקס על ``deleted_expires_at``, לא ב-``code_snippets``
ולא ב-``large_files``, ומסמכים שתאריכם עבר חודשים ישבו בסל (המדידה והשאילתה
שהפיקה אותה — בתיאור ה-PR).

המפרט כתוב כאן במפורש ולא נקרא מהקבועים שבקוד, בכוונה: טסט שגוזר את הציפייה
מאותו מקום שהוא בודק לא יתפוס שינוי מקרי במקום הזה.
"""

from __future__ import annotations

import types

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


def _fake_self(safe_create_index) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        collection=_Coll(),
        large_files_collection=_Coll(),
        db=_DB(),
        backup_ratings_collection=_Coll(),
        internal_shares_collection=_Coll(),
        community_library_collection=_Coll(),
        snippets_collection=_Coll(),
        safe_create_index=safe_create_index,
    )


@pytest.fixture
def emitted(monkeypatch) -> list[tuple]:
    """מה ש-``_create_recycle_bin_ttl_indexes`` פולט, במקום ``emit_event`` האמיתי.

    ההחלפה נעשית במילון שהפונקציה באמת קוראת ממנו (ה-globals של המודול שבו היא
    הוגדרה), ולא דרך ``import database.manager``. בהרצה המלאה יכולים לחיות שני
    עותקים של המודול: אחרי טסט שמשאיר ב-``sys.modules`` מודול ``database`` מדומה,
    ה-fixture ``_reset_database_package_stub_between_tests`` ב-conftest מוציא משם את
    כל ``database.*``, והייבוא הבא טוען עותק חדש. המחלקה שבראש הקובץ נשארת מהעותק
    הראשון, והחלפה דרך ייבוא חדש נוחתת בשני. כך זה נכשל בפועל — רק כשהסדר יצא כך.

    ובלי קשר לזה: ``emit_event`` האמיתי ברמת error נכתב למאגר השגיאות האחרונות של
    ``observability``, שמשותף לכל הטסטים באותו תהליך.
    """
    events: list[tuple] = []
    monkeypatch.setitem(
        DatabaseManager._create_recycle_bin_ttl_indexes.__globals__,
        "emit_event",
        lambda event, severity="info", **fields: events.append((event, severity, fields)),
    )
    return events


def _missing(events: list[tuple]) -> list[str]:
    return sorted(
        fields.get("collection")
        for event, severity, fields in events
        if event == "db_recycle_bin_ttl_index_missing" and severity == "error"
    )


def _ttl_requests(requested: list[tuple], collection: str) -> list[tuple]:
    # ``is not None`` ולא אמיתות: חלון של 0 שניות הוא בדיוק הערך המבוקש כאן,
    # והוא falsy.
    return [
        (keys, kwargs)
        for coll, keys, kwargs in requested
        if coll == collection and kwargs.get("expire_after_seconds") is not None
    ]


@pytest.mark.parametrize("collection", ["code_snippets", "large_files"])
def test_startup_declares_the_recycle_bin_ttl_index(collection):
    requested: list[tuple] = []

    def _safe_create_index(coll, keys, **kwargs):
        requested.append((coll, list(keys), kwargs))
        return True

    DatabaseManager._create_indexes(_fake_self(_safe_create_index))

    ttl = _ttl_requests(requested, collection)
    assert len(ttl) == 1, f"{collection}: אין אינדקס TTL במסלול העלייה — הסל לעולם לא יתרוקן"
    keys, kwargs = ttl[0]
    assert keys == [("deleted_expires_at", 1)]
    # 0: המסמך נמחק בדיוק בתאריך שכתוב בשדה, שהוא התאריך שהעמוד מציג.
    assert kwargs["expire_after_seconds"] == 0
    # רק מה שבסל. גם אם מסלול שחזור ישכח לנקות את התאריך, קובץ פעיל לא יימחק.
    assert kwargs["partial_filter_expression"] == {"is_active": False}
    assert kwargs["name"] == "deleted_ttl"
    # בלי enforce, אינדקס קיים בשם הזה שאינו במפרט (למשל ``deleted_ttl`` בלי
    # המסנן) נשאר במקומו, והאינדקס הרצוי לעולם לא נבנה.
    assert kwargs["enforce"] is True


def test_a_failed_ttl_index_is_reported_as_an_error(emitted):
    """``safe_create_index`` אינו זורק; כשל חוזר כ-``False`` (K11).

    לאינדקס ביצועים זו איטיות, ולכן רוב הקוראים מתעלמים מהערך. כאן זו הבטחה
    שבורה למשתמש — ולכן הכשל חייב לצאת כאירוע ברמת error ולא להיבלע.
    """

    def _safe_create_index(coll, keys, **kwargs):
        # רק אינדקס ה-TTL נכשל; שאר האינדקסים "מצליחים".
        is_recycle_ttl = kwargs.get("expire_after_seconds") is not None and coll in (
            "code_snippets",
            "large_files",
        )
        return not is_recycle_ttl

    DatabaseManager._create_indexes(_fake_self(_safe_create_index))

    assert _missing(emitted) == ["code_snippets", "large_files"]


def test_ensure_reports_the_status_of_each_collection(emitted):
    """הפקודה ``/recycle_backfill`` מדווחת לפי הערך הזה — לכל קולקציה בנפרד."""
    outcomes = {"code_snippets": True, "large_files": False}

    def _safe_create_index(coll, keys, **kwargs):
        return outcomes[coll]

    fake = types.SimpleNamespace(safe_create_index=_safe_create_index)
    assert DatabaseManager.ensure_recycle_bin_ttl_indexes(fake) == outcomes
    # האירוע יוצא רק על הקולקציה שנכשלה.
    assert _missing(emitted) == ["large_files"]


class TestIsRecycleBinTtlIndex:
    """הזיהוי של אינדקס קיים מול המפרט — משמש את ``/admin/verify-indexes``.

    השורות כאן בצורה ש-``list_indexes`` מחזיר.
    """

    @staticmethod
    def _row(**overrides):
        row = {
            "v": 2,
            "key": {"deleted_expires_at": 1},
            "name": "deleted_ttl",
            "expireAfterSeconds": 0,
            "partialFilterExpression": {"is_active": False},
        }
        row.update(overrides)
        return {k: v for k, v in row.items() if v is not None}

    def test_the_declared_index_matches(self):
        from file_deletion import is_recycle_bin_ttl_index

        assert is_recycle_bin_ttl_index(self._row()) is True

    def test_a_ttl_without_the_partial_filter_does_not_match(self):
        """כך נראה ``deleted_ttl`` שנוצר לפני המסנן (PR #648, ``/recycle_backfill``)."""
        from file_deletion import is_recycle_bin_ttl_index

        assert is_recycle_bin_ttl_index(self._row(partialFilterExpression=None)) is False

    def test_a_plain_index_on_the_field_does_not_match(self):
        from file_deletion import is_recycle_bin_ttl_index

        assert is_recycle_bin_ttl_index(self._row(expireAfterSeconds=None)) is False

    def test_a_different_expiry_window_does_not_match(self):
        from file_deletion import is_recycle_bin_ttl_index

        assert is_recycle_bin_ttl_index(self._row(expireAfterSeconds=3600)) is False

    def test_a_compound_key_does_not_match(self):
        """אינדקס TTL הוא חד-שדה; השרת דוחה TTL על מפתח מורכב (נמדד מול 8.0.32).
        הבדיקה נשארת כי השורה מגיעה מחוץ לתהליך."""
        from file_deletion import is_recycle_bin_ttl_index

        row = self._row(key={"deleted_expires_at": 1, "user_id": 1})
        assert is_recycle_bin_ttl_index(row) is False

    def test_the_name_is_not_what_matters(self):
        """מונגו מוחק לפי המפרט, לא לפי השם — אינדקס תקין בשם אחר עושה את העבודה."""
        from file_deletion import is_recycle_bin_ttl_index

        assert is_recycle_bin_ttl_index(self._row(name="deleted_expires_at_1")) is True

    def test_garbage_is_not_an_index(self):
        from file_deletion import is_recycle_bin_ttl_index

        assert is_recycle_bin_ttl_index(None) is False
        assert is_recycle_bin_ttl_index({"key": "deleted_expires_at"}) is False
