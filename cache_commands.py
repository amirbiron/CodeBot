"""
פקודות ניהול Cache לבוט
Cache Management Commands for Bot
"""

import logging
import json
import hashlib
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from cache_manager import cache
from html import escape as html_escape

logger = logging.getLogger(__name__)


def _get_db():
    """Attempt to fetch DB via webapp.app.get_db to reuse connection config."""
    try:
        from webapp.app import get_db as _get  # type: ignore
        return _get()
    except Exception:
        return None

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
                "📊 <b>סטטיסטיקות Cache</b>\n\n"
                "❌ Redis Cache מושבת\n"
                "💡 להפעלה: הגדר <code>REDIS_URL</code> במשתני הסביבה",
                parse_mode='HTML'
            )
            return
        
        if "error" in stats:
            await update.message.reply_text(
                f"📊 <b>סטטיסטיקות Cache</b>\n\n"
                f"⚠️ <b>שגיאה:</b> {html_escape(stats['error'])}",
                parse_mode='HTML'
            )
            return
        
        # הצגת סטטיסטיקות מפורטות
        hit_rate = stats.get('hit_rate', 0)
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
        
        await update.message.reply_text(message, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"שגיאה בהצגת סטטיסטיקות cache: {e}")
        await update.message.reply_text(
            "❌ שגיאה בקבלת סטטיסטיקות cache"
        )

async def clear_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ניקוי cache של המשתמש"""
    user_id = update.effective_user.id
    
    try:
        deleted = cache.invalidate_user_cache(user_id)
        
        await update.message.reply_text(
            f"🧹 <b>Cache נוקה בהצלחה!</b>\n\n"
            f"🗑️ נמחקו {deleted} ערכים\n"
            f"⚡ הפעולות הבאות יהיו מעט איטיות יותר עד שה-cache יתמלא מחדש",
            parse_mode='HTML'
        )
        
    except Exception as e:
        logger.error(f"שגיאה בניקוי cache: {e}")
        await update.message.reply_text("❌ שגיאה בניקוי cache")

def setup_cache_handlers(application):
    """הוספת handlers לפקודות cache"""
    application.add_handler(CommandHandler("cache_stats", cache_stats_command))
    application.add_handler(CommandHandler("clear_cache", clear_cache_command))
    application.add_handler(CommandHandler("cache_warm", cache_warm_command))
    
    logger.info("Cache handlers הוגדרו בהצלחה")


async def cache_warm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """חימום קאש מהיר לסטטיסטיקות משתמש (/cache_warm)."""
    user_id = update.effective_user.id
    try:
        db = _get_db()
        if db is None:
            await update.message.reply_text("❌ DB לא זמין לחימום קאש כרגע")
            return

        # חשב סטטיסטיקות כמו ב-/api/stats (תמציתי)
        active_query = {
            'user_id': user_id,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        }
        stats = {
            'total_files': db.code_snippets.count_documents(active_query),
            'languages': list(db.code_snippets.distinct('programming_language', active_query)),
            'recent_activity': []
        }
        recent = db.code_snippets.find(active_query, {'file_name': 1, 'created_at': 1}).sort('created_at', -1).limit(10)
        for item in recent:
            stats['recent_activity'].append({
                'file_name': item.get('file_name', ''),
                'created_at': (item.get('created_at') or datetime.now(timezone.utc)).isoformat()
            })

        # בניית מפתח הקאש לפי אותו פורמט
        _params = {}
        _raw = json.dumps(_params, sort_keys=True, ensure_ascii=False)
        _hash = hashlib.sha256(_raw.encode('utf-8')).hexdigest()[:16]
        stats_cache_key = f"api:stats:user:{user_id}:{_hash}"

        # שמירה עם TTL דינמי
        try:
            cache.set_dynamic(
                stats_cache_key,
                stats,
                "user_stats",
                {
                    "user_id": user_id,
                    "user_tier": "regular",
                    "endpoint": "api_stats",
                    "access_frequency": "high",
                },
            )
        except Exception:
            cache.set(stats_cache_key, stats, 120)

        await update.message.reply_text("✅ קאש חומם בהצלחה לסטטיסטיקות משתמש")
    except Exception as e:
        logger.error(f"שגיאה בחימום קאש: {e}")
        await update.message.reply_text("❌ שגיאה בחימום קאש")