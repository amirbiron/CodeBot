.. _cursor-pagination:

Cursor-based Pagination (created_at / _id)
==========================================

למה?
-----
- **יציבות**: נמנע כפילויות או דילוגים כשפריטים חדשים נכנסים בין דפים.
- **ביצועים**: יעיל מ-``skip/limit`` בקולקציות גדולות, ומנצל אינדקסים קיימים.
- **פשטות**: קידוד קורסור קצר שניתן להעביר ב-URL.

עקרונות מיון יציב
------------------
- מיון ראשי לפי ``created_at`` (יורד לחדש→ישן) ומשני לפי ``_id`` באותו כיוון.
- הקורסור מכיל את הזוג ``{t, id}`` עבור הרשומה האחרונה שנראתה (timestamp + ObjectId).

קידוד/פענוח קורסור (Python)
----------------------------
.. code-block:: python

   import base64
   import json
   from datetime import datetime, timezone
   from bson import ObjectId

   def encode_cursor(dt: datetime, oid: ObjectId) -> str:
       # dt חייב להיות timezone-aware (UTC)
       payload = {
           "t": int(dt.replace(tzinfo=timezone.utc).timestamp()),
           "id": str(oid),
       }
       raw = json.dumps(payload, separators=(",", ":")).encode()
       return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

   def decode_cursor(token: str) -> tuple[datetime, ObjectId]:
       # הוספת padding חסר ל-Base64 URL-safe
       padded = token + "=" * (-len(token) % 4)
       data = base64.urlsafe_b64decode(padded)
       obj = json.loads(data.decode())
       dt = datetime.fromtimestamp(int(obj["t"]), tz=timezone.utc)
       oid = ObjectId(obj["id"])
       return dt, oid

תבנית שאילתה (חדש → ישן)
------------------------
הבא דף נוסף לאחר ``last_dt, last_id``:

.. code-block:: json

   {
     "$or": [
       { "created_at": { "$lt": "<last_dt>" } },
       {
         "$and": [
           { "created_at": { "$eq": "<last_dt>" } },
           { "_id": { "$lt": { "$oid": "<last_id>" } } }
         ]
       }
     ]
   }

PyMongo – דוגמה מלאה
---------------------
.. code-block:: python

   from pymongo import DESCENDING

   PAGE_SIZE = 20

   def list_snippets_page(coll, user_id, cursor: str | None):
       query = {"user_id": user_id}
       sort = [("created_at", DESCENDING), ("_id", DESCENDING)]

       if cursor:
           last_dt, last_oid = decode_cursor(cursor)
           query.update({
               "$or": [
                   {"created_at": {"$lt": last_dt}},
                   {"$and": [
                       {"created_at": {"$eq": last_dt}},
                       {"_id": {"$lt": last_oid}},
                   ]},
               ]
           })

       docs = list(coll.find(query).sort(sort).limit(PAGE_SIZE))

       # הכנת next_cursor
       next_cursor = None
       if len(docs) == PAGE_SIZE:
           last = docs[-1]
           next_cursor = encode_cursor(last["created_at"], last["_id"])

       return docs, next_cursor

דפדוף לאחור (ישן → חדש)
------------------------
- הפכו את כיוון המיון ל-``ASCENDING`` בשני השדות.
- החליפו את תנאי הסף ל-``$gt`` במקום ``$lt``.
- שמרו על זוג השדות זהה כדי להבטיח יציבות.

בדיקות ידניות (Copy‑Paste)
--------------------------
.. code-block:: sh

   # דף ראשון
   curl -s "https://<host>/files?user_id=123&limit=20" | jq -r .next_cursor

   # דף שני (עם next_cursor מהתגובה)
   curl -s "https://<host>/files?user_id=123&limit=20&cursor=<TOKEN>" | jq .

שיטות עבודה מומלצות
--------------------
- **אינדקסים**: ודאו אינדקס מרוכב ``(user_id, created_at, _id)`` או ``(user_id, created_at)`` + מיון משני על ``_id``.
- **UTC תמיד**: שמרו את ``created_at`` כ-UTC aware לקבלת השוואות עקביות.
- **Page Size קבוע**: נוח לחשב ``has_more``/``next_cursor``.
- **קורסור אטום**: התייחסו אליו כטוקן – אין תלות פנימית במבנה.

Gotchas נפוצים
--------------
- **כפילות/חורים**: אם המיון לא יציב (ללא ``_id``), ייתכנו כפילויות או דילוגים.
- **Padding חסר**: Base64 URL-safe עלול לדרוש padding; הוסיפו ``=`` לפי הצורך.
- **Timezone naive/aware**: ערבוב יגרום להשוואות שגויות; אחדו ל-UTC aware.
- **שגיאת כיוון**: שימוש ב-``$gt`` במקום ``$lt`` (או להפך) ישנה את הכיוון.

קישורים
-------
- `MongoDB Sort <https://www.mongodb.com/docs/manual/reference/method/cursor.sort/>`_
- `PyMongo Sort <https://pymongo.readthedocs.io/en/stable/examples/aggregation.html#sorting>`_
- `ObjectId <https://www.mongodb.com/docs/manual/reference/method/ObjectId/>`_
