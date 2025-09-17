import io
import json
from pathlib import Path

import pytest

from file_manager import BackupManager


class _FakeFSDoc:
    def __init__(self, filename: str, data: bytes, metadata: dict):
        import hashlib
        self.filename = filename
        self._data = data
        self.metadata = metadata
        self.length = len(data)
        # pseudo id
        self._id = hashlib.md5(filename.encode()).hexdigest()


class _FakeGridFS:
    def __init__(self, docs):
        self._docs = list(docs)

    def find(self, query: dict = None):
        # very naive filter for tests
        if not query:
            return list(self._docs)
        res = []
        for d in self._docs:
            ok = True
            for k, v in query.items():
                if k == "filename":
                    ok = ok and (d.filename == v)
                elif k == "metadata.backup_id":
                    ok = ok and (d.metadata.get("backup_id") == v)
                elif k == "metadata.user_id":
                    ok = ok and (d.metadata.get("user_id") == v)
            if ok:
                res.append(d)
        return res

    def get(self, _id):
        class _Out:
            def __init__(self, data: bytes):
                self._data = data

            def read(self):
                return self._data

        for d in self._docs:
            if d._id == _id:
                return _Out(d._data)
        raise FileNotFoundError

    def delete(self, _id):
        self._docs = [d for d in self._docs if d._id != _id]


def _zip_bytes_with_md(md: dict):
    import zipfile
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("f.txt", "content")
        zf.writestr("metadata.json", json.dumps(md))
    return mem.getvalue()


def test_gridfs_list_infers_owner_from_filename_and_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKUPS_STORAGE", "mongo")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    # doc1: no metadata.user_id but filename encodes owner
    d1 = _FakeFSDoc(
        filename="backup_555_a.zip",
        data=_zip_bytes_with_md({"backup_id": "backup_555_a"}),
        metadata={"backup_id": "backup_555_a"},
    )
    # doc2: metadata.user_id as string
    d2 = _FakeFSDoc(
        filename="backup_xx.zip",
        data=_zip_bytes_with_md({"backup_id": "any"}),
        metadata={"backup_id": "any", "user_id": "555"},
    )
    fake_fs = _FakeGridFS([d1, d2])

    mgr = BackupManager()

    def _fake_get_gridfs():
        return fake_fs

    monkeypatch.setattr(mgr, "_get_gridfs", _fake_get_gridfs)

    lst = mgr.list_backups(555)
    ids = {b.backup_id for b in lst}
    assert "backup_555_a" in ids
    assert "any" in ids


def test_gridfs_delete_without_user_id_allows_owner_by_pattern(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKUPS_STORAGE", "mongo")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    d1 = _FakeFSDoc(
        filename="backup_777_b.zip",
        data=_zip_bytes_with_md({"backup_id": "backup_777_b"}),
        metadata={"backup_id": "backup_777_b"},
    )
    fake_fs = _FakeGridFS([d1])
    mgr = BackupManager()

    def _fake_get_gridfs():
        return fake_fs

    monkeypatch.setattr(mgr, "_get_gridfs", _fake_get_gridfs)

    res = mgr.delete_backups(777, ["backup_777_b"])
    assert res["deleted"] >= 1
