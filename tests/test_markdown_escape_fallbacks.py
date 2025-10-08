import types
import sys
import pytest


def _stub_telegram_if_missing():
    try:
        import telegram  # type: ignore
        import telegram.error  # type: ignore
        import telegram.constants  # type: ignore
        import telegram.ext  # type: ignore
    except Exception:
        tg = types.ModuleType('telegram')
        sys.modules['telegram'] = tg

        class Update:  # minimal placeholder
            pass
        class ReplyKeyboardMarkup:
            def __init__(self, *args, **kwargs):
                pass
        class ReplyKeyboardRemove:
            def __init__(self, *args, **kwargs):
                pass
        class InlineKeyboardButton:
            def __init__(self, text=None, callback_data=None):
                self.text = text
                self.callback_data = callback_data
        class InlineKeyboardMarkup:
            def __init__(self, keyboard=None):
                self.keyboard = keyboard or []
        tg.Update = Update
        tg.ReplyKeyboardMarkup = ReplyKeyboardMarkup
        tg.ReplyKeyboardRemove = ReplyKeyboardRemove
        tg.InlineKeyboardButton = InlineKeyboardButton
        tg.InlineKeyboardMarkup = InlineKeyboardMarkup

        err = types.ModuleType('telegram.error')
        class BadRequest(Exception):
            pass
        err.BadRequest = BadRequest
        sys.modules['telegram.error'] = err

        consts = types.ModuleType('telegram.constants')
        consts.ParseMode = types.SimpleNamespace(HTML='HTML', MARKDOWN='Markdown')
        sys.modules['telegram.constants'] = consts

        ext = types.ModuleType('telegram.ext')
        class _ContextTypes:
            DEFAULT_TYPE = object
        ext.ContextTypes = _ContextTypes
        class ConversationHandler:
            END = -1
        ext.ConversationHandler = ConversationHandler
        # placeholders for handlers/filters (not used directly in these tests)
        ext.CommandHandler = object
        ext.MessageHandler = object
        ext.CallbackQueryHandler = object
        ext.filters = types.SimpleNamespace()
        sys.modules['telegram.ext'] = ext


_stub_telegram_if_missing()


@pytest.mark.asyncio
async def test_conversation_file_menu_markdown_escape_and_fallback(monkeypatch):
    # Import after stubbing telegram
    import conversation_handlers as ch

    # Arrange context and update
    class Q:
        data = 'file_1'
        async def answer(self):
            return None

    captured = {}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured['text'] = text
        captured['parse_mode'] = parse_mode

    monkeypatch.setattr(ch.TelegramUtils, 'safe_edit_message_text', fake_safe_edit_message_text)

    ctx = types.SimpleNamespace(user_data={'files_cache': {'1': {
        'file_name': 'main.py',
        'programming_language': 'python',
        'description': '__main__',
    }}})
    upd = types.SimpleNamespace(callback_query=Q())

    # Path 1: normal escape
    await ch.handle_file_menu(upd, ctx)
    assert captured.get('parse_mode') in ('Markdown', ch.ParseMode.MARKDOWN)
    assert '📝 הערה:' in captured.get('text', '')

    # Path 2: fallback on exception
    def raise_escape(text, version=1):
        raise RuntimeError('boom')
    monkeypatch.setattr(ch, 'TextUtils', types.SimpleNamespace(escape_markdown=raise_escape))
    await ch.handle_file_menu(upd, ctx)
    assert '📝 הערה:' in captured.get('text', '')


@pytest.mark.asyncio
async def test_conversation_edit_note_current_note_fallback(monkeypatch):
    import conversation_handlers as ch

    class Q:
        data = 'edit_note_1'
        async def answer(self):
            return None
        def __init__(self):
            self.captured = None
        async def edit_message_text(self, text=None, reply_markup=None, parse_mode=None):
            self.captured = text

    ctx = types.SimpleNamespace(user_data={'files_cache': {'1': {
        'file_name': 'main.py',
        'description': 'a*b',
    }}})
    upd = types.SimpleNamespace(callback_query=Q())

    # Force fallback by raising from escape_markdown
    def raise_escape(text, version=1):
        raise RuntimeError('boom')
    monkeypatch.setattr(ch, 'TextUtils', types.SimpleNamespace(escape_markdown=raise_escape))

    await ch.handle_edit_note(upd, ctx)
    assert upd.callback_query.captured is not None
    # Fallback should escape asterisk
    assert 'a\\*b' in upd.callback_query.captured


@pytest.mark.asyncio
async def test_file_view_menu_markdown_fallback(monkeypatch):
    import handlers.file_view as fv

    class Q:
        data = 'file_1'
        async def answer(self):
            return None

    captured = {}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured['text'] = text
        captured['parse_mode'] = parse_mode

    monkeypatch.setattr(fv.TelegramUtils, 'safe_edit_message_text', fake_safe_edit_message_text)

    ctx = types.SimpleNamespace(user_data={'files_cache': {'1': {
        'file_name': 'main.py',
        'programming_language': 'python',
        'description': '__main__',
    }}})
    upd = types.SimpleNamespace(callback_query=Q())

    # Force fallback by raising from escape_markdown
    def raise_escape(text, version=1):
        raise RuntimeError('boom')
    monkeypatch.setattr(fv, 'TextUtils', types.SimpleNamespace(escape_markdown=raise_escape))

    await fv.handle_file_menu(upd, ctx)
    assert captured.get('parse_mode') == 'Markdown'
    assert '📝 הערה:' in captured.get('text', '')


@pytest.mark.asyncio
async def test_file_view_direct_markdown_note_fallback(monkeypatch):
    import handlers.file_view as fv

    class Q:
        data = 'view_direct_main.py'
        async def answer(self):
            return None

    captured = {}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured['text'] = text
        captured['parse_mode'] = parse_mode

    monkeypatch.setattr(fv.TelegramUtils, 'safe_edit_message_text', fake_safe_edit_message_text)

    # Stub db used inside handlers.file_view
    class _DB:
        @staticmethod
        def get_latest_version(user_id, file_name):
            return {
                'file_name': file_name,
                'code': 'print(1)\n',
                'programming_language': 'python',
                'version': 1,
                'description': 'md*special',
                '_id': 'abc123',
            }

    # Inject stub database module so internal `from database import db` resolves
    db_mod = types.ModuleType('database')
    db_mod.db = _DB()
    monkeypatch.setitem(sys.modules, 'database', db_mod)

    # User/context
    ctx = types.SimpleNamespace(user_data={})
    upd = types.SimpleNamespace(callback_query=Q(), effective_user=types.SimpleNamespace(id=123))

    # Force fallback
    def raise_escape(text, version=1):
        raise RuntimeError('boom')
    monkeypatch.setattr(fv, 'TextUtils', types.SimpleNamespace(escape_markdown=raise_escape))

    await fv.handle_view_direct_file(upd, ctx)
    assert captured.get('parse_mode') == 'Markdown'
    # Fallback should escape asterisk
    assert 'md\\*special' in captured.get('text', '')

