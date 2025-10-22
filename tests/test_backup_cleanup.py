import os
import json
import time
from datetime import datetime, timedelta, timezone
import zipfile

from file_manager import BackupManager


def _write_zip_with_metadata(path, md):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('metadata.json', json.dumps(md))
        zf.writestr('dummy.txt', 'x')


def test_cleanup_skips_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv('DISABLE_BACKGROUND_CLEANUP', 'true')
    mgr = BackupManager()
    # עבוד רק בתיקיית tmp בטסט
    mgr.backup_dir = tmp_path
    mgr.legacy_backup_dir = None

    # צור גיבוי ישן
    old_md = {"user_id": 1, "created_at": (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()}
    _write_zip_with_metadata(tmp_path / 'backup_1_old.zip', old_md)

    res = mgr.cleanup_expired_backups(retention_days=30)
    assert res.get('skipped') is True
    assert (tmp_path / 'backup_1_old.zip').exists()


def test_cleanup_skips_in_safe_mode(monkeypatch, tmp_path):
    monkeypatch.delenv('DISABLE_BACKGROUND_CLEANUP', raising=False)
    monkeypatch.setenv('SAFE_MODE', 'true')
    mgr = BackupManager()
    mgr.backup_dir = tmp_path
    mgr.legacy_backup_dir = None

    md = {"user_id": 2, "created_at": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()}
    _write_zip_with_metadata(tmp_path / 'backup_2_old.zip', md)

    res = mgr.cleanup_expired_backups(retention_days=30)
    assert res.get('skipped') is True
    assert (tmp_path / 'backup_2_old.zip').exists()


def test_cleanup_deletes_by_retention(monkeypatch, tmp_path):
    monkeypatch.delenv('DISABLE_BACKGROUND_CLEANUP', raising=False)
    monkeypatch.delenv('SAFE_MODE', raising=False)
    mgr = BackupManager()
    mgr.backup_dir = tmp_path
    mgr.legacy_backup_dir = None

    # ישן (יימחק)
    old_dt = datetime.now(timezone.utc) - timedelta(days=40)
    old_md = {"user_id": 7, "created_at": old_dt.isoformat()}
    old_p = tmp_path / 'backup_7_old.zip'
    _write_zip_with_metadata(old_p, old_md)
    # עדכן mtime לסנכרון עם התאריך במטא-דטה (לא חובה אך מועיל)
    os.utime(old_p, (time.time(), (datetime.now(timezone.utc) - timedelta(days=35)).timestamp()))

    # חדש (יישאר)
    new_dt = datetime.now(timezone.utc) - timedelta(days=5)
    new_md = {"user_id": 7, "created_at": new_dt.isoformat()}
    new_p = tmp_path / 'backup_7_new.zip'
    _write_zip_with_metadata(new_p, new_md)

    res = mgr.cleanup_expired_backups(retention_days=30, budget_seconds=5)
    assert isinstance(res, dict)
    # לפחות פריט אחד נמחק
    assert res.get('fs_deleted', 0) >= 1
    assert not old_p.exists()
    assert new_p.exists()


def test_cleanup_limits_max_per_user(monkeypatch, tmp_path):
    monkeypatch.delenv('DISABLE_BACKGROUND_CLEANUP', raising=False)
    monkeypatch.delenv('SAFE_MODE', raising=False)
    mgr = BackupManager()
    mgr.backup_dir = tmp_path
    mgr.legacy_backup_dir = None

    uid = 42
    base = datetime.now(timezone.utc)
    # צור 5 גיבויים באינטרוולים — נשמור רק את 2 החדשים
    paths = []
    for i in range(5):
        dt = base - timedelta(days=(5 - i))
        p = tmp_path / f'backup_{uid}_{i}.zip'
        _write_zip_with_metadata(p, {"user_id": uid, "created_at": dt.isoformat()})
        paths.append(p)

    res = mgr.cleanup_expired_backups(retention_days=3650, max_per_user=2, budget_seconds=5)
    assert isinstance(res, dict)
    # צפה שמספר המחיקות יהיה 3
    assert res.get('fs_deleted', 0) == 3
    # שני האחרונים (i=3,4) נשארים
    assert paths[-1].exists()
    assert paths[-2].exists()
    # הראשונים הוסרו
    assert not paths[0].exists()
    assert not paths[1].exists()
    assert not paths[2].exists()
