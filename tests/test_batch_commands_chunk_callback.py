import types
import pytest


@pytest.mark.asyncio
async def test_batch_callbacks_chunk_invokes_lazy_loader(monkeypatch):
    bc = __import__('batch_commands')

    # stub lazy_loader.lazy_loader.show_large_file_lazy
    ll = __import__('lazy_loader')
    called = {'ok': False}
    async def _show(update, user_id, file_name, chunk_index):
        called['ok'] = True
    monkeypatch.setattr(ll.lazy_loader, 'show_large_file_lazy', _show, raising=True)

    class _Q:
        data = 'chunk:file.py:1'
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
    class _Upd:
        callback_query = _Q()
        effective_user = type('U', (), {'id': 1})()
    class _Ctx:
        pass

    await bc.handle_batch_callbacks(_Upd(), _Ctx())
    assert called['ok'] is True

