import types
from database.manager import DatabaseManager


class _Coll:
    def __init__(self):
        self.called = False

    def create_indexes(self, indexes):
        self.called = True

    def list_indexes(self):
        return []


class _DB:
    def __init__(self):
        self.users = _Coll()

    def __getitem__(self, name):
        return _Coll()


def test_create_indexes_calls_snippets_indexes():
    # Build a minimal self to run DatabaseManager._create_indexes on
    self = types.SimpleNamespace(
        collection=_Coll(),
        large_files_collection=_Coll(),
        db=_DB(),
        backup_ratings_collection=_Coll(),
        internal_shares_collection=_Coll(),
        community_library_collection=_Coll(),
        snippets_collection=_Coll(),
    )
    DatabaseManager._create_indexes(self)
    assert self.snippets_collection.called is True


def test_create_indexes_covers_snippet_chunks():
    """הקולקציה של החיפוש הסמנטי חייבת אינדקס באתחול הרגיל.

    הרקע (אישו #3332): האינדקס הוגדר רק ב-``scripts/migrate_semantic_search.py``,
    סקריפט חד-פעמי. בקלאסטר שנמדד נותר רק ``_id_``, ולכן כל מחיקת צ'אנקים
    סרקה את כל הקולקציה.

    המחיקות בכל התוכנית — ``save_snippet_chunks``, ``delete_snippet_chunks``
    וג'וב הניקוי — נושאות תמיד גם ``userId`` וגם ``snippetId``, ולכן אינדקס
    אחד בסדר הזה מספיק. סינון לפי ``language`` נעשה בתוך אינדקסי Atlas.
    """
    calls = []

    self = types.SimpleNamespace(
        collection=_Coll(),
        large_files_collection=_Coll(),
        db=_DB(),
        backup_ratings_collection=_Coll(),
        internal_shares_collection=_Coll(),
        community_library_collection=_Coll(),
        snippets_collection=_Coll(),
        safe_create_index=lambda collection, keys, **kwargs: calls.append((collection, keys, kwargs)),
    )
    DatabaseManager._create_indexes(self)

    matching = [c for c in calls if c[0] == "snippet_chunks"]
    assert matching, "snippet_chunks has no index in the regular startup path"
    _name, keys, kwargs = matching[0]
    assert keys == [("userId", 1), ("snippetId", 1)]
    assert kwargs.get("name") == "snippet_chunks_user_snippet_idx"

