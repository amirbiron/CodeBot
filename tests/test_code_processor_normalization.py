import pytest

from code_processor import code_processor


def test_validator_removes_hidden_chars_non_markdown():
    text = (
        "This\u200b is\u200f a\u200d test\u202c string\u200e with\u2060 hidden\u202d characters!\n"
        "Line\u200b two\u202e also\u200f has\u200d some\u202a sneaky\u2060 stuff.\n"
        "Even\u200b more\u202c here\u2060..."
    )
    ok, cleaned, msg = code_processor.validate_code_input(text, filename="Nikui.py", user_id=123)
    assert ok is True
    # hidden/control characters removed
    for ch in ["\u200b", "\u200c", "\u200d", "\u2060", "\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e"]:
        assert ch not in cleaned
    # cleaned text should be shorter
    assert len(cleaned) < len(text)


def test_validator_preserves_markdown_trailing_spaces():
    # Two trailing spaces at EOL should be preserved in Markdown to keep hard line breaks
    text = "first line  \nsecond\u200e line  \n"
    ok, cleaned, msg = code_processor.validate_code_input(text, filename="notes.md", user_id=123)
    assert ok is True
    # directional mark removed
    assert "\u200e" not in cleaned
    # trailing double spaces preserved before newline on both lines
    assert "line  \n" in cleaned
    # ensure both lines maintain hard breaks count (two occurrences of '  \n')
    assert cleaned.count("  \n") >= 2
