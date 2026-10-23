"""עיצוב תשובות היועץ לטלגרם (``handlers/advisor_text.py``).

רוב הטסטים עברו כמו שהם מהבוט הנפרד ``codekeeper_advisor_bot``; החדש הוא
``test_split_counts_emoji_as_two_units``, על מדידת האורך ב-UTF-16.
"""

from handlers.advisor_text import RLM, html_to_plain, rtl_lines, sanitize_telegram_html, split_message, utf16_length


def test_sanitize_keeps_telegram_tags_and_escapes_the_rest():
    out = sanitize_telegram_html("<b>שלום</b> <script>x</script> a < b & c")
    assert out == "<b>שלום</b> &lt;script&gt;x&lt;/script&gt; a &lt; b &amp; c"


def test_sanitize_drops_tag_with_attributes_and_its_closing_tag():
    assert sanitize_telegram_html('<b class="x">טקסט</b>') == "טקסט"


def test_html_to_plain_restores_real_characters():
    sanitized = sanitize_telegram_html("<b>א</b> < ב & ג")
    assert html_to_plain(sanitized) == "א < ב & ג"


def test_split_message_respects_limit_and_keeps_all_content():
    paragraphs = [f"פסקה {i} " + "מילה " * 30 for i in range(40)]
    text = "\n\n".join(paragraphs)
    chunks = split_message(text, limit=500)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)
    assert "".join(chunks).replace("\n", "").replace(" ", "") == text.replace("\n", "").replace(" ", "")


def test_split_message_prefers_paragraph_boundary():
    text = "א" * 300 + "\n\n" + "ב" * 300
    assert split_message(text, limit=500) == ["א" * 300, "ב" * 300]


def test_split_message_hard_cuts_a_single_huge_word():
    chunks = split_message("x" * 1200, limit=500)
    assert [len(c) for c in chunks] == [500, 500, 200]


def test_short_message_is_one_chunk():
    assert split_message("  שלום  ") == ["שלום"]


def test_rtl_mark_on_hebrew_lines_whose_first_letter_is_english():
    lines = [
        "CodeKeeper עוזר למפתחים",        # מתחילה באנגלית ← RLM
        "• Claude Code עובד גם מהנייד",   # תבליט אינו אות ← RLM
        "<b>CodeKeeper</b> שומר מסמכים",  # התג אינו מוצג ← RLM
        "המסמך נגיש מ-Claude Code",        # מתחילה בעברית ← בלי
        "<b>שמירה</b> עם CodeKeeper",      # האות הגלויה הראשונה בעברית ← בלי
        "Claude Code",                      # בלי עברית ← בלי
    ]
    out = rtl_lines("\n".join(lines))
    assert [line.startswith(RLM) for line in out.split("\n")] == [True, True, True, False, False, False]
    assert rtl_lines(out) == out  # שורה שכבר מתחילה ב-RLM לא מקבלת עוד אחד


def test_rtl_mark_skips_lines_inside_pre():
    text = "<pre>npm install  # התקנה\nnpm start  # הרצה</pre>\nCodeKeeper מוכן"
    assert rtl_lines(text) == "<pre>npm install  # התקנה\nnpm start  # הרצה</pre>\n" + RLM + "CodeKeeper מוכן"


def test_split_counts_emoji_as_two_units():
    """אימוג'י הוא תו אחד בפייתון ושתי יחידות ב-UTF-16 — החלק נמדד ביחידה הגדולה."""
    text = "🙂" * 300  # 300 תווי פייתון, 600 יחידות UTF-16
    chunks = split_message(text, limit=500)
    assert [utf16_length(c) for c in chunks] == [500, 100]
    assert "".join(chunks) == text
