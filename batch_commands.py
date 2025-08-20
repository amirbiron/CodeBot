"""
פקודות Batch לעיבוד מרובה קבצים
Batch Commands for Multiple File Processing
"""

import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from telegram.constants import ParseMode
from database import db
from batch_processor import batch_processor
from lazy_loader import lazy_loader
from autocomplete_manager import autocomplete
from html import escape as html_escape

logger = logging.getLogger(__name__)

async def batch_analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת ניתוח batch של קבצים"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "📊 <b>ניתוח Batch של קבצים</b>\n\n"
            "שימוש:\n"
            "• <code>/batch_analyze all</code> - ניתוח כל הקבצים\n"
            "• <code>/batch_analyze python</code> - ניתוח קבצי Python בלבד\n"
            "• <code>/batch_analyze file1.py file2.js</code> - ניתוח קבצים ספציפיים\n\n"
            "💡 הפעולה תתבצע ברקע ותקבל עדכונים",
            parse_mode=ParseMode.HTML
        )
        return
    
    # זיהוי סוג הבקשה
    args = context.args
    files_to_analyze = []
    
    if args[0] == "all":
        # כל הקבצים
        all_files = db.get_user_files(user_id, limit=1000)
        files_to_analyze = [f['file_name'] for f in all_files]
        
    elif args[0] in ['python', 'javascript', 'java', 'cpp', 'html', 'css']:
        # קבצים לפי שפה
        language = args[0]
        all_files = db.get_user_files(user_id, limit=1000)
        files_to_analyze = [
            f['file_name'] for f in all_files 
            if f.get('programming_language', '').lower() == language.lower()
        ]
        
    else:
        # קבצים ספציפיים
        files_to_analyze = args
    
    if not files_to_analyze:
        await update.message.reply_text(
            "❌ לא נמצאו קבצים לניתוח\n\n"
            "💡 בדוק שהקבצים קיימים או השפה נכונה",
            parse_mode=ParseMode.HTML
        )
        return
    
    # יצירת עבודת batch
    try:
        job_id = await batch_processor.analyze_files_batch(user_id, files_to_analyze)
        
        # הודעת התחלה
        keyboard = [[
            InlineKeyboardButton("📊 בדוק סטטוס", callback_data=f"job_status:{job_id}"),
            InlineKeyboardButton("❌ בטל", callback_data=f"job_cancel:{job_id}")
        ]]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"⚡ <b>ניתוח Batch התחיל!</b>\n\n"
            f"📁 מנתח {len(files_to_analyze)} קבצים\n"
            f"🆔 Job ID: <code>{job_id}</code>\n\n"
            f"⏱️ זמן משוער: {len(files_to_analyze) * 2} שניות",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        try:
            # יצירת רענון אוטומטי להודעת הסטטוס (אם conversation_handlers זמין)
            from conversation_handlers import _auto_update_batch_status
            sent = await update.message.reply_text(
                f"📊 <b>סטטוס עבודת Batch</b>\n\n🆔 <code>{job_id}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 רענן", callback_data=f"job_status:{job_id}")]])
            )
            asyncio.create_task(_auto_update_batch_status(context.application, sent.chat_id, sent.message_id, job_id, user_id))
        except Exception:
            pass
        
    except Exception as e:
        logger.error(f"שגיאה בהתחלת ניתוח batch: {e}")
        await update.message.reply_text("❌ שגיאה בהתחלת הניתוח")

async def batch_validate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת בדיקת תקינות batch"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "✅ <b>בדיקת תקינות Batch</b>\n\n"
            "שימוש:\n"
            "• <code>/batch_validate all</code> - בדיקת כל הקבצים\n"
            "• <code>/batch_validate python</code> - בדיקת קבצי Python\n"
            "• <code>/batch_validate file1.py file2.js</code> - בדיקת קבצים ספציפיים",
            parse_mode=ParseMode.HTML
        )
        return
    
    # זיהוי קבצים (אותה לוגיקה כמו analyze)
    args = context.args
    files_to_validate = []
    
    if args[0] == "all":
        all_files = db.get_user_files(user_id, limit=1000)
        files_to_validate = [f['file_name'] for f in all_files]
    elif args[0] in ['python', 'javascript', 'java', 'cpp']:
        language = args[0]
        all_files = db.get_user_files(user_id, limit=1000)
        files_to_validate = [
            f['file_name'] for f in all_files 
            if f.get('programming_language', '').lower() == language.lower()
        ]
    else:
        files_to_validate = args
    
    if not files_to_validate:
        await update.message.reply_text("❌ לא נמצאו קבצים לבדיקה")
        return
    
    try:
        job_id = await batch_processor.validate_files_batch(user_id, files_to_validate)
        
        keyboard = [[
            InlineKeyboardButton("📊 בדוק סטטוס", callback_data=f"job_status:{job_id}")
        ]]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ <b>בדיקת תקינות Batch התחילה!</b>\n\n"
            f"📁 בודק {len(files_to_validate)} קבצים\n"
            f"🆔 Job ID: <code>{job_id}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        try:
            from conversation_handlers import _auto_update_batch_status
            sent = await update.message.reply_text(
                f"📊 <b>סטטוס עבודת Batch</b>\n\n🆔 <code>{job_id}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 רענן", callback_data=f"job_status:{job_id}")]])
            )
            asyncio.create_task(_auto_update_batch_status(context.application, sent.chat_id, sent.message_id, job_id, user_id))
        except Exception:
            pass
        
    except Exception as e:
        logger.error(f"שגיאה בהתחלת בדיקת batch: {e}")
        await update.message.reply_text("❌ שגיאה בהתחלת הבדיקה")

async def job_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """בדיקת סטטוס עבודת batch"""
    user_id = update.effective_user.id
    
    if not context.args:
        # הצגת כל העבודות הפעילות
        active_jobs = [
            job for job in batch_processor.active_jobs.values() 
            if job.user_id == user_id
        ]
        
        if not active_jobs:
            await update.message.reply_text(
                "📋 אין עבודות batch פעילות\n\n"
                "💡 שימוש: <code>/job_status &lt;job_id&gt;</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # הצגת רשימת עבודות
        keyboard = []
        for job in active_jobs[-5:]:  # 5 עבודות אחרונות
            keyboard.append([
                InlineKeyboardButton(
                    f"{job.operation} - {job.status}",
                    callback_data=f"job_status:{job.job_id}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"📋 <b>עבודות Batch פעילות ({len(active_jobs)}):</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        return
    
    job_id = " ".join(context.args)
    job = batch_processor.get_job_status(job_id)
    
    if not job:
        await update.message.reply_text(
            f"❌ עבודת batch '{html_escape(job_id)}' לא נמצאה",
            parse_mode=ParseMode.HTML
        )
        return
    
    if job.user_id != user_id:
        await update.message.reply_text("❌ אין הרשאה לצפות בעבודה זו")
        return
    
    # הצגת סטטוס מפורט
    summary = batch_processor.format_job_summary(job)
    
    keyboard = []
    if job.status == "completed":
        keyboard.append([
            InlineKeyboardButton("📋 הצג תוצאות", callback_data=f"job_results:{job_id}")
        ])
    elif job.status == "running":
        keyboard.append([
            InlineKeyboardButton("🔄 רענן", callback_data=f"job_status:{job_id}")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    await update.message.reply_text(
        f"📊 <b>סטטוס עבודת Batch</b>\n\n"
        f"🆔 <code>{job_id}</code>\n"
        f"🔧 <b>פעולה:</b> {job.operation}\n\n"
        f"{summary}",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def large_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת הצגת קובץ גדול עם lazy loading"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "📄 <b>הצגת קובץ גדול</b>\n\n"
            "שימוש: <code>/large &lt;שם_קובץ&gt;</code>\n\n"
            "💡 קבצים גדולים יוצגו בחלקים לנוחיות",
            parse_mode=ParseMode.HTML
        )
        return
    
    file_name = " ".join(context.args)
    file_data = db.get_latest_version(user_id, file_name)
    
    if not file_data:
        # הצעת אוטו-השלמה
        suggestions = autocomplete.suggest_filenames(user_id, file_name, limit=3)
        if suggestions:
            suggestion_text = "\n".join([f"• {s['display']}" for s in suggestions])
            await update.message.reply_text(
                f"❌ קובץ '{html_escape(file_name)}' לא נמצא\n\n"
                f"🔍 <b>האם התכוונת ל:</b>\n{suggestion_text}",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                f"❌ קובץ '{html_escape(file_name)}' לא נמצא",
                parse_mode=ParseMode.HTML
            )
        return
    
    code = file_data['code']
    
    # בדיקה אם הקובץ גדול
    if lazy_loader.is_large_file(code):
        # הצגה עם lazy loading
        await lazy_loader.show_large_file_lazy(update, user_id, file_name, chunk_index=0)
    else:
        # קובץ רגיל - הצגה רגילה
        show_command = f"/show {file_name}"
        await update.message.reply_text(
            f"📄 <b>{html_escape(file_name)}</b>\n\n"
            f"ℹ️ קובץ זה אינו גדול ({len(code.splitlines())} שורות)\n"
            f"השתמש ב-<code>{html_escape(show_command)}</code> להצגה רגילה",
            parse_mode=ParseMode.HTML
        )

async def handle_batch_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול בcallbacks של batch operations"""
    query = update.callback_query
    await query.answer(cache_time=0)
    
    user_id = update.effective_user.id
    data = query.data
    
    try:
        if data.startswith("job_status:"):
            job_id = data[11:]  # הסרת "job_status:"
            job = batch_processor.get_job_status(job_id)
            
            if not job or job.user_id != user_id:
                await query.edit_message_text("❌ עבודה לא נמצאה")
                return
            
            summary = batch_processor.format_job_summary(job)
            
            keyboard = []
            if job.status == "completed":
                keyboard.append([
                    InlineKeyboardButton("📋 הצג תוצאות", callback_data=f"job_results:{job_id}")
                ])
            elif job.status == "running":
                keyboard.append([
                    InlineKeyboardButton("🔄 רענן", callback_data=f"job_status:{job_id}")
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            await query.edit_message_text(
                f"📊 <b>סטטוס עבודת Batch</b>\n\n"
                f"🆔 <code>{job_id}</code>\n"
                f"🔧 <b>פעולה:</b> {job.operation}\n\n"
                f"{summary}",
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            
        elif data.startswith("job_results:"):
            job_id = data[12:]  # הסרת "job_results:"
            job = batch_processor.get_job_status(job_id)
            
            if not job or job.user_id != user_id:
                await query.edit_message_text("❌ עבודה לא נמצאה")
                return
            
            if job.status != "completed":
                await query.edit_message_text("⏳ עבודה עדיין לא הושלמה")
                return
            
            # בדיקת סוג הפעולה
            is_analyze = job.operation == "analyze"
            
            # הצגת תוצאות מפורטות
            if is_analyze:
                results_text = "📊 <b>תוצאות ניתוח הקוד</b>\n"
            else:
                results_text = "🔍 <b>תוצאות בדיקת התקינות</b>\n"
            results_text += "━━━━━━━━━━━━━━━━━━━━\n\n"
            
            successful_files = []
            failed_files = []
            
            for file_name, result in job.results.items():
                if result.get('success', False):
                    successful_files.append(file_name)
                else:
                    failed_files.append((file_name, result.get('error', 'שגיאה לא ידועה')))
            
            # סטטיסטיקות כלליות
            total_files = len(job.results)
            results_text += f"📈 <b>סטטיסטיקות:</b>\n"
            results_text += f"   • סה״כ קבצים: <b>{total_files}</b>\n"
            results_text += f"   • ✅ עברו בהצלחה: <b>{len(successful_files)}</b>\n"
            results_text += f"   • ❌ נכשלו: <b>{len(failed_files)}</b>\n\n"
            
            if successful_files:
                results_text += f"✅ <b>קבצים שעברו בהצלחה ({len(successful_files)}):</b>\n"
                for file_name in successful_files[:10]:  # הצג עד 10
                    results_text += f"   • <code>{html_escape(file_name)}</code>\n"
                
                if len(successful_files) > 10:
                    results_text += f"   <i>... ועוד {len(successful_files) - 10} קבצים</i>\n"
                results_text += "\n"
            
            if failed_files:
                results_text += f"❌ <b>קבצים עם בעיות ({len(failed_files)}):</b>\n"
                for file_name, error in failed_files[:5]:  # הצג עד 5 שגיאות
                    results_text += f"   • <code>{html_escape(file_name)}</code>\n"
                    results_text += f"     └ {html_escape(error[:50])}...\n"
                if len(failed_files) > 5:
                    results_text += f"   <i>... ועוד {len(failed_files) - 5} קבצים</i>\n"
                results_text += "\n"

            # תקציר בדיקות מתקדמות (אם קיימות)
            detailed_advanced = []
            for file_name, result in job.results.items():
                adv = result.get('result', {}).get('advanced_checks') if result.get('result') else None
                if adv:
                    file_issues = []
                    for tool, tool_res in adv.items():
                        rc = tool_res.get('returncode')
                        # תרגום שמות הכלים
                        tool_name = {
                            'flake8': '🔍 בדיקת סגנון',
                            'mypy': '📝 בדיקת טיפוסים', 
                            'bandit': '🔒 בדיקת אבטחה',
                            'black': '🎨 עיצוב קוד'
                        }.get(tool, tool)
                        
                        if rc == 0:
                            status_icon = '✅'
                            status_text = 'תקין'
                        elif rc == 127:
                            status_icon = '⚠️'
                            status_text = 'כלי חסר'
                        elif rc == 124:
                            status_icon = '⏱️'
                            status_text = 'תם הזמן'
                        else:
                            status_icon = '❌'
                            status_text = 'בעיה'
                            out = (tool_res.get('output') or '').splitlines()
                            if out:
                                # ניקוי ותרגום השגיאה
                                error_msg = out[0][:100]
                                if 'imported but unused' in error_msg:
                                    error_msg = 'ייבוא לא בשימוש'
                                elif 'would reformat' in error_msg:
                                    error_msg = 'דורש עיצוב מחדש'
                                elif 'SyntaxError' in error_msg:
                                    error_msg = 'שגיאת תחביר'
                                elif 'invalid syntax' in error_msg:
                                    error_msg = 'תחביר לא תקין'
                                else:
                                    error_msg = html_escape(error_msg[:50])
                                status_text = f"{status_text}: {error_msg}"
                        
                        file_issues.append(f"      {status_icon} {tool_name}: <b>{status_text}</b>")
                    
                    if file_issues:
                        detailed_advanced.append(f"\n   📄 <code>{html_escape(file_name)}</code>\n" + "\n".join(file_issues))
            
            if detailed_advanced:
                results_text += "🧪 <b>בדיקות מתקדמות לקבצי Python:</b>\n"
                results_text += "━━━━━━━━━━━━━━━━━━━━\n"
                for details in detailed_advanced[:5]:
                    results_text += details + "\n"
                if len(detailed_advanced) > 5:
                    results_text += f"\n   <i>... ועוד {len(detailed_advanced) - 5} קבצים נבדקו</i>"
            
            # אם זה ניתוח, הוסף מידע נוסף
            if is_analyze:
                analysis_summary = []
                total_lines = 0
                total_chars = 0
                languages = {}
                
                for file_name, result in job.results.items():
                    if result.get('success', False):
                        res_data = result.get('result', {})
                        if res_data:
                            total_lines += res_data.get('lines', 0)
                            total_chars += res_data.get('chars', 0)
                            lang = res_data.get('language', 'unknown')
                            languages[lang] = languages.get(lang, 0) + 1
                            
                            # אם יש ניתוח מפורט
                            analysis = res_data.get('analysis', {})
                            if analysis and isinstance(analysis, dict):
                                complexity = analysis.get('complexity', 'N/A')
                                quality_score = analysis.get('quality_score', 'N/A')
                                if complexity != 'N/A' or quality_score != 'N/A':
                                    analysis_summary.append({
                                        'file': file_name,
                                        'complexity': complexity,
                                        'quality': quality_score
                                    })
                
                # הוסף סיכום ניתוח
                if total_lines > 0:
                    results_text += "\n📈 <b>סיכום הניתוח:</b>\n"
                    results_text += "━━━━━━━━━━━━━━━━━━━━\n"
                    results_text += f"   📏 סה״כ שורות קוד: <b>{total_lines:,}</b>\n"
                    results_text += f"   📝 סה״כ תווים: <b>{total_chars:,}</b>\n"
                    
                    if languages:
                        results_text += f"\n   🔤 <b>שפות תכנות:</b>\n"
                        for lang, count in sorted(languages.items(), key=lambda x: x[1], reverse=True):
                            lang_display = lang.title() if lang != 'unknown' else 'לא זוהה'
                            results_text += f"      • {lang_display}: <b>{count}</b> קבצים\n"
                    
                    if analysis_summary:
                        results_text += f"\n   🎯 <b>ציוני איכות (דוגמאות):</b>\n"
                        for item in analysis_summary[:3]:
                            results_text += f"      • <code>{html_escape(item['file'])}</code>\n"
                            if item['quality'] != 'N/A':
                                results_text += f"        ציון איכות: <b>{item['quality']}</b>\n"
                            if item['complexity'] != 'N/A':
                                results_text += f"        מורכבות: <b>{item['complexity']}</b>\n"
            
            await query.edit_message_text(
                results_text,
                parse_mode=ParseMode.HTML
            )
            
        elif data.startswith("chunk:"):
            # טיפול בnavigation של chunks
            parts = data.split(":")
            if len(parts) == 3:
                file_name = parts[1]
                chunk_index = int(parts[2])
                
                await lazy_loader.show_large_file_lazy(query, user_id, file_name, chunk_index)
                
    except Exception as e:
        logger.error(f"שגיאה בטיפול ב-batch callback: {e}")
        await query.edit_message_text("❌ שגיאה בעיבוד הבקשה")

def setup_batch_handlers(application):
    """הוספת handlers לפקודות batch"""
    application.add_handler(CommandHandler("batch_analyze", batch_analyze_command))
    application.add_handler(CommandHandler("batch_validate", batch_validate_command))
    application.add_handler(CommandHandler("job_status", job_status_command))
    application.add_handler(CommandHandler("large", large_file_command))
    
    # הוספת callback handlers
    application.add_handler(CallbackQueryHandler(
        handle_batch_callbacks,
        pattern="^(job_status:|job_results:|job_cancel:|chunk:)"
    ))
    
    logger.info("Batch handlers הוגדרו בהצלחה")