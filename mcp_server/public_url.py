"""כתובת השירות בפקודות ``curl`` שבתיאורי הכלים — מ-``MCP_SERVER_URL``, פעם אחת.

שני ראוטים מגיעים לסוכן כפקודה בתוך תיאור כלי: ההעלאה (``PUT /api/agent/upload``,
בתיאור ``upload_id``) וההורדה (``GET /api/agent/download``, בתיאור ``file_id`` של
``codekeeper_get_file`` ובתיאור ``codekeeper_list_versions``). שניהם צריכים את אותו
בסיס — הכתובת הציבורית של השירות — ולכן הבדיקה שלו יושבת כאן ולא בכל ראוט: עד
ההורדה היא חיה ב-``mcp_server/uploads.py`` בשם ``upload_url_for``, ועותק שני שלה
לראוט השני היה נסחף מהראשון (R6), וגם היה כותב שתי שורות WARNING בעלייה על אותה
תצורה שגויה. ``build_mcp`` קורא ל-:func:`public_base_for` פעם אחת, ומצרף לבסיס את
הנתיב של כל ראוט.

צרכן שלישי, מחוץ לשירות: עמוד ההגדרות בוובאפ מציג את הכתובת שמדביקים בלקוח —
הבסיס ואחריו :data:`MCP_ENDPOINT_PATH` (``_mcp_connect_url`` ב-
``webapp/routes/settings_routes.py``). הוא עובר באותה בדיקה, :func:`why_not_usable`,
כי גם שם הכתובת מגיעה לכל משתמש.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

#: ה-host בפקודות שבתיאורי הכלים, כשכתובת השירות אינה ידועה.
PLACEHOLDER_HOST = "<mcp-host>"

#: הנתיב שבו השירות מקבל את בקשות ה-MCP — מה שבא אחרי הבסיס בכתובת שמדביקים בלקוח.
#: הוא אינו נקבע כאן אלא ב-``mcp.streamable_http_app()`` (``build_app`` ב-
#: ``mcp_server/server.py``), והקבוע הוא עותק שלו. הטסט
#: ``test_every_route_answers_401_without_a_token_except_a_closed_list`` ב-
#: ``tests/test_mcp_uploads.py`` מוודא שהאפליקציה האמיתית מגישה אותו, ולכן שינוי
#: הנתיב מפיל טסט ולא את הכתובת שהמשתמש מעתיק.
MCP_ENDPOINT_PATH = "/mcp"


def why_not_usable(public_url: str) -> str | None:
    """למה הכתובת לא תיכנס לפקודה או לעמוד — או ``None`` כשהיא תקינה.

    הסיבה, ולא הערך: היא זו שנרשמת בלוג, ומה שנדחה עלול להיות בדיוק סיסמה
    בכתובת (K13). ``port`` נקרא כאן כדי שפורט שבור ייפול כאן, ולא בפקודה שהסוכן
    מריץ — ``SplitResult.port`` זורק ``ValueError`` על פורט שאינו מספר או שמחוץ
    לטווח (``urllib/parse.py``, ``_NetlocResultMixinBase.port``).
    """
    try:
        parts = urlsplit(public_url)
        hostname = parts.hostname
        _ = parts.port
    except ValueError:
        return "not a valid URL"
    if parts.scheme not in {"http", "https"}:
        return "scheme is not http or https"
    if not hostname:
        return "no host"
    if "@" in parts.netloc:
        return "carries a user name or password"
    if parts.query or parts.fragment:
        return "carries a query or a fragment"
    return None


def public_base_for(public_url: str | None) -> str:
    """הבסיס של הפקודות שבתיאורי הכלים — מ-``MCP_SERVER_URL`` כשהוא ידוע, בלי ``/`` בסוף.

    הערך מגיע מהסביבה (U3), והוא נכנס לתיאור שכל לקוח מקבל ב-``tools/list``.
    לכן רק ``http``/``https`` עם host ופורט תקין, **בלי** שם משתמש או סיסמה
    בכתובת (K13), ובלי query או fragment. כל צורה אחרת — ה-host המדומה, ולא ניחוש.
    המתקשר מצרף את הנתיב של הראוט (``UPLOAD_PATH``, ``DOWNLOAD_PATH``) — אותה הרכבה
    של ``consent_url`` ב-``mcp_server/app.py``: הבסיס, ואחריו הנתיב.

    **מה הבדיקה הזו אינה עושה: היא אינה הופכת את הערך לבטוח ל-shell.** נתיב כמו ``/$(id)``
    עובר אותה. הפקודות שבתיאורים מצטטות את הכתובת בנקודת ההרכבה (``_shell_word`` ב-
    ``mcp_server/server.py``), כי שם הדקדוק הוא של shell — וזה המקום היחיד שיודע אותו.

    **כתובת שלא הוגדרה וכתובת שנדחתה אינן אותו מצב.** בלי ``MCP_SERVER_URL`` (מצב
    PAT מקומי) הכתובת פשוט לא ידועה — מצב סטטי ומוכר, בלי לוג. כתובת שהוגדרה
    ונדחתה היא תצורה שגויה, והפקודות בתיאורים נשארות בלי host שאפשר להריץ; בלי
    WARNING היא הייתה נראית בדיוק כמו "לא הוגדר".
    """
    placeholder = f"https://{PLACEHOLDER_HOST}"
    if not isinstance(public_url, str) or not public_url:
        return placeholder
    reason = why_not_usable(public_url)
    if reason is not None:
        logger.warning(
            "MCP_SERVER_URL not used for the commands in the tool descriptions: %s — they show %s instead",
            reason, PLACEHOLDER_HOST,
        )
        return placeholder
    return public_url.rstrip("/")
