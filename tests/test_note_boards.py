"""בדיקות ל-``note_boards`` — לוח ברירת המחדל וריפוי פתקים יתומים.

התבנית היא זו שכבר בשימוש ב-``tests/test_sticky_notes_api.py``: stub של
אוסף בפייתון טהור, בלי pymongo ובלי ספריות mock, כדי שהבדיקה תוכל לתאר גם
מצבים שקשה לייצר מול מסד אמיתי — למשל כתיבה שמדווחת הצלחה ולא נקלטה.
"""

import pytest

from note_boards import (
    DEFAULT_BOARD_NAME,
    board_order,
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


def _sorted_names(*boards):
    """שמות הלוחות כפי ש-``list_boards`` מחזירה אותם. ``order`` נקבע לפי המיקום ברשימה — כלומר סדר
    היצירה הוא הסדר שבו הלוחות כתובים בטסט, והוא בכוונה **שונה** מהסדר שמצופה בתוצאה."""
    docs = [
        {"_id": index + 1, "user_id": 7, "name": name, "order": index, **extra}
        for index, (name, extra) in enumerate(boards)
    ]
    return [b["name"] for b in list_boards(_StubDB(boards=_StubColl(docs)), 7)]


def test_hebrew_boards_first_then_english_by_abc():
    """עברית בסדר הא'-ב', אחריה אנגלית בסדר ה-ABC — ולא סדר היצירה. ``מCLAUDE.md`` בעברית: מספיקה אות
    עברית אחת בהתחלה. ``amir`` לפני ``Markdown_Ck``: בלי הבדל בין אותיות גדולות לקטנות."""
    names = _sorted_names(
        ("לוח עבודה", {"is_default": True}),
        ("To CC", {}),
        ("פריימר", {}),
        ("מCLAUDE.md", {}),
        ("amir bug patterns", {}),
        ("ארכיון", {}),
        ("Markdown_Ck", {}),
        ("מודלים", {}),
    )

    assert names == [
        "לוח עבודה",
        "ארכיון",
        "מCLAUDE.md",
        "מודלים",
        "פריימר",
        "amir bug patterns",
        "Markdown_Ck",
        "To CC",
    ]


def test_default_board_stays_first_even_against_the_alphabet():
    """לוח ברירת המחדל ראשון גם כשהשם שלו היה נופל אחרון — באנגלית, אחרי כל העברית."""
    names = _sorted_names(("ארכיון", {}), ("Zebra", {"is_default": True}), ("בית", {}))

    assert names == ["Zebra", "ארכיון", "בית"]


def test_the_first_letter_decides_not_the_first_character():
    """אימוג'י, ספרה או סימן בתחילת השם אינם אות: הקבוצה והמיון לפי האות הראשונה. שם בלי אף אות —
    בסוף."""
    names = _sorted_names(
        ("🎉", {}),
        ("2026 plan", {}),
        ("📌 משימות", {}),
        ("#ideas", {}),
        ("123", {}),
        ("בית", {}),
    )

    assert names == ["בית", "📌 משימות", "#ideas", "2026 plan", "123", "🎉"]


def test_accents_and_niqqud_do_not_move_a_name():
    """ניקוד ואקסנטים אינם אות נפרדת: ``École`` בין ``Delta`` ל-``Ezra``, ו-``שָׁלוֹם`` אחרי ``שלב``
    (ב' לפני ו'). בלי ההשמטה é היה אחרי כל האנגלית, וסימני הניקוד — לפני כל אות."""
    names = _sorted_names(("Ezra", {}), ("שָׁלוֹם", {}), ("École", {}), ("שלב", {}), ("Delta", {}))

    assert names == ["שלב", "שָׁלוֹם", "Delta", "École", "Ezra"]


def test_a_final_letter_sorts_as_the_regular_letter():
    """ם היא מ': ההכרעה בין ``אםב`` ל-``אמא`` עוברת לאות השלישית, וא' לפני ב'. בלי ההמרה הסופית הייתה
    נחשבת אות נפרדת שקודמת למ', ו-``אםב`` היה ראשון."""
    names = _sorted_names(("אםב", {}), ("אמא", {}))

    assert names == ["אמא", "אםב"]


def test_same_name_keeps_creation_order():
    """שני לוחות באותו שם בדיוק: ``order`` (סדר היצירה) מכריע ביניהם, ולכן הסדר קבוע בכל טעינה."""
    docs = [
        {"_id": 1, "user_id": 7, "name": "רעיונות", "order": 5},
        {"_id": 2, "user_id": 7, "name": "רעיונות", "order": 2},
    ]

    ids = [b["_id"] for b in list_boards(_StubDB(boards=_StubColl(docs)), 7)]
    assert ids == [2, 1]


@pytest.mark.parametrize(
    "stored, expected",
    [
        (7, 7),
        ("7", 7),
        (3.0, 3),
        (None, 0),
        ("", 0),
        ("abc", 0),  # ValueError
        (float("nan"), 0),  # ValueError
        (float("inf"), 0),  # OverflowError
        ([1], 0),  # TypeError
        ({"a": 1}, 0),  # TypeError
    ],
)
def test_board_order_is_zero_for_what_int_rejects(stored, expected):
    """מה ש-``int`` מקבל עובר כמו קודם; מה שהוא זורק עליו — 0, ולא חריגה."""
    assert board_order({"order": stored}) == expected


def test_board_order_of_a_board_without_the_field_is_zero():
    assert board_order({}) == 0


def test_a_corrupted_order_does_not_break_the_list():
    """מסמך עם ``order`` פגום אינו מפיל את הרשימה (עד היום — ``ValueError`` מתוך המיון). הערך הפגום נחשב 0:
    בין שלושה לוחות באותו שם, שני הפגומים לפני זה שה-``order`` שלו 3, וביניהם לפי המזהה."""
    docs = [
        {"_id": 1, "user_id": 7, "name": "רעיונות", "order": "abc"},
        {"_id": 2, "user_id": 7, "name": "רעיונות", "order": 3},
        {"_id": 3, "user_id": 7, "name": "רעיונות", "order": float("inf")},
    ]

    ids = [b["_id"] for b in list_boards(_StubDB(boards=_StubColl(docs)), 7)]
    assert ids == [1, 3, 2]


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


# -- board_names_by_id --


class _NamesColl:
    """``note_boards`` לשליפת שמות: מסנן לפי ``_id`` ב-``$in`` ולפי ``user_id``, ורושם כל שאילתה."""

    def __init__(self, docs=(), *, fail=None):
        self.docs = list(docs)
        self.fail = fail
        self.calls = []

    def find(self, query, projection=None):
        self.calls.append((query, projection))
        if self.fail is not None:
            raise self.fail
        wanted = query["_id"]["$in"]
        return [
            {"_id": d["_id"], "name": d.get("name")} for d in self.docs
            if d["_id"] in wanted and d.get("user_id") == query["user_id"]
        ]


def test_board_names_by_id_reads_all_the_names_in_one_query_of_the_users_boards():
    from bson import ObjectId

    from note_boards import board_names_by_id

    ideas, work, foreign = ObjectId(), ObjectId(), ObjectId()
    coll = _NamesColl([
        {"_id": ideas, "user_id": 7, "name": "רעיונות"},
        {"_id": work, "user_id": 7, "name": "לוח עבודה"},
        {"_id": foreign, "user_id": 99, "name": "של מישהו אחר"},
    ])

    names = board_names_by_id(coll, 7, [str(ideas), str(work), str(ideas), str(foreign)])

    assert names == {str(ideas): "רעיונות", str(work): "לוח עבודה"}
    assert len(coll.calls) == 1
    query, projection = coll.calls[0]
    assert query["user_id"] == 7 and projection == {"name": 1}
    assert sorted(map(str, query["_id"]["$in"])) == sorted([str(ideas), str(work), str(foreign)])


def test_board_names_by_id_skips_ids_that_are_not_object_ids_and_does_not_query_without_one():
    from bson import ObjectId

    from note_boards import board_names_by_id

    board = ObjectId()
    coll = _NamesColl([{"_id": board, "user_id": 7, "name": "רעיונות"}])

    assert board_names_by_id(coll, 7, ["not-an-object-id", "", None]) == {}
    assert coll.calls == []
    assert board_names_by_id(coll, 7, ["not-an-object-id", str(board)]) == {str(board): "רעיונות"}


def test_board_names_by_id_lets_a_database_failure_through():
    """מפה ריקה הייתה נראית כמו "אין לוחות כאלה" — כל קורא רושם את הכשל בלוג שלו."""
    import pytest
    from bson import ObjectId
    from pymongo.errors import AutoReconnect

    from note_boards import board_names_by_id

    coll = _NamesColl(fail=AutoReconnect("down"))
    with pytest.raises(AutoReconnect):
        board_names_by_id(coll, 7, [str(ObjectId())])
