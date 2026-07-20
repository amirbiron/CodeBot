"""טסטים ל-handlers של הפתקים הדביקים ב-MCP (list/create/update).

הכול הרמטי: fake backend שמקליט kwargs, בלי Flask ובלי Mongo. את נכונות
ה-scope בודקים מול make_scope_id האמיתי (sticky_notes_scope בשורש — מודול טהור).
"""

from mcp_server import handlers
from mcp_server.backend import _as_note, _notes_scope_filter
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
    assert _notes_scope_filter(42, None, []) == {"user_id": 42}


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
        "created_at",
        "updated_at",
    }
