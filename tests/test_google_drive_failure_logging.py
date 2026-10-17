"""כשל של פעולת Drive שמחזירה ``None`` בלי לזרוק נרשם בלוג — עם הסיבה, ובלי הטקסט של החריגה.

``upload_bytes`` / ``upload_file`` / ``ensure_folder`` / ``get_drive_service`` בולעים חריגות ומחזירים ``None``. הקורא בודק את הערך ומציג כשל (תמונת קוד ב-``bot_handlers.py``, הגיבוי של הוובאפ), אבל הסיבה הלכה לאיבוד: הלוג שבקורא לא ראה אותה, כי ממנו לא יצאה חריגה. ``_log_drive_call_failed`` רושם אותה בנקודה שבה היא נבלעת.

ה-``HttpError`` כאן אמיתי (google-api-python-client), כדי שהטקסט שלו — כתובת הבקשה והודעת השגיאה של גוגל — יהיה הטקסט שהספרייה באמת בונה.
"""

from __future__ import annotations

import importlib
import io
import logging

import httplib2
import pytest
from googleapiclient.errors import HttpError

LOGGER = "services.google_drive_service"
UPLOAD_URI = "https://www.googleapis.com/upload/drive/v3/files?alt=json&uploadType=resumable"
QUOTA_MESSAGE = "The user's Drive storage quota has been exceeded."


def _gds():
    # טסטים אחרים טוענים את המודול מחדש; לוקחים את העותק הנוכחי
    return importlib.import_module("services.google_drive_service")


def _http_error(status, body: bytes) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), body, uri=UPLOAD_URI)


def _drive_logs(caplog):
    return [r.getMessage() for r in caplog.records if r.name == LOGGER]


def _upload_with_failing_chunk(monkeypatch, error):
    gds = _gds()

    class _Request:
        def next_chunk(self):
            raise error

    class _Files:
        def create(self, body=None, media_body=None, fields=None):
            return _Request()

    class _Service:
        def files(self):
            return _Files()

    class _Media:
        def __init__(self, fh, mimetype=None, resumable=False, chunksize=None):
            assert isinstance(fh, io.BytesIO)

    monkeypatch.setattr(gds, "get_drive_service", lambda uid, *, owner: _Service())
    monkeypatch.setattr(gds, "ensure_subpath", lambda uid, sub, *, owner: "folder-1")
    monkeypatch.setattr(gds, "MediaIoBaseUpload", _Media)
    return gds.upload_bytes(7, "backup.zip", b"PK", sub_path="zip", owner="webapp")


def test_a_failed_upload_logs_the_status_and_the_drive_reason_and_not_the_error_text(monkeypatch, caplog):
    error = _http_error(403, b'{"error": {"code": 403, "message": "%s", "errors": [{"reason": "storageQuotaExceeded"}]}}' % QUOTA_MESSAGE.encode())
    assert UPLOAD_URI in str(error) and QUOTA_MESSAGE in str(error)  # מה שאסור שיגיע ללוג באמת נמצא בטקסט של החריגה

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert _upload_with_failing_chunk(monkeypatch, error) is None

    assert _drive_logs(caplog) == [
        "drive_call_failed op=upload_bytes.chunk owner=webapp user_id=7 error_type=HttpError http_status=403 drive_reason=storageQuotaExceeded oauth_error=None"
    ]
    everything = "\n".join(_drive_logs(caplog))
    assert UPLOAD_URI not in everything and QUOTA_MESSAGE not in everything


@pytest.mark.parametrize("message", ["Invalid value for owner someone@example.com", "PrivateName"])
def test_a_drive_error_without_a_code_logs_no_reason_and_never_the_message(monkeypatch, caplog, message):
    # בלי errors[].reason ובלי error.status אין קוד שגיאה. error.message הוא טקסט חופשי של גוגל — גם כשהוא מילה אחת, שהייתה עוברת את בדיקת הצורה של קוד
    error = _http_error(400, b'{"error": {"code": 400, "message": "%s"}}' % message.encode())

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert _upload_with_failing_chunk(monkeypatch, error) is None

    (line,) = _drive_logs(caplog)
    assert line.endswith("http_status=400 drive_reason=None oauth_error=None")
    assert message not in line


def test_a_drive_code_that_is_not_one_word_is_logged_as_unrecognized(monkeypatch, caplog):
    error = _http_error(400, b'{"error": {"code": 400, "errors": [{"reason": "bad value for someone@example.com"}]}}')

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert _upload_with_failing_chunk(monkeypatch, error) is None

    (line,) = _drive_logs(caplog)
    assert line.endswith("http_status=400 drive_reason=unrecognized oauth_error=None")
    assert "someone@example.com" not in line


def test_an_upload_without_a_drive_service_says_so(monkeypatch, caplog):
    gds = _gds()
    monkeypatch.setattr(gds, "get_drive_service", lambda uid, *, owner: None)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert gds.upload_bytes(7, "image.png", b"\x89PNG", sub_path="code_images", owner="bot") is None

    assert _drive_logs(caplog) == [
        "drive_call_failed op=upload_bytes.no_service owner=bot user_id=7 error_type=None http_status=None drive_reason=None oauth_error=None"
    ]


def test_a_drive_service_that_cannot_be_built_says_why(monkeypatch, caplog):
    gds = _gds()

    def _build(*_a, **_k):
        raise ValueError("discovery document is broken")

    monkeypatch.setattr(gds, "build", _build)
    monkeypatch.setattr(gds, "_ensure_valid_credentials", lambda uid, *, owner: type("Creds", (), {"token": "t", "refresh_token": "r"})())
    monkeypatch.setattr(gds, "_SERVICE_CACHE", {})

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert gds.get_drive_service(7, owner="bot") is None

    assert _drive_logs(caplog) == [
        "drive_call_failed op=build_service owner=bot user_id=7 error_type=ValueError http_status=None drive_reason=None oauth_error=None"
    ]


#: מה ש-google-auth זורק כשגוגל דוחה את ה-refresh token: ``RefreshError(error_details, response_data, retryable=...)`` (``google/oauth2/_client.py``, ``_handle_error_response``, google-auth 2.41.1). ``AuthorizedHttp`` זורק אותה מתוך ``files().list()`` — כך נראה הכשל בפרודקשן (op=ensure_folder, error_type=RefreshError).
_EXPIRED_GRANT = {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}


def _folder_failure(failure):
    from google.auth.exceptions import RefreshError

    if failure == "http":
        return _http_error(404, b'{"error": {"errors": [{"reason": "notFound"}]}}')
    if failure == "refresh":
        return RefreshError("invalid_grant: Token has been expired or revoked.", dict(_EXPIRED_GRANT), retryable=False)
    if failure == "refresh_without_body":
        return RefreshError("The credentials do not contain the necessary fields need to refresh the access token.")
    if failure == "refresh_unrecognized_code":
        return RefreshError("x", {"error": "Not A Code <someone@example.com>"}, retryable=False)
    return ConnectionResetError()


@pytest.mark.parametrize(
    ("failure", "expected_tail"),
    [
        ("http", "error_type=HttpError http_status=404 drive_reason=notFound oauth_error=None"),
        ("other", "error_type=ConnectionResetError http_status=None drive_reason=None oauth_error=None"),
        # הקוד של גוגל הוא מה שמבדיל בין חיבור שמת (invalid_grant) לבין תקלת הגדרות — בלעדיו שני המקרים נראו זהים
        ("refresh", "error_type=RefreshError http_status=None drive_reason=None oauth_error=invalid_grant"),
        ("refresh_without_body", "error_type=RefreshError http_status=None drive_reason=None oauth_error=None"),
        ("refresh_unrecognized_code", "error_type=RefreshError http_status=None drive_reason=None oauth_error=unrecognized"),
    ],
)
def test_a_folder_that_cannot_be_created_says_why(monkeypatch, caplog, failure, expected_tail):
    gds = _gds()
    error = _folder_failure(failure)

    class _Files:
        def list(self, **_k):
            raise error

    monkeypatch.setattr(gds, "get_drive_service", lambda uid, *, owner: type("Svc", (), {"files": lambda self: _Files()})())

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert gds.ensure_folder(7, "zip", "root-1", owner="bot") is None

    assert _drive_logs(caplog) == [f"drive_call_failed op=ensure_folder owner=bot user_id=7 {expected_tail}"]
    assert "someone@example.com" not in "\n".join(_drive_logs(caplog))
