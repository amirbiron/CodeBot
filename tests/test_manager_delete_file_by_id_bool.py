import types

def test_manager_delete_file_by_id_returns_bool():
    from database.manager import DatabaseManager
    m = DatabaseManager()
    # Inject a dummy repo that returns True
    class Repo:
        def delete_file_by_id(self, fid: str) -> bool:
            return True
    m._repo = Repo()
    assert m.delete_file_by_id("507f1f77bcf86cd799439011") is True
