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


def test_build_help_message_highlights_and_filters():
    text = mod._build_help_message({"image", "remind"})

    assert "<b><code>/image</code></b>" in text
    assert "<b><code>/remind</code></b>" in text
    assert "/cache_stats" not in text
    assert "/batch_analyze" not in text


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
    assert "<b><code>/image</code></b>" in text
    assert "/cache_stats" not in text
    assert replies["kwargs"]["parse_mode"]
    assert replies["kwargs"]["disable_web_page_preview"] is True
