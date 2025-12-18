from __future__ import annotations

from typing import Any, Dict, Optional


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
        self.description = str(description or "").strip()
        self.url = url
        self.http_status = http_status
        self.payload = payload
        msg = f"Telegram API error"
        if error_code is not None:
            msg += f" error_code={error_code}"
        if self.description:
            msg += f" description={self.description}"
        if http_status is not None:
            msg += f" http_status={http_status}"
        if url:
            msg += f" url={url}"
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

