"""קישורי השיתוף של ייצוא ה-HTML המעוצב (``/shared/styled/<token>``) — המפרט שהמסד והוובאפ חולקים.

הוובאפ הוא הכותב היחיד לאוסף, בשני מסלולים: ``api_create_styled_share`` ב-``webapp/app.py`` — משתמש מחובר, מעמוד
הקובץ — ו-``markdown_editor_create_share`` — גולש בעורך הציבורי (``/markdown-editor``), בלי התחברות, עם
``origin`` = :data:`STYLED_SHARE_ORIGIN_PUBLIC_EDITOR`. מוחקים: הביטול של המחובר (``api_revoke_styled_share``), המחיקה
של הגולש במפתח המחיקה (``markdown_editor_delete_share``), והמחיקה של אדמין (``admin_delete_styled_share``). הוא גם
הקורא היחיד (``public_shared_styled``, ורשימת הקישורים של קובץ, ``api_list_styled_shares``).
``DatabaseManager._create_indexes``, שהוובאפ עובר בכל עלייה, מצהיר על האינדקסים מכאן.

**שתי צורות של מסמך.** הראשונה — ``styled_html``, העמוד שהשרת בנה ב-Python-Markdown ברגע השיתוף. השנייה
(``format`` = :data:`STYLED_SHARE_FORMAT_MARKDOWN`) — הטקסט של הגרסה ששותפה (``markdown``) ותמונה של הערכה ברגע
השיתוף (``theme``), והדפדפן של מי שפותח את הקישור מרנדר אותם באותו מנוע כמו התצוגה החיה. קישורים מהצורה הראשונה
נשארים כמו שהם, ומוגשים כמו קודם. הקישור מהעורך הציבורי הוא תמיד מהצורה השנייה, והשדות שלה נבנים לשני הכותבים
באותה פונקציה (:func:`markdown_share_fields`).

**טהור** — בלי pymongo ובלי מסד, מאותה סיבה של ``mcp_uploads.py``: מודול תחת ``database/`` היה גורר את
``database/__init__.py``, שיוצר ``DatabaseManager()`` גלובלי בזמן הייבוא.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from typing import Any

__all__ = [
    "STYLED_SHARES_COLLECTION",
    "STYLED_SHARE_BY_FILE_INDEX_NAME",
    "STYLED_SHARE_DELETE_KEY_HASH_FIELD",
    "STYLED_SHARE_EXPIRES_FIELD",
    "STYLED_SHARE_FORMAT_MARKDOWN",
    "STYLED_SHARE_MAX_MARKDOWN_BYTES",
    "STYLED_SHARE_ORIGIN_FIELD",
    "STYLED_SHARE_ORIGIN_PUBLIC_EDITOR",
    "STYLED_SHARE_PUBLIC_EDITOR_RECENT_INDEX_NAME",
    "STYLED_SHARE_TOKEN_INDEX_NAME",
    "STYLED_SHARE_TOKEN_RE",
    "STYLED_SHARE_TTL_INDEX_NAME",
    "markdown_share_fields",
    "new_styled_share_secret",
    "styled_share_delete_key_hash",
    "styled_shares_indexes",
]

STYLED_SHARES_COLLECTION = "styled_shares"

#: מועד הפקיעה של קישור זמני, כ-``datetime`` (ולא מחרוזת: מסמך שהשדה שלו אינו תאריך לא נמחק לעולם).
#: לקישור קבוע הערך ``None``, ו-TTL מדלג על מסמך שהשדה שלו אינו תאריך
#: (https://www.mongodb.com/docs/manual/core/index-ttl/), כך שהוא נשאר.
STYLED_SHARE_EXPIRES_FIELD = "expires_at"

STYLED_SHARE_TTL_INDEX_NAME = "styled_shares_ttl"
STYLED_SHARE_TOKEN_INDEX_NAME = "styled_shares_token"
STYLED_SHARE_BY_FILE_INDEX_NAME = "styled_shares_by_file"

#: הערך של ``format`` במסמך מהצורה השנייה (הטקסט ותמונה של הערכה). מסמך בלי ``format`` הוא מהצורה הראשונה.
STYLED_SHARE_FORMAT_MARKDOWN = 2

#: התקרה על הטקסט של שיתוף מהצורה השנייה, בבתים (UTF-8). מעליה השיתוף נדחה (413), ולא נחתך.
#:
#: הטקסט מרונדר בדפדפן של מי שפותח את הקישור, ב-thread הראשי, והעמוד קופא בזמן הרינדור. נמדד ב-Chromium ב-6.11.2026
#: (בדיקת ההיתכנות של ההעברה לדפדפן, על טקסט ההדגמה של העורך ועוד מקרי קצה): 680KB — ‏1.3 שניות, ‏3.5 שניות בהאטה
#: פי 4 של המעבד ו-5.6 בהאטה פי 6; ‏2.7MB — ‏4.9 שניות, ו-18.7 בהאטה פי 4. מגה אחד הוא גם הסף שמעליו עמוד הקובץ
#: מפסיק להציג את הטקסט (``MAX_DISPLAY_SIZE`` ב-``view_file``). התקרה היא על הטקסט מהמסד (הקובץ של המשתמש), ולא על
#: גוף הבקשה; גוף הבקשה והקצב מוגבלים בנפרד.
STYLED_SHARE_MAX_MARKDOWN_BYTES = 1024 * 1024

#: מאיפה נוצר הקישור. רק הכותב של העורך הציבורי כותב את השדה (:data:`STYLED_SHARE_ORIGIN_PUBLIC_EDITOR`), ומסמך בלעדיו
#: הוא של משתמש מחובר: לכל הקישורים שנוצרו לפני העורך הציבורי אין אותו בכל מקרה, ולכן הקורא מבחין רק לפי השוויון
#: לערך הזה, ולא לפי קיום השדה.
STYLED_SHARE_ORIGIN_FIELD = "origin"
STYLED_SHARE_ORIGIN_PUBLIC_EDITOR = "public_editor"

#: ה-hash (SHA-256, hex) של מפתח המחיקה, בקישור מהעורך הציבורי. המפתח עצמו לא נשמר: הגולש מקבל אותו פעם אחת, בתוך קישור
#: המחיקה, ומי שקורא את המסד לא יכול למחוק בשמו.
STYLED_SHARE_DELETE_KEY_HASH_FIELD = "delete_key_sha256"

STYLED_SHARE_PUBLIC_EDITOR_RECENT_INDEX_NAME = "styled_shares_public_editor_recent"

#: כמה בתים אקראיים במזהה של קישור ובמפתח המחיקה (``secrets.token_urlsafe``). ‏256 ביט — אי אפשר לנחש.
_SECRET_BYTES = 32

#: הצורה של מזהה ושל מפתח מחיקה: ה-base64 של :data:`_SECRET_BYTES` בתים בלי ה-``=`` שבסוף, כמו ש-``token_urlsafe`` מחזיר.
#: האורך נגזר מהמספר ולא מוקלד, כדי שהבדיקה תשתנה יחד איתו.
STYLED_SHARE_TOKEN_RE = re.compile(
    r"[A-Za-z0-9_-]{%d}" % len(base64.urlsafe_b64encode(bytes(_SECRET_BYTES)).rstrip(b"="))
)


def new_styled_share_secret() -> str:
    """מזהה חדש לקישור, או מפתח מחיקה חדש — אותה צורה לשניהם (:data:`STYLED_SHARE_TOKEN_RE`)."""
    return secrets.token_urlsafe(_SECRET_BYTES)


def styled_share_delete_key_hash(delete_key: str) -> str:
    """מה שנשמר במסד במקום מפתח המחיקה (:data:`STYLED_SHARE_DELETE_KEY_HASH_FIELD`).

    SHA-256 רגיל ולא hash איטי של סיסמה: המפתח הוא 256 ביט אקראיים, ואין מילון שאפשר לנסות מולו. ``delete_key`` חייב
    להיות בצורה של :data:`STYLED_SHARE_TOKEN_RE` (ASCII), והקורא בודק את זה לפני הקריאה.
    """
    return hashlib.sha256(delete_key.encode("ascii")).hexdigest()


def markdown_share_fields(markdown: str, theme: dict[str, Any]) -> dict[str, Any]:
    """השדות של מסמך מהצורה השנייה — לשני הכותבים (עמוד הקובץ והעורך הציבורי), כדי שלא יהיו שני עותקים של הצורה.

    ``theme`` הוא מה ש-``get_export_theme`` החזיר, ונשמר כולו: העמוד נבנה ממנו בכל צפייה, ושינוי מאוחר בערכה אינו משנה
    קישור שכבר נשלח. ``tests/test_public_editor_share.py`` בודק ששני הכותבים קוראים לפונקציה הזו.
    """
    return {
        "format": STYLED_SHARE_FORMAT_MARKDOWN,
        "markdown": markdown,
        "theme": dict(theme),
    }


def styled_shares_indexes() -> list[dict[str, Any]]:
    """הגדרות האינדקסים, בצורה ש-``safe_create_index`` מקבלת.

    ``required`` מסמן אינדקס של **התנהגות**: כשל שלו יוצא כאירוע ``db_styled_shares_index_missing`` ברמת
    error (``DatabaseManager._create_styled_shares_indexes``).
    """
    return [
        {
            # אף שורת קוד שלנו אינה מוחקת קישור שפקע. הקורא כבר עונה 404 על קישור כזה, ולכן ה-TTL הוא מה
            # שמוחק את ה-HTML (ומעכשיו את ה-Markdown) של המשתמש מהמסד, ולא רק מסתיר אותו.
            "keys": [(STYLED_SHARE_EXPIRES_FIELD, 1)],
            "name": STYLED_SHARE_TTL_INDEX_NAME,
            "expire_after_seconds": 0,
            # אינדקס קיים בשם הזה שאינו במפרט היה מתנגש, ובלי אכיפה ה-TTL לא היה נבנה לעולם.
            "enforce": True,
            "required": True,
        },
        {
            # הקורא מוצא קישור לפי ``token`` (``find_one``). ‏256 ביט אקראיים (``secrets.token_urlsafe(32)``)
            # אינם מתנגשים בפועל; האינדקס הייחודי הוא מה שהופך את "לא בפועל" ל"לא", ומונע סריקה מלאה.
            # כפילות קיימת הייתה מכשילה את היצירה, וזה מדווח באותו אירוע.
            "keys": [("token", 1)],
            "name": STYLED_SHARE_TOKEN_INDEX_NAME,
            "unique": True,
            "enforce": True,
            "required": True,
        },
        {
            # רשימת הקישורים של קובץ בחלון הייצוא (``api_list_styled_shares``): כל הקישורים של המשתמש לאותו שם קובץ —
            # הישות, ולא גרסה אחת שלה — מהחדש לישן. שוויון, ואחריו המיון (ESR). אינדקס ביצועים: בלעדיו הרשימה סורקת,
            # ולא שבורה, ולכן כשל שלו אינו אירוע error.
            "keys": [("user_id", 1), ("file_name", 1), ("created_at", -1)],
            "name": STYLED_SHARE_BY_FILE_INDEX_NAME,
            "required": False,
        },
        {
            # התקרה הכוללת של העורך הציבורי (``markdown_editor_create_share``) סופרת את הקישורים שנוצרו שם ב-24 השעות
            # האחרונות: שוויון על ``origin``, ואחריו טווח על ``created_at``. אינדקס ביצועים: בלעדיו הספירה סורקת את
            # האוסף, ולא שבורה, ולכן כשל שלו אינו אירוע error.
            "keys": [(STYLED_SHARE_ORIGIN_FIELD, 1), ("created_at", -1)],
            "name": STYLED_SHARE_PUBLIC_EDITOR_RECENT_INDEX_NAME,
            "required": False,
        },
    ]
