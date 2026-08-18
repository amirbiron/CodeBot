from __future__ import annotations

import re
from typing import Any, Dict, Optional

# מבנה טוקן של בוט טלגרם: מזהה מספרי, נקודתיים, ואז סוד באורך ~35 תווים.
# כתובות ה-API נבנות כ-https://api.telegram.org/bot<TOKEN>/method — ולכן כל טקסט
# שנגזר מכתובת כזו (הודעת שגיאה, לוג, אירוע Sentry) עלול לשאת את הטוקן במלואו.
# דרישת 30+ תווים בסוד מצמצמת פגיעה בטקסטים לגיטימיים (hash/מזהה עם נקודתיים),
# ועדיין תופסת כל טוקן אמיתי.
_BOT_TOKEN_RE = re.compile(r"\d{5,16}:[A-Za-z0-9_-]{30,}")

TOKEN_PLACEHOLDER = "<REDACTED>"

# מוחזר כשאי אפשר לנקות ערך (str() נכשל) — עדיף לאבד את הערך מאשר להדליף טוקן
UNREDACTABLE_PLACEHOLDER = "<UNREDACTABLE>"


def redact_bot_token(value: Any) -> Any:
    """מחליף כל טוקן בוט שמופיע בטקסט בסימון ``<REDACTED>``.

    מחזיר ``None`` כפי שהוא, וכל ערך אחר מומר למחרוזת מנוקה. אם ההמרה למחרוזת
    נכשלת מוחזר ``<UNREDACTABLE>`` — כישלון ניקוי לעולם לא מחזיר את הערך הגולמי.
    זו נקודת הניקוי היחידה בקוד — ``TelegramAPIError``, מסנני ה-Sentry ומסנן
    הלוגים נשענים עליה.
    """
    if value is None:
        return None
    try:
        text = value if isinstance(value, str) else str(value)
        return _BOT_TOKEN_RE.sub(TOKEN_PLACEHOLDER, text)
    except Exception:
        return UNREDACTABLE_PLACEHOLDER


def _redact_bytes(obj: Any) -> Any:
    """מנקה טוקן מ-bytes/bytearray תוך שמירה על הטיפוס המקורי."""
    try:
        cleaned_text = _BOT_TOKEN_RE.sub(TOKEN_PLACEHOLDER, obj.decode("utf-8", errors="replace"))
        encoded = cleaned_text.encode("utf-8")
        return bytearray(encoded) if isinstance(obj, bytearray) else encoded
    except Exception:
        return UNREDACTABLE_PLACEHOLDER


def _dedupe_key(ck: Any, cleaned_dict: Dict[Any, Any]) -> Any:
    """ממספר מפתח שמתנגש עם מפתח קיים אחרי ניקוי (‎#2 למחרוזת, ‎(key, 2)‎ לאחרים).

    שני מפתחות שונים יכולים להתנקות לאותו ערך (שתי כתובות עם טוקנים שונים);
    דריסה שקטה מאבדת שדה אבחוני — במקום זה המאוחר מקבל סיומת מספור.
    """
    if ck not in cleaned_dict:
        return ck
    n = 2
    candidate = f"{ck}#{n}" if isinstance(ck, str) else (ck, n)
    while candidate in cleaned_dict:
        n += 1
        candidate = f"{ck}#{n}" if isinstance(ck, str) else (ck, n)
    return candidate


def _redact_dict(obj: Dict[Any, Any], _memo: Dict[int, Any], _depth: int) -> Dict[Any, Any]:
    cleaned_dict: Dict[Any, Any] = {}
    # רישום לפני המילוי — כך הפניה מעגלית חוזרת לעותק המנוקה ולא למקור
    _memo[id(obj)] = cleaned_dict
    for k, v in obj.items():
        # גם מפתח יכול לשאת טוקן — כמחרוזת או בתוך tuple/frozenset (שנשארים hashable)
        ck = _dedupe_key(redact_bot_token_deep(k, _memo, _depth + 1), cleaned_dict)
        cleaned_dict[ck] = redact_bot_token_deep(v, _memo, _depth + 1)
    return cleaned_dict


def _redact_list(obj: list, _memo: Dict[int, Any], _depth: int) -> list:
    cleaned_list: list = []
    _memo[id(obj)] = cleaned_list
    for v in obj:
        cleaned_list.append(redact_bot_token_deep(v, _memo, _depth + 1))
    return cleaned_list


def _redact_tuple(obj: tuple, _memo: Dict[int, Any], _depth: int) -> tuple:
    cleaned_items = [redact_bot_token_deep(v, _memo, _depth + 1) for v in obj]
    try:
        if hasattr(obj, "_fields"):  # namedtuple — בנייה מאיברים בודדים
            return type(obj)(*cleaned_items)
        return type(obj)(cleaned_items)
    except Exception:
        # תת-מחלקה עם בנאי לא סטנדרטי — tuple רגיל עדיף על אובייקט לא מנוקה
        return tuple(cleaned_items)


def redact_bot_token_deep(obj: Any, _memo: Optional[Dict[int, Any]] = None, _depth: int = 0) -> Any:
    """מנקה טוקנים מכל המחרוזות בתוך מבנה נתונים מקונן.

    נועד למסנני Sentry: אירוע שגיאה פורש את הטוקן על פני כמה שדות (גוף החריגה,
    הודעת הלוג, breadcrumbs), ורשימת שדות קבועה תמיד תפספס אחד. במקום זה עוברים
    על כל המבנה — dict (כולל מפתחות), list, tuple (כולל namedtuple), set ו-frozenset.

    מבנים מעגליים מטופלים ב-memo לפי ‎id()‎ כך שכל צומת מנוקה בדיוק פעם אחת;
    מגבלת העומק היא רשת ביטחון בלבד, וחצייה שלה מחזירה placeholder — לעולם לא
    את הערך המקורי.
    """
    if _memo is None:
        _memo = {}
    if _depth > 100:
        # עומק כזה לא קיים באירועי Sentry אמיתיים; מחזירים placeholder ולא את המקור
        return UNREDACTABLE_PLACEHOLDER
    if isinstance(obj, str):
        return redact_bot_token(obj)
    if isinstance(obj, (bytes, bytearray)):
        return _redact_bytes(obj)
    if isinstance(obj, (dict, list)):
        existing = _memo.get(id(obj))
        if existing is not None:
            return existing
        if isinstance(obj, dict):
            return _redact_dict(obj, _memo, _depth)
        return _redact_list(obj, _memo, _depth)
    if isinstance(obj, tuple):
        return _redact_tuple(obj, _memo, _depth)
    if isinstance(obj, (set, frozenset)):
        cleaned_set = {redact_bot_token_deep(v, _memo, _depth + 1) for v in obj}
        return frozenset(cleaned_set) if isinstance(obj, frozenset) else cleaned_set
    # סקלרים חסרי טקסט — אין מה לנקות בהם
    if obj is None or isinstance(obj, (int, float, bool)):
        return obj
    # אובייקט זר (למשל מופע חריגה בתוך hint/extra): Sentry ימיר אותו למחרוזת
    # אחרי שהניקוי כבר עבר — ב-repr() עבור אובייקטים שאינם JSON — ולכן בודקים
    # את שני הייצוגים. אם אחד מהם נושא טוקן, מחזירים את הייצוג המנוקה במקום
    # האובייקט. אובייקט נקי בשניהם נשמר כמות שהוא.
    try:
        text = str(obj)
        rep = repr(obj)
    except Exception:
        return UNREDACTABLE_PLACEHOLDER
    if _BOT_TOKEN_RE.search(rep):
        return _BOT_TOKEN_RE.sub(TOKEN_PLACEHOLDER, rep)
    if _BOT_TOKEN_RE.search(text):
        return _BOT_TOKEN_RE.sub(TOKEN_PLACEHOLDER, text)
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
        # ניקוי עמוק — גם dict/list (למשל payload מלא של תגובת טלגרם) חייבים לצאת נקיים
        self.payload = redact_bot_token_deep(payload) if payload is not None else None
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

