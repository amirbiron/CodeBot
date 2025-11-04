from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

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

    def find_one(self, flt: Dict[str, Any]):
        for d in self.docs:
            if _match(d, flt):
                return dict(d)
        return None

    def find(self, flt: Dict[str, Any]):
        return [dict(d) for d in self.docs if _match(d, flt)]


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


class FakeDB:
    def __init__(self) -> None:
        self.user_collections = FakeCollection()
        self.collection_items = FakeCollection()
        self.code_snippets = FakeCollection()
        self.large_files = FakeCollection()


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
    assert on["collection"]["share"]["visibility"] in {"link", "private"}  # default to link

    off = mgr.set_share(10, cid, enabled=False)
    assert off["ok"] and off["collection"]["share"]["enabled"] is False  # type: ignore[index]
    # token נשמר גם אם השיתוף כבוי
    assert off["collection"]["share"]["token"] == token  # type: ignore[index]
    assert off["collection"]["share"]["visibility"] == "private"  # type: ignore[index]


def test_set_share_invalid_visibility_and_bad_id(mgr: CollectionsManager):
    cid = _create_collection(mgr, 11)
    bad_vis = mgr.set_share(11, cid, enabled=True, visibility="wrong")
    assert not bad_vis["ok"]

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
