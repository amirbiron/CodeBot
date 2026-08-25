"""בדיקות לראוטי פתקי הריפו — היעד השלישי.

התבנית זהה ל-``tests/test_note_boards_api.py``: stub של אוסף בפייתון טהור,
בלי mock ובלי מסד. היתרון כאן הוא שאפשר לתאר בדיוק את המצבים שקשה לייצר
מול מסד אמיתי — מניפסט ריפו שלא נקרא, ריפו שהוסר מהמראות, וספירה שנכשלת.
"""

import pytest

flask = pytest.importorskip("flask")


try:
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
        self.distinct_fails = False
        self.duplicate_titles = False
        #: מדמה את האינדקס הייחודי במסלול העדכון (ראו ``update_one``)
        self.enforce_unique_titles = False

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

    def distinct(self, field, query=None):
        if self.distinct_fails:
            raise RuntimeError("distinct failed")
        return sorted({
            doc.get(field) for doc in self._matching(query or {}) if doc.get(field) is not None
        })

    def insert_one(self, doc):
        doc = dict(doc)
        if self.duplicate_titles and doc.get("title"):
            raise _StubDuplicateKeyError("E11000 duplicate key")
        doc["_id"] = doc.get("_id") or self._next
        self._next += 1
        self.docs.append(doc)
        return _Res(inserted_id=doc["_id"])

    def update_one(self, query, ops, **k):
        # **מודל של אינדקס ייחודי אמיתי, לא "זרוק תמיד".** הסטאב הקודם זרק
        # על כל עדכון שנשא ``title``, ולכן טסט שעבר לא הבחין בין "המסד דחה
        # כפילות" לבין "כל שינוי שם נכשל". כאן הוא מחפש מסמך **אחר** של
        # אותו משתמש עם אותו שם באותו יעד — בדיוק מה שהאינדקס אוכף.
        new_title = (ops.get("$set") or {}).get("title")
        if self.enforce_unique_titles and new_title:
            target = self._matching(query)
            mine = target[0] if target else {}
            for doc in self.docs:
                if doc.get("_id") == mine.get("_id"):
                    continue
                if doc.get("title") != new_title or doc.get("user_id") != mine.get("user_id"):
                    continue
                same_board = doc.get("board_id") and doc.get("board_id") == mine.get("board_id")
                same_repo = (
                    doc.get("repo_path")
                    and doc.get("repo_path") == mine.get("repo_path")
                    and doc.get("repo_name") == mine.get("repo_name")
                )
                if same_board or same_repo:
                    raise _StubDuplicateKeyError("E11000 duplicate key")
        matched = self._matching(query)
        if not matched:
            return _Res(modified_count=0)
        doc = matched[0]
        doc.update(ops.get("$set") or {})
        for field in (ops.get("$unset") or {}):
            doc.pop(field, None)
        return _Res(modified_count=1)

    def create_index(self, *a, **k):
        return None

    def create_indexes(self, *a, **k):
        return None

    def _matching(self, query):
        return [doc for doc in self.docs if all(self._match(doc, k, v) for k, v in query.items())]

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


class _NullSortCursor:
    """סמן ש-``sort`` שלו מחזיר ``None`` — כשל שמדווח בערך החזרה בלבד.

    זה מה שמפריד את הדפוס מ"חריגה": שום ``except`` לא נדלק כאן, ולכן קוד
    שבודק רק חריגות ממשיך כאילו הכול תקין.
    """

    def sort(self, *_a, **_k):
        return None


class _NullSortColl(_StubColl):
    def find(self, *_a, **_k):
        return _NullSortCursor()


class _StubDB:
    def __init__(self):
        self.sticky_notes = _StubColl()
        self.repo_files = _StubColl()
        self.repo_metadata = _StubColl()


@pytest.fixture
def client(monkeypatch):
    from webapp import sticky_notes_api

    db = _StubDB()
    monkeypatch.setattr(sticky_notes_api, "get_db", lambda: db)
    monkeypatch.setattr(sticky_notes_api, "_ensure_indexes", lambda: None)

    app = flask.Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sticky_notes_api.sticky_notes_bp)

    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess["user_id"] = 7
    test_client.db = db
    return test_client


def _mirror(db, repo="CodeBot", paths=("webapp/app.py",), last_sync="2026-08-24T10:00:00Z"):
    """ריפו ממורר עם מניפסט קבצים, כמו ``repo_metadata`` + ``repo_files``."""
    db.repo_metadata.docs.append({"repo_name": repo, "last_sync_time": last_sync})
    for p in paths:
        db.repo_files.docs.append({"repo_name": repo, "path": p})


# ---------- צל-שם: הסיבה שראוטי היתומים יושבים מחוץ לתת-העץ ----------

def test_file_named_orphans_is_reachable(client):
    """**קובץ אמיתי בשם ``orphans`` חייב להיות נגיש דרך ה-API.**

    אילו ראוט היתומים היה ``/repo/<name>/orphans``, הראוט הסטטי היה מנצח
    את ``<path:repo_path>`` — וקובץ בשם הזה (שם סביר לגמרי בשורש ריפו) לא
    היה נגיש לעולם, בלי שום שגיאה. זה בדיוק הכשל השקט.

    נופלת אם מחזירים את ראוטי היתומים אל תוך תת-העץ.
    """
    _mirror(client.db, paths=("orphans", "docs/orphans"))
    client.db.sticky_notes.docs.append({
        "_id": 1, "user_id": 7, "repo_name": "CodeBot", "repo_path": "orphans",
        "content": "פתק על הקובץ ששמו orphans", "position_x": 10, "position_y": 10,
    })

    res = client.get("/api/sticky-notes/repo/CodeBot/orphans")
    body = res.get_json()

    assert res.status_code == 200
    assert body["count"] == 1
    # ולא סומן כמיותם — הקובץ באמת קיים בעץ
    assert body.get("orphaned") is not True


def test_orphan_routes_live_outside_the_subtree(client):
    """שני ראוטי היתומים נגישים, ואינם מתנגשים בנתיב קובץ."""
    _mirror(client.db)
    assert client.get("/api/sticky-notes/repo-orphans/CodeBot").status_code == 200
    assert client.get("/api/sticky-notes/orphan-repos").status_code == 200


# ---------- יצירה ----------

def test_create_repo_note_writes_both_target_fields(client):
    _mirror(client.db)
    res = client.post(
        "/api/sticky-notes/repo/CodeBot/webapp/app.py",
        json={"content": "צריך לבדוק את הפונקציה הזו"},
    )

    assert res.status_code == 201
    doc = client.db.sticky_notes.docs[0]
    assert doc["repo_name"] == "CodeBot"
    assert doc["repo_path"] == "webapp/app.py"
    # ואין זליגה של שדות יעד אחרים
    assert "file_id" not in doc and "board_id" not in doc and "scope_id" not in doc


def test_create_normalizes_path_on_write(client):
    """נתיב לא-מנורמל נכתב בצורה המנורמלת — אותה צורה שהקריאה מחפשת."""
    _mirror(client.db, paths=("docs/guide.rst",))
    res = client.post(
        "/api/sticky-notes/repo/CodeBot/docs/../docs/guide.rst", json={"content": "x"}
    )
    assert res.status_code == 201
    assert client.db.sticky_notes.docs[0]["repo_path"] == "docs/guide.rst"


@pytest.mark.parametrize(
    "lookup",
    [
        "docs/guide.rst",            # הצורה המנורמלת
        "docs//guide.rst",           # לוכסן כפול
        "./docs/guide.rst",          # ``.`` מוביל
        "docs/../docs/guide.rst",    # ``..`` פנימי
    ],
)
def test_note_written_unnormalized_is_found_over_http(client, lookup):
    """**שני הקצוות מתכנסים — מקצה לקצה, דרך ה-HTTP.**

    הפתק נכתב בצורה אחת ונקרא בכל צורה שקולה. הנתב מעביר את הנתיב
    **הגולמי** (נבדק: ``docs//guide.rst`` מגיע כמות שהוא), ולכן אם
    הנרמול היה רץ רק בכתיבה — הקריאה הייתה מחזירה אפס בלי לזרוק כלום.

    נופלת אם ``list_repo_notes`` מפסיק לנרמל את ``repo_path``.
    """
    _mirror(client.db, paths=("docs/guide.rst",))
    created = client.post(
        "/api/sticky-notes/repo/CodeBot/docs/../docs/guide.rst", json={"content": "x"}
    )
    assert created.status_code == 201

    res = client.get(f"/api/sticky-notes/repo/CodeBot/{lookup}")
    assert res.get_json()["count"] == 1


def test_create_on_unmirrored_repo_is_rejected(client):
    """ריפו שאינו ממורר ⇒ 404, ולא פתק שלא ייראה בשום ממשק."""
    _mirror(client.db, repo="CodeBot")
    res = client.post("/api/sticky-notes/repo/SomeOtherRepo/a.py", json={"content": "x"})
    assert res.status_code == 404
    assert res.get_json()["error"] == "repo_not_found"
    assert client.db.sticky_notes.docs == []


def test_create_on_path_outside_the_tree_is_rejected(client):
    """**ריפו ממורר אינו מספיק — גם הקובץ חייב להיות בעץ.**

    נתיב שאינו ב-``repo_files`` הוא בדיוק מה שמסלול הקריאה מסמן
    ``orphaned``. בלי השער הזה הפתק היה נולד יתום: נספר בתקרת הקובץ,
    מופיע ברשימת היתומים, ולא נראה בשום קובץ.

    נופל אם בדיקת ``_repo_file_exists`` תוסר מהיצירה.
    """
    _mirror(client.db, paths=("webapp/app.py",))
    res = client.post("/api/sticky-notes/repo/CodeBot/webapp/gone.py", json={"content": "x"})
    assert res.status_code == 404
    assert res.get_json()["error"] == "repo_file_not_found"
    assert client.db.sticky_notes.docs == []


def test_create_rejected_when_file_lookup_fails(client):
    """כשל בקריאת המניפסט נסגר (503), לא נפתח.

    אותו כלל של רשימת המראות ושל ``check_note_quota``: קריאה שנכשלה אינה
    עדות שהקובץ קיים, ולכן אינה רשיון לכתוב.

    נופל אם ``None`` מ-``_repo_file_exists`` ייקרא כ"קיים".
    """
    _mirror(client.db)

    class _Boom(_StubColl):
        def find_one(self, *a, **k):
            raise RuntimeError("manifest unavailable")

    client.db.repo_files = _Boom()
    res = client.post("/api/sticky-notes/repo/CodeBot/webapp/app.py", json={"content": "x"})
    assert res.status_code == 503
    assert res.get_json()["error"] == "repo_file_unavailable"
    assert client.db.sticky_notes.docs == []


def test_traversal_path_is_rejected(client):
    """בריחה מעל שורש הריפו נדחית ב-400, ולא מייצרת פתק."""
    _mirror(client.db)
    res = client.post("/api/sticky-notes/repo/CodeBot/../../etc/passwd", json={"content": "x"})
    assert res.status_code == 400
    assert client.db.sticky_notes.docs == []


def test_anchored_mode_is_rejected(client):
    """``anchored`` דורש שורת מקור, והעיגון כאן הוא ברמת קובץ."""
    _mirror(client.db)
    res = client.post(
        "/api/sticky-notes/repo/CodeBot/webapp/app.py",
        json={"content": "x", "mode": "anchored"},
    )
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_mode"


# ---------- מכסה ----------

def test_repo_file_cap_is_enforced_even_for_admin(client, monkeypatch):
    """**התקרה לקובץ נאכפת גם על אדמין — אחרת היא לא נאכפת על אף אחד.**

    דפדפן הריפו חסום לאדמינים, ולכן ``is_admin=is_admin_user`` היה הופך
    את ``MAX_NOTES_PER_REPO_FILE`` לקבוע מת שנראה חי.

    נופלת אם הראוט יעביר את ``is_admin`` האמיתי במקום ``False``.
    """
    from sticky_notes_target import MAX_NOTES_PER_REPO_FILE
    from webapp import sticky_notes_api

    monkeypatch.setattr(sticky_notes_api, "_current_user_is_admin", lambda: True)
    _mirror(client.db)
    for i in range(MAX_NOTES_PER_REPO_FILE):
        client.db.sticky_notes.docs.append({
            "_id": i, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py",
        })

    res = client.post("/api/sticky-notes/repo/CodeBot/webapp/app.py", json={"content": "x"})
    assert res.status_code == 409
    assert res.get_json()["error"] == "note_quota_exceeded"


def test_repo_quota_fails_closed_when_count_fails(client, monkeypatch):
    """ספירה שנכשלה ⇒ דחייה — ומבודד ל-cap-לקובץ בלבד.

    **הבידוד קריטי.** ``count_fails=True`` מפיל **כל** ספירה, כולל ספירת
    תקרת המשתמש. עם משתמש רגיל, גם אם בדיקת ה-cap-לקובץ הייתה מוסרת
    לגמרי, ספירת המשתמש הייתה זורקת ``note_quota_unknown`` והטסט היה עובר
    — fake positive. משתמש **אדמין** פוטר את תקרת המשתמש (``is_admin=True``
    שם), ולכן ה-409 יכול לבוא **רק** מה-cap-לקובץ (שנקרא עם ``is_admin=False``).

    נופל אם בדיקת ה-cap-לקובץ תוסר.
    """
    from webapp import sticky_notes_api
    monkeypatch.setattr(sticky_notes_api, "_current_user_is_admin", lambda: True)
    _mirror(client.db)
    client.db.sticky_notes.count_fails = True
    res = client.post("/api/sticky-notes/repo/CodeBot/webapp/app.py", json={"content": "x"})
    assert res.status_code == 409
    assert res.get_json()["error"] == "note_quota_unknown"


def test_create_rejected_when_mirror_list_unavailable(client, monkeypatch):
    """כשל בקריאת רשימת המראות נסגר (503), לא נפתח.

    ``None`` אינו "אין ריפואים" — קריאה שנכשלה אינה רשיון ליצור פתק על
    ריפו שאולי אינו ממורר.

    נופל אם המסלול חוזר להתנהגות ``if known is not None and ...``.
    """
    class _Boom(_StubColl):
        def distinct(self, *a, **k):
            raise RuntimeError("mirror list unavailable")

    client.db.repo_metadata = _Boom()
    res = client.post("/api/sticky-notes/repo/CodeBot/webapp/app.py", json={"content": "x"})
    assert res.status_code == 503
    assert res.get_json()["error"] == "repo_list_unavailable"
    assert client.db.sticky_notes.docs == []


def test_malformed_payload_is_400_not_500(client):
    """גוף שאינו אובייקט, או position/size לא-אובייקט — 400, לא 500.

    ``position`` ו-``size`` מאומתים בשני ``if`` נפרדים בראוט, ולכן שניהם
    נבדקים כאן: בדיקה של אחד בלבד הייתה מפספסת רגרסיה בשני.
    """
    _mirror(client.db, paths=("webapp/app.py", "a.py"))
    r1 = client.post("/api/sticky-notes/repo/CodeBot/a.py", json=["not", "an", "object"])
    assert r1.status_code == 400
    r2 = client.post("/api/sticky-notes/repo/CodeBot/webapp/app.py",
                     json={"content": "x", "position": [1, 2]})
    assert r2.status_code == 400
    r3 = client.post("/api/sticky-notes/repo/CodeBot/webapp/app.py",
                     json={"content": "x", "size": [1, 2]})
    assert r3.status_code == 400
    assert client.db.sticky_notes.docs == []


def test_duplicate_title_rejected_by_index(client, monkeypatch):
    """כשהאינדקס אומת — כפילות שם נדחית ע"י המסד (DuplicateKeyError ⇒ 409)."""
    from webapp import sticky_notes_api
    monkeypatch.setattr(sticky_notes_api, "_REPO_TITLE_INDEX_OK", True, raising=False)
    _mirror(client.db)
    client.db.sticky_notes.duplicate_titles = True
    res = client.post("/api/sticky-notes/repo/CodeBot/webapp/app.py",
                      json={"content": "x", "title": "תפוס"})
    assert res.status_code == 409
    assert res.get_json()["error"] == "duplicate_title"


def test_duplicate_title_rejected_by_backup_when_index_unverified(client, monkeypatch):
    """כשהאינדקס לא אומת — בדיקת הגיבוי תופסת את הכפילות (409).

    שולט בדגל במפורש (``False``) כדי שמצב fixture לא ישפיע על התוצאה.
    """
    from webapp import sticky_notes_api
    monkeypatch.setattr(sticky_notes_api, "_REPO_TITLE_INDEX_OK", False, raising=False)
    _mirror(client.db)
    client.db.sticky_notes.docs.append({
        "_id": 1, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py",
        "title": "תפוס", "content": "קיים",
    })
    res = client.post("/api/sticky-notes/repo/CodeBot/webapp/app.py",
                      json={"content": "x", "title": "תפוס"})
    assert res.status_code == 409
    assert res.get_json()["error"] == "duplicate_title"


# ---------- עדכון ----------

def test_update_repo_note_title_uses_the_repo_backup_check(client, monkeypatch):
    """**בדיקת הגיבוי בעדכון נבחרת לפי סוג היעד.**

    ``_title_conflict`` יוצא מיד כשאין ``board_id`` — ולפתק ריפו אין — ולכן
    כשאינדקס הריפו לא אומת, העדכון לא היה נבדק בשום מקום: לא בקוד ולא
    במסד. שני פתקים על אותו קובץ היו מקבלים את אותו שם, וה-API היה מחזיר
    ``ok: true``.

    נופל אם העדכון חוזר לקרוא ל-``_title_conflict`` על פתק ריפו.
    """
    from bson import ObjectId
    from webapp import sticky_notes_api

    monkeypatch.setattr(sticky_notes_api, "_REPO_TITLE_INDEX_OK", False, raising=False)
    _mirror(client.db)
    taken, mine = ObjectId(), ObjectId()
    client.db.sticky_notes.docs += [
        {"_id": taken, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py",
         "title": "תפוס", "content": "קיים"},
        {"_id": mine, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py",
         "content": "שלי"},
    ]

    res = client.put(f"/api/sticky-notes/note/{mine}", json={"title": "תפוס"})

    assert res.status_code == 409
    assert res.get_json()["error"] == "duplicate_title"
    # ובעיקר: השם לא נכתב
    assert "title" not in client.db.sticky_notes.docs[1]


def test_update_repo_note_title_allows_a_free_name(client, monkeypatch):
    """שם פנוי על אותו קובץ עובר — הבדיקה החדשה אינה חוסמת עדכון תקין."""
    from bson import ObjectId
    from webapp import sticky_notes_api

    monkeypatch.setattr(sticky_notes_api, "_REPO_TITLE_INDEX_OK", False, raising=False)
    _mirror(client.db)
    mine = ObjectId()
    client.db.sticky_notes.docs.append(
        {"_id": mine, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py",
         "content": "שלי"}
    )

    res = client.put(f"/api/sticky-notes/note/{mine}", json={"title": "פנוי"})

    assert res.status_code == 200
    assert client.db.sticky_notes.docs[0]["title"] == "פנוי"


# ---------- קומה ראשונה: קובץ שנעלם ----------

def test_list_flags_note_whose_file_left_the_tree(client):
    """הקובץ אינו במניפסט ⇒ הפתק מסומן מיותם, אבל עדיין מוחזר."""
    _mirror(client.db, paths=("webapp/app.py",))
    client.db.sticky_notes.docs.append({
        "_id": 1, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/deleted.py",
        "content": "פתק על קובץ שנמחק",
    })

    body = client.get("/api/sticky-notes/repo/CodeBot/webapp/deleted.py").get_json()
    assert body["count"] == 1          # לא נעלם
    assert body["orphaned"] is True    # אבל מסומן


def test_repo_orphans_lists_only_missing_paths(client):
    _mirror(client.db, paths=("webapp/app.py",))
    client.db.sticky_notes.docs += [
        {"_id": 1, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py", "content": "חי"},
        {"_id": 2, "user_id": 7, "repo_name": "CodeBot", "repo_path": "gone.py", "content": "יתום"},
    ]

    body = client.get("/api/sticky-notes/repo-orphans/CodeBot").get_json()
    assert body["count"] == 1
    assert body["notes"][0]["repo_path"] == "gone.py"
    # טריות המראה מוצגת — "מיותם" נגזר מהמראה ולא מ-GitHub
    assert body["last_sync_time"] == "2026-08-24T10:00:00Z"


def test_orphans_unknown_when_notes_query_returns_no_cursor(client):
    """**``None`` הוא ערוץ כשל, לא רק חריגה.**

    שאילתה שהחזירה ``None`` אינה זורקת כלום, והקוד המשיך עם רשימה ריקה
    ועם ``unknown: false`` — כלומר "לא הצלחנו לקרוא" הוצג כ"אין יתומים".
    זה בדיוק הדפוס K11: כשל שמדווח בערך החזרה ונבלע.

    נופל אם ``cursor is None`` יחזור להיקרא כרשימה ריקה.
    """
    _mirror(client.db)

    client.db.sticky_notes = _NullSortColl()
    body = client.get("/api/sticky-notes/repo-orphans/CodeBot").get_json()
    assert body["unknown"] is True
    assert body["count"] == 0


def test_repo_list_fails_loudly_when_query_returns_no_cursor(client):
    """אותו כלל בקריאת הפתקים של קובץ: ``None`` הוא כשל, לא "אין פתקים".

    ``notes: []`` כאן אינו רק תצוגה חסרה — הלקוח כותב את התשובה לקאש
    המקומי, ולכן קריאה שנכשלה הייתה **מוחקת** את הפתקים ששמורים בו.
    """
    _mirror(client.db)

    client.db.sticky_notes = _NullSortColl()
    res = client.get("/api/sticky-notes/repo/CodeBot/webapp/app.py")
    assert res.status_code == 500
    assert res.get_json()["ok"] is False


def test_orphans_unknown_when_manifest_unreadable(client):
    """מניפסט שלא נקרא אינו "אין יתומים" — הוא "לא ידוע"."""
    _mirror(client.db)
    client.db.repo_files.distinct_fails = True
    body = client.get("/api/sticky-notes/repo-orphans/CodeBot").get_json()
    assert body["unknown"] is True


def test_list_does_not_flag_orphan_when_lookup_fails(client):
    """כשל שאילתה אינו ראיה שהקובץ נעלם — ולכן לא מסמנים."""
    _mirror(client.db)

    class _Boom(_StubColl):
        def find_one(self, *a, **k):
            raise RuntimeError("mirror unavailable")

    client.db.repo_files = _Boom()
    client.db.sticky_notes.docs.append({
        "_id": 1, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py", "content": "x",
    })

    body = client.get("/api/sticky-notes/repo/CodeBot/webapp/app.py").get_json()
    assert body.get("orphaned") is not True


# ---------- קומה שנייה: ריפו שנעלם ----------

def test_notes_of_unmirrored_repo_are_listed(client):
    """**בלי הקומה הזו, פתקים של ריפו שהוסר לא מופיעים בשום תצוגה.**

    לא בעץ שלו — כי אין עץ; ולא ברשימת היתומים — כי היא פר-ריפו. זה
    בדיוק "המצב שנעלם בשקט".

    נופלת בלי ``distinct`` מול רשימת המראות.
    """
    _mirror(client.db, repo="CodeBot")
    client.db.sticky_notes.docs += [
        {"_id": 1, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py", "content": "חי"},
        {"_id": 2, "user_id": 7, "repo_name": "OldRepo", "repo_path": "a.py", "content": "ריפו שנעלם"},
        {"_id": 3, "user_id": 7, "repo_name": "OldRepo", "repo_path": "b.py", "content": "עוד אחד"},
    ]

    body = client.get("/api/sticky-notes/orphan-repos").get_json()
    assert body["count"] == 1
    assert body["repos"][0]["repo_name"] == "OldRepo"
    assert body["repos"][0]["notes"] == 2


def test_orphan_repos_reports_unknown_when_mirror_list_fails(client):
    """אין רשימת מראות ⇒ לא מדווחים על אף ריפו כיתום."""
    client.db.sticky_notes.docs.append(
        {"_id": 1, "user_id": 7, "repo_name": "X", "repo_path": "a.py", "content": "x"}
    )
    client.db.repo_metadata.distinct_fails = True

    body = client.get("/api/sticky-notes/orphan-repos").get_json()
    assert body["unknown"] is True
    assert body["repos"] == []


def test_orphan_repos_ignores_file_and_board_notes(client):
    """פתקי קובץ/לוח אין להם ``repo_path``, ולכן אינם נספרים כאן כלל."""
    _mirror(client.db)
    client.db.sticky_notes.docs += [
        {"_id": 1, "user_id": 7, "file_id": "abc", "content": "פתק קובץ"},
        {"_id": 2, "user_id": 7, "board_id": "b1", "content": "פתק לוח"},
    ]

    body = client.get("/api/sticky-notes/orphan-repos").get_json()
    assert body["count"] == 0


# ---------- אי-דליפה, מקצה לקצה ----------

def test_repo_listing_does_not_return_file_or_board_notes(client):
    """שאילתת הריפו אינה תופסת פתקים מסוגים אחרים."""
    _mirror(client.db)
    client.db.sticky_notes.docs += [
        {"_id": 1, "user_id": 7, "file_id": "abc", "content": "פתק קובץ"},
        {"_id": 2, "user_id": 7, "board_id": "b1", "content": "פתק לוח"},
        {"_id": 3, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py", "content": "ריפו"},
    ]

    body = client.get("/api/sticky-notes/repo/CodeBot/webapp/app.py").get_json()
    assert body["count"] == 1
    assert body["notes"][0]["content"] == "ריפו"


def test_another_users_repo_notes_are_not_visible(client):
    """הבידוד לפי ``user_id`` נשמר גם ביעד השלישי."""
    _mirror(client.db)
    client.db.sticky_notes.docs.append({
        "_id": 1, "user_id": 999, "repo_name": "CodeBot", "repo_path": "webapp/app.py",
        "content": "של מישהו אחר",
    })

    body = client.get("/api/sticky-notes/repo/CodeBot/webapp/app.py").get_json()
    assert body["count"] == 0


def test_batch_repo_note_title_uses_the_repo_backup_check(client, monkeypatch):
    """**גם ``/batch`` בוחר את הבדיקה לפי סוג היעד, לא רק ``PUT /note``.**

    זה המסלול שהלקוח באמת משתמש בו: ``_queueSave`` מאגד שמירות ושולח
    ל-``/batch``. כשהפיצול היה משוכפל, ``update_note`` קיבל אותו ו-``batch``
    נשאר עם ``_title_conflict`` — שיוצא מיד בלי ``board_id`` — ולכן דווקא
    המסלול השקוף לא אכף כלום.

    נופל אם ``batch`` חוזר לקרוא ל-``_title_conflict`` ישירות.
    """
    from bson import ObjectId
    from webapp import sticky_notes_api
    monkeypatch.setattr(sticky_notes_api, "_REPO_TITLE_INDEX_OK", False, raising=False)
    _mirror(client.db)
    taken, mine = ObjectId(), ObjectId()
    client.db.sticky_notes.docs.extend([
        {"_id": taken, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py",
         "title": "תפוס", "content": "קיים"},
        {"_id": mine, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py",
         "title": "אחר", "content": "שלי"},
    ])

    res = client.post("/api/sticky-notes/batch",
                      json={"updates": [{"id": str(mine), "title": "תפוס"}]})

    assert res.status_code == 200
    result = res.get_json()["results"][0]
    assert result["ok"] is False
    assert result["status"] == 409
    assert result["error"] == "duplicate_title"
    assert client.db.sticky_notes.docs[1]["title"] == "אחר", "השם לא שונה"


def test_board_note_title_still_uses_the_board_check(client, monkeypatch):
    """הפיצול לא שבר את מסלול הלוח — אותה דחייה, מאותו גיבוי.

    בלי הרגרסיה הזו, דיספצ'ר ששולח **הכול** לבדיקת הריפו היה מכבה בשקט
    את אכיפת השם בלוחות.
    """
    from bson import ObjectId
    from webapp import sticky_notes_api
    monkeypatch.setattr(sticky_notes_api, "_TITLE_INDEX_OK", False, raising=False)
    taken, mine = ObjectId(), ObjectId()
    client.db.sticky_notes.docs.extend([
        {"_id": taken, "user_id": 7, "board_id": "b1", "title": "תפוס", "content": "קיים"},
        {"_id": mine, "user_id": 7, "board_id": "b1", "title": "אחר", "content": "שלי"},
    ])

    res = client.put(f"/api/sticky-notes/note/{mine}", json={"title": "תפוס"})

    assert res.status_code == 409
    assert res.get_json()["error"] == "duplicate_title"


# ---------- המסלול שהמסד אוכף: DuplicateKeyError בעדכון ----------

def test_update_duplicate_title_from_the_index_is_409(client, monkeypatch):
    """**זה המסלול האמיתי בפרודקשן.** כשהאינדקס מאומת, בדיקת הגיבוי בקוד
    יוצאת מיד ואף אחד לא בודק כלום — האכיפה כולה היא ``DuplicateKeyError``
    מהמסד, ש-``update_note`` חייב לתרגם ל-409 ולא ל-500.

    כל שאר טסטי כפילות-השם בעדכון מכבים את דגל האינדקס ובודקים רק את
    הגיבוי; בלי הטסט הזה, רגרסיה בתרגום החריגה לא הייתה נתפסת.
    """
    from bson import ObjectId
    from webapp import sticky_notes_api
    monkeypatch.setattr(sticky_notes_api, "_REPO_TITLE_INDEX_OK", True, raising=False)
    _mirror(client.db)
    client.db.sticky_notes.enforce_unique_titles = True
    taken, mine = ObjectId(), ObjectId()
    client.db.sticky_notes.docs.extend([
        {"_id": taken, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py",
         "title": "תפוס", "content": "קיים"},
        {"_id": mine, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py",
         "title": "אחר", "content": "שלי"},
    ])

    res = client.put(f"/api/sticky-notes/note/{mine}", json={"title": "תפוס"})

    assert res.status_code == 409
    assert res.get_json()["error"] == "duplicate_title"


def test_batch_duplicate_title_from_the_index_is_409(client, monkeypatch):
    """אותו מסלול ב-``/batch`` — שם הלקוח באמת שומר."""
    from bson import ObjectId
    from webapp import sticky_notes_api
    monkeypatch.setattr(sticky_notes_api, "_REPO_TITLE_INDEX_OK", True, raising=False)
    _mirror(client.db)
    client.db.sticky_notes.enforce_unique_titles = True
    taken, mine = ObjectId(), ObjectId()
    client.db.sticky_notes.docs.extend([
        {"_id": taken, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py",
         "title": "תפוס", "content": "קיים"},
        {"_id": mine, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py",
         "title": "אחר", "content": "שלי"},
    ])

    res = client.post("/api/sticky-notes/batch",
                      json={"updates": [{"id": str(mine), "title": "תפוס"}]})

    assert res.status_code == 200
    result = res.get_json()["results"][0]
    assert result["ok"] is False
    assert result["status"] == 409
    assert result["error"] == "duplicate_title"


def test_update_to_a_free_title_still_succeeds_under_the_index(client, monkeypatch):
    """הרגרסיה הנגדית: עם אינדקס פעיל, שם פנוי עדיין נשמר.

    בלי הטסט הזה, סטאב שזורק על **כל** שינוי שם (כפי שהיה) היה מייצר
    "אכיפה" שמכשילה גם עדכונים תקינים — והטסטים היו ירוקים.
    """
    from bson import ObjectId
    from webapp import sticky_notes_api
    monkeypatch.setattr(sticky_notes_api, "_REPO_TITLE_INDEX_OK", True, raising=False)
    _mirror(client.db)
    client.db.sticky_notes.enforce_unique_titles = True
    mine = ObjectId()
    client.db.sticky_notes.docs.append(
        {"_id": mine, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py",
         "title": "אחר", "content": "שלי"}
    )

    res = client.put(f"/api/sticky-notes/note/{mine}", json={"title": "חדש ופנוי"})

    assert res.status_code == 200
    assert client.db.sticky_notes.docs[-1]["title"] == "חדש ופנוי"


# -- בוטסטראפ האינדקסים בוובאפ ------------------------------------------

class _FallbackIdxColl:
    """אוסף שמפיל את המסלול המהיר, ואת האינדקס שבוחרים לו במסלול הגיבוי."""

    def __init__(self, fail_name=None):
        self.fail_name = fail_name
        self.built = []

    def create_indexes(self, models):          # המסלול המהיר
        raise RuntimeError("no pymongo typings")

    def create_index(self, keys, name=None, **kw):
        if name == self.fail_name:
            raise RuntimeError("boom")
        self.built.append(name)

    def index_information(self):
        # מחזיר גם ``key``, כי האימות משווה מפתחות ולא רק שמות
        from webapp.sticky_notes_api import _QUERY_INDEX_SPECS

        by_name = dict(_QUERY_INDEX_SPECS)
        return {n: {"key": list(by_name.get(n, []))} for n in self.built}


def _run_bootstrap(coll, monkeypatch):
    """מריץ את ``_ensure_indexes`` האמיתי מול אוסף מזויף.

    **הגלובלים משוחזרים בסוף, ולא רק נקבעים בהתחלה.** ``_ensure_indexes``
    כותב ל-``_INDEX_READY``/``_TITLE_INDEX_OK``/``_REPO_TITLE_INDEX_OK``
    דרך ``global``, ו-``monkeypatch`` אינו רואה השמה שנעשית **בתוך**
    הפונקציה — הוא משחזר רק את הערך שהוא עצמו קבע. בלי השחזור הידני כאן,
    שלושת הטסטים היו משאירים את המודול במצב "אינדקסים מוכנים ואכיפה
    חיה" לשארית הסשן, וכל טסט אחר שמייבא אותו היה מקבל מסלול שונה **לפי
    סדר ההרצה**.
    """
    import webapp.sticky_notes_api as api

    class _DB:
        sticky_notes = coll
        note_boards = _FallbackIdxColl()
        note_reminders = _FallbackIdxColl()

    saved = {
        n: getattr(api, n)
        for n in ("_INDEX_READY", "_TITLE_INDEX_OK", "_REPO_TITLE_INDEX_OK", "_INDEX_RETRY_AFTER")
    }
    monkeypatch.setattr(api, "get_db", lambda: _DB())
    monkeypatch.setattr(api, "_cache_flag_ready", lambda: False)
    monkeypatch.setattr(api, "_mark_cache_flag", lambda: None)  # לא נוגעים בקאש משותף
    monkeypatch.setattr(api, "ensure_title_index", lambda c: True)
    monkeypatch.setattr(api, "ensure_repo_title_index", lambda c: True)
    api._INDEX_READY = False
    api._INDEX_RETRY_AFTER = 0.0
    try:
        api._ensure_indexes()
        return api
    finally:
        for name, value in saved.items():
            setattr(api, name, value)


def test_one_failing_fallback_index_does_not_skip_the_rest(monkeypatch):
    """**``try`` יחיד סביב הרשימה הופך אותה לשרשרת.**

    כשל באינדקס הראשון היה מדלג על ששת הבאים, והם לא היו נבנים לעולם —
    בלי שום שגיאה. האינדקס האחרון ברשימה הוא הקורבן הסביר ביותר.

    נופלת אם ה-``try`` יחזור לעטוף את הלולאה כולה.
    """
    from webapp.sticky_notes_api import _QUERY_INDEX_SPECS

    coll = _FallbackIdxColl(fail_name="user_file_idx")
    _run_bootstrap(coll, monkeypatch)

    assert "user_file_idx" not in coll.built            # זה אכן נכשל
    assert set(coll.built) == {n for n, _ in _QUERY_INDEX_SPECS} - {"user_file_idx"}
    assert "user_title_idx" in coll.built               # האחרון ברשימה נבנה


def test_a_missing_query_index_is_reported_not_swallowed(monkeypatch, caplog):
    """**ערך החזרה של כתיבה אינו אימות.**

    ``create_index`` מדווח הצלחה בערך ההחזרה, ובסביבת stub הוא no-op.
    בלי קריאה חוזרת, אינדקס שלא נבנה נעלם בשקט.

    נופלת אם האימות ב-``index_information`` יוסר.
    """
    import logging

    coll = _FallbackIdxColl(fail_name="user_title_idx")
    with caplog.at_level(logging.ERROR):
        _run_bootstrap(coll, monkeypatch)

    assert any("user_title_idx" in r.getMessage() for r in caplog.records), caplog.text


def test_a_missing_query_index_does_not_block_readiness(monkeypatch):
    """אינדקס שאילתה חסר הוא האטה, לא באג נכונות.

    חסימת ``_INDEX_READY`` עליו הייתה מריצה את הבוטסטראפ כולו בכל בקשה,
    לנצח, בכל סביבת stub. שני אינדקסי **השם** כן חוסמים — הם אכיפה.
    """
    coll = _FallbackIdxColl(fail_name="user_title_idx")
    ready = {}

    import webapp.sticky_notes_api as api

    real = api._mark_indexes_ready
    monkeypatch.setattr(
        api, "_mark_indexes_ready",
        lambda duration_ms=None: ready.setdefault("marked", True),
    )
    _run_bootstrap(coll, monkeypatch)

    # נבדק דרך הקריאה עצמה ולא דרך הגלובל, כי ``_run_bootstrap`` משחזר
    # אותו — והשחזור הזה הוא מה ששומר על בידוד שאר הסוויטה.
    assert ready.get("marked") is True
    assert real is not None


def test_the_bootstrap_tests_leave_no_state_behind(monkeypatch):
    """**דליפת גלובלים היא באג תלוי-סדר, וזה הגרוע שבסוגים.**

    ``_ensure_indexes`` כותב ל-``_INDEX_READY``/``_TITLE_INDEX_OK``/
    ``_REPO_TITLE_INDEX_OK`` דרך ``global``. ``monkeypatch`` אינו רואה
    השמה שנעשית **בתוך** הפונקציה — הוא משחזר רק ערך שהוא עצמו קבע.
    בלי שחזור מפורש, כל טסט אחר שמייבא את המודול היה מקבל מסלול אחר לפי
    סדר ההרצה: אכיפה דרך אינדקס במקום גיבוי בקוד, או להפך.

    נופלת אם ה-``finally`` שמשחזר ב-``_run_bootstrap`` יוסר.
    """
    import webapp.sticky_notes_api as api

    names = ("_INDEX_READY", "_TITLE_INDEX_OK", "_REPO_TITLE_INDEX_OK", "_INDEX_RETRY_AFTER")
    before = {n: getattr(api, n) for n in names}

    _run_bootstrap(_FallbackIdxColl(), monkeypatch)

    assert {n: getattr(api, n) for n in names} == before


def test_verification_flags_an_index_that_exists_with_other_keys(monkeypatch, caplog):
    """**שם זהה ומפתחות שונים הוא בדיוק המצב ששקט מסתיר.**

    מונגו דוחה יצירה כזו ב-``code 85/86``, ובדיקה לפי שם בלבד הייתה
    מדווחת "קיים" — והשאילתה ממשיכה ב-COLLSCAN בלי שאיש יידע.

    נופלת אם האימות יחזור להשוות שמות בלבד.
    """
    import logging

    class _StaleColl(_FallbackIdxColl):
        def index_information(self):
            info = super().index_information()
            if "user_title_idx" in info:
                info["user_title_idx"] = {"key": [("user_id", 1), ("content", 1)]}
            return info

    with caplog.at_level(logging.ERROR):
        _run_bootstrap(_StaleColl(), monkeypatch)

    assert any("different key spec" in r.getMessage() for r in caplog.records), caplog.text
