"""בדיקות שהטוקן של הבוט לא דולף לטקסטים שנשמרים או נשלחים החוצה.

כתובות ה-API של טלגרם נבנות כ-``https://api.telegram.org/bot<TOKEN>/method``,
ולכן כל טקסט שנגזר מהן — הודעת חריגה, שורת לוג או אירוע Sentry — עלול לשאת
את הטוקן במלואו. הבדיקות כאן נועלות את נקודות הניקוי.
"""

import logging

import pytest

from telegram_api import (
    TelegramAPIError,
    parse_telegram_json_from_response,
    redact_bot_token,
    redact_bot_token_deep,
    require_telegram_ok,
)

# טוקן בדוי במבנה אמיתי — משמש רק לבדיקה שהוא לא שורד בפלט
FAKE_TOKEN = "7628556044:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
API_URL = f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage"


class _FakeResponse:
    """תגובת HTTP מינימלית, כמו זו ש-requests/http_sync מחזירים."""

    def __init__(self, *, payload=None, text="", status_code=200, url=API_URL):
        self._payload = payload
        self.text = text
        self.status_code = status_code
        self.url = url

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_redact_bot_token_replaces_token_in_url():
    assert FAKE_TOKEN not in redact_bot_token(API_URL)
    assert "<REDACTED>" in redact_bot_token(API_URL)


def test_redact_bot_token_keeps_surrounding_text():
    cleaned = redact_bot_token(f"POST {API_URL} failed")
    assert cleaned.startswith("POST https://api.telegram.org/bot")
    assert cleaned.endswith("/sendMessage failed")


def test_redact_bot_token_passes_through_none_and_clean_text():
    assert redact_bot_token(None) is None
    assert redact_bot_token("nothing secret here") == "nothing secret here"


def test_error_message_has_no_token():
    err = TelegramAPIError(
        error_code=403,
        description="Forbidden: bot was blocked by the user",
        url=API_URL,
        http_status=403,
    )
    assert FAKE_TOKEN not in str(err)


def test_error_attributes_have_no_token():
    """גם מי שקורא ``e.url`` ישירות ורושם אותו ללוג לא אמור לקבל את הטוקן."""
    err = TelegramAPIError(error_code=None, description="boom", url=API_URL)
    assert FAKE_TOKEN not in str(err.url)


def test_error_description_carrying_token_is_cleaned():
    err = TelegramAPIError(error_code=None, description=f"failed calling {API_URL}", url=None)
    assert FAKE_TOKEN not in str(err)


def test_require_telegram_ok_raises_without_token():
    payload = {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
    with pytest.raises(TelegramAPIError) as excinfo:
        require_telegram_ok(payload, url=API_URL)
    assert FAKE_TOKEN not in str(excinfo.value)


def test_parse_invalid_json_raises_without_token():
    resp = _FakeResponse(payload=None, text="<html>502</html>", status_code=502)
    with pytest.raises(TelegramAPIError) as excinfo:
        parse_telegram_json_from_response(resp, url=API_URL)
    assert FAKE_TOKEN not in str(excinfo.value)


def test_parse_falls_back_to_response_url_without_token():
    """כש-url לא מועבר במפורש הוא נשלף מהתגובה — וגם אז חייב להיות נקי."""
    resp = _FakeResponse(payload=None, text="oops", status_code=500)
    with pytest.raises(TelegramAPIError) as excinfo:
        parse_telegram_json_from_response(resp)
    assert FAKE_TOKEN not in str(excinfo.value)


def test_parse_non_dict_json_raises_without_token():
    resp = _FakeResponse(payload=["not", "a", "dict"], status_code=200)
    with pytest.raises(TelegramAPIError) as excinfo:
        parse_telegram_json_from_response(resp, url=API_URL)
    assert FAKE_TOKEN not in str(excinfo.value)


def test_redact_deep_cleans_nested_sentry_shaped_event():
    event = {
        "exception": {"values": [{"type": "TelegramAPIError", "value": f"error url={API_URL}"}]},
        "logentry": {"message": f"calling {API_URL}"},
        "breadcrumbs": [{"data": {"url": API_URL}}],
        "extra": {"safe": 1, "nested": ("tuple", API_URL)},
    }
    cleaned = redact_bot_token_deep(event)
    assert FAKE_TOKEN not in repr(cleaned)
    # מבנה הנתונים נשמר — רק המחרוזות נוקו
    assert cleaned["extra"]["safe"] == 1
    assert isinstance(cleaned["extra"]["nested"], tuple)
    assert cleaned["exception"]["values"][0]["type"] == "TelegramAPIError"


def test_redact_deep_survives_self_referencing_structure():
    """מבנה מעגלי מנוקה במלואו — ההפניה המעגלית מצביעה על העותק המנוקה, לא על המקור."""
    node: dict = {"url": API_URL}
    node["self"] = node
    cleaned = redact_bot_token_deep(node)
    assert FAKE_TOKEN not in str(cleaned["url"])
    # ההפניה המעגלית נסגרת על העותק המנוקה — אין דרך להגיע מהתוצאה לטוקן הגולמי
    assert cleaned["self"] is cleaned
    assert FAKE_TOKEN not in str(cleaned["self"]["url"])


def test_redact_deep_handles_deep_nesting_without_leaking():
    """קינון עמוק (מעבר לכל cap) לא מחזיר לעולם את הערך הגולמי."""
    node: dict = {"url": API_URL}
    for _ in range(150):
        node = {"child": node}
    cleaned = redact_bot_token_deep(node)
    assert FAKE_TOKEN not in repr(cleaned)


def test_redact_deep_cleans_dict_keys_sets_and_namedtuples():
    import collections

    Point = collections.namedtuple("Point", ["x", "y"])
    obj = {
        API_URL: "key-carrying-token",
        "set": {API_URL, "safe"},
        "frozen": frozenset({API_URL}),
        "named": Point(x=API_URL, y=1),
    }
    cleaned = redact_bot_token_deep(obj)
    assert FAKE_TOKEN not in repr(cleaned)
    # namedtuple נשמר כ-namedtuple, set נשאר set
    named = next(v for v in cleaned.values() if isinstance(v, tuple) and hasattr(v, "_fields"))
    assert named.y == 1
    assert isinstance(cleaned["set"], set)
    assert isinstance(cleaned["frozen"], frozenset)


def test_error_payload_dict_is_redacted_and_structure_kept():
    payload = {"ok": False, "description": f"failed {API_URL}", "error_code": 400}
    err = TelegramAPIError(error_code=400, description="Bad Request", url=API_URL, payload=payload)
    assert FAKE_TOKEN not in repr(err.payload)
    assert err.payload["error_code"] == 400


def test_error_payload_string_is_redacted():
    err = TelegramAPIError(error_code=None, description="boom", url=None, payload=f"body {API_URL}")
    assert FAKE_TOKEN not in err.payload


def test_redact_deep_cleans_transaction_shaped_event_with_http_spans():
    """אירוע transaction של Sentry: ה-URL המלא יושב ב-spans וב-breadcrumbs."""
    event = {
        "type": "transaction",
        "spans": [
            {"op": "http.client", "description": f"POST {API_URL}", "data": {"url": API_URL}},
        ],
        "breadcrumbs": {"values": [{"category": "httplib", "data": {"url": API_URL}}]},
        "request": {"url": API_URL},
    }
    cleaned = redact_bot_token_deep(event)
    assert FAKE_TOKEN not in repr(cleaned)
    assert cleaned["type"] == "transaction"
    assert cleaned["spans"][0]["op"] == "http.client"


def test_logging_filter_redacts_bot_token():
    from utils import SensitiveDataFilter

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=f"request failed: {API_URL}",
        args=(),
        exc_info=None,
    )
    SensitiveDataFilter().filter(record)
    assert FAKE_TOKEN not in record.getMessage()


def test_logging_formatter_does_not_leak_token_from_traceback():
    """ה-Formatter מדביק את ה-traceback אחרי ההודעה — גם הוא חייב לצאת נקי."""
    import sys

    from utils import SensitiveDataFilter

    try:
        raise RuntimeError(f"request failed: {API_URL}")
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="clean message",
        args=(),
        exc_info=exc_info,
    )
    SensitiveDataFilter().filter(record)
    formatted = logging.Formatter().format(record)
    assert FAKE_TOKEN not in formatted
    # ה-traceback עצמו לא נעלם — רק הטוקן הוחלף
    assert "RuntimeError" in formatted
    # exc_info נשמר: Formatter משתמש בקאש exc_text המנוקה, ו-Sentry עוד צריך
    # את החריגה המובנית (הניקוי שלה קורה ב-before_send)
    assert record.exc_info is not None


def test_redact_deep_cleans_bytes_and_non_string_dict_keys():
    """גם bytes (גוף תגובה גולמי) וגם מפתחות מורכבים חייבים לצאת נקיים."""
    obj = {
        ("tuple-key", API_URL): "value",
        frozenset({API_URL}): "value2",
        b"body": API_URL.encode("utf-8"),
        "ba": bytearray(API_URL.encode("utf-8")),
    }
    cleaned = redact_bot_token_deep(obj)
    assert FAKE_TOKEN not in repr(cleaned)
    assert FAKE_TOKEN.encode("utf-8") not in cleaned[b"body"]
    # הטיפוסים נשמרים — bytes נשאר bytes, bytearray נשאר bytearray
    assert isinstance(cleaned[b"body"], bytes)
    assert isinstance(cleaned["ba"], bytearray)
    assert any(isinstance(k, tuple) for k in cleaned)
    assert any(isinstance(k, frozenset) for k in cleaned)


def test_redact_deep_preserves_entries_on_key_collision():
    """שני מפתחות עם טוקנים שונים מתנקים לאותו ערך — אף שדה לא נדרס בשקט."""
    other_token = "999999999:BBcdqTcvCH1vGWJxfSeofSAs0K5PALDzzz"
    obj = {
        f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage": "first",
        f"https://api.telegram.org/bot{other_token}/sendMessage": "second",
    }
    cleaned = redact_bot_token_deep(obj)
    assert FAKE_TOKEN not in repr(cleaned)
    assert other_token not in repr(cleaned)
    # שני הערכים שרדו — המפתח השני קיבל סיומת מספור במקום לדרוס את הראשון
    assert len(cleaned) == 2
    assert sorted(cleaned.values()) == ["first", "second"]
    # מדיניות המספור מפורשת: המפתח המאוחר מסתיים ב-#2
    assert any(isinstance(k, str) and k.endswith("#2") for k in cleaned)


def test_redact_deep_key_collision_on_non_string_keys():
    """התנגשות בין מפתחות tuple — המאוחר נעטף ב-(key, 2) במקום לדרוס."""
    other_token = "999999999:BBcdqTcvCH1vGWJxfSeofSAs0K5PALDzzz"
    obj = {
        ("chat", API_URL): "first",
        ("chat", f"https://api.telegram.org/bot{other_token}/sendMessage"): "second",
    }
    cleaned = redact_bot_token_deep(obj)
    assert FAKE_TOKEN not in repr(cleaned)
    assert other_token not in repr(cleaned)
    assert len(cleaned) == 2
    assert sorted(cleaned.values()) == ["first", "second"]
    # המפתח המתנגש נעטף עם מונה: (המפתח המנוקה, 2)
    assert any(isinstance(k, tuple) and len(k) == 2 and k[1] == 2 for k in cleaned)


def test_logging_formatter_redacts_github_and_bearer_from_traceback():
    """ה-traceback עובר את אותם דפוסי ניקוי כמו ההודעה — לא רק טלגרם."""
    import sys

    from utils import SensitiveDataFilter

    gh_token = "ghp_" + "a" * 30
    try:
        raise RuntimeError(f"auth failed: {gh_token} Bearer abc123def456ghi789")
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="clean message",
        args=(),
        exc_info=exc_info,
    )
    SensitiveDataFilter().filter(record)
    formatted = logging.Formatter().format(record)
    assert gh_token not in formatted
    assert "abc123def456ghi789" not in formatted
    assert "REDACTED" in formatted
    assert "RuntimeError" in formatted
    assert record.exc_info is not None


def test_redact_deep_cleans_foreign_objects_carrying_token():
    """אובייקט זר (כמו מופע חריגה) שהייצוג שלו נושא טוקן מוחלף בייצוג המנוקה."""

    class _Foreign:
        def __str__(self):
            return f"request to {API_URL} failed"

    cleaned = redact_bot_token_deep({"exc": _Foreign()})
    assert FAKE_TOKEN not in str(cleaned["exc"])
    assert "<REDACTED>" in str(cleaned["exc"])


def test_redact_deep_catches_token_hiding_only_in_repr():
    """Sentry ממיר אובייקטים זרים ב-repr — טוקן שמופיע רק שם חייב להיתפס."""

    class _Foreign:
        def __str__(self):
            return "looks clean"

        def __repr__(self):
            return f"<Foreign url={API_URL}>"

    cleaned = redact_bot_token_deep({"exc": _Foreign()})
    assert FAKE_TOKEN not in str(cleaned["exc"])
    assert FAKE_TOKEN not in repr(cleaned["exc"])
    assert "<REDACTED>" in str(cleaned["exc"])


def test_redact_deep_preserves_clean_foreign_objects():
    """אובייקט זר נקי נשמר כמות שהוא — לא הופכים כל אירוע למחרוזות."""

    class _Foreign:
        def __str__(self):
            return "nothing secret"

    obj = _Foreign()
    cleaned = redact_bot_token_deep({"exc": obj, "num": 42, "flag": True, "none": None})
    assert cleaned["exc"] is obj
    assert cleaned["num"] == 42 and cleaned["flag"] is True and cleaned["none"] is None


def test_logging_formatter_keeps_clean_exceptions_untouched():
    """חריגה בלי טוקן שומרת על exc_info — אין פגיעה במבנה עבור Sentry וכו'."""
    import sys

    from utils import SensitiveDataFilter

    try:
        raise ValueError("nothing secret")
    except ValueError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="clean message",
        args=(),
        exc_info=exc_info,
    )
    SensitiveDataFilter().filter(record)
    assert record.exc_info is not None
    assert "ValueError" in logging.Formatter().format(record)
