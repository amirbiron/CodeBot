def test_manager_soft_delete_files_by_ids_passes_through():
    """‏``DatabaseManager`` הוא מעבר דק — הבדיקה מקבעת את החתימה.

    ‏``user_id`` הוא חלק מהחתימה ולא פרט טכני: קודמתה,
    ``delete_file_by_id``, לא תחמה למשתמש כלל, ולכן מזהה שדלף היה מוחק
    קובץ של מישהו אחר. התיחום נאכף בשאילתה ולא בבדיקה שאפשר לשכוח.
    """
    from database.manager import DatabaseManager
    m = DatabaseManager()

    class Repo:
        def __init__(self):
            self.seen = None

        def soft_delete_files_by_ids(self, user_id, file_ids):
            self.seen = (user_id, list(file_ids))
            return {"files": 1, "versions": 3, "missing": 0}

    repo = Repo()
    m._repo = repo
    out = m.soft_delete_files_by_ids(7, ["507f1f77bcf86cd799439011"])

    assert out == {"files": 1, "versions": 3, "missing": 0}
    assert repo.seen == (7, ["507f1f77bcf86cd799439011"])
