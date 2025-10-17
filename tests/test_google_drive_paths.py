import re
from types import SimpleNamespace

import pytest


def _import_gds():
    import importlib
    import sys
    sys.modules.pop("services.google_drive_service", None)
    return importlib.import_module("services.google_drive_service")


class _FilesStub:
    def __init__(self):
        # map key: (name, parent_id) -> id
        self.folders = {}
        self.created = []
        self._seq = 0

    def _parse_q(self, q: str):
        name = None
        parent = None
        if q:
            m = re.search(r"name\s*=\s*'([^']+)'", q)
            if m:
                name = m.group(1)
            m2 = re.search(r"and\s*'([^']+)'\s*in\s*parents", q)
            if m2:
                parent = m2.group(1)
        return name, parent

    class _List:
        def __init__(self, outer, q):
            self._outer = outer
            self._q = q
        def execute(self):
            name, parent = self._outer._parse_q(self._q)
            fid = self._outer.folders.get((name, parent))
            files = ([{"id": fid}] if fid else [])
            return {"files": files}

    class _Create:
        def __init__(self, outer, body):
            self._outer = outer
            self._body = body
        def execute(self):
            name = (self._body or {}).get("name")
            parents = (self._body or {}).get("parents") or []
            parent = parents[0] if parents else None
            self._outer._seq += 1
            fid = f"fid_{self._outer._seq}"
            self._outer.folders[(name, parent)] = fid
            self._outer.created.append((name, parent, fid))
            return {"id": fid}

    class _Get:
        def __init__(self, outer, file_id, fields):
            self._outer = outer
            self._file_id = file_id
            self._fields = fields
        def execute(self):
            # Return trashed for any id ending with 'trashed'
            if str(self._file_id).endswith("trashed"):
                return {"id": self._file_id, "trashed": True, "mimeType": "application/vnd.google-apps.folder"}
            return {"id": self._file_id, "trashed": False, "mimeType": "application/vnd.google-apps.folder"}

    def list(self, q=None, fields=None):
        return _FilesStub._List(self, q)

    def create(self, body=None, fields=None):
        return _FilesStub._Create(self, body)

    def get(self, fileId=None, fields=None):
        return _FilesStub._Get(self, fileId, fields)


class _ServiceStub:
    def __init__(self, files_stub):
        self._files = files_stub
    def files(self):
        return self._files


def test_ensure_folder_reuse_and_create(monkeypatch):
    gds = _import_gds()

    files = _FilesStub()
    # Pre-populate an existing root folder 'A' (no parent)
    files.folders[("A", None)] = "root_A"

    service = _ServiceStub(files)
    monkeypatch.setattr(gds, "get_drive_service", lambda uid: service, raising=True)

    # Reuse existing
    fid_a = gds.ensure_folder(7, "A", None)
    assert fid_a == "root_A"

    # Create under parent
    fid_b = gds.ensure_folder(7, "B", parent_id=fid_a)
    assert fid_b and fid_b.startswith("fid_")
    # Ensure it was created with correct parent
    assert ("B", fid_a) in files.folders


def test_ensure_path_updates_prefs_with_last_folder(monkeypatch):
    gds = _import_gds()

    # Track saved prefs
    calls = {"prefs": []}
    class _DB:
        def save_drive_prefs(self, user_id, prefs):
            calls["prefs"].append((user_id, dict(prefs)))
            return True
    monkeypatch.setattr(gds, "db", _DB(), raising=True)

    # Stub ensure_folder to return deterministic ids in sequence A->B
    seq = iter(["idA", "idB"])
    monkeypatch.setattr(gds, "ensure_folder", lambda uid, name, parent=None: next(seq), raising=True)

    out = gds.ensure_path(5, "A/B")
    assert out == "idB"
    # Last call should persist target_folder_id=idB
    merged = {}
    for _, p in calls["prefs"]:
        merged.update(p)
    assert merged.get("target_folder_id") == "idB"


def test_get_or_create_default_folder_recreates_when_trashed(monkeypatch):
    gds = _import_gds()

    # Prefs contain stale folder id 'old_trashed'
    class _DB:
        def __init__(self):
            self.saved = []
        def get_drive_prefs(self, user_id):
            return {"target_folder_id": "old_trashed"}
        def save_drive_prefs(self, user_id, prefs):
            self.saved.append(prefs)
            return True
    db = _DB()
    monkeypatch.setattr(gds, "db", db, raising=True)

    files = _FilesStub()
    service = _ServiceStub(files)
    monkeypatch.setattr(gds, "get_drive_service", lambda uid: service, raising=True)

    # When old is trashed, ensure_folder should be called to create default root
    # Stub ensure_folder to return 'new_root'
    monkeypatch.setattr(gds, "ensure_folder", lambda uid, name, parent=None: "new_root", raising=True)

    fid = gds.get_or_create_default_folder(3)
    assert fid == "new_root"
    # And prefs were updated with the new target folder id
    merged = {}
    for p in db.saved:
        merged.update(p)
    assert merged.get("target_folder_id") == "new_root"


def test_ensure_subpath_does_not_override_target_prefs(monkeypatch):
    gds = _import_gds()

    # Existing prefs already have a valid root id; ensure_subpath should NOT write a new target id
    class _DB:
        def __init__(self):
            self.saved = []
        def get_drive_prefs(self, user_id):
            return {"target_folder_id": "root"}
        def save_drive_prefs(self, user_id, prefs):
            self.saved.append(prefs)
            return True
    db = _DB()
    monkeypatch.setattr(gds, "db", db, raising=True)

    # Return root without writing prefs
    monkeypatch.setattr(gds, "_get_root_folder", lambda uid: "root", raising=True)

    # ensure_folder returns nested ids for subfolders
    seq = iter(["subA", "subB"])  # A -> subA, then B under subA -> subB
    monkeypatch.setattr(gds, "ensure_folder", lambda uid, name, parent=None: next(seq), raising=True)

    out = gds.ensure_subpath(11, "A/B")
    assert out == "subB"
    # No new prefs saves should occur (target_folder_id must not be overridden to subB)
    assert not db.saved
