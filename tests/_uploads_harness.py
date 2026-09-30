"""אחסון ההעלאות של שירות ה-MCP מעל הדמה המשותפת — לטסטים שעוברים דרך ``ProductionBackend``.

פונקציות ומחלקות ולא fixtures (T3), כמו ``_save_layer_harness.py``.

**ההצהרה והאימות הם הקוד האמיתי.** ``ensure_mcp_uploads_indexes`` כאן מריץ את
``DatabaseManager._create_mcp_uploads_indexes`` ואת ``safe_create_index`` האמיתיים,
מעל מסד מדומה; ורק האוסף עצמו — :class:`IndexedCollection` — מדומה. כך שער
המוכנות (``ProductionBackend.upload_storage_ready``) נפתח רק כשהקוד שרץ בעלייה
באמת ביקש TTL במפרט, והקריאה החוזרת (``list_indexes``) באמת מצאה אותו.
"""

from __future__ import annotations

from typing import Any

from _fake_mongo import FakeCollection, FakeDB


class IndexedCollection(FakeCollection):
    """``FakeCollection`` שזוכר את האינדקסים שלו בצורה ש-``list_indexes()`` מחזיר.

    ``refuse_ttl`` — יצירת אינדקס עם ``expireAfterSeconds`` נכשלת, כמו מסד שאינו
    מאפשר אותה. ``safe_create_index`` תופס ומחזיר ``False``, כמו מול מונגו אמיתי.

    **``is not None`` ולא אמיתות:** ``expireAfterSeconds`` הוא ``0``, ו-``0`` שקרי —
    ובפייתון גם ``0 == False``. שורה שהייתה מסננת לפי אמיתות הייתה מאבדת בדיוק את
    ה-TTL שהטסטים בודקים.
    """

    def __init__(self, *, refuse_ttl: bool = False) -> None:
        super().__init__()
        self.indexes: dict[str, dict[str, Any]] = {}
        self.refuse_ttl = refuse_ttl

    def create_index(self, keys, **kwargs):
        if self.refuse_ttl and kwargs.get("expireAfterSeconds") is not None:
            raise RuntimeError("simulated: this deployment cannot build a TTL index")
        name = kwargs["name"]
        row: dict[str, Any] = {"v": 2, "key": dict(keys), "name": name}
        if kwargs.get("unique") is True:
            row["unique"] = True
        if kwargs.get("expireAfterSeconds") is not None:
            row["expireAfterSeconds"] = kwargs["expireAfterSeconds"]
        if kwargs.get("partialFilterExpression") is not None:
            row["partialFilterExpression"] = kwargs["partialFilterExpression"]
        self.indexes[name] = row
        return name

    def list_indexes(self):
        return iter([{"v": 2, "key": {"_id": 1}, "name": "_id_"}, *self.indexes.values()])


class UploadsDbm:
    """``DatabaseManager`` מינימלי מעל ``db``: ההצהרה והאימות — הקוד האמיתי."""

    def __init__(self, db: Any) -> None:
        self.db = db

    def safe_create_index(self, *args: Any, **kwargs: Any) -> bool:
        from database.manager import DatabaseManager

        return DatabaseManager.safe_create_index(self, *args, **kwargs)

    def ensure_mcp_uploads_indexes(self) -> dict[str, bool]:
        from database.manager import DatabaseManager

        return DatabaseManager.ensure_mcp_uploads_indexes(self)


def upload_storage(*, refuse_ttl: bool = False) -> tuple[FakeDB, IndexedCollection]:
    """מסד מדומה שאוסף ההעלאות שלו זוכר אינדקסים."""
    from mcp_uploads import MCP_UPLOADS_COLLECTION

    db = FakeDB()
    uploads = IndexedCollection(refuse_ttl=refuse_ttl)
    db.c[MCP_UPLOADS_COLLECTION] = uploads
    return db, uploads


def install_upload_storage(monkeypatch, store) -> IndexedCollection:
    """מחבר את אחסון ההעלאות ל-``store`` של ``_save_layer_harness.install_fake_collections``.

    שם ``database.db`` הוא ה-``DatabaseManager`` האמיתי, בלי חיבור; ההצהרה מופנית
    כאן ל-``store.raw`` — המסד שה-backend מקבל כ-``mongo_db`` — דרך הקוד האמיתי.
    """
    from mcp_uploads import MCP_UPLOADS_COLLECTION

    uploads = IndexedCollection()
    store.raw.c[MCP_UPLOADS_COLLECTION] = uploads
    on_raw = UploadsDbm(store.raw)
    # ``setitem`` על ``vars`` ולא ``setattr``: ``database.db`` הוא סינגלטון של התהליך,
    # ו-``setattr`` היה משאיר בסוף הטסט מתודה קשורה במילון של המופע. כאן המפתח נמחק.
    monkeypatch.setitem(vars(store.dbm), "ensure_mcp_uploads_indexes", on_raw.ensure_mcp_uploads_indexes)
    return uploads
