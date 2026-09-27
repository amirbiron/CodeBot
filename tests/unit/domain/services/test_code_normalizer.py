"""הניקוי המינימלי לקוד שמודבק בבוט: מה הוא מנקה, ובעיקר מה הוא משאיר.

עד ספטמבר 2026 הקובץ הזה בדק את ``CodeNormalizer`` — שהוא מוחק LRM, מוחק רצפי
escape טקסטואליים ומוחק את ה-newline שבסוף. שלושתם נשמרים עכשיו, והטסטים כאן
מקבעים את זה. תווי כיווניות ורוחב-אפס כתובים רק כ-escapes: תו כזה בקובץ מקור
מפיל את bandit ב-B613 (H1).
"""

import sys
import unicodedata

import pytest

from src.domain.services import code_normalizer as cn
from src.domain.services import language_detector as ld
from src.domain.services.code_normalizer import clean_pasted_code, is_markdown_filename

LRM, RLM, ALM = "\u200e", "\u200f", "\u061c"
ZWNJ, ZWJ, WJ, SOFT_HYPHEN = "\u200c", "\u200d", "\u2060", "\u00ad"
ZWSP, BOM, NBSP, THIN_SPACE = "\u200b", "\ufeff", "\u00a0", "\u2009"
# טבלה 1 במאמר Trojan Source: LRE, RLE, PDF, LRO, RLO, LRI, RLI, FSI, PDI
TROJAN_SOURCE = ("\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069")


@pytest.mark.parametrize("is_markdown", [False, True])
def test_marks_joiners_and_other_format_chars_are_never_touched(is_markdown):
    text = (
        RLM + "שלום בתחילת שורה\n"
        "גרסה" + RLM + " 2.0 באמצע שורה, " + LRM + "LTR" + LRM + " ו-" + ALM + "عربي\n"
        "a" + ZWNJ + "b" + ZWJ + "c" + WJ + "d" + SOFT_HYPHEN + "e\n"
    )
    out = clean_pasted_code(text, is_markdown=is_markdown)
    assert out.text == text
    assert not out.changed
    assert out.bidi_control_lines == ()


def test_textual_escapes_in_code_are_code():
    """עד #643 נמחקו מכאן — קבוע קיבל ערך אחר, ורגקס נשבר."""
    code = (
        'RLM = "\\u200f"\n'
        'HIDDEN = re.compile(r"[\\u200b-\\u200f\\u202a-\\u202e\\u2066-\\u2069]")\n'
        'SMILE = "\\u263A"\n'
        'TAG = "\\U000E0001"\n'
    )
    assert clean_pasted_code(code, is_markdown=False).text == code


@pytest.mark.parametrize("tail", ["\n", "\n\n\n"])
@pytest.mark.parametrize("is_markdown", [False, True])
def test_trailing_newlines_are_kept(tail, is_markdown):
    """עד היום נמחקו כולם (#1662)."""
    text = "x = 1" + tail
    assert clean_pasted_code(text, is_markdown=is_markdown).text == text


@pytest.mark.parametrize("is_markdown", [False, True])
def test_family_emoji_keeps_its_joiners(is_markdown):
    family = "\U0001F468" + ZWJ + "\U0001F469" + ZWJ + "\U0001F467"
    text = "print('" + family + "')\n"
    assert clean_pasted_code(text, is_markdown=is_markdown).text == text


def test_control_characters_are_kept():
    text = "a\x1b[0mb\x0cc\x00d\x07\n"
    assert clean_pasted_code(text, is_markdown=False).text == text


@pytest.mark.parametrize("is_markdown", [False, True])
def test_line_endings_become_lf_in_every_file(is_markdown):
    out = clean_pasted_code("a\r\nb\rc\r\n", is_markdown=is_markdown)
    assert out.text == "a\nb\nc\n"
    assert (out.crlf, out.lone_cr) == (2, 1)


@pytest.mark.parametrize("is_markdown", [False, True])
def test_only_a_leading_bom_is_removed(is_markdown):
    out = clean_pasted_code(BOM + "x" + BOM + "y", is_markdown=is_markdown)
    assert out.text == "x" + BOM + "y"
    assert out.bom is True


@pytest.mark.parametrize("is_markdown", [False, True])
def test_a_run_of_leading_boms_is_removed_so_the_code_compiles(is_markdown):
    """BOM שנשאר בתחילת קוד מפיל אותו, גם כשהוא השני ברצף — ולכן נמחק כל הרצף."""
    raw = BOM + BOM + "x = 1\n"
    with pytest.raises(SyntaxError):
        compile(raw[1:], "pasted.py", "exec")

    out = clean_pasted_code(raw, is_markdown=is_markdown)
    assert out.text == "x = 1\n"
    assert out.bom is True
    compile(out.text, "pasted.py", "exec")


def test_code_loses_special_spaces_zwsp_and_trailing_whitespace_and_then_compiles():
    """הסיבה שהניקוי קיים: הטקסט הגולמי מפיל את פייתון, והנקי לא."""
    raw = "def f():" + NBSP + "\n    return" + THIN_SPACE + " 1  \t\n" + ZWSP + "x = 1\n"
    with pytest.raises(SyntaxError):
        compile(raw, "pasted.py", "exec")

    out = clean_pasted_code(raw, is_markdown=False)
    assert out.text == "def f():\n    return  1\nx = 1\n"
    assert (out.special_spaces, out.zwsp, out.trailing_whitespace_lines) == (2, 1, 2)
    compile(out.text, "pasted.py", "exec")


def test_every_zs_space_becomes_a_regular_space_in_code():
    """קטגוריה ולא רשימה: כל תו ``Zs`` בבנייה המותקנת, חוץ מהרווח הרגיל עצמו."""
    zs = [chr(cp) for cp in range(sys.maxunicode + 1) if unicodedata.category(chr(cp)) == "Zs" and cp != 0x20]
    assert NBSP in zs and "\u202f" in zs and "\u3000" in zs
    out = clean_pasted_code("x" + "x".join(zs) + "x", is_markdown=False)
    assert out.text == "x" + "x".join(" " * len(zs)) + "x"
    assert out.special_spaces == len(zs)


def test_markdown_keeps_special_spaces_zwsp_and_hard_breaks():
    """שני רווחים בסוף שורה ב-Markdown הם Hard break."""
    md = "first line  \nsecond" + NBSP + "line" + ZWSP + "\n"
    out = clean_pasted_code(md, is_markdown=True)
    assert out.text == md
    assert not out.changed


@pytest.mark.parametrize("is_markdown", [False, True])
def test_bidi_controls_stay_and_are_reported_by_line(is_markdown):
    rlo, lri, pdi = "\u202e", "\u2066", "\u2069"
    text = (
        "ok = True\n"
        'if access_level != "user' + rlo + " " + lri + "// Check if admin" + pdi + " " + lri + '":\n'
        "plain = 1  # " + RLM + "RLM alone is not reported\n"
        'name = "' + "\u2068" + "משתמש" + pdi + '"\n'
    )
    out = clean_pasted_code(text, is_markdown=is_markdown)
    assert out.text == text
    assert out.bidi_control_lines == (2, 4)


def test_explicit_bidi_classes_are_exactly_the_nine_trojan_source_chars():
    """המחלקות של UAX #9 הן בדיוק תשעת התווים — ו-LRM, RLM ו-ALM מחוץ להן."""
    found = {
        chr(cp)
        for cp in range(sys.maxunicode + 1)
        if unicodedata.bidirectional(chr(cp)) in cn._EXPLICIT_BIDI_CLASSES
    }
    assert found == set(TROJAN_SOURCE)
    assert not ({LRM, RLM, ALM} & found)


def test_cleaning_is_idempotent():
    raw = BOM + BOM + "a" + NBSP + " \r\nb" + ZWSP + "\rc  \n\n"
    once = clean_pasted_code(raw, is_markdown=False)
    twice = clean_pasted_code(once.text, is_markdown=False)
    assert twice.text == once.text
    assert not twice.changed


def test_a_non_string_is_refused_not_guessed():
    with pytest.raises(TypeError):
        clean_pasted_code(None, is_markdown=False)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "name, expected",
    [
        ("README.md", True),
        ("notes.MARKDOWN", True),
        ("long.mdown", True),
        ("x.mkd", True),
        ("x.mkdn", True),
        ("docs/readme.md", True),
        ("readme.md ", True),
        ("script.py", False),
        ("md", False),
        (".md", False),
        ("notes.md.py", False),
        (None, False),
        (123, False),
    ],
)
def test_is_markdown_filename(name, expected):
    assert is_markdown_filename(name) is expected


def test_markdown_has_one_definition_shared_with_language_detection():
    """R6: הניקוי וזיהוי השפה קוראים את אותה קבוצה, ולא שתי רשימות שיסחפו."""
    assert cn.MARKDOWN_SUFFIXES is ld.MARKDOWN_SUFFIXES
    for suffix in ld.MARKDOWN_SUFFIXES:
        assert is_markdown_filename("notes" + suffix)
