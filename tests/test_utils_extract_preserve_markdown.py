import types


def test_extract_message_text_prefers_raw_over_markdown():
    from utils import TelegramUtils

    class Msg:
        def __init__(self):
            self.text_markdown_v2 = "__main__"
            self.text_markdown = None
            self.text = "main"
            self.caption = None

    m = Msg()
    out = TelegramUtils.extract_message_text_preserve_markdown(m)
    assert out == "main"


def test_extract_message_text_falls_back_to_text():
    from utils import TelegramUtils

    class Msg:
        def __init__(self):
            self.text_markdown_v2 = None
            self.text_markdown = None
            self.text = "plain"
            self.caption = None

    m = Msg()
    out = TelegramUtils.extract_message_text_preserve_markdown(m, reconstruct_from_entities=False)
    assert out == "plain"


def test_extract_message_text_uses_caption_markdown_when_available():
    from utils import TelegramUtils

    class _Ent:
        def __init__(self, type, offset, length):
            self.type = type
            self.offset = offset
            self.length = length

    class Msg:
        def __init__(self):
            self.text_markdown_v2 = None
            self.text_markdown = None
            self.text = None
            self.caption_markdown = "__caption__"
            self.caption = "caption"
            self.caption_entities = [_Ent("bold", 0, len(self.caption))]

    m = Msg()
    out = TelegramUtils.extract_message_text_preserve_markdown(m)
    assert out == "__caption__"


def test_extract_message_text_entities_bold_italic_ordering():
    from utils import TelegramUtils

    class _Ent:
        def __init__(self, type, offset, length):
            self.type = type
            self.offset = offset
            self.length = length

    class Msg:
        def __init__(self):
            self.text = "ab"
            # italic על 'a' (0..1), bold על 'b' (1..2)
            self.entities = [
                _Ent("italic", 0, 1),
                _Ent("bold", 1, 1),
            ]

    m = Msg()
    out = TelegramUtils.extract_message_text_preserve_markdown(m)
    # ציפייה: italic על 'a' יופיע כ-"_", ו-bold על 'b' כ-"__"; יש חפיפה בסמנים סביב 'b'
    assert out == "_a___b__"


def test_extract_message_text_entities_clamped_offsets():
    from utils import TelegramUtils

    class _Ent:
        def __init__(self, type, offset, length):
            self.type = type
            self.offset = offset
            self.length = length

    class Msg:
        def __init__(self):
            self.text = "abc"
            # italic עם offset שלילי -> ייקלם ל-0
            # ו-entity נוסף מחוץ לאורך -> יתבטל ללא השפעה
            self.entities = [
                _Ent("italic", -5, 1),
                _Ent("bold", 5, 2),
            ]

    m = Msg()
    out = TelegramUtils.extract_message_text_preserve_markdown(m)
    # italic על 'a' בלבד (offset שלילי מקלמפון ל-0); ה-bold מחוץ לטווח ולכן מתעלמים ממנו
    assert out == "_a_bc"


def test_extract_message_text_ignores_unknown_entity_type():
    from utils import TelegramUtils

    class _Ent:
        def __init__(self, type, offset, length):
            self.type = type
            self.offset = offset
            self.length = length

    class Msg:
        def __init__(self):
            self.text = "abc"
            # underline אינו נתמך – אמור להתעלם
            self.entities = [_Ent("underline", 0, 3)]

    m = Msg()
    out = TelegramUtils.extract_message_text_preserve_markdown(m)
    assert out == "abc"


def test_extract_message_text_full_range_bold_closes_at_end():
    from utils import TelegramUtils

    class _Ent:
        def __init__(self, type, offset, length):
            self.type = type
            self.offset = offset
            self.length = length

    class Msg:
        def __init__(self):
            self.text = "abc"
            self.entities = [_Ent("bold", 0, 3)]

    m = Msg()
    out = TelegramUtils.extract_message_text_preserve_markdown(m)
    assert out == "__abc__"


def test_extract_message_text_bold_and_italic_full_overlap():
    from utils import TelegramUtils

    class _Ent:
        def __init__(self, type, offset, length):
            self.type = type
            self.offset = offset
            self.length = length

    class Msg:
        def __init__(self):
            self.text = "xyz"
            self.entities = [
                _Ent("italic", 0, 3),
                _Ent("bold", 0, 3),
            ]

    m = Msg()
    out = TelegramUtils.extract_message_text_preserve_markdown(m)
    assert out == "___xyz___"


def test_extract_message_text_empty_base_returns_empty():
    from utils import TelegramUtils

    class Msg:
        def __init__(self):
            self.text = ""
            self.caption = None
            self.entities = []

    m = Msg()
    out = TelegramUtils.extract_message_text_preserve_markdown(m)
    assert out == ""

