import io
import json
import zipfile
from pathlib import Path


def _zip_with_user(user_id: int, bid: str = "bid") -> bytes:
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('a.txt', 'A')
        zf.writestr('metadata.json', json.dumps({"backup_id": bid, "user_id": user_id}))
    return mem.getvalue()


def test_delete_backups_skips_other_user(tmp_path, monkeypatch):
    from file_manager import BackupManager

    monkeypatch.setenv("BACKUPS_STORAGE", "fs")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    mgr = BackupManager()
    # create a zip for user 111
    path = Path(mgr.backup_dir) / "keep_me.zip"
    path.write_bytes(_zip_with_user(111, "keep_me"))

    # attempt to delete as user 222 — should skip
    res = mgr.delete_backups(user_id=222, backup_ids=["keep_me"])
    assert res["deleted"] == 0
    assert path.exists()


def test_save_backup_file_from_existing_zip(tmp_path, monkeypatch):
    from file_manager import BackupManager

    monkeypatch.setenv("BACKUPS_STORAGE", "fs")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    mgr = BackupManager()
    # write a ready zip with metadata
    src = tmp_path / "ready.zip"
    src.write_bytes(_zip_with_user(999, "from_file"))

    out_id = mgr.save_backup_file(str(src))
    assert out_id == "from_file"
    # ensure saved into backup_dir
    saved = Path(mgr.backup_dir) / "from_file.zip"
    assert saved.exists()


def test_list_backups_skips_zip_without_owner(tmp_path, monkeypatch):
    from file_manager import BackupManager

    monkeypatch.setenv("BACKUPS_STORAGE", "fs")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    mgr = BackupManager()
    # write zip without metadata.json and name without userId pattern
    path = Path(mgr.backup_dir) / "no_owner.zip"
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('a.txt', 'A')
    path.write_bytes(mem.getvalue())

    lst = mgr.list_backups(123)
    assert all(b.backup_id != 'no_owner' for b in lst)

