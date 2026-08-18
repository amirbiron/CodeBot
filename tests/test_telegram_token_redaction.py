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
    """מבנה מעגלי לא אמור להפיל את המסנן — הוא רץ לפני שליחה לכל אירוע."""
    node: dict = {"url": API_URL}
    node["self"] = node
    cleaned = redact_bot_token_deep(node)
    assert FAKE_TOKEN not in str(cleaned["url"])


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
