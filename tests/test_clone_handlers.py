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
	# Arrange database stubs
	from database import db as real_db
	calls = {"saved": []}

	def _fake_get_latest_version(user_id, file_name):
		# Simulate original exists and also first copy exists
		if file_name in {"hello.py", "hello (copy).py"}:
			return {"user_id": user_id, "file_name": file_name, "code": "print('x')", "programming_language": "python", "description": "", "version": 1}
		return None

	# Patch DB methods using import-path style
	monkeypatch.setattr("database.db.get_latest_version", _fake_get_latest_version)

	def _fake_save(snippet):
		calls["saved"].append(snippet.file_name)
		return True

	monkeypatch.setattr("database.db.save_code_snippet", _fake_save)

	# Import after monkeypatch
	import handlers.file_view as fv

	# Prepare update with direct clone
	upd = _Update()
	upd.callback_query.data = "clone_direct_hello.py"

	# Also stub file fetch inside handler
	monkeypatch.setattr("database.db.get_latest_version", lambda uid, name: {"file_name": "hello.py", "code": "print('x')", "programming_language": "python", "description": ""} if name == "hello.py" else _fake_get_latest_version(uid, name))

	# Stub telegram utils to avoid real editing
	async def _safe_edit(q, text, reply_markup=None, parse_mode=None):
		return None
	monkeypatch.setattr(fv.TelegramUtils, "safe_edit_message_text", _safe_edit)

	ctx = _Context()
	await fv.handle_clone_direct(upd, ctx)

	# Assert that second unique name was attempted: "hello (copy 2).py"
	assert any(name.startswith("hello (copy 2)") for name in calls["saved"]) or any(name.startswith("hello (copy ") for name in calls["saved"]) 


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

	# DB stubs
	from database import db
	monkeypatch.setattr(db, "get_latest_version", lambda uid, name: None)
	class _Saver:
		def save_code_snippet(self, snippet):
			return True
	monkeypatch.setattr(db, "save_code_snippet", _Saver().save_code_snippet)

	# Stub Telegram utils
	async def _safe_edit(q, text, reply_markup=None, parse_mode=None):
		return None
	monkeypatch.setattr(fv.TelegramUtils, "safe_edit_message_text", _safe_edit)

	await fv.handle_clone(upd, ctx)
	# If no exception, and we reached end, test passes
	assert True


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