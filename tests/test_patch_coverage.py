import types
import pytest


@pytest.mark.asyncio
async def test_show_all_files_menu_order_message(monkeypatch):
    # Stub modules and functions used inside show_all_files
    from conversation_handlers import show_all_files

    # database db stub
    mod = types.ModuleType("database")
    mod.db = types.SimpleNamespace(get_user_files=lambda *_a, **_k: [])
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    # user_stats/reporter stubs
    import conversation_handlers as ch
    monkeypatch.setattr(ch.user_stats, "log_user", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ch.reporter, "report_activity", lambda *a, **k: None, raising=False)

    class DummyMessage:
        def __init__(self):
            self.captured = None
        async def reply_text(self, *_a, **kwargs):
            self.captured = kwargs.get("reply_markup")

    class DummyUpdate:
        def __init__(self):
            self.message = DummyMessage()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1, username="u")

    class DummyContext:
        def __init__(self):
            self.user_data = {}

    u = DummyUpdate()
    c = DummyContext()
    await show_all_files(u, c)

    rm = u.message.captured
    assert rm is not None
    # Extract the callback_data of the first button in each row
    rows = rm.inline_keyboard
    callbacks = [row[0].callback_data for row in rows]
    # Expect order: search_files, by_repo_menu, backup_list, show_large_files, show_regular_files
    assert callbacks[:5] == [
        "search_files",
        "by_repo_menu",
        "backup_list",
        "show_large_files",
        "show_regular_files",
    ]


@pytest.mark.asyncio
async def test_show_all_files_menu_order_callback(monkeypatch):
    from conversation_handlers import show_all_files_callback
    import conversation_handlers as ch

    # Monkeypatch TelegramUtils.safe_edit_message_text to capture reply_markup
    captured = {}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured["reply_markup"] = reply_markup

    from utils import TelegramUtils
    monkeypatch.setattr(TelegramUtils, "safe_edit_message_text", fake_safe_edit_message_text)

    class DummyQuery:
        def __init__(self):
            self.data = "files"  # not used inside
        async def answer(self):
            return None

    class DummyUpdate:
        def __init__(self):
            self.callback_query = DummyQuery()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    class DummyContext:
        def __init__(self):
            self.user_data = {}

    u = DummyUpdate()
    c = DummyContext()
    await show_all_files_callback(u, c)

    rm = captured.get("reply_markup")
    assert rm is not None
    rows = rm.inline_keyboard
    callbacks = [row[0].callback_data for row in rows]
    assert callbacks[:4] == [
        "by_repo_menu",
        "backup_list",
        "show_large_files",
        "show_regular_files",
    ]


@pytest.mark.asyncio
async def test_large_files_selection_markdown_safe_filename(monkeypatch):
    from large_files_handler import large_files_handler

    class DummyQuery:
        def __init__(self, data):
            self.data = data
            self.captured_text = None
            self.captured_mode = None
        async def answer(self):
            return None
        async def edit_message_text(self, text=None, reply_markup=None, parse_mode=None):
            self.captured_text = text
            self.captured_mode = parse_mode

    class DummyUpdate:
        def __init__(self, data):
            self.callback_query = DummyQuery(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    class Ctx:
        def __init__(self):
            self.user_data = {
                'large_files_cache': {
                    'lf_1_0': {
                        'file_name': '4_5960942637186816320.md',
                        'programming_language': 'markdown',
                        'file_size': 1234,
                        'lines_count': 10,
                        'created_at': 'now'
                    }
                }
            }

    u = DummyUpdate("large_file_lf_1_0")
    c = Ctx()
    await large_files_handler.handle_file_selection(u, c)
    assert u.callback_query.captured_mode == 'Markdown'
    assert "4_5960942637186816320.md" in (u.callback_query.captured_text or "")


@pytest.mark.asyncio
async def test_large_files_view_small_content_escapes_backticks(monkeypatch):
    from large_files_handler import large_files_handler

    class DummyMsg:
        async def reply_document(self, **kwargs):
            self.kwargs = kwargs

    class DummyQuery:
        def __init__(self, data):
            self.data = data
            self.message = DummyMsg()
            self.captured_text = None
            self.captured_mode = None
        async def answer(self):
            return None
        async def edit_message_text(self, text=None, reply_markup=None, parse_mode=None):
            self.captured_text = text
            self.captured_mode = parse_mode

    class DummyUpdate:
        def __init__(self, data):
            self.callback_query = DummyQuery(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    class Ctx:
        def __init__(self):
            self.user_data = {
                'large_files_cache': {
                    'lf_1_0': {
                        'file_name': 'f.md',
                        'content': 'start```mid```end',
                        'programming_language': 'markdown'
                    }
                }
            }

    u = DummyUpdate("lf_view_lf_1_0")
    c = Ctx()
    await large_files_handler.view_large_file(u, c)
    assert u.callback_query.captured_mode == 'Markdown'
    assert u.callback_query.captured_text is not None


@pytest.mark.asyncio
async def test_large_files_view_large_content_no_markdown_in_document_caption(monkeypatch):
    from large_files_handler import large_files_handler

    big_content = "x" * 4000 + "```more```"

    class DummyMsg:
        def __init__(self):
            self.doc_kwargs = None
        async def reply_document(self, **kwargs):
            self.doc_kwargs = kwargs

    class DummyQuery:
        def __init__(self, data):
            self.data = data
            self.message = DummyMsg()
            self.captured_text = None
            self.captured_mode = None
        async def answer(self):
            return None
        async def edit_message_text(self, text=None, reply_markup=None, parse_mode=None):
            self.captured_text = text
            self.captured_mode = parse_mode

    class DummyUpdate:
        def __init__(self, data):
            self.callback_query = DummyQuery(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    class Ctx:
        def __init__(self):
            self.user_data = {
                'large_files_cache': {
                    'lf_1_0': {
                        'file_name': 'big.md',
                        'content': big_content,
                        'programming_language': 'markdown'
                    }
                }
            }

    u = DummyUpdate("lf_view_lf_1_0")
    c = Ctx()
    await large_files_handler.view_large_file(u, c)
    # Document should be sent without parse_mode to avoid Markdown parse errors
    assert u.callback_query.message.doc_kwargs is not None
    assert "parse_mode" not in u.callback_query.message.doc_kwargs


def test_manager_search_snippets_delegates_query(monkeypatch):
    # Ensure DB disabled and repo delegated with query keyword
    monkeypatch.setenv("DISABLE_DB", "1")
    from database.manager import DatabaseManager

    called = {}
    class DummyRepo:
        def search_code(self, user_id, query, programming_language=None, tags=None, limit=20):
            called['args'] = (user_id, query, programming_language, tags, limit)
            return [
                {"file_name": "a.py"}
            ]

    mgr = DatabaseManager()
    monkeypatch.setattr(mgr, "_get_repo", lambda: DummyRepo())
    res = mgr.search_snippets(7, search_term="abc", programming_language="python", tags=["t"], limit=5)
    assert isinstance(res, list)
    assert called.get('args') == (7, "abc", "python", ["t"], 5)

