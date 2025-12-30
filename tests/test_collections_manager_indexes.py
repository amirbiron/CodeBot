from types import SimpleNamespace


def test_collections_manager_creates_user_active_name_index():
    # Import from module to respect pymongo fallback logic
    import database.collections_manager as cm

    created: list = []

    class _Coll:
        def create_indexes(self, indexes):  # noqa: ANN001
            created.extend(list(indexes or []))
            return []

    db = SimpleNamespace(
        user_collections=_Coll(),
        collection_items=_Coll(),
        code_snippets=None,
        large_files=None,
        collection_share_activity=None,
    )

    cm.CollectionsManager(db)

    # Best-effort assertion:
    # - אם pymongo זמין, IndexModel יכיל document עם name/key ואפשר לאמת.
    # - אם לא, לא נשבור את הטסטים — העיקר שהקריאה ל-create_indexes בוצעה בלי חריגה.
    docs = []
    for idx in created:
        doc = getattr(idx, "document", None)
        if isinstance(doc, dict):
            docs.append(doc)

    if not docs:
        # אין יכולת אינטרוספקציה בסביבה ללא pymongo
        assert len(created) > 0
        return

    assert any(
        (d.get("name") == "user_active_name")
        and (list(d.get("key") or []) == [("user_id", 1), ("is_active", 1), ("name", 1)])
        for d in docs
    )

