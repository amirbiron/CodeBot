import types

def test_code_service_detect_language_smoke():
    from services import code_service

    assert code_service.detect_language("print('hi')", "a.py").lower() in {"python", "py", "python3"}


def test_backup_service_interface_smoke():
    from services import backup_service

    # API presence check (no actual backup run here)
    assert hasattr(backup_service, "list_backups")
    assert hasattr(backup_service, "restore_from_backup")
    assert hasattr(backup_service, "save_backup_bytes")

