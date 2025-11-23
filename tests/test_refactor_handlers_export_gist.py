import sys
import pytest

from refactoring_engine import RefactorProposal, RefactorType


class _App:
    def add_handler(self, *args, **kwargs):
        return None


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append((text, kwargs))


class _Query:
    def __init__(self):
        self.data = ""
        self.message = _Msg()

    async def answer(self, *args, **kwargs):
        return None

    async def edit_message_text(self, *args, **kwargs):
        return None


class _Ctx:
    pass


def _build_update(user_id: int, query) -> object:
    class _User:
        id = user_id

    class _Upd:
        effective_user = _User()
        callback_query = query

    return _Upd()


@pytest.mark.asyncio
async def test_export_gist_success(monkeypatch):
    sys.modules.pop("refactor_handlers", None)
    mod = __import__("refactor_handlers")
    RH = getattr(mod, "RefactorHandlers")

    rh = RH(_App())
    user_id = 42
    query = _Query()
    rh.pending_proposals[user_id] = RefactorProposal(
        refactor_type=RefactorType.SPLIT_FUNCTIONS,
        original_file="large.py",
        new_files={"large_part_a.py": "print('a')"},
        description="desc",
        changes_summary=["split"],
    )

    class _Gist:
        def __init__(self):
            self.calls = 0

        def is_available(self):
            return True

        def create_gist_multi(self, files_map, description, public=True):
            self.calls += 1
            assert "large_part_a.py" in files_map
            return {"url": "https://gist.github.com/demo"}

    gist_stub = _Gist()
    integrations_mod = __import__("integrations")
    monkeypatch.setattr(integrations_mod, "gist_integration", gist_stub, raising=True)

    query.data = "refactor_action:export_gist"
    await rh.handle_proposal_callback(_build_update(user_id, query), _Ctx())

    assert gist_stub.calls == 1
    assert any("https://gist.github.com/demo" in text for text, _ in query.message.sent)


@pytest.mark.asyncio
async def test_export_gist_unavailable(monkeypatch):
    sys.modules.pop("refactor_handlers", None)
    mod = __import__("refactor_handlers")
    RH = getattr(mod, "RefactorHandlers")

    rh = RH(_App())
    user_id = 7
    query = _Query()
    rh.pending_proposals[user_id] = RefactorProposal(
        refactor_type=RefactorType.SPLIT_FUNCTIONS,
        original_file="large.py",
        new_files={"large_part_a.py": "print('a')"},
        description="desc",
        changes_summary=["split"],
    )

    class _Gist:
        def __init__(self):
            self.calls = 0

        def is_available(self):
            return False

        def create_gist_multi(self, *args, **kwargs):
            self.calls += 1
            return {"url": "https://gist.github.com/demo"}

    gist_stub = _Gist()
    integrations_mod = __import__("integrations")
    monkeypatch.setattr(integrations_mod, "gist_integration", gist_stub, raising=True)

    query.data = "refactor_action:export_gist"
    await rh.handle_proposal_callback(_build_update(user_id, query), _Ctx())

    assert gist_stub.calls == 0
    assert any("לא זמין" in text for text, _ in query.message.sent)
