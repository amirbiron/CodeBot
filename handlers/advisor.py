"""מצב היועץ — שיחה עם AI שעונה אם CodeKeeper מתאים לאופן שבו הגולש עובד.

עבר מהבוט הנפרד ``codekeeper_advisor_bot``. ההבדל המהותי הוא שכאן טקסט חופשי
כבר תפוס: מחוץ ליועץ, כל הודעת טקסט שלא שייכת לזרימה אחרת היא קוד לשמירה
(``handle_text_message`` ב-``main.py``). לכן היועץ הוא **מצב** — נכנסים אליו
ב-``/advisor`` או בקישור ``t.me/<bot>?start=advisor``, ויוצאים בכפתור היציאה
שמופיע בכל תשובה או ב-``/cancel``. כל עדכון אחר במצב היועץ — פקודה, כפתור של
התפריט הראשי, קובץ, לחיצה על כפתור של תפריט אחר — מוציא מהמצב וממשיך לבוט הרגיל.
אין יציאה אוטומטית אחרי זמן בלי פעילות: גולש שחוזר אחרי שעה ממשיך את השיחה, והמחיר
הוא שגולש ששכח שהוא ביועץ ושולח קוד יקבל תשובה מהמודל ולא שמירה.

**הניתוב.** ``ConversationHandler`` בקבוצה ``ADVISOR_HANDLER_GROUP``: אחרי שער
מגבלת הקצב (``-90``) ולפני כל handler טקסט אחר של הבוט (הנמוך שבהם ב-``-5``).
הודעה שהיועץ לוקח עוצרת שם (``ApplicationHandlerStop``) ולא מגיעה לשמירת קוד.

**מה רץ ברקע.** הבוט מעבד עדכון אחד בכל פעם (אין ``concurrent_updates``), וקריאה
למודל נמשכת שניות. לכן ה-handlers כאן רק מחליטים לאן ההודעה הולכת ומחזירים
מיד, והעבודה — הפתיחה, הקריאה למודל, השליחה והשמירה — רצה במשימה של
``application.create_task``. ההחלטה עצמה חייבת להיות סינכרונית: ב-handler שרץ
ברקע (``block=False``) ``ApplicationHandlerStop`` לא עוצר דבר (python-telegram-bot
22.5, ``telegram/ext/_application.py``: *"ApplicationHandlerStop is not supported
with handlers running non-blocking"*), וההודעה הייתה ממשיכה גם לשמירת קוד.

**סדר.** כל המשימות של גולש אחד עוברות דרך ``asyncio.Lock`` ב-``user_data``, ולכן
שאלה שנשלחת מיד אחרי הכניסה רואה את הפתיחה בזיכרון השיחה, ושתי שאלות מהירות
נענות לפי הסדר.

**מה לא שורד ריסטארט.** מצב השיחה חי בזיכרון, כמו בכל שאר הזרימות של הבוט (אין
לו persistence, בכוונה — ראו ``main.py``). אחרי פריסה הגולש מחוץ ליועץ, וההודעה
הבאה שלו מגיעה לבוט הרגיל. זיכרון השיחה והמכסה היומית במונגו
(``services/advisor_store.py``) כן נשמרים.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
from contextlib import asynccontextmanager
from html import escape as html_escape
from typing import List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from advisor_collections import HISTORY_RETENTION_DAYS
from handlers.advisor_text import html_to_plain, rtl_lines, sanitize_telegram_html, split_message
from services import advisor_service, advisor_store
from utils import TelegramUtils

logger = logging.getLogger(__name__)

#: הקבוצה של היועץ ב-``application.handlers``. ראו "הניתוב" בראש הקובץ.
ADVISOR_HANDLER_GROUP = -10

#: המצב היחיד של השיחה.
ADVISOR_CHAT = "advisor_chat"

EXIT_CALLBACK = "advisor_exit"
FOLLOW_UP_PREFIX = "advisor_q:"
# התבניות של ה-handlers נגזרות מהערכים שהכפתורים נושאים, כדי ששינוי באחד לא ינתק את השני
_EXIT_PATTERN = f"^{re.escape(EXIT_CALLBACK)}$"
_FOLLOW_UP_PATTERN = f"^{re.escape(FOLLOW_UP_PREFIX)}"
_FOLLOW_UPS_KEY = "advisor_follow_ups"
_LOCK_KEY = "advisor_lock"
# שאלות ההמשך של שלוש התשובות האחרונות. callback_data מוגבל ל-64 בתים
# (telegram/constants.py, InlineKeyboardButtonLimit.MAX_CALLBACK_DATA), ולכן
# הכפתור נושא מפתח והשאלה עצמה נשמרת כאן.
_MAX_STORED_FOLLOW_UPS = 9

WELCOME_TEXT = (
    "היי! אני כאן כדי לעזור לך לבדוק בכנות אם CodeKeeper באמת מתאים לאיך שאתה עובד עם סוכני AI, "
    "או שאולי פתרון פשוט יותר יספיק לך.\n"
    "כדי שלא אשפוך עליך סתם מידע, בוא נתחיל מאיך אתה עובד היום:\n"
    "באילו סוכנים אתה משתמש (Claude Code, צ'אט בדפדפן)?\n"
    "והאם קורה לך הרבה שהם שוכחים החלטות ארכיטקטורה ישנות וחוזרים על טעויות?\n\n"
    f"<i>כדי שאזכור את ההקשר, השיחה נשמרת אצלי {HISTORY_RETENTION_DAYS} ימים ואז נמחקת.</i>"
)
EXIT_TEXT = "יצאת ממצב היועץ 👋\nלתפריט הראשי של CodeKeeper: /start\nכדי לחזור ליועץ: /advisor"
LEFT_TEXT = "יצאתי ממצב היועץ. כדי לחזור: /advisor"
ALREADY_OUT_TEXT = "כבר יצאת ממצב היועץ. לשיחה חדשה עם היועץ שלח /advisor"
UNAVAILABLE_TEXT = "🤖 היועץ לא זמין כרגע. אפשר להמשיך להשתמש ב-CodeKeeper כרגיל."
STORE_ERROR_TEXT = "מצטער, היועץ לא זמין כרגע. נסו שוב בעוד כמה דקות 🙏"
LIMIT_TEXT = (
    f"הגעת למכסה היומית של היועץ — {advisor_store.DAILY_QUESTION_LIMIT} שאלות ביום. "
    "אפשר להמשיך מחר 🙏"
)
FOLLOW_UP_GONE_TEXT = "⏳ השאלה כבר לא זמינה. אפשר לשאול אותי ישירות!"
FOLLOW_UP_HEADER = "💡 <b>אולי תרצו גם לשאול:</b>"


# ─── שליחה ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _typing_indicator(bot, chat_id: int, interval: float = 4.0):
    """חיווי "מקליד..." כל interval שניות עד שהבלוק מסתיים (החיווי פג אחרי כ-5 שניות)."""
    stop = asyncio.Event()

    async def _loop():
        while not stop.is_set():
            try:
                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except TelegramError as e:
                logger.debug("Advisor typing indicator failed for chat %s: %s", chat_id, e)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                # לא כשל: עברו interval שניות והבלוק עוד רץ — זה המסלול הרגיל לחיווי הבא
                pass

    task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        stop.set()
        await task


async def _send_text(bot, chat_id: int, text: str, reply_markup=None) -> None:
    """שליחת טקסט של היועץ: סניטציה ← כיוון שורות ← פיצול ← HTML, ו-fallback לטקסט נקי.

    המקלדת מוצמדת רק לחלק האחרון, כך שהכפתורים יופיעו מתחת לסוף התשובה. כיוון
    השורות לפני הפיצול, כדי שתקרת האורך תכלול את סימני ה-RLM שנוספו.
    """
    chunks = split_message(rtl_lines(sanitize_telegram_html(text)))
    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        try:
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=ParseMode.HTML, reply_markup=markup)
        except BadRequest as e:
            # HTML שטלגרם לא הצליח לפרסר (למשל תג שנחתך בפיצול). parse_mode=None
            # במפורש: לבוט מוגדר Defaults(parse_mode=HTML), ובלעדיו הטקסט הנקי היה
            # מפורסר שוב כ-HTML.
            logger.warning("Advisor HTML rejected by Telegram (%s) — sending plain text", e)
            await bot.send_message(chat_id=chat_id, text=html_to_plain(chunk), parse_mode=None, reply_markup=markup)


def _exit_button() -> InlineKeyboardButton:
    return InlineKeyboardButton("🚪 יציאה מהיועץ", callback_data=EXIT_CALLBACK)


def _answer_keyboard(needs_contact: bool = False) -> InlineKeyboardMarkup:
    """כפתור היציאה בכל תשובה, ומעליו כפתור יצירת קשר כשהמודל ביקש אותו."""
    rows = []
    settings = advisor_service.current_settings()
    if needs_contact and settings is not None and settings.contact_url:
        rows.append([InlineKeyboardButton("💬 לדבר עם המפתח", url=settings.contact_url)])
    rows.append([_exit_button()])
    return InlineKeyboardMarkup(rows)


def _store_follow_ups(user_data: dict, questions: List[str]) -> List[Tuple[str, str]]:
    """שמירת השאלות תחת מפתחות אקראיים, ומחיקת הישנות מעבר ל-``_MAX_STORED_FOLLOW_UPS``."""
    stored = user_data.get(_FOLLOW_UPS_KEY)
    if not isinstance(stored, dict):
        stored = {}
    entries = []
    for question in questions:
        token = secrets.token_urlsafe(8)
        stored[token] = question
        entries.append((token, question))
    while len(stored) > _MAX_STORED_FOLLOW_UPS:
        stored.pop(next(iter(stored)))  # מילון שומר על סדר ההכנסה — הראשון הוא הישן
    user_data[_FOLLOW_UPS_KEY] = stored
    return entries


def _follow_up_keyboard(entries: List[Tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(rtl_lines(f"💡 {question}"), callback_data=FOLLOW_UP_PREFIX + token)]
         for token, question in entries]
    )


# ─── הצינור היחיד ל-AI ───────────────────────────────────────────────────────


def _user_lock(context: ContextTypes.DEFAULT_TYPE) -> asyncio.Lock:
    """מנעול לכל גולש — כל מה שקורא או כותב את זיכרון השיחה שלו עובר דרכו, אחד-אחד."""
    return context.user_data.setdefault(_LOCK_KEY, asyncio.Lock())


async def _answer_and_reply(context: ContextTypes.DEFAULT_TYPE, *, user_id: int, chat_id: int, text: str) -> None:
    """זיכרון ← מכסה ← מודל ← שליחה ← שמירה ← שאלות המשך.

    כל נתיב שמגיע ל-AI — הודעת טקסט ולחיצה על שאלת המשך — עובר כאן בלבד.
    הזיכרון נקרא לפני רישום המכסה, כך שתקלה בקריאה לא גובה שאלה.
    """
    async with _user_lock(context):
        refusal = ""  # תשובה בלי מודל: המכסה מלאה, או שהמסד לא זמין
        answer: Optional[advisor_service.Answer] = None
        async with _typing_indicator(context.bot, chat_id):
            try:
                history = await asyncio.to_thread(
                    advisor_store.get_history, user_id, advisor_service.context_exchanges()
                )
                allowed = await asyncio.to_thread(advisor_store.take_daily_question, user_id)
            except advisor_store.AdvisorStoreError:
                logger.exception("Advisor storage unavailable for user %s", user_id)
                refusal = STORE_ERROR_TEXT
            else:
                if allowed:
                    answer = await advisor_service.generate_answer(history, text)
                else:
                    refusal = LIMIT_TEXT

        if answer is None:
            await _send_text(context.bot, chat_id, refusal, reply_markup=_answer_keyboard())
            return

        await _send_text(context.bot, chat_id, answer.text, reply_markup=_answer_keyboard(answer.needs_contact))
        if not answer.ok:
            return  # הודעת תקלה לא נכנסת לזיכרון של המודל

        try:
            await asyncio.to_thread(advisor_store.save_exchange, user_id, text, answer.text)
        except advisor_store.AdvisorStoreError:
            # התשובה כבר אצל הגולש; מה שאבד הוא רק ההקשר לשאלה הבאה
            logger.exception("Advisor history not saved for user %s", user_id)

        if answer.follow_up_questions:
            entries = _store_follow_ups(context.user_data, answer.follow_up_questions)
            await context.bot.send_message(
                chat_id=chat_id,
                text=FOLLOW_UP_HEADER,
                parse_mode=ParseMode.HTML,
                reply_markup=_follow_up_keyboard(entries),
            )


async def _send_welcome(context: ContextTypes.DEFAULT_TYPE, *, user_id: int, chat_id: int, entry_text: str) -> None:
    """הפתיחה נשמרת בזיכרון השיחה כמו כל זוג שאלה-תשובה.

    היא שואלת את הגולש שאלות, ובלעדיה בזיכרון התשובה הראשונה שלו ("כן, כל
    הזמן") הייתה מגיעה למודל בלי השאלה שהיא עונה עליה.
    """
    async with _user_lock(context):
        await _send_text(context.bot, chat_id, WELCOME_TEXT, reply_markup=_answer_keyboard())
        try:
            await asyncio.to_thread(advisor_store.save_exchange, user_id, entry_text, WELCOME_TEXT)
        except advisor_store.AdvisorStoreError:
            logger.exception("Advisor welcome not saved for user %s", user_id)


async def _answer_follow_up(context: ContextTypes.DEFAULT_TYPE, query, *, user_id: int, chat_id: int, question: str) -> None:
    # הכפתורים נעלמים, ובמקומם נשארת השאלה שנבחרה
    await TelegramUtils.safe_edit_message_text(query, rtl_lines(f"💡 {html_escape(question)}"), parse_mode=ParseMode.HTML)
    await _answer_and_reply(context, user_id=user_id, chat_id=chat_id, text=question)


# ─── Handlers ────────────────────────────────────────────────────────────────


async def _enter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/advisor`` או ``/start advisor`` — כניסה, או כניסה מחדש מתוך היועץ."""
    message = update.message
    context.application.create_task(
        _send_welcome(context, user_id=update.effective_user.id, chat_id=message.chat_id, entry_text=message.text),
        update=update,
        name="advisor:welcome",
    )
    raise ApplicationHandlerStop(ADVISOR_CHAT)


async def _on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    context.application.create_task(
        _answer_and_reply(context, user_id=update.effective_user.id, chat_id=message.chat_id, text=message.text),
        update=update,
        name="advisor:answer",
    )
    raise ApplicationHandlerStop(ADVISOR_CHAT)


async def _on_follow_up(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """לחיצה על שאלת המשך — נשלחת לצינור כאילו הגולש הקליד אותה.

    זו גם נקודת כניסה: לחיצה על כפתור של היועץ מחזירה ליועץ, גם אחרי יציאה.
    """
    query = update.callback_query
    await query.answer()
    stored = context.user_data.get(_FOLLOW_UPS_KEY)
    token = query.data[len(FOLLOW_UP_PREFIX):]
    question = stored.pop(token, None) if isinstance(stored, dict) else None
    if question is None:
        # שאלה ישנה, או שאלה מלפני ריסטארט — הזיכרון שלהן לא שרד
        await TelegramUtils.safe_edit_message_text(query, FOLLOW_UP_GONE_TEXT, parse_mode=ParseMode.HTML)
    else:
        context.application.create_task(
            _answer_follow_up(
                context, query, user_id=update.effective_user.id, chat_id=update.effective_chat.id, question=question
            ),
            update=update,
            name="advisor:follow_up",
        )
    raise ApplicationHandlerStop(ADVISOR_CHAT)


async def _exit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור היציאה או ``/cancel`` — יציאה, בלי שההודעה תמשיך לשאר הבוט."""
    query = update.callback_query
    if query is not None:
        await query.answer()
    await context.bot.send_message(chat_id=update.effective_chat.id, text=EXIT_TEXT, parse_mode=None)
    raise ApplicationHandlerStop(ConversationHandler.END)


async def _ignore_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """עריכה של הודעה במצב היועץ אינה שאלה חדשה, וגם אינה קוד לשמירה."""
    raise ApplicationHandlerStop(ADVISOR_CHAT)


async def _leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """כל עדכון אחר במצב היועץ: יוצאים מהמצב, וההודעה ממשיכה לבוט הרגיל."""
    await context.bot.send_message(chat_id=update.effective_chat.id, text=LEFT_TEXT, parse_mode=None)
    return ConversationHandler.END


async def _on_stale_exit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור יציאה בתשובה ישנה, כשהגולש כבר מחוץ ליועץ."""
    await update.callback_query.answer(ALREADY_OUT_TEXT)
    raise ApplicationHandlerStop


async def _advisor_unavailable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(UNAVAILABLE_TEXT, parse_mode=None)


async def _advisor_unavailable_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור יציאה או שאלת המשך בהודעה מתקופה שבה היועץ היה פעיל, כשהוא כבוי עכשיו.

    ה-handler הכללי של הלחיצות (``handle_callback_query``) לא מכיר את הכפתורים האלה
    ומסיים בלי ``query.answer()``, ובלי תשובה הגולש נשאר עם גלגל טעינה.
    """
    await update.callback_query.answer(UNAVAILABLE_TEXT)
    raise ApplicationHandlerStop


# ─── רישום ───────────────────────────────────────────────────────────────────


def _main_menu_labels() -> List[str]:
    """הכפתורים של המקלדת הראשית. לחיצה עליהם במצב היועץ היא פעולה בבוט, לא שאלה."""
    from conversation_handlers import MAIN_KEYBOARD  # מאוחר, כמו ב-handlers/file_view.py

    return [label for row in MAIN_KEYBOARD for label in row]


def build_advisor_conversation() -> ConversationHandler:
    private_message = filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE
    question = private_message & filters.TEXT & ~filters.COMMAND & ~filters.Text(_main_menu_labels())
    return ConversationHandler(
        entry_points=[
            CommandHandler("advisor", _enter, filters=private_message),
            CommandHandler(
                "start", _enter, filters=private_message & filters.Regex(r"^/start(?:@\w+)?\s+advisor\s*$")
            ),
            CallbackQueryHandler(_on_follow_up, pattern=_FOLLOW_UP_PATTERN),
        ],
        states={
            ADVISOR_CHAT: [
                MessageHandler(question, _on_text),
                CommandHandler("cancel", _exit, filters=private_message),
                CallbackQueryHandler(_exit, pattern=_EXIT_PATTERN),
                MessageHandler(filters.UpdateType.EDITED_MESSAGE, _ignore_edit),
            ],
        },
        fallbacks=[
            MessageHandler(filters.UpdateType.MESSAGE, _leave),
            CallbackQueryHandler(_leave),
        ],
        allow_reentry=True,
    )


def register_advisor_handlers(application) -> bool:
    """רישום היועץ בבוט. ``True`` — היועץ פעיל; ``False`` — כבוי, ו-``/advisor`` עונה שאינו זמין.

    הגדרות חסרות או שגויות, או כשל באתחול, מכבים את היועץ בלבד ולא את הבוט.
    בלי היועץ, ``/start advisor`` מגיע ל-``/start`` הרגיל, וכפתורים בהודעות ישנות
    של היועץ עונים שהוא אינו זמין.
    """
    settings, errors = advisor_service.load_settings()
    if errors:
        logger.error("Advisor disabled — invalid configuration: %s", "; ".join(errors))
    elif settings is None:
        logger.info("Advisor disabled — ADVISOR_* environment variables are not set")
    if settings is not None:
        try:
            advisor_service.init_advisor(settings)
        except Exception:
            # גבול עלייה: כשל כאן (מסמך ידע חסר, לקוח שלא נבנה) מכבה את היועץ ולא את הבוט
            logger.exception("Advisor disabled — initialization failed")
            settings = None

    if settings is None:
        application.add_handler(
            CommandHandler(
                "advisor", _advisor_unavailable, filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE
            ),
            group=ADVISOR_HANDLER_GROUP,
        )
        application.add_handler(
            CallbackQueryHandler(_advisor_unavailable_button, pattern=f"{_EXIT_PATTERN}|{_FOLLOW_UP_PATTERN}"),
            group=ADVISOR_HANDLER_GROUP,
        )
        return False

    application.add_handler(build_advisor_conversation(), group=ADVISOR_HANDLER_GROUP)
    # אחרי השיחה ובאותה קבוצה: מגיע לכאן רק כשהשיחה לא לקחה את הלחיצה, כלומר מחוץ ליועץ
    application.add_handler(CallbackQueryHandler(_on_stale_exit, pattern=_EXIT_PATTERN), group=ADVISOR_HANDLER_GROUP)
    return True
