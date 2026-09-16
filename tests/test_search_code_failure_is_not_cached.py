"""כשל של ``search_code`` אינו תוצאה, ולכן אינו נכנס לקאש.

**הבאג שהקובץ הזה שומר מפניו.** ``Repository.search_code`` תפס כל חריגה
והחזיר ``[]``, והפונקציה כולה הייתה עטופה ב-``@cached(expire_seconds=300)``.
‏``cache_manager`` מדלג רק על ``None`` — ``[]`` נשמר ככל ערך אחר — ולכן
כשל חולף של מסד הפך ל"לא נמצא" שנמשך **חמש דקות**, גם אחרי שהמסד חזר.

**הפיצול הוא התיקון:** ה-``except`` יצא מחוץ לפונקציה המקושטת. חריגה
עולה דרך הדקורטור, והקריאה ל-``func`` שם אינה בתוך ``try`` — ולכן
השמירה פשוט אינה מגיעה. הקוראים ממשיכים לקבל ``[]``.

**ולמה שתי אסרשנים על הקאש ולא אחת.** בטסטים אין Redis, ולכן
``cache.set`` מחזיר ``False`` והדקורטור נופל ל-``_local_cache_store`` —
שהוא קאש אמיתי לכל דבר. בדיקה שמסתכלת רק על ``cache.set`` הייתה עוברת
גם על הקוד הישן. זו אותה צורה שב-``tests/test_cache_manager_none_results.py``.
"""

import pytest

import cache_manager as cm_mod


@pytest.fixture(autouse=True)
def _clean_local_cache():
    cm_mod._local_cache_store.clear()
    yield
    cm_mod._local_cache_store.clear()


class _Boom(Exception):
    """כשל מסד, לא כשל של השאילתה."""


class _FailingCollection:
    """אוסף שנופל ב-``aggregate`` — מספר פעמים נתון, ואז מצליח.

    מדמה כשל חולף: בדיוק המקרה שבו קיבוע ה-``[]`` בקאש מזיק.

    **המונה יושב מחוץ ל-``__dict__``, וזה לא קוסמטי.** ``_make_key`` בונה
    את חלק ה-``self`` שבמפתח מטביעת אצבע **רקורסיבית של ``__dict__``**
    (``cache_manager.py`` — ענף 4), ולכן מונה שמשתנה בין קריאות היה
    משנה את המפתח עצמו. נמדד: עם ``self.calls`` הגיבוב היה
    ``114caa05…`` ואז ``a8148890…``, הקאש לא נפגע אף פעם, והטסט של
    התוצאה התקינה נכשל מסיבה שאין לה קשר לתיקון. ``id`` קבוע מקצר את
    ``_stable_part`` לענף 3 ומייצב את המפתח.
    """

    def __init__(self, fail_times: int = 1, ident: str = "coll-1"):
        self.id = ident
        self._fail_times = fail_times
        self._counter = _Counter()

    @property
    def calls(self) -> int:
        return self._counter.n

    def aggregate(self, pipeline, **kwargs):
        self._counter.n += 1
        if self._counter.n <= self._fail_times:
            raise _Boom("connection reset")
        return iter([{"_id": "a.py", "file_name": "a.py"}])


class _Counter:
    """מונה שאינו חלק מטביעת האצבע של המפתח."""

    def __init__(self):
        self.n = 0


class _Manager:
    def __init__(self, collection):
        self.id = "mgr-1"
        self.collection = collection


def _repo(collection):
    from database.repository import Repository

    repo = Repository.__new__(Repository)
    repo.manager = _Manager(collection)
    return repo


def test_a_transient_failure_does_not_pin_an_empty_result_for_five_minutes(monkeypatch):
    """הקריאה השנייה מגיעה שוב למסד, ומחזירה את מה שיש.

    **מוטציה שמפילה:** להחזיר את ``@cached`` על ``search_code`` עצמה, עם
    ה-``except`` בתוכה — ואז הקריאה השנייה נענית מהקאש ו-``calls``
    נשאר 1.
    """
    coll = _FailingCollection(fail_times=1)
    repo = _repo(coll)

    first = repo.search_code(7, "needle")
    assert first == [], "הקוראים ממשיכים לקבל רשימה ריקה — החוזה לא זז"
    assert coll.calls == 1

    second = repo.search_code(7, "needle")
    assert coll.calls == 2, "הכשל קובע בקאש: הקריאה השנייה לא הגיעה למסד"
    assert [r["file_name"] for r in second] == ["a.py"]


def test_the_failure_reaches_neither_the_remote_cache_nor_the_local_fallback(monkeypatch):
    """שני מסלולי הכתיבה של הדקורטור, ולא רק אחד מהם.

    **מוטציה שמפילה:** להחזיר את ``@cached`` על ``search_code`` — ואז
    ``cache.set`` נקרא (או, כשאין Redis, נכתב מפתח ל-``_local_cache_store``).
    """
    def _no_set(*a, **k):
        raise AssertionError("כשל אינו תוצאה ואינו נכנס לקאש")

    monkeypatch.setattr(cm_mod.cache, "get", lambda _k: None, raising=True)
    monkeypatch.setattr(cm_mod.cache, "set", _no_set, raising=True)

    repo = _repo(_FailingCollection(fail_times=99))

    assert repo.search_code(7, "needle") == []
    assert cm_mod._local_cache_store == {}, "הכשל נכתב לפולבק המקומי"


def test_a_successful_result_is_still_cached(monkeypatch):
    """התיקון לא ביטל את הקאש — רק הוציא ממנו את הכשל.

    **מוטציה שמפילה:** להסיר את ``@cached`` מ-``_search_code_cached``
    לגמרי; אז ``calls`` היה 2 והקאש לא היה עושה דבר.
    """
    coll = _FailingCollection(fail_times=0)
    repo = _repo(coll)

    assert [r["file_name"] for r in repo.search_code(7, "needle")] == ["a.py"]
    assert coll.calls == 1

    assert [r["file_name"] for r in repo.search_code(7, "needle")] == ["a.py"]
    assert coll.calls == 1, "תוצאה תקינה חייבת להישמר"


def test_the_error_event_is_still_emitted(monkeypatch):
    """אירוע הדיווח לא זז מהפיצול — הוא רק עבר לעטיפה.

    **מוטציה שמפילה:** להשמיט את ``emit_event`` מהעטיפה החדשה.
    """
    import database.repository as repo_mod

    seen = []
    monkeypatch.setattr(
        repo_mod, "emit_event", lambda name, **kw: seen.append((name, kw)), raising=True
    )

    assert _repo(_FailingCollection(fail_times=99)).search_code(7, "needle") == []

    assert [n for n, _ in seen] == ["db_search_code_error"]
    assert "connection reset" in seen[0][1].get("error", "")


def test_the_key_the_code_actually_builds_is_still_caught_by_invalidation(monkeypatch):
    """הניקוי של המשתמש חייב להמשיך לתפוס את המפתח שהקוד באמת בונה.

    ``_make_key`` כולל את ``func.__name__``, ולכן הפיצול הזיז את המפתח
    מ-``search_code:search_code:...`` ל-``search_code:_search_code_cached:...``.
    ``invalidate_user_cache`` מנקה לפי ``search_code:*:<user_id>:*``
    (``cache_manager.py:801``), וזה חייב להמשיך להתאים.

    **המפתח נתפס מהקריאה האמיתית ולא נבנה כאן.** גרסה ראשונה של הטסט
    הרכיבה אותו ביד עם ה-prefix מוקלד — כלומר גזרה את הציפייה ואת
    הבדיקה מאותו מקור, ועברה גם כששיניתי את ``key_prefix`` בקוד. נמדד.

    **מוטציה שמפילה:** לשנות את ``key_prefix`` ל-``search_code_v2``.
    """
    from fnmatch import fnmatch

    keys = []
    original = cm_mod.cache._make_key
    monkeypatch.setattr(
        cm_mod.cache, "_make_key",
        lambda *a, **k: keys.append(original(*a, **k)) or keys[-1],
        raising=True,
    )

    _repo(_FailingCollection(fail_times=0)).search_code(7, "needle")

    assert keys, "הדקורטור לא בנה מפתח בכלל — הטסט אינו מודד כלום"
    assert fnmatch(keys[0], "search_code:*:7:*"), f"הניקוי לא יתפוס את {keys[0]!r}"
