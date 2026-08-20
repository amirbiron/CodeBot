"""בדיקות ל-``note_boards`` — לוח ברירת המחדל וריפוי פתקים יתומים.

התבנית היא זו שכבר בשימוש ב-``tests/test_sticky_notes_api.py``: stub של
אוסף בפייתון טהור, בלי pymongo ובלי ספריות mock, כדי שהבדיקה תוכל לתאר גם
מצבים שקשה לייצר מול מסד אמיתי — למשל כתיבה שמדווחת הצלחה ולא נקלטה.
"""

from note_boards import (
    DEFAULT_BOARD_NAME,
    ensure_default_board,
    list_boards,
    normalize_board_name,
    reattach_orphan_notes,
)


class _StubColl:
    """אוסף מינימלי. ``insert_fails`` מדמה דחייה של המסד (מרוץ/אינדקס ייחודי)."""

    def __init__(self, docs=None, *, insert_fails=False):
        self.docs = list(docs or [])
        self.insert_fails = insert_fails
        self.inserted = []
        self.updates = []
        self._next_id = 100

    def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    def find(self, query):
        return [d for d in self.docs if all(d.get(k) == v for k, v in query.items())]

    def insert_one(self, doc):
        self.inserted.append(dict(doc))
        if self.insert_fails:
            raise RuntimeError("E11000 duplicate key")
        doc = dict(doc)
        doc["_id"] = self._next_id
        self._next_id += 1
        self.docs.append(doc)
        return type("Res", (), {"inserted_id": doc["_id"]})()

    def count_documents(self, query):
        return len(self._matching(query))

    def update_many(self, query, update):
        self.updates.append((query, update))
        for doc in self._matching(query):
            doc.update(update.get("$set", {}))
        return type("Res", (), {"modified_count": 1})()

    def _matching(self, query):
        out = []
        for doc in self.docs:
            ok = True
            for key, cond in query.items():
                value = doc.get(key)
                if isinstance(cond, dict):
                    if "$nin" in cond and value in cond["$nin"]:
                        ok = False
                    if "$exists" in cond and (key in doc) != cond["$exists"]:
                        ok = False
                    if "$ne" in cond and value == cond["$ne"]:
                        ok = False
                elif value != cond:
                    ok = False
            if ok:
                out.append(doc)
        return out


class _StubDB:
    def __init__(self, boards=None, notes=None):
        self.note_boards = boards if boards is not None else _StubColl()
        self.sticky_notes = notes if notes is not None else _StubColl()


# -- normalize_board_name --

def test_blank_name_falls_back_to_default():
    """לוח בלי שם אינו ניתן לזיהוי בממשק."""
    assert normalize_board_name("") == DEFAULT_BOARD_NAME
    assert normalize_board_name("   ") == DEFAULT_BOARD_NAME
    assert normalize_board_name(None) == DEFAULT_BOARD_NAME


def test_name_whitespace_is_collapsed_and_capped():
    assert normalize_board_name("  לוח   שלי  ") == "לוח שלי"
    assert len(normalize_board_name("x" * 500)) == 120


# -- ensure_default_board --

def test_creates_default_board_when_missing():
    db = _StubDB()
    board_id = ensure_default_board(db, 7)

    assert board_id is not None
    created = db.note_boards.docs[0]
    assert created["user_id"] == 7
    assert created["name"] == DEFAULT_BOARD_NAME
    assert created["is_default"] is True


def test_is_idempotent():
    """קריאה שנייה לא יוצרת לוח שני — היא נקראת בכל טעינת רשימה."""
    db = _StubDB()
    first = ensure_default_board(db, 7)
    second = ensure_default_board(db, 7)

    assert first == second
    assert len(db.note_boards.docs) == 1


def test_identifies_by_flag_not_by_name():
    """לוח ברירת מחדל ששמו שונה עדיין מזוהה.

    זו הסיבה המרכזית שלא חיקינו את "שולחן עבודה" באוספים, שמזוהה לפי
    השוואת מחרוזת. האפיון מרשה במפורש לשנות את שם לוח ברירת המחדל, ולכן
    זיהוי לפי שם היה נשבר בפעולה חוקית לגמרי.
    """
    db = _StubDB(boards=_StubColl([
        {"_id": 55, "user_id": 7, "name": "הלוח האישי שלי", "is_default": True},
    ]))

    assert ensure_default_board(db, 7) == "55"
    assert len(db.note_boards.docs) == 1


def test_race_loser_returns_the_winners_board():
    """הכתיבה נדחתה, אבל הלוח קיים — ולכן מחזירים אותו ולא ``None``.

    זה בדיוק המרוץ שהאינדקס הייחודי-החלקי ``one_default_per_user`` מייצר:
    שתי בקשות מקבילות מגלות שאין לוח, שתיהן מנסות ליצור, והמסד דוחה את
    השנייה. הבדיקה נופלת אם מסיקים מהצלחת/כשלון הכתיבה במקום לקרוא שוב.
    """
    boards = _StubColl(insert_fails=True)
    db = _StubDB(boards=boards)

    # המנצח כותב בין הבדיקה לכתיבה שלנו
    def _insert_then_win(doc, _orig=boards.insert_one):
        boards.docs.append({"_id": 99, "user_id": 7, "name": DEFAULT_BOARD_NAME, "is_default": True})
        return _orig(doc)

    boards.insert_one = _insert_then_win

    assert ensure_default_board(db, 7) == "99"


def test_returns_none_when_board_absent_after_write():
    """כתיבה שלא נקלטה ואין לוח — מדווחים כישלון, לא מזהה מדומה."""
    boards = _StubColl(insert_fails=True)
    db = _StubDB(boards=boards)

    assert ensure_default_board(db, 7) is None


def test_successful_insert_that_did_not_land_is_not_trusted():
    """``inserted_id`` שחזר אינו ראיה שהמסמך קיים.

    זו הבדיקה שמגנה על הקריאה החוזרת. ה-stub מדווח הצלחה ומחזיר מזהה,
    אבל לא מוסיף את המסמך — בדיוק הדפוס שבו כתיבה "מצליחה" ולא נקלטת.
    בלי האימות הפונקציה הייתה מחזירה מזהה של לוח שאינו קיים, וכל פתק
    שהיה נוחת עליו נעלם מהממשק.

    אומת במוטציה: החזרת ``inserted_id`` ישירות מפילה בדיוק את הטסט הזה.
    """
    boards = _StubColl()
    boards.insert_one = lambda doc: type("Res", (), {"inserted_id": 12345})()
    db = _StubDB(boards=boards)

    assert ensure_default_board(db, 7) is None


def test_no_collection_is_survivable():
    assert ensure_default_board(object(), 7) is None


# -- list_boards --

def test_default_board_sorts_first():
    db = _StubDB(boards=_StubColl([
        {"_id": 2, "user_id": 7, "name": "ב", "order": 1},
        {"_id": 1, "user_id": 7, "name": "ברירת מחדל", "is_default": True, "order": 9},
        {"_id": 3, "user_id": 7, "name": "א", "order": 0},
    ]))

    names = [b["name"] for b in list_boards(db, 7)]
    assert names == ["ברירת מחדל", "א", "ב"]


# -- reattach_orphan_notes --

def test_orphan_notes_move_to_default():
    """פתק שמצביע ללוח שנעלם חוזר לברירת המחדל — הקישור מתוקן, לא הפתק."""
    notes = _StubColl([
        {"_id": 1, "user_id": 7, "board_id": "gone"},
        {"_id": 2, "user_id": 7, "board_id": "alive"},
    ])
    db = _StubDB(notes=notes)

    moved = reattach_orphan_notes(db, 7, ["alive", "home"], "home")

    assert moved == 1
    assert notes.docs[0]["board_id"] == "home"
    assert notes.docs[1]["board_id"] == "alive"


def test_file_notes_are_untouched():
    """פתק קובץ אינו נושא ``board_id`` ולכן אינו נסרק."""
    notes = _StubColl([{"_id": 1, "user_id": 7, "file_id": "f1"}])
    db = _StubDB(notes=notes)

    assert reattach_orphan_notes(db, 7, ["home"], "home") == 0
    assert "board_id" not in notes.docs[0]


def test_moved_count_comes_from_a_recount_not_from_the_write():
    """הספירה היא הפרש בין שתי קריאות, ולא ``modified_count``.

    ``update_many`` כאן מדווח ``modified_count=1`` תמיד, גם כשלא זז דבר.
    בלי הקריאה החוזרת הפונקציה הייתה מדווחת על העברה שלא קרתה.
    """
    notes = _StubColl([{"_id": 1, "user_id": 7, "board_id": "gone"}])
    notes.update_many = lambda q, u: type("Res", (), {"modified_count": 1})()
    db = _StubDB(notes=notes)

    assert reattach_orphan_notes(db, 7, ["home"], "home") == 0


def test_nothing_to_do_skips_the_write_entirely():
    notes = _StubColl([{"_id": 1, "user_id": 7, "board_id": "home"}])
    db = _StubDB(notes=notes)

    assert reattach_orphan_notes(db, 7, ["home"], "home") == 0
    assert notes.updates == []


def test_missing_default_id_is_a_noop():
    """בלי יעד אין לאן להעביר — לא נוגעים בפתקים."""
    notes = _StubColl([{"_id": 1, "user_id": 7, "board_id": "gone"}])
    db = _StubDB(notes=notes)

    assert reattach_orphan_notes(db, 7, ["alive"], "") == 0
    assert notes.docs[0]["board_id"] == "gone"
