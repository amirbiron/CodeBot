# 📚 Code Snippets Library – ספריית תבניות קוד

> ספרייה התחלתית של תבניות קוד שימושיות מהפרויקט CodeBot.  
> כל סניפט נבחר בקפידה, מתועד ומוכן להעתקה.

---

## 📖 תוכן העניינים

1. [תפריטים בבוט (InlineKeyboard)](#1-תפריטים-בבוט-inlinekeyboard)
2. [עבודה עם Database & MongoDB](#2-עבודה-עם-database--mongodb)
3. [שמירה וטעינה של קבצים](#3-שמירה-וטעינה-של-קבצים)
4. [Structured Logging עם request_id](#4-structured-logging-עם-request_id)
5. [הודעות שגיאה ידידותיות](#5-הודעות-שגיאה-ידידותיות)
6. [WebApp – פתיחה מטלגרם](#6-webapp--פתיחה-מטלגרם)
7. [WebApp – Toast & Notifications](#7-webapp--toast--notifications)
8. [טיפול בטוח ב-CallbackQuery](#8-טיפול-בטוח-ב-callbackquery)
9. [בדיקות pytest פשוטות](#9-בדיקות-pytest-פשוטות)
10. [Safe File Deletion](#10-safe-file-deletion)
11. [Retry & Resilience](#11-retry--resilience)
12. [Cache Utils](#12-cache-utils)
13. [Text Utils](#13-text-utils)
14. [Security & Validation](#14-security--validation)
15. [Performance Timing](#15-performance-timing)
16. [Background Cleanup](#16-background-cleanup)
17. [Observability Context](#17-observability-context)
18. [Error Classification](#18-error-classification)
19. [HTTP Requests עם Tracing](#19-http-requests-עם-tracing)
20. [Code Normalization](#20-code-normalization)

---

## 1. תפריטים בבוט (InlineKeyboard)

### 1.1 תפריט בסיסי עם כפתורים

**למה זה שימושי:** יצירת תפריט אינטראקטיבי עם כפתורי callback.

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# בניית תפריט עם כפתורים
keyboard = [
    [InlineKeyboardButton("📄 הצג קבצים", callback_data="show_files")],
    [InlineKeyboardButton("⭐ מועדפים", callback_data="show_favorites")],
    [InlineKeyboardButton("🔍 חיפוש", callback_data="start_search")],
    [InlineKeyboardButton("⚙️ הגדרות", callback_data="settings")]
]
reply_markup = InlineKeyboardMarkup(keyboard)

await update.message.reply_text(
    "בחר פעולה:",
    reply_markup=reply_markup
)
```

### 1.2 תפריט עם עימוד (Pagination)

**למה זה שימושי:** ניווט בין דפים של תוצאות.

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def build_pagination_keyboard(page: int, total_pages: int, base_callback: str):
    """בניית מקלדת עימוד"""
    keyboard = []
    
    # כפתורי ניווט
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"{base_callback}_{page-1}"))
    
    nav_row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
    
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("➡️ הבא", callback_data=f"{base_callback}_{page+1}"))
    
    keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data="back")])
    
    return InlineKeyboardMarkup(keyboard)

# שימוש
reply_markup = build_pagination_keyboard(page=2, total_pages=10, base_callback="search_page")
await query.edit_message_text("תוצאות חיפוש:", reply_markup=reply_markup)
```

### 1.3 תפריט דינמי מנתוני DB

**למה זה שימושי:** בניית תפריט מרשימת פריטים מה-DB.

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# קבלת רשימת קבצים מהDB
files = db.get_user_files(user_id, limit=10)

keyboard = []
for idx, file_doc in enumerate(files):
    file_name = file_doc.get('file_name', 'קובץ')
    lang = file_doc.get('programming_language', 'text')
    button_text = f"📄 {file_name} ({lang})"
    keyboard.append([InlineKeyboardButton(button_text, callback_data=f"file_{idx}")])

keyboard.append([InlineKeyboardButton("🔙 חזרה", callback_data="main_menu")])
reply_markup = InlineKeyboardMarkup(keyboard)

await update.message.reply_text("בחר קובץ:", reply_markup=reply_markup)
```

---

## 2. עבודה עם Database & MongoDB

### 2.1 שמירת קובץ ל-DB

**למה זה שימושי:** שמירה מהירה של קטע קוד עם metadata.

```python
from datetime import datetime, timezone

def save_file(user_id: int, file_name: str, code: str, programming_language: str = "text", 
              extra_tags: list = None):
    """שמירת קובץ חדש ל-DB"""
    doc = {
        "user_id": user_id,
        "file_name": file_name,
        "code": code,
        "programming_language": programming_language,
        "tags": extra_tags or [],
        "version": 1,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "is_active": True
    }
    
    result = db.files.insert_one(doc)
    return result.inserted_id
```

### 2.2 שליפת גרסה אחרונה של קובץ

**למה זה שימושי:** קבלת הגרסה העדכנית ביותר של קובץ.

```python
def get_latest_version(user_id: int, file_name: str):
    """שליפת גרסה אחרונה של קובץ"""
    return db.files.find_one(
        {
            "user_id": user_id,
            "file_name": file_name,
            "is_active": True
        },
        sort=[("version", -1)]
    )
```

### 2.3 חיפוש קבצים עם פילטרים

**למה זה שימושי:** חיפוש גמיש עם מספר קריטריונים.

```python
def search_files(user_id: int, query: str = "", language: str = None, 
                 tags: list = None, limit: int = 20):
    """חיפוש קבצים עם פילטרים"""
    filters = {
        "user_id": user_id,
        "is_active": True
    }
    
    # חיפוש טקסט
    if query:
        filters["$or"] = [
            {"file_name": {"$regex": query, "$options": "i"}},
            {"code": {"$regex": query, "$options": "i"}}
        ]
    
    # סינון לפי שפה
    if language:
        filters["programming_language"] = language
    
    # סינון לפי תגיות
    if tags:
        filters["tags"] = {"$in": tags}
    
    return list(db.files.find(filters).limit(limit).sort("updated_at", -1))
```

---

## 3. שמירה וטעינה של קבצים

### 3.1 יצירת גיבוי ZIP

**למה זה שימושי:** יצירת ארכיון ZIP עם metadata.

```python
import zipfile
import json
from datetime import datetime, timezone
from pathlib import Path

def create_backup_zip(user_id: int, files_data: list, output_path: str):
    """יצירת ZIP עם metadata"""
    with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        # שמירת metadata
        metadata = {
            "user_id": user_id,
            "backup_id": f"backup_{user_id}_{int(datetime.now(timezone.utc).timestamp())}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "file_count": len(files_data),
            "backup_type": "manual"
        }
        zf.writestr('metadata.json', json.dumps(metadata, indent=2, ensure_ascii=False))
        
        # שמירת קבצים
        for file_doc in files_data:
            file_name = file_doc.get('file_name', 'untitled.txt')
            code = file_doc.get('code', '')
            zf.writestr(file_name, code.encode('utf-8'))
    
    return Path(output_path).stat().st_size
```

### 3.2 בדיקת בטיחות לפני מחיקה

**למה זה שימושי:** מניעת מחיקה בטעות של נתיבים מסוכנים.

```python
from pathlib import Path

def is_safe_path(target: Path, allow_under: Path) -> bool:
    """בדיקת בטיחות למסלול לפני מחיקה"""
    try:
        rp_target = target.resolve()
        rp_base = allow_under.resolve()
        
        # מונע מחיקה של נתיבים מסוכנים
        if str(rp_target) in ["/", str(Path.home()), str(Path.cwd())]:
            return False
        
        # דרוש שהנתיב יהיה תחת allow_under
        return str(rp_target).startswith(str(rp_base) + "/") or (str(rp_target) == str(rp_base))
    except Exception:
        return False

# שימוש
backup_dir = Path("/app/backups")
file_to_delete = Path("/app/backups/backup_123.zip")

if is_safe_path(file_to_delete, backup_dir):
    file_to_delete.unlink()
else:
    raise ValueError("Unsafe path - deletion blocked")
```

---

## 4. Structured Logging עם request_id

### 4.1 יצירה וקישור של request_id

**למה זה שימושי:** מעקב אחר בקשות ושגיאות לאורך כל המערכת.

```python
from observability import generate_request_id, bind_request_id, emit_event

# בתחילת handler
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # יצירת request_id ייחודי
    request_id = generate_request_id()
    bind_request_id(request_id)
    
    # לוג עם הקשר מלא
    emit_event(
        "command_received",
        severity="info",
        command="start",
        user_id=update.effective_user.id
    )
    
    # כל הלוגים מעכשיו יכללו את ה-request_id אוטומטית
    try:
        # ... הלוגיקה שלך ...
        emit_event("command_completed", severity="info")
    except Exception as e:
        emit_event("command_failed", severity="error", error=str(e))
```

### 4.2 העברת request_id ל-HTTP requests

**למה זה שימושי:** שמירה על correlation בין שירותים.

```python
from observability import prepare_outgoing_headers

async def call_external_api(url: str, data: dict):
    """קריאה לAPI חיצוני עם tracing headers"""
    # הכנת headers עם request_id ו-tracing
    headers = prepare_outgoing_headers({
        "Content-Type": "application/json"
    })
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as response:
            return await response.json()
```

---

## 5. הודעות שגיאה ידידותיות

### 5.1 הודעת שגיאה עם context

**למה זה שימושי:** מסר ברור למשתמש + לוג טכני מפורט.

```python
async def handle_error(update: Update, context: ContextTypes.DEFAULT_TYPE, error: Exception):
    """טיפול בשגיאה עם הודעה ידידותית"""
    # הודעה למשתמש
    user_message = (
        "⚠️ אופס! משהו השתבש.\n"
        "נסה שוב בעוד רגע, או פנה לתמיכה אם הבעיה נמשכת."
    )
    
    await update.message.reply_text(user_message)
    
    # לוג מפורט למפתחים
    emit_event(
        "user_action_failed",
        severity="error",
        error=str(error),
        error_type=type(error).__name__,
        user_id=update.effective_user.id,
        command=context.user_data.get('last_command', 'unknown')
    )
```

### 5.2 בדיקת input והודעות ולידציה

**למה זה שימושי:** למנוע שגיאות מראש עם feedback ברור.

```python
async def validate_filename(filename: str) -> tuple[bool, str]:
    """בדיקת תקינות שם קובץ"""
    if not filename:
        return False, "❌ שם הקובץ לא יכול להיות ריק"
    
    if len(filename) > 100:
        return False, "❌ שם הקובץ ארוך מדי (מקסימום 100 תווים)"
    
    # תווים לא חוקיים
    invalid_chars = '<>:"/\\|?*'
    if any(char in filename for char in invalid_chars):
        return False, f"❌ שם הקובץ מכיל תווים לא חוקיים: {invalid_chars}"
    
    return True, "✅ שם הקובץ תקין"

# שימוש
is_valid, message = await validate_filename(user_input)
if not is_valid:
    await update.message.reply_text(message)
    return
```

---

## 6. WebApp – פתיחה מטלגרם

### 6.1 כפתור לפתיחת WebApp

**למה זה שימושי:** פתיחת אפליקציית Web מתוך טלגרם.

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def show_webapp_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """הצגת כפתור לפתיחת WebApp"""
    webapp_url = os.getenv('WEBAPP_URL', 'https://example.com')
    
    keyboard = [
        [InlineKeyboardButton("🌐 פתח את ה-Web App", url=webapp_url)],
        [InlineKeyboardButton("🔐 התחבר ל-Web App", url=f"{webapp_url}/login")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📱 ניתן לצפות בקבצים גם דרך ה-Web App:",
        reply_markup=reply_markup
    )
```

### 6.2 Telegram Login Widget (backend)

**למה זה שימושי:** אימות משתמשים דרך Telegram.

```python
import hashlib
import hmac

def verify_telegram_auth(auth_data: dict, bot_token: str) -> bool:
    """אימות נתוני התחברות מ-Telegram"""
    check_hash = auth_data.get('hash', '')
    
    # הכנת נתוני בדיקה
    data_check_arr = []
    for key in sorted(auth_data.keys()):
        if key != 'hash':
            data_check_arr.append(f"{key}={auth_data[key]}")
    
    data_check_string = '\n'.join(data_check_arr)
    
    # חישוב hash
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return calculated_hash == check_hash
```

---

## 7. WebApp – Toast & Notifications

### 7.1 Toast Notification (JavaScript)

**למה זה שימושי:** הצגת הודעות זמניות בממשק.

```javascript
// פונקציה להצגת Toast
function showToast(message, type = 'info', duration = 3000) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    
    // סגנון בסיסי
    Object.assign(toast.style, {
        position: 'fixed',
        bottom: '20px',
        right: '20px',
        padding: '15px 20px',
        borderRadius: '8px',
        backgroundColor: type === 'success' ? '#4CAF50' : 
                        type === 'error' ? '#f44336' : '#2196F3',
        color: 'white',
        boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
        zIndex: '9999',
        animation: 'slideIn 0.3s ease-out'
    });
    
    document.body.appendChild(toast);
    
    // הסרה אוטומטית
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// שימוש
showToast('הקובץ נשמר בהצלחה!', 'success');
showToast('שגיאה בשמירה', 'error');
```

### 7.2 Modal Dialog (JavaScript)

**למה זה שימושי:** תיבת דו-שיח מותאמת אישית.

```javascript
function showModal(title, content, buttons = []) {
    // יצירת רקע עמום
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.style.cssText = `
        position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.5); z-index: 10000;
        display: flex; align-items: center; justify-content: center;
    `;
    
    // יצירת modal
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.cssText = `
        background: white; padding: 24px; border-radius: 12px;
        max-width: 500px; width: 90%; box-shadow: 0 10px 40px rgba(0,0,0,0.2);
    `;
    
    modal.innerHTML = `
        <h3 style="margin-top: 0;">${title}</h3>
        <div style="margin: 16px 0;">${content}</div>
        <div class="modal-buttons" style="display: flex; gap: 8px; justify-content: flex-end;">
        </div>
    `;
    
    // הוספת כפתורים
    const buttonsContainer = modal.querySelector('.modal-buttons');
    buttons.forEach(btn => {
        const button = document.createElement('button');
        button.textContent = btn.text;
        button.className = btn.primary ? 'btn-primary' : 'btn-secondary';
        button.onclick = () => {
            overlay.remove();
            if (btn.onClick) btn.onClick();
        };
        buttonsContainer.appendChild(button);
    });
    
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    
    // סגירה בלחיצה על הרקע
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.remove();
    });
}

// שימוש
showModal(
    'מחיקת קובץ',
    'האם אתה בטוח שברצונך למחוק את הקובץ?',
    [
        { text: 'ביטול', onClick: () => console.log('Cancelled') },
        { text: 'מחק', primary: true, onClick: () => deleteFile() }
    ]
);
```

---

## 8. טיפול בטוח ב-CallbackQuery

### 8.1 מענה בטוח ל-query (נגד "Query is too old")

**למה זה שימושי:** מונע שגיאות במקרים של query ישן.

```python
async def safe_answer(query, text: str = None, show_alert: bool = False):
    """מענה בטוח ל-CallbackQuery: מתעלם משגיאות 'Query is too old'"""
    try:
        kwargs = {}
        if text is not None:
            kwargs["text"] = text
        if show_alert:
            kwargs["show_alert"] = True
        await query.answer(**kwargs)
    except Exception as e:
        msg = str(e).lower()
        if "query is too old" in msg or "query_id_invalid" in msg:
            return  # התעלם מ-query ישן
        raise  # שגיאות אחרות - העלה מחדש
```

### 8.2 עריכת הודעה בטוחה (נגד "Message is not modified")

**למה זה שימושי:** מונע שגיאות כאשר ההודעה זהה.

```python
async def safe_edit_message_text(query, text: str, reply_markup=None, parse_mode=None):
    """עריכת טקסט הודעה בבטיחות: מתעלם משגיאת 'Message is not modified'"""
    try:
        kwargs = {"text": text, "reply_markup": reply_markup}
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        
        await query.edit_message_text(**kwargs)
    except Exception as e:
        msg = str(e).lower()
        if "not modified" in msg or "message is not modified" in msg:
            return  # ההודעה זהה - אין צורך בעדכון
        raise
```

### 8.3 מניעת לחיצות כפולות

**למה זה שימושי:** חוסם פעולה מרובת ביצועים בגלל לחיצות כפולות.

```python
import time
from typing import Dict

class CallbackQueryGuard:
    """Guard ללחיצות כפולות על כפתורי CallbackQuery"""
    _last_clicks: Dict[int, float] = {}
    WINDOW_SECONDS = 1.2
    
    @staticmethod
    def should_block(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """בודק האם יש לחסום את העדכון כלחיצה כפולה"""
        user_id = update.effective_user.id
        now = time.time()
        
        last_click = CallbackQueryGuard._last_clicks.get(user_id, 0.0)
        if (now - last_click) < CallbackQueryGuard.WINDOW_SECONDS:
            return True  # חסום - לחיצה כפולה
        
        CallbackQueryGuard._last_clicks[user_id] = now
        return False

# שימוש ב-handler
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if CallbackQueryGuard.should_block(update, context):
        return  # התעלם מלחיצה כפולה
    
    query = update.callback_query
    await query.answer()
    # ... הלוגיקה שלך ...
```

---

## 9. בדיקות pytest פשוטות

### 9.1 טסט אסינכרוני בסיסי

**למה זה שימושי:** בדיקת פונקציות async.

```python
import pytest

@pytest.mark.asyncio
async def test_save_file_success():
    """בדיקת שמירת קובץ מוצלחת"""
    user_id = 12345
    file_name = "test.py"
    code = "print('hello')"
    
    # הרצת הפעולה
    result = await save_file_async(user_id, file_name, code)
    
    # בדיקות
    assert result is not None
    assert result['file_name'] == file_name
    assert result['user_id'] == user_id
```

### 9.2 טסט עם mock

**למה זה שימושי:** בדיקת לוגיקה ללא תלות ב-DB/API.

```python
import pytest
from unittest.mock import Mock, AsyncMock

@pytest.mark.asyncio
async def test_send_notification_success(monkeypatch):
    """בדיקת שליחת התראה"""
    # Mock של הפונקציה החיצונית
    mock_send = AsyncMock(return_value=True)
    monkeypatch.setattr("my_module.send_telegram_message", mock_send)
    
    # הרצה
    result = await notify_user(user_id=123, message="Test")
    
    # בדיקות
    assert result is True
    mock_send.assert_called_once_with(123, "Test")
```

### 9.3 טסט עם fixtures

**למה זה שימושי:** שיתוף setup בין טסטים.

```python
import pytest

@pytest.fixture
def sample_user():
    """משתמש לדוגמה לבדיקות"""
    return {
        "user_id": 12345,
        "username": "test_user",
        "files_count": 10
    }

@pytest.fixture
def sample_files():
    """קבצים לדוגמה"""
    return [
        {"file_name": "test1.py", "code": "print(1)"},
        {"file_name": "test2.js", "code": "console.log(2)"}
    ]

def test_user_has_files(sample_user, sample_files):
    """בדיקה שהמשתמש מקבל קבצים"""
    result = assign_files_to_user(sample_user, sample_files)
    assert len(result['files']) == 2
    assert result['user_id'] == 12345
```

---

## 10. Safe File Deletion

### 10.1 מחיקה בטוחה עם בדיקות

**למה זה שימושי:** מניעת מחיקה בטעות של קבצים חשובים.

```python
from pathlib import Path

def safe_rmtree(path: Path, allow_under: Path) -> None:
    """מחיקה בטוחה של תיקייה"""
    import shutil
    
    p = path.resolve()
    base = allow_under.resolve()
    
    # בדיקות בטיחות
    dangerous_paths = [Path('/'), Path.home(), Path.cwd()]
    if p in dangerous_paths:
        raise RuntimeError(f"Refusing to delete dangerous path: {p}")
    
    if not str(p).startswith(str(base)):
        raise RuntimeError(f"Path {p} is not under allowed base {base}")
    
    # מחיקה
    shutil.rmtree(p)

# שימוש
try:
    safe_rmtree(Path("/tmp/backups/old"), allow_under=Path("/tmp/backups"))
except RuntimeError as e:
    print(f"Deletion blocked: {e}")
```

---

## 11. Retry & Resilience

### 11.1 Retry עם exponential backoff

**למה זה שימושי:** חוסן בפני כשלים זמניים.

```python
import asyncio
from typing import Callable, Any

async def retry_async(
    func: Callable,
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    **kwargs
) -> Any:
    """ניסיון חוזר עם exponential backoff"""
    delay = initial_delay
    last_error = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            return await func(**kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_attempts:
                await asyncio.sleep(delay)
                delay *= backoff_factor
    
    raise last_error

# שימוש
result = await retry_async(
    fetch_data_from_api,
    max_attempts=3,
    initial_delay=1.0,
    url="https://api.example.com/data"
)
```

---

## 12. Cache Utils

### 12.1 Cache פשוט עם TTL

**למה זה שימושי:** שיפור ביצועים עם caching זמני.

```python
import time
from typing import Any, Dict

class SimpleCache:
    """Cache פשוט עם TTL"""
    
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._times: Dict[str, float] = {}
    
    def set(self, key: str, value: Any, ttl: int = 300):
        """שמירה בcache עם TTL (שניות)"""
        self._cache[key] = value
        self._times[key] = time.time() + ttl
    
    def get(self, key: str, default: Any = None) -> Any:
        """קבלה מהcache"""
        if key not in self._cache:
            return default
        
        # בדיקת תפוגה
        if time.time() > self._times.get(key, 0):
            self.delete(key)
            return default
        
        return self._cache[key]
    
    def delete(self, key: str):
        """מחיקה מהcache"""
        self._cache.pop(key, None)
        self._times.pop(key, None)

# שימוש
cache = SimpleCache()
cache.set("user_123_files", files_list, ttl=600)  # 10 דקות
files = cache.get("user_123_files", default=[])
```

---

## 13. Text Utils

### 13.1 Escape Markdown V2

**למה זה שימושי:** הגנה על תווים מיוחדים ב-Telegram MarkdownV2.

```python
def escape_markdown(text: str, version: int = 2) -> str:
    """הגנה על תווים מיוחדים ב-Markdown"""
    if version == 2:
        # Markdown V2
        special_chars = set("_*[]()~`>#+-=|{}.!\\")
        return "".join(("\\" + ch) if ch in special_chars else ch for ch in text)
    else:
        # Markdown V1
        special_chars = set("_*`[()\\")
        return "".join(("\\" + ch) if ch in special_chars else ch for ch in text)

# שימוש
safe_text = escape_markdown("קובץ [test].py עם *כוכבית*")
await update.message.reply_text(safe_text, parse_mode="MarkdownV2")
```

### 13.2 Format File Size

**למה זה שימושי:** המרה קריאה של bytes לגודל קובץ.

```python
def format_file_size(size_bytes: int) -> str:
    """פורמט גודל קובץ (bytes -> KB/MB/GB)"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.1f} GB"

# שימוש
size = format_file_size(1536000)  # "1.5 MB"
```

### 13.3 Truncate Text

**למה זה שימושי:** קיצור טקסט ארוך עם סיומת.

```python
def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """קיצור טקסט עם סיומת"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix

# שימוש
short_text = truncate_text("This is a very long text that needs to be shortened", max_length=30)
# "This is a very long text..."
```

---

## 14. Security & Validation

### 14.1 Hash Content

**למה זה שימושי:** יצירת hash לזיהוי תוכן ייחודי.

```python
import hashlib

def hash_content(content: str, algorithm: str = 'sha256') -> str:
    """יצירת hash לתוכן"""
    if algorithm == 'sha256':
        return hashlib.sha256(content.encode()).hexdigest()
    elif algorithm == 'md5':
        return hashlib.md5(content.encode()).hexdigest()
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")

# שימוש
file_hash = hash_content(code_content)
```

### 14.2 Validate User Input

**למה זה שימושי:** בדיקת קלט משתמש לפני עיבוד.

```python
import re

def validate_user_input(text: str, max_length: int = 10000, 
                       forbidden_patterns: list = None) -> tuple[bool, str]:
    """בדיקת קלט משתמש"""
    if len(text) > max_length:
        return False, f"הטקסט ארוך מדי (מקסימום {max_length} תווים)"
    
    if forbidden_patterns:
        for pattern in forbidden_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False, "הטקסט מכיל תוכן אסור"
    
    return True, "תקין"

# שימוש
is_valid, message = validate_user_input(
    user_text,
    forbidden_patterns=[r'<script>', r'javascript:']
)
```

---

## 15. Performance Timing

### 15.1 Context Manager למדידת זמן

**למה זה שימושי:** מדידה פשוטה של זמן ביצוע.

```python
import time
from contextlib import contextmanager

@contextmanager
def measure_time(operation_name: str):
    """מדידת זמן עם context manager"""
    start_time = time.time()
    try:
        yield
    finally:
        execution_time = time.time() - start_time
        print(f"{operation_name}: {execution_time:.3f}s")

# שימוש
with measure_time("Database Query"):
    results = db.files.find({"user_id": 123}).limit(100).to_list()

# פלט: "Database Query: 0.045s"
```

### 15.2 Timing Decorator

**למה זה שימושי:** דקורטור אוטומטי למדידת פונקציות.

```python
import time
from functools import wraps

def timing_decorator(func):
    """דקורטור למדידת זמן ביצוע"""
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = await func(*args, **kwargs)
            duration = time.time() - start
            print(f"{func.__name__} completed in {duration:.3f}s")
            return result
        except Exception as e:
            duration = time.time() - start
            print(f"{func.__name__} failed after {duration:.3f}s: {e}")
            raise
    
    return async_wrapper

# שימוש
@timing_decorator
async def process_large_file(file_id: str):
    # ... עיבוד ...
    pass
```

---

## 16. Background Cleanup

### 16.1 ניקוי גיבויים ישנים

**למה זה שימושי:** ניהול אוטומטי של מקום בדיסק.

```python
from datetime import datetime, timedelta, timezone
from pathlib import Path

def cleanup_old_backups(backup_dir: Path, retention_days: int = 30, 
                       max_per_user: int = None) -> dict:
    """ניקוי גיבויים ישנים"""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    
    summary = {"scanned": 0, "deleted": 0, "errors": []}
    
    # סריקת קבצי ZIP
    by_user = {}
    for backup_file in backup_dir.glob("*.zip"):
        summary["scanned"] += 1
        
        # חילוץ תאריך יצירה
        created_at = datetime.fromtimestamp(backup_file.stat().st_mtime, tz=timezone.utc)
        
        # חילוץ user_id מהשם
        user_id = extract_user_id_from_filename(backup_file.name)
        
        by_user.setdefault(user_id, []).append((backup_file, created_at))
    
    # מחיקה לפי מדיניות
    for user_id, backups in by_user.items():
        backups.sort(key=lambda x: x[1], reverse=True)  # מהחדש לישן
        
        # שמור רק את ה-N האחרונים
        if max_per_user and len(backups) > max_per_user:
            for backup_file, _ in backups[max_per_user:]:
                try:
                    backup_file.unlink()
                    summary["deleted"] += 1
                except Exception as e:
                    summary["errors"].append(str(e))
        
        # מחק גיבויים ישנים מעבר ל-retention
        for backup_file, created_at in backups:
            if created_at < cutoff:
                try:
                    backup_file.unlink()
                    summary["deleted"] += 1
                except Exception as e:
                    summary["errors"].append(str(e))
    
    return summary
```

---

## 17. Observability Context

### 17.1 קבלת context נוכחי

**למה זה שימושי:** גישה למידע על הבקשה הנוכחית.

```python
from observability import get_observability_context, get_request_id

# קבלת כל ה-context
context = get_observability_context()
print(f"Request ID: {context.get('request_id')}")
print(f"User ID: {context.get('user_id')}")
print(f"Command: {context.get('command')}")

# קבלת request_id בלבד
request_id = get_request_id(default="unknown")
```

### 17.2 Binding User Context

**למה זה שימושי:** קישור מידע משתמש ללוגים.

```python
from observability import bind_user_context, bind_command

async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # קישור פרטי משתמש
    bind_user_context(
        user_id=update.effective_user.id,
        chat_id=update.effective_chat.id
    )
    
    # קישור פקודה
    bind_command(update.message.text)
    
    # כל הלוגים מעכשיו יכללו את המידע הזה
    emit_event("processing_command", severity="info")
```

---

## 18. Error Classification

### 18.1 סיווג שגיאה לפי Signature

**למה זה שימושי:** זיהוי אוטומטי של סוג השגיאה.

```python
from observability import classify_error

# סיווג שגיאה
error_text = "Connection timeout after 30 seconds"
match = classify_error({"error": error_text, "operation": "fetch_data"})

if match:
    print(f"Category: {match.category}")
    print(f"Severity: {match.severity}")
    print(f"Summary: {match.summary}")
    print(f"Policy: {match.policy}")
else:
    print("No matching error signature found")
```

---

## 19. HTTP Requests עם Tracing

### 19.1 Request עם Headers אוטומטיים

**למה זה שימושי:** מעקב end-to-end בין שירותים.

```python
from observability import prepare_outgoing_headers
import aiohttp

async def fetch_from_service(url: str, data: dict = None):
    """קריאת HTTP עם tracing headers"""
    # הכנת headers עם request_id ו-trace context
    headers = prepare_outgoing_headers({
        "Content-Type": "application/json",
        "User-Agent": "CodeBot/1.0"
    })
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as response:
            if response.status != 200:
                emit_event(
                    "external_api_error",
                    severity="error",
                    status_code=response.status,
                    url=url
                )
                return None
            
            return await response.json()
```

---

## 20. Code Normalization

### 20.1 נרמול קוד לפני שמירה

**למה זה שימושי:** הסרת תווים נסתרים ותקינה של formatting.

```python
def normalize_code(text: str,
                   strip_bom: bool = True,
                   normalize_newlines: bool = True,
                   remove_zero_width: bool = True) -> str:
    """נרמול קוד לפני שמירה"""
    if not isinstance(text, str):
        return text or ""
    
    out = text
    
    # הסרת BOM בתחילת הטקסט
    if strip_bom and out.startswith("\ufeff"):
        out = out.lstrip("\ufeff")
    
    # נרמול שורות חדשות ל-LF
    if normalize_newlines:
        out = out.replace("\r\n", "\n").replace("\r", "\n")
    
    # הסרת תווי zero-width
    if remove_zero_width:
        zero_width_chars = {"\u200B", "\u200C", "\u200D", "\u2060", "\uFEFF"}
        out = "".join(ch for ch in out if ch not in zero_width_chars)
    
    # הסרת רווחים בסוף שורות
    out = "\n".join(line.rstrip() for line in out.split("\n"))
    
    return out

# שימוש
clean_code = normalize_code(user_input)
db.save_file(user_id, file_name, clean_code, language)
```

---

## 🎯 דוגמאות שילוב

### דוגמה מלאה: טיפול בשמירת קובץ

```python
from observability import generate_request_id, bind_request_id, emit_event, bind_user_context
from utils import normalize_code, escape_markdown

async def handle_save_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול מלא בשמירת קובץ"""
    # 1. Setup observability
    request_id = generate_request_id()
    bind_request_id(request_id)
    bind_user_context(user_id=update.effective_user.id)
    
    # 2. חסימת לחיצות כפולות
    if CallbackQueryGuard.should_block(update, context):
        return
    
    # 3. קבלת נתונים
    user_id = update.effective_user.id
    file_name = context.user_data.get('pending_filename')
    code = update.message.text
    
    # 4. ולידציה
    is_valid, message = await validate_filename(file_name)
    if not is_valid:
        await update.message.reply_text(message)
        emit_event("save_file_validation_failed", severity="warning", reason=message)
        return
    
    # 5. נרמול קוד
    clean_code = normalize_code(code)
    
    # 6. שמירה עם retry
    try:
        result = await retry_async(
            db.save_file,
            max_attempts=3,
            user_id=user_id,
            file_name=file_name,
            code=clean_code,
            programming_language="python"
        )
        
        # 7. הצלחה
        safe_filename = escape_markdown(file_name, version=2)
        await update.message.reply_text(
            f"✅ הקובץ {safe_filename} נשמר בהצלחה!",
            parse_mode="MarkdownV2"
        )
        
        emit_event("file_saved", severity="info", file_name=file_name)
        
    except Exception as e:
        # 8. טיפול בשגיאה
        await update.message.reply_text(
            "⚠️ אופס! משהו השתבש בשמירה.\nנסה שוב בעוד רגע."
        )
        
        emit_event(
            "file_save_failed",
            severity="error",
            error=str(e),
            error_type=type(e).__name__,
            file_name=file_name
        )
```

---

## 📝 הערות לסיום

1. **כל הסניפטים נלקחו מקוד אמיתי עובד** במערכת CodeBot.
2. **התאם לצרכים שלך:** שנה פרמטרים, הוסף לוגיקה, התאם למקרה השימוש.
3. **בדוק תמיד:** כל סניפט צריך טסטים לפני production.
4. **תיעוד:** הוסף הערות והסברים בקוד שלך.
5. **אבטחה:** אל תשכח ולידציה, sanitization ו-error handling.

---

**עדכון אחרון:** 2025-11-06  
**גרסה:** 1.0  
**רישיון:** MIT (לשימוש חופשי)

להצעות ושיפורים, פנה למפתח הראשי של הפרויקט.
