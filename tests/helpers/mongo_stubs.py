"""דמויות מונגו משותפות לטסטים.

**למה משותף:** ``__getitem__`` שוכפל בארבע מחלקות דמה בשני קבצים. אם חוזה
הגישה של pymongo ישתנה, ארבעה עותקים יצטרכו להשתנות יחד — וכזה תיקון תמיד
מפספס אחד.

**החוזה שמדומה כאן:** ב-pymongo 4.15.3 גם ``Database.__getitem__`` וגם
``Database.__getattr__`` מחזירות ``Collection(self, name)`` — אומת מול קוד
המקור המותקן. כלומר ``db["x"]`` ו-``db.x`` שקולים לחלוטין בפרודקשן. דמויות
שתומכות רק בגישת תכונה נשברות ברגע שקוד הייצור קורא את שם האוסף ממשתנה.
"""

from __future__ import annotations

import types
from typing import Any, Dict, List


class StubDBItemAccess:
    """מוסיפה ``db["name"]`` לדמה שכבר מחזיקה את האוספים כתכונות."""

    def __getitem__(self, name):
        return getattr(self, str(name))


class RecordingCollection:
    """אוסף שרושם כל פעולה, כדי שאפשר יהיה לשאול "האם נגעת ב-DB?"."""

    def __init__(self) -> None:
        self.delete_calls = 0
        self.dropped: List[str] = []
        self.created: List[Dict[str, Any]] = []
        self._info: Dict[str, Any] = {}

    def delete_many(self, _query):
        self.delete_calls += 1
        return types.SimpleNamespace(deleted_count=0)

    def index_information(self):
        return dict(self._info)

    def drop_index(self, name):
        self.dropped.append(str(name))
        self._info.pop(str(name), None)

    def create_index(self, keys, **kwargs):
        self.created.append({"keys": list(keys), **kwargs})
        name = str(kwargs.get("name") or "idx")
    def create_index(self, keys, **kwargs):
        self.created.append({"keys": list(keys), **kwargs})
        name = str(kwargs.get("name") or "idx")
        info = {"key": list(keys)}
        if "expireAfterSeconds" in kwargs:
            info["expireAfterSeconds"] = kwargs["expireAfterSeconds"]
        if kwargs.get("unique"):
            info["unique"] = True
        self._info[name] = info
        return name
class RecordingDB:
    """דמה של ``Database`` שיוצרת אוספים לפי דרישה ורושמת מה נעשה בהם.

    יוצרת אוסף בכל שם שמבקשים — וזה מה שמאפשר לבדוק שקוד התחזוקה ניגש
    לאוסף ששמו נקבע ב-``COLLECTION_NAME`` ולא לשם קשיח.
    """

    def __init__(self) -> None:
        object.__setattr__(self, "collections", {})

    def __getitem__(self, name):
        return self.collections.setdefault(str(name), RecordingCollection())

    def __getattr__(self, name):
        if str(name).startswith("_") or name == "collections":
            raise AttributeError(name)
        return self[name]

    def touched(self) -> Dict[str, Any]:
        """אילו אוספים נמחקו או הופל בהם אינדקס."""
        return {
            name: (coll.delete_calls, list(coll.dropped))
            for name, coll in self.collections.items()
            if coll.delete_calls or coll.dropped
        }
