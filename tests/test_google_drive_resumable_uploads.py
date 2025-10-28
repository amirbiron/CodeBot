import io
import os
from types import SimpleNamespace

import pytest


def _import_fresh():
    import importlib, sys
    mod = 'services.google_drive_service'
    sys.modules.pop(mod, None)
    return importlib.import_module(mod)


def test_upload_bytes_resumable_success(monkeypatch):
    gds = _import_fresh()

    # Fake Drive service with resumable next_chunk loop
    class _Req:
        def __init__(self):
            self.calls = 0
        def next_chunk(self):
            self.calls += 1
            if self.calls < 2:
                return None, None
            return None, {"id": "fid123"}

    class _Files:
        def create(self, body=None, media_body=None, fields=None):
            # ensure resumable enabled
            assert getattr(media_body, 'resumable', False) is True
            return _Req()

    class _Svc:
        def files(self):
            return _Files()

    # Stub get_drive_service + folder resolution
    monkeypatch.setattr(gds, "get_drive_service", lambda uid: _Svc(), raising=True)
    monkeypatch.setattr(gds, "ensure_subpath", lambda uid, sub: "folder123", raising=True)

    # Dummy MediaIoBaseUpload to capture args
    class _MediaIoBaseUpload:
        def __init__(self, fh, mimetype=None, resumable=False, chunksize=None):
            assert isinstance(fh, io.BytesIO)
            self.resumable = resumable
            self.chunksize = chunksize
    monkeypatch.setattr(gds, "MediaIoBaseUpload", _MediaIoBaseUpload, raising=True)

    fid = gds.upload_bytes(7, "file.zip", b"ZIPDATA", sub_path="zip")
    assert fid == "fid123"


def test_upload_file_resumable_success(tmp_path, monkeypatch):
    gds = _import_fresh()

    # Write a tiny zip file to disk (content is irrelevant for API call)
    p = tmp_path / "b1.zip"
    p.write_bytes(b"PK\x03\x04dummy")

    class _Req:
        def __init__(self):
            self.calls = 0
        def next_chunk(self):
            self.calls += 1
            if self.calls < 3:
                return None, None
            return None, {"id": "fid-file"}

    class _Files:
        def create(self, body=None, media_body=None, fields=None):
            assert getattr(media_body, 'resumable', False) is True
            return _Req()

    class _Svc:
        def files(self):
            return _Files()

    monkeypatch.setattr(gds, "get_drive_service", lambda uid: _Svc(), raising=True)
    monkeypatch.setattr(gds, "ensure_subpath", lambda uid, sub: "folder123", raising=True)

    class _MediaFileUpload:
        def __init__(self, file_path, mimetype=None, resumable=False, chunksize=None):
            assert os.path.exists(file_path)
            self.resumable = resumable
            self.chunksize = chunksize
    monkeypatch.setattr(gds, "MediaFileUpload", _MediaFileUpload, raising=True)

    fid = gds.upload_file(9, "BKP.zip", str(p), sub_path="zip")
    assert fid == "fid-file"


def test_upload_all_saved_zip_backups_prefers_file_then_fallback(tmp_path, monkeypatch):
    gds = _import_fresh()

    # Create two zip files
    def _make_zip(path):
        import zipfile
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr('a.txt', 'hello')
    p1 = tmp_path / "b1.zip"
    p2 = tmp_path / "b2.zip"
    _make_zip(p1)
    _make_zip(p2)

    class _B:
        def __init__(self, bid, file_path):
            self.backup_id = bid
            self.file_path = str(file_path)
            self.metadata = {"backup_id": bid}
    backups = [_B("b1", p1), _B("b2", p2)]

    # backup_manager backed by our list
    monkeypatch.setattr(gds, "backup_manager", SimpleNamespace(list_backups=lambda uid: backups), raising=True)

    # Avoid Drive listing (so existing_md5 is None path), and provide folder resolution
    monkeypatch.setattr(gds, "get_drive_service", lambda uid: None, raising=True)
    monkeypatch.setattr(gds, "compute_subpath", lambda cat, repo=None: "zip", raising=True)
    monkeypatch.setattr(gds, "compute_friendly_name", lambda uid, cat, entity, rating=None, content_sample=None: f"{entity}.zip", raising=True)

    # upload_file first returns None (to force fallback), then returns id
    calls = {"file": [], "bytes": []}
    def _upload_file(uid, filename, file_path, folder_id=None, sub_path=None):
        calls["file"].append(filename)
        return None if len(calls["file"]) == 1 else "fid2"
    def _upload_bytes(uid, filename, data, folder_id=None, sub_path=None):
        calls["bytes"].append(filename)
        return "fid1"
    monkeypatch.setattr(gds, "upload_file", _upload_file, raising=True)
    monkeypatch.setattr(gds, "upload_bytes", _upload_bytes, raising=True)

    # db stubs for rating and prefs
    class _DB:
        def get_backup_rating(self, user_id, b_id):
            return None
        def get_drive_prefs(self, user_id):
            return {}
        def save_drive_prefs(self, user_id, prefs):
            return True
    monkeypatch.setattr(gds, "db", _DB(), raising=True)

    uploaded, ids = gds.upload_all_saved_zip_backups(11)
    # First item fell back to bytes, second used file upload
    assert uploaded == 2 and len(ids) == 2
    assert calls["bytes"] and calls["file"]
