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

