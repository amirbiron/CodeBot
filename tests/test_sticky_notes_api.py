"""בדיקות יחידה למנגנון פתקים דביקים"""

import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock
import base64
from flask import Flask

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib
sticky_mod = importlib.import_module('webapp.sticky_notes_api')
from webapp.sticky_notes_api import _as_note_response, _resolve_scope, _sanitize_text, _decode_content_b64


class TestStickyNotesSanitize(unittest.TestCase):
    def test_sanitize_preserves_quotes_and_text(self):
        text = '"לפי ריפו"'
        self.assertEqual(_sanitize_text(text), '"לפי ריפו"')

    def test_sanitize_unescapes_html_entities(self):
        text = '&quot;בדיקה &amp; ועוד&quot;'
        self.assertEqual(_sanitize_text(text), '"בדיקה & ועוד"')

    def test_sanitize_handles_long_notes_without_trimming_short_content(self):
        long_text = "א" * 6000
        out = _sanitize_text(long_text)
        self.assertEqual(len(out), 6000)

    def test_sanitize_caps_extreme_length(self):
        very_long = "ב" * 25000
        out = _sanitize_text(very_long)
        self.assertEqual(len(out), 20000)

    def test_sanitize_strips_control_chars(self):
        dirty = "טקסט\x00\x07ניקוי"
        self.assertEqual(_sanitize_text(dirty), "טקסטניקוי")


class TestNoteResponse(unittest.TestCase):
    def test_as_note_response_unescapes_content(self):
        doc = {
            '_id': '1',
            'file_id': 'file',
            'content': '&quot;שלום&quot;',
            'position_x': 120,
            'position_y': 260,
            'width': 300,
            'height': 200,
            'color': '#ffffcc',
            'is_minimized': False,
            'created_at': None,
            'updated_at': None,
            'anchor_id': None,
            'anchor_text': None,
        }
        note = _as_note_response(doc)
        self.assertEqual(note['content'], '"שלום"')
        self.assertEqual(note['size']['width'], 300)
        self.assertEqual(note['size']['height'], 200)


class TestStickyScope(unittest.TestCase):
    def test_resolve_scope_collects_related_versions(self):
        db = MagicMock()
        db.code_snippets = MagicMock()
        db.code_snippets.find_one.return_value = {'file_name': 'Notes.md'}
        db.code_snippets.find.return_value = [
            {'_id': '64a000000000000000000001'},
            {'_id': '64a000000000000000000002'},
        ]
        scope_id, file_name, related_ids = _resolve_scope(db, 42, '64a000000000000000000003')
        self.assertEqual(file_name, 'Notes.md')
        self.assertTrue(scope_id.startswith('user:42:file:'))
        self.assertIn('64a000000000000000000003', related_ids)
        self.assertIn('64a000000000000000000001', related_ids)
        self.assertEqual(len(related_ids), len(set(related_ids)))

    def test_resolve_scope_without_match_returns_only_input(self):
        db = MagicMock()
        db.code_snippets = MagicMock()
        db.code_snippets.find_one.return_value = None
        db.code_snippets.find.return_value = []
        scope_id, file_name, related_ids = _resolve_scope(db, 7, 'plain-id')
        self.assertIsNone(scope_id)
        self.assertIsNone(file_name)
        self.assertEqual(related_ids, ['plain-id'])


class TestStickyNotesContentB64(unittest.TestCase):
    def test_decode_content_b64_simple_ascii(self):
        b64 = base64.b64encode(b"curl -s https://example.com").decode("ascii")
        self.assertEqual(_decode_content_b64(b64), "curl -s https://example.com")

    def test_decode_content_b64_utf8_and_urlsafe_no_padding(self):
        txt = "שלום 🌍 curl"
        b64 = base64.urlsafe_b64encode(txt.encode("utf-8")).decode("ascii").rstrip("=")
        self.assertEqual(_decode_content_b64(b64), txt)

    def test_decode_content_b64_invalid_raises(self):
        with self.assertRaises(ValueError):
            _decode_content_b64("!!!not-base64!!!")

    def test_decode_content_b64_non_string_raises(self):
        with self.assertRaises(ValueError):
            _decode_content_b64(123)  # type: ignore[arg-type]


class _StubColl:
    def __init__(self):
        self._docs = []
        self.calls = []

    def create_index(self, *args, **kwargs):
        return None

    def create_indexes(self, *args, **kwargs):
        return None

    def insert_one(self, doc):
        self._docs.append(dict(doc))
        class R:
            inserted_id = doc.get("_id") or "1"
        return R()

    def find_one(self, query, *args, **kwargs):
        for d in self._docs:
            ok = True
            for k, v in query.items():
                if d.get(k) != v:
                    ok = False
                    break
            if ok:
                return d
        return None

    def update_one(self, filt, update, upsert=False):
        self.calls.append(("update_one", filt, update, upsert))
        target = self.find_one(filt)
        if target and isinstance(update, dict) and "$set" in update:
            target.update(update["$set"])
        class R:
            matched_count = 1 if target else 0
            modified_count = 1 if target else 0
        return R()


class _StubDB:
    def __init__(self):
        self.sticky_notes = _StubColl()
        self.note_reminders = _StubColl()
        self.code_snippets = MagicMock()
        self.code_snippets.find_one.return_value = None
        self.code_snippets.find.return_value = []


def _make_app(db_stub):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(sticky_mod.sticky_notes_bp)
    return app


class TestStickyNotesApiContentB64(unittest.TestCase):
    def setUp(self):
        self.db = _StubDB()
        self.user_id = 42
        self.file_id = "64a000000000000000000003"
        self.note_id = "507f1f77bcf86cd799439011"
        # Patch module globals but restore in tearDown to avoid leaking across suite
        self._orig_get_db = sticky_mod.get_db
        self._orig_ensure_indexes = getattr(sticky_mod, "_ensure_indexes", None)
        sticky_mod.get_db = lambda: self.db
        sticky_mod._ensure_indexes = lambda: None
        self.app = _make_app(self.db)
        self.client = self.app.test_client()

    def tearDown(self):
        try:
            sticky_mod.get_db = self._orig_get_db
        except Exception:
            pass
        try:
            if self._orig_ensure_indexes is not None:
                sticky_mod._ensure_indexes = self._orig_ensure_indexes
        except Exception:
            pass

    def _login(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_id
            sess["user_data"] = {"first_name": "Test"}

    def test_create_note_accepts_content_b64_and_stores_plain_text(self):
        self._login()
        content = "curl שלום"
        content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        r = self.client.post(
            f"/api/sticky-notes/{self.file_id}",
            json={"content_b64": content_b64, "position": {"x": 1, "y": 2}, "size": {"width": 260, "height": 200}},
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.get_json()["ok"])
        self.assertTrue(self.db.sticky_notes._docs)
        self.assertEqual(self.db.sticky_notes._docs[-1]["content"], content)

    def test_update_note_accepts_content_b64(self):
        self._login()
        oid = sticky_mod.ObjectId(self.note_id)
        self.db.sticky_notes._docs.append({"_id": oid, "user_id": self.user_id, "file_id": self.file_id, "updated_at": None})
        content = "curl update ✓"
        content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        r = self.client.put(f"/api/sticky-notes/note/{self.note_id}", json={"content_b64": content_b64})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(self.db.sticky_notes._docs[-1]["content"], content)


class TestSyncStickyNotesOnRename(unittest.TestCase):
    """בדיקות ל-sync_sticky_notes_on_rename מ-sticky_notes_scope."""

    def setUp(self):
        from sticky_notes_scope import make_scope_id, sync_sticky_notes_on_rename
        self.make_scope_id = make_scope_id
        self.sync = sync_sticky_notes_on_rename

        self.user_id = 12345
        self.old_name = "notes.md"
        self.new_name = "my_notes.md"
        self.old_scope = make_scope_id(self.user_id, self.old_name)
        self.new_scope = make_scope_id(self.user_id, self.new_name)

        # Mock DB
        self.db = MagicMock()
        self.db.sticky_notes = MagicMock()
        self.db.code_snippets = MagicMock()
        self.db.code_snippets.find.return_value = [{"_id": "abc123"}, {"_id": "def456"}]

    def test_updates_scope_and_file_name(self):
        self.sync(self.db, self.user_id, self.old_name, self.new_name)
        self.db.sticky_notes.update_many.assert_called_once()
        call_args = self.db.sticky_notes.update_many.call_args
        query = call_args[0][0]
        update = call_args[0][1]
        self.assertEqual(query["user_id"], self.user_id)
        self.assertIn("$or", query)
        self.assertEqual(update["$set"]["scope_id"], self.new_scope)
        self.assertEqual(update["$set"]["file_name"], self.new_name)

    def test_sets_new_file_id_when_provided(self):
        self.sync(self.db, self.user_id, self.old_name, self.new_name, new_file_id="new_id_999")
        call_args = self.db.sticky_notes.update_many.call_args
        update = call_args[0][1]
        self.assertEqual(update["$set"]["file_id"], "new_id_999")

    def test_does_not_set_file_id_when_empty(self):
        self.sync(self.db, self.user_id, self.old_name, self.new_name)
        call_args = self.db.sticky_notes.update_many.call_args
        update = call_args[0][1]
        self.assertNotIn("file_id", update["$set"])

    def test_noop_when_names_equal(self):
        self.sync(self.db, self.user_id, "same.md", "same.md")
        self.db.sticky_notes.update_many.assert_not_called()

    def test_noop_when_old_name_empty(self):
        self.sync(self.db, self.user_id, "", self.new_name)
        self.db.sticky_notes.update_many.assert_not_called()

    def test_noop_when_no_sticky_notes_collection(self):
        self.db.sticky_notes = None
        # Should not raise
        self.sync(self.db, self.user_id, self.old_name, self.new_name)

    def test_includes_old_file_ids_in_query(self):
        self.sync(self.db, self.user_id, self.old_name, self.new_name)
        call_args = self.db.sticky_notes.update_many.call_args
        query = call_args[0][0]
        or_clauses = query["$or"]
        file_id_clause = [c for c in or_clauses if "file_id" in c]
        self.assertTrue(file_id_clause)
        self.assertIn("abc123", file_id_clause[0]["file_id"]["$in"])
        self.assertIn("def456", file_id_clause[0]["file_id"]["$in"])

    def test_uses_provided_old_file_ids(self):
        self.sync(self.db, self.user_id, self.old_name, self.new_name, old_file_ids=["custom_id"])
        # Should NOT query code_snippets when old_file_ids provided
        self.db.code_snippets.find.assert_not_called()
        call_args = self.db.sticky_notes.update_many.call_args
        query = call_args[0][0]
        or_clauses = query["$or"]
        file_id_clause = [c for c in or_clauses if "file_id" in c]
        self.assertTrue(file_id_clause)
        self.assertIn("custom_id", file_id_clause[0]["file_id"]["$in"])


if __name__ == "__main__":
    unittest.main()
