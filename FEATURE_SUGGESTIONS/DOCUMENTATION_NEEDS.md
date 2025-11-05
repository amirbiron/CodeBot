# 📚 צרכי תיעוד - CodeBot & WebApp

> **מטרה:** לסכם מה קריטי להוסיף לאתר התיעוד ([https://amirbiron.github.io/CodeBot/](https://amirbiron.github.io/CodeBot/)) כדי לעזור למפתחים ולסוכני AI בעבודה על הריפו.

**תאריך יצירה:** 2025-10-10  
**סטטוס:** ממתין למימוש

---

## 📋 תוכן עניינים

- [חסרים קריטיים (עדיפות גבוהה)](#-חסרים-קריטיים-עדיפות-גבוהה)
- [חסרים חשובים (עדיפות בינונית)](#-חסרים-חשובים-עדיפות-בינונית)
- [רצוי להוסיף (עדיפות נמוכה)](#-רצוי-להוסיף-עדיפות-נמוכה)
- [המלצות יישום מיידיות](#-המלצות-יישום-מיידיות)
- [טיפ חשוב לסוכני AI](#-טיפ-חשוב-לסוכני-ai)

---

## ⚠️ חסרים קריטיים (עדיפות גבוהה)

### 1. 🚀 Quickstart כפול - מפתחים וסוכני AI (חדש!)

**למה זה קריטי:**
- **נקודת כניסה מהירה** - צריך לזרז את ההתחלה
- **שני קהלי יעד שונים** - מפתחים אנושיים vs. סוכני AI
- צריך להיות עמוד ראשון שכולם רואים

#### א. Quickstart למפתחים (3 צעדים)

```markdown
# 🚀 התחלה מהירה - מפתחים

## שלב 1: התקנה
```bash
git clone https://github.com/amirbiron/CodeBot.git
cd CodeBot
pip install -r requirements.txt
```

## שלב 2: הגדרת .env
```bash
cp .env.example .env
# ערוך .env והוסף:
# - BOT_TOKEN (מ-BotFather)
# - MONGODB_URL (מקומי או Atlas)
```

## שלב 3: הרצה
```bash
# הרצת הבוט
python main.py

# הרצת WebApp (בטרמינל נפרד)
cd webapp && python app.py
```

## ✅ מה הלאה?
- [ארכיטקטורה](architecture.html) - הבן את המערכת
- [תרומה](contributing.html) - כתוב קוד
- [טסטים](testing.html) - הרץ בדיקות
```

#### ב. Quickstart לסוכני AI (קריטי!)

**מה להוסיף:**

```markdown
# 🤖 התחלה מהירה - סוכני AI

ברוך הבא! אתה עובד על CodeBot - בוט Telegram לניהול קוד.

## 🎯 עקרונות עבודה קריטיים

### ❌ מה אסור לעשות
- **ללא sudo** - אף פעם
- **ללא תהליכים ארוכי-חיים** - לא `npm run dev`, `watch`, background processes
- **ללא פקודות אינטראקטיביות** - לא `git rebase -i`, `git add -i`
- **ללא שינוי git config** - אף פעם
- **ללא דחיפה לremote** - אלא אם התבקשת מפורשות

### ✅ מה מותר ומומלץ
- **כלי קריאה מאושרים:** Read, LS, Grep, Glob
- **ללא grep/find/cat גולמי** - השתמש בכלים המובנים
- **עבודה בנתיבים מוחלטים** - תמיד
- **IO רק ב-/tmp** - בטסטים ובפיתוח
- **עריכות נקודתיות** - שמור סגנון קיים

## 📝 פורמטי ציטוט קוד

### קוד קיים - השתמש ב-CODE REFERENCE:
\`\`\`12:15:app/components/Todo.tsx
export const Todo = () => {
  return <div>Todo</div>;
};
\`\`\`

### קוד חדש/מוצע - Markdown code block רגיל:
\`\`\`bash
gh pr create --title "feat: add X" --body "Why and test plan"
\`\`\`

## 🔧 עבודה עם קבצים

### קריאה
\`\`\`python
# ✅ נכון
Read("path/to/file.py")

# ❌ לא נכון
cat path/to/file.py
\`\`\`

### חיפוש
\`\`\`python
# ✅ נכון
Grep(pattern="function.*hello", type="py")

# ❌ לא נכון
grep -r "function.*hello" .
\`\`\`

### מחיקה בטוחה (רק ב-tmp!)
\`\`\`python
from pathlib import Path
import shutil

def safe_rmtree(path: Path, allow_under: Path) -> None:
    p = path.resolve()
    base = allow_under.resolve()
    if not str(p).startswith(str(base)) or p in (Path('/'), base.parent, Path.cwd()):
        raise RuntimeError(f"Refusing to delete unsafe path: {p}")
    shutil.rmtree(p)

# שימוש:
safe_rmtree(Path("/tmp/test"), allow_under=Path("/tmp"))
\`\`\`

## 🎫 קומיטים ו-PR

### פורמט קומיט (HEREDOC)
\`\`\`bash
git commit -m "$(cat <<'EOF'
feat: add user authentication

- Implement JWT tokens
- Add login/logout endpoints
- Update tests

EOF
)"
\`\`\`

### לפני קומיט - בדוק:
- [ ] אין סודות/טוקנים בקוד
- [ ] אין PII בלוגים
- [ ] Conventional Commit format
- [ ] טסטים עוברים

### צ'קליסט PR:
- [ ] What/Why/Tests מפורט
- [ ] קישור ל-[CodeBot Docs](https://amirbiron.github.io/CodeBot/)
- [ ] תכנית Rollback
- [ ] CI ירוק (3 סטטוסים)

## 🧪 טסטים

### הרצה
\`\`\`bash
# כל הטסטים
pytest

# ספציפי
pytest tests/test_bot_handlers.py -v

# עם coverage
pytest --cov=. --cov-report=html
\`\`\`

### עבודה ב-tmp בלבד
\`\`\`python
def test_file_operations(tmp_path):
    # ✅ נכון - עובד ב-tmp_path
    test_file = tmp_path / "test.py"
    test_file.write_text("print('hello')")
    
    # ❌ לא נכון - עובד בroot
    # Path("test.py").write_text("print('hello')")
\`\`\`

## 📊 CI - סטטוסים נדרשים

חייבים לעבור:
- ✅ 🔍 Code Quality & Security
- ✅ Unit Tests (3.11)
- ✅ Unit Tests (3.12)

## 🗺️ ניווט במערכת

\`\`\`
handlers/        → Telegram handlers
services/        → Business logic
database/        → MongoDB models
webapp/          → Flask web app
tests/          → All tests
\`\`\`

## 📚 קישורים חשובים

- [ארכיטקטורה](architecture.html) - מפת המערכת
- [Database Schema](database-schema.html) - מבנה נתונים
- [הנחיות מלאות](ai-guidelines.html) - כללים מפורטים
- [מדיניות](https://amirbiron.github.io/CodeBot/) - Project Docs
```

**מיקום מוצע:** 
- `docs/quickstart.rst` (למפתחים)
- `docs/quickstart-ai.rst` (לסוכני AI)
- **לשים קישורים בולטים ל-2 הדפים האלה בראש `docs/index.rst`**

---

### 2. 🤖 עמוד "הנחיות לסוכני AI" מפורט (חדש - קריטי!)

**למה זה קריטי:**
- **סוכני AI צריכים כללים ברורים** - אחרת הם עלולים לפגוע
- **מניעת תקלות** - שגיאות נפוצות שסוכנים עושים
- **אכיפה** - מה מותר ומה אסור

**מה להוסיף:**

```markdown
# 🤖 הנחיות לסוכני AI - מדריך מלא

## 🚨 מגבלות קריטיות

### הרצת פקודות

**אסור בהחלט:**
```bash
# ❌ sudo - אף פעם
sudo apt install something

# ❌ תהליכים ארוכי-חיים
npm run dev
python manage.py runserver
watch -n 1 "pytest"

# ❌ פקודות אינטראקטיביות
git rebase -i
git add -i
nano file.txt

# ❌ שינוי git config
git config user.email "..."
git config --global ...

# ❌ פעולות git מסוכנות (אלא אם נתבקש מפורשות)
git push
git push --force
git clean -fdx
git reset --hard
```

**מותר ומומלץ:**
```bash
# ✅ טסטים
pytest
pytest tests/test_file.py -v

# ✅ linting
black --check .
mypy .

# ✅ בדיקות
python -c "import sys; print(sys.version)"
```

---

### כלי קבצים מאושרים

**השתמש בכלים המובנים:**
```python
# ✅ קריאה
Read(path="file.py")

# ✅ רשימת קבצים
LS(target_directory=".")

# ✅ חיפוש בקבצים
Grep(pattern="def.*hello", type="py")

# ✅ מציאת קבצים
Glob(glob_pattern="*.py")
```

**אל תשתמש בפקודות גולמיות:**
```bash
# ❌ אל תשתמש
cat file.py
ls -la
find . -name "*.py"
grep -r "pattern" .
head -n 10 file.py
tail -f log.txt
```

---

## 📝 עריכת קוד

### עקרונות

1. **עריכות נקודתיות** - שנה רק מה שצריך
2. **שמור סגנון** - הסתכל על הקוד הקיים והמשך את אותו סגנון
3. **ללא הערות מיותרות** - אל תוסיף `# TODO: implement later`
4. **guard clauses** - מותר להעדיף על פני if-else מקוננים
5. **ללא try/except מיותר** - רק אם באמת צריך לטפל בשגיאה

### דוגמה - עריכה טובה

**לפני:**
```python
def process_file(filename):
    data = read_file(filename)
    result = process_data(data)
    return result
```

**עריכה טובה:**
```python
def process_file(filename):
    """Process a file and return results.
    
    Args:
        filename: Path to file
        
    Returns:
        Processed data
    """
    data = read_file(filename)
    result = process_data(data)
    return result
```

**עריכה רעה:**
```python
def process_file(filename):
    # TODO: add validation
    # TODO: add error handling
    # FIXME: this is slow
    try:  # מיותר!
        data = read_file(filename)  # קוראים את הקובץ
        result = process_data(data)  # מעבדים את הדאטה
        return result  # מחזירים תוצאה
    except Exception as e:
        # TODO: handle this better
        raise  # למה try/except אם רק raise?
```

---

## 🎫 קומיטים ו-Pull Requests

### פורמט קומיט

**תמיד השתמש ב-HEREDOC:**
```bash
git commit -m "$(cat <<'EOF'
feat: add user authentication

- Implement JWT token generation
- Add login/logout endpoints  
- Update database schema
- Add integration tests

Related: #123
EOF
)"
```

**אל תשתמש:**
```bash
# ❌ רע - בעיות עם שורות חדשות
git commit -m "feat: add user authentication
- Implement JWT tokens
- Add endpoints"
```

### Conventional Commits

| Type | תיאור | דוגמה |
|------|--------|--------|
| `feat` | פיצ'ר חדש | `feat: add bookmarks feature` |
| `fix` | תיקון באג | `fix: resolve memory leak in cache` |
| `docs` | תיעוד | `docs: update API reference` |
| `test` | טסטים | `test: add tests for auth flow` |
| `refactor` | רפקטור | `refactor: simplify error handling` |
| `chore` | תחזוקה | `chore: update dependencies` |
| `perf` | ביצועים | `perf: optimize database queries` |

### לפני קומיט - checklist

```bash
# בדוק סודות
git diff | grep -i "token\|password\|secret\|api_key"

# בדוק PII
git diff | grep -i "email\|phone\|address"

# הרץ טסטים
pytest

# בדוק linting
black --check .
```

### תבנית PR

```markdown
## What
תיאור קצר של השינוי

## Why
למה צריך את זה?

## Tests
- [ ] Unit tests עוברים
- [ ] Integration tests עוברים
- [ ] בדקתי ידנית

## Rollback Plan
איך לחזור אחורה אם משהו נשבר?

## Docs
- [ ] עדכנתי תיעוד
- [ ] קראתי את [CodeBot Docs](https://amirbiron.github.io/CodeBot/)
```

---

## 📊 פורמטי ציטוט קוד

### קוד קיים במערכת

השתמש ב-**CODE REFERENCE** עם מספרי שורות:

\`\`\`12:15:app/components/Todo.tsx
export const Todo = () => {
  return <div>Todo</div>;
};
\`\`\`

**פורמט:** \`\`\`startLine:endLine:filepath

### קוד חדש/מוצע

השתמש ב-Markdown code block רגיל:

\`\`\`python
def new_function():
    """New function to implement."""
    pass
\`\`\`

---

## 🧪 עבודה עם טסטים

### עבודה רק ב-tmp

**חובה:**
```python
import pytest
from pathlib import Path

def test_file_operations(tmp_path):
    # ✅ נכון - כל IO ב-tmp_path
    test_file = tmp_path / "test.py"
    test_file.write_text("code")
    
    result = process_file(test_file)
    
    assert result == expected
```

**אסור:**
```python
def test_file_operations():
    # ❌ לא נכון - יוצר קבצים בroot!
    Path("test.py").write_text("code")
    result = process_file("test.py")
    Path("test.py").unlink()  # מסוכן!
```

### מחיקה בטוחה

```python
from pathlib import Path
import shutil

def safe_rmtree(path: Path, allow_under: Path) -> None:
    """Delete directory safely - only under allowed path."""
    p = path.resolve()
    base = allow_under.resolve()
    
    # Block dangerous paths
    dangerous = [Path('/'), base.parent, Path.cwd()]
    if p in dangerous:
        raise RuntimeError(f"Refusing to delete: {p}")
    
    # Block paths outside allowlist
    if not str(p).startswith(str(base)):
        raise RuntimeError(f"Path {p} not under {base}")
    
    shutil.rmtree(p)

# שימוש
safe_rmtree(Path("/tmp/test-data"), allow_under=Path("/tmp"))
```

---

## 🚫 מדיניות CI

### חוקים קשיחים

1. **אין git clean/reset ב-CI** - מסוכן למערכת
2. **עבודה רק על tmp** - לא ב-workspace
3. **אין sudo ב-CI** - אף פעם
4. **בידוד טסטים** - כל טסט ב-tmp_path נפרד

### סטטוסים נדרשים

חייב לעבור **בדיוק 3**:
- ✅ 🔍 Code Quality & Security
- ✅ Unit Tests (3.11)
- ✅ Unit Tests (3.12)

אם אחד נכשל - **ה-PR לא יעבור**.

---

## 📱 Telegram Bot - תקלות נפוצות

### "Message is not modified"

**הבעיה:** ניסיון לערוך הודעה עם אותו תוכן

**הפתרון:**
```python
import telegram.error

async def safe_edit(query, text, reply_markup=None, parse_mode=None):
    """Edit message safely - ignore 'not modified' error."""
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except telegram.error.BadRequest as e:
        if "message is not modified" in str(e).lower():
            return  # Ignore - message unchanged
        raise  # Re-raise other errors
```

**חובה לפני עריכה:**
```python
await query.answer()  # תמיד קודם!
await safe_edit(query, text, markup)
```

---

## 🔒 סודות ופרטיות

### אל תרשום בלוגים

```python
# ❌ רע
logger.info(f"User token: {token}")
logger.debug(f"Password: {password}")
logger.info(f"Email: {user.email}")

# ✅ טוב
logger.info("User authenticated")
logger.debug("Credentials validated")
logger.info(f"User ID: {user.id}")
```

### אל תקומיט

```python
# ❌ אל תקומיט
BOT_TOKEN = "123456:ABC-DEF..."
API_KEY = "sk-proj-..."
PASSWORD = "mypassword"

# ✅ תמיד מ-ENV
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
PASSWORD = os.getenv("PASSWORD")
```

---

## 📚 קישורים מהירים

- [Quickstart למפתחים](quickstart.html)
- [ארכיטקטורה](architecture.html)
- [Database Schema](database-schema.html)
- [Contributing](contributing.html)
- [Testing](testing.html)
- [מדיניות מלאה](https://amirbiron.github.io/CodeBot/)
```

**מיקום מוצע:** `docs/ai-guidelines.rst`

---

### 3. 🤝 מדריך תרומה למפתחים (CONTRIBUTING.md)

**למה זה חשוב:**
- סוכני AI צריכים להבין את תהליך הפיתוח
- מפתחים חדשים צריכים נקודת כניסה ברורה
- תקנים עקביים לקוד

**מה להוסיף:**
- ✅ כללי קוד (code style, PEP 8, type hints)
- ✅ **סגנון קוד:** עקרונות שמות, מבני קבצים, guard clauses
- ✅ תהליך PR (branch naming, commit messages, review process)
- ✅ **Conventional Commits:** קטגוריות ודוגמאות
- ✅ הרצת טסטים (pytest, coverage, linting)
- ✅ **נתיבי tmp:** חובה לעבוד רק ב-tmp בטסטים
- ✅ הגדרת סביבת פיתוח מקומית
- ✅ דוגמאות לתרומות טובות
- ✅ checklist לפני שליחת PR
- ✅ **.env.example מלא** - ללא ערכים אמיתיים

**מיקום מוצע:** `docs/contributing.rst`

---

### 2. 🏗️ ארכיטקטורה ומבנה הפרויקט (ARCHITECTURE.md)

**למה זה חשוב:**
- הבנה מהירה של המערכת כולה
- מפת דרכים למציאת קוד רלוונטי
- החלטות עיצוב והיגיון
- **קריטי להבנת איך Bot ו-WebApp מתקשרים**

**מה להוסיף:**
- ✅ תרשים ארכיטקטורה (Bot → MongoDB ← WebApp)
- ✅ זרימת נתונים (data flow)
- ✅ רכיבים עיקריים והאחריות שלהם
- ✅ דפוסי עיצוב בשימוש (patterns)
- ✅ החלטות טכניות מרכזיות (למה MongoDB? למה Telegram Bot API?)
- ✅ מבנה תיקיות מפורט והתפקיד של כל מודול
- ✅ קשרים בין מודולים
- ✅ **מה הקשר בין הבוט ל-WebApp** (חולקים MongoDB, אימות משותף)
- ✅ **איך המרכיבים מתקשרים** (handlers → services → database)

**דוגמה למה שצריך:**
```
┌──────────────┐              ┌──────────────┐
│   Telegram   │              │   WebApp     │
│     Bot      │              │  (Flask)     │
└──────┬───────┘              └──────┬───────┘
       │                             │
       │  ┌────────────────────────┐ │
       └──┤   Shared MongoDB       ├─┘
          │   - code_snippets      │
          │   - users              │
          │   - bookmarks          │
          │   - sessions           │
          └────────────────────────┘

Bot Flow:
┌─────────────┐
│   Telegram  │
│   Updates   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Handlers   │
│ bot_handlers│
│conversation │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Services   │
│ github,     │
│ backup,code │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Database   │
│  Manager    │
└─────────────┘
```

**מיקום מוצע:** `docs/architecture.rst`

---

### 3. 🗄️ תיעוד Database Schema (חסר לגמרי!)

**למה זה חשוב:**
- **קריטי להבנת המערכת** - ללא זה לא יודעים איך הנתונים מאוחסנים
- מפתחים צריכים לדעת מה יש במסד הנתונים
- סוכני AI צריכים להבין את המבנה כדי לכתוב שאילתות נכון

**מה להוסיף:**

#### מבנה הקולקציות ב-MongoDB

**Collection: `code_snippets`**
```javascript
{
  _id: ObjectId("..."),
  user_id: 123456789,              // Telegram user ID
  file_name: "example.py",
  programming_language: "python",
  code: "def hello():\n    pass",
  note: "Example function",        // תיאור/הערה
  tags: ["python", "example"],
  created_at: ISODate("2025-10-10T10:30:00Z"),
  updated_at: ISODate("2025-10-10T10:30:00Z"),
  version: 1,
  is_deleted: false,
  file_size: 1234,                // bytes
  line_count: 10
}
```

**Collection: `users`**
```javascript
{
  _id: ObjectId("..."),
  user_id: 123456789,              // Telegram user ID (unique)
  username: "john_doe",
  first_name: "John",
  last_name: "Doe",
  created_at: ISODate("2025-01-01T00:00:00Z"),
  last_active: ISODate("2025-10-10T10:30:00Z"),
  settings: {
    language: "he",
    notifications: true
  },
  stats: {
    total_files: 156,
    total_searches: 45
  }
}
```

**Collection: `bookmarks`**
```javascript
{
  _id: ObjectId("..."),
  user_id: 123456789,
  file_id: ObjectId("..."),        // Reference to code_snippets
  bookmark_name: "Important code",
  created_at: ISODate("2025-10-10T10:30:00Z"),
  tags: ["important", "review"]
}
```

**Collection: `sessions` (WebApp)**
```javascript
{
  _id: "session_id_here",
  user_id: 123456789,
  created_at: ISODate("2025-10-10T10:30:00Z"),
  expires_at: ISODate("2025-10-11T10:30:00Z"),
  data: {
    // session data
  }
}
```

#### אינדקסים נדרשים

```javascript
// code_snippets
db.code_snippets.createIndex({ "user_id": 1, "created_at": -1 })
db.code_snippets.createIndex({ "programming_language": 1 })
db.code_snippets.createIndex({ "file_name": "text", "code": "text", "note": "text" })
db.code_snippets.createIndex({ "tags": 1 })
db.code_snippets.createIndex({ "is_deleted": 1 })

// users
db.users.createIndex({ "user_id": 1 }, { unique: true })
db.users.createIndex({ "username": 1 })

// bookmarks
db.bookmarks.createIndex({ "user_id": 1, "file_id": 1 })

// sessions
db.sessions.createIndex({ "expires_at": 1 }, { expireAfterSeconds: 0 })
```

#### קשרים בין קולקציות

```
users (user_id)
  ├─→ code_snippets (user_id)
  └─→ bookmarks (user_id)
          └─→ code_snippets (_id via file_id)
```

#### דוגמאות לשאילתות נפוצות

```javascript
// כל הקבצים של משתמש
db.code_snippets.find({ 
  user_id: 123456789, 
  is_deleted: false 
}).sort({ created_at: -1 })

// חיפוש בקוד
db.code_snippets.find({
  user_id: 123456789,
  $text: { $search: "function" }
})

// קבצים לפי שפה
db.code_snippets.find({
  user_id: 123456789,
  programming_language: "python"
})

// עם bookmarks
db.code_snippets.aggregate([
  { $match: { user_id: 123456789 } },
  { $lookup: {
      from: "bookmarks",
      localField: "_id",
      foreignField: "file_id",
      as: "bookmarks"
  }}
])
```

**מיקום מוצע:** `docs/database-schema.rst`

---

### 4. 🔄 State Machine & Conversation Handlers (חסר לגמרי!)

**למה זה חשוב:**
- הבוט משתמש ב-ConversationHandlers עם states מורכבים
- בלי תיעוד של ה-states אי אפשר להבין את הזרימה
- קריטי להוספת handlers חדשים

**מה להוסיף:**

#### רשימת כל ה-States

```python
# handlers/states.py
class States:
    # Save flow
    WAITING_FOR_CODE = 1
    WAITING_FOR_FILENAME = 2
    WAITING_FOR_NOTE = 3
    
    # Edit flow
    EDITING_CODE = 10
    EDITING_FILENAME = 11
    
    # GitHub flow
    GITHUB_MENU = 20
    GITHUB_REPO_SELECT = 21
    GITHUB_FILE_BROWSE = 22
    
    # Backup flow
    BACKUP_MENU = 30
    BACKUP_CONFIRM = 31
```

#### תרשים ConversationHandler - Save Flow

```mermaid
stateDiagram-v2
    [*] --> WAITING_FOR_FILENAME: /save
    WAITING_FOR_FILENAME --> WAITING_FOR_CODE: שם קובץ התקבל
    WAITING_FOR_CODE --> WAITING_FOR_NOTE: קוד התקבל
    WAITING_FOR_NOTE --> [*]: הערה התקבלה / דילוג
    
    WAITING_FOR_FILENAME --> [*]: /cancel
    WAITING_FOR_CODE --> [*]: /cancel
    WAITING_FOR_NOTE --> [*]: /cancel
```

#### תרשים ConversationHandler - GitHub Flow

```mermaid
stateDiagram-v2
    [*] --> GITHUB_MENU: /github
    GITHUB_MENU --> GITHUB_REPO_SELECT: "בחר ריפו"
    GITHUB_REPO_SELECT --> GITHUB_FILE_BROWSE: ריפו נבחר
    GITHUB_FILE_BROWSE --> GITHUB_FILE_BROWSE: ניווט בתיקיות
    GITHUB_FILE_BROWSE --> [*]: קובץ נשמר
    
    GITHUB_MENU --> [*]: חזרה
    GITHUB_REPO_SELECT --> GITHUB_MENU: חזרה
    GITHUB_FILE_BROWSE --> GITHUB_REPO_SELECT: חזרה
```

#### איך לנהל States מורכבים

```python
# דוגמה: conversation handler עם מספר states
save_conversation = ConversationHandler(
    entry_points=[CommandHandler('save', start_save)],
    states={
        WAITING_FOR_FILENAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_filename)
        ],
        WAITING_FOR_CODE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_code)
        ],
        WAITING_FOR_NOTE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_note),
            CallbackQueryHandler(skip_note, pattern='^skip_note$')
        ],
    },
    fallbacks=[CommandHandler('cancel', cancel)],
    name="save_conversation",
    persistent=True  # שמירת state בין הפעלות
)
```

#### Context Data Management

```python
# שמירת מידע בין states
async def receive_filename(update, context):
    filename = update.message.text
    context.user_data['filename'] = filename
    context.user_data['start_time'] = datetime.now()
    return WAITING_FOR_CODE

# שימוש במידע ב-state הבא
async def receive_code(update, context):
    code = update.message.text
    filename = context.user_data.get('filename')
    # ...
```

**מיקום מוצע:** `docs/conversation-handlers.rst`

---

### 5. 🧪 מדריך הרצת טסטים ו-CI/CD

**למה זה חשוב:**
- סוכני AI צריכים לדעת איך לוודא שהקוד שלהם עובד
- מפתחים צריכים להריץ טסטים לפני PR

**מה להוסיף:**

#### א. הרצת טסטים מקומית
```bash
# הרצת כל הטסטים
pytest

# הרצת טסט ספציפי
pytest tests/test_bot_handlers.py

# עם coverage
pytest --cov=. --cov-report=html

# הרצת linting
flake8 .
mypy .
black --check .
```

#### ב. הסבר על CI/CD Pipeline
- GitHub Actions workflows
- סטטוסי בדיקה נדרשים:
  - 🔍 Code Quality & Security
  - Unit Tests (3.11)
  - Unit Tests (3.12)
- איך לדבג כשלונות ב-CI

#### ג. כללים
- Coverage מינימלי: 80%
- כל PR חייב לעבור linting
- טסטים חייבים לעבור ב-2 גרסאות Python

#### ד. איך לכתוב טסטים חדשים
```python
# דוגמה לטסט handler
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_save_command():
    """Test the /save command handler."""
    update = create_mock_update()
    context = create_mock_context()
    
    result = await save_command(update, context)
    
    assert result == ConversationStates.WAITING_FOR_CODE
    assert context.bot.send_message.called
```

#### ה. Mocking של Telegram API (חשוב!)

**למה צריך mocking:**
- לא רוצים לשלוח הודעות אמיתיות בטסטים
- מהיר יותר מקריאות API אמיתיות
- לא תלוי ברשת

**דוגמאות למוקים:**
```python
from unittest.mock import AsyncMock, MagicMock
from telegram import Update, Message, User, Chat

def create_mock_update(text="test", user_id=123):
    """Create a mock Telegram Update."""
    update = MagicMock(spec=Update)
    update.effective_user = User(id=user_id, first_name="Test", is_bot=False)
    update.effective_chat = Chat(id=user_id, type="private")
    update.message = MagicMock(spec=Message)
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update

def create_mock_context():
    """Create a mock Context."""
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.user_data = {}
    context.chat_data = {}
    return context

# שימוש בטסטים
@pytest.mark.asyncio
async def test_start_command():
    update = create_mock_update(text="/start")
    context = create_mock_context()
    
    await start_command(update, context)
    
    # בדיקה שנשלחה הודעה
    update.message.reply_text.assert_called_once()
    args = update.message.reply_text.call_args
    assert "ברוך הבא" in args[0][0]
```

**מוק של MongoDB בטסטים:**
```python
import pytest
from mongomock import MongoClient

@pytest.fixture
def mock_db():
    """Create a mock MongoDB for tests."""
    client = MongoClient()
    db = client['test_db']
    yield db
    client.close()

async def test_save_to_database(mock_db):
    collection = mock_db['code_snippets']
    
    # שמירת מסמך
    result = collection.insert_one({
        "user_id": 123,
        "file_name": "test.py",
        "code": "print('hello')"
    })
    
    # בדיקה
    assert result.inserted_id is not None
    doc = collection.find_one({"user_id": 123})
    assert doc["file_name"] == "test.py"
```

**מיקום מוצע:** `docs/testing.rst` + `docs/ci-cd.rst`

---

### 4. 🌐 API Reference לWebApp

**למה זה חשוב:**
- התיעוד הקיים מתמקד בבוט, לא ב-webapp
- endpoints, authentication, response formats חסרים

**מה להוסיף:**

#### טבלת Endpoints מלאה

| Endpoint | Method | תיאור | דורש אימות | Request Body | Response |
|----------|--------|-------|-------------|--------------|----------|
| `/` | GET | דף הבית | ❌ | - | HTML |
| `/login` | GET | דף התחברות | ❌ | - | HTML |
| `/auth/telegram` | POST | אימות Telegram | ❌ | `{id, first_name, ...}` | `{success: true}` |
| `/logout` | GET | התנתקות | ✅ | - | Redirect |
| `/dashboard` | GET | דשבורד | ✅ | - | HTML |
| `/files` | GET | רשימת קבצים | ✅ | Query: `?search=...&lang=...` | HTML |
| `/file/<id>` | GET | צפייה בקובץ | ✅ | - | HTML |
| `/download/<id>` | GET | הורדת קובץ | ✅ | - | File Download |
| `/html/<id>` | GET | תצוגת HTML בטוחה | ✅ | - | HTML (iframe) |
| `/md/<id>` | GET | תצוגת Markdown | ✅ | - | HTML (rendered) |
| `/api/stats` | GET | סטטיסטיקות | ✅ | - | JSON |

#### Authentication Flow
```mermaid
sequenceDiagram
    User->>WebApp: GET /login
    WebApp->>User: Login page with Telegram Widget
    User->>Telegram: Click "Login"
    Telegram->>WebApp: POST /auth/telegram (user data + hash)
    WebApp->>WebApp: Verify hash with BOT_TOKEN
    WebApp->>User: Set session cookie
    User->>WebApp: GET /dashboard
    WebApp->>User: Dashboard (authenticated)
```

#### Response Schemas
```json
// GET /api/stats
{
  "total_files": 156,
  "languages": {
    "python": 45,
    "javascript": 32,
    "java": 20
  },
  "recent_files": [
    {
      "id": "507f1f77bcf86cd799439011",
      "file_name": "example.py",
      "language": "python",
      "created_at": "2025-10-10T10:30:00Z"
    }
  ]
}
```

#### Error Handling
```json
// 401 Unauthorized
{
  "error": "Authentication required",
  "redirect": "/login"
}

// 404 Not Found
{
  "error": "File not found",
  "file_id": "507f1f77bcf86cd799439011"
}

// 500 Internal Server Error
{
  "error": "Database connection failed",
  "details": "..."
}
```

**מיקום מוצע:** `docs/webapp/api-reference.rst`

---

### 5. 🔧 Environment Variables Reference מלא

**למה זה חשוב:**
- יש משתני סביבה פזורים במסמכים שונים
- צריך מקור אחד ומקיף

**מה להוסיף:**

#### טבלה מרכזית

| משתנה | תיאור | חובה | ברירת מחדל | דוגמה | רכיב |
|-------|--------|------|-------------|--------|------|
| `BOT_TOKEN` | טוקן הבוט מ-BotFather | ✅ | - | `123456:ABC-DEF...` | Bot |
| `MONGODB_URL` | חיבור ל-MongoDB | ✅ | - | `mongodb://localhost:27017` | Both |
| `DATABASE_NAME` | שם DB | ❌ | `code_keeper_bot` | `my_db` | Both |
| `SECRET_KEY` | מפתח הצפנה Flask | ✅ (WebApp) | - | `supersecretkey123` | WebApp |
| `BOT_USERNAME` | שם משתמש הבוט | ❌ | `my_code_keeper_bot` | `@MyBot` | Both |
| `GITHUB_TOKEN` | טוקן GitHub | ❌ | - | `ghp_xxx...` | Bot |
| `WEBAPP_URL` | כתובת WebApp | ❌ | `https://...onrender.com` | `https://my.app` | WebApp |
| `REDIS_URL` | חיבור ל-Redis (cache) | ❌ | - | `redis://localhost:6379` | Bot |
| `LOG_LEVEL` | רמת logging | ❌ | `INFO` | `DEBUG` | Both |
| `ENCRYPTION_KEY` | מפתח הצפנה נתונים | ❌ | - | `32-byte-key` | Both |
| `RATE_LIMIT_ENABLED` | הפעלת rate limiting | ❌ | `false` | `true` | Bot |
| `MAX_FILES_PER_USER` | מקסימום קבצים | ❌ | `1000` | `5000` | Bot |
| `BACKUP_ENABLED` | הפעלת גיבויים | ❌ | `false` | `true` | Bot |
| `UPTIME_PROVIDER` | ספק uptime monitoring | ❌ | - | `betteruptime` | WebApp |

#### דוגמאות לקונפיגורציות

**Development (מקומי):**
```env
BOT_TOKEN=your_bot_token_here
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=code_keeper_dev
LOG_LEVEL=DEBUG
```

**Staging:**
```env
BOT_TOKEN=staging_bot_token
MONGODB_URL=mongodb+srv://user:pass@cluster.mongodb.net
DATABASE_NAME=code_keeper_staging
LOG_LEVEL=INFO
REDIS_URL=redis://staging-redis:6379
```

**Production:**
```env
BOT_TOKEN=prod_bot_token
MONGODB_URL=mongodb+srv://user:pass@prod-cluster.mongodb.net
DATABASE_NAME=code_keeper_prod
LOG_LEVEL=WARNING
REDIS_URL=redis://prod-redis:6379
ENCRYPTION_KEY=your-32-byte-encryption-key
RATE_LIMIT_ENABLED=true
BACKUP_ENABLED=true
```

**מיקום מוצע:** `docs/environment-variables.rst`

---

## 🔧 חסרים חשובים (עדיפות בינונית)

### 6. 🛠️ Troubleshooting Guide מפורט

**מה להוסיף:**

#### שגיאות נפוצות ופתרונות

**שגיאה:** `ModuleNotFoundError: No module named 'telegram'`
```bash
# פתרון:
pip install -r requirements.txt
# או ספציפית:
pip install python-telegram-bot
```

**שגיאה:** `ServerSelectionTimeoutError: No servers available`
```bash
# פתרון:
# 1. בדוק ש-MongoDB רץ:
systemctl status mongodb
# 2. בדוק את ה-MONGODB_URL ב-.env
# 3. אם Atlas - בדוק Network Access (IP whitelist)
```

**שגיאה:** `Telegram API Error: Conflict: terminated by other getUpdates`
```bash
# פתרון:
# יש instance אחר של הבוט שרץ
pkill -f "python main.py"
# חכה 30 שניות ונסה שוב
```

**שגיאה:** `Message is not modified`
```python
# פתרון: השתמש ב-wrapper בטוח
async def safe_edit(query, text, reply_markup=None):
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    except telegram.error.BadRequest as e:
        if "message is not modified" in str(e).lower():
            return  # התעלם מהשגיאה
        raise
```

#### דיבוג

**הפעלת debug mode:**
```bash
LOG_LEVEL=DEBUG python main.py
```

**צפייה בלוגים:**
```bash
# ב-Render:
# Dashboard → Service → Logs → Live Logs

# מקומי:
tail -f bot.log
```

**בדיקת חיבור MongoDB:**
```python
python -c "from database.manager import DatabaseManager; db = DatabaseManager(); print('Connected!' if db.test_connection() else 'Failed')"
```

#### בעיות Deployment ב-Render

**הבוט נרדם (sleep mode):**
- Free plan: הבוט נרדם אחרי 15 דקות חוסר פעילות
- פתרון 1: שדרג ל-Starter Plan ($7/month)
- פתרון 2: שימוש ב-cron job לping כל 10 דקות

**בעיות זיכרון:**
- Free plan: 512MB RAM
- בדיקת שימוש זיכרון:
```python
import psutil
print(f"RAM: {psutil.virtual_memory().percent}%")
```

**מיקום מוצע:** `docs/troubleshooting.rst`

---

### 7. 🔄 מדריך Migration/Upgrade

**מה להוסיף:**
- איך לשדרג בין גרסאות
- breaking changes בכל גרסה
- database migrations (אם יש)
- backup לפני שדרוג
- rollback plan

**דוגמה:**
```markdown
## Upgrade from v1.0 to v2.0

### Breaking Changes
- Changed database schema for `code_snippets` collection
- New required environment variable: `ENCRYPTION_KEY`

### Migration Steps
1. Backup your database:
   ```bash
   mongodump --uri="$MONGODB_URL" --out=./backup
   ```

2. Update code:
   ```bash
   git pull origin main
   pip install -r requirements.txt --upgrade
   ```

3. Run migration script:
   ```bash
   python scripts/migrate_v1_to_v2.py
   ```

4. Test:
   ```bash
   pytest tests/
   ```

5. Deploy
```

**מיקום מוצע:** `docs/migration.rst`

---

### 8. 🔨 Development Workflow

**מה להוסיף:**

#### איך להוסיף handler חדש

```python
# 1. צור קובץ חדש: handlers/my_feature.py
from telegram import Update
from telegram.ext import ContextTypes

async def my_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mycommand."""
    await update.message.reply_text("Hello!")

# 2. הוסף ל-main.py:
from handlers.my_feature import my_command

app.add_handler(CommandHandler("mycommand", my_command))

# 3. כתוב טסט: tests/test_my_feature.py
@pytest.mark.asyncio
async def test_my_command():
    # ...
```

#### איך להוסיף endpoint ל-WebApp

```python
# 1. ב-webapp/app.py:
@app.route('/my-endpoint')
@login_required
def my_endpoint():
    return render_template('my_page.html')

# 2. צור template: webapp/templates/my_page.html
{% extends "base.html" %}
{% block content %}
  <h1>My Page</h1>
{% endblock %}

# 3. עדכן תיעוד API
```

#### איך לעדכן database schema

```python
# 1. עדכן model: database/models.py
class CodeSnippet:
    def __init__(self, new_field=None):
        self.new_field = new_field  # NEW

# 2. צור migration script
def migrate_add_new_field():
    db.code_snippets.update_many(
        {"new_field": {"$exists": False}},
        {"$set": {"new_field": None}}
    )

# 3. עדכן טסטים
```

**מיקום מוצע:** `docs/development.rst`

---

### 9. 🔒 Security Best Practices

**מה להוסיף:**
- איך לטפל בטוקנים (הצפנה, אחסון)
- encryption של נתונים רגישים
- rate limiting
- input validation
- **CSRF protection ב-WebApp** (חשוב!)
- הרשאות משתמש
- OWASP Top 10 considerations

**דוגמאות:**

#### Encryption של טוקנים
```python
from cryptography.fernet import Fernet

def encrypt_token(token: str, key: bytes) -> str:
    f = Fernet(key)
    return f.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str, key: bytes) -> str:
    f = Fernet(key)
    return f.decrypt(encrypted_token.encode()).decode()
```

#### Input Validation
```python
def validate_filename(filename: str) -> bool:
    if not filename or len(filename) > 255:
        return False
    # Block path traversal
    if '..' in filename or '/' in filename:
        return False
    # Block special characters
    if any(c in filename for c in ['<', '>', ':', '"', '|', '?', '*']):
        return False
    return True

def sanitize_code_input(code: str) -> str:
    """Remove potentially dangerous code patterns."""
    # Remove NULL bytes
    code = code.replace('\x00', '')
    # Limit size
    max_size = 1024 * 1024  # 1MB
    if len(code) > max_size:
        raise ValueError(f"Code too large: {len(code)} bytes")
    return code
```

#### Rate Limiting
```python
from functools import wraps
from time import time

def rate_limit(max_calls=10, period=60):
    calls = {}
    def decorator(func):
        @wraps(func)
        async def wrapper(update, context):
            user_id = update.effective_user.id
            now = time()
            if user_id not in calls:
                calls[user_id] = []
            calls[user_id] = [t for t in calls[user_id] if now - t < period]
            if len(calls[user_id]) >= max_calls:
                await update.message.reply_text("Too many requests!")
                return
            calls[user_id].append(now)
            return await func(update, context)
        return wrapper
    return decorator
```

#### CSRF Protection ב-WebApp (חשוב!)

**למה צריך CSRF protection:**
- מונע התקפות Cross-Site Request Forgery
- חיוני בטפסים ב-WebApp
- דרישה בסיסית לאבטחת web

**הטמעה עם Flask-WTF:**
```python
# webapp/app.py
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
csrf = CSRFProtect(app)

# בטפסים
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired

class CodeForm(FlaskForm):
    filename = StringField('File Name', validators=[DataRequired()])
    code = TextAreaField('Code', validators=[DataRequired()])

# ב-template
<!-- templates/upload.html -->
<form method="POST">
    {{ form.csrf_token }}
    {{ form.filename.label }} {{ form.filename() }}
    {{ form.code.label }} {{ form.code() }}
    <button type="submit">Save</button>
</form>

# ב-route
@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    form = CodeForm()
    if form.validate_on_submit():
        # CSRF verified automatically!
        save_code(form.filename.data, form.code.data)
    return render_template('upload.html', form=form)
```

**הגנה על API endpoints:**
```python
# For AJAX requests
@app.route('/api/save', methods=['POST'])
@login_required
def api_save():
    # Verify CSRF token from header
    token = request.headers.get('X-CSRF-Token')
    if not validate_csrf_token(token):
        abort(403)
    # Process request...
```

**JavaScript client:**
```javascript
// קבלת CSRF token
const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

// שימוש ב-AJAX
fetch('/api/save', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken
    },
    body: JSON.stringify(data)
});
```

**מיקום מוצע:** `docs/security.rst`

---

### 10. ⚡ Performance & Optimization Guide

**מה להוסיף:**

#### MongoDB Indexing
```javascript
// Recommended indexes
db.code_snippets.createIndex({"user_id": 1, "created_at": -1})
db.code_snippets.createIndex({"programming_language": 1})
db.code_snippets.createIndex({"file_name": "text", "code": "text"})

// Check index usage
db.code_snippets.find({user_id: 123}).explain("executionStats")
```

#### Caching Strategies
```python
# Redis cache for frequent queries
import redis
from functools import wraps

redis_client = redis.from_url(os.getenv('REDIS_URL'))

def cache_result(ttl=300):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = f"{func.__name__}:{args}:{kwargs}"
            cached = redis_client.get(key)
            if cached:
                return json.loads(cached)
            result = await func(*args, **kwargs)
            redis_client.setex(key, ttl, json.dumps(result))
            return result
        return wrapper
    return decorator
```

#### Batch Processing
```python
# Process multiple files at once
async def save_multiple_files(files: list):
    # Instead of N database calls:
    # for file in files:
    #     db.insert_one(file)
    
    # Do one bulk insert:
    db.insert_many(files)
```

#### Memory Optimization
```python
# Don't load all files into memory
# BAD:
files = list(db.find({}))  # Loads everything!

# GOOD:
for file in db.find({}).batch_size(100):  # Streams in batches
    process_file(file)
```

**מיקום מוצע:** `docs/performance.rst`

---

## 🔧 חסרים חשובים נוספים (עדיפות בינונית-גבוהה)

### 11. 🔗 תיעוד אינטגרציות מפורט

**למה זה חשוב:**
- הבוט משתלב עם GitHub, Google Drive, Telegram
- צריך הסבר מלא על OAuth flows והגדרות API

#### GitHub API

**מה להוסיף:**
- איך ליצור Personal Access Token
- הרשאות נדרשות (scopes)
- דוגמאות לכל פעולה (gist, repo browsing, file download)
- Rate limiting של GitHub

```python
# דוגמה: יצירת Gist
from github import Github

g = Github(github_token)
user = g.get_user()

gist = user.create_gist(
    public=False,
    files={
        "example.py": InputFileContent("print('hello')")
    },
    description="Code snippet from bot"
)

print(f"Gist URL: {gist.html_url}")
```

#### Google Drive API - OAuth Flow מלא

**למה זה חשוב:**
- OAuth2 מורכב ודורש הסבר צעד אחרי צעד
- צריך הגדרה ב-Google Cloud Console

**מה להוסיף:**

**שלב 1: הגדרת Google Cloud Project**
```
1. עבור ל-Google Cloud Console
2. צור פרויקט חדש
3. הפעל את Google Drive API
4. צור OAuth 2.0 credentials
5. הוסף redirect URI: http://localhost:5000/oauth2callback
6. שמור את CLIENT_ID ו-CLIENT_SECRET
```

**שלב 2: OAuth Flow**
```python
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

# 1. Initialize flow
flow = Flow.from_client_secrets_file(
    'credentials.json',
    scopes=['https://www.googleapis.com/auth/drive.file'],
    redirect_uri='http://localhost:5000/oauth2callback'
)

# 2. Generate authorization URL
authorization_url, state = flow.authorization_url(
    access_type='offline',
    include_granted_scopes='true'
)

# 3. Redirect user to authorization_url
# User authorizes and gets redirected back with code

# 4. Exchange code for credentials
flow.fetch_token(code=authorization_code)
credentials = flow.credentials

# 5. Use credentials
drive_service = build('drive', 'v3', credentials=credentials)

# 6. Upload file
file_metadata = {'name': 'code.py'}
media = MediaFileUpload('code.py', mimetype='text/plain')
file = drive_service.files().create(
    body=file_metadata,
    media_body=media,
    fields='id, webViewLink'
).execute()

print(f"File uploaded: {file.get('webViewLink')}")
```

**שלב 3: שמירת Credentials**
```python
# שמירה מוצפנת
from cryptography.fernet import Fernet

def save_credentials(user_id, credentials):
    encrypted = encrypt_token(
        credentials.to_json(),
        ENCRYPTION_KEY
    )
    db.users.update_one(
        {"user_id": user_id},
        {"$set": {"google_credentials": encrypted}}
    )

def load_credentials(user_id):
    user = db.users.find_one({"user_id": user_id})
    if user and 'google_credentials' in user:
        decrypted = decrypt_token(
            user['google_credentials'],
            ENCRYPTION_KEY
        )
        return Credentials.from_authorized_user_info(
            json.loads(decrypted)
        )
    return None
```

#### Telegram Bot API - Webhooks vs Polling

**למה זה חשוב:**
- שתי דרכים לקבל עדכונים מטלגרם
- צריך להבין מתי להשתמש בכל אחת

**Polling (ברירת מחדל):**
```python
# main.py
from telegram.ext import Application

app = Application.builder().token(BOT_TOKEN).build()

# Add handlers...

# Start polling
app.run_polling()
```

**יתרונות:**
- ✅ פשוט להגדרה
- ✅ עובד מכל סביבה (גם ללא IP ציבורי)
- ✅ מתאים לפיתוח מקומי

**חסרונות:**
- ❌ פחות יעיל (שאילתות תכופות)
- ❌ עלות רשת גבוהה יותר
- ❌ לא מומלץ ל-production בקנה מידה גדול

**Webhooks (מומלץ ל-production):**
```python
# main.py
from telegram.ext import Application

app = Application.builder().token(BOT_TOKEN).build()

# Add handlers...

# Start webhook
app.run_webhook(
    listen="0.0.0.0",
    port=8443,
    url_path="/webhook",
    webhook_url=f"https://your-domain.com/webhook"
)
```

**הגדרת Webhook ב-Telegram:**
```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
     -d "url=https://your-domain.com/webhook" \
     -d "max_connections=100" \
     -d "allowed_updates=[\"message\",\"callback_query\"]"

# בדיקת סטטוס
curl "https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo"
```

**יתרונות:**
- ✅ יעיל יותר (עדכונים מיידיים)
- ✅ פחות עומס על הרשת
- ✅ מומלץ ל-production

**חסרונות:**
- ❌ דורש HTTPS ו-IP ציבורי
- ❌ מורכב יותר להגדרה
- ❌ לא מתאים לפיתוח מקומי

**מיקום מוצע:** `docs/integrations.rst`

---

## 📝 רצוי להוסיף (עדיפות נמוכה)

### 12. 🚀 Quick Start Guide (עמוד אחד)

**למה זה חשוב:**
- מפתחים חדשים רוצים להתחיל מהר
- עמוד אחד עם הכל = אין תירוצים

**תוכן מוצע:**
```markdown
# Quick Start - CodeBot

## התקנה מהירה (5 דקות)

### 1. Clone & Install
```bash
git clone https://github.com/amirbiron/CodeBot.git
cd CodeBot
pip install -r requirements.txt
```

### 2. הגדרת .env
```bash
cp .env.example .env
nano .env  # הוסף BOT_TOKEN ו-MONGODB_URL
```

### 3. הרצה
```bash
python main.py
```

## טסטים מהירים
```bash
pytest tests/
```

## בעיות נפוצות
- MongoDB לא עובד? → `systemctl start mongodb`
- טוקן לא תקין? → בדוק ב-BotFather

## מה הלאה?
- [מדריך תרומה](contributing.html)
- [ארכיטקטורה](architecture.html)
- [API Reference](api/index.html)
```

**מיקום מוצע:** `docs/quickstart.rst`

---

### 13. 📡 Swagger/OpenAPI למפרט WebApp

**למה זה חשוב:**
- תיעוד אינטראקטיבי של ה-API
- אפשר לבדוק endpoints ישירות מהדפדפן
- יצירה אוטומטית של SDK clients

**הוספת Swagger לFlask:**
```python
# webapp/app.py
from flask_swagger_ui import get_swaggerui_blueprint

# Swagger UI
SWAGGER_URL = '/api/docs'
API_URL = '/static/swagger.json'

swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL,
    API_URL,
    config={'app_name': "CodeBot WebApp API"}
)

app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)
```

**קובץ swagger.json:**
```json
{
  "openapi": "3.0.0",
  "info": {
    "title": "CodeBot WebApp API",
    "version": "1.0.0"
  },
  "paths": {
    "/api/stats": {
      "get": {
        "summary": "Get user statistics",
        "security": [{"cookieAuth": []}],
        "responses": {
          "200": {
            "description": "Statistics object",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "total_files": {"type": "integer"},
                    "languages": {"type": "object"}
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

**אוטומציה עם flask-swagger:**
```python
from flask_swagger import swagger

@app.route('/api/swagger.json')
def swagger_spec():
    swag = swagger(app)
    swag['info']['version'] = "1.0.0"
    swag['info']['title'] = "CodeBot API"
    return jsonify(swag)
```

**מיקום מוצע:** `docs/swagger-setup.rst`

---

### 14. 📮 Postman Collection

**למה זה חשוב:**
- דוגמאות מוכנות לשימוש
- קל לבדוק API בלי לכתוב קוד
- שיתוף עם צוות

**יצירת Collection:**
```json
{
  "info": {
    "name": "CodeBot WebApp API",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "item": [
    {
      "name": "Auth",
      "item": [
        {
          "name": "Login with Telegram",
          "request": {
            "method": "POST",
            "header": [
              {"key": "Content-Type", "value": "application/json"}
            ],
            "body": {
              "mode": "raw",
              "raw": "{\n  \"id\": 123456789,\n  \"first_name\": \"John\",\n  \"hash\": \"...\"\n}"
            },
            "url": {
              "raw": "{{base_url}}/auth/telegram",
              "host": ["{{base_url}}"],
              "path": ["auth", "telegram"]
            }
          }
        }
      ]
    },
    {
      "name": "Files",
      "item": [
        {
          "name": "Get Statistics",
          "request": {
            "method": "GET",
            "url": {
              "raw": "{{base_url}}/api/stats",
              "host": ["{{base_url}}"],
              "path": ["api", "stats"]
            }
          }
        }
      ]
    }
  ],
  "variable": [
    {
      "key": "base_url",
      "value": "http://localhost:5000"
    }
  ]
}
```

**מיקום:** `docs/postman/CodeBot_API.postman_collection.json`

---

### 15. ❓ FAQ למפתחים

**שאלות נפוצות:**
- למה נבחרה MongoDB?
- איך עובד ה-state management ב-ConversationHandler?
- למה יש גם bot וגם webapp?
- איך לתרום תרגום לשפה חדשה?
- איך להוסיף שפת תכנות חדשה להדגשת syntax?

---

### 12. 📜 Code of Conduct

**תוכן:**
- התנהגות מצופה
- התנהגות אסורה
- תהליך דיווח על בעיות
- enforcement

---

### 13. 📅 Changelog מפורט

**פורמט:**
```markdown
## [2.0.0] - 2025-10-10

### Added
- WebApp with Telegram Login
- Markdown preview with KaTeX support
- Bookmarks feature

### Changed
- Improved database schema
- Updated to python-telegram-bot v20

### Fixed
- Memory leak in file processing
- Rate limiting bug

### Security
- Added encryption for GitHub tokens
```

---

### 14. 🗺️ Roadmap ציבורי

**מה לכלול:**
- פיצ'רים בפיתוח
- פיצ'רים מתוכננים
- רעיונות עתידיים
- timeline משוער

---

### 15. 📊 Sequence Diagrams לזרימות מרכזיות

**דוגמאות:**

**שמירת קובץ:**
```mermaid
sequenceDiagram
    User->>Bot: /save file.py
    Bot->>Handler: save_command()
    Handler->>User: "שלח את הקוד"
    User->>Bot: <code content>
    Bot->>Handler: handle_code()
    Handler->>CodeProcessor: process_code()
    CodeProcessor->>Handler: {language, highlighted}
    Handler->>Database: save_snippet()
    Database->>Handler: {id, success}
    Handler->>User: "נשמר בהצלחה!"
```

**GitHub Integration:**
```mermaid
sequenceDiagram
    User->>Bot: /share file.py → GitHub Gist
    Bot->>Handler: share_to_gist()
    Handler->>Database: get_file()
    Database->>Handler: file_data
    Handler->>GitHub API: create_gist()
    GitHub API->>Handler: gist_url
    Handler->>User: "שותף ב-Gist: <url>"
```

---

## 🎯 המלצות יישום מיידיות

### שלב 1: יצירת דפים חדשים ב-`docs/`

```
docs/
├── contributing.rst         # NEW - מדריך תרומה
├── architecture.rst         # NEW - ארכיטקטורה
├── testing.rst             # NEW - טסטים
├── ci-cd.rst              # NEW - CI/CD
├── troubleshooting.rst    # NEW - פתרון בעיות
├── development.rst        # NEW - תהליך פיתוח
├── security.rst           # NEW - אבטחה
├── performance.rst        # NEW - ביצועים
├── environment-variables.rst  # NEW - משתני סביבה
├── migration.rst          # NEW - שדרוגים
└── webapp/
    └── api-reference.rst  # NEW - API של webapp
```

### שלב 2: עדכון `docs/index.rst`

הוסף את הדפים החדשים ל-toctree:

```rst
.. Code Keeper Bot documentation master file

Code Keeper Bot - תיעוד API
============================

.. toctree::
   :maxdepth: 2
   :caption: מדריכים בסיסיים:

   installation
   configuration
   environment-variables

.. toctree::
   :maxdepth: 2
   :caption: למפתחים:
   
   contributing
   architecture
   development
   testing
   ci-cd
   troubleshooting
   security
   performance
   migration

.. toctree::
   :maxdepth: 2
   :caption: API Reference:
   
   api/index
   modules/index
   handlers/index
   services/index
   database/index

.. toctree::
   :maxdepth: 2
   :caption: WebApp:
   
   webapp/overview
   webapp/api-reference

.. toctree::
   :maxdepth: 2
   :caption: עזרה ודוגמאות:
   
   examples
   user/share_code
   user/github_browse
   user/download_repo
```

### שלב 3: קישור מ-README.md

הוסף סעיף בולט ב-README:

```markdown
## 📖 תיעוד למפתחים

מתכנן לתרום לפרויקט? התחל כאן:

- **[מדריך תרומה](https://amirbiron.github.io/CodeBot/contributing.html)** - איך לתרום קוד
- **[ארכיטקטורה](https://amirbiron.github.io/CodeBot/architecture.html)** - הבנת המערכת
- **[מדריך פיתוח](https://amirbiron.github.io/CodeBot/development.html)** - workflow יומיומי
- **[טסטים](https://amirbiron.github.io/CodeBot/testing.html)** - איך להריץ ולכתוב טסטים
- **[API Reference](https://amirbiron.github.io/CodeBot/api/index.html)** - תיעוד API מלא
```

### שלב 4: יצירת Templates

צור תבניות סטנדרטיות:

**`docs/_templates/module_template.rst`:**
```rst
Module Name
===========

תיאור כללי של המודול.

Overview
--------

מה המודול עושה?

Usage
-----

.. code-block:: python

   from module import MyClass
   
   obj = MyClass()
   obj.do_something()

API Reference
-------------

.. automodule:: module
   :members:
   :undoc-members:
   :show-inheritance:

Examples
--------

דוגמאות מעשיות.

See Also
--------

- :mod:`related_module`
- :doc:`../guides/related_guide`
```

---

## 💡 טיפ חשוב לסוכני AI

### צור קובץ `docs/ai-developer-guide.rst`

**תוכן מוצע:**

```rst
מדריך מהיר לסוכני AI ומפתחים
==============================

מסמך זה מספק סקירה מהירה למציאת מידע בפרויקט.

איפה למצוא מה?
---------------

**רוצה להוסיף פיצ'ר חדש?**
→ קרא: :doc:`development` → "Adding a new feature"

**רוצה לתקן באג?**
→ קרא: :doc:`troubleshooting` → מצא את השגיאה

**רוצה להבין את הארכיטקטורה?**
→ קרא: :doc:`architecture` → תרשימים וזרימות

**רוצה להריץ טסטים?**
→ קרא: :doc:`testing` → Quick Start

**רוצה לפרוס?**
→ קרא: :doc:`installation` → Deployment Options

מוסכמות הפרויקט
-----------------

Naming Conventions
~~~~~~~~~~~~~~~~~~

- Files: ``snake_case.py``
- Classes: ``PascalCase``
- Functions: ``snake_case()``
- Constants: ``UPPER_CASE``
- Private: ``_leading_underscore()``

Code Style
~~~~~~~~~~

- Follow PEP 8
- Use type hints
- Docstrings: Google style
- Max line length: 100
- Use Black for formatting

Structure
~~~~~~~~~

::

   handlers/        # Telegram handlers
   services/        # Business logic
   database/        # Database models & managers
   webapp/          # Flask web app
   tests/          # All tests
   docs/           # Documentation

דוגמאות לשינויים נפוצים
-------------------------

הוספת פקודה חדשה לבוט
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   # 1. handlers/my_handler.py
   async def my_command(update, context):
       await update.message.reply_text("Hello!")
   
   # 2. main.py
   from handlers.my_handler import my_command
   app.add_handler(CommandHandler("mycommand", my_command))
   
   # 3. tests/test_my_handler.py
   @pytest.mark.asyncio
   async def test_my_command():
       # test implementation

הוספת endpoint ל-WebApp
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   # webapp/app.py
   @app.route('/my-endpoint')
   @login_required
   def my_endpoint():
       return render_template('my_template.html')

Checklist לפני PR
------------------

- [ ] הקוד עובר ``pytest``
- [ ] הקוד עובר ``black --check .``
- [ ] הקוד עובר ``mypy .``
- [ ] Coverage > 80%
- [ ] עדכנתי docstrings
- [ ] עדכנתי ``CHANGELOG.md``
- [ ] בדקתי ש-CI עובר
- [ ] ביצעתי self-review
- [ ] תיעדתי breaking changes (אם יש)
```

---

## 📊 סיכום עדיפויות מעודכן

### 🔴 עדיפות גבוהה - קריטי (חסר לגמרי!)

| # | מסמך | זמן משוער | השפעה | הערות |
|---|------|-----------|--------|-------|
| 1 | **Quickstart כפול (מפתחים + AI)** | 3 שעות | ⭐⭐⭐⭐⭐ | **v3!** נקודת כניסה מהירה |
| 2 | **הנחיות מלאות לסוכני AI** | 5 שעות | ⭐⭐⭐⭐⭐ | **v3!** מניעת תקלות |
| 3 | Contributing Guide + .env.example | 5 שעות | ⭐⭐⭐⭐⭐ | כולל נתיבי tmp, סגנון |
| 4 | Architecture + Bot↔WebApp | 6 שעות | ⭐⭐⭐⭐⭐ | הבנת המערכת כולה |
| 5 | **Database Schema** | 5 שעות | ⭐⭐⭐⭐⭐ | **v2!** חסר לגמרי |
| 6 | **Conversation Handlers/States** | 4 שעות | ⭐⭐⭐⭐⭐ | **v2!** חסר לגמרי |
| 7 | Testing + Mocking + safe_rmtree | 5 שעות | ⭐⭐⭐⭐⭐ | כולל עבודה ב-tmp |
| 8 | WebApp API Reference | 4 שעות | ⭐⭐⭐⭐ | Endpoints + schemas |
| 9 | Environment Variables + .env.example | 3 שעות | ⭐⭐⭐⭐ | מקור מקיף + טמפלט |

**סיכום משני:** ~40 שעות | **תועלת:** קריטי לעבודה בסיסית על הפרויקט

---

### 🟡 עדיפות בינונית-גבוהה - חשוב מאוד

| # | מסמך | זמן משוער | השפעה | הערות |
|---|------|-----------|--------|-------|
| 8 | Troubleshooting | 3 שעות | ⭐⭐⭐⭐ | פתרון בעיות נפוצות |
| 9 | Development Workflow | 3 שעות | ⭐⭐⭐ | איך להוסיף פיצ'רים |
| 10 | Security + CSRF | 5 שעות | ⭐⭐⭐⭐ | **מורחב!** כולל CSRF |
| 11 | Performance Guide | 3 שעות | ⭐⭐⭐ | אופטימיזציות |
| 12 | Migration Guide | 2 שעות | ⭐⭐ | שדרוגי גרסאות |
| 13 | **Integrations מפורט** | 6 שעות | ⭐⭐⭐⭐ | **חדש!** OAuth, Webhooks vs Polling |

**סיכום משני:** ~22 שעות | **תועלת:** שיפור משמעותי בחוויית המפתח

---

### 🟢 עדיפות נמוכה - כלים מעשיים

| # | מסמך | זמן משוער | השפעה | הערות |
|---|------|-----------|--------|-------|
| 14 | **Quick Start (עמוד אחד)** | 2 שעות | ⭐⭐⭐⭐ | **חדש!** כניסה מהירה |
| 15 | **Swagger/OpenAPI** | 4 שעות | ⭐⭐⭐ | **חדש!** תיעוד אינטראקטיבי |
| 16 | **Postman Collection** | 2 שעות | ⭐⭐⭐ | **חדש!** דוגמאות מוכנות |
| 17 | FAQ | 2 שעות | ⭐⭐ | שאלות נפוצות |
| 18 | Code of Conduct | 1 שעה | ⭐⭐ | התנהגות קהילה |
| 19 | Changelog | 1 שעה | ⭐⭐ | היסטוריית גרסאות |
| 20 | Roadmap | 2 שעות | ⭐⭐ | תכנון עתידי |
| 21 | AI Developer Guide | 3 שעות | ⭐⭐⭐⭐ | מדריך מהיר לAI |
| 22 | Video Tutorials | 8 שעות | ⭐⭐⭐ | סרטוני הדרכה |
| 23 | Sequence Diagrams | 3 שעות | ⭐⭐⭐ | תרשימי זרימה |

**סיכום משני:** ~28 שעות | **תועלת:** נוחות ונגישות

---

## 📈 סיכום כללי

| קטגוריה | מספר מסמכים | זמן כולל | עדיפות |
|----------|-------------|----------|---------|
| 🔴 קריטי | 9 | ~40 שעות | **התחל כאן!** |
| 🟡 חשוב | 6 | ~22 שעות | לאחר הקריטיים |
| 🟢 נוסף | 10 | ~28 שעות | בהדרגה |
| **סה"כ** | **25** | **~90 שעות** | |

---

## 🎯 תכנית פעולה מומלצת

### שלב 1: נקודת כניסה (שבוע 1) - **התחל כאן!**
1. ✅ **Quickstart כפול** (מפתחים + AI) ← **הכי חשוב!**
2. ✅ **הנחיות לסוכני AI** ← **קריטי למניעת תקלות!**
3. ✅ Architecture + Bot↔WebApp

**תוצאה:** כל אחד יכול להתחיל לעבוד מיידית ללא תקלות

### שלב 2: יסודות (שבוע 2-3)
4. ✅ Database Schema
5. ✅ Conversation Handlers/States
6. ✅ Environment Variables + .env.example
7. ✅ Contributing Guide

**תוצאה:** מפתחים מבינים את המערכת ויודעים לתרום

### שלב 3: בדיקות ואיכות (שבוע 4)
8. ✅ Testing + Mocking + safe_rmtree
9. ✅ Development Workflow
10. ✅ WebApp API Reference

**תוצאה:** קוד איכותי עם טסטים

### שלב 3: אינטגרציות (שבוע 5)
9. ✅ Integrations (OAuth, Webhooks)
10. ✅ WebApp API Reference
11. ✅ Security + CSRF

**תוצאה:** פיתוח מאובטח ומשולב

### שלב 4: כלים וניטוח (שבוע 6-7)
12. ✅ Swagger/OpenAPI
13. ✅ Postman Collection
14. ✅ Troubleshooting
15. ✅ Performance Guide
16. ✅ AI Developer Guide

**תוצאה:** חוויית מפתח מעולה

### שלב 5: תחזוקה (מתמשך)
17. ✅ FAQ
18. ✅ Changelog
19. ✅ Migration Guide
20. ✅ כל השאר...

**תוצאה:** תיעוד שמור ומעודכן

---

## 💡 עצות יישום

1. **התחל קטן:** כתוב גרסה בסיסית קודם, שפר אחר כך
2. **העתק מהקוד:** קח דוגמאות אמיתיות מהפרויקט
3. **בקש feedback:** שתף עם מפתחים וסוכני AI
4. **עדכן כל PR:** כל פיצ'ר חדש = עדכון תיעוד
5. **אוטומט:** CI שבודק שהתיעוד נבנה בהצלחה

**המלצה:** התחל מהמסמכים המסומנים בעדיפות גבוהה, הם יתנו את הערך הגדול ביותר מיד!

---

## 🚀 צעדים הבאים

1. **תעדוף:** קבע אילו מסמכים הכי קריטיים לצרכים שלך
2. **הקצאה:** הקצה זמן ומשאבים ליצירת המסמכים
3. **יצירה:** צור את המסמכים בהדרגה (אפשר להתחיל עם גרסאות בסיסיות)
4. **סקירה:** בקש feedback ממפתחים ומשתמשי AI
5. **שיפור:** עדכן ושפר את המסמכים בהתאם לצורך
6. **תחזוקה:** קבע תהליך לעדכון התיעוד עם כל שינוי משמעותי

---

## 📞 יצירת קשר

שאלות על המסמך הזה או על התיעוד?
- פתח Issue ב-GitHub
- צור קשר דרך הבוט
- קבוצת Telegram: [https://t.me/+nh9skKRgTEVkZmJk](https://t.me/+nh9skKRgTEVkZmJk)

---

## ✨ מה התווסף - היסטוריית גרסאות

### 🎉 גרסה 3.0 (2025-10-10) - דגש על סוכני AI

**תוספות מהירות עבודה וזירוז פיתוח:**

#### 🆕 סעיפים חדשים קריטיים

1. **🚀 Quickstart כפול (סעיף 1)** - **הכי חשוב!**
   - Quickstart למפתחים (3 צעדים)
   - **Quickstart לסוכני AI** (חדש!) - עקרונות עבודה קריטיים
   - מה אסור ומה מותר
   - פורמטי ציטוט קוד
   
2. **🤖 הנחיות מלאות לסוכני AI (סעיף 2)** - **קריטי למניעת תקלות!**
   - מגבלות הרצה (sudo, תהליכים ארוכים, אינטראקטיבי)
   - כלי קבצים מאושרים (Read, LS, Grep, Glob)
   - עקרונות עריכת קוד (guard clauses, ללא try/except מיותר)
   - פורמטי ציטוט (CODE REFERENCE vs. code blocks)
   - קומיטים (HEREDOC, Conventional Commits)
   - עבודה עם טסטים (tmp_path בלבד!)
   - **safe_rmtree** - מחיקה בטוחה
   - **safe_edit** - עריכת הודעות טלגרם בטוחה
   - מדיניות CI קשיחה
   - סודות ופרטיות

#### 🔧 הרחבות משמעותיות

3. **Contributing Guide** - הורחב עם:
   - סגנון קוד (שמות, guard clauses)
   - נתיבי tmp חובה
   - .env.example מלא
   
4. **Testing** - הורחב עם:
   - safe_rmtree בפירוט
   - חובת עבודה ב-tmp_path
   - דוגמאות נוספות

#### 📊 עדכונים

- ✅ **25 מסמכים** (היו 23)
- ✅ **~90 שעות** (היו ~79)
- ✅ תכנית פעולה מעודכנת: 5 שלבים עם דגש על AI
- ✅ טבלאות עדיפויות מעודכנות

---

### 🎁 גרסה 2.0 (2025-10-10) - מבנה ואינטגרציות

**תוספות מהסיכום השני:**

#### 🆕 סעיפים חדשים

1. **🗄️ Database Schema** - קריטי!
   - מבנה כל הקולקציות ב-MongoDB
   - אינדקסים נדרשים
   - קשרים בין קולקציות
   - דוגמאות שאילתות
   
2. **🔄 State Machine & Conversation Handlers** - קריטי!
   - רשימת כל ה-states
   - תרשימי מצבים
   - ניהול context data
   
3. **🔗 תיעוד אינטגרציות מפורט**
   - OAuth Flow מלא לGoogle Drive
   - Webhooks vs Polling (טלגרם)
   - GitHub API פירוט

4. **🚀 Quick Start Guide**
   - עמוד אחד להתחלה מהירה
   
5. **📡 Swagger/OpenAPI**
   - תיעוד אינטראקטיבי
   
6. **📮 Postman Collection**
   - דוגמאות מוכנות לשימוש

#### 🔧 הרחבות

7. **Testing** + Mocking Telegram API
8. **Security** + CSRF Protection
9. **Architecture** + הדגשת Bot↔WebApp

---

### 📝 גרסה 1.0 (2025-10-10) - גרסה ראשונית

15 מסמכים בסיסיים, ~45 שעות

---

## 🎯 סיכום השינויים בין גרסאות

| גרסה | מסמכים | שעות | חידושים עיקריים |
|------|---------|------|------------------|
| 1.0 | 15 | ~45 | בסיס התיעוד |
| 2.0 | 23 | ~79 | Database, States, Integrations |
| **3.0** | **25** | **~90** | **🤖 Quickstart AI, הנחיות AI, safe_* utils** |

**📌 ההבדל המרכזי בv3.0:** דגש חזק על **סוכני AI** - איך הם צריכים לעבוד נכון, מה אסור, מה מותר, פורמטים, כלים מאושרים.

---

**📝 עדכון אחרון:** 2025-10-10  
**🔄 גרסה:** 3.0 (דגש AI + זירוז עבודה)  
**✍️ נוצר עבור:** CodeBot & WebApp  
**🎯 מטרה:** שיפור התיעוד למפתחים וסוכני AI  
**🙏 תודות:** ל-3 הסיכומים שהעשירו את המסמך!
