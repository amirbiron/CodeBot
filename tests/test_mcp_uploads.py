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
   השלמות שלפני המחיקה (``upload_corrupted``), עם שומר מבני על המקור שאין דרך
   צריכה אחרת.
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
import shutil
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
from _mcp_apps import PatTokens, app_in_mode  # noqa: E402
from _save_layer_harness import clear_local_cache, install_fake_collections, load_production_config  # noqa: E402
from _uploads_harness import IndexedCollection, UploadsDbm, install_upload_storage, upload_storage  # noqa: E402

import mcp_uploads  # noqa: E402
from database.manager import DatabaseManager  # noqa: E402
from mcp_server import handlers  # noqa: E402
from mcp_server.backend import ProductionBackend  # noqa: E402
from mcp_server.limits import MIN_MAX_REQUEST_BYTES, BodySizeLimitMiddleware, ToolRateLimiter  # noqa: E402
from mcp_server.uploads import UPLOAD_PATH, agent_upload_route, upload_url_for  # noqa: E402
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
    """``tools/call`` דרך ``POST /mcp`` כמו שלקוח שולח — ומה שבבלוק הטקסט של התשובה."""
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": name, "arguments": arguments or {"file_name": "x.md"}}},
        headers={"authorization": f"Bearer {token}", "accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 200, response.text
    data = next(line[len("data: "):] for line in response.text.splitlines() if line.startswith("data: "))
    result = json.loads(data)["result"]
    return {"is_error": result.get("isError"), "text": result["content"][0]["text"]}


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
    """זה הראוט השני שמאמת בגוף שלו, אחרי הפריימר; הטסט מונע מהשלישי לשכוח.

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
    assert {"/mcp", "/api/agent/primer", UPLOAD_PATH} <= protected


# ---------------------------------------------------------------------------
# הפקודה — ``curl`` אמיתי, מול uvicorn אמיתי
# ---------------------------------------------------------------------------


class _Served:
    """האפליקציה על uvicorn אמיתי, ב-127.0.0.1 ובפורט שמערכת ההפעלה בוחרת."""

    def __init__(self, app):
        import uvicorn

        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 20
        while not self.server.started:
            assert self.thread.is_alive(), "uvicorn did not start"
            assert time.monotonic() < deadline, "uvicorn did not start in time"
            time.sleep(0.02)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=20)


def _curl() -> str:
    path = shutil.which("curl")
    # בקול, לא בדילוג: בלי curl הטסט הזה אינו בודק את מה שהסוכן מריץ.
    assert path, "curl is required: this test runs the command the tool description gives"
    return path


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
    (None, "https://<mcp-host>/api/agent/upload"),
    ("", "https://<mcp-host>/api/agent/upload"),
    ("https://mcp.example.com", "https://mcp.example.com/api/agent/upload"),
    ("https://mcp.example.com/", "https://mcp.example.com/api/agent/upload"),
    ("http://127.0.0.1:8000", "http://127.0.0.1:8000/api/agent/upload"),
    ("https://user:hunter2@mcp.example.com", "https://<mcp-host>/api/agent/upload"),
    ("https://mcp.example.com?token=hunter2", "https://<mcp-host>/api/agent/upload"),
    ("ftp://mcp.example.com", "https://<mcp-host>/api/agent/upload"),
    ("https://[::1", "https://<mcp-host>/api/agent/upload"),
    ("mcp.example.com", "https://<mcp-host>/api/agent/upload"),
    ("https://mcp.example.com:8443", "https://mcp.example.com:8443/api/agent/upload"),
    ("https://mcp.example.com:abc", "https://<mcp-host>/api/agent/upload"),
    ("https://mcp.example.com:99999", "https://<mcp-host>/api/agent/upload"),
])
def test_the_upload_url_in_the_descriptions_is_the_configured_host_or_a_placeholder(public_url, expected):
    """‏``MCP_SERVER_URL`` נכנס לתיאור שכל לקוח מקבל — בלי סיסמה ובלי query (K13)."""
    assert upload_url_for(public_url) == expected


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


@pytest.mark.parametrize("tool, param", [("codekeeper_save_file", "code"), ("codekeeper_append_file", "content")])
def test_every_upload_refusal_carries_a_hint_that_names_the_parameter(store, backend, call, tool, param):
    """התיאור אינו מונה את הסירובים, ולכן ההסבר שבכל סירוב הוא ההסבר היחיד שהסוכן מקבל."""
    assert call("codekeeper_save_file", file_name="log.md", code="head\n")["ok"] is True
    upload_id = _create(backend, "tail\n")

    both = call(tool, file_name="log.md", upload_id=upload_id, **{param: "inline\n"})
    assert both["error"] == f"{param}_and_upload_id"
    assert both["hint"] == f"pass either the {param} parameter or upload_id, not both"

    neither = call(tool, file_name="log.md")
    assert neither["error"] == f"empty_{param}"
    assert f"in the {param} parameter, or upload the file first and pass upload_id" in neither["hint"]

    for bad_id, error in (("../../etc/passwd", "invalid_upload_id"), (mcp_uploads.new_upload_id(), "upload_not_found")):
        res = call(tool, file_name="log.md", upload_id=bad_id)
        assert res["error"] == error
        assert isinstance(res.get("hint"), str) and res["hint"].strip(), res

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


@pytest.mark.parametrize("corruption", sorted(_CORRUPTIONS))
@pytest.mark.parametrize("tool, seed", [("codekeeper_save_file", None), ("codekeeper_append_file", "head\n")])
def test_an_upload_that_does_not_match_its_hash_writes_nothing_and_is_gone(store, backend, call, tool, seed, corruption):
    """``upload_corrupted``: שום גרסה, שום התראה, וההעלאה עצמה נמחקת — בשני הכלים.

    לפני הבדיקה הטקסט המשובש נשמר בשקט: ``content_changed`` היה ``false``, כי מה
    שנכתב שווה למה שנשלף.
    """
    if seed is not None:
        assert call("codekeeper_save_file", file_name="log.md", code=seed)["ok"] is True
    versions = len(store.code_snippets.docs)
    pushes = len(store.raw["push_events"].docs)
    upload_id = _create(backend, "tail\n")
    _CORRUPTIONS[corruption](store.uploads.docs[0])

    res = call(tool, file_name="log.md", upload_id=upload_id)
    assert res["ok"] is False and res["error"] == "upload_corrupted", res
    assert "upload the file again" in res["hint"], res
    assert len(store.code_snippets.docs) == versions
    assert len(store.raw["push_events"].docs) == pushes
    assert store.uploads.docs == []


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

    אחד מוחק ואחד מוצא שכבר נמחקה, והתשובה של שניהם זהה — כי הבדיקה באה לפני המחיקה.
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


@pytest.mark.parametrize("tool, param, seed", [
    ("codekeeper_save_file", "code", None),
    ("codekeeper_append_file", "content", "head\n"),
])
def test_without_upload_id_the_upload_storage_is_not_touched(store, call, monkeypatch, tool, param, seed):
    """בלי ``upload_id`` שום דבר לא משתנה: הבדיקה היא של העלאות, ותוכן inline אינו עובר בה.

    מקבע התנהגות שכבר הייתה נכונה, ולכן עובר גם על הקוד שלפני בדיקת השלמות — בכוונה.
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
    res = call(tool, file_name="log.md", **{param: "inline\n"})
    assert res["ok"] is True and res["content_changed"] is False, res
    assert touched == []
    assert not [key for key in res if key.startswith("upload")], res


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


#: מי רשאי לקרוא לשיטות ההעלאה של ה-backend. שליפה רק דרך ``_load_upload``, ומחיקה
#: — צריכה או השלכה של העלאה משובשת — רק דרך ``_consume_upload``, שבודק את השלמות
#: לפני שהוא מוחק.
_UPLOAD_METHOD_CALLERS = {
    "find_upload": "_load_upload",
    "consume_upload": "_consume_upload",
    "discard_upload": "_consume_upload",
}

#: פעולות שכותבות או מוחקות באוסף. מחיקה מותרת רק במקום אחד; עדכון — בשום מקום,
#: כי טקסט שנשמר עם ה-hash שלו ואז השתנה הוא בדיוק מה שבדיקת השלמות דוחה.
_COLLECTION_WRITES = {
    "delete_one", "delete_many", "find_one_and_delete", "find_one_and_update",
    "find_one_and_replace", "update_one", "update_many", "replace_one", "bulk_write",
}


def test_every_upload_is_consumed_through_the_one_helper_that_checks_it():
    """שומר מבני: כל כלי שמקבל ``upload_id`` צורך דרך ``_consume_upload``, ואין אתר צריכה אחר.

    **מה זה שומר.** בדיקת השלמות חיה כולה ב-``_consume_upload``, לפני המחיקה. כלי
    שלישי שיקבל ``upload_id`` ויקרא ל-``backend.consume_upload`` ישירות — או שיטת
    backend שתמחק העלאה בעצמה — ישמור טקסט שלא נבדק, וכל הטסטים ההתנהגותיים ימשיכו
    לעבור, כי הם מכסים את שני הכלים של היום ולא את זה שייכתב. לכן הבדיקה על המקור,
    באותו נימוק של השומר על תקרת הסורקים ב-``tests/test_mcp_outline.py``, ודרך ``ast``
    ולא רג'קס: שם שמופיע ב-docstring אינו קריאה.

    רשימת הכלים נגזרת מהרישום האמיתי (``list_tools``), ולא מרשימה בטסט: כלי חדש
    עם ``upload_id`` נכנס לבדיקה בלי שמישהו יזכור להוסיף אותו.

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

    # וכל כלי רשום עם ``upload_id`` מגיע ל-handler כזה.
    listed = asyncio.run(srv.build_mcp(_backend()[0], public_url="https://mcp.example.com").list_tools())
    takes_upload = {tool.name for tool in listed if "upload_id" in tool.inputSchema.get("properties", {})}
    assert takes_upload, "אף כלי אינו מקבל upload_id — הרשימה נגזרת מהרישום, משהו השתנה שם"
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
        for tool in registered & takes_upload:
            for call_node in ast.walk(node):
                if (
                    isinstance(call_node, ast.Call)
                    and isinstance(call_node.func, ast.Attribute)
                    and isinstance(call_node.func.value, ast.Name)
                    and call_node.func.value.id == "handlers"
                    and any(keyword.arg == "upload_id" for keyword in call_node.keywords)
                ):
                    routed[tool].add(call_node.func.attr)
    for tool, targets in sorted(routed.items()):
        if not targets:
            offenders.append(f"{tool} מקבל upload_id ואינו מעביר אותו ל-handler")
        for target in targets:
            if "_consume_upload" not in names_in(handler_defs.get(target, ast.Module(body=[], type_ignores=[]))):
                offenders.append(f"{tool} ← handlers.{target}, שאינו עובר ב-_consume_upload")

    assert offenders == [], (
        "מסלול שצורך העלאה בלי בדיקת השלמות של _consume_upload. אם הוא באמת נחוץ — "
        f"הוא צריך את הבדיקה לידו במפורש: {offenders}"
    )


# ---------------------------------------------------------------------------
# 5. נראות — בתהליך נקי, לא ב-``caplog``
# ---------------------------------------------------------------------------

#: הגדרת הלוג של השירות, כמו ב-uvicorn — **בלי** ``try``: ייבוא שנכשל היה משאיר את
#: הלוגר בברירת המחדל של פייתון, שמדפיסה WARNING ומעלה גם בלי שום הגדרה, וטסט
#: של שורת WARNING היה עובר בלי לבדוק את מה שרץ בייצור. הסביבה שהייבוא צריך
#: (``BOT_TOKEN``, ``MONGODB_URL``) עוברת לתהליך מ-``tests/conftest.py``.
_SERVICE_LOGGING = """
import os, sys
sys.path.insert(0, {repo!r})
sys.path.insert(0, {tests!r})
os.environ["MCP_PUSH_NOTIFICATIONS_ENABLED"] = "false"
import mcp_server.app  # noqa: F401
print("SERVICE-LOGGING-READY", flush=True)
"""

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
pending = handlers._load_upload(backend, 4242, stored["upload_id"])
answer = handlers._consume_upload(backend, 4242, pending, tool="codekeeper_save_file")
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
from mcp_server.uploads import upload_url_for

for public_url in (None, "https://mcp.example.com", {rejected!r}):
    print("URL", upload_url_for(public_url), flush=True)
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
    assert urls == [
        "https://<mcp-host>/api/agent/upload",
        "https://mcp.example.com/api/agent/upload",
        "https://<mcp-host>/api/agent/upload",
    ]

    log = proc.stderr + proc.stdout
    warnings = [line for line in log.splitlines() if "MCP_SERVER_URL not used" in line]
    assert len(warnings) == 1, log
    assert "WARNING" in warnings[0] and "carries a user name or password" in warnings[0], log
    assert "<mcp-host>" in warnings[0], log
    assert "hunter2" not in log and "ops:" not in log
