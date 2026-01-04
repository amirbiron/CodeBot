"""
בדיקות אינטגרציה לחיפוש סמנטי.

המטרה: לוודא Flow מלא:
1) שמירת קובץ -> 2) יצירת embedding ברקע -> 3) חיפוש (CONTENT) משתמש בוקטורי ומחזיר תוצאה.
"""

from __future__ import annotations

import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from database.models import CodeSnippet
from database.repository import Repository
from flask import Flask
from webapp.search_api import search_bp


class _CodeSnippetsCollectionStub:
    def __init__(self):
        self.docs: list[dict] = []
        self._id_seq = 0
        self.aggregate_calls = 0

    def _next_id(self) -> str:
        self._id_seq += 1
        return str(self._id_seq)

    def insert_one(self, doc: dict):
        d = dict(doc)
        d.setdefault("_id", self._next_id())
        self.docs.append(d)
        return types.SimpleNamespace(inserted_id=d["_id"])

    def update_one(self, query: dict, update: dict):
        matched = 0
        modified = 0
        for d in self.docs:
            ok = True
            for k, v in query.items():
                if isinstance(v, dict) and "$ne" in v:
                    ok = ok and (d.get(k) != v.get("$ne"))
                else:
                    ok = ok and (d.get(k) == v)
            if ok:
                matched += 1
                fields = (update or {}).get("$set", {})
                for k2, v2 in fields.items():
                    d[k2] = v2
                modified += 1
                break
        return types.SimpleNamespace(matched_count=matched, modified_count=modified)

    def find_one(self, query: dict, projection: dict | None = None, sort=None):
        # naive "latest" by version desc
        candidates = []
        for d in self.docs:
            ok = True
            for k, v in query.items():
                if isinstance(v, dict) and "$ne" in v:
                    ok = ok and (d.get(k) != v.get("$ne"))
                else:
                    ok = ok and (d.get(k) == v)
            if ok:
                candidates.append(d)
        if not candidates:
            return None
        candidates.sort(key=lambda x: int(x.get("version") or 0), reverse=True)
        doc = dict(candidates[0])
        if projection and isinstance(projection, dict):
            # support include projection (best-effort)
            include_keys = [k for k, v in projection.items() if v == 1]
            if include_keys:
                return {k: doc.get(k) for k in include_keys if k in doc}
        return doc

    def aggregate(self, pipeline, allowDiskUse=False):
        # Mark call for assertions
        self.aggregate_calls += 1
        # Return "vectorSearch" style docs: latest active doc that has embedding
        out = []
        for d in self.docs:
            if d.get("is_active", True) is False:
                continue
            if d.get("embedding") is None:
                continue
            out.append(
                {
                    "_id": d.get("_id"),
                    "file_name": d.get("file_name"),
                    "code": d.get("code", ""),
                    "programming_language": d.get("programming_language", ""),
                    "tags": d.get("tags") or [],
                    "description": d.get("description") or "",
                    "created_at": d.get("created_at") or datetime.now(timezone.utc),
                    "updated_at": d.get("updated_at") or datetime.now(timezone.utc),
                    "version": d.get("version") or 1,
                    "snippet_preview": (d.get("code") or "")[:2000],
                    "score": 0.99,
                }
            )
        return out


class _ManagerStub:
    def __init__(self):
        self.collection = _CodeSnippetsCollectionStub()

    @property
    def manager(self):
        # תאימות ל-`db.manager.collection`
        return self


def _login(client, user_id=42):
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["user_data"] = {"id": int(user_id), "first_name": "Tester"}


class _SyncThread:
    def __init__(self, target=None, daemon=None, **_kwargs):
        self._target = target
        self.daemon = daemon

    def start(self):
        if self._target:
            self._target()


def test_semantic_search_end_to_end(monkeypatch):
    # Flags + embedding config (tests may run with a config stub).
    # נעדיף לפאץ' את האובייקטים שכבר מיובאים בתוך המודולים הרלוונטיים כדי למנוע תלות בסדר טעינה.
    import search_engine as se
    import database.repository as repo_mod
    import webapp.search_api as api_mod

    for cfg_obj in (se.config, repo_mod.config, api_mod.config):
        monkeypatch.setattr(cfg_obj, "SEMANTIC_SEARCH_ENABLED", True, raising=False)
        monkeypatch.setattr(cfg_obj, "SEMANTIC_SEARCH_INDEX_ON_SAVE", True, raising=False)
        monkeypatch.setattr(cfg_obj, "EMBEDDING_MODEL", "text-embedding-3-small", raising=False)
        monkeypatch.setattr(cfg_obj, "EMBEDDING_DIMENSIONS", 1536, raising=False)
        monkeypatch.setattr(cfg_obj, "EMBEDDING_MAX_CHARS", 2000, raising=False)

    # Stub DB and wire it into both search_engine and search_api usage of `database.db`
    mgr = _ManagerStub()

    # Patch database.db and search_engine.db to point at our stub
    import database

    monkeypatch.setattr(database, "db", mgr, raising=False)
    monkeypatch.setattr(se, "db", mgr, raising=False)

    # Prevent index rebuild (so we don't need db.get_user_files for this test)
    idx = se.SearchIndex()
    idx.last_update = datetime.now(timezone.utc)
    se.search_engine.indexes[42] = idx

    # Save a file (this should schedule background embedding update)
    repo = Repository(mgr)
    snippet = CodeSnippet(
        user_id=42,
        file_name="email_validator.py",
        code="def is_valid_email_address(x):\n    return '@' in x\n",
        programming_language="python",
        description="validate email address",
        tags=["email", "validation"],
    )

    embedding_vec = [0.1] * 1536

    with patch("threading.Thread", _SyncThread):
        with patch("services.embedding_service.generate_embedding_sync", return_value=embedding_vec):
            assert repo.save_code_snippet(snippet) is True

    # Verify embedding was stored
    saved = mgr.collection.find_one({"user_id": 42, "file_name": "email_validator.py", "version": 1})
    assert saved is not None
    assert saved.get("embedding") == embedding_vec
    assert saved.get("needs_embedding_update") is False

    # Query embedding for semantic search call (avoid external IO)
    monkeypatch.setattr(se.config, "SEMANTIC_SEARCH_ENABLED", True, raising=False)
    monkeypatch.setattr(se.config, "EMBEDDING_DIMENSIONS", 1536, raising=False)

    with patch("services.embedding_service.generate_embedding", new=AsyncMock(return_value=embedding_vec)):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(search_bp)
        app.testing = True
        client = app.test_client()
        _login(client, 42)

        # Use the new API endpoint; CONTENT should route to semantic when enabled
        resp = client.get("/api/search?q=validate%20email&type=content&limit=20")
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["ok"] is True
        assert data["total"] >= 1
        assert any(it.get("file_name") == "email_validator.py" for it in data.get("items") or [])
        # Ensure vector search pipeline executed
        assert mgr.collection.aggregate_calls >= 1

