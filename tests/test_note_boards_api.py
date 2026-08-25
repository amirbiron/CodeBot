"""בדיקות ל-API של לוחות הפתקים ולראוטי פתקי הלוח.

התבנית: stub של אוסף בפייתון טהור, כמו ב-``tests/test_sticky_notes_api.py``.
היתרון המרכזי כאן הוא שאפשר לתאר מצבים שקשה לייצר מול מסד אמיתי — למשל
``update_many`` שמדווח הצלחה ולא מזיז כלום, שזה בדיוק המצב שהמחיקה חייבת
לשרוד בלי לאבד פתקים.
"""

import pytest

flask = pytest.importorskip("flask")


try:  # אותה תבנית ייבוא עמיד שבמודול הנבדק
    from pymongo.errors import DuplicateKeyError as _StubDuplicateKeyError
except Exception:  # pragma: no cover
    class _StubDuplicateKeyError(Exception):
        pass


class _Res:
    def __init__(self, inserted_id=None, modified_count=1, deleted_count=1):
        self.inserted_id = inserted_id
        self.modified_count = modified_count
        self.deleted_count = deleted_count


class _StubColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self._next = 1000
        self.count_fails = False
        self.move_is_noop = False
        #: מדמה את דחיית האינדקס הייחודי ``one_title_per_board``
        self.duplicate_titles = False

    # -- קריאה --
    def find_one(self, query, projection=None):
        for doc in self._matching(query):
            return doc
        return None

    def find(self, query, projection=None):
        return _Cursor(self._matching(query))

    def count_documents(self, query):
        if self.count_fails:
            raise RuntimeError("count failed")
        return len(self._matching(query))

    def aggregate(self, pipeline):
        if self.count_fails:
            raise RuntimeError("aggregate failed")
        match = pipeline[0].get("$match", {})
        group_key = pipeline[1]["$group"]["_id"].lstrip("$")
        buckets = {}
        for doc in self._matching(match):
            buckets[doc.get(group_key)] = buckets.get(doc.get(group_key), 0) + 1
        return [{"_id": k, "n": v} for k, v in buckets.items()]

    # -- כתיבה --
    def insert_one(self, doc):
        doc = dict(doc)
        doc["_id"] = doc.get("_id") or self._next
        self._next += 1
        self.docs.append(doc)
        return _Res(inserted_id=doc["_id"])

    def update_one(self, query, update):
        for doc in self._matching(query):
            new_title = update.get("$set", {}).get("title")
            if new_title is not None and self.duplicate_titles:
                raise _StubDuplicateKeyError("E11000 duplicate key")
            doc.update(update.get("$set", {}))
            # ``$unset`` — בלעדיו כל בדיקה על מחיקת שדה עוברת מעצמה
            for field in (update.get("$unset") or {}):
                doc.pop(field, None)
            return _Res()
        return _Res(modified_count=0)

    def update_many(self, query, update):
        if self.move_is_noop:
            return _Res()  # מדווח הצלחה, לא מזיז דבר
        n = 0
        for doc in self._matching(query):
            doc.update(update.get("$set", {}))
            n += 1
        return _Res(modified_count=n)

    def delete_one(self, query):
        for doc in self._matching(query):
            self.docs.remove(doc)
            return _Res()
        return _Res(deleted_count=0)

    def create_index(self, *a, **k):
        return None

    def create_indexes(self, *a, **k):
        return None

    def _matching(self, query):
        out = []
        for doc in self.docs:
            if all(self._match(doc, k, v) for k, v in query.items()):
                out.append(doc)
        return out

    @staticmethod
    def _match(doc, key, cond):
        value = doc.get(key)
        if isinstance(cond, dict):
            if "$in" in cond and value not in cond["$in"]:
                return False
            if "$nin" in cond and value in cond["$nin"]:
                return False
            if "$exists" in cond and (key in doc) != cond["$exists"]:
                return False
            if "$ne" in cond and value == cond["$ne"]:
                return False
            return True
        return value == cond


class _Cursor(list):
    def sort(self, *_a, **_k):
        return self


class _StubDB:
    def __init__(self, boards=None, notes=None):
        self.note_boards = boards or _StubColl()
        self.sticky_notes = notes or _StubColl()


@pytest.fixture
def client(monkeypatch):
    """אפליקציית Flask מינימלית עם שני ה-blueprints ו-stub למסד."""
    from webapp import note_boards_api, sticky_notes_api

    db = _StubDB()
    monkeypatch.setattr(note_boards_api, "get_db", lambda: db)
    monkeypatch.setattr(sticky_notes_api, "get_db", lambda: db)
    monkeypatch.setattr(sticky_notes_api, "_ensure_indexes", lambda: None)
    # ObjectId של bson דוחה מזהים שאינם 24-hex; ה-stub עובד עם int
    monkeypatch.setattr(note_boards_api, "ObjectId", lambda x: int(x))
    monkeypatch.setattr(sticky_notes_api, "ObjectId", lambda x: int(x))

    app = flask.Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(note_boards_api.note_boards_bp)
    app.register_blueprint(sticky_notes_api.sticky_notes_bp)

    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess["user_id"] = 7
    test_client.db = db
    return test_client


# -- רשימה ולוח ברירת מחדל --

def test_list_returns_default_board(client):
    """הרשימה היא הנקודה שבה לוח ברירת המחדל נוצר — היא נטענת בכל כניסה."""
    res = client.get("/api/note-boards")
    body = res.get_json()

    assert res.status_code == 200
    assert body["count"] == 1
    assert body["boards"][0]["is_default"] is True
    assert body["boards"][0]["note_count"] == 0


def test_list_reattaches_orphan_notes(client):
    """פתק שמצביע ללוח שנעלם חוזר לברירת המחדל בטעינת הרשימה."""
    client.db.sticky_notes.docs.append({"_id": 1, "user_id": 7, "board_id": "ghost"})

    body = client.get("/api/note-boards").get_json()

    assert body["reattached"] == 1
    default_id = body["boards"][0]["id"]
    assert client.db.sticky_notes.docs[0]["board_id"] == default_id


# -- יצירה --

def test_create_board(client):
    res = client.post("/api/note-boards", json={"name": "  לוח   שלי "})
    body = res.get_json()

    assert res.status_code == 201
    assert body["board"]["name"] == "לוח שלי"
    assert body["board"]["is_default"] is False


def test_create_verifies_the_write_landed(client, monkeypatch):
    """``inserted_id`` שחזר אינו ראיה. לוח שלא נוצר יבלע כל פתק שינחת עליו.

    נופל בלי הקריאה החוזרת — שם הראוט היה מחזיר 201 על לוח שאינו קיים.
    """
    monkeypatch.setattr(client.db.note_boards, "insert_one", lambda doc: _Res(inserted_id=999))

    res = client.post("/api/note-boards", json={"name": "רפאים"})

    assert res.status_code == 500
    assert res.get_json()["error"] == "board_create_not_applied"


def test_create_rejects_when_count_failed(client):
    """ספירה שנכשלה אינה "אין לוחות" — אותה הכרעה כמו בתקרת הפתקים."""
    client.db.note_boards.count_fails = True

    res = client.post("/api/note-boards", json={"name": "x"})

    assert res.status_code == 409
    assert res.get_json()["error"] == "board_quota_unknown"


# -- שינוי שם --

def test_rename_default_board_is_allowed(client):
    """שינוי שם מותר גם לברירת המחדל — הזיהוי הוא is_default ולא השם.

    זו בדיוק הסיבה שלא חיקינו את "שולחן עבודה", שמזוהה לפי מחרוזת.
    """
    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]

    res = client.patch(f"/api/note-boards/{board_id}", json={"name": "הלוח שלי"})
    assert res.status_code == 200
    assert res.get_json()["board"]["name"] == "הלוח שלי"

    after = client.get("/api/note-boards").get_json()["boards"][0]
    assert after["is_default"] is True  # עדיין ברירת מחדל


def test_rename_verifies_the_write(client, monkeypatch):
    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    monkeypatch.setattr(client.db.note_boards, "update_one", lambda q, u: _Res())

    res = client.patch(f"/api/note-boards/{board_id}", json={"name": "שם חדש"})

    assert res.status_code == 409
    assert res.get_json()["error"] == "rename_not_applied"


# -- נעיצה --

def test_a_board_without_the_field_is_not_pinned(client):
    """מסמכי לוח קיימים נוצרו לפני השדה. ברירת המחדל היא התשובה הנכונה
    עבורם, ולכן אין מיגרציה.

    נופל אם ``is_pinned`` יוסר מ-``_board_response``.
    """
    board = client.get("/api/note-boards").get_json()["boards"][0]
    assert board["is_pinned"] is False


def test_pin_and_unpin_round_trip(client):
    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]

    res = client.patch(f"/api/note-boards/{board_id}", json={"is_pinned": True})
    assert res.status_code == 200
    assert res.get_json()["board"]["is_pinned"] is True
    assert client.get("/api/note-boards").get_json()["boards"][0]["is_pinned"] is True

    res = client.patch(f"/api/note-boards/{board_id}", json={"is_pinned": False})
    assert res.status_code == 200
    assert client.get("/api/note-boards").get_json()["boards"][0]["is_pinned"] is False


def test_pin_verifies_the_write(client, monkeypatch):
    """**ערך ההחזרה של הכתיבה אינו אימות.**

    ``update_one`` מדווח הצלחה גם כשלא נגע בכלום. בלי הקריאה החוזרת
    המודאל היה מציג לוח נעוץ שאינו נעוץ במסד — וברענון הסימון היה נעלם.

    נופל אם בדיקת ``is_pinned`` אחרי הכתיבה תוסר.
    """
    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    monkeypatch.setattr(client.db.note_boards, "update_one", lambda q, u: _Res())

    res = client.patch(f"/api/note-boards/{board_id}", json={"is_pinned": True})

    assert res.status_code == 409
    assert res.get_json()["error"] == "pin_not_applied"


def test_pinning_does_not_clear_the_name(client):
    """**עדכון חלקי באמת.**

    ``$set`` נבנה רק מהשדות שנשלחו. אילו הוא היה נבנה תמיד משניהם,
    ``PATCH`` עם ``is_pinned`` בלבד היה כותב שם מנורמל מ-``None`` —
    כלומר מוחק את שם הלוח בלחיצה על צ'קבוקס.

    נופל אם הבנייה המותנית של ``updates`` תוסר.
    """
    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    client.patch(f"/api/note-boards/{board_id}", json={"name": "לוח בדיקה"})

    client.patch(f"/api/note-boards/{board_id}", json={"is_pinned": True})

    after = client.get("/api/note-boards").get_json()["boards"][0]
    assert after["name"] == "לוח בדיקה"
    assert after["is_pinned"] is True


def test_renaming_does_not_clear_the_pin(client):
    """הכיוון ההפוך — שינוי שם אינו מבטל נעיצה."""
    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    client.patch(f"/api/note-boards/{board_id}", json={"is_pinned": True})

    client.patch(f"/api/note-boards/{board_id}", json={"name": "שם אחר"})

    after = client.get("/api/note-boards").get_json()["boards"][0]
    assert after["is_pinned"] is True
    assert after["name"] == "שם אחר"


def test_patch_without_known_fields_is_rejected(client):
    """שדה לא מוכר אינו "עדכון ריק שהצליח" — הוא בקשה שגויה."""
    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]

    res = client.patch(f"/api/note-boards/{board_id}", json={"color": "red"})

    assert res.status_code == 400
    assert res.get_json()["error"] == "no_fields_to_update"


def test_pinning_a_foreign_board_is_404(client):
    """הבעלות נאכפת לפני הכתיבה, לא אחריה."""
    from bson import ObjectId

    res = client.patch(f"/api/note-boards/{ObjectId()}", json={"is_pinned": True})

    assert res.status_code == 404


# -- מחיקה --

def test_cannot_delete_default_board(client):
    """החסימה שאין לה מקבילה באוספים — ובכוונה.

    מחיקת אוסף מאבדת סידור; מחיקת לוח מאבדת את המקום היחיד של הפתק.
    """
    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]

    res = client.delete(f"/api/note-boards/{board_id}")

    assert res.status_code == 409
    assert res.get_json()["error"] == "cannot_delete_default"
    assert client.db.note_boards.find_one({"_id": int(board_id)}) is not None


def test_delete_moves_notes_to_default(client):
    default_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    other_id = client.post("/api/note-boards", json={"name": "זמני"}).get_json()["board"]["id"]
    client.db.sticky_notes.docs.append({"_id": 1, "user_id": 7, "board_id": other_id})

    res = client.delete(f"/api/note-boards/{other_id}")
    body = res.get_json()

    assert res.status_code == 200
    assert body["moved"] == 1
    assert client.db.sticky_notes.docs[0]["board_id"] == default_id
    assert client.db.note_boards.find_one({"_id": int(other_id)}) is None


def test_delete_aborts_when_notes_remain(client):
    """``update_many`` מדווח הצלחה ולא מזיז דבר — והלוח **לא** נמחק.

    זו הבדיקה המרכזית של הפעולה הזו. בלי הספירה החוזרת אחרי ההעברה הראוט
    היה מחזיר 200, מוחק את הלוח, ומשאיר את הפתקים מצביעים ללוח מת: בלתי
    נראים בממשק, ובלתי ניתנים לשחזור בלי גישה ישירה למונגו.
    """
    other_id = client.post("/api/note-boards", json={"name": "זמני"}).get_json()["board"]["id"]
    client.db.sticky_notes.docs.append({"_id": 1, "user_id": 7, "board_id": other_id})
    client.db.sticky_notes.move_is_noop = True

    res = client.delete(f"/api/note-boards/{other_id}")
    body = res.get_json()

    assert res.status_code == 500
    assert body["error"] == "notes_move_incomplete"
    assert body["remaining"] == 1
    # הלוח שרד, ואפשר לנסות שוב
    assert client.db.note_boards.find_one({"_id": int(other_id)}) is not None
    assert client.db.sticky_notes.docs[0]["board_id"] == other_id


def test_delete_of_foreign_board_is_404(client):
    client.db.note_boards.docs.append({"_id": 555, "user_id": 99, "name": "של מישהו אחר"})

    assert client.delete("/api/note-boards/555").status_code == 404


# -- פתקי לוח --

def test_create_board_note_writes_board_id_only(client):
    """פתק לוח נושא ``board_id`` ולא ``file_id``, ולא מקבל ``scope_id``."""
    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]

    res = client.post(f"/api/sticky-notes/board/{board_id}", json={"content": "שלום"})
    assert res.status_code == 201

    note = client.db.sticky_notes.docs[0]
    assert note["board_id"] == board_id
    assert "file_id" not in note
    assert "scope_id" not in note
    assert note["mode"] == "surface"


def test_board_note_list_never_touches_code_snippets(client, monkeypatch):
    """שאילתת הלוח ישירה — בלי ``_resolve_scope`` ובלי קריאה ל-code_snippets.

    נופלת אם מנתבים פתקי לוח דרך ``list_notes`` הקיים.
    """
    from webapp import sticky_notes_api

    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    client.post(f"/api/sticky-notes/board/{board_id}", json={"content": "א"})

    called = []
    monkeypatch.setattr(
        sticky_notes_api, "_resolve_scope",
        lambda *a, **k: called.append(a) or (None, None, []),
    )

    body = client.get(f"/api/sticky-notes/board/{board_id}").get_json()

    assert body["count"] == 1
    assert called == []


def test_invalid_mode_is_rejected(client):
    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]

    res = client.post(f"/api/sticky-notes/board/{board_id}", json={"content": "x", "mode": "diagonal"})

    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_mode"


def test_note_on_foreign_board_is_404(client):
    """בלי הבדיקה הזו אפשר ליצור פתקים על ``board_id`` שרירותי."""
    client.db.note_boards.docs.append({"_id": 555, "user_id": 99, "name": "זר"})

    assert client.post("/api/sticky-notes/board/555", json={"content": "x"}).status_code == 404
    assert client.get("/api/sticky-notes/board/555").status_code == 404


def test_board_quota_is_enforced(client, monkeypatch):
    from webapp import sticky_notes_api

    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    monkeypatch.setattr(sticky_notes_api, "MAX_NOTES_PER_BOARD", 1)

    assert client.post(f"/api/sticky-notes/board/{board_id}", json={"content": "א"}).status_code == 201
    res = client.post(f"/api/sticky-notes/board/{board_id}", json={"content": "ב"})

    assert res.status_code == 409
    assert res.get_json()["error"] == "note_quota_exceeded"


def test_admin_is_exempt_from_quota(client, monkeypatch):
    from webapp import sticky_notes_api

    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    monkeypatch.setattr(sticky_notes_api, "MAX_NOTES_PER_BOARD", 1)
    monkeypatch.setattr(sticky_notes_api, "_current_user_is_admin", lambda: True)

    assert client.post(f"/api/sticky-notes/board/{board_id}", json={"content": "א"}).status_code == 201
    assert client.post(f"/api/sticky-notes/board/{board_id}", json={"content": "ב"}).status_code == 201


def test_quota_rejects_when_count_failed(client):
    """ספירה שנכשלה ⇒ דחייה, לא מעבר.

    ``mcp_server/backend`` עושה כאן את ההפך (``existing = 0`` בכשל). נופל
    אם מעתיקים את ההתנהגות ההיא.
    """
    board_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    client.db.sticky_notes.count_fails = True

    res = client.post(f"/api/sticky-notes/board/{board_id}", json={"content": "x"})

    assert res.status_code == 409
    assert res.get_json()["error"] == "note_quota_unknown"


def test_user_quota_applies_to_file_notes_too(client, monkeypatch):
    """התקרה למשתמש חלה על כל הפתקים, לא רק על אלה שבלוחות.

    היא מתועדת מזה זמן ולא נאכפה בשום מקום. אכיפה רק במסלול הלוח הייתה
    הופכת את התיעוד לנכון-למחצה — וזה בדיוק סוג הטענה שהלינט של
    התקצירים נבנה כדי לתפוס.
    """
    from webapp import sticky_notes_api

    monkeypatch.setattr(sticky_notes_api, "MAX_NOTES_PER_USER", 1)
    monkeypatch.setattr(sticky_notes_api, "_resolve_scope", lambda *a, **k: (None, None, []))
    client.db.sticky_notes.docs.append({"_id": 1, "user_id": 7, "file_id": "f1"})

    res = client.post("/api/sticky-notes/f1", json={"content": "עוד אחד"})

    assert res.status_code == 409
    assert res.get_json()["error"] == "note_quota_exceeded"


def test_board_routes_ensure_indexes(client, monkeypatch):
    """האינדקסים נוצרים גם כשנכנסים ישר לעמוד הלוחות.

    ``one_default_per_user`` — האינדקס הייחודי-החלקי שסוגר את המרוץ
    ביצירת לוח ברירת מחדל — נבנה ב-``sticky_notes_api._ensure_indexes``,
    שנקרא רק ממסלולי הפתקים. משתמש שנכנס ישר ל-``/boards`` לא היה עובר
    שם, ולכן ההגנה מפני שתי בקשות מקבילות פשוט לא הייתה קיימת.
    """
    from webapp import note_boards_api

    calls = []
    monkeypatch.setattr(note_boards_api, "_ensure_board_indexes", lambda: calls.append(1))

    client.get("/api/note-boards")
    client.post("/api/note-boards", json={"name": "x"})

    assert len(calls) == 2


def test_note_counts_come_from_one_aggregation(client, monkeypatch):
    """מונה אחד לכל הלוחות, ולא שאילתה פר לוח.

    עם עשרים לוחות, ``count_documents`` פר לוח הוא עשרים סיבובים למסד
    בכל טעינת עמוד.
    """
    default_id = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    client.db.sticky_notes.docs.append({"_id": 1, "user_id": 7, "board_id": default_id})

    calls = []
    original = client.db.sticky_notes.count_documents
    monkeypatch.setattr(
        client.db.sticky_notes, "count_documents",
        lambda q: calls.append(q) or original(q),
    )

    body = client.get("/api/note-boards").get_json()

    assert body["boards"][0]["note_count"] == 1
    # ספירות שנותרו הן של סריקת היתומים בלבד, לא פר לוח
    assert not any("board_id" in c and isinstance(c.get("board_id"), str) for c in calls)


def test_count_failure_is_distinguishable_from_empty(client):
    """כשל ספירה משמיט את המונה במקום להציג אפס.

    אחרת לוח מלא היה נראה ריק בדיוק כשהמסד מתקשה.
    """
    client.db.sticky_notes.count_fails = True

    board = client.get("/api/note-boards").get_json()["boards"][0]

    assert "note_count" not in board


# -- ``mode``: הכפתור בלוח נשמר --
#
# ``mode`` נכתב עד היום רק ביצירה, ולכן כפתור המצב לא יכול היה לשנות כלום
# שנשמר. מה שכן קרה בלחיצה עליו זה שהמיקום נכתב מחדש — כלומר הפתק זז ולא
# שינה מצב.


def _board_note(client, **extra):
    doc = {"_id": 1, "user_id": 7, "board_id": "b1", "content": "", "mode": "surface"}
    doc.update(extra)
    client.db.sticky_notes.docs.append(doc)
    return doc


def test_mode_update_is_persisted_for_board_note(client):
    doc = _board_note(client)

    res = client.put("/api/sticky-notes/note/1", json={"mode": "screen"})

    assert res.status_code == 200, res.get_json()
    assert doc["mode"] == "screen"


def test_mode_alone_is_enough_to_update(client):
    """``mode`` בלבד אינו "אין שדות לעדכון"."""
    _board_note(client)

    res = client.put("/api/sticky-notes/note/1", json={"mode": "screen"})

    assert res.status_code == 200
    assert res.get_json()["ok"] is True


def test_invalid_mode_is_rejected(client):
    doc = _board_note(client)

    res = client.put("/api/sticky-notes/note/1", json={"mode": "anchored"})

    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_mode"
    assert doc["mode"] == "surface", "הפתק לא השתנה"


def test_mode_is_refused_on_a_file_note(client):
    """פתק קובץ אינו מקבל ``mode``.

    ``_resolveMode`` בלקוח קורא את ``mode`` **לפני** הסנטינלים, ולכן שדה
    כזה על פתק קובץ היה משתלט על מסלול העיגון לשורות המקור.
    """
    doc = {"_id": 2, "user_id": 7, "file_id": "f1", "content": "", "scope_id": "s1"}
    client.db.sticky_notes.docs.append(doc)

    res = client.put("/api/sticky-notes/note/2", json={"mode": "screen"})

    assert res.status_code == 400
    assert res.get_json()["error"] == "mode_not_supported"
    assert "mode" not in doc


def test_mode_update_works_through_the_batch_route(client):
    """זה המסלול שהלקוח באמת משתמש בו — ``_performSaveBatch``."""
    doc = _board_note(client)

    res = client.post(
        "/api/sticky-notes/batch",
        json={"updates": [{"id": "1", "mode": "screen", "position": {"x": 5, "y": 6}}]},
    )

    assert res.status_code == 200
    assert res.get_json()["results"][0]["ok"] is True
    assert doc["mode"] == "screen"
    assert (doc["position_x"], doc["position_y"]) == (5, 6)


def test_batch_rejects_invalid_mode_without_touching_the_note(client):
    doc = _board_note(client)

    res = client.post(
        "/api/sticky-notes/batch",
        json={"updates": [{"id": "1", "mode": "לא-קיים", "position": {"x": 5, "y": 6}}]},
    )

    result = res.get_json()["results"][0]
    assert result["ok"] is False
    assert result["status"] == 400
    assert result["error"] == "invalid_mode"
    # הפריט כולו נדחה, ולא "חצי נשמר"
    assert doc["mode"] == "surface"
    assert "position_x" not in doc


# -- תקרת אורך התוכן --
#
# עד לשינוי הזה השרת אכף אותה ב**חיתוך שקט**: הדבקה של 16,291 תווים נשמרה
# כ-5,000 והתשובה הייתה 200 OK. mcp_server/handlers דחה כבר אז; הוובאפ היה
# החריג, ולכן אותו פתק התקבל בערוץ אחד ונחתך בשני.

import base64


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_the_limit_has_a_single_source(client):
    """שלושת הצרכנים מייבאים את אותו מספר, לא מקלידים אותו."""
    from mcp_server import handlers
    from sticky_notes_target import MAX_NOTE_CHARS
    from webapp import sticky_notes_api

    assert sticky_notes_api.MAX_NOTE_CHARS == MAX_NOTE_CHARS
    assert handlers.MAX_NOTE_CONTENT == MAX_NOTE_CHARS


def test_the_javascript_holds_no_hardcoded_limit():
    """הלקוח מקבל את התקרה מהשרת.

    מספר בצד הלקוח היה מקור אמת שני, ופער בינו לבין השרת נראה למשתמש
    כחיתוך בלי הסבר. הבדיקה נופלת אם מישהו יחזיר ליטרל.
    """
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "webapp/static/js/sticky-notes.js").read_text(encoding="utf-8")
    assert "window.STICKY_NOTE_MAX_CHARS" in js, "הלקוח אינו קורא את הערך מהשרת"
    assert "MAX_NOTE_CHARS = 5000" not in js
    assert "MAX_NOTE_CHARS = 20000" not in js


def test_content_at_the_limit_is_accepted(client):
    """הגבול עצמו חוקי — off-by-one כאן פוסל תוכן תקין."""
    from sticky_notes_target import MAX_NOTE_CHARS

    client.db.note_boards.docs.append({"_id": 1, "user_id": 7, "name": "לוח", "is_default": True})
    text = "א" * MAX_NOTE_CHARS

    res = client.post("/api/sticky-notes/board/1", json={"content_b64": _b64(text)})

    assert res.status_code == 201, res.get_json()
    assert len(client.db.sticky_notes.docs[-1]["content"]) == MAX_NOTE_CHARS


def test_content_over_the_limit_is_rejected_not_truncated(client):
    """**זה הבאג.** חיתוך שקט שמוחזר כ-200 הוא מחיקת מידע."""
    from sticky_notes_target import MAX_NOTE_CHARS

    client.db.note_boards.docs.append({"_id": 1, "user_id": 7, "name": "לוח", "is_default": True})
    before = len(client.db.sticky_notes.docs)

    res = client.post("/api/sticky-notes/board/1", json={"content_b64": _b64("א" * (MAX_NOTE_CHARS + 1))})

    assert res.status_code == 400
    body = res.get_json()
    assert body["error"] == "content_too_long"
    assert body["max"] == MAX_NOTE_CHARS, "הלקוח צריך לדעת מה התקרה"
    assert len(client.db.sticky_notes.docs) == before, "לא נוצר פתק חתוך"


def test_update_over_the_limit_leaves_the_note_untouched(client):
    from sticky_notes_target import MAX_NOTE_CHARS

    doc = {"_id": 1, "user_id": 7, "board_id": "b1", "content": "המקורי", "mode": "surface"}
    client.db.sticky_notes.docs.append(doc)

    res = client.put("/api/sticky-notes/note/1", json={"content_b64": _b64("א" * (MAX_NOTE_CHARS + 1))})

    assert res.status_code == 400
    assert res.get_json()["error"] == "content_too_long"
    assert doc["content"] == "המקורי", "התוכן הקיים לא נדרס בגרסה חתוכה"


def test_batch_rejects_the_item_without_touching_the_note(client):
    from sticky_notes_target import MAX_NOTE_CHARS

    doc = {"_id": 1, "user_id": 7, "board_id": "b1", "content": "המקורי"}
    client.db.sticky_notes.docs.append(doc)

    res = client.post(
        "/api/sticky-notes/batch",
        json={"updates": [{"id": "1", "content_b64": _b64("א" * (MAX_NOTE_CHARS + 1))}]},
    )

    result = res.get_json()["results"][0]
    assert result["status"] == 400
    assert result["error"] == "content_too_long"
    assert doc["content"] == "המקורי"


# -- דלף מידע דרך טקסט של חריגה (CodeQL code-scanning/620) --


def test_exception_text_never_reaches_the_client(client, monkeypatch):
    """טקסט של חריגה לא יוצא ללקוח, גם כשהיא נושאת פרט פנימי.

    ``str(exc)`` בתשובה הוא דלף ממתין: הוא נכון היום כי כל ה-``raise``
    מעבירים ליטרל, אבל שום דבר לא אוכף את זה. הבדיקה מזריקה חריגה שנושאת
    נתיב פנימי ומוודאת שהוא **אינו** יוצא.
    """
    import sticky_notes_target

    secret = "failed at /srv/app/secrets/db.conf line 42"

    def _leaky(*_a, **_k):
        raise sticky_notes_target.NoteQuotaError(secret)

    # ``check_note_quota`` מיובאת בתוך הפונקציה, ולכן מחליפים אותה במקור
    monkeypatch.setattr(sticky_notes_target, "check_note_quota", _leaky)
    client.db.note_boards.docs.append({"_id": 1, "user_id": 7, "name": "לוח", "is_default": True})

    res = client.post("/api/sticky-notes/board/1", json={"content": "שלום"})

    body = str(res.get_json())
    assert "secrets" not in body, f"דלף פרט פנימי: {body}"
    assert "/srv" not in body
    assert secret not in body


def test_quota_errors_map_to_codes_by_type_not_by_text(client, monkeypatch):
    """הקוד שמוחזר נגזר מ**סוג** החריגה, ולא מהטקסט שלה.

    לכן גם חריגה שהטקסט שלה שונה לגמרי עדיין מקבלת את הקוד הנכון — וגם
    ההפך: טקסט לא יכול להפוך לקוד.
    """
    import sticky_notes_target

    client.db.note_boards.docs.append({"_id": 1, "user_id": 7, "name": "לוח", "is_default": True})

    for exc_cls, expected in (
        (sticky_notes_target.NoteQuotaUnknown, "note_quota_unknown"),
        (sticky_notes_target.NoteQuotaExceeded, "note_quota_exceeded"),
    ):
        def _raise(*_a, _cls=exc_cls, **_k):
            raise _cls("טקסט אחר לגמרי שאסור שיצא")

        monkeypatch.setattr(sticky_notes_target, "check_note_quota", _raise)
        res = client.post("/api/sticky-notes/board/1", json={"content": "שלום"})

        assert res.status_code == 409
        assert res.get_json()["error"] == expected
        assert "טקסט אחר" not in str(res.get_json())


# -- שם הפתק במסלול ה-batch --
#
# זה **המסלול הרגיל**, לא הפולבק: ``_queueSave`` בלקוח מנקז דרך debounce
# אל ``POST /batch``, וה-PUT הבודד רץ רק אם בקשת ה-batch עצמה נכשלה.


def test_batch_saves_the_note_title(client):
    """**אבידת כתיבה שקטה, מהסוג הגרוע ביותר.**

    ``title`` לא היה ב-allowlist של ה-batch. הראוט החזיר ``ok: True,
    status: 200``, הלקוח ניקה את התור בהתאם — והשם פשוט לא נשמר. שום
    חיווי, שום לוג, ואין דרך למשתמש לדעת.

    נמדד מול הראוט לפני התיקון: השם במסד נשאר "ישן" אחרי בקשה ששלחה
    "שם חדש", והתשובה הייתה 200.

    נופלת בלי ``title`` ב-allowlist של ה-batch.
    """
    client.db.sticky_notes.docs.append(
        {"_id": 1, "user_id": 7, "board_id": "b1", "content": "x", "title": "ישן"}
    )

    res = client.post("/api/sticky-notes/batch", json={"updates": [{"id": "1", "title": "  שם   חדש "}]})
    body = res.get_json()

    assert body["results"][0]["ok"] is True
    assert client.db.sticky_notes.docs[0]["title"] == "שם חדש"


def test_batch_clearing_a_title_removes_the_field(client):
    """שם ריק ← ``$unset``, ולא ``title: ""``.

    שני פתקים ששמם נוקה היו מתנגשים באינדקס, כי ``$exists`` מתקיים גם
    למחרוזת ריקה. אותה סמנטיקה בדיוק כמו ב-PUT הבודד.

    נופלת אם ה-batch כותב מחרוזת ריקה במקום למחוק את השדה.
    """
    client.db.sticky_notes.docs.append(
        {"_id": 1, "user_id": 7, "board_id": "b1", "content": "x", "title": "יש שם"}
    )

    res = client.post("/api/sticky-notes/batch", json={"updates": [{"id": "1", "title": "   "}]})

    assert res.get_json()["results"][0]["ok"] is True
    assert "title" not in client.db.sticky_notes.docs[0]


def test_batch_reports_a_duplicate_title_as_409_and_not_500(client):
    """קוד השגיאה הוא **ההבדל בין תיקון ללולאה אינסופית**.

    הלקוח מנסה שוב על 409 גנרי (התנגשות גרסה) ומפסיק על ``duplicate_title``.
    ``500 Failed`` — מה שהמסלול הזה החזיר עד היום, כי הכתיבה לא הייתה
    עטופה — היה מסמן כשל בלי לומר למשתמש שהשם תפוס.

    נופלת בלי ``except DuplicateKeyError`` סביב הכתיבה ב-batch.
    """
    client.db.sticky_notes.docs.append({"_id": 1, "user_id": 7, "board_id": "b1", "content": "x"})
    client.db.sticky_notes.duplicate_titles = True

    res = client.post("/api/sticky-notes/batch", json={"updates": [{"id": "1", "title": "טודו"}]})
    result = res.get_json()["results"][0]

    assert result["status"] == 409
    assert result["error"] == "duplicate_title"


def test_single_put_clearing_a_title_removes_the_field(client):
    """אותה סמנטיקה גם ב-PUT — כאן דרך ה-HTTP, לא ישירות מול המסד."""
    client.db.sticky_notes.docs.append(
        {"_id": 1, "user_id": 7, "board_id": "b1", "content": "x", "title": "יש שם"}
    )

    res = client.put("/api/sticky-notes/note/1", json={"title": ""})

    assert res.status_code == 200
    assert "title" not in client.db.sticky_notes.docs[0]


# -- גיבוי לאכיפת השם כשהאינדקס לא אומת --


def test_duplicate_title_is_caught_by_code_when_the_index_is_missing(client, monkeypatch):
    """**הבטחה שאין מאחוריה כלום היא הדבר היחיד שגרוע יותר מהתנגשות.**

    הראוט מחזיר ``duplicate_title`` על סמך דחייה של המסד. אם האינדקס
    הייחודי לא נבנה — כשל חולף בעלייה, פריסה שהוובאפ לא רץ בה — הדחייה
    לעולם לא תגיע, והשמות הכפולים נכנסים בשקט בזמן שהתיעוד מבטיח 409.

    נופלת בלי ``_title_conflict`` בראוט **היצירה**. שני הראוטים האחרים
    נבדקים בנפרד — הגיבוי מחווט לשלושה מסלולים, ובדיקה של אחד מהם אינה
    מגינה על השניים האחרים.
    """
    from webapp import sticky_notes_api

    monkeypatch.setattr(sticky_notes_api, "_TITLE_INDEX_OK", False, raising=False)
    board = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    first = client.post(f"/api/sticky-notes/board/{board}", json={"content": "a", "title": "טודו"})
    assert first.status_code == 201

    res = client.post(f"/api/sticky-notes/board/{board}", json={"content": "b", "title": "טודו"})

    assert res.status_code == 409
    assert res.get_json()["error"] == "duplicate_title"
    assert client.db.sticky_notes.count_documents({"title": "טודו"}) == 1


def test_the_fallback_covers_the_single_put_route(client, monkeypatch):
    """נופלת אם הגיבוי מוסר מ-``update_note`` בלבד."""
    from webapp import sticky_notes_api

    monkeypatch.setattr(sticky_notes_api, "_TITLE_INDEX_OK", False, raising=False)
    board = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    taken = client.post(f"/api/sticky-notes/board/{board}", json={"content": "a", "title": "טודו"})
    other = client.post(f"/api/sticky-notes/board/{board}", json={"content": "b"})
    assert taken.status_code == 201 and other.status_code == 201

    res = client.put(f"/api/sticky-notes/note/{other.get_json()['id']}", json={"title": "טודו"})

    assert res.status_code == 409
    assert res.get_json()["error"] == "duplicate_title"


def test_the_fallback_covers_the_batch_route(client, monkeypatch):
    """נופלת אם הגיבוי מוסר מ-``batch`` בלבד — וזה **המסלול הרגיל** של הלקוח."""
    from webapp import sticky_notes_api

    monkeypatch.setattr(sticky_notes_api, "_TITLE_INDEX_OK", False, raising=False)
    board = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    client.post(f"/api/sticky-notes/board/{board}", json={"content": "a", "title": "טודו"})
    other = client.post(f"/api/sticky-notes/board/{board}", json={"content": "b"})

    res = client.post(
        "/api/sticky-notes/batch",
        json={"updates": [{"id": other.get_json()["id"], "title": "טודו"}]},
    )
    result = res.get_json()["results"][0]

    assert result["status"] == 409
    assert result["error"] == "duplicate_title"


def test_the_fallback_renaming_a_note_to_its_own_title_is_allowed(client, monkeypatch):
    """פתק ששומר על שמו אינו מתנגש בעצמו.

    ``exclude_id`` שייך ל**שאילתה**: סינון התוצאה בדיעבד היה נכשל כאן ברגע
    שיש עוד פתק תואם, כי ``find_one`` מחזיר מסמך אחד שרירותי.
    """
    from webapp import sticky_notes_api

    monkeypatch.setattr(sticky_notes_api, "_TITLE_INDEX_OK", False, raising=False)
    board = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    mine = client.post(f"/api/sticky-notes/board/{board}", json={"content": "a", "title": "טודו"})

    res = client.put(f"/api/sticky-notes/note/{mine.get_json()['id']}", json={"title": "טודו"})

    assert res.status_code == 200


def test_the_fallback_is_scoped_to_the_board(client, monkeypatch):
    """**הממד שהתיקון כולו עומד עליו: אותו שם בלוח אחר הוא חוקי.**

    בלי ``board_id`` בשאילתת הגיבוי, הבדיקה הזו הופכת את הגיבוי למחמיר
    יותר מהאינדקס עצמו — ופתק בלוח שני נדחה בלי סיבה. בדיקה שנוגעת רק
    בלוח אחד לא יכולה לתפוס את זה.
    """
    from webapp import sticky_notes_api

    monkeypatch.setattr(sticky_notes_api, "_TITLE_INDEX_OK", False, raising=False)
    first = client.get("/api/note-boards").get_json()["boards"][0]["id"]
    second = client.post("/api/note-boards", json={"name": "לוח שני"}).get_json()["board"]["id"]

    a = client.post(f"/api/sticky-notes/board/{first}", json={"content": "a", "title": "טודו"})
    b = client.post(f"/api/sticky-notes/board/{second}", json={"content": "b", "title": "טודו"})

    assert a.status_code == 201
    assert b.status_code == 201, f"אותו שם בלוח אחר נדחה: {b.get_json()}"
    assert client.db.sticky_notes.count_documents({"title": "טודו"}) == 2


def test_the_fallback_costs_nothing_when_the_index_is_confirmed(client, monkeypatch):
    """במצב התקין האכיפה היא של המסד, והגיבוי לא עולה שום שאילתה.

    נופלת אם ``_title_conflict`` מריצה ``find_one`` בלי תנאי — כלומר אם
    מישהו יסיר את הדגל ויהפוך בדיקה חירומית לעלות קבועה בכל כתיבה.
    """
    from webapp import sticky_notes_api

    monkeypatch.setattr(sticky_notes_api, "_TITLE_INDEX_OK", True, raising=False)
    board = client.get("/api/note-boards").get_json()["boards"][0]["id"]

    calls = []
    real = client.db.sticky_notes.find_one
    monkeypatch.setattr(
        client.db.sticky_notes, "find_one",
        lambda *a, **k: (calls.append(a), real(*a, **k))[1],
    )

    res = client.post(f"/api/sticky-notes/board/{board}", json={"content": "a", "title": "טודו"})

    assert res.status_code == 201
    assert calls == [], f"נורו שאילתות מיותרות: {calls}"


def test_a_missing_index_does_not_mark_the_warmup_as_done(monkeypatch):
    """``_mark_indexes_ready`` כותב דגל **משותף ברדיס ל-24 שעות**.

    סימון הצלחה כשהאינדקס לא אומת היה נועל כשל חולף אחד ליממה שלמה של
    אכיפה שאינה קיימת, בכל התהליכים. בלי הסימון הבקשה הבאה בונה שוב.

    נופלת אם ``_mark_indexes_ready`` נקראת ללא תנאי.
    """
    from webapp import sticky_notes_api

    marked = []
    monkeypatch.setattr(sticky_notes_api, "get_db", lambda: _StubDB())
    monkeypatch.setattr(sticky_notes_api, "_INDEX_READY", False, raising=False)
    monkeypatch.setattr(sticky_notes_api, "_cache_flag_ready", lambda: False, raising=False)
    monkeypatch.setattr(sticky_notes_api, "ensure_title_index", lambda coll: False)
    monkeypatch.setattr(sticky_notes_api, "_mark_indexes_ready", lambda **kw: marked.append(kw))
    # ``_ensure_indexes`` כותב ל-``_TITLE_INDEX_OK`` ול-``_INDEX_RETRY_AFTER``
    # דרך ``global``. בלי monkeypatch עליהם הכתיבה שורדת את הבדיקה ודולפת
    # לבאות אחריה — שם היא נראית ככשל אקראי שתלוי בסדר ההרצה.
    monkeypatch.setattr(sticky_notes_api, "_TITLE_INDEX_OK", sticky_notes_api._TITLE_INDEX_OK, raising=False)
    monkeypatch.setattr(sticky_notes_api, "_INDEX_RETRY_AFTER", 0.0, raising=False)

    sticky_notes_api._ensure_indexes()

    assert marked == [], "האתחול סומן כהצלחה בעוד שהאינדקס הקריטי אינו קיים"
    assert sticky_notes_api._TITLE_INDEX_OK is False


def test_a_failing_build_is_not_retried_on_every_request(monkeypatch):
    """**בלי חסם, כשל מתמשך מסריאל את השירות סביב מנעול אחד.**

    ``_ensure_indexes`` תופס את ``_INDEX_READY_LOCK`` ובונה שש קבוצות
    אינדקסים. כל עוד האתחול אינו מסומן כהצלחה — וזה בדיוק מה שהתיקון
    הקודם קבע — כל בקשה נכנסת שוב לאותו מסלול.

    נופלת בלי ``_INDEX_RETRY_AFTER``.
    """
    from webapp import sticky_notes_api

    calls = []
    clock = {"now": 1000.0}
    monkeypatch.setattr(sticky_notes_api, "get_db", lambda: _StubDB())
    monkeypatch.setattr(sticky_notes_api, "_INDEX_READY", False, raising=False)
    monkeypatch.setattr(sticky_notes_api, "_cache_flag_ready", lambda: False, raising=False)
    monkeypatch.setattr(sticky_notes_api, "_TITLE_INDEX_OK", False, raising=False)
    monkeypatch.setattr(sticky_notes_api, "_INDEX_RETRY_AFTER", 0.0, raising=False)
    monkeypatch.setattr(sticky_notes_api.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        sticky_notes_api, "ensure_title_index",
        lambda coll: (calls.append(clock["now"]), False)[1],
    )

    sticky_notes_api._ensure_indexes()
    sticky_notes_api._ensure_indexes()
    sticky_notes_api._ensure_indexes()
    assert len(calls) == 1, f"הבנייה רצה {len(calls)} פעמים בתוך חלון ההמתנה"

    # ...ואחרי שההשהיה חלפה — ניסיון חדש, כי כשל חולף חייב להיפתר לבד
    clock["now"] += sticky_notes_api._INDEX_RETRY_SECONDS + 1
    sticky_notes_api._ensure_indexes()
    assert len(calls) == 2, "אחרי ההשהיה לא נוסה שוב"


def test_the_shared_cache_flag_also_confirms_the_title_index(monkeypatch):
    """**worker חדש שיורש את הדגל אינו אמור להריץ שאילתת גיבוי לנצח.**

    ``_mark_indexes_ready`` — הכותב היחיד של הדגל — רץ רק כשאינדקס השם
    אומת, ולכן קיום הדגל הוא עדות לכך שהאילוץ חי. בלי הגרירה הזו התהליך
    היה מדלג על הבנייה ונשאר עם ``_TITLE_INDEX_OK`` כבוי לתמיד.

    נופלת אם ``_cache_flag_ready`` מדליק רק את ``_INDEX_READY``.
    """
    from webapp import sticky_notes_api

    class _Cache:
        is_enabled = True

        def get(self, key):
            return {"ready": True, "ts": 1}

    monkeypatch.setattr(sticky_notes_api, "cache", _Cache(), raising=False)
    monkeypatch.setattr(sticky_notes_api, "_INDEX_READY", False, raising=False)
    monkeypatch.setattr(sticky_notes_api, "_INDEX_CACHE_LAST_CHECK", 0.0, raising=False)
    monkeypatch.setattr(sticky_notes_api, "_TITLE_INDEX_OK", False, raising=False)
    monkeypatch.setattr(sticky_notes_api, "_REPO_TITLE_INDEX_OK", False, raising=False)

    assert sticky_notes_api._cache_flag_ready() is True
    assert sticky_notes_api._TITLE_INDEX_OK is True
    # הדגל המשותף מעיד עכשיו על **שני** אינדקסי השם, ולכן משחזר את שניהם.
    assert sticky_notes_api._REPO_TITLE_INDEX_OK is True


def test_the_cache_key_version_was_bumped_with_the_meaning_change():
    """מפתח ישן נושא משמעות ישנה.

    הדגל המשותף העיד תחילה רק על אינדקס הלוח, ובהוספת אינדקס הריפו משמעותו
    התרחבה לשני האינדקסים. תחת אותו מפתח, דגל v2 ישן היה מתפרש עכשיו
    כאימות של אינדקס הריפו שלא היה — למשך ה-TTL, ובכל התהליכים. לכן הועלה
    ל-v3, בדיוק כפי שהועלה בעבר עם שינוי המשמעות הקודם.
    """
    from webapp import sticky_notes_api

    assert sticky_notes_api._INDEX_READY_CACHE_KEY.endswith("_v3")
