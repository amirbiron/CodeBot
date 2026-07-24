"""
Telegram handlers לשליחת משימות ל‑Claude Code.

הפקודות:
    /claude <משימה>       – פותח preview, ואחרי אישור פותח Issue שמפעיל את Claude
    /claude_status [N]    – מצב משימה (ברירת מחדל: האחרונה)
    /claude_tasks         – 10 המשימות האחרונות
    /claude_cancel [N]    – סוגר את ה‑Issue ועוצר את העבודה

הכל מוגבל לאדמינים ולצ'אט פרטי בלבד — Claude Code כאן מקבל הרשאת כתיבה לריפו,
אז זה לא משהו שרוצים לפתוח לכולם.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from chatops import claude_commands as cc
from chatops.permissions import get_admin_user_ids, is_admin
from chatops.ratelimit import limit_sensitive
from services import claude_dispatch_service as dispatch
from services import claude_tasks_store as store

logger = logging.getLogger(__name__)

# כמה שניות אחרי השליחה בודקים שבאמת התחילה ריצה
_DEFAULT_WATCHDOG_SEC = 180


def _watchdog_delay() -> int:
    try:
        import os

        return max(30, int(os.getenv("CLAUDE_WATCHDOG_SEC", str(_DEFAULT_WATCHDOG_SEC))))
    except (TypeError, ValueError):
        return _DEFAULT_WATCHDOG_SEC


# ── שערי גישה ──────────────────────────────────────────────────────────────

def _gate(update: Update) -> Optional[str]:
    """בודק הרשאות. מחזיר הודעת סירוב או None אם מותר.

    שים לב: לא מסתמכים רק על ‎is_admin‎. אם ‎ADMIN_USER_IDS‎ ריקה ובמקביל
    ‎CHATOPS_ALLOW_ALL_IF_NO_ADMINS=1‎ — ‎is_admin‎ יחזיר True לכולם.
    לפקודה שנותנת גישת כתיבה לריפו זה מסוכן מדי, אז דורשים רשימה מפורשת.
    """
    user = getattr(update, "effective_user", None)
    user_id = int(getattr(user, "id", 0) or 0)

    if not get_admin_user_ids():
        return "❌ הפקודה דורשת הגדרת ADMIN_USER_IDS. פנה למנהל המערכת."
    if not is_admin(user_id):
        return "❌ פקודה זמינה למנהלים בלבד"

    chat = getattr(update, "effective_chat", None)
    if getattr(chat, "type", "private") != "private":
        return "🔒 הפקודה זמינה בצ'אט פרטי בלבד."
    return None


async def _reply(update: Update, text: str, **kwargs) -> Any:
    """שליחה עם fallback לטקסט נקי אם ה‑HTML נשבר."""
    message = update.message or update.effective_message
    if message is None:
        return None
    try:
        return await message.reply_text(
            text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, **kwargs
        )
    except Exception:
        plain = (
            text.replace("<b>", "")
            .replace("</b>", "")
            .replace("<code>", "")
            .replace("</code>", "")
            .replace("<blockquote>", "")
            .replace("</blockquote>", "")
        )
        try:
            return await message.reply_text(plain, disable_web_page_preview=True)
        except Exception:
            logger.error("claude handlers: reply failed", exc_info=True)
            return None


# ── /claude ────────────────────────────────────────────────────────────────

@limit_sensitive("claude")
async def claude_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מקבל משימה, מנקה אותה, ומציג preview לאישור."""
    denial = _gate(update)
    if denial:
        await _reply(update, denial)
        return

    if not dispatch.is_enabled():
        await _reply(
            update,
            "⚙️ הפיצ'ר כבוי כרגע.\nכדי להפעיל: <code>CLAUDE_DISPATCH_ENABLED=true</code>",
        )
        return

    raw = " ".join(getattr(context, "args", None) or []).strip()
    prompt, error = cc.sanitize_prompt(raw)
    if error:
        await _reply(update, f"⚠️ {error}")
        return

    user_id = int(update.effective_user.id)
    chat_id = int(update.effective_chat.id)
    message_id = int(getattr(update.message, "message_id", 0) or 0)

    # מכסות — cooldown של כמה שניות לא מגן על ארנק ה-API
    max_per_day = cc.get_max_tasks_per_day()
    if max_per_day and store.count_today(user_id) >= max_per_day:
        await _reply(update, f"🛑 הגעת למכסה היומית ({max_per_day} משימות). נסה שוב מחר.")
        return
    if store.count_active(user_id) >= 3:
        await _reply(
            update,
            "🛑 יש כבר 3 משימות פעילות. חכה שיסתיימו או בטל אחת עם <code>/claude_cancel</code>.",
        )
        return

    request_id = store.new_request_id()
    # שומרים ב-DB ולא ב-user_data: restart של Render היה מאבד את הבקשה
    store.create_task(
        request_id=request_id,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        prompt=prompt,
        repo=dispatch.get_repo(),
    )

    message = update.message or update.effective_message
    await message.reply_text(
        cc.build_preview_text(prompt, dispatch.get_repo()),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=cc.build_preview_keyboard(request_id),
    )


async def claude_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מטפל בלחיצה על ✅/❌ ב‑preview.

    ‎admin_required‎ לא מתאים לקאלבקים (הוא עונה על ‎update.message‎, שבקאלבק
    היא ההודעה של הבוט), לכן הבדיקה כאן ידנית.
    """
    query = update.callback_query
    if query is None:
        return

    user_id = int(getattr(getattr(query, "from_user", None), "id", 0) or 0)
    if not get_admin_user_ids() or not is_admin(user_id):
        await query.answer("פקודה זמינה למנהלים בלבד", show_alert=True)
        return

    data = str(getattr(query, "data", "") or "")
    action, _, request_id = data.partition(":")
    task = store.get_by_request_id(request_id)

    if not task:
        await query.answer("הבקשה כבר לא זמינה", show_alert=True)
        return
    # לא מספיק שהלוחץ אדמין — הבקשה חייבת להיות שלו
    if int(task.get("user_id") or 0) != user_id:
        await query.answer("הבקשה שייכת למשתמש אחר", show_alert=True)
        return
    # לחיצה כפולה לא תפתח שני Issues
    if task.get("status") != "pending_confirm":
        await query.answer("הבקשה כבר טופלה")
        return

    if action == "claude_no":
        store.update_task(request_id, {"status": "cancelled"})
        await query.answer("בוטל")
        await _safe_edit(query, "🚫 המשימה בוטלה.")
        return

    await query.answer("שולח…")
    await _safe_edit(query, "📤 פותח Issue ב‑GitHub…")

    result = await dispatch.dispatch_claude_task(
        prompt=task.get("prompt") or "",
        chat_id=int(task.get("chat_id") or 0),
        message_id=task.get("message_id"),
        user_id=user_id,
        request_id=request_id,
    )

    if result.get("success"):
        store.update_task(
            request_id,
            {
                "status": "dispatched",
                "issue_number": result.get("issue_number"),
                "issue_url": result.get("issue_url"),
            },
        )
        _schedule_watchdog(context, request_id)
    else:
        store.update_task(request_id, {"status": "failed", "error": result.get("error")})

    await _safe_edit(query, cc.format_dispatch_result(result))


async def _safe_edit(query, text: str) -> None:
    """עריכת הודעה שמתעלמת רק מ‑'message is not modified'."""
    import telegram.error

    try:
        await query.edit_message_text(
            text=text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    except telegram.error.BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        logger.warning("claude handlers: edit failed: %s", exc)
    except Exception:
        logger.error("claude handlers: edit failed", exc_info=True)


# ── watchdog ───────────────────────────────────────────────────────────────

def _schedule_watchdog(context: ContextTypes.DEFAULT_TYPE, request_id: str) -> None:
    """מתזמן בדיקה שה‑workflow באמת התחיל.

    זה מכסה את התקלה הכי מבלבלת: ה‑Issue נפתח, אבל ה‑workflow לא רץ (בדרך כלל
    כי הטוקן הוא GITHUB_TOKEN של Actions, או שה‑workflow עוד לא ב‑main).
    בלי זה המשתמש פשוט מחכה לנצח.
    """
    try:
        job_queue = getattr(getattr(context, "application", None), "job_queue", None)
        if job_queue is None:
            return
        job_queue.run_once(
            _claude_watchdog,
            when=_watchdog_delay(),
            name=f"claude_wd_{request_id}",
            data={"request_id": request_id},
        )
    except Exception:
        logger.warning("claude handlers: watchdog scheduling failed", exc_info=True)


async def _claude_watchdog(context: ContextTypes.DEFAULT_TYPE) -> None:
    """מזהיר אם אחרי כמה דקות עדיין לא זוהתה ריצה."""
    try:
        job_data: Dict[str, Any] = getattr(getattr(context, "job", None), "data", None) or {}
        request_id = str(job_data.get("request_id") or "")
        task = store.get_by_request_id(request_id)
        if not task or task.get("status") != "dispatched":
            return

        run = await dispatch.find_workflow_run_for_issue(int(task.get("issue_number") or 0))
        if run:
            store.update_task(
                request_id, {"status": "running", "run_id": run.get("run_id"), "run_url": run.get("run_url")}
            )
            return

        store.update_task(request_id, {"status": "timeout"})
        await context.bot.send_message(
            chat_id=int(task.get("chat_id") or 0),
            text=(
                f"⚠️ לא זוהתה ריצה ל‑Issue #{task.get('issue_number')}.\n\n"
                "שתי סיבות נפוצות:\n"
                "• ה‑workflow <code>claude.yml</code> עדיין לא מוזג ל‑main\n"
                "• הטוקן שפתח את ה‑Issue הוא GITHUB_TOKEN של Actions ולא PAT"
            ),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        logger.error("claude handlers: watchdog failed", exc_info=True)


# ── /claude_status, /claude_tasks, /claude_cancel ──────────────────────────

def _select_task(user_id: int, args: str) -> Optional[Dict[str, Any]]:
    """בוחר משימה לפי הארגומנט: מספר Issue, או האחרונה כברירת מחדל."""
    issue_number, want_last = cc.parse_task_selector(args)
    if want_last or issue_number is None:
        return store.get_last_for_user(user_id)
    return store.get_by_issue_number(issue_number, user_id=user_id)


async def claude_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    denial = _gate(update)
    if denial:
        await _reply(update, denial)
        return

    user_id = int(update.effective_user.id)
    task = _select_task(user_id, " ".join(getattr(context, "args", None) or []))
    if not task:
        await _reply(update, cc.format_task_details(None))
        return

    # רענון מ-GitHub כדי לא להציג מצב מיושן
    task = await _refresh_task(task)
    await _reply(update, cc.format_task_details(task))


async def _refresh_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """מעדכן PR/סטטוס מ‑GitHub. כישלון ברענון לא מונע הצגה."""
    issue_number = task.get("issue_number")
    if not issue_number:
        return task
    try:
        pr_url = await dispatch.find_pr_for_issue(int(issue_number))
        if pr_url and pr_url != task.get("pr_url"):
            task = dict(task)
            task["pr_url"] = pr_url
            store.update_task(str(task.get("request_id")), {"pr_url": pr_url})
    except Exception:
        logger.debug("claude handlers: refresh failed", exc_info=True)
    return task


async def claude_tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    denial = _gate(update)
    if denial:
        await _reply(update, denial)
        return
    tasks = store.list_recent(int(update.effective_user.id), limit=10)
    await _reply(update, cc.format_tasks_list(tasks))


@limit_sensitive("claude_cancel")
async def claude_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    denial = _gate(update)
    if denial:
        await _reply(update, denial)
        return

    user_id = int(update.effective_user.id)
    task = _select_task(user_id, " ".join(getattr(context, "args", None) or []))
    if not task or not task.get("issue_number"):
        await _reply(update, "לא נמצאה משימה לביטול.")
        return

    result = await dispatch.cancel_claude_task(int(task["issue_number"]))
    if result.get("success"):
        store.update_task(str(task.get("request_id")), {"status": "cancelled"})
        await _reply(update, f"🚫 Issue #{task['issue_number']} נסגר.")
    else:
        await _reply(update, f"❌ הביטול נכשל: {result.get('error')}")


# ── רישום ──────────────────────────────────────────────────────────────────

def setup_claude_handlers(application) -> None:
    """מוסיף את כל ה‑handlers של ‎/claude‎ לאפליקציה."""
    application.add_handler(CommandHandler("claude", claude_command))
    application.add_handler(CommandHandler("claude_status", claude_status_command))
    application.add_handler(CommandHandler("claude_tasks", claude_tasks_command))
    application.add_handler(CommandHandler("claude_cancel", claude_cancel_command))
    application.add_handler(
        CallbackQueryHandler(claude_callback, pattern=r"^claude_(ok|no):")
    )
    logger.info("Claude task handlers הוגדרו בהצלחה")
