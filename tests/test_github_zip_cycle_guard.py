import types
import io
import pytest


def _capture_zipfile(monkeypatch, module_under_test):
    captured = {"calls": []}

    import zipfile as _real_zipfile

    def ZipFileWrapper(
        file,
        mode="r",
        compression=_real_zipfile.ZIP_STORED,
        allowZip64=True,
        compresslevel=None,
        **kwargs,
    ):
        captured["calls"].append(
            {
                "mode": mode,
                "compression": compression,
                "compresslevel": compresslevel,
            }
        )
        return _real_zipfile.ZipFile(
            file,
            mode=mode,
            compression=compression,
            allowZip64=allowZip64,
            compresslevel=compresslevel,
            **kwargs,
        )

    monkeypatch.setattr(module_under_test.zipfile, "ZipFile", ZipFileWrapper, raising=True)
    return captured


@pytest.mark.asyncio
async def test_github_zip_folder_cycle_is_guarded(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    handler.get_user_session = lambda uid: {"selected_repo": "o/r"}
    handler.get_user_token = lambda uid: "t"

    # Fake GitHub API with a directory cycle: folder/a -> folder/a
    class _Item:
        def __init__(self, t, name, path, size=0, data=b""):
            self.type = t
            self.name = name
            self.path = path
            self.size = size
            self.decoded_content = data

    class _Repo:
        name = "r"
        full_name = "o/r"

        def get_contents(self, path):
            if path in ("", None):  # root
                return [_Item("dir", "folder", "folder")]
            if path == "folder":
                # folder contains a dir 'a' and also a file to include
                return [
                    _Item("dir", "a", "folder/a"),
                    _Item("file", "root.txt", "folder/root.txt", size=1, data=b"r"),
                ]
            if path == "folder/a":
                # cycle: points back to itself, plus a file
                return [
                    _Item("dir", "a", "folder/a"),
                    _Item("file", "f.txt", "folder/a/f.txt", size=1, data=b"x"),
                ]
            # default: empty
            return []

    class _Gh:
        def __init__(self, *a, **k):
            pass

        def get_repo(self, _):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)

    captured = _capture_zipfile(monkeypatch, gh)

    class _Msg:
        async def reply_document(self, document=None, filename=None, caption=None):
            return None

        async def reply_text(self, *a, **k):
            return None

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

    # Force folder path flow
    monkeypatch.setattr(handler, "_get_path_from_cb", lambda context, data, prefix: "folder", raising=True)

    # Act
    await handler.handle_menu_callback(upd, ctx)

    # Assert: both creation ('w') and metadata append ('a') used compresslevel=9
    assert any(c["mode"] == "w" and c["compresslevel"] == 9 for c in captured["calls"])  # build zip
    assert any(c["mode"] == "a" and c["compresslevel"] == 9 for c in captured["calls"])  # metadata
