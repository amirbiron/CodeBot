# 🔄 תוכנית Refactoring - פירוק main.py

## 📊 מצב נוכחי
- `main.py`: **2,322 שורות** (!)
- אחריות מרובה: initialization, handlers, middleware, business logic
- קשה לתחזוקה ולטסטים

---

## 🎯 מטרה
פירוק ל-6 מודולים ברורים, כל אחד עד 400 שורות.

---

## 📁 מבנה מוצע

```
src/
├── core/
│   ├── __init__.py
│   ├── application.py       # ← אתחול Application, 150 שורות
│   ├── middleware.py         # ← Guards, logging, maintenance, 200 שורות
│   └── lock_manager.py       # ← MongoDB lock logic, 150 שורות
├── handlers/
│   ├── __init__.py
│   ├── commands.py           # ← /start, /help, /save, /list, 250 שורות
│   ├── documents.py          # ← Document handler logic, 350 שורות
│   ├── messages.py           # ← Text/code message handlers, 200 שורות
│   └── inline_query.py       # ← Inline mode handlers, 150 שורות
└── utils/
    ├── __init__.py
    ├── admin.py              # ← notify_admins, get_admin_ids, 100 שורות
    └── helpers.py            # ← Misc utilities, 100 שורות
```

---

## 🔧 שלבי ביצוע

### Phase 1: Extraction (שבוע 1)
1. **יצירת `core/lock_manager.py`**
   - העבר את `manage_mongo_lock()`, `cleanup_mongo_lock()`, `ensure_lock_indexes()`
   - ~200 שורות
   
2. **יצירת `core/middleware.py`**
   - העבר את `_global_callback_guard`
   - העבר את `log_user_activity`
   - העבר את maintenance mode logic
   - ~250 שורות

3. **יצירת `utils/admin.py`**
   - `get_admin_ids()`
   - `notify_admins()`
   - ~80 שורות

### Phase 2: Handler Separation (שבוע 2)
4. **יצירת `handlers/commands.py`**
   ```python
   class CommandHandlers:
       def __init__(self, application):
           self.app = application
       
       async def start_command(self, update, context): ...
       async def help_command(self, update, context): ...
       async def save_command(self, update, context): ...
       async def list_command(self, update, context): ...
       async def search_command(self, update, context): ...
       async def stats_command(self, update, context): ...
   ```

5. **יצירת `handlers/documents.py`**
   - העבר את כל לוגיקת `handle_document()` (600+ שורות!)
   - פצל לפונקציות עזר קטנות יותר

6. **יצירת `handlers/messages.py`**
   - `handle_text_message()`
   - `_save_code_snippet()`
   - `_looks_like_code()`
   - `_detect_language()`

### Phase 3: Clean Application (שבוע 3)
7. **יצירת `core/application.py`**
   ```python
   class CodeKeeperBot:
       def __init__(self):
           self.app = self._create_application()
           self.lock_manager = LockManager()
       
       def _create_application(self): ...
       def setup_handlers(self): ...
       async def run(self): ...
   ```

8. **עדכון `main.py` להיות רק entry point**
   ```python
   # main.py - NEW (50 שורות!)
   #!/usr/bin/env python3
   import asyncio
   from core.application import CodeKeeperBot
   
   if __name__ == '__main__':
       bot = CodeKeeperBot()
       asyncio.run(bot.run())
   ```

---

## ✅ יתרונות

### Maintainability
- קל למצוא קוד רלוונטי
- כל מודול עם אחריות ברורה
- פחות merge conflicts

### Testability  
- ניתן לטסט כל handler בנפרד
- Mocking קל יותר
- הפרדת concerns

### Performance
- Lazy loading אפשרי
- Import times מהירים יותר
- Memory footprint קטן יותר

### Team Work
- אפשר לעבוד על מודולים שונים במקביל
- Code reviews ממוקדים יותר
- אונבורדינג מהיר יותר

---

## 🧪 תוכנית טסטים

לכל מודול חדש:
```python
# tests/core/test_lock_manager.py
def test_acquire_lock_success(): ...
def test_acquire_lock_already_held(): ...
def test_cleanup_lock(): ...

# tests/handlers/test_commands.py
async def test_start_command(): ...
async def test_help_command_pagination(): ...
```

---

## 📋 Checklist לפני Refactoring

- [ ] יצירת branch: `refactor/split-main-py`
- [ ] הרצת כל הטסטים - וידוא שהכל ירוק ✅
- [ ] יצירת baseline coverage report
- [ ] תיעוד API הנוכחי
- [ ] הודעה לצוות על שינויים צפויים

---

## 🚦 Rollback Plan

אם משהו משתבש:
1. Git revert לקומיט הקודם
2. או: הפעל את `main.py` הישן מ-branch `main`
3. Hotfix במקרה הצורך

---

## 📈 מדדי הצלחה

- [ ] `main.py` < 200 שורות
- [ ] כל מודול חדש < 400 שורות
- [ ] כיסוי טסטים נשאר > 80%
- [ ] כל הטסטים עוברים
- [ ] CI/CD ירוק
- [ ] אין regression bugs לאחר שבועיים

---

## 🎓 למידה

תיעוד patterns ששימשו:
- Strategy Pattern (handlers)
- Facade Pattern (Application wrapper)
- Singleton Pattern (lock manager)

**Reference**: Clean Code (Robert Martin), Chapter 3 - Functions should do one thing
