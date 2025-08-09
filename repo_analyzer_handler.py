"""
Repository Analyzer Handler for Telegram Bot
טיפול בניתוח ריפוזיטוריים עם ממשק כפתורים
"""

import logging
import asyncio
import json
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
try:
    from repo_analyzer import RepoAnalyzer, generate_improvement_suggestions
except ImportError:
    # אם המודולים לא מותקנים, נשתמש בפונקציות דמה
    class RepoAnalyzer:
        def __init__(self, token=None):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def fetch_and_analyze_repo(self, url):
            raise ImportError("aiohttp module is required for repository analysis. Please install it with: pip install aiohttp")
    
    def generate_improvement_suggestions(data):
        return []
from activity_reporter import create_reporter
from conversation_handlers import MAIN_KEYBOARD

logger = logging.getLogger(__name__)

# States for conversation
WAITING_REPO_URL = 1
ANALYZING = 2
SHOW_SUMMARY = 3
SHOW_SUGGESTIONS = 4
SHOW_SUGGESTION_DETAIL = 5

reporter = create_reporter(
    mongodb_uri="mongodb+srv://mumin:M43M2TFgLfGvhBwY@muminai.tm6x81b.mongodb.net/?retryWrites=true&w=majority&appName=muminAI",
    service_id="srv-d29d72adbo4c73bcuep0",
    service_name="CodeBot"
)

class RepoAnalyzerHandler:
    """מטפל בניתוח ריפוזיטוריים"""
    
    def __init__(self):
        self.github_token = None  # יילקח מה-config או מהמשתמש
    
    async def start_repo_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """התחלת תהליך ניתוח ריפוזיטורי"""
        user_id = update.effective_user.id
        
        # נקה state קודם
        context.user_data.pop('repo_analysis', None)
        context.user_data['current_state'] = WAITING_REPO_URL
        
        await update.message.reply_text(
            "📝 שלח לי קישור לריפוזיטורי ב-GitHub שתרצה לנתח\n\n"
            "דוגמה:\n"
            "https://github.com/owner/repo\n\n"
            "💡 טיפ: הריפו חייב להיות ציבורי",
            reply_markup=ReplyKeyboardMarkup([["❌ ביטול"]], resize_keyboard=True)
        )
        
        reporter.report_activity(user_id)
        return WAITING_REPO_URL
    
    async def handle_repo_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """טיפול בקבלת URL של ריפו"""
        user_id = update.effective_user.id
        text = update.message.text.strip()
        
        # בדוק ביטול
        if text == "❌ ביטול":
            await update.message.reply_text(
                "❌ הניתוח בוטל",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            context.user_data.pop('current_state', None)
            return ConversationHandler.END
        
        # בדוק תקינות URL
        if not text.startswith(('https://github.com/', 'http://github.com/')):
            await update.message.reply_text(
                "❌ זה לא נראה כמו קישור תקין ל-GitHub\n"
                "נסה שוב עם קישור בפורמט:\n"
                "https://github.com/owner/repo"
            )
            return WAITING_REPO_URL
        
        # התחל ניתוח
        context.user_data['current_state'] = ANALYZING
        context.user_data['repo_url'] = text
        
        analyzing_msg = await update.message.reply_text(
            "🔍 מנתח את הריפו...\n"
            "זה עלול לקחת כמה שניות ⏳",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        try:
            # נתח את הריפו
            analyzer = RepoAnalyzer(self.github_token)
            async with analyzer:
                analysis_data = await analyzer.fetch_and_analyze_repo(text)
            
            # ייצר הצעות שיפור
            suggestions = generate_improvement_suggestions(analysis_data)
            
            # שמור בcontext
            context.user_data['repo_analysis'] = {
                'data': analysis_data,
                'suggestions': suggestions
            }
            
            # מחק הודעת "מנתח..."
            await analyzing_msg.delete()
            
            # הצג סיכום עם כפתורים
            await self._show_analysis_summary(update, context)
            
            reporter.report_activity(user_id)
            context.user_data['current_state'] = SHOW_SUMMARY
            return SHOW_SUMMARY
            
        except ValueError as e:
            await analyzing_msg.delete()
            await update.message.reply_text(
                f"❌ שגיאה: {str(e)}\n\n"
                "וודא שהריפו ציבורי וה-URL נכון",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error analyzing repo: {e}")
            await analyzing_msg.delete()
            await update.message.reply_text(
                "❌ שגיאה בניתוח הריפו\n"
                "נסה שוב מאוחר יותר",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            return ConversationHandler.END
    
    async def _show_analysis_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת סיכום הניתוח עם כפתורים"""
        analysis = context.user_data.get('repo_analysis', {})
        data = analysis.get('data', {})
        
        # בנה טקסט סיכום
        summary_text = f"📊 ניתוח הריפו {data.get('name', 'Unknown')}\n\n"
        
        # סטטוס קבצים חשובים
        summary_text += "✅ יש README\n" if data.get('has_readme') else "❌ חסר README\n"
        summary_text += "✅ יש LICENSE\n" if data.get('has_license') else "❌ חסר LICENSE\n"
        summary_text += "✅ יש .gitignore\n" if data.get('has_gitignore') else "❌ חסר .gitignore\n"
        
        # סטטיסטיקות
        file_counts = data.get('file_counts', {})
        if file_counts:
            total_code_files = sum(file_counts.values())
            main_language = max(file_counts, key=file_counts.get) if file_counts else "Unknown"
            summary_text += f"\n📄 {total_code_files} קבצי קוד"
            summary_text += f" (עיקרי: {main_language})\n"
        
        # תלויות
        dependencies = data.get('dependencies', {})
        if dependencies:
            total_deps = sum(len(deps) for deps in dependencies.values() if isinstance(deps, list))
            summary_text += f"📦 {total_deps} תלויות\n"
        
        # קבצים גדולים
        large_files = data.get('large_files', [])
        if large_files:
            summary_text += f"⚠️ {len(large_files)} קבצים גדולים\n"
        
        summary_text += "\nבחר אפשרות:"
        
        # כפתורים
        keyboard = [
            [InlineKeyboardButton("🎯 הצג הצעות לשיפור", callback_data="repo_show_suggestions")],
            [InlineKeyboardButton("📋 פרטים מלאים", callback_data="repo_show_details")],
            [InlineKeyboardButton("📥 הורד דוח JSON", callback_data="repo_download_json")],
            [InlineKeyboardButton("🔍 נתח ריפו אחר", callback_data="repo_analyze_another")],
            [InlineKeyboardButton("🔙 חזור לתפריט", callback_data="repo_back_to_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.message:
            await update.message.reply_text(summary_text, reply_markup=reply_markup)
        else:
            await update.callback_query.message.reply_text(summary_text, reply_markup=reply_markup)
    
    async def handle_summary_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """טיפול בכפתורים של סיכום הניתוח"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "repo_show_suggestions":
            await self._show_suggestions_list(update, context)
            context.user_data['current_state'] = SHOW_SUGGESTIONS
            return SHOW_SUGGESTIONS
            
        elif query.data == "repo_show_details":
            await self._show_full_details(update, context)
            return SHOW_SUMMARY
            
        elif query.data == "repo_download_json":
            await self._send_json_report(update, context)
            return SHOW_SUMMARY
            
        elif query.data == "repo_analyze_another":
            # התחל ניתוח חדש
            await query.message.reply_text(
                "📝 שלח לי קישור לריפוזיטורי ב-GitHub שתרצה לנתח\n\n"
                "דוגמה:\n"
                "https://github.com/owner/repo",
                reply_markup=ReplyKeyboardMarkup([["❌ ביטול"]], resize_keyboard=True)
            )
            context.user_data['current_state'] = WAITING_REPO_URL
            return WAITING_REPO_URL
            
        elif query.data == "repo_back_to_menu":
            await query.edit_message_text(
                "חזרת לתפריט הראשי",
                reply_markup=None
            )
            context.user_data.pop('repo_analysis', None)
            context.user_data.pop('current_state', None)
            return ConversationHandler.END
    
    async def _show_suggestions_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת רשימת הצעות השיפור"""
        query = update.callback_query
        analysis = context.user_data.get('repo_analysis', {})
        suggestions = analysis.get('suggestions', [])
        data = analysis.get('data', {})
        
        if not suggestions:
            await query.edit_message_text(
                "🎉 מעולה! לא נמצאו הצעות לשיפור משמעותיות.\n"
                "הריפו שלך נראה מסודר!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 חזור לסיכום", callback_data="repo_back_to_summary")]
                ])
            )
            return
        
        text = f"💡 הצעות לשיפור לריפו {data.get('name', 'Unknown')}:\n\n"
        text += "בחר הצעה לפרטים נוספים:\n"
        
        keyboard = []
        for i, suggestion in enumerate(suggestions[:8]):  # מקסימום 8 הצעות
            impact_emoji = "🔴" if suggestion['impact'] == 'high' else "🟡" if suggestion['impact'] == 'medium' else "🟢"
            button_text = f"{impact_emoji} {suggestion['title']}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"repo_suggestion_{i}")])
        
        keyboard.append([InlineKeyboardButton("🔙 חזור לסיכום", callback_data="repo_back_to_summary")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def handle_suggestions_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """טיפול בכפתורי הצעות"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "repo_back_to_summary":
            await self._show_analysis_summary(update, context)
            context.user_data['current_state'] = SHOW_SUMMARY
            return SHOW_SUMMARY
        
        elif query.data.startswith("repo_suggestion_"):
            # הצג פרטי הצעה
            suggestion_index = int(query.data.split("_")[2])
            await self._show_suggestion_detail(update, context, suggestion_index)
            context.user_data['current_state'] = SHOW_SUGGESTION_DETAIL
            return SHOW_SUGGESTION_DETAIL
    
    async def _show_suggestion_detail(self, update: Update, context: ContextTypes.DEFAULT_TYPE, index: int):
        """הצגת פרטי הצעה ספציפית"""
        query = update.callback_query
        analysis = context.user_data.get('repo_analysis', {})
        suggestions = analysis.get('suggestions', [])
        
        if index >= len(suggestions):
            await query.edit_message_text("❌ הצעה לא נמצאה")
            return
        
        suggestion = suggestions[index]
        context.user_data['current_suggestion_index'] = index
        
        # אמוג'י לפי רמת השפעה
        impact_emoji = {
            'high': '🔴 גבוהה',
            'medium': '🟡 בינונית', 
            'low': '🟢 נמוכה'
        }
        
        effort_emoji = {
            'low': '⚡ נמוך',
            'medium': '⏱️ בינוני',
            'high': '🏋️ גבוה'
        }
        
        text = f"📌 {suggestion['title']}\n\n"
        text += f"❓ למה: {suggestion['why']}\n\n"
        text += f"💡 איך: {suggestion['how']}\n\n"
        text += f"📊 השפעה: {impact_emoji.get(suggestion['impact'], suggestion['impact'])}\n"
        text += f"💪 מאמץ: {effort_emoji.get(suggestion['effort'], suggestion['effort'])}"
        
        keyboard = []
        
        # כפתורים למידע נוסף לפי סוג ההצעה
        if 'LICENSE' in suggestion['title']:
            keyboard.append([InlineKeyboardButton("📚 מידע על רישיונות", callback_data="repo_info_licenses")])
        elif 'README' in suggestion['title']:
            keyboard.append([InlineKeyboardButton("📝 מדריך לכתיבת README", callback_data="repo_info_readme")])
        elif 'CI/CD' in suggestion['title'] or 'Actions' in suggestion['title']:
            keyboard.append([InlineKeyboardButton("🔧 מדריך GitHub Actions", callback_data="repo_info_actions")])
        
        keyboard.append([InlineKeyboardButton("🔙 חזור להצעות", callback_data="repo_back_to_suggestions")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def handle_suggestion_detail_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """טיפול בכפתורים של פרטי הצעה"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "repo_back_to_suggestions":
            await self._show_suggestions_list(update, context)
            context.user_data['current_state'] = SHOW_SUGGESTIONS
            return SHOW_SUGGESTIONS
        
        elif query.data == "repo_info_licenses":
            await query.answer(
                "רישיונות פופולריים:\n"
                "• MIT - פשוט ומתירני\n"
                "• Apache 2.0 - כולל הגנת פטנטים\n"
                "• GPL - קוד פתוח חובה\n"
                "בקר ב-choosealicense.com",
                show_alert=True
            )
            return SHOW_SUGGESTION_DETAIL
            
        elif query.data == "repo_info_readme":
            await query.answer(
                "README טוב כולל:\n"
                "• תיאור הפרויקט\n"
                "• דרישות והתקנה\n"
                "• דוגמאות שימוש\n"
                "• תרומה ורישיון",
                show_alert=True
            )
            return SHOW_SUGGESTION_DETAIL
            
        elif query.data == "repo_info_actions":
            await query.answer(
                "GitHub Actions:\n"
                "• בדיקות אוטומטיות\n"
                "• CI/CD pipeline\n"
                "• אוטומציה של משימות\n"
                "התחל מ-github.com/features/actions",
                show_alert=True
            )
            return SHOW_SUGGESTION_DETAIL
    
    async def _show_full_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """הצגת פרטים מלאים של הניתוח"""
        query = update.callback_query
        analysis = context.user_data.get('repo_analysis', {})
        data = analysis.get('data', {})
        
        # בנה טקסט מפורט
        details = f"📊 פרטי ניתוח מלאים - {data.get('name', 'Unknown')}\n"
        details += "=" * 30 + "\n\n"
        
        # מידע בסיסי
        details += f"👤 בעלים: {data.get('owner', 'Unknown')}\n"
        details += f"📝 תיאור: {data.get('description', 'אין תיאור')}\n"
        details += f"⭐ כוכבים: {data.get('stars', 0)}\n"
        details += f"🍴 פורקים: {data.get('forks', 0)}\n"
        details += f"🌿 ענף ראשי: {data.get('default_branch', 'main')}\n\n"
        
        # קבצים לפי שפה
        file_counts = data.get('file_counts', {})
        if file_counts:
            details += "📁 קבצים לפי שפה:\n"
            for lang, count in sorted(file_counts.items(), key=lambda x: x[1], reverse=True):
                details += f"  • {lang}: {count} קבצים\n"
            details += "\n"
        
        # תלויות
        dependencies = data.get('dependencies', {})
        if dependencies:
            details += "📦 קבצי תלויות:\n"
            for dep_file in dependencies:
                details += f"  • {dep_file}\n"
            details += "\n"
        
        # מבנה תיקיות
        dirs = data.get('directory_structure', [])
        if dirs:
            details += "📂 תיקיות עיקריות:\n"
            for dir_name in dirs[:10]:
                details += f"  • /{dir_name}\n"
            if len(dirs) > 10:
                details += f"  • ועוד {len(dirs) - 10} תיקיות...\n"
        
        # גודל כולל
        total_size = data.get('total_size', 0)
        if total_size:
            size_mb = round(total_size / (1024 * 1024), 2)
            details += f"\n💾 גודל כולל: {size_mb} MB"
        
        # שלח בהודעה נפרדת כי זה ארוך
        await query.message.reply_text(
            details,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 חזור לסיכום", callback_data="repo_back_to_summary")]
            ])
        )
    
    async def _send_json_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """שליחת דוח JSON מלא"""
        query = update.callback_query
        analysis = context.user_data.get('repo_analysis', {})
        
        if not analysis:
            await query.answer("❌ אין נתוני ניתוח", show_alert=True)
            return
        
        # צור JSON יפה
        json_data = json.dumps(analysis, ensure_ascii=False, indent=2)
        
        # שלח כקובץ
        from io import BytesIO
        file_buffer = BytesIO(json_data.encode('utf-8'))
        file_buffer.name = f"repo_analysis_{analysis['data'].get('name', 'unknown')}.json"
        
        await query.message.reply_document(
            document=file_buffer,
            caption="📥 דוח ניתוח מלא בפורמט JSON",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 חזור לסיכום", callback_data="repo_back_to_summary")]
            ])
        )
        
        await query.answer("✅ הדוח נשלח")
    
    def get_conversation_handler(self) -> ConversationHandler:
        """מחזיר את ה-ConversationHandler לניתוח ריפוזיטורי"""
        return ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex("^🔍 נתח ריפוזיטורי$"), self.start_repo_analysis)
            ],
            states={
                WAITING_REPO_URL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_repo_url)
                ],
                SHOW_SUMMARY: [
                    CallbackQueryHandler(self.handle_summary_callback, pattern="^repo_")
                ],
                SHOW_SUGGESTIONS: [
                    CallbackQueryHandler(self.handle_suggestions_callback, pattern="^repo_")
                ],
                SHOW_SUGGESTION_DETAIL: [
                    CallbackQueryHandler(self.handle_suggestion_detail_callback, pattern="^repo_")
                ]
            },
            fallbacks=[
                CommandHandler('cancel', lambda u, c: ConversationHandler.END),
                MessageHandler(filters.Regex("^❌ ביטול$"), lambda u, c: ConversationHandler.END)
            ],
            name="repo_analyzer",
            persistent=True
        )


# יצירת instance גלובלי
repo_analyzer_handler = RepoAnalyzerHandler()