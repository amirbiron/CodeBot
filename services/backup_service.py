from typing import Any, Dict, List, Tuple, cast

from file_manager import backup_manager


def save_backup_bytes(data: bytes, metadata: Dict[str, Any]) -> bool:
    # ודא שתמיד מוחזר bool גם אם ה-implementation מחזיר backup_id/str/None
    return bool(backup_manager.save_backup_bytes(data, metadata))


def list_backups(user_id: int):
    return backup_manager.list_backups(user_id)


def restore_from_backup(user_id: int, backup_path: str, overwrite: bool = True, purge: bool = True) -> Dict[str, Any]:
    return backup_manager.restore_from_backup(user_id=user_id, backup_path=backup_path, overwrite=overwrite, purge=purge)


def delete_backups(user_id: int, backup_ids: List[str]) -> Dict[str, Any]:
    return backup_manager.delete_backups(user_id=user_id, backup_ids=backup_ids)

