import sys
import types
import pytest


@pytest.fixture(autouse=True)
def stub_db(monkeypatch):
    class _DB:
        def __init__(self):
            self.saved = {}
        def get_file(self, user_id, filename):
            return {"code": "def a():\n    return 1\n\ndef b():\n    return 2\n", "file_name": filename, "programming_language": "python"}
        def save_file(self, user_id: int, file_name: str, code: str, programming_language: str, extra_tags=None):
            self.saved[file_name] = code
            return True
        def collection(self, name):
            return types.SimpleNamespace(insert_one=lambda doc: types.SimpleNamespace(inserted_id="1"))
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)
    return db_mod.db


@pytest.mark.asyncio
async def test_refactor_command_menu(monkeypatch):
    # Lazy import to avoid telegram deps
    sys.modules.pop('refactor_handlers', None)
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    # Minimal application stub
    class _App:
        def __init__(self):
            self.handlers = []
        def add_handler(self, *a, **k):
            self.handlers.append((a, k))

    app = _App()
    rh = RH(app)
    # Build Update/Context stubs
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _User: id = 1
    class _Upd:
        effective_user = _User()
        message = _Msg()
    class _Ctx:
        args = ["test.py"]
    await rh.refactor_command(_Upd(), _Ctx())


@pytest.mark.asyncio
async def test_refactor_split_and_approve_flow(monkeypatch):
    sys.modules.pop('refactor_handlers', None)
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def __init__(self):
            self.handlers = []
        def add_handler(self, *a, **k):
            self.handlers.append((a, k))

    # minimal Query stub
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _Q:
        data = ''
        message = _Msg()
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None

    class _User: id = 7
    class _Upd:
        effective_user = _User()
        callback_query = _Q()
    class _Ctx: pass

    rh = RH(_App())

    # Simulate choosing split_functions for file 'test.py'
    q = rh.handle_refactor_type_callback
    _Upd.callback_query.data = 'refactor_type:split_functions:test.py'
    await q(_Upd, _Ctx())

    # After proposal stored, simulate approve
    _Upd.callback_query.data = 'refactor_action:approve'
    await rh.handle_proposal_callback(_Upd, _Ctx())

