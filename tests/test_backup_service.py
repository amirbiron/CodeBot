import types


def test_backup_service_delegations(monkeypatch):
    # Stub backup_manager in file_manager
    class _FakeMgr:
        def __init__(self):
            self.saved = []
            self.listed_user = None
            self.restores = []
            self.deletes = []
        def save_backup_bytes(self, data, metadata):
            self.saved.append((data, metadata))
            return True
        def list_backups(self, user_id):
            self.listed_user = user_id
            return ["b1", "b2"]
        def restore_from_backup(self, user_id, backup_path, overwrite=True, purge=True):
            self.restores.append((user_id, backup_path, overwrite, purge))
            return {"restored_files": 1, "errors": []}
        def delete_backups(self, user_id, backup_ids):
            self.deletes.append((user_id, tuple(backup_ids)))
            return {"deleted": len(backup_ids), "errors": []}

    fake = _FakeMgr()
    fm = types.ModuleType("file_manager")
    fm.backup_manager = fake
    monkeypatch.setitem(__import__('sys').modules, 'file_manager', fm)

    import services.backup_service as svc

    assert svc.save_backup_bytes(b"zip", {"backup_id": "x"}) is True
    assert svc.list_backups(7) == ["b1", "b2"]
    out = svc.restore_from_backup(7, "/tmp/x.zip", overwrite=False, purge=False)
    assert out.get("restored_files") == 1
    res = svc.delete_backups(7, ["a", "b", "c"])
    assert res.get("deleted") == 3

    # verify delegation targets were called with expected args
    assert fake.saved and fake.saved[0][0] == b"zip"
    assert fake.listed_user == 7
    assert fake.restores and fake.restores[0] == (7, "/tmp/x.zip", False, False)
    assert fake.deletes and fake.deletes[0] == (7, ("a", "b", "c"))

