"""המאמת של מסלול העריכה בבוט אינו מנקה תווים.

עד ספטמבר 2026 ``code_processor.validate_code_input`` הריץ את ``normalize_code``,
והטסטים כאן קיבעו שהוא מוחק 11 תווי רוחב-אפס וכיווניות ורצפי escape טקסטואליים.
הניקוי של קוד מודבק עבר ל-``code_service.clean_pasted_code``, שה-handler מריץ
פעם אחת לפני האימות, והוא לא מוחק את רוב התווים האלה בכלל (ראו
``tests/unit/domain/services/test_code_normalizer.py``). המאמת עצמו מחזיר את
הטקסט כמו שקיבל, חוץ מהסרת גדרות ``` בקוד שאינו Markdown.
"""

from code_processor import code_processor


def test_validator_returns_hidden_and_directional_chars_untouched():
    text = (
        "This\u200b is\u200f a\u200d test\u202c string\u200e with\u2060 hidden\u202d characters!\n"
        "Line\u200b two\u202e also\u200f has\u200d some\u202a sneaky\u2060 stuff.\n"
        # רצפי escape שהמשתמש הקליד כטקסט הם קוד, לא תווים נסתרים
        "This\\u200b stays as typed.\\u202E\n"
    )
    ok, cleaned, msg = code_processor.validate_code_input(text, filename="Nikui.py", user_id=123)
    assert ok is True and msg == ""
    assert cleaned == text


def test_validator_keeps_markdown_as_is():
    text = "first line  \nsecond\u200e line  \n"
    ok, cleaned, msg = code_processor.validate_code_input(text, filename="notes.md", user_id=123)
    assert ok is True
    assert cleaned == text


def test_validator_uses_the_domain_markdown_suffixes():
    """הגדרת ה-Markdown של המאמת היא ``MARKDOWN_SUFFIXES`` מהדומיין.

    עד היום המאמת החזיק רשימה משלו (``.md`` ו-``.markdown`` בלבד), בעוד שזיהוי
    השפה הכיר גם ``.mdown``, ``.mkd`` ו-``.mkdn``. ב-``.mkd`` גדרות ``` הן חלק
    מהמסמך, ולכן הן נשארות; בקובץ פייתון הן עטיפה של הדבקה, ולכן הן מוסרות.
    """
    fenced = "intro\n```python\nprint(1)\n```\n"
    ok, cleaned_md, _ = code_processor.validate_code_input(fenced, filename="notes.mkd", user_id=1)
    assert ok is True and cleaned_md == fenced

    ok, cleaned_py, _ = code_processor.validate_code_input(fenced, filename="snippet.py", user_id=1)
    assert ok is True and "```" not in cleaned_py
