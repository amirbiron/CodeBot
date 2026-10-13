"""התראת push על תגובת סוכן בשרשור — שולח האירועים של הוובאפ, מול מונגו אמיתי.

האירוע נכתב ל-``push_events`` **בדיוק כמו שה-MCP כותב אותו** (``nt.note_comment_push_event``), והשולח
האמיתי (``_send_due_events_once``) שולף, בונה ומסמן — מול המסד. רק המסירה עצמה (``pywebpush``)
מוחלפת בלוכדת. כך הטסט עובר דרך ההיטלה הקבועה של השולח: שדה שחסר בה מגיע לבונה כ-``None``, הבונה
מחזיר ``None``, והאירוע נסגר בלי שנשלח — ולכן ``test_an_agent_comment_is_sent_with_what_the_click_needs``
נופל כשמסירים מההיטלה את שדות האירוע.

הדילוג הוא ב-fixture ולא ב-``pytestmark`` (``bugbot-rules/import-time-side-effects.md`` §3), ורק על
"אין שרת" (``mongo_reachable``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("pymongo")
pytest.importorskip("flask")

from bson import ObjectId  # noqa: E402
from pymongo.errors import PyMongoError  # noqa: E402

from _note_threads_harness import insert_board, insert_note, mongo_reachable, temp_database  # noqa: E402

import note_threads as nt  # noqa: E402

USER = 7
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
LONG_BODY = (
    "מצאתי את המקור: גוף הפתק מקבל dir=\"rtl\" ברמת הקונטיינר, והירושה עוברת גם לבלוקי קוד. "
    "הוספתי dir=\"ltr\" ל-pre ול-code, ושמרתי יישור לימין לטקסט הרגיל. נשאר מקרה אחד."
)


@pytest.fixture(scope="module")
def _mongo():
    if not mongo_reachable():
        pytest.skip("דורש MONGODB_URL עם שרת מונגו נגיש")


@pytest.fixture
def db(_mongo):
    with temp_database("codebot_threads_push_it_") as database:
        yield database


class _Sender:
    """השולח האמיתי מעל המסד הזמני, עם מסירה שנלכדת במקום ``pywebpush``."""

    def __init__(self, monkeypatch: Any, db: Any) -> None:
        import webapp.push_api as push_api

        self.module = push_api
        self.db = db
        self.delivery_db = db
        self.sent: list[dict] = []
        monkeypatch.setattr(push_api, "get_db", lambda: db)
        monkeypatch.setattr(
            push_api, "_open_delivery",
            lambda uid: SimpleNamespace(db=self.delivery_db, subs=[{"endpoint": "https://push.test/e"}],
                                        endpoints_to_delete=set(), user_id=uid),
        )

        def _deliver(ctx: Any, payload: dict, *, idempotency_key: str = "") -> bool:
            self.sent.append(payload)
            return True

        monkeypatch.setattr(push_api, "_deliver_payload", _deliver)

    def run(self) -> list[dict]:
        self.module._send_due_events_once()
        return self.sent

    def events(self) -> list[dict]:
        return list(self.db.push_events.find({}).sort("_id", 1))


@pytest.fixture
def sender(monkeypatch, db):
    return _Sender(monkeypatch, db)


def _agent(client: Any = "claude-code") -> dict:
    return nt.agent_author(client=client, working_on="תיקון כיוון קוד")


def _comment_event(db: Any, *, title: str | None = "כיוון טקסט בבלוקי קוד", body: str = LONG_BODY,
                   author: Any = None, minutes: int = 0) -> tuple[str, str, str]:
    """פתק, שרשור עם תגובת סוכן, ואירוע ההתראה עליה — בדיוק כמו שה-MCP רושם אותו."""
    board = insert_board(db, USER)
    note = insert_note(db, USER, board_id=board, title=title)
    author = author or _agent()
    res = nt.create_thread(db[nt.NOTE_THREADS_COLLECTION], user_id=USER, note_id=note, author=author,
                           body=body, now=T0 + timedelta(minutes=minutes))
    assert res["ok"], res
    event_author = author if author["kind"] == nt.AUTHOR_AGENT else _agent()
    event = nt.note_comment_push_event(
        user_id=USER, note_id=note, thread_id=res["thread_id"], comment_id=res["comment_id"],
        author=event_author, target_ref={"target": "board", "board_id": board},
        now=T0 + timedelta(minutes=minutes),
    )
    db.push_events.insert_one(event)
    return note, res["thread_id"], res["comment_id"]


def test_an_agent_comment_is_sent_with_what_the_click_needs(sender, db):
    note, thread_id, _comment_id = _comment_event(db)
    sent = sender.run()
    assert len(sent) == 1, sent
    payload = sent[0]
    title = '💬 CC הגיב על "כיוון טקסט בבלוקי קוד"'
    body = payload["notification"]["body"]
    assert payload["notification"]["title"] == title
    assert body.startswith("מצאתי את המקור") and body.endswith("…"), body
    assert len(body) == sender.module._PUSH_COMMENT_PREVIEW_MAX_CHARS + 1, "קיצור בתווים, עם … אחד"
    assert payload["notification"]["actions"] == [], "בלי כפתורי תזכורת על תגובה"
    assert payload["notification"]["tag"] == f"note-thread-{thread_id}"
    assert payload["data"] == {
        "type": "note_comment", "note_id": note, "thread_id": thread_id,
        "file_id": "", "board_id": "", "title": title, "body": body,
    }
    [event] = sender.events()
    assert event["needs_push"] is False and event.get("sent_at") is not None, event


def test_a_note_without_a_title_is_named_generically(sender, db):
    _comment_event(db, title=None, body="קצר")
    [payload] = sender.run()
    assert payload["notification"]["title"] == "💬 CC הגיב על פתק"
    assert payload["notification"]["body"] == "קצר"


@pytest.mark.parametrize("client, label", [("Gemini", "Gemini"), ("Anthropic/ClaudeAI", "Claude"),
                                           ("Cursor", "Cursor"), (None, nt.UNKNOWN_AGENT_LABEL)])
def test_the_author_label_comes_from_the_module(sender, db, client, label):
    _comment_event(db, body="x", author=_agent(client))
    [payload] = sender.run()
    assert payload["notification"]["title"].startswith(f"💬 {label} הגיב")


def test_a_secret_in_the_comment_is_redacted_before_it_is_cut(sender, db):
    """K13: גוף ההתראה מוצג במסך הנעילה, וה-SW מדווח את תחילתו לשרת. הניקוי קודם לקיצור — טוקן
    שהיה נחתך קודם היה קצר מהדפוס, ומחציתו הייתה עוברת."""
    token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0" * 2
    _comment_event(db, body=("א" * 100) + " " + token)
    [payload] = sender.run()
    assert "ghp_" not in payload["notification"]["body"]
    assert "ghp_" not in payload["data"]["body"]
    assert "REDACTED" in payload["notification"]["body"]


@pytest.mark.parametrize("what", ["note_deleted", "thread_deleted", "not_an_agent", "other_note"])
def test_nothing_to_open_is_closed_without_sending(sender, db, what):
    note, thread_id, _ = _comment_event(db, author=nt.user_author() if what == "not_an_agent" else None)
    if what == "note_deleted":
        db.sticky_notes.delete_one({"_id": ObjectId(note)})
    elif what == "thread_deleted":
        db[nt.NOTE_THREADS_COLLECTION].delete_one({"_id": ObjectId(thread_id)})
    elif what == "other_note":
        # האירוע מצביע על שרשור של פתק אחר של אותו משתמש.
        db.push_events.update_one({}, {"$set": {"note_id": insert_note(db, USER, board_id=insert_board(db, USER))}})
    assert sender.run() == []
    [event] = sender.events()
    assert (event["needs_push"], event.get("skipped_reason")) == (False, "incomplete_event"), event


def test_one_batch_reads_notes_and_comments_once_not_per_event(sender, db):
    """R8: שלושה אירועים במנה — שאילתה אחת לשמות הפתקים ואחת לתגובות, ולא קריאה לכל אירוע."""
    for minutes in range(3):
        _comment_event(db, body=f"תגובה {minutes}", minutes=minutes)
    calls = {"notes_find": 0, "threads_aggregate": 0}

    class _Counting:
        def __init__(self, coll: Any, method: str, key: str) -> None:
            self._coll, self._method, self._key = coll, method, key

        def __getattr__(self, name: str) -> Any:
            attr = getattr(self._coll, name)
            if name != self._method:
                return attr

            def _counted(*args: Any, **kwargs: Any) -> Any:
                calls[self._key] += 1
                return attr(*args, **kwargs)

            return _counted

    class _CountingDb:
        def __init__(self, real: Any) -> None:
            self._real = real
            self.sticky_notes = _Counting(real.sticky_notes, "find", "notes_find")

        def __getitem__(self, name: str) -> Any:
            coll = self._real[name]
            return _Counting(coll, "aggregate", "threads_aggregate") if name == nt.NOTE_THREADS_COLLECTION else coll

        def __getattr__(self, name: str) -> Any:
            return getattr(self._real, name)

    sender.delivery_db = _CountingDb(db)
    assert len(sender.run()) == 3
    assert calls == {"notes_find": 1, "threads_aggregate": 1}, calls


def test_a_database_failure_while_preparing_leaves_the_events_pending(sender, db):
    """כשל קריאה חולף אינו סיבה לסגור אירוע — הסגירה היא מצב סופי. הם נשארים לסבב הבא."""
    _comment_event(db)

    class _Broken:
        def find(self, *args: Any, **kwargs: Any):
            raise PyMongoError("simulated")

    class _BrokenDb:
        def __init__(self, real: Any) -> None:
            self._real = real
            self.sticky_notes = _Broken()

        def __getitem__(self, name: str) -> Any:
            return self._real[name]

        def __getattr__(self, name: str) -> Any:
            return getattr(self._real, name)

    sender.delivery_db = _BrokenDb(db)
    assert sender.run() == []
    [event] = sender.events()
    assert event["needs_push"] is True and "skipped_reason" not in event, event


def test_the_projection_is_derived_from_what_the_builders_read():
    """ההיטלה נגזרת מההצהרות של הסוגים, כך שסוג חדש אינו יכול לשכוח את שדותיו."""
    import webapp.push_api as push_api

    projection = push_api._event_projection()
    for kind, spec in push_api._EVENT_KINDS.items():
        assert set(spec.fields) <= set(projection), kind
    assert {"note_id", "thread_id", "comment_id"} <= set(projection)
    assert {"_id", "user_id", "kind", "created_at", "attempts"} <= set(projection)


def test_a_file_saved_event_is_still_sent(sender, db):
    """רגרסיה: ``file_saved`` עובר עכשיו דרך הבורר החדש, באותה תוצאה."""
    db.push_events.insert_one({
        "user_id": USER, "kind": "file_saved", "file_name": "notes.md", "file_id": "f1", "created": True,
        "created_at": T0, "needs_push": True,
    })
    [payload] = sender.run()
    assert payload["notification"]["title"] == "📄 קובץ חדש נשמר"
    assert payload["data"]["type"] == "mcp_file_saved"
    assert payload["data"]["file_id"] == "f1"


def test_an_unknown_kind_is_still_closed_without_sending(sender, db):
    db.push_events.insert_one({"user_id": USER, "kind": "future_kind", "created_at": T0, "needs_push": True})
    assert sender.run() == []
    [event] = sender.events()
    assert (event["needs_push"], event.get("skipped_reason")) == (False, "unknown_kind")
