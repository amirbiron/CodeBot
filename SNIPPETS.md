# Code Snippets Library 📚

ספרייה של תבניות קוד שימושיות למפתחים שבונים בוטים בטלגרם, WebApps וזרימות משתמש.

## תוכן עניינים

1. [תפריטים בבוט](#1-תפריטים-בבוט)
2. [עבודה עם מסד נתונים](#2-עבודה-עם-מסד-נתונים)
3. [ניהול קבצים וגרסאות](#3-ניהול-קבצים-וגרסאות)
4. [אינטגרציה עם WebApp](#4-אינטגרציה-עם-webapp)
5. [רכיבי UI ב-WebApp](#5-רכיבי-ui-ב-webapp)
6. [Structured Logging](#6-structured-logging)
7. [הודעות שגיאה ידידותיות](#7-הודעות-שגיאה-ידידותיות)
8. [בדיקות Pytest](#8-בדיקות-pytest)

---

## 1. תפריטים בבוט

### 1.1 תפריט פעולות על קובץ (Multi-Row Grid)

**למה זה שימושי:** יצירת תפריט עם מספר שורות של כפתורים, מאורגנים לפי פונקציונליות.

**מיקום:** `bot_handlers.py:309-328`

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# יצירת תפריט עם כפתורים מרובים
buttons = [
    [
        InlineKeyboardButton("🗑️ מחיקה", callback_data=f"delete_{file_id}"),
        InlineKeyboardButton("✏️ עריכה", callback_data=f"edit_{file_id}")
    ],
    [
        InlineKeyboardButton("📝 ערוך הערה", callback_data=f"edit_note_{file_id}"),
        InlineKeyboardButton("💾 הורדה", callback_data=f"download_{file_id}")
    ],
    [
        InlineKeyboardButton("🌐 שיתוף", callback_data=f"share_{file_id}")
    ],
    [
        InlineKeyboardButton(fav_text, callback_data=fav_cb)
    ]
]
reply_markup = InlineKeyboardMarkup(buttons)
await update.message.reply_text(
    response_text,
    parse_mode='HTML',
    reply_markup=reply_markup
)
```

---

### 1.2 תיבת אישור עם כפתורים (Yes/No Dialog)

**למה זה שימושי:** דיאלוג אישור פשוט לפני ביצוע פעולה קריטית.

**מיקום:** `bot_handlers.py:530-544`

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

keyboard = [
    [
        InlineKeyboardButton("✅ כן, מחק", callback_data=f"confirm_delete_{file_name}"),
        InlineKeyboardButton("❌ ביטול", callback_data="cancel_delete")
    ]
]
reply_markup = InlineKeyboardMarkup(keyboard)

await update.message.reply_text(
    f"🗑️ **אישור מחיקה**\n\n"
    f"האם אתה בטוח שברצונך למחוק את `{file_name}`?",
    parse_mode=ParseMode.MARKDOWN,
    reply_markup=reply_markup
)
```

---

### 1.3 Callback Query Handler - ניתוב לפי דפוס

**למה זה שימושי:** טיפול מרוכז בכל לחיצות הכפתורים, עם ניתוב לפי prefix.

**מיקום:** `bot_handlers.py:2703-2770`

```python
async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול בלחיצות על כפתורים"""
    query = update.callback_query
    await query.answer()  # חשוב! מאשר קבלת הלחיצה

    data = query.data
    user_id = query.from_user.id

    try:
        if data.startswith("confirm_delete_"):
            file_name = data.replace("confirm_delete_", "")
            if db.delete_file(user_id, file_name):
                await query.edit_message_text(
                    f"✅ הקובץ `{file_name}` נמחק בהצלחה!",
                    parse_mode=ParseMode.MARKDOWN
                )

        elif data == "cancel_delete":
            await query.edit_message_text("❌ מחיקה בוטלה.")

        elif data.startswith("share_gist_"):
            file_name = data.replace("share_gist_", "")
            await self._share_to_gist(query, user_id, file_name)

        # ... more handlers

    except Exception as e:
        logger.error(f"Error handling callback: {e}")
        await query.edit_message_text("⚠️ אירעה שגיאה")
```

---

### 1.4 Pagination Helper - כפתורי הקודם/הבא

**למה זה שימושי:** פונקציה שימושית לבניית כפתורי ניווט בעמודים.

**מיקום:** `handlers/pagination.py:6-29`

```python
from telegram import InlineKeyboardButton
from typing import Optional, List

def build_pagination_row(
    page: int,
    total_items: int,
    page_size: int,
    callback_prefix: str,
) -> Optional[List[InlineKeyboardButton]]:
    """בונה שורת כפתורי pagination או None אם אין צורך."""
    if page_size <= 0:
        return None

    total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1
    if total_pages <= 1:
        return None

    row: List[InlineKeyboardButton] = []

    if page > 1:
        row.append(
            InlineKeyboardButton("⬅️ הקודם", callback_data=f"{callback_prefix}{page-1}")
        )

    if page < total_pages:
        row.append(
            InlineKeyboardButton("➡️ הבא", callback_data=f"{callback_prefix}{page+1}")
        )

    return row or None
```

---

## 2. עבודה עם מסד נתונים

### 2.1 שמירת מסמך עם Versioning

**למה זה שימושי:** שמירה עם ניהול גרסאות אוטומטי + ביטול cache.

**מיקום:** `database/repository.py:141-165`

```python
from datetime import datetime, timezone
from dataclasses import asdict

def save_code_snippet(self, snippet: CodeSnippet) -> bool:
    try:
        # נרמול קוד לפני שמירה
        if config.NORMALIZE_CODE_ON_SAVE:
            snippet.code = normalize_code(snippet.code)

        # בדיקת גרסה קיימת
        existing = self.get_latest_version(snippet.user_id, snippet.file_name)
        if existing:
            snippet.version = existing['version'] + 1

        snippet.updated_at = datetime.now(timezone.utc)

        # שמירה במסד הנתונים
        result = self.manager.collection.insert_one(asdict(snippet))

        if result.inserted_id:
            # ביטול cache למשתמש
            cache.invalidate_user_cache(snippet.user_id)
            return True

        return False

    except Exception as e:
        logger.error(f"Error saving snippet: {e}")
        return False
```

---

### 2.2 שליפת מסמך אחד עם מטמון (Cached Query)

**למה זה שימושי:** שליפה מהירה עם caching אוטומטי למשך 3 דקות.

**מיקום:** `database/repository.py:643-671`

```python
from typing import Optional, Dict

@cached(expire_seconds=180, key_prefix="latest_version")
def get_latest_version(self, user_id: int, file_name: str) -> Optional[Dict]:
    try:
        # Fast-path לסביבות בדיקה
        docs_list = getattr(self.manager.collection, 'docs', None)
        if isinstance(docs_list, list):
            candidates = [
                d for d in docs_list
                if isinstance(d, dict)
                and d.get('user_id') == user_id
                and d.get('file_name') == file_name
            ]
            if candidates:
                latest = max(candidates, key=lambda d: int(d.get('version', 0) or 0))
                return dict(latest)

        # שליפה מה-DB עם סינון וסידור
        return self.manager.collection.find_one(
            {
                "user_id": user_id,
                "file_name": file_name,
                "$or": [
                    {"is_active": True},
                    {"is_active": {"$exists": False}}
                ]
            },
            sort=[("version", -1)],
        )

    except Exception as e:
        logger.error(f"Error fetching latest version: {e}")
        return None
```

---

### 2.3 Update עם Upsert וטיפול בשדות מותנים

**למה זה שימושי:** עדכון או יצירה (upsert) עם הגדרת שדות שונים ליצירה מול עדכון.

**מיקום:** `database/repository.py:1513-1529`

```python
from datetime import datetime, timezone

def save_github_token(self, user_id: int, token: str) -> bool:
    try:
        # הצפנת הטוקן
        from secret_manager import encrypt_secret
        enc = encrypt_secret(token)
        stored = enc if enc else token

        users_collection = self.manager.db.users

        result = users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "github_token": stored,
                    "updated_at": datetime.now(timezone.utc)
                },
                "$setOnInsert": {
                    "created_at": datetime.now(timezone.utc)
                }
            },
            upsert=True,  # יצירה אם לא קיים
        )

        return bool(result.acknowledged)

    except Exception as e:
        logger.error(f"Error saving token: {e}")
        return False
```

---

### 2.4 Aggregation Pipeline - שאילתא מורכבת

**למה זה שימושי:** שאילתות מתקדמות עם grouping, sorting ו-projection.

**מיקום:** `database/repository.py:394-404`

```python
def get_latest_files_aggregated(self, user_id: int, limit: int = 50):
    """מחזיר את הגרסה האחרונה של כל קובץ"""

    match = {"user_id": user_id, "is_active": True}
    sort_key = "updated_at"
    sort_dir = -1  # DESC

    pipeline = [
        {"$match": match},  # סינון
        {"$sort": {"file_name": 1, "version": -1}},  # מיון
        {"$group": {  # קיבוץ לפי שם קובץ
            "_id": "$file_name",
            "latest": {"$first": "$$ROOT"}
        }},
        {"$replaceRoot": {"newRoot": "$latest"}},  # החלפת root
        {"$sort": {sort_key: sort_dir}},  # מיון סופי
        {"$limit": max(1, int(limit or 50))},  # הגבלת תוצאות
        {"$project": {  # בחירת שדות
            "_id": 1,
            "file_name": 1,
            "programming_language": 1,
            "updated_at": 1
        }},
    ]

    rows = list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))
    return rows
```

---

### 2.5 Soft Delete עם TTL (Recycle Bin)

**למה זה שימושי:** מחיקה רכה עם אפשרות שחזור, ומחיקה סופית אוטומטית לאחר 7 ימים.

**מיקום:** `database/repository.py:954-986`

```python
from datetime import datetime, timezone, timedelta

def delete_file(self, user_id: int, file_name: str) -> bool:
    """מחיקה רכה - מסמן כלא פעיל במקום למחוק"""
    try:
        now = datetime.now(timezone.utc)
        ttl_days = int(getattr(config, 'RECYCLE_TTL_DAYS', 7) or 7)
        expires = now + timedelta(days=max(1, ttl_days))

        result = self.manager.collection.update_many(
            {
                "user_id": user_id,
                "file_name": file_name,
                "$or": [
                    {"is_active": True},
                    {"is_active": {"$exists": False}}
                ]
            },
            {
                "$set": {
                    "is_active": False,
                    "updated_at": now,
                    "deleted_at": now,
                    "deleted_expires_at": expires,  # TTL field
                }
            },
        )

        if result.modified_count > 0:
            cache.invalidate_user_cache(user_id)
            return True

        return False

    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        return False
```

---

## 3. ניהול קבצים וגרסאות

### 3.1 שמירת קובץ עם זיהוי שפה אוטומטי

**למה זה שימושי:** זרימה מלאה של שמירת קובץ - נרמול, זיהוי שפה, שמירה + החזרת ID.

**מיקום:** `handlers/save_flow.py:379-398`

```python
from database import db, CodeSnippet
from services.code_service import detect_language, normalize_code

async def save_file_final(update, context, filename, user_id):
    """שומר קובץ עם metadata מלא"""

    code = context.user_data.get('code_to_save')

    # נרמול קוד
    try:
        code = normalize_code(code)
    except Exception:
        pass

    # זיהוי שפת תכנות
    detected_language = detect_language(code, filename)

    # הערה אופציונלית
    note = (context.user_data.get('note_to_save') or '').strip()

    # יצירת snippet
    snippet = CodeSnippet(
        user_id=user_id,
        file_name=filename,
        code=code,
        programming_language=detected_language,
        description=note,
    )

    # שמירה
    success = db.save_code_snippet(snippet)

    if success:
        # שליפת המסמך השמור לקבלת ID
        saved_doc = db.get_latest_version(user_id, filename) or {}
        file_id = str(saved_doc.get('_id') or '')

        # שמירה בהקשר לשימוש עתידי
        context.user_data["last_save_success"] = {
            "file_name": filename,
            "language": detected_language,
            "file_id": file_id,
        }

        await update.message.reply_text(f"✅ הקובץ `{filename}` נשמר בהצלחה!")
```

---

### 3.2 שליפת גרסאות - Latest / All / Specific

**למה זה שימושי:** ממשק פשוט לניהול גרסאות של קבצים.

**מיקום:** `database/manager.py:618-628`

```python
def get_latest_version(self, user_id: int, file_name: str) -> Optional[Dict]:
    """מחזיר את הגרסה האחרונה של קובץ"""
    return self._get_repo().get_latest_version(user_id, file_name)

def get_all_versions(self, user_id: int, file_name: str) -> List[Dict]:
    """מחזיר את כל הגרסאות של קובץ"""
    return self._get_repo().get_all_versions(user_id, file_name)

def get_version(self, user_id: int, file_name: str, version: int) -> Optional[Dict]:
    """מחזיר גרסה ספציפית"""
    return self._get_repo().get_version(user_id, file_name, version)

# שימוש:
# latest = db.get_latest_version(123, "main.py")
# all_versions = db.get_all_versions(123, "main.py")
# v2 = db.get_version(123, "main.py", 2)
```

---

### 3.3 זיהוי שינויים בקובץ עם Hash

**למה זה שימושי:** זיהוי אם קובץ השתנה ללא צורך בהשוואת תוכן מלא.

**מיקום:** `database/bookmarks_manager.py:463-517`

```python
import hashlib
from datetime import datetime, timezone

def check_file_sync(self, file_id: str, new_content: str) -> Dict[str, Any]:
    """בודק אם הקובץ השתנה מאז השמירה האחרונה"""

    # חישוב hash חדש
    new_hash = hashlib.sha256(new_content.encode()).hexdigest()

    # שליפת hash ישן
    file_doc = self.files_collection.find_one({"_id": ObjectId(file_id)})
    old_hash = file_doc.get("content_hash") if file_doc else None

    # השוואה
    if old_hash == new_hash:
        return {"changed": False, "affected": []}

    # ניתוח השפעה על רשומות תלויות (למשל סימניות)
    old_lines = file_doc.get("code", "").splitlines()
    new_lines = new_content.splitlines()
    affected = self._analyze_bookmark_changes(file_id, old_lines, new_lines)

    # עדכון hash
    self.files_collection.update_one(
        {"_id": ObjectId(file_id)},
        {"$set": {
            "content_hash": new_hash,
            "code": new_content,
            "last_sync": datetime.now(timezone.utc)
        }}
    )

    return {
        "changed": True,
        "old_hash": old_hash,
        "new_hash": new_hash,
        "affected": affected
    }
```

---

## 4. אינטגרציה עם WebApp

### 4.1 יצירת כפתור WebApp עם קישור לקובץ

**למה זה שימושי:** פתיחת WebApp ישירות לקובץ ספציפי או תוצאות חיפוש.

**מיקום:** `handlers/file_view.py:84-108`

```python
from telegram import InlineKeyboardButton
from urllib.parse import quote_plus
from typing import Optional, List

def _get_webapp_button_row(
    file_id: Optional[str],
    file_name: Optional[str] = None
) -> Optional[List[InlineKeyboardButton]]:
    """בונה כפתור WebApp עם קישור לקובץ"""

    base_url = os.getenv('WEBAPP_URL') or config.WEBAPP_URL
    if not base_url:
        return None

    # קישור ישיר לקובץ לפי ID
    if file_id:
        target_url = f"{base_url}/file/{file_id}"

    # או קישור לחיפוש לפי שם
    elif file_name:
        try:
            query = quote_plus(str(file_name))
        except Exception:
            query = str(file_name)
        target_url = f"{base_url}/files?q={query}#results"

    else:
        return None

    return [InlineKeyboardButton("🌐 צפייה בWebApp", url=target_url)]

# שימוש:
# webapp_row = _get_webapp_button_row(file_id_str, file_name)
# if webapp_row:
#     buttons.append(webapp_row)
```

---

### 4.2 יצירת טוקן התחברות ל-WebApp

**למה זה שימושי:** יצירת טוקן מאובטח לכניסה ל-WebApp מהבוט.

**מיקום:** `conversation_handlers.py:171-202`

```python
import hashlib
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict

def _build_webapp_login_payload(
    db_manager,
    user_id: int,
    username: Optional[str]
) -> Optional[Dict[str, str]]:
    """יוצר טוקן התחברות מאובטח ל-WebApp"""

    base_url = os.getenv("WEBAPP_URL") or config.WEBAPP_URL
    secret = os.getenv("WEBAPP_LOGIN_SECRET") or config.SECRET_KEY or "dev-secret-key"

    try:
        # יצירת טוקן מאובטח
        token_data = f"{user_id}:{int(time.time())}:{secret}"
        auth_token = hashlib.sha256(token_data.encode("utf-8")).hexdigest()[:32]
    except Exception:
        logger.exception("יצירת טוקן webapp נכשלה")
        return None

    # שמירת הטוקן ב-DB
    now_utc = datetime.now(timezone.utc)
    token_doc = {
        "token": auth_token,
        "user_id": user_id,
        "username": username,
        "created_at": now_utc,
        "expires_at": now_utc + timedelta(minutes=5),  # תוקף 5 דקות
    }
    db_manager.db.webapp_tokens.insert_one(token_doc)

    # יצירת URL התחברות
    login_url = f"{base_url}/auth/token?token={auth_token}&user_id={user_id}"

    return {
        "auth_token": auth_token,
        "login_url": login_url,
        "webapp_url": base_url,
    }
```

---

### 4.3 אימות טוקן ויצירת Session (Server-Side)

**למה זה שימושי:** אימות הטוקן מהבוט ויצירת session במערכת ה-WebApp.

**מיקום:** `webapp/app.py:2526-2598`

```python
from flask import request, session, render_template
from datetime import datetime, timezone

@app.route('/auth/token')
def token_auth():
    """טיפול באימות עם טוקן מהבוט"""

    token = request.args.get('token')
    user_id = request.args.get('user_id')

    if not token or not user_id:
        return render_template('404.html'), 404

    try:
        db = get_db()

        # חיפוש הטוקן במסד נתונים
        token_doc = db.webapp_tokens.find_one({
            'token': token,
            'user_id': int(user_id)
        })

        if not token_doc:
            return render_template('login.html',
                                 error="קישור ההתחברות לא תקף או פג תוקפו")

        # בדיקת תוקף
        if token_doc['expires_at'] < datetime.now(timezone.utc):
            db.webapp_tokens.delete_one({'_id': token_doc['_id']})
            return render_template('login.html',
                                 error="קישור ההתחברות פג תוקף. אנא בקש קישור חדש מהבוט.")

        # מחיקת הטוקן לאחר שימוש (חד פעמי)
        db.webapp_tokens.delete_one({'_id': token_doc['_id']})

        # שמירת נתוני המשתמש בסשן
        user_id_int = int(user_id)
        session['user_id'] = user_id_int
        session['user_data'] = {
            'id': user_id_int,
            'first_name': token_doc.get('first_name', ''),
            'username': token_doc.get('username', ''),
        }

        # הפוך את הסשן לקבוע (30 יום)
        session.permanent = True

        return redirect('/files')

    except Exception as e:
        logger.error(f"Error in token auth: {e}")
        return render_template('login.html', error="שגיאה באימות")
```

---

### 4.4 אתחול WebApp בצד הלקוח (Frontend)

**למה זה שימושי:** זיהוי שה-WebApp נטען בתוך טלגרם והתאמת התצוגה.

**מיקום:** `webapp/templates/base.html:702-723`

```javascript
<script>
(function() {
    try {
        // זיהוי Telegram WebApp SDK
        if (window.Telegram && window.Telegram.WebApp) {
            document.body.classList.add('telegram-mini-app');

            // הרחבת viewport לשימוש מלא במסך
            try {
                window.Telegram.WebApp.expand();
            } catch (e) {}

            // איתות שה-WebApp מוכן
            try {
                window.Telegram.WebApp.ready();
            } catch (e) {}

            // קבלת נתוני משתמש מטלגרם
            const initData = window.Telegram.WebApp.initData;
            console.log('Telegram WebApp initialized:', initData);
        }
    } catch (e) {
        console.error('Error initializing Telegram WebApp:', e);
    }
})();
</script>
```

---

## 5. רכיבי UI ב-WebApp

### 5.1 Modal Dialog עם Promise

**למה זה שימושי:** דיאלוג מודלי שמחזיר תוצאה דרך Promise (async/await).

**מיקום:** `webapp/static/js/bulk-actions.js:296-428`

```javascript
async showTagDialog() {
    return new Promise((resolve) => {
        const dialog = document.createElement('div');
        dialog.className = 'modal-overlay';

        dialog.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h3><i class="fas fa-tags"></i> הוסף תגיות</h3>
                    <button class="modal-close" data-action="cancel">
                        <i class="fas fa-times"></i>
                    </button>
                </div>

                <div class="modal-body">
                    <p>הזן תגיות מופרדות בפסיקים:</p>
                    <input type="text" id="tagInput" class="tag-input"
                           placeholder="למשל: python, utils, important" autofocus>
                    <div class="tag-suggestions">
                        <span class="suggestion-label">הצעות:</span>
                        <button class="tag-suggestion" data-tag="important">important</button>
                        <button class="tag-suggestion" data-tag="python">python</button>
                    </div>
                </div>

                <div class="modal-footer">
                    <button class="btn btn-primary" data-action="confirm">
                        <i class="fas fa-check"></i> אישור
                    </button>
                    <button class="btn btn-secondary" data-action="cancel">
                        <i class="fas fa-times"></i> ביטול
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(dialog);

        // טיפול באירועים
        dialog.addEventListener('click', (e) => {
            const action = e.target.closest('[data-action]')?.dataset.action;

            if (action === 'confirm') {
                const input = dialog.querySelector('#tagInput');
                const tags = input.value.split(',').map(t => t.trim()).filter(Boolean);
                document.body.removeChild(dialog);
                resolve(tags);
            } else if (action === 'cancel') {
                document.body.removeChild(dialog);
                resolve(null);
            }
        });

        // פוקוס על ה-input
        setTimeout(() => dialog.querySelector('#tagInput')?.focus(), 100);
    });
}

// שימוש:
// const tags = await showTagDialog();
// if (tags) {
//     console.log('Selected tags:', tags);
// }
```

---

### 5.2 Toast Notification עם Auto-Dismiss

**למה זה שימושי:** הצגת הודעות זמניות שנעלמות אוטומטית.

**מיקום:** `webapp/static/js/bulk-actions.js:430-478`

```javascript
class NotificationManager {
    constructor() {
        this.notificationContainer = document.createElement('div');
        this.notificationContainer.className = 'notification-container';
        document.body.appendChild(this.notificationContainer);
    }

    showNotification(message, type = 'info', options = {}) {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;

        let icon = 'info-circle';
        if (type === 'success') icon = options.icon || 'check-circle';
        else if (type === 'error') icon = 'exclamation-circle';
        else if (type === 'warning') icon = 'exclamation-triangle';

        notification.innerHTML = `
            <div class="notification-content">
                <i class="fas fa-${icon}"></i>
                <span>${message}</span>
            </div>
            <button class="notification-close">
                <i class="fas fa-times"></i>
            </button>
        `;

        // טיפול בסגירה ידנית
        notification.querySelector('.notification-close').addEventListener('click', () => {
            notification.classList.add('fade-out');
            setTimeout(() => notification.remove(), 300);
        });

        this.notificationContainer.appendChild(notification);

        // אנימציית כניסה
        setTimeout(() => notification.classList.add('show'), 10);

        // סגירה אוטומטית
        const duration = options.duration || 3000;
        setTimeout(() => {
            if (notification.parentNode) {
                notification.classList.add('fade-out');
                setTimeout(() => notification.remove(), 300);
            }
        }, duration);
    }
}

// שימוש:
// const notifier = new NotificationManager();
// notifier.showNotification('הקובץ נשמר בהצלחה!', 'success');
// notifier.showNotification('שגיאה בשמירה', 'error', { duration: 5000 });
```

---

### 5.3 Loading Overlay עם Progress Bar

**למה זה שימושי:** מסך טעינה עם אפשרות לעדכון התקדמות באחוזים.

**מיקום:** `webapp/static/js/bulk-actions.js:12-29`

```javascript
class ProcessingOverlay {
    constructor() {
        const overlay = document.createElement('div');
        overlay.className = 'processing-overlay hidden';
        overlay.innerHTML = `
            <div class="processing-content">
                <div class="spinner"></div>
                <div class="processing-text">מעבד...</div>
                <div class="processing-progress hidden">
                    <div class="progress-bar">
                        <div class="progress-fill"></div>
                    </div>
                    <div class="progress-text">0%</div>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        this.overlay = overlay;
    }

    show(text = 'מעבד...', showProgress = false) {
        this.overlay.querySelector('.processing-text').textContent = text;
        const progressEl = this.overlay.querySelector('.processing-progress');

        if (showProgress) {
            progressEl.classList.remove('hidden');
        } else {
            progressEl.classList.add('hidden');
        }

        this.overlay.classList.remove('hidden');
    }

    updateProgress(percent) {
        const progressFill = this.overlay.querySelector('.progress-fill');
        const progressText = this.overlay.querySelector('.progress-text');

        if (progressFill && progressText) {
            progressFill.style.width = `${percent}%`;
            progressText.textContent = `${Math.round(percent)}%`;
        }
    }

    hide() {
        this.overlay.classList.add('hidden');
    }
}

// שימוש:
// const overlay = new ProcessingOverlay();
// overlay.show('מעבד קבצים...', true);
// for (let i = 0; i <= 100; i += 10) {
//     overlay.updateProgress(i);
//     await processChunk();
// }
// overlay.hide();
```

---

### 5.4 Card עם הרחבה (Expandable Card)

**למה זה שימושי:** כרטיס שניתן להרחיב לתצוגה מקדימה מלאה.

**מיקום:** `webapp/static/js/card-preview.js:40-63`

```javascript
async expandCard(fileId, cardElement) {
    cardElement.classList.add('card-preview-expanding');

    const wrapper = cardElement.querySelector('.preview-wrapper') ||
                   this.createWrapper(cardElement);

    // הצגת spinner
    wrapper.innerHTML = `
        <div class="preview-spinner">
            <i class="fas fa-circle-notch"></i>
            <span>טוען תצוגה מקדימה...</span>
        </div>
    `;

    try {
        // שליפת תוכן
        const res = await fetch(`/api/file/${encodeURIComponent(fileId)}/preview`, {
            headers: { 'Accept': 'application/json' },
            credentials: 'same-origin'
        });

        const data = await res.json().catch(() => ({}));

        if (!res.ok || !data || data.ok === false) {
            const msg = (data && data.error) ? data.error : 'שגיאה בטעינת תצוגה מקדימה';
            wrapper.innerHTML = `
                <div class="preview-error">
                    <i class="fas fa-exclamation-triangle"></i> ${msg}
                </div>
            `;
            return;
        }

        // הצגת תוכן
        wrapper.innerHTML = this.buildPreviewHTML(data, fileId);
        cardElement.classList.add('card-preview-expanded');

    } catch (error) {
        wrapper.innerHTML = `
            <div class="preview-error">
                <i class="fas fa-exclamation-triangle"></i> שגיאת רשת
            </div>
        `;
    } finally {
        cardElement.classList.remove('card-preview-expanding');
    }
}
```

---

## 6. Structured Logging

### 6.1 Emit Event עם Request ID

**למה זה שימושי:** לוגים מובנים עם מעקב אחר request ייחודי לאורך כל התהליך.

**מיקום:** `observability.py:492-589`

```python
import structlog
from typing import Any

def emit_event(event: str, severity: str = "info", **fields: Any) -> None:
    """שולח אירוע לוג מובנה"""

    logger = structlog.get_logger()
    fields.setdefault("event", event)

    # הוספת request_id מהקונטקסט
    if severity in {"error", "critical"}:
        ctx = get_observability_context()
        request_id = str(fields.get("request_id") or ctx.get("request_id") or "").strip()
        if request_id and "request_id" not in fields:
            fields["request_id"] = request_id

        # העשרת context עם command, user_id, chat_id
        command_tag = _sanitize_command_identifier(fields.get("command")) or str(ctx.get("command") or "")
        user_tag = _hash_identifier(fields.get("user_id")) or str(ctx.get("user_id") or "")
        chat_tag = _hash_identifier(fields.get("chat_id")) or str(ctx.get("chat_id") or "")

        if command_tag:
            fields["command"] = command_tag
        if user_tag:
            fields["user_id"] = user_tag
        if chat_tag:
            fields["chat_id"] = chat_tag

    # שליחת לוג
    log_method = getattr(logger, severity, logger.info)
    log_method(event, **fields)

# שימוש:
# emit_event("file_saved", severity="info", user_id=123, file_name="main.py")
# emit_event("db_error", severity="error", error=str(e), request_id=req_id)
```

---

### 6.2 Binding Request ID לקונטקסט

**למה זה שימושי:** קושר request_id לכל הלוגים בזרימה הנוכחית (גם async).

**מיקום:** `observability.py:484-489`

```python
import structlog

def bind_request_id(request_id: str) -> None:
    """קושר request_id לכל הלוגים בהקשר הנוכחי"""
    try:
        structlog.contextvars.bind_contextvars(request_id=request_id)
    except Exception:
        pass

    # שליחה גם ל-Sentry
    _set_sentry_tag("request_id", request_id)

# שימוש בתחילת request:
# request_id = generate_request_id()  # uuid4().hex
# bind_request_id(request_id)
#
# # כל הלוגים מעכשיו יכללו את ה-request_id אוטומטית:
# emit_event("processing_started", severity="info")
# emit_event("processing_completed", severity="info")
```

---

### 6.3 Binding User Context

**למה זה שימושי:** קישור user_id ו-chat_id לכל הלוגים בצורה אוטומטית.

**מיקום:** `observability.py:171-185`

```python
import structlog
from typing import Any, Optional, Dict

def bind_user_context(
    *,
    user_id: Any | None = None,
    chat_id: Any | None = None
) -> None:
    """קושר הקשר משתמש לכל הלוגים"""

    to_bind: Dict[str, str] = {}

    # Hash של user_id (אבטחת פרטיות)
    user_hash = _hash_identifier(user_id)
    if user_hash:
        to_bind["user_id"] = user_hash
        _set_sentry_tag("user_id", user_hash)

    # Hash של chat_id
    chat_hash = _hash_identifier(chat_id)
    if chat_hash:
        to_bind["chat_id"] = chat_hash
        _set_sentry_tag("chat_id", chat_hash)

    # קישור לקונטקסט
    if to_bind:
        try:
            structlog.contextvars.bind_contextvars(**to_bind)
        except Exception:
            pass

# שימוש:
# bind_user_context(user_id=update.effective_user.id, chat_id=update.effective_chat.id)
```

---

### 6.4 הגדרת Structlog עם Merge Context

**למה זה שימושי:** קונפיגורציה מלאה של structlog עם מיזוג קונטקסט אוטומטי.

**מיקום:** `observability.py:461-477`

```python
import structlog

def setup_structlog_logging(min_level: str | int = "INFO") -> None:
    """מגדיר structlog עם processors מלאים"""

    level = _parse_log_level(min_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # מיזוג context אוטומטי
            _add_otel_ids,                             # הוספת trace_id/span_id
            _redact_sensitive,                         # הסרת נתונים רגישים
            _add_schema_version,                       # גרסת schema
            structlog.processors.add_log_level,        # רמת לוג
            _mirror_to_log_aggregator,                 # שליחה ל-aggregator
            _maybe_sample_info,                        # דגימת info logs
            structlog.processors.TimeStamper(fmt="iso"),
            _choose_renderer(),  # JSON או console
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

# שימוש:
# setup_structlog_logging("INFO")
```

---

## 7. הודעות שגיאה ידידותיות

### 7.1 Rate Limit Error Handler

**למה זה שימושי:** טיפול בגבלת קצב עם הודעה ידידותית למשתמש + metrics.

**מיקום:** `webapp/app.py:1696-1727`

```python
from flask import jsonify, request

@app.errorhandler(429)
def _ratelimit_handler(e):
    """טיפול בהגבלת קצב"""
    try:
        # לוגים ומטריקות (best-effort)
        try:
            emit_event(
                "rate_limit_blocked",
                severity="warning",
                path=str(getattr(request, 'path', '')),
                remote=str(getattr(request, 'remote_addr', '')),
            )
        except Exception:
            pass

        try:
            from metrics import rate_limit_blocked
            if rate_limit_blocked is not None:
                scope = str(getattr(request, 'path', '') or 'route')
                rate_limit_blocked.labels(
                    source="webapp",
                    scope=scope,
                    limit="route"
                ).inc()
        except Exception:
            pass

        # תגובה למשתמש
        payload = {
            "error": "rate_limit_exceeded",
            "message": "יותר מדי בקשות. אנא נסה שוב מאוחר יותר.",
            "retry_after": getattr(e, 'description', None),
        }
        return jsonify(payload), 429

    except Exception:
        # fallback אם הכל נכשל
        return jsonify({"error": "rate_limit_exceeded"}), 429
```

---

### 7.2 Database Error עם הודעות ספציפיות

**למה זה שימושי:** טיפול בשגיאות DB ספציפיות עם הודעות מתאימות.

**מיקום:** `database/bookmarks_manager.py:116-240`

```python
from pymongo.errors import DuplicateKeyError

def toggle_bookmark(
    self,
    user_id: int,
    file_id: str,
    file_name: str,
    line_number: int,
    **kwargs
) -> Dict[str, Any]:
    """מוסיף או מסיר סימנייה"""

    try:
        # Validation
        if line_number <= 0:
            return {
                "ok": False,
                "action": "error",
                "error": "מספר שורה לא תקין"
            }

        note = kwargs.get('note', '')
        if len(note) > MAX_NOTE_LENGTH:
            note = note[:MAX_NOTE_LENGTH]

        # ... bookmark logic ...

        return {
            "ok": True,
            "action": "added",
            "bookmark": self._bookmark_to_response(bookmark)
        }

    except DuplicateKeyError:
        # שגיאה ספציפית - מפתח כפול
        return {
            "ok": False,
            "action": "error",
            "error": "הסימנייה כבר קיימת"
        }

    except Exception as e:
        # שגיאה כללית
        logger.error(f"Error toggling bookmark: {e}", exc_info=True)
        return {
            "ok": False,
            "action": "error",
            "error": "שגיאה בשמירת הסימנייה"
        }
```

---

### 7.3 Validation עם Error Messages

**למה זה שימושי:** ולידציה עם החזרת tuple של (success, data, error_message).

**מיקום:** `services/code_service.py:113-168`

```python
from typing import Tuple

def validate_code_input(
    code: str,
    file_name: str,
    user_id: int
) -> Tuple[bool, str, str]:
    """
    בודק ומנקה קלט קוד.

    Returns:
        Tuple[bool, str, str]: (is_valid, cleaned_code, error_message)
    """

    # בדיקות בסיסיות
    if not code or not code.strip():
        return False, "", "הקוד ריק"

    if len(code) > MAX_CODE_LENGTH:
        return False, "", f"הקוד ארוך מדי (מקסימום {MAX_CODE_LENGTH} תווים)"

    # ניקוי קוד
    try:
        cleaned = normalize_code(code)
    except Exception as e:
        return False, "", f"שגיאה בניקוי הקוד: {str(e)}"

    # ולידציה נוספת אם יש
    if code_processor:
        ok, cleaned, msg = code_processor.validate_code_input(code, file_name, user_id)
        if not ok:
            return False, cleaned, msg

    return True, cleaned, ""

# שימוש:
# is_valid, cleaned_code, error_msg = validate_code_input(code, filename, user_id)
# if not is_valid:
#     await update.message.reply_text(f"❌ {error_msg}")
#     return
# # המשך עם cleaned_code
```

---

### 7.4 Batch Processing עם Per-Item Errors

**למה זה שימושי:** עיבוד batch שלא נעצר על שגיאה בודדת, אלא עוקב אחר הצלחות/כישלונות.

**מיקום:** `batch_processor.py:70-138`

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

async def process_files_batch(
    self,
    job_id: str,
    operation_func: Callable,
    **kwargs
) -> BatchJob:
    """עיבוד batch של קבצים עם מעקב אחר שגיאות"""

    if job_id not in self.active_jobs:
        raise ValueError(f"עבודת batch {job_id} לא נמצאה")

    job = self.active_jobs[job_id]
    job.status = "running"
    job.start_time = time.time()

    try:
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # יצירת futures לכל הקבצים
            future_to_file = {
                executor.submit(operation_func, job.user_id, file_name, **kwargs): file_name
                for file_name in job.files
            }

            # עיבוד תוצאות עם מעקב אחר שגיאות
            for future in as_completed(future_to_file):
                file_name = future_to_file[future]

                try:
                    result = future.result()
                    success_flag = True

                    # בדיקת הצלחה
                    if isinstance(result, dict):
                        if 'is_valid' in result:
                            success_flag = bool(result.get('is_valid'))
                        elif 'error' in result:
                            success_flag = False

                    job.results[file_name] = {
                        'success': success_flag,
                        'result': result
                    }

                except Exception as e:
                    # שגיאה בקובץ בודד - לא עוצרים
                    job.results[file_name] = {
                        'success': False,
                        'error': str(e)
                    }
                    logger.error(f"שגיאה בעיבוד {file_name}: {e}")

                job.progress += 1

        # סיכום
        job.status = "completed"
        successful = sum(1 for r in job.results.values() if r['success'])
        failed = job.total - successful

        logger.info(f"עבודת batch {job_id} הושלמה: {successful} הצליחו, {failed} נכשלו")

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        logger.error(f"עבודת batch {job_id} נכשלה: {e}")

    return job
```

---

## 8. בדיקות Pytest

### 8.1 Fixture עם Setup/Teardown

**למה זה שימושי:** ניקוי סביבה לפני ואחרי כל בדיקה.

**מיקום:** `tests/test_webapp_button_helpers.py:13-17`

```python
import pytest

@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """ניקוי משתני סביבה לפני ואחרי כל בדיקה"""
    # Setup
    monkeypatch.delenv('WEBAPP_URL', raising=False)

    yield  # הבדיקה רצה כאן

    # Teardown
    monkeypatch.delenv('WEBAPP_URL', raising=False)
```

---

### 8.2 Test Parametrization

**למה זה שימושי:** הרצת אותה בדיקה עם כמה סטים של נתונים.

**מיקום:** `tests/test_webapp_button_helpers.py:20-40`

```python
import pytest
import types

@pytest.mark.parametrize(
    "config_values, env_value, expected",
    [
        (
            {"WEBAPP_URL": "https://cfg.example", "PUBLIC_BASE_URL": None},
            None,
            "https://cfg.example/file/abc"
        ),
        (
            {"WEBAPP_URL": None, "PUBLIC_BASE_URL": "https://public.example"},
            None,
            "https://public.example/file/abc"
        ),
        (
            {"WEBAPP_URL": None, "PUBLIC_BASE_URL": None},
            "https://env.example",
            "https://env.example/file/abc"
        ),
    ],
)
def test_file_view_webapp_button_prefers_available_source(
    monkeypatch,
    config_values,
    env_value,
    expected
):
    """בודק שהכפתור בוחר את המקור הנכון"""
    import handlers.file_view as fv

    # הגדרת config mock
    stub_cfg = types.SimpleNamespace(**config_values)
    monkeypatch.setattr(fv, 'config', stub_cfg, raising=False)

    # הגדרת env אם נדרש
    if env_value:
        monkeypatch.setenv('WEBAPP_URL', env_value)

    # הרצת הפונקציה
    row = fv._get_webapp_button_row('abc', None)

    # בדיקה
    assert row[0].url == expected
```

---

### 8.3 Async Test

**למה זה שימושי:** בדיקת פונקציות async עם aiohttp או asyncio.

**מיקום:** `tests/test_webserver_basic.py:5-25`

```python
import pytest
from aiohttp import web
import aiohttp

@pytest.mark.asyncio
async def test_health_endpoint_ok(monkeypatch):
    """בודק שה-health endpoint עובד"""
    from services.webserver import create_app

    app = create_app()

    # הרצת server זמני
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()

    try:
        # קבלת פורט דינמי
        port = list(site._server.sockets)[0].getsockname()[1]

        # שליחת request
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/health") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data.get("status") == "ok"

    finally:
        # ניקוי
        await runner.cleanup()
```

---

### 8.4 Mocking עם MagicMock

**למה זה שימושי:** החלפת dependencies עם mocks לבדיקה מבודדת.

**מיקום:** `test_bookmarks.py:112-134`

```python
from unittest.mock import MagicMock, Mock
import unittest

class TestBookmarks(unittest.TestCase):
    def test_toggle_bookmark_add(self):
        """בודק הוספת סימנייה חדשה"""

        # הגדרת mocks
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None  # סימנייה לא קיימת
        mock_collection.count_documents.return_value = 0
        mock_collection.insert_one.return_value = Mock(inserted_id="new_id")

        mock_db = MagicMock()
        mock_db.file_bookmarks = mock_collection

        manager = BookmarksManager(mock_db)

        # הרצת הפונקציה
        result = manager.toggle_bookmark(
            user_id=123,
            file_id="file123",
            file_name="test.py",
            file_path="/test.py",
            line_number=42,
            line_text="def test():",
            note="Test bookmark"
        )

        # בדיקות
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "added")
        self.assertIsNotNone(result["bookmark"])

        # וידוא שהפונקציה נקראה
        mock_collection.insert_one.assert_called_once()
```

---

### 8.5 Mocking עם @patch Decorator

**למה זה שימושי:** החלפת מודולים שלמים או פונקציות בצורה נקייה.

**מיקום:** `test_bookmarks.py:497-525`

```python
from unittest.mock import patch, MagicMock
import unittest

class TestBookmarks(unittest.TestCase):

    @patch('database.bookmarks_manager.logger')
    def test_error_handling(self, mock_logger):
        """בודק שהלוגים עובדים בשגיאות"""

        # הגדרת mocks
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_db.file_bookmarks = mock_collection

        # גורם לשגיאה
        mock_collection.find_one.return_value = None
        mock_collection.count_documents.return_value = 0
        mock_collection.insert_one.side_effect = Exception("DB Error")

        manager = BookmarksManager(mock_db)

        # הרצת הפונקציה
        result = manager.toggle_bookmark(
            user_id=123,
            file_id="file123",
            file_name="test.py",
            file_path="/test.py",
            line_number=42
        )

        # בדיקות
        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "error")

        # וידוא שהשגיאה נרשמה
        mock_logger.error.assert_called()
```

---

## סיכום

ספרייה זו מכילה **25+ סניפטים** מתוך הפרויקט, המכסים:

- ✅ **תפריטים בטלגרם**: כפתורים, callbacks, pagination
- ✅ **מסד נתונים**: MongoDB queries, updates, aggregations, soft deletes
- ✅ **ניהול קבצים**: שמירה, שליפה, versioning, hash-based tracking
- ✅ **WebApp**: אימות, tokens, buttons, frontend initialization
- ✅ **UI Components**: modals, toasts, overlays, cards
- ✅ **Logging**: structured logs, request_id, context binding
- ✅ **Error Handling**: user-friendly messages, per-item tracking
- ✅ **Testing**: fixtures, parametrization, async, mocking

כל סניפט כולל:
- **הסבר למה זה שימושי**
- **מיקום מדויק בקוד** (file:lines)
- **קוד עובד** שניתן להעתיק ישירות
- **הערות ודוגמאות שימוש**

---

**📌 טיפ:** השתמש ב-Ctrl+F כדי לחפש לפי נושא או מילת מפתח (למשל: "pagination", "modal", "async", "error").
