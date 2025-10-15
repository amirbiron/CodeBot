.. _static-checklist:

Static Performance & Security Checklist (gzip/br, Cache, SRI)
=============================================================

מטרה
-----
להבטיח טעינה מהירה ובטוחה של נכסים סטטיים (CSS/JS/Images).

דחיסה (br/gzip)
----------------
- הפעילו דחיסה בצד השרת. לדוגמה עם Flask אפשר להשתמש ב-``Flask-Compress``.
- סדר עדיפויות: ``br`` (Brotli) עדיף על ``gzip`` כשזמין; ספקו fallbacks.

.. code-block:: python

   from flask_compress import Compress

   def init_app(app):
       Compress(app)

כותרות Cache-Control
---------------------
- עבור קבצים עם fingerprint בשם (למשל ``app.<hash>.css``):

.. code-block:: text

   Cache-Control: public, max-age=31536000, immutable

- עבור קבצים בלי fingerprint (משתנים לעיתים קרובות):

.. code-block:: text

   Cache-Control: no-cache

Subresource Integrity (SRI)
---------------------------
- בעת טעינה מ-CDN, הוסיפו ``integrity`` + ``crossorigin``.
- חישוב ``sha384``:

.. code-block:: sh

   openssl dgst -sha384 -binary < file.min.css | openssl base64 -A

.. code-block:: html

   <link rel="stylesheet" href="https://cdn.example.com/style.min.css"
         integrity="sha384-<BASE64_HASH>" crossorigin="anonymous">

בדיקות ידניות (Copy‑Paste)
--------------------------
.. code-block:: sh

   # ודאו דחיסה
   curl -I https://<host>/static/app.css | rg -i "content-encoding|cache-control"

   # בדיקת SRI (בטעינה דרך דפדפן/CI)
   # טעינת הקובץ עם hash שגוי אמורה להיחסם ע"י הדפדפן

Best Practices
--------------
- **קונסיסטנטיות**: שמרו על fingerprint לכל נכס ארוך-חיים.
- **צמצום**: מיניפיקציה לקובצי CSS/JS לפני פריסה.
- **HTTP/2**: העדיפו איגוד בקשות (bundling) באופן מושכל ולא מופרז.
- **TLS מודרני**: ודאו תמיכה ב-TLS עדכני, HSTS, ו-OCSP stapling.
- **SRI עדכני**: עדכנו hash בכל שינוי גרסה.

Gotchas
-------
- **SRI mismatch**: hash לא תואם יגרום לחסימה; ודאו התאמה מדויקת.
- **double-compression**: אל תדחסו קבצים שכבר דחוסים (``.br``/``.gz`` מוכנים מראש).
- **Caching אגרסיבי לקבצים דינמיים**: הימנעו מ-``immutable`` לקבצים ללא fingerprint.
