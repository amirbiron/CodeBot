"""טסטים לשכבת אחסון הסקילים (SkillManager) — אחסון נפרד מגיבויים.

מוקד עיקרי: הסקיל נשמר ומוחזר byte-for-byte (בלי הזרקת metadata.json כמו בגיבויים),
קולקציית ה-skills מבודדת מ-cleanup של הגיבויים, ושני סקילים עם אותו שם לא דורסים זה את זה.

בעקבות מוסכמת הריפו (fakes בעבודת יד, בלי mongomock) — ראו tests/test_gridfs_backups.py.
"""

import io
import zipfile

from file_manager import SkillManager, BackupManager


class _FakeFSDoc:
    def __init__(self, _id, filename, data, metadata):
        self._id = _id
        self.filename = filename
        self._data = data
        self.metadata = metadata
        self.length = len(data)
        self.uploadDate = None


class _FakeGridFS:
    """Fake מינימלי ל-GridFS שתומך ב-put/find/get/delete עם התאמת query על metadata."""

    def __init__(self, docs=None):
        self._docs = list(docs or [])
        self._seq = 0

    def put(self, data, filename=None, metadata=None):
        self._seq += 1
        _id = self._seq
        self._docs.append(_FakeFSDoc(_id, filename, bytes(data), dict(metadata or {})))
        return _id

    @staticmethod
    def _match(d, query):
        for k, v in (query or {}).items():
            if k == "filename":
                if d.filename != v:
                    return False
            elif k == "metadata.user_id":
                if (d.metadata or {}).get("user_id") != v:
                    return False
            elif k == "metadata.skill_id":
                if (d.metadata or {}).get("skill_id") != v:
                    return False
            elif k == "metadata.backup_id":
                if (d.metadata or {}).get("backup_id") != v:
                    return False
        return True

    def find(self, query=None):
        return [d for d in self._docs if self._match(d, query or {})]

    def get(self, _id):
        for d in self._docs:
            if d._id == _id:
                class _Out:
                    def __init__(self, data):
                        self._data = data

                    def read(self):
                        return self._data

                return _Out(d._data)
        raise FileNotFoundError(_id)

    def delete(self, _id):
        self._docs = [d for d in self._docs if d._id != _id]


def _zip_bytes(extra: bytes = b""):
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", "# My Skill\ncontent" + extra.decode("latin-1"))
        zf.writestr("scripts/run.py", "print('hi')")
    return mem.getvalue()


def _mgr_with_fake(monkeypatch, fake):
    mgr = SkillManager()
    monkeypatch.setattr(mgr, "_get_skills_gridfs", lambda: fake)
    return mgr


def test_skill_saved_and_retrieved_byte_for_byte(monkeypatch):
    """הטסט החשוב ביותר: מה שנשמר חוזר byte-for-byte, בלי הזרקת metadata.json."""
    raw = _zip_bytes()
    fake = _FakeGridFS()
    mgr = _mgr_with_fake(monkeypatch, fake)

    skill_id = mgr.save_skill_bytes(raw, {"user_id": 555, "original_name": "my skill.zip"})
    assert skill_id

    got = mgr.get_skill_bytes(555, skill_id)
    assert got == raw  # זהות מוחלטת — byte-for-byte

    # בניגוד לגיבויים: אין הזרקת metadata.json לתוך הארכיון
    names = zipfile.ZipFile(io.BytesIO(got)).namelist()
    assert "metadata.json" not in names
    assert "SKILL.md" in names


def test_get_skill_bytes_rejects_other_user(monkeypatch):
    """סקיל לא נגיש למשתמש אחר (אימות בעלות)."""
    raw = _zip_bytes()
    fake = _FakeGridFS()
    mgr = _mgr_with_fake(monkeypatch, fake)
    skill_id = mgr.save_skill_bytes(raw, {"user_id": 111, "original_name": "s.zip"})
    assert mgr.get_skill_bytes(222, skill_id) is None
    assert mgr.get_skill_bytes(111, skill_id) == raw


def test_two_skills_same_name_no_overwrite(monkeypatch):
    """שני סקילים עם אותו שם מקורי אינם דורסים זה את זה."""
    fake = _FakeGridFS()
    mgr = _mgr_with_fake(monkeypatch, fake)
    raw1 = _zip_bytes()
    raw2 = _zip_bytes(extra=b"XYZ")

    id1 = mgr.save_skill_bytes(raw1, {"user_id": 7, "original_name": "skill.zip"})
    id2 = mgr.save_skill_bytes(raw2, {"user_id": 7, "original_name": "skill.zip"})
    assert id1 != id2

    lst = mgr.list_skills(7)
    assert len(lst) == 2
    filenames = {s.file_name for s in lst}
    assert len(filenames) == 2  # שמות קבצים שונים בפועל — אין דריסה

    # כל אחד מחזיר את התוכן שלו במדויק
    assert mgr.get_skill_bytes(7, id1) == raw1
    assert mgr.get_skill_bytes(7, id2) == raw2


def test_delete_skill_only_own(monkeypatch):
    fake = _FakeGridFS()
    mgr = _mgr_with_fake(monkeypatch, fake)
    sid = mgr.save_skill_bytes(_zip_bytes(), {"user_id": 42, "original_name": "a.zip"})
    # משתמש אחר לא יכול למחוק
    res_other = mgr.delete_skills(999, [sid])
    assert res_other["deleted"] == 0
    assert mgr.get_skill_bytes(42, sid) is not None
    # הבעלים מוחק
    res = mgr.delete_skills(42, [sid])
    assert res["deleted"] == 1
    assert mgr.get_skill_bytes(42, sid) is None


def _real_pymongo_db():
    """Database אמיתי של pymongo בלי שרת (connect=False) — הבנאי לא מתחבר.

    זהו בדיוק האובייקט ש-get_mongo_db() מחזיר בבוט המחובר, וה-bool() שלו זורק
    NotImplementedError — מה שהפיל את _get_skills_gridfs לפני התיקון.
    """
    import pytest
    pymongo = pytest.importorskip("pymongo")
    client = pymongo.MongoClient("mongodb://localhost:27017", connect=False)
    return client["codebot_test"]


class _FakeFacade:
    def __init__(self, db):
        self._db = db

    def get_mongo_db(self):
        return self._db


def test_get_skills_gridfs_with_real_pymongo_db(monkeypatch):
    """רגרסיה: get_mongo_db מחזיר Database אמיתי → _get_skills_gridfs חייב GridFS, לא None.

    לפני התיקון היה כאן ``if not mongo_db`` שזרק NotImplementedError (pymongo לא תומך
    ב-bool על Database) → נבלע ב-except → הוחזר None → "GridFS 'skills' לא זמין" בפרודקשן.
    שאר הטסטים מוקים את _get_skills_gridfs ולכן פספסו את זה — כאן קוראים למתודה האמיתית.
    """
    import pytest
    gridfs = pytest.importorskip("gridfs")
    db = _real_pymongo_db()
    monkeypatch.setattr("file_manager.get_files_facade", lambda: _FakeFacade(db))

    fs = SkillManager()._get_skills_gridfs()
    assert fs is not None, "אמור להחזיר GridFS על Database מחובר — לא None"
    assert isinstance(fs, gridfs.GridFS)


def test_get_gridfs_backups_with_real_pymongo_db(monkeypatch):
    """אותה רגרסיה עבור BackupManager._get_gridfs (מוסתר בפרודקשן ע"י BACKUPS_STORAGE=fs)."""
    import pytest
    gridfs = pytest.importorskip("gridfs")
    monkeypatch.setenv("BACKUPS_STORAGE", "mongo")  # אחרת מחזיר None עוד לפני get_mongo_db
    db = _real_pymongo_db()
    monkeypatch.setattr("file_manager.get_files_facade", lambda: _FakeFacade(db))

    fs = BackupManager()._get_gridfs()
    assert fs is not None
    assert isinstance(fs, gridfs.GridFS)


def test_get_skills_gridfs_returns_none_without_db(monkeypatch):
    """כשאין חיבור (get_mongo_db מחזיר None) עדיין מחזירים None בשקט — בלי חריגה."""
    monkeypatch.setattr("file_manager.get_files_facade", lambda: _FakeFacade(None))
    assert SkillManager()._get_skills_gridfs() is None


def test_cleanup_backups_does_not_touch_skills(monkeypatch, tmp_path):
    """cleanup_expired_backups כבול לקולקציית "backups"; קולקציית "skills" לא נסרקת ולא נמחקת."""
    monkeypatch.setenv("BACKUPS_STORAGE", "mongo")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))

    skills_fs = _FakeGridFS()
    smgr = _mgr_with_fake(monkeypatch, skills_fs)
    raw = _zip_bytes()
    sid = smgr.save_skill_bytes(raw, {"user_id": 9, "original_name": "keep.zip"})
    assert sid

    # BackupManager עם קולקציית backups ריקה ו-retention אגרסיבי
    bmgr = BackupManager()
    monkeypatch.setattr(bmgr, "_get_gridfs", lambda: _FakeGridFS())
    bmgr.cleanup_expired_backups(retention_days=0)

    # הסקיל שרד — קולקציה נפרדת לגמרי
    assert smgr.get_skill_bytes(9, sid) == raw
    assert len(smgr.list_skills(9)) == 1
