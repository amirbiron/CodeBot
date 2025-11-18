# מדריך ארכיטקטורה שכבתית - CodeBot
## חלק 2: ארכיטקטורה מוצעת ומיפוי קבצים

---

## 📋 תוכן עניינים - חלק 2
1. [עקרונות הארכיטקטורה המוצעת](#עקרונות)
2. [מבנה שכבות מפורט](#מבנה-שכבות)
3. [עץ תיקיות מלא](#עץ-תיקיות)
4. [הסבר מפורט לכל שכבה](#הסבר-שכבות)
5. [מיפוי קבצים קיימים → שכבות חדשות](#מיפוי-קבצים)
6. [תלויות בין שכבות](#תלויות)

---

## 🎯 עקרונות הארכיטקטורה המוצעת

### מודל 4 שכבות + Shared

```
┌─────────────────────────────────────────┐
│   Presentation Layer (handlers/)        │  ◄── Telegram, CLI
├─────────────────────────────────────────┤
│   Application Layer (services/)         │  ◄── Business Logic Orchestration
├─────────────────────────────────────────┤
│   Domain Layer (domain/)                │  ◄── Core Business Rules (NEW!)
├─────────────────────────────────────────┤
│   Infrastructure Layer (infrastructure/)│  ◄── DB, External APIs, Files
└─────────────────────────────────────────┘
         Shared (shared/)                      ◄── Cross-cutting utilities
```

### כללי זהב

1. **Dependency Rule**: שכבה יכולה לדבר רק עם השכבה שמתחתיה
2. **Domain = Pure Python**: ללא תלויות ב-Telegram, DB, או frameworks
3. **Services = Orchestrators**: מתאמים בין Domain ל-Infrastructure
4. **Handlers = Thin Layer**: רק I/O, ללא לוגיקה עסקית
5. **Infrastructure = Details**: הכל שקשור לטכנולוגיה ספציפית

---

## 📁 מבנה שכבות מפורט

### Layer 1️⃣: Presentation (handlers/)
**תפקיד:** קבלת קלט מהמשתמש והצגת תוצאות

```
מה מותר:
✅ לקרוא input מ-Telegram
✅ להציג תוצאות למשתמש
✅ לקרוא ל-services
✅ לנהל state של conversation
✅ validation בסיסי של input (לא ריק, אורך)

מה אסור:
❌ גישה ישירה ל-DB
❌ לוגיקה עסקית (normalize, validate business rules)
❌ יצירת entities (CodeSnippet, etc.)
❌ קריאות ל-APIs חיצוניים
```

### Layer 2️⃣: Application (services/)
**תפקיד:** תזמור לוגיקה עסקית

```
מה מותר:
✅ לקרוא ל-domain functions
✅ לקרוא ל-repositories
✅ לתאם בין מספר repositories
✅ ניהול transactions
✅ המרה בין DTOs ל-Entities
✅ error handling ו-logging

מה אסור:
❌ לדעת על Telegram
❌ SQL/MongoDB queries ישירות
❌ קריאה ל-handlers
```

### Layer 3️⃣: Domain (domain/) **🆕 חדש!**
**תפקיד:** חוקים עסקיים טהורים

```
מה מותר:
✅ לוגיקה עסקית טהורה (Pure Functions)
✅ entities, value objects
✅ business validations
✅ business exceptions
✅ רק פייתון סטנדרטי

מה אסור:
❌ כל תלות חיצונית (no imports מ-telegram, pymongo, aiohttp)
❌ I/O operations
❌ קריאות ל-DB
```

### Layer 4️⃣: Infrastructure (infrastructure/)
**תפקיד:** פרטים טכניים

```
מה מותר:
✅ MongoDB queries
✅ HTTP calls
✅ File I/O
✅ External APIs (GitHub, Google Drive)
✅ Caching, Encryption
✅ Email, SMS

מה אסור:
❌ לוגיקה עסקית
❌ לדעת על handlers
```

### Layer 🔀: Shared (shared/)
**תפקיד:** כלים משותפים לכל השכבות

```
מה מותר:
✅ Text utilities (truncate, format)
✅ Time utilities (parse, format)
✅ Constants
✅ Base exceptions
✅ Common types

מה אסור:
❌ לוגיקה עסקית ספציפית לפרויקט
❌ תלויות ב-framework
```

---

## 🌳 עץ תיקיות מלא - הארכיטקטורה המוצעת

```
CodeBot/
│
├── 📂 src/                           # כל קוד המקור (NEW structure)
│   │
│   ├── 📂 presentation/              # LAYER 1: Presentation
│   │   ├── 📂 telegram/              # Telegram bot handlers
│   │   │   ├── 📂 handlers/
│   │   │   │   ├── 📂 snippet/       # Snippet management
│   │   │   │   │   ├── save_handler.py
│   │   │   │   │   ├── edit_handler.py
│   │   │   │   │   ├── view_handler.py
│   │   │   │   │   ├── delete_handler.py
│   │   │   │   │   ├── search_handler.py
│   │   │   │   │   └── __init__.py
│   │   │   │   │
│   │   │   │   ├── 📂 collection/    # Collections management
│   │   │   │   │   ├── create_handler.py
│   │   │   │   │   ├── manage_handler.py
│   │   │   │   │   └── __init__.py
│   │   │   │   │
│   │   │   │   ├── 📂 integration/   # GitHub, Drive
│   │   │   │   │   ├── github_handler.py
│   │   │   │   │   ├── drive_handler.py
│   │   │   │   │   └── __init__.py
│   │   │   │   │
│   │   │   │   ├── 📂 backup/        # Backup handlers
│   │   │   │   │   ├── backup_handler.py
│   │   │   │   │   └── __init__.py
│   │   │   │   │
│   │   │   │   └── 📂 common/        # Common handlers
│   │   │   │       ├── start_handler.py
│   │   │   │       ├── help_handler.py
│   │   │   │       ├── settings_handler.py
│   │   │   │       └── __init__.py
│   │   │   │
│   │   │   ├── 📂 helpers/           # Telegram-specific helpers
│   │   │   │   ├── telegram_formatter.py  # Format messages for Telegram
│   │   │   │   ├── keyboard_builder.py    # Inline keyboards
│   │   │   │   ├── conversation_state.py  # State management
│   │   │   │   └── __init__.py
│   │   │   │
│   │   │   ├── 📂 dto/               # Data Transfer Objects
│   │   │   │   ├── snippet_dto.py
│   │   │   │   ├── user_dto.py
│   │   │   │   └── __init__.py
│   │   │   │
│   │   │   ├── bot_app.py            # Bot application setup
│   │   │   └── __init__.py
│   │   │
│   │   └── 📂 cli/                   # CLI interface (future)
│   │       └── __init__.py
│   │
│   ├── 📂 application/               # LAYER 2: Application Services
│   │   ├── 📂 services/
│   │   │   ├── snippet_service.py    # Core snippet operations
│   │   │   ├── collection_service.py # Collections logic
│   │   │   ├── search_service.py     # Search orchestration
│   │   │   ├── backup_service.py     # Backup/restore
│   │   │   ├── image_service.py      # Code image generation
│   │   │   ├── sync_service.py       # GitHub/Drive sync
│   │   │   └── __init__.py
│   │   │
│   │   ├── 📂 dto/                   # Application DTOs
│   │   │   ├── create_snippet_dto.py
│   │   │   ├── update_snippet_dto.py
│   │   │   ├── search_criteria_dto.py
│   │   │   └── __init__.py
│   │   │
│   │   └── 📂 exceptions/            # Application exceptions
│   │       ├── service_exceptions.py
│   │       └── __init__.py
│   │
│   ├── 📂 domain/                    # LAYER 3: Domain (🆕 NEW!)
│   │   ├── 📂 entities/              # Business entities
│   │   │   ├── snippet.py            # CodeSnippet entity
│   │   │   ├── large_file.py         # LargeFile entity
│   │   │   ├── collection.py         # Collection entity
│   │   │   ├── user.py               # User entity
│   │   │   └── __init__.py
│   │   │
│   │   ├── 📂 value_objects/         # Immutable values
│   │   │   ├── snippet_content.py    # Code content + metadata
│   │   │   ├── file_name.py          # Validated filename
│   │   │   ├── programming_language.py
│   │   │   └── __init__.py
│   │   │
│   │   ├── 📂 services/              # Domain services (pure logic)
│   │   │   ├── code_normalizer.py    # normalize_code()
│   │   │   ├── language_detector.py  # detect_language()
│   │   │   ├── code_analyzer.py      # analyze complexity, etc.
│   │   │   └── __init__.py
│   │   │
│   │   ├── 📂 validation/            # Business validation rules
│   │   │   ├── snippet_validator.py  # Validate snippet rules
│   │   │   ├── filename_validator.py
│   │   │   ├── code_validator.py
│   │   │   └── __init__.py
│   │   │
│   │   ├── 📂 exceptions/            # Domain exceptions
│   │   │   ├── domain_exceptions.py  # InvalidSnippet, etc.
│   │   │   └── __init__.py
│   │   │
│   │   └── 📂 interfaces/            # Repository interfaces
│   │       ├── snippet_repository_interface.py
│   │       ├── user_repository_interface.py
│   │       └── __init__.py
│   │
│   ├── 📂 infrastructure/            # LAYER 4: Infrastructure
│   │   ├── 📂 database/              # Database access
│   │   │   ├── 📂 mongodb/
│   │   │   │   ├── connection.py     # MongoDB connection manager
│   │   │   │   ├── repositories/
│   │   │   │   │   ├── snippet_repository.py  # Implements interface
│   │   │   │   │   ├── user_repository.py
│   │   │   │   │   ├── collection_repository.py
│   │   │   │   │   ├── bookmark_repository.py
│   │   │   │   │   └── __init__.py
│   │   │   │   ├── models/           # DB models (different from entities!)
│   │   │   │   │   ├── snippet_model.py
│   │   │   │   │   ├── user_model.py
│   │   │   │   │   └── __init__.py
│   │   │   │   └── __init__.py
│   │   │   └── __init__.py
│   │   │
│   │   ├── 📂 external/              # External APIs
│   │   │   ├── 📂 github/
│   │   │   │   ├── github_client.py
│   │   │   │   ├── github_mapper.py  # Map GitHub data to domain
│   │   │   │   └── __init__.py
│   │   │   ├── 📂 google_drive/
│   │   │   │   ├── drive_client.py
│   │   │   │   ├── drive_mapper.py
│   │   │   │   └── __init__.py
│   │   │   └── __init__.py
│   │   │
│   │   ├── 📂 storage/               # File storage
│   │   │   ├── file_storage.py       # Local file operations
│   │   │   ├── temp_file_manager.py
│   │   │   └── __init__.py
│   │   │
│   │   ├── 📂 cache/                 # Caching
│   │   │   ├── redis_cache.py        # Redis implementation
│   │   │   ├── memory_cache.py       # In-memory fallback
│   │   │   └── __init__.py
│   │   │
│   │   ├── 📂 security/              # Security utilities
│   │   │   ├── encryption.py         # Encrypt/decrypt tokens
│   │   │   ├── hashing.py            # Hash utilities
│   │   │   └── __init__.py
│   │   │
│   │   └── 📂 observability/         # Monitoring
│   │       ├── logging_config.py
│   │       ├── metrics.py
│   │       ├── tracing.py
│   │       └── __init__.py
│   │
│   └── 📂 shared/                    # Cross-cutting concerns
│       ├── 📂 utils/
│       │   ├── text_utils.py         # TextUtils class
│       │   ├── time_utils.py         # TimeUtils class
│       │   └── __init__.py
│       │
│       ├── 📂 constants/
│       │   ├── languages.py          # Programming languages list
│       │   ├── limits.py             # Max file size, etc.
│       │   └── __init__.py
│       │
│       ├── 📂 types/
│       │   ├── common_types.py       # Common type aliases
│       │   └── __init__.py
│       │
│       └── 📂 exceptions/
│           ├── base_exceptions.py    # Base exception classes
│           └── __init__.py
│
├── 📂 config/                        # Configuration (outside src/)
│   ├── settings.py                   # App settings
│   ├── logging.yaml
│   └── __init__.py
│
├── 📂 tests/                         # Tests mirror src/ structure
│   ├── 📂 unit/
│   │   ├── 📂 domain/
│   │   ├── 📂 application/
│   │   └── 📂 infrastructure/
│   ├── 📂 integration/
│   └── 📂 e2e/
│
├── 📂 scripts/                       # Utility scripts
│   ├── dev_seed.py
│   ├── migrate_db.py
│   └── cleanup.py
│
├── 📂 docs/                          # Documentation
├── main.py                           # Application entry point
├── requirements.txt
└── README.md
```

---

## 📚 הסבר מפורט לכל שכבה

### 1️⃣ Presentation Layer - `src/presentation/`

#### `telegram/handlers/snippet/`
**תפקיד:** ניהול conversation flows לניהול snippets

**דוגמה - `save_handler.py`:**
```python
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from application.services.snippet_service import SnippetService
from application.dto.create_snippet_dto import CreateSnippetDTO
from presentation.telegram.helpers.telegram_formatter import format_success_message

# States
GET_CODE, GET_FILENAME, GET_NOTE = range(3)

class SaveSnippetHandler:
    def __init__(self, snippet_service: SnippetService):
        self.snippet_service = snippet_service

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Entry point - רק I/O"""
        await update.message.reply_text(
            "📝 שלח לי את קטע הקוד שלך"
        )
        return GET_CODE

    async def receive_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive code - רק שמירה ב-context"""
        code = update.message.text

        # Basic validation only
        if not code or len(code) < 5:
            await update.message.reply_text("❌ הקוד קצר מדי")
            return GET_CODE

        # Store in context
        context.user_data['code'] = code

        await update.message.reply_text("💭 מה שם הקובץ?")
        return GET_FILENAME

    async def receive_filename(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive filename and save - קריאה ל-service בלבד"""
        filename = update.message.text.strip()
        code = context.user_data.get('code')
        user_id = update.effective_user.id

        # Create DTO
        dto = CreateSnippetDTO(
            user_id=user_id,
            filename=filename,
            code=code,
            note=None
        )

        # Call service - כל הלוגיקה שם!
        try:
            snippet = await self.snippet_service.create_snippet(dto)

            # Format and display
            message = format_success_message(snippet)
            await update.message.reply_text(message)

            return ConversationHandler.END

        except Exception as e:
            await update.message.reply_text(f"❌ שגיאה: {str(e)}")
            return ConversationHandler.END
```

**שים לב:**
- ✅ Handler לא יודע מה זה `normalize_code()`
- ✅ Handler לא יודע מה זה `CodeSnippet` entity
- ✅ Handler לא מדבר עם DB
- ✅ Handler רק מעביר DTO ל-service

---

### 2️⃣ Application Layer - `src/application/services/`

#### `snippet_service.py`
**תפקיד:** תזמור יצירת snippet - קורא ל-domain ול-infrastructure

```python
from typing import Optional
from application.dto.create_snippet_dto import CreateSnippetDTO
from domain.entities.snippet import Snippet
from domain.services.code_normalizer import CodeNormalizer
from domain.services.language_detector import LanguageDetector
from domain.validation.snippet_validator import SnippetValidator
from domain.exceptions.domain_exceptions import InvalidSnippetError
from infrastructure.database.mongodb.repositories.snippet_repository import SnippetRepository

class SnippetService:
    """Service layer - orchestrates domain and infrastructure"""

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
        Create a new snippet

        Orchestrates:
        1. Code normalization (domain)
        2. Language detection (domain)
        3. Validation (domain)
        4. Persistence (infrastructure)
        """
        # 1. Normalize code (domain service)
        normalized_code = self.normalizer.normalize(dto.code)

        # 2. Detect language (domain service)
        language = self.detector.detect(normalized_code, dto.filename)

        # 3. Create entity (domain)
        snippet = Snippet(
            user_id=dto.user_id,
            filename=dto.filename,
            code=normalized_code,
            language=language,
            description=dto.note or ""
        )

        # 4. Validate (domain)
        validation_result = self.validator.validate(snippet)
        if not validation_result.is_valid:
            raise InvalidSnippetError(validation_result.errors)

        # 5. Save (infrastructure)
        saved_snippet = await self.repository.save(snippet)

        return saved_snippet

    async def get_snippet(self, user_id: int, filename: str) -> Optional[Snippet]:
        """Get latest version of snippet"""
        return await self.repository.get_latest_version(user_id, filename)

    async def search_snippets(self, user_id: int, query: str, language: Optional[str] = None):
        """Search snippets - delegates to repository"""
        return await self.repository.search(user_id, query, language)
```

**שים לב:**
- ✅ Service לא יודע מה זה Telegram
- ✅ Service לא כותב SQL/MongoDB queries
- ✅ Service מתאם בין domain ל-infrastructure
- ✅ Service מטפל ב-business flow

---

### 3️⃣ Domain Layer - `src/domain/` 🆕

#### `domain/entities/snippet.py`
**תפקיד:** ייצוג עצמי עסקי של snippet

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from domain.value_objects.file_name import FileName
from domain.value_objects.programming_language import ProgrammingLanguage

@dataclass
class Snippet:
    """
    Core business entity - represents a code snippet

    Pure Python - no framework dependencies!
    """
    user_id: int
    filename: FileName  # Value object
    code: str
    language: ProgrammingLanguage  # Value object
    description: str = ""
    tags: List[str] = field(default_factory=list)
    version: int = 1
    is_favorite: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def mark_as_favorite(self) -> None:
        """Business method - mark snippet as favorite"""
        self.is_favorite = True
        self.updated_at = datetime.now(timezone.utc)

    def add_tag(self, tag: str) -> None:
        """Business method - add tag if not exists"""
        if tag and tag not in self.tags:
            self.tags.append(tag)
            self.updated_at = datetime.now(timezone.utc)

    def update_code(self, new_code: str) -> None:
        """Business method - update code and increment version"""
        if new_code != self.code:
            self.code = new_code
            self.version += 1
            self.updated_at = datetime.now(timezone.utc)
```

#### `domain/services/code_normalizer.py`
**תפקיד:** נרמול קוד - pure business logic

```python
import re
import unicodedata

class CodeNormalizer:
    """
    Domain service - normalizes code content

    Pure Python - no external dependencies!
    """

    def normalize(self, code: str) -> str:
        """
        Normalize code by removing hidden characters,
        fixing line endings, etc.

        Business rule: All code must be normalized before storage
        """
        if not code:
            return ""

        # 1. Remove unicode direction markers
        code = self._remove_direction_markers(code)

        # 2. Normalize unicode (NFC form)
        code = unicodedata.normalize('NFC', code)

        # 3. Fix line endings (to \n)
        code = code.replace('\r\n', '\n').replace('\r', '\n')

        # 4. Remove trailing whitespace per line
        lines = code.split('\n')
        lines = [line.rstrip() for line in lines]
        code = '\n'.join(lines)

        # 5. Ensure single trailing newline
        code = code.rstrip() + '\n' if code.rstrip() else ''

        return code

    def _remove_direction_markers(self, text: str) -> str:
        """Remove unicode bidirectional markers"""
        direction_chars = [
            '\u200e',  # LEFT-TO-RIGHT MARK
            '\u200f',  # RIGHT-TO-LEFT MARK
            '\u202a',  # LEFT-TO-RIGHT EMBEDDING
            '\u202b',  # RIGHT-TO-LEFT EMBEDDING
            '\u202c',  # POP DIRECTIONAL FORMATTING
            '\u202d',  # LEFT-TO-RIGHT OVERRIDE
            '\u202e',  # RIGHT-TO-LEFT OVERRIDE
        ]
        for char in direction_chars:
            text = text.replace(char, '')
        return text
```

#### `domain/validation/snippet_validator.py`
**תפקיד:** חוקי ולידציה עסקיים

```python
from dataclasses import dataclass
from typing import List
from domain.entities.snippet import Snippet

@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]

class SnippetValidator:
    """
    Domain validator - enforces business rules
    """

    MAX_CODE_LENGTH = 500_000  # 500KB
    MAX_FILENAME_LENGTH = 255
    MIN_CODE_LENGTH = 1

    def validate(self, snippet: Snippet) -> ValidationResult:
        """Validate snippet against business rules"""
        errors = []

        # Rule 1: Code length
        if len(snippet.code) < self.MIN_CODE_LENGTH:
            errors.append("Code is too short")

        if len(snippet.code) > self.MAX_CODE_LENGTH:
            errors.append(f"Code exceeds maximum length of {self.MAX_CODE_LENGTH} characters")

        # Rule 2: Filename
        if not snippet.filename.value:  # FileName is a value object
            errors.append("Filename is required")

        if len(snippet.filename.value) > self.MAX_FILENAME_LENGTH:
            errors.append(f"Filename exceeds maximum length of {self.MAX_FILENAME_LENGTH}")

        # Rule 3: No malicious patterns
        if self._contains_secrets(snippet.code):
            errors.append("Code appears to contain secrets/tokens - please remove them")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors
        )

    def _contains_secrets(self, code: str) -> bool:
        """Basic secret detection"""
        patterns = [
            r"ghp_[A-Za-z0-9]{36,}",
            r"sk_(live|test)_[0-9A-Za-z]{20,}",
            r"-----BEGIN (RSA |EC |)PRIVATE KEY-----",
        ]
        for pattern in patterns:
            if re.search(pattern, code):
                return True
        return False
```

**שים לב:**
- ✅ Pure Python - אפשר להריץ בלי Telegram, בלי DB
- ✅ קל לבדוק - `assert normalizer.normalize("  code  ") == "code\n"`
- ✅ ניתן לשימוש חוזר (CLI, API, tests)
- ✅ אין תלויות ב-frameworks

---

### 4️⃣ Infrastructure Layer - `src/infrastructure/`

#### `infrastructure/database/mongodb/repositories/snippet_repository.py`
**תפקיד:** מימוש ה-repository interface עבור MongoDB

```python
from typing import Optional, List
from datetime import datetime, timezone
from domain.entities.snippet import Snippet
from domain.interfaces.snippet_repository_interface import ISnippetRepository
from infrastructure.database.mongodb.connection import get_collection
from infrastructure.database.mongodb.models.snippet_model import SnippetModel

class SnippetRepository(ISnippetRepository):
    """
    MongoDB implementation of snippet repository

    Implements domain interface
    """

    def __init__(self, db_manager):
        self.collection = get_collection('code_snippets')

    async def save(self, snippet: Snippet) -> Snippet:
        """Save snippet to MongoDB"""
        # Map domain entity → DB model
        db_model = SnippetModel.from_entity(snippet)

        # Check if exists (for versioning)
        existing = await self._get_latest(snippet.user_id, snippet.filename.value)
        if existing:
            db_model.version = existing['version'] + 1

        # Insert
        result = await self.collection.insert_one(db_model.to_dict())

        # Map back: DB model → domain entity
        saved_doc = await self.collection.find_one({'_id': result.inserted_id})
        return SnippetModel.to_entity(saved_doc)

    async def get_latest_version(self, user_id: int, filename: str) -> Optional[Snippet]:
        """Get latest version of snippet"""
        doc = await self._get_latest(user_id, filename)
        if not doc:
            return None

        return SnippetModel.to_entity(doc)

    async def search(self, user_id: int, query: str, language: Optional[str] = None) -> List[Snippet]:
        """Search snippets - MongoDB text search"""
        filter_query = {
            'user_id': user_id,
            'is_active': True
        }

        if query:
            filter_query['$text'] = {'$search': query}

        if language:
            filter_query['programming_language'] = language

        # Aggregate to get latest versions only
        pipeline = [
            {'$match': filter_query},
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {
                '_id': '$file_name',
                'latest': {'$first': '$$ROOT'}
            }},
            {'$replaceRoot': {'newRoot': '$latest'}},
            {'$limit': 50}
        ]

        docs = await self.collection.aggregate(pipeline).to_list(None)

        # Map to entities
        return [SnippetModel.to_entity(doc) for doc in docs]

    async def _get_latest(self, user_id: int, filename: str):
        """Internal helper - get latest document"""
        return await self.collection.find_one(
            {
                'user_id': user_id,
                'file_name': filename,
                'is_active': True
            },
            sort=[('version', -1)]
        )
```

#### `infrastructure/database/mongodb/models/snippet_model.py`
**תפקיד:** מיפוי בין domain entity ל-MongoDB document

```python
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any
from domain.entities.snippet import Snippet
from domain.value_objects.file_name import FileName
from domain.value_objects.programming_language import ProgrammingLanguage

@dataclass
class SnippetModel:
    """
    Database model - MongoDB document structure

    Different from domain entity!
    """
    user_id: int
    file_name: str  # Plain string in DB
    code: str
    programming_language: str  # Plain string in DB
    description: str
    tags: list
    version: int
    is_favorite: bool
    created_at: datetime
    updated_at: datetime
    is_active: bool = True
    _id: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to MongoDB document"""
        data = asdict(self)
        if self._id is None:
            data.pop('_id', None)
        return data

    @staticmethod
    def from_entity(snippet: Snippet) -> 'SnippetModel':
        """Map domain entity → DB model"""
        return SnippetModel(
            user_id=snippet.user_id,
            file_name=snippet.filename.value,  # Extract value from value object
            code=snippet.code,
            programming_language=snippet.language.value,  # Extract value
            description=snippet.description,
            tags=snippet.tags.copy(),
            version=snippet.version,
            is_favorite=snippet.is_favorite,
            created_at=snippet.created_at,
            updated_at=snippet.updated_at,
            is_active=True
        )

    @staticmethod
    def to_entity(doc: Dict[str, Any]) -> Snippet:
        """Map DB document → domain entity"""
        return Snippet(
            user_id=doc['user_id'],
            filename=FileName(doc['file_name']),  # Wrap in value object
            code=doc['code'],
            language=ProgrammingLanguage(doc['programming_language']),  # Wrap
            description=doc.get('description', ''),
            tags=doc.get('tags', []),
            version=doc.get('version', 1),
            is_favorite=doc.get('is_favorite', False),
            created_at=doc['created_at'],
            updated_at=doc['updated_at']
        )
```

**שים לב:**
- ✅ Infrastructure יודע על MongoDB
- ✅ Infrastructure מממש את ה-interface מ-domain
- ✅ יש הפרדה בין DB model ל-domain entity
- ✅ Mapping layer מנטרל שינויים ב-DB structure

---

## 🗺️ מיפוי קבצים קיימים → שכבות חדשות

### טבלת מיפוי מלאה

| קובץ נוכחי | שורות | → יעד חדש | הערות |
|------------|-------|-----------|-------|
| **handlers/** | | | |
| `handlers/save_flow.py` | 498 | `presentation/telegram/handlers/snippet/save_handler.py` | ✂️ הפרד logic ל-service |
| `handlers/file_view.py` | 1,406 | `presentation/telegram/handlers/snippet/view_handler.py` | ✂️ הפרד logic ל-service |
| `handlers/documents.py` | 982 | `presentation/telegram/handlers/snippet/document_handler.py` | ✂️ הפרד file logic |
| `handlers/states.py` | 19 | `presentation/telegram/handlers/common/states.py` | ✅ העתק כמות שהוא |
| `handlers/pagination.py` | 30 | `presentation/telegram/helpers/pagination.py` | ✅ העתק |
| `handlers/github/menu.py` | - | `presentation/telegram/handlers/integration/github_handler.py` | |
| `handlers/drive/menu.py` | - | `presentation/telegram/handlers/integration/drive_handler.py` | |
| **services/** | | | |
| `services/code_service.py` | 238 | ✂️ פצל ל-2: | |
| | | `application/services/snippet_service.py` | חלק orchestration |
| | | `domain/services/language_detector.py` | חלק pure logic |
| `services/image_generator.py` | 721 | `application/services/image_service.py` | ✅ כמעט מוכן |
| `services/google_drive_service.py` | 1,033 | `infrastructure/external/google_drive/drive_client.py` | Infrastructure! |
| `services/github_service.py` | 12 | `infrastructure/external/github/github_client.py` | Infrastructure! |
| `services/backup_service.py` | 21 | `application/services/backup_service.py` | ✅ כמעט מוכן |
| `services/snippet_library_service.py` | 1,102 | `application/services/snippet_library_service.py` | ✂️ הפרד domain logic |
| **database/** | | | |
| `database/repository.py` | 1,960 | ✂️ פצל לפי אחריות: | **קובץ ענק!** |
| | | `infrastructure/database/mongodb/repositories/snippet_repository.py` | Snippets |
| | | `infrastructure/database/mongodb/repositories/user_repository.py` | Users |
| | | `infrastructure/database/mongodb/repositories/collection_repository.py` | Collections |
| `database/models.py` | 95 | ✂️ פצל: | |
| | | `domain/entities/snippet.py` | Domain entity |
| | | `infrastructure/database/mongodb/models/snippet_model.py` | DB model |
| `database/manager.py` | 815 | `infrastructure/database/mongodb/connection.py` | ✅ כמעט מוכן |
| `database/collections_manager.py` | 1,245 | `infrastructure/database/mongodb/repositories/collection_repository.py` | |
| `database/bookmarks_manager.py` | 875 | `infrastructure/database/mongodb/repositories/bookmark_repository.py` | |
| **utils.py** | 1,437 | ✂️✂️✂️ פצל ל-7: | **הקובץ הכי בעייתי!** |
| | | `domain/services/code_normalizer.py` | normalize_code() |
| | | `domain/validation/code_validator.py` | validate_* functions |
| | | `shared/utils/text_utils.py` | TextUtils class |
| | | `shared/utils/time_utils.py` | TimeUtils class |
| | | `presentation/telegram/helpers/telegram_formatter.py` | TelegramUtils |
| | | `infrastructure/storage/file_utils.py` | FileUtils |
| | | `infrastructure/security/hashing.py` | SecurityUtils |
| **conversation_handlers.py** | 231KB | ✂️✂️✂️ פצל לפי features: | **מונסטר!** |
| | | `presentation/telegram/handlers/snippet/*.py` | Save, edit, view, search |
| | | `presentation/telegram/handlers/collection/*.py` | Collection handlers |
| | | `presentation/telegram/handlers/integration/*.py` | GitHub, Drive |
| **bot_handlers.py** | 183KB | ✂️✂️✂️ פצל: | **מונסטר!** |
| | | `presentation/telegram/handlers/common/*.py` | Start, help, settings |
| | | `presentation/telegram/handlers/*/*.py` | Feature handlers |
| **main.py** | 192KB | ✂️ פצל: | **מונסטר!** |
| | | `main.py` (slim) | Entry point only |
| | | `presentation/telegram/bot_app.py` | Bot setup |
| | | `config/settings.py` | Configuration |

### סיכום סטטיסטי

```
📊 פיצול קבצים:
├── קבצים שנשארים כמעט ללא שינוי: 5
├── קבצים שמועברים עם שינויים קלים: 8
├── קבצים שמפוצלים ל-2-3 חלקים: 6
└── קבצים שמפוצלים ל-4+ חלקים: 4 (utils.py, conversation_handlers.py, bot_handlers.py, main.py)

📦 תוצאה:
├── קבצים לפני: ~50
└── קבצים אחרי: ~80-100 (אבל קטנים ומאורגנים!)
```

---

## 🔗 תלויות בין שכבות

### חוקי התלויות

```
┌─────────────────────────┐
│   Presentation          │  ─┐
├─────────────────────────┤   │
│   Application           │  ─┤ יכול לדבר עם →
├─────────────────────────┤   │
│   Domain                │  ─┤
├─────────────────────────┤   │
│   Infrastructure        │  ─┘
└─────────────────────────┘

Domain ← Infrastructure (implements interfaces)
       ↑ (depends on)
```

### מטריצת תלויות

|  | Presentation | Application | Domain | Infrastructure | Shared |
|---|:---:|:---:|:---:|:---:|:---:|
| **Presentation** | - | ✅ Use | ❌ No | ❌ No | ✅ Use |
| **Application** | ❌ No | - | ✅ Use | ✅ Use | ✅ Use |
| **Domain** | ❌ No | ❌ No | - | ❌ No | ✅ Use (limited) |
| **Infrastructure** | ❌ No | ❌ No | ✅ Implements | - | ✅ Use |
| **Shared** | ❌ No | ❌ No | ❌ No | ❌ No | - |

### דוגמאות ייבוא נכונות

```python
# ✅ Presentation → Application
from application.services.snippet_service import SnippetService

# ✅ Application → Domain
from domain.services.code_normalizer import CodeNormalizer
from domain.entities.snippet import Snippet

# ✅ Application → Infrastructure
from infrastructure.database.mongodb.repositories.snippet_repository import SnippetRepository

# ✅ Infrastructure → Domain (implements)
from domain.interfaces.snippet_repository_interface import ISnippetRepository

# ✅ Any → Shared
from shared.utils.text_utils import TextUtils

# ❌ Domain → Infrastructure (WRONG!)
from infrastructure.database.mongodb.connection import db

# ❌ Domain → Presentation (WRONG!)
from presentation.telegram.helpers.telegram_formatter import format_message

# ❌ Infrastructure → Application (WRONG!)
from application.services.snippet_service import SnippetService
```

---

## 🎯 סיכום חלק 2

### מה קיבלנו?

1. **ארכיטקטורה ברורה ב-4 שכבות** + shared
2. **עץ תיקיות מפורט** עם 80-100 קבצים מאורגנים
3. **הפרדת אחריות** - כל קובץ עם תפקיד אחד
4. **מיפוי מדויק** של כל קובץ קיים ליעד
5. **חוקי תלויות** ברורים

### מה הלאה?

**בחלק 3** נראה:
- 📏 כללי הפרדת שכבות מפורטים
- 💻 דוגמאות קוד: לפני ← אחרי
- ✅ Checklist לכל שכבה
- 🧪 איך לבדוק שלא עברנו גבולות

**בחלק 4** נראה:
- 🗺️ מפת דרכים מעשית (5 שלבים)
- 🔄 רפקטור הדרגתי
- 📝 דוגמה מלאה: save_flow מקצה לקצה
- ✅ אסטרטגיית בדיקות

---

*מסמך זה נוצר ב-18/11/2024 - CodeBot Architecture Refactoring Initiative - Part 2*
