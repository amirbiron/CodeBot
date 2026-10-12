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


def _is_the_latest_version_query(query):
    """המסנן של ``Repository._fetch_latest_version``, ורק הוא.

    שאילתת המספור (``_max_version_any_state``) אינה מסננת לפי ``is_active``, ושאילתת המועדף
    מוסיפה ``is_favorite`` — ולכן הן עונות כרגיל גם כשהקריאה של קובץ "נכשלת". כך הבדיקה רואה מה
    המסלול עושה עם קריאה אחת שנכשלה, ולא מסד שנפל כולו.
    """
    return isinstance(query, dict) and set(query) == {"user_id", "file_name", "is_active"} and query["is_active"] is True


class _CollectionWithoutDocs:
    """``FakeCollection`` בלי ``docs``, כדי ש-``Repository`` ישאל את האוסף כמו בייצור.

    ``fail_latest_for`` (שמות קבצים) ו-``fail_listing`` מפילים את השאילתה של ``_fetch_latest_version``
    לקובץ ואת השאילתה של ``_fetch_user_files``, בשגיאה שמונגו זורק כשלא ענה. ``listing_error`` זורק
    מהרשימה חריגה אחרת, שאינה של המסד — כמו באג.
    """

    def __init__(self):
        from _fake_mongo import FakeCollection

        self._inner = FakeCollection()
        self.fail_latest_for = set()
        self.fail_listing = False
        self.listing_error = None

    def __getattr__(self, name):
        if name == "docs":
            raise AttributeError(name)
        return getattr(self._inner, name)

    def find_one(self, q=None, *args, **kwargs):
        if _is_the_latest_version_query(q) and q["file_name"] in self.fail_latest_for:
            raise _db_did_not_answer()
        return self._inner.find_one(q, *args, **kwargs)

    def aggregate(self, pipeline, *args, **kwargs):
        if self.fail_listing:
            raise _db_did_not_answer()
        if self.listing_error is not None:
            raise self.listing_error
        return _answer_the_listing(self._inner, pipeline)

    def distinct(self, key, q=None, *args, **kwargs):
        # ``FakeCollection`` אינו מממש ``distinct``, והמחיקה הרכה (``file_deletion.soft_delete_files_by_names``)
        # שואלת דרכו אילו מהשמות עדיין פעילים. בלעדיו כל מחיקה "נכשלת" בדמה.
        values = []
        for doc in self._inner.find(q or {}):
            if doc.get(key) not in values:
                values.append(doc.get(key))
        return values


def _answer_the_listing(collection, pipeline):
    """התשובה לצינור של ``Repository._fetch_user_files``, ורק לו: הגרסה הפעילה האחרונה של כל קובץ, מהחדש לישן.

    ``FakeCollection`` אינו מריץ ``aggregate``. צינור בצורה אחרת זורק ``NotImplementedError``, כמו אופרטור
    שהדמה אינה מכירה — כדי ששינוי בצינור יפיל את הטסט, ולא יקבל תשובה לשאלה שלא נשאלה.
    """
    shape = [next(iter(stage)) for stage in pipeline]
    if shape[:5] != ["$match", "$sort", "$group", "$replaceRoot", "$sort"] or not set(shape[5:]) <= {"$project", "$skip", "$limit"}:
        raise NotImplementedError(f"aggregate pipeline {shape}")
    latest = {}
    for doc in collection.find(pipeline[0]["$match"]):
        name = doc["file_name"]
        if name not in latest or doc.get("version", 0) > latest[name].get("version", 0):
            latest[name] = doc
    rows = sorted(latest.values(), key=lambda doc: doc["updated_at"], reverse=True)
    for stage in pipeline[5:]:
        ((op, arg),) = stage.items()
        if op == "$project":
            rows = collection._project(rows, arg)
        elif op == "$skip":
            rows = rows[arg:]
        else:
            rows = rows[:arg]
    return rows


def _db_did_not_answer():
    # ``ServerSelectionTimeoutError`` יורש מ-``PyMongoError`` (‏``AutoReconnect`` ← ``ConnectionFailure``),
    # נבדק ב-``__mro__`` של pymongo 4.15.3 — הבסיס שהקוד תופס.
    from pymongo.errors import ServerSelectionTimeoutError

    return ServerSelectionTimeoutError("the database did not answer")


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
    def __init__(self):
        super().__init__()
        self.fresh_calls = []

    def get_latest_version_fresh(self, user_id, file_name, *, raise_on_error=False):
        self.fresh_calls.append(("get_latest_version_fresh", raise_on_error))
        return {"file_name": file_name, "code": "מהמסד"}

    def get_user_files_fresh(self, user_id, limit=50, *, raise_on_error=False, **_kwargs):
        self.fresh_calls.append(("get_user_files_fresh", raise_on_error))
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
    # ה-facade של הבוט מבקש שקריאה שנכשלה תזרוק; ה-MCP עדיין קורא בברירת המחדל.
    assert fresh.fresh_calls == [
        ("get_latest_version_fresh", True),
        ("get_user_files_fresh", True),
        ("get_latest_version_fresh", False),
    ]

    cached_only = _CachedOnlyManager()
    monkeypatch.setattr(database, "db", cached_only)
    with pytest.raises(AttributeError):
        facade.get_latest_version_fresh(USER_ID, NOTE_FILE)
    with pytest.raises(AttributeError):
        facade.get_user_files_fresh(USER_ID, limit=10)
    with pytest.raises(AttributeError):
        _latest_fresh(cached_only, USER_ID, NOTE_FILE)
    assert cached_only.cached_calls == []


# ---------------------------------------------------------------------------
# קריאה שנכשלה אינה "אין". ``_fetch_latest_version`` ו-``_fetch_user_files`` מחזירות כברירת מחדל
# ``None`` / ``[]`` גם כשהמסד נכשל — אותו ערך כמו "אין קובץ" ו"אין קבצים". מסלול שכותב לפי התשובה
# היה ממשיך כאילו השם פנוי או שאין מה למחוק. ה-facade של הבוט מבקש ``raise_on_error=True``, וכל
# מסלול מטפל בכשל במפורש.
# ---------------------------------------------------------------------------


def test_the_fresh_doors_raise_when_the_read_fails_and_the_display_getters_do_not(world, monkeypatch):
    from pymongo.errors import PyMongoError

    import database
    import database.repository as repository
    from mcp_server.backend import _latest_fresh
    from src.infrastructure.composition import get_files_facade

    recorded = []
    monkeypatch.setattr(repository, "emit_event", lambda event, **fields: recorded.append(event))
    world.write_version(NOTE_FILE, 1, OLD)
    world.collection.fail_latest_for.add(NOTE_FILE)
    world.collection.fail_listing = True
    facade = get_files_facade()

    with pytest.raises(PyMongoError):
        facade.get_latest_version_fresh(USER_ID, NOTE_FILE)
    assert recorded == ["db_get_latest_version_error"], "הכשל צריך להירשם פעם אחת, גם כשהוא נזרק הלאה"
    with pytest.raises(PyMongoError):
        facade.get_user_files_fresh(USER_ID, limit=10)

    # התצוגה וה-MCP נשארים בברירת המחדל: הערך הוותיק, ובלי חריגה.
    assert facade.get_latest_version(USER_ID, NOTE_FILE) is None
    assert facade.get_user_files(USER_ID, limit=10) == []
    assert _latest_fresh(database.db, USER_ID, NOTE_FILE) is None


@pytest.mark.parametrize("module_name", [
    pytest.param("conversation_handlers", id="the-handler-that-runs"),
    pytest.param("handlers.file_view", id="the-file-view-twin"),
])
async def test_a_note_edit_whose_read_fails_answers_an_error_and_writes_nothing(world, module_name):
    handlers = importlib.import_module(module_name)
    world.write_version(NOTE_FILE, 1, OLD)
    world.collection.fail_latest_for.add(NOTE_FILE)

    message = _Message("הערה חדשה")
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=USER_ID))
    context = SimpleNamespace(user_data={"editing_note_file": NOTE_FILE})
    await handlers.receive_new_code(update, context)

    assert message.replies == ["❌ שגיאה בעדכון ההערה"], message.replies
    world.collection.fail_latest_for.clear()
    assert world.latest(NOTE_FILE)["version"] == 1


async def test_the_note_handler_that_runs_reports_a_manager_without_the_fresh_door_as_an_error(monkeypatch):
    """``_call_files_api`` מחזיר ``None`` על כל חריגה, ו-``None`` נקרא כאן "הקובץ לא נמצא". מנהל בלי
    הדלת הטרייה הוא תקלה, לא קובץ שנמחק."""
    import conversation_handlers
    import database

    cached_only = _CachedOnlyManager()
    monkeypatch.setattr(database, "db", cached_only)

    message = _Message("הערה חדשה")
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=USER_ID))
    context = SimpleNamespace(user_data={"editing_note_file": NOTE_FILE})
    await conversation_handlers.receive_new_code(update, context)

    assert message.replies == ["❌ שגיאה בעדכון ההערה"], message.replies
    assert cached_only.cached_calls == []


@pytest.mark.parametrize("failing_read", [
    pytest.param(NOTE_FILE, id="the-source"),
    pytest.param("notes (copy).md", id="the-name-check"),
])
@pytest.mark.parametrize("callback_data, list_entry", [
    pytest.param("clone_0", {"file_name": NOTE_FILE}, id="from-a-list-entry"),
    pytest.param(f"clone_direct_{NOTE_FILE}", None, id="by-name"),
])
async def test_a_clone_whose_read_fails_answers_an_error_and_writes_nothing(world, callback_data, list_entry, failing_read):
    """קריאה שנכשלה אינה "אין קובץ", וגם לא "השם פנוי".

    השכפול קורא פעמיים: את המקור, ואת השם שהעותק יקבל. מקור שלא נקרא דווח עד היום "הקובץ לא נמצא",
    ושם שלא הצלחנו לבדוק נחשב פנוי — ושמירה בשם תפוס הייתה נכתבת כגרסה חדשה של הקובץ האחר.
    """
    from handlers import file_view

    world.write_version(NOTE_FILE, 1, NEW)
    world.collection.fail_latest_for.add(failing_read)

    query = _Query(callback_data)
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=USER_ID))
    context = SimpleNamespace(user_data={"files_cache": {"0": dict(list_entry)}} if list_entry else {})
    handler = file_view.handle_clone_direct if list_entry is None else file_view.handle_clone
    await handler(update, context)

    assert query.texts and query.texts[-1] == "❌ שגיאה בשכפול הקובץ", query.texts
    world.collection.fail_latest_for.clear()
    assert world.latest("notes (copy).md") is None


def test_a_rename_whose_target_check_fails_is_refused_and_changes_nothing(world):
    from src.infrastructure.composition import get_files_facade

    world.write_version("old.py", 1, NEW)
    world.write_version("taken.py", 1, OLD)
    world.collection.fail_latest_for.add("taken.py")

    assert get_files_facade().rename_file(USER_ID, "old.py", "taken.py") is False

    world.collection.fail_latest_for.clear()
    assert world.latest("old.py")["code"] == NEW["code"]
    assert world.latest("taken.py")["code"] == OLD["code"]


def test_a_rename_to_a_free_name_still_renames(world):
    from src.infrastructure.composition import get_files_facade

    world.write_version("old.py", 1, NEW)

    assert get_files_facade().rename_file(USER_ID, "old.py", "new.py") is True
    assert world.latest("new.py")["code"] == NEW["code"]
    assert world.latest("old.py") is None


def test_a_full_restore_whose_listing_fails_does_not_start(world, tmp_path):
    """purge שלא יכול לדעת מה למחוק לא ממשיך לשחזור: התוצאה הייתה מיזוג שקט ולא החלפה."""
    import zipfile

    from file_manager import backup_manager

    world.write_version("kept.py", 1, OLD)
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("from_backup.py", "print('restored')\n")
    world.collection.fail_listing = True

    results = backup_manager.restore_from_backup(USER_ID, str(archive), overwrite=True, purge=True)

    assert results == {"restored_files": 0, "errors": ["purge listing failed"]}, results
    world.collection.fail_listing = False
    assert world.latest("from_backup.py") is None
    assert world.latest("kept.py") is not None


def test_a_full_restore_whose_listing_is_read_replaces_the_files(world, tmp_path):
    """המצב התקין: הרשימה נקראה, הקבצים הקיימים עוברים לסל, והגיבוי משוחזר במקומם."""
    import zipfile

    from file_manager import backup_manager

    world.write_version("kept.py", 1, OLD)
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("from_backup.py", "print('restored')\n")

    results = backup_manager.restore_from_backup(USER_ID, str(archive), overwrite=True, purge=True)

    assert results == {"restored_files": 1, "errors": []}, results
    assert world.latest("kept.py") is None
    assert world.latest("from_backup.py")["code"] == "print('restored')\n"


def test_a_full_restore_whose_listing_hits_a_bug_does_not_call_it_a_database_failure(world, tmp_path):
    """רק כשל של המסד נקרא "purge listing failed". באג ברשימה מגיע עם הטקסט שלו — ובכל זאת לא נמחק ולא שוחזר דבר."""
    import zipfile

    from file_manager import backup_manager

    world.write_version("kept.py", 1, OLD)
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("from_backup.py", "print('restored')\n")
    world.collection.listing_error = TypeError("a bug in the listing")

    results = backup_manager.restore_from_backup(USER_ID, str(archive), overwrite=True, purge=True)

    assert results == {"restored_files": 0, "errors": ["a bug in the listing"]}, results
    world.collection.listing_error = None
    assert world.latest("from_backup.py") is None
    assert world.latest("kept.py") is not None


async def _import_a_repo_zip(monkeypatch, tmp_path, files):
    """מריץ את ``import_repo_from_zip`` על ZIP שמכיל ``files``, ומחזיר את ההודעות שנשלחו.

    הרתמה היא של ``tests/test_github_import_repo_zip_limit.py``. ``tempfile.tempdir`` מופנה ל-``tmp_path``,
    כדי שהחילוץ והניקוי של ה-handler ירוצו שם.
    """
    import io
    import tempfile
    import zipfile

    import github_menu_handler as gh

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    handler = gh.GitHubMenuHandler()
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    class _Repo:
        def get_archive_link(self, *_a, **_k):
            return "https://example.com/archive.zip"

    class _Github:
        def __init__(self, *_a, **_k):
            pass

        def get_repo(self, _full):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Github)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(f"repo-123/{name}", text)
    payload = buf.getvalue()

    class _Response:
        headers = {"Content-Length": str(len(payload))}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=131072):
            for i in range(0, len(payload), chunk_size):
                yield payload[i:i + chunk_size]

    monkeypatch.setattr(gh, "http_request", lambda *_a, **_k: _Response())

    texts = []

    class _CallbackQuery:
        from_user = SimpleNamespace(id=USER_ID)

        async def edit_message_text(self, text, **_kwargs):
            texts.append(text)

        async def answer(self, *_a, **_k):
            return None

    update = SimpleNamespace(callback_query=_CallbackQuery())
    context = SimpleNamespace(user_data={}, bot_data={})
    await handler.import_repo_from_zip(update, context, "o/r", "main")
    return texts


async def test_an_import_whose_read_fails_stops_and_does_not_report_completion(world, monkeypatch, tmp_path):
    world.collection.fail_latest_for.add("a.py")

    texts = await _import_a_repo_zip(monkeypatch, tmp_path, {"a.py": "print(1)\n"})

    assert texts and texts[-1].startswith("❌ קריאה מהמסד נכשלה"), texts
    assert not any(text.startswith("✅") for text in texts), texts
    assert "did not answer" not in texts[-1], "טקסט החריגה של pymongo לא מוצג למשתמש"
    world.collection.fail_latest_for.clear()
    assert world.latest("a.py") is None


async def test_an_import_through_a_facade_without_the_fresh_door_fails_and_writes_nothing(monkeypatch, tmp_path):
    """חריגה שאינה כשל מסד — כאן דלת שחסרה — עולה, ולא נספרת כ"דילוג" בייבוא ש"הושלם"."""
    import github_menu_handler as gh

    class _FacadeWithoutTheFreshDoor:
        def __init__(self):
            self.saved = []

        def save_file(self, **kwargs):
            self.saved.append(kwargs)
            return True

    facade = _FacadeWithoutTheFreshDoor()
    monkeypatch.setattr(gh, "_get_files_facade", lambda: facade)

    texts = await _import_a_repo_zip(monkeypatch, tmp_path, {"a.py": "print(1)\n"})

    assert texts and texts[-1].startswith("❌ שגיאה בייבוא"), texts
    assert not any(text.startswith("✅") for text in texts), texts
    assert facade.saved == []
