"""טוקן שהתקבל מרענון נשמר, שמירה שנכשלה נרשמת, והניסיון החוזר מקבל את הטוקן המרוענן גם אז.

``_force_refresh_credentials`` (אחרי 401 באמצע פעולת Drive) מרענן את הטוקן ושומר אותו. החישוב של ``expires_in`` היה ``creds.expiry - _now_utc()``: ה-``expiry`` של google-auth הוא UTC נאיבי, ``_now_utc()`` מודע-אזור, והחיסור זרק ``TypeError`` שנבלע ב-``except: pass`` — כלומר הטוקן החדש לא נשמר אף פעם, והשירות הבא נבנה שוב מהטוקן הישן. ובנוסף ``save_tokens`` מחזיר ``False`` בכשל מסד ולא זורק, ואיש לא בדק את הערך. וכשהשמירה נכשלה, הניסיון החוזר טען מהמסד את הטוקן שגוגל כבר דחה: הרענון הגיע אליו רק דרך המסד.

הרענון כאן אמיתי (google-auth): רק התעבורה מוחלפת, כך ש-``expiry`` נבנה בדיוק כמו בייצור. המסד (``_load_tokens`` / ``save_tokens``) ו-``build`` מוחלפים בדמויות.
"""

from __future__ import annotations

import importlib
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httplib2
import pytest
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

LOGGER = "services.google_drive_service"


def _gds():
    # טסטים אחרים טוענים את המודול מחדש; לוקחים את העותק הנוכחי
    return importlib.import_module("services.google_drive_service")


class _TokenResponse:
    """תשובת נקודת הטוקנים של גוגל לרענון מוצלח, בצורה ש-google-auth קורא (``status``, ``headers``, ``data``)."""

    status = 200
    headers: dict = {}
    data = json.dumps({"access_token": "ya29.refreshed", "expires_in": 3600, "token_type": "Bearer"}).encode()


def _transport(url, method="GET", body=None, headers=None, **_kwargs):
    return _TokenResponse()


class _Drive:
    """שירות Drive מדומה, שנבנה מ-``credentials`` כמו ב-``build``: ההעלאה מצליחה רק עם הטוקן המרוענן, וכל ניסיון נרשם עם הטוקן שלו."""

    def __init__(self, credentials, uploads):
        self.token = credentials.token
        self.uploads = uploads

    def files(self):
        return self

    def create(self, body=None, media_body=None, fields=None):
        return self

    def next_chunk(self):
        self.uploads.append(self.token)
        if self.token != "ya29.refreshed":
            raise HttpError(httplib2.Response({"status": 401}), b'{"error": {"code": 401, "errors": [{"reason": "authError"}]}}', uri="https://www.googleapis.com/upload/drive/v3/files")
        return None, {"id": "file-1"}


@pytest.fixture
def refresh(monkeypatch):
    gds = _gds()
    # ``db`` הוא הטוקנים שבמסד: ``_load_tokens`` קורא אותם, ושמירה שהצליחה מעדכנת אותם
    state = SimpleNamespace(saved=[], result=True, db={"access_token": "ya29.old", "refresh_token": "1//refresh"}, uploads=[])

    def _save_tokens(user_id, tokens, *, owner):
        state.saved.append((user_id, dict(tokens), owner))
        if state.result:
            state.db.update(tokens)
        return state.result

    monkeypatch.setattr(gds, "Request", lambda: _transport)
    monkeypatch.setattr(gds, "_load_tokens", lambda uid, *, owner: dict(state.db))
    monkeypatch.setattr(gds, "build", lambda *_a, credentials=None, **_k: _Drive(credentials, state.uploads))
    monkeypatch.setattr(gds, "_SERVICE_CACHE", {})
    monkeypatch.setattr(
        gds,
        "_credentials_from_tokens",
        lambda tokens: Credentials(
            token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            token_uri=gds.TOKEN_URL,
            client_id="client-id",
            client_secret="client-secret",
            scopes=["https://www.googleapis.com/auth/drive.file"],
        ),
    )
    monkeypatch.setattr(gds, "save_tokens", _save_tokens)
    return gds, state


def test_a_forced_refresh_saves_the_new_token_with_a_utc_expiry(refresh):
    gds, state = refresh
    before = datetime.now(timezone.utc)

    assert gds._force_refresh_credentials(7, owner="webapp") is True

    ((user_id, tokens, owner),) = state.saved
    assert (user_id, owner, tokens["access_token"], tokens["refresh_token"]) == (7, "webapp", "ya29.refreshed", "1//refresh")
    expiry = datetime.fromisoformat(tokens["expiry"])
    assert expiry.utcoffset() == timedelta(0)
    assert before + timedelta(seconds=3590) <= expiry <= datetime.now(timezone.utc) + timedelta(seconds=3600)
    assert 3590 <= tokens["expires_in"] <= 3600


def test_a_refreshed_token_that_was_not_saved_is_logged(refresh, caplog):
    gds, state = refresh
    state.result = False

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        # הרענון עצמו הצליח, ולכן הקורא ממשיך איתו — אבל הכישלון בשמירה נרשם
        assert gds._force_refresh_credentials(7, owner="webapp") is True

    assert [r.getMessage() for r in caplog.records if r.name == LOGGER] == ["drive_refresh_not_saved owner=webapp user_id=7"]


class _Media:
    def __init__(self, fh, mimetype=None, resumable=False, chunksize=None):
        assert isinstance(fh, io.BytesIO)


@pytest.mark.parametrize("saved", [False, True])
def test_the_retry_after_a_401_uses_the_refreshed_token_even_when_it_was_not_saved(refresh, monkeypatch, saved):
    """אחרי 401, ``_force_refresh_credentials`` מרענן והפעולה מנסה שוב דרך ``get_drive_service`` — שטוען את הטוקנים מהמסד. כשהשמירה של הטוקן המרוענן נכשלה, הניסיון החוזר טען את הטוקן שגוגל כבר דחה, והרענון הלך לאיבוד (וגם המטמון נוקה, כך שלא נשאר ממנו כלום). ``saved=True`` הוא הבקרה: שם המסד עצמו מחזיק את הטוקן המרוענן."""
    gds, state = refresh
    state.result = saved
    monkeypatch.setattr(gds, "ensure_subpath", lambda uid, sub, *, owner: "folder-1")
    monkeypatch.setattr(gds, "MediaIoBaseUpload", _Media)

    assert gds.upload_bytes(7, "backup.zip", b"PK", sub_path="zip", owner="webapp") == "file-1"

    assert state.uploads == ["ya29.old", "ya29.refreshed"]
    assert state.db["access_token"] == ("ya29.refreshed" if saved else "ya29.old")


def test_a_refresh_whose_service_cannot_be_built_does_not_ask_for_a_retry(refresh, monkeypatch, caplog):
    """בלי שירות של הטוקן המרוענן אין עם מה לנסות שוב, ולכן ``_force_refresh_credentials`` מחזיר ``False`` — והבנייה שנכשלה נרשמת."""
    gds, state = refresh

    def _build(*_a, credentials=None, **_k):
        raise ValueError("discovery document is broken")

    monkeypatch.setattr(gds, "build", _build)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert gds._force_refresh_credentials(7, owner="webapp") is False

    assert [r.getMessage() for r in caplog.records if r.name == LOGGER] == [
        "drive_call_failed op=build_service owner=webapp user_id=7 error_type=ValueError http_status=None drive_reason=None"
    ]
