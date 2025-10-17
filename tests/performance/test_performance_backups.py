import os
import time
import json
import zipfile
import pytest


pytestmark = pytest.mark.performance


def _should_run():
    return os.getenv("RUN_PERF", "") == "1"


@pytest.mark.skipif(not _should_run(), reason="Performance tests are opt-in (set RUN_PERF=1)")
def test_list_backups_1000_files_under_time(tmp_path, monkeypatch):
    # Arrange env to force FS storage into tmp
    monkeypatch.setenv("BACKUPS_STORAGE", "fs")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    # Create N zip backups belonging to same user
    user_id = 777
    n_files = int(os.getenv("PERF_N_BACKUPS", "1000"))

    for i in range(n_files):
        zpath = tmp_path / f"backup_{user_id}_{i}.zip"
        with zipfile.ZipFile(zpath, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('a.txt', 'x')
            zf.writestr('metadata.json', json.dumps({
                "backup_id": f"backup_{user_id}_{i}",
                "user_id": user_id,
                "file_count": 1,
            }))

    # Import after env is set
    from file_manager import BackupManager
    mgr = BackupManager()

    t0 = time.perf_counter()
    items = mgr.list_backups(user_id=user_id)
    dt = time.perf_counter() - t0

    # Basic sanity
    assert len(items) == n_files
    # Threshold generous to avoid flakiness on CI machines; adjust via PERF_MAX_SECS env
    max_secs = float(os.getenv("PERF_MAX_SECS", "2.5"))
    assert dt < max_secs, f"listing {n_files} backups took {dt:.3f}s (> {max_secs}s)"
