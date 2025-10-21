import types
import io
import json
import pytest

import services.google_drive_service as gds


class _DB:
    def __init__(self, docs, large_docs=None):
        self._docs = docs
        self._large = large_docs or []
    def get_user_files(self, user_id, limit=1000, projection=None, skip=0):
        # סימולציה בסיסית של projection
        rows = self._docs[skip: skip + limit]
        if projection:
            out = []
            for r in rows:
                out.append({k: r.get(k) for k, v in projection.items() if v})
            return out
        return rows
    def get_user_large_files(self, user_id, page=1, per_page=10000):
        return (self._large, len(self._large))


def _extract_zip_entries(zip_bytes: bytes):
    import zipfile
    buf = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(buf, 'r') as zf:
        names = zf.namelist()
        files = {name: zf.read(name).decode('utf-8') for name in names if not name.endswith('/')}
    return files


def test_create_repo_grouped_zip_bytes_includes_tags_and_code(monkeypatch):
    docs = [
        {"file_name": "a.py", "tags": ["repo:owner/repo"], "code": "print('A')", "_id": "1"},
        {"file_name": "b.py", "tags": ["misc"], "code": "print('B')", "_id": "2"},
    ]
    monkeypatch.setattr(gds, "db", types.SimpleNamespace(), raising=False)
    monkeypatch.setattr(gds, "_now_utc", lambda: __import__('datetime').datetime.now(__import__('datetime').timezone.utc), raising=False)
    monkeypatch.setattr(gds, "compute_friendly_name", lambda *a, **k: "name.zip", raising=False)
    fake_db = _DB(docs)
    monkeypatch.setattr(gds, "db", types.SimpleNamespace(), raising=False)
    # פנימי משתמש ב-import מקומי: נחטוף בפנים
    monkeypatch.setitem(__import__('sys').modules, 'database', types.SimpleNamespace(db=fake_db))

    out = gds.create_repo_grouped_zip_bytes(1)
    assert out, "expected at least one repo zip"
    repo, suggested, data = out[0]
    files = _extract_zip_entries(data)
    assert "a.py" in files and files["a.py"].strip() == "print('A')"


def test_create_full_backup_zip_bytes_all_and_other(monkeypatch):
    docs = [
        {"file_name": "a.py", "tags": ["repo:owner/repo"], "code": "A", "_id": "1"},
        {"file_name": "b.py", "tags": ["misc"], "code": "B", "_id": "2"},
    ]
    fake_db = _DB(docs)
    monkeypatch.setitem(__import__('sys').modules, 'database', types.SimpleNamespace(db=fake_db))
    monkeypatch.setattr(gds, "_now_utc", lambda: __import__('datetime').datetime.now(__import__('datetime').timezone.utc), raising=False)
    monkeypatch.setattr(gds, "compute_friendly_name", lambda *a, **k: "fname.zip", raising=False)

    fname_all, data_all = gds.create_full_backup_zip_bytes(1, category="all")
    files_all = _extract_zip_entries(data_all)
    assert files_all.get("a.py") == "A"
    assert files_all.get("b.py") == "B"

    fname_other, data_other = gds.create_full_backup_zip_bytes(1, category="other")
    files_other = _extract_zip_entries(data_other)
    assert "a.py" not in files_other and files_other.get("b.py") == "B"
