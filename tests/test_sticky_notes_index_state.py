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
מקבע את שני החלקים:

- **הפונקציה מאפסת את כל מה שהבוטסטראפ כותב.** רשימת הגלובלים נגזרת כאן מקוד
  המקור — כל שם שמוצהר ``global`` בבוטסטראפ ובפונקציות שהוא קורא להן — ולא
  מרשימה מוקלדת. כך שומר חדש שנוסף לבוטסטראפ בלי שנוסף לאיפוס מפיל את הבדיקה,
  במקום להיסחף כמו הרשימה ב-``indexed_db``.
- **הפיקסצ'ר מחובר.** זוג בדיקות שמשחזר את הדליפה בלי מונגו: הראשונה משאירה
  את החלון פתוח בדיוק כמו בדיקות התזכורות, והשנייה — שרצה אחריה באותו תהליך —
  חייבת לבנות מאפס.
"""

from __future__ import annotations

import ast
import re
import threading
import time
from pathlib import Path

import pytest

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
    monkeypatch.setattr(api, "_ensure_indexes", lambda: builds.append("build"))

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
