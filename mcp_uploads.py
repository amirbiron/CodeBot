"""העלאות ממתינות של שירות ה-MCP — המפרט שהמסד והשירות חולקים.

``PUT /api/agent/upload`` (``mcp_server/uploads.py``) שומר כאן טקסט לזמן קצוב,
ו-``codekeeper_save_file`` / ``codekeeper_append_file`` צורכים אותו לפי
``upload_id``. שני צדדים צריכים את אותו מפרט: ``DatabaseManager._create_indexes``,
שמצהיר על האינדקסים בכל עלייה — גם של שירות ה-MCP — ו-``ProductionBackend``,
שמאמת את ה-TTL בקריאה חוזרת לפני שהוא מקבל העלאה. מפרט בשני מקומות היה סוטה
בשקט, ומונגו דוחה ב-code 85/86 אינדקס בשם קיים עם מפתחות אחרים — כלומר סטייה
של תו אחד הופכת את אחת ההצהרות לכשל קבוע (``docs/performance-sticky-notes.rst``,
"ושלושה מקומות, לא אחד").

**טהור** — ``re``, ``secrets``, ``typing`` ו-``ttl_index`` ותו לא, בלי pymongo
ובלי מסד. אותה תבנית של ``file_deletion.py``, ומאותה סיבה: מודול תחת
``database/`` היה גורר את ``database/__init__.py``, שיוצר ``DatabaseManager()``
גלובלי בזמן הייבוא, ושירות ה-MCP מייבא את ``database`` רק בתוך ``create_app``.

**המספרים קבועים בקוד ולא משתני סביבה**, כמו קבועי הפריימר: הם חלק מהחוזה
שתיאור הכלי מציג לסוכן, ושינוי שלהם עובר PR.
"""

from __future__ import annotations

import re
import secrets
from typing import Any

from ttl_index import is_ttl_index

__all__ = [
    "MAX_PENDING_UPLOADS",
    "MCP_UPLOADS_COLLECTION",
    "UPLOAD_EXPIRES_FIELD",
    "UPLOAD_ID_BYTES",
    "UPLOAD_ID_LENGTH",
    "UPLOAD_TTL_EXPIRE_AFTER_SECONDS",
    "UPLOAD_TTL_INDEX_NAME",
    "UPLOAD_TTL_SECONDS",
    "UploadStorageUnavailable",
    "is_upload_id",
    "is_upload_ttl_index",
    "mcp_uploads_indexes",
    "new_upload_id",
]

MCP_UPLOADS_COLLECTION = "mcp_uploads"

#: כמה זמן העלאה ממתינה לצריכה, בשניות. מספיק לקריאת ``curl`` ולקריאת כלי
#: אחריה, וקצר מספיק כדי שתוכן שנשכח לא יישאר.
UPLOAD_TTL_SECONDS = 600

#: כמה העלאות חיות מותרות למשתמש בו-זמנית. זה החסם על האחסון של משתמש אחד:
#: כל העלאה עד ``max_code_size()`` תווים, ובמקרה הגרוע תו הוא ארבעה בתים.
MAX_PENDING_UPLOADS = 5

#: השדה שאינדקס ה-TTL קורא. **הוא נושא את מועד המחיקה עצמו**, ולא את מועד
#: היצירה: ``expireAfterSeconds`` הוא ``0``, ולכן ``UPLOAD_TTL_SECONDS`` מוגדר
#: במקום אחד — בכתיבה. TTL על ``created_at`` עם משך היה מכפיל את מקור האמת.
UPLOAD_EXPIRES_FIELD = "expires_at"

UPLOAD_TTL_INDEX_NAME = "mcp_uploads_ttl"

#: ``0``: המסמך נמחק במועד שבשדה — *"specify an expireAfterSeconds value of 0"*
#: ב-"Expire Documents at a Specific Clock Time"
#: (https://www.mongodb.com/docs/manual/tutorial/expire-data/). **המחיקה עצלה**
#: — המוניטור רץ בערך פעם בדקה — ולכן כל קורא מסנן ``expires_at > now`` בעצמו.
UPLOAD_TTL_EXPIRE_AFTER_SECONDS = 0

#: בתים אקראיים במזהה. ``secrets.token_urlsafe`` מקודד אותם ב-base64 בטוח
#: ל-URL בלי ריפוד (``Lib/secrets.py``), כלומר ``ceil(4n/3)`` תווים.
UPLOAD_ID_BYTES = 32
UPLOAD_ID_LENGTH = (4 * UPLOAD_ID_BYTES + 2) // 3

#: הצורה של מזהה שיצא מ-:func:`new_upload_id`. טווחים מפורשים ולא ``\w``,
#: כי ``\w`` על ``str`` תופס גם אותיות שאינן ASCII.
_UPLOAD_ID_RE = re.compile(rf"[A-Za-z0-9_-]{{{UPLOAD_ID_LENGTH}}}")


class UploadStorageUnavailable(Exception):
    """אחסון ההעלאות לא ענה — תקלת מסד, לא "אין העלאה".

    ``ProductionBackend`` מתרגם אליה שגיאות pymongo בלבד, ורושם אותן שם. הקוראים —
    הראוט (503) והכלים (``upload_storage_unavailable``) — תופסים רק אותה, כדי
    שבאג (``TypeError``, ``AttributeError``) לא יוצג כתקלה רגעית.
    """


def new_upload_id() -> str:
    """מזהה חדש: ``UPLOAD_ID_BYTES`` בתים מ-``secrets``, ולא מזהה מבוסס-זמן (U1)."""
    return secrets.token_urlsafe(UPLOAD_ID_BYTES)


def is_upload_id(value: Any) -> bool:
    """האם ``value`` בצורה ש-:func:`new_upload_id` מייצר. הערך מגיע מהסוכן (U3)."""
    return isinstance(value, str) and _UPLOAD_ID_RE.fullmatch(value) is not None


def mcp_uploads_indexes() -> list[dict[str, Any]]:
    """הגדרות האינדקסים, בצורה ש-``safe_create_index`` מקבלת.

    ``required`` מסמן אינדקס של **התנהגות**: כשל שלו יוצא כאירוע ברמת error
    (``DatabaseManager._create_mcp_uploads_indexes``). אינדקס שאינו ``required``
    הוא ביצועים, וכשל שלו הוא איטיות.
    """
    return [
        {
            # אף שורת קוד שלנו אינה מוחקת העלאה שלא נצרכה. בלי האינדקס הזה
            # "חמש העלאות ממתינות" הוא חסם על הנייר: הספירה מדלגת על מה שפקע,
            # והתוכן נשאר לצמיתות.
            "keys": [(UPLOAD_EXPIRES_FIELD, 1)],
            "name": UPLOAD_TTL_INDEX_NAME,
            "expire_after_seconds": UPLOAD_TTL_EXPIRE_AFTER_SECONDS,
            # אינדקס קיים בשם הזה שאינו במפרט היה מתנגש, ובלי אכיפה ה-TTL לא
            # היה נבנה לעולם — כמו אצל סל המיחזור.
            "enforce": True,
            "required": True,
        },
        {
            # מזהה ההעלאה. 256 ביט אקראיים אינם מתנגשים בפועל; האינדקס
            # הייחודי הוא מה שהופך את "לא בפועל" ל"לא".
            "keys": [("upload_id", 1)],
            "name": "mcp_uploads_upload_id",
            "unique": True,
            "enforce": True,
            "required": True,
        },
        {
            # ספירת הממתינות של משתמש (שוויון על ``user_id``, טווח ומיון על
            # ``expires_at``) ומסנן הצריכה.
            "keys": [("user_id", 1), (UPLOAD_EXPIRES_FIELD, 1)],
            "name": "mcp_uploads_user_expires",
        },
    ]


def is_upload_ttl_index(index_info: Any) -> bool:
    """האם שורה מ-``list_indexes()`` היא ה-TTL של ההעלאות כפי שהוצהר.

    בלי מסנן חלקי: TTL חלקי היה מוחק רק חלק מההעלאות. הבדיקה עצמה — ב-
    :func:`ttl_index.is_ttl_index`, אותה בדיקה של סל המיחזור.
    """
    return is_ttl_index(
        index_info,
        field=UPLOAD_EXPIRES_FIELD,
        expire_after_seconds=UPLOAD_TTL_EXPIRE_AFTER_SECONDS,
    )
