from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class _Result:
    modified_count: int = 0
    deleted_count: int = 0


class _FakeCursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = list(docs)
        self._offset = 0
        self._limit: Optional[int] = None

    def skip(self, n: int):
        self._offset = max(0, int(n or 0))
        return self

    def limit(self, n: int):
        self._limit = max(0, int(n or 0))
        return self

    def sort(self, key: str, direction: int):  # noqa: ARG002
        # Sort by key, best-effort, reverse when direction < 0
        reverse = direction < 0
        self._docs.sort(key=lambda d: str(d.get(key, "")), reverse=reverse)
        return self

    def __iter__(self) -> Iterable[Dict[str, Any]]:
        docs = self._docs[self._offset :]
        if self._limit is not None:
            docs = docs[: self._limit]
        return iter(docs)


class _FakeCollection:
    def __init__(self):
        self._docs: Dict[str, Dict[str, Any]] = {}
        self._indexes: List[tuple] = []

    def create_index(self, *args, **kwargs):  # noqa: ARG002
        self._indexes.append((args, kwargs))

    def update_one(self, filt: Dict[str, Any], update: Dict[str, Any], upsert: bool = False):  # noqa: ARG002
        rule_id = (filt or {}).get("rule_id")
        if not rule_id:
            return _Result(modified_count=0)
        doc = self._docs.get(rule_id)
        if doc is None:
            if not upsert:
                return _Result(modified_count=0)
            doc = {"_id": f"fake:{rule_id}", "rule_id": rule_id}
            self._docs[rule_id] = doc
        set_doc = (update or {}).get("$set") or {}
        doc.update(set_doc)
        return _Result(modified_count=1)

    def find_one(self, filt: Dict[str, Any]):
        rule_id = (filt or {}).get("rule_id")
        if not rule_id:
            return None
        doc = self._docs.get(rule_id)
        if doc is None:
            return None
        return dict(doc)

    def find(self, query: Dict[str, Any]):
        query = query or {}

        def _match(doc: Dict[str, Any]) -> bool:
            for k, v in query.items():
                if k == "enabled":
                    if bool(doc.get("enabled")) is not bool(v):
                        return False
                elif k == "created_by":
                    if doc.get("created_by") != v:
                        return False
                elif k == "metadata.tags":
                    # "$all" support
                    if isinstance(v, dict) and "$all" in v:
                        need = list(v.get("$all") or [])
                        have = ((doc.get("metadata") or {}).get("tags") or [])
                        if not all(tag in have for tag in need):
                            return False
                    else:
                        return False
                else:
                    if doc.get(k) != v:
                        return False
            return True

        return _FakeCursor([dict(d) for d in self._docs.values() if _match(d)])

    def delete_one(self, filt: Dict[str, Any]):
        rule_id = (filt or {}).get("rule_id")
        if rule_id and rule_id in self._docs:
            del self._docs[rule_id]
            return _Result(deleted_count=1)
        return _Result(deleted_count=0)

    def count_documents(self, query: Dict[str, Any]):
        return sum(1 for _ in self.find(query))


class _FakeDB:
    def __init__(self):
        self._coll = _FakeCollection()

    def __getitem__(self, _name: str):
        return self._coll


def test_rules_storage_crud_and_filters():
    from services.rules_storage import RulesStorage

    storage = RulesStorage(_FakeDB())

    r1 = {
        "name": "A",
        "enabled": True,
        "created_by": "u1",
        "metadata": {"tags": ["t1", "t2"]},
        "conditions": {"type": "group", "operator": "AND", "children": []},
        "actions": [],
    }
    rule_id_1 = storage.save_rule(r1)
    assert rule_id_1

    r2 = {
        "rule_id": "r2",
        "name": "B",
        "enabled": False,
        "created_by": "u2",
        "metadata": {"tags": ["t2"]},
        "conditions": {"type": "group", "operator": "AND", "children": []},
        "actions": [],
    }
    storage.save_rule(r2)

    # get_rule strips _id
    fetched = storage.get_rule(rule_id_1)
    assert fetched is not None
    assert fetched.get("_id") is None
    assert fetched["name"] == "A"

    assert storage.count_rules() == 2
    assert storage.count_rules(enabled_only=True) == 1

    enabled = storage.get_enabled_rules()
    assert len(enabled) == 1
    assert enabled[0]["name"] == "A"

    only_u2 = storage.list_rules(created_by="u2")
    assert len(only_u2) == 1 and only_u2[0]["rule_id"] == "r2"

    tagged = storage.list_rules(tags=["t2"])
    assert len(tagged) == 2

    # toggle + delete
    assert storage.toggle_rule("r2", enabled=True) is True
    assert storage.count_rules(enabled_only=True) == 2

    assert storage.delete_rule("r2") is True
    assert storage.delete_rule("r2") is False
