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
        #: כמה פעמים ה-keyspace נסרק. הצורה הישנה סרקה אחת לכל דפוס.
        self.scan_calls = 0

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
        # מחזיר את כל המפתחות ומשאיר ל-``delete_patterns`` לסנן, בדיוק כפי
        # שהיא עושה מול לקוחות שאינם מכבדים ``match``. מאז המעבר לסריקה
        # אחת הקוד ממילא אינו מעביר ``match``.
        self.scan_calls += 1
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


def test_all_the_patterns_share_one_scan_of_the_keyspace(cache):
    """הניקוי סורק את ה-keyspace **פעם אחת**, לא פעם לכל דפוס.

    **למה זה נבדק, ולמה זה לא רק ביצועים.** הצורה הקודמת קראה ל-
    ``delete_pattern`` בלולאה, וכל קריאה הריצה ``SCAN`` משלה. שתי
    תוצאות, ושתיהן נמדדו מול Redis 7 אמיתי על keyspace של 100,000
    מפתחות:

    1. **2,000 פקודות ``SCAN`` מול 200.** ``MATCH`` של Redis מסנן
       *אחרי* השליפה מהאוסף, ולכן דפוס אינו מקצר את הסריקה — עשרה
       דפוסים היו עשרה מעברים מלאים. על localhost ההפרש נבלע, אבל
       ב-RTT של 1ms זה 2.0 שניות מול 0.2.
    2. **תקציב הזמן היה פר-דפוס.** ``CACHE_DELETE_PATTERN_BUDGET_SECONDS``
       הוא 5 שניות, וכל קריאה קיבלה תקציב משלה — כלומר עשרה דפוסים יכלו
       לחסום את התהליך עד 50 שניות. זו התנהגות, לא אופטימיזציה.

    הטענה היא על **מספר הסריקות** ולא על זמן, כי זמן על מכונת בדיקה
    אינו מעיד על פרודקשן — ומספר הסריקות כן.
    """
    for key in LIST_KEYS.values():
        cache.set(key, json.dumps([{"description": "ישן"}]))
    cache.redis_client.scan_calls = 0

    cache.invalidate_file_related(FILE_ID, USER_ID)

    assert cache.redis_client.scan_calls == 1, (
        f"ה-keyspace נסרק {cache.redis_client.scan_calls} פעמים — "
        "כלומר הדפוסים עדיין נמחקים אחד-אחד"
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
