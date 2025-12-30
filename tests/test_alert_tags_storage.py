import importlib
import sys
import types
from datetime import datetime, timezone

import pytest


def _install_observability_stub(monkeypatch):
    def _emit(_event, severity="info", **_fields):
        return None

    monkeypatch.setitem(sys.modules, "observability", types.SimpleNamespace(emit_event=_emit))


def _install_fake_pymongo(monkeypatch, *, docs=None):
    """מזריק pymongo מזויף עם Collection in-memory עבור alert_tags_storage."""
    docs = list(docs or [])

    class _Result:
        def __init__(self, *, upserted_id=None, modified_count=0, deleted_count=0):
            self.upserted_id = upserted_id
            self.modified_count = modified_count
            self.deleted_count = deleted_count

    class _FakeCollection:
        def __init__(self):
            self._docs = docs

        def create_index(self, *_a, **_k):
            return None

        def find_one(self, query):
            for d in self._docs:
                ok = True
                for k, v in (query or {}).items():
                    if d.get(k) != v:
                        ok = False
                        break
                if ok:
                    return dict(d)
            return None

        def find(self, query, projection=None):
            query = query or {}

            def _match(d):
                for k, v in query.items():
                    if isinstance(v, dict) and "$in" in v:
                        if d.get(k) not in set(v["$in"]):
                            return False
                    else:
                        if d.get(k) != v:
                            return False
                return True

            matched = [dict(d) for d in self._docs if _match(d)]

            # naive projection support (include keys with 1, skip _id)
            if isinstance(projection, dict):
                keep = {k for k, vv in projection.items() if vv == 1}
                if keep:
                    out = []
                    for d in matched:
                        out.append({k: d.get(k) for k in keep if k in d})
                    matched = out
            return matched

        def update_one(self, query, update, upsert=False):
            # minimal support for alert_uid and alert_type_name upserts
            query = query or {}
            set_doc = (update or {}).get("$set", {}) or {}
            set_on_insert = (update or {}).get("$setOnInsert", {}) or {}
            add_to_set = (update or {}).get("$addToSet", {}) or {}
            pull = (update or {}).get("$pull", {}) or {}

            for d in self._docs:
                ok = True
                for k, v in query.items():
                    if d.get(k) != v:
                        ok = False
                        break
                if not ok:
                    continue

                modified = 0
                if set_doc:
                    for k, v in set_doc.items():
                        if d.get(k) != v:
                            d[k] = v
                            modified = 1
                if add_to_set:
                    for k, v in add_to_set.items():
                        arr = d.get(k) or []
                        if not isinstance(arr, list):
                            arr = []
                        if v not in arr:
                            arr.append(v)
                            d[k] = arr
                            modified = 1
                if pull:
                    for k, v in pull.items():
                        arr = d.get(k) or []
                        if isinstance(arr, list) and v in arr:
                            d[k] = [x for x in arr if x != v]
                            modified = 1
                return _Result(upserted_id=None, modified_count=modified)

            if upsert:
                new_doc = dict(set_on_insert)
                new_doc.update(query)
                new_doc.update(set_doc)
                if add_to_set:
                    for k, v in add_to_set.items():
                        new_doc[k] = [v]
                self._docs.append(new_doc)
                return _Result(upserted_id="new", modified_count=0)
            return _Result(upserted_id=None, modified_count=0)

        def delete_one(self, query):
            query = query or {}
            before = len(self._docs)
            self._docs[:] = [
                d for d in self._docs if not all(d.get(k) == v for k, v in query.items())
            ]
            deleted = 1 if len(self._docs) < before else 0
            return _Result(deleted_count=deleted)

        def aggregate(self, *_a, **_k):
            # not needed for this test suite
            return []

    class _FakeDB:
        def __init__(self):
            self._coll = _FakeCollection()

        def __getitem__(self, _name):
            return self._coll

    class _FakeAdmin:
        def command(self, *_a, **_k):
            return {"ok": 1}

    class _FakeClient:
        def __init__(self, *_a, **_k):
            self.admin = _FakeAdmin()
            self._db = _FakeDB()

        def __getitem__(self, _name):
            return self._db

    monkeypatch.setitem(sys.modules, "pymongo", types.SimpleNamespace(MongoClient=_FakeClient))


def _import_fresh_storage(monkeypatch):
    sys.modules.pop("monitoring.alert_tags_storage", None)
    return importlib.import_module("monitoring.alert_tags_storage")


def test_get_tags_map_for_alerts_app_side_merge_two_queries(monkeypatch):
    # enable DB path inside storage, but use fake pymongo
    monkeypatch.delenv("DISABLE_DB", raising=False)
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DATABASE_NAME", "code_keeper_bot")
    _install_observability_stub(monkeypatch)

    # Note: alert_type_name is stored normalized (lowercase + underscore)
    # so "CPU High" becomes "cpu_high" in DB
    docs = [
        # instance tags
        {"alert_uid": "uid-1", "tags": ["specific-tag"]},
        # global tags - stored with normalized name
        {"alert_type_name": "cpu_high", "tags": ["global-tag", "prod"]},
    ]
    _install_fake_pymongo(monkeypatch, docs=docs)
    s = _import_fresh_storage(monkeypatch)

    # alerts can arrive with any format - the code normalizes for lookup
    alerts = [
        {"alert_uid": "uid-1", "name": "CPU High"},  # "CPU High" -> normalized to "cpu_high"
        {"alert_uid": "uid-2", "name": "cpu_high"},  # Already normalized
        {"alert_uid": "uid-3", "name": "Other"},
    ]
    result = s.get_tags_map_for_alerts(alerts)

    assert result["uid-1"] == ["global-tag", "prod", "specific-tag"]
    assert result["uid-2"] == ["global-tag", "prod"]
    assert result["uid-3"] == []


def test_get_tags_map_for_alerts_field_fallbacks(monkeypatch):
    # enable DB path inside storage, but use fake pymongo
    monkeypatch.delenv("DISABLE_DB", raising=False)
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DATABASE_NAME", "code_keeper_bot")
    _install_observability_stub(monkeypatch)

    # Note: alert_type_name is stored normalized (lowercase + underscore)
    docs = [
        # instance tags
        {"alert_uid": "uid-1", "tags": ["specific-tag"]},
        # global tags - stored with normalized name
        {"alert_type_name": "cpu_high", "tags": ["global-tag", "prod"]},
    ]
    _install_fake_pymongo(monkeypatch, docs=docs)
    s = _import_fresh_storage(monkeypatch)

    # alerts may arrive with different field names (name/uid mismatches)
    # The name values will be normalized for lookup (CPU High -> cpu_high)
    alerts = [
        {"uid": "uid-1", "alert_type": "CPU High"},  # uid + alert_type -> normalized
        {"id": "uid-2", "rule_name": "cpu-high"},  # id + rule_name -> normalized
        {"_id": "uid-3", "alert_name": "Other"},  # _id + alert_name
    ]
    result = s.get_tags_map_for_alerts(alerts)

    assert result["uid-1"] == ["global-tag", "prod", "specific-tag"]
    assert result["uid-2"] == ["global-tag", "prod"]
    assert result["uid-3"] == []


def test_get_tags_map_prefers_alert_type_over_name(monkeypatch):
    """
    When an alert has both 'name' (descriptive title) and 'alert_type' (categorized type),
    the lookup should prefer alert_type to match global tags.
    
    Example: name="Sentry: TEST-1", alert_type="sentry_issue"
    Global tags saved under "sentry_issue" should apply, not "sentry_test_1".
    """
    monkeypatch.delenv("DISABLE_DB", raising=False)
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DATABASE_NAME", "code_keeper_bot")
    _install_observability_stub(monkeypatch)

    # Global tags stored under normalized alert_type
    docs = [
        {"alert_type_name": "sentry_issue", "tags": ["sentry", "error-tracking"]},
    ]
    _install_fake_pymongo(monkeypatch, docs=docs)
    s = _import_fresh_storage(monkeypatch)

    # Alert has both name (descriptive) and alert_type (categorized)
    # The code should prefer alert_type for global tag lookup
    alerts = [
        {
            "alert_uid": "uid-1",
            "name": "Sentry: TEST-1",  # Descriptive title (would normalize to "sentry_test_1")
            "alert_type": "sentry_issue",  # Categorized type (should be used)
        },
        {
            "alert_uid": "uid-2",
            "name": "Some Other Alert",  # Only name, no alert_type
        },
    ]
    result = s.get_tags_map_for_alerts(alerts)

    # uid-1 should get tags because alert_type matches
    assert result["uid-1"] == ["sentry", "error-tracking"]
    # uid-2 should NOT get tags because its name doesn't match any global tags
    assert result["uid-2"] == []


def test_set_and_get_global_tags(monkeypatch):
    monkeypatch.delenv("DISABLE_DB", raising=False)
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    _install_observability_stub(monkeypatch)
    _install_fake_pymongo(monkeypatch, docs=[])
    s = _import_fresh_storage(monkeypatch)

    # Note: alert_type_name is normalized on save (CPU High -> cpu_high)
    res = s.set_global_tags_for_name("CPU High", ["Infrastructure", "critical", "critical"])
    assert res["alert_type_name"] == "cpu_high"  # normalized
    assert res["tags"] == ["infrastructure", "critical"]
    # Lookup also uses normalized name, so any format works
    assert set(s.get_global_tags_for_name("CPU High")) == {"infrastructure", "critical"}
    assert set(s.get_global_tags_for_name("cpu-high")) == {"infrastructure", "critical"}
    assert set(s.get_global_tags_for_name("cpu_high")) == {"infrastructure", "critical"}


def test_set_and_get_instance_tags(monkeypatch):
    monkeypatch.delenv("DISABLE_DB", raising=False)
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    _install_observability_stub(monkeypatch)
    _install_fake_pymongo(monkeypatch, docs=[])
    s = _import_fresh_storage(monkeypatch)

    ts = datetime.now(timezone.utc)
    res = s.set_tags_for_alert("uid-x", ts, ["Bug", "production", "bug", "  "])
    assert res["alert_uid"] == "uid-x"
    assert res["tags"] == ["bug", "production"]
    assert s.get_tags_for_alert("uid-x") == ["bug", "production"]


def test_set_and_get_signature_tags(monkeypatch):
    """Test signature-based tags (for tagging specific errors that recur)."""
    monkeypatch.delenv("DISABLE_DB", raising=False)
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    _install_observability_stub(monkeypatch)
    _install_fake_pymongo(monkeypatch, docs=[])
    s = _import_fresh_storage(monkeypatch)

    res = s.set_tags_for_signature("PYTHON-1F", ["known", "low-priority"])
    assert res["error_signature"] == "PYTHON-1F"
    assert res["tags"] == ["known", "low-priority"]
    assert s.get_tags_for_signature("PYTHON-1F") == ["known", "low-priority"]
    assert s.get_tags_for_signature("OTHER-SIG") == []


def test_get_tags_map_includes_signature_tags(monkeypatch):
    """Test that get_tags_map_for_alerts includes signature-based tags from metadata."""
    monkeypatch.delenv("DISABLE_DB", raising=False)
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DATABASE_NAME", "code_keeper_bot")
    _install_observability_stub(monkeypatch)

    docs = [
        # Instance tags
        {"alert_uid": "uid-1", "tags": ["specific-tag"]},
        # Global tags (by alert type)
        {"alert_type_name": "sentry_issue", "tags": ["sentry-global"]},
        # Signature tags (by error signature)
        {"error_signature": "PYTHON-1F", "tags": ["known-bug", "low-priority"]},
    ]
    _install_fake_pymongo(monkeypatch, docs=docs)
    s = _import_fresh_storage(monkeypatch)

    # Alert with both global (alert_type) and signature (sentry_issue_id) matching
    alerts = [
        {
            "alert_uid": "uid-1",
            "alert_type": "sentry_issue",
            "metadata": {"sentry_issue_id": "PYTHON-1F"},
        },
        {
            "alert_uid": "uid-2",
            "alert_type": "sentry_issue",
            "metadata": {"sentry_issue_id": "OTHER-2G"},  # Different issue
        },
        {
            "alert_uid": "uid-3",
            "alert_type": "slow_response",
            "metadata": {},  # No signature
        },
    ]
    result = s.get_tags_map_for_alerts(alerts)

    # uid-1: should get global + signature + instance tags
    assert set(result["uid-1"]) == {"sentry-global", "known-bug", "low-priority", "specific-tag"}
    # uid-2: should only get global tags (no signature match)
    assert result["uid-2"] == ["sentry-global"]
    # uid-3: no tags (different alert type, no signature)
    assert result["uid-3"] == []
