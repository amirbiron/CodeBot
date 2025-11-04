from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pytest

from database.collections_manager import CollectionsManager, ObjectId


class FakeCollection:
    def __init__(self) -> None:
        self.docs: List[Dict[str, Any]] = []

    def create_indexes(self, *a, **k):
        return None

    def insert_one(self, doc: Dict[str, Any]):
        if "_id" not in doc or not doc["_id"]:
            doc["_id"] = f"oid{len(self.docs)+1}"
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc["_id"])  # type: ignore[attr-defined]

    def update_one(self, flt: Dict[str, Any], upd: Dict[str, Any], **kwargs):
        modified = 0
        for d in self.docs:
            if _match(d, flt):
                _apply_update(d, upd)
                modified += 1
                break
        return SimpleNamespace(modified_count=modified)  # type: ignore[attr-defined]

    def find_one(
        self,
        flt: Dict[str, Any],
        projection: Optional[Dict[str, int]] = None,
        sort: Optional[List[Tuple[str, int]]] = None,
    ) -> Optional[Dict[str, Any]]:
        rows = self.find(flt, projection=projection)
        if sort:
            for field, direction in reversed(sort):
                reverse = int(direction or 0) < 0
                rows.sort(key=lambda doc: _sort_value(doc, field), reverse=reverse)
        if rows:
            return dict(rows[0])
        return None

    def find(self, flt: Dict[str, Any], projection: Optional[Dict[str, int]] = None):
        rows = [dict(d) for d in self.docs if _match(d, flt)]
        if projection:
            rows = [_apply_projection(doc, projection) for doc in rows]
        return rows


def _getv(d: Dict[str, Any], key: str) -> Any:
    if not isinstance(d, dict):
        return None
    cur: Any = d
    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _match(doc: Dict[str, Any], flt: Dict[str, Any]) -> bool:
    def m(d: Dict[str, Any], f: Dict[str, Any]) -> bool:
        for k, v in f.items():
            if k == "$or" and isinstance(v, list):
                if not any(isinstance(cond, dict) and m(d, cond) for cond in v):
                    return False
                continue
            actual = _getv(d, k)
            if isinstance(v, dict):
                if "$in" in v:
                    if actual not in v["$in"]:
                        return False
                    continue
                if "$exists" in v:
                    should_exist = bool(v["$exists"])
                    # קיום שדה (נחשב קיים אם הערך אינו None)
                    exists = _getv(d, k) is not None
                    if should_exist != exists:
                        return False
                    continue
            # default equality (string-compare for stability)
            if str(actual) != str(v):
                return False
        return True
    return m(doc, flt)


def _apply_update(doc: Dict[str, Any], upd: Dict[str, Any]) -> None:
    if "$set" in upd and isinstance(upd["$set"], dict):
        for k, v in upd["$set"].items():
            # תמיכה בנתיב מקונן כמו share.token
            parts = k.split(".")
            cur = doc
            for p in parts[:-1]:
                cur.setdefault(p, {})
                cur = cur[p]
            cur[parts[-1]] = v
    if "$unset" in upd and isinstance(upd["$unset"], dict):
        for k in upd["$unset"].keys():
            if k in doc:
                del doc[k]


def _apply_projection(doc: Dict[str, Any], projection: Dict[str, int | bool]) -> Dict[str, Any]:
    result = dict(doc)
    for field, mode in projection.items():
        drop = False
        try:
            drop = int(mode) == 0
        except Exception:
            drop = not bool(mode)
        if drop and field in result:
            result.pop(field, None)
    return result


def _sort_value(doc: Dict[str, Any], field: str) -> Any:
    value = _getv(doc, field)
    if isinstance(value, datetime):
        try:
            return value.timestamp()
        except Exception:
            return 0.0
    return value


class FakeDB:
    def __init__(self) -> None:
        self.user_collections = FakeCollection()
        self.collection_items = FakeCollection()
        self.code_snippets = FakeCollection()
        self.large_files = FakeCollection()
        self.collection_share_activity = FakeCollection()


@pytest.fixture()
def mgr() -> CollectionsManager:
    return CollectionsManager(FakeDB())


def _create_collection(mgr: CollectionsManager, user_id: int = 1) -> str:
    res = mgr.create_collection(user_id, "ShareTest")
    assert res["ok"]
    return str(res["collection"]["id"])  # type: ignore[index]


def test_set_share_enable_generates_token_and_disable_preserves_token(mgr: CollectionsManager):
    cid = _create_collection(mgr, 10)

    on = mgr.set_share(10, cid, enabled=True)
    assert on["ok"] and on["collection"]["share"]["enabled"] is True  # type: ignore[index]
    token = on["collection"]["share"]["token"]  # type: ignore[index]
    assert isinstance(token, str) and len(token) > 0

    off = mgr.set_share(10, cid, enabled=False)
    assert off["ok"] and off["collection"]["share"]["enabled"] is False  # type: ignore[index]
    # token נשמר גם אם השיתוף כבוי
    assert off["collection"]["share"]["token"] == token  # type: ignore[index]


def test_set_share_bad_id(mgr: CollectionsManager):
    cid = _create_collection(mgr, 11)
    bad_id = mgr.set_share(11, "not-an-id", enabled=True)
    assert not bad_id["ok"]


def test_get_collection_by_share_token_found_and_not_found(mgr: CollectionsManager):
    cid = _create_collection(mgr, 12)
    on = mgr.set_share(12, cid, enabled=True)
    token = on["collection"]["share"]["token"]  # type: ignore[index]

    ok = mgr.get_collection_by_share_token(token)
    assert ok["ok"] and ok["collection"]["id"] == cid  # type: ignore[index]

    not_found = mgr.get_collection_by_share_token("no-such-token")
    assert not not_found["ok"]


def test_is_file_active_for_regular_and_large_and_exception_path(mgr: CollectionsManager):
    # הכנת אוסף ופריטים ידניים
    cid = _create_collection(mgr, 20)
    # regular item
    mgr.add_items(20, cid, [{"source": "regular", "file_name": "a.py"}])
    # large item
    mgr.add_items(20, cid, [{"source": "large", "file_name": "b.big"}])

    # סימון קבצים פעילים ב-DB: מסמך regular קיים; large קיים
    mgr.code_snippets.insert_one({"user_id": 20, "file_name": "a.py", "is_active": True})  # type: ignore[attr-defined]
    mgr.large_files.insert_one({"user_id": 20, "file_name": "b.big", "is_active": True})  # type: ignore[attr-defined]

    out = mgr.get_collection_items(20, cid, page=1, per_page=10, include_computed=False)
    assert out["ok"]
    by_name = {it["file_name"]: it for it in out["items"]}
    assert by_name["a.py"]["is_file_active"] is True
    assert by_name["b.big"]["is_file_active"] is True

    # הפוך: regular לא קיים -> False; large is_active=False -> לא יימצא -> False
    # מחיקת המסמך הרגיל: ננקה את docs ידנית
    mgr.code_snippets.docs = []  # type: ignore[attr-defined]
    mgr.large_files.docs = [{"user_id": 20, "file_name": "b.big", "is_active": False}]  # type: ignore[attr-defined]
    out2 = mgr.get_collection_items(20, cid, page=1, per_page=10, include_computed=False)
    assert out2["ok"]
    by_name2 = {it["file_name"]: it for it in out2["items"]}
    assert by_name2["a.py"]["is_file_active"] is False
    assert by_name2["b.big"]["is_file_active"] is False

    # מסלול חריגות: large_files.find_one יזרוק — המנג'ר צריך לסמן True (fail-open)
    class Boom:
        def find_one(self, *a, **k):  # pragma: no cover - exercised here
            raise RuntimeError("db down")
    mgr.large_files = Boom()  # type: ignore[assignment]
    out3 = mgr.get_collection_items(20, cid, page=1, per_page=10, include_computed=False)
    assert out3["ok"]
    by_name3 = {it["file_name"]: it for it in out3["items"]}
    # ה-regular עדיין False (אין מסמך), אך large נהיה True בגלל fail-open
    assert by_name3["a.py"]["is_file_active"] is False
    assert by_name3["b.big"]["is_file_active"] is True


def test_share_context_and_file_details_for_regular_item(mgr: CollectionsManager):
    cid = _create_collection(mgr, 30)
    mgr.add_items(30, cid, [{"source": "regular", "file_name": "snippet.py"}])
    now = datetime.now()
    mgr.code_snippets.insert_one({
        "_id": "code1",
        "user_id": 30,
        "file_name": "snippet.py",
        "code": "print('hi')\n",
        "programming_language": "python",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    })  # type: ignore[attr-defined]
    share = mgr.set_share(30, cid, enabled=True)
    assert share["ok"]
    token = share["collection"]["share"]["token"]  # type: ignore[index]
    ctx = mgr.get_share_context(token)
    assert ctx["ok"]
    doc_refs = ctx["doc_refs"]
    assert len(doc_refs) == 1
    doc_id = next(iter(doc_refs))
    details = mgr.get_shared_file_details(token, doc_id)
    assert details["ok"]
    payload = details["file"]
    assert payload["file_name"] == "snippet.py"
    assert payload["content"].startswith("print")
    exported = mgr.collect_shared_documents(token)
    assert exported["ok"]
    assert len(exported["documents"]) == 1
    assert exported["documents"][0]["file_name"] == "snippet.py"
    mgr.log_share_activity(token, collection_id=ctx["collection_id"], file_id=doc_id, event="view", ip="1.2.3.4", user_agent="pytest")
    assert len(mgr.share_activity.docs) == 1  # type: ignore[attr-defined]


def test_share_context_handles_large_file(mgr: CollectionsManager):
    cid = _create_collection(mgr, 31)
    mgr.add_items(31, cid, [{"source": "large", "file_name": "big.log"}])
    now = datetime.now()
    mgr.large_files.insert_one({
        "_id": "large1",
        "user_id": 31,
        "file_name": "big.log",
        "content": "large content",
        "programming_language": "text",
        "file_size": 13,
        "lines_count": 1,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    })  # type: ignore[attr-defined]
    share = mgr.set_share(31, cid, enabled=True)
    token = share["collection"]["share"]["token"]  # type: ignore[index]
    ctx = mgr.get_share_context(token)
    assert ctx["ok"]
    doc_id = next(iter(ctx["doc_refs"]))
    details = mgr.get_shared_file_details(token, doc_id)
    assert details["ok"]
    assert details["file"]["source"] == "large"
    exported = mgr.collect_shared_documents(token)
    assert exported["ok"]
    assert exported["documents"][0]["content"] == "large content"
