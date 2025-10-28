import io
import json
import types
import zipfile as _real_zipfile

import pytest


def _capture_zipfile(monkeypatch, module_under_test):
    captured = {"calls": []}

    def ZipFileWrapper(file, mode="r", compression=_real_zipfile.ZIP_STORED, allowZip64=True, compresslevel=None, **kwargs):
        captured["calls"].append({
            "mode": mode,
            "compression": compression,
            "compresslevel": compresslevel,
        })
        return _real_zipfile.ZipFile(
            file,
            mode=mode,
            compression=compression,
            allowZip64=allowZip64,
            compresslevel=compresslevel,
            **kwargs,
        )

    monkeypatch.setattr(module_under_test.zipfile, "ZipFile", ZipFileWrapper, raising=True)
    return captured


@pytest.mark.asyncio
async def test_backup_menu_handler_full_backup_uses_level_9(monkeypatch):
    import backup_menu_handler as bmh

    # Fake DB: two files
    class _DB:
        def get_user_files(self, user_id, limit=1000):
            return [
                {"_id": 1, "file_name": "a.py", "code": "print(1)"},
                {"_id": 2, "file_name": "b.js", "code": "var x;"},
            ]
    monkeypatch.setattr(bmh, "db", _DB(), raising=False)

    # Capture save and reply
    class _Mgr:
        def save_backup_bytes(self, data, metadata):
            # Ensure it's a zip and contains metadata
            bio = io.BytesIO(data)
            with _real_zipfile.ZipFile(bio, 'r') as zf:
                assert 'metadata.json' in zf.namelist()
                json.loads(zf.read('metadata.json'))
            return True
    monkeypatch.setattr(bmh, "backup_manager", _Mgr(), raising=False)

    # Capture compresslevel via monkeypatch
    captured = _capture_zipfile(monkeypatch, bmh)

    # Minimal telegram stubs
    class _Msg:
        async def reply_document(self, *a, **k):
            return None
    class _Q:
        def __init__(self):
            self.from_user = types.SimpleNamespace(id=21)
            self.message = _Msg()
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
    upd = types.SimpleNamespace(callback_query=_Q(), effective_user=types.SimpleNamespace(id=21))
    ctx = types.SimpleNamespace(user_data={})

    handler = bmh.BackupMenuHandler()
    await handler._create_full_backup(upd, ctx)

    # Ensure a write call was made with compresslevel=9
    assert any(c["mode"] == 'w' and c["compresslevel"] == 9 for c in captured["calls"]) \
        or any(c["mode"] == 'a' and c["compresslevel"] == 9 for c in captured["calls"])  # metadata write


def test_gds_create_full_backup_zip_bytes_uses_level_9(monkeypatch):
    import services.google_drive_service as gds

    class _DB:
        def get_user_files(self, user_id, limit=1000, projection=None):
            return [
                {"_id": 1, "file_name": "a.txt", "tags": [], "code": "a"},
                {"_id": 2, "file_name": "b.txt", "tags": [], "code": "b"},
            ]
    monkeypatch.setattr(gds, "db", _DB(), raising=False)

    captured = _capture_zipfile(monkeypatch, gds)

    name, data = gds.create_full_backup_zip_bytes(7, category="all")
    assert name.endswith('.zip') and isinstance(data, (bytes, bytearray))

    # ensure a 'w' call captured compresslevel=9
    assert any(c["mode"] == 'w' and c["compresslevel"] == 9 for c in captured["calls"]) \
        or any(c["mode"] == 'a' and c["compresslevel"] == 9 for c in captured["calls"])  # metadata


def test_gds_create_repo_grouped_zip_bytes_uses_level_9(monkeypatch):
    import services.google_drive_service as gds

    class _DB:
        def get_user_files(self, user_id, limit=1000, projection=None):
            return [
                {"_id": 1, "file_name": "a.txt", "tags": ["repo:o/r"], "code": "a"},
                {"_id": 2, "file_name": "b.txt", "tags": ["repo:o/r"], "code": "b"},
            ]
    monkeypatch.setattr(gds, "db", _DB(), raising=False)

    captured = _capture_zipfile(monkeypatch, gds)

    results = gds.create_repo_grouped_zip_bytes(7)
    assert results and results[0][2].startswith(b"PK")

    assert any(c["mode"] == 'w' and c["compresslevel"] == 9 for c in captured["calls"]) \
        or any(c["mode"] == 'a' and c["compresslevel"] == 9 for c in captured["calls"])  # metadata


@pytest.mark.asyncio
async def test_github_menu_handler_folder_zip_uses_level_9(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    handler.get_user_session = lambda uid: {"selected_repo": "o/r"}
    handler.get_user_token = lambda uid: "t"

    class _Item:
        def __init__(self, t, name, size=0, data=b""):
            self.type = t
            self.name = name
            self.path = name
            self.size = size
            self.decoded_content = data

    class _Repo:
        name = "r"
        full_name = "o/r"
        def get_contents(self, path):
            return [_Item('file', 'a.txt', len(b'a'), b'a')]

    class _Gh:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, _):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)

    captured = _capture_zipfile(monkeypatch, gh)

    class _Msg:
        async def reply_document(self, document=None, filename=None, caption=None):
            return None
        async def reply_text(self, *a, **k):
            return None
    class _Q:
        def __init__(self):
            self.data = "download_zip:folder"
            self.message = _Msg()
            self.from_user = types.SimpleNamespace(id=5)
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None

    upd = types.SimpleNamespace(callback_query=_Q(), effective_user=types.SimpleNamespace(id=5))
    ctx = types.SimpleNamespace(user_data={})

    # force folder path flow
    monkeypatch.setattr(handler, "_get_path_from_cb", lambda context, data, prefix: "folder", raising=True)
    await handler.handle_menu_callback(upd, ctx)

    # 'w' for building, 'a' for metadata
    assert any(c["mode"] == 'w' and c["compresslevel"] == 9 for c in captured["calls"]) \
        and any(c["mode"] == 'a' and c["compresslevel"] == 9 for c in captured["calls"]) 
