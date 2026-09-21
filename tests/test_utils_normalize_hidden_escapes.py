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


def test_normalize_code_strips_literal_U_variation_selectors_when_enabled():
    # U+E0001 (LANGUAGE TAG, Cf) should be stripped always
    # U+E0100 (Variation Selector-17, Mn) should be stripped only when remove_variation_selectors=True
    text = "X\\U000E0001Y Z\\U000E0100W"
    out_default = normalize_code(text)
    assert "\\U000E0001" not in out_default
    assert "\\U000E0100" in out_default  # default: keep VS17

    out_strip_vs = normalize_code(text, remove_variation_selectors=True)
    assert "\\U000E0001" not in out_strip_vs
    assert "\\U000E0100" not in out_strip_vs
    # Ensure surrounding characters still present
    assert "X" in out_strip_vs and "Y" in out_strip_vs and "Z" in out_strip_vs and "W" in out_strip_vs


def test_normalize_code_disable_strip_literal_escapes():
    # When disabled, escapes should remain as-is
    text = "pre\\u200Bpost and pre2\\U000E0001post2"
    out = normalize_code(text, remove_escaped_format_escapes=False)
    assert "\\u200B" in out
    assert "\\U000E0001" in out


# ---------------------------------------------------------------------------
# #3427: רשימה אחת נמחקה משני מקומות, ופונקציה אחת במקום שתיים
# ---------------------------------------------------------------------------

#: 16 הקודים שישבו ב-``known_hex4`` (utils) וב-``_KNOWN_ESCAPE_HEX4`` (הדומיין) —
#: זהים תו-בתו, ונמדד שכולם ``Cf``, כלומר הרשימה לא הוסיפה דבר על הקטגוריה.
_FORMERLY_LISTED = [
    "200B", "200C", "200D", "2060", "FEFF",
    "200E", "200F", "202A", "202B", "202C", "202D", "202E",
    "2066", "2067", "2068", "2069",
]


def test_the_two_normalizers_share_one_hidden_escape_rule_and_no_list():
    """הגדרה אחת בשכבת הדומיין, ושני הצרכנים קוראים לה — בלי רשימה באף אחד מהם."""
    import inspect

    import utils
    from src.domain.services import code_normalizer

    assert utils._strip_hidden_escapes is code_normalizer.strip_hidden_escapes
    assert not hasattr(code_normalizer.CodeNormalizer, "_KNOWN_ESCAPE_HEX4")
    assert not hasattr(code_normalizer.CodeNormalizer, "_strip_hidden_escapes")
    assert "known_hex4" not in inspect.getsource(utils.normalize_code)


@pytest.mark.parametrize("hexcode", _FORMERLY_LISTED)
def test_every_code_the_deleted_lists_named_is_cf_and_is_still_stripped_on_both_paths(hexcode):
    """המדידה מהאישו, כטסט: כל קוד שהרשימה תפסה נתפס על ידי הקטגוריה — בשני הנרמולים."""
    from src.domain.services.code_normalizer import CodeNormalizer

    assert unicodedata.category(chr(int(hexcode, 16))) == "Cf"
    text = f"a\\u{hexcode}b"
    assert CodeNormalizer().normalize(text) == "ab"
    assert normalize_code(text, strip_bom=False) == "ab", "המסלול הישן של utils (אפשרות שאינה ברירת מחדל)"


def test_variation_selectors_stay_a_separate_branch_because_they_are_mn_not_cf():
    """‏``U+FE0F`` הוא ``Mn``: הקטגוריה לא תופסת אותו, ולכן הוא ענף משלו שנדלק רק לפי בקשה."""
    from src.domain.services.code_normalizer import CodeNormalizer, strip_hidden_escapes

    assert unicodedata.category("\uFE0F") == "Mn"
    assert strip_hidden_escapes("a\\uFE0Fb") == "a\\uFE0Fb"
    assert strip_hidden_escapes("a\\uFE0Fb", remove_variation_selectors=True) == "ab"
    assert CodeNormalizer().normalize("a\\uFE0Fb") == "a\\uFE0Fb"
    assert normalize_code("a\\uFE0Fb", strip_bom=False) == "a\\uFE0Fb"
    assert normalize_code("a\\uFE0Fb", strip_bom=False, remove_variation_selectors=True) == "ab"


def test_a_variation_selector_is_stripped_whatever_escape_form_spells_it():
    """‏``\\U0000FE0F`` ו-``\\uFE0F`` הם אותו תו, ולכן אותה החלטה בשתי הצורות (סקירת CodeRabbit על #3443).

    הענף של ``\\UXXXXXXXX`` בדק רק את הטווח האידאוגרפי (``U+E0100``–``U+E01EF``),
    כאילו הצורה הארוכה מאייתת רק אותו — אבל ``\\U0000FE0F`` היא כתיב חוקי של
    ``U+FE0F``, ונשארה כמות שהיא בזמן ש-``\\uFE0F`` הוסר. כלל אחד לשתי הצורות.
    """
    from src.domain.services.code_normalizer import strip_hidden_escapes

    assert strip_hidden_escapes("a\\U0000FE0Fb") == "a\\U0000FE0Fb", "default: kept, like the short form"
    assert strip_hidden_escapes("a\\U0000FE0Fb", remove_variation_selectors=True) == "ab"
    assert strip_hidden_escapes("a\\U0000FE00b", remove_variation_selectors=True) == "ab"
    assert normalize_code("a\\U0000FE0Fb", strip_bom=False, remove_variation_selectors=True) == "ab"


def test_an_escape_beyond_unicode_is_left_exactly_as_written():
    """‏``\\U00110000`` אינו תו (מעל U+10FFFF): לא ``Cf``, לא שגיאה — נשאר כמות שהוא, כמו קודם."""
    from src.domain.services.code_normalizer import strip_hidden_escapes

    assert strip_hidden_escapes("a\\U00110000b") == "a\\U00110000b"
