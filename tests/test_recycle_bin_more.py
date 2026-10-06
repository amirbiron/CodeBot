import types
import pytest


@pytest.mark.asyncio
async def test_recycle_pagination_and_invalid_actions(monkeypatch):
    import conversation_handlers as ch

    class DummyRepo:
        def list_deleted_files(self, user_id, page=1, per_page=10):
            # Return different items per page to exercise nav
            if page == 1:
                items = [{"_id": "id1", "file_name": "a.py"}] * per_page
            else:
                items = [{"_id": "id2", "file_name": "b.js"}] * 5
            total = per_page + 5  # 2 pages
            return (items, total)
        def restore_file_by_id(self, user_id, fid):
            return True
        def purge_file_by_id(self, user_id, fid):
            return True

    class DummyDB:
        def __init__(self, repo):
            self._repo = repo
        def _get_repo(self):
            return self._repo

    repo = DummyRepo()
    mod = types.ModuleType("database")
    mod.db = DummyDB(repo)
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    captured = {"reply_markup": None}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured["reply_markup"] = reply_markup
    from utils import TelegramUtils
    monkeypatch.setattr(TelegramUtils, "safe_edit_message_text", fake_safe_edit_message_text)

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
            return types.SimpleNamespace(id=7)

    class Ctx:
        def __init__(self):
            self.user_data = {}

    # Page 2 triggers nav "previous" button existence
    u = U("recycle_page_2")
    c = Ctx()
    await ch.show_recycle_bin(u, c)
    rm = captured.get("reply_markup")
    assert rm is not None
    nav_row = rm.inline_keyboard[-2] if len(rm.inline_keyboard) >= 2 else []
    # Expect at least one nav button present
    assert any(btn.callback_data.startswith("recycle_page_") for btn in nav_row)

    # Invalid restore (missing id) answers with alert
    u2 = U("recycle_restore:")
    await ch.recycle_restore(u2, c)
    assert any(k.get("show_alert") for k in u2.callback_query.answers)

    # Invalid purge (missing id) answers with alert
    u3 = U("recycle_purge:")
    await ch.recycle_purge(u3, c)
    assert any(k.get("show_alert") for k in u3.callback_query.answers)


def test_repository_delete_by_id_and_large_files(monkeypatch):
    """מחיקה, שחזור ומחיקה סופית לפי מזהה — כולן לפי **שם** בשאילתה.

    הסטאב מחזיק מסמכים ומכבד את המסננים. קודם הוא החזיר הצלחה לכל
    שאילתה, ולכן לא היה יכול להבדיל בין "כל הגרסאות" לבין "הגרסה
    שנשלחה" — בדיוק ההבדל שהבאג חי בו.
    """
    from database.repository import Repository
    from datetime import datetime
    from bson import ObjectId

    class DummyCollection:
        def __init__(self, docs=()):
            self.docs = [dict(d) for d in docs]
            self.updated = None
            self.deleted = None
            self.pipelines = []

        def _matching(self, flt):
            def _in(value):
                return value.get("$in") if isinstance(value, dict) else None

            ids = _in(flt.get("_id"))
            names = _in(flt.get("file_name"))
            name = flt.get("file_name") if isinstance(flt.get("file_name"), str) else None
            out = []
            for d in self.docs:
                if "user_id" in flt and d.get("user_id") != flt.get("user_id"):
                    continue
                if "is_active" in flt and d.get("is_active") is not flt.get("is_active"):
                    continue
                if ids is not None and d.get("_id") not in ids:
                    continue
                if names is not None and d.get("file_name") not in names:
                    continue
                if name is not None and d.get("file_name") != name:
                    continue
                out.append(d)
            return out

        def find(self, query, projection=None, *a, **k):
            # חתימה כמו של pymongo: ההיטלה היא הארגומנט הפוזיציוני השני.
            return [dict(d) for d in self._matching(query)]

        def update_many(self, flt, upd):
            self.updated = (flt, upd)
            hits = self._matching(flt)
            for d in hits:
                d.update(upd.get("$set") or {})
                for key in (upd.get("$unset") or {}):
                    d.pop(key, None)
            return types.SimpleNamespace(modified_count=len(hits))

        def delete_many(self, flt):
            self.deleted = flt
            hits = self._matching(flt)
            for d in hits:
                self.docs.remove(d)
            return types.SimpleNamespace(deleted_count=len(hits))

        def count_documents(self, flt=None, *a, **k):
            return len(self._matching(flt or {}))

        def aggregate(self, pipeline, *a, **k):
            # ‏``$count`` ו-``$limit`` הם שני צינורות שונים על אותו קלט,
            # ולכן סטאב שמחזיר את אותה שורה לשניהם מדווח ``total`` שגוי.
            self.pipelines.append(pipeline)
            rows = [{"_id": d["_id"], "file_name": d["file_name"], "versions": 1}
                    for d in self.docs if d.get("is_active") is False]
            if any("$count" in stage for stage in pipeline):
                return [{"total": len(rows)}] if rows else []
            return rows

        def distinct(self, key, filter=None, *a, **k):
            return sorted({d[key] for d in self._matching(filter or {}) if key in d})

    def _versions(file_name, count, *, user_id, is_active):
        return [{"_id": ObjectId(), "user_id": user_id, "file_name": file_name,
                 "version": v, "is_active": is_active}
                for v in range(1, count + 1)]

    class DummyManager:
        def __init__(self, docs=(), large=()):
            self.collection = DummyCollection(docs)
            self.large_files_collection = DummyCollection(large)

    # מחיקה לפי מזהה — המסנן שיוצא הוא **לפי שם**, כי המזהה מסמן גרסה
    # אחת בלבד והמחיקה היא של הקובץ כולו.
    active = _versions("z.py", 3, user_id=1, is_active=True)
    mgr = DummyManager(active)
    repo = Repository(mgr)
    rc = repo.soft_delete_files_by_ids(1, [str(active[-1]["_id"])])
    assert rc == {"files": 1, "versions": 3, "missing": 0}, rc
    _flt, _upd = mgr.collection.updated
    assert "_id" not in _flt, _flt
    assert _flt["file_name"]["$in"] == ["z.py"], _flt
    assert _upd["$set"]["is_active"] is False
    assert isinstance(_upd["$set"]["deleted_at"], datetime)
    assert isinstance(_upd["$set"]["deleted_expires_at"], datetime)
    assert all(d["is_active"] is False for d in mgr.collection.docs)

    # קבצים גדולים — לפי שם ולפי מזהה. שני מסמכים ולא אחד: שתי הפעולות
    # מסננות ``is_active: True``, ולכן השנייה על אותו מסמך אינה מוצאת כלום.
    by_name = _versions("big.txt", 1, user_id=3, is_active=True)
    by_id = _versions("other.txt", 1, user_id=3, is_active=True)
    mgr_large = DummyManager(large=by_name + by_id)
    repo_large = Repository(mgr_large)
    assert repo_large.delete_large_file(user_id=3, file_name="big.txt") is True
    assert repo_large.delete_large_file_by_id(str(by_id[0]["_id"])) is True
    assert all(d["is_active"] is False for d in mgr_large.large_files_collection.docs)

    # רשימת הסל — ``total`` סופר קבצים, ו-``$count`` הוא צינור נפרד
    trashed = _versions("t.py", 2, user_id=1, is_active=False)
    mgr_list = DummyManager(trashed)
    items, total = Repository(mgr_list).list_deleted_files(user_id=1, page=1, per_page=10)
    assert isinstance(items, list) and isinstance(total, int)
    assert total == len(items), (total, items)

    # שחזור ומחיקה סופית — כל הגרסאות, דרך מזהה של אחת מהן
    trashed = _versions("t.py", 2, user_id=1, is_active=False)
    mgr_r = DummyManager(trashed)
    repo_r = Repository(mgr_r)
    assert repo_r.restore_file_by_id(user_id=1, file_id=str(trashed[0]["_id"])) is True
    assert all(d["is_active"] is True for d in mgr_r.collection.docs)

    trashed = _versions("t.py", 2, user_id=1, is_active=False)
    mgr_p = DummyManager(trashed)
    repo_p = Repository(mgr_p)
    assert repo_p.purge_file_by_id(user_id=1, file_id=str(trashed[1]["_id"])) is True
    assert mgr_p.collection.docs == []
