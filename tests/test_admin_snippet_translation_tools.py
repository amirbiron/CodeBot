import types

from webapp import app as app_mod


class _StubExportCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, projection):
        status = query.get("status")
        if isinstance(status, dict):
            allowed = status.get("$in", [])
            return [doc for doc in self.docs if doc.get("status") in allowed]
        return [doc for doc in self.docs if doc.get("status") == status]


class _StubImportCollection:
    def __init__(self, docs):
        self.docs = {doc["_id"]: dict(doc) for doc in docs}
        self.calls = 0

    def update_one(self, query, update):
        self.calls += 1
        target = self.docs.get(query.get("_id"))
        if target is None:
            return types.SimpleNamespace(modified_count=0, matched_count=0)
        target.update(update.get("$set", {}))
        return types.SimpleNamespace(modified_count=1, matched_count=1)


class _StubRepo:
    def _normalize_snippet_identifier(self, value):
        return value


def test_build_snippet_export_payload_supports_pending_toggle():
    docs = [
        {"_id": "1", "title": "א", "language": "python", "status": "approved"},
        {"_id": "2", "title": "ב", "language": "python", "status": "pending"},
    ]
    coll = _StubExportCollection(docs)

    approved_only = app_mod._build_snippet_export_payload(coll, include_pending=False)
    assert len(approved_only) == 1
    assert approved_only[0]["id"] == "1"

    with_pending = app_mod._build_snippet_export_payload(coll, include_pending=True)
    assert len(with_pending) == 2
    assert {item["id"] for item in with_pending} == {"1", "2"}


def test_apply_snippet_json_import_handles_dry_run_and_errors():
    coll = _StubImportCollection([{"_id": "1", "title": "ישן", "language": "python"}])
    repo = _StubRepo()
    payload = [
        {"id": "1", "title": "חדש"},
        {"title": "ללא מזהה"},
    ]

    dry_summary = app_mod._apply_snippet_json_import(coll, repo, payload, dry_run=True)
    assert dry_summary["updated"] == 1
    assert dry_summary["skipped"] == 1
    assert dry_summary["errors"]
    assert coll.docs["1"]["title"] == "ישן"

    live_summary = app_mod._apply_snippet_json_import(coll, repo, [{"id": "1", "title": "מעודכן"}], dry_run=False)
    assert live_summary["updated"] == 1
    assert coll.docs["1"]["title"] == "מעודכן"
