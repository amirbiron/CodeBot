"""העלאת תוכן בלי לעבור דרך המודל — ``PUT /api/agent/upload`` ו-``upload_id``.

הטסטים עוברים בשכבה שבה כל הבטחה חיה:

1. **החוזה של האחסון** — צורת המזהה, בדיקת ה-TTL, וההצהרה באינדקסים של העלייה.
2. **ה-backend** — שמירה, שליפה, מחיקה-כשער, מכסה, ושער המוכנות שנפתח רק על
   קריאה חוזרת. ``ProductionBackend`` אמיתי מעל מסד מדומה, וההצהרה היא הקוד
   האמיתי של ``DatabaseManager`` (``tests/_uploads_harness.py``).
3. **הראוט, על האפליקציה המלאה ובשני מצבי האימות** — ``build_app`` כפי שהוא
   רץ, דרך ``TestClient`` (``tests/_mcp_apps.py``); והפקודה עצמה, ב-``curl``
   אמיתי מול uvicorn אמיתי.
4. **הכלים** — ``codekeeper_save_file`` ו-``codekeeper_append_file`` עם
   ``upload_id``, דרך ``call_tool`` מעל שכבת השמירה האמיתית
   (``tests/_save_layer_harness.py``), וחד-פעמיות בשני חוטים דרך ה-handler; ובדיקת
   השלמות (``upload_corrupted``), שרצה עם השליפה ולפני כל שער שמחליט לפי הטקסט, עם
   שומר מבני על המקור שאין דרך שליפה או צריכה אחרת. ו-``codekeeper_multi_edit_file``
   עם ``edits_upload_id`` (סעיף 4ב): ההעלאה שם היא רשימת הזוגות כקובץ JSON, ומה
   שנבדק הוא שהיא מפוענחת פעם אחת — לצד שלוש הצורות שבהן ``edits`` מגיע על החוט,
   דרך ``POST /mcp`` עם גוף שנכתב ביד.
5. **נראות** — שורות ה-``INFO``, בתהליך נקי ולא ב-``caplog``.

**בלי ``sleep``:** הדדליין מוקטן, השעון של השער מוזז, והתפוגה נכתבת למסמך.

כל טסט שבודק תיקון הורץ על הקוד שלפני השינוי ונכשל; טסט שמקבע התנהגות שכבר הייתה
נכונה אומר זאת בגוף שלו. כל מוטציה שמוזכרת בגוף טסט הורצה על עותק (``git worktree``)
והפילה אותו. הפלטים בגוף ה-PR.
"""

from __future__ import annotations

import ast
import asyncio
import functools
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import textwrap
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

import anyio  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

# ‏``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _mcp_apps import SERVICE_LOGGING, PatTokens, Served, app_in_mode, curl_path, tool_call_over_http  # noqa: E402
from _save_layer_harness import clear_local_cache, install_fake_collections, load_production_config  # noqa: E402
from _uploads_harness import IndexedCollection, UploadsDbm, install_upload_storage, upload_storage  # noqa: E402

import mcp_uploads  # noqa: E402
from database.manager import DatabaseManager  # noqa: E402
from mcp_server import handlers  # noqa: E402
from mcp_server.backend import ProductionBackend  # noqa: E402
from mcp_server.limits import MIN_MAX_REQUEST_BYTES, BodySizeLimitMiddleware, ToolRateLimiter  # noqa: E402
from mcp_server.downloads import DOWNLOAD_PATH  # noqa: E402
from mcp_server.public_url import MCP_ENDPOINT_PATH, public_base_for  # noqa: E402
from mcp_server.uploads import UPLOAD_PATH, agent_upload_route  # noqa: E402
from mcp_uploads import UploadStorageUnavailable  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
MODES = ["pat", "oauth"]

USER_A, USER_B = 101, 202
#: ‏``ckmcp_`` בראש, כדי שבמצב OAuth ``load_access_token`` ינתב אותם לאימות ה-PAT.
READ_A, WRITE_A, READ_B = "ckmcp_read_a", "ckmcp_write_a", "ckmcp_read_b"
TOKENS = PatTokens({
    READ_A: {"user_id": USER_A, "scopes": ["read"]},
    WRITE_A: {"user_id": USER_A, "scopes": ["read", "write"]},
    READ_B: {"user_id": USER_B, "scopes": ["read"]},
})


# ---------------------------------------------------------------------------
# עזרים
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _production(monkeypatch):
    # ``build_mcp`` קורא ל-``instrument_mcp_server``, שזורק מחוץ לפרודקשן בלי PostHog —
    # אותו קיבוע כמו ב-``tests/test_mcp_content_sha256.py``.
    monkeypatch.setenv("ENVIRONMENT", "production")


@pytest.fixture(autouse=True)
def events(monkeypatch) -> list[tuple]:
    """מה שההצהרה פולטת, במקום ``emit_event`` האמיתי.

    במילון שהפונקציה באמת קוראת ממנו (ה-globals של ``database.manager``), כמו
    ``emitted`` ב-``tests/test_recycle_bin_ttl_index.py`` ומאותה סיבה: ``emit_event``
    ברמת error נכתב למאגר השגיאות האחרונות, שמשותף לכל הטסטים בתהליך.
    """
    recorded: list[tuple] = []
    monkeypatch.setitem(
        DatabaseManager._create_mcp_uploads_indexes.__globals__,
        "emit_event",
        lambda event, severity="info", **fields: recorded.append((event, severity, fields)),
    )
    return recorded


class _Backend(ProductionBackend):
    """``ProductionBackend`` אמיתי מעל מסד מדומה; ``get_file`` עונה "לא נמצא", כדי
    שקריאת כלי דרך ``/mcp`` תרוץ בלי שכבת הקבצים — היא נדרשת כאן רק כקריאה שנספרת."""

    def get_file(self, *args, **kwargs):
        return None


def _backend(*, refuse_ttl: bool = False) -> tuple[_Backend, IndexedCollection]:
    db, uploads = upload_storage(refuse_ttl=refuse_ttl)
    return _Backend(db_manager=UploadsDbm(db), mongo_db=db), uploads


def _put(client, body: bytes, token: str | None = READ_A, **headers):
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    return client.put(UPLOAD_PATH, content=body, headers=headers)


def _closes(response) -> bool:
    return response.headers.get("connection", "").lower() == "close"


def _call_over_http(client, token: str, name: str = "codekeeper_get_file", arguments=None) -> dict:
    """``tools/call`` דרך ``POST /mcp`` (``tool_call_over_http``); בלי ארגומנטים — קריאה שנספרת."""
    return tool_call_over_http(client, token, name, arguments or {"file_name": "x.md"})


def _ceiling(monkeypatch, value: int) -> None:
    """``MAX_CODE_SIZE`` של התצורה שהשירות קורא — ``max_code_size()`` בשני הצדדים."""
    from config import config as cfg

    monkeypatch.setattr(cfg, "MAX_CODE_SIZE", value, raising=False)
    assert handlers.max_code_size() == value


# ---------------------------------------------------------------------------
# 1. החוזה של האחסון
# ---------------------------------------------------------------------------


def test_a_new_upload_id_has_the_shape_the_tools_accept():
    """43 תווים של base64 בטוח ל-URL: 32 בתים, בלי ריפוד (``Lib/secrets.py``)."""
    ids = {mcp_uploads.new_upload_id() for _ in range(500)}
    assert len(ids) == 500
    for upload_id in ids:
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", upload_id), upload_id
        assert mcp_uploads.is_upload_id(upload_id)

    sample = next(iter(ids))
    for bad in (sample + "\n", sample[:-1], sample + "A", "é" * 43, "a b" + "c" * 40, None, 43, b"x" * 43):
        assert mcp_uploads.is_upload_id(bad) is False, repr(bad)


class TestTheUploadTtlPredicate:
    """הקריאה החוזרת של שער המוכנות: שורה מ-``list_indexes`` מול המפרט, ולא השם."""

    @staticmethod
    def _row(**overrides):
        row = {"v": 2, "key": {"expires_at": 1}, "name": "mcp_uploads_ttl", "expireAfterSeconds": 0}
        row.update(overrides)
        return {k: v for k, v in row.items() if v is not None}

    def test_the_declared_spec_matches_under_any_name(self):
        assert mcp_uploads.is_upload_ttl_index(self._row()) is True
        assert mcp_uploads.is_upload_ttl_index(self._row(name="expires_at_1")) is True
        # mongosh שומר ``0.0`` ו-``1.0``; אותו מפרט.
        assert mcp_uploads.is_upload_ttl_index(self._row(key={"expires_at": 1.0}, expireAfterSeconds=0.0)) is True

    @pytest.mark.parametrize("overrides", [
        {"expireAfterSeconds": None},                       # אינדקס רגיל על השדה — אינו מוחק דבר
        {"expireAfterSeconds": 600},                        # משך על ``expires_at`` — מכפיל את זמן החיים
        {"key": {"created_at": 1}},                         # TTL על שדה אחר
        {"key": {"user_id": 1, "expires_at": 1}},           # מורכב — אינו נושא TTL
        {"key": {"expires_at": -1}},                        # לא הכיוון שהוצהר
        {"partialFilterExpression": {"user_id": 1}},        # חלקי — מוחק רק חלק
        {"expireAfterSeconds": False},                      # ``False == 0`` בפייתון, ואינו מספר
    ])
    def test_anything_else_is_not_the_ttl(self, overrides):
        assert mcp_uploads.is_upload_ttl_index(self._row(**overrides)) is False

    def test_a_row_that_is_not_a_mapping_is_not_the_ttl(self):
        assert mcp_uploads.is_upload_ttl_index(None) is False
        assert mcp_uploads.is_upload_ttl_index({"key": "expires_at", "expireAfterSeconds": 0}) is False


class _Coll:
    def create_indexes(self, indexes):
        return None

    def list_indexes(self):
        return []


class _DB:
    def __getitem__(self, name):
        return _Coll()


def _fake_self(safe_create_index) -> SimpleNamespace:
    """``self`` מדומה ל-``DatabaseManager._create_indexes`` — אותה צורה של
    ``tests/test_recycle_bin_ttl_index.py``."""
    return SimpleNamespace(
        collection=_Coll(), large_files_collection=_Coll(), db=_DB(),
        backup_ratings_collection=_Coll(), internal_shares_collection=_Coll(),
        community_library_collection=_Coll(), snippets_collection=_Coll(),
        safe_create_index=safe_create_index,
    )


def test_startup_declares_the_upload_indexes():
    """המפרט כתוב כאן במפורש ולא נקרא מ-``mcp_uploads.py``, בכוונה: טסט שגוזר את
    הציפייה מאותו מקום שהוא בודק לא יתפוס שינוי מקרי במקום הזה.

    **ובמסלול העלייה** (``_create_indexes``), שכל שירות עובר — גם ה-MCP, הכותב
    היחיד — ולא רק בכניסה של שער המוכנות (דפוס 9 ב-``BY-STACK/mongodb.md``).
    """
    requested: list[tuple] = []

    def _safe_create_index(coll, keys, **kwargs):
        requested.append((coll, list(keys), kwargs))
        return True

    DatabaseManager._create_indexes(_fake_self(_safe_create_index))

    declared = {kwargs["name"]: (keys, kwargs) for coll, keys, kwargs in requested if coll == "mcp_uploads"}
    assert set(declared) == {"mcp_uploads_ttl", "mcp_uploads_upload_id", "mcp_uploads_user_expires"}

    keys, ttl = declared["mcp_uploads_ttl"]
    assert keys == [("expires_at", 1)]
    # ``is 0`` ולא אמיתות: חלון של 0 שניות הוא בדיוק הערך המבוקש, והוא שקרי.
    assert ttl["expire_after_seconds"] == 0 and ttl["expire_after_seconds"] is not None
    # בלי אכיפה, אינדקס קיים בשם הזה שאינו במפרט נשאר, וה-TTL לעולם לא נבנה.
    assert ttl["enforce"] is True

    keys, unique = declared["mcp_uploads_upload_id"]
    assert keys == [("upload_id", 1)] and unique["unique"] is True and unique["enforce"] is True

    keys, pending = declared["mcp_uploads_user_expires"]
    assert keys == [("user_id", 1), ("expires_at", 1)]
    assert pending.get("expire_after_seconds") is None and pending["unique"] is False


def test_a_failed_behaviour_index_is_an_error_event_and_a_speed_index_is_not(events):
    """``safe_create_index`` אינו זורק; כשל חוזר כ-``False`` (K11). TTL וייחודי הם
    הבטחה — כשל שלהם יוצא ברמת error; אינדקס ביצועים שנכשל הוא איטיות בלבד."""

    def _safe_create_index(coll, keys, **kwargs):
        return coll != "mcp_uploads"

    results = DatabaseManager.ensure_mcp_uploads_indexes(SimpleNamespace(safe_create_index=_safe_create_index))

    assert results == {"mcp_uploads_ttl": False, "mcp_uploads_upload_id": False, "mcp_uploads_user_expires": False}
    missing = sorted(fields["index_name"] for event, severity, fields in events
                     if event == "db_mcp_uploads_index_missing" and severity == "error")
    assert missing == ["mcp_uploads_ttl", "mcp_uploads_upload_id"]


# ---------------------------------------------------------------------------
# 2. ה-backend
# ---------------------------------------------------------------------------


def _create(backend, text: str, user: int = USER_A) -> str:
    return backend.create_upload(user, text=text, size_bytes=len(text.encode("utf-8")))["upload_id"]


def test_an_upload_is_found_once_and_used_up_by_the_gate():
    backend, uploads = _backend()
    text = "שורה ראשונה\n"
    stored = backend.create_upload(USER_A, text=text, size_bytes=len(text.encode()))
    assert stored["content_sha256"] == hashlib.sha256(text.encode()).hexdigest()

    upload_id = stored["upload_id"]
    assert backend.find_upload(USER_A, upload_id) == {
        "text": text, "bytes": len(text.encode()), "content_sha256": stored["content_sha256"]
    }
    # השליפה אינה צורכת: היא יכולה לחזור, וההעלאה עדיין באוסף.
    assert backend.find_upload(USER_A, upload_id)["text"] == text

    assert backend.consume_upload(USER_A, upload_id, tool="t", size_bytes=1, chars=1) is True
    assert backend.consume_upload(USER_A, upload_id, tool="t", size_bytes=1, chars=1) is False
    assert backend.find_upload(USER_A, upload_id) is None
    assert uploads.docs == []


def test_an_expired_upload_is_gone_for_every_reader_before_mongo_deletes_it():
    """המחיקה של TTL עצלה, ולכן ``expires_at > now`` נבדק בכל קורא.

    מוטציה: ``expires_at`` הוצא מהמסנן של השליפה והמחיקה — הטסט נופל.
    """
    backend, uploads = _backend()
    upload_id = _create(backend, "ישן\n")
    uploads.docs[0]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    assert backend.find_upload(USER_A, upload_id) is None
    assert backend.consume_upload(USER_A, upload_id, tool="t", size_bytes=1, chars=1) is False
    assert backend.pending_upload_expiries(USER_A, limit=5) == []
    assert len(uploads.docs) == 1, "המחיקה של מה שפקע היא של מונגו, לא שלנו"


def test_someone_elses_upload_is_not_there_for_you():
    backend, uploads = _backend()
    upload_id = _create(backend, "של A\n", user=USER_A)

    assert backend.find_upload(USER_B, upload_id) is None
    assert backend.consume_upload(USER_B, upload_id, tool="t", size_bytes=1, chars=1) is False
    assert backend.find_upload(USER_A, upload_id)["text"] == "של A\n"


def test_pending_expiries_are_the_live_uploads_of_one_user_soonest_first():
    backend, uploads = _backend()
    for i in range(3):
        _create(backend, f"{i}\n")
    _create(backend, "b\n", user=USER_B)
    now = datetime.now(timezone.utc)
    uploads.docs[0]["expires_at"] = now + timedelta(seconds=30)
    uploads.docs[1]["expires_at"] = now - timedelta(seconds=30)  # פקע

    expiries = backend.pending_upload_expiries(USER_A, limit=5)
    assert len(expiries) == 2
    assert expiries == sorted(expiries) and expiries[0] == uploads.docs[0]["expires_at"]
    assert all(e.tzinfo is not None for e in expiries)
    assert backend.pending_upload_expiries(USER_A, limit=1) == expiries[:1]


class _Failing(IndexedCollection):
    """אוסף שכל פעולה עליו נכשלת בשגיאת pymongo אמיתית."""

    def __init__(self, error):
        super().__init__()
        self.error = error

    def insert_one(self, doc):
        raise self.error

    def find_one(self, *args, **kwargs):
        raise self.error

    def delete_one(self, *args, **kwargs):
        raise self.error

    def find(self, *args, **kwargs):
        raise self.error


def test_a_database_error_is_upload_storage_unavailable_and_a_bug_is_not():
    """רק שגיאת pymongo מתורגמת; ``TypeError`` הוא באג ועולה כמו שהוא."""
    from pymongo.errors import AutoReconnect

    db, _ = upload_storage()
    db.c["mcp_uploads"] = _Failing(AutoReconnect("connection reset"))
    backend = ProductionBackend(db_manager=UploadsDbm(db), mongo_db=db)
    for call in (
        lambda: backend.create_upload(USER_A, text="x", size_bytes=1),
        lambda: backend.find_upload(USER_A, "a" * 43),
        lambda: backend.consume_upload(USER_A, "a" * 43, tool="t", size_bytes=1, chars=1),
        lambda: backend.pending_upload_expiries(USER_A, limit=5),
    ):
        with pytest.raises(UploadStorageUnavailable) as caught:
            call()
        assert isinstance(caught.value.__cause__, AutoReconnect)

    db.c["mcp_uploads"] = _Failing(TypeError("a bug, not a database"))
    with pytest.raises(TypeError):
        backend.find_upload(USER_A, "a" * 43)


def test_discarding_a_corrupted_upload_logs_a_database_error_and_lets_a_bug_through():
    """השלכת העלאה משובשת היא ניקיון ולא השער: התשובה לסוכן אינה תלויה בה.

    שגיאת מסד נרשמת (בשורה של ההשלכה, עם "deleted: unknown") ואינה עולה, וההעלאה
    פוקעת ב-TTL. ``TypeError`` הוא באג ועולה כמו שהוא — אותו קו של
    ``test_a_database_error_is_upload_storage_unavailable_and_a_bug_is_not``.
    """
    from pymongo.errors import AutoReconnect

    db, _ = upload_storage()
    db.c["mcp_uploads"] = _Failing(AutoReconnect("connection reset"))
    backend = ProductionBackend(db_manager=UploadsDbm(db), mongo_db=db)
    discard = functools.partial(
        backend.discard_upload, USER_A, "a" * 43, tool="t", reason="hash_mismatch", size_bytes=1, chars=1
    )
    assert discard() is None

    db.c["mcp_uploads"] = _Failing(TypeError("a bug, not a database"))
    with pytest.raises(TypeError):
        discard()


def test_an_unacknowledged_insert_is_not_an_upload():
    """‏``w=0``: אין עדות שנשמר דבר, ומזהה שיימסר עליו היה נענה ``upload_not_found``."""

    class _Unacknowledged(IndexedCollection):
        def insert_one(self, doc):
            result = super().insert_one(doc)
            result.acknowledged = False
            return result

    db, _ = upload_storage()
    db.c["mcp_uploads"] = _Unacknowledged()
    backend = ProductionBackend(db_manager=UploadsDbm(db), mongo_db=db)
    with pytest.raises(UploadStorageUnavailable):
        backend.create_upload(USER_A, text="x", size_bytes=1)


def test_the_gate_opens_on_a_read_back_and_not_on_a_claim():
    """``ensure_mcp_uploads_indexes`` שאומר "בניתי" בלי שהאינדקס קיים — השער סגור.

    מוטציה: ``_confirm_upload_ttl`` מחזיר את ערך ההחזרה של ההצהרה במקום
    ``list_indexes`` — הטסט נופל.
    """
    db, uploads = upload_storage()

    class _Claims:
        def ensure_mcp_uploads_indexes(self):
            return {"mcp_uploads_ttl": True, "mcp_uploads_upload_id": True, "mcp_uploads_user_expires": True}

    assert ProductionBackend(db_manager=_Claims(), mongo_db=db).upload_storage_ready() is False
    # ...ומול ההצהרה האמיתית, אותו אוסף נפתח — וה-TTL באמת שם.
    assert ProductionBackend(db_manager=UploadsDbm(db), mongo_db=db).upload_storage_ready() is True
    assert uploads.indexes["mcp_uploads_ttl"]["expireAfterSeconds"] == 0


def test_a_ttl_that_cannot_be_built_keeps_the_gate_shut_and_retries_after_the_pause(monkeypatch, events):
    """fail-closed, בלי לולאה חמה: ניסיון אחד בחלון, ועוד אחד אחרי ההשהיה.

    ובלי נעילה: ``_ensure_enforced_index`` אינו ממתין לבנייה של אחר — ראו את
    ה-docstring שלו ו-``docs/performance-sticky-notes.rst``.
    """
    import mcp_server.backend as backend_module

    clock = {"now": 1000.0}
    monkeypatch.setattr(backend_module._time, "monotonic", lambda: clock["now"])
    attempts = []
    backend, uploads = _backend(refuse_ttl=True)
    real_create = uploads.create_index

    def _counting(keys, **kwargs):
        if kwargs.get("expireAfterSeconds") is not None:
            attempts.append(kwargs["name"])
        return real_create(keys, **kwargs)

    uploads.create_index = _counting

    assert backend.upload_storage_ready() is False
    assert backend.upload_storage_ready() is False
    assert attempts == ["mcp_uploads_ttl"], "נוסה שוב בתוך חלון ההמתנה"
    assert [f["index_name"] for e, s, f in events if e == "db_mcp_uploads_index_missing"] == ["mcp_uploads_ttl"]

    clock["now"] += ProductionBackend._INDEX_RETRY_SECONDS + 1
    uploads.refuse_ttl = False
    assert backend.upload_storage_ready() is True
    assert attempts == ["mcp_uploads_ttl", "mcp_uploads_ttl"]


# ---------------------------------------------------------------------------
# 3. הראוט — האפליקציה המלאה, בשני מצבי האימות
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_without_a_valid_token_it_is_a_401_that_closes_the_connection(mode):
    """‏401 מהראוט עצמו — גם במצב PAT, שבו הנתיב פטור מ-``PATAuthMiddleware``.

    ובלי שדבר נוגע באחסון: לא הספירה, לא שער המוכנות.
    """
    backend, uploads = _backend()
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS)) as client:
        for token in (None, "ckmcp_not_a_token", "not-a-pat-either"):
            response = _put(client, b"secret text", token=token)
            assert response.status_code == 401, (token, response.text)
            assert response.json() == {"error": "invalid_token"}
            assert _closes(response) and "www-authenticate" in response.headers
    assert uploads.docs == [] and uploads.indexes == {}


@pytest.mark.parametrize("mode", MODES)
def test_a_read_token_is_enough_and_the_answer_is_the_hash_of_the_bytes_sent(mode):
    """‏201 על טוקן ``read`` — זו ההכרעה, לא 403. וה-hash הוא של הבתים שנשלחו,
    מחושב כאן ב-``hashlib`` ולא דרך הפונקציה של ה-backend."""
    backend, uploads = _backend()
    raw = "דוח ארוך — שורה ראשונה\n\U0001F468‍\U0001F469‍\U0001F467 ועוד\r\n".encode("utf-8")
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS)) as client:
        response = _put(client, raw, token=READ_A)

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"upload_id", "bytes", "chars", "content_sha256", "expires_in_seconds"}
    assert body["content_sha256"] == hashlib.sha256(raw).hexdigest()
    assert body["bytes"] == len(raw) and body["chars"] == len(raw.decode("utf-8"))
    assert body["expires_in_seconds"] == 600
    assert mcp_uploads.is_upload_id(body["upload_id"])
    assert not _closes(response), "תשובה מוצלחת משאירה את החיבור"

    (doc,) = uploads.docs
    assert doc["upload_id"] == body["upload_id"] and doc["user_id"] == USER_A
    assert doc["text"] == raw.decode("utf-8")
    assert doc["expires_at"] - doc["created_at"] == timedelta(seconds=600)


def test_a_bom_stays_a_character_as_it_does_in_code():
    """‏``utf-8`` ולא ``utf-8-sig``. מוטציה: ``utf-8-sig`` — הטסט נופל."""
    backend, uploads = _backend()
    raw = b"\xef\xbb\xbf# title\n"
    with TestClient(app_in_mode("pat", backend, tokens=TOKENS)) as client:
        body = _put(client, raw).json()
    assert body["chars"] == len("﻿# title\n")
    assert body["content_sha256"] == hashlib.sha256(raw).hexdigest()
    assert uploads.docs[0]["text"] == "﻿# title\n"


@pytest.mark.parametrize("raw, error, status", [
    (b"", "empty_upload", 400),
    (b"\xff\xfe", "invalid_utf8", 400),
    (b"abc\x80", "invalid_utf8", 400),
    (b"\xed\xa0\x80", "invalid_utf8", 400),   # surrogate מקודד — UTF-8 קפדני דוחה
    (b"\xc0\xaf", "invalid_utf8", 400),       # overlong
])
@pytest.mark.parametrize("mode", MODES)
def test_a_body_that_is_not_text_is_refused_and_closes(mode, raw, error, status):
    backend, uploads = _backend()
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS)) as client:
        response = _put(client, raw)
    assert response.status_code == status and response.json() == {"error": error}
    assert _closes(response)
    assert uploads.docs == []


@pytest.mark.parametrize("mode", MODES)
def test_text_over_the_code_ceiling_is_413_code_too_large_counted_in_characters(mode, monkeypatch):
    """אותה תקרה ואותו קוד של ``codekeeper_save_file`` — ``max_code_size()`` — ובתווים:
    "שלום!" הוא 5 תווים ו-9 בתים."""
    _ceiling(monkeypatch, 5)
    backend, uploads = _backend()
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS)) as client:
        over = _put(client, b"abcdef")
        fits = _put(client, "שלום!".encode("utf-8"))
    assert over.status_code == 413 and over.json() == {"error": "code_too_large", "max": 5}
    assert _closes(over)
    assert fits.status_code == 201
    assert [d["text"] for d in uploads.docs] == ["שלום!"]


@pytest.mark.parametrize("mode", MODES)
def test_a_declared_length_over_the_body_cap_is_the_middlewares_413_and_the_route_never_runs(mode):
    backend, uploads = _backend()
    touched = []
    backend.pending_upload_expiries = lambda *a, **k: touched.append("count") or []
    app = app_in_mode(mode, backend, tokens=TOKENS, max_request_bytes=MIN_MAX_REQUEST_BYTES)
    body = b"x" * (MIN_MAX_REQUEST_BYTES + 1)
    with TestClient(app) as client:
        response = _put(client, body)
    assert response.status_code == 413
    assert response.json() == {"error": "body_too_large", "max_bytes": MIN_MAX_REQUEST_BYTES,
                               "content_length": len(body)}
    assert _closes(response)
    assert touched == [] and uploads.docs == []


@pytest.mark.parametrize("mode", MODES)
def test_the_sixth_pending_upload_waits_for_the_oldest_to_expire(mode):
    """מוטציה: ``expires_at`` הוצא מהספירה — העלאה שפקעה עדיין תופסת מקום, והטסט נופל."""
    backend, uploads = _backend()
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS)) as client:
        for i in range(5):
            assert _put(client, f"{i}\n".encode()).status_code == 201
        refused = _put(client, b"6\n")
        assert refused.status_code == 429 and _closes(refused)
        body = refused.json()
        assert body["error"] == "too_many_pending_uploads" and body["max"] == 5 and "ok" not in body
        assert 590 <= body["retry_after_seconds"] <= 600
        assert len(uploads.docs) == 5

        # לכל משתמש המכסה שלו.
        assert _put(client, b"b\n", token=READ_B).status_code == 201

        # הישנה ביותר פקעה — לפני שמונגו מחק אותה.
        oldest = min((d for d in uploads.docs if d["user_id"] == USER_A), key=lambda d: d["expires_at"])
        oldest["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert _put(client, b"7\n").status_code == 201


@pytest.mark.parametrize("mode", MODES)
def test_an_unverified_ttl_index_is_503_and_nothing_is_stored(mode, events):
    """מוטציה: ההתעלמות מהקריאה החוזרת (השער נפתח על ערך ההחזרה) — הטסט נופל."""
    backend, uploads = _backend(refuse_ttl=True)
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS)) as client:
        response = _put(client, b"text\n")
    assert response.status_code == 503 and response.json() == {"error": "upload_storage_unavailable"}
    assert _closes(response)
    assert uploads.docs == []
    assert ("db_mcp_uploads_index_missing", "error") in {(e, s) for e, s, _ in events}


@pytest.mark.parametrize("mode", MODES)
def test_an_upload_and_a_tool_call_draw_on_one_quota(mode):
    """המגביל של הראוט **הוא** המגביל של ``call_tool``: שתי קריאות מתוך שתיים.

    מוטציה: מגביל נפרד לראוט (``ToolRateLimiter(...)`` חדש ב-``build_app``) —
    ההעלאה השלישית עוברת, והטסט נופל.
    """
    backend, _ = _backend()
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS, rate_limit_per_minute=2)) as client:
        assert _put(client, b"one\n").status_code == 201
        assert "rate_limited" not in _call_over_http(client, READ_A)["text"]
        refused = _put(client, b"two\n")
        assert refused.status_code == 429 and _closes(refused)
        body = refused.json()
        assert body["error"] == "rate_limited" and body["limit_per_minute"] == 2 and "ok" not in body
        assert body["retry_after_seconds"] >= 1
        # ...ולזהות אחרת המכסה שלה.
        assert _put(client, b"three\n", token=READ_B).status_code == 201

    backend, _ = _backend()
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS, rate_limit_per_minute=2)) as client:
        _call_over_http(client, READ_A)
        _call_over_http(client, READ_A)
        assert _put(client, b"four\n").status_code == 429


def _scope(headers) -> dict:
    return {
        "type": "http", "http_version": "1.1", "method": "PUT", "path": UPLOAD_PATH,
        "raw_path": UPLOAD_PATH.encode(), "root_path": "", "query_string": b"",
        "headers": [(k.encode(), v.encode()) for k, v in headers],
        "server": ("test", 80), "client": ("127.0.0.1", 1), "scheme": "http",
    }


async def test_a_declared_body_that_drips_is_408_within_the_routes_own_deadline():
    """‏``Content-Length: 1000`` ו-100 בתים, ואז כלום.

    אורך מוצהר תקין עובר את ``BodySizeLimitMiddleware`` בלי קריאה, ולכן הדדליין
    היחיד כאן הוא של הראוט. ההרכבה היא של הייצור — המידלוור עוטף את הראוט.
    מוטציה: בלי ``fail_after`` בראוט — ה-``fail_after(5)`` של הטסט פוקע, והוא נופל.
    """
    backend, uploads = _backend()
    route = agent_upload_route(backend, token_store=TOKENS, rate_limiter=ToolRateLimiter(60), read_timeout=0.3)
    app = BodySizeLimitMiddleware(Starlette(routes=[route]), max_bytes=10_000)
    stalled = anyio.Event()
    messages = [{"type": "http.request", "body": b"x" * 100, "more_body": True}]
    sent: list[dict] = []

    async def receive():
        if messages:
            return messages.pop(0)
        await stalled.wait()  # הלקוח הפסיק לשלוח, ולא ניתק

    async def send(message):
        sent.append(message)

    started = time.monotonic()
    with anyio.fail_after(5):
        await app(_scope([("content-length", "1000"), ("authorization", f"Bearer {READ_A}")]), receive, send)
    elapsed = time.monotonic() - started

    start = next(m for m in sent if m["type"] == "http.response.start")
    body = json.loads(b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body"))
    assert start["status"] == 408
    assert body == {"error": "body_read_timeout", "read_timeout_seconds": 0.3, "received_bytes": 100}
    assert (b"connection", b"close") in start["headers"]
    assert elapsed < 2.5
    assert uploads.docs == []


#: מה שעונה בלי טוקן במשהו שאינו 401 — **רשימה סגורה ומפורשת**. ``/healthz`` בשני
#: המצבים; ונקודות ה-OAuth שה-SDK רושם (``/token`` ו-``/revoke`` עונים 401 בעצמם,
#: ולכן אינם כאן), ועמוד ההסכמה.
PUBLIC = {
    "pat": {"/healthz"},
    "oauth": {"/healthz", "/.well-known/oauth-authorization-server",
              "/.well-known/oauth-protected-resource", "/authorize", "/register", "/oauth/consent"},
}


@pytest.mark.parametrize("mode", MODES)
def test_every_route_answers_401_without_a_token_except_a_closed_list(mode):
    """ההעלאה וההורדה מאמתות בגוף שלהן, כמו הפריימר; הטסט מונע מהראוט הבא לשכוח.

    בשני הכיוונים: ראוט חדש שעונה בלי טוקן מפיל אותו, וגם רשומה ברשימה שכבר
    אינה ציבורית — רשימה שמתיישנת בשקט אינה שומרת על כלום.
    """
    backend, _ = _backend()
    app = app_in_mode(mode, backend, tokens=TOKENS)
    answered = set()
    protected = set()
    with TestClient(app, raise_server_exceptions=False) as client:
        for route in app.router.routes:
            methods = sorted(set(getattr(route, "methods", None) or {"GET"}) - {"HEAD"})
            statuses = {client.request(method, route.path).status_code for method in methods}
            (protected if statuses == {401} else answered).add(route.path)
    assert answered == PUBLIC[mode]
    # ``MCP_ENDPOINT_PATH`` ולא ``"/mcp"``: עמוד ההגדרות בוובאפ מציג את הקבוע הזה בכתובת
    # שמדביקים בלקוח, ולכן האפליקציה האמיתית חייבת להגיש בדיוק אותו.
    assert {MCP_ENDPOINT_PATH, "/api/agent/primer", UPLOAD_PATH, DOWNLOAD_PATH} <= protected


# ---------------------------------------------------------------------------
# הפקודה — ``curl`` אמיתי, מול uvicorn אמיתי
# ---------------------------------------------------------------------------


# ``Served`` ו-``curl_path`` חיים ב-``tests/_mcp_apps.py``, משותפים עם טסטי ההורדה.
_Served = Served
_curl = curl_path


@pytest.mark.parametrize("expect", ["Expect: 100-continue", "Expect:"])
def test_the_command_in_the_tool_description_uploads_the_file_as_it_is(tmp_path, expect):
    """הפקודה **מתוך תיאור הפרמטר**, ב-``bash``, עם ``$CODEKEEPER_PAT`` בסביבה.

    curl 8.5.0 שולח ``Expect: 100-continue`` רק מעל 1MiB או כשהגודל אינו ידוע, ולא
    ב-HTTP/2 — ולכן שני המסלולים נכפים בכותרת ולא נשענים על מה ש-curl יבחר.
    """
    import mcp_server.server as srv

    curl = _curl()
    raw = ("# דוח\n" + "שורה עם ‏ כיווניות ו-\U0001F600\r\n" * 200).encode("utf-8")
    (tmp_path / "report.md").write_bytes(raw)
    backend, uploads = _backend()
    with _Served(app_in_mode("pat", backend, tokens=TOKENS)) as served:
        base = f"http://127.0.0.1:{served.port}"
        described = srv.build_mcp(backend, public_url=base)._tool_manager.get_tool("codekeeper_save_file")
        doc = described.parameters["properties"]["upload_id"]["description"]
        command = re.search(r'curl -sS -T report\.md -H "Authorization: Bearer \$CODEKEEPER_PAT" \S+', doc).group(0)
        assert command.endswith(f"{base}{UPLOAD_PATH}")

        proc = subprocess.run(
            ["bash", "-c", command.replace("curl ", f"{curl} -H '{expect}' ", 1)],
            cwd=tmp_path, capture_output=True, timeout=60,
            env={**os.environ, "CODEKEEPER_PAT": READ_A},
        )
    assert proc.returncode == 0, proc.stderr
    body = json.loads(proc.stdout)
    assert body["content_sha256"] == hashlib.sha256(raw).hexdigest()
    assert body["bytes"] == len(raw)
    assert uploads.docs[0]["text"].encode("utf-8") == raw


def test_a_refusal_over_the_wire_says_connection_close(tmp_path):
    curl = _curl()
    (tmp_path / "report.md").write_bytes(b"x\n")
    backend, _ = _backend()
    with _Served(app_in_mode("pat", backend, tokens=TOKENS)) as served:
        proc = subprocess.run(
            [curl, "-sS", "-D", "-", "-o", os.devnull, "-T", "report.md",
             f"http://127.0.0.1:{served.port}{UPLOAD_PATH}"],
            cwd=tmp_path, capture_output=True, text=True, timeout=60,
        )
    headers = proc.stdout.lower()
    assert " 401 " in headers.splitlines()[0]
    assert "connection: close" in headers


# ---------------------------------------------------------------------------
# תיאורי הכלים
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("public_url, expected", [
    (None, "https://<mcp-host>"),
    ("", "https://<mcp-host>"),
    ("https://mcp.example.com", "https://mcp.example.com"),
    ("https://mcp.example.com/", "https://mcp.example.com"),
    ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
    ("https://user:hunter2@mcp.example.com", "https://<mcp-host>"),
    ("https://mcp.example.com?token=hunter2", "https://<mcp-host>"),
    ("ftp://mcp.example.com", "https://<mcp-host>"),
    ("https://[::1", "https://<mcp-host>"),
    ("mcp.example.com", "https://<mcp-host>"),
    ("https://mcp.example.com:8443", "https://mcp.example.com:8443"),
    ("https://mcp.example.com:abc", "https://<mcp-host>"),
    ("https://mcp.example.com:99999", "https://<mcp-host>"),
])
def test_the_base_of_the_commands_in_the_descriptions_is_the_configured_host_or_a_placeholder(public_url, expected):
    """‏``MCP_SERVER_URL`` נכנס לתיאור שכל לקוח מקבל — בלי סיסמה ובלי query (K13).

    הבסיס משותף לפקודת ההעלאה ולפקודת ההורדה (``mcp_server/public_url.py``); כל ראוט
    מצרף אליו את הנתיב שלו.
    """
    assert public_base_for(public_url) == expected


def test_the_descriptions_carry_the_rule_first_the_minutes_and_the_ceiling(monkeypatch):
    import mcp_server.server as srv

    _ceiling(monkeypatch, 12_345)
    tools = srv.build_mcp(_backend()[0], public_url="https://mcp.example.com")._tool_manager
    for name, instead_of in (("codekeeper_save_file", "code"), ("codekeeper_append_file", "content")):
        props = tools.get_tool(name).parameters["properties"]
        upload_doc = props["upload_id"]["description"]
        # הכלל במשפט הראשון, וכולו בתוך 120 תווים: לקוח שמקצר תיאור פרמטר לשורת
        # סיכום רואה רק אותו.
        rule = upload_doc.split(". ", 1)[0]
        assert len(rule) <= 120, rule
        assert rule.startswith(f"Instead of {instead_of}, for text already in a file")
        assert "single-use" in rule and "size ceiling still applies" in rule
        assert "valid for 10 minutes" in upload_doc
        assert "https://mcp.example.com/api/agent/upload" in upload_doc
        assert "CODEKEEPER_PAT (Claude.ai" in upload_doc
        assert "12,345" in props[instead_of]["description"]
        assert "upload_id" in props[instead_of]["description"]
        assert instead_of not in tools.get_tool(name).parameters.get("required", [])
        assert "upload_id" in tools.get_tool(name).description


def test_the_upload_id_description_names_the_parameter_and_leaves_refusals_to_their_hints():
    """מה שהלקוח מקבל ב-``tools/list``: בלי רשימת הסירובים, ושם הפרמטר נקרא כשם פרמטר.

    הסירובים רלוונטיים רק אחרי כשל, ואז כל אחד נושא ``hint`` משלו (הטסט שאחרי זה);
    התיאור נקרא בכל שיחה שבה הכלים נטענים, גם ב-Claude.ai. ו-``content`` הוא גם שם
    עצם: הנוסח הקודם יצא "send the content in content as usual".
    """
    import mcp_server.server as srv

    listed = asyncio.run(srv.build_mcp(_backend()[0], public_url="https://mcp.example.com").list_tools())
    tools = {tool.name: tool for tool in listed}
    for name, param in (("codekeeper_save_file", "code"), ("codekeeper_append_file", "content")):
        doc = tools[name].inputSchema["properties"]["upload_id"]["description"]
        assert doc.endswith(
            f"Without bash, network access or CODEKEEPER_PAT (Claude.ai, for one), use the {param} parameter as usual."
        ), doc
        for word in ("Refusals", "upload_not_found", "upload_corrupted", "invalid_upload_id", f"{param}_and_upload_id"):
            assert word not in doc, word
        assert f"{param} in {param}" not in doc and f"{param}, for {param}" not in doc


#: כל כלי שמקבל העלאה, כפי שהטסטים קוראים לו: ``(הכלי, הפרמטר שההעלאה באה במקומו,
#: הפרמטר שנושא את המזהה, ערך inline תקין, הסירוב כשלא נשלח אף אחד מהשניים, מה ה-hint
#: מציע לעשות בלי העלאה)``. ב-``codekeeper_multi_edit_file`` ההעלאה היא רשימת הזוגות,
#: הפרמטר נקרא ``edits_upload_id``, והנסיגה היא ``codekeeper_edit_file`` ולא "inline".
_ONE_EDIT = [{"old_string": "head", "new_string": "HEAD"}]
_TAKES_AN_UPLOAD = [
    ("codekeeper_save_file", "code", "upload_id", "inline\n", "empty_code", "send the content inline"),
    ("codekeeper_append_file", "content", "upload_id", "inline\n", "empty_content", "send the content inline"),
    ("codekeeper_multi_edit_file", "edits", "edits_upload_id", _ONE_EDIT, "missing_edits", "codekeeper_edit_file"),
]
#: שם הפרמטר שנושא את המזהה, לכל כלי — לטסטים שרצים על כמה כלים.
_UPLOAD_ARG = {tool: upload_arg for tool, _, upload_arg, _, _, _ in _TAKES_AN_UPLOAD}


@pytest.mark.parametrize(
    "tool, param, upload_arg, inline, neither_error, otherwise", _TAKES_AN_UPLOAD, ids=[row[0] for row in _TAKES_AN_UPLOAD]
)
def test_every_upload_refusal_carries_a_hint_that_names_the_parameter(
    store, backend, call, tool, param, upload_arg, inline, neither_error, otherwise
):
    """התיאור אינו מונה את הסירובים, ולכן ההסבר שבכל סירוב הוא ההסבר היחיד שהסוכן מקבל.

    **וההסבר נוקב בשמות של הכלי הזה.** העוזרים של ההעלאה משותפים, והשמות היו מוקלדים
    בתוכם — ``upload_id`` ו-"send the content inline". ב-``codekeeper_multi_edit_file``
    הפרמטר הוא ``edits_upload_id`` וההעלאה היא רשימת הזוגות, ולכן סירוב שנוקב שם ב-
    ``upload_id`` שולח את הסוכן לחפש פרמטר שאין בכלי, ו-"inline" מחזיר אותו ל-``edits``.
    """
    assert call("codekeeper_save_file", file_name="log.md", code="head\n")["ok"] is True
    upload_id = _create(backend, "tail\n")
    hints: list[str] = []

    both = call(tool, file_name="log.md", **{upload_arg: upload_id, param: inline})
    assert both["error"] == f"{param}_and_{upload_arg}"
    assert both["hint"] == f"pass either the {param} parameter or {upload_arg}, not both"
    hints.append(both["hint"])

    neither = call(tool, file_name="log.md")
    assert neither["error"] == neither_error
    if upload_arg == "upload_id":
        assert f"in the {param} parameter, or upload the file first and pass upload_id" in neither["hint"]
    else:
        # "לא נשלח" הוא רשימה ריקה, והתשובה היא זו של רשימה ריקה שנשלחה — בלי שדה נוסף.
        assert neither == {"ok": False, "error": "missing_edits"}

    invalid = call(tool, file_name="log.md", **{upload_arg: "../../etc/passwd"})
    assert invalid["error"] == f"invalid_{upload_arg}"
    assert upload_arg in invalid["hint"], invalid
    hints.append(invalid["hint"])

    not_found = call(tool, file_name="log.md", **{upload_arg: mcp_uploads.new_upload_id()})
    assert not_found["error"] == "upload_not_found"
    assert otherwise in not_found["hint"], not_found
    hints.append(not_found["hint"])

    if upload_arg != "upload_id":
        for hint in hints:
            assert "inline" not in hint, hint
            assert "upload_id" not in hint.replace(upload_arg, ""), hint

    assert len(store.uploads.docs) == 1


# ---------------------------------------------------------------------------
# 4. הכלים — ``upload_id`` ב-``codekeeper_save_file`` וב-``codekeeper_append_file``
# ---------------------------------------------------------------------------


@pytest.fixture
def store(monkeypatch):
    load_production_config(monkeypatch)
    harness = install_fake_collections(monkeypatch)
    harness.uploads = install_upload_storage(monkeypatch, harness)
    yield harness
    clear_local_cache()


@pytest.fixture
def backend(store):
    return ProductionBackend(db_manager=store.dbm, mongo_db=store.raw)


@pytest.fixture
def call(monkeypatch, backend):
    """``call_tool`` על שרת MCP אמיתי; ``user=`` קובע מי קורא, כמו ``current_user_id``."""
    import mcp.server.auth.middleware.auth_context as auth_context

    import mcp_server.server as srv

    who = {"user": USER_A}
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: who["user"])
    monkeypatch.setattr(auth_context, "get_access_token", lambda: SimpleNamespace(scopes=["read", "write"]))
    mcp = srv.build_mcp(backend)

    def _call(tool: str, *, user: int = USER_A, **arguments) -> dict:
        who["user"] = user
        result = asyncio.run(mcp.call_tool(tool, arguments))
        blocks = result[0] if isinstance(result, tuple) else result
        return json.loads(blocks[0].text)

    return _call


def _stored_code(store, file_id: str) -> str:
    (doc,) = [d for d in store.code_snippets.docs if str(d.get("_id")) == file_id]
    return doc["code"]


def test_save_file_takes_the_content_from_an_upload_and_uses_it_up(store, backend, call):
    text = "# דוח\nשורה עם ‏ ו-\r\n\n\n"
    upload_id = _create(backend, text)

    saved = call("codekeeper_save_file", file_name="report.md", upload_id=upload_id, description="d")
    assert saved["ok"] is True and saved["content_changed"] is False, saved
    assert _stored_code(store, saved["file"]["id"]) == text
    assert saved["file"]["content_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert store.uploads.docs == []

    again = call("codekeeper_save_file", file_name="other.md", upload_id=upload_id)
    assert again["ok"] is False and again["error"] == "upload_not_found"
    assert [d["file_name"] for d in store.code_snippets.docs] == ["report.md"]


def test_code_and_upload_id_together_is_refused_before_anything_is_read(store, backend, call):
    upload_id = _create(backend, "x\n")
    res = call("codekeeper_save_file", file_name="a.md", code="inline\n", upload_id=upload_id)
    assert res["ok"] is False and res["error"] == "code_and_upload_id"
    assert len(store.uploads.docs) == 1 and store.code_snippets.docs == []


def test_no_content_at_all_is_empty_code_that_names_the_other_way(store, call):
    res = call("codekeeper_save_file", file_name="a.md")
    assert res["ok"] is False and res["error"] == "empty_code" and "upload_id" in res["hint"]
    assert store.code_snippets.docs == []


@pytest.mark.parametrize("bad", ["../../etc/passwd", "a" * 42, "a" * 44, "", " " + "a" * 42])
def test_an_upload_id_of_the_wrong_shape_is_refused_without_echoing_it(store, call, bad):
    res = call("codekeeper_save_file", file_name="a.md", upload_id=bad)
    assert res["ok"] is False and res["error"] == "invalid_upload_id"
    if bad.strip():
        assert bad.strip() not in json.dumps(res)


def test_someone_elses_upload_is_not_found_and_stays_for_its_owner(store, backend, call):
    """העלאה בטוקן של A, שמירה בטוקן של B — ``upload_not_found``, אותה תשובה של פגה."""
    upload_id = _create(backend, "של A\n", user=USER_A)
    theirs = call("codekeeper_save_file", user=USER_B, file_name="b.md", upload_id=upload_id)
    assert theirs["ok"] is False and theirs["error"] == "upload_not_found"
    assert store.code_snippets.docs == []

    mine = call("codekeeper_save_file", user=USER_A, file_name="a.md", upload_id=upload_id)
    assert mine["ok"] is True


def test_an_expired_upload_is_not_found_even_before_mongo_deletes_it(store, backend, call):
    upload_id = _create(backend, "ישן\n")
    store.uploads.docs[0]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    res = call("codekeeper_save_file", file_name="old.md", upload_id=upload_id)
    assert res["ok"] is False and res["error"] == "upload_not_found"
    assert store.code_snippets.docs == []


def test_file_exists_does_not_use_up_the_upload(store, backend, call):
    """הבדיקה באה לפני השער, ולכן סירוב שלה משאיר את ההעלאה לשמירה בשם אחר."""
    assert call("codekeeper_save_file", file_name="taken.md", code="old\n")["ok"] is True
    upload_id = _create(backend, "new\n")

    refused = call("codekeeper_save_file", file_name="taken.md", upload_id=upload_id)
    assert refused["ok"] is False and refused["error"] == "file_exists"
    assert len(store.uploads.docs) == 1

    saved = call("codekeeper_save_file", file_name="free.md", upload_id=upload_id)
    assert saved["ok"] is True and _stored_code(store, saved["file"]["id"]) == "new\n"


def test_a_file_over_the_ceiling_does_not_use_up_the_upload(store, backend, call, monkeypatch):
    upload_id = _create(backend, "abcdef\n")
    _ceiling(monkeypatch, 5)
    res = call("codekeeper_save_file", file_name="big.md", upload_id=upload_id)
    assert res == {"ok": False, "error": "code_too_large", "max": 5}
    assert len(store.uploads.docs) == 1


def test_a_save_that_fails_after_the_gate_says_the_upload_was_used_up(store, backend, call, monkeypatch):
    """המחיר של "המחיקה היא השער", בכוונה — והתשובה אומרת אותו."""
    upload_id = _create(backend, "x\n")
    monkeypatch.setattr(store.dbm, "save_code_snippet_returning_id", lambda snippet: None)
    res = call("codekeeper_save_file", file_name="a.md", upload_id=upload_id)
    assert res["ok"] is False and res["error"] == "save_failed"
    assert res["upload_consumed"] is True and "upload the file again" in res["hint"]
    assert store.uploads.docs == []


class _Racing(IndexedCollection):
    """שני צורכים עוברים יחד את השליפה, ורק אז ממשיכים — המרוץ שהשער סוגר.

    ``delete_one`` אטומי במסד; כאן נעילה נותנת לו את אותה תכונה, כי הדמה המשותפת
    אינה בטוחה לחוטים.
    """

    def __init__(self):
        super().__init__()
        self.both_fetched = threading.Barrier(2, timeout=10)
        self.lock = threading.Lock()

    def find_one(self, *args, **kwargs):
        with self.lock:
            found = super().find_one(*args, **kwargs)
        self.both_fetched.wait()
        return found

    def delete_one(self, *args, **kwargs):
        with self.lock:
            return super().delete_one(*args, **kwargs)


def test_two_consumers_of_one_upload_save_exactly_once(store, backend):
    """ישירות דרך ה-handler: תור הכתיבה מסדר קריאות ``call_tool`` בטור, ודרכו הטסט
    לא היה יכול ליפול. מוטציה: מחיקה אחרי השמירה — שתיהן שומרות, והטסט נופל."""
    racing = _Racing()
    store.raw.c["mcp_uploads"] = racing
    upload_id = _create(backend, "פעם אחת בלבד\n")
    answers: dict[str, dict] = {}

    def consume(name: str) -> None:
        answers[name] = handlers.save_file(backend, USER_A, file_name=name, upload_id=upload_id)

    threads = [threading.Thread(target=consume, args=(f"t{i}.md",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    outcomes = sorted((a["ok"], a.get("error")) for a in answers.values())
    assert outcomes == [(False, "upload_not_found"), (True, None)], answers
    assert len(store.code_snippets.docs) == 1 and racing.docs == []


def test_append_file_takes_the_text_from_an_upload(store, backend, call):
    assert call("codekeeper_save_file", file_name="log.md", code="head")["ok"] is True
    upload_id = _create(backend, "tail\n")
    res = call("codekeeper_append_file", file_name="log.md", upload_id=upload_id)
    assert res["ok"] is True and res["appended_chars"] == len("tail\n") and res["content_changed"] is False
    assert _stored_code(store, res["file"]["id"]) == "head\ntail\n"
    assert store.uploads.docs == []


def test_append_file_refuses_content_and_upload_id_together(store, backend, call):
    assert call("codekeeper_save_file", file_name="log.md", code="head\n")["ok"] is True
    upload_id = _create(backend, "tail\n")
    res = call("codekeeper_append_file", file_name="log.md", content="x", upload_id=upload_id)
    assert res["ok"] is False and res["error"] == "content_and_upload_id"
    none = call("codekeeper_append_file", file_name="log.md")
    assert none["error"] == "empty_content" and "upload_id" in none["hint"]
    assert len(store.uploads.docs) == 1 and len(store.code_snippets.docs) == 1


def test_an_append_over_the_ceiling_keeps_the_upload(store, backend, call, monkeypatch):
    """התקרה חלה על הקובץ **אחרי** ההוספה, ונבדקת לפני השער."""
    assert call("codekeeper_save_file", file_name="log.md", code="12345\n")["ok"] is True
    upload_id = _create(backend, "67890\n")
    _ceiling(monkeypatch, 10)
    res = call("codekeeper_append_file", file_name="log.md", upload_id=upload_id)
    assert res == {"ok": False, "error": "code_too_large", "max": 10}
    assert len(store.uploads.docs) == 1


def test_an_append_sent_again_adds_the_text_exactly_once(store, backend, call):
    """שני המקרים של "התשובה אבדה בדרך":

    1. הקריאה הצליחה והתשובה לא הגיעה — שליחה חוזרת נענית ``upload_not_found``.
    2. תקלת אחסון ענתה על הקריאה הראשונה — שליחה חוזרת מוסיפה את הטקסט פעם אחת.

    מוטציה: מחיקה אחרי השמירה — במקרה השני הטקסט נוסף פעמיים, והטסט נופל.
    """
    from pymongo.errors import AutoReconnect

    assert call("codekeeper_save_file", file_name="log.md", code="head\n")["ok"] is True
    upload_id = _create(backend, "once\n")
    assert call("codekeeper_append_file", file_name="log.md", upload_id=upload_id)["ok"] is True
    again = call("codekeeper_append_file", file_name="log.md", upload_id=upload_id)
    assert again["ok"] is False and again["error"] == "upload_not_found"

    upload_id = _create(backend, "twice?\n")
    real_delete = store.uploads.delete_one
    failures = iter([AutoReconnect("connection reset before the delete ran")])

    def delete_once_failing(*args, **kwargs):
        for error in failures:
            raise error
        return real_delete(*args, **kwargs)

    store.uploads.delete_one = delete_once_failing
    first = call("codekeeper_append_file", file_name="log.md", upload_id=upload_id)
    assert first["ok"] is False and first["error"] == "upload_storage_unavailable", first
    second = call("codekeeper_append_file", file_name="log.md", upload_id=upload_id)
    assert second["ok"] is True, second

    final = _stored_code(store, second["file"]["id"])
    assert final == "head\nonce\ntwice?\n"


def test_upload_save_and_read_agree_on_one_hash_and_one_push(store, backend, call):
    """מקצה לקצה: ``PUT`` → ``codekeeper_save_file(upload_id)`` → ``codekeeper_get_file``.

    שלושה hash-ים שווים — של ``hashlib`` על הבתים ששלחנו, בתשובת ההעלאה, ו-
    ``file.content_sha256`` בשמירה ובקריאה — מסמך אחד ב-``push_events``, ו-
    ``content_changed`` שקרי.
    """
    raw = "# handoff\n﻿שורה‏\r\nסוף \U0001F600\n".encode("utf-8")
    with TestClient(app_in_mode("pat", backend, tokens=TOKENS)) as client:
        uploaded = _put(client, raw, token=READ_A).json()

    saved = call("codekeeper_save_file", file_name="handoff.md", upload_id=uploaded["upload_id"])
    read = call("codekeeper_get_file", file_name="handoff.md")

    local = hashlib.sha256(raw).hexdigest()
    assert uploaded["content_sha256"] == local
    assert saved["file"]["content_sha256"] == local == read["file"]["content_sha256"]
    assert saved["content_changed"] is False
    assert read["file"]["code"].encode("utf-8") == raw
    assert len(store.raw["push_events"].docs) == 1


@pytest.mark.parametrize("tool, seed", [("codekeeper_save_file", None), ("codekeeper_append_file", "head")])
def test_what_the_upload_id_description_says_about_the_hash_is_what_the_tool_returns(store, backend, call, tool, seed):
    """המשפט על ה-hash בתיאור ``upload_id`` נבדק מול מה שהכלי מחזיר באמת — לכל כלי בנפרד.

    בשמירה הקובץ הוא ההעלאה, ולכן ``file.content_sha256`` שווה ל-``content_sha256`` של
    ההעלאה. בהוספה ``file.content_sha256`` הוא של הקובץ כולו אחרי ההוספה — כאן ה-hash של
    ``"head" + "\\n" + text``, מחושב בטסט — ומה שמראה שהטקסט נכנס בשלמותו הוא
    ``content_changed: false``. התיאור היה משותף לשני הכלים והבטיח את הראשון גם בהוספה:
    סוכן שבודק לפיו מסיק שההוספה נכשלה, מעלה שוב, ומוסיף את הטקסט פעמיים.

    מקרה השמירה הוא הבקרה ועובר גם על הקוד שלפני התיקון; מקרה ההוספה נפל עליו.
    """
    import mcp_server.server as srv

    listed = asyncio.run(srv.build_mcp(backend, public_url="https://mcp.example.com").list_tools())
    doc = {listed_tool.name: listed_tool for listed_tool in listed}[tool].inputSchema["properties"]["upload_id"][
        "description"
    ]

    if seed is not None:
        assert call("codekeeper_save_file", file_name="log.md", code=seed)["ok"] is True
    text = "tail ‏ \U0001F600\n"
    created = backend.create_upload(USER_A, text=text, size_bytes=len(text.encode("utf-8")))
    res = call(tool, file_name="log.md", upload_id=created["upload_id"])
    assert res["ok"] is True and res["content_changed"] is False, res

    whole = text if seed is None else seed + "\n" + text
    assert res["file"]["content_sha256"] == hashlib.sha256(whole.encode("utf-8")).hexdigest()
    promises_the_upload_hash = "which file.content_sha256 matches" in doc
    assert promises_the_upload_hash == (res["file"]["content_sha256"] == created["content_sha256"]), doc
    if seed is not None:
        assert "whole file" in doc and "content_changed: false" in doc, doc


#: איך העלאה שמורה יכולה לא להתאים ל-hash שחושב כשהגיעה. הראשונה היא הטקסט שהשתבש
#: באחסון הזמני — הרגל שאף hash אחר אינו רואה: ``content_changed`` משווה את מה
#: שנשלף למה שנכתב, ושניהם כבר משובשים. השאר הן ה-hash השמור עצמו, בכל צורה שאינה
#: 64 ספרות הקס של הטקסט.
_CORRUPTIONS = {
    "text_changed_in_storage": lambda doc: doc.update(text=doc["text"].replace("tail", "tall")),
    "hash_missing": lambda doc: doc.pop("content_sha256"),
    "hash_not_a_string": lambda doc: doc.update(content_sha256=12345),
    "hash_not_hex": lambda doc: doc.update(content_sha256="not-a-sha256"),
    "hash_of_other_text": lambda doc: doc.update(content_sha256=hashlib.sha256(b"other").hexdigest()),
}


#: קובץ זוגות תקין שמחליף את ``head`` ב-``tail``. ``text_changed_in_storage`` הופך בו את
#: ``tail`` ל-``tall``, כלומר קובץ זוגות תקין **אחר** — שבלי בדיקת השלמות היה מוחל ונשמר.
_EDITS_HEAD_TO_TAIL = '[{"old_string": "head", "new_string": "tail"}]'


@pytest.mark.parametrize("corruption", sorted(_CORRUPTIONS))
@pytest.mark.parametrize("tool, seed, uploaded", [
    ("codekeeper_save_file", None, "tail\n"),
    ("codekeeper_append_file", "head\n", "tail\n"),
    ("codekeeper_multi_edit_file", "head\n", _EDITS_HEAD_TO_TAIL),
])
def test_an_upload_that_does_not_match_its_hash_writes_nothing_and_is_gone(
    store, backend, call, tool, seed, uploaded, corruption
):
    """``upload_corrupted``: שום גרסה, שום התראה, וההעלאה עצמה נמחקת — בכל כלי שמקבל העלאה.

    לפני הבדיקה הטקסט המשובש נשמר בשקט: ``content_changed`` היה ``false``, כי מה
    שנכתב שווה למה שנשלף. ב-``codekeeper_multi_edit_file`` ההעלאה היא רשימת הזוגות,
    והשיבוש הופך אותה לרשימה תקינה אחרת — שהייתה מוחלת.
    """
    if seed is not None:
        assert call("codekeeper_save_file", file_name="log.md", code=seed)["ok"] is True
    versions = len(store.code_snippets.docs)
    pushes = len(store.raw["push_events"].docs)
    upload_id = _create(backend, uploaded)
    _CORRUPTIONS[corruption](store.uploads.docs[0])

    res = call(tool, file_name="log.md", **{_UPLOAD_ARG[tool]: upload_id})
    assert res["ok"] is False and res["error"] == "upload_corrupted", res
    assert "upload the file again" in res["hint"], res
    assert len(store.code_snippets.docs) == versions
    assert len(store.raw["push_events"].docs) == pushes
    assert store.uploads.docs == []


def _seed_log(call) -> None:
    assert call("codekeeper_save_file", file_name="log.md", code="head\n")["ok"] is True


def _no_setup(call, backend, monkeypatch) -> dict:
    return {}


def _tiny_ceiling(call, backend, monkeypatch) -> dict:
    _ceiling(monkeypatch, 3)
    return {}


def _existence_unanswered(call, backend, monkeypatch) -> dict:
    monkeypatch.setattr(backend, "file_exists", lambda *args, **kwargs: None)
    return {}


def _log_exists(call, backend, monkeypatch) -> dict:
    _seed_log(call)
    return {}


def _log_and_malformed_expected(call, backend, monkeypatch) -> dict:
    _seed_log(call)
    return {"expected_content_sha256": "not-a-hash"}


def _log_and_stale_expected(call, backend, monkeypatch) -> dict:
    _seed_log(call)
    return {"expected_content_sha256": hashlib.sha256(b"what the agent read before").hexdigest()}


def _log_and_tiny_ceiling(call, backend, monkeypatch) -> dict:
    _seed_log(call)
    _ceiling(monkeypatch, 6)
    return {}


#: כל שער שבא בגוף הכלי אחרי השליפה ומחליט לפי הטקסט: ``(הכלי, הסירוב של השער, הטקסט
#: כמו שהוא שמור, ההכנה שמפילה את השער)``. ההכנה מחזירה ארגומנטים נוספים לכלי.
_GATES_AFTER_THE_READ = [
    ("codekeeper_save_file", "empty_code", "", _no_setup),
    ("codekeeper_save_file", "code_too_large", "tall\n", _tiny_ceiling),
    ("codekeeper_save_file", "existence_check_unavailable", "tall\n", _existence_unanswered),
    ("codekeeper_save_file", "file_exists", "tall\n", _log_exists),
    ("codekeeper_append_file", "empty_content", "", _log_exists),
    ("codekeeper_append_file", "invalid_expected_content_sha256", "tall\n", _log_and_malformed_expected),
    ("codekeeper_append_file", "not_found", "tall\n", _no_setup),
    ("codekeeper_append_file", "conflict", "tall\n", _log_and_stale_expected),
    ("codekeeper_append_file", "code_too_large", "tall\n", _log_and_tiny_ceiling),
    # ב-``codekeeper_multi_edit_file`` הטקסט הוא קובץ הזוגות, והשערים שמחליטים לפיו הם
    # הפענוח שלו, מבנה הרשימה, ואחר כך הקובץ והזוגות עצמם.
    ("codekeeper_multi_edit_file", "invalid_edits_upload", "tall\n", _log_exists),
    ("codekeeper_multi_edit_file", "missing_edits", "[]", _log_exists),
    ("codekeeper_multi_edit_file", "invalid_edit", '[{"old_string": "head"}]', _log_exists),
    ("codekeeper_multi_edit_file", "invalid_expected_content_sha256", _EDITS_HEAD_TO_TAIL, _log_and_malformed_expected),
    ("codekeeper_multi_edit_file", "not_found", _EDITS_HEAD_TO_TAIL, _no_setup),
    ("codekeeper_multi_edit_file", "conflict", _EDITS_HEAD_TO_TAIL, _log_and_stale_expected),
    ("codekeeper_multi_edit_file", "no_match", '[{"old_string": "tall", "new_string": "x"}]', _log_exists),
    ("codekeeper_multi_edit_file", "code_too_large", '[{"old_string": "head", "new_string": "headhead"}]',
     _log_and_tiny_ceiling),
]


@pytest.mark.parametrize(
    "tool, gate, stored_text, prepare", _GATES_AFTER_THE_READ, ids=[f"{t}-{g}" for t, g, _, _ in _GATES_AFTER_THE_READ]
)
def test_a_corrupted_upload_is_refused_before_the_gates_that_read_its_text(
    store, backend, call, monkeypatch, tool, gate, stored_text, prepare
):
    """השלמות נבדקת עם השליפה, לפני כל שער שמחליט לפי הטקסט — ולא רק לפני המחיקה.

    **הבקרה** — אותו טקסט שמור, הפעם עם ה-hash שלו: השער עונה את הסירוב שלו, וההעלאה
    נשארת (השער בא לפני הצריכה). כך הטסט אינו יכול לעבור על הכנה שלא מגיעה לשער.

    **ההעלאה המשובשת** — אותו טקסט שמור, עם ה-hash של מה שהגיע: ``upload_corrupted``,
    ``discard_upload`` פעם אחת עם הכלי והסיבה (ומשם שורת ה-``ERROR``), ההעלאה הזו
    בלבד נעלמה, ושום דבר לא נכתב. כשהבדיקה ישבה רק לפני המחיקה, כל אחד מהמקרים ענה
    את הסירוב של השער — החלטה על טקסט שלא נשלח — וההעלאה נשארה חיה, בלי לוג, עד שפקעה.
    """
    extra = prepare(call, backend, monkeypatch)
    upload_arg = _UPLOAD_ARG[tool]
    intact = _create(backend, stored_text)
    control = call(tool, file_name="log.md", **{upload_arg: intact}, **extra)
    assert control.get("error") == gate, control
    versions = len(store.code_snippets.docs)
    pushes = len(store.raw["push_events"].docs)

    corrupted = _create(backend, "tail\n")
    (doc,) = [d for d in store.uploads.docs if d["upload_id"] == corrupted]
    doc["text"] = stored_text
    discarded: list[tuple[str, str]] = []
    discard = backend.discard_upload

    def recorded(user_id, upload_id, **kwargs):
        discarded.append((kwargs["tool"], kwargs["reason"]))
        return discard(user_id, upload_id, **kwargs)

    monkeypatch.setattr(backend, "discard_upload", recorded)
    res = call(tool, file_name="log.md", **{upload_arg: corrupted}, **extra)
    assert res["ok"] is False and res["error"] == "upload_corrupted", res
    assert discarded == [(tool, "hash_mismatch")], discarded
    assert [d["upload_id"] for d in store.uploads.docs] == [intact]
    assert len(store.code_snippets.docs) == versions
    assert len(store.raw["push_events"].docs) == pushes


def test_a_corrupted_upload_is_corrupted_even_when_its_deletion_finds_nothing(store, backend, call, monkeypatch):
    """הבדיקה באה **לפני** המחיקה, ולכן התשובה אינה תלויה בתוצאה שלה.

    כאן ההעלאה נעלמת בין השליפה למחיקה — צורך מקביל, או ה-TTL. מוטציה שמשווה אחרי
    המחיקה עונה ``upload_not_found``, "פגה או נצרכה", על העלאה שהאחסון שיבש.
    """
    upload_id = _create(backend, "tail\n")
    store.uploads.docs[0]["text"] = "tall\n"
    read = store.uploads.find_one

    def read_then_vanish(*args, **kwargs):
        found = read(*args, **kwargs)
        store.uploads.docs.clear()
        return found

    monkeypatch.setattr(store.uploads, "find_one", read_then_vanish)
    res = call("codekeeper_save_file", file_name="a.md", upload_id=upload_id)
    assert res["ok"] is False and res["error"] == "upload_corrupted", res
    assert store.code_snippets.docs == []


def test_two_consumers_of_one_corrupted_upload_both_refuse_and_nothing_is_saved(store, backend):
    """במקביל, בשני חוטים שעוברים יחד את השליפה (``_Racing``): שניהם ``upload_corrupted``.

    אחד מוחק ואחד מוצא שכבר נמחקה, והתשובה של שניהם זהה — כי הבדיקה באה עם השליפה,
    לפני המחיקה.
    על הקוד שלפני הבדיקה אחד שמר את הטקסט המשובש; במוטציה שמשווה אחרי המחיקה, השני
    עונה ``upload_not_found``.
    """
    racing = _Racing()
    store.raw.c["mcp_uploads"] = racing
    upload_id = _create(backend, "tail\n")
    racing.docs[0]["text"] = "tall\n"
    answers: dict[str, dict] = {}

    def consume(name: str) -> None:
        answers[name] = handlers.save_file(backend, USER_A, file_name=name, upload_id=upload_id)

    threads = [threading.Thread(target=consume, args=(f"t{i}.md",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert [answer.get("error") for answer in answers.values()] == ["upload_corrupted"] * 2, answers
    assert store.code_snippets.docs == [] and racing.docs == []


def test_a_corrupted_upload_is_corrupted_even_when_the_storage_does_not_answer_its_deletion(
    store, backend, call, monkeypatch
):
    """המחיקה של העלאה משובשת היא ניקיון ולא השער: כשל שלה נרשם, וההעלאה פוקעת ב-TTL.

    התשובה נשארת ``upload_corrupted`` — ``upload_storage_unavailable`` היה שולח את
    הסוכן לנסות שוב את אותו מזהה, על אותה העלאה משובשת.
    """
    from pymongo.errors import AutoReconnect

    upload_id = _create(backend, "tail\n")
    store.uploads.docs[0]["text"] = "tall\n"

    def unanswered(*args, **kwargs):
        raise AutoReconnect("simulated: no answer")

    monkeypatch.setattr(store.uploads, "delete_one", unanswered)
    res = call("codekeeper_save_file", file_name="a.md", upload_id=upload_id)
    assert res["ok"] is False and res["error"] == "upload_corrupted", res
    assert store.code_snippets.docs == [] and len(store.uploads.docs) == 1


@pytest.mark.parametrize("tool, param, seed, inline", [
    ("codekeeper_save_file", "code", None, "inline\n"),
    ("codekeeper_append_file", "content", "head\n", "inline\n"),
    ("codekeeper_multi_edit_file", "edits", "head\n", _ONE_EDIT),
])
def test_without_upload_id_the_upload_storage_is_not_touched(store, call, monkeypatch, tool, param, seed, inline):
    """בלי מזהה העלאה שום דבר לא משתנה: הבדיקה היא של העלאות, ותוכן inline אינו עובר בה.

    מקבע התנהגות שכבר הייתה נכונה, ולכן עובר גם על הקוד שלפני בדיקת השלמות — בכוונה.
    וכך גם השורה של ``codekeeper_multi_edit_file``: היא עוברת גם על הקוד שלפני
    ``edits_upload_id``, כי בלי הפרמטר הכלי הוא מה שהיה.
    """
    if seed is not None:
        assert call("codekeeper_save_file", file_name="log.md", code=seed)["ok"] is True
    touched: list[str] = []
    for method in ("find_one", "delete_one", "insert_one", "count_documents", "find"):
        original = getattr(store.uploads, method)
        monkeypatch.setattr(
            store.uploads, method,
            lambda *args, _method=method, _original=original, **kwargs: (
                touched.append(_method), _original(*args, **kwargs)
            )[1],
        )
    res = call(tool, file_name="log.md", **{param: inline})
    assert res["ok"] is True and res["content_changed"] is False, res
    assert touched == []
    assert not [key for key in res if key.startswith("upload")], res


# ---------------------------------------------------------------------------
# 4ב. ``edits_upload_id`` ב-``codekeeper_multi_edit_file`` — הזוגות כבתים מדויקים
#
# ``edits`` הוא רשימה, ולכן נשאר ב-``pre_parse_json`` של ה-SDK: רשימה שלקוח שולח
# כמחרוזת JSON חייבת להמשיך להתפענח. המחיר: מחרוזת **בתוך** זוג עוברת פענוח JSON
# אחד כשהרשימה הגיעה כמערך, ושניים כשהגיעה כמחרוזת — והשרת אינו יכול לדעת באיזו
# צורה הלקוח שלח, ולמה המודל התכוון. קובץ שעולה כבתים אינו עובר באף אחת מהשכבות
# האלה, ונשאר פענוח אחד, של השרת.
# ---------------------------------------------------------------------------

MULTI_EDIT = "codekeeper_multi_edit_file"

#: לוכסן אחד. נבנה כך, ולא נכתב כ-escape בתוך המחרוזות שלמטה, כדי שמספר הלוכסנים
#: בכל צורה ייספר בעין: ``_BS * 2`` הם שני לוכסנים בטקסט, לא אחד.
_BS = "\\"
#: מה שסוכן רוצה לכתוב לקובץ כשהוא מתעד escape: לוכסן, ``u`` וארבע ספרות — שישה תווים.
_ESCAPE_AS_TEXT = _BS + "u200F"
#: והתו שששת התווים האלה מקודדים, כשקוראים אותם כ-escape של JSON.
_RLM = "‏"
#: ערך שמסמן תוכן שנשלח, כדי לבדוק שאף סירוב אינו מהדהד אותו.
_SECRET = "SECRET-VALUE-7f3a"

#: מערך הזוגות כטקסט JSON — פעם עם ה-escape הנכון לששת התווים (שני לוכסנים), ופעם
#: עם לוכסן יחיד, שב-JSON הוא ה-escape של התו עצמו.
_PAIRS_TEXT = '[{"old_string": "X", "new_string": "' + _BS * 2 + 'u200F"}]'
_PAIRS_CHAR = '[{"old_string": "X", "new_string": "' + _BS + 'u200F"}]'


def _as_json_string(text: str) -> str:
    """``text`` כערך מחרוזת של JSON, כתוב ביד: לוכסן נהיה שניים, וגרשיים מקבלים לוכסן."""
    return '"' + text.replace(_BS, _BS * 2).replace('"', _BS + '"') + '"'


#: ``arguments`` של ``tools/call`` **כמו שהם על החוט**, בשלוש הצורות שבהן ``edits`` עם
#: אותו ``new_string`` יכול לצאת מלקוח. כתוב ביד ולא ב-``json.dumps``, שתמיד מכפיל
#: לוכסנים ולכן אינו יכול לייצר את הצורה השלישית.
_EDITS_ON_THE_WIRE = {
    # מערך. שני הלוכסנים הם ה-escape של JSON ללוכסן אחד, והתעבורה מפענחת אותם.
    "array": '{"file_name": "log.md", "edits": ' + _PAIRS_TEXT + "}",
    # מחרוזת שמכילה את אותו מערך, עם escape לכל אחת משתי הרמות (ארבעה לוכסנים):
    # התעבורה מפענחת רמה אחת, ו-``pre_parse_json`` את השנייה.
    "json_text_escaped_for_both_levels": '{"file_name": "log.md", "edits": ' + _as_json_string(_PAIRS_TEXT) + "}",
    # מחרוזת עם escape לרמה אחת בלבד (שני לוכסנים): שני הפענוחים אוכלים את שניהם.
    "json_text_escaped_for_one_level": '{"file_name": "log.md", "edits": ' + _as_json_string(_PAIRS_CHAR) + "}",
}
#: מה שהגיע ל-``_apply_edit`` כ-``new_string`` בכל צורה — נמדד על ``mcp 1.28.1``.
_REACHES_THE_TOOL = {
    "array": _ESCAPE_AS_TEXT,
    "json_text_escaped_for_both_levels": _ESCAPE_AS_TEXT,
    "json_text_escaped_for_one_level": _RLM,
}


def _tool_call_with_raw_arguments(client, token: str, name: str, arguments_json: str) -> dict:
    """``tools/call`` דרך ``POST /mcp``, כש-``arguments`` הוא טקסט JSON שנשלח כמו שהוא.

    ``tool_call_over_http`` בונה את הגוף ב-``json=``, כלומר מקודד את הארגומנטים מחדש;
    כאן הגוף הוא הבתים שהטסט כתב, כדי שפענוח התעבורה יהיה חלק ממה שנמדד.
    """
    body = (
        '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "' + name
        + '", "arguments": ' + arguments_json + "}}"
    )
    response = client.post(
        "/mcp",
        content=body.encode("utf-8"),
        headers={"authorization": f"Bearer {token}", "content-type": "application/json",
                 "accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 200, response.text
    data = next(line[len("data: "):] for line in response.text.splitlines() if line.startswith("data: "))
    return json.loads(json.loads(data)["result"]["content"][0]["text"])


@pytest.fixture
def reached_apply_edit(monkeypatch) -> list[str]:
    """ה-``new_string`` של כל קריאה ל-``_apply_edit`` — מה שהגיע לגוף הכלי אחרי כל השכבות."""
    reached: list[str] = []
    real = handlers._apply_edit

    def recording(code, old_string, new_string, replace_all, *, max_size):
        reached.append(new_string)
        return real(code, old_string, new_string, replace_all, max_size=max_size)

    monkeypatch.setattr(handlers, "_apply_edit", recording)
    return reached


@pytest.mark.parametrize("form", sorted(_EDITS_ON_THE_WIRE))
def test_the_server_is_deterministic_for_each_form_edits_can_arrive_in(store, backend, reached_apply_edit, form):
    """שלוש צורות של אותו ``edits``, על החוט: מה מגיע ל-``_apply_edit`` בכל אחת.

    מערך ← ששת התווים. מחרוזת JSON עם escape לשתי הרמות ← ששת התווים. מחרוזת JSON
    עם escape לרמה אחת ← התו U+200F עצמו. **השרת דטרמיניסטי לכל צורה** — וזו בדיוק
    הבעיה: איזו צורה הלקוח שלח, ולמה המודל התכוון, הטסט הזה אינו רואה ואינו יכול
    לראות. לכן אין כאן שום ניחוש לתקן, ו-``edits_upload_id`` הוא הדרך שאינה תלויה בזה.

    ``content_changed`` הוא ``false`` בשלושתן, גם בזו שכתבה תו בלתי-נראה במקום הטקסט:
    הוא משווה את מה שהכלי **קיבל** למה שנשמר.

    מקבע התנהגות קיימת, ולכן עובר גם על הקוד שלפני ``edits_upload_id`` — בכוונה. הוא
    הבסיס למשפט "Send edits as a JSON array" בתיאור ``edits``: מערך מפוענח פעם אחת.
    """
    with TestClient(app_in_mode("pat", backend, tokens=TOKENS)) as client:
        seeded = _tool_call_with_raw_arguments(
            client, WRITE_A, "codekeeper_save_file", '{"file_name": "log.md", "code": "a X b"}')
        assert seeded["ok"] is True, seeded
        res = _tool_call_with_raw_arguments(client, WRITE_A, MULTI_EDIT, _EDITS_ON_THE_WIRE[form])

    assert res["ok"] is True, res
    assert reached_apply_edit == [_REACHES_THE_TOOL[form]]
    expected = "a " + _REACHES_THE_TOOL[form] + " b"
    assert _stored_code(store, res["file"]["id"]) == expected
    assert res["file"]["content_sha256"] == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert res["content_changed"] is False


def test_pairs_uploaded_as_a_file_are_decoded_exactly_once(store, backend, call, reached_apply_edit, tmp_path):
    """מקצה לקצה: קובץ ← ``PUT /api/agent/upload`` ← ``edits_upload_id`` — פענוח JSON אחד, של השרת.

    בקובץ שני זוגות, ובהם שתי הצורות. שני לוכסנים לפני ``u200F`` הם ששת התווים — וזה
    מה שסוכן שמתעד escape רוצה. לוכסן יחיד הוא ה-escape של JSON, כלומר התו עצמו: הפענוח
    היחיד אינו מייתר את ה-escape, ותיאור הפרמטר אומר זאת.

    ``content_sha256`` מחושב כאן על התוצאה הצפויה, ולא נלקח מהכלי. וה-hash שבתשובת
    ההעלאה הוא של קובץ הזוגות ולא של הקובץ הערוך — מה שתיאור הפרמטר אומר.

    **המוטציה שחייבת להפיל אותו — פענוח נוסף של ה-escapes** (``unicode_escape`` על הטקסט
    לפני ``json.loads``): הזוג הראשון נשמר אז כתו, לא כטקסט.
    """
    import mcp_server.server as srv

    pairs = tmp_path / "edits.json"
    pairs.write_bytes(
        ('[{"old_string": "X", "new_string": "' + _BS * 2 + 'u200F"},\n'
         ' {"old_string": "Y", "new_string": "' + _BS + 'u200F"}]\n').encode("utf-8")
    )
    raw = pairs.read_bytes()
    assert call("codekeeper_save_file", file_name="log.md", code="a X b Y c")["ok"] is True
    with TestClient(app_in_mode("pat", backend, tokens=TOKENS)) as client:
        uploaded = _put(client, raw, token=READ_A).json()

    res = call(MULTI_EDIT, file_name="log.md", edits_upload_id=uploaded["upload_id"])

    expected = "a " + _ESCAPE_AS_TEXT + " b " + _RLM + " c"
    assert res["ok"] is True and res["edits_applied"] == 2 and res["replacements"] == 2, res
    assert reached_apply_edit == [_ESCAPE_AS_TEXT, _RLM]
    assert _stored_code(store, res["file"]["id"]) == expected
    assert res["file"]["content_sha256"] == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert res["content_changed"] is False
    assert store.uploads.docs == []
    assert not [key for key in res if key.startswith("upload")], res

    # חד-פעמי: שליחה חוזרת של אותו מזהה אינה מוצאת העלאה, ואינה כותבת.
    versions = len(store.code_snippets.docs)
    again = call(MULTI_EDIT, file_name="log.md", edits_upload_id=uploaded["upload_id"])
    assert again["ok"] is False and again["error"] == "upload_not_found", again
    assert len(store.code_snippets.docs) == versions

    # ה-hash של ההעלאה הוא של קובץ הזוגות — ולכן התיאור אינו מבטיח שהוא יהיה של הקובץ.
    assert uploaded["content_sha256"] == hashlib.sha256(raw).hexdigest() != res["file"]["content_sha256"]
    listed = asyncio.run(srv.build_mcp(backend, public_url="https://mcp.example.com").list_tools())
    doc = {tool.name: tool for tool in listed}[MULTI_EDIT].inputSchema["properties"]["edits_upload_id"]["description"]
    assert "its content_sha256 is the hash of this JSON file, not of the edited file" in doc, doc
    assert "which file.content_sha256 matches" not in doc


def test_a_pairs_file_that_opens_with_a_bom_is_not_json(store, backend, call):
    """הראוט שומר BOM כתו (``utf-8``, לא ``utf-8-sig``), ו-JSON אינו נפתח ב-BOM.

    עורך שמוסיף BOM הוא הדרך השכיחה להגיע לכאן, ולכן המקרה עובר דרך הראוט ולא דרך
    ``create_upload``: מה שנבדק הוא מה שקורה לבתים האלה מקצה לקצה.
    """
    assert call("codekeeper_save_file", file_name="log.md", code="head\n")["ok"] is True
    with TestClient(app_in_mode("pat", backend, tokens=TOKENS)) as client:
        uploaded = _put(client, b"\xef\xbb\xbf" + _EDITS_HEAD_TO_TAIL.encode("utf-8"), token=READ_A).json()

    res = call(MULTI_EDIT, file_name="log.md", edits_upload_id=uploaded["upload_id"])

    assert res["ok"] is False and res["error"] == "invalid_edits_upload", res
    assert (res["line"], res["column"], res["position"]) == (1, 1, 0)
    assert "byte-order mark" in res["hint"]
    assert len(store.code_snippets.docs) == 1 and len(store.uploads.docs) == 1


def _stopped_at(text: str, token: str) -> dict[str, int]:
    """המיקום של ``token`` ב-``text``, בשדות של הסירוב: שורה ועמודה מ-1, והיסט מ-0."""
    at = text.index(token)
    return {"line": text.count("\n", 0, at) + 1, "column": at - text.rfind("\n", 0, at), "position": at}


_BROKEN_ON_LINE_3 = '[\n  {"old_string": "' + _SECRET + '",\n   "new_string": "b" "c"}\n]'
_NOT_AN_ESCAPE = '[{"old_string": "' + _SECRET + '", "new_string": "' + _BS + 'd+"}]'

#: העלאות שאינן מערך JSON: ``(הטקסט, המיקום שהסירוב נושא — או None כשאין מיקום)``.
_NOT_AN_ARRAY_OF_PAIRS = {
    "not_json": (f"{_SECRET} [", {"line": 1, "column": 1, "position": 0}),
    "json_broken_on_line_3": (_BROKEN_ON_LINE_3, _stopped_at(_BROKEN_ON_LINE_3, '"c"')),
    # לוכסן יחיד לפני תו שאינו escape של JSON — מה שיוצא כשכותבים regex בלי להכפיל.
    "a_backslash_that_is_not_an_escape": (_NOT_AN_ESCAPE, _stopped_at(_NOT_AN_ESCAPE, _BS)),
    "json_object": ('{"edits": ' + _EDITS_HEAD_TO_TAIL + "}", None),
    # מערך תקין שנעטף כמחרוזת JSON — הצורה שבה לקוח שולח רשימה ב-``edits``. כאן היא
    # **אינה** מתפענחת שוב: פענוח שני הוא בדיוק מה שהפרמטר בא למנוע.
    "json_string_that_holds_the_array": (json.dumps(_EDITS_HEAD_TO_TAIL), None),
    "json_null": ("null", None),
    "json_number": ("5", None),
    "nested_too_deep": ("[" * 50_000, None),
    "a_number_too_long_to_convert": ("[" + "1" * 5_000 + "]", None),
}


@pytest.mark.parametrize("case", sorted(_NOT_AN_ARRAY_OF_PAIRS))
def test_an_upload_that_is_not_a_json_array_is_refused_with_numbers_only(store, backend, call, case):
    """``invalid_edits_upload``: מיקום במספרים בלבד, שום דבר מהקובץ, ושום דבר לא נכתב.

    שלוש הדרכים שבהן ``json.loads`` אומר "זה אינו JSON" — ``JSONDecodeError`` (עם מיקום),
    ``ValueError`` על מספר ארוך מתקרת ההמרה, ו-``RecursionError`` על קינון עמוק — ומה
    שמפוענח ואינו רשימה. ההעלאה נשארת: הסירוב בא לפני השער.

    **המוטציה שחייבת להפיל את ``json_string_that_holds_the_array`` — פענוח JSON שני**
    (``json.loads`` נוסף כשהפענוח הראשון החזיר מחרוזת): הזוג מוחל, והקובץ משתנה.
    """
    text, position = _NOT_AN_ARRAY_OF_PAIRS[case]
    assert call("codekeeper_save_file", file_name="log.md", code="head\n")["ok"] is True
    upload_id = _create(backend, text)

    res = call(MULTI_EDIT, file_name="log.md", edits_upload_id=upload_id)

    assert res["ok"] is False and res["error"] == "invalid_edits_upload", res
    assert {key: value for key, value in res.items() if key not in ("ok", "error", "hint")} == (position or {})
    assert _SECRET not in json.dumps(res)
    assert "edits_upload_id" in res["hint"] and "upload it again" in res["hint"], res
    assert len(store.code_snippets.docs) == 1 and len(store.uploads.docs) == 1


def test_a_list_from_an_upload_gets_the_refusals_of_edits_and_how_to_send_it_again(store, backend, call):
    """מערך ריק, מעל התקרה, וזוג פגום — הקודים של ``edits``, מאותו קוד, ועם מה שעושים בהעלאה.

    ב-``edits`` הסירובים האלה אינם נושאים ``hint``: הסוכן שולח שוב את הארגומנט, מתוקן.
    העלאה אי אפשר לתקן — רק להעלות חדשה — ולכן כאן הסירוב אומר זאת.
    """
    assert call("codekeeper_save_file", file_name="log.md", code="head\n")["ok"] is True
    pair = {"old_string": "head", "new_string": "HEAD"}
    over = handlers.MAX_EDIT_PAIRS + 1

    empty = call(MULTI_EDIT, file_name="log.md", edits_upload_id=_create(backend, "[]"))
    too_many = call(MULTI_EDIT, file_name="log.md", edits_upload_id=_create(backend, json.dumps([pair] * over)))
    malformed = call(MULTI_EDIT, file_name="log.md", edits_upload_id=_create(backend, json.dumps(
        [pair, {"old_string": _SECRET, "new_string": "x", "colour": _SECRET}])))

    assert empty["error"] == "missing_edits"
    assert (too_many["error"], too_many["count"], too_many["max"]) == ("too_many_edits", over, handlers.MAX_EDIT_PAIRS)
    assert (malformed["error"], malformed["index"]) == ("invalid_edit", 1)
    assert [problem["loc"] for problem in malformed["problems"]] == [[1, "colour"]]
    for res in (empty, too_many, malformed):
        assert res["ok"] is False
        assert "upload it again" in res["hint"] and "edits_upload_id" in res["hint"], res
        # שם המפתח הזר יוצא ב-``loc``, כמו ב-``edits``; הערכים — לעולם לא.
        assert _SECRET not in json.dumps({key: value for key, value in res.items() if key != "problems"})
        assert all(_SECRET not in str(problem["msg"]) for problem in res.get("problems", []))
    assert len(store.code_snippets.docs) == 1 and len(store.uploads.docs) == 3


def test_a_refusal_before_the_gate_leaves_the_upload_for_the_next_call(store, backend, call):
    """``not_found``, ``conflict`` ו-hash פגום באים לפני השער: אותו מזהה עובד בקריאה הבאה.

    זה מה שהשער-אחרי-הבדיקות נותן: סוכן שטעה בשם הקובץ או שקרא גרסה ישנה אינו צריך
    להעלות את הזוגות שוב.
    """
    assert call("codekeeper_save_file", file_name="log.md", code="head\n")["ok"] is True
    upload_id = _create(backend, _EDITS_HEAD_TO_TAIL)
    stale = hashlib.sha256(b"what the agent read before").hexdigest()
    current = hashlib.sha256(b"head\n").hexdigest()

    wrong_name = call(MULTI_EDIT, file_name="nope.md", edits_upload_id=upload_id)
    changed = call(MULTI_EDIT, file_name="log.md", edits_upload_id=upload_id, expected_content_sha256=stale)
    not_a_hash = call(MULTI_EDIT, file_name="log.md", edits_upload_id=upload_id, expected_content_sha256="x")

    assert [res.get("error") for res in (wrong_name, changed, not_a_hash)] == [
        "not_found", "conflict", "invalid_expected_content_sha256"]
    assert len(store.code_snippets.docs) == 1 and len(store.uploads.docs) == 1

    res = call(MULTI_EDIT, file_name="log.md", edits_upload_id=upload_id, expected_content_sha256=current)
    assert res["ok"] is True and res["content_changed"] is False, res
    assert _stored_code(store, res["file"]["id"]) == "tail\n"
    assert store.uploads.docs == []


def test_a_pair_that_does_not_apply_says_to_upload_the_file_again(store, backend, call):
    """סירוב על זוג מהעלאה: אותם קוד, ``index`` ומונים — ו-hint שאומר מה עושים בהעלאה.

    הבקרה היא אותו באץ' ב-``edits``: שם ה-hint אומר לשלוח שוב את הבאץ', ואינו מזכיר העלאה.
    """
    assert call("codekeeper_save_file", file_name="log.md", code="head\n")["ok"] is True
    batch = [{"old_string": "head", "new_string": "HEAD"}, {"old_string": "nope", "new_string": "x"}]

    uploaded = call(MULTI_EDIT, file_name="log.md", edits_upload_id=_create(backend, json.dumps(batch)))
    inline = call(MULTI_EDIT, file_name="log.md", edits=batch)

    for res in (uploaded, inline):
        assert (res["error"], res["index"]) == ("no_match", 1), res
        assert (res["occurrences"], res["occurrences_in_stored_version"]) == (0, 0)
        assert res["hint"].startswith("nothing was written: the batch is all or nothing. ")
    assert "An upload cannot be changed: fix the file, upload it again and pass the new id in edits_upload_id" in uploaded["hint"]
    assert "send the whole batch again" not in uploaded["hint"]
    assert "Fix this pair and send the whole batch again" in inline["hint"] and "upload" not in inline["hint"]
    assert len(store.code_snippets.docs) == 1 and len(store.uploads.docs) == 1


def test_a_save_that_fails_after_the_gate_burns_the_edits_upload_and_says_so(store, backend, call, monkeypatch):
    """המחיר של "המחיקה היא השער" — אותו מחיר של ``codekeeper_save_file``, ואותה תשובה."""
    assert call("codekeeper_save_file", file_name="log.md", code="head\n")["ok"] is True
    upload_id = _create(backend, _EDITS_HEAD_TO_TAIL)
    monkeypatch.setattr(store.dbm, "save_code_snippet_returning_id", lambda snippet: None)

    res = call(MULTI_EDIT, file_name="log.md", edits_upload_id=upload_id)

    assert res["ok"] is False and res["error"] == "save_failed", res
    assert res["upload_consumed"] is True and "upload the file again" in res["hint"]
    assert store.uploads.docs == [] and len(store.code_snippets.docs) == 1


def test_an_edits_upload_of_someone_else_or_past_its_time_is_not_found(store, backend, call):
    """של משתמש אחר, או שפקעה — ``upload_not_found``, אותה תשובה, ושום דבר לא נכתב."""
    assert call("codekeeper_save_file", user=USER_B, file_name="log.md", code="head\n")["ok"] is True
    theirs = _create(backend, _EDITS_HEAD_TO_TAIL, user=USER_A)

    res = call(MULTI_EDIT, user=USER_B, file_name="log.md", edits_upload_id=theirs)
    assert res["ok"] is False and res["error"] == "upload_not_found", res
    assert len(store.uploads.docs) == 1

    mine = _create(backend, _EDITS_HEAD_TO_TAIL, user=USER_B)
    (doc,) = [d for d in store.uploads.docs if d["upload_id"] == mine]
    doc["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    res = call(MULTI_EDIT, user=USER_B, file_name="log.md", edits_upload_id=mine)
    assert res["ok"] is False and res["error"] == "upload_not_found", res
    assert len(store.code_snippets.docs) == 1


def test_upload_storage_that_does_not_answer_keeps_the_upload_and_offers_edit_file(store, backend, call):
    """האחסון לא ענה — בשליפה, ואחר כך בשער: ``upload_storage_unavailable``, ושום דבר לא נכתב.

    ה-hint מציע את ``codekeeper_edit_file`` ולא "send the content inline". ואחרי כשל של
    המחיקה בשער ההעלאה עדיין שם, והקריאה הבאה מחילה את הזוגות פעם אחת.
    """
    from pymongo.errors import AutoReconnect

    assert call("codekeeper_save_file", file_name="log.md", code="head\n")["ok"] is True
    upload_id = _create(backend, _EDITS_HEAD_TO_TAIL)
    real_find, real_delete = store.uploads.find_one, store.uploads.delete_one

    def unanswered(*args, **kwargs):
        raise AutoReconnect("simulated: no answer")

    store.uploads.find_one = unanswered
    at_the_read = call(MULTI_EDIT, file_name="log.md", edits_upload_id=upload_id)
    store.uploads.find_one = real_find
    store.uploads.delete_one = unanswered
    at_the_gate = call(MULTI_EDIT, file_name="log.md", edits_upload_id=upload_id)
    store.uploads.delete_one = real_delete

    for res in (at_the_read, at_the_gate):
        assert res["ok"] is False and res["error"] == "upload_storage_unavailable", res
        assert "codekeeper_edit_file" in res["hint"] and "inline" not in res["hint"]
    assert len(store.code_snippets.docs) == 1 and len(store.uploads.docs) == 1

    res = call(MULTI_EDIT, file_name="log.md", edits_upload_id=upload_id)
    assert res["ok"] is True and _stored_code(store, res["file"]["id"]) == "tail\n"
    assert store.uploads.docs == []


def test_two_consumers_of_one_edits_upload_apply_it_exactly_once(store, backend, call):
    """שני חוטים עוברים יחד את השליפה (``_Racing``), ורק אחד עובר את השער.

    ישירות דרך ה-handler, כמו ``test_two_consumers_of_one_upload_save_exactly_once``:
    תור הכתיבה מסדר ``call_tool`` בטור ומסתיר את המרוץ. הזוג הוא ``replace_all`` שמתאים
    גם אחרי שהוחל פעם אחת, ולכן המפסיד מגיע תמיד לשער ולא נעצר לפניו ב-``no_match`` —
    בלי זה התוצאה הייתה תלויה בסדר החוטים.
    """
    assert call("codekeeper_save_file", file_name="log.md", code="a\n")["ok"] is True
    racing = _Racing()
    store.raw.c["mcp_uploads"] = racing
    upload_id = _create(backend, '[{"old_string": "a", "new_string": "ab", "replace_all": true}]')
    answers: dict[int, dict] = {}

    def consume(index: int) -> None:
        answers[index] = handlers.multi_edit_file(
            backend, USER_A, file_name="log.md", edits=[], edits_upload_id=upload_id)

    threads = [threading.Thread(target=consume, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    outcomes = sorted((answer["ok"], answer.get("error")) for answer in answers.values())
    assert outcomes == [(False, "upload_not_found"), (True, None)], answers
    assert len(store.code_snippets.docs) == 2 and racing.docs == []


def test_the_edits_upload_id_description_is_built_from_the_parts_of_upload_id():
    """מה שהלקוח מקבל ב-``tools/list`` על ``edits_upload_id``, ועל שני המשפטים שמפנים אליו.

    הפקודה, התוקף ומי שאינו יכול להעלות הם אותם חלקים של ``upload_id`` — רק שם הקובץ
    שבפקודה שונה — ולא נוסח שהוקלד מחדש. מה ששונה הוא מה שעולה ומה עושים בלי העלאה:
    הנסיגה היא ``codekeeper_edit_file``, ולא "use the edits parameter as usual".
    """
    import mcp_server.server as srv

    tools = srv.build_mcp(_backend()[0], public_url="https://mcp.example.com")._tool_manager
    multi_edit = tools.get_tool(MULTI_EDIT)
    props = multi_edit.parameters["properties"]
    doc = props["edits_upload_id"]["description"]

    # הכלל במשפט הראשון, וכולו בתוך 120 תווים.
    rule = doc.split(". ", 1)[0]
    assert len(rule) <= 120, rule
    assert rule == "Instead of edits, for edits with backslashes meant as text (a literal " + _BS + "u200F or " + _BS + "n): single-use"

    # מה ש-JSON צריך, בשתי הצורות: שני לוכסנים הם הטקסט, אחד הוא התו.
    assert "decoded exactly once" in doc
    assert "written " + _BS * 2 + ": there " + _BS * 2 + "u200F is the six characters of text, and " + _BS + (
        "u200F is the character U+200F itself") in doc

    # אותם חלקים של ``upload_id``.
    shared = ('curl -sS -T {} -H "Authorization: Bearer $CODEKEEPER_PAT" https://mcp.example.com/api/agent/upload'
              f" — the reply carries upload_id, valid for {mcp_uploads.UPLOAD_TTL_SECONDS // 60} minutes")
    assert shared.format("edits.json") in doc
    for tool in ("codekeeper_save_file", "codekeeper_append_file"):
        assert shared.format("report.md") in tools.get_tool(tool).parameters["properties"]["upload_id"]["description"]
    assert doc.endswith(
        "Without bash, network access or CODEKEEPER_PAT (Claude.ai, for one), make such edits with "
        "codekeeper_edit_file, one edit per call."
    ), doc
    assert "as usual" not in doc
    for word in ("Refusals", "upload_not_found", "upload_corrupted", "invalid_edits_upload", "edits_and_edits_upload_id"):
        assert word not in doc, word

    # ``edits`` נהיה רשות — עם רשימה ריקה ולא עם ``null`` — והמשפט הראשון שלו נשאר.
    assert multi_edit.parameters["required"] == ["file_name"]
    assert props["edits"]["type"] == "array" and "anyOf" not in props["edits"]
    first, second = props["edits"]["description"].split(". ")[:2]
    assert first == "Edits applied in order, each to the result of the one before, all or nothing, saved as one version"
    assert second == ("Send edits as a JSON array, not as a string that holds JSON: strings inside a list that "
                      "arrived as a string are decoded twice")

    # ושני המשפטים בתיאורי הכלים: ההכרעה בין שלוש הדרכים, ומה מיוחד ב-``codekeeper_edit_file``.
    assert ("Prefer this tool for several edits in one version; for text with backslashes meant as text (a literal "
            + _BS + "u200F or " + _BS + "n), prefer codekeeper_edit_file, whose strings arrive as sent, or "
            "edits_upload_id.") in multi_edit.description
    assert ("old_string and new_string reach this tool as they were sent, so for text with backslashes meant as "
            "text, this is the tool.") in tools.get_tool("codekeeper_edit_file").description


def _owners(tree: ast.AST) -> dict[int, str]:
    """לכל צומת — הנתיב של ההגדרות שעוטפות אותו (``Class.method``, ``outer.inner``)."""
    owners: dict[int, str] = {}

    def walk(node: ast.AST, path: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            inner = path
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = path + (child.name,)
            owners[id(child)] = ".".join(inner)
            walk(child, inner)

    walk(tree, ())
    return owners


#: מי רשאי לקרוא לשיטות ההעלאה של ה-backend. שליפה רק דרך ``_load_upload``, שבודק את
#: השלמות מיד אחרי השליפה ומשליך שם העלאה משובשת; וצריכה רק דרך ``_consume_upload``,
#: השער.
_UPLOAD_METHOD_CALLERS = {
    "find_upload": "_load_upload",
    "discard_upload": "_load_upload",
    "consume_upload": "_consume_upload",
}

#: פעולות שכותבות או מוחקות באוסף. מחיקה מותרת רק במקום אחד; עדכון — בשום מקום,
#: כי טקסט שנשמר עם ה-hash שלו ואז השתנה הוא בדיוק מה שבדיקת השלמות דוחה.
_COLLECTION_WRITES = {
    "delete_one", "delete_many", "find_one_and_delete", "find_one_and_update",
    "find_one_and_replace", "update_one", "update_many", "replace_one", "bulk_write",
}


def test_every_upload_is_checked_as_it_is_read_and_consumed_at_one_gate():
    """שומר מבני: כל כלי שמקבל ``upload_id`` שולף דרך ``_load_upload`` וצורך דרך ``_consume_upload``.

    **מה זה שומר.** בדיקת השלמות חיה ב-``_load_upload``, מיד אחרי השליפה ולפני כל
    שער, והצריכה ב-``_consume_upload``. כלי שלישי שיקבל ``upload_id`` ויקרא ל-
    ``backend.find_upload`` או ל-``backend.consume_upload`` ישירות — או שיבנה
    ``_PendingUpload`` בעצמו, או שיטת backend שתמחק העלאה בעצמה — יחליט וישמור לפי
    טקסט שלא נבדק, וכל הטסטים ההתנהגותיים ימשיכו לעבור, כי הם מכסים את שני הכלים של
    היום ולא את זה שייכתב. לכן הבדיקה על המקור, באותו נימוק של השומר על תקרת הסורקים
    ב-``tests/test_mcp_outline.py``, ודרך ``ast`` ולא רג'קס: שם שמופיע ב-docstring
    אינו קריאה.

    רשימת הכלים נגזרת מהרישום האמיתי (``list_tools``), ולא מרשימה בטסט: כלי חדש
    עם פרמטר העלאה נכנס לבדיקה בלי שמישהו יזכור להוסיף אותו.

    **"פרמטר העלאה" הוא כל פרמטר ששמו מסתיים ב-``upload_id``**, ולא רק ``upload_id``
    בדיוק. עד ``edits_upload_id`` הגזירה חיפשה את השם המדויק, וכך גם את הארגומנט שעובר
    ל-handler — ו-``codekeeper_multi_edit_file``, שקורא לפרמטר שלו אחרת כי ההעלאה שם
    היא רשימת הזוגות ולא התוכן, היה יוצא מהחצי הזה של השומר בשקט. מוטציה שמראה שההרחבה
    מסוגלת ליפול: להפסיק להעביר את ``edits_upload_id`` ל-handler.

    נמדד על הקוד של היום: אפס מסלולים עוקפים.
    """
    import mcp_server.server as srv

    package = REPO / "mcp_server"
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in sorted(package.rglob("*.py"))}
    offenders: list[str] = []

    for path, tree in trees.items():
        owners = _owners(tree)
        name = path.relative_to(REPO).as_posix()
        for node in ast.walk(tree):
            where = f"{name}:{getattr(node, 'lineno', 0)}"
            owner = owners.get(id(node), "")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                method = node.func.attr
                # ``backend.consume_upload(...)`` מחוץ לעוזר — צריכה בלי הבדיקה.
                allowed = _UPLOAD_METHOD_CALLERS.get(method)
                if allowed is not None and not (
                    name == "mcp_server/handlers.py" and owner.split(".")[-1] == allowed
                ):
                    offenders.append(f"{where} {method} מתוך {owner or '<module>'}")
                # ``self._uploads_coll().delete_one(...)`` מחוץ למחיקה היחידה.
                receiver = node.func.value
                if (
                    method in _COLLECTION_WRITES
                    and isinstance(receiver, ast.Call)
                    and isinstance(receiver.func, ast.Attribute)
                    and receiver.func.attr == "_uploads_coll"
                    and not (method == "delete_one" and owner == "ProductionBackend._delete_live_upload")
                ):
                    offenders.append(f"{where} {method} על אוסף ההעלאות מתוך {owner}")
            # ``_PendingUpload(...)`` מחוץ ל-``_load_upload`` — העלאה שלא עברה את בדיקת
            # השלמות, ושכל שער אחריה יקבל כאילו עברה.
            if (
                isinstance(node, ast.Call)
                and (
                    (isinstance(node.func, ast.Name) and node.func.id == "_PendingUpload")
                    or (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr == "_make"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "_PendingUpload"
                    )
                )
                and not (name == "mcp_server/handlers.py" and owner.split(".")[-1] == "_load_upload")
            ):
                offenders.append(f"{where} _PendingUpload נבנית מתוך {owner or '<module>'}")
            # ``db[MCP_UPLOADS_COLLECTION]`` מחוץ ל-``_uploads_coll`` — דרך שנייה לאוסף.
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Name)
                and node.slice.id == "MCP_UPLOADS_COLLECTION"
                and owner != "ProductionBackend._uploads_coll"
            ):
                offenders.append(f"{where} גישה לאוסף ההעלאות מתוך {owner}")

    handlers_tree = trees[package / "handlers.py"]
    handler_defs = {
        node.name: node for node in handlers_tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    def names_in(node: ast.AST) -> set[str]:
        return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}

    # מי ששולף העלאה חייב לעבור בשער.
    for handler_name, handler in handler_defs.items():
        used = names_in(handler)
        if "_load_upload" in used and "_consume_upload" not in used:
            offenders.append(f"handlers.{handler_name} שולף העלאה ואינו עובר ב-_consume_upload")

    # וכל כלי רשום עם פרמטר העלאה מגיע ל-handler כזה.
    listed = asyncio.run(srv.build_mcp(_backend()[0], public_url="https://mcp.example.com").list_tools())
    takes_upload = {
        tool.name: sorted(name for name in tool.inputSchema.get("properties", {}) if name.endswith("upload_id"))
        for tool in listed
    }
    takes_upload = {tool: params for tool, params in takes_upload.items() if params}
    assert takes_upload, "אף כלי אינו מקבל פרמטר העלאה — הרשימה נגזרת מהרישום, משהו השתנה שם"
    # הכלים שהטסטים ההתנהגותיים מכסים הם בדיוק אלה שהרישום מפרסם: כלי רביעי שיקבל
    # העלאה נכנס לשומר מעצמו, ונופל כאן עד שיוסיפו אותו גם לטבלה.
    assert takes_upload == {tool: [upload_arg] for tool, upload_arg in _UPLOAD_ARG.items()}, (
        "הכלים שמקבלים העלאה לפי הרישום אינם אלה שב-_TAKES_AN_UPLOAD, והטסטים ההתנהגותיים "
        f"(ה-hint-ים, בדיקת השלמות) רצים על הטבלה: {takes_upload}"
    )
    routed: dict[str, set[str]] = {tool: set() for tool in takes_upload}
    for node in ast.walk(trees[package / "server.py"]):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        registered = {
            keyword.value.value
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Call)
            for keyword in decorator.keywords
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)
        }
        for tool in registered & set(takes_upload):
            for call_node in ast.walk(node):
                if (
                    isinstance(call_node, ast.Call)
                    and isinstance(call_node.func, ast.Attribute)
                    and isinstance(call_node.func.value, ast.Name)
                    and call_node.func.value.id == "handlers"
                    # הפרמטר שהכלי מפרסם הוא זה שעובר ל-handler, באותו שם.
                    and {keyword.arg for keyword in call_node.keywords} >= set(takes_upload[tool])
                ):
                    routed[tool].add(call_node.func.attr)
    for tool, targets in sorted(routed.items()):
        if not targets:
            offenders.append(f"{tool} מקבל {takes_upload[tool]} ואינו מעביר אותו ל-handler")
        for target in targets:
            if "_consume_upload" not in names_in(handler_defs.get(target, ast.Module(body=[], type_ignores=[]))):
                offenders.append(f"{tool} ← handlers.{target}, שאינו עובר ב-_consume_upload")

    assert offenders == [], (
        "מסלול ששולף או צורך העלאה בלי _load_upload (שבודק את השלמות) או בלי השער של "
        f"_consume_upload. אם הוא באמת נחוץ — הוא צריך את הבדיקה לידו במפורש: {offenders}"
    )


# ---------------------------------------------------------------------------
# 5. נראות — בתהליך נקי, לא ב-``caplog``
# ---------------------------------------------------------------------------

#: הגדרת הלוג של השירות, כמו ב-uvicorn — **בלי** ``try``: ייבוא שנכשל היה משאיר את
#: הלוגר בברירת המחדל של פייתון, שמדפיסה WARNING ומעלה גם בלי שום הגדרה, וטסט
#: של שורת WARNING היה עובר בלי לבדוק את מה שרץ בייצור. הסביבה שהייבוא צריך
#: (``BOT_TOKEN``, ``MONGODB_URL``) עוברת לתהליך מ-``tests/conftest.py``.
_SERVICE_LOGGING = SERVICE_LOGGING

_LOG_PROBE = _SERVICE_LOGGING + """
from _uploads_harness import UploadsDbm, upload_storage
from mcp_server.backend import ProductionBackend

db, _ = upload_storage()
backend = ProductionBackend(db_manager=UploadsDbm(db), mongo_db=db)
text = {text!r}
stored = backend.create_upload(4242, text=text, size_bytes=len(text.encode("utf-8")))
print("UPLOAD-ID", stored["upload_id"], flush=True)
assert backend.consume_upload(4242, stored["upload_id"], tool="codekeeper_save_file",
                              size_bytes=len(text.encode("utf-8")), chars=len(text))
print("PROBE-DONE", flush=True)
"""


def test_a_stored_and_a_consumed_upload_each_leave_one_info_line_without_the_id_or_the_text(tmp_path):
    """השורות הן הנראות היחידה בייצור: PostHog אינו רואה ראוטים, וסירובים אינם נרשמים.

    התהליך רץ עם ``-B`` ו-``cwd=tmp_path``: שום ``__pycache__`` ושום קובץ לא נכתבים לעץ.
    """
    secret = "תוכן-פרטי-של-המשתמש"
    text = f"שורה {secret}\n"
    script = textwrap.dedent(_LOG_PROBE).format(repo=str(REPO), tests=str(REPO / "tests"), text=text)
    proc = subprocess.run(
        [sys.executable, "-B", "-c", script], capture_output=True, text=True, timeout=180,
        cwd=str(tmp_path), env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert "PROBE-DONE" in proc.stdout, f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    upload_id = proc.stdout.split("UPLOAD-ID ", 1)[1].split()[0]
    log = proc.stderr + proc.stdout.replace(f"UPLOAD-ID {upload_id}", "")

    size = len(text.encode("utf-8"))
    stored = [line for line in log.splitlines() if "mcp upload: stored" in line]
    consumed = [line for line in log.splitlines() if "mcp upload: consumed" in line]
    assert len(stored) == 1 and f"{size} bytes, {len(text)} chars for user 4242" in stored[0], log
    assert len(consumed) == 1 and "codekeeper_save_file" in consumed[0] and "user 4242" in consumed[0], log
    assert upload_id not in log and secret not in log


_DISCARD_PROBE = _SERVICE_LOGGING + """
from _uploads_harness import UploadsDbm, upload_storage
from mcp_server import handlers
from mcp_server.backend import ProductionBackend

db, uploads = upload_storage()
backend = ProductionBackend(db_manager=UploadsDbm(db), mongo_db=db)
text = {text!r}
stored = backend.create_upload(4242, text=text, size_bytes=len(text.encode("utf-8")))
print("UPLOAD-ID", stored["upload_id"], flush=True)
uploads.docs[0]["text"] = text.replace("שורה", "שורא")
answer = handlers.save_file(backend, 4242, file_name="a.md", upload_id=stored["upload_id"])
print("ANSWER", answer["error"], flush=True)
print("PROBE-DONE", flush=True)
"""


def test_a_corrupted_upload_leaves_one_error_line_and_no_consumed_line(tmp_path):
    """השלכה אינה צריכה: שורה אחת עם הכלי, הסיבה ומה שהמחיקה עשתה — בלי המזהה ובלי הטקסט.

    בלי השורה הזו אחסון שמשבש העלאות נראה בדיוק כמו סוכן שהעלה שוב, ושורת
    ``consumed`` הייתה אומרת שהעלאה נצרכה לשמירה כשלא נשמר כלום.
    """
    secret = "תוכן-פרטי-של-המשתמש"
    text = f"שורה {secret}\n"
    script = textwrap.dedent(_DISCARD_PROBE).format(repo=str(REPO), tests=str(REPO / "tests"), text=text)
    proc = subprocess.run(
        [sys.executable, "-B", "-c", script], capture_output=True, text=True, timeout=180,
        cwd=str(tmp_path), env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert "PROBE-DONE" in proc.stdout and "ANSWER upload_corrupted" in proc.stdout, (
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    upload_id = proc.stdout.split("UPLOAD-ID ", 1)[1].split()[0]
    log = proc.stderr + proc.stdout.replace(f"UPLOAD-ID {upload_id}", "")

    size = len(text.encode("utf-8"))
    corrupted = [line for line in log.splitlines() if "corrupted upload" in line]
    assert len(corrupted) == 1, log
    assert corrupted[0].split("mcp upload:", 1)[0].startswith("ERROR"), corrupted[0]
    for part in ("codekeeper_save_file", "hash_mismatch", f"{size} bytes, {len(text)} chars", "user 4242", "deleted: yes"):
        assert part in corrupted[0], (part, corrupted[0])
    assert not [line for line in log.splitlines() if "mcp upload: consumed" in line], log
    assert upload_id not in log and secret not in log


_URL_PROBE = _SERVICE_LOGGING + """
from mcp_server.public_url import public_base_for

for public_url in (None, "https://mcp.example.com", {rejected!r}):
    print("URL", public_base_for(public_url), flush=True)
print("PROBE-DONE", flush=True)
"""


def test_a_configured_url_that_is_rejected_leaves_one_warning_without_the_url(tmp_path):
    """‏``MCP_SERVER_URL`` שהוגדר ונדחה — WARNING אחד עם הסיבה, בלי הכתובת עצמה (K13).

    "לא הוגדר" ו"הוגדר ונדחה" נותנים אותו ``<mcp-host>`` בתיאור, ורק השורה הזו
    מבדילה ביניהם. כתובת שלא הוגדרה, וכתובת תקינה, אינן משאירות שורה.

    ``MCP_SERVER_URL`` מוסר מהסביבה של התהליך: ייבוא האפליקציה בונה את הכלים, וערך
    שדלף מהסביבה של מי שמריץ את הטסט היה מוסיף שורה משלו.
    """
    rejected = "https://ops:hunter2@mcp.example.com"
    script = textwrap.dedent(_URL_PROBE).format(repo=str(REPO), tests=str(REPO / "tests"), rejected=rejected)
    env = {key: value for key, value in os.environ.items() if key != "MCP_SERVER_URL"}
    proc = subprocess.run(
        [sys.executable, "-B", "-c", script], capture_output=True, text=True, timeout=180,
        cwd=str(tmp_path), env={**env, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert "SERVICE-LOGGING-READY" in proc.stdout and "PROBE-DONE" in proc.stdout, (
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    urls = [line.split(" ", 1)[1] for line in proc.stdout.splitlines() if line.startswith("URL ")]
    assert urls == ["https://<mcp-host>", "https://mcp.example.com", "https://<mcp-host>"]

    log = proc.stderr + proc.stdout
    warnings = [line for line in log.splitlines() if "MCP_SERVER_URL not used" in line]
    assert len(warnings) == 1, log
    assert "WARNING" in warnings[0] and "carries a user name or password" in warnings[0], log
    assert "<mcp-host>" in warnings[0], log
    assert "hunter2" not in log and "ops:" not in log
