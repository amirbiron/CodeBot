"""טסטים לשדה "הוראות לסוכן" בוובאפ (``/api/settings/agent-instructions``).

השדה הזה הוא עיקר התוכן של ``GET /api/agent/primer`` בשירות ה-MCP. שני
השירותים נפרדים אבל חולקים את אותו מסמך ``user_preferences``, ולכן החוזה החשוב
כאן הוא **טיפוס המפתח**: הוובאפ חייב לכתוב ``user_id`` כמספר, אחרת הפריימר פשוט
לא ימצא את המסמך.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("flask")

from flask import Flask  # noqa: E402

from webapp.routes import settings_routes  # noqa: E402
from webapp.routes.settings_routes import (  # noqa: E402
    AGENT_INSTRUCTIONS_MAX_CHARS,
    AGENT_PRIMER_MAX_BYTES,
    settings_bp,
)

# מפתח סשן לטסט בלבד — נבנה בזמן ריצה כדי שלא ייראה כמו ערך אמיתי לסורקי סודות
SECRET = "flask-session-for-" + "unit-tests-only"
ENDPOINT = "/api/settings/agent-instructions"


class _FakeColl:
    def __init__(self, doc=None):
        self.doc = doc
        self.calls = []

    def find_one(self, query, projection=None):
        self.calls.append(("find_one", query))
        return self.doc

    def update_one(self, query, update, upsert=False):
        self.calls.append(("update_one", query, update, upsert))
        self.doc = {**(self.doc or {}), **update["$set"]}
        return SimpleNamespace(modified_count=1)


class _FakeDb:
    def __init__(self, coll):
        self.user_preferences = coll


def _client(monkeypatch, coll, *, logged_in_as=7):
    monkeypatch.setattr(
        settings_routes,
        "_get_app_helpers",
        lambda: SimpleNamespace(get_db=lambda: _FakeDb(coll)),
    )
    app = Flask(__name__)
    app.secret_key = SECRET
    app.register_blueprint(settings_bp)
    client = app.test_client()
    if logged_in_as is not None:
        with client.session_transaction() as sess:
            sess["user_id"] = logged_in_as
    return client


# ------------------------------------------------------------------ אימות
def test_get_requires_login(monkeypatch):
    client = _client(monkeypatch, _FakeColl(), logged_in_as=None)
    assert client.get(ENDPOINT).status_code == 401


def test_put_requires_login(monkeypatch):
    client = _client(monkeypatch, _FakeColl(), logged_in_as=None)
    assert client.put(ENDPOINT, json={"text": "x"}).status_code == 401


# ------------------------------------------------------------------ קריאה
def test_get_returns_the_saved_text_and_the_ui_limits(monkeypatch):
    coll = _FakeColl({"agent_instructions": "תמיד בעברית"})
    resp = _client(monkeypatch, coll).get(ENDPOINT)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["text"] == "תמיד בעברית"
    # ה-UI מקבל את הספים מהשרת כדי שלא יתפצלו משני צדדים
    assert data["primer_max_bytes"] == AGENT_PRIMER_MAX_BYTES
    assert data["warn_bytes"] < AGENT_PRIMER_MAX_BYTES
    assert data["max_chars"] == AGENT_INSTRUCTIONS_MAX_CHARS


def test_get_on_a_user_with_no_preferences_returns_empty(monkeypatch):
    resp = _client(monkeypatch, _FakeColl(None)).get(ENDPOINT)
    assert resp.status_code == 200
    assert resp.get_json()["text"] == ""


# ------------------------------------------------------------------ כתיבה
def test_put_saves_the_text(monkeypatch):
    coll = _FakeColl()
    resp = _client(monkeypatch, coll).put(ENDPOINT, json={"text": "כלל אחד"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    op = [c for c in coll.calls if c[0] == "update_one"][0]
    assert op[2]["$set"]["agent_instructions"] == "כלל אחד"
    assert op[3] is True  # upsert — למשתמש חדש אין עדיין מסמך העדפות


def test_put_writes_user_id_as_an_int(monkeypatch):
    """החוזה בין השירותים: ה-MCP מחפש ``{"user_id": <int>}``.

    כתיבה עם מחרוזת הייתה יוצרת מסמך מקביל שהפריימר לעולם לא היה מוצא.
    """
    coll = _FakeColl()
    _client(monkeypatch, coll, logged_in_as="7").put(ENDPOINT, json={"text": "x"})
    op = [c for c in coll.calls if c[0] == "update_one"][0]
    assert op[1] == {"user_id": 7}
    assert isinstance(op[1]["user_id"], int)


def test_put_normalizes_crlf_and_trims(monkeypatch):
    """\\r\\n מדפדפן היה מנפח את הגודל ומזייף את מונה הבייטים ב-UI."""
    coll = _FakeColl()
    _client(monkeypatch, coll).put(ENDPOINT, json={"text": "  שורה\r\nשנייה  \n"})
    op = [c for c in coll.calls if c[0] == "update_one"][0]
    assert op[2]["$set"]["agent_instructions"] == "שורה\nשנייה"


def test_put_rejects_text_over_the_storage_cap(monkeypatch):
    coll = _FakeColl()
    resp = _client(monkeypatch, coll).put(
        ENDPOINT, json={"text": "א" * (AGENT_INSTRUCTIONS_MAX_CHARS + 1)}
    )
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert not [c for c in coll.calls if c[0] == "update_one"]  # לא נכתב כלום


def test_put_rejects_a_non_string_value(monkeypatch):
    resp = _client(monkeypatch, _FakeColl()).put(ENDPOINT, json={"text": 42})
    assert resp.status_code == 400


def test_put_rejects_a_missing_field(monkeypatch):
    resp = _client(monkeypatch, _FakeColl()).put(ENDPOINT, json={})
    assert resp.status_code == 400


def test_put_allows_clearing_the_field(monkeypatch):
    """מחיקת ההוראות היא פעולה לגיטימית — היא מחזירה את הפריימר ל-204."""
    coll = _FakeColl({"agent_instructions": "ישן"})
    resp = _client(monkeypatch, coll).put(ENDPOINT, json={"text": ""})
    assert resp.status_code == 200
    op = [c for c in coll.calls if c[0] == "update_one"][0]
    assert op[2]["$set"]["agent_instructions"] == ""


def test_put_flags_text_that_will_be_truncated(monkeypatch):
    """חידוד ה-UX: התראה בכתיבה, לא רק שורת חיתוך שרק הסוכן רואה."""
    coll = _FakeColl()
    resp = _client(monkeypatch, coll).put(
        ENDPOINT, json={"text": "a" * (AGENT_PRIMER_MAX_BYTES + 10)}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True  # נשמר בכל זאת — האחסון רחב מההגשה
    assert body["will_truncate"] is True


def test_put_does_not_flag_text_under_the_cap(monkeypatch):
    resp = _client(monkeypatch, _FakeColl()).put(ENDPOINT, json={"text": "קצר"})
    assert resp.get_json()["will_truncate"] is False


def test_put_reports_bytes_not_chars(monkeypatch):
    """עברית היא 2 בייטים לתו — מונה תווים היה מטעה מול תקרת בייטים."""
    resp = _client(monkeypatch, _FakeColl()).put(ENDPOINT, json={"text": "שלום"})
    assert resp.get_json()["bytes"] == len("שלום".encode()) == 8


def test_put_stores_secrets_verbatim(monkeypatch):
    """הסינון קורה בהגשה, לא באחסון.

    אם היינו מצנזרים כאן, המשתמש היה פותח את ההגדרות ומוצא ``***REDACTED***``
    במקום מה שכתב — בלי דרך לדעת מה נמחק לו.
    """
    coll = _FakeColl()
    secret = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"
    _client(monkeypatch, coll).put(ENDPOINT, json={"text": f"המפתח: {secret}"})
    op = [c for c in coll.calls if c[0] == "update_one"][0]
    assert secret in op[2]["$set"]["agent_instructions"]


def test_put_survives_a_db_error(monkeypatch):
    class _Boom:
        def update_one(self, *a, **k):
            raise RuntimeError("mongo down")

    resp = _client(monkeypatch, _Boom()).put(ENDPOINT, json={"text": "x"})
    assert resp.status_code == 500
    assert resp.get_json()["ok"] is False
