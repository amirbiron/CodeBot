"""
Handler לניתוח ריפוזיטורי GitHub עם ממשק כפתורים
"""

import logging
import re
import json
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from repo_analyzer import fetch_and_analyze_repo, generate_improvement_suggestions
from conversation_handlers import MAIN_KEYBOARD
from activity_reporter import create_reporter

logger = logging.getLogger(__name__)

# מצבים לשיחה
REPO_STATES = {
    'WAITING_REPO_URL': 1,
    'ANALYZING': 2,
    'SHOW_SUMMARY': 3,
    'SHOW_SUGGESTIONS': 4,
    'SHOW_SUGGESTION_DETAIL': 5,
    'SHOW_FULL_DETAILS': 6
}

# יצירת reporter
reporter = create_reporter(
    mongodb_uri="mongodb+srv://mumin:M43M2TFgLfGvhBwY@muminai.tm6x81b.mongodb.net/?retryWrites=true&w=majority&appName=muminAI",
    service_id="srv-d29d72adbo4c73bcuep0",
    service_name="CodeBot"
)


class RepoAnalyzerHandler:
    """מחלקה לניהול ניתוח ריפוזיטורי בטלגרם"""
    
    @staticmethod
    async def start_repo_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """התחלת תהליך ניתוח ריפוזיטורי"""
        user_id = update.effective_user.id
        
        # בדוק אם יש טוקן GitHub
        from github_menu_handler import GitHubMenuHandler
        github_handler = GitHubMenuHandler()
        has_token = False
        if hasattr(github_handler, 'user_sessions') and user_id in github_handler.user_sessions:
            has_token = bool(github_handler.user_sessions[user_id].get('github_token'))
        
        token_status = "✅ יש לך טוקן GitHub - תוכל לנתח גם ריפוז פרטיים!" if has_token else "ℹ️ אין טוקן - רק ריפוז ציבוריים (מוגבל ל-60 בקשות לשעה)"
        
        # אם זה מהתפריט הראשי
        if update.message:
            await update.message.reply_text(
                "📝 *ניתוח ריפוזיטורי GitHub*\n\n"
                f"{token_status}\n\n"
                "שלח לי קישור לריפוזיטורי ב-GitHub שתרצה לנתח.\n\n"
                "דוגמה:\n"
                "`https://github.com/owner/repo`\n\n"
                "💡 *טיפ:* להוספת טוקן GitHub, השתמש בתפריט /github\n\n"
                "לביטול, שלח /cancel",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardMarkup([["❌ ביטול"]], resize_keyboard=True)
            )
        # אם זה מכפתור callback
        elif update.callback_query:
            query = update.callback_query
            await query.answer()
            await query.edit_message_text(
                "📝 *ניתוח ריפוזיטורי GitHub*\n\n"
                "שלח לי קישור לריפוזיטורי ציבורי ב-GitHub שתרצה לנתח.\n\n"
                "דוגמה:\n"
                "`https://github.com/owner/repo`\n\n"
                "💡 *טיפ:* הריפו חייב להיות ציבורי כדי שאוכל לנתח אותו.",
                parse_mode='Markdown'
            )
            
            # שלח הודעה נוספת עם כפתור ביטול
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="ממתין לקישור...",
                reply_markup=ReplyKeyboardMarkup([["❌ ביטול"]], resize_keyboard=True)
            )
        
        # שמור state
        context.user_data['repo_state'] = 'WAITING_REPO_URL'
        reporter.report_activity(user_id)
        
        return REPO_STATES['WAITING_REPO_URL']
    
    @staticmethod
    async def handle_repo_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """טיפול בקישור הריפו שהתקבל"""
        user_id = update.effective_user.id
        text = update.message.text.strip()
        
        # בדיקת ביטול
        if text == "❌ ביטול":
            await update.message.reply_text(
                "❌ הניתוח בוטל.",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            context.user_data.pop('repo_state', None)
            context.user_data.pop('repo_analysis', None)
            return ConversationHandler.END
        
        # בדיקת תקינות URL
        if not re.match(r'https?://github\.com/[\w-]+/[\w.-]+/?', text):
            await update.message.reply_text(
                "❌ *URL לא תקין*\n\n"
                "אנא שלח קישור תקין לריפוזיטורי ב-GitHub.\n"
                "דוגמה: `https://github.com/owner/repo`",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardMarkup([["❌ ביטול"]], resize_keyboard=True)
            )
            return REPO_STATES['WAITING_REPO_URL']
        
        # התחל ניתוח
        analyzing_msg = await update.message.reply_text(
            "🔍 *מנתח את הריפוזיטורי...*\n\n"
            "⏳ זה עשוי לקחת מספר שניות...",
            parse_mode='Markdown'
        )
        
        try:
            # בדוק אם יש טוקן GitHub שמור מהתפריט של GitHub
            from github_menu_handler import GitHubMenuHandler
            github_handler = GitHubMenuHandler()
            
            # נסה לקבל את הטוקן מה-session
            github_token = None
            if hasattr(github_handler, 'user_sessions') and user_id in github_handler.user_sessions:
                github_token = github_handler.user_sessions[user_id].get('github_token')
            
            # אם יש טוקן, עדכן את ה-analyzer
            if github_token:
                from repo_analyzer import repo_analyzer
                repo_analyzer.set_token(github_token)
                logger.info(f"Using GitHub token for user {user_id}")
            
            # נתח את הריפו
            analysis_result = await fetch_and_analyze_repo(text)
            
            if 'error' in analysis_result:
                error_msg = f"❌ *שגיאה בניתוח*\n\n{analysis_result['error']}"
                
                # אם השגיאה קשורה לריפו פרטי ואין טוקן
                if 'פרטי' in analysis_result['error'] and not github_token:
                    error_msg += "\n\n💡 *טיפ:* נראה שזה ריפו פרטי. הוסף טוקן GitHub דרך /github כדי לנתח ריפוז פרטיים."
                
                await analyzing_msg.edit_text(error_msg, parse_mode='Markdown')
                await update.message.reply_text(
                    "נסה שוב עם ריפו אחר או חזור לתפריט הראשי:",
                    reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
                )
                return ConversationHandler.END
            
            # שמור את תוצאות הניתוח
            context.user_data['repo_analysis'] = analysis_result
            context.user_data['used_token'] = bool(github_token)  # שמור אם השתמשנו בטוקן
            
            # צור הצעות שיפור
            suggestions = generate_improvement_suggestions(analysis_result)
            context.user_data['repo_suggestions'] = suggestions
            
            # הצג סיכום
            await RepoAnalyzerHandler._show_analysis_summary(analyzing_msg, context, analysis_result, suggestions)
            
            # החזר לתפריט רגיל
            await update.message.reply_text(
                "בחר פעולה:",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            
            context.user_data['repo_state'] = 'SHOW_SUMMARY'
            reporter.report_activity(user_id)
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error analyzing repo: {e}")
            await analyzing_msg.edit_text(
                "❌ *שגיאה לא צפויה*\n\nמשהו השתבש בניתוח. נסה שוב מאוחר יותר.",
                parse_mode='Markdown'
            )
            await update.message.reply_text(
                "חזור לתפריט הראשי:",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            return ConversationHandler.END
    
    @staticmethod
    async def _show_analysis_summary(message, context: ContextTypes.DEFAULT_TYPE, 
                                    analysis_result: Dict, suggestions: List[Dict]):
        """הצגת סיכום הניתוח"""
        analysis = analysis_result.get('analysis', {})
        repo_name = analysis_result.get('repo_name', 'Unknown')
        owner = analysis_result.get('owner', 'Unknown')
        
        # בנה טקסט סיכום
        summary_text = f"📊 *ניתוח הריפו {repo_name}*\n"
        summary_text += f"👤 בעלים: {owner}\n"
        
        # הוסף אינדיקציה על שימוש בטוקן
        if context.user_data.get('used_token'):
            summary_text += "🔑 נותח עם טוקן GitHub\n"
        summary_text += "\n"
        
        # מידע בסיסי
        if analysis.get('description'):
            summary_text += f"📝 {analysis['description']}\n\n"
        
        summary_text += f"⭐ כוכבים: {analysis.get('stars', 0)}\n"
        summary_text += f"🍴 פיצולים: {analysis.get('forks', 0)}\n"
        summary_text += f"🐛 בעיות פתוחות: {analysis.get('open_issues', 0)}\n\n"
        
        # סטטוס קבצים חשובים
        summary_text += "*📁 קבצים חשובים:*\n"
        summary_text += f"{'✅' if analysis.get('has_readme') else '❌'} README\n"
        summary_text += f"{'✅' if analysis.get('has_license') else '❌'} LICENSE\n"
        summary_text += f"{'✅' if analysis.get('has_gitignore') else '❌'} .gitignore\n"
        summary_text += f"{'✅' if analysis.get('has_tests') else '❌'} Tests\n"
        summary_text += f"{'✅' if analysis.get('has_ci_cd') else '❌'} CI/CD\n\n"
        
        # סטטיסטיקות
        summary_text += "*📊 סטטיסטיקות:*\n"
        summary_text += f"📄 {analysis.get('total_files', 0)} קבצים\n"
        summary_text += f"📁 {analysis.get('total_directories', 0)} תיקיות\n"
        
        # שפות
        languages = analysis.get('languages', {})
        if languages:
            summary_text += f"\n*💻 שפות תכנות:*\n"
            for lang, count in sorted(languages.items(), key=lambda x: x[1], reverse=True)[:5]:
                summary_text += f"• {lang}: {count} קבצים\n"
        
        # תלויות
        if analysis.get('dependency_files'):
            summary_text += f"\n📦 *קבצי תלויות:* {len(analysis['dependency_files'])}\n"
        
        # בעיות
        large_files = analysis.get('large_files', [])
        if large_files:
            summary_text += f"\n⚠️ *{len(large_files)} קבצים גדולים*\n"
        
        # הצעות
        if suggestions:
            high_priority = len([s for s in suggestions if s['impact'] == 'high'])
            summary_text += f"\n💡 *נמצאו {len(suggestions)} הצעות לשיפור*\n"
            if high_priority:
                summary_text += f"   ({high_priority} בעדיפות גבוהה)\n"
        
        # כפתורים
        keyboard = []
        
        if suggestions:
            keyboard.append([InlineKeyboardButton("🎯 הצג הצעות לשיפור", callback_data="repo_show_suggestions")])
        
        keyboard.extend([
            [InlineKeyboardButton("📋 פרטים מלאים", callback_data="repo_show_details")],
            [InlineKeyboardButton("📥 הורד דוח JSON", callback_data="repo_download_json")],
            [InlineKeyboardButton("🔍 נתח ריפו אחר", callback_data="repo_analyze_another")],
            [InlineKeyboardButton("🔙 סגור", callback_data="repo_close")]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            summary_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    @staticmethod
    async def handle_repo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """טיפול בכפתורי callback של ניתוח ריפו"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = update.effective_user.id
        
        # הצג הצעות
        if data == "repo_show_suggestions":
            await RepoAnalyzerHandler._show_suggestions_list(query, context)
            
        # הצג פרטים מלאים
        elif data == "repo_show_details":
            await RepoAnalyzerHandler._show_full_details(query, context)
            
        # הורד JSON
        elif data == "repo_download_json":
            await RepoAnalyzerHandler._send_json_report(query, context)
            
        # נתח ריפו אחר
        elif data == "repo_analyze_another":
            await query.edit_message_text(
                "📝 *ניתוח ריפוזיטורי חדש*\n\n"
                "שלח לי קישור לריפוזיטורי ציבורי ב-GitHub שתרצה לנתח.\n\n"
                "דוגמה:\n"
                "`https://github.com/owner/repo`",
                parse_mode='Markdown'
            )
            context.user_data['repo_state'] = 'WAITING_REPO_URL'
            return REPO_STATES['WAITING_REPO_URL']
            
        # סגור
        elif data == "repo_close":
            await query.edit_message_text(
                "✅ הניתוח הושלם.\n\nבחר פעולה מהתפריט הראשי.",
                parse_mode='Markdown'
            )
            context.user_data.pop('repo_analysis', None)
            context.user_data.pop('repo_suggestions', None)
            
        # חזור לסיכום
        elif data == "repo_back_to_summary":
            analysis_result = context.user_data.get('repo_analysis')
            suggestions = context.user_data.get('repo_suggestions', [])
            if analysis_result:
                await RepoAnalyzerHandler._show_analysis_summary(query.message, context, analysis_result, suggestions)
                
        # הצג הצעה ספציפית
        elif data.startswith("repo_suggestion_"):
            suggestion_id = data.replace("repo_suggestion_", "")
            await RepoAnalyzerHandler._show_suggestion_detail(query, context, suggestion_id)
            
        # מידע על רישיונות
        elif data == "repo_license_info":
            await RepoAnalyzerHandler._show_license_info(query)
            
        # חזור להצעות
        elif data == "repo_back_to_suggestions":
            await RepoAnalyzerHandler._show_suggestions_list(query, context)
        
        reporter.report_activity(user_id)
    
    @staticmethod
    async def _show_suggestions_list(query, context: ContextTypes.DEFAULT_TYPE):
        """הצגת רשימת ההצעות"""
        suggestions = context.user_data.get('repo_suggestions', [])
        
        if not suggestions:
            await query.edit_message_text(
                "🎉 *מעולה!*\n\nהריפו שלך נראה טוב מאוד, אין לי הצעות לשיפור כרגע.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 חזור לסיכום", callback_data="repo_back_to_summary")]
                ])
            )
            return
        
        text = "💡 *הצעות לשיפור*\n\n"
        text += "בחר הצעה לפרטים נוספים:\n\n"
        
        keyboard = []
        
        # מיין לפי קטגוריות
        categories = {
            'legal': '🔒 משפטי',
            'documentation': '📝 תיעוד',
            'configuration': '🔧 הגדרות',
            'dependencies': '📦 תלויות',
            'automation': '🔄 אוטומציה',
            'quality': '🧪 איכות',
            'refactoring': '🔨 ריפקטורינג',
            'community': '👥 קהילה',
            'maintenance': '🔧 תחזוקה',
            'metadata': '📋 מטא-דאטה'
        }
        
        # הצג עד 10 הצעות הכי חשובות
        for i, suggestion in enumerate(suggestions[:10]):
            impact_emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(suggestion['impact'], '⚪')
            button_text = f"{impact_emoji} {suggestion['title']}"
            keyboard.append([InlineKeyboardButton(
                button_text,
                callback_data=f"repo_suggestion_{suggestion['id']}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 חזור לסיכום", callback_data="repo_back_to_summary")])
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    @staticmethod
    async def _show_suggestion_detail(query, context: ContextTypes.DEFAULT_TYPE, suggestion_id: str):
        """הצגת פרטי הצעה ספציפית"""
        suggestions = context.user_data.get('repo_suggestions', [])
        suggestion = next((s for s in suggestions if s['id'] == suggestion_id), None)
        
        if not suggestion:
            await query.edit_message_text(
                "❌ הצעה לא נמצאה",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 חזור להצעות", callback_data="repo_back_to_suggestions")]
                ])
            )
            return
        
        # בנה טקסט מפורט
        impact_text = {'high': 'גבוהה', 'medium': 'בינונית', 'low': 'נמוכה'}.get(suggestion['impact'], 'לא ידוע')
        effort_text = {'high': 'גבוה', 'medium': 'בינוני', 'low': 'נמוך'}.get(suggestion['effort'], 'לא ידוע')
        
        text = f"*{suggestion['title']}*\n\n"
        text += f"❓ *למה:*\n{suggestion['why']}\n\n"
        text += f"💡 *איך:*\n{suggestion['how']}\n\n"
        text += f"📊 *השפעה:* {impact_text}\n"
        text += f"⚡ *מאמץ:* {effort_text}\n"
        
        keyboard = []
        
        # כפתורים ספציפיים להצעה
        if suggestion_id == 'add_license':
            keyboard.append([InlineKeyboardButton("📚 מידע על רישיונות", callback_data="repo_license_info")])
        
        keyboard.append([InlineKeyboardButton("🔙 חזור להצעות", callback_data="repo_back_to_suggestions")])
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    @staticmethod
    async def _show_full_details(query, context: ContextTypes.DEFAULT_TYPE):
        """הצגת פרטים מלאים של הניתוח"""
        analysis_result = context.user_data.get('repo_analysis', {})
        analysis = analysis_result.get('analysis', {})
        
        text = "*📋 פרטים מלאים של הניתוח*\n\n"
        
        # מבנה הריפו
        text += "*🗂️ מבנה:*\n"
        text += f"• קבצים: {analysis.get('total_files', 0)}\n"
        text += f"• תיקיות: {analysis.get('total_directories', 0)}\n\n"
        
        # שפות מפורט
        languages = analysis.get('languages', {})
        if languages:
            text += "*💻 שפות תכנות (כל השפות):*\n"
            for lang, count in sorted(languages.items(), key=lambda x: x[1], reverse=True):
                text += f"• {lang}: {count} קבצים\n"
            text += "\n"
        
        # קבצי תלויות
        dep_files = analysis.get('dependency_files', [])
        if dep_files:
            text += "*📦 קבצי תלויות:*\n"
            for file in dep_files:
                text += f"• {file}\n"
            text += "\n"
        
        # קבצים גדולים
        large_files = analysis.get('large_files', [])
        if large_files:
            text += "*⚠️ קבצים גדולים:*\n"
            for file in large_files[:5]:
                text += f"• {file['name']}: {file['size_kb']}KB\n"
            text += "\n"
        
        # תלויות Python
        if 'python' in analysis.get('dependencies', {}):
            deps = analysis['dependencies']['python']
            text += f"*🐍 תלויות Python ({len(deps)}):*\n"
            for dep in deps[:10]:
                text += f"• {dep['name']} {dep.get('version', '')}\n"
            if len(deps) > 10:
                text += f"... ועוד {len(deps) - 10}\n"
            text += "\n"
        
        # תלויות NPM
        if 'npm' in analysis.get('dependencies', {}):
            deps = analysis['dependencies']['npm']
            text += f"*📦 תלויות NPM ({len(deps)}):*\n"
            for dep in deps[:10]:
                dev_mark = " (dev)" if dep.get('dev') else ""
                text += f"• {dep['name']}{dev_mark}\n"
            if len(deps) > 10:
                text += f"... ועוד {len(deps) - 10}\n"
        
        # חתוך אם ארוך מדי (טלגרם מגביל ל-4096 תווים)
        if len(text) > 4000:
            text = text[:3997] + "..."
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 חזור לסיכום", callback_data="repo_back_to_summary")]
            ])
        )
    
    @staticmethod
    async def _send_json_report(query, context: ContextTypes.DEFAULT_TYPE):
        """שליחת דוח JSON מלא"""
        analysis_result = context.user_data.get('repo_analysis', {})
        suggestions = context.user_data.get('repo_suggestions', [])
        
        if not analysis_result:
            await query.answer("אין נתונים לייצוא", show_alert=True)
            return
        
        # הכן את הדוח
        report = {
            'repo_url': analysis_result.get('repo_url'),
            'owner': analysis_result.get('owner'),
            'repo_name': analysis_result.get('repo_name'),
            'analysis': analysis_result.get('analysis'),
            'suggestions': suggestions,
            'generated_at': str(context.user_data.get('analysis_timestamp', ''))
        }
        
        # המר ל-JSON יפה
        json_str = json.dumps(report, ensure_ascii=False, indent=2)
        
        # שלח כקובץ
        from io import BytesIO
        file_bytes = BytesIO(json_str.encode('utf-8'))
        file_bytes.name = f"repo_analysis_{analysis_result.get('repo_name', 'unknown')}.json"
        
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=file_bytes,
            filename=file_bytes.name,
            caption=f"📊 דוח ניתוח מלא עבור {analysis_result.get('repo_name', 'הריפו')}"
        )
        
        await query.answer("✅ הדוח נשלח")
    
    @staticmethod
    async def _show_license_info(query):
        """הצגת מידע על רישיונות"""
        text = "*📚 מידע על רישיונות נפוצים*\n\n"
        
        text += "*MIT License:*\n"
        text += "• הכי פופולרי ופשוט\n"
        text += "• מאפשר שימוש מסחרי\n"
        text += "• דורש שמירת הקרדיט\n\n"
        
        text += "*Apache 2.0:*\n"
        text += "• מתאים לפרויקטים גדולים\n"
        text += "• כולל הגנת פטנטים\n"
        text += "• דורש תיעוד שינויים\n\n"
        
        text += "*GPL v3:*\n"
        text += "• קוד פתוח חזק\n"
        text += "• מחייב פרסום נגזרות כקוד פתוח\n"
        text += "• לא מתאים לשימוש מסחרי סגור\n\n"
        
        text += "*BSD:*\n"
        text += "• פשוט ומתירני\n"
        text += "• מאפשר שימוש מסחרי\n"
        text += "• מינימום דרישות\n\n"
        
        text += "💡 *טיפ:* השתמש ב-choosealicense.com לבחירה"
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 חזור", callback_data="repo_back_to_suggestions")]
            ])
        )
    
    @staticmethod
    async def cancel_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """ביטול תהליך הניתוח"""
        await update.message.reply_text(
            "❌ הניתוח בוטל.",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        # נקה נתונים
        context.user_data.pop('repo_state', None)
        context.user_data.pop('repo_analysis', None)
        context.user_data.pop('repo_suggestions', None)
        
        return ConversationHandler.END


# יצירת ConversationHandler לניתוח ריפו
def get_repo_analyzer_conversation_handler():
    """יצירת conversation handler לניתוח ריפו"""
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^🔍 נתח ריפוזיטורי$"), RepoAnalyzerHandler.start_repo_analysis),
            CallbackQueryHandler(RepoAnalyzerHandler.start_repo_analysis, pattern="^repo_analyze_another$")
        ],
        states={
            REPO_STATES['WAITING_REPO_URL']: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, RepoAnalyzerHandler.handle_repo_url)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", RepoAnalyzerHandler.cancel_analysis),
            MessageHandler(filters.Regex("^❌ ביטול$"), RepoAnalyzerHandler.cancel_analysis)
        ]
    )