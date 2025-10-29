import asyncio
import io
import types
import zipfile

import pytest


@pytest.mark.asyncio
async def test_download_zip_folder_uses_high_compression(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    # user session
    handler.get_user_session = lambda uid: {"selected_repo": "o/r"}
    handler.get_user_token = lambda uid: "t"

    # fake repo API for folder path
    class _Item:
        def __init__(self, t, name, size=0, data=b""):
            self.type = t
            self.name = name
            self.path = name
            self.size = size
            self.decoded_content = data

    class _Repo:
        name = "r"
        full_name = "o/r"
        def get_contents(self, path):
            if not path:
                return [_Item('file', 'a.txt', len(b'a'), b'a')]
            return [_Item('file', 'b.txt', len(b'bb'), b'bb')]

    class _Gh:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, _):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)

    # Capture document sent to user and inspect the in-memory zip
    sent = {}
    class _Msg:
        async def reply_document(self, document=None, filename=None, caption=None):
            sent['doc'] = document
            sent['filename'] = filename
            sent['caption'] = caption
        async def reply_text(self, text, **kwargs):
            sent['text'] = text

    class _Q:
        def __init__(self):
            self.data = "download_zip:folder"
            self.message = _Msg()
            self.from_user = types.SimpleNamespace(id=5)
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None

    upd = types.SimpleNamespace(callback_query=_Q(), effective_user=types.SimpleNamespace(id=5))
    ctx = types.SimpleNamespace(user_data={})

    # Force the "build local zip" branch by providing a non-empty path
    def _get_path_from_cb(context, data, prefix):
        return "folder"
    monkeypatch.setattr(handler, "_get_path_from_cb", _get_path_from_cb)

    await handler.handle_menu_callback(upd, ctx)

    # Now read the produced zip from memory
    assert 'doc' in sent and isinstance(sent['doc'], io.BytesIO)
    bio = sent['doc']
    bio.seek(0)
    with zipfile.ZipFile(bio, 'r') as zf:
        # presence check and comment on compression type
        names = set(zf.namelist())
        assert any(n.endswith('a.txt') or n.endswith('b.txt') for n in names)
        # Each entry should use deflate (ZIP_DEFLATED)
        for info in zf.infolist():
            assert info.compress_type == zipfile.ZIP_DEFLATED
