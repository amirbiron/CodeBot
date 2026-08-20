"""טסטים ל-``GET /api/agent/primer`` (mcp_server/primer.py).

מכסה את ארבעת האילוצים של האנדפוינט: אימות, תקרת 24KB, cache של 60 שניות,
וסינון סודות — וגם את מקרי הקצה של הגוף (204 בהוראות ריקות, אין שורת מצב
כשאין קבצים).
"""

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("starlette")

from starlette.applications import Starlette  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from mcp_server.primer import (  # noqa: E402
    MAX_BYTES,
    MAX_STATUS_BYTES,
    WARN_BYTES,
    PrimerCache,
    agent_primer_route,
    build_primer,
    build_status_line,
    redact_secrets,
)

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)
_SEP_MARK = "---"


class _FakeStore:
    """token store בסגנון ``MCPTokenStore`` — אותו חוזה ``verify``."""

    def __init__(self, mapping):
        self.mapping = mapping

    def verify(self, token):
        return self.mapping.get(token)


class _FakeBackend:
    def __init__(self, instructions="", files=None):
        self.instructions = instructions
        self.files = files or []
        self.instruction_calls = 0
        self.file_calls = 0

    def get_agent_instructions(self, user_id):
        self.instruction_calls += 1
        if isinstance(self.instructions, dict):
            return self.instructions.get(int(user_id), "")
        return self.instructions

    def recent_files(self, user_id, *, limit=3):
        self.file_calls += 1
        if isinstance(self.files, dict):
            return self.files.get(int(user_id), [])[:limit]
        return self.files[:limit]


def _client(backend, *, store=None, cache=None):
    store = store or _FakeStore({"good": {"user_id": 7, "scopes": ["read"]}})
    app = Starlette(
        routes=[agent_primer_route(backend, token_store=store, cache=cache or PrimerCache())]
    )
    return TestClient(app)


def _auth(token="good"):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- אימות
def test_no_token_returns_401():
    resp = _client(_FakeBackend("שלום")).get("/api/agent/primer")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate", "").startswith("Bearer")


def test_bad_token_returns_401():
    resp = _client(_FakeBackend("שלום")).get("/api/agent/primer", headers=_auth("nope"))
    assert resp.status_code == 401


def test_non_bearer_scheme_returns_401():
    resp = _client(_FakeBackend("שלום")).get(
        "/api/agent/primer", headers={"Authorization": "Basic good"}
    )
    assert resp.status_code == 401


def test_unauthenticated_request_never_touches_the_backend():
    """401 חייב לחסום *לפני* כל קריאה לנתונים — לא רק להסתיר את הפלט."""
    backend = _FakeBackend("סודי")
    resp = _client(backend).get("/api/agent/primer")
    assert resp.status_code == 401
    assert backend.instruction_calls == 0
    assert b"\xd7\xa1\xd7\x95\xd7\x93\xd7\x99" not in resp.content


def test_valid_token_returns_plain_text():
    backend = _FakeBackend("תמיד תענה בעברית.")
    resp = _client(backend).get("/api/agent/primer", headers=_auth())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "charset=utf-8" in resp.headers["content-type"].lower()
    assert "תמיד תענה בעברית." in resp.text


def test_response_is_not_json():
    """הגוף נקרא ע"י הסוכן כפי שהוא — עטיפת JSON תהפוך אותו לרעש."""
    resp = _client(_FakeBackend("כלל")).get("/api/agent/primer", headers=_auth())
    assert "json" not in resp.headers["content-type"].lower()
    assert not resp.text.lstrip().startswith(("{", "["))


def test_oauth_provider_path_authenticates_too():
    """במצב OAuth הראוט מאמת דרך load_access_token — אותו נתיב של טרנספורט ה-MCP."""

    class _Token:
        subject = "7"
        scopes = ["read"]

    class _Provider:
        async def load_access_token(self, token):
            return _Token() if token == "ckoat_ok" else None

    app = Starlette(
        routes=[
            agent_primer_route(_FakeBackend("שלום"), auth_provider=_Provider(), cache=PrimerCache())
        ]
    )
    client = TestClient(app)
    assert client.get("/api/agent/primer", headers=_auth("ckoat_ok")).status_code == 200
    assert client.get("/api/agent/primer", headers=_auth("bad")).status_code == 401


# ---------------------------------------------------------------- 204
def test_empty_instructions_return_204_not_empty_200():
    backend = _FakeBackend("", files=[{"file_name": "a.py", "saved_at": NOW}])
    resp = _client(backend).get("/api/agent/primer", headers=_auth())
    assert resp.status_code == 204
    assert resp.content == b""


def test_whitespace_only_instructions_return_204():
    resp = _client(_FakeBackend("   \n\n\t  ")).get("/api/agent/primer", headers=_auth())
    assert resp.status_code == 204


def test_no_instructions_skips_the_recent_files_query():
    """204 לא אמור לשלם על שאילתה שהתוצאה שלה לא תוגש."""
    backend = _FakeBackend("")
    _client(backend).get("/api/agent/primer", headers=_auth())
    assert backend.file_calls == 0


# ---------------------------------------------------------------- שורת מצב
def test_status_line_lists_three_files_with_times():
    files = [
        {"file_name": "app.py", "saved_at": NOW - timedelta(hours=3)},
        {"file_name": "utils.js", "saved_at": NOW - timedelta(days=1)},
        {"file_name": "README.md", "saved_at": NOW - timedelta(minutes=5)},
    ]
    line = build_status_line(files, now=NOW)
    assert "app.py (לפני 3 שעות)" in line
    assert "utils.js (אתמול)" in line
    assert "README.md (לפני 5 דקות)" in line
    assert line.count("\n") == 0  # שורה אחת, "לא יותר מזה"


def test_no_files_means_no_status_line_at_all():
    """יש הוראות, אין קבצים ⇒ 200 עם ההוראות בלבד.

    שורת מצב ריקה עדיפה על שורת מצב שמדווחת על כלום.
    """
    backend = _FakeBackend("כלל יחיד.", files=[])
    resp = _client(backend).get("/api/agent/primer", headers=_auth())
    assert resp.status_code == 200
    assert resp.text.strip() == "כלל יחיד."
    assert "---" not in resp.text
    assert "קבצים אחרונים" not in resp.text


def test_status_line_survives_a_missing_timestamp():
    line = build_status_line([{"file_name": "x.py", "saved_at": None}], now=NOW)
    assert "x.py" in line


def test_naive_timestamps_are_treated_as_utc():
    """Mongo עשוי להחזיר datetime בלי tzinfo — אסור שזה יפיל את השורה."""
    naive = (NOW - timedelta(hours=2)).replace(tzinfo=None)
    line = build_status_line([{"file_name": "x.py", "saved_at": naive}], now=NOW)
    assert "לפני 2 שעות" in line


def test_recent_files_failure_still_serves_the_instructions():
    """שורת המצב היא תוספת; כישלון שלה לא מוחק את עיקר התוכן."""

    class _Broken(_FakeBackend):
        def recent_files(self, user_id, *, limit=3):
            raise RuntimeError("mongo down")

    resp = _client(_Broken("ההוראות שלי")).get("/api/agent/primer", headers=_auth())
    assert resp.status_code == 200
    assert "ההוראות שלי" in resp.text


# --------------------------------------------------------------- תקרת 24KB
def test_oversized_primer_is_truncated_not_rejected():
    backend = _FakeBackend("א" * 20000, files=[{"file_name": "a.py", "saved_at": NOW}])
    resp = _client(backend).get("/api/agent/primer", headers=_auth())
    assert resp.status_code == 200  # לעולם לא שגיאה
    assert len(resp.content) <= MAX_BYTES
    assert "נחתך" in resp.text


def test_truncation_keeps_the_status_line():
    """הוראות ארוכות לא דוחפות את שורת המצב מחוץ לגוף."""
    body = build_primer("א" * 20000, [{"file_name": "a.py", "saved_at": NOW}], now=NOW)
    assert len(body.encode("utf-8")) <= MAX_BYTES
    assert "קבצים אחרונים" in body
    assert "a.py" in body


def test_truncation_does_not_split_a_utf8_character():
    """חיתוך נאיבי על בייטים היה מוציא תו עברי חצוי ובייטים לא-תקינים."""
    body = build_primer("ש" * 9000, [], now=NOW)
    raw = body.encode("utf-8")
    assert len(raw) <= MAX_BYTES
    assert raw.decode("utf-8") == body  # רק אם כל תו שלם


def test_body_exactly_under_the_cap_is_not_truncated():
    body = build_primer("a" * 100, [], now=NOW)
    assert "נחתך" not in body
    assert body.startswith("a" * 100)


# ---------------------------------------------------------------- cache
def test_second_request_is_served_from_cache():
    backend = _FakeBackend("שלום")
    client = _client(backend)
    client.get("/api/agent/primer", headers=_auth())
    client.get("/api/agent/primer", headers=_auth())
    assert backend.instruction_calls == 1


def test_cache_control_header_is_private_and_60s():
    resp = _client(_FakeBackend("שלום")).get("/api/agent/primer", headers=_auth())
    assert resp.headers["cache-control"] == "private, max-age=60"


def test_204_also_carries_the_cache_header():
    resp = _client(_FakeBackend("")).get("/api/agent/primer", headers=_auth())
    assert resp.status_code == 204
    assert resp.headers["cache-control"] == "private, max-age=60"


def test_expired_cache_entry_is_refetched():
    cache = PrimerCache(ttl_seconds=0)
    backend = _FakeBackend("שלום")
    client = _client(backend, cache=cache)
    client.get("/api/agent/primer", headers=_auth())
    client.get("/api/agent/primer", headers=_auth())
    assert backend.instruction_calls == 2


def test_cache_is_per_user_and_never_leaks_across_users():
    """הבאג המסוכן ביותר ב-cache: להגיש פריימר של משתמש אחד למשתמש אחר."""
    store = _FakeStore(
        {
            "tok-a": {"user_id": 1, "scopes": ["read"]},
            "tok-b": {"user_id": 2, "scopes": ["read"]},
        }
    )
    backend = _FakeBackend({1: "הסודות של אלף", 2: "הסודות של בית"})
    client = _client(backend, store=store)

    first = client.get("/api/agent/primer", headers=_auth("tok-a"))
    second = client.get("/api/agent/primer", headers=_auth("tok-b"))

    assert "הסודות של אלף" in first.text
    assert "הסודות של בית" in second.text
    assert "אלף" not in second.text


def test_cache_evicts_when_over_capacity():
    cache = PrimerCache(ttl_seconds=300, max_entries=3)
    for uid in range(10):
        cache.put(uid, f"body-{uid}")
    assert len(cache._data) <= 3


# ---------------------------------------------------------------- סינון סודות
#
# הדוגמאות מורכבות בזמן ריצה מקידומת + גוף ולא נכתבות כמחרוזת שלמה: קובץ טסט
# שמכיל מחרוזת בצורת מפתח אמיתי נתפס ע"י סורקי הסודות (וגם ע"י push protection
# של GitHub) ומעורר התראה על סוד שלא קיים. הערכים סינתטיים לחלוטין.
_FILLER = "AbCdEfGhIjKlMnOpQrStUvWxYz012345"
_ALPHA = "abcdefghijklmnopqrstuvwxyz0123456789"

SECRET_SHAPES = [
    ("ghp_", _ALPHA),
    ("github_pat_", "11ABCDEFG0abcdefghij_ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    ("ckmcp_", _FILLER),
    ("ckoat_", _FILLER),
    ("sk-ant-api03-", _FILLER),
    ("AKIA", "IOSFODNN7EXAMPLE"),
    ("xoxb-", "123456789012-1234567890123-" + _FILLER),
    ("AIza", "SyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7"),
    ("eyJhbGciOiJIUzI1NiJ9.", "eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w"),
]


@pytest.mark.parametrize("prefix,body", SECRET_SHAPES)
def test_known_secret_shapes_are_redacted(prefix, body):
    secret = prefix + body
    out = redact_secrets(f"ההקשר שלי:\n{secret}\nסוף")
    assert secret not in out
    assert "REDACTED" in out


def test_env_style_assignments_are_redacted():
    text = (
        "OPENAI_API_KEY=sk-verysecretvalue1234567890\n"
        "DB_PASSWORD: hunter2hunter2\n"
        "export MY_TOKEN=abc123def456"
    )
    out = redact_secrets(text)
    assert "hunter2hunter2" not in out
    assert "abc123def456" not in out
    assert "sk-verysecretvalue1234567890" not in out


def test_bearer_header_pasted_as_text_is_redacted():
    out = redact_secrets("Authorization: Bearer abcdef1234567890xyz")
    assert "abcdef1234567890xyz" not in out


def test_connection_string_password_is_redacted():
    uri = "mongo" + "db://admin:" + "supersecretpw" + "@cluster0.example.net/db"
    out = redact_secrets(uri)
    assert "supersecretpw" not in out


def test_private_key_block_is_redacted():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----"
    out = redact_secrets(text)
    assert "MIIEowIBAAKCAQEA" not in out


def test_secrets_pasted_into_the_field_never_reach_the_response():
    """המסלול המלא: מפתח שהודבק לשדה ההוראות לא יוצא בגוף התשובה."""
    secret = "ghp_" + _ALPHA
    backend = _FakeBackend(f"השתמש במפתח {secret} בבקשה")
    resp = _client(backend).get("/api/agent/primer", headers=_auth())
    assert resp.status_code == 200
    assert secret not in resp.text
    assert "REDACTED" in resp.text


def test_ordinary_text_is_left_alone():
    """הסינון לא אמור לפגוע בטקסט רגיל — פריימר מושחת גרוע מפריימר לא מסונן."""
    text = "תמיד תענה בעברית.\nהפרויקט נמצא ב-webapp/app.py ומשתמש ב-Flask.\nkey=value זה בסדר."
    assert redact_secrets(text) == text


@pytest.mark.parametrize(
    "line",
    [
        "API_KEY=<your-key-here>",
        "OPENAI_API_KEY=${OPENAI_API_KEY}",
        "MY_TOKEN=$SOME_ENV_VAR",
        "DB_PASSWORD=...",
        "key=value",
        "SECRET_KEY={{ secret }}",
    ],
)
def test_placeholders_and_env_references_are_not_redacted(line):
    """הוראות מלאות דוגמאות קונפיג — placeholder הוא לא סוד ואסור למחוק אותו."""
    assert redact_secrets(line) == line


# ---------------------------------------------------------------- סנכרון בין השירותים
def test_webapp_limits_match_the_primer_limits():
    """הוובאפ ושירות ה-MCP נפרדים ואין ביניהם ייבוא — הערכים משוכפלים.

    הטסט הזה הוא מה שמונע מהם להתפצל בשקט: אם התקרה תשתנה בצד אחד בלבד, ה-UI
    יתריע על סף לא נכון והמשתמש יגלה חיתוך רק דרך שורה שרק הסוכן רואה.
    """
    flask = pytest.importorskip("flask")  # noqa: F841
    from webapp.routes.settings_routes import (
        AGENT_INSTRUCTIONS_MAX_CHARS,
        AGENT_INSTRUCTIONS_WARN_BYTES,
        AGENT_PRIMER_MAX_BYTES,
    )

    assert AGENT_PRIMER_MAX_BYTES == MAX_BYTES
    assert AGENT_INSTRUCTIONS_WARN_BYTES == WARN_BYTES
    assert WARN_BYTES < MAX_BYTES  # אחרת האזהרה מגיעה רק אחרי החריגה

    # האחסון רחב מההגשה — אינווריאנט מוצהר ב-``docs/mcp-server.rst``, שנועד
    # לכך שהמשתמש לא יאבד טקסט שכתב: החיתוך הוא החלטה של ההגשה ולא של
    # השמירה. ההשוואה היא תווים מול בייטים, ולכן המקרה הקובע הוא ASCII —
    # שם תו הוא בייט. בעברית תו הוא שני בייטים והמרווח גדול פי שניים.
    assert AGENT_INSTRUCTIONS_MAX_CHARS >= AGENT_PRIMER_MAX_BYTES


def test_the_truncation_notice_quotes_the_actual_cap():
    """הודעת החיתוך נגזרת מ-``MAX_BYTES`` ולא מוקלדת.

    ההודעה הזו היא הדבר היחיד שהסוכן רואה כשהפריימר נחתך, והיא מצטטת את
    התקרה במספר. כשהיא הייתה מוקלדת ("8KB"), שינוי התקרה היה משאיר אותה
    משקרת בשקט — בדיוק הדפוס של ערך משוכפל שמתפצל מהמקור.
    """
    from mcp_server.primer import _TRUNCATION_NOTICE

    assert f"{MAX_BYTES // 1024}KB" in _TRUNCATION_NOTICE


def test_204_is_cached_too():
    """גם "אין פריימר" הוא תשובה — אסור לה לפגוע במסד בכל פתיחת סשן."""
    backend = _FakeBackend("")
    client = _client(backend)
    assert client.get("/api/agent/primer", headers=_auth()).status_code == 204
    assert client.get("/api/agent/primer", headers=_auth()).status_code == 204
    assert backend.instruction_calls == 1


# ------------------------------------------------- רגרסיות מביקורת ה-PR
def test_status_line_is_redacted_too():
    """שמות קבצים הם קלט משתמש — קובץ ששמור בשם בצורת מפתח לא יוצא כמו שהוא.

    ה-docstring של המודול מבטיח סינון על כל הגוף; לפני התיקון הסינון רץ רק על
    שדה ההוראות, ושורת המצב עקפה אותו.
    """
    secret_name = "ghp_" + _ALPHA
    body = build_primer("כלל", [{"file_name": secret_name, "saved_at": NOW}], now=NOW)
    assert secret_name not in body
    assert "REDACTED" in body


def test_long_file_names_cannot_push_the_body_over_the_cap():
    """גם שמות הקבצים הם קלט משתמש — בלי תקרה לשורת המצב הגוף היה חורג."""
    files = [{"file_name": "x" * 5000, "saved_at": NOW} for _ in range(3)]
    body = build_primer("כלל קצר", files, now=NOW)
    assert len(body.encode("utf-8")) <= MAX_BYTES


def test_status_line_has_its_own_byte_cap():
    files = [{"file_name": "y" * 4000, "saved_at": NOW}]
    body = build_primer("כלל", files, now=NOW)
    status_part = body.split(_SEP_MARK, 1)[-1]
    assert len(status_part.encode("utf-8")) <= MAX_STATUS_BYTES + 16


@pytest.mark.parametrize("cap", [1, 16, 64, 200, 1000, MAX_BYTES])
def test_cap_is_never_exceeded_for_any_budget(cap):
    """החוזה נאכף על התוצאה עצמה, ולא נגזר מנכונות החישובים שמעליה."""
    files = [{"file_name": "z" * 900, "saved_at": NOW} for _ in range(3)]
    body = build_primer("א" * 9000, files, now=NOW, max_bytes=cap)
    assert len(body.encode("utf-8")) <= cap
    assert body.encode("utf-8").decode("utf-8") == body  # לא נשבר תו UTF-8


def test_one_minute_reads_as_singular():
    line = build_status_line(
        [{"file_name": "a.py", "saved_at": NOW - timedelta(seconds=100)}], now=NOW
    )
    assert "לפני דקה" in line
    assert "לפני 1 דקות" not in line


# ------------------------------------------------- נתיבי קצה שלא היו מכוסים
def test_future_timestamp_does_not_invent_a_future():
    """שעון שלא מסונכרן בין השירותים לא אמור להוציא "בעוד 3 שעות"."""
    line = build_status_line([{"file_name": "a.py", "saved_at": NOW + timedelta(hours=3)}], now=NOW)
    assert "לפני רגע" in line


def test_old_files_fall_back_to_a_date():
    """מעל חודש, "לפני 400 ימים" פחות שימושי מתאריך."""
    line = build_status_line(
        [{"file_name": "a.py", "saved_at": NOW - timedelta(days=120)}], now=NOW
    )
    assert "2026-04-09" in line


def test_blank_file_names_are_skipped_in_the_status_line():
    files = [
        {"file_name": "   ", "saved_at": NOW},
        {"file_name": "real.py", "saved_at": NOW},
    ]
    line = build_status_line(files, now=NOW)
    assert "real.py" in line
    assert line.count("(") == 1  # רק ערך אחד נכנס


def test_build_primer_returns_empty_for_blank_instructions():
    """הגנה כפולה: הקורא כבר מסנן, אבל הפונקציה עומדת בחוזה גם לבדה."""
    assert build_primer("", [{"file_name": "a.py", "saved_at": NOW}], now=NOW) == ""
    assert build_primer("   \n ", [], now=NOW) == ""


def test_cache_prunes_expired_entries_before_evicting_live_ones():
    """ניקוי הפגים קודם — כדי לא לזרוק ערך חי בזמן שיש מת בתור."""
    cache = PrimerCache(ttl_seconds=0, max_entries=2)
    cache.put(1, "old-1")
    cache.put(2, "old-2")
    cache.put(3, "fresh")  # דוחף ניקוי; שני הראשונים כבר פגו
    assert cache.get(1) is None
    assert len(cache._data) <= 2


def test_cache_clear_empties_everything():
    cache = PrimerCache(ttl_seconds=300)
    cache.put(1, "a")
    cache.clear()
    assert cache.get(1) is None
