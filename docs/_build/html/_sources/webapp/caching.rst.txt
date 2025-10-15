.. _webapp-caching:

Caching & HTTP Validators (ETag / Last-Modified / 304)
======================================================

למה זה חשוב?
--------------
**להקטין רוחב‑פס וזמני תגובה**: אם התוכן לא השתנה, נחזיר ``304 Not Modified`` במקום גוף מלא.
כך דפדפנים ולקוחות יכולים להשתמש במטמון מקומי בצורה בטוחה ויעילה.

עקרונות בסיס
-------------
- **ETag**: מזהה גרסה של המשאב. יכול להיות חזק (``"abc123"``) או חלש (``W/"abc123"``).
- **Last-Modified**: זמן העדכון האחרון בפורמט HTTP (RFC 1123).
- **If-None-Match / If-Modified-Since**: כותרות מהלקוח שמאפשרות לוודא אם יש שינוי.
- אם אין שינוי – מחזירים ``304`` וכוללים שוב את הכותרות ``ETag`` ו-``Last-Modified``.

מתכון: Flask + werkzeug
------------------------
הדוגמה הבאה מציגה זרימת מימוש בטוחה, כולל סדר בדיקות נכון וקיזוז מיקרו‑שניות להשוואה יציבה.

.. code-block:: python

   from werkzeug.http import http_date, parse_date
   from flask import request, Response

   def build_validators(hash_value: str, updated_at) -> tuple[str, str]:
       """יוצר ערכי ETag (חלש) ו-Last-Modified מפורמטים לתשובה.

       updated_at חייב להיות timezone-aware (UTC) כדי למנוע השוואות שגויות.
       """
       etag = f'W/"{hash_value}"'
       last_modified = http_date(updated_at)
       return etag, last_modified

   def maybe_not_modified(hash_value: str, updated_at, body: bytes, mimetype: str = "text/html; charset=utf-8"):
       etag, last_modified = build_validators(hash_value, updated_at)

       # בדיקת ETag (עדיפות ראשונה)
       if request.headers.get('If-None-Match') == etag:
           resp = Response(status=304)
           resp.headers['ETag'] = etag
           resp.headers['Last-Modified'] = last_modified
           return resp

       # בדיקת Last-Modified (עדיפות שנייה)
       ims = request.headers.get('If-Modified-Since')
       parsed_ims = parse_date(ims) if ims else None
       if parsed_ims and updated_at.replace(microsecond=0) <= parsed_ims:
           resp = Response(status=304)
           resp.headers['ETag'] = etag
           resp.headers['Last-Modified'] = last_modified
           return resp

       # 200 OK – יש לצרף את הכותרות כדי לאפשר אימות בבקשות הבאות
       resp = Response(body, mimetype=mimetype)
       resp.headers['ETag'] = etag
       resp.headers['Last-Modified'] = last_modified
       return resp

בדיקות ידניות (Copy‑Paste)
--------------------------
.. code-block:: sh

   # בקשה רגילה – קבל ETag ו-Last-Modified
   curl -i https://<host>/file/<id>

   # שליחת If-None-Match עם ה-ETag שהתקבל — מצופה 304
   curl -i -H 'If-None-Match: W/"abc123..."' https://<host>/file/<id>

   # שליחת If-Modified-Since עם זמן קודם/שווה — מצופה 304
   curl -i -H 'If-Modified-Since: Tue, 15 Nov 1994 12:45:26 GMT' https://<host>/file/<id>

Checklist למימוש נכון
----------------------
- להחליט על אסטרטגיית ETag: חזק (hash של התוכן) או חלש (גרסה/עדכון).
- לשמור ``updated_at`` כ-UTC aware; להשוות בלי מיקרו‑שניות.
- תמיד לצרף ``ETag`` ו-``Last-Modified`` גם בתשובת ``200`` וגם ב-``304``.
- להקדים בדיקת ``If-None-Match`` לפני ``If-Modified-Since``.
- ליישר קו עם שכבת קאש פנימית (MRU/LRU) כדי למנוע מירוצים.

Gotchas נפוצים
--------------
- **ETag לא יציב**: חישוב hash שכולל שדות משתנים (כמו timestamps) יגרום לפספוסי קאש.
- **Timezone naive/aware**: השוואה בין ערכים ללא אזור זמן לערכים עם אזור זמן תיכשל.
- **מיקרו‑שניות**: לקוחות מסוימים חותכים לרזולוציית שנייה; בצעו ``replace(microsecond=0)`` להשוואה.
- **שינוי ללא עדכון ``updated_at``**: ודאו שהשדה מייצג את מצב התוכן בפועל.

שילוב עם Cache-Control
-----------------------
ניתן להוסיף ``Cache-Control`` בצד השרת בהתאם למדיניות (למשל: משאבים סטטיים עם פינגרפרינט בשם הקובץ):

.. code-block:: text

   Cache-Control: public, max-age=31536000, immutable

קישורים נוספים
---------------
- `RFC 7232 – HTTP/1.1 Conditional Requests <https://httpwg.org/specs/rfc7232.html>`_
- `Flask Response <https://flask.palletsprojects.com/en/latest/api/#flask.Response>`_
- `werkzeug.http <https://werkzeug.palletsprojects.com/en/latest/utils/#module-werkzeug.http>`_
