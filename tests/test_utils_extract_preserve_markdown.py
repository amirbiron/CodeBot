import types


def test_extract_message_text_prefers_markdown_v2():
    from utils import TelegramUtils

    class Msg:
        def __init__(self):
            self.text_markdown_v2 = "__main__"
            self.text_markdown = None
            self.text = "main"
            self.caption = None

    m = Msg()
    out = TelegramUtils.extract_message_text_preserve_markdown(m)
    assert out == "__main__"


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

