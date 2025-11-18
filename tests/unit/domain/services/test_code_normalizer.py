import pytest

from src.domain.services.code_normalizer import CodeNormalizer


def test_removes_bidi_markers():
    normalizer = CodeNormalizer()
    # contains U+200E (LRM) between words
    s = "hello\u200eworld"
    out = normalizer.normalize(s)
    assert out == "helloworld"


def test_handles_literal_unicode_escapes_hidden_chars():
    normalizer = CodeNormalizer()
    # literal escape for zero-width space should be stripped
    s = "x\\u200By"
    out = normalizer.normalize(s)
    assert out == "xy"


def test_keeps_literal_non_hidden_escapes():
    normalizer = CodeNormalizer()
    # U+263A (WHITE SMILING FACE) is not Cf; literal escape should remain
    s = "a\\u263Ab"
    out = normalizer.normalize(s)
    assert out == "a\\u263Ab"


def test_trims_trailing_whitespace_and_crlf_to_lf():
    normalizer = CodeNormalizer()
    s = "line1\r\nline2  \r\n"
    out = normalizer.normalize(s)
    assert out == "line1\nline2\n".rstrip("\n")  # no forced trailing newline
