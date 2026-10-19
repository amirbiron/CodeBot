"""הצ'קליסט "צעדים ראשונים" בדשבורד (``webapp/first_steps.py``) — הבדיקות שרצות ב-CI.

**המסד הוא ``tests/_fake_mongo.FakeDB``, והנתונים נבנים דרך הכותבים האמיתיים**, ולא במסמכים
שנכתבים ביד: אוסף דרך ``CollectionsManager``, פתק דרך ``build_note_target`` (הבנאי שממנו
``create_board_note`` לוקח את שדות היעד), טוקן דרך ``MCPTokenStore`` ו-``OAuthStore``, וערכה
והסתרה דרך ``/api/ui_prefs`` ו-``/api/themes``. כך בדיקה של תנאי בודקת את השדה שהכותב באמת
כותב, ולא את מה שהטסט חשב שהוא כותב.

**הווידג'טים האחרים של הדשבורד מוחלפים בערכים קבועים** (כמו ב-``tests/test_admin_impersonation.py``),
כדי שמונה הקריאות יספור רק את מה ששייך לצ'קליסט: ציר הפעילות, כרטיס הפוש והפתקים האחרונים
קוראים מאותם אוספים. ובכל בקשה לדשבורד נבדק שהיא לא נפלה לדף השגיאה שלו — בלי זה, דמה
שחסר לה משהו מעבירה את הדשבורד לדף השגיאה, והטסטים ממשיכים לעבור על הכפתורים שב-``base.html``.

בדיקות הדפדפן של אותו פיצ'ר: ``tests/test_first_steps_browser.py``.
"""

from __future__ import annotations

import ast
import logging
import re
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pymongo.errors import (
    AutoReconnect,
    ConfigurationError,
    DuplicateKeyError,
    ExecutionTimeout,
    NetworkTimeout,
    NotPrimaryError,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeCollection, FakeDB

import mcp_server.oauth_store as oauth_store
import mcp_server.token_store as token_store
from database.collections_manager import WORKSPACE_COLLECTION_NAME, CollectionsManager
from mcp_server.oauth_store import ACCESS_PREFIX, REFRESH_PREFIX, OAuthStore, new_secret
from mcp_server.token_store import MCPTokenStore
from sticky_notes_target import build_note_target
from webapp import first_steps

REPO_ROOT = Path(__file__).resolve().parent.parent

#: משתמש רגיל (לא אדמין), כדי שהדשבורד לא יפנה לריפוים ולמראה של גיט.
USER_ID = 7

#: האוספים שהבדיקות של הצ'קליסט קוראות. מונה הקריאות סופר רק אותם.
CHECKLIST_COLLECTIONS = {"user_collections", "sticky_notes", "mcp_tokens", oauth_store.TOKENS_COLLECTION}

#: שגיאות המסד שמסמך המשתמש ושתי כתיבות העזר צריכים לבלוע. ``OperationFailure`` הוא המקרה מהשטח
#: (הרשאה שגויה), ו-``PyMongoError`` עצמו הוא העד לטענה "כל כשל של המסד": רק ``except PyMongoError``
#: תופס מופע של הבסיס, ולכן תפיסה צרה יותר — גם כזו שמוסיפה ``OperationFailure`` לניתוק — נופלת עליו.
AUXILIARY_DB_ERRORS = pytest.mark.parametrize(
    "db_error", [OperationFailure, PyMongoError], ids=["OperationFailure", "PyMongoError"],
)


class _Collection(FakeCollection):
    """``FakeCollection`` עם ``aggregate`` של אוסף ריק — הדשבורד מריץ שניים על ``code_snippets``.

    על אוסף שיש בו מסמכים הוא נכשל, ולא מחזיר תשובה שאינה נכונה.
    """

    def aggregate(self, pipeline, *args, **kwargs):
        if self.docs:
            raise NotImplementedError("aggregate על אוסף שיש בו מסמכים אינו ממודל כאן")
        return iter([])


class _Counted:
    """עוטף אוסף ורושם כל קריאה למתודה שלו, לפי שם האוסף."""

    def __init__(self, coll, name, calls):
        self._coll = coll
        self._name = name
        self._calls = calls

    def __getattr__(self, attr):
        target = getattr(self._coll, attr)
        if not callable(target):
            return target

        def _recorded(*args, **kwargs):
            self._calls.append((self._name, attr))
            return target(*args, **kwargs)

        return _recorded


class _CountingDB(FakeDB):
    """``FakeDB`` שסופר קריאות. ``db.c[name]`` הוא האוסף עצמו, בלי ספירה, לבנייה ולקריאה חוזרת."""

    def __init__(self):
        super().__init__()
        self.calls: list[tuple[str, str]] = []

    def __getitem__(self, name):
        return _Counted(self.c.setdefault(name, _Collection()), name, self.calls)

    def checklist_calls(self):
        return [call for call in self.calls if call[0] in CHECKLIST_COLLECTIONS]


def _raw(db, name):
    """האוסף עצמו, בלי ספירה — לבנייה, לקריאה חוזרת ולהחלפת מתודה בכשל."""
    return db.c.setdefault(name, _Collection())


def _user_doc(db, user_id=USER_ID):
    return _raw(db, "users").find_one({"user_id": user_id}) or {}


def _card(db, user_doc=None, *, device_theme="", user_id=USER_ID):
    """``build_card`` כמו שהדשבורד קורא לו, עם ``_stored_theme_pref`` האמיתי."""
    import webapp.app as app_mod

    doc = _user_doc(db, user_id) if user_doc is None else user_doc
    return first_steps.build_card(
        db,
        user_id,
        doc,
        stored_theme=app_mod._stored_theme_pref(doc),
        device_theme=device_theme,
    )


def _states(card):
    return {step["key"]: step["state"] for step in card["steps"]}


@pytest.fixture
def db(monkeypatch):
    import webapp.app as app_mod

    fake = _CountingDB()
    monkeypatch.setattr(app_mod, "get_db", lambda: fake)
    return fake


@pytest.fixture
def client(db, monkeypatch):
    """הוובאפ האמיתי מול ``db``, עם session של ``USER_ID`` ובלי הווידג'טים שאינם הצ'קליסט."""
    import webapp.app as app_mod

    monkeypatch.setattr(app_mod.app, "testing", True)
    monkeypatch.setitem(app_mod.app.config, "SECRET_KEY", "first-steps-tests")
    monkeypatch.setattr(app_mod, "_build_activity_timeline", lambda *_a, **_k: {
        "groups": [], "feed": [], "filters": [], "compact_limit": 0, "has_events": False, "updated_at": "",
    })
    monkeypatch.setattr(app_mod, "_build_push_card", lambda *_a, **_k: {
        "feature_enabled": False, "subscriptions": 0, "status_text": "", "status_variant": "",
        "pending_count": 0, "last_push": None, "next_reminder": None, "cta_href": "", "cta_label": "",
    })
    monkeypatch.setattr(app_mod, "_build_notes_snapshot", lambda *_a, **_k: {
        "notes": [], "total": 0, "has_notes": False,
    })
    monkeypatch.setattr(app_mod, "_load_whats_new", lambda *_a, **_k: {
        "features": [], "has_features": False, "total": 0,
    })
    monkeypatch.setattr(app_mod, "_get_active_dismissals", lambda *_a, **_k: [])
    monkeypatch.setattr(app_mod, "_build_files_need_attention", lambda *_a, **_k: {
        "missing_metadata": [], "stale_files": [], "total_missing": 0, "total_stale": 0,
        "shown_missing": 0, "shown_stale": 0, "has_items": False,
        "settings": {"stale_days": 60, "max_items": 10},
    })
    monkeypatch.setattr(app_mod, "user_stats", types.SimpleNamespace(
        get_all_time_stats=lambda: {"total_users": 1, "active_today": 1, "active_week": 1},
        get_weekly_stats=lambda: [],
    ))
    with app_mod.app.test_client() as test_client:
        with test_client.session_transaction() as sess:
            sess["user_id"] = USER_ID
            sess["user_data"] = {"id": USER_ID, "first_name": "Test"}
        yield test_client


@pytest.fixture
def dashboard(client, caplog):
    """``GET /dashboard`` שנכשל אם הדשבורד נפל לדף השגיאה שלו."""

    def _get():
        # בלי ``caplog.at_level`` כאן: הוא קובע גם את הרמה של ה-handler, ובדיקה שמחכה ל-WARNING
        # מתוך הבקשה הייתה מאבדת אותו. ``logger.exception`` הוא ERROR, ונתפס גם בלעדיו.
        caplog.clear()
        resp = client.get("/dashboard")
        assert resp.status_code == 200, resp.status_code
        assert not [r for r in caplog.records if r.getMessage() == "Error in dashboard"], (
            "הדשבורד נפל לדף השגיאה שלו — כנראה דמה שחסרה לה מתודה"
        )
        return resp.get_data(as_text=True)

    return _get


def _post_prefs(client, payload):
    return client.post("/api/ui_prefs", json=payload)


# --- כל צעד: לא מסומן, ואחרי שהכותב האמיתי רץ — מסומן --------------------------------------


def test_a_new_user_gets_every_step_unchecked(db):
    card = _card(db)
    assert [step["key"] for step in card["steps"]] == list(first_steps.STEP_KEYS)
    assert set(_states(card).values()) == {False}
    assert card["done_count"] == 0
    assert card["total"] == len(first_steps.STEPS)


def test_the_theme_step_counts_a_choice_saved_for_every_device(client, db):
    assert _states(_card(db))[first_steps.STEP_THEME] is False

    assert _post_prefs(client, {"theme": "dark"}).status_code == 200

    assert _user_doc(db)["ui_prefs"]["theme"] == "dark"
    assert _states(_card(db))[first_steps.STEP_THEME] is True


def test_the_theme_step_counts_a_device_only_choice_on_every_device(client, db):
    """ערכה "רק במכשיר הזה" לא נכתבת למסד — אבל נרשם שנבחרה, ולכן גם מכשיר בלי ה-cookie מסמן."""
    resp = _post_prefs(client, {"theme": "dark", "theme_scope": "device"})
    assert resp.status_code == 200

    prefs = _user_doc(db)["ui_prefs"]
    assert "theme" not in prefs, prefs
    assert prefs[first_steps.DEVICE_THEME_CHOSEN_PREF] is True
    # מכשיר אחר: אין cookie של ערכה, ובכל זאת הצעד מסומן.
    assert _states(_card(db, device_theme=""))[first_steps.STEP_THEME] is True


def test_the_theme_step_counts_the_device_cookie_on_its_own_device(db):
    """בחירה "רק במכשיר הזה" שנעשתה לפני הרישום: במכשיר שלה היא מסמנת לפי ה-cookie."""
    assert _states(_card(db, device_theme="dark"))[first_steps.STEP_THEME] is True


def test_the_collection_step_ignores_the_workspace_collection(db):
    mgr = CollectionsManager(db)
    assert mgr.ensure_default_collections(USER_ID) is True
    assert _raw(db, "user_collections").find_one({"name": WORKSPACE_COLLECTION_NAME})
    assert _states(_card(db))[first_steps.STEP_COLLECTION] is False

    created = mgr.create_collection(user_id=USER_ID, name="Roadmap")
    assert created["ok"], created
    assert _states(_card(db))[first_steps.STEP_COLLECTION] is True


def test_a_deleted_collection_stops_counting_and_an_archived_one_still_counts(db):
    mgr = CollectionsManager(db)
    created = mgr.create_collection(user_id=USER_ID, name="Roadmap")
    collection_id = created["collection"]["id"]

    assert mgr.update_collection(USER_ID, collection_id, is_archived=True)["ok"]
    assert _states(_card(db))[first_steps.STEP_COLLECTION] is True

    assert mgr.delete_collection(USER_ID, collection_id)["ok"]
    assert _states(_card(db))[first_steps.STEP_COLLECTION] is False


def test_the_note_step_counts_a_board_note_and_not_a_file_note(db):
    _raw(db, "sticky_notes").insert_one({"user_id": USER_ID, "content": "x", **build_note_target(file_id="f1")})
    assert _states(_card(db))[first_steps.STEP_NOTE] is False

    _raw(db, "sticky_notes").insert_one({"user_id": USER_ID, "content": "y", **build_note_target(board_id="b1")})
    assert _states(_card(db))[first_steps.STEP_NOTE] is True


def test_another_users_board_note_does_not_count(db):
    _raw(db, "sticky_notes").insert_one({"user_id": USER_ID + 1, "content": "y", **build_note_target(board_id="b1")})
    assert _states(_card(db))[first_steps.STEP_NOTE] is False


def test_the_ai_step_counts_a_personal_token_until_it_is_revoked(db):
    store = MCPTokenStore(db)
    store.issue(USER_ID)
    assert _states(_card(db))[first_steps.STEP_AI] is True

    # ``FakeCollection`` נותן ``_id`` מספרי, ולכן ``revoke`` מקבל אותו ולא מחרוזת.
    token_id = _raw(db, "mcp_tokens").docs[0]["_id"]
    assert store.revoke(USER_ID, token_id) is True
    assert _states(_card(db))[first_steps.STEP_AI] is False


def test_the_ai_step_counts_an_oauth_connection_until_it_is_revoked(db):
    store = OAuthStore(db)
    token = new_secret(ACCESS_PREFIX)
    store.save_token(token, kind="access", data={"client_id": "c1", "subject": str(USER_ID)})
    assert _states(_card(db))[first_steps.STEP_AI] is True

    assert store.revoke_token(token) is True
    assert _states(_card(db))[first_steps.STEP_AI] is False


def test_an_expired_token_does_not_count(db, monkeypatch):
    MCPTokenStore(db).issue(USER_ID, ttl_days=1)
    OAuthStore(db).save_token(new_secret(REFRESH_PREFIX), kind="refresh", data={"subject": str(USER_ID)})
    assert _states(_card(db))[first_steps.STEP_AI] is True

    later = datetime.now(UTC) + timedelta(days=60)
    monkeypatch.setattr(token_store, "_now", lambda: later)
    monkeypatch.setattr(oauth_store, "_now", lambda: later)
    assert _states(_card(db))[first_steps.STEP_AI] is False


# --- הכלל של "חיבור פעיל" הוא הכלל של השרת עצמו -----------------------------------------------


@pytest.mark.parametrize("case", ["no_expiry", "future_expiry", "expired", "expires_this_instant", "revoked"])
def test_the_personal_token_rule_agrees_with_verify(case, monkeypatch):
    """טוקן שמכניס לשרת הוא טוקן שנספר, ולהפך — ``user_has_live_token`` מול ``verify``.

    ``verify`` מחיל את ``_is_expired`` בפייתון, ו-``user_has_live_token`` שואל את השרת עם
    ``_not_expired_condition`` — אותו כלל בשתי שפות, והטסט מחזיק אותם לתשובה אחת. הרגע עצמו של
    ``expires_at`` עוד אינו "פג" בשניהם: ``$lte`` בתנאי היה מפיל את הטוקן כאן ולא ב-``verify``.
    """
    frozen = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(token_store, "_now", lambda: frozen)
    db = FakeDB()
    store = MCPTokenStore(db)
    raw = store.issue(USER_ID, ttl_days=None if case == "no_expiry" else 1)
    doc = _raw(db, "mcp_tokens").docs[0]
    if case == "expired":
        doc["expires_at"] = frozen - timedelta(seconds=1)
    elif case == "expires_this_instant":
        doc["expires_at"] = frozen
    elif case == "revoked":
        assert store.revoke(USER_ID, doc["_id"]) is True

    accepted = store.verify(raw) is not None
    assert token_store.user_has_live_token(db, USER_ID) is accepted
    assert accepted is (case in {"no_expiry", "future_expiry", "expires_this_instant"})


@pytest.mark.parametrize("kind", ["access", "refresh"])
@pytest.mark.parametrize("case", ["live", "revoked", "expired", "expires_this_instant"])
def test_the_oauth_rule_agrees_with_get_token(kind, case, monkeypatch):
    """``subject_has_live_token`` מול ``get_token``, כולל הרגע עצמו של ``expires_at``.

    ``expires_at >= now`` בשאילתה ו-``_expired`` (``<``) צריכים להסכים בדיוק ברגע הזה — עם ``>``
    בשאילתה הטוקן היה עובד בשרת ולא נספר כאן.
    """
    frozen = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(oauth_store, "_now", lambda: frozen)
    db = FakeDB()
    store = OAuthStore(db)
    raw = new_secret(ACCESS_PREFIX if kind == "access" else REFRESH_PREFIX)
    store.save_token(raw, kind=kind, data={"client_id": "c1", "subject": str(USER_ID)})
    doc = _raw(db, oauth_store.TOKENS_COLLECTION).docs[0]
    if case == "revoked":
        assert store.revoke_token(raw) is True
    elif case == "expired":
        doc["expires_at"] = frozen - timedelta(seconds=1)
    elif case == "expires_this_instant":
        doc["expires_at"] = frozen

    works = store.get_token(raw, kind=kind) is not None
    assert oauth_store.subject_has_live_token(db, str(USER_ID)) is works
    assert works is (case in {"live", "expires_this_instant"})


def test_the_oauth_answer_is_the_token_that_expires_last(monkeypatch):
    """מהשרת חוזר מסמך אחד — הטוקן שתוקפו נגמר אחרון — ו-``_expired`` מכריע עליו.

    השעון זז בין השאילתה (``expires_at >= now``) לבין ``_expired``, כמו בשרת אמיתי. טוקן A עובר את
    השאילתה ופג לפני ש-``_expired`` רץ, וטוקן B חי. בלי המיון חוזר A, שנכתב ראשון, והתשובה "אין
    חיבור" שגויה; עם המיון חוזר B. ואם גם B היה פג — פגו כולם, כי אף אחד לא פג אחריו.
    """
    t0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(oauth_store, "_now", lambda: t0)
    db = FakeDB()
    store = OAuthStore(db)
    for _ in range(2):
        store.save_token(new_secret(ACCESS_PREFIX), kind="access", data={"client_id": "c1", "subject": str(USER_ID)})
    first, second = _raw(db, oauth_store.TOKENS_COLLECTION).docs
    first["expires_at"] = t0 + timedelta(milliseconds=500)

    def moving_clock():
        ticks = [t0, t0 + timedelta(seconds=1)]
        return lambda: ticks.pop(0) if len(ticks) > 1 else ticks[0]

    monkeypatch.setattr(oauth_store, "_now", moving_clock())
    assert oauth_store.subject_has_live_token(db, str(USER_ID)) is True

    second["expires_at"] = t0 + timedelta(milliseconds=600)
    monkeypatch.setattr(oauth_store, "_now", moving_clock())
    assert oauth_store.subject_has_live_token(db, str(USER_ID)) is False


def test_each_connection_check_asks_the_server_for_one_document(db):
    """"יש לפחות אחד" — מסמך אחד מהשרת, ולא מעבר בקוד על כל הטוקנים של המשתמש.

    דמה לא מראה כמה מסמכים השרת קורא, ולכן כאן נבדק שכל אוסף נשאל ב-``find_one`` בלבד. המדידה
    עצמה, מול mongod אמיתי, ב-``tests/test_first_steps_mongo.py``.
    """
    assert _states(_card(db))[first_steps.STEP_AI] is False
    for name in ("mcp_tokens", oauth_store.TOKENS_COLLECTION):
        methods = {method for collection, method in db.checklist_calls() if collection == name}
        assert methods == {"find_one"}, (name, methods)


# --- נעילה ---------------------------------------------------------------------------------------


def _complete_every_step(db):
    """כל ארבעת הצעדים, דרך הכותבים האמיתיים. הערכה עוברת ב-``ui_prefs.theme``."""
    _raw(db, "users").update_one({"user_id": USER_ID}, {"$set": {"ui_prefs.theme": "dark"}}, upsert=True)
    assert CollectionsManager(db).create_collection(user_id=USER_ID, name="Roadmap")["ok"]
    _raw(db, "sticky_notes").insert_one({"user_id": USER_ID, "content": "y", **build_note_target(board_id="b1")})
    MCPTokenStore(db).issue(USER_ID)


def test_finishing_every_step_saves_the_lock_and_hides_the_card(db):
    _complete_every_step(db)

    assert _card(db) is None
    assert _user_doc(db)["ui_prefs"][first_steps.DONE_PREF] is True


@AUXILIARY_DB_ERRORS
def test_a_database_error_while_saving_the_lock_does_not_stop_the_page(db, caplog, db_error):
    """הנעילה היא עזר: כל כשל של המסד בה נרשם, הכרטיס לא מוצג (כל הצעדים בוצעו), ובטעינה הבאה ינסו שוב."""
    _complete_every_step(db)
    _failing(db, "users", "update_one", db_error("the database failed"))

    with caplog.at_level(logging.WARNING, logger="webapp.first_steps"):
        assert _card(db) is None
    assert first_steps.DONE_PREF not in _user_doc(db)["ui_prefs"]
    assert [r for r in caplog.records if "lock was not saved" in r.getMessage() and r.exc_info]


def test_a_bug_while_saving_the_lock_surfaces(db):
    _complete_every_step(db)
    _failing(db, "users", "update_one", TypeError("a bug"))
    with pytest.raises(TypeError):
        _card(db)


def test_after_the_lock_the_dashboard_runs_no_checklist_query(dashboard, db):
    """"בטעינה הבאה של הדשבורד לא רצה אף שאילתה של הצ'קליסט" — ומחיקת האוספים לא מחזירה אותו."""
    _complete_every_step(db)
    html = dashboard()
    assert 'id="firstSteps"' not in html
    assert _user_doc(db)["ui_prefs"][first_steps.DONE_PREF] is True

    db.calls.clear()
    html = dashboard()
    assert 'id="firstSteps"' not in html
    assert db.checklist_calls() == []

    mgr = CollectionsManager(db)
    for doc in list(_raw(db, "user_collections").docs):
        assert mgr.delete_collection(USER_ID, str(doc["_id"]))["ok"]
    assert not [d for d in _raw(db, "user_collections").docs if d["is_active"]]
    db.calls.clear()
    assert 'id="firstSteps"' not in dashboard()
    assert db.checklist_calls() == []


def test_the_lock_is_not_saved_while_a_step_is_still_open(db):
    _raw(db, "users").update_one({"user_id": USER_ID}, {"$set": {"ui_prefs.theme": "dark"}}, upsert=True)
    card = _card(db)
    assert card is not None and card["done_count"] == 1
    assert first_steps.DONE_PREF not in _user_doc(db)["ui_prefs"]


def test_the_lock_is_not_written_over_a_show_again(db, caplog):
    """"הצג שוב" שנוחת בין שליפת מסמך המשתמש לכתיבת הנעילה מנצח, כי התנאי יושב בכתיבה עצמה.

    הקריאה הישירה ל-``_write_lock`` היא המרוץ עצמו: ההחלטה לנעול כבר התקבלה על מסמך ישן, ובמסד
    המשתמש כבר ביקש לראות את הכרטיס. וגם לא נוצר מסמך שני למשתמש, כמו ש-``upsert`` היה יוצר כאן.
    """
    _raw(db, "users").insert_one({"user_id": USER_ID, "ui_prefs": {first_steps.HIDDEN_PREF: False}})

    with caplog.at_level(logging.INFO, logger="webapp.first_steps"):
        first_steps._write_lock(db, USER_ID)

    docs = list(_raw(db, "users").find({"user_id": USER_ID}))
    assert len(docs) == 1, docs
    assert first_steps.DONE_PREF not in docs[0]["ui_prefs"], docs[0]
    assert [r for r in caplog.records if r.getMessage().startswith("first steps: the lock was not written")]


def test_without_a_user_document_the_lock_creates_nothing(db, caplog):
    """בלי ``upsert``: הנעילה לא יוצרת מסמך משתמש (את זה עושה הכניסה), והבדיקות ירוצו שוב בטעינה הבאה."""
    with caplog.at_level(logging.INFO, logger="webapp.first_steps"):
        first_steps._write_lock(db, USER_ID)

    assert _raw(db, "users").find_one({"user_id": USER_ID}) is None
    assert [r for r in caplog.records if r.getMessage().startswith("first steps: the lock was not written")]


# --- כשל במסד: "לא ידוע כרגע" ולא "לא בוצע" ----------------------------------------------------


def _failing(db, collection, method, exc):
    def _raise(*_a, **_k):
        raise exc

    setattr(_raw(db, collection), method, _raise)


def test_a_check_that_could_not_reach_the_database_is_unknown_and_blocks_the_lock(db, caplog):
    _complete_every_step(db)
    _failing(db, "sticky_notes", "find_one", ServerSelectionTimeoutError("no primary"))

    with caplog.at_level(logging.WARNING, logger="webapp.first_steps"):
        card = _card(db)

    assert card is not None, "צעד שלא נבדק אינו בוצע — ואין נעילה על סמך בדיקה שלא רצה"
    assert _states(card)[first_steps.STEP_NOTE] is None
    assert card["done_count"] == 3
    assert first_steps.DONE_PREF not in _user_doc(db)["ui_prefs"]
    assert [r for r in caplog.records if first_steps.STEP_NOTE in r.getMessage() and r.exc_info]


def test_a_database_error_that_is_not_an_outage_surfaces(db):
    """``OperationFailure`` — הרשאה, שאילתה פגומה — אינו "לא ידוע". הוא עולה (R10)."""
    _failing(db, "user_collections", "find_one", OperationFailure("bad query"))
    with pytest.raises(OperationFailure):
        _card(db)


def test_a_live_oauth_connection_answers_even_when_the_token_check_failed(db):
    OAuthStore(db).save_token(new_secret(ACCESS_PREFIX), kind="access", data={"subject": str(USER_ID)})
    _failing(db, "mcp_tokens", "find_one", AutoReconnect("connection reset"))
    assert _states(_card(db))[first_steps.STEP_AI] is True


def test_no_ai_connection_found_and_one_check_failed_is_unknown(db):
    _failing(db, "mcp_tokens", "find_one", AutoReconnect("connection reset"))
    assert _states(_card(db))[first_steps.STEP_AI] is None


@pytest.mark.parametrize(
    "exc, caught",
    [
        (ServerSelectionTimeoutError("x"), True),
        (AutoReconnect("x"), True),
        (NetworkTimeout("x"), True),
        (NotPrimaryError("x"), True),
        (ExecutionTimeout("x"), True),
        (OperationFailure("x"), False),
        (DuplicateKeyError("x"), False),
        (ConfigurationError("x"), False),
    ],
)
def test_only_an_outage_counts_as_the_database_not_answering(exc, caught):
    """מקבע את החלוקה של ``DB_UNAVAILABLE_ERRORS`` מול ``pymongo`` המותקן — שדרוג שמזיז מחלקה נופל כאן."""
    assert isinstance(exc, first_steps.DB_UNAVAILABLE_ERRORS) is caught


# --- הסתרה ו"הצג שוב" — דרך ``/api/ui_prefs``, הנתיב שהכפתורים שולחים אליו ------------------


def test_hiding_is_saved_on_the_server_and_stops_the_checks(client, dashboard, db):
    assert 'id="firstSteps"' in dashboard()

    resp = _post_prefs(client, {first_steps.HIDDEN_PREF: True})
    assert resp.status_code == 200 and resp.get_json()["ok"] is True
    assert _user_doc(db)["ui_prefs"][first_steps.HIDDEN_PREF] is True

    db.calls.clear()
    assert 'id="firstSteps"' not in dashboard()
    assert db.checklist_calls() == []


def test_show_again_saves_the_request_lifts_the_lock_and_the_checks_run_again(client, dashboard, db):
    _raw(db, "users").update_one(
        {"user_id": USER_ID},
        {"$set": {f"ui_prefs.{first_steps.HIDDEN_PREF}": True, f"ui_prefs.{first_steps.DONE_PREF}": True}},
        upsert=True,
    )
    assert 'id="firstSteps"' not in dashboard()

    resp = _post_prefs(client, {first_steps.HIDDEN_PREF: False})
    assert resp.status_code == 200 and resp.get_json()["ok"] is True
    prefs = _user_doc(db).get("ui_prefs") or {}
    # ``False`` נשמר כמו שנשלח, כי הוא הבקשה לראות את הכרטיס; הנעילה נמחקת.
    assert prefs.get(first_steps.HIDDEN_PREF) is False and first_steps.DONE_PREF not in prefs, prefs

    db.calls.clear()
    assert 'id="firstSteps"' in dashboard()
    assert db.checklist_calls(), "אחרי \"הצג שוב\" הבדיקות רצות שוב"


def test_after_show_again_a_finished_user_sees_the_whole_card_on_every_load(client, dashboard, db):
    """מי שסיים הכל ולחץ "הצג שוב" רואה את הכרטיס מלא, וגם בטעינה הבאה: הנעילה לא נכתבת עליו."""
    _complete_every_step(db)
    assert 'id="firstSteps"' not in dashboard(), "בלי \"הצג שוב\" הכרטיס ננעל, כמו קודם"
    assert _user_doc(db)["ui_prefs"][first_steps.DONE_PREF] is True

    assert _post_prefs(client, {first_steps.HIDDEN_PREF: False}).get_json()["ok"] is True

    total = len(first_steps.STEPS)
    for _ in range(2):
        html = dashboard()
        assert re.search(rf'data-testid="first-steps-count">\s*{total} מתוך {total}\s*<', html)
        assert html.count('data-testid="first-step-done"') == total
        assert 'id="firstStepsHide"' in html
    prefs = _user_doc(db)["ui_prefs"]
    assert first_steps.DONE_PREF not in prefs and prefs[first_steps.HIDDEN_PREF] is False, prefs


def test_hiding_again_after_show_again_stops_every_check(client, dashboard, db):
    _complete_every_step(db)
    _raw(db, "users").update_one({"user_id": USER_ID}, {"$set": {f"ui_prefs.{first_steps.HIDDEN_PREF}": False}})
    assert 'id="firstSteps"' in dashboard()

    assert _post_prefs(client, {first_steps.HIDDEN_PREF: True}).get_json()["ok"] is True
    db.calls.clear()
    assert 'id="firstSteps"' not in dashboard()
    assert db.checklist_calls() == []


@pytest.mark.parametrize(
    "prefs",
    [{}, {first_steps.HIDDEN_PREF: None}, {first_steps.HIDDEN_PREF: True}, {first_steps.HIDDEN_PREF: False},
     {first_steps.HIDDEN_PREF: "false"}, {first_steps.HIDDEN_PREF: ""}],
    ids=["missing", "none", "true", "false", "string_false", "empty_string"],
)
def test_asking_to_see_again_and_its_query_condition_agree(db, prefs):
    """``asked_to_see_again`` ו-``_NOT_ASKED_TO_SEE_AGAIN`` הם אותו כלל, בפייתון וכתנאי שאילתה.

    כאן על הדמה. ``0`` ומערכים נבדקים מול mongod ב-``tests/test_first_steps_mongo.py``: הדמה משווה
    בפייתון, שבו ``0 == False``.
    """
    doc = {"user_id": USER_ID, "ui_prefs": prefs}
    _raw(db, "users").insert_one(dict(doc))
    lockable = _raw(db, "users").find_one({"user_id": USER_ID, **first_steps._NOT_ASKED_TO_SEE_AGAIN}) is not None
    assert lockable is not first_steps.asked_to_see_again(doc)


@pytest.mark.parametrize("value", ["false", 0, 1, None, "true"])
def test_a_hidden_value_that_is_not_a_boolean_is_rejected(client, db, value):
    resp = _post_prefs(client, {first_steps.HIDDEN_PREF: value})
    assert resp.status_code == 400
    assert not _user_doc(db), "ערך שנדחה לא נכתב"


# --- מסמך המשתמש: שליפה אחת לבקשה, ו-None כשהמסד לא ענה --------------------------------------


def test_the_dashboard_fetches_the_user_document_once_per_request(dashboard, db):
    db.calls.clear()
    dashboard()
    assert db.calls.count(("users", "find_one")) == 1, db.calls


def test_when_the_user_document_did_not_load_there_is_no_card_and_no_check(dashboard, db, caplog):
    """משתמש שהסתיר לא יראה את הכרטיס חוזר בגלל תקלה: בלי מסמך — בלי כרטיס ובלי בדיקות."""
    _failing(db, "users", "find_one", ServerSelectionTimeoutError("no primary"))
    db.calls.clear()
    with caplog.at_level(logging.WARNING, logger="webapp.app"):
        html = dashboard()
    assert 'id="firstSteps"' not in html
    assert db.checklist_calls() == []
    assert [r for r in caplog.records if r.getMessage() == "user document fetch failed" and r.exc_info]


@AUXILIARY_DB_ERRORS
def test_any_database_error_on_the_user_document_gives_none(client, db, caplog, db_error):
    """לא רק ניתוק: גם הרשאה שגויה נותנת ``None``. כל הקוראים מתייחסים ל-``None`` כברירות מחדל
    בטוחות, ולפני הצ'קליסט ``inject_globals`` בלע את אותה שגיאה בכל דף."""
    import webapp.app as app_mod

    _failing(db, "users", "find_one", db_error("the database failed"))
    with app_mod.app.test_request_context("/dashboard"), caplog.at_level(logging.WARNING, logger="webapp.app"):
        assert app_mod._request_user_doc(USER_ID) is None
    assert [r for r in caplog.records if r.getMessage() == "user document fetch failed" and r.exc_info]


def test_a_bug_while_fetching_the_user_document_surfaces(client, db):
    """חריגה שאינה של המסד היא באג, ולא "המסמך לא נטען" (R10)."""
    import webapp.app as app_mod

    _failing(db, "users", "find_one", TypeError("a bug"))
    with app_mod.app.test_request_context("/dashboard"):
        with pytest.raises(TypeError):
            app_mod._request_user_doc(USER_ID)


def test_a_database_error_on_the_user_document_does_not_take_down_the_pages(client, dashboard, db):
    """הכרטיס והקישור "הצג שוב" הם תוספות. כשמסמך המשתמש לא נטען, ההגדרות והדשבורד נטענים בלעדיהם —
    כמו לפני שנוספו — ולא נופלים לדף שגיאה. הפיקסצ'ר ``dashboard`` בודק שהדשבורד לא עבר לדף השגיאה שלו."""
    _raw(db, "users").update_one(
        {"user_id": USER_ID}, {"$set": {f"ui_prefs.{first_steps.HIDDEN_PREF}": True}}, upsert=True,
    )
    _failing(db, "users", "find_one", OperationFailure("not authorized"))

    resp = client.get("/settings")
    assert resp.status_code == 200
    assert 'id="firstStepsShowAgain"' not in resp.get_data(as_text=True)

    assert 'id="firstSteps"' not in dashboard()


# --- מה הדשבורד מרנדר -----------------------------------------------------------------------------


def test_the_card_renders_the_steps_closed_with_their_texts_and_targets(dashboard, db):
    html = dashboard()
    assert "dashboard-grid" in html and "has-first-steps" in html
    assert "🚀 ברוכים הבאים! בואו נתחיל" in html
    assert "השלם את הצעדים הבאים כדי להוציא את המקסימום מ-CodeKeeper." in html
    assert re.search(r'data-testid="first-steps-count">\s*0 מתוך 4\s*<', html)
    assert html.count('data-testid="first-step-todo"') == len(first_steps.STEPS)
    assert "<details open" not in html, "כל הצעדים סגורים"
    for step in first_steps.STEPS:
        assert f'id="first-step-{step["key"]}"' in html
        assert f'href="{step["action_href"]}"' in html
    # Jinja מקודד את המירכאות בטקסט (``&#34;``), והדפדפן מציג אותן כרגיל.
    assert "&#34;האוספים שלי&#34;" in html
    assert "CodeKeeper: ידע שנשמר גם אחרי שהחיבור נגמר" in html
    assert 'id="firstStepsHide"' in html


def test_the_hint_under_the_hide_button_says_where_the_card_comes_back(dashboard, db):
    html = dashboard()
    hint = re.search(r'<p class="first-steps-hide-hint" id="(?P<id>[^"]+)">(?P<text>[^<]*)</p>', html)
    assert hint and hint["text"] == "אפשר להחזיר את הכרטיס מתחתית עמוד ההגדרות", hint
    assert re.search(rf'id="firstStepsHide"[^>]*aria-describedby="{hint["id"]}"', html), "הכפתור מקושר לשורה"


def test_the_counter_comes_from_the_same_states_as_the_checks(dashboard, db):
    CollectionsManager(db).create_collection(user_id=USER_ID, name="Roadmap")
    _raw(db, "sticky_notes").insert_one({"user_id": USER_ID, "content": "y", **build_note_target(board_id="b1")})

    html = dashboard()
    assert re.search(r'data-testid="first-steps-count">\s*2 מתוך 4\s*<', html)
    assert html.count('data-testid="first-step-done"') == 2
    assert re.search(r'id="first-step-collection"\s+data-testid="first-step-done"', html)
    assert re.search(r'id="first-step-note"\s+data-testid="first-step-done"', html)


def test_the_device_cookie_marks_the_theme_step_on_the_dashboard(client, dashboard, db):
    client.set_cookie("ui_theme", "dark")
    client.set_cookie("ui_theme_scope", "device")
    assert re.search(r'id="first-step-theme"\s+data-testid="first-step-done"', dashboard())


# --- עמוד ההגדרות --------------------------------------------------------------------------------


def test_settings_shows_show_again_only_when_the_checklist_is_dismissed(client, db):
    html = client.get("/settings").get_data(as_text=True)
    assert 'id="firstStepsShowAgain"' not in html

    _raw(db, "users").update_one(
        {"user_id": USER_ID}, {"$set": {f"ui_prefs.{first_steps.HIDDEN_PREF}": True}}, upsert=True,
    )
    html = client.get("/settings").get_data(as_text=True)
    assert 'id="firstStepsShowAgain"' in html
    assert "הצג שוב את הצעדים הראשונים" in html

    # אחרי "הצג שוב" הכרטיס מוצג בדשבורד, ולכן כאן אין מה להחזיר.
    _raw(db, "users").update_one({"user_id": USER_ID}, {"$set": {f"ui_prefs.{first_steps.HIDDEN_PREF}": False}})
    html = client.get("/settings").get_data(as_text=True)
    assert 'id="firstStepsShowAgain"' not in html


def test_show_again_sits_at_the_bottom_of_settings(client, db):
    """השורה בכרטיס, "אפשר להחזיר את הכרטיס מתחתית עמוד ההגדרות", מתארת את המקום הזה: אחרי כל
    כרטיסי ההגדרות ולפני קישור העזרה. מי שמזיז את הכפתור נופל כאן, ומשנה גם את השורה."""
    _raw(db, "users").update_one(
        {"user_id": USER_ID}, {"$set": {f"ui_prefs.{first_steps.HIDDEN_PREF}": True}}, upsert=True,
    )
    html = client.get("/settings").get_data(as_text=True)
    button = html.index('id="firstStepsShowAgain"')
    help_link = html.index('class="settings-help-link"')
    cards = [m.start() for m in re.finditer(r'class="[^"]*\bglass-card\b', html[:help_link])]
    assert cards and cards[-1] < button < help_link, (cards[-1:], button, help_link)


def test_settings_has_the_theme_anchor_and_the_closed_agent_examples(client, db):
    html = client.get("/settings").get_data(as_text=True)
    assert re.search(r'<div\s+class="glass-card"\s+id="appearance"', html), "היעד של \"לבחירת ערכה\""
    assert html.count('id="appearance"') == 1
    examples = html.split('<details class="ai-connect__examples">', 1)
    assert len(examples) == 2, "הבלוק \"מה אפשר לבקש מהסוכן\" חסר, או שהוא נפתח מראש"
    block = examples[1].split("</details>", 1)[0]
    assert "מה אפשר לבקש מהסוכן" in block
    for example in (
        "תיצור פתק בלוח שלי עם המשימות שסיכמנו",
        "תמצא את הקובץ שבו טיפלנו בבאג של התאריכים",
        "תסכם את ה-Roadmap שבאוסף שלי ותגיד מה עוד פתוח",
        "תשמור את הסקריפט הזה כקובץ חדש, עם תיאור",
    ):
        assert example in block
    # הבלוק בתוך "חיבור סוכן AI", ואחרי הלשוניות.
    section = html.split('id="ai-connect"', 1)[1].split('id="agent-instructions-section"', 1)[0]
    assert section.index('role="tablist"') < section.index("ai-connect__examples")


# --- "לוח העבודה": ‏/boards/default --------------------------------------------------------------


def test_the_default_board_link_routes_to_its_own_view():
    """Werkzeug בודק קטע סטטי לפני קטע עם משתנה — ``default`` אינו נבלע ב-``/boards/<board_id>``."""
    import webapp.app as app_mod

    adapter = app_mod.app.url_map.bind("localhost")
    assert adapter.match("/boards/default")[0] == "boards_ui.default_board_page"
    assert adapter.match("/boards/0123456789abcdef01234567")[0] == "boards_ui.board_page"


def test_the_default_board_link_creates_the_board_and_redirects_to_it(client, db):
    resp = client.get("/boards/default")
    assert resp.status_code == 302
    boards = [d for d in _raw(db, "note_boards").docs if d.get("user_id") == USER_ID and d.get("is_default")]
    assert len(boards) == 1
    assert resp.headers["Location"].endswith(f"/boards/{boards[0]['_id']}")

    again = client.get("/boards/default")
    assert again.headers["Location"] == resp.headers["Location"]
    assert len([d for d in _raw(db, "note_boards").docs if d.get("is_default")]) == 1


def test_the_default_board_link_goes_to_the_list_when_the_database_did_not_answer(client, db):
    _failing(db, "note_boards", "find_one", ServerSelectionTimeoutError("no primary"))
    resp = client.get("/boards/default")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/boards")


def test_the_default_board_link_requires_login(db):
    import webapp.app as app_mod

    with app_mod.app.test_client() as anonymous:
        resp = anonymous.get("/boards/default")
    assert resp.status_code == 302
    assert "/login?next=/boards/default" in resp.headers["Location"]


# --- ערכה "רק במכשיר הזה": כל כותב רושם, וטסט מבני שמוצא כותב חדש --------------------------------


def _device_choice_recorded(db, user_id=USER_ID):
    prefs = (_user_doc(db, user_id).get("ui_prefs") or {})
    return prefs.get(first_steps.DEVICE_THEME_CHOSEN_PREF) is True


#: הכותבים שמחילים ערכה במצב ``device``, והפונקציה של כל אחד. ``test_every_writer_of_the_theme_cookie_records_a_device_choice``
#: מוודא שאלה בדיוק הכותבים שבקוד, ולכן כותב חדש נכנס גם לכאן — ומקבל את הבדיקות ההתנהגותיות.
DEVICE_THEME_WRITERS = {
    "ui_prefs": "webapp/app.py:api_ui_prefs",
    "shared_apply": "webapp/themes_api.py:apply_shared_theme",
    "activate": "webapp/themes_api.py:activate_theme_endpoint",
}


def _apply_device_theme(client, db, writer):
    """מחיל ערכה "רק במכשיר הזה" דרך הכותב ``writer`` (מפתח ב-:data:`DEVICE_THEME_WRITERS`), ומחזיר את התשובה."""
    if writer == "ui_prefs":
        return _post_prefs(client, {"theme": "ocean", "theme_scope": "device"})
    if writer == "shared_apply":
        _raw(db, "shared_themes").insert_one({"_id": "cyber", "name": "Cyber", "is_active": True, "colors": {}})
        return client.post("/api/themes/shared/cyber/apply", json={"theme_scope": "device"})
    users = _raw(db, "users")
    original_find_one = users.find_one

    def _find_one(query=None, projection=None, *a, **k):
        # ``custom_themes.id`` הוא שאילתה על מערך, ש-``FakeCollection`` אינו ממדל.
        if isinstance(query, dict) and "custom_themes.id" in query:
            return {"custom_themes": [{"id": query["custom_themes.id"], "name": "Mine", "is_active": False}]}
        return original_find_one(query, projection, *a, **k)

    users.find_one = _find_one
    return client.post("/api/themes/t1/activate", json={"theme_scope": "device"})


def _failing_device_record(db, exc):
    """רק הכתיבה של ``record_device_theme_choice`` נכשלת; שאר הכתיבות למסמך המשתמש עוברות."""
    users = _raw(db, "users")
    original_update_one = users.update_one

    def _update_one(query, update, *a, **k):
        if f"ui_prefs.{first_steps.DEVICE_THEME_CHOSEN_PREF}" in (update.get("$set") or {}):
            raise exc
        return original_update_one(query, update, *a, **k)

    users.update_one = _update_one


@pytest.mark.parametrize("writer", list(DEVICE_THEME_WRITERS))
def test_each_device_theme_writer_records_the_choice(client, db, writer):
    resp = _apply_device_theme(client, db, writer)
    assert resp.status_code == 200 and resp.get_json()["ok"] is True
    assert "ui_theme_scope=device" in " ".join(resp.headers.getlist("Set-Cookie"))
    assert "theme" not in (_user_doc(db).get("ui_prefs") or {}), "במצב device הערכה עצמה לא נכתבת למסד"
    assert _device_choice_recorded(db)


@AUXILIARY_DB_ERRORS
@pytest.mark.parametrize("writer", list(DEVICE_THEME_WRITERS))
def test_a_database_error_while_recording_does_not_undo_the_theme(client, db, writer, caplog, db_error):
    """הרישום משרת רק את הצ'קליסט: כשהמסד נכשל בו, הערכה עדיין מוחלת — 200, וה-cookie בתשובה."""
    _failing_device_record(db, db_error("the database failed"))
    with caplog.at_level(logging.WARNING, logger="webapp.first_steps"):
        resp = _apply_device_theme(client, db, writer)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert "ui_theme_scope=device" in " ".join(resp.headers.getlist("Set-Cookie"))
    assert not _device_choice_recorded(db)
    assert [r for r in caplog.records if "device theme choice not recorded" in r.getMessage() and r.exc_info]


def test_a_bug_while_recording_a_device_choice_surfaces(db):
    _failing(db, "users", "update_one", TypeError("a bug"))
    with pytest.raises(TypeError):
        first_steps.record_device_theme_choice(db, USER_ID)


def test_ui_prefs_does_not_record_a_rejected_device_theme_request(client, db):
    """בקשה שנדחתה (400) לא החילה ערכה, ולכן גם לא נרשמת בחירה."""
    resp = _post_prefs(client, {"theme": "ocean", "theme_scope": "device", first_steps.HIDDEN_PREF: "no"})
    assert resp.status_code == 400
    assert not _device_choice_recorded(db)


def _calls_named(func_node, name):
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name) and target.id == name:
                return True
            if isinstance(target, ast.Attribute) and target.attr == name:
                return True
    return False


def _sets_theme_cookie(func_node):
    """קורא ל-``set_cookie`` שהארגומנט הראשון שלו הוא ``"ui_theme"`` או ``"ui_theme_scope"``."""
    for node in ast.walk(func_node):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "set_cookie"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in {"ui_theme", "ui_theme_scope"}
        ):
            return True
    return False


def test_every_writer_of_the_theme_cookie_records_a_device_choice():
    """כל פונקציה ב-``webapp/`` שכותבת את ה-cookie של הערכה — ישירות, או דרך
    ``_set_theme_scope_cookies`` — קוראת ל-``record_device_theme_choice``.

    הסריקה עוברת על כל קבצי ``webapp/``, ולא על רשימת כותבים ידועה: כותב חדש בלי הרישום ייפול
    כאן, וכותב חדש שלא נכנס ל-:data:`DEVICE_THEME_WRITERS` ייפול גם הוא. מה שהסריקה **לא** בודקת
    הוא שהקריאה באמת רצה בענף של ``device`` — את זה בודקות הבדיקות ההתנהגותיות שלמעלה, שרצות
    על כל כותב ב-:data:`DEVICE_THEME_WRITERS`, מול המסד.
    """
    helper = "_set_theme_scope_cookies"
    writers, missing = [], []
    for path in sorted((REPO_ROOT / "webapp").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name == helper:
                continue
            if _sets_theme_cookie(node) or _calls_named(node, helper):
                where = f"{path.relative_to(REPO_ROOT)}:{node.name}"
                writers.append(where)
                if not _calls_named(node, "record_device_theme_choice"):
                    missing.append(where)
    assert sorted(writers) == sorted(DEVICE_THEME_WRITERS.values()), (
        "כותב חדש של ה-cookie של הערכה צריך להיכנס ל-DEVICE_THEME_WRITERS, כדי שיקבל את הבדיקות ההתנהגותיות",
        writers,
    )
    assert missing == [], f"כותבים של ה-cookie של הערכה שלא רושמים בחירה במכשיר: {missing}"


# --- ייבוא -----------------------------------------------------------------------------------------


def test_first_steps_imports_nothing_from_the_database_package_at_module_level():
    """``webapp/app.py`` מייבא את המודול ברמת המודול, ו-``database`` בונה ``DatabaseManager`` בזמן
    ייבוא — ייבוא ממנה כאן היה מפיל את ``import webapp.app`` בסביבה בלי ``MONGODB_URL``."""
    tree = ast.parse((REPO_ROOT / "webapp" / "first_steps.py").read_text(encoding="utf-8"))

    def _module_level_imports(nodes):
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                yield node
            elif isinstance(node, (ast.If, ast.Try)):
                for block in (getattr(node, "body", []), getattr(node, "orelse", []),
                              getattr(node, "finalbody", []),
                              *[h.body for h in getattr(node, "handlers", [])]):
                    yield from _module_level_imports(block)

    offenders = []
    for node in _module_level_imports(tree.body):
        names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
        offenders += [n for n in names if n == "database" or n.startswith("database.")]
    assert offenders == []
