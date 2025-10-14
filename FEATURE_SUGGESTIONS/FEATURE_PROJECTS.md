# 🏷️ פיצ'ר: Projects / קבוצות - ארגון קבצים בפרויקטים

## 📋 תיאור כללי

מערכת ניהול פרויקטים שמאפשרת לארגן קבצים קשורים תחת פרויקט אחד. הפיצ'ר מוסיף שכבת ארגון מעל התגיות ומאפשר ניהול קבוצות של קבצים בצורה מובנית.

### 🎯 מטרות הפיצ'ר
- ארגון קבצים קשורים תחת פרויקט אחד
- ניהול פרויקטים שלמים (צפייה, ייצוא, גיבוי)
- הפרדה ברורה בין פרויקטים שונים
- תמיכה בעבודה על מספר פרויקטים במקביל

### 👤 תרחישי שימוש
1. **Web Developer**: ארגון קבצי Frontend ו-Backend לפי פרויקט
2. **Student**: הפרדה בין תרגילים של קורסים שונים
3. **Freelancer**: ניהול קבצים של לקוחות שונים
4. **Data Scientist**: ארגון סקריפטים לפי פרויקטי מחקר

---

## 🗄️ מבנה Database

### קולקציה חדשה: projects

```python
# מבנה מסמך בקולקציה projects

{
    "_id": ObjectId("..."),
    "project_id": "proj_abc123xyz",           # מזהה ייחודי
    "user_id": 123456789,                      # בעלים
    "project_name": "WebApp",                  # שם הפרויקט
    "display_name": "My Web Application",      # שם תצוגה
    "description": "Full-stack web app with React and Flask",
    "icon": "🌐",                              # אייקון
    "color": "#3498db",                        # צבע לזיהוי חזותי
    "tags": ["web", "fullstack", "react"],    # תגיות
    "files": [                                 # רשימת קבצים
        "api.py",
        "database.py",
        "frontend/App.js",
        "frontend/components/Header.js"
    ],
    "file_count": 4,                           # מספר קבצים
    "total_size": 15420,                       # גודל כולל (bytes)
    "languages": {                             # שפות בפרויקט
        "python": 2,
        "javascript": 2
    },
    "is_active": true,                         # פרויקט פעיל
    "is_archived": false,                      # ארכיון
    "created_at": ISODate("2024-10-09T10:00:00Z"),
    "updated_at": ISODate("2024-10-09T15:30:00Z"),
    "last_accessed_at": ISODate("2024-10-09T15:30:00Z")
}
```

### שדה חדש בקולקציית code_snippets

```python
# הוספה לכל מסמך קוד קיים:
{
    # ... שדות קיימים
    "project_id": "proj_abc123xyz",  # השתייכות לפרויקט (אופציונלי)
    "project_name": "WebApp"         # שם הפרויקט (לשאילתות מהירות)
}
```

### אינדקסים

```python
# ב-database/manager.py - __init__

# קולקציית פרויקטים
self.projects_collection = self.db.projects

# אינדקס ראשי
self.projects_collection.create_index([
    ("user_id", 1),
    ("project_name", 1)
], unique=True)  # שם פרויקט ייחודי למשתמש

# אינדקס לפרויקטים פעילים
self.projects_collection.create_index([
    ("user_id", 1),
    ("is_active", 1),
    ("updated_at", -1)
])

# אינדקס בקולקציית הקוד לפרויקטים
self.collection.create_index([
    ("user_id", 1),
    ("project_id", 1)
])
```

---

## 💻 מימוש קוד

### 1. מודל Project (database/models.py)

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Optional

@dataclass
class Project:
    """מודל פרויקט"""
    project_id: str
    user_id: int
    project_name: str
    display_name: str
    description: str = ""
    icon: str = "📁"
    color: str = "#3498db"
    tags: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    file_count: int = 0
    total_size: int = 0
    languages: Dict[str, int] = field(default_factory=dict)
    is_active: bool = True
    is_archived: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        """המרה למילון"""
        return {
            "project_id": self.project_id,
            "user_id": self.user_id,
            "project_name": self.project_name,
            "display_name": self.display_name,
            "description": self.description,
            "icon": self.icon,
            "color": self.color,
            "tags": self.tags,
            "files": self.files,
            "file_count": self.file_count,
            "total_size": self.total_size,
            "languages": self.languages,
            "is_active": self.is_active,
            "is_archived": self.is_archived,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_accessed_at": self.last_accessed_at
        }
```

---

### 2. פונקציות Database (database/manager.py)

```python
import secrets
from typing import List, Dict, Optional

def create_project(
    self,
    user_id: int,
    project_name: str,
    display_name: str = None,
    description: str = "",
    icon: str = "📁",
    tags: List[str] = None
) -> Optional[str]:
    """
    יצירת פרויקט חדש
    
    Returns:
        project_id אם הצליח, None אם נכשל
    """
    try:
        # בדיקה אם שם הפרויקט תפוס
        existing = self.projects_collection.find_one({
            "user_id": user_id,
            "project_name": project_name
        })
        
        if existing:
            logger.warning(f"פרויקט {project_name} כבר קיים")
            return None
        
        project_id = f"proj_{secrets.token_urlsafe(16)}"
        
        project_data = {
            "project_id": project_id,
            "user_id": user_id,
            "project_name": project_name,
            "display_name": display_name or project_name,
            "description": description,
            "icon": icon,
            "color": "#3498db",
            "tags": tags or [],
            "files": [],
            "file_count": 0,
            "total_size": 0,
            "languages": {},
            "is_active": True,
            "is_archived": False,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "last_accessed_at": None
        }
        
        self.projects_collection.insert_one(project_data)
        logger.info(f"פרויקט {project_name} נוצר בהצלחה")
        return project_id
        
    except Exception as e:
        logger.error(f"שגיאה ביצירת פרויקט: {e}")
        return None


def get_user_projects(
    self,
    user_id: int,
    include_archived: bool = False,
    limit: int = 50
) -> List[Dict]:
    """קבלת כל הפרויקטים של משתמש"""
    try:
        query = {"user_id": user_id}
        if not include_archived:
            query["is_archived"] = False
        
        projects = list(
            self.projects_collection.find(query)
            .sort("updated_at", -1)
            .limit(limit)
        )
        
        for p in projects:
            p["_id"] = str(p["_id"])
        
        return projects
        
    except Exception as e:
        logger.error(f"שגיאה בקבלת פרויקטים: {e}")
        return []


def get_project(self, user_id: int, project_name: str) -> Optional[Dict]:
    """קבלת פרויקט ספציפי"""
    try:
        project = self.projects_collection.find_one({
            "user_id": user_id,
            "project_name": project_name
        })
        
        if project:
            project["_id"] = str(project["_id"])
        
        return project
        
    except Exception as e:
        logger.error(f"שגיאה בקבלת פרויקט: {e}")
        return None


def add_file_to_project(
    self,
    user_id: int,
    project_name: str,
    file_name: str
) -> bool:
    """הוספת קובץ לפרויקט"""
    try:
        project = self.get_project(user_id, project_name)
        if not project:
            logger.warning(f"פרויקט {project_name} לא נמצא")
            return False
        
        # בדיקה אם הקובץ קיים
        snippet = self.get_code_snippet(user_id, file_name)
        if not snippet:
            logger.warning(f"קובץ {file_name} לא נמצא")
            return False
        
        # בדיקה אם הקובץ כבר בפרויקט
        if file_name in project.get("files", []):
            logger.info(f"קובץ {file_name} כבר בפרויקט")
            return True
        
        # עדכון הפרויקט
        project_id = project["project_id"]
        language = snippet.get("programming_language", "unknown")
        code_size = len(snippet.get("code", ""))
        
        # עדכון מונה שפות
        languages = project.get("languages", {})
        languages[language] = languages.get(language, 0) + 1
        
        self.projects_collection.update_one(
            {"user_id": user_id, "project_name": project_name},
            {
                "$push": {"files": file_name},
                "$inc": {
                    "file_count": 1,
                    "total_size": code_size
                },
                "$set": {
                    "languages": languages,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
        
        # עדכון הקובץ עצמו
        self.collection.update_one(
            {"user_id": user_id, "file_name": file_name},
            {
                "$set": {
                    "project_id": project_id,
                    "project_name": project_name,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
        
        logger.info(f"קובץ {file_name} נוסף לפרויקט {project_name}")
        return True
        
    except Exception as e:
        logger.error(f"שגיאה בהוספת קובץ לפרויקט: {e}")
        return False


def remove_file_from_project(
    self,
    user_id: int,
    project_name: str,
    file_name: str
) -> bool:
    """הסרת קובץ מפרויקט"""
    try:
        project = self.get_project(user_id, project_name)
        if not project or file_name not in project.get("files", []):
            return False
        
        snippet = self.get_code_snippet(user_id, file_name)
        if not snippet:
            return False
        
        language = snippet.get("programming_language", "unknown")
        code_size = len(snippet.get("code", ""))
        
        # עדכון מונה שפות
        languages = project.get("languages", {})
        if language in languages:
            languages[language] -= 1
            if languages[language] <= 0:
                del languages[language]
        
        self.projects_collection.update_one(
            {"user_id": user_id, "project_name": project_name},
            {
                "$pull": {"files": file_name},
                "$inc": {
                    "file_count": -1,
                    "total_size": -code_size
                },
                "$set": {
                    "languages": languages,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
        
        # הסרת הפרויקט מהקובץ
        self.collection.update_one(
            {"user_id": user_id, "file_name": file_name},
            {
                "$unset": {
                    "project_id": "",
                    "project_name": ""
                },
                "$set": {
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
        
        logger.info(f"קובץ {file_name} הוסר מפרויקט {project_name}")
        return True
        
    except Exception as e:
        logger.error(f"שגיאה בהסרת קובץ מפרויקט: {e}")
        return False


def get_project_files(self, user_id: int, project_name: str) -> List[Dict]:
    """קבלת כל הקבצים של פרויקט"""
    try:
        project = self.get_project(user_id, project_name)
        if not project:
            return []
        
        file_names = project.get("files", [])
        if not file_names:
            return []
        
        files = list(self.collection.find(
            {
                "user_id": user_id,
                "file_name": {"$in": file_names}
            },
            {
                "file_name": 1,
                "programming_language": 1,
                "tags": 1,
                "note": 1,
                "updated_at": 1,
                "code": 1,
                "_id": 0
            }
        ).sort("file_name", 1))
        
        return files
        
    except Exception as e:
        logger.error(f"שגיאה בקבלת קבצי פרויקט: {e}")
        return []


def delete_project(
    self,
    user_id: int,
    project_name: str,
    delete_files: bool = False
) -> bool:
    """
    מחיקת פרויקט
    
    Args:
        delete_files: אם True, גם מוחק את כל הקבצים בפרויקט
    """
    try:
        project = self.get_project(user_id, project_name)
        if not project:
            return False
        
        if delete_files:
            # מחק את כל הקבצים
            files = project.get("files", [])
            for file_name in files:
                self.delete_code_snippet(user_id, file_name)
        else:
            # רק הסר את הקישור לפרויקט מהקבצים
            self.collection.update_many(
                {
                    "user_id": user_id,
                    "project_name": project_name
                },
                {
                    "$unset": {
                        "project_id": "",
                        "project_name": ""
                    }
                }
            )
        
        # מחק את הפרויקט
        self.projects_collection.delete_one({
            "user_id": user_id,
            "project_name": project_name
        })
        
        logger.info(f"פרויקט {project_name} נמחק")
        return True
        
    except Exception as e:
        logger.error(f"שגיאה במחיקת פרויקט: {e}")
        return False


def archive_project(self, user_id: int, project_name: str) -> bool:
    """העברת פרויקט לארכיון"""
    try:
        result = self.projects_collection.update_one(
            {"user_id": user_id, "project_name": project_name},
            {
                "$set": {
                    "is_archived": True,
                    "is_active": False,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
        
        return result.modified_count > 0
        
    except Exception as e:
        logger.error(f"שגיאה בארכוב פרויקט: {e}")
        return False


def update_project_access(self, user_id: int, project_name: str):
    """עדכון זמן גישה אחרון לפרויקט"""
    try:
        self.projects_collection.update_one(
            {"user_id": user_id, "project_name": project_name},
            {"$set": {"last_accessed_at": datetime.now(timezone.utc)}}
        )
    except Exception as e:
        logger.error(f"שגיאה בעדכון גישה: {e}")
```

---

### 3. Handler לפרויקטים (projects_handler.py)

צור קובץ חדש: `projects_handler.py`

```python
"""
מטפל בפרויקטים - Projects Handler
"""

import logging
from typing import List, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

from database import db
from utils import get_language_emoji
from activity_reporter import create_reporter

logger = logging.getLogger(__name__)

# שלבי שיחה
PROJECT_NAME, PROJECT_DESC, ADD_FILES = range(3)

reporter = create_reporter(
    mongodb_uri="mongodb+srv://mumin:M43M2TFgLfGvhBwY@muminai.tm6x81b.mongodb.net/?retryWrites=true&w=majority&appName=muminAI",
    service_id="srv-d3ilh4vfte5s7392s000",
    service_name="CodeBot3"
)

# אייקונים לפרויקטים
PROJECT_ICONS = ["📁", "🌐", "📱", "🖥️", "🎨", "🔧", "⚙️", "🚀", "💼", "📊"]


async def project_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    פקודה: /project_create
    התחלת תהליך יצירת פרויקט
    """
    reporter.report_activity(update.effective_user.id)
    
    await update.message.reply_text(
        "📁 <b>יצירת פרויקט חדש</b>\n\n"
        "פרויקט מאפשר לארגן קבצים קשורים תחת שם אחד.\n\n"
        "📝 שלח שם לפרויקט (באנגלית, ללא רווחים):\n\n"
        "דוגמה: <code>WebApp</code> או <code>my_project</code>",
        parse_mode=ParseMode.HTML
    )
    
    return PROJECT_NAME


async def project_create_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """קבלת שם הפרויקט"""
    user_id = update.effective_user.id
    project_name = update.message.text.strip()
    
    # ולידציה
    if not project_name.replace("_", "").replace("-", "").isalnum():
        await update.message.reply_text(
            "❌ שם הפרויקט חייב להכיל רק אותיות, מספרים, קו תחתון (_) ומקף (-)\n\n"
            "נסה שוב:"
        )
        return PROJECT_NAME
    
    # בדיקה אם קיים
    existing = db.get_project(user_id, project_name)
    if existing:
        await update.message.reply_text(
            f"⚠️ פרויקט <code>{project_name}</code> כבר קיים.\n\n"
            "בחר שם אחר:",
            parse_mode=ParseMode.HTML
        )
        return PROJECT_NAME
    
    context.user_data["project_name"] = project_name
    
    await update.message.reply_text(
        f"✅ שם הפרויקט: <code>{project_name}</code>\n\n"
        f"📝 עכשיו שלח תיאור קצר (או <code>skip</code> לדילוג):\n\n"
        f"דוגמה: <code>אפליקציית Web עם React ו-Flask</code>",
        parse_mode=ParseMode.HTML
    )
    
    return PROJECT_DESC


async def project_create_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """קבלת תיאור ויצירת הפרויקט"""
    user_id = update.effective_user.id
    description = update.message.text.strip()
    
    if description.lower() == "skip":
        description = ""
    
    project_name = context.user_data["project_name"]
    
    # יצירת הפרויקט
    project_id = db.create_project(
        user_id=user_id,
        project_name=project_name,
        display_name=project_name.replace("_", " ").title(),
        description=description,
        icon="📁"
    )
    
    if not project_id:
        await update.message.reply_text(
            "❌ שגיאה ביצירת הפרויקט. נסה שוב מאוחר יותר."
        )
        context.user_data.clear()
        return ConversationHandler.END
    
    message = (
        f"✅ <b>פרויקט נוצר בהצלחה!</b>\n\n"
        f"📁 שם: <code>{project_name}</code>\n"
    )
    
    if description:
        message += f"📝 תיאור: {description}\n"
    
    message += (
        f"\n💡 <b>הוספת קבצים לפרויקט:</b>\n"
        f"<code>/project_add {project_name} file1.py</code>\n\n"
        f"או:\n"
        f"<code>/show file.py</code> ← ולחץ על כפתור \"הוסף לפרויקט\""
    )
    
    keyboard = [
        [
            InlineKeyboardButton("➕ הוסף קבצים", callback_data=f"proj_add_{project_name}"),
            InlineKeyboardButton("📋 רשימת פרויקטים", callback_data="projects_list")
        ]
    ]
    
    await update.message.reply_text(
        message,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    context.user_data.clear()
    return ConversationHandler.END


async def projects_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    פקודה: /projects
    הצגת כל הפרויקטים
    """
    reporter.report_activity(update.effective_user.id)
    user_id = update.effective_user.id
    
    projects = db.get_user_projects(user_id, include_archived=False)
    
    if not projects:
        await update.message.reply_text(
            "💭 <b>אין לך פרויקטים עדיין</b>\n\n"
            "💡 צור פרויקט חדש:\n"
            "<code>/project_create</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # בניית הודעה
    message_lines = [
        "📁 <b>הפרויקטים שלך</b>",
        f"📊 סה״כ: {len(projects)} פרויקטים\n"
    ]
    
    for idx, proj in enumerate(projects, 1):
        name = proj["project_name"]
        display = proj.get("display_name", name)
        icon = proj.get("icon", "📁")
        file_count = proj.get("file_count", 0)
        languages = proj.get("languages", {})
        desc = proj.get("description", "")
        
        # שפות בפרויקט
        lang_str = ""
        if languages:
            top_langs = sorted(languages.items(), key=lambda x: x[1], reverse=True)[:2]
            lang_str = " • ".join([f"{get_language_emoji(l)} {l}" for l, _ in top_langs])
        
        line = f"{idx}. {icon} <b>{display}</b>"
        if desc:
            desc_short = desc[:50] + "..." if len(desc) > 50 else desc
            line += f"\n   📝 {desc_short}"
        line += f"\n   📂 {file_count} קבצים"
        if lang_str:
            line += f" • {lang_str}"
        
        message_lines.append(line)
    
    message = "\n\n".join(message_lines)
    
    # כפתורים
    keyboard = []
    
    # פעולות כלליות
    keyboard.append([
        InlineKeyboardButton("➕ פרויקט חדש", callback_data="project_create_btn"),
        InlineKeyboardButton("📊 סטטיסטיקה", callback_data="projects_stats")
    ])
    
    # כפתורים לפרויקטים (עד 6)
    proj_buttons = []
    for proj in projects[:6]:
        name = proj["project_name"]
        icon = proj.get("icon", "📁")
        proj_buttons.append(
            InlineKeyboardButton(
                f"{icon} {name[:15]}",
                callback_data=f"show_proj_{name}"
            )
        )
    
    for i in range(0, len(proj_buttons), 2):
        keyboard.append(proj_buttons[i:i+2])
    
    await update.message.reply_text(
        message,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def project_add_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    פקודה: /project_add <project_name> <file_name>
    הוספת קובץ לפרויקט
    """
    reporter.report_activity(update.effective_user.id)
    user_id = update.effective_user.id
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "➕ <b>הוספת קובץ לפרויקט</b>\n\n"
            "שימוש: <code>/project_add &lt;project&gt; &lt;file&gt;</code>\n\n"
            "דוגמה:\n"
            "<code>/project_add WebApp api.py</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    project_name = context.args[0]
    file_name = " ".join(context.args[1:])
    
    success = db.add_file_to_project(user_id, project_name, file_name)
    
    if success:
        project = db.get_project(user_id, project_name)
        file_count = project.get("file_count", 0) if project else 0
        
        await update.message.reply_text(
            f"✅ <b>קובץ נוסף לפרויקט!</b>\n\n"
            f"📁 פרויקט: <code>{project_name}</code>\n"
            f"📄 קובץ: <code>{file_name}</code>\n"
            f"📊 סה״כ קבצים: {file_count}",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            f"❌ לא ניתן להוסיף את הקובץ.\n"
            f"ודא שהפרויקט והקובץ קיימים."
        )


async def project_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    פקודה: /project <project_name>
    הצגת פרטי פרויקט
    """
    reporter.report_activity(update.effective_user.id)
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "📁 <b>הצגת פרויקט</b>\n\n"
            "שימוש: <code>/project &lt;project_name&gt;</code>\n\n"
            "דוגמה:\n"
            "<code>/project WebApp</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    project_name = " ".join(context.args)
    project = db.get_project(user_id, project_name)
    
    if not project:
        await update.message.reply_text(
            f"❌ פרויקט <code>{project_name}</code> לא נמצא.\n\n"
            "שלח <code>/projects</code> לרשימה.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # עדכון זמן גישה
    db.update_project_access(user_id, project_name)
    
    # בניית הודעה
    icon = project.get("icon", "📁")
    display = project.get("display_name", project_name)
    desc = project.get("description", "")
    file_count = project.get("file_count", 0)
    total_size = project.get("total_size", 0)
    languages = project.get("languages", {})
    files = project.get("files", [])
    
    message = f"{icon} <b>{display}</b>\n\n"
    
    if desc:
        message += f"📝 {desc}\n\n"
    
    message += f"📊 <b>סטטיסטיקה:</b>\n"
    message += f"   📂 {file_count} קבצים\n"
    message += f"   💾 {total_size:,} bytes\n"
    
    if languages:
        message += f"\n🔤 <b>שפות:</b>\n"
        for lang, count in sorted(languages.items(), key=lambda x: x[1], reverse=True):
            emoji = get_language_emoji(lang)
            message += f"   {emoji} {lang}: {count} קבצים\n"
    
    if files:
        message += f"\n📄 <b>קבצים ({min(len(files), 10)} ראשונים):</b>\n"
        for file_name in files[:10]:
            message += f"   • <code>{file_name}</code>\n"
        
        if len(files) > 10:
            message += f"   ... ועוד {len(files) - 10} קבצים\n"
    
    # כפתורים
    keyboard = [
        [
            InlineKeyboardButton("📄 הצג קבצים", callback_data=f"proj_files_{project_name}"),
            InlineKeyboardButton("➕ הוסף קובץ", callback_data=f"proj_add_{project_name}")
        ],
        [
            InlineKeyboardButton("📥 ייצא ZIP", callback_data=f"proj_export_{project_name}"),
            InlineKeyboardButton("⚙️ הגדרות", callback_data=f"proj_settings_{project_name}")
        ],
        [
            InlineKeyboardButton("🗑️ מחק פרויקט", callback_data=f"proj_delete_{project_name}")
        ]
    ]
    
    await update.message.reply_text(
        message,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def project_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מטפל בלחיצות על כפתורים"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data.startswith("show_proj_"):
        # הצגת פרויקט
        project_name = data.replace("show_proj_", "")
        project = db.get_project(user_id, project_name)
        
        if not project:
            await query.edit_message_text("❌ פרויקט לא נמצא")
            return
        
        db.update_project_access(user_id, project_name)
        
        # בניית הודעה (בדומה ל-project_show)
        icon = project.get("icon", "📁")
        display = project.get("display_name", project_name)
        file_count = project.get("file_count", 0)
        
        message = (
            f"{icon} <b>{display}</b>\n\n"
            f"📂 {file_count} קבצים\n"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("📄 קבצים", callback_data=f"proj_files_{project_name}"),
                InlineKeyboardButton("➕ הוסף", callback_data=f"proj_add_{project_name}")
            ],
            [
                InlineKeyboardButton("🔙 חזור", callback_data="projects_list")
            ]
        ]
        
        await query.edit_message_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("proj_files_"):
        # הצגת קבצי פרויקט
        project_name = data.replace("proj_files_", "")
        files = db.get_project_files(user_id, project_name)
        
        if not files:
            await query.edit_message_text(
                f"📁 פרויקט: <code>{project_name}</code>\n\n"
                "💭 אין קבצים בפרויקט עדיין.",
                parse_mode=ParseMode.HTML
            )
            return
        
        message_lines = [
            f"📁 <b>קבצי הפרויקט: {project_name}</b>\n"
        ]
        
        for idx, file in enumerate(files[:15], 1):
            name = file.get("file_name", "")
            lang = file.get("programming_language", "")
            emoji = get_language_emoji(lang)
            message_lines.append(f"{idx}. {emoji} <code>{name}</code>")
        
        if len(files) > 15:
            message_lines.append(f"\n... ועוד {len(files) - 15} קבצים")
        
        message = "\n".join(message_lines)
        
        keyboard = [[
            InlineKeyboardButton("🔙 חזור לפרויקט", callback_data=f"show_proj_{project_name}")
        ]]
        
        await query.edit_message_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("proj_delete_"):
        # מחיקת פרויקט
        project_name = data.replace("proj_delete_", "")
        
        keyboard = [
            [
                InlineKeyboardButton("⚠️ כן, מחק הכל", callback_data=f"proj_confirm_del_files_{project_name}"),
                InlineKeyboardButton("📁 מחק רק פרויקט", callback_data=f"proj_confirm_del_only_{project_name}")
            ],
            [
                InlineKeyboardButton("❌ ביטול", callback_data=f"show_proj_{project_name}")
            ]
        ]
        
        await query.edit_message_text(
            f"⚠️ <b>מחיקת פרויקט: {project_name}</b>\n\n"
            "בחר אפשרות:\n"
            "• <b>מחק הכל</b> - גם הפרויקט וגם הקבצים\n"
            "• <b>מחק רק פרויקט</b> - הקבצים יישארו",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("proj_confirm_del_"):
        # אישור מחיקה
        delete_files = "files" in data
        project_name = data.split("_")[-1]
        
        success = db.delete_project(user_id, project_name, delete_files=delete_files)
        
        if success:
            action = "והקבצים נמחקו" if delete_files else "נמחק (הקבצים נשארו)"
            await query.edit_message_text(
                f"✅ פרויקט <code>{project_name}</code> {action}",
                parse_mode=ParseMode.HTML
            )
        else:
            await query.edit_message_text("❌ שגיאה במחיקה")
    
    elif data == "projects_list":
        # חזרה לרשימת פרויקטים
        projects = db.get_user_projects(user_id)
        
        if not projects:
            await query.edit_message_text("💭 אין פרויקטים")
            return
        
        message_lines = ["📁 <b>הפרויקטים שלך</b>\n"]
        
        for proj in projects[:10]:
            name = proj["project_name"]
            icon = proj.get("icon", "📁")
            count = proj.get("file_count", 0)
            message_lines.append(f"{icon} <code>{name}</code> ({count} קבצים)")
        
        message = "\n".join(message_lines)
        
        keyboard = []
        proj_buttons = []
        for proj in projects[:6]:
            name = proj["project_name"]
            icon = proj.get("icon", "📁")
            proj_buttons.append(
                InlineKeyboardButton(f"{icon} {name[:12]}", callback_data=f"show_proj_{name}")
            )
        
        for i in range(0, len(proj_buttons), 2):
            keyboard.append(proj_buttons[i:i+2])
        
        await query.edit_message_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


def setup_projects_handlers(application):
    """רישום handlers"""
    
    # ConversationHandler ליצירת פרויקט
    create_conv = ConversationHandler(
        entry_points=[CommandHandler("project_create", project_create_start)],
        states={
            PROJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, project_create_name)],
            PROJECT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, project_create_description)]
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
    )
    
    application.add_handler(create_conv)
    application.add_handler(CommandHandler("projects", projects_list_command))
    application.add_handler(CommandHandler("project", project_show))
    application.add_handler(CommandHandler("project_add", project_add_file_command))
    application.add_handler(CallbackQueryHandler(
        project_callback_handler,
        pattern="^(show_proj_|proj_files_|proj_add_|proj_delete_|proj_confirm_|projects_list)"
    ))
```

---

### 4. שילוב ב-main.py

```python
from projects_handler import setup_projects_handlers

setup_projects_handlers(application)
```

---

### 5. שילוב בהצגת קובץ (bot_handlers.py)

```python
# בתוך show_command, הוסף כפתור "הוסף לפרויקט":

# קבלת פרויקטים של המשתמש
projects = db.get_user_projects(user_id)

keyboard = [
    # ... כפתורים קיימים
    [
        InlineKeyboardButton("📁 הוסף לפרויקט", callback_data=f"add_to_project_{file_name}"),
        InlineKeyboardButton("✏️ עריכה", callback_data=f"edit_{file_name}")
    ],
    # ...
]
```

---

## ✅ רשימת משימות

- [ ] יצירת קולקציה projects
- [ ] שדה project_id בקבצים
- [ ] מודל Project
- [ ] פונקציות DB
- [ ] Handler ליצירה
- [ ] Handler להצגה
- [ ] הוספה/הסרה של קבצים
- [ ] מחיקת פרויקט
- [ ] ייצוא פרויקט
- [ ] ארכוב פרויקטים

---

**סיום מדריך Projects** 📁
