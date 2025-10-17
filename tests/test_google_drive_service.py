import io
import json
from types import SimpleNamespace
from importlib import import_module
from datetime import datetime, timezone

import pytest


def _import_module_fresh(module_name: str):
    """Import the exact module (not just the top-level package)."""
    import sys
    sys.modules.pop(module_name, None)
    # import_module returns the actual submodule object
    return import_module(module_name)


def _fixed_now_iso_str(dt: str):
    class _DT:
        @staticmethod
        def isoformat():
            return dt
    return _DT()


def _fake_response(status: int, payload: dict):
    class _Resp:
        def __init__(self):
            self.status_code = status
        def json(self):
            return payload
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http error")
    return _Resp()


def test_compute_subpath_variants(monkeypatch):
    gds = _import_module_fresh("services.google_drive_service")

    assert gds.compute_subpath("zip") == "zip"
    assert gds.compute_subpath("all") == "הכל"
    assert gds.compute_subpath("large") == "קבצים_גדולים"
    assert gds.compute_subpath("other") == "שאר_קבצים"
    assert gds.compute_subpath("by_repo", "owner/name") == "לפי_ריפו/owner/name"


def test_compute_friendly_name_increments_and_flags(monkeypatch):
    gds = _import_module_fresh("services.google_drive_service")

    # freeze date string used by compute_friendly_name
    monkeypatch.setattr(gds, "_date_str_ddmmyyyy", lambda: "26-08-2025", raising=True)
    # control version counter
    seq = {"zip:CodeBot": 6}
    def _next(user_id, key):
        seq[key] = seq.get(key, 0) + 1
        return seq[key]
    monkeypatch.setattr(gds, "_next_version", _next, raising=True)

    # enable short hash
    from config import config
    monkeypatch.setattr(config, "DRIVE_ADD_HASH", True, raising=False)

    name1 = gds.compute_friendly_name(7, "zip", "CodeBot", None, b"abc")
    name2 = gds.compute_friendly_name(7, "zip", "CodeBot", "🏆", b"abc")

    assert name1.startswith("BKP_zip_CodeBot_v7_") and name1.endswith(".zip")
    # hash is 8 hex chars — ensure present (between underscores)
    parts = name1.split("_")
    assert len(parts[-2]) == 8  # hash

    assert "🏆" in name2
    assert name2.startswith("BKP_zip_CodeBot_v8_")


def test_poll_device_token_pending_error_and_success(monkeypatch):
    gds = _import_module_fresh("services.google_drive_service")

    # pending path
    monkeypatch.setattr(gds, "requests", SimpleNamespace(post=lambda *a, **k: _fake_response(400, {"error": "authorization_pending"})))
    res = gds.poll_device_token("dc")
    assert res is None

    # user-facing error path
    monkeypatch.setattr(gds, "requests", SimpleNamespace(post=lambda *a, **k: _fake_response(400, {"error": "access_denied", "error_description": "Denied"})))
    res = gds.poll_device_token("dc")
    assert isinstance(res, dict) and res.get("error") == "access_denied"

    # success path
    fixed_dt = datetime(2025, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(gds, "_now_utc", lambda: fixed_dt, raising=True)
    monkeypatch.setattr(gds, "requests", SimpleNamespace(post=lambda *a, **k: _fake_response(200, {"access_token": "x", "expires_in": 3600, "scope": "s"})))
    res = gds.poll_device_token("dc")
    assert isinstance(res, dict) and res.get("access_token") == "x" and "expiry" in res


def test_get_drive_service_none_without_build_or_creds(monkeypatch):
    gds = _import_module_fresh("services.google_drive_service")
    # no build available
    monkeypatch.setattr(gds, "build", None, raising=True)
    monkeypatch.setattr(gds, "_ensure_valid_credentials", lambda uid: None, raising=True)
    assert gds.get_drive_service(1) is None


def test_perform_scheduled_backup_all_updates_prefs(monkeypatch):
    gds = _import_module_fresh("services.google_drive_service")

    # stub db
    calls = {"save_prefs": []}
    class _DB:
        def get_drive_prefs(self, user_id):
            return {"schedule_category": "all"}
        def save_drive_prefs(self, user_id, prefs):
            calls["save_prefs"].append(prefs)
            return True
    monkeypatch.setattr(gds, "db", _DB(), raising=True)

    # stub zip creation and upload
    monkeypatch.setattr(gds, "create_full_backup_zip_bytes", lambda uid, category="all": ("f.zip", b"ZIP"), raising=True)
    monkeypatch.setattr(gds, "compute_friendly_name", lambda uid, cat, label, content_sample=None: "BKP_zip_CodeBot_v1_26-08-2025.zip", raising=True)
    monkeypatch.setattr(gds, "compute_subpath", lambda cat, repo=None: "zip", raising=True)
    monkeypatch.setattr(gds, "upload_bytes", lambda uid, filename, data, folder_id=None, sub_path=None: "fid1", raising=True)

    ok = gds.perform_scheduled_backup(9)
    assert ok is True
    # last_backup_at and last_full_backup_at should be set in one of the calls
    merged = {}
    for p in calls["save_prefs"]:
        merged.update(p)
    assert "last_backup_at" in merged and "last_full_backup_at" in merged


def test_upload_all_saved_zip_backups_counts_and_marks(monkeypatch, tmp_path):
    gds = _import_module_fresh("services.google_drive_service")

    # create two dummy zip files
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

    # stub db prefs set/get
    class _DB:
        def __init__(self):
            self.prefs = {}
        def get_drive_prefs(self, user_id):
            return dict(self.prefs)
        def save_drive_prefs(self, user_id, prefs):
            self.prefs.update(prefs)
            return True
    db = _DB()
    monkeypatch.setattr(gds, "db", db, raising=True)

    # stub backup_manager
    monkeypatch.setattr(gds, "backup_manager", SimpleNamespace(list_backups=lambda uid: backups), raising=True)

    # avoid Google API paths
    monkeypatch.setattr(gds, "get_drive_service", lambda uid: None, raising=True)
    monkeypatch.setattr(gds, "compute_friendly_name", lambda uid, cat, entity, rating=None, content_sample=None: f"{entity}.zip", raising=True)
    monkeypatch.setattr(gds, "compute_subpath", lambda cat, repo=None: "zip", raising=True)
    monkeypatch.setattr(gds, "upload_bytes", lambda uid, filename, data, folder_id=None, sub_path=None: "fid", raising=True)

    count, ids = gds.upload_all_saved_zip_backups(7)
    assert count == 2 and len(ids) == 2
    # uploaded_backup_ids should be persisted in prefs
    assert set(db.prefs.get("uploaded_backup_ids", [])) == {"b1", "b2"}
