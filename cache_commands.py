"""
פקודות ניהול Cache לבוט
Cache Management Commands for Bot
"""

import logging
from html import escape as html_escape

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from cache_manager import cache

logger = logging.getLogger(__name__)


async def cache_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """הצגת סטטיסטיקות cache"""
    user_id = update.effective_user.id

    # בדיקה אם המשתמש הוא admin (אופציונלי)
    # if user_id not in ADMIN_USER_IDS:
    #     await update.message.reply_text("❌ פקודה זמינה רק למנהלים")
    #     return

    try:
        stats = cache.get_stats()

        if not stats.get("enabled", False):
            await update.message.reply_text(
                "📊 **סטטיסטיקות Cache**\n\n"
                "❌ Redis Cache מושבת\n"
                "💡 להפעלה: הגדר REDIS_URL במשתני הסביבה",
                parse_mode="Markdown",
            )
            return

        if "error" in stats:
            await update.message.reply_text(
                f"📊 **סטטיסטיקות Cache**\n\n" f"⚠️ שגיאה: {html_escape(stats['error'])}",
                parse_mode="HTML",
            )
            return

        # הצגת סטטיסטיקות מפורטות
        hit_rate = stats.get("hit_rate", 0)
        hit_emoji = "🎯" if hit_rate > 80 else "📈" if hit_rate > 60 else "📉"

        message = (
            f"📊 <b>סטטיסטיקות Cache</b>\n\n"
            f"✅ <b>סטטוס:</b> פעיל\n"
            f"💾 <b>זיכרון בשימוש:</b> {stats.get('used_memory', 'N/A')}\n"
            f"👥 <b>חיבורים:</b> {stats.get('connected_clients', 0)}\n\n"
            f"🎯 <b>ביצועי Cache:</b>\n"
            f"{hit_emoji} <b>Hit Rate:</b> {hit_rate}%\n"
            f"✅ <b>Hits:</b> {stats.get('keyspace_hits', 0):,}\n"
            f"❌ <b>Misses:</b> {stats.get('keyspace_misses', 0):,}\n\n"
            f"💡 <b>טיפ:</b> Hit Rate גבוה = ביצועים טובים יותר!"
        )

        await update.message.reply_text(message, parse_mode="HTML")

    except Exception as e:
        logger.error(f"שגיאה בהצגת סטטיסטיקות cache: {e}")
        await update.message.reply_text("❌ שגיאה בקבלת סטטיסטיקות cache")


async def clear_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ניקוי cache של המשתמש"""
    user_id = update.effective_user.id

    try:
        deleted = cache.invalidate_user_cache(user_id)

        await update.message.reply_text(
            f"🧹 <b>Cache נוקה בהצלחה!</b>\n\n"
            f"🗑️ נמחקו {deleted} ערכים\n"
            f"⚡ הפעולות הבאות יהיו מעט איטיות יותר עד שה-cache יתמלא מחדש",
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"שגיאה בניקוי cache: {e}")
        await update.message.reply_text("❌ שגיאה בניקוי cache")


def setup_cache_handlers(application):
    """הוספת handlers לפקודות cache"""
    application.add_handler(CommandHandler("cache_stats", cache_stats_command))
    application.add_handler(CommandHandler("clear_cache", clear_cache_command))

    logger.info("Cache handlers הוגדרו בהצלחה")
