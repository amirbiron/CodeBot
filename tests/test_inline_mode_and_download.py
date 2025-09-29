import asyncio
import types
import pytest


@pytest.mark.asyncio
async def test_inline_download_sends_document_to_user_when_no_message(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    # --- Prepare update/context for Inline callback (query.message is None)
    class _Query:
        def __init__(self):
            self.message = None  # Inline: no message object
            self.data = "inline_download_file:dir/readme.md"
            self.from_user = types.SimpleNamespace(id=42)

        async def edit_message_text(self, text, **kwargs):
            # allow TelegramUtils.safe_edit_message_text to call us
            return None

    class _Update:
        def __init__(self):
            self.callback_query = _Query()
            self.effective_user = types.SimpleNamespace(id=42)

    class _Bot:
        def __init__(self):
            self.sent = {"doc": None, "msg": None}

        async def send_document(self, chat_id, document, filename, caption=None):
            self.sent["doc"] = {
                "chat_id": chat_id,
                "filename": filename,
            }

        async def send_message(self, chat_id, text, parse_mode=None):
            self.sent["msg"] = {"chat_id": chat_id, "text": text}

    class _Context:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}
            self.bot = _Bot()

    update = _Update()
    context = _Context()

    # --- Arrange session and token
    session = handler.get_user_session(42)
    session["selected_repo"] = "owner/name"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    # --- Stub Telegram utils (ignore edit errors)
    async def _safe_edit(q, text, reply_markup=None, parse_mode=None):
        return None

    monkeypatch.setattr(gh.TelegramUtils, "safe_edit_message_text", _safe_edit)

    # --- Stub Github -> repo.get_contents
    class _Contents:
        path = "dir/readme.md"
        size = 12

        @property
        def decoded_content(self):
            return b"hello world\n"

    class _Repo:
        def get_contents(self, path):
            return _Contents()

    class _Gh:
        def __init__(self, *a, **k):
            pass

        def get_repo(self, _):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)

    # --- Act
    await asyncio.wait_for(handler.handle_menu_callback(update, context), timeout=2.0)

    # --- Assert: document was sent to the user (not as reply)
    assert context.bot.sent["doc"] is not None
    assert context.bot.sent["doc"]["chat_id"] == 42
    assert context.bot.sent["doc"]["filename"].endswith("readme.md")


@pytest.mark.asyncio
async def test_inline_query_empty_and_zip_are_suppressed(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    # --- Prepare InlineQuery stub
    class _InlineQuery:
        def __init__(self, text):
            self.from_user = types.SimpleNamespace(id=7)
            self.query = text
            self.answered = None

        async def answer(self, results, cache_time=1, is_personal=True):
            self.answered = results

    class _Update:
        def __init__(self, text):
            self.inline_query = _InlineQuery(text)

    class _Context:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    # --- Session/token
    session = handler.get_user_session(7)
    session["selected_repo"] = "o/r"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "t")

    # Stub Github minimal (won't be called for empty/zip)
    class _Gh:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(gh, "Github", _Gh)

    # empty query -> []
    upd1 = _Update("")
    await handler.handle_inline_query(upd1, _Context())
    assert upd1.inline_query.answered == []

    # zip command -> []
    upd2 = _Update("zip src")
    await handler.handle_inline_query(upd2, _Context())
    assert upd2.inline_query.answered == []


@pytest.mark.asyncio
async def test_inline_query_file_returns_article_with_download_button(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    # Patch Telegram result/markup classes to lightweight stubs
    def _IQArticle(**kwargs):
        return kwargs

    def _IQText(text):
        return {"text": text}

    def _Btn(text, callback_data=None):
        return types.SimpleNamespace(text=text, callback_data=callback_data)

    def _Markup(rows):
        return types.SimpleNamespace(inline_keyboard=rows)

    monkeypatch.setattr(gh, "InlineQueryResultArticle", _IQArticle)
    monkeypatch.setattr(gh, "InputTextMessageContent", _IQText)
    monkeypatch.setattr(gh, "InlineKeyboardButton", _Btn)
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", _Markup)

    # InlineQuery stub
    class _InlineQuery:
        def __init__(self, text):
            self.from_user = types.SimpleNamespace(id=9)
            self.query = text
            self.answered = None

        async def answer(self, results, cache_time=1, is_personal=True):
            self.answered = results

    class _Update:
        def __init__(self, text):
            self.inline_query = _InlineQuery(text)

    class _Context:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    # Session/token
    session = handler.get_user_session(9)
    session["selected_repo"] = "o/r"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    # Repo.get_contents -> File object
    class _Contents:
        path = "README.md"
        size = 16

        @property
        def decoded_content(self):
            return b"line1\nline2\nline3\nline4\n"

    class _Repo:
        def get_contents(self, path):
            assert path == "README.md"
            return _Contents()

    class _Gh:
        def __init__(self, *a, **k):
            pass

        def get_repo(self, _):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)

    upd = _Update("file README.md")
    ctx = _Context()
    await handler.handle_inline_query(upd, ctx)

    results = upd.inline_query.answered
    assert isinstance(results, list) and results
    # Extract callback_data from the first button
    kb = results[0]["reply_markup"].inline_keyboard
    first_cb = kb[0][0].callback_data
    assert str(first_cb).startswith("inline_download_file:README.md")

