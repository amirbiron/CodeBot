import unicodedata
import pytest

from utils import normalize_code


def test_normalize_code_strips_literal_u_hidden_set():
    # includes known set (200B, 202E, 2066) and a Cf not in allowlist (206A)
    text = "A\\u200B B\\u202E C\\u2066 D\\u206A E\\u200F"
    out = normalize_code(text)
    for esc in ["\\u200B", "\\u202E", "\\u2066", "\\u206A", "\\u200F"]:
        assert esc not in out
    # Non-hidden regular content should remain
    assert "A" in out and "B" in out and "C" in out and "D" in out and "E" in out


def test_normalize_code_preserves_non_cf_escapes():
    # \u0041 (A) is category 'Lu' and must not be stripped
    text = "X\\u0041Y"
    out = normalize_code(text)
    assert "\\u0041" in out
    assert out.count("\\u0041") == 1


def test_normalize_code_strips_literal_U_cf():
    # U+E0001 (LANGUAGE TAG) and U+E0100 (Variation Selector-17) are 'Cf'
    text = "X\\U000E0001Y Z\\U000E0100W"
    out = normalize_code(text)
    for esc in ["\\U000E0001", "\\U000E0100"]:
        assert esc not in out
    # Ensure surrounding characters still present
    assert "X" in out and "Y" in out and "Z" in out and "W" in out


def test_normalize_code_disable_strip_literal_escapes():
    # When disabled, escapes should remain as-is
    text = "pre\\u200Bpost and pre2\\U000E0001post2"
    out = normalize_code(text, remove_escaped_format_escapes=False)
    assert "\\u200B" in out
    assert "\\U000E0001" in out
