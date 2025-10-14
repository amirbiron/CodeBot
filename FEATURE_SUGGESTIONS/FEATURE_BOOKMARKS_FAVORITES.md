# 🔖 פיצ'ר: Bookmarks / Favorites - מועדפים

## 📋 תיאור כללי

מערכת מועדפים שמאפשרת למשתמשים לסמן קבצים חשובים לגישה מהירה. הפיצ'ר מוסיף שכבת ארגון נוספת על התגיות הקיימות ומאפשר מיון לפי חשיבות.

### 🎯 מטרות הפיצ'ר
- גישה מהירה לקבצים נפוצים בשימוש
- ארגון קבצים לפי חשיבות אישית
- חיסכון בזמן חיפוש
- הפרדה בין קבצים פעילים לארכיון

### 👤 תרחישי שימוש
1. **Developer בעבודה יומיומית**: מסמן config.py, api.py, auth.py למעבר מהיר
2. **Student לומד**: מסמן קבצי דוגמה חשובים מהקורס
3. **Project Manager**: מסמן קבצי README ודוקומנטציה מרכזיים

---

## 🗄️ מבנה Database

### שדה חדש במסמכי Code Snippets

```python
# הוספה לסכמת CodeSnippet ב-database/models.py

class CodeSnippet:
    """מודל לקטע קוד"""
    def __init__(self):
        self.user_id: int
        self.file_name: str
        self.code: str
        self.programming_language: str
        self.tags: List[str]
        self.note: str
        self.created_at: datetime
        self.updated_at: datetime
        self.version: int
        self.versions: List[dict]
        # ⭐ שדה חדש - מועדפים
        self.is_favorite: bool = False  # האם הקובץ במועדפים
        self.favorited_at: Optional[datetime] = None  # מתי נוסף למועדפים
```

### אינדקס למהירות

```python
# ב-database/manager.py - __init__

# אינדקס למועדפים לביצועים טובים
self.collection.create_index([
    ("user_id", 1),
    ("is_favorite", 1),
    ("favorited_at", -1)
])
```

---

## 💻 מימוש קוד

### 1. פונקציות Database (database/manager.py)

```python
def toggle_favorite(self, user_id: int, file_name: str) -> bool:
    """
    הוספה/הסרה של קובץ מהמועדפים
    
    Args:
        user_id: מזהה המשתמש
        file_name: שם הקובץ
    
    Returns:
        True אם נוסף למועדפים, False אם הוסר
    """
    try:
        snippet = self.collection.find_one({
            "user_id": user_id,
            "file_name": file_name
        })
        
        if not snippet:
            logger.warning(f"קובץ {file_name} לא נמצא למשתמש {user_id}")
            return False
        
        # החלף מצב
        new_favorite_state = not snippet.get("is_favorite", False)
        
        update_data = {
            "is_favorite": new_favorite_state,
            "updated_at": datetime.now(timezone.utc)
        }
        
        if new_favorite_state:
            # אם מוסיפים למועדפים - שמור תאריך
            update_data["favorited_at"] = datetime.now(timezone.utc)
        else:
            # אם מסירים - נקה תאריך
            update_data["favorited_at"] = None
        
        self.collection.update_one(
            {"user_id": user_id, "file_name": file_name},
            {"$set": update_data}
        )
        
        logger.info(
            f"קובץ {file_name} {'נוסף ל' if new_favorite_state else 'הוסר מ'}מועדפים"
        )
        return new_favorite_state
        
    except Exception as e:
        logger.error(f"שגיאה ב-toggle_favorite: {e}")
        return False


def get_favorites(self, user_id: int, limit: int = 50) -> List[Dict]:
    """
    קבלת כל הקבצים המועדפים של משתמש
    
    Args:
        user_id: מזהה המשתמש
        limit: מספר מקסימלי של תוצאות
    
    Returns:
        רשימת קבצים מועדפים ממוינים לפי תאריך הוספה
    """
    try:
        favorites = list(self.collection.find(
            {
                "user_id": user_id,
                "is_favorite": True
            },
            {
                "file_name": 1,
                "programming_language": 1,
                "tags": 1,
                "note": 1,
                "favorited_at": 1,
                "updated_at": 1,
                "code": 1,
                "_id": 0
            }
        ).sort("favorited_at", -1).limit(limit))
        
        logger.info(f"נמצאו {len(favorites)} מועדפים עבור משתמש {user_id}")
        return favorites
        
    except Exception as e:
        logger.error(f"שגיאה ב-get_favorites: {e}")
        return []


def get_favorites_count(self, user_id: int) -> int:
    """ספירת מספר המועדפים של משתמש"""
    try:
        count = self.collection.count_documents({
            "user_id": user_id,
            "is_favorite": True
        })
        return count
    except Exception as e:
        logger.error(f"שגיאה בספירת מועדפים: {e}")
        return 0


def is_favorite(self, user_id: int, file_name: str) -> bool:
    """בדיקה אם קובץ במועדפים"""
    try:
        snippet = self.collection.find_one(
            {
                "user_id": user_id,
                "file_name": file_name
            },
            {"is_favorite": 1}
        )
        return snippet.get("is_favorite", False) if snippet else False
    except Exception as e:
        logger.error(f"שגיאה בבדיקת מועדף: {e}")
        return False
```

---

### 2. Handlers חדשים (favorites_handler.py)

צור קובץ חדש: `favorites_handler.py`

```python
"""
מטפל במועדפים - Favorites Handler
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes

from database import db
from utils import get_language_emoji
from activity_reporter import create_reporter

logger = logging.getLogger(__name__)

reporter = create_reporter(
    mongodb_uri="mongodb+srv://mumin:M43M2TFgLfGvhBwY@muminai.tm6x81b.mongodb.net/?retryWrites=true&w=majority&appName=muminAI",
    service_id="srv-d3ilh4vfte5s7392s000",
    service_name="CodeBot3"
)


async def favorite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    פקודה: /favorite <file_name>
    הוספה/הסרה של קובץ מהמועדפים
    """
    reporter.report_activity(update.effective_user.id)
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "🔖 <b>הוספה/הסרה ממועדפים</b>\n\n"
            "שימוש: <code>/favorite &lt;file_name&gt;</code>\n\n"
            "דוגמה:\n"
            "<code>/favorite config.py</code>\n\n"
            "או שלח <code>/favorites</code> לצפייה בכל המועדפים",
            parse_mode=ParseMode.HTML
        )
        return
    
    file_name = " ".join(context.args)
    
    # בדוק אם הקובץ קיים
    snippet = db.get_code_snippet(user_id, file_name)
    if not snippet:
        await update.message.reply_text(
            f"❌ הקובץ <code>{file_name}</code> לא נמצא.\n"
            "שלח <code>/list</code> לרשימת הקבצים שלך.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # החלף מצב מועדף
    is_now_favorite = db.toggle_favorite(user_id, file_name)
    
    # הכן הודעת תגובה
    language_emoji = get_language_emoji(snippet.get("programming_language", ""))
    
    if is_now_favorite:
        message = (
            f"⭐ <b>נוסף למועדפים!</b>\n\n"
            f"📁 קובץ: <code>{file_name}</code>\n"
            f"{language_emoji} שפה: {snippet.get('programming_language', 'לא ידוע')}\n\n"
            f"💡 גש במהירות עם <code>/favorites</code>"
        )
    else:
        message = (
            f"💔 <b>הוסר מהמועדפים</b>\n\n"
            f"📁 קובץ: <code>{file_name}</code>\n\n"
            f"ניתן להוסיף שוב מאוחר יותר."
        )
    
    # כפתורים מהירים
    keyboard = [
        [
            InlineKeyboardButton("📋 הצג קובץ", callback_data=f"show_{file_name}"),
            InlineKeyboardButton("⭐ כל המועדפים", callback_data="favorites_list")
        ]
    ]
    
    await update.message.reply_text(
        message,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def favorites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    פקודה: /favorites
    הצגת כל הקבצים המועדפים
    """
    reporter.report_activity(update.effective_user.id)
    user_id = update.effective_user.id
    
    favorites = db.get_favorites(user_id, limit=50)
    
    if not favorites:
        await update.message.reply_text(
            "💭 <b>אין לך עדיין מועדפים</b>\n\n"
            "💡 הוסף קובץ למועדפים עם:\n"
            "<code>/favorite &lt;file_name&gt;</code>\n\n"
            "דוגמה:\n"
            "<code>/favorite config.py</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # בניית ההודעה
    message_lines = [
        "⭐ <b>הקבצים המועדפים שלך</b>",
        f"📊 סה״כ: {len(favorites)} קבצים\n"
    ]
    
    for idx, fav in enumerate(favorites, 1):
        file_name = fav.get("file_name", "לא ידוע")
        language = fav.get("programming_language", "")
        language_emoji = get_language_emoji(language)
        tags = fav.get("tags", [])
        note = fav.get("note", "")
        
        # חישוב זמן מאז הוספה למועדפים
        favorited_at = fav.get("favorited_at")
        time_str = ""
        if favorited_at:
            delta = datetime.now(timezone.utc) - favorited_at
            days = delta.days
            if days == 0:
                time_str = "היום"
            elif days == 1:
                time_str = "אתמול"
            else:
                time_str = f"לפני {days} ימים"
        
        # שורת קובץ
        file_line = f"{idx}. ⭐ <code>{file_name}</code>"
        if language:
            file_line += f"\n   {language_emoji} {language}"
        if time_str:
            file_line += f" • {time_str}"
        if tags:
            tags_str = " ".join([f"#{tag}" for tag in tags[:3]])
            file_line += f"\n   🏷️ {tags_str}"
        if note:
            note_short = note[:50] + "..." if len(note) > 50 else note
            file_line += f"\n   📝 {note_short}"
        
        message_lines.append(file_line)
    
    message = "\n\n".join(message_lines)
    
    # כפתורים לפעולות
    keyboard = []
    
    # שורה ראשונה: פעולות כלליות
    keyboard.append([
        InlineKeyboardButton("📥 ייצא הכל", callback_data="export_favorites"),
        InlineKeyboardButton("📊 סטטיסטיקה", callback_data="favorites_stats")
    ])
    
    # כפתורים לקבצים (עד 5 ראשונים)
    file_buttons = []
    for fav in favorites[:5]:
        file_name = fav.get("file_name", "")
        file_buttons.append(
            InlineKeyboardButton(
                f"📄 {file_name[:20]}",
                callback_data=f"show_{file_name}"
            )
        )
    
    # חלק לשורות של 2
    for i in range(0, len(file_buttons), 2):
        keyboard.append(file_buttons[i:i+2])
    
    await update.message.reply_text(
        message,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def favorites_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מטפל בלחיצות על כפתורים של מועדפים"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data == "favorites_list":
        # הצגת רשימת מועדפים
        favorites = db.get_favorites(user_id, limit=50)
        
        if not favorites:
            await query.edit_message_text(
                "💭 אין לך מועדפים כרגע.\n"
                "השתמש ב-/favorite <file_name> להוספה."
            )
            return
        
        # בניית הודעה
        message_lines = [
            "⭐ <b>המועדפים שלך</b>\n"
        ]
        
        for idx, fav in enumerate(favorites[:10], 1):
            file_name = fav.get("file_name", "")
            language = fav.get("programming_language", "")
            emoji = get_language_emoji(language)
            message_lines.append(f"{idx}. {emoji} <code>{file_name}</code>")
        
        if len(favorites) > 10:
            message_lines.append(f"\n➕ ועוד {len(favorites) - 10} קבצים...")
        
        message = "\n".join(message_lines)
        
        keyboard = [[
            InlineKeyboardButton("🔙 חזור", callback_data="back_to_file")
        ]]
        
        await query.edit_message_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == "export_favorites":
        # ייצוא מועדפים
        await query.edit_message_text("🔄 מייצא מועדפים...")
        
        favorites = db.get_favorites(user_id)
        
        if not favorites:
            await query.edit_message_text("❌ אין מועדפים לייצוא")
            return
        
        # יצירת ZIP עם כל המועדפים
        # (ניתן לשלב עם הפונקציה הקיימת של ZIP)
        await query.edit_message_text(
            f"✅ {len(favorites)} קבצים מועדפים מוכנים לייצוא!\n"
            "השתמש ב-/export zip כדי להוריד."
        )
    
    elif data == "favorites_stats":
        # סטטיסטיקות על מועדפים
        favorites = db.get_favorites(user_id)
        
        if not favorites:
            await query.edit_message_text("💭 אין סטטיסטיקות - אין מועדפים")
            return
        
        # חישוב סטטיסטיקות
        languages = {}
        total_tags = []
        for fav in favorites:
            lang = fav.get("programming_language", "לא ידוע")
            languages[lang] = languages.get(lang, 0) + 1
            total_tags.extend(fav.get("tags", []))
        
        # שפה פופולרית
        popular_lang = max(languages.items(), key=lambda x: x[1]) if languages else ("אין", 0)
        
        # תגיות פופולריות
        from collections import Counter
        tag_counts = Counter(total_tags)
        top_tags = tag_counts.most_common(3)
        
        message = (
            "📊 <b>סטטיסטיקות מועדפים</b>\n\n"
            f"⭐ סך המועדפים: {len(favorites)}\n\n"
            f"🔤 שפה פופולרית:\n"
            f"   {get_language_emoji(popular_lang[0])} {popular_lang[0]} ({popular_lang[1]} קבצים)\n\n"
        )
        
        if top_tags:
            message += "🏷️ תגיות פופולריות:\n"
            for tag, count in top_tags:
                message += f"   #{tag} ({count})\n"
        
        keyboard = [[
            InlineKeyboardButton("🔙 חזור", callback_data="favorites_list")
        ]]
        
        await query.edit_message_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


def setup_favorites_handlers(application):
    """רישום handlers של מועדפים"""
    application.add_handler(CommandHandler("favorite", favorite_command))
    application.add_handler(CommandHandler("favorites", favorites_command))
    application.add_handler(
        CallbackQueryHandler(
            favorites_callback_handler,
            pattern="^(favorites_list|export_favorites|favorites_stats)$"
        )
    )
```

---

### 3. שילוב בהודעת הצגת קובץ

ב-`bot_handlers.py` בפונקציה `show_command`, הוסף כפתור מועדפים:

```python
# בתוך show_command, בבניית הכפתורים:

# בדיקה אם הקובץ במועדפים
is_fav = db.is_favorite(user_id, file_name)
fav_text = "💔 הסר ממועדפים" if is_fav else "⭐ הוסף למועדפים"
fav_callback = f"unfavorite_{file_name}" if is_fav else f"add_favorite_{file_name}"

keyboard = [
    [
        InlineKeyboardButton("🎨 הדגשה צבעונית", callback_data=f"highlight_{file_name}"),
        InlineKeyboardButton("📊 ניתוח", callback_data=f"analyze_{file_name}")
    ],
    [
        InlineKeyboardButton(fav_text, callback_data=fav_callback),  # כפתור מועדפים
        InlineKeyboardButton("✏️ עריכה", callback_data=f"edit_{file_name}")
    ],
    # ... שאר הכפתורים
]
```

והוסף handler ללחיצה:

```python
# ב-handle_callback_query

if query.data.startswith("add_favorite_") or query.data.startswith("unfavorite_"):
    file_name = query.data.split("_", 2)[2]
    
    is_now_fav = db.toggle_favorite(user_id, file_name)
    
    await query.answer(
        "⭐ נוסף למועדפים!" if is_now_fav else "💔 הוסר מהמועדפים",
        show_alert=False
    )
    
    # עדכן את הכפתורים
    # (קוד לעדכון המקלדת...)
```

---

### 4. שילוב ב-main.py

```python
# ב-main.py, בפונקציה main():

from favorites_handler import setup_favorites_handlers

# אחרי הגדרת application
setup_favorites_handlers(application)
```

---

## 🎨 עיצוב UI/UX

### הודעות טקסט

```
⭐ נוסף למועדפים!

📁 קובץ: config.py
🐍 שפה: Python

💡 גש במהירות עם /favorites
```

### רשימת מועדפים

```
⭐ הקבצים המועדפים שלך
📊 סה״כ: 5 קבצים

1. ⭐ config.py
   🐍 Python • היום
   🏷️ #config #settings

2. ⭐ api_client.py
   🐍 Python • אתמול
   🏷️ #api #client
   📝 Client ל-API החיצוני

3. ⭐ auth.js
   📜 JavaScript • לפני 3 ימים
   🏷️ #auth #frontend

[📥 ייצא הכל] [📊 סטטיסטיקה]
[📄 config.py] [📄 api_client.py]
```

---

## ✅ רשימת משימות למימוש

### שלב 1: Database
- [ ] הוסף שדות `is_favorite` ו-`favorited_at` למודל
- [ ] צור אינדקס למהירות
- [ ] הוסף פונקציות: `toggle_favorite`, `get_favorites`, `is_favorite`
- [ ] בדיקות unit tests ל-DB

### שלב 2: Handlers
- [ ] צור `favorites_handler.py`
- [ ] מימוש `/favorite` command
- [ ] מימוש `/favorites` command
- [ ] מימוש callback handlers
- [ ] שילוב כפתור מועדפים ב-show_command

### שלב 3: UI/UX
- [ ] עיצוב הודעות
- [ ] כפתורים אינטראקטיביים
- [ ] סטטיסטיקות מועדפים

### שלב 4: אינטגרציה
- [ ] שילוב ב-main.py
- [ ] טסטים אינטגרציה
- [ ] תיעוד למשתמש

### שלב 5: פיצ'רים מתקדמים (אופציונלי)
- [ ] ייצוא ZIP של מועדפים בלבד
- [ ] סינון חיפוש רק במועדפים
- [ ] מיון מועדפים (לפי תאריך/שם/שפה)
- [ ] הגבלת מספר מועדפים (למשל 50)

---

## 🧪 דוגמאות שימוש

### תרחיש 1: הוספת קובץ למועדפים
```
משתמש: /favorite config.py

בוט:
⭐ נוסף למועדפים!

📁 קובץ: config.py
🐍 שפה: Python

💡 גש במהירות עם /favorites

[📋 הצג קובץ] [⭐ כל המועדפים]
```

### תרחיש 2: צפייה במועדפים
```
משתמש: /favorites

בוט:
⭐ הקבצים המועדפים שלך
📊 סה״כ: 3 קבצים

1. ⭐ config.py
   🐍 Python • היום
   
2. ⭐ api.py
   🐍 Python • אתמול
   
3. ⭐ auth.js
   📜 JavaScript • לפני 2 ימים

[📥 ייצא הכל] [📊 סטטיסטיקה]
```

### תרחיש 3: הסרה מהמועדפים
```
משתמש: /favorite config.py

בוט:
💔 הוסר מהמועדפים

📁 קובץ: config.py

ניתן להוסיף שוב מאוחר יותר.
```

---

## 🔧 שיקולים טכניים

### ביצועים
- אינדקס על `user_id` + `is_favorite` למהירות
- הגבלת תוצאות ל-50 מועדפים בברירת מחדל
- שימוש ב-projection לשדות נחוצים בלבד

### אבטחה
- בדיקת הרשאות - רק בעלים יכול לשנות מועדפים
- Validation על שמות קבצים

### תאימות לאחור
- השדה `is_favorite` הוא False בברירת מחדל
- קבצים ישנים יעבדו בלי שינויים

### הרחבות עתידיות
- קטגוריות מועדפים (עבודה, לימודים, פרויקטים)
- שיתוף רשימת מועדפים
- סינכרון עם GitHub stars

---

## 📚 תיעוד למשתמש

### פקודות
- `/favorite <file>` - הוסף/הסר קובץ מהמועדפים
- `/favorites` - הצג את כל המועדפים שלך

### טיפים
- השתמש במועדפים לקבצים שאתה עובד עליהם כרגע
- הוסף קבצי config וקבצים חשובים למועדפים
- ייצא מועדפים לגיבוי מהיר

---

**סיום מדריך Bookmarks/Favorites** 🔖
