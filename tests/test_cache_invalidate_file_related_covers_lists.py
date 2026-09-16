"""``invalidate_file_related`` מנקה גם את הרשימות שנושאות ``description``.

**הפער שהקובץ הזה נולד ממנו.** ``POST /api/file/<id>/quick-update`` —
"עדכון תיאור מהיר" בעמוד הקובץ — קורא רק ל-``invalidate_file_related``,
ו-``invalidate_user_cache`` אינו רץ שם. דפוסי הניקוי של הראשונה כיסו את
``user_files``, ``latest_version`` ו-``web:files``, אבל **לא** את
``search_code`` — ש-``@cached`` שלו הוא 300 שניות
(``database/repository.py``, ``_search_code_cached``). כלומר התיאור
השתנה במסד, והחיפוש המשיך להגיש את הישן עד חמש דקות.

``invalidate_user_cache`` תפסה אותו ממילא, דרך ה-fallback הרחב
``*:{user_id}:*`` שיש שם ואין כאן — ולכן הפער היה גלוי רק למי שהשווה את
שתי הרשימות זו לזו.

הבדיקה היא **התנהגותית ולא על רשימת הדפוסים**: היא שותלת מפתחות בצורה
שבה ``_make_key`` באמת מייצר אותם, ומוודאת שהם נעלמו. טענה על תוכן
``patterns`` הייתה עוברת גם על דפוס שנכתב נכון ולא מתאים לשום מפתח אמיתי.

אין כאן קלט או פלט לדיסק — הקאש הוא ``DummyRedis`` בזיכרון.
"""

from __future__ import annotations

import json

import pytest

from cache_manager import CacheManager

USER_ID = 4242
FILE_ID = "65f1c2d3e4f5a6b7c8d9e0f1"


class _DummyRedis:
    """Redis מינימלי — **עם ``scan_iter``, וזה ההבדל שמכריע כאן.**

    ``delete_pattern`` מסתעפת לפי מה שהלקוח מציע. עם ``scan_iter`` היא
    מסננת כל מפתח שוב דרך ``fnmatch`` בעצמה, כלומר ההתאמה זהה לזו של
    Redis אמיתי. עם ``keys()`` בלבד היא מוסרת את ההחלטה ללקוח.

    הדמה ב-``test_cache_manager_basic`` מציעה ``keys()`` עם glob נאיבי
    שחותך בכוכבית הראשונה, ולכן ``search_code:*:4242:*`` היה מתרגם שם
    ל"כל מפתח שמתחיל ב-``search_code:``" — כולל של משתמשים אחרים.
    הבדיקה שלמטה על בידוד בין משתמשים הייתה נכשלת **בגלל הדמה ולא בגלל
    הקוד**, וזו בדיוק הדוגמה של ``bugbot-rules/widened-exception-scope.md``:
    כשבדיקה נופלת, השורש בדרך כלל בסטאב. ההרחבה כאן היא של הדמה; קוד
    הייצור לא נגע.
    """

    def __init__(self):
        self.store: dict[str, str] = {}
        #: כמה פעמים ה-keyspace נסרק, ועם איזה ``match`` בכל פעם. הסריקה
        #: היא אחת לכל דפוס, וה-``match`` הוא מה שמונע מכל ה-keyspace
        #: לחצות את הרשת.
        self.scan_calls = 0
        self.match_args: list = []

    def ping(self):
        return True

    def get(self, k):
        return self.store.get(k)

    def setex(self, k, ttl, v):
        self.store[k] = v
        return True

    def set(self, k, v, ex=None):
        self.store[k] = v
        return True

    def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                count += 1
        return count

    def scan_iter(self, match=None, count=None):
        # מתעד את ``match`` ומחזיר את **כל** המפתחות, כמו לקוח שאינו מכבד
        # אותו — כך הסינון בצד הלקוח נבדק, ולא רק זה שבשרת.
        self.scan_calls += 1
        self.match_args.append(match)
        return list(self.store.keys())


@pytest.fixture
def cache(monkeypatch):
    """``CacheManager`` עם Redis מדומה, בלי לדלוף ``REDIS_URL`` החוצה.

    ``monkeypatch.setenv`` ולא השמה ישירה ל-``os.environ``: ההשמה הישירה
    שרדה את סוף הבדיקה, וכל ``CacheManager`` שנבנה אחריה באותה ריצה ירש
    ``redis://dummy`` — כתובת שאין מאחוריה שרת. ``monkeypatch`` מחזיר את
    המצב הקודם, כולל **הסרה** של המשתנה כשהוא לא היה מוגדר מלכתחילה.
    """
    monkeypatch.setenv("REDIS_URL", "redis://dummy")
    cm = CacheManager()
    monkeypatch.setattr(cm, "redis_client", _DummyRedis(), raising=True)
    monkeypatch.setattr(cm, "is_enabled", True, raising=True)
    return cm


#: המפתחות כפי ש-``cached`` מייצר אותם: ``<prefix>:<func>:<self>:<args...>``.
#: שלושת אלה הם הרשימות שמחזירות ``description`` של הגרסה האחרונה, ולכן
#: הן בדיוק אלה שמתיישנות מעדכון תיאור.
LIST_KEYS = {
    "search_code": f"search_code:_search_code_cached:Repository:{USER_ID}:שלום:None:None:20",
    "regular_files": f"regular_files:get_regular_files_paginated:Repository:{USER_ID}:1:10",
    "files_by_repo": f"files_by_repo:get_user_files_by_repo:Repository:{USER_ID}:repo:x:1:50",
}


def test_invalidating_a_file_clears_the_lists_that_carry_its_description(cache):
    """שלוש הרשימות נעלמות — ולא רק אלה שכוסו קודם.

    ``search_code`` הוא העיקר (300 שניות), ושתי האחרות נכללות כי זו
    אותה מחלקה: כל רשימה שמחזירה מטא-דאטה של הגרסה האחרונה מתיישנת
    מאותה כתיבה בדיוק.
    """
    for key in LIST_KEYS.values():
        cache.set(key, json.dumps([{"description": "ישן"}]))

    deleted = cache.invalidate_file_related(FILE_ID, USER_ID)

    assert deleted >= len(LIST_KEYS), deleted
    remaining = [name for name, key in LIST_KEYS.items() if cache.get(key) is not None]
    assert remaining == [], f"רשימות שממשיכות להגיש תיאור ישן: {remaining}"


def test_the_previously_covered_keys_are_still_cleared(cache):
    """הכיסוי הישן לא נשבר בדרך.

    הוספת דפוסים לרשימה יכולה להיראות בטוחה עד שמישהו משכתב אותה. בלי
    הטענה הזו, הבדיקה שמעל הייתה עוברת גם על גרסה שהחליפה את הדפוסים
    הקיימים במקום להוסיף עליהם.
    """
    keys = {
        "user_files": f"user_files:get_user_files:Repository:{USER_ID}:1:20",
        "latest_version": f"latest_version:get_latest_version:Repository:{USER_ID}:a.md",
        "web:files": f"web:files:user:{USER_ID}:page:1",
        "file_content": f"file_content:{FILE_ID}:raw",
    }
    for key in keys.values():
        cache.set(key, json.dumps({"description": "ישן"}))

    cache.invalidate_file_related(FILE_ID, USER_ID)

    remaining = [name for name, key in keys.items() if cache.get(key) is not None]
    assert remaining == [], remaining


def test_another_users_cache_is_left_alone(cache):
    """הניקוי ממוקד במשתמש — דפוס רחב מדי היה מרוקן קאש של אחרים.

    ``invalidate_user_cache`` נושא fallback רחב (``*:{user_id}:*``)
    שמותר לו כי הוא ממילא מכוון למשתמש אחד ובכוונה סוחף. כאן אין דבר
    כזה, ולכן צריך לוודא שהדפוסים שנוספו לא גלשו: ``search_code:*:42:*``
    לא אמור לתפוס את ``search_code:...:424242:...``.
    """
    other = f"search_code:_search_code_cached:Repository:{USER_ID + 1}:שלום:None:None:20"
    mine = LIST_KEYS["search_code"]
    cache.set(other, json.dumps(["של מישהו אחר"]))
    cache.set(mine, json.dumps(["שלי"]))

    cache.invalidate_file_related(FILE_ID, USER_ID)

    assert cache.get(mine) is None, "שלי לא נוקה"
    assert cache.get(other) is not None, "נוקה קאש של משתמש אחר"


def test_without_a_user_id_only_the_file_keyed_entries_go(cache):
    """``user_id=None`` הוא מסלול נתמך, והרשימות אינן ניתנות לניקוי בו.

    מפתח של רשימה נושא את מזהה המשתמש ולא את מזהה הקובץ, ולכן בלי
    ``user_id`` אין לפי מה לתפוס אותו. הבדיקה מתעדת את הגבול הזה כדי
    שלא ייראה כמו באג — ומוודאת שהחתימה הזו עדיין עובדת ולא זורקת.
    """
    list_key = LIST_KEYS["search_code"]
    file_key = f"file_content:{FILE_ID}:raw"
    cache.set(list_key, json.dumps(["ישן"]))
    cache.set(file_key, json.dumps({"code": "x"}))

    cache.invalidate_file_related(FILE_ID)

    assert cache.get(file_key) is None
    assert cache.get(list_key) is not None


def test_each_pattern_is_scanned_with_server_side_match(cache):
    """כל דפוס מקבל ``SCAN`` משלו, ו-``match`` מועבר לשרת בכל אחד.

    **למה זה נבדק, ואיפה זה נשבר קודם.** גרסת ביניים של ``delete_patterns``
    הריצה סריקה אחת בלי ``match`` וסיננה בפייתון — ונמדדה מול Redis 7 עם
    200,000 מפתחות: ``delete_pattern`` עם דפוס יחיד משך **200,007
    מפתחות** לתהליך כדי למחוק אחד. ``MATCH`` אינו מקצר את המעבר של
    Redis על ה-keyspace, אבל הוא קובע מה חוצה את הרשת; ובלעדיו כל אחד
    מעשרות הקוראים עם דפוס יחיד שילם את כל ה-keyspace, וב-MCP — על
    ה-worker היחיד של ``_WRITE_POOL``.

    הטענה היא על **הארגומנטים שנשלחו** ולא על זמן: זמן על מכונת בדיקה
    אינו מעיד על פרודקשן, ו-``match`` שהגיע לשרת כן.
    """
    for key in LIST_KEYS.values():
        cache.set(key, json.dumps([{"description": "ישן"}]))
    cache.redis_client.scan_calls = 0
    cache.redis_client.match_args.clear()

    cache.invalidate_file_related(FILE_ID, USER_ID)

    sent = cache.redis_client.match_args
    assert None not in sent, f"סריקה בלי match מושכת את כל ה-keyspace: {sent}"
    assert f"search_code:*:{USER_ID}:*" in sent, sent
    assert f"file_content:{FILE_ID}*" in sent, sent
    assert len(sent) == cache.redis_client.scan_calls == len(set(sent)), (
        "כל דפוס נסרק בדיוק פעם אחת, ולא יותר"
    )

def test_a_single_pattern_still_works_through_the_same_path(cache):
    """``delete_pattern`` נשארה עובדת — היא מקרה פרטי של ``delete_patterns``.

    יש לה קוראים רבים בריפו, והמעבר לא אמור להיראות להם. הבדיקה גם
    מוודאת שדפוס בודד אינו סורק יותר מפעם אחת.
    """
    cache.set("file_content:abc:raw", json.dumps({"code": "x"}))
    cache.set("other:abc:raw", json.dumps({"code": "y"}))
    cache.redis_client.scan_calls = 0

    deleted = cache.delete_pattern("file_content:*")

    assert deleted == 1, deleted
    assert cache.get("file_content:abc:raw") is None
    assert cache.get("other:abc:raw") is not None, "נמחק מפתח שלא תאם"
    assert cache.redis_client.scan_calls == 1


def test_an_empty_pattern_list_scans_nothing(cache):
    """רשימה ריקה אינה סורקת, ובוודאי אינה מוחקת.

    בלי היציאה המוקדמת, רג'קס מאוחד מאפס דפוסים הוא מחרוזת ריקה —
    שמתאימה ל**כל** מפתח. כלומר "אין מה למחוק" היה הופך ל"מחק הכול".
    זה תרחיש הכשל שהופך את השורה הזו לבדיקה ולא לפורמליות.
    """
    cache.set("file_content:abc:raw", json.dumps({"code": "x"}))
    cache.redis_client.scan_calls = 0

    assert cache.delete_patterns([]) == 0
    assert cache.redis_client.scan_calls == 0
    assert cache.get("file_content:abc:raw") is not None, "רשימה ריקה מחקה מפתחות"


def test_a_pattern_matches_the_whole_key_and_not_a_substring_of_it(cache):
    """הדפוס מעוגן לתחילת המפתח, כמו glob של Redis.

    **המוטציה שחשפה את הפער:** ``matcher.search`` במקום ``matcher.match``
    עבר את כל שאר הקובץ. ``fnmatch.translate`` מייצר דפוס שמעוגן בסוף
    (``\\Z``) אבל **לא** בהתחלה, ולכן ``search`` היה מתאים גם מפתח
    שהדפוס יושב באמצעו. ``MATCH`` של Redis מתאים את המפתח **כולו**,
    ולכן ``match`` הוא מה ששומר על זהות בין הסינון בשרת לסינון בלקוח.

    בלי הבדיקה הזו, מפתח של מודול אחר שבמקרה מכיל ``file_content:``
    באמצעו היה נמחק בניקוי של קובץ שאינו קשור אליו.
    """
    victim = "unrelated:file_content:abc:raw"
    target = "file_content:abc:raw"
    cache.set(victim, json.dumps({"code": "לא שלי"}))
    cache.set(target, json.dumps({"code": "שלי"}))

    cache.delete_pattern("file_content:*")

    assert cache.get(target) is None, "המפתח שהיה אמור להימחק נשאר"
    assert cache.get(victim) is not None, (
        "נמחק מפתח שהדפוס מופיע רק באמצעו — הסינון אינו מעוגן לתחילת המפתח"
    )


def test_a_bare_string_is_rejected_instead_of_exploding_into_per_character_patterns(cache):
    """מחרוזת במקום רשימה — ``TypeError``, ושום מפתח לא נגע.

    ``str`` עומד ב-``Sequence[str]``, ולכן ``[str(p) for p in "file_content:*"]``
    היה מתפרק לדפוס לכל תו — והתו ``*`` לבדו מתאים ל**כל** מפתח. טעות של
    תו אחד בין ``delete_pattern`` ל-``delete_patterns`` הייתה מוחקת את
    המסד כולו, כולל מוני ה-rate-limit של flask-limiter שחיים באותו Redis.

    זורק ולא עוטף בשקט, כי זו שגיאת קורא: קוד שמחזיר 0 היה נראה כמו "לא
    היה מה למחוק". והאסרשן על המסד אינו קישוט — סירוב שמגיע **אחרי**
    מחיקה הוא עדיין מחיקה.
    """
    cache.set("session:abc", "1")
    cache.set("LIMITER/limiter/1/60/1/minute", "1")
    cache.set(LIST_KEYS["search_code"], "[]")

    with pytest.raises(TypeError):
        cache.delete_patterns("file_content:*")  # type: ignore[arg-type]

    assert cache.get("session:abc") is not None, "הסשן נמחק"
    assert cache.get("LIMITER/limiter/1/60/1/minute") is not None, "מונה rate-limit נמחק"
    assert cache.get(LIST_KEYS["search_code"]) is not None
    assert cache.redis_client.scan_calls == 0, "בכלל נסרק"


@pytest.mark.parametrize("pattern", ["*", "**", "?*", "??"])
def test_a_pattern_that_matches_every_key_is_refused(cache, pattern, caplog):
    """דפוס בלי אף תו מילולי נדחה ב-``ValueError`` — ניקוי מלא הוא ``clear_all``.

    **הקריטריון הוא "אין תו מילולי בכלל", ולא "אין תו מילולי לפני הכוכבית
    הראשונה".** ``*:user:4242:*`` ב-``invalidate_user_cache`` מתחיל בכוכבית
    ואינו מתאים לכל מפתח — הוא דורש ``:user:4242:`` — והקריטריון השני היה
    פוסל אותו ושובר ניקוי חי. הטסט שאחרי זה מוודא שהדפוס ההוא עדיין עובר.
    """
    cache.set("session:abc", "1")
    cache.set("LIMITER/limiter/1/60/1/minute", "1")

    with pytest.raises(ValueError):
        cache.delete_pattern(pattern)

    assert cache.get("session:abc") is not None
    assert cache.get("LIMITER/limiter/1/60/1/minute") is not None
    assert cache.redis_client.scan_calls == 0
    assert any("clear_all" in r.getMessage() for r in caplog.records), (
        "הסירוב לא נרשם ללוג עם ההפניה ל-clear_all"
    )


def test_a_pattern_that_merely_starts_with_a_star_is_still_allowed(cache):
    """``*:user:{uid}:*`` — כוכבית בהתחלה, תו מילולי אחריה — עובר.

    זה הדפוס החי מ-``invalidate_user_cache``. אם השומר על "מתאים לכל מפתח"
    היה נכתב כ"אין תו לפני הכוכבית הראשונה", הוא היה נופל כאן.
    """
    mine = f"x:user:{USER_ID}:files"
    other = f"x:user:{USER_ID + 1}:files"
    cache.set(mine, "1")
    cache.set(other, "1")

    deleted = cache.delete_pattern(f"*:user:{USER_ID}:*")

    assert deleted == 1, deleted
    assert cache.get(mine) is None
    assert cache.get(other) is not None


class _SlowRedis(_DummyRedis):
    """מחזיר שלושה מפתחות מיד, ואז נתקע מעבר לתקציב לפני הרביעי."""

    def __init__(self, stall_seconds: float):
        super().__init__()
        self.stall_seconds = stall_seconds

    def scan_iter(self, match=None, count=None):
        import time as _time

        self.scan_calls += 1
        self.match_args.append(match)
        keys = sorted(self.store.keys())
        for k in keys[:3]:
            yield k
        _time.sleep(self.stall_seconds)
        for k in keys[3:]:
            yield k


def test_keys_already_matched_are_deleted_when_the_budget_runs_out(cache, monkeypatch, caplog):
    """מיצוי תקציב אינו זורק את מה שכבר הותאם — וגם אינו שותק.

    **הבאג שזה שומר עליו.** הצורה הקודמת שטפה את ה-batch רק כש-
    ``time.time() <= deadline``; כשהתקציב נגמר באמצע, עד 199 מפתחות שכבר
    עברו התאמה נזרקו בלי ``DEL`` — כלומר בדיוק הקאש הישן שהניקוי בא
    להסיר נשאר, והקורא קיבל מספר שנראה תקין. כאן ה-batch נשטף לפני **כל**
    יציאה, ומיצוי התקציב נרשם כ-``WARNING`` עם "חלקי", כדי שניקוי חלקי
    לא ייראה כמו ניקוי מלא.

    התקציב מקוצר ל-50ms דרך אותו משתנה סביבה שהקוד קורא, והדמה נתקעת
    ל-200ms אחרי שלושה מפתחות — כלומר הבדיקה מפעילה את מסלול המיצוי
    האמיתי ולא מדמה אותו.
    """
    monkeypatch.setenv("CACHE_DELETE_PATTERN_BUDGET_SECONDS", "0.05")
    slow = _SlowRedis(stall_seconds=0.2)
    monkeypatch.setattr(cache, "redis_client", slow, raising=True)
    for i in range(6):
        cache.set(f"file_content:{i}:raw", "x")

    deleted = cache.delete_pattern("file_content:*")

    gone = [f"file_content:{i}:raw" for i in range(3)]
    kept = [f"file_content:{i}:raw" for i in range(3, 6)]
    assert all(cache.get(k) is None for k in gone), (
        f"מפתחות שכבר הותאמו לפני מיצוי התקציב לא נמחקו: "
        f"{[k for k in gone if cache.get(k) is not None]}"
    )
    assert deleted == 3, deleted
    # מה שלא הספיק להיסרק נשאר — זו המשמעות של "חלקי", והיא חייבת להיאמר
    assert all(cache.get(k) is not None for k in kept)
    assert any(
        "חלקי" in r.getMessage() and r.levelname == "WARNING" for r in caplog.records
    ), [r.getMessage() for r in caplog.records]
