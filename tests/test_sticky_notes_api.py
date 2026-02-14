"""בדיקות יחידה למנגנון פתקים דביקים"""

import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webapp.sticky_notes_api import _as_note_response, _resolve_scope, _sanitize_text, _content_from_payload


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


class TestStickyNotesContentDecoding(unittest.TestCase):
    def test_content_from_payload_plain(self):
        payload = {"content": "`curl -s https://example.com`"}
        self.assertEqual(_content_from_payload(payload), "`curl -s https://example.com`")

    def test_content_from_payload_base64_utf8(self):
        import base64
        text = "`curl` בדיקה"
        payload = {"content_b64": base64.b64encode(text.encode("utf-8")).decode("ascii")}
        self.assertEqual(_content_from_payload(payload), text)

    def test_content_from_payload_invalid_base64_falls_back(self):
        payload = {"content_b64": "!!!not-base64!!!", "content": "fallback"}
        self.assertEqual(_content_from_payload(payload), "fallback")


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


if __name__ == "__main__":
    unittest.main()
