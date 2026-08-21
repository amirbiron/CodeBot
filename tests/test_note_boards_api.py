"""בדיקות ל-API של לוחות הפתקים ולראוטי פתקי הלוח.

התבנית: stub של אוסף בפייתון טהור, כמו ב-``tests/test_sticky_notes_api.py``.
היתרון המרכזי כאן הוא שאפשר לתאר מצבים שקשה לייצר מול מסד אמיתי — למשל
``update_many`` שמדווח הצלחה ולא מזיז כלום, שזה בדיוק המצב שהמחיקה חייבת
לשרוד בלי לאבד פתקים.
"""

import pytest

flask = pytest.importorskip("flask")


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
            doc.update(update.get("$set", {}))
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
