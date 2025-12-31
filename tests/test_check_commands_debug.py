import os
import types

import pytest
from telegram.ext import CommandHandler

import main as mod


async def _noop(update, context):  # pragma: no cover - helper stub
    return None


def test_build_debug_commands_report_includes_hidden_and_menu_only():
    public_cmds = [types.SimpleNamespace(command="help", description="Help")]
    personal_cmds = [types.SimpleNamespace(command="start", description="Start")]

    text = mod._build_debug_commands_report(
        registered_commands={"help", "jobs"},
        public_menu_commands=public_cmds,
        personal_menu_commands=personal_cmds,
    )

    assert "Debug Commands Report" in text
    assert "/help" in text
    assert "/jobs" in text
    assert "Hidden Commands" in text
    assert "<pre>/jobs</pre>" in text
    assert "Menu-only" in text
    assert "<pre>/start</pre>" in text


@pytest.mark.asyncio
async def test_check_commands_rejects_non_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "2")
    monkeypatch.delenv("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", raising=False)

    bot = object.__new__(mod.CodeKeeperBot)
    bot.application = types.SimpleNamespace(handlers=[])

    replies = {}

    class _Message:
        async def reply_text(self, text, **kwargs):
            replies["text"] = text
            replies["kwargs"] = kwargs

    update = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=1),
        effective_message=_Message(),
    )
    context = types.SimpleNamespace(args=["commands"], application=None, bot=None)

    await mod.CodeKeeperBot.check_commands(bot, update, context)

    assert "מנהלים בלבד" in replies["text"]


@pytest.mark.asyncio
async def test_check_commands_commands_mode_lists_registered_and_hidden(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "2")
    monkeypatch.delenv("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", raising=False)

    bot = object.__new__(mod.CodeKeeperBot)
    bot.application = types.SimpleNamespace(
        handlers=[
            CommandHandler("jobs", _noop),
            CommandHandler("help", _noop),
        ]
    )

    replies = {}

    class _Message:
        async def reply_text(self, text, **kwargs):
            replies["text"] = text
            replies["kwargs"] = kwargs

    class _Bot:
        async def get_my_commands(self, scope=None):
            # התפריט מכיל רק help, ולכן jobs אמור להיות "Hidden"
            if scope is None:
                return [types.SimpleNamespace(command="help", description="Help")]
            return [types.SimpleNamespace(command="help", description="Help")]

    update = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=2),
        effective_message=_Message(),
    )
    context = types.SimpleNamespace(args=["commands"], application=None, bot=_Bot())

    await mod.CodeKeeperBot.check_commands(bot, update, context)

    text = replies["text"]
    assert "/help" in text
    assert "/jobs" in text
    assert "Hidden Commands" in text
    assert replies["kwargs"]["disable_web_page_preview"] is True


@pytest.mark.asyncio
async def test_check_commands_menu_mode_handles_missing_user_id_gracefully(monkeypatch):
    # מצב שבו אין effective_user, אבל בכל זאת יש "אדמין" בגלל allow-all dev flag
    monkeypatch.setenv("ADMIN_USER_IDS", "")
    monkeypatch.setenv("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", "1")

    bot = object.__new__(mod.CodeKeeperBot)
    bot.application = types.SimpleNamespace(handlers=[])

    replies = {}

    class _Message:
        async def reply_text(self, text, **kwargs):
            replies["text"] = text
            replies["kwargs"] = kwargs

    class _Bot:
        async def get_my_commands(self, scope=None):
            if scope is None:
                return [types.SimpleNamespace(command="help", description="Help")]
            # אם ננסה לקרוא scope עם chat_id לא תקין – זה היה מתרסק קודם
            raise RuntimeError("scope call should be guarded")

    update = types.SimpleNamespace(
        effective_user=None,
        effective_chat=None,
        effective_message=_Message(),
    )
    context = types.SimpleNamespace(args=[], application=None, bot=_Bot())

    await mod.CodeKeeperBot.check_commands(bot, update, context)

    assert "Telegram Menu" in replies["text"]
    assert "/help" in replies["text"]

