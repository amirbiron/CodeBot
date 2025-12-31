Google Drive Service
====================

סקירה
-----
שירות גוגל דרייב אחראי לאימות (Device Flow), ניהול טוקנים, יצירת ZIP, והעלאות לתיקיות ממוסלות לפי קטגוריה/תאריך/ריפו.

הערות OAuth
------------
- שימור refresh_token: בשמירה מתמזג עם טוקנים קיימים כדי לא למחוק רענון שלא הוחזר.
- רענון טוקן: ניסיון רענון עם טיפול כשלים שקט.

מבני קבצים
-----------
- שמות קבצים: BKP_{label}_{entity}_v{n}_{date}.zip
- נתיב משנה: {קטגוריה}/{YYYY}/{MM-DD} ולפי ריפו אם רלוונטי.

API (autodoc)
-------------
.. automodule:: services.google_drive_service
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

