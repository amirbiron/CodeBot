import io
import json
import zipfile
from pathlib import Path

import pytest

from file_manager import BackupManager


@pytest.mark.asyncio
async def test_list_backups_skips_non_zip_and_empty(tmp_path: Path, caplog):
    # Prepare directory with: non-zip, empty file, and valid zip
    non_zip = tmp_path / "backup_123_bad.txt.zip"  # not a real zip
    non_zip.write_text("not a zip")

    empty_zip = tmp_path / "backup_123_empty.zip"
    empty_zip.touch()  # size 0

    valid_zip = tmp_path / "backup_123_ok.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        md = {"backup_id": "backup_123_ok", "user_id": 123, "created_at": "2025-01-01T00:00:00+00:00", "file_count": 1}
        zf.writestr("metadata.json", json.dumps(md))
        zf.writestr("file.txt", "hello")
    valid_zip.write_bytes(buf.getvalue())

    # Create manager pointing to tmp_path
    mgr = BackupManager()
    mgr.backup_dir = tmp_path
    # Execute twice to cover cache/dedup of invalid warnings
    with caplog.at_level("INFO"):
        items1 = mgr.list_backups(user_id=123)
        items2 = mgr.list_backups(user_id=123)

    # Only the valid zip should be returned
    assert len(items1) == 1
    assert len(items2) == 1
    info = items1[0]
    assert info.backup_id == "backup_123_ok"
    assert info.user_id == 123
    assert info.file_count >= 1

    # Ensure no exception on non-zip/empty; optional: logs present at most once
    msgs = [rec.getMessage() for rec in caplog.records if "דלג על" in rec.getMessage()]
    # At least one informative skip log should appear
    assert any("שאינו ZIP" in m or "לא תקין" in m for m in msgs)
