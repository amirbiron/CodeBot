import types
import pytest


class _Msg:
    def __init__(self):
        self.texts = []
        self.markups = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)
        self.markups.append(kwargs.get("reply_markup"))
        return self

    async def edit_text(self, text, **kwargs):
        self.texts.append(text)
        self.markups.append(kwargs.get("reply_markup"))
        return self


class _Query:
    def __init__(self):
        self.message = _Msg()
        self.data = "notifications_menu"
        self.from_user = types.SimpleNamespace(id=123)

    async def edit_message_text(self, text, **kwargs):
        # Capture text and markup similar to Telegram API
        return await self.message.edit_text(text, **kwargs)

    async def answer(self, *args, **kwargs):
        return None


class _Update:
    def __init__(self):
        self.callback_query = _Query()
        self.effective_user = types.SimpleNamespace(id=123)


class _Context:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


@pytest.mark.asyncio
async def test_notifications_menu_shows_30s_option_and_displays_seconds(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    update = _Update()
    context = _Context()

    # Ensure a repo is selected to avoid early-return guard
    session = handler.get_user_session(123)
    session["selected_repo"] = "owner/name"

    # Seed notifications state with 30 seconds interval
    context.user_data["notifications"] = {
        "enabled": True,
        "pr": True,
        "issues": True,
        "interval": 30,
    }

    # Stub Telegram UI components to simple tuples/identity for easy assertions
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    # Route to notifications menu
    update.callback_query.data = "notifications_menu"

    await handler.handle_menu_callback(update, context)

    # Validate text shows seconds for sub-minute intervals (new wording without the word 'תדירות')
    all_text = "\n".join(update.callback_query.message.texts)
    assert "⏱ 30 שנ׳" in all_text

    # Validate keyboard contains a 30s option button
    # reply_markup is a list of rows; each button is (args, kwargs)
    found_30s = False
    for rows in update.callback_query.message.markups:
        if not rows:
            continue
        for row in rows:
            for button in row:
                label = button[0][0] if button and button[0] else ""
                if "30שנ׳" in label:
                    found_30s = True
                    break
            if found_30s:
                break
        if found_30s:
            break

    assert found_30s
