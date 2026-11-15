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

    results = gds.create_repo_grouped_zip_bytes(7, owner="bot")
    assert results and results[0][2].startswith(b"PK")

    assert any(c["mode"] == 'w' and c["compresslevel"] == 9 for c in captured["calls"]) \
        or any(c["mode"] == 'a' and c["compresslevel"] == 9 for c in captured["calls"])  # metadata


def test_github_folder_packer_uses_level_9(monkeypatch, tmp_path):
    """אריזת תיקייה מגיטהאב: כתיבה אחת עם ``compresslevel=9``, וכל רשומה דחוסה.

    האריזה רצה בתהליך נפרד (``services/github_zip_packer.py``, ראו ההסבר שם), ולכן
    הבדיקה פונה לפונקציה שהתהליך מריץ, באותו תהליך: monkeypatch לא מגיע לתהליך-בן.
    המעטפת שומרת את המחלקה המקורית לפני ההחלפה, כי ``_capture_zipfile`` שלמעלה
    נשען על הפרוקסי של ``github_menu_handler`` ובמודול הזה אין כזה.
    """
    from services import github_zip_packer as packer
    from _github_zip_harness import zipball_bytes

    archive = tmp_path / "archive.zip"
    archive.write_bytes(zipball_bytes({"folder/a.txt": b"a" * 100}))
    dest = tmp_path / "packed.zip"

    calls = []
    original = _real_zipfile.ZipFile

    def _wrapper(file, mode="r", compression=_real_zipfile.ZIP_STORED, allowZip64=True, compresslevel=None, **kwargs):
        calls.append({"mode": mode, "compression": compression, "compresslevel": compresslevel})
        return original(file, mode=mode, compression=compression, allowZip64=allowZip64, compresslevel=compresslevel, **kwargs)

    monkeypatch.setattr(packer.zipfile, "ZipFile", _wrapper)
    stats = packer.pack_folder(
        str(archive), "folder", str(dest), max_files=500, max_file_bytes=5 * 1024 * 1024, max_total_bytes=50 * 1024 * 1024
    )

    # הזיפ נבנה בכתיבה אחת עם compresslevel=9. אין פתיחה שנייה במצב 'a':
    # metadata.json לא מוזרק כאן — הגיבוי מקבל אותו מ-save_backup_bytes, ולסקיל
    # קובץ זר בשורש הארכיון פוסל אותו כסקיל תקין.
    assert any(c["mode"] == "w" and c["compresslevel"] == 9 for c in calls), calls
    assert not any(c["mode"] == "a" for c in calls)
    assert stats["total_files"] == 1
    # וכל רשומה נדחסה בפועל — לא רק שהארכיון נפתח עם הרמה הנכונה
    with original(dest) as zf:
        assert zf.namelist() == ["folder/a.txt"]
        assert all(i.compress_type == _real_zipfile.ZIP_DEFLATED for i in zf.infolist())
