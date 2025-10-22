import io
import json
import zipfile
from pathlib import Path


def _zip_with_md(bid: str, uid: int) -> bytes:
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('a.txt', 'hello')
        zf.writestr('metadata.json', json.dumps({"backup_id": bid, "user_id": uid}))
    return mem.getvalue()


def test_save_backup_file_fs_streams_without_readall(tmp_path, monkeypatch):
    from file_manager import BackupManager

    monkeypatch.setenv("BACKUPS_STORAGE", "fs")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    mgr = BackupManager()
    src = tmp_path / "src.zip"
    src.write_bytes(_zip_with_md("bid1", 123))

    out_id = mgr.save_backup_file(str(src))
    assert out_id == "bid1"
    # Ensure file exists under backup_dir
    saved = Path(mgr.backup_dir) / "bid1.zip"
    assert saved.exists() and saved.is_file()


def test_save_backup_file_gridfs_falls_back_to_fs_when_no_db(tmp_path, monkeypatch):
    from file_manager import BackupManager

    # Force mongo mode but with no gridfs/db available → fallback to fs
    monkeypatch.setenv("BACKUPS_STORAGE", "mongo")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    mgr = BackupManager()
    src = tmp_path / "src2.zip"
    src.write_bytes(_zip_with_md("bid2", 456))

    out_id = mgr.save_backup_file(str(src))
    assert out_id == "bid2"
    saved = Path(mgr.backup_dir) / "bid2.zip"
    assert saved.exists()
