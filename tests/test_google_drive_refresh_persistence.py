"""טוקן שהתקבל מרענון נשמר — ושמירה שנכשלה נרשמת.

``_force_refresh_credentials`` (אחרי 401 באמצע פעולת Drive) מרענן את הטוקן ושומר אותו. החישוב של ``expires_in`` היה ``creds.expiry - _now_utc()``: ה-``expiry`` של google-auth הוא UTC נאיבי, ``_now_utc()`` מודע-אזור, והחיסור זרק ``TypeError`` שנבלע ב-``except: pass`` — כלומר הטוקן החדש לא נשמר אף פעם, והשירות הבא נבנה שוב מהטוקן הישן. ובנוסף ``save_tokens`` מחזיר ``False`` בכשל מסד ולא זורק, ואיש לא בדק את הערך.

הרענון כאן אמיתי (google-auth): רק התעבורה מוחלפת, כך ש-``expiry`` נבנה בדיוק כמו בייצור.
"""

from __future__ import annotations

import importlib
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from google.oauth2.credentials import Credentials

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


@pytest.fixture
def refresh(monkeypatch):
    gds = _gds()
    state = SimpleNamespace(saved=[], result=True)

    def _save_tokens(user_id, tokens, *, owner):
        state.saved.append((user_id, dict(tokens), owner))
        return state.result

    monkeypatch.setattr(gds, "Request", lambda: _transport)
    monkeypatch.setattr(gds, "_load_tokens", lambda uid, *, owner: {"access_token": "ya29.old", "refresh_token": "1//refresh"})
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
