# מדריך ארכיטקטורה שכבתית - CodeBot
## חלק 3: כללי הפרדה ודוגמאות קוד

---

## 📋 תוכן עניינים - חלק 3
1. [כללי הפרדת שכבות מפורטים](#כללי-הפרדה)
2. [דוגמאות לפני ← אחרי](#דוגמאות-refactoring)
3. [Checklist לכל שכבה](#checklist)
4. [Code Smells והתרעות](#code-smells)
5. [Testing Strategy](#testing-strategy)

---

## 📏 כללי הפרדת שכבות מפורטים

### כלל #1: Handlers לא מדברים עם DB

#### ❌ לפני (הקוד הנוכחי):
```python
# handlers/save_flow.py:344-398
async def save_file_final(update, context, filename, user_id):
    context.user_data['filename_to_save'] = filename
    code = context.user_data.get('code_to_save')

    # ❌ Business logic בתוך handler
    try:
        code = normalize_code(code)
    except Exception:
        pass

    try:
        # ❌ גישה ישירה ל-DB!
        detected_language = code_service.detect_language(code, filename)
        from database import db, CodeSnippet  # ❌❌❌
        note = (context.user_data.get('note_to_save') or '').strip()

        # ❌ יצירת entity בתוך handler
        snippet = CodeSnippet(
            user_id=user_id,
            file_name=filename,
            code=code,
            programming_language=detected_language,
            description=note,
        )

        # ❌ קריאה ישירה ל-repository
        success = db.save_code_snippet(snippet)

        if success:
            await update.message.reply_text("✅ נשמר!")
```

**בעיות:**
1. Handler יודע מה זה `CodeSnippet`
2. Handler קורא ישירות ל-`db.save_code_snippet()`
3. Handler מבצע business logic (`normalize_code`)
4. Handler יוצר entities

#### ✅ אחרי (הארכיטקטורה החדשה):
```python
# src/presentation/telegram/handlers/snippet/save_handler.py
from application.services.snippet_service import SnippetService
from application.dto.create_snippet_dto import CreateSnippetDTO

class SaveSnippetHandler:
    def __init__(self, snippet_service: SnippetService):
        self.snippet_service = snippet_service  # Dependency Injection

    async def save_file_final(self, update, context, filename, user_id):
        """Handler - רק I/O ו-orchestration"""
        code = context.user_data.get('code_to_save')
        note = context.user_data.get('note_to_save', '')

        # יצירת DTO - אובייקט העברת נתונים בלבד
        dto = CreateSnippetDTO(
            user_id=user_id,
            filename=filename,
            code=code,
            note=note
        )

        # קריאה ל-service - זה הכל!
        try:
            snippet = await self.snippet_service.create_snippet(dto)

            # הצגת תוצאה
            await update.message.reply_text(
                f"✅ קובץ {snippet.filename.value} נשמר!\n"
                f"🧠 שפה: {snippet.language.value}"
            )

        except InvalidSnippetError as e:
            await update.message.reply_text(f"❌ שגיאה: {e.message}")
        except Exception as e:
            await update.message.reply_text("❌ שגיאה טכנית")
```

**מה השתנה?**
- ✅ Handler לא יודע מה זה `CodeSnippet` entity
- ✅ Handler לא יודע שיש DB
- ✅ Handler לא מבצע business logic
- ✅ Handler רק מעביר DTO ומציג תוצאות
- ✅ קל לבדוק - mock את `snippet_service`

---

### כלל #2: Services תזמרים, לא מבצעים

#### ❌ לפני:
```python
# services/code_service.py
def detect_language(code: str, filename: str) -> str:
    """Service שמבצע את הלוגיקה בעצמו"""
    if not code_processor:
        # Fallback logic ישירות בתוך service
        ext = filename.lower()
        if ext.endswith('.py'):
            return 'python'
        elif ext.endswith('.js'):
            return 'javascript'
        # ... עוד 20 שורות
        return 'text'

    return code_processor.detect_language(code, filename)
```

#### ✅ אחרי:
```python
# src/application/services/snippet_service.py
from domain.services.code_normalizer import CodeNormalizer
from domain.services.language_detector import LanguageDetector
from domain.validation.snippet_validator import SnippetValidator
from infrastructure.database.mongodb.repositories.snippet_repository import SnippetRepository

class SnippetService:
    """Application service - מתאם בלבד"""

    def __init__(
        self,
        snippet_repository: SnippetRepository,
        code_normalizer: CodeNormalizer,
        language_detector: LanguageDetector,
        snippet_validator: SnippetValidator
    ):
        # Dependency Injection של כל התלויות
        self.repository = snippet_repository
        self.normalizer = code_normalizer
        self.detector = language_detector
        self.validator = snippet_validator

    async def create_snippet(self, dto: CreateSnippetDTO) -> Snippet:
        """
        Orchestrator - קורא לכולם, לא מבצע לוגיקה בעצמו
        """
        # 1. קריאה ל-domain service
        normalized_code = self.normalizer.normalize(dto.code)

        # 2. קריאה ל-domain service
        language = self.detector.detect(normalized_code, dto.filename)

        # 3. יצירת entity
        snippet = Snippet(
            user_id=dto.user_id,
            filename=FileName(dto.filename),
            code=normalized_code,
            language=ProgrammingLanguage(language),
            description=dto.note
        )

        # 4. קריאה ל-domain validator
        validation_result = self.validator.validate(snippet)
        if not validation_result.is_valid:
            raise InvalidSnippetError(validation_result.errors)

        # 5. קריאה ל-repository
        return await self.repository.save(snippet)
```

**מה השתנה?**
- ✅ Service לא מבצע לוגיקה בעצמו - רק מתאם
- ✅ כל לוגיקה ב-domain services
- ✅ Dependency Injection - קל להחליף implementations
- ✅ קל לבדוק - mock את כל התלויות

---

### כלל #3: Domain = Pure Python

#### ❌ לפני:
```python
# utils.py:400-500
def normalize_code(code: str) -> str:
    """פונקציה ב-utils - מעורב עם 7 דברים אחרים"""
    if not code:
        return ""

    # Logic...
    code = remove_bidi_marks(code)
    code = unicodedata.normalize('NFC', code)
    # ...
    return code

# נמצא בקובץ עם:
# - TelegramUtils (תלוי ב-telegram)
# - FileUtils (תלוי ב-aiofiles)
# - SecurityUtils (תלוי ב-hashlib)
```

#### ✅ אחרי:
```python
# src/domain/services/code_normalizer.py
import unicodedata
import re

# ⚠️ רק Python standard library - אין תלויות חיצוניות!

class CodeNormalizer:
    """
    Domain service - pure business logic

    Rules:
    - No framework dependencies
    - No I/O operations
    - Pure functions
    - Easily testable
    """

    # Constants
    DIRECTION_MARKERS = [
        '\u200e',  # LEFT-TO-RIGHT MARK
        '\u200f',  # RIGHT-TO-LEFT MARK
        '\u202a',  # LEFT-TO-RIGHT EMBEDDING
        '\u202b',  # RIGHT-TO-LEFT EMBEDDING
        '\u202c',  # POP DIRECTIONAL FORMATTING
    ]

    def normalize(self, code: str) -> str:
        """
        Normalize code content

        Business rule: All code must be normalized before storage

        Args:
            code: Raw code string

        Returns:
            Normalized code

        Examples:
            >>> normalizer = CodeNormalizer()
            >>> normalizer.normalize("  hello\\r\\n")
            'hello\\n'
        """
        if not code:
            return ""

        # 1. Remove unicode direction markers
        code = self._remove_direction_markers(code)

        # 2. Normalize unicode (NFC form)
        code = unicodedata.normalize('NFC', code)

        # 3. Fix line endings
        code = self._normalize_line_endings(code)

        # 4. Remove trailing whitespace per line
        code = self._remove_trailing_whitespace(code)

        # 5. Ensure single trailing newline
        code = code.rstrip() + '\n' if code.rstrip() else ''

        return code

    def _remove_direction_markers(self, text: str) -> str:
        """Remove unicode bidirectional markers"""
        for marker in self.DIRECTION_MARKERS:
            text = text.replace(marker, '')
        return text

    def _normalize_line_endings(self, text: str) -> str:
        """Convert all line endings to \\n"""
        return text.replace('\r\n', '\n').replace('\r', '\n')

    def _remove_trailing_whitespace(self, text: str) -> str:
        """Remove trailing whitespace from each line"""
        lines = text.split('\n')
        lines = [line.rstrip() for line in lines]
        return '\n'.join(lines)
```

**מה השתנה?**
- ✅ קובץ ייעודי עם אחריות אחת
- ✅ Pure Python - אפשר להריץ בכל מקום (CLI, API, tests)
- ✅ מתועד היטב
- ✅ קל לבדוק:
  ```python
  def test_normalize_removes_direction_markers():
      normalizer = CodeNormalizer()
      code = "hello\u200eworld"
      assert normalizer.normalize(code) == "helloworld\n"
  ```

---

### כלל #4: Infrastructure מממש Interfaces

#### ❌ לפני:
```python
# database/repository.py
class Repository:
    """Repository שלא מממש interface"""

    def __init__(self, manager: DatabaseManager):
        self.manager = manager

    def save_code_snippet(self, snippet: CodeSnippet) -> bool:
        # ❌ Business logic בתוך repository!
        try:
            if config.NORMALIZE_CODE_ON_SAVE:
                snippet.code = normalize_code(snippet.code)
        except Exception:
            pass

        # MongoDB specific code...
        result = self.manager.collection.insert_one(asdict(snippet))
        return bool(result.inserted_id)
```

**בעיות:**
1. Repository מבצע business logic
2. אין interface - קשה להחליף ל-PostgreSQL
3. Repository תלוי ב-`normalize_code` שהוא domain logic

#### ✅ אחרי:
```python
# src/domain/interfaces/snippet_repository_interface.py
from abc import ABC, abstractmethod
from typing import Optional, List
from domain.entities.snippet import Snippet

class ISnippetRepository(ABC):
    """
    Repository interface - מגדיר חוזה

    Domain מגדיר מה צריך, Infrastructure מממש
    """

    @abstractmethod
    async def save(self, snippet: Snippet) -> Snippet:
        """Save snippet and return saved entity"""
        pass

    @abstractmethod
    async def get_by_id(self, snippet_id: str) -> Optional[Snippet]:
        """Get snippet by ID"""
        pass

    @abstractmethod
    async def get_latest_version(self, user_id: int, filename: str) -> Optional[Snippet]:
        """Get latest version of file"""
        pass

    @abstractmethod
    async def search(self, user_id: int, query: str, language: Optional[str] = None) -> List[Snippet]:
        """Search snippets"""
        pass

    @abstractmethod
    async def delete(self, snippet_id: str) -> bool:
        """Soft delete snippet"""
        pass
```

```python
# src/infrastructure/database/mongodb/repositories/snippet_repository.py
from domain.interfaces.snippet_repository_interface import ISnippetRepository
from domain.entities.snippet import Snippet
from infrastructure.database.mongodb.models.snippet_model import SnippetModel

class MongoSnippetRepository(ISnippetRepository):
    """
    MongoDB implementation של ISnippetRepository

    - מממש את ה-interface מ-domain
    - יודע רק על MongoDB
    - לא מבצע business logic
    """

    def __init__(self, db_manager):
        self.collection = db_manager.get_collection('snippets')

    async def save(self, snippet: Snippet) -> Snippet:
        """
        Save snippet - NO business logic!

        Normalization כבר בוצעה ב-service layer
        """
        # Map domain entity → DB model
        db_model = SnippetModel.from_entity(snippet)

        # Check for existing (versioning)
        existing = await self._find_latest(snippet.user_id, snippet.filename.value)
        if existing:
            db_model.version = existing['version'] + 1

        # Pure DB operation
        result = await self.collection.insert_one(db_model.to_dict())

        # Map back: DB → entity
        saved_doc = await self.collection.find_one({'_id': result.inserted_id})
        return SnippetModel.to_entity(saved_doc)

    async def get_latest_version(self, user_id: int, filename: str) -> Optional[Snippet]:
        """Get latest version - pure query"""
        doc = await self.collection.find_one(
            {
                'user_id': user_id,
                'file_name': filename,
                'is_active': True
            },
            sort=[('version', -1)]
        )

        if not doc:
            return None

        return SnippetModel.to_entity(doc)

    # ... שאר המתודות
```

**מה השתנה?**
- ✅ יש interface ב-domain
- ✅ Infrastructure מממש את ה-interface
- ✅ אפשר להחליף ל-PostgreSQL/Redis בלי לשנות domain/application
- ✅ Repository רק עושה DB operations - אין business logic
- ✅ יש הפרדה: Domain Entity ≠ DB Model

---

### כלל #5: DTOs להעברת נתונים בין שכבות

#### ❌ לפני:
```python
# Handler מעביר נתונים גולמיים
await save_snippet(user_id, filename, code, note, tags, language, is_favorite)
# 😱 6 פרמטרים! מה הסדר? מה חובה?
```

#### ✅ אחרי:
```python
# src/application/dto/create_snippet_dto.py
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class CreateSnippetDTO:
    """
    Data Transfer Object - העברת נתונים מ-presentation ל-application

    - Immutable
    - Simple types only
    - No business logic
    """
    user_id: int
    filename: str
    code: str
    note: Optional[str] = None
    tags: Optional[List[str]] = None

    def __post_init__(self):
        """Basic validation"""
        if not self.user_id or self.user_id <= 0:
            raise ValueError("user_id must be positive")

        if not self.filename:
            raise ValueError("filename is required")

        if not self.code:
            raise ValueError("code is required")

# שימוש:
dto = CreateSnippetDTO(
    user_id=123,
    filename="script.py",
    code="print('hello')",
    note="My first script"
)

snippet = await snippet_service.create_snippet(dto)
```

**יתרונות:**
- ✅ ברור מה חובה ומה אופציונלי
- ✅ Type hints עובדים
- ✅ IDE autocomplete
- ✅ קל לשנות בעתיד (הוסף שדה - רק צריך לעדכן DTO)
- ✅ הפרדה בין presentation ל-domain

---

### כלל #6: פיצול קבצים ענקיים

#### ❌ לפני:
```python
# conversation_handlers.py (231KB!)
# כל ה-handlers בקובץ אחד:

def save_snippet_handler():
    # 100 שורות
    pass

def edit_snippet_handler():
    # 150 שורות
    pass

def view_snippet_handler():
    # 200 שורות
    pass

def search_handler():
    # 80 שורות
    pass

# ... עוד 50 handlers
```

#### ✅ אחרי:
```
src/presentation/telegram/handlers/
├── snippet/
│   ├── save_handler.py      (100 שורות)
│   ├── edit_handler.py      (150 שורות)
│   ├── view_handler.py      (200 שורות)
│   ├── search_handler.py    (80 שורות)
│   └── __init__.py          (exports)
├── collection/
│   ├── create_handler.py
│   ├── manage_handler.py
│   └── __init__.py
└── integration/
    ├── github_handler.py
    └── drive_handler.py
```

**יתרונות:**
- ✅ קל למצוא דברים
- ✅ merge conflicts פחות
- ✅ IDE מהיר יותר
- ✅ אפשר לעבוד במקביל על features שונים

---

## 🔄 דוגמאות Refactoring מלאות

### דוגמה #1: save_flow.py → שכבות

#### לפני - הקוד המלא:
```python
# handlers/save_flow.py (498 שורות)
from utils import normalize_code
from services import code_service
from database import db, CodeSnippet

async def get_code(update, context):
    code = update.message.text or ''

    # ❌ Business logic
    try:
        code = normalize_code(code)
    except Exception:
        pass

    context.user_data['code_to_save'] = code

    lines = len(code.split('\n'))
    await update.message.reply_text(
        f"✅ קוד התקבל!\n"
        f"📏 שורות: {lines}"
    )
    return GET_FILENAME

async def get_filename(update, context):
    filename = update.message.text.strip()
    user_id = update.message.from_user.id

    # ❌ גישה ישירה ל-DB
    from database import db
    existing_file = db.get_latest_version(user_id, filename)

    if existing_file:
        await update.message.reply_text("⚠️ קובץ קיים!")
        return GET_FILENAME

    context.user_data['pending_filename'] = filename
    await update.message.reply_text("📝 הוסף הערה או שלח 'דלג'")
    return GET_NOTE

async def save_file_final(update, context, filename, user_id):
    code = context.user_data.get('code_to_save')

    # ❌ Business logic
    try:
        code = normalize_code(code)
    except Exception:
        pass

    try:
        # ❌ Business logic
        detected_language = code_service.detect_language(code, filename)

        # ❌ יצירת entity
        from database import db, CodeSnippet
        note = context.user_data.get('note_to_save') or ''

        snippet = CodeSnippet(
            user_id=user_id,
            file_name=filename,
            code=code,
            programming_language=detected_language,
            description=note,
        )

        # ❌ גישה ישירה ל-repository
        success = db.save_code_snippet(snippet)

        if success:
            await update.message.reply_text("🎉 נשמר!")
        else:
            await update.message.reply_text("💥 שגיאה!")

    except Exception as e:
        logger.error(f"Failed: {e}")
        await update.message.reply_text("🤖 שגיאה טכנית")

    return ConversationHandler.END
```

#### אחרי - שכבות נפרדות:

**1. Presentation Layer:**
```python
# src/presentation/telegram/handlers/snippet/save_handler.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from application.services.snippet_service import SnippetService
from application.dto.create_snippet_dto import CreateSnippetDTO
from application.exceptions.service_exceptions import (
    SnippetAlreadyExistsError,
    InvalidSnippetError
)
from presentation.telegram.helpers.telegram_formatter import (
    format_snippet_saved_message,
    format_error_message
)

# States
GET_CODE, GET_FILENAME, GET_NOTE = range(3)


class SaveSnippetHandler:
    """Handler for saving code snippets - thin layer, only I/O"""

    def __init__(self, snippet_service: SnippetService):
        self.snippet_service = snippet_service

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Entry point"""
        await update.message.reply_text(
            "✨ בוא ניצור קוד חדש!\n"
            "📝 שלח לי את קטע הקוד שלך"
        )
        return GET_CODE

    async def receive_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive code - store in context only"""
        code = update.message.text or ''

        # ✅ Only basic validation (not empty)
        if not code or len(code) < 5:
            await update.message.reply_text(
                "❌ הקוד קצר מדי\n"
                "💡 שלח לפחות 5 תווים"
            )
            return GET_CODE

        # ✅ Store in context
        context.user_data['code'] = code

        # ✅ Display info only
        lines = len(code.split('\n'))
        chars = len(code)

        await update.message.reply_text(
            f"✅ קוד התקבל!\n\n"
            f"📊 סטטיסטיקות:\n"
            f"• שורות: {lines:,}\n"
            f"• תווים: {chars:,}\n\n"
            f"💭 עכשיו תן שם קובץ (למשל: script.py)"
        )
        return GET_FILENAME

    async def receive_filename(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive filename - validate via service"""
        filename = update.message.text.strip()
        user_id = update.effective_user.id

        # ✅ Basic check only
        if not filename:
            await update.message.reply_text("❌ שם קובץ לא יכול להיות ריק")
            return GET_FILENAME

        # ✅ Check if exists - via service
        try:
            existing = await self.snippet_service.get_snippet(user_id, filename)

            if existing:
                # Show options
                keyboard = [
                    [InlineKeyboardButton("🔄 החלף", callback_data=f"replace_{filename}")],
                    [InlineKeyboardButton("✏️ שנה שם", callback_data="rename")],
                    [InlineKeyboardButton("🚫 בטל", callback_data="cancel")],
                ]

                await update.message.reply_text(
                    f"⚠️ הקובץ `{filename}` כבר קיים!\n"
                    f"מה תרצה לעשות?",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return GET_FILENAME

        except Exception as e:
            await update.message.reply_text(
                format_error_message("שגיאה בבדיקת קובץ קיים")
            )
            return ConversationHandler.END

        # ✅ Store and continue
        context.user_data['filename'] = filename

        await update.message.reply_text(
            "📝 רוצה להוסיף הערה?\n"
            "כתוב אותה או שלח 'דלג'"
        )
        return GET_NOTE

    async def receive_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive note and save - call service"""
        note_text = update.message.text.strip()

        # Parse 'skip'
        if note_text.lower() in {'דלג', 'skip'}:
            note = None
        else:
            note = note_text

        # ✅ Create DTO
        dto = CreateSnippetDTO(
            user_id=update.effective_user.id,
            filename=context.user_data['filename'],
            code=context.user_data['code'],
            note=note
        )

        # ✅ Call service - all logic there!
        try:
            snippet = await self.snippet_service.create_snippet(dto)

            # ✅ Format and display
            message = format_snippet_saved_message(snippet)
            await update.message.reply_text(message, parse_mode='Markdown')

            return ConversationHandler.END

        except InvalidSnippetError as e:
            # Business validation error
            await update.message.reply_text(
                f"❌ שגיאת ולידציה:\n{e.message}"
            )
            return ConversationHandler.END

        except Exception as e:
            # Technical error
            await update.message.reply_text(
                format_error_message("שגיאה טכנית בשמירה")
            )
            return ConversationHandler.END
```

**2. Application Layer:**
```python
# src/application/services/snippet_service.py
from typing import Optional
from application.dto.create_snippet_dto import CreateSnippetDTO
from domain.entities.snippet import Snippet
from domain.services.code_normalizer import CodeNormalizer
from domain.services.language_detector import LanguageDetector
from domain.validation.snippet_validator import SnippetValidator
from domain.value_objects.file_name import FileName
from domain.value_objects.programming_language import ProgrammingLanguage
from domain.exceptions.domain_exceptions import InvalidSnippetError
from infrastructure.database.mongodb.repositories.snippet_repository import SnippetRepository

class SnippetService:
    """
    Application service - orchestrates snippet operations

    Responsibilities:
    - Coordinate domain and infrastructure
    - Transaction management
    - DTO ↔ Entity conversion
    - Error handling
    """

    def __init__(
        self,
        snippet_repository: SnippetRepository,
        code_normalizer: CodeNormalizer,
        language_detector: LanguageDetector,
        snippet_validator: SnippetValidator
    ):
        self.repository = snippet_repository
        self.normalizer = code_normalizer
        self.detector = language_detector
        self.validator = snippet_validator

    async def create_snippet(self, dto: CreateSnippetDTO) -> Snippet:
        """
        Create new snippet

        Flow:
        1. Normalize code (domain)
        2. Detect language (domain)
        3. Create entity (domain)
        4. Validate (domain)
        5. Save (infrastructure)
        """
        # 1. Domain service: normalize
        normalized_code = self.normalizer.normalize(dto.code)

        # 2. Domain service: detect language
        language = self.detector.detect(normalized_code, dto.filename)

        # 3. Create domain entity
        snippet = Snippet(
            user_id=dto.user_id,
            filename=FileName(dto.filename),
            code=normalized_code,
            language=ProgrammingLanguage(language),
            description=dto.note or ""
        )

        # 4. Domain validation
        validation_result = self.validator.validate(snippet)
        if not validation_result.is_valid:
            raise InvalidSnippetError(
                message="Snippet validation failed",
                errors=validation_result.errors
            )

        # 5. Infrastructure: save
        saved_snippet = await self.repository.save(snippet)

        return saved_snippet

    async def get_snippet(self, user_id: int, filename: str) -> Optional[Snippet]:
        """Get latest version of snippet"""
        return await self.repository.get_latest_version(user_id, filename)
```

**3. Domain Layer:**
```python
# src/domain/services/code_normalizer.py
import unicodedata

class CodeNormalizer:
    """Domain service - normalize code (pure Python)"""

    def normalize(self, code: str) -> str:
        """Business rule: all code must be normalized"""
        if not code:
            return ""

        # Remove direction markers
        code = self._remove_bidi(code)

        # Normalize unicode
        code = unicodedata.normalize('NFC', code)

        # Fix line endings
        code = code.replace('\r\n', '\n').replace('\r', '\n')

        # Remove trailing whitespace
        lines = [line.rstrip() for line in code.split('\n')]
        code = '\n'.join(lines)

        # Single trailing newline
        return code.rstrip() + '\n' if code.rstrip() else ''

    def _remove_bidi(self, text: str) -> str:
        """Remove bidirectional markers"""
        markers = ['\u200e', '\u200f', '\u202a', '\u202b', '\u202c']
        for m in markers:
            text = text.replace(m, '')
        return text
```

```python
# src/domain/validation/snippet_validator.py
from dataclasses import dataclass
from typing import List
from domain.entities.snippet import Snippet

@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]

class SnippetValidator:
    """Domain validator - business rules"""

    MAX_CODE_LENGTH = 500_000
    MIN_CODE_LENGTH = 1

    def validate(self, snippet: Snippet) -> ValidationResult:
        """Validate against business rules"""
        errors = []

        # Length rules
        if len(snippet.code) < self.MIN_CODE_LENGTH:
            errors.append("Code is too short")

        if len(snippet.code) > self.MAX_CODE_LENGTH:
            errors.append(f"Code exceeds {self.MAX_CODE_LENGTH} characters")

        # Filename rules
        if not snippet.filename.value:
            errors.append("Filename is required")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors
        )
```

**4. Infrastructure Layer:**
```python
# src/infrastructure/database/mongodb/repositories/snippet_repository.py
from typing import Optional
from domain.entities.snippet import Snippet
from domain.interfaces.snippet_repository_interface import ISnippetRepository
from infrastructure.database.mongodb.models.snippet_model import SnippetModel

class MongoSnippetRepository(ISnippetRepository):
    """MongoDB implementation - no business logic!"""

    def __init__(self, db_manager):
        self.collection = db_manager.get_collection('snippets')

    async def save(self, snippet: Snippet) -> Snippet:
        """Save to MongoDB"""
        # Map entity → DB model
        db_model = SnippetModel.from_entity(snippet)

        # Check version
        existing = await self._find_latest(
            snippet.user_id,
            snippet.filename.value
        )
        if existing:
            db_model.version = existing['version'] + 1

        # Insert
        result = await self.collection.insert_one(db_model.to_dict())

        # Fetch and map back
        doc = await self.collection.find_one({'_id': result.inserted_id})
        return SnippetModel.to_entity(doc)

    async def get_latest_version(
        self,
        user_id: int,
        filename: str
    ) -> Optional[Snippet]:
        """Get latest version"""
        doc = await self.collection.find_one(
            {
                'user_id': user_id,
                'file_name': filename,
                'is_active': True
            },
            sort=[('version', -1)]
        )

        return SnippetModel.to_entity(doc) if doc else None
```

**השוואה:**

| לפני | אחרי |
|------|------|
| 1 קובץ (498 שורות) | 7 קבצים (~600 שורות סה"כ) |
| הכל מעורבב | כל קובץ עם תפקיד אחד |
| handler יודע על DB | handler לא יודע על DB |
| קשה לבדוק | קל לבדוק כל שכבה בנפרד |
| utils.py מעורב | domain services נפרדים |
| אין DTOs | DTOs ברורים |

---

## ✅ Checklist לכל שכבה

### Presentation Layer Checklist

כשאתה כותב/סוקר handler, בדוק:

- [ ] ✅ Handler מקבל dependencies ב-`__init__` (DI)
- [ ] ✅ Handler רק עובד עם DTOs
- [ ] ✅ אין ייבוא מ-`database`
- [ ] ✅ אין ייבוא מ-`infrastructure`
- [ ] ✅ אין business logic (normalize, validate business rules)
- [ ] ✅ רק קריאות ל-services
- [ ] ✅ רק Telegram-specific code (keyboards, formatting)
- [ ] ❌ אין יצירת entities (CodeSnippet, etc.)
- [ ] ❌ אין קריאות DB ישירות
- [ ] ❌ אין MongoDB queries

### Application Layer Checklist

כשאתה כותב/סוקר service, בדוק:

- [ ] ✅ Service מקבל כל התלויות ב-`__init__`
- [ ] ✅ Service עובד עם DTOs (input) ו-Entities (output)
- [ ] ✅ Service קורא ל-domain services
- [ ] ✅ Service קורא ל-repositories
- [ ] ✅ Service מתאם, לא מבצע
- [ ] ❌ אין business logic ישירות בתוך service
- [ ] ❌ אין SQL/MongoDB queries
- [ ] ❌ אין ייבוא מ-`telegram`

### Domain Layer Checklist

כשאתה כותב/סוקר domain code, בדוק:

- [ ] ✅ Pure Python בלבד
- [ ] ✅ רק Python standard library
- [ ] ✅ Pure functions (אין side effects)
- [ ] ✅ Well-documented
- [ ] ✅ מכיל docstrings + examples
- [ ] ❌ אין ייבוא מ-`telegram`, `pymongo`, `aiohttp`, וכו'
- [ ] ❌ אין I/O operations (קבצים, network, DB)
- [ ] ❌ אין תלות ב-frameworks

### Infrastructure Layer Checklist

כשאתה כותב/סוקר repository, בדוק:

- [ ] ✅ Repository מממש interface מ-domain
- [ ] ✅ יש mapping layer (Entity ↔ DB Model)
- [ ] ✅ רק DB/API operations
- [ ] ❌ אין business logic
- [ ] ❌ אין קריאות ל-domain services
- [ ] ❌ Repository לא מנרמל קוד

---

## 🚨 Code Smells והתרעות

### Smell #1: Handler מדבר עם DB

```python
# ❌ Code smell!
from database import db

async def my_handler(update, context):
    user_id = update.effective_user.id
    snippet = db.get_latest_version(user_id, "file.py")  # 🚨 Smell!
```

**תיקון:**
```python
# ✅ Fixed
async def my_handler(update, context):
    user_id = update.effective_user.id
    snippet = await self.snippet_service.get_snippet(user_id, "file.py")
```

---

### Smell #2: Service מבצע business logic

```python
# ❌ Code smell!
class MyService:
    async def save_snippet(self, code, filename):
        # 🚨 Business logic בתוך service!
        normalized = code.replace('\r\n', '\n')
        normalized = normalized.strip()
        # ... עוד 20 שורות
```

**תיקון:**
```python
# ✅ Fixed
class MyService:
    def __init__(self, code_normalizer: CodeNormalizer):
        self.normalizer = code_normalizer

    async def save_snippet(self, code, filename):
        # קריאה ל-domain service
        normalized = self.normalizer.normalize(code)
```

---

### Smell #3: Domain תלוי ב-framework

```python
# ❌ Code smell!
# domain/services/my_service.py
from telegram import Update  # 🚨 Domain תלוי ב-Telegram!

def process_code(update: Update):
    code = update.message.text
```

**תיקון:**
```python
# ✅ Fixed
# domain/services/my_service.py
# אין ייבוא של telegram!

def process_code(code: str) -> str:
    # Pure Python
    return code.strip()
```

---

### Smell #4: Repository עם business logic

```python
# ❌ Code smell!
class Repository:
    async def save(self, snippet):
        # 🚨 Business logic!
        if len(snippet.code) > 10000:
            snippet.code = snippet.code[:10000]

        await self.collection.insert_one(...)
```

**תיקון:**
```python
# ✅ Fixed - validation ב-domain
class Repository:
    async def save(self, snippet):
        # snippet כבר עבר validation ב-service
        await self.collection.insert_one(...)
```

---

## 🧪 Testing Strategy

### בדיקת Presentation Layer

```python
# tests/unit/presentation/telegram/handlers/test_save_handler.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from presentation.telegram.handlers.snippet.save_handler import SaveSnippetHandler
from application.dto.create_snippet_dto import CreateSnippetDTO

@pytest.fixture
def mock_snippet_service():
    """Mock service"""
    service = AsyncMock()
    service.create_snippet = AsyncMock(return_value=MagicMock(
        filename=MagicMock(value="test.py"),
        language=MagicMock(value="python")
    ))
    return service

@pytest.fixture
def handler(mock_snippet_service):
    """Create handler with mocked service"""
    return SaveSnippetHandler(snippet_service=mock_snippet_service)

@pytest.mark.asyncio
async def test_receive_code_success(handler, mock_snippet_service):
    """Test receiving code successfully"""
    # Arrange
    update = MagicMock()
    update.message.text = "print('hello')"
    context = MagicMock()
    context.user_data = {}

    # Act
    result = await handler.receive_code(update, context)

    # Assert
    assert context.user_data['code'] == "print('hello')"
    assert result == handler.GET_FILENAME
    update.message.reply_text.assert_called_once()

@pytest.mark.asyncio
async def test_receive_note_calls_service(handler, mock_snippet_service):
    """Test that handler calls service correctly"""
    # Arrange
    update = MagicMock()
    update.message.text = "My note"
    update.effective_user.id = 123
    context = MagicMock()
    context.user_data = {
        'code': "print('test')",
        'filename': "test.py"
    }

    # Act
    await handler.receive_note(update, context)

    # Assert
    # Verify service was called with correct DTO
    mock_snippet_service.create_snippet.assert_called_once()
    call_args = mock_snippet_service.create_snippet.call_args[0][0]
    assert isinstance(call_args, CreateSnippetDTO)
    assert call_args.user_id == 123
    assert call_args.filename == "test.py"
    assert call_args.code == "print('test')"
    assert call_args.note == "My note"
```

**שים לב:**
- ✅ לא צריך Telegram bot אמיתי
- ✅ לא צריך DB
- ✅ רק mock את ה-service
- ✅ בודק שה-handler עושה I/O נכון

---

### בדיקת Application Layer

```python
# tests/unit/application/services/test_snippet_service.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from application.services.snippet_service import SnippetService
from application.dto.create_snippet_dto import CreateSnippetDTO

@pytest.fixture
def mock_dependencies():
    """Mock all dependencies"""
    return {
        'repository': AsyncMock(),
        'normalizer': MagicMock(),
        'detector': MagicMock(),
        'validator': MagicMock()
    }

@pytest.fixture
def service(mock_dependencies):
    """Create service with mocks"""
    return SnippetService(
        snippet_repository=mock_dependencies['repository'],
        code_normalizer=mock_dependencies['normalizer'],
        language_detector=mock_dependencies['detector'],
        snippet_validator=mock_dependencies['validator']
    )

@pytest.mark.asyncio
async def test_create_snippet_success(service, mock_dependencies):
    """Test successful snippet creation"""
    # Arrange
    dto = CreateSnippetDTO(
        user_id=123,
        filename="test.py",
        code="print('hello')",
        note="Test"
    )

    # Mock responses
    mock_dependencies['normalizer'].normalize.return_value = "print('hello')\n"
    mock_dependencies['detector'].detect.return_value = "python"
    mock_dependencies['validator'].validate.return_value = MagicMock(
        is_valid=True,
        errors=[]
    )
    mock_dependencies['repository'].save = AsyncMock(return_value=MagicMock())

    # Act
    result = await service.create_snippet(dto)

    # Assert
    mock_dependencies['normalizer'].normalize.assert_called_once_with("print('hello')")
    mock_dependencies['detector'].detect.assert_called_once()
    mock_dependencies['validator'].validate.assert_called_once()
    mock_dependencies['repository'].save.assert_called_once()
```

**שים לב:**
- ✅ לא צריך DB
- ✅ לא צריך Telegram
- ✅ mock את כל התלויות
- ✅ בודק orchestration

---

### בדיקת Domain Layer

```python
# tests/unit/domain/services/test_code_normalizer.py
import pytest
from domain.services.code_normalizer import CodeNormalizer

def test_normalize_removes_direction_markers():
    """Test that direction markers are removed"""
    # Arrange
    normalizer = CodeNormalizer()
    code = "hello\u200eworld\u200f"

    # Act
    result = normalizer.normalize(code)

    # Assert
    assert result == "helloworld\n"

def test_normalize_fixes_line_endings():
    """Test that line endings are normalized"""
    # Arrange
    normalizer = CodeNormalizer()
    code = "line1\r\nline2\rline3\n"

    # Act
    result = normalizer.normalize(code)

    # Assert
    assert result == "line1\nline2\nline3\n"

def test_normalize_empty_string():
    """Test empty string"""
    normalizer = CodeNormalizer()
    assert normalizer.normalize("") == ""

def test_normalize_idempotent():
    """Test that normalizing twice gives same result"""
    normalizer = CodeNormalizer()
    code = "hello  \r\nworld  "

    result1 = normalizer.normalize(code)
    result2 = normalizer.normalize(result1)

    assert result1 == result2
```

**שים לב:**
- ✅ Pure unit tests
- ✅ אין mocks בכלל
- ✅ מהיר מאוד
- ✅ קל לכתוב
- ✅ בודק business logic ישירות

---

### בדיקת Infrastructure Layer

```python
# tests/integration/infrastructure/database/test_snippet_repository.py
import pytest
from infrastructure.database.mongodb.repositories.snippet_repository import MongoSnippetRepository
from domain.entities.snippet import Snippet
from domain.value_objects.file_name import FileName
from domain.value_objects.programming_language import ProgrammingLanguage

@pytest.fixture
async def repository(test_db):
    """Repository with test DB"""
    return MongoSnippetRepository(test_db)

@pytest.mark.asyncio
async def test_save_and_retrieve(repository):
    """Integration test - real DB"""
    # Arrange
    snippet = Snippet(
        user_id=123,
        filename=FileName("test.py"),
        code="print('test')\n",
        language=ProgrammingLanguage("python"),
        description="Test snippet"
    )

    # Act
    saved = await repository.save(snippet)
    retrieved = await repository.get_latest_version(123, "test.py")

    # Assert
    assert retrieved is not None
    assert retrieved.user_id == 123
    assert retrieved.filename.value == "test.py"
    assert retrieved.code == "print('test')\n"
```

**שים לב:**
- ✅ Integration test - DB אמיתי (test DB)
- ✅ בודק mapping Entity ↔ DB
- ✅ בודק queries

---

## 🎯 סיכום חלק 3

### מה למדנו?

1. **6 כללי זהב** להפרדת שכבות
2. **דוגמאות refactoring** מלאות (save_flow)
3. **Checklists** לכל שכבה
4. **Code smells** נפוצים ואיך לתקן
5. **Testing strategy** לכל שכבה

### העקרונות המרכזיים:

✅ **Handlers** = Thin, רק I/O
✅ **Services** = Orchestrators, לא מבצעים
✅ **Domain** = Pure Python, business logic
✅ **Infrastructure** = מימוש interfaces, פרטים טכניים

### מה הלאה?

**בחלק 4** (הסופי) נראה:
- 🗺️ **מפת דרכים** מעשית ל-5 שלבים
- 📅 **לוח זמנים** מציאותי
- ✅ **Checklist** לכל שלב
- 🔄 **דוגמה מלאה** - save_flow מקצה לקצה בכל השכבות

---

*מסמך זה נוצר ב-18/11/2024 - CodeBot Architecture Refactoring Initiative - Part 3*
