"""טסטים ל-handlers של הפתקים הדביקים ב-MCP (list/create/update).

הכול הרמטי: fake backend שמקליט kwargs, בלי Flask ובלי Mongo. את נכונות
ה-scope בודקים מול make_scope_id האמיתי (sticky_notes_scope בשורש — מודול טהור).
"""

from mcp_server import handlers
from mcp_server.backend import _as_note, _NoteIndex, _notes_scope_filter
from mcp_server.handlers import (
    DEFAULT_NOTE_COLOR,
    MAX_NOTE_CONTENT,
    NOTE_FLOATING_ANCHOR,
    _sanitize_note_text,
)


class _NotesBackend:
    """Fake שמקליט את הקריאה האחרונה ומחזיר תשובת הצלחה קבועה."""

    def __init__(self):
        self.calls = []

    def list_notes(self, user_id, *, file_name):
        self.calls.append(("list", user_id, file_name))
        return {"ok": True, "file_name": file_name, "count": 0, "notes": []}

    def create_note(self, user_id, *, file_name, content, line, color, anchor_text, anchor_id):
        self.calls.append(
            (
                "create",
                user_id,
                {
                    "file_name": file_name,
                    "content": content,
                    "line": line,
                    "color": color,
                    "anchor_text": anchor_text,
                    "anchor_id": anchor_id,
                },
            )
        )
        return {"ok": True, "note": {"id": "a" * 24, "content": content}}

    def update_note(self, user_id, *, note_id, fields):
        self.calls.append(("update", user_id, note_id, dict(fields)))
        return {"ok": True, "note": {"id": note_id, **fields}}

    @property
    def last_kwargs(self):
        return self.calls[-1][2]


# -- sanitizer --------------------------------------------------------------


def test_sanitize_normalizes_crlf_and_strips_control_chars():
    assert _sanitize_note_text("a\r\nb\rc") == "a\nb\nc"
    assert _sanitize_note_text("xyz") == "xyz"
    assert _sanitize_note_text("שלום\tעולם") == "שלום\tעולם"  # טאב מותר, כמו בוובאפ


def test_sanitize_unescapes_html_entities_and_handles_none():
    assert _sanitize_note_text("&quot;ציטוט&quot;") == '"ציטוט"'
    assert _sanitize_note_text(None) == ""


# -- list_notes -------------------------------------------------------------


def test_list_notes_requires_file_name():
    be = _NotesBackend()
    assert handlers.list_notes(be, 7, file_name="  ") == {
        "ok": False,
        "error": "missing_file_name",
    }
    assert be.calls == []


def test_list_notes_strips_name_and_delegates():
    be = _NotesBackend()
    out = handlers.list_notes(be, 7, file_name=" notes.md ")
    assert out["ok"] is True
    assert be.calls[0] == ("list", 7, "notes.md")


# -- create_note ------------------------------------------------------------


def test_create_note_rejects_empty_and_control_only_content():
    be = _NotesBackend()
    assert handlers.create_note(be, 7, file_name="a.md", content="  ")["error"] == "empty_content"
    assert handlers.create_note(be, 7, file_name="a.md", content="")["error"] == "empty_content"
    assert be.calls == []


def test_create_note_rejects_oversize_content():
    be = _NotesBackend()
    out = handlers.create_note(be, 7, file_name="a.md", content="x" * (MAX_NOTE_CONTENT + 1))
    assert out == {"ok": False, "error": "content_too_long", "max": MAX_NOTE_CONTENT}
    assert be.calls == []


def test_create_note_sanitizes_content():
    be = _NotesBackend()
    handlers.create_note(be, 7, file_name="a.md", content="a\r\nb&quot;c")
    assert be.last_kwargs["content"] == 'a\nb"c'


def test_create_note_invalid_line_rejected():
    be = _NotesBackend()
    for bad in (0, -3, "x", 10**7):
        out = handlers.create_note(be, 7, file_name="a.md", content="hi", line=bad)
        assert out["error"] == "invalid_line", bad
    assert be.calls == []


def test_create_note_without_line_sets_floating_sentinel():
    be = _NotesBackend()
    handlers.create_note(be, 7, file_name="a.md", content="hi")
    assert be.last_kwargs["anchor_id"] == NOTE_FLOATING_ANCHOR
    assert be.last_kwargs["line"] is None


def test_create_note_with_line_sets_no_sentinel():
    be = _NotesBackend()
    handlers.create_note(be, 7, file_name="a.md", content="hi", line=42)
    assert be.last_kwargs["anchor_id"] is None
    assert be.last_kwargs["line"] == 42


def test_create_note_color_default_and_fallback():
    be = _NotesBackend()
    handlers.create_note(be, 7, file_name="a.md", content="hi")
    assert be.last_kwargs["color"] == DEFAULT_NOTE_COLOR
    handlers.create_note(be, 7, file_name="a.md", content="hi", color="red")
    assert be.last_kwargs["color"] == DEFAULT_NOTE_COLOR  # לא-חוקי ⇒ ברירת מחדל
    handlers.create_note(be, 7, file_name="a.md", content="hi", color="#AABBCC")
    assert be.last_kwargs["color"] == "#AABBCC"


def test_create_note_anchor_text_trimmed_and_capped():
    be = _NotesBackend()
    handlers.create_note(be, 7, file_name="a.md", content="hi", anchor_text=" " + "t" * 300)
    assert be.last_kwargs["anchor_text"] == "t" * 256
    handlers.create_note(be, 7, file_name="a.md", content="hi", anchor_text="   ")
    assert be.last_kwargs["anchor_text"] is None


# -- update_note ------------------------------------------------------------


def test_update_note_rejects_bad_note_id():
    be = _NotesBackend()
    for bad in ("", "zzz", "a" * 23, "g" * 24):
        out = handlers.update_note(be, 7, note_id=bad, content="x")
        assert out == {"ok": False, "error": "invalid_note_id"}, bad
    assert be.calls == []


def test_update_note_requires_some_field():
    be = _NotesBackend()
    out = handlers.update_note(be, 7, note_id="a" * 24)
    assert out == {"ok": False, "error": "no_fields_to_update"}
    # צבע לא-חוקי בעדכון נשמט — ואם זה השדה היחיד, אין מה לעדכן
    out = handlers.update_note(be, 7, note_id="a" * 24, color="red")
    assert out == {"ok": False, "error": "no_fields_to_update"}
    assert be.calls == []


def test_update_note_line_clears_anchor_fields():
    be = _NotesBackend()
    handlers.update_note(be, 7, note_id="a" * 24, line=7)
    assert be.calls[0][3] == {"line_start": 7, "anchor_id": None, "line_end": None}


def test_update_note_partial_fields_forwarded():
    be = _NotesBackend()
    handlers.update_note(be, 7, note_id="b" * 24, content="new", is_minimized=1)
    fields = be.calls[0][3]
    assert fields == {"content": "new", "is_minimized": True}  # רק מה שנמסר, bool אמיתי


def test_update_note_rejects_empty_and_oversize_content():
    be = _NotesBackend()
    assert handlers.update_note(be, 7, note_id="a" * 24, content="  ")["error"] == "empty_content"
    out = handlers.update_note(be, 7, note_id="a" * 24, content="x" * (MAX_NOTE_CONTENT + 1))
    assert out["error"] == "content_too_long"
    assert be.calls == []


# -- scope filter + serialization (מול make_scope_id האמיתי) ---------------


def test_notes_scope_filter_matches_webapp_shape():
    from sticky_notes_scope import make_scope_id

    sid = make_scope_id(42, "Notes.md")
    assert sid is not None and sid.startswith("user:42:file:")
    assert len(sid.rsplit(":", 1)[-1]) == 16  # 16 תווי hex
    # נרמול רווחים ואותיות — שמות שקולים מקבלים אותו scope
    assert make_scope_id(42, "  notes.MD ") == sid
    assert make_scope_id(42, "notes  .md") == make_scope_id(42, "notes .md")

    q = _notes_scope_filter(42, sid, ["id1", "id2"])
    assert q == {"user_id": 42, "$or": [{"scope_id": sid}, {"file_id": {"$in": ["id1", "id2"]}}]}
    assert _notes_scope_filter(42, sid, []) == {"user_id": 42, "$or": [{"scope_id": sid}]}


def test_notes_scope_filter_without_clauses_matches_nothing():
    """בלי scope ובלי related — שאילתה שלא תופסת דבר, לא "הכול".

    הטענה כאן הייתה קודם ``== {"user_id": 42}``, כלומר היא **קיבעה באג**:
    שאילתה כזו מחזירה את כל הפתקים של המשתמש במקום את הפתקים של הקובץ
    שהתבקש. היום המסלול הזה לא נגיש, כי ``scope_id`` תמיד מחושב משם קובץ
    לא-ריק — אבל עם פתקי לוח, פתק שאינו שייך לשום קובץ היה נשאב לתשובה של
    ``list_notes`` על קובץ אקראי.

    ``{"_id": {"$in": []}}`` הוא הביטוי המפורש ל"אין לי לפי מה לחפש".
    """
    assert _notes_scope_filter(42, None, []) == {"user_id": 42, "_id": {"$in": []}}


def test_as_note_serialization():
    import datetime as dt

    doc = {
        "_id": "OID",
        "content": "a &quot;b&quot;",
        "color": "#FFFFCC",
        "line_start": 3,
        "anchor_text": None,
        "is_minimized": False,
        "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        "updated_at": dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc),
        "position_x": 120,  # שדה ויזואלי — לא נחשף
    }
    out = _as_note(doc)
    assert out["id"] == "OID"
    assert out["content"] == 'a "b"'  # פתקי legacy עם entities משוחזרים
    assert out["line_start"] == 3
    assert out["created_at"].startswith("2026-01-01")
    assert out["updated_at"].startswith("2026-01-02")
    assert "position_x" not in out
    assert set(out) == {
        "id",
        "content",
        "color",
        "line_start",
        "anchor_text",
        "is_minimized",
        # פתק לוח חייב לומר איפה הוא יושב. בפתק קובץ שניהם ריקים.
        "board_id",
        "mode",
        # שם הפתק — תווית שמזהה אותו בתוך הלוח
        "title",
        # יעד הריפו, משני חצאיו. ``update_note`` מחזיר ``_as_note``, ובלי
        # שניהם עדכון פתק ריפו מדווח על פתק בלי שום יעד.
        "repo_name",
        "repo_path",
        "created_at",
        "updated_at",
    }


def test_as_note_reports_where_a_board_note_sits():
    """``board_id`` ו-``mode`` אינם קישוט — בלעדיהם הפלט לא אומר כלום על מיקום.

    בלי הבדיקה הזו, הרחבת הקבוצה הסגורה למעלה הייתה חותמת גומי: היא הייתה
    עוברת גם אם השדות תמיד ריקים.
    """
    out = _as_note({"_id": "OID", "content": "x", "board_id": "b1", "mode": "screen"})

    assert out["board_id"] == "b1"
    assert out["mode"] == "screen"


def test_as_note_leaves_board_fields_empty_for_a_file_note():
    """מסלול הקובץ לא משתנה — שני השדות ריקים ואינם ממציאים לוח."""
    out = _as_note({"_id": "OID", "content": "x", "file_id": "f1", "line_start": 5})

    assert not out["board_id"]
    assert not out["mode"]


# ---------- לוחות פתקים ----------
#
# עד כאן ה-MCP הכיר רק פתקים שצמודים לקובץ. הלוחות הם משטח שני לאותם
# פתקים, ולכן הבדיקות כאן מתמקדות בשני דברים שהם **לא** חיווט: בעלות, ותקרה
# שמתנהגת נכון כשהספירה נכשלת.

from mcp_server import handlers as _h  # noqa: E402


class _BoardsBackend:
    """Backend מדומה בפייתון טהור, בתבנית ``_NotesBackend`` שכבר בקובץ."""

    def __init__(self):
        self.calls = []

    def list_boards(self, user_id):
        self.calls.append(("list_boards", user_id))
        return {"ok": True, "count": 1, "boards": [{"id": "a" * 24, "name": "לוח עבודה"}]}

    def list_board_notes(self, user_id, *, board_id):
        self.calls.append(("list_board_notes", user_id, board_id))
        return {"ok": True, "board_id": board_id, "count": 0, "notes": []}

    def create_board_note(self, user_id, *, board_id, content, color, mode, title=""):
        self.calls.append(("create_board_note", user_id, board_id, content, color, mode, title))
        return {"ok": True, "note": {"id": "n1", "board_id": board_id, "mode": mode}}


_VALID_BOARD = "a" * 24


def test_board_id_must_be_an_object_id():
    """מזהה פגום נעצר בשער, בלי לגעת במסד.

    בלי הבדיקה הזו כל מחרוזת הייתה עוברת ל-``ObjectId(...)`` ומייצרת חריגה
    במקום תשובה מסודרת.
    """
    b = _BoardsBackend()

    for bad in ("", "   ", "not-an-id", "a" * 23, "z" * 24):
        res = _h.list_board_notes(b, 7, board_id=bad)
        assert res == {"ok": False, "error": "invalid_board_id"}, bad

    assert b.calls == [], "מזהה פגום לא אמור להגיע ל-backend"


def test_create_board_note_also_gates_on_the_board_id():
    """הכתיבה נעצרת על מזהה פגום בדיוק כמו הקריאה.

    שני ה-handlers חולקים את אותו שער; בלי בדיקה מקבילה, שינוי באחד היה
    יכול להשאיר את השני פתוח.
    """
    b = _BoardsBackend()

    for bad in ("", "   ", "not-an-id", "a" * 23, "z" * 24):
        res = _h.create_board_note(b, 7, board_id=bad, content="x")
        assert res == {"ok": False, "error": "invalid_board_id"}, bad

    assert b.calls == [], "מזהה פגום לא אמור להגיע ל-backend"


def test_create_board_note_rejects_empty_and_overlong_content():
    from sticky_notes_target import MAX_NOTE_CHARS

    b = _BoardsBackend()

    assert _h.create_board_note(b, 7, board_id=_VALID_BOARD, content="   ")["error"] == "empty_content"

    over = _h.create_board_note(b, 7, board_id=_VALID_BOARD, content="א" * (MAX_NOTE_CHARS + 1))
    assert over["error"] == "content_too_long"
    assert over["max"] == MAX_NOTE_CHARS

    assert b.calls == []


def test_create_board_note_rejects_anchored_mode():
    """``anchored`` דורש שורות מקור, ובלוח אין כאלה.

    פתק כזה היה מחשב מיקום מול עוגן שאינו קיים — כלומר פתק שנעלם. זו הסיבה
    ש-``is_valid_board_mode`` נפרד מ-``is_valid_mode``.
    """
    b = _BoardsBackend()

    res = _h.create_board_note(b, 7, board_id=_VALID_BOARD, content="x", mode="anchored")

    assert res["error"] == "invalid_mode"
    assert res["allowed"] == ["surface", "screen"]
    assert b.calls == []


def test_create_board_note_normalizes_the_title():
    """שם מנורמל לפני שהוא מגיע למסד: רווחים, שורות, ואורך.

    שם רב-שורות היה שובר את שורת הכפתורים, ושם ריק חייב להישאר ריק כדי
    שהשדה כלל לא ייכתב — אחרת הוא נכנס לאינדקס הייחודי ומתנגש.
    """
    from sticky_notes_target import MAX_NOTE_TITLE

    b = _BoardsBackend()
    _h.create_board_note(b, 7, board_id=_VALID_BOARD, content="x", title="  שם\nעם שורות  ")
    assert b.calls[0][6] == "שם עם שורות"

    b2 = _BoardsBackend()
    _h.create_board_note(b2, 7, board_id=_VALID_BOARD, content="x", title="   ")
    assert b2.calls[0][6] == "", "שם ריק נשאר ריק, והשדה לא ייכתב"

    b3 = _BoardsBackend()
    _h.create_board_note(b3, 7, board_id=_VALID_BOARD, content="x", title="א" * 200)
    assert len(b3.calls[0][6]) == MAX_NOTE_TITLE


def test_create_board_note_normalizes_color_and_mode():
    b = _BoardsBackend()

    _h.create_board_note(b, 7, board_id=_VALID_BOARD, content="שלום", color="לא-צבע")

    _, _, _, content, color, mode, _title = b.calls[0]
    assert content == "שלום"
    assert color == _h.DEFAULT_NOTE_COLOR, "צבע לא חוקי נופל לברירת המחדל, כמו ביצירת פתק קובץ"
    assert mode == "surface", "ברירת המחדל בלוח"


# ---------- מכונת המצבים של אינדקס השם ב-MCP ----------
#
# ``create_board_note`` מבטיח ``duplicate_title``. ההבטחה נשענת על אינדקס
# שנבנה כאן, ולכן מסלולי הכשל שלה הם חלק מהחוזה ולא פרט פנימי.


class _IndexSpyColl:
    """אוסף מדומה שסופר קריאות ומאפשר לשלוט בתוצאת הבנייה."""

    def __init__(self):
        self.index_calls = 0
        self.find_calls = []
        self.inserted = []
        self.result = True
        self.raises = False

    # -- מה ש-``ensure_title_index`` המדומה תצרוך --
    def create_index(self, *a, **k):
        return None

    def index_information(self):
        return {}

    # -- מה ש-``title_is_taken`` צורכת --
    def find_one(self, query, projection=None):
        self.find_calls.append(query)
        for doc in self.inserted:
            if all(doc.get(k) == v for k, v in query.items() if not isinstance(v, dict)):
                return doc
        return None

    def insert_one(self, doc):
        self.inserted.append(dict(doc))

        class _R:
            inserted_id = len(self.inserted)

        return _R()

    def count_documents(self, *a, **k):
        return len(self.inserted)


def _verified(b, *which):
    """מסמן אינדקסים כמאומתים — כלומר בלי מסלול הגיבוי בקוד.

    נוגע ב-``_IndexGate`` ולא בדגל מחרוזתי, כי זה הייצוג שהקוד מחזיק.
    """
    from mcp_server.backend import _IndexGate

    gates = b.__dict__.setdefault("_note_index_gates", {})
    for w in which:
        gate = gates.setdefault(w, _IndexGate())
        gate.ok = True
    return b


def _backend_with(coll, monkeypatch, clock):
    """``ProductionBackend`` בלי ה-``__init__`` הכבד, עם שעון נשלט."""
    from mcp_server.backend import ProductionBackend
    import mcp_server.backend as backend_mod

    monkeypatch.setattr(backend_mod._time, "monotonic", lambda: clock["now"])
    b = ProductionBackend.__new__(ProductionBackend)
    b._notes_idx_done = True
    b._raw_mongo = lambda: {"sticky_notes": coll}
    return b


def test_a_failed_index_build_is_retried_only_after_the_cooldown(monkeypatch):
    """דגל "ניסינו" שנדלק לפני הניסיון משבית את האכיפה לכל חיי התהליך.

    כאן הוא מנסה שוב — אבל לא בכל קריאה, אחרת כל כלי משלם על בנייה
    כושלת. נופלת אם ההשהיה מוסרת, וגם אם הניסיון החוזר מוסר.
    """
    import sticky_notes_target

    clock = {"now": 500.0}
    coll = _IndexSpyColl()
    b = _backend_with(coll, monkeypatch, clock)
    attempts = []
    monkeypatch.setattr(
        sticky_notes_target, "ensure_title_index",
        lambda c: (attempts.append(clock["now"]), False)[1],
    )

    assert b._ensure_title_index(coll) is False
    assert b._ensure_title_index(coll) is False
    assert b._ensure_title_index(coll) is False
    assert len(attempts) == 1, f"נוסה {len(attempts)} פעמים בתוך חלון ההמתנה"

    clock["now"] += b._TITLE_INDEX_RETRY_SECONDS + 1
    assert b._ensure_title_index(coll) is False
    assert len(attempts) == 2, "אחרי ההשהיה לא נוסה שוב"


def test_an_exception_during_the_build_is_not_fatal(monkeypatch):
    """חריגה בבנייה מחזירה ``False``, לא מפילה את הכלי."""
    import sticky_notes_target

    clock = {"now": 500.0}
    coll = _IndexSpyColl()
    b = _backend_with(coll, monkeypatch, clock)

    def _boom(_c):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(sticky_notes_target, "ensure_title_index", _boom)

    assert b._ensure_title_index(coll) is False


def test_a_confirmed_index_is_never_rebuilt(monkeypatch):
    """אחרי אימות, אין יותר קריאות — וגם אין שאילתת גיבוי."""
    import sticky_notes_target

    clock = {"now": 500.0}
    coll = _IndexSpyColl()
    b = _backend_with(coll, monkeypatch, clock)
    attempts = []
    monkeypatch.setattr(
        sticky_notes_target, "ensure_title_index",
        lambda c: (attempts.append(1), True)[1],
    )

    assert b._ensure_title_index(coll) is True
    clock["now"] += 10_000
    assert b._ensure_title_index(coll) is True
    assert len(attempts) == 1


def test_create_board_note_falls_back_to_a_code_check_without_the_index(monkeypatch):
    """**זו ההבטחה שהכלי נותן, וזה מה שקורה כשאין מי שיאכוף אותה.**

    נופלת אם ``create_board_note`` מדלג על הגיבוי כשהאינדקס לא אומת.
    """
    import sticky_notes_target

    clock = {"now": 500.0}
    coll = _IndexSpyColl()
    b = _backend_with(coll, monkeypatch, clock)
    monkeypatch.setattr(sticky_notes_target, "ensure_title_index", lambda c: False)
    monkeypatch.setattr(b, "_notes_coll", lambda: coll)
    monkeypatch.setattr(b, "_canonical_board_id", lambda board: "b1", raising=False)
    monkeypatch.setattr(b, "_owned_board", lambda uid, bid: {"_id": "b1"}, raising=False)

    first = b.create_board_note(7, board_id="b1", content="a", color="#FFFFCC", mode="surface", title="טודו")
    assert first.get("ok") is True, first

    dup = b.create_board_note(7, board_id="b1", content="b", color="#FFFFCC", mode="surface", title="טודו")

    assert dup == {"ok": False, "error": "duplicate_title"}
    assert coll.find_calls, "הגיבוי לא נשאל בכלל"


def test_as_note_carries_a_repo_targets_two_halves():
    """**הרחבת הקבוצה הסגורה אינה חותמת גומי.**

    האסרשן שמעל בודק רק ששני המפתחות *קיימים* — והוא היה עובר גם אילו הם
    תמיד ``None``, כלומר גם אילו ``_as_note`` לא היה קורא אותם מהמסמך
    בכלל. כאן נבדק שהם נושאים את הערך של הפתק.

    נופל אם ``repo_name``/``repo_path`` יוסרו מ-``_NOTE_FIELDS``, וגם אם
    יוחזרו ריקים.
    """
    out = _as_note({"_id": "OID", "repo_name": "CodeBot", "repo_path": "webapp/app.py"})

    assert out["repo_name"] == "CodeBot"
    assert out["repo_path"] == "webapp/app.py"


# ==========================================================================
# פתקי ריפו + חיפוש — היעד השלישי ב-MCP
#
# **מה שסטאב כאן אינו יכול לבדוק:** את ה-``partialFilterExpression`` בפועל.
# ``create_index`` של ``_IndexSpyColl`` מחזיר ``None`` וכל בדיקת כפילות
# עוברת, ולכן סוויטה ירוקה כאן **אינה** ראיה שהאינדקס הייחודי אוכף משהו.
# האכיפה עצמה נבדקת מול מונגו אמיתי, מחוץ לקובץ הזה.
# ==========================================================================

class _Cursor:
    """סמן מדומה: ``find(...).sort(...).limit(n)`` — כמו pymongo, שרשור עצל.

    ``limit`` **חותך בפועל**, כי הסנטינל של החיפוש (``want + 1``) נסמך על
    כך שהמסד מחזיר לכל היותר ``n`` — סמן שמתעלם מהתקרה היה מסתיר באג.
    """

    def __init__(self, rows):
        self._rows = list(rows)
        self.sorted_by = None
        self.limited_to = None

    def sort(self, key, direction=1):
        self.sorted_by = (key, direction)
        self._rows.sort(key=lambda r: r.get(key), reverse=direction < 0)
        return self

    def limit(self, n):
        self.limited_to = n
        self._rows = self._rows[:n]
        return self

    def __iter__(self):
        return iter(self._rows)


class _RepoNotesBackend:
    """Fake בתבנית ``_BoardsBackend``, מקליט kwargs ומחזיר הצלחה קבועה."""

    def __init__(self):
        self.calls = []

    def list_repo_notes(self, user_id, *, repo_name, repo_path):
        self.calls.append(("list", user_id, {"repo_name": repo_name, "repo_path": repo_path}))
        return {"ok": True, "repo_name": repo_name, "repo_path": repo_path, "notes": []}

    def create_repo_note(self, user_id, *, repo_name, repo_path, content, color, mode, title=""):
        self.calls.append(("create", user_id, {
            "repo_name": repo_name, "repo_path": repo_path, "content": content,
            "color": color, "mode": mode, "title": title,
        }))
        return {"ok": True, "note": {"id": "n1", "repo_name": repo_name, "repo_path": repo_path}}

    def search_notes(self, user_id, *, query, limit, search_content=False):
        self.calls.append(("search", user_id, {"query": query, "limit": limit}))
        return {"ok": True, "query": query, "count": 0, "truncated": False, "notes": []}

    @property
    def last_kwargs(self):
        return self.calls[-1][2]


def _both_repo_paths(backend, **kw):
    """שני המסלולים, עם אותם ארגומנטים — לבדיקת זהות השערים."""
    return (
        handlers.list_repo_notes(backend, 7, repo_name=kw["repo_name"], repo_path=kw["repo_path"]),
        handlers.create_repo_note(backend, 7, content="שלום", **kw),
    )


def test_a_blank_repo_name_never_reaches_the_backend():
    b = _RepoNotesBackend()
    for res in _both_repo_paths(b, repo_name="  ", repo_path="a.py"):
        assert res == {"ok": False, "error": "invalid_repo_name"}
    assert b.calls == []


def test_a_repo_name_with_a_slash_is_rejected():
    """``owner/repo`` אינו מה ש-``repo_metadata`` מחזיק — פתק כזה לא יימצא לעולם."""
    b = _RepoNotesBackend()
    for res in _both_repo_paths(b, repo_name="amirbiron/CodeBot", repo_path="a.py"):
        assert res["error"] == "invalid_repo_name"
    assert b.calls == []


def test_path_traversal_is_rejected_in_both_paths():
    """``..`` נדחה — ולא "מנוקה" לנתיב אחר, שהיה שקט וגרוע יותר."""
    b = _RepoNotesBackend()
    for res in _both_repo_paths(b, repo_name="CodeBot", repo_path="../../etc/passwd"):
        assert res == {"ok": False, "error": "invalid_repo_path"}
    assert b.calls == []


def test_the_path_is_normalized_before_the_backend_sees_it():
    """**הנרמול בהנדלר, לא ב-backend.**

    ``repo_files`` שומר נתיבים בצורת git הגולמית. בלי המעבר הזה
    ``./webapp/../a.py`` היה שאילתה שאינה מוצאת דבר — בלי שום שגיאה,
    כלומר "אין פתקים" על קובץ שיש לו.
    """
    b = _RepoNotesBackend()
    handlers.list_repo_notes(b, 7, repo_name="CodeBot", repo_path="./webapp/../a.py")

    assert b.last_kwargs["repo_path"] == "a.py"


def test_both_repo_paths_derive_the_same_gates():
    """שני מסלולים עם שערים שונים = שני מושגים שונים של "יעד חוקי"."""
    b = _RepoNotesBackend()
    for bad in ("  ", "amirbiron/CodeBot", "x" * 200):
        listed, created = _both_repo_paths(b, repo_name=bad, repo_path="a.py")
        assert listed["error"] == created["error"] == "invalid_repo_name", bad
    for bad in ("", "   ", "../x"):
        listed, created = _both_repo_paths(b, repo_name="CodeBot", repo_path=bad)
        assert listed["error"] == created["error"] == "invalid_repo_path", bad
    assert b.calls == []


def test_create_repo_note_rejects_empty_and_overlong_content():
    b = _RepoNotesBackend()
    kw = {"repo_name": "CodeBot", "repo_path": "a.py"}
    assert handlers.create_repo_note(b, 7, content="   ", **kw)["error"] == "empty_content"
    long = handlers.create_repo_note(b, 7, content="א" * (MAX_NOTE_CONTENT + 1), **kw)
    assert long == {"ok": False, "error": "content_too_long", "max": MAX_NOTE_CONTENT}
    assert b.calls == []


def test_create_repo_note_rejects_anchored_mode():
    """``anchored`` דורש שורות DOM. התצוגה כאן היא CodeMirror, שאינו מרנדר
    שורות מחוץ למסך — פתק כזה היה מחשב מיקום מול עוגן שאינו קיים.

    נופלת אם הבדיקה תוחלף ב-``is_valid_mode``, שמכיר ``anchored``.
    """
    b = _RepoNotesBackend()
    res = handlers.create_repo_note(
        b, 7, repo_name="CodeBot", repo_path="a.py", content="שלום", mode="anchored"
    )
    assert res == {"ok": False, "error": "invalid_mode", "allowed": ["surface", "screen"]}
    assert b.calls == []


def test_create_repo_note_normalizes_title_color_and_mode():
    b = _RepoNotesBackend()
    handlers.create_repo_note(
        b, 7, repo_name="CodeBot", repo_path="a.py", content="שלום",
        color="not-a-color", mode=None, title="  שם   ארוך \n שני ",
    )
    kw = b.last_kwargs
    assert kw["color"] == DEFAULT_NOTE_COLOR
    assert kw["mode"] == "surface"
    assert kw["title"] == "שם ארוך שני"


# -- חיפוש --------------------------------------------------------------

def test_an_empty_query_never_reaches_the_backend():
    b = _RepoNotesBackend()
    for q in ("", "   ", None, ["a"]):
        assert handlers.search_notes(b, 7, query=q)["error"] == "empty_query"
    assert b.calls == []


def test_a_query_longer_than_any_possible_title_is_rejected():
    """**זו לא קפדנות — זו הימנעות מתשובה לשאלה אחרת.**

    שם פתק חסום ב-``MAX_NOTE_TITLE``, ולכן שאילתה ארוכה ממנו לא תתפוס
    דבר. קיצוץ שקט שלה היה מחזיר תוצאות עבור **קידומת**, והקורא היה מבין
    אותן כתשובה לשאילתה המלאה.

    נופלת אם החיתוך יחזור: ``normalize_note_title`` כבר חותך ל-80, ולכן
    בדיקת אורך על הפלט שלו היא תמיד ``False``. הבדיקה חייבת לרוץ על
    הקנוניזציה **בלי** התקרה.
    """
    from sticky_notes_target import MAX_NOTE_TITLE

    b = _RepoNotesBackend()
    res = handlers.search_notes(b, 7, query="א" * (MAX_NOTE_TITLE + 1))

    assert res == {"ok": False, "error": "query_too_long", "max": MAX_NOTE_TITLE}
    assert b.calls == []


def test_the_query_is_canonicalized_like_a_stored_title():
    """שם נשמר מכווץ לשורה אחת; שאילתה שאינה עוברת אותו נרמול לא תתפוס אותו."""
    b = _RepoNotesBackend()
    handlers.search_notes(b, 7, query="  5   PR \n ")

    assert b.last_kwargs["query"] == "5 PR"


def test_the_search_limit_is_clamped_and_not_rejected():
    """מספר גדול מדי הוא בקשה לרוחב, לא שגיאה."""
    from mcp_server.handlers import DEFAULT_NOTE_SEARCH_RESULTS, MAX_NOTE_SEARCH_RESULTS

    b = _RepoNotesBackend()
    for given, expected in (
        (9999, MAX_NOTE_SEARCH_RESULTS), (0, 1), (-5, 1),
        (None, DEFAULT_NOTE_SEARCH_RESULTS), ("שלוש", DEFAULT_NOTE_SEARCH_RESULTS), (7, 7),
    ):
        handlers.search_notes(b, 7, query="a", limit=given)
        assert b.last_kwargs["limit"] == expected, given


# -- backend של פתקי ריפו ------------------------------------------------

class _RepoDB:
    """ידית מסד מזויפת: גם ``["sticky_notes"]`` וגם ``.repo_metadata``.

    ``ProductionBackend`` ניגש לפתקים באינדוקס ולמניפסט בתכונה, ולכן
    ה-fake חייב לתמוך בשניהם — בדיוק כמו ``pymongo.Database``.
    """

    def __init__(self, coll, *, repos=("CodeBot",), files=(("CodeBot", "a.py"),),
                 meta_fails=False, files_fail=False):
        self._coll = coll
        self._repos, self._files = repos, files
        self._meta_fails, self._files_fail = meta_fails, files_fail
        self.file_queries = []

    def __getitem__(self, name):
        assert name == "sticky_notes", name
        return self._coll

    class _Meta:
        def __init__(self, outer): self._o = outer
        def distinct(self, field):
            if self._o._meta_fails:
                raise RuntimeError("db down")
            return list(self._o._repos)

    class _Files:
        def __init__(self, outer): self._o = outer
        def find_one(self, query, projection=None):
            self._o.file_queries.append(query)
            if self._o._files_fail:
                raise RuntimeError("db down")
            pair = (query.get("repo_name"), query.get("path"))
            return {"_id": 1} if pair in self._o._files else None

    @property
    def repo_metadata(self): return self._Meta(self)

    @property
    def repo_files(self): return self._Files(self)


def _repo_backend(db, monkeypatch, *, admin=False):
    from mcp_server.backend import ProductionBackend

    b = ProductionBackend.__new__(ProductionBackend)
    b._notes_idx_done = True
    # האינדקס מאומת ← בלי מסלול הגיבוי
    _verified(b, _NoteIndex.REPO_TITLE, _NoteIndex.BOARD_TITLE)
    b._raw_mongo = lambda: db
    monkeypatch.setitem(__import__("sys").modules, "user_roles",
                        type("M", (), {"is_admin": staticmethod(lambda uid: admin)}))
    return b


def test_a_missing_mirrored_repo_is_rejected_before_any_write(monkeypatch):
    coll = _IndexSpyColl()
    b = _repo_backend(_RepoDB(coll, repos=("Other",)), monkeypatch)

    res = b.create_repo_note(7, repo_name="CodeBot", repo_path="a.py",
                             content="שלום", color="#FFFFCC", mode="surface")

    assert res["error"] == "repo_not_found"
    assert coll.inserted == []


def test_a_missing_path_is_rejected_before_any_write(monkeypatch):
    coll = _IndexSpyColl()
    b = _repo_backend(_RepoDB(coll, files=()), monkeypatch)

    res = b.create_repo_note(7, repo_name="CodeBot", repo_path="gone.py",
                             content="שלום", color="#FFFFCC", mode="surface")

    assert res["error"] == "repo_file_not_found"
    assert coll.inserted == []


def test_a_failed_manifest_is_fail_closed_and_says_so(monkeypatch):
    """**"לא נענה" אינו "לא קיים".**

    ההבדל אינו סמנטי: "לא קיים" מזמין את הקורא לתקן את הנתיב, וזו עצה
    שגויה כשהמסד פשוט לא ענה. נופלת אם ``None`` ייקרא כ"חסר".
    """
    coll = _IndexSpyColl()

    b = _repo_backend(_RepoDB(coll, meta_fails=True), monkeypatch)
    assert b.create_repo_note(7, repo_name="CodeBot", repo_path="a.py",
                              content="x", color="#FFFFCC", mode="surface")["error"] == \
        "repo_list_unavailable"

    b2 = _repo_backend(_RepoDB(_IndexSpyColl(), files_fail=True), monkeypatch)
    assert b2.create_repo_note(7, repo_name="CodeBot", repo_path="a.py",
                               content="x", color="#FFFFCC", mode="surface")["error"] == \
        "repo_file_unavailable"

    assert coll.inserted == []


def test_the_per_file_cap_is_enforced_on_an_admin(monkeypatch):
    """**זה הטסט שכל ה-``False`` בלולאת המכסות קיים בשבילו.**

    כל הקוראים למשטח הזה הם אדמינים, ולכן ריוויואר ש"יסדר" את ה-``False``
    ל-``is_admin_user`` יהפוך תקרה של 20 לתקרה שאינה נאכפת על **אף אחד** —
    בלי ששום טסט אחר יבחין.
    """
    from sticky_notes_target import MAX_NOTES_PER_REPO_FILE

    coll = _IndexSpyColl()
    coll.count_documents = lambda *a, **k: MAX_NOTES_PER_REPO_FILE
    b = _repo_backend(_RepoDB(coll), monkeypatch, admin=True)

    res = b.create_repo_note(7, repo_name="CodeBot", repo_path="a.py",
                             content="שלום", color="#FFFFCC", mode="surface")

    assert res["error"] == "too_many_notes"
    assert res["max"] == MAX_NOTES_PER_REPO_FILE
    assert coll.inserted == []


def test_the_per_user_cap_does_exempt_an_admin(monkeypatch):
    """הצד השני: הפטור הכללי נשמר, אחרת ה-``False`` שמעל היה סתם קפדנות.

    התקרה-לקובץ מרוצה (0 פתקים על הקובץ), התקרה-למשתמש חצויה — ואדמין עובר.
    """
    from sticky_notes_target import MAX_NOTES_PER_USER

    coll = _IndexSpyColl()
    seen = []

    def _count(query, *a, **k):
        seen.append(query)
        return 0 if "repo_name" in query else MAX_NOTES_PER_USER

    coll.count_documents = _count
    b = _repo_backend(_RepoDB(coll), monkeypatch, admin=True)

    res = b.create_repo_note(7, repo_name="CodeBot", repo_path="a.py",
                             content="שלום", color="#FFFFCC", mode="surface")

    assert res["ok"] is True
    assert len(seen) == 2  # שתי התקרות אכן נבדקו
    assert len(coll.inserted) == 1


def test_a_failed_count_rejects_rather_than_opening_the_cap(monkeypatch):
    """תקרה שנפתחת לרווחה בדיוק כשהמסד מתקשה אינה תקרה.

    הקוד נגזר ממצב הספירה ולא מטקסט החריגה — טקסט חריגה בתשובה הוא דלף
    ממתין.
    """
    coll = _IndexSpyColl()

    def _boom(*a, **k):
        raise RuntimeError("db down")

    coll.count_documents = _boom
    b = _repo_backend(_RepoDB(coll), monkeypatch)

    res = b.create_repo_note(7, repo_name="CodeBot", repo_path="a.py",
                             content="שלום", color="#FFFFCC", mode="surface")

    assert res["error"] == "note_quota_unknown"
    assert res["count"] is None
    assert coll.inserted == []


def test_the_stored_note_carries_both_halves_of_the_target(monkeypatch):
    coll = _IndexSpyColl()
    b = _repo_backend(_RepoDB(coll), monkeypatch)

    b.create_repo_note(7, repo_name="CodeBot", repo_path="a.py",
                       content="שלום", color="#FFFFCC", mode="surface", title="שם")

    doc = coll.inserted[0]
    assert doc["repo_name"] == "CodeBot" and doc["repo_path"] == "a.py"
    assert "board_id" not in doc and "file_id" not in doc  # יעד אחד בלבד


def test_a_repo_note_without_a_title_stores_no_title_field(monkeypatch):
    """``title: ""`` היה נכנס לאינדקס הייחודי, ושני פתקים כאלה היו מתנגשים."""
    coll = _IndexSpyColl()
    b = _repo_backend(_RepoDB(coll), monkeypatch)

    b.create_repo_note(7, repo_name="CodeBot", repo_path="a.py",
                       content="שלום", color="#FFFFCC", mode="surface", title="")

    assert "title" not in coll.inserted[0]


def test_orphaned_is_flagged_only_on_an_explicit_missing_file(monkeypatch):
    """**תקלת מסד חולפת אינה מסמנת קובץ חי כמיותם.**

    ובכל שלושת המצבים הפתקים עצמם חוזרים: קובץ שנמחק מהריפו אינו סיבה
    להעלים את מה שנכתב עליו.
    """
    coll = _IndexSpyColl()
    coll.inserted.append({"_id": 1, "repo_name": "CodeBot", "repo_path": "a.py"})
    coll.find = lambda q, *a, **k: _Cursor(list(coll.inserted))

    present = _repo_backend(_RepoDB(coll), monkeypatch).list_repo_notes(
        7, repo_name="CodeBot", repo_path="a.py")
    missing = _repo_backend(_RepoDB(coll, files=()), monkeypatch).list_repo_notes(
        7, repo_name="CodeBot", repo_path="a.py")
    unknown = _repo_backend(_RepoDB(coll, files_fail=True), monkeypatch).list_repo_notes(
        7, repo_name="CodeBot", repo_path="a.py")

    assert "orphaned" not in present
    assert missing["orphaned"] is True
    assert "orphaned" not in unknown          # ``None`` אינו "מיותם"
    assert present["count"] == missing["count"] == unknown["count"] == 1


def test_listing_normalizes_the_path_it_reports_back(monkeypatch):
    coll = _IndexSpyColl()
    coll.find = lambda q, *a, **k: _Cursor([])
    b = _repo_backend(_RepoDB(coll), monkeypatch)

    out = b.list_repo_notes(7, repo_name="CodeBot", repo_path="./a.py")

    assert out["repo_path"] == "a.py"


# -- backend של החיפוש ----------------------------------------------------

class _SearchColl(_IndexSpyColl):
    """מקליט את השאילתה, הפרויקציה, המיון והתקרה שהחיפוש ביקש."""

    def __init__(self, rows=()):
        super().__init__()
        self.rows = list(rows)
        self.query = None
        self.projection = None
        self.cursor = None

    def find(self, query, projection=None):
        self.query, self.projection = query, projection
        self.cursor = _Cursor(self.rows)
        return self.cursor


class _SnippetColl:
    """``code_snippets`` מזויף — מקליט את השאילתות שהמילוי שולח."""

    def __init__(self, docs):
        self.docs = list(docs)
        self.queries = []

    def find(self, query, projection=None):
        self.queries.append(query)
        wanted = {str(o) for o in query.get("_id", {}).get("$in", [])}
        return [d for d in self.docs if str(d["_id"]) in wanted]


def _search_backend(coll):
    from mcp_server.backend import ProductionBackend

    b = ProductionBackend.__new__(ProductionBackend)
    b._notes_idx_done = True
    b._raw_mongo = lambda: {"sticky_notes": coll}
    return b


def _row(i, **kw):
    import datetime as dt
    base = {"_id": f"id{i}", "title": f"פתק {i}",
            "updated_at": dt.datetime(2026, 1, i + 1, tzinfo=dt.timezone.utc)}
    base.update(kw)
    return base


def test_search_never_asks_the_database_for_note_content():
    """**הפרויקציה נושאת משקל ואינה קוסמטיקה.**

    היא אוכפת "שם בלבד" בגבול המסד ולא בסמך הסריאלייזר, ובכך מנתקת את
    עלות החיפוש מגודל גוף הפתק (עד 20K תווים למסמך).

    נופלת אם הפרויקציה תוסר — ואז ``content`` נשלף לכל פגיעה.
    """
    coll = _SearchColl()
    _search_backend(coll).search_notes(7, query="פתק", limit=10)

    assert coll.projection is not None
    assert "content" not in coll.projection
    assert set(coll.projection) >= {"title", "file_name", "board_id", "repo_name", "repo_path"}


def test_search_is_scoped_to_the_caller_and_escaped():
    coll = _SearchColl()
    _search_backend(coll).search_notes(7, query="a.py", limit=10)

    assert coll.query["user_id"] == 7
    assert coll.query["title"]["$regex"] == "a\\.py"   # הנקודה מנוטרלת


def test_search_asks_for_one_row_beyond_the_limit():
    """**``truncated`` הוא עובדה ולא ניחוש.**

    שורה נוספת שחזרה היא ראיה שיש עוד; ספירה ששווה לתקרה אינה ראיה לכלום.
    נופלת אם ה-``+ 1`` יוסר.
    """
    coll = _SearchColl(rows=[_row(i) for i in range(10)])
    out = _search_backend(coll).search_notes(7, query="פתק", limit=3)

    assert coll.cursor.limited_to == 4
    assert out["truncated"] is True
    assert out["count"] == 3            # שורת הסנטינל נחתכה ואינה מוחזרת
    assert len(out["notes"]) == 3


def test_search_reports_no_truncation_when_the_page_is_not_full():
    coll = _SearchColl(rows=[_row(i) for i in range(2)])
    out = _search_backend(coll).search_notes(7, query="פתק", limit=5)

    assert out["truncated"] is False and out["count"] == 2


def test_search_returns_the_freshest_notes_first():
    coll = _SearchColl(rows=[_row(i) for i in range(3)])
    _search_backend(coll).search_notes(7, query="פתק", limit=10)

    assert coll.cursor.sorted_by == ("updated_at", -1)


def test_every_hit_says_where_the_note_sits():
    """**האינווריאנטה:** שדות הזיהוי של פגיעה הם בדיוק הארגומנטים של כלי
    הרשימה המתאים — אחרת פגיעה היא מבוי סתום.
    """
    coll = _SearchColl(rows=[
        _row(0, file_name="a.md", file_id="f1"),
        _row(1, board_id="b1"),
        _row(2, repo_name="CodeBot", repo_path="a.py"),
    ])
    notes = _search_backend(coll).search_notes(7, query="פתק", limit=10)["notes"]
    by_target = {n["target"]: n for n in notes}

    assert by_target["file"]["file_name"] == "a.md"
    assert by_target["board"]["board_id"] == "b1"
    assert by_target["repo"]["repo_name"] == "CodeBot"
    assert by_target["repo"]["repo_path"] == "a.py"


def test_a_hit_carries_no_content_and_no_preview():
    coll = _SearchColl(rows=[_row(0, board_id="b1", content="סוד")])
    note = _search_backend(coll).search_notes(7, query="פתק", limit=10)["notes"][0]

    assert "content" not in note and "preview" not in note
    assert set(note) == {"id", "title", "target", "board_id", "updated_at"}


def test_one_malformed_row_does_not_kill_the_whole_result():
    """פתק legacy בלי יעד מסומן ``unknown`` — ולא מפיל את התוצאה."""
    coll = _SearchColl(rows=[_row(0), _row(1, board_id="b1")])
    notes = _search_backend(coll).search_notes(7, query="פתק", limit=10)["notes"]

    assert {n["target"] for n in notes} == {"unknown", "board"}


# -- אינדקסים ------------------------------------------------------------

def test_the_notes_collection_builds_all_four_query_indexes():
    """ה-MCP הוא כותב מלא של פתקים ובנה עד היום אינדקס אחד.

    נופלת אם אחד השלושה החדשים יוסר.
    """
    built = []

    class _Coll:
        def create_index(self, keys, name=None):
            built.append((tuple(keys), name))

        def index_information(self):
            return {}

    from mcp_server.backend import ProductionBackend

    coll = _Coll()
    b = ProductionBackend.__new__(ProductionBackend)
    b._notes_idx_done = False
    _verified(b, _NoteIndex.BOARD_TITLE)   # אינדקס השם כבר מאומת — לא נבדק כאן
    b._raw_mongo = lambda: {"sticky_notes": coll}
    b._notes_coll()

    assert {name for _, name in built} == {
        "user_scope_idx", "user_board_idx", "user_repo_idx", "user_title_idx",
    }
    by_name = {name: keys for keys, name in built}
    assert by_name["user_repo_idx"] == (("user_id", 1), ("repo_name", 1), ("repo_path", 1))
    assert by_name["user_title_idx"] == (("user_id", 1), ("title", 1))


def test_one_failing_index_does_not_block_the_others():
    """בנייה best-effort: אינדקס שנכשל אינו מפיל כלי, ואינו בולע את השאר.

    נופלת אם ה-``try`` יעטוף את הלולאה כולה במקום כל איטרציה.
    """
    built = []

    class _Coll:
        def create_index(self, keys, name=None):
            if name == "user_board_idx":
                raise RuntimeError("boom")
            built.append(name)

        def index_information(self):
            return {}

    from mcp_server.backend import ProductionBackend

    b = ProductionBackend.__new__(ProductionBackend)
    b._notes_idx_done = False
    _verified(b, _NoteIndex.BOARD_TITLE)
    b._raw_mongo = lambda: {"sticky_notes": _Coll()}
    b._notes_coll()

    assert set(built) == {"user_scope_idx", "user_repo_idx", "user_title_idx"}


def test_the_two_title_indexes_retry_independently(monkeypatch):
    """**דגל משותף היה מדליק אכיפה שלא אומתה.**

    הצלחת אינדקס הלוח אינה ראיה להצלחת אינדקס הריפו, ולהפך. כאן אחד
    מצליח והשני נכשל — ומצבם חייב להיבדל.

    נופלת אם שניהם יחלקו ``_IndexGate`` אחד.
    """
    import sticky_notes_target

    clock = {"now": 100.0}
    coll = _IndexSpyColl()
    monkeypatch.setattr(sticky_notes_target, "ensure_title_index", lambda c: True)
    monkeypatch.setattr(sticky_notes_target, "ensure_repo_title_index", lambda c: False)

    b = _backend_with(coll, monkeypatch, clock)

    assert b._ensure_title_index(coll) is True
    assert b._ensure_repo_title_index(coll) is False
    gates = b.__dict__["_note_index_gates"]
    assert gates[_NoteIndex.BOARD_TITLE].ok is True
    assert gates[_NoteIndex.REPO_TITLE].ok is False
    # ...וההשהיה של הכושל אינה חוסמת את המוצלח, ולהפך
    assert b._ensure_title_index(coll) is True


def test_the_repo_title_index_is_not_built_on_every_read(monkeypatch):
    """ההבטחה ``duplicate_title`` נאמרת רק במסלול הכתיבה, ורק הוא משלם עליה.

    נופלת אם ``_ensure_repo_title_index`` תיקרא מ-``_notes_coll``.
    """
    calls = []

    class _Coll:
        def create_index(self, keys, name=None): pass
        def index_information(self): return {}

    from mcp_server.backend import ProductionBackend

    b = ProductionBackend.__new__(ProductionBackend)
    b._notes_idx_done = False
    _verified(b, _NoteIndex.BOARD_TITLE)
    b._raw_mongo = lambda: {"sticky_notes": _Coll()}
    b._ensure_repo_title_index = lambda coll: calls.append("repo") or True
    b._notes_coll()

    assert calls == []


def test_repo_note_creation_falls_back_to_a_code_check_without_the_index(monkeypatch):
    """בלי אינדקס מאומת, ``duplicate_title`` חייב להיאמר על סמך **בדיקה**.

    נופלת אם הגיבוי יוסר — ואז שם כפול נכתב בשקט על אותו קובץ.
    """
    coll = _IndexSpyColl()
    coll.inserted.append({"user_id": 7, "repo_name": "CodeBot",
                          "repo_path": "a.py", "title": "שם"})
    b = _repo_backend(_RepoDB(coll), monkeypatch)
    b._ensure_repo_title_index = lambda c: False   # האינדקס לא אומת

    res = b.create_repo_note(7, repo_name="CodeBot", repo_path="a.py",
                             content="שלום", color="#FFFFCC", mode="surface", title="שם")

    assert res == {"ok": False, "error": "duplicate_title"}
    assert len(coll.inserted) == 1   # לא נכתב פתק שני


def test_a_legacy_file_hit_gets_its_navigation_field_filled_in():
    """**פגיעה בלי ``file_name`` היא מבוי סתום.**

    ``codekeeper_list_notes`` מקבל ``file_name`` בלבד, ופתק שנשמר לפני
    שהשדה היה קיים נושא ``file_id`` בלבד. בלי המילוי הסוכן רואה שהפתק
    קיים ואין לו דרך לקרוא אותו — כלומר האינווריאנטה המתועדת שקרית.

    נופלת אם ``_backfill_file_names`` יוסר.
    """
    coll = _SearchColl(rows=[_row(0, file_id="6a8cfe7e35f97a799c443650")])
    b = _search_backend(coll)
    b._raw_mongo = lambda: {
        "sticky_notes": coll,
        "code_snippets": _SnippetColl([
            {"_id": "6a8cfe7e35f97a799c443650", "file_name": "old.py"},
        ]),
    }

    note = b.search_notes(7, query="פתק", limit=10)["notes"][0]

    assert note["file_name"] == "old.py"
    assert note["file_id"] == "6a8cfe7e35f97a799c443650"


def test_the_backfill_is_one_query_not_one_per_hit():
    """N+1 על מסלול חיפוש הוא בדיוק מה ש-Smart Projection נועד למנוע.

    נופלת אם המילוי יהפוך ללולאת ``find_one``.
    """
    ids = [f"6a8cfe7e35f97a799c44365{i}" for i in range(5)]
    coll = _SearchColl(rows=[_row(i, file_id=fid) for i, fid in enumerate(ids)])
    snips = _SnippetColl([{"_id": i, "file_name": f"f{n}.py"} for n, i in enumerate(ids)])
    b = _search_backend(coll)
    b._raw_mongo = lambda: {"sticky_notes": coll, "code_snippets": snips}

    b.search_notes(7, query="פתק", limit=10)

    assert len(snips.queries) == 1
    assert {str(o) for o in snips.queries[0]["_id"]["$in"]} == set(ids)
    assert snips.queries[0]["user_id"] == 7          # לא שולפים קבצים של אחרים


def test_the_backfill_does_not_run_when_nothing_is_missing():
    """פתק מודרני נושא ``file_name``, ואז אין שאילתה נוספת בכלל."""
    coll = _SearchColl(rows=[_row(0, file_id="f1", file_name="a.md")])
    snips = _SnippetColl([])
    b = _search_backend(coll)
    b._raw_mongo = lambda: {"sticky_notes": coll, "code_snippets": snips}

    b.search_notes(7, query="פתק", limit=10)

    assert snips.queries == []


def test_a_failed_backfill_degrades_and_does_not_kill_the_search():
    """הפגיעה נשארת עם ``file_id`` בלבד — בדיוק כפי שהייתה בלעדי המילוי."""
    class _Boom:
        queries: list = []

        def find(self, *a, **k):
            raise RuntimeError("db down")

    coll = _SearchColl(rows=[_row(0, file_id="6a8cfe7e35f97a799c443650")])
    b = _search_backend(coll)
    b._raw_mongo = lambda: {"sticky_notes": coll, "code_snippets": _Boom()}

    out = b.search_notes(7, query="פתק", limit=10)

    assert out["ok"] is True and out["count"] == 1
    assert "file_name" not in out["notes"][0]


def test_every_note_on_the_same_legacy_file_gets_the_name():
    """**כמה פתקים על אותו קובץ הם המקרה הרגיל, לא הקצה.**

    מילון ``{file_id: row}`` היה שומר רק את הפתק האחרון ומשאיר את כל
    השאר בלי נתיב ניווט — אותו מבוי סתום שהמילוי נועד לסגור, רק בשקט
    יותר: השאילתה כן נשלחה, והתוצאה כן חזרה, אבל רק אחת מהשורות התמלאה.

    נופלת אם המיפוי יחזור להיות שורה-אחת-למזהה.
    """
    fid = "6a8cfe7e35f97a799c443650"
    coll = _SearchColl(rows=[_row(0, file_id=fid), _row(1, file_id=fid), _row(2, file_id=fid)])
    b = _search_backend(coll)
    b._raw_mongo = lambda: {
        "sticky_notes": coll,
        "code_snippets": _SnippetColl([{"_id": fid, "file_name": "old.py"}]),
    }

    notes = b.search_notes(7, query="פתק", limit=10)["notes"]

    assert len(notes) == 3
    assert [n.get("file_name") for n in notes] == ["old.py"] * 3
