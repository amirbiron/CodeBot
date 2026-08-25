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
    scrub_sentry_event,
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


def _filtered_record_for(exc: BaseException) -> logging.LogRecord:
    """מרים את החריגה, אורז אותה ב-LogRecord ומריץ עליו את המסנן.

    התשתית המשותפת לטסטי ה-Formatter — כל טסט מספק רק את החריגה ואת ה-asserts.
    """
    import sys

    from utils import SensitiveDataFilter

    try:
        raise exc
    except type(exc):
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
    return record


def test_logging_formatter_does_not_leak_token_from_traceback():
    """ה-Formatter מדביק את ה-traceback אחרי ההודעה — גם הוא חייב לצאת נקי."""
    record = _filtered_record_for(RuntimeError(f"request failed: {API_URL}"))
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
    gh_token = "ghp_" + "a" * 30
    record = _filtered_record_for(RuntimeError(f"auth failed: {gh_token} Bearer abc123def456ghi789"))
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
    record = _filtered_record_for(ValueError("nothing secret"))
    assert record.exc_info is not None
    assert "ValueError" in logging.Formatter().format(record)


def test_scrub_sentry_event_cleans_and_fails_closed(monkeypatch):
    """העוזר המשותף לשני ה-before_send: מנקה אירוע, ומחזיר None בכשל ניקוי."""
    import telegram_api
    from telegram_api import scrub_sentry_event

    cleaned = scrub_sentry_event({"logentry": {"message": f"calling {API_URL}"}})
    # חייבים אירוע ממשי ומנוקה — ‎repr(None)‎ לעולם לא מכיל טוקן, כך שבלי
    # הבדיקות האלה הטסט היה עובר גם אם הפונקציה הייתה מפילה כל אירוע
    assert cleaned is not None
    assert cleaned["logentry"]["message"] == "calling https://api.telegram.org/bot<REDACTED>/sendMessage"

    def _boom(_obj):
        raise RuntimeError("redaction broke")

    monkeypatch.setattr(telegram_api, "redact_bot_token_deep", _boom)
    assert scrub_sentry_event({"anything": "at all"}) is None


# ---------- סוד שרוכב על שורת שאילתה (מפתח Gemini שדלף ל-Sentry) ----------

# מפתח בדוי בצורת מפתח של Google — משמש רק כדי לוודא שהוא לא שורד בפלט
FAKE_GOOGLE_KEY = "AIzaSyFAKE0000_NOT_A_REAL_KEY_000000000"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"text-embedding-004:embedContent?key={FAKE_GOOGLE_KEY}"
)


def test_sentry_span_shape_from_httpx_integration_is_scrubbed():
    """**זו בדיוק צורת האירוע שדלף.**

    אינטגרציית httpx של Sentry נדלקת מעצמה, קוראת ל-``parse_url`` עם
    ``sanitize=False``, ורושמת את שורת השאילתה בשדה נפרד — ``http.query`` —
    שערכו מחרוזת עירומה בלי ``?`` מוביל. הרשת הישנה הכירה רק את צורת הטוקן
    של טלגרם, ולכן המפתח עבר דרכה שלם.

    נופל אם דפוס שורת-השאילתה יוסר, או אם יעוגן ל-``?``/``&`` בלבד.
    """
    event = {
        "type": "transaction",
        "spans": [
            {
                "op": "http.client",
                "description": f"POST {GEMINI_URL}",
                "data": {
                    "url": GEMINI_URL.split("?")[0],
                    # השדה שדלף: מחרוזת עירומה, בלי ``?`` מוביל
                    "http.query": f"key={FAKE_GOOGLE_KEY}",
                },
            }
        ],
        "breadcrumbs": {"values": [{"type": "http", "data": {"url": GEMINI_URL}}]},
    }

    cleaned = scrub_sentry_event(event)

    assert cleaned is not None, "הניקוי נכשל — fail-closed היה מפיל את האירוע"
    blob = repr(cleaned)
    assert FAKE_GOOGLE_KEY not in blob
    assert cleaned["spans"][0]["data"]["http.query"] == "key=<REDACTED>"


def test_bare_query_string_without_leading_question_mark_is_scrubbed():
    """שורת שאילתה עירומה — הצורה שבה Sentry שומר את ``http.query``.

    נופל אם הדפוס יעוגן ל-``?``/``&`` בלבד ולא גם לתחילת מחרוזת.
    """
    assert redact_bot_token(f"key={FAKE_GOOGLE_KEY}") == "key=<REDACTED>"
    assert redact_bot_token(f"foo=1&api_key={FAKE_GOOGLE_KEY}") == "foo=1&api_key=<REDACTED>"


def test_secret_query_param_is_scrubbed_by_name_not_by_value_shape():
    """**הכלל חסין-ספק.** הוא מנקה לפי שם הפרמטר ולא לפי צורת הערך.

    זה מה שמונע את החזרה של האירוע עם הספק הבא: אין כאן שום ידע על Google.

    נופל אם מחליפים את הכלל בדפוס-צורה ספציפי (למשל ``AIza...``).
    """
    for name in ("key", "api_key", "token", "access_token", "secret", "password", "signature"):
        cleaned = redact_bot_token(f"https://example.com/v1/x?{name}=SOME_OPAQUE_VALUE_123")
        assert "SOME_OPAQUE_VALUE_123" not in cleaned, name
        assert f"{name}=<REDACTED>" in cleaned, name


def test_compound_parameter_names_are_scrubbed_too():
    """**שם מורכב הוא הצורה הנפוצה, לא החריגה.**

    ``auth_token``, ``oauth_token``, ``id_token``, ``private_key``,
    ``x-api-key`` ו-``session_token`` הם שמות פרמטרים סטנדרטיים ב-OAuth
    ובקולבקים. כשהדפוס דרש התאמה מדויקת מהמפריד, כולם עברו שלמים.

    התיקון אינו הוספתם לרשימה — זה היה משחזר את אותה רשימה שחורה
    שמתעדכנת רק אחרי דליפה — אלא תחילית-מקטע שמכסה כל וריאציה כזו.

    נופל אם התחילית ``(?:[A-Za-z0-9]+[_.\\-])*`` תוסר מהדפוס.
    """
    for name in (
        "auth_token", "oauth_token", "id_token", "private_key",
        "x-api-key", "session_token", "refresh_token", "api_key_secret",
    ):
        cleaned = redact_bot_token(f"https://example.com/cb?{name}=OPAQUE_SECRET_123")
        assert "OPAQUE_SECRET_123" not in cleaned, name
        assert f"{name}=<REDACTED>" in cleaned, name


def test_camel_case_parameter_names_are_scrubbed_too():
    """**camelCase הוא אותו שם, בכתיב אחר.**

    ``privateKey``, ``authToken`` ו-``xApiKey`` הם בדיוק ``private_key``,
    ``auth_token`` ו-``x-api-key`` — ספקים כותבים בשני הכתיבים. תחילית
    שמסתיימת רק במפריד תופסת חצי מהם.

    נופל אם גבול ה-camelCase יוסר מהתחילית.
    """
    for name in ("privateKey", "authToken", "xApiKey", "refreshToken", "sessionToken"):
        cleaned = redact_bot_token(f"https://example.com/cb?{name}=OPAQUE_SECRET_123")
        assert "OPAQUE_SECRET_123" not in cleaned, name
        assert f"{name}=<REDACTED>" in cleaned, name


def test_digits_act_as_a_segment_boundary_in_both_casings():
    """**רצף ספרות הוא מפריד מקטע, ולכן הרישיות לא קובעת.**

    גרסאות ואלגוריתמים נכנסים לשמות פרמטרים כמעט תמיד, ובשני הכתיבים:
    ``v2Token`` ו-``v2token`` יכולים לשאת בדיוק את אותו credential.
    ``v2`` + ``token`` היא קריאה טבעית של השם — בניגוד ל-``mon`` +
    ``key`` — ולכן המעבר ספרה ← אות הוא גבול, וגבול אות ← אות אינו.

    נופל אם הגבול ספרה ← אות יוסר, או אם ה-``0-9`` יוסר מהצד השמאלי של
    גבול ה-camelCase.
    """
    for name in ("v2Token", "oauth2Token", "sha256Token", "x509Key", "md5Secret",
                 "v2token", "oauth2token", "sha256token", "x509key"):
        cleaned = redact_bot_token(f"https://example.com/cb?{name}=OPAQUE_SECRET_123")
        assert "OPAQUE_SECRET_123" not in cleaned, name
        assert f"{name}=<REDACTED>" in cleaned, name


def test_a_digit_somewhere_in_the_name_is_not_enough_on_its_own():
    """הגבול נדרש **צמוד** למילה הרגישה, לא איפשהו בשם.

    ``top10keys`` ו-``utf8keyboard`` מכילים ספרות וגם ``key``, ובכל זאת
    אינם נתפסים: באחד המילה אינה נגמרת ב-``=``, ובשני היא חלק ממילה
    ארוכה יותר.
    """
    for benign in ("?top10keys=5", "?utf8keyboard=1", "?sha256=abc"):
        assert redact_bot_token(benign) == benign, benign


def test_camel_boundary_is_case_sensitive_inside_a_case_insensitive_pattern():
    """**מלכודת ``(?i)``.** תחת דגל חוסר-רגישות-רישיות, ``[A-Z]`` תופס גם
    אותיות קטנות — וגבול ה-camelCase מתדרדר ל"בין כל שתי אותיות". אז
    ``?monkey=`` היה נתפס, כי ``mon`` + גבול + ``key`` "מתאים".

    הגבול חייב להיות ב-``(?-i:...)``. הטסט הזה נועל את זה בנפרד משאר
    בדיקות ה-``monkey`` כי הוא נוגע לסיבה אחרת לגמרי לאותה תוצאה.

    נופל אם דגלי ה-``(?-i:...)`` יוסרו מהגבול.
    """
    for benign in ("?monkey=banana", "?donkey=1", "?turkey=2", "?keyId=42"):
        assert redact_bot_token(benign) == benign, benign


def test_over_redaction_of_benign_names_is_a_deliberate_choice():
    """**ניקוי-יתר מכוון, ולא תופעת לוואי.**

    ``search_key`` ו-``sort_token`` אינם סודות, וכן ינוקו: לפי **שם** אי
    אפשר להבחין ביניהם לבין ``private_key``. הבחירה היא בין ניקוי-יתר של
    ערך אבחוני לבין דליפת credential, וברשת של לוגים ו-Sentry הכיוון הוא
    fail-closed. לשם השוואה, ``sanitize_url`` של Sentry מנקה **כל** ערך
    בשאילתה כולל ``limit=5``; הכלל כאן צר ממנו.

    הטסט קיים כדי שהתנהגות כזו לא תיראה כבאג בסבב הבא. נופל אם מישהו
    יצמצם את התחילית לרשימת מקטעים מוכרים — וזה יהיה סימן להחלטה מודעת
    ולא לתיקון שקט.
    """
    assert redact_bot_token("?search_key=price") == "?search_key=<REDACTED>"
    assert redact_bot_token("?sort_token=abc") == "?sort_token=<REDACTED>"
    # ומה שכן נשמר — פרמטרים שכנים שאינם נושאים שם רגיש
    assert redact_bot_token("?page_key=3&limit=5") == "?page_key=<REDACTED>&limit=5"


def test_a_sensitive_word_must_be_a_whole_segment_not_a_suffix():
    """**הגבול של התחילית.** המילה הרגישה חייבת להיות מקטע שלם בשם.

    בלי הדרישה שהתחילית תסתיים במפריד, ``?monkey=`` היה נתפס (הוא מסתיים
    ב-``key``) וכל שם פרמטר שמכיל צירוף מקרי היה מנוקה. ``key_id`` נשמר
    מאותה סיבה הפוכה: הוא מזהה, לא סוד.

    נופל אם התחילית תשוחרר ל-``[A-Za-z0-9_.-]*`` בלי דרישת המפריד.
    """
    for benign in ("?monkey=banana", "?cameronkey=x", "?keys=3", "?author=me",
                   "?key_id=42", "?tokenizer=bpe"):
        assert redact_bot_token(benign) == benign, benign


def test_query_scrub_keeps_neighbouring_params_and_fragment():
    """מנקה את הערך בלבד — לא את שאר השאילתה ולא את ה-fragment."""
    cleaned = redact_bot_token(f"https://x.io/a?key={FAKE_GOOGLE_KEY}&limit=5#section")
    assert cleaned == "https://x.io/a?key=<REDACTED>&limit=5#section"


def test_diagnostic_log_line_with_non_secret_key_is_left_alone():
    """**לא לסרס מידע אבחוני.** ``embedding_worker`` מדפיס ``key=`` על מפתח
    מודל/מימד, שאינו סוד. הדפוס מעוגן לשורת שאילתה או לתחילת מחרוזת בדיוק
    כדי לא לגעת בשורות כאלה.

    נופל אם מרחיבים את העיגון לרווח.
    """
    line = "Snippet 42: retry using model=gemini-embedding-001 api=v1 dim=768 key=models/emb-004"
    assert redact_bot_token(line) == line


def test_log_filter_inherits_the_shared_pattern_list(caplog):
    """רשת הלוגים ורשת Sentry חולקות רשימת דפוסים אחת.

    נופל אם ``SensitiveDataFilter`` יחזור לרשימה משלו.
    """
    from utils import SensitiveDataFilter

    record = logging.LogRecord(
        name="probe", level=logging.ERROR, pathname=__file__, lineno=1,
        msg="POST %s failed", args=(GEMINI_URL,), exc_info=None,
    )
    SensitiveDataFilter().filter(record)

    assert FAKE_GOOGLE_KEY not in str(record.msg)
    assert "key=<REDACTED>" in str(record.msg)
