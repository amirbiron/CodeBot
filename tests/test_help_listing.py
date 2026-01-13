import types
import pytest

import main as mod
from telegram.ext import CommandHandler, ConversationHandler


async def _noop(update, context):  # pragma: no cover - helper stub
    return None


def test_get_registered_commands_collects_from_conversation():
    image_handler = CommandHandler("image", _noop)
    reminder_conv = ConversationHandler(
        entry_points=[CommandHandler("remind", _noop)],
        states={},
        fallbacks=[CommandHandler("cancel", _noop)],
    )
    app = types.SimpleNamespace(handlers=[image_handler, reminder_conv])

    commands = mod._get_registered_commands(app)

    assert {"image", "remind", "cancel"}.issubset(commands)


def test_collect_commands_accepts_command_attr(monkeypatch):
    handler = CommandHandler("unused", _noop)
    handler.commands = [types.SimpleNamespace(command=["IMAGE", "ImG2"])]

    names = mod._collect_commands_from_handler(handler, set())

    assert {"image", "img2"} <= names


def test_build_help_message_filters_sections():
    text = mod._build_help_message({"image", "remind"})

    assert "📚 עזרה – פקודות ללא כפתורים" in text
    assert "<code>/image</code>" in text
    assert "<code>/remind</code>" in text
    assert "/cache_stats" not in text
    assert "/batch_analyze" not in text


def test_build_help_message_no_additional_commands_section():
    # גם אם יש פקודות שאינן בקטגוריות, לא מציגים "פקודות נוספות"
    text = mod._build_help_message({"save", "search", "remind"})
    assert "🛠️ <b>פקודות נוספות</b>" not in text
    assert "<code>/save</code>" not in text
    assert "<code>/search</code>" not in text


def test_help_message_contains_spacing_before_footer():
    text = mod._build_help_message({"image"})

    assert "\n\nלבעיות או הצעות: @moominAmir" in text


def test_build_help_message_hides_admin_section_for_non_admin():
    # גם אם הפקודות קיימות, לא מציגים את הסקשן למשתמש רגיל
    text = mod._build_help_message({"status", "errors"}, is_admin=False)
    assert "⚙️ <b>מנהל (מוגבל)</b>" not in text
    assert "<code>/status</code>" not in text


def test_build_help_message_shows_admin_section_for_admin():
    text = mod._build_help_message({"status", "errors"}, is_admin=True)
    assert "⚙️ <b>מנהל (מוגבל)</b>" in text
    assert "<code>/status</code>" in text


def test_admin_help_does_not_duplicate_cache_commands():
    # cache_stats/clear_cache מוגדרים גם בקטלוג ChatOps וגם בסקשן "מטמון".
    # בעזרת אדמין לא אמורים לראות אותם כפעמיים.
    text = mod._build_help_message({"cache_stats", "clear_cache", "status"}, is_admin=True)
    assert text.count("<code>/cache_stats</code>") == 1
    assert text.count("<code>/clear_cache</code>") == 1


@pytest.mark.asyncio
async def test_codekeeperbot_help_command_uses_registered_commands(monkeypatch):
    bot = object.__new__(mod.CodeKeeperBot)
    bot.application = types.SimpleNamespace(
        handlers=[
            CommandHandler("image", _noop),
            CommandHandler("remind", _noop),
        ]
    )

    replies = {}

    class _Message:
        async def reply_text(self, text, **kwargs):
            replies["text"] = text
            replies["kwargs"] = kwargs

    update = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=123),
        message=_Message(),
    )
    context = types.SimpleNamespace(application=None)

    class _Reporter:
        def __init__(self):
            self.calls = []

        def report_activity(self, user_id):
            self.calls.append(user_id)

    async def _fake_log(*_a, **_k):
        return None

    monkeypatch.setattr(mod, "reporter", _Reporter(), raising=False)
    monkeypatch.setattr(mod, "log_user_activity", _fake_log, raising=False)

    await mod.CodeKeeperBot.help_command(bot, update, context)

    text = replies["text"]
    assert "<code>/image</code>" in text
    assert "/cache_stats" not in text
    assert replies["kwargs"]["parse_mode"]
    assert replies["kwargs"]["disable_web_page_preview"] is True
