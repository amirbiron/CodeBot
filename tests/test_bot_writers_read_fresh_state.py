"""עריכת הערה ושכפול בבוט כותבים את מה שיש **במסד**, ולא את מה שהקאש זוכר.

שני המסלולים בונים גרסה חדשה משדות של קובץ קיים: עריכת הערה כותבת מחדש את גוף הקוד, השפה והתגיות עם תיאור חדש, ושכפול מעתיק הכול לקובץ חדש. עד התיקון שניהם קראו את הקובץ דרך ``get_latest_version``, שעטופה ב-``@cached`` — והשכפול מהרשימה קרא קודם כול מ-``context.user_data['files_cache']``, רשימת התצוגה של הבוט, שאין לה TTL בכלל. הוובאפ כותב למסד בחיבור משלו, וכמה ממסלוליו אינם מבטלים את הקאש, ולכן עריכה בוובאפ ואחריה עריכת הערה בבוט, בתוך חלון הקאש, יצרו גרסה חדשה עם **הקוד הישן**.

הצורה של כל בדיקה כאן, כמו ב-``tests/test_save_file_reads_fresh_state.py``: קוראים דרך הגטר המקוּש, כותבים גרסה חדשה ישירות לאוסף כמו שהוובאפ כותב, מוודאים שהקאש **עדיין** מחזיק את הישנה — אחרת הבדיקה לא בודקת כלום — ורק אז מריצים את המסלול ובודקים מה **נכתב**. ``tests/test_handlers_receive_new_code_preserve.py`` מחליף את המסד בדמות בלי קאש, ולכן אינו ראיה לזה: הוא מסיר בדיוק את השכבה שבה הבאג.

**מה אמיתי ומה לא.** ``DatabaseManager``, ``Repository`` עם ה-``@cached`` שלו, ``FilesFacade`` וה-handlers — אמיתיים. רק האוסף מזויף (``tests/_fake_mongo.py``), והוא עטוף כך שאין לו ``docs``: בלי העטיפה ``Repository`` היה פונה למסלול הזיכרון שקיים רק בשביל בדיקות, ולא לשאילתה שרצה בייצור. כך הבדיקות רצות בכל סביבה, גם ב-CI של ה-PR, שבו מונגו אמיתי אינו נגיש (``docs/testing.rst``).

**ועריכת ההערה נבדקת בשני מקומות.** ``conversation_handlers.py`` מייבא את ``receive_new_code`` מ-``handlers/file_view.py`` ואחר כך מגדיר עותק משלו באותו שם — וזה העותק שה-``ConversationHandler`` מריץ. שניהם נבדקים, ושניהם קוראים עכשיו דרך הדלת הטרייה.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

USER_ID = 6161
NOTE_FILE = "notes.md"
CREATED = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)

OLD = {"code": "# גרסה ישנה\n", "programming_language": "text", "description": "תיאור ישן", "tags": ["old"]}
NEW = {"code": "# גרסה חדשה\n", "programming_language": "markdown", "description": "תיאור חדש", "tags": ["new"]}


class _CollectionWithoutDocs:
    """``FakeCollection`` בלי ``docs``, כדי ש-``Repository`` ישאל את האוסף כמו בייצור."""

    def __init__(self):
        from _fake_mongo import FakeCollection

        self._inner = FakeCollection()

    def __getattr__(self, name):
        if name == "docs":
            raise AttributeError(name)
        return getattr(self._inner, name)


class _World:
    def __init__(self, collection):
        self.collection = collection

    def write_version(self, file_name, version, fields):
        """כתיבה ישירה לאוסף, כמו שהוובאפ כותב — בלי ``Repository`` ובלי לבטל את הקאש שלו."""
        self.collection.insert_one({
            "user_id": USER_ID, "file_name": file_name, "version": version, "is_active": True,
            "created_at": CREATED, "updated_at": CREATED, **fields,
        })

    def latest(self, file_name):
        return self.collection.find_one(
            {"user_id": USER_ID, "file_name": file_name, "is_active": True}, sort=[("version", -1)])

    def cached_latest(self, file_name):
        from src.infrastructure.composition import get_files_facade

        return get_files_facade().get_latest_version(USER_ID, file_name)

    def file_with_a_stale_cache(self, file_name):
        """קובץ שהבוט קרא בגרסה 1, ואחר כך נכתבה לו גרסה 2 בוובאפ."""
        self.write_version(file_name, 1, OLD)
        assert self.cached_latest(file_name)["code"] == OLD["code"]
        self.write_version(file_name, 2, NEW)
        assert self.cached_latest(file_name)["code"] == OLD["code"], "הקאש לא החזיק את הגרסה — הבדיקה לא בודקת כלום"


@pytest.fixture
def world(monkeypatch):
    import database
    from database.manager import DatabaseManager

    # ``DISABLE_DB`` (``tests/conftest.py``) משאיר את המנהל בלי חיבור; האוסף מוחלף כאן.
    manager = DatabaseManager()
    manager.collection = _CollectionWithoutDocs()
    monkeypatch.setattr(database, "db", manager)
    return _World(manager.collection)


class _Message:
    def __init__(self, text):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **_kwargs):
        self.replies.append(text)


class _Query:
    def __init__(self, data):
        self.data = data
        self.texts = []

    async def answer(self, *_args, **_kwargs):
        return None

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        self.texts.append(text)


#: לכל handler — השדות שהוא מעתיק מהקובץ לגרסה החדשה. העותק ב-``handlers/file_view.py`` אינו מעביר תגיות
#: כלל (הגרסה החדשה יוצאת בלעדיהן) — פגם נפרד, שמדווח ב-PR ואינו נבדק כאן.
NOTE_EDIT_HANDLERS = [
    pytest.param("conversation_handlers", ("code", "programming_language", "tags"), id="the-handler-that-runs"),
    pytest.param("handlers.file_view", ("code", "programming_language"), id="the-file-view-twin"),
]


@pytest.mark.parametrize("module_name, copied_fields", NOTE_EDIT_HANDLERS)
async def test_editing_a_note_writes_the_code_the_database_holds_now(world, module_name, copied_fields):
    handlers = importlib.import_module(module_name)
    world.file_with_a_stale_cache(NOTE_FILE)

    message = _Message("הערה חדשה")
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=USER_ID))
    context = SimpleNamespace(user_data={"editing_note_file": NOTE_FILE})
    await handlers.receive_new_code(update, context)

    assert message.replies and message.replies[-1].startswith("✅"), message.replies
    written = world.latest(NOTE_FILE)
    assert written["version"] == 3, written
    assert written["description"] == "הערה חדשה"
    for field in copied_fields:
        assert written[field] == NEW[field], f"{field} נכתב מהקאש: {written[field]!r}"


#: שלוש הכניסות לשכפול. רשומה ברשימה שמחזיקה את כל השדות, ורשומה בלי ``code`` — כמו שהרשימות נבנות
#: בהיטלה בלי השדות הכבדים — ושכפול לפי שם, בלי הרשימה.
CLONE_ENTRIES = [
    pytest.param("clone_0", {"file_name": NOTE_FILE, **OLD}, id="from-a-list-entry-with-the-content"),
    pytest.param(
        "clone_0", {"file_name": NOTE_FILE, **{k: v for k, v in OLD.items() if k != "code"}},
        id="from-a-list-entry-without-the-code",
    ),
    pytest.param(f"clone_direct_{NOTE_FILE}", None, id="by-name"),
]


@pytest.mark.parametrize("callback_data, list_entry", CLONE_ENTRIES)
async def test_a_clone_copies_what_the_database_holds_now(world, callback_data, list_entry):
    from handlers import file_view

    world.file_with_a_stale_cache(NOTE_FILE)

    query = _Query(callback_data)
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=USER_ID))
    context = SimpleNamespace(user_data={"files_cache": {"0": dict(list_entry)}} if list_entry else {})
    handler = file_view.handle_clone_direct if list_entry is None else file_view.handle_clone
    await handler(update, context)

    assert query.texts and query.texts[-1].startswith("✅"), query.texts
    clone = world.latest("notes (copy).md")
    assert clone is not None, query.texts
    for field in ("code", "programming_language", "description", "tags"):
        assert clone[field] == NEW[field], f"{field} הועתק מהקאש: {clone[field]!r}"


async def test_a_clone_of_a_file_that_is_gone_is_refused_and_not_rebuilt_from_the_list(world):
    """הרשומה ברשימה מזהה את הקובץ בלבד: קובץ שכבר אינו במסד לא נבנה מחדש ממה שהרשימה זוכרת."""
    from handlers import file_view

    query = _Query("clone_0")
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=USER_ID))
    context = SimpleNamespace(user_data={"files_cache": {"0": {"file_name": NOTE_FILE, **OLD}}})
    await file_view.handle_clone(update, context)

    assert query.texts and query.texts[-1].startswith("❌"), query.texts
    assert world.latest("notes (copy).md") is None


class _CachedOnlyManager:
    """מנהל מסד שיש לו רק את הגטרים המקוּשים — כמו דמות בדיקה ישנה."""

    def __init__(self):
        self.cached_calls = []

    def get_latest_version(self, user_id, file_name):
        self.cached_calls.append(("get_latest_version", file_name))
        return {"file_name": file_name, "code": "מהקאש"}

    def get_user_files(self, user_id, limit=50, **_kwargs):
        self.cached_calls.append(("get_user_files", limit))
        return [{"file_name": "מהקאש"}]


class _FreshManager(_CachedOnlyManager):
    def get_latest_version_fresh(self, user_id, file_name):
        return {"file_name": file_name, "code": "מהמסד"}

    def get_user_files_fresh(self, user_id, limit=50, **_kwargs):
        return [{"file_name": "מהמסד"}]


def test_the_fresh_doors_read_fresh_and_never_fall_back_to_the_cached_getter(monkeypatch):
    """דלת טרייה שנופלת לגטר המקוּש כשאין לה מה לקרוא הופכת למקוּשה בלי שאיש יראה.

    ``silent-fallback-to-worse-path`` ב-amir-bug-patterns: מנהל בלי הדלת נופל בקול, ולא עובר בשקט לקאש.
    """
    import database
    from mcp_server.backend import _latest_fresh
    from src.infrastructure.composition.files_facade import FilesFacade

    fresh = _FreshManager()
    monkeypatch.setattr(database, "db", fresh)
    facade = FilesFacade()
    assert facade.get_latest_version_fresh(USER_ID, NOTE_FILE)["code"] == "מהמסד"
    assert facade.get_user_files_fresh(USER_ID, limit=10) == [{"file_name": "מהמסד"}]
    assert _latest_fresh(fresh, USER_ID, NOTE_FILE)["code"] == "מהמסד"
    assert fresh.cached_calls == []

    cached_only = _CachedOnlyManager()
    monkeypatch.setattr(database, "db", cached_only)
    with pytest.raises(AttributeError):
        facade.get_latest_version_fresh(USER_ID, NOTE_FILE)
    with pytest.raises(AttributeError):
        facade.get_user_files_fresh(USER_ID, limit=10)
    with pytest.raises(AttributeError):
        _latest_fresh(cached_only, USER_ID, NOTE_FILE)
    assert cached_only.cached_calls == []
