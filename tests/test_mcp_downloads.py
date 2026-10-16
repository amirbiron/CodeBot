"""הורדת קובץ שמור לדיסק של הסוכן בלי לעבור דרך המודל — ``GET /api/agent/download``.

הטסטים עוברים בשכבה שבה כל הבטחה חיה:

1. **הראוט, על האפליקציה המלאה ובשני מצבי האימות** — ``build_app`` כפי שהוא רץ, דרך
   ``TestClient`` (``tests/_mcp_apps.py``), מעל שכבת השמירה האמיתית
   (``tests/_save_layer_harness.py``). הקבצים נשמרים ונקראים בכלים עצמם, דרך ``POST /mcp``,
   כך שה-hash שההורדה מחזירה מושווה למה ש-``codekeeper_get_file`` מחזיר — ולצד זה גם ל-
   ``hashlib`` על הבתים, מחושב כאן.
2. **הלולאה הסגורה עם ההעלאה** — ``PUT /api/agent/upload`` ← ``codekeeper_save_file`` עם
   ``upload_id`` ← הורדה, על 12 המקרים הקשים (``tests/_hard_text_cases.py``). אותה לולאה
   מול ``mongod`` אמיתי — ב-``tests/test_mcp_content_sha256_real_mongo.py``.
3. **הפקודה עצמה** — כפי שהיא כתובה בתיאורי הכלים, ב-``bash`` עם ``curl`` אמיתי מול
   uvicorn אמיתי.
4. **התיאורים** — הפקודה וה-host בתיאור ``file_id`` ובתיאור ``codekeeper_list_versions``,
   וההפניה בתיאור ``codekeeper_get_file``.
5. **נראות** — שורת ה-``INFO``, ו-WARNING אחד על ``MCP_SERVER_URL`` שנדחה, בתהליך נקי.

כל טסט כאן הורץ על הקוד שלפני הראוט ונכשל (הראוט לא היה קיים: 401 במצב PAT, 404 ב-OAuth).
כל מוטציה שמוזכרת בגוף טסט הורצה על עותק (``git worktree``) והפילה אותו. הפלטים בגוף ה-PR.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("mcp")

from starlette.testclient import TestClient  # noqa: E402

# ‏``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _hard_text_cases import CASES  # noqa: E402
from _mcp_apps import SERVICE_LOGGING, PatTokens, Served, app_in_mode, curl_path, tool_call_over_http  # noqa: E402
from _save_layer_harness import clear_local_cache, install_fake_collections, load_production_config  # noqa: E402
from _uploads_harness import install_upload_storage  # noqa: E402

from mcp_server import handlers  # noqa: E402
from mcp_server.backend import ProductionBackend  # noqa: E402
from mcp_server.downloads import DOWNLOAD_PATH, PARAMETERS  # noqa: E402
from mcp_server.uploads import UPLOAD_PATH  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
MODES = ["pat", "oauth"]

USER_A, USER_B = 101, 202
#: ‏``ckmcp_`` בראש, כדי שבמצב OAuth ``load_access_token`` ינתב אותם לאימות ה-PAT.
READ_A, WRITE_A, READ_B, WRITE_B = "ckmcp_read_a", "ckmcp_write_a", "ckmcp_read_b", "ckmcp_write_b"
TOKENS = PatTokens({
    READ_A: {"user_id": USER_A, "scopes": ["read"]},
    WRITE_A: {"user_id": USER_A, "scopes": ["read", "write"]},
    READ_B: {"user_id": USER_B, "scopes": ["read"]},
    WRITE_B: {"user_id": USER_B, "scopes": ["read", "write"]},
})

#: מזהה בצורה של ``ObjectId`` שאין מאחוריו מסמך.
MISSING_ID = "0123456789abcdef01234567"


# ---------------------------------------------------------------------------
# עזרים
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _production(monkeypatch):
    # ``build_mcp`` קורא ל-``instrument_mcp_server``, שזורק מחוץ לפרודקשן בלי PostHog —
    # אותו קיבוע כמו ב-``tests/test_mcp_uploads.py``.
    monkeypatch.setenv("ENVIRONMENT", "production")


@pytest.fixture
def store(monkeypatch):
    """שכבת השמירה האמיתית מעל הדמה המשותפת, ואחסון העלאות לצידה.

    ``get_file_by_id`` ממיר ``ObjectId(file_id)``, והדמה נותנת ``_id`` מספרי; לכן ה-insert
    נותן ``ObjectId`` כשאין ``_id`` — כמו pymongo, שמייצר אותו בצד הלקוח (אותה החלפה כמו
    ב-``tests/test_mcp_content_sha256.py``). ``emit_event`` של ``Repository`` נרשם כאן:
    מזהה פגום מגיע ל-``get_file_by_id``, שרושם אירוע ברמת error, וזה נכתב למאגר
    השגיאות האחרונות שמשותף לכל הטסטים בתהליך.
    """
    from bson import ObjectId

    from database.repository import Repository

    load_production_config(monkeypatch)
    harness = install_fake_collections(monkeypatch)
    real_insert = harness.code_snippets.insert_one
    monkeypatch.setattr(harness.code_snippets, "insert_one", lambda doc: real_insert({"_id": ObjectId(), **doc}))
    harness.uploads = install_upload_storage(monkeypatch, harness)
    harness.events = []
    monkeypatch.setitem(
        Repository.get_file_by_id.__globals__, "emit_event",
        lambda event, severity="info", **fields: harness.events.append((event, severity)),
    )
    yield harness
    clear_local_cache()


@pytest.fixture
def backend(store):
    return ProductionBackend(db_manager=store.dbm, mongo_db=store.raw)


@pytest.fixture
def fetches(monkeypatch) -> list[dict]:
    """כל קריאה ל-``handlers.get_file`` — מי שמגיע לשליפה, ועם אילו ארגומנטים."""
    calls: list[dict] = []
    real = handlers.get_file

    def spy(backend, user_id, **kwargs):
        calls.append({"user_id": user_id, **kwargs})
        return real(backend, user_id, **kwargs)

    monkeypatch.setattr(handlers, "get_file", spy)
    return calls


def _tool(client, token: str, name: str, **arguments) -> dict:
    """קריאת כלי דרך ``POST /mcp``, והתשובה מפוענחת."""
    answer = tool_call_over_http(client, token, name, arguments)
    assert not answer["is_error"], answer
    return json.loads(answer["text"])


def _save(client, file_name: str, code: str, token: str = WRITE_A) -> dict:
    saved = _tool(client, token, "codekeeper_save_file", file_name=file_name, code=code)
    assert saved["ok"] is True and saved["content_changed"] is False, saved
    return saved["file"]


def _download(client, token: str | None = READ_A, query: str | None = None, method: str = "GET", **params):
    headers = {"authorization": f"Bearer {token}"} if token is not None else {}
    url = f"{DOWNLOAD_PATH}?{query}" if query is not None else DOWNLOAD_PATH
    return client.request(method, url, params=params or None, headers=headers)


def _closes(response) -> bool:
    return response.headers.get("connection", "").lower() == "close"


def _no_store(response) -> bool:
    return response.headers.get("cache-control") == "no-store"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# 1. הראוט — האפליקציה המלאה, בשני מצבי האימות
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_without_a_valid_token_it_is_a_401_that_closes_and_is_not_stored(mode, backend, fetches):
    """‏401 מהראוט עצמו — גם במצב PAT, שבו הנתיב פטור מ-``PATAuthMiddleware`` — ושום שליפה.

    מוטציה: הנתיב יוצא מרשימת הפטור ב-``build_app`` — במצב PAT ה-401 הוא של המידלוור,
    בלי ``Connection: close`` ובלי ``no-store``, והטסט נופל.
    """
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS)) as client:
        for token in (None, "ckmcp_not_a_token", "not-a-pat-either"):
            response = _download(client, token=token, file_id=MISSING_ID)
            assert response.status_code == 401, (token, response.text)
            assert response.json() == {"error": "invalid_token"}
            assert _closes(response) and _no_store(response) and "www-authenticate" in response.headers
    assert fetches == []


@pytest.mark.parametrize("mode", MODES)
def test_a_read_token_downloads_the_exact_bytes_with_the_hash_get_file_returns(mode, backend):
    """‏200 על טוקן ``read`` — ההכרעה, לא 403. הגוף הוא ``code.encode("utf-8")`` ותו לא.

    ``X-Content-SHA256`` מושווה לשני מקורות שאינם הראוט: ``hashlib`` על הבתים שהגיעו,
    מחושב כאן, ו-``file.content_sha256`` ש-``codekeeper_get_file`` מחזיר על אותו מזהה.
    """
    code = "﻿#!/usr/bin/env python3\r\nprint('שלום \U0001F600')\r\n\n"
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS)) as client:
        saved = _save(client, "run.py", code)
        response = _download(client, file_id=saved["id"])
        read = _tool(client, READ_A, "codekeeper_get_file", file_id=saved["id"], lines=[1, 1])

    assert response.status_code == 200, response.text
    assert response.content == code.encode("utf-8")
    assert response.headers["x-content-sha256"] == _sha(response.content) == read["file"]["content_sha256"]
    assert response.headers["x-file-version"] == "1"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-length"] == str(len(code.encode("utf-8")))
    assert _no_store(response)
    assert not _closes(response), "הורדה שהצליחה משאירה את החיבור"


@pytest.mark.parametrize("mode", MODES)
def test_by_name_is_the_latest_by_name_and_version_is_that_one_and_by_id_is_the_version_it_names(mode, backend):
    """שלוש דרכי הזיהוי של ``codekeeper_get_file``, על קובץ עם שתי גרסאות."""
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS)) as client:
        first = _save(client, "notes.md", "גרסה ראשונה\n")
        second = _tool(client, WRITE_A, "codekeeper_append_file", file_name="notes.md", content="תוספת\n")["file"]
        latest = _download(client, file_name="notes.md")
        pinned = _download(client, file_name="notes.md", version="1")
        by_id = _download(client, file_id=first["id"])

        # ה-``id`` שברשימת הגרסאות הוא ה-``file_id`` שהתיאורים מבטיחים.
        listed = _tool(client, READ_A, "codekeeper_list_versions", file_name="notes.md")["versions"]
        (listed_v1,) = [v for v in listed if v["version"] == 1]
        from_list = _download(client, file_id=listed_v1["id"])

    v1 = "גרסה ראשונה\n".encode("utf-8")
    assert from_list.status_code == 200 and from_list.content == v1
    assert latest.status_code == 200 and latest.headers["x-file-version"] == "2"
    assert latest.headers["x-content-sha256"] == second["content_sha256"] == _sha(latest.content)
    assert latest.content != v1
    assert pinned.content == v1 and pinned.headers["x-file-version"] == "1"
    assert by_id.content == v1 and by_id.headers["x-file-version"] == "1"
    assert by_id.headers["x-content-sha256"] == first["content_sha256"] == _sha(v1)


@pytest.mark.parametrize("mode", MODES)
def test_someone_elses_a_missing_and_a_malformed_id_are_one_404(mode, backend, store):
    """שלושתם אותה תשובה בדיוק — הסירוב אינו מגלה שהמזהה קיים אצל מישהו אחר.

    מוטציה: בלי בדיקת הבעלות בענף ``file_id`` של ``ProductionBackend.get_file`` — B מקבל
    את הבתים של A ב-200, והטסט נופל.
    """
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS)) as client:
        mine = _save(client, "secret.py", "TOKEN = 'של A'\n", token=WRITE_A)
        answers = [
            _download(client, token=READ_B, file_id=mine["id"]),
            _download(client, token=READ_B, file_name="secret.py"),
            _download(client, token=READ_A, file_id=MISSING_ID),
            _download(client, token=READ_A, file_id="not-an-object-id"),
            _download(client, token=READ_A, file_name="no-such-file.py"),
        ]
        still_mine = _download(client, token=READ_A, file_id=mine["id"])

    for response in answers:
        assert response.status_code == 404, response.text
        assert response.json() == {"error": "not_found"}
        assert _closes(response) and _no_store(response)
    assert still_mine.status_code == 200 and still_mine.content == "TOKEN = 'של A'\n".encode("utf-8")


@pytest.mark.parametrize("case", sorted(CASES))
def test_nothing_in_the_body_is_normalized(backend, case):
    """BOM, ‏CRLF, ‏CR בודד, ירידות שורה בסוף, NUL — הבתים שירדו הם בתי ה-UTF-8 של מה שנשמר.

    מוטציה: ``.replace("\\r\\n", "\\n")`` או ``lstrip("\\ufeff")`` על הטקסט ב-``_load`` —
    המקרים עם CRLF או BOM נופלים.
    """
    text = CASES[case]
    with TestClient(app_in_mode("pat", backend, tokens=TOKENS)) as client:
        saved = _save(client, f"{case}.txt", text)
        response = _download(client, file_id=saved["id"])
    assert response.status_code == 200
    assert response.content == text.encode("utf-8")
    assert response.headers["x-content-sha256"] == _sha(text.encode("utf-8")) == saved["content_sha256"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("case", sorted(CASES))
def test_upload_save_and_download_return_the_bytes_that_were_uploaded(mode, backend, store, case):
    """הלולאה הסגורה: ``PUT /api/agent/upload`` ← ``codekeeper_save_file`` עם ``upload_id`` ← הורדה.

    שלושה hash-ים — תשובת ההעלאה, ``file.content_sha256`` של השמירה, ו-``X-Content-SHA256`` —
    שווים ל-``hashlib`` על הבתים שהועלו, והבתים שירדו הם הבתים שהועלו.
    """
    raw = CASES[case].encode("utf-8")
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS)) as client:
        uploaded = client.put(UPLOAD_PATH, content=raw, headers={"authorization": f"Bearer {READ_A}"})
        assert uploaded.status_code == 201, uploaded.text
        saved = _tool(client, WRITE_A, "codekeeper_save_file", file_name=f"loop_{case}.txt",
                      upload_id=uploaded.json()["upload_id"])
        assert saved["ok"] is True, saved
        response = _download(client, file_id=saved["file"]["id"])

    assert response.status_code == 200
    assert response.content == raw
    assert (uploaded.json()["content_sha256"] == saved["file"]["content_sha256"]
            == response.headers["x-content-sha256"] == _sha(raw))


def test_a_hebrew_name_with_a_space_is_found_when_it_is_encoded(backend):
    """שם בעברית עם רווח, מקודד בשורת השאילתה (כמו ש-``httpx`` מקודד את ``params``) ← 200,
    והבתים של הגרסה האחרונה. הצורה הלא-מקודדת אינה נבדקת כאן: לקוח HTTP תקין לא שולח אותה,
    והתיעוד נוקב רק בצורה המקודדת. ‏``curl --data-urlencode`` — בטסט של הפקודה, למטה."""
    name = "דוח שבועי.md"
    with TestClient(app_in_mode("pat", backend, tokens=TOKENS)) as client:
        _save(client, name, "ישן\n")
        latest = _tool(client, WRITE_A, "codekeeper_append_file", file_name=name, content="חדש\n")["file"]
        response = _download(client, file_name=name)
    assert response.status_code == 200
    assert response.headers["x-file-version"] == "2"
    assert _sha(response.content) == latest["content_sha256"]


#: שורות שאילתה שאינן בקשה תקינה — וכל אחת עם הקוד שלה. ``version`` של 5,000 ספרות
#: היה 500 בלי התקרה ב-``_VERSION``: ``int()`` זורק מעל ``sys.int_info.default_max_str_digits``.
SHAPE_REFUSALS = [
    ("", {"error": "missing_target"}),
    ("version=2", {"error": "missing_target"}),
    ("repo=CodeBot&path=main.py", {"error": "unknown_parameter", "allowed": list(PARAMETERS)}),
    ("verison=1&file_name=a.md", {"error": "unknown_parameter", "allowed": list(PARAMETERS)}),
    (f"file_id={MISSING_ID}&file_id=abc", {"error": "repeated_parameter", "parameter": "file_id"}),
    ("file_name=a.md&file_name=b.md", {"error": "repeated_parameter", "parameter": "file_name"}),
    ("file_name=", {"error": "empty_parameter", "parameter": "file_name"}),
    ("file_name=a.md&version=", {"error": "empty_parameter", "parameter": "version"}),
    (f"file_id={MISSING_ID}&file_name=a.md", {"error": "ambiguous_target"}),
    (f"file_id={MISSING_ID}&version=1", {"error": "ambiguous_target"}),
    ("file_name=a.md&version=abc", {"error": "invalid_version"}),
    ("file_name=a.md&version=-1", {"error": "invalid_version"}),
    ("file_name=a.md&version=%C2%B2", {"error": "invalid_version"}),
    ("file_name=a.md&version=1.0", {"error": "invalid_version"}),
    ("file_name=a.md&version=" + "9" * 5000, {"error": "invalid_version"}),
]


@pytest.mark.parametrize("query, body", SHAPE_REFUSALS, ids=[q[:40] or "empty" for q, _ in SHAPE_REFUSALS])
def test_a_request_of_the_wrong_shape_is_a_400_with_its_own_code_and_nothing_is_fetched(backend, fetches, query, body):
    """סירוב ולא התעלמות: ``verison=1`` שהיה נבלע היה מחזיר את הגרסה האחרונה ב-200.

    מוטציה: ``request.query_params.get(...)`` לכל פרמטר במקום ``download_target`` — שם שגוי,
    ערך כפול ו-``version`` לצד ``file_id`` עוברים בשקט, והטסט נופל.
    """
    with TestClient(app_in_mode("pat", backend, tokens=TOKENS)) as client:
        response = _download(client, query=query)
    assert response.status_code == 400, response.text
    assert response.json() == body
    assert _closes(response) and _no_store(response)
    assert fetches == []


@pytest.mark.parametrize("mode", MODES)
def test_a_download_and_a_tool_call_draw_on_one_quota(mode, backend):
    """המגביל של הראוט **הוא** המגביל של ``call_tool``: שלוש קריאות מתוך שתיים.

    מוטציה: מגביל נפרד לראוט (``ToolRateLimiter(...)`` חדש ב-``build_app``) — ההורדה
    השלישית עוברת, והטסט נופל.
    """
    with TestClient(app_in_mode(mode, backend, tokens=TOKENS, rate_limit_per_minute=2)) as client:
        assert _download(client, file_id=MISSING_ID).status_code == 404
        assert "rate_limited" not in tool_call_over_http(
            client, READ_A, "codekeeper_get_file", {"file_name": "x.md"})["text"]
        refused = _download(client, file_id=MISSING_ID)
        assert refused.status_code == 429 and _closes(refused) and _no_store(refused)
        body = refused.json()
        assert body["error"] == "rate_limited" and body["limit_per_minute"] == 2 and "ok" not in body
        assert body["retry_after_seconds"] >= 1
        # ...ולזהות אחרת המכסה שלה.
        assert _download(client, token=READ_B, file_id=MISSING_ID).status_code == 404


def test_the_fetch_runs_on_the_read_pool_and_not_on_anyios_threads(backend, monkeypatch):
    """השליפה רצה במאגר הקריאה שגודלו נגזר ממכסת הזיכרון (``attach_read_pool``, החוטים
    ``mcp-read``), כמו גוף ``codekeeper_get_file`` — ולא במאגר של anyio, שאינו נספר שם.

    מוטציה: ``anyio.to_thread.run_sync`` במקום ``asyncio.to_thread`` ב-``endpoint`` — השליפה
    רצה ב-``AnyIO worker thread``, והטסט נופל.
    """
    import threading

    import mcp_server.downloads as downloads

    seen: list[str] = []
    real = downloads._load

    def spy(*args):
        seen.append(threading.current_thread().name)
        return real(*args)

    monkeypatch.setattr(downloads, "_load", spy)
    with TestClient(app_in_mode("pat", backend, tokens=TOKENS)) as client:
        saved = _save(client, "t.txt", "x\n")
        assert _download(client, file_id=saved["id"]).status_code == 200
    assert len(seen) == 1 and seen[0].startswith("mcp-read"), seen


def test_head_runs_the_whole_route_and_counts_against_the_quota(backend):
    """Starlette מוסיף ``HEAD`` לכל ראוט ``GET``; היא עוברת את כל הראוט ונספרת כקריאה."""
    with TestClient(app_in_mode("pat", backend, tokens=TOKENS, rate_limit_per_minute=2)) as client:
        saved = _save(client, "h.txt", "abc\n")  # הקריאה הראשונה מתוך שתיים
        head = _download(client, method="HEAD", file_id=saved["id"])
        after = _download(client, file_id=saved["id"])
    assert head.status_code == 200 and head.headers["x-content-sha256"] == _sha(b"abc\n")
    assert after.status_code == 429


# ---------------------------------------------------------------------------
# 2. הפקודה — כפי שהיא כתובה בתיאורים, ב-``curl`` אמיתי מול uvicorn אמיתי
# ---------------------------------------------------------------------------


def _command(tool, base: str, *, param: str | None) -> str:
    """פקודת ההורדה מתוך תיאור הכלי — או מתיאור הפרמטר ``param`` שלו."""
    doc = tool.parameters["properties"][param]["description"] if param else tool.description
    match = re.search(r'curl -fsS -H "Authorization: Bearer \$CODEKEEPER_PAT" -o (\S+) "(\S+)" && sha256sum (\S+)', doc)
    assert match, doc
    assert match.group(1) == match.group(3)
    assert match.group(2) == f"{base}{DOWNLOAD_PATH}?file_id=<id>"
    return match.group(0)


def _run(command: str, cwd: pathlib.Path, token: str | None) -> subprocess.CompletedProcess:
    curl = curl_path()
    env = {key: value for key, value in os.environ.items() if key != "CODEKEEPER_PAT"}
    if token is not None:
        env["CODEKEEPER_PAT"] = token
    return subprocess.run(
        ["bash", "-c", command.replace("curl ", f"{curl} ", 1)],
        cwd=cwd, capture_output=True, text=True, timeout=60, env=env,
    )


@pytest.mark.parametrize("tool_name, param", [("codekeeper_get_file", "file_id"), ("codekeeper_list_versions", None)])
def test_the_command_in_the_descriptions_saves_the_exact_bytes_and_prints_their_hash(tmp_path, backend, tool_name, param):
    """הפקודה **מתוך התיאור**, ב-``bash``, עם ``$CODEKEEPER_PAT`` בסביבה: הקובץ שנכתב הוא
    הבתים שנשמרו, וה-hash ש-``sha256sum`` מדפיס הוא ``file.content_sha256``."""
    import mcp_server.server as srv

    code = "﻿echo 'שלום'\r\nexit 0\n"
    with Served(app_in_mode("pat", backend, tokens=TOKENS)) as served:
        base = f"http://127.0.0.1:{served.port}"
        tool = srv.build_mcp(backend, public_url=base)._tool_manager.get_tool(tool_name)
        command = _command(tool, base, param=param)
        with TestClient(app_in_mode("pat", backend, tokens=TOKENS)) as client:
            saved = _save(client, "deploy.sh", code)
        proc = _run(command.replace("<id>", saved["id"]), tmp_path, READ_A)

    assert proc.returncode == 0, proc.stderr
    out = re.search(r"-o (\S+)", command).group(1)
    assert (tmp_path / out).read_bytes() == code.encode("utf-8")
    assert proc.stdout.split()[0] == saved["content_sha256"] == _sha(code.encode("utf-8"))


@pytest.mark.parametrize("token, file_id", [(READ_A, MISSING_ID), (None, MISSING_ID), ("ckmcp_wrong", MISSING_ID)])
def test_the_command_fails_without_a_file_and_sha256sum_does_not_run(tmp_path, backend, token, file_id):
    """מזהה שאינו קיים, בלי טוקן, או טוקן פסול: קוד יציאה שאינו 0, ``sha256sum`` לא רץ,
    וקובץ היעד לא נוצר.

    מוטציה: ``-f`` יוצא מ-``_download_command`` (``curl -sS``) — curl כותב את
    ``{"error":"not_found"}`` לקובץ היעד ויוצא ב-0, ``sha256sum`` רץ על הודעת השגיאה, והטסט
    נופל. נמדד גם על 401 (curl 8.5.0 מול uvicorn 0.38.0): ``-f`` נכשל בו בקוד 22, אף שה-man
    של curl מזהיר ש-401 יכול לחמוק — שם מדובר באימות של curl עצמו (``-u``), לא בכותרת.
    """
    import mcp_server.server as srv

    with Served(app_in_mode("pat", backend, tokens=TOKENS)) as served:
        base = f"http://127.0.0.1:{served.port}"
        tool = srv.build_mcp(backend, public_url=base)._tool_manager.get_tool("codekeeper_get_file")
        command = _command(tool, base, param="file_id")
        proc = _run(command.replace("<id>", file_id), tmp_path, token)

    assert proc.returncode != 0
    assert "script.py" not in proc.stdout, "sha256sum ran on whatever curl wrote"
    assert not (tmp_path / "script.py").exists()


def test_a_name_in_hebrew_with_a_space_downloads_with_data_urlencode(tmp_path, backend):
    """הצורה המקודדת שהתיעוד נוקב בה להורדה לפי שם: ``-G`` ו-``--data-urlencode``."""
    name = "דוח שבועי.md"
    with TestClient(app_in_mode("pat", backend, tokens=TOKENS)) as client:
        _save(client, name, "ישן\n")
        latest = _tool(client, WRITE_A, "codekeeper_append_file", file_name=name, content="חדש\n")["file"]
    with Served(app_in_mode("pat", backend, tokens=TOKENS)) as served:
        command = (
            'curl -fsS -G -H "Authorization: Bearer $CODEKEEPER_PAT" '
            f'--data-urlencode "file_name={name}" -o out.md "http://127.0.0.1:{served.port}{DOWNLOAD_PATH}"'
        )
        proc = _run(command, tmp_path, READ_A)
    assert proc.returncode == 0, proc.stderr
    assert _sha((tmp_path / "out.md").read_bytes()) == latest["content_sha256"]


def test_head_over_the_wire_sends_the_headers_without_the_body(tmp_path, backend):
    """uvicorn שולח ל-``HEAD`` את הכותרות בלי הגוף — ``Content-Length`` הוא אורך הקובץ."""
    with TestClient(app_in_mode("pat", backend, tokens=TOKENS)) as client:
        saved = _save(client, "h.txt", "שלום\n")
    with Served(app_in_mode("pat", backend, tokens=TOKENS)) as served:
        proc = subprocess.run(
            [curl_path(), "-sS", "-I", "-H", f"Authorization: Bearer {READ_A}",
             f"http://127.0.0.1:{served.port}{DOWNLOAD_PATH}?file_id={saved['id']}"],
            cwd=tmp_path, capture_output=True, text=True, timeout=60,
        )
    raw = "שלום\n".encode("utf-8")
    headers = proc.stdout.lower()
    assert " 200 " in headers.splitlines()[0]
    assert f"x-content-sha256: {_sha(raw)}" in headers
    assert f"content-length: {len(raw)}" in headers


# ---------------------------------------------------------------------------
# 3. התיאורים
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("public_url, base", [
    (None, "https://<mcp-host>"),
    ("https://mcp.example.com/", "https://mcp.example.com"),
    ("https://ops:hunter2@mcp.example.com", "https://<mcp-host>"),
])
def test_the_descriptions_name_the_route_with_the_configured_host_and_point_from_get_file(backend, public_url, base):
    """בתיאור ``codekeeper_get_file`` — רק ההפניה ל-``file_id`` (התיאור קרוב לתקרת תיאור כלי);
    בתיאור ``file_id`` ובתיאור ``codekeeper_list_versions`` — הפקודה, עם ``-f``, ב-host של
    השירות כשהוא ידוע, ו-``<mcp-host>`` כשלא או כשהוא נדחה."""
    import mcp_server.server as srv

    tools = srv.build_mcp(backend, public_url=public_url)._tool_manager
    get_file = tools.get_tool("codekeeper_get_file")
    assert "see file_id" in get_file.description
    assert "curl" not in get_file.description
    _command(get_file, base, param="file_id")
    _command(tools.get_tool("codekeeper_list_versions"), base, param=None)
    file_id_doc = get_file.parameters["properties"]["file_id"]["description"]
    # הכלל במשפט הראשון, בתוך 120 תווים: לקוח שמקצר תיאור פרמטר רואה רק אותו.
    first = file_id_doc.split(". ")[0]
    assert len(first) <= 120 and "codekeeper_list_versions" in first
    assert "hunter2" not in file_id_doc


# ---------------------------------------------------------------------------
# 4. נראות — בתהליך נקי
# ---------------------------------------------------------------------------


_DOWNLOAD_LOG_PROBE = SERVICE_LOGGING + """
from starlette.testclient import TestClient
from _mcp_apps import PatTokens, app_in_mode
from _save_layer_harness import install_fake_collections
from mcp_server.backend import ProductionBackend
from bson import ObjectId

class _MP:
    def setattr(self, obj, name, value):
        setattr(obj, name, value)

harness = install_fake_collections(_MP())
oid = ObjectId()
harness.code_snippets.docs.append({{
    "_id": oid, "user_id": 4242, "file_name": "p.py", "version": 3, "is_active": True,
    "code": {text!r}, "programming_language": "python",
}})
backend = ProductionBackend(db_manager=harness.dbm, mongo_db=harness.raw)
tokens = PatTokens({{"ckmcp_r": {{"user_id": 4242, "scopes": ["read"]}}}})
with TestClient(app_in_mode("pat", backend, tokens=tokens)) as client:
    ok = client.get("/api/agent/download", params={{"file_id": str(oid)}},
                    headers={{"authorization": "Bearer ckmcp_r"}})
    missing = client.get("/api/agent/download", params={{"file_id": "0123456789abcdef01234567"}},
                         headers={{"authorization": "Bearer ckmcp_r"}})
print("STATUS", ok.status_code, missing.status_code, flush=True)
print("FILE-ID", oid, flush=True)
print("PROBE-DONE", flush=True)
"""


def test_a_download_leaves_one_info_line_without_the_content_or_the_name(tmp_path):
    """השורה היא הנראות היחידה בייצור: PostHog אינו רואה ראוטים, וסירובים אינם נרשמים.

    התהליך רץ עם ``-B`` ו-``cwd=tmp_path``: שום ``__pycache__`` ושום קובץ לא נכתבים לעץ.
    """
    secret = "תוכן-פרטי-של-המשתמש"
    text = f"x = '{secret}'\n"
    script = textwrap.dedent(_DOWNLOAD_LOG_PROBE).format(repo=str(REPO), tests=str(REPO / "tests"), text=text)
    proc = subprocess.run(
        [sys.executable, "-B", "-c", script], capture_output=True, text=True, timeout=180,
        cwd=str(tmp_path), env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "ENVIRONMENT": "production"},
    )
    assert "PROBE-DONE" in proc.stdout and "STATUS 200 404" in proc.stdout, (
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    file_id = proc.stdout.split("FILE-ID ", 1)[1].split()[0]
    log = proc.stderr + proc.stdout.replace(f"FILE-ID {file_id}", "")

    lines = [line for line in log.splitlines() if "mcp download:" in line]
    assert len(lines) == 1, log
    size = len(text.encode("utf-8"))
    assert f"{size} bytes of file {file_id} (version 3) for user 4242" in lines[0], lines[0]
    assert "INFO" in lines[0].split("mcp download:", 1)[0], lines[0]
    assert secret not in log and "p.py" not in log


_URL_PROBE = SERVICE_LOGGING + """
from mcp_server import server as srv

class _B:
    pass

tools = srv.build_mcp(_B(), public_url={rejected!r})._tool_manager
get_file = tools.get_tool("codekeeper_get_file")
print("FILE-ID-DOC", get_file.parameters["properties"]["file_id"]["description"], flush=True)
print("LIST-DOC", tools.get_tool("codekeeper_list_versions").description, flush=True)
print("UPLOAD-DOC", tools.get_tool("codekeeper_save_file").parameters["properties"]["upload_id"]["description"], flush=True)
print("PROBE-DONE", flush=True)
"""


def test_a_rejected_url_leaves_one_warning_for_both_commands(tmp_path):
    """‏``MCP_SERVER_URL`` שנדחה — WARNING **אחד** בבניית הכלים, אף ששתי פקודות נבנות ממנו.

    מוטציה: כל ראוט בודק את הכתובת בעצמו (``public_base_for`` נקרא פעם לפקודת ההעלאה ופעם
    להורדה) — שתי שורות, והטסט נופל. ``MCP_SERVER_URL`` מוסר מהסביבה: ייבוא האפליקציה בונה
    את הכלים, וערך מהסביבה של מי שמריץ היה מוסיף שורה משלו.
    """
    rejected = "https://ops:hunter2@mcp.example.com"
    script = textwrap.dedent(_URL_PROBE).format(repo=str(REPO), tests=str(REPO / "tests"), rejected=rejected)
    env = {key: value for key, value in os.environ.items() if key != "MCP_SERVER_URL"}
    proc = subprocess.run(
        [sys.executable, "-B", "-c", script], capture_output=True, text=True, timeout=180,
        cwd=str(tmp_path), env={**env, "PYTHONDONTWRITEBYTECODE": "1", "ENVIRONMENT": "production"},
    )
    assert "SERVICE-LOGGING-READY" in proc.stdout and "PROBE-DONE" in proc.stdout, (
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    after_ready = proc.stdout.split("SERVICE-LOGGING-READY", 1)[1]
    for marker, path in (("FILE-ID-DOC", DOWNLOAD_PATH), ("LIST-DOC", DOWNLOAD_PATH), ("UPLOAD-DOC", UPLOAD_PATH)):
        doc = next(line for line in after_ready.splitlines() if line.startswith(marker))
        assert f"https://<mcp-host>{path}" in doc, doc

    log = proc.stderr + proc.stdout
    warnings = [line for line in log.splitlines() if "MCP_SERVER_URL not used" in line]
    assert len(warnings) == 1, log
    assert "carries a user name or password" in warnings[0]
    assert "hunter2" not in proc.stderr + proc.stdout
