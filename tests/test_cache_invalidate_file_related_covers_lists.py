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
import os

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
        # מחזיר את כל המפתחות ומשאיר ל-``delete_pattern`` לסנן ב-``fnmatch``,
        # בדיוק כפי שהיא עושה מול לקוחות שאינם מכבדים ``match``.
        return list(self.store.keys())


@pytest.fixture
def cache(monkeypatch):
    os.environ["REDIS_URL"] = "redis://dummy"
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
