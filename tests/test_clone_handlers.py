import types
import pytest

# Stubs for telegram objects
class _Msg:
	def __init__(self):
		self._text = None
	async def reply_text(self, text, **kwargs):
		self._text = text
		return self
	async def edit_text(self, text, **kwargs):
		self._text = text
		return self

class _Query:
	def __init__(self):
		self.message = _Msg()
		self.data = ""
		self.from_user = types.SimpleNamespace(id=1)
	async def edit_message_text(self, text, **kwargs):
		return self.message
	async def answer(self, *args, **kwargs):
		return None

class _Update:
	def __init__(self):
		self.callback_query = _Query()
		self.effective_user = types.SimpleNamespace(id=1)

class _Context:
	def __init__(self):
		self.user_data = {}
		self.bot_data = {}

@pytest.mark.asyncio
async def test_clone_direct_creates_unique_name(monkeypatch):
	import handlers.file_view as fv
	upd = _Update()
	upd.callback_query.data = "clone_direct_hello.py"

	class _Facade:
		def __init__(self):
			self.saved = []
		def get_latest_version(self, user_id, file_name):
			if file_name == "hello.py":
				return {"file_name": file_name, "code": "print('x')", "programming_language": "python", "description": "", "tags": []}
			if file_name == "hello (copy).py":
				return {"file_name": file_name, "code": "print('x')", "programming_language": "python", "description": "", "tags": []}
			return None
		def save_code_snippet(self, *, user_id, file_name, code, programming_language, description, tags):
			self.saved.append(file_name)
			return True

	facade = _Facade()
	monkeypatch.setattr("src.infrastructure.composition.get_files_facade", lambda: facade, raising=False)

	# Stub telegram utils to avoid real editing
	async def _safe_edit(q, text, reply_markup=None, parse_mode=None):
		return None
	monkeypatch.setattr(fv.TelegramUtils, "safe_edit_message_text", _safe_edit)

	ctx = _Context()
	await fv.handle_clone_direct(upd, ctx)

	# Assert that second unique name was attempted: "hello (copy 2).py"
	assert any(name.startswith("hello (copy 2)") for name in facade.saved) or any(name.startswith("hello (copy ") for name in facade.saved)


@pytest.mark.asyncio
async def test_clone_from_list_uses_cache_and_succeeds(monkeypatch):
	# Arrange cache item
	import handlers.file_view as fv
	upd = _Update()
	ctx = _Context()
	ctx.user_data["files_cache"] = {
		"3": {"file_name": "a.txt", "code": "hi", "programming_language": "text", "description": "note", "tags": ["x"]}
	}
	upd.callback_query.data = "clone_3"

	class _Facade:
		def __init__(self):
			self.saved = False
		def get_latest_version(self, user_id, file_name):
			return None
		def save_code_snippet(self, *, user_id, file_name, code, programming_language, description, tags):
			self.saved = True
			return True

	facade = _Facade()
	monkeypatch.setattr("src.infrastructure.composition.get_files_facade", lambda: facade, raising=False)

	# Stub Telegram utils
	async def _safe_edit(q, text, reply_markup=None, parse_mode=None):
		return None
	monkeypatch.setattr(fv.TelegramUtils, "safe_edit_message_text", _safe_edit)

	await fv.handle_clone(upd, ctx)
	# If no exception, and we reached end, test passes
	assert facade.saved is True


@pytest.mark.asyncio
async def test_clone_from_list_fetches_code_when_missing(monkeypatch):
	import handlers.file_view as fv
	upd = _Update()
	ctx = _Context()
	ctx.user_data["files_cache"] = {
		"1": {"file_name": "missing.py", "code": "", "programming_language": "text", "description": "", "tags": []}
	}
	upd.callback_query.data = "clone_1"

	class _Facade:
		def __init__(self):
			self.saved = None
		def get_latest_version(self, user_id, file_name):
			return {
				"file_name": file_name,
				"code": "print('server')",
				"programming_language": "python",
				"description": "srv",
				"tags": ["t"],
			}
		def save_code_snippet(self, *, user_id, file_name, code, programming_language, description, tags):
			self.saved = {
				"user_id": user_id,
				"file_name": file_name,
				"code": code,
				"programming_language": programming_language,
				"description": description,
				"tags": list(tags or []),
			}
			return True

	facade = _Facade()
	monkeypatch.setattr("src.infrastructure.composition.get_files_facade", lambda: facade, raising=False)

	async def _safe_edit(q, text, reply_markup=None, parse_mode=None):
		return None
	monkeypatch.setattr(fv.TelegramUtils, "safe_edit_message_text", _safe_edit)

	await fv.handle_clone(upd, ctx)
	assert facade.saved is not None
	assert facade.saved["code"] == "print('server')"


@pytest.mark.asyncio
async def test_back_after_view_keyboard_contains_note_button(monkeypatch):
	# Import callback router
	import conversation_handlers as ch

	upd = _Update()
	ctx = _Context()
	# Prepare state as if just saved
	ctx.user_data["last_save_success"] = {
		"file_name": "b.py",
		"language": "python",
		"note": "",
		"file_id": ""
	}
	upd.callback_query.data = "back_after_view:b.py"

	# Monkeypatch telegram classes to capture reply_markup structure
	captured = {"kb": None}
	class _Btn:
		def __init__(self, text, callback_data=None):
			self.text = text
			self.callback_data = callback_data
	class _Markup:
		def __init__(self, rows):
			captured["kb"] = rows
	monkeypatch.setattr(ch, "InlineKeyboardButton", _Btn)
	monkeypatch.setattr(ch, "InlineKeyboardMarkup", _Markup)

	# Execute
	await ch.handle_callback_query(upd, ctx)

	# Verify that one of the rows contains the note button with the expected text
	texts = [btn.text for row in (captured["kb"] or []) for btn in row]
	assert any("הוסף הערה" in t or "ערוך הערה" in t for t in texts)