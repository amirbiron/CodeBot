"""קוד שמודבק בבוט עובר ניקוי מינימלי אחד, ממש לפני השמירה — ורק הוא.

**דרך ה-handlers הרשומים.** השיחה נבנית ב-
``conversation_handlers.get_save_conversation_handler()``, והטסט שולף ממנה את
ה-callback של כל מצב (``GET_CODE`` ← ``GET_FILENAME`` ← ``GET_NOTE``, ו-``EDIT_CODE``)
ואת נקודת הכניסה לעריכה, ומריץ אותם בסדר שהמשתמש עובר. ``/save`` נשלף מה-
handlers ש-``CodeKeeperBot`` רושם. בטסטים ``telegram.ext`` הוא הסטאב של
``tests/_telegram_stubs.py``, ששומר את ``states`` ואת ``entry_points`` ב-``kwargs``.

**מה שנשמר נקרא מהאוסף**, מעל ``DatabaseManager`` ו-``Repository`` אמיתיים ועם
``config.py`` של הייצור — ראו ``tests/_save_layer_harness.py``.

**מה מצופה** — ``clean_pasted_code``: בכל קובץ CRLF ← LF ו-BOM בתחילה נמחק; בקוד
שאינו Markdown גם רווחי ``Zs``, ZWSP ורווחים בסוף שורה. RLM, תווי override
ו-isolate, וה-newline בסוף נשארים. הודעת ההצלחה אומרת מה נוקה, ומזהירה על
override ו-isolate. תווי כיווניות כתובים רק כ-escapes (H1).
"""

from __future__ import annotations

import asyncio
import itertools
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _save_layer_harness import clear_local_cache, install_fake_collections, latest, load_production_config

import conversation_handlers as ch
from handlers.states import EDIT_CODE, GET_CODE, GET_FILENAME, GET_NOTE

USER = 7117
BOM, NBSP, ZWSP, RLM = "\ufeff", "\u00a0", "\u200b", "\u200f"
RLO, LRI, FSI, PDI = "\u202e", "\u2066", "\u2068", "\u2069"
_update_ids = itertools.count(1)


@pytest.fixture
def store(monkeypatch):
    monkeypatch.delenv("USE_NEW_SAVE_FLOW", raising=False)
    load_production_config(monkeypatch)
    yield install_fake_collections(monkeypatch)
    clear_local_cache()


class _Message:
    def __init__(self, text: str, replies: List[str]):
        self.text = text
        self.caption = None
        self.entities = None
        self.document = None
        self.from_user = SimpleNamespace(id=USER, username="tester", first_name="T")
        self.chat_id = 1
        self.message_id = next(_update_ids)
        self._replies = replies

    async def reply_text(self, text, *args, **kwargs):
        self._replies.append(text)
        return SimpleNamespace(chat_id=1, message_id=next(_update_ids))


class _Query:
    def __init__(self, data: str, replies: List[str]):
        self.data = data
        self.from_user = SimpleNamespace(id=USER, username="tester", first_name="T")
        self.message = _Message("", replies)
        self._replies = replies

    async def answer(self, *args, **kwargs):
        return None

    async def edit_message_text(self, text, *args, **kwargs):
        self._replies.append(text)


class _Chat:
    """שיחה אחת: ``user_data`` נשמר בין ההודעות, כמו ב-PTB."""

    def __init__(self):
        self.user_data: Dict[str, Any] = {}
        self.replies: List[str] = []
        self.context = SimpleNamespace(
            user_data=self.user_data,
            chat_data={},
            bot_data={},
            args=[],
            bot=SimpleNamespace(),
            job_queue=SimpleNamespace(run_once=lambda *a, **k: None),
            application=SimpleNamespace(bot_data={}),
        )

    def _update(self, message=None, query=None):
        return SimpleNamespace(
            update_id=next(_update_ids),
            message=message,
            callback_query=query,
            effective_user=SimpleNamespace(id=USER, username="tester", first_name="T"),
            effective_chat=SimpleNamespace(id=1),
        )

    def text(self, handler, text: str, args: Optional[List[str]] = None):
        self.context.args = list(args or [])
        return asyncio.run(handler(self._update(message=_Message(text, self.replies)), self.context))

    def tap(self, handler, data: str):
        return asyncio.run(handler(self._update(query=_Query(data, self.replies)), self.context))


def _conversation():
    conv = ch.get_save_conversation_handler()
    kwargs = getattr(conv, "kwargs", {})
    states = getattr(conv, "states", None) or kwargs["states"]
    entry_points = getattr(conv, "entry_points", None) or kwargs["entry_points"]
    return states, entry_points


def _text_callback(handlers):
    """ה-callback של ה-MessageHandler במצב (ולא של CallbackQueryHandler שלצידו)."""
    found = [h.callback for h in handlers if type(h).__name__ == "MessageHandler"]
    assert len(found) == 1, found
    return found[0]


def _entry_callback(entry_points, callback_data: str):
    """נקודת הכניסה שה-pattern שלה תופס את ה-callback_data."""
    import re

    for h in entry_points:
        pattern = getattr(h, "pattern", None) or getattr(h, "kwargs", {}).get("pattern")
        if pattern is not None and re.match(getattr(pattern, "pattern", pattern), callback_data):
            return h.callback
    raise AssertionError(f"אין נקודת כניסה ל-{callback_data}")


def _save_new_file(file_name: str, pasted: str) -> _Chat:
    """GET_CODE ← GET_FILENAME ← GET_NOTE, דרך ה-callbacks הרשומים."""
    states, _ = _conversation()
    chat = _Chat()
    assert chat.text(_text_callback(states[GET_CODE]), pasted) == GET_FILENAME
    assert chat.text(_text_callback(states[GET_FILENAME]), file_name) == GET_NOTE
    chat.text(_text_callback(states[GET_NOTE]), "דלג")
    return chat


def test_new_python_file_gets_the_minimal_cleaning_and_the_notice(store):
    pasted = BOM + "def f():" + NBSP + "\r\n    return 1  \r\n" + ZWSP + "x = 'גרסה" + RLM + "'\r\n"
    chat = _save_new_file("pasted.py", pasted)

    assert latest(store.code_snippets, USER, "pasted.py")["code"] == (
        "def f():\n    return 1\nx = 'גרסה" + RLM + "'\n"
    )
    success = chat.replies[-1]
    assert "🧹 ניקיתי מהקוד:" in success
    assert "3 סופי שורה של Windows" in success and "ZWSP אחד" in success
    assert "⚠️" not in success


def test_new_markdown_file_only_loses_crlf_and_the_bom(store):
    pasted = BOM + "# כותרת\r\nשורה עם שבירה  \r\nגרסה" + RLM + " 2.0" + NBSP + ZWSP + "\r\n"
    chat = _save_new_file("notes.md", pasted)

    assert latest(store.code_snippets, USER, "notes.md")["code"] == (
        "# כותרת\nשורה עם שבירה  \nגרסה" + RLM + " 2.0" + NBSP + ZWSP + "\n"
    )
    assert "3 סופי שורה של Windows" in chat.replies[-1]


def test_override_and_isolate_chars_stay_and_are_warned_about(store):
    pasted = (
        "ok = True\n"
        'if access_level != "user' + RLO + " " + LRI + "// admin" + PDI + " " + LRI + '":\n'
        "    pass\n"
        'name = "' + FSI + "משתמש" + PDI + '"\n'
    )
    chat = _save_new_file("trojan.py", pasted)

    assert latest(store.code_snippets, USER, "trojan.py")["code"] == pasted
    success = chat.replies[-1]
    assert "⚠️ בשורות 2 ו-4 יש תווים שמשנים את סדר התצוגה." in success
    assert "לא נגעתי בהם." in success
    assert "🧹" not in success  # לא נוקה דבר


def test_editing_a_file_cleans_once_before_the_save(store):
    existing = {
        "_id": 101,
        "user_id": USER,
        "file_name": "edit.py",
        "code": "x = 0\n",
        "programming_language": "python",
        "description": "",
        "tags": [],
        "version": 1,
        "is_active": True,
    }
    store.code_snippets.insert_one(dict(existing))
    states, entry_points = _conversation()
    chat = _Chat()
    chat.user_data["files_cache"] = {"0": dict(existing)}

    assert chat.tap(_entry_callback(entry_points, "edit_code_0"), "edit_code_0") == EDIT_CODE
    chat.text(_text_callback(states[EDIT_CODE]), "x = 1" + NBSP + " \r\ny = 'גרסה" + RLM + "'\r\n")

    saved = latest(store.code_snippets, USER, "edit.py")
    assert saved["version"] == 2
    assert saved["code"] == "x = 1\ny = 'גרסה" + RLM + "'\n"
    assert "🧹 ניקיתי מהקוד:" in chat.replies[-1]


def test_editing_a_large_file_cleans_before_the_save(store):
    """עד היום הקוד כאן נוקה רק בשכבת השמירה, ולכן הוא צריך נקודת ניקוי משלו."""
    store.large_files.insert_one({
        "user_id": USER,
        "file_name": "big.md",
        "content": "old\n",
        "programming_language": "markdown",
        "is_active": True,
    })
    states, entry_points = _conversation()
    chat = _Chat()
    chat.user_data["large_files_cache"] = {"0": {"file_name": "big.md"}}

    assert chat.tap(_entry_callback(entry_points, "lf_edit_0"), "lf_edit_0") == EDIT_CODE
    chat.text(_text_callback(states[EDIT_CODE]), BOM + "שורה  \r\nגרסה" + RLM + "\r\n")

    active = [d for d in store.large_files.docs if d.get("file_name") == "big.md" and d.get("is_active")]
    assert len(active) == 1
    assert active[0]["content"] == "שורה  \nגרסה" + RLM + "\n"
    assert "🧹 ניקיתי מהקוד:" in chat.replies[-1]


def test_the_save_command_cleans_before_the_save(store):
    """``/save <שם>`` ואז הקוד ואז ההערה — דרך ה-handlers ש-``CodeKeeperBot`` רושם."""
    import main

    bot = main.CodeKeeperBot()
    handlers = [args[0] for args, _kwargs in bot.application.handlers]
    save_cb = next(
        h.callback for h in handlers
        if type(h).__name__ == "CommandHandler" and "save" in (getattr(h, "commands", None) or ())
    )
    text_cbs = [
        h.callback for h in handlers
        if type(h).__name__ == "MessageHandler" and getattr(h.callback, "__name__", "") == "handle_text_message"
    ]
    assert save_cb == bot.save_command
    assert text_cbs, "אין MessageHandler רשום ל-handle_text_message"
    text_cb = text_cbs[0]

    chat = _Chat()
    chat.text(save_cb, "/save cmd.py", args=["cmd.py"])
    chat.text(text_cb, "a = 1  \r\nb = 'גרסה" + RLM + "'\r\n")
    chat.text(text_cb, "דלג")

    assert latest(store.code_snippets, USER, "cmd.py")["code"] == "a = 1\nb = 'גרסה" + RLM + "'\n"
    assert "🧹 ניקיתי מהקוד:" in chat.replies[-1]
