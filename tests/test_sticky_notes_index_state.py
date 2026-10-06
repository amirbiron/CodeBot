"""מצב "האינדקסים מוכנים" של הפתקים הדביקים מתאפס בין בדיקות — וכולו.

**הבאג.** ``webapp/sticky_notes_api.py`` זוכר בגלובלים אם האינדקסים נבנו, ואחרי
בנייה שנכשלה גם מתי מותר לנסות שוב (``_INDEX_RETRY_AFTER``). בדיקות התזכורות
ב-``tests/test_sticky_note_reminders.py`` מריצות את הבנייה מול stub שאינו מאמת
את אינדקס השם, ולכן משאירות את חלון ההמתנה פתוח. ``indexed_db`` ב-
``tests/test_note_boards_mongo.py`` איפס בעצמו את השומרים שהכיר ולא את החלון,
וכשרץ אחריהן באותו תהליך בתוך ``_INDEX_RETRY_SECONDS``, ``_ensure_indexes`` יצא
מוקדם — ובדיקות האינדקסים שם נפלו על מסד בלי אינדקסים.

**התיקון** הוא רשימה אחת ליד המצב, ``reset_index_state_for_tests``, ופיקסצ'ר
אוטומטי ב-``conftest.py`` שבשורש שקורא לה לפני כל בדיקה ואחריה. הקובץ הזה
מקבע את שני החלקים, ואת מה שהאיפוס מבטיח:

- **הפונקציה מאפסת את כל מה שהבוטסטראפ כותב.** רשימת הגלובלים נגזרת כאן מקוד
  המקור — כל שם שמוצהר ``global`` בבוטסטראפ ובפונקציות שהוא קורא להן — ולא
  מרשימה מוקלדת. כך שומר חדש שנוסף לבוטסטראפ בלי שנוסף לאיפוס מפיל את הבדיקה,
  במקום להיסחף כמו הרשימה ב-``indexed_db``.
- **הפיקסצ'ר מחובר.** זוג בדיקות שמשחזר את הדליפה בלי מונגו: הראשונה משאירה
  את החלון פתוח בדיוק כמו בדיקות התזכורות, והשנייה — שרצה אחריה באותו תהליך —
  חייבת לבנות מאפס.
- **האיפוס הוא גבול.** מחיקת הדגל המשותף מאומתת מול הלקוח עצמו ולא דרך
  ``CacheManager``, שבולע את שגיאות Redis; ועבודה שהתחילה לפני האיפוס — חימום
  שתוזמן, בקשה שממתינה לנעילה, בנייה שנכשלת בזמן שהאיפוס ממתין — אינה בונה
  ואינה כותבת אחריו.
"""

from __future__ import annotations

import ast
import re
import threading
import time
import types
from pathlib import Path

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

import webapp.sticky_notes_api as api

_TREE = ast.parse(Path(api.__file__).read_text(encoding="utf-8"))
_TOP_LEVEL_FUNCTIONS = {node.name: node for node in _TREE.body if isinstance(node, ast.FunctionDef)}

#: שתי נקודות הכניסה של הבוטסטראפ: הבקשה הראשונה, וחימום העלייה.
_ENTRY_POINTS = ("_ensure_indexes", "kickoff_index_warmup")


def _globals_the_bootstrap_writes() -> set[str]:
    """כל שם שמוצהר ``global`` בנקודות הכניסה ובכל פונקציה במודול שהן קוראות לה, לעומק."""
    pending, seen, names = list(_ENTRY_POINTS), set(), set()
    while pending:
        name = pending.pop()
        if name in seen or name not in _TOP_LEVEL_FUNCTIONS:
            continue
        seen.add(name)
        for node in ast.walk(_TOP_LEVEL_FUNCTIONS[name]):
            if isinstance(node, ast.Global):
                names.update(node.names)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                pending.append(node.func.id)
    return names


def _import_time_value(name: str):
    """הערך שהגלובל מקבל כשהמודול נטען — מההשמה שלו ברמה העליונה של הקובץ."""
    for node in _TREE.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"ל-{name} אין השמה ברמה העליונה של {api.__file__}")


class _DictCache:
    """קאש מדומה עם החלק של ``CacheManager`` שהמודול נוגע בו: ``is_enabled``, ``get``, ``set``, ``delete``."""

    is_enabled = True

    def __init__(self, *, deletes: bool = True):
        self.store: dict = {}
        self._deletes = deletes

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, expire_seconds=300):
        self.store[key] = value
        return True

    def delete(self, key):
        if not self._deletes:
            return False
        return self.store.pop(key, None) is not None


class _RecordingDB:
    """מסד מדומה שרושם כל בקשת אינדקס, כדי שאפשר יהיה לדעת אם הבנייה רצה או יצאה מוקדם."""

    def __init__(self):
        self.index_requests: list = []
        requests = self.index_requests

        class _Coll:
            def create_indexes(self, models):
                requests.append("create_indexes")

            def create_index(self, *args, **kwargs):
                requests.append("create_index")

            def index_information(self):
                return {}

        self.sticky_notes = _Coll()
        self.note_boards = _Coll()
        self.note_reminders = _Coll()


# ---------- הפונקציה: כל המצב, ורק מהמקום שהקורא קורא ממנו ----------


def test_the_reset_returns_every_global_the_bootstrap_writes_to_its_import_value(monkeypatch):
    """כל גלובל שהבוטסטראפ כותב חוזר לערך שלו בטעינת המודול.

    כל אחד מהם מקבל קודם ערך שאינו שום ערך התחלתי, כך שגלובל שהאיפוס שוכח
    נשאר עם הערך הזה ונתפס. נופלת אם שורה נמחקת מהאיפוס, או אם נוסף לבוטסטראפ
    גלובל שהאיפוס אינו מכיר.
    """
    written = _globals_the_bootstrap_writes()
    assert "_INDEX_RETRY_AFTER" in written, (
        f"הסריקה לא מצאה את חלון ההמתנה, ולכן אינה סורקת את הבוטסטראפ: {sorted(written)}"
    )

    for name in written:
        monkeypatch.setattr(api, name, object())
    api.reset_index_state_for_tests()

    not_reset = sorted(name for name in written if getattr(api, name) != _import_time_value(name))
    assert not not_reset, f"האיפוס לא החזיר לערך ההתחלתי את: {not_reset}"


def test_the_reset_lets_the_startup_warmup_run_again(monkeypatch):
    """``_WARMUP_TRIGGERED`` אינו גלובל שמוצב מחדש אלא אירוע שנדלק, ולכן נבדק בנפרד — לפי ההתנהגות."""
    monkeypatch.setattr(api, "_WARMUP_TRIGGERED", threading.Event())
    builds = []
    monkeypatch.setattr(api, "_ensure_indexes", lambda generation=None: builds.append("build"))

    api.kickoff_index_warmup(background=False)
    api.reset_index_state_for_tests()
    api.kickoff_index_warmup(background=False)

    assert builds == ["build", "build"], "אחרי האיפוס חימום העלייה עדיין סבור שכבר רץ"


def test_the_reset_removes_the_shared_flag_the_bootstrap_wrote(monkeypatch):
    """הדגל נכתב בכותב האמיתי, ואחרי האיפוס גם הקורא האמיתי אינו מוצא אותו."""
    shared = _DictCache()
    monkeypatch.setattr(api, "cache", shared)
    api._mark_cache_flag()
    assert shared.get(api._INDEX_READY_CACHE_KEY), "התרחיש לא כתב את הדגל, ואין כאן מה לאפס"

    api.reset_index_state_for_tests()

    assert shared.get(api._INDEX_READY_CACHE_KEY) is None
    assert api._cache_flag_ready() is False


def test_the_reset_refuses_when_the_shared_flag_survives(monkeypatch):
    """קאש שאינו מוחק — האיפוס זורק, ואינו ממשיך כאילו הצליח.

    ``delete`` מחזיר ``False`` גם כשהמפתח לא היה וגם כשהמחיקה נכשלה, ולכן רק
    קריאה חוזרת מבחינה ביניהם. נופלת אם הקריאה החוזרת תוסר מהאיפוס.
    """
    stubborn = _DictCache(deletes=False)
    monkeypatch.setattr(api, "cache", stubborn)
    api._mark_cache_flag()

    with pytest.raises(RuntimeError, match=re.escape(api._INDEX_READY_CACHE_KEY)):
        api.reset_index_state_for_tests()


class _RawRedis:
    """הלקוח שמאחורי ``CacheManager`` (``redis_client``): מילון, או לקוח שאינו עונה.

    רק שלוש הפעולות שהקוד נוגע בהן — ``setex`` (הכתיבה של ``CacheManager.set``),
    ``get`` ו-``delete`` — וכשהוא "אינו עונה" הוא זורק ``ConnectionError`` של
    redis-py, כמו לקוח אמיתי מול שרת שנפל.
    """

    def __init__(self, *, answers: bool = True):
        self.store: dict = {}
        self._answers = answers

    def _check(self):
        if not self._answers:
            raise RedisConnectionError("Redis is not answering")

    def setex(self, key, seconds, value):
        self._check()
        self.store[key] = value
        return True

    def get(self, key):
        self._check()
        return self.store.get(key)

    def delete(self, key):
        self._check()
        return 1 if self.store.pop(key, None) is not None else 0


def _cache_manager_on(raw, monkeypatch):
    """``CacheManager`` אמיתי מעל לקוח נתון — הקאש שהמודול משתמש בו בפרודקשן.

    אמיתי ולא מדומה, כי מה שנבדק הוא בדיוק ההתנהגות שלו: ``get`` ו-``delete``
    בולעים את חריגת הלקוח ומחזירים ``None``/``False``. ``connect`` מנוטרל לפני
    הבנייה, כדי שהבנאי לא ינסה להגיע ל-``REDIS_URL`` של הסביבה.
    """
    from cache_manager import CacheManager

    monkeypatch.setattr(CacheManager, "connect", lambda self: None)
    manager = CacheManager()
    manager.redis_client = raw
    manager.is_enabled = True
    return manager


def test_an_unanswered_read_is_not_proof_that_the_flag_is_gone(monkeypatch):
    """Redis שאינו עונה — האיפוס זורק, ואינו מדווח שהדגל נמחק.

    ``CacheManager.get`` מחזיר ``None`` גם כשהלקוח זרק, בדיוק כמו על מפתח שאינו
    קיים, ולכן קריאה חוזרת דרכו מאשרת "נמחק" גם כשלא קיבלה תשובה — והדגל, אם
    שרד, מתגלה רק בבדיקה הבאה. נופלת אם האיפוס יחזור לקרוא דרך ``CacheManager``
    ולא דרך הלקוח שמאחוריו.
    """
    monkeypatch.setattr(api, "cache", _cache_manager_on(_RawRedis(answers=False), monkeypatch))

    with pytest.raises(RedisConnectionError):
        api.reset_index_state_for_tests()


def test_the_reset_removes_the_flag_from_the_client_behind_the_cache_manager(monkeypatch):
    """הדגל נכתב דרך ``CacheManager.set`` האמיתי, ואחרי האיפוס הוא איננו בלקוח.

    שומר: עובר גם על הקוד שלפני התיקון, בכוונה — הוא מקבע שהקריאה דרך הלקוח
    מוחקת ולא רק בודקת.
    """
    raw = _RawRedis()
    monkeypatch.setattr(api, "cache", _cache_manager_on(raw, monkeypatch))
    api._mark_cache_flag()
    assert api._INDEX_READY_CACHE_KEY in raw.store, "התרחיש לא כתב את הדגל, ואין כאן מה לאפס"

    api.reset_index_state_for_tests()

    assert api._INDEX_READY_CACHE_KEY not in raw.store
    assert api._cache_flag_ready() is False


class _ClientWithoutGet:
    """לקוח בלי ``get``, כמו אלה שחלק מבדיקות הקאש בריפו מתקינות על ``cache_manager.cache``.

    ``delete`` רושם כל קריאה, כדי שהבדיקה תדע אם האיפוס נגע בו.
    """

    def __init__(self):
        self.deleted: list = []

    def delete(self, *keys):
        self.deleted.extend(keys)
        return 0


@pytest.mark.parametrize(
    "make_client", [lambda: None, _ClientWithoutGet], ids=["no-client", "client-without-get"]
)
def test_a_client_the_reader_cannot_read_through_is_left_alone(make_client, monkeypatch):
    """לקוח ש-``_cache_flag_ready`` אינו יכול לקרוא דרכו — האיפוס אינו זורק ואינו נוגע בו.

    ``CacheManager.get`` קורא ל-``redis_client.get``. בלי לקוח, או בלקוח בלי
    ``get``, הקריאה נכשלת תמיד והכשל נבלע לתוך ``None`` — ולכן דרכו אין דגל
    שאפשר לאמץ, ואין מה למחוק, וחריגה כאן הייתה אזעקת שווא.

    לקוח בלי ``get`` הוא הצורה שחלק מבדיקות הקאש בריפו מתקינות על
    ``cache_manager.cache`` — למשל ``tests/test_invalidate_file_related_patterns.py``.
    היום אלה עושות קודם ``importlib.reload``, ולכן הפיקסצ'ר האוטומטי שבשורש,
    שעובר דרך הקאש שהמודול של הפתקים קשר בייבוא, אינו פוגש את הלקוח שלהן; הכלל
    אינו תלוי בזה. נופלת אם האיפוס יקרא ``get`` בלי לבדוק שהוא קיים.
    """
    client = make_client()
    monkeypatch.setattr(api, "cache", _cache_manager_on(client, monkeypatch))

    api.reset_index_state_for_tests()

    assert api._cache_flag_ready() is False
    if client is not None:
        assert client.deleted == [], "האיפוס מחק מלקוח שהקורא אינו יכול לקרוא דרכו"


# ---------- עבודה שהתחילה לפני האיפוס אינה בונה ואינה כותבת אחריו ----------
#
# האיפוס מאפס מצב, אבל עבודה יכולה להיות באמצע: חימום רקע שתוזמן ועוד לא רץ,
# בקשה שעברה את המסלול המהיר ומחכה לנעילה, או בנייה שנכשלת בזמן שהאיפוס ממתין
# לנעילה. בלי הגנה היא בונה או כותבת אחרי האיפוס, מפרסמת לבדיקה הבאה, ואפילו
# פונה ל-``get_db`` שהבדיקה הבאה החליפה.


def _a_build_would_publish(monkeypatch):
    """מסד שרושם כל בקשת אינדקס, ושני אינדקסי שם ש"מאומתים" — בנייה שרצה מדליקה את ``_INDEX_READY``."""
    db = _RecordingDB()
    monkeypatch.setattr(api, "get_db", lambda: db)
    monkeypatch.setattr(api, "ensure_title_index", lambda coll: True)
    monkeypatch.setattr(api, "ensure_repo_title_index", lambda coll: True)
    return db


def test_a_warmup_scheduled_before_the_reset_neither_builds_nor_reads_the_cache_after_it(monkeypatch):
    """חימום רקע שתוזמן לפני האיפוס ומתעורר אחריו — יוצא בלי לבנות ובלי לקרוא את הקאש.

    החוט מוחזק ולא מתחיל, כדי שהבדיקה תריץ את המשימה שלו בדיוק אחרי האיפוס:
    זה מה שקורה עם ``delay_seconds`` חיובי. אחרי האיפוס מותקן קאש משותף דלוק,
    כמו שהבדיקה הבאה הייתה מתקינה. חימום ישן שקורא אותו מזיז לה את
    ``_INDEX_CACHE_LAST_CHECK``, ואז הקריאה שלה עצמה ל-``_cache_flag_ready``
    יוצאת בלי לקרוא את הדגל. נופלת בלי היציאה המוקדמת של דור קודם
    ב-``_ensure_indexes``, או בלי קידום הדור באיפוס.
    """
    held = []

    class _HeldThread:
        def __init__(self, target, name=None, daemon=None):
            self._target = target

        def start(self):
            held.append(self._target)

    db = _a_build_would_publish(monkeypatch)
    monkeypatch.setattr(api, "threading", types.SimpleNamespace(Thread=_HeldThread))

    api.kickoff_index_warmup()
    assert len(held) == 1, "החימום לא תוזמן בחוט רקע, ולכן התרחיש לא נבדק"
    api.reset_index_state_for_tests()
    monkeypatch.setattr(api, "cache", _DictCache())
    held[0]()

    assert db.index_requests == [], "חימום שתוזמן לפני האיפוס בנה אחריו"
    assert api._INDEX_READY is False
    assert api._INDEX_CACHE_LAST_CHECK == 0.0, "חימום שתוזמן לפני האיפוס קרא אחריו את הקאש המשותף"


def test_a_warmup_that_the_reset_interrupts_before_it_is_scheduled_does_not_build(monkeypatch):
    """איפוס שקורה בתוך ``kickoff_index_warmup`` עצמו, אחרי הכניסה ולפני התזמון — החימום אינו בונה.

    הדור נלכד בכניסה, לפני הבדיקות של ``kickoff_index_warmup``. לכידה אחרי
    ``_WARMUP_TRIGGERED.set()`` הייתה מצמידה לחימום הזה את הדור החדש, והוא היה
    בונה אחרי האיפוס. האיפוס מוזרק דרך ``_cache_flag_ready``, שהחימום קורא
    בבדיקה שלו — בקריאה הראשונה בלבד. נופלת אם הלכידה תזוז אל אחרי הבדיקות.
    """
    db = _a_build_would_publish(monkeypatch)
    resets = []

    def _reset_inside_the_check():
        if not resets:
            resets.append(True)
            api.reset_index_state_for_tests()
        return False

    monkeypatch.setattr(api, "_cache_flag_ready", _reset_inside_the_check)

    api.kickoff_index_warmup(background=False)

    assert resets, "האיפוס לא הוזרק לתוך החימום, ולכן התרחיש לא נבדק"
    assert db.index_requests == [], "חימום שהתחיל לפני האיפוס בנה אחריו"
    assert api._INDEX_READY is False


def test_a_request_that_reaches_the_lock_after_the_reset_does_not_build(monkeypatch):
    """בקשה שעברה את המסלול המהיר לפני האיפוס ומגיעה לנעילה אחריו — יוצאת בלי לבנות.

    הבקשה רצה בחוט משלה ונעצרת בתוך המסלול המהיר (``_cache_flag_ready``) עד
    שהאיפוס מסתיים; רק אז היא ממשיכה לנעילה. נופלת בלי בדיקת הדור בנעילה.
    """
    db = _a_build_would_publish(monkeypatch)
    entered, go = threading.Event(), threading.Event()

    def _paused_fast_path():
        entered.set()
        go.wait(timeout=10)
        return False

    monkeypatch.setattr(api, "_cache_flag_ready", _paused_fast_path)
    errors = []

    def _request():
        try:
            api._ensure_indexes()
        except BaseException as exc:  # מועבר לחוט הבדיקה ונבדק שם
            errors.append(exc)

    request = threading.Thread(target=_request, name="request-before-reset", daemon=True)
    request.start()
    try:
        assert entered.wait(timeout=10), "הבקשה לא הגיעה למסלול המהיר"
        api.reset_index_state_for_tests()
    finally:
        go.set()
        request.join(timeout=10)

    assert not request.is_alive(), "הבקשה לא הסתיימה"
    assert errors == []
    assert db.index_requests == [], "בקשה שהתחילה לפני האיפוס בנתה אחריו"
    assert api._INDEX_READY is False


class _OwnedLock:
    """``threading.Lock`` שזוכר איזה חוט מחזיק בו, כדי שהבדיקה תדע אם קוד רץ תחת הנעילה."""

    def __init__(self):
        self._lock = threading.Lock()
        self.owner = None

    def __enter__(self):
        self._lock.acquire()
        self.owner = threading.get_ident()
        return self

    def __exit__(self, *exc_info):
        self.owner = None
        self._lock.release()
        return False


def test_a_build_that_fails_while_the_reset_waits_does_not_reopen_the_retry_window(monkeypatch):
    """בנייה שנכשלת בזמן שהאיפוס ממתין לנעילה — חלון ההמתנה סגור אחרי האיפוס.

    ``get_db`` שזורק הוא הכשל של בדיקה שמריצה את הבנייה מול מסד שאינו זמין. אם
    ``_INDEX_RETRY_AFTER`` נקבע אחרי שחרור הנעילה, האיפוס שממתין לה נכנס בין
    השחרור להשמה, וההשמה נוחתת אחריו — והבדיקה הבאה מקבלת יציאה מוקדמת, בדיוק
    הבאג שהאיפוס בא לסגור.

    הסדר נכפה ולא מקווה: הקריאה ל-``time.monotonic`` שמחשבת את המועד אחרי
    הכשל ממתינה לסוף האיפוס **רק כשהחוט שלה אינו מחזיק בנעילה**. כשההשמה תחת
    הנעילה אין המתנה, והאיפוס רץ אחריה; כשהיא מחוצה לה, האיפוס מסתיים לפניה.
    נופלת אם הטיפול בכשל יחזור אל מחוץ לנעילה.
    """
    lock = _OwnedLock()
    monkeypatch.setattr(api, "_INDEX_READY_LOCK", lock)
    building, fail_now, failed, reset_done = (threading.Event() for _ in range(4))

    def _db_that_stops_answering():
        building.set()
        fail_now.wait(timeout=10)
        failed.set()
        raise RuntimeError("mongo is not answering")

    monkeypatch.setattr(api, "get_db", _db_that_stops_answering)

    def _monotonic():
        if failed.is_set() and lock.owner != threading.get_ident():
            reset_done.wait(timeout=10)
        return time.monotonic()

    clock = types.ModuleType("time")
    clock.__dict__.update(time.__dict__)
    clock.monotonic = _monotonic
    monkeypatch.setattr(api, "time", clock)
    errors = []

    def _run(target, done=None):
        try:
            target()
        except BaseException as exc:  # מועבר לחוט הבדיקה ונבדק שם
            errors.append(exc)
        finally:
            if done is not None:
                done.set()

    request = threading.Thread(target=_run, args=(api._ensure_indexes,), name="failing-build", daemon=True)
    resetter = threading.Thread(
        target=_run, args=(api.reset_index_state_for_tests, reset_done), name="reset-waits-for-the-lock", daemon=True
    )
    request.start()
    started = building.wait(timeout=10)
    if started:
        resetter.start()
    fail_now.set()
    request.join(timeout=10)
    if started:
        resetter.join(timeout=10)

    assert started, "הבנייה לא הגיעה ל-get_db, ולכן התרחיש לא נבדק"
    assert not request.is_alive() and not resetter.is_alive(), "אחד החוטים לא הסתיים"
    assert errors == []
    assert api._INDEX_RETRY_AFTER == 0.0, "בנייה שנכשלה בזמן שהאיפוס המתין פתחה אחריו את חלון ההמתנה"


def test_a_build_that_raises_sends_its_failed_event_after_releasing_the_lock(monkeypatch):
    """בנייה שזורקת — חלון ההמתנה נקבע, והאירוע ``failed`` נשלח רק אחרי שחרור הנעילה.

    ``emit_event`` על שגיאה עושה עבודה משלו — סיווג, Sentry, ולפי
    ``ALERT_EACH_ERROR`` גם התראה — ובקשות שממתינות לנעילה לא צריכות להמתין גם
    לה. נופלת אם השליחה תזוז אל תוך הנעילה, יחד עם ההשמה של
    ``_INDEX_RETRY_AFTER``.
    """
    lock = _OwnedLock()
    monkeypatch.setattr(api, "_INDEX_READY_LOCK", lock)

    def _db_that_raises():
        raise RuntimeError("mongo is not answering")

    monkeypatch.setattr(api, "get_db", _db_that_raises)
    sent_under_the_lock = {}

    def _record(stage, duration_ms=None, error=None):
        sent_under_the_lock[stage] = lock.owner == threading.get_ident()

    monkeypatch.setattr(api, "_emit_index_event", _record)

    api._ensure_indexes()

    assert api._INDEX_RETRY_AFTER > time.monotonic(), "הבנייה שנכשלה לא קבעה את חלון ההמתנה"
    assert sent_under_the_lock == {"failed": False}, "האירוע failed נשלח בזמן שהבנייה עוד מחזיקה בנעילה"


# ---------- הפיקסצ'ר: הזוג שמשחזר את הדליפה ----------
#
# שתי הבדיקות חייבות לרוץ אחת אחרי השנייה באותו תהליך, וזה סדר ברירת המחדל
# של pytest בתוך קובץ — וגם תחת ``--dist=loadscope`` של ``ci.yml``, שמקבץ את
# כל הפונקציות של מודול ליחידת עבודה אחת (``LoadScopeScheduling._split_scope``,
# pytest-xdist 3.8.0). הרצה של השנייה לבדה מדלגת עם הסבר, במקום לעבור בלי לבדוק.

#: נרשם בבדיקה הראשונה של הזוג ונבדק בשנייה.
_RETRY_WINDOW_LEFT_OPEN: list = []


def test_a_build_whose_title_index_is_not_confirmed_leaves_the_retry_window_open(monkeypatch):
    """החצי הראשון: מה שבדיקות התזכורות עושות מול ה-stub שלהן."""
    monkeypatch.setattr(api, "get_db", _RecordingDB)
    monkeypatch.setattr(api, "ensure_title_index", lambda coll: False)

    api._ensure_indexes()

    assert api._INDEX_RETRY_AFTER > time.monotonic(), (
        "הבנייה לא השאירה את חלון ההמתנה פתוח, ולכן הזוג אינו משחזר את הדליפה"
    )
    _RETRY_WINDOW_LEFT_OPEN.append(True)


def test_the_test_after_it_builds_the_indexes_from_scratch(monkeypatch):
    """החצי השני: באותו תהליך, בתוך ``_INDEX_RETRY_SECONDS`` מהקודמת.

    בלי הפיקסצ'ר האוטומטי ב-``conftest.py`` שבשורש, ``_ensure_indexes`` יוצא
    כאן מוקדם ואינו מבקש אף אינדקס — זה הבאג שהפיל את בדיקות האינדקסים ב-
    ``tests/test_note_boards_mongo.py``.
    """
    if not _RETRY_WINDOW_LEFT_OPEN:
        pytest.skip("הבדיקה הקודמת בזוג לא רצה לפני זו באותו תהליך, ולכן אין כאן דליפה לבדוק")
    db = _RecordingDB()
    monkeypatch.setattr(api, "get_db", lambda: db)
    monkeypatch.setattr(api, "ensure_title_index", lambda coll: True)
    monkeypatch.setattr(api, "ensure_repo_title_index", lambda coll: True)

    api._ensure_indexes()

    assert db.index_requests, "הבנייה יצאה מוקדם ולא ביקשה אף אינדקס: המצב של הבדיקה הקודמת דלף לזו"
    assert api._INDEX_READY is True
