import types
import pytest


@pytest.mark.asyncio
async def test_recycle_restore_and_purge_invalid_id(monkeypatch):
    import conversation_handlers as ch

    class DummyRepo:
        def list_deleted_files(self, user_id, page=1, per_page=10):
            return ([], 0)
        def restore_file_by_id(self, user_id, fid):
            return False
        def purge_file_by_id(self, user_id, fid):
            return False

    class DummyDB:
        def __init__(self, repo):
            self._repo = repo
        def _get_repo(self):
            return self._repo

    mod = types.ModuleType("database")
    mod.db = DummyDB(DummyRepo())
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    class Q:
        def __init__(self, data):
            self.data = data
            self.answers = []
        async def answer(self, *a, **k):
            self.answers.append(k)

    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=99)

    class Ctx:
        def __init__(self):
            self.user_data = {}

    u = U("recycle_restore:")
    await ch.recycle_restore(u, Ctx())
    assert any(a.get("show_alert") for a in u.callback_query.answers)

    u2 = U("recycle_purge:")
    await ch.recycle_purge(u2, Ctx())
    assert any(a.get("show_alert") for a in u2.callback_query.answers)


def test_repository_restore_and_purge_paths(monkeypatch):
    """המסלולים לפי מזהה, כשהמזהה שייך לקובץ שבסל.

    הפעולות עוברות עכשיו דרך ``file_deletion``, ולכן הן קודם **קוראות**:
    המזהה מתורגם לשם קובץ (``resolve_trashed_file_names``), ואז נאספים
    מזהי כל גרסאות הסל של אותו שם — כדי שהצ'אנקים והסימון לאינדוקס לא
    יקבלו גרסה אחת מתוך כמה. הסטאב כאן מכבד את המסננים, כי סטאב שמחזיר
    הצלחה לכל שאילתה אינו בודק דבר.
    """
    from database.repository import Repository
    from bson import ObjectId

    class DummyCollection:
        def __init__(self, docs=()):
            self.docs = [dict(d) for d in docs]
            self.update_calls = []
            self.delete_calls = []

        def find(self, query, projection=None, *a, **k):
            ids = (query.get("_id") or {}).get("$in")
            names = (query.get("file_name") or {}).get("$in")
            out = []
            for d in self.docs:
                if d.get("user_id") != query.get("user_id"):
                    continue
                if d.get("is_active") is not query.get("is_active"):
                    continue
                if ids is not None and d.get("_id") not in ids:
                    continue
                if names is not None and d.get("file_name") not in names:
                    continue
                out.append(dict(d))
            return out

        def update_many(self, flt, upd):
            self.update_calls.append((flt, upd))
            names = (flt.get("file_name") or {}).get("$in") or []
            n = 0
            for d in self.docs:
                if (d.get("user_id") == flt.get("user_id")
                        and d.get("file_name") in names
                        and d.get("is_active") is flt.get("is_active")):
                    d.update(upd.get("$set") or {})
                    for key in (upd.get("$unset") or {}):
                        d.pop(key, None)
                    n += 1
            return types.SimpleNamespace(modified_count=n)

        def delete_many(self, flt):
            self.delete_calls.append(flt)
            names = (flt.get("file_name") or {}).get("$in") or []
            before = len(self.docs)
            self.docs = [
                d for d in self.docs
                if not (d.get("user_id") == flt.get("user_id")
                        and d.get("file_name") in names
                        and d.get("is_active") is flt.get("is_active"))
            ]
            return types.SimpleNamespace(deleted_count=before - len(self.docs))

        def count_documents(self, *a, **k):
            return 0

        def aggregate(self, *a, **k):
            return []

    def _trashed(file_name, versions):
        return [{"_id": ObjectId(), "user_id": 5, "file_name": file_name,
                 "version": v, "is_active": False} for v in range(1, versions + 1)]

    class DummyManager:
        def __init__(self, docs):
            self.collection = DummyCollection(docs)
            self.large_files_collection = DummyCollection()

    # שחזור: המזהה הוא של הגרסה האמצעית, וכל השלוש חוזרות.
    docs = _trashed("a.py", 3)
    mgr = DummyManager(docs)
    repo = Repository(mgr)
    assert repo.restore_file_by_id(user_id=5, file_id=str(docs[1]["_id"])) is True
    assert all(d["is_active"] is True for d in mgr.collection.docs), mgr.collection.docs
    # והמסנן עצמו לפי שם ולא לפי מזהה — אחרת הטענה למעלה עוברת במקרה.
    assert "_id" not in mgr.collection.update_calls[-1][0]

    # מחיקה סופית: אותו דבר, ואין שארית.
    docs = _trashed("b.py", 2)
    mgr = DummyManager(docs)
    repo = Repository(mgr)
    assert repo.purge_file_by_id(user_id=5, file_id=str(docs[0]["_id"])) is True
    assert mgr.collection.docs == []
    # המסנן לפי שם, ותחום ל**כל** מזהי הקובץ שבסל — לא למזהה הבודד שהגיע
    # מהממשק. התחימה ל-``_id`` היא מה שמאפשר להשוות ``deleted_count`` למה
    # שנאסף (``purge_files_by_names``).
    flt = mgr.collection.delete_calls[-1]
    assert flt["file_name"] == {"$in": ["b.py"]}, flt
    assert set(flt["_id"]["$in"]) == {d["_id"] for d in docs}, flt


def test_an_id_that_is_not_in_the_trash_is_not_a_success(monkeypatch):
    """מזהה של משתמש אחר, או של קובץ **פעיל**, אינו מצליח בשקט.

    ``resolve_trashed_file_names`` אוכף גם בעלות וגם ``is_active: False``
    בשאילתה, ולכן אין כאן בדיקה מקדימה שניתן לדלג עליה.
    """
    from database.repository import Repository
    from bson import ObjectId

    active = {"_id": ObjectId(), "user_id": 5, "file_name": "live.py",
              "version": 1, "is_active": True}
    theirs = {"_id": ObjectId(), "user_id": 6, "file_name": "theirs.py",
              "version": 1, "is_active": False}

    class _Coll:
        def __init__(self):
            self.docs = [dict(active), dict(theirs)]
            self.writes = 0

        def find(self, query, projection=None, *a, **k):
            ids = (query.get("_id") or {}).get("$in")
            return [
                dict(d) for d in self.docs
                if d["user_id"] == query.get("user_id")
                and d["is_active"] is query.get("is_active")
                and (ids is None or d["_id"] in ids)
            ]

        def update_many(self, *a, **k):
            self.writes += 1
            return types.SimpleNamespace(modified_count=0)

        def delete_many(self, *a, **k):
            self.writes += 1
            return types.SimpleNamespace(deleted_count=0)

        def count_documents(self, *a, **k):
            return 0

        def aggregate(self, *a, **k):
            return []

    class _Mgr:
        def __init__(self):
            self.collection = _Coll()
            self.large_files_collection = _Coll()

    mgr = _Mgr()
    repo = Repository(mgr)

    assert repo.restore_file_by_id(user_id=5, file_id=str(active["_id"])) is False
    assert repo.purge_file_by_id(user_id=5, file_id=str(theirs["_id"])) is False
    assert mgr.collection.writes == 0, "נשלחה כתיבה על מזהה שאינו בסל של המשתמש"
    assert mgr.large_files_collection.writes == 0
