from pathlib import Path
from file_manager import BackupManager


def test_is_safe_path_allows_under_base(tmp_path):
    mgr = BackupManager()
    base = tmp_path / "allowed"
    base.mkdir()
    child = base / "x.zip"
    assert mgr._is_safe_path(child, base) is True


def test_is_safe_path_blocks_root(tmp_path):
    mgr = BackupManager()
    base = tmp_path
    assert mgr._is_safe_path(Path("/"), base) is False
