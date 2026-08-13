"""חסימת משתמשים מהבוט.

הבדיקות כאן נכתבו לפי הכלל של ``amir-bug-patterns`` T2: **כל בדיקה
הורצה על הקוד לפני התיקון ואומתה כנופלת.** בדיקה שנכתבה אחרי התיקון
ולא הורצה לפניו אינה ראיה שהיא מכסה משהו.

שתי משפחות:

* בדיקות יחידה על ``blocked_users_manager`` — בלי DB, עם קולקציה מזויפת.
* בדיקות של **השער עצמו** ב-``main``, כי שם ההחלטה נאכפת. בדיקה של
  ``is_blocked`` לבדה לא הייתה תופסת שער שלא קורא לה.
"""

import asyncio
import types

import pytest
from telegram.ext._application import ApplicationHandlerStop

from database import blocked_users_manager as bum


# ── כלים ──────────────────────────────────────────────────────────────


class _FakeUser:
    def __init__(self, uid):
        self.id = uid


class _FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class _FakeCallbackQuery:
    def __init__(self):
        self.answered = []

    async def answer(self, text=None, show_alert=False, cache_time=None):
        self.answered.append((text, show_alert, cache_time))


class _FakeCollection:
    """קולקציה בזיכרון, מספיק כדי לבדוק את החוזה מול pymongo."""

    def __init__(self, docs=None, fail=False):
        self.docs = list(docs or [])
        self.fail = fail
        self.indexes = []

    def create_index(self, key, **kwargs):
        self.indexes.append((key, kwargs))

    def find(self, query=None, projection=None):
        if self.fail:
            raise RuntimeError("DB למטה")
        return _FakeCursor(list(self.docs))

    def update_one(self, filt, update, upsert=False):
        if self.fail:
            raise RuntimeError("DB למטה")
        uid = filt["user_id"]
        for doc in self.docs:
            if doc["user_id"] == uid:
                doc.update(update.get("$set", {}))
                return types.SimpleNamespace(upserted_id=None)
        doc = dict(update.get("$setOnInsert", {}))
        doc.update(update.get("$set", {}))
        self.docs.append(doc)
        return types.SimpleNamespace(upserted_id=uid)

    def delete_one(self, filt):
        if self.fail:
            raise RuntimeError("DB למטה")
        before = len(self.docs)
        self.docs = [d for d in self.docs if d["user_id"] != filt["user_id"]]
        return types.SimpleNamespace(deleted_count=before - len(self.docs))


class _FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def __iter__(self):
        return iter(self.docs)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """קאש נקי וסביבה נקייה לכל בדיקה.

    בלי זה הקאש דולף בין בדיקות, וזה בדיוק סוג הכשל הלא-דטרמיניסטי
    ש-``TESTING-PATTERNS.md`` T3 מתעד.
    """
    monkeypatch.delenv("BLOCKED_USER_IDS", raising=False)
    monkeypatch.delenv("ADMIN_USER_IDS", raising=False)
    bum.invalidate_cache()
    yield
    bum.invalidate_cache()


def _use(monkeypatch, collection):
    monkeypatch.setattr(bum, "_collection", lambda: collection)


# ── שכבת ה-ENV ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_env_list_blocks_without_touching_the_database(monkeypatch):
    """רשת הביטחון עובדת גם כשאין DB בכלל."""
    monkeypatch.setenv("BLOCKED_USER_IDS", "111,222")
    _use(monkeypatch, None)

    assert await bum.is_blocked(111) is True
    assert await bum.is_blocked(222) is True
    assert await bum.is_blocked(333) is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,2,3", {1, 2, 3}),
        (" 1 , 2 ", {1, 2}),
        ("1,,2", {1, 2}),
        ("1,abc,2", {1, 2}),
        ("-5,7", {7}),
        ("", set()),
        (None, set()),
    ],
    ids=["רגיל", "רווחים", "פסיק-כפול", "ערך-לא-מספרי", "שלילי", "ריק", "חסר"],
)
def test_the_env_list_survives_sloppy_values(raw, expected, monkeypatch):
    """משתנה סביבה עם פסיק מיותר אינו סיבה לפתוח או לחסום את כולם."""
    if raw is None:
        monkeypatch.delenv("BLOCKED_USER_IDS", raising=False)
    else:
        monkeypatch.setenv("BLOCKED_USER_IDS", raw)
    assert bum.env_blocked_ids() == frozenset(expected)


# ── אדמין ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_admin_is_never_blocked_even_when_listed(monkeypatch):
    """הבדיקה שמונעת נעילה עצמית.

    אם אדמין ייחסם, אין מי שישחרר אותו — ``/unban`` עצמה זמינה
    לאדמינים בלבד. זה חייב להיות בלתי אפשרי, לא רק לא סביר.
    """
    monkeypatch.setenv("ADMIN_USER_IDS", "999")
    monkeypatch.setenv("BLOCKED_USER_IDS", "999")
    _use(monkeypatch, _FakeCollection([{"user_id": 999}]))

    assert await bum.is_blocked(999) is False


# ── שכבת ה-DB והקאש ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_database_list_blocks(monkeypatch):
    _use(monkeypatch, _FakeCollection([{"user_id": 42, "reason": "ספאם"}]))
    assert await bum.is_blocked(42) is True
    assert await bum.is_blocked(43) is False


@pytest.mark.asyncio
async def test_a_database_failure_does_not_block_anyone(monkeypatch):
    """fail-open, כמו במגביל הקצב.

    לנעול את כל המשתמשים בכל תקלת DB גרוע בהרבה מלתת לספאמר בודד
    לעבור בזמן תקלה.
    """
    _use(monkeypatch, _FakeCollection(fail=True))
    assert await bum.is_blocked(42) is False


@pytest.mark.asyncio
async def test_a_failure_is_not_cached(monkeypatch):
    """כשל אינו נכנס לקאש, אחרת DB שחזר לא ייבדק במשך דקה."""
    collection = _FakeCollection([{"user_id": 42}], fail=True)
    _use(monkeypatch, collection)
    assert await bum.is_blocked(42) is False

    collection.fail = False
    assert await bum.is_blocked(42) is True, "הכשל נשמר בקאש וחסם בדיקה מחודשת"


@pytest.mark.asyncio
async def test_an_unavailable_database_is_not_cached_either(monkeypatch):
    """מסלול הכשל השני: ``_collection()`` שמחזיר ``None``.

    זה קורה בעלייה, לפני שהחיבור נוצר. הבדיקה הקודמת כיסתה רק חריגה,
    ולכן היא עברה בזמן שהמסלול הזה **כן** נשמר בקאש — "אין DB" נראה
    בדיוק כמו "אין חסומים". התוצאה: DB שלא הספיק לעלות היה מבטל את
    כל החסימות עד לפקיעת הקאש.

    נמצא בסקירה של Sourcery ב-#3222.
    """
    collection = _FakeCollection([{"user_id": 42}])
    state = {"ready": False}
    monkeypatch.setattr(bum, "_collection", lambda: collection if state["ready"] else None)

    assert await bum.is_blocked(42) is False  # אין DB — fail-open

    state["ready"] = True
    assert await bum.is_blocked(42) is True, "היעדר ה-DB נשמר בקאש וחסם בדיקה מחודשת"


@pytest.mark.asyncio
async def test_the_cache_spares_the_database_on_every_message(monkeypatch):
    """הקאש אינו אופטימיזציה: pymongo סינכרוני, וכל שאילתה חוסמת את הלולאה."""
    calls = {"n": 0}

    class _Counting(_FakeCollection):
        def find(self, *a, **k):
            calls["n"] += 1
            return super().find(*a, **k)

    _use(monkeypatch, _Counting([{"user_id": 42}]))
    for _ in range(20):
        await bum.is_blocked(42)
    assert calls["n"] == 1, f"נעשו {calls['n']} שאילתות במקום אחת"


@pytest.mark.asyncio
async def test_an_invalidate_during_a_load_wins(monkeypatch):
    """מרוץ: ``/ban`` מאפס את הקאש בזמן שטעינה כבר רצה.

    בלי מונה גרסה, הכתיבה המאוחרת הייתה מחזירה לקאש את הקבוצה שנקראה
    **לפני** החסימה — והחסימה החדשה לא הייתה תופסת עד לפקיעת ה-TTL,
    בדיוק ההפך ממה ש-``block_user`` מבטיח.

    נמצא בסקירה של CodeRabbit ב-#3222.
    """
    started = asyncio.Event()
    release = asyncio.Event()
    collection = _FakeCollection()  # ריק בזמן הטעינה

    def _slow_load():
        # מדמה טעינה איטית: הצילום נלקח כאן, ה-invalidate יקרה אחריו
        return frozenset()

    async def _load_with_pause():
        started.set()
        await release.wait()
        return _slow_load()

    _use(monkeypatch, collection)
    monkeypatch.setattr(bum.asyncio, "to_thread", lambda fn: _load_with_pause())

    task = asyncio.create_task(bum.blocked_ids())
    await started.wait()

    # החסימה קורית בזמן שהטעינה תקועה
    collection.docs.append({"user_id": 42})
    bum._cache.invalidate()

    release.set()
    await task

    # הטעינה המיושנת לא נכתבה, ולכן הבדיקה הבאה פונה שוב ל-DB
    monkeypatch.undo()
    _use(monkeypatch, collection)
    assert await bum.is_blocked(42) is True, "הקבוצה המיושנת נכתבה לקאש אחרי invalidate"


@pytest.mark.asyncio
async def test_concurrent_cache_misses_query_the_database_once(monkeypatch):
    """עשרים הודעות ברגע שהקאש פג פותחות טעינה אחת, לא עשרים."""
    calls = {"n": 0}

    class _Counting(_FakeCollection):
        def find(self, *a, **k):
            calls["n"] += 1
            return super().find(*a, **k)

    _use(monkeypatch, _Counting([{"user_id": 42}]))
    results = await asyncio.gather(*(bum.is_blocked(42) for _ in range(20)))

    assert all(results)
    assert calls["n"] == 1, f"נעשו {calls['n']} שאילתות מקבילות במקום אחת"


@pytest.mark.asyncio
async def test_a_ban_takes_effect_immediately(monkeypatch):
    """בלי איפוס הקאש החסימה הייתה נכנסת לתוקף רק אחרי דקה.

    המפעיל שלוחץ /ban ורואה שהמשתמש עדיין עובר מסיק שהפקודה נכשלה.
    """
    collection = _FakeCollection()
    _use(monkeypatch, collection)
    assert await bum.is_blocked(42) is False  # מחמם את הקאש

    assert bum.block_user(42, reason="ספאם", blocked_by=1) is True
    assert await bum.is_blocked(42) is True, "הקאש לא אופס אחרי חסימה"


@pytest.mark.asyncio
async def test_an_unban_takes_effect_immediately(monkeypatch):
    collection = _FakeCollection([{"user_id": 42}])
    _use(monkeypatch, collection)
    assert await bum.is_blocked(42) is True

    assert bum.unblock_user(42) is True
    assert await bum.is_blocked(42) is False


def test_banning_twice_keeps_one_row(monkeypatch):
    """ייחודיות נאכפת ב-DB, ולכן אין כאן check-then-act."""
    collection = _FakeCollection()
    _use(monkeypatch, collection)

    bum.block_user(42, reason="ראשונה")
    bum.block_user(42, reason="שנייה")

    assert len(collection.docs) == 1
    assert collection.docs[0]["reason"] == "שנייה"


def test_the_original_block_date_is_kept_on_reban(monkeypatch):
    """``$setOnInsert`` ולא ``$set`` — התאריך המקורי אינו נדרס."""
    collection = _FakeCollection()
    _use(monkeypatch, collection)

    bum.block_user(42, reason="ראשונה")
    first = collection.docs[0]["blocked_at"]
    bum.block_user(42, reason="שנייה")

    assert collection.docs[0]["blocked_at"] == first


def test_the_unique_index_is_declared(monkeypatch):
    collection = _FakeCollection()
    _use(monkeypatch, collection)
    bum.ensure_indexes()
    assert ("user_id", {"unique": True, "name": "blocked_user_id_unique"}) in collection.indexes


def test_write_operations_report_failure_instead_of_pretending(monkeypatch):
    """``/ban`` שנכשל חייב לומר זאת, אחרת המפעיל חושב שהמשתמש חסום."""
    _use(monkeypatch, _FakeCollection(fail=True))
    assert bum.block_user(42) is False
    assert bum.unblock_user(42) is False

    _use(monkeypatch, None)
    assert bum.block_user(42) is False
    assert bum.unblock_user(42) is False


# ── השער עצמו ─────────────────────────────────────────────────────────
#
# כאן ההחלטה נאכפת בפועל. בדיקה של is_blocked לבדה עוברת גם כששכחנו
# לחבר אותה לשער — וזו בדיוק הווריאציה של T1 שמייצרת ביטחון שווא.


def _build_bot(monkeypatch, tmp_path):
    """בונה בוט מינימלי עם ה-handlers בלבד.

    ``DISABLE_ACTIVITY_REPORTER`` הכרחי: בלעדיו ``CodeKeeperBot.__init__``
    מעביר את ``MONGODB_URL`` ל-``create_reporter`` ומנסה חיבור אמיתי.
    ב-CI בלי Mongo מקומי זו המתנה לטיימאאוט בכל בדיקה.

    ה-persistence נכתב ל-``/tmp/bot_data.pickle`` — נתיב **קבוע** שמשותף
    לכל הבדיקות. בהרצה מקבילית שתי בדיקות היו כותבות לאותו קובץ. ``HOME``
    ו-``TMPDIR`` מופנים ל-``tmp_path`` הייחודי של pytest, לפי הכלל
    ב-CLAUDE.md על הפרדת תיקיות עבודה.
    """
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_ACTIVITY_REPORTER", "1")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    import main as mod

    class _MiniApp:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}

        def add_handler(self, handler, group=None):
            self.handlers.append((handler, group))

        def add_error_handler(self, handler, group=None):
            pass

    class _Builder:
        def token(self, *a, **k):
            return self

        def defaults(self, *a, **k):
            return self

        def persistence(self, *a, **k):
            return self

        def post_init(self, *a, **k):
            return self

        def build(self):
            return _MiniApp()

    class _AppNS:
        def builder(self):
            return _Builder()

    monkeypatch.setattr(mod, "Application", _AppNS())
    bot = mod.CodeKeeperBot()
    gate = next((h for h, g in bot.application.handlers if g == -90), None)
    assert gate is not None, "שער הכניסה אינו רשום"
    return bot, gate


@pytest.mark.asyncio
async def test_the_gate_stops_a_blocked_user_message(monkeypatch, tmp_path):
    monkeypatch.setenv("BLOCKED_USER_IDS", "77")
    _, gate = _build_bot(monkeypatch, tmp_path)

    update = types.SimpleNamespace(
        effective_user=_FakeUser(77), message=_FakeMessage(), callback_query=None
    )
    with pytest.raises(ApplicationHandlerStop):
        await gate.callback(update, types.SimpleNamespace())

    # חסימה שקטה: הודעה מזמינה ויכוח ומאשרת לספאמר שהוא זוהה.
    assert update.message.replies == []


@pytest.mark.asyncio
async def test_the_gate_stops_a_blocked_user_callback(monkeypatch, tmp_path):
    """הודעות ולחיצות הן שני handlers נפרדים.

    בדיקה של אחד מהם בלבד הייתה משאירה חצי דלת פתוחה — משתמש חסום
    יכול להמשיך ללחוץ על כפתורים בתפריט שכבר פתוח אצלו.
    """
    monkeypatch.setenv("BLOCKED_USER_IDS", "77")
    bot, _ = _build_bot(monkeypatch, tmp_path)

    handlers = [h for h, g in bot.application.handlers if g == -90]
    assert len(handlers) == 2, "צפויים שני handlers בשער: הודעות ולחיצות"

    query = _FakeCallbackQuery()
    query.from_user = _FakeUser(77)
    update = types.SimpleNamespace(effective_user=None, message=None, callback_query=query)

    for handler in handlers:
        with pytest.raises(ApplicationHandlerStop):
            await handler.callback(update, types.SimpleNamespace())
    assert query.answered == []


@pytest.mark.asyncio
async def test_the_gate_lets_a_normal_user_through(monkeypatch, tmp_path):
    monkeypatch.setenv("BLOCKED_USER_IDS", "77")
    _, gate = _build_bot(monkeypatch, tmp_path)

    update = types.SimpleNamespace(
        effective_user=_FakeUser(78), message=_FakeMessage(), callback_query=None
    )
    await gate.callback(update, types.SimpleNamespace())  # לא אמור לזרוק


@pytest.mark.asyncio
async def test_the_gate_lets_an_admin_through_even_when_listed(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_USER_IDS", "77")
    monkeypatch.setenv("BLOCKED_USER_IDS", "77")
    _, gate = _build_bot(monkeypatch, tmp_path)

    update = types.SimpleNamespace(
        effective_user=_FakeUser(77), message=_FakeMessage(), callback_query=None
    )
    await gate.callback(update, types.SimpleNamespace())


@pytest.mark.asyncio
async def test_a_broken_block_check_does_not_lock_the_bot(monkeypatch, tmp_path):
    """fail-open גם כשהבדיקה עצמה מתפוצצת.

    באג בקוד החסימה אינו סיבה שאף אחד לא יוכל להשתמש בבוט.
    """
    import database.blocked_users_manager as mod

    async def _explode(_uid):
        raise RuntimeError("בום")

    monkeypatch.setattr(mod, "is_blocked", _explode)
    _, gate = _build_bot(monkeypatch, tmp_path)

    update = types.SimpleNamespace(
        effective_user=_FakeUser(78), message=_FakeMessage(), callback_query=None
    )
    await gate.callback(update, types.SimpleNamespace())


# ── הפקודות ───────────────────────────────────────────────────────────


def _cmd_update(uid):
    return types.SimpleNamespace(
        effective_user=_FakeUser(uid),
        message=_FakeMessage(),
        effective_message=None,
    )


@pytest.mark.asyncio
async def test_ban_commands_reject_non_admins(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    import main as mod

    for command in (mod.ban_command, mod.unban_command, mod.blocked_command):
        update = _cmd_update(2)
        await command(update, types.SimpleNamespace(args=["42"]))
        assert "מנהלים בלבד" in update.message.replies[-1]


@pytest.mark.asyncio
async def test_ban_refuses_a_username(monkeypatch):
    """``@username`` אינו נתמך: תרגום שגוי היה חוסם את המשתמש הלא נכון."""
    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    import main as mod

    update = _cmd_update(1)
    await mod.ban_command(update, types.SimpleNamespace(args=["@spammer"]))
    assert "מזהה מספרי" in update.message.replies[-1]


@pytest.mark.asyncio
async def test_ban_refuses_to_block_an_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "1,2")
    import main as mod

    update = _cmd_update(1)
    await mod.ban_command(update, types.SimpleNamespace(args=["2"]))
    assert "אי אפשר לחסום אדמין" in update.message.replies[-1]


@pytest.mark.asyncio
async def test_unban_explains_that_env_entries_cannot_be_released(monkeypatch):
    """כישלון שקט כאן היה נראה כמו באג, והמפעיל היה מנסה שוב ושוב."""
    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    monkeypatch.setenv("BLOCKED_USER_IDS", "42")
    _use(monkeypatch, _FakeCollection())
    import main as mod

    update = _cmd_update(1)
    await mod.unban_command(update, types.SimpleNamespace(args=["42"]))
    reply = update.message.replies[-1]
    assert "BLOCKED_USER_IDS" in reply and "Render" in reply


@pytest.mark.asyncio
async def test_ban_reports_a_database_failure(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    _use(monkeypatch, _FakeCollection(fail=True))
    import main as mod

    update = _cmd_update(1)
    await mod.ban_command(update, types.SimpleNamespace(args=["42", "ספאם"]))
    assert "נכשלה" in update.message.replies[-1]


@pytest.mark.asyncio
async def test_blocked_lists_both_sources(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    monkeypatch.setenv("BLOCKED_USER_IDS", "11")
    _use(monkeypatch, _FakeCollection([{"user_id": 22, "reason": "ספאם"}]))
    import main as mod

    update = _cmd_update(1)
    await mod.blocked_command(update, types.SimpleNamespace(args=[]))
    reply = update.message.replies[-1]
    assert "11" in reply and "22" in reply and "ספאם" in reply
