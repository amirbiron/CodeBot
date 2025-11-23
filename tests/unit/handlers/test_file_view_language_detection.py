import types
import sys
import pytest


@pytest.mark.asyncio
async def test_edit_large_file_detects_bash_via_shebang(monkeypatch):
    import handlers.file_view as fv

    saved = {}

    # Stub database module to capture LargeFile save with detected language
    mod = types.ModuleType("database")

    class _LargeFile:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class _DB:
        @staticmethod
        def save_large_file(large_file):
            saved["language"] = getattr(large_file, "programming_language", None)
            return True

    mod.LargeFile = _LargeFile
    mod.db = _DB()
    monkeypatch.setitem(sys.modules, "database", mod)

    # Prepare update/context for large-file edit flow
    class Msg:
        def __init__(self):
            self.text = "#!/usr/bin/env bash\npython main.py\n"

        async def reply_text(self, *_a, **_kw):
            return None

    class U:
        def __init__(self):
            self.message = Msg()

        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    ctx = types.SimpleNamespace(
        user_data={"editing_large_file": {"file_name": "run"}}
    )

    await fv.receive_new_code(U(), ctx)
    assert saved.get("language") == "bash"


@pytest.mark.asyncio
async def test_edit_regular_file_detects_yaml_for_taskfile(monkeypatch):
    import handlers.file_view as fv

    calls = {}

    # Stub database module for regular file save
    class _DB:
        @staticmethod
        def save_file(user_id, file_name, content, detected_language):
            calls["language"] = detected_language
            return True

        @staticmethod
        def get_latest_version(user_id, file_name):
            return {"version": 1, "_id": "x1"}

    mod = types.ModuleType("database")
    mod.db = _DB()
    monkeypatch.setitem(sys.modules, "database", mod)

    # Make validation pass-through
    monkeypatch.setattr(
        fv.code_service,
        "validate_code_input",
        lambda code, file_name, user_id: (True, code, ""),
    )

    yaml_code = "version: '3'\ntasks:\n  run:\n    desc: Run\n    cmds:\n      - python main.py\n"

    class Msg:
        def __init__(self):
            self.text = yaml_code

        async def reply_text(self, *_a, **_kw):
            return None

    class U:
        def __init__(self):
            self.message = Msg()

        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    ctx = types.SimpleNamespace(
        user_data={
            "editing_file_data": {
                "file_name": "Taskfile",
                "code": "",
                "programming_language": "text",
            },
            "editing_file_index": "0",
            "files_cache": {"0": {"file_name": "Taskfile"}},
        }
    )

    await fv.receive_new_code(U(), ctx)
    assert calls.get("language") == "yaml"


@pytest.mark.asyncio
async def test_edit_regular_file_detects_env_for_dotenv(monkeypatch):
    import handlers.file_view as fv

    calls = {}

    class _DB:
        @staticmethod
        def save_file(user_id, file_name, content, detected_language):
            calls["language"] = detected_language
            return True

        @staticmethod
        def get_latest_version(user_id, file_name):
            return {"version": 1}

    mod = types.ModuleType("database")
    mod.db = _DB()
    monkeypatch.setitem(sys.modules, "database", mod)

    # Pass validation
    monkeypatch.setattr(
        fv.code_service,
        "validate_code_input",
        lambda code, file_name, user_id: (True, code, ""),
    )

    env_code = "BOT_TOKEN=\nOWNER_CHAT_ID=\n"

    class Msg:
        def __init__(self):
            self.text = env_code

        async def reply_text(self, *_a, **_kw):
            return None

    class U:
        def __init__(self):
            self.message = Msg()

        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    ctx = types.SimpleNamespace(
        user_data={
            "editing_file_data": {
                "file_name": ".ENV",
                "code": "",
                "programming_language": "text",
            },
            "editing_file_index": "0",
            "files_cache": {"0": {"file_name": ".ENV"}},
        }
    )

    await fv.receive_new_code(U(), ctx)
    assert calls.get("language") == "env"


@pytest.mark.asyncio
async def test_view_file_redetects_when_text_language(monkeypatch):
    from handlers.file_view import handle_view_file as view
    from handlers import file_view as fv

    # Capture message text to assert detected language
    captured = {}

    async def fake_edit(query, text, reply_markup=None, parse_mode=None):
        captured["text"] = text
        captured["parse_mode"] = parse_mode
        return None

    monkeypatch.setattr(fv.TelegramUtils, "safe_edit_message_text", fake_edit)

    class Q:
        def __init__(self):
            self.data = "view_0"

        async def answer(self):
            return None

    class U:
        def __init__(self):
            self.callback_query = Q()

        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    yaml_code = "version: '3'\nkey: val\n- list\n"
    ctx = types.SimpleNamespace(
        user_data={
            "files_cache": {
                "0": {
                    "file_name": "Taskfile",
                    "programming_language": "text",
                    "version": 1,
                    "code": yaml_code,
                }
            },
            "files_last_page": 1,
            "files_origin": {"type": "regular"},
        }
    )
    await view(U(), ctx)
    assert "yaml" in (captured.get("text") or ""), "expected re-detected 'yaml' to appear in message"


@pytest.mark.asyncio
async def test_view_file_keeps_markdown_for_plain_doc_md(monkeypatch):
    from handlers.file_view import handle_view_file as view
    from handlers import file_view as fv

    captured = {}

    async def fake_edit(query, text, reply_markup=None, parse_mode=None):
        captured["text"] = text
        captured["parse_mode"] = parse_mode
        return None

    monkeypatch.setattr(fv.TelegramUtils, "safe_edit_message_text", fake_edit)

    class Q:
        def __init__(self):
            self.data = "view_0"

        async def answer(self):
            return None

    class U:
        def __init__(self):
            self.callback_query = Q()

        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    md = "# כותרת\n\n- רשימה\n\nקישור: [דוגמה](https://example.com)\n"
    ctx = types.SimpleNamespace(
        user_data={
            "files_cache": {
                "0": {
                    "file_name": "doc.md",
                    "programming_language": "text",  # לא אמין → רידיטקט
                    "version": 1,
                    "code": md,
                }
            },
            "files_last_page": 1,
            "files_origin": {"type": "regular"},
        }
    )
    await view(U(), ctx)
    assert "markdown" in (captured.get("text") or ""), "expected 'markdown' to appear in message"

