import io
import os
import zipfile
from pathlib import Path

import pytest

from file_manager import BackupManager


def make_zip_bytes(files):
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
        # מטאדטה מינימלית
        zf.writestr(
            "metadata.json",
            "{""backup_id"": ""test_backup"", ""user_id"": 123, ""file_count"": 1}",
        )
    return mem.getvalue()


def test_save_and_list_backups_fs_only(tmp_path, monkeypatch):
    # הבטח עבודה בתיקייה זמנית בלבד
    monkeypatch.setenv("BACKUPS_STORAGE", "fs")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    mgr = BackupManager()
    assert Path(mgr.backup_dir).resolve().as_posix().startswith(Path(tmp_path).resolve().as_posix())

    data = make_zip_bytes({"hello.py": "print('hi')"})
    bid = mgr.save_backup_bytes(data, {"backup_id": "test_backup", "user_id": 123, "file_count": 1})
    assert bid == "test_backup"

    items = mgr.list_backups(user_id=123)
    assert any(b.backup_id == "test_backup" for b in items)


def test_delete_backups_fs_only(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUPS_STORAGE", "fs")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    mgr = BackupManager()
    data = make_zip_bytes({"hello.py": "print('hi')"})
    bid = mgr.save_backup_bytes(data, {"backup_id": "test_backup_del", "user_id": 999, "file_count": 1})
    assert bid == "test_backup_del"

    # קובץ נוצר בדיסק תחת tmp
    path = Path(mgr.backup_dir) / f"{bid}.zip"
    assert path.exists()

    res = mgr.delete_backups(user_id=999, backup_ids=[bid])
    assert res["deleted"] >= 1
    assert not path.exists()


def test_list_backups_filters_by_user(tmp_path, monkeypatch):
    # ודא שהרשימה כוללת רק ZIPים של המשתמש המבקש
    monkeypatch.setenv("BACKUPS_STORAGE", "fs")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    mgr = BackupManager()
    data_a = make_zip_bytes({"a.py": "print('a')"})
    data_b = make_zip_bytes({"b.py": "print('b')"})
    bid_a = mgr.save_backup_bytes(data_a, {"backup_id": "backup_111_1", "user_id": 111, "file_count": 1})
    bid_b = mgr.save_backup_bytes(data_b, {"backup_id": "backup_222_1", "user_id": 222, "file_count": 1})
    assert bid_a and bid_b

    list_for_111 = mgr.list_backups(user_id=111)
    ids_111 = {b.backup_id for b in list_for_111}
    assert "backup_111_1" in ids_111
    assert "backup_222_1" not in ids_111

    list_for_222 = mgr.list_backups(user_id=222)
    ids_222 = {b.backup_id for b in list_for_222}
    assert "backup_222_1" in ids_222
    assert "backup_111_1" not in ids_222


def _make_zip_with_metadata(backup_id: str, user_id: int) -> bytes:
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.txt", "A")
        zf.writestr(
            "metadata.json",
            ("{""backup_id"": ""%s"", ""user_id"": %d}" % (backup_id, user_id)).replace("""", '"'),
        )
    return mem.getvalue()


def test_save_backup_bytes_merges_metadata_preexisting_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUPS_STORAGE", "fs")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    mgr = BackupManager()
    raw = _make_zip_with_metadata("orig", 123)
    merged_id = "merged_999"
    out_id = mgr.save_backup_bytes(raw, {"backup_id": merged_id, "user_id": 999})
    assert out_id == merged_id
    # נשמר בדיסק תחת tmp
    path = Path(mgr.backup_dir) / f"{merged_id}.zip"
    assert path.exists()
    # list_backups מזהה כבעלות של 999
    items = mgr.list_backups(999)
    ids = {b.backup_id for b in items}
    assert merged_id in ids
    # metadata.json מעודכן בפועל
    with zipfile.ZipFile(path, 'r') as zf:
        md = zf.read('metadata.json').decode('utf-8')
        assert '"user_id": 999' in md
        assert f'"backup_id": "{merged_id}"' in md


def test_list_backups_fs_regex_fallback_and_count(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUPS_STORAGE", "fs")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    mgr = BackupManager()
    # צור ZIP ללא metadata.json בשם הכולל userId
    name = "backup_777_unknown"
    path = Path(mgr.backup_dir) / f"{name}.zip"
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("x.py", "print('x')")
        zf.writestr("y.txt", "y")
        zf.writestr("dir/", b"")
        zf.writestr("dir/z.md", "z")
    path.write_bytes(mem.getvalue())

    lst = mgr.list_backups(777)
    # מזהה לפי שם
    assert any(b.backup_id == name for b in lst)
    # file_count חושב (3 קבצים שאינם תיקיות)
    match = next(b for b in lst if b.backup_id == name)
    assert match.file_count == 3

