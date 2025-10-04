import hashlib
import os

import pytest

from utils import TextUtils, SecurityUtils, FileUtils, normalize_code


def test_truncate_text_basic():
    text = "abcdef"
    assert TextUtils.truncate_text(text, max_length=10) == "abcdef"
    assert TextUtils.truncate_text(text, max_length=5) == "ab..."


def test_escape_markdown_v2_and_v1():
    s = "a_b[c](d)"
    out_v2 = TextUtils.escape_markdown(s, version=2)
    assert out_v2 == "a\\_b\\[c\\]\\(d\\)"
    out_v1 = TextUtils.escape_markdown(s, version=1)
    # V1 אצלנו בורח גם את ')', ולכן התוצאה דטרמיניסטית כך:
    assert out_v1 == "a\\_b\\[c]\\(d\\)"


def test_clean_filename_and_hashtags_and_highlight():
    assert TextUtils.clean_filename("a:b/c*d?e|f.txt") == "a_b_c_d_e_f.txt"
    assert TextUtils.extract_hashtags("hello #tag1 and #tag2!") == ["tag1", "tag2"]
    assert TextUtils.highlight_text("Hello World", "world") == "Hello **World**"


def test_format_file_size_and_pluralize_hebrew():
    assert TextUtils.format_file_size(999) == "999 B"
    assert TextUtils.format_file_size(1024) == "1.0 KB"
    assert TextUtils.format_file_size(1024 * 1024) == "1.0 MB"
    assert TextUtils.pluralize_hebrew(1, "קובץ", "קבצים") == "1 קובץ"
    assert TextUtils.pluralize_hebrew(2, "קובץ", "קבצים") == "2 קבצים"
    assert TextUtils.pluralize_hebrew(3, "קובץ", "קבצים") == "3 קבצים"


def test_security_utils_hash_and_validate_and_sanitize():
    content = "hello"
    expected_sha256 = hashlib.sha256(content.encode()).hexdigest()
    assert SecurityUtils.hash_content(content, "sha256") == expected_sha256
    assert SecurityUtils.validate_user_input("ok text", max_length=5) is False
    assert SecurityUtils.validate_user_input("ok", max_length=5) is True
    assert (
        SecurityUtils.validate_user_input(
            "password=123", max_length=100, forbidden_patterns=["password"]
        )
        is False
    )
    sanitized = SecurityUtils.sanitize_code("print('x'); exec('rm -rf /')")
    assert "exec" not in sanitized.lower()


def test_file_utils_extension_and_mime():
    assert FileUtils.get_file_extension("note.TXT").lower() == ".txt"
    assert FileUtils.get_mime_type("note.txt") == "text/plain"


def test_normalize_code_removes_invisibles_and_normalizes_newlines():
    # Compose a string with BOM, CRLF, zero-width space, directional marks, NBSP, and trailing spaces
    s = "\ufeffline1\r\nline\u200B2\u200E\u200F\u202A\u202B\u202C\u202D\u202E\u2066\u2067\u2068\u2069\rend\u00A0 \t\r\n"
    out = normalize_code(s)
    # Newlines normalized to LF only
    assert "\r" not in out
    # Zero-width and directional marks removed
    for ch in ["\u200B", "\u200E", "\u200F", "\u202A", "\u202B", "\u202C", "\u202D", "\u202E", "\u2066", "\u2067", "\u2068", "\u2069"]:
        assert ch not in out
    # NBSP replaced with regular space already trimmed at end of line
    assert out.endswith(" ") is False
    assert out.rstrip("\n") == "line1\nline2\nend"

