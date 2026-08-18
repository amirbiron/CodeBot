from __future__ import annotations

import re
from typing import Any, Dict, Optional

# מבנה טוקן של בוט טלגרם: מזהה מספרי, נקודתיים, ואז מחרוזת ארוכה.
# כתובות ה-API נבנות כ-https://api.telegram.org/bot<TOKEN>/method — ולכן כל טקסט
# שנגזר מכתובת כזו (הודעת שגיאה, לוג, אירוע Sentry) עלול לשאת את הטוקן במלואו.
_BOT_TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{20,}")

TOKEN_PLACEHOLDER = "<REDACTED>"


def redact_bot_token(value: Any) -> Any:
    """מחליף כל טוקן בוט שמופיע בטקסט בסימון ``<REDACTED>``.

    מחזיר ``None`` כפי שהוא, וכל ערך אחר מומר למחרוזת מנוקה. זו נקודת הניקוי
    היחידה בקוד — גם ``TelegramAPIError`` וגם מסנני ה-Sentry נשענים עליה.
    """
    if value is None:
        return None
    try:
        text = value if isinstance(value, str) else str(value)
    except Exception:
        return value
    return _BOT_TOKEN_RE.sub(TOKEN_PLACEHOLDER, text)


def redact_bot_token_deep(obj: Any, _depth: int = 0) -> Any:
    """מנקה טוקנים מכל המחרוזות בתוך מבנה נתונים מקונן (dict/list/tuple).

    נועד למסנני Sentry: אירוע שגיאה פורש את הטוקן על פני כמה שדות (גוף החריגה,
    הודעת הלוג, breadcrumbs), ורשימת שדות קבועה תמיד תפספס אחד. במקום זה עוברים
    על כל המבנה. העומק מוגבל כדי לא להיתקע על מבנים מעגליים.
    """
    if _depth > 12:
        return obj
    if isinstance(obj, str):
        return redact_bot_token(obj)
    if isinstance(obj, dict):
        return {k: redact_bot_token_deep(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        cleaned = [redact_bot_token_deep(v, _depth + 1) for v in obj]
        return type(obj)(cleaned) if isinstance(obj, tuple) else cleaned
    return obj


def _truncate(text: Any, limit: int = 800) -> str:
    try:
        s = str(text)
    except Exception:
        s = ""
    s = s.strip()
    if limit and len(s) > limit:
        return s[: max(0, limit - 1)] + "…"
    return s


class TelegramAPIError(RuntimeError):
    """שגיאה מפורטת כאשר Telegram Bot API מחזיר ok=false (או תגובה לא תקינה)."""

    def __init__(
        self,
        *,
        error_code: Optional[int],
        description: str,
        url: Optional[str] = None,
        http_status: Optional[int] = None,
        payload: Any = None,
    ) -> None:
        self.error_code = error_code
        # ניקוי הטוקן כבר כאן, לפני ההשמה: כך גם ``self.url``/``self.description``
        # וגם טקסט החריגה נקיים, ולא משנה מי יקרא אותם או ירשום אותם ללוג.
        self.description = redact_bot_token(str(description or "").strip())
        self.url = redact_bot_token(url)
        self.http_status = http_status
        self.payload = redact_bot_token(payload) if isinstance(payload, str) else payload
        msg = f"Telegram API error"
        if error_code is not None:
            msg += f" error_code={error_code}"
        if self.description:
            msg += f" description={self.description}"
        if http_status is not None:
            msg += f" http_status={http_status}"
        if self.url:
            msg += f" url={self.url}"
        super().__init__(msg)


def parse_telegram_json_from_response(resp: Any, *, url: Optional[str] = None) -> Dict[str, Any]:
    """ממיר Response (requests/http_sync) ל-JSON dict של Telegram.

    זורק TelegramAPIError אם אי אפשר לפרסר JSON או אם מבנה התגובה לא dict.
    """
    http_status: Optional[int]
    try:
        http_status = int(getattr(resp, "status_code", 0) or 0) or None
    except Exception:
        http_status = None
    if url is None:
        try:
            url = str(getattr(resp, "url", "") or "") or None
        except Exception:
            url = None

    try:
        data = resp.json()
    except Exception:
        # Telegram בדרך כלל מחזיר JSON גם בשגיאות. אם לא, נשלוף טקסט לצורכי דיבוג.
        body_preview = None
        try:
            body_preview = _truncate(getattr(resp, "text", None) or getattr(resp, "content", None))
        except Exception:
            body_preview = None
        raise TelegramAPIError(
            error_code=None,
            description=f"telegram response is not valid json body={body_preview or '—'}",
            url=url,
            http_status=http_status,
            payload=body_preview,
        )

    if not isinstance(data, dict):
        raise TelegramAPIError(
            error_code=None,
            description=f"telegram response json is not an object type={type(data).__name__}",
            url=url,
            http_status=http_status,
            payload=data,
        )
    return data


def require_telegram_ok(payload: Any, *, url: Optional[str] = None) -> Dict[str, Any]:
    """מוודא ש-Telegram החזיר ok=True; אחרת זורק TelegramAPIError עם error_code/description."""
    if not isinstance(payload, dict):
        raise TelegramAPIError(
            error_code=None,
            description=f"telegram payload is not a dict type={type(payload).__name__}",
            url=url,
            http_status=None,
            payload=payload,
        )
    ok = payload.get("ok")
    if ok is True:
        return payload

    raw_code = payload.get("error_code")
    code: Optional[int]
    try:
        code = int(raw_code) if raw_code is not None else None
    except Exception:
        code = None
    desc = _truncate(payload.get("description"), 500) or "telegram ok=false"
    raise TelegramAPIError(
        error_code=code,
        description=desc,
        url=url,
        http_status=None,
        payload=payload,
    )

