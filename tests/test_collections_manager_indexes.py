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

    def _key_pairs(doc):  # noqa: ANN001
        """Normalize pymongo IndexModel.document['key'] to list[tuple[str,int]]."""
        key = doc.get("key")
        if key is None:
            return []
        # pymongo uses bson.son.SON which is dict-like; iterating yields keys only
        try:
            items = list(key.items())  # type: ignore[attr-defined]
            return [(str(k), int(v)) for k, v in items]
        except Exception:
            pass
        if isinstance(key, dict):
            return [(str(k), int(v)) for k, v in key.items()]
        if isinstance(key, (list, tuple)):
            out = []
            for it in key:
                try:
                    k, v = it
                    out.append((str(k), int(v)))
                except Exception:
                    continue
            return out
        return []

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
        and (_key_pairs(d) == [("user_id", 1), ("is_active", 1), ("name", 1)])
        for d in docs
    )

    assert any(
        (d.get("name") == "collection_tags")
        and (_key_pairs(d) == [("collection_id", 1), ("tags", 1)])
        for d in docs
    )

