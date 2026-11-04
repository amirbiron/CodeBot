"""הכנה משותפת לטסטים שעוברים דרך שכבת השמירה האמיתית.

שני דברים, לשני קובצי טסט (``test_save_preserves_content_mcp.py`` ו-
``test_bot_paste_cleanup_flows.py``) — פונקציות עזר ולא fixtures, כי fixture
מיובא נרשם מחדש במודול שמייבא אותו (T3).

1. **``config.py`` של הייצור.** תחת pytest ``import config`` מגיע ל-
   ``tests/config.py``, שאין בו ``NORMALIZE_CODE_ON_SAVE``. עד ספטמבר 2026 שכבת
   השמירה קראה את הדגל בתוך ``try/except Exception: pass``, ולכן בטסטים ה-
   ``AttributeError`` נבלע והנרמול שם אף פעם לא רץ: טסט שלא מתקן את זה היה
   עובר גם על הקוד שמחק את התווים, מהסיבה הלא נכונה.
2. **האוספים של ``database.db``** מוחלפים בדמה המשותפת (``_fake_mongo.py``),
   וה-``Repository`` נבנה מחדש מעליהם. ``DatabaseManager`` ו-``Repository``
   עצמם אמיתיים.

ולצידם :class:`StableKeyCollection`, לטסטים שצריכים קאש שבאמת זוכר ערך ישן.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

from _fake_mongo import FakeCollection, FakeDB

ROOT = Path(__file__).resolve().parents[1]


def load_production_config(monkeypatch) -> Any:
    """טוען את ``config.py`` של השורש ומציב אותו במקום שה-``Repository`` קורא ממנו."""
    spec = importlib.util.spec_from_file_location("codebot_production_config", ROOT / "config.py")
    module = importlib.util.module_from_spec(spec)
    # pydantic פותר את ההפניות של BotConfig דרך sys.modules, ולכן המודול נרשם
    # לפני ההרצה. בלי זה: ``PydanticUserError: BotConfig is not fully defined`` (נמדד).
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    import database.repository as repository_module

    monkeypatch.setattr(repository_module, "config", module.config)
    return module.config


def install_fake_collections(monkeypatch) -> SimpleNamespace:
    """``database.db`` נשאר ה-``DatabaseManager`` האמיתי; רק האוספים שלו מוחלפים.

    ``raw`` הוא אותו ``code_snippets`` מאחורי ממשק ``db[name]`` — מה שה-MCP מקבל
    כ-``mongo_db`` בייצור. כל ההחלפות נעשות ב-``monkeypatch`` ולכן מוחזרות בסוף
    הטסט, כולל ה-``Repository`` שנבנה מעל האוספים.
    """
    from database import db as dbm

    code_snippets = FakeCollection()
    large_files = FakeCollection()
    monkeypatch.setattr(dbm, "collection", code_snippets)
    monkeypatch.setattr(dbm, "large_files_collection", large_files)
    monkeypatch.setattr(dbm, "_repo", None)
    raw = FakeDB()
    raw.c["code_snippets"] = code_snippets
    raw.c["large_files"] = large_files
    clear_local_cache()
    return SimpleNamespace(dbm=dbm, raw=raw, code_snippets=code_snippets, large_files=large_files)


def clear_local_cache() -> None:
    """הקאש המקומי (Redis כבוי בטסטים) משותף לכל התהליך: גרסה מקוּשה מטסט
    אחר הייתה נראית כקובץ קיים. נקרא בתחילת הטסט ובסופו."""
    import cache_manager

    cache_manager._local_cache_store.clear()


def latest(collection: FakeCollection, user_id: int, file_name: str) -> Dict[str, Any]:
    """הגרסה האחרונה ישירות מהאוסף — מקור האמת, לא מסלול הקריאה של הקוד."""
    docs = [d for d in collection.docs if d.get("user_id") == user_id and d.get("file_name") == file_name]
    assert docs, f"{file_name} לא נשמר כלל"
    return max(docs, key=lambda d: int(d.get("version", 0) or 0))


class StableKeyCollection:
    """הדמה המשותפת, מאחורי טביעת קאש יציבה — כמו ``Collection`` של pymongo.

    ``@cached`` בונה את המפתח מטביעה של ``__dict__`` של ה-``Repository``, והטביעה
    יורדת עד האוסף. בדמה המשותפת ``docs`` נכנס אליה כ-``[len=N]``, ולכן **כל insert
    מחליף את המפתח**, והגטר המקוּש מחטיא אחרי כל כתיבה — נמדד: אחרי insert ישיר הוא
    החזיר את הערך החדש, כלומר בדמה הקאש אינו יכול להיות ישן. באוסף אמיתי הטביעה
    אינה תלויה בתוכן. לאובייקט בלי ``__dict__`` הטביעה היא שם המחלקה ו-``repr``, ולכן
    היא יציבה; שמות dunder לא מועברים, אחרת ``__dict__`` של הדמה דולף דרך ``__getattr__``.
    כל השאר עובר לדמה כמו שהוא.

    משותפת לכל טסט שצריך גטר מקוּש שבאמת זוכר ערך ישן (``tests/test_mcp_content_sha256.py``,
    ``tests/test_mcp_is_latest.py``) — שם מחממים את הקאש, כותבים בלי לבטל אותו, ובודקים
    שהקוד קרא טרי.
    """

    __slots__ = ("_inner",)

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_inner"), name)

    def __repr__(self):
        return "StableKeyCollection(code_snippets)"
