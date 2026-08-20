---
summary: 'מטרה: לשמר בטיחות טיפוסים ברורה, להקשיח מודולים בהדרגה, ולא להסתמך על `type: ignore`.'
---

# 📝 Type Hints – Best Practices

## אסטרטגיה: הקשחה הדרגתית
- התחילו ממודולים מרכזיים (DB, Web) והוסיפו טיפוסים ברורים לפונקציות ציבוריות.
- טפלו באזהרות MyPy נקודתית במקום `type: ignore` גורף.

---

## פרוטוקולים וסטאבים
- לפריטים ממשקי־הפעלה (למשל אוסף Mongo) – הגדירו `Protocol` כדי לאפשר החלפה/מוקינג בטסטים.

```python
from typing import Protocol, Any, Optional

class CollectionLike(Protocol):
    def find_one(self, query: dict[str, Any]) -> Optional[dict[str, Any]]: ...
    def insert_one(self, doc: dict[str, Any]) -> Any: ...
```

- עבור `ObjectId`/BSON – הימנעו מתלות קשה; העדיפו טיפוסים כלליים עם ולידציה בקוד.

דוגמאות מהקוד
--------------
- בפרויקט קיימים פרוטוקולים וממשקי גישה עקביים במודולים DB, למשל ב‑``database/manager.py`` נשענים על חתימות ברורות
  לאינדקסים ולפעולות CRUD. ההקשחה ההדרגתית משמרת תאימות טסטים.

הגדרות MyPy
------------
- הקובץ ``mypy.ini`` מחמיר מודולים מסוימים (למשל ``services.code_service``) ומאפשר החמרה הדרגתית.
- מומלץ להוסיף מודולים עם ``disallow_untyped_defs = True`` בהדרגה, ובמקביל לצמצם ``ignore_missing_imports`` כאשר אפשר.

מסלול מיגרציה
--------------
1. הוסיפו טיפוסים לפונקציות ציבוריות.
2. פירקו ביטויים מורכבים למשתנים מתוּגים.
3. החליפו ``Any`` בטיפוסים מדויקים יותר כאשר יש אינוואריאנט ברור.

---

## הנחיות לסוכנים
- אל תשנו חתימות קיימות ללא צורך (שבר תאימות).
- הימנעו מ-`type: ignore`; במקום זה:
  - פירוק ביטויים מורכבים למשתנים מתוּגים
  - שימוש ב-`cast` ממוקד רק כשיש אינוואריאנט ברור
- השתמשו ב-`Optional[T]` כשערך עלול להיות `None`.
- `typing.Any` – שימוש מבוקר בלבד, כנקודת קצה API או צד שלישי.

---

## דוגמאות קצרות

```python
from typing import Optional

def get_username(user_id: int) -> Optional[str]:
    user = repo.get(user_id)
    return user["name"] if user else None
```

```python
from typing import cast

value: object = get_value()
config = cast(dict[str, str], value)  # ידוע ממקור הפונקציה
```
