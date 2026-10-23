"""הצינור של היועץ (``handlers/advisor.py``): זיכרון ← מכסה ← מודל ← שליחה ← שמירה.

המודל והמסד מוחלפים בכפילים בזיכרון: כאן נבדקים הסדר, המנעול, מה נשמר ומה
נשלח. המסד האמיתי — ``test_advisor_store_mongo.py``; הניתוב מול
python-telegram-bot האמיתי — ``test_advisor_routing_real_ptb.py``.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from handlers import advisor
from handlers.advisor_text import RLM
from services import advisor_service, advisor_store


class FakeBot:
    """כפיל של ``telegram.Bot`` — רושם כל שליחה, ויכול לדחות HTML כמו טלגרם."""

    def __init__(self, reject_html_containing: str | None = None, send_delay: float = 0.0):
        self.sent: list[dict] = []
        self.reject_html_containing = reject_html_containing
        self.send_delay = send_delay

    async def send_message(self, **kwargs):
        from telegram.error import BadRequest

        if self.send_delay:
            await asyncio.sleep(self.send_delay)
        if (
            self.reject_html_containing
            and kwargs.get("parse_mode") == "HTML"
            and self.reject_html_containing in kwargs["text"]
        ):
            raise BadRequest("Can't parse entities")
        self.sent.append(kwargs)
        return SimpleNamespace(message_id=len(self.sent))

    async def send_chat_action(self, **kwargs):
        return True


class MemoryStore:
    """המסד של היועץ בזיכרון, באותן חתימות כמו ``services/advisor_store.py``."""

    def __init__(self):
        self.exchanges: dict[int, list[tuple[str, str]]] = {}
        self.allowed = True
        self.questions_taken = 0
        self.read_error = False
        self.write_error = False
        self._lock = threading.Lock()

    def get_history(self, user_id, now=None):
        if self.read_error:
            raise advisor_store.AdvisorStoreError("read failed")
        with self._lock:
            pairs = list(self.exchanges.get(user_id, []))[-advisor_store.CONTEXT_EXCHANGES:]
        messages = []
        for question, answer in pairs:
            messages += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        return messages

    def take_daily_question(self, user_id, now=None):
        self.questions_taken += 1
        return self.allowed

    def save_exchange(self, user_id, question, answer, now=None):
        if self.write_error:
            raise advisor_store.AdvisorStoreError("write failed")
        with self._lock:
            self.exchanges.setdefault(user_id, []).append((question, answer))


@pytest.fixture
def store(monkeypatch):
    memory = MemoryStore()
    monkeypatch.setattr(advisor_store, "get_history", memory.get_history)
    monkeypatch.setattr(advisor_store, "take_daily_question", memory.take_daily_question)
    monkeypatch.setattr(advisor_store, "save_exchange", memory.save_exchange)
    return memory


@pytest.fixture
def settings(monkeypatch):
    current = advisor_service.AdvisorSettings(
        api_key="k", base_url="https://llm.example.test/v1/", model="m", contact_url="https://t.me/someone"
    )
    monkeypatch.setattr(advisor_service, "current_settings", lambda: current)
    return current


def _context(bot):
    return SimpleNamespace(bot=bot, user_data={})


def _callbacks(message) -> list[str]:
    markup = message.get("reply_markup")
    if markup is None:
        return []
    return [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]


async def test_same_user_messages_are_answered_in_order(store, settings, monkeypatch):
    """שתי הודעות מהירות של אותו גולש: השנייה חייבת לראות את הראשונה בזיכרון."""
    seen_history_lengths = []

    async def fake_generate(history, text):
        seen_history_lengths.append(len(history))
        await asyncio.sleep(0.05)  # קריאה איטית למודל
        return advisor_service.Answer(text=f"תשובה ל-{text}", ok=True)

    monkeypatch.setattr(advisor_service, "generate_answer", fake_generate)
    bot = FakeBot()
    context = _context(bot)
    await asyncio.gather(
        advisor._answer_and_reply(context, user_id=1, chat_id=1, text="ראשונה"),
        advisor._answer_and_reply(context, user_id=1, chat_id=1, text="שנייה"),
    )
    assert seen_history_lengths == [0, 2]
    assert [m["text"] for m in bot.sent] == ["תשובה ל-ראשונה", "תשובה ל-שנייה"]


async def test_question_right_after_the_welcome_sees_it(store, settings, monkeypatch):
    """הפתיחה ושאלה מיד אחריה, במקביל: המודל חייב לקבל את הפתיחה בזיכרון."""
    seen_history = []

    async def fake_generate(history, text):
        seen_history.append([m["content"] for m in history])
        return advisor_service.Answer(text="תשובה", ok=True)

    monkeypatch.setattr(advisor_service, "generate_answer", fake_generate)
    # שליחה איטית: בלי המנעול, השאלה קוראת את הזיכרון לפני שהפתיחה נשמרה
    context = _context(FakeBot(send_delay=0.05))
    await asyncio.gather(
        advisor._send_welcome(context, user_id=1, chat_id=1, entry_text="/start advisor"),
        advisor._answer_and_reply(context, user_id=1, chat_id=1, text="כן, כל הזמן"),
    )
    assert seen_history == [["/start advisor", advisor.WELCOME_TEXT]]


async def test_every_reply_carries_the_exit_button(store, settings, monkeypatch):
    """פתיחה, תשובה, תשובת יצירת קשר, תקלה ומכסה מלאה — בכולן כפתור היציאה."""
    answers = iter([
        advisor_service.Answer(text="תשובה", ok=True),
        advisor_service.Answer(text="אין לי מידע", ok=True, needs_contact=True),
        advisor_service.Answer(text=advisor_service.FALLBACK_ERROR, ok=False),
    ])

    async def fake_generate(history, text):
        return next(answers)

    monkeypatch.setattr(advisor_service, "generate_answer", fake_generate)
    bot = FakeBot()
    context = _context(bot)
    await advisor._send_welcome(context, user_id=1, chat_id=1, entry_text="/advisor")
    for text in ("א", "ב", "ג"):
        await advisor._answer_and_reply(context, user_id=1, chat_id=1, text=text)
    store.allowed = False
    await advisor._answer_and_reply(context, user_id=1, chat_id=1, text="ד")
    store.read_error = True
    await advisor._answer_and_reply(context, user_id=1, chat_id=1, text="ה")

    assert [m["text"] for m in bot.sent] == [
        advisor.WELCOME_TEXT, "תשובה", "אין לי מידע", advisor_service.FALLBACK_ERROR,
        advisor.LIMIT_TEXT, advisor.STORE_ERROR_TEXT,
    ]
    assert all(advisor.EXIT_CALLBACK in _callbacks(m) for m in bot.sent)
    contact_rows = bot.sent[2]["reply_markup"].inline_keyboard
    assert contact_rows[0][0].url == "https://t.me/someone"


async def test_full_quota_skips_the_model(store, settings, monkeypatch):
    called = []

    async def fake_generate(history, text):
        called.append(text)
        return advisor_service.Answer(text="לא אמור לרוץ", ok=True)

    monkeypatch.setattr(advisor_service, "generate_answer", fake_generate)
    store.allowed = False
    bot = FakeBot()
    await advisor._answer_and_reply(_context(bot), user_id=1, chat_id=1, text="שאלה")
    assert called == []
    assert bot.sent[0]["text"] == advisor.LIMIT_TEXT
    assert store.exchanges == {}


async def test_history_read_failure_skips_the_model_and_the_quota(store, settings, monkeypatch, caplog):
    """הזיכרון נקרא לפני המכסה: תקלה בקריאה לא גובה שאלה."""
    called = []

    async def fake_generate(history, text):
        called.append(text)
        return advisor_service.Answer(text="לא אמור לרוץ", ok=True)

    monkeypatch.setattr(advisor_service, "generate_answer", fake_generate)
    store.read_error = True
    bot = FakeBot()
    caplog.set_level("ERROR")
    await advisor._answer_and_reply(_context(bot), user_id=7, chat_id=7, text="שאלה סודית")
    assert called == [] and store.questions_taken == 0
    assert bot.sent[0]["text"] == advisor.STORE_ERROR_TEXT
    assert "Advisor storage unavailable for user 7" in caplog.text
    assert "שאלה סודית" not in caplog.text


async def test_failed_answer_is_not_saved(store, settings, monkeypatch):
    async def fake_generate(history, text):
        return advisor_service.Answer(text=advisor_service.FALLBACK_ERROR, ok=False)

    monkeypatch.setattr(advisor_service, "generate_answer", fake_generate)
    bot = FakeBot()
    await advisor._answer_and_reply(_context(bot), user_id=1, chat_id=1, text="שאלה")
    assert bot.sent[0]["text"] == advisor_service.FALLBACK_ERROR
    assert store.exchanges == {}


async def test_save_failure_is_logged_and_follow_ups_still_arrive(store, settings, monkeypatch, caplog):
    async def fake_generate(history, text):
        return advisor_service.Answer(text="כן", ok=True, follow_up_questions=["א?"])

    monkeypatch.setattr(advisor_service, "generate_answer", fake_generate)
    store.write_error = True
    bot = FakeBot()
    caplog.set_level("ERROR")
    await advisor._answer_and_reply(_context(bot), user_id=3, chat_id=3, text="שאלה")
    assert [m["text"] for m in bot.sent] == ["כן", advisor.FOLLOW_UP_HEADER]
    assert "Advisor history not saved for user 3" in caplog.text


async def test_follow_ups_are_stored_per_user_with_short_callback_data(store, settings, monkeypatch):
    async def fake_generate(history, text):
        return advisor_service.Answer(text="כן", ok=True, follow_up_questions=["שאלה ארוכה מאוד " * 10, "ב?"])

    monkeypatch.setattr(advisor_service, "generate_answer", fake_generate)
    bot = FakeBot()
    context = _context(bot)
    await advisor._answer_and_reply(context, user_id=1, chat_id=1, text="שאלה")
    follow_up_message = bot.sent[-1]
    callbacks = _callbacks(follow_up_message)
    assert len(callbacks) == 2
    assert all(cb.startswith(advisor.FOLLOW_UP_PREFIX) and len(cb.encode()) <= 64 for cb in callbacks)
    stored = context.user_data["advisor_follow_ups"]
    assert stored[callbacks[1][len(advisor.FOLLOW_UP_PREFIX):]] == "ב?"


def test_follow_up_store_keeps_only_the_newest():
    user_data: dict = {}
    for i in range(5):
        advisor._store_follow_ups(user_data, [f"{i}-א", f"{i}-ב", f"{i}-ג"])
    questions = list(user_data["advisor_follow_ups"].values())
    assert len(questions) == advisor._MAX_STORED_FOLLOW_UPS
    assert questions[-1] == "4-ג" and "0-א" not in questions


async def test_english_first_lines_reach_telegram_rtl_but_history_stays_clean(store, settings, monkeypatch):
    """טלגרם מציג שורה עברית שמתחילה באנגלית משמאל לימין — RLM מתקן, רק ביציאה."""
    answer_text = "<b>CodeKeeper</b> עוזר למפתחים.\nהמסמך נגיש מכל סוכן."

    async def fake_generate(history, text):
        return advisor_service.Answer(text=answer_text, ok=True, follow_up_questions=["Claude Code מתאים לי?"])

    monkeypatch.setattr(advisor_service, "generate_answer", fake_generate)
    bot = FakeBot()
    await advisor._answer_and_reply(_context(bot), user_id=1, chat_id=1, text="שאלה")
    first, second = bot.sent[0]["text"].split("\n")
    assert first.startswith(RLM) and not second.startswith(RLM)
    assert bot.sent[-1]["reply_markup"].inline_keyboard[0][0].text.startswith(RLM)
    assert store.exchanges[1] == [("שאלה", answer_text)]  # הזיכרון בלי סימנים נסתרים


async def test_rejected_html_falls_back_to_plain_text_with_explicit_parse_mode_none():
    """לבוט מוגדר Defaults(parse_mode=HTML), ולכן הטקסט הנקי חייב parse_mode=None מפורש."""
    bot = FakeBot(reject_html_containing="<b>")
    await advisor._send_text(bot, 1, "<b>כותרת</b> & עוד")
    assert bot.sent == [{"chat_id": 1, "text": "כותרת & עוד", "parse_mode": None, "reply_markup": None}]


async def test_long_answer_is_split_and_buttons_go_on_the_last_chunk():
    text = "\n\n".join(["פסקה " + "מילה " * 200] * 6)  # כ-6,000 תווים
    bot = FakeBot()
    await advisor._send_text(bot, 1, text, reply_markup="KB")
    assert len(bot.sent) == 2
    assert all(len(m["text"]) <= 4096 for m in bot.sent)
    assert [m["reply_markup"] for m in bot.sent] == [None, "KB"]
