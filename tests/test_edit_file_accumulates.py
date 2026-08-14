"""בדיקת קבלה: עריכות עוקבות דרך ה-MCP חייבות להצטבר.

הבדיקה לא מסתמכת על ערך ההחזרה של הכתיבה — היא קוראת את הקובץ מחדש אחרי
כל עריכה. זה הלקח מהבאג המקורי: הכתיבה החזירה ``ok:true`` בכל פעם, בעוד
שהקובץ הפעיל לא השתנה כלל.

הרגרסיה שנשמרת כאן: ``get_latest_version`` מקוּשה, ואותו ערך שימש גם
לקריאה לפני עריכה וגם לחישוב מספר הגרסה הבאה. כשה-invalidation לא ניקה
את הפולבק המקומי, כל עריכה נבנתה מחדש על גבי אותה גרסת בסיס.
"""

import cache_manager
import pytest
from cache_manager import cache

from mcp_server import handlers


class _FakeCollection:
    """אוסף מונגו מינימלי עם append-only versioning, כמו במסד האמיתי."""

    def __init__(self):
        self.docs = []
        self._seq = 0

    def insert_one(self, doc):
        self._seq += 1
        stored = dict(doc)
        stored["_id"] = f"id-{self._seq}"
        self.docs.append(stored)
        return type("R", (), {"inserted_id": stored["_id"]})()

    def find_one(self, query, sort=None):
        matches = [
            d
            for d in self.docs
            if d.get("user_id") == query.get("user_id")
            and d.get("file_name") == query.get("file_name")
        ]
        if not matches:
            return None
        return max(matches, key=lambda d: int(d.get("version", 0) or 0))

    def update_many(self, *a, **k):
        return type("R", (), {"modified_count": 0})()


class _FakeDBM:
    """שכבת DB שמריצה את לוגיקת הגרסאות האמיתית מעל האוסף המזויף."""

    def __init__(self):
        self.collection = _FakeCollection()
        from database.repository import Repository

        self.repo = Repository(self)

    def get_latest_version(self, user_id, file_name):
        return self.repo.get_latest_version(user_id, file_name)

    def get_latest_version_fresh(self, user_id, file_name):
        return self.repo._fetch_latest_version(user_id, file_name)

    def save_code_snippet(self, snippet):
        return self.repo.save_code_snippet(snippet)

    def get_version(self, user_id, file_name, version):
        for d in self.collection.docs:
            if (
                d.get("user_id") == user_id
                and d.get("file_name") == file_name
                and int(d.get("version", 0)) == int(version)
            ):
                return d
        return None

    def get_all_versions(self, user_id, file_name):
        return [
            d
            for d in self.collection.docs
            if d.get("user_id") == user_id and d.get("file_name") == file_name
        ]


def _make_backend(dbm):
    """ה-backend האמיתי של ה-MCP, מחווט ל-DB המזויף."""
    from mcp_server.backend import ProductionBackend

    return ProductionBackend(db_manager=dbm)


USER = 4242
NAME = "notes.md"


@pytest.fixture
def backend():
    # הבאג מתגלה בדיוק כש-Redis כבוי והפולבק המקומי נכנס לפעולה
    cache_manager._local_cache_store.clear()
    assert not cache.is_enabled, "הבדיקה מיועדת למצב שבו Redis אינו זמין"
    dbm = _FakeDBM()
    be = _make_backend(dbm)
    handlers.save_file(
        be,
        USER,
        file_name=NAME,
        code="alpha\nbravo\ncharlie\n",
        language="markdown",
    )
    yield be
    cache_manager._local_cache_store.clear()


def _read(backend):
    doc = backend.get_file(USER, file_name=NAME, file_id=None, version=None)
    return doc.get("code"), int(doc.get("version", 0))


def _assert_edit_path_bypasses_cache():
    """מסלול העריכה לא אמור להשאיר מאחוריו מפתח גרסה מקוּש כלל.

    בלי הבדיקה הזו הקובץ עלול לעבור מהסיבה הלא נכונה: אם מסלול העריכה
    יחזור להסתמך על ``get_latest_version`` המקוּשה, ריצה שנמשכת יותר
    מ-180 שניות עדיין תיראה ירוקה — פשוט כי ה-TTL פג בינתיים.

    הבדיקה חזקה מ"הקאש התפנה": היא דורשת שהערך לא ייכנס לקאש מלכתחילה.
    זה מה שהופך את המסלול לעמיד גם מול הפולבק המקומי, שהוא פר-תהליך
    וניקוי שלו ב-worker אחד אינו נוגע באחרים.
    """
    leftovers = [k for k in cache_manager._local_cache_store if "latest_version" in k]
    assert not leftovers, f"מסלול העריכה נשען על קאש גרסאות: {leftovers}"


def test_consecutive_edits_accumulate(backend):
    """שלוש עריכות עוקבות — כל אחת נקראת מחדש מהמסד ומאמתת הצטברות."""
    base_code, base_version = _read(backend)
    assert base_version == 1
    assert "alpha" in base_code

    # עריכה A
    res = handlers.edit_file(
        backend, USER, file_name=NAME, old_string="alpha", new_string="ALPHA-1"
    )
    assert res.get("ok") is True
    _assert_edit_path_bypasses_cache()
    code, version = _read(backend)
    assert "ALPHA-1" in code, "העריכה הראשונה לא נשמרה"
    assert version == 2, f"הגרסה לא עלתה ל-2 (התקבל {version})"

    # עריכה B — חייבת להישמר *וגם* לשמר את A
    res = handlers.edit_file(
        backend, USER, file_name=NAME, old_string="bravo", new_string="BRAVO-2"
    )
    assert res.get("ok") is True
    _assert_edit_path_bypasses_cache()
    code, version = _read(backend)
    assert "BRAVO-2" in code, "העריכה השנייה לא נשמרה"
    assert "ALPHA-1" in code, "העריכה השנייה דרסה את הראשונה"
    assert version == 3, f"הגרסה לא עלתה ל-3 (התקבל {version})"

    # עריכה C — שלושתן יחד
    res = handlers.edit_file(
        backend, USER, file_name=NAME, old_string="charlie", new_string="CHARLIE-3"
    )
    assert res.get("ok") is True
    code, version = _read(backend)
    assert "ALPHA-1" in code and "BRAVO-2" in code and "CHARLIE-3" in code
    assert version == 4, f"הגרסה לא עלתה ל-4 (התקבל {version})"


def test_every_version_number_is_unique(backend):
    """מספר גרסה כפול הוא הסימפטום שממנו התחיל הבאג."""
    for old, new in (("alpha", "A"), ("bravo", "B"), ("charlie", "C")):
        handlers.edit_file(backend, USER, file_name=NAME, old_string=old, new_string=new)

    versions = [int(v.get("version", 0)) for v in backend.list_versions(USER, file_name=NAME)]
    assert sorted(versions) == [1, 2, 3, 4], f"גרסאות לא רציפות: {sorted(versions)}"
    assert len(versions) == len(set(versions)), f"נמצאו גרסאות כפולות: {versions}"


def test_write_result_reports_the_stored_version(backend):
    """ה-re-fetch שאחרי הכתיבה מוצהר כ-authoritative — שיהיה."""
    res = handlers.edit_file(backend, USER, file_name=NAME, old_string="alpha", new_string="ZULU")
    assert res.get("ok") is True
    reported = int((res.get("file") or {}).get("version", 0))
    _, actual = _read(backend)
    assert reported == actual, f"הכתיבה דיווחה גרסה {reported} אבל במסד יש {actual}"
