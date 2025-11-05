import types
import pytest


@pytest.mark.asyncio
async def test_handle_download_file_uses_safe_answer(monkeypatch):
    # Arrange: monkeypatch TelegramUtils.safe_answer to observe it was called
    from utils import TelegramUtils

    called = {"flag": False}

    async def fake_safe_answer(query, text=None, show_alert=False, cache_time=None):
        called["flag"] = True
        return None

    monkeypatch.setattr(TelegramUtils, "safe_answer", fake_safe_answer, raising=True)

    # Minimal update/context with files_cache and dl_ path to avoid DB calls
    class Q:
        def __init__(self):
            self.data = "dl_7"
            self.message = types.SimpleNamespace(reply_document=self._reply_document)

        async def _reply_document(self, **kwargs):
            return None

        async def edit_message_text(self, *a, **kw):
            return None

    class U:
        def __init__(self):
            self.callback_query = Q()

        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    class Ctx:
        def __init__(self):
            self.user_data = {
                "files_cache": {
                    "7": {
                        "file_name": "d.py",
                        "code": "print(1)",
                        "programming_language": "python",
                    }
                }
            }

    from conversation_handlers import handle_download_file

    # Act
    u = U()
    ctx = Ctx()
    await handle_download_file(u, ctx)

    # Assert
    assert called["flag"] is True
