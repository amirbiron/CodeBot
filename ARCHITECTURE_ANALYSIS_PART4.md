# מדריך ארכיטקטורה שכבתית - CodeBot
## חלק 4: מפת דרכים לרפקטור ודוגמה מלאה

---

## 📋 תוכן עניינים - חלק 4
1. [מפת דרכים ב-5 שלבים](#מפת-דרכים)
2. [שלב 1: סידור תיקיות והזזת קבצים](#שלב-1)
3. [שלב 2: פיצול utils.py](#שלב-2)
4. [שלב 3: יצירת שכבת Domain](#שלב-3)
5. [שלב 4: רפקטור Services ו-Repositories](#שלב-4)
6. [שלב 5: רפקטור Handlers](#שלב-5)
7. [דוגמה מלאה: Save Flow מקצה לקצה](#דוגמה-מלאה)
8. [כלים ו-Automation](#כלים)
9. [FAQ - שאלות נפוצות](#faq)

---

## 🗺️ מפת דרכים ב-5 שלבים

### סקירה כללית

```
שלב 1: תיקיות + העברות בסיסיות      [1-2 שבועות]  🟢 Low Risk
    ↓
שלב 2: פיצול utils.py                 [2-3 שבועות]  🟡 Medium Risk
    ↓
שלב 3: יצירת שכבת Domain              [3-4 שבועות]  🟡 Medium Risk
    ↓
שלב 4: רפקטור Services + Repositories [3-4 שבועות]  🟠 High Risk
    ↓
שלב 5: רפקטור Handlers                [4-5 שבועות]  🟠 High Risk

📅 סה"כ: 13-18 שבועות (3-4.5 חודשים)
```

### עקרונות לכל שלב

✅ **כלל 1:** כל שלב = PR אחד (או מספר PRים קטנים)
✅ **כלל 2:** לא ממשיכים לשלב הבא עד שהקודם stable
✅ **כלל 3:** כל שלב חייב לעבור:
   - ✅ All tests pass
   - ✅ Code review
   - ✅ QA testing (manual)
   - ✅ Deploy to staging
   - ✅ Monitor for 2-3 days

✅ **כלל 4:** תמיד יש rollback plan
✅ **כלל 5:** לא משנים behavior - רק structure

---

## 📦 שלב 1: סידור תיקיות והזזת קבצים

**מטרה:** ליצור את המבנה הבסיסי בלי לשנות קוד

**משך זמן:** 1-2 שבועות
**רמת סיכון:** 🟢 נמוכה

### 1.1 יצירת מבנה תיקיות

```bash
# צור את המבנה החדש
mkdir -p src/presentation/telegram/handlers
mkdir -p src/presentation/telegram/helpers
mkdir -p src/application/services
mkdir -p src/application/dto
mkdir -p src/domain/entities
mkdir -p src/domain/services
mkdir -p src/domain/validation
mkdir -p src/infrastructure/database/mongodb/repositories
mkdir -p src/infrastructure/database/mongodb/models
mkdir -p src/infrastructure/external/github
mkdir -p src/infrastructure/external/google_drive
mkdir -p src/shared/utils
```

### 1.2 העתקת קבצים (לא הזזה!)

**שלב ביניים: קבצים קיימים במקומם + עותקים חדשים**

```bash
# העתק handlers (לא מעביר!)
cp handlers/states.py src/presentation/telegram/handlers/common/states.py
cp handlers/pagination.py src/presentation/telegram/helpers/pagination.py

# העתק services
cp services/backup_service.py src/application/services/backup_service.py
cp services/image_generator.py src/application/services/image_service.py

# העתק database
cp database/models.py src/infrastructure/database/mongodb/models/snippet_model.py
cp database/manager.py src/infrastructure/database/mongodb/connection.py
```

**למה העתקה ולא הזזה?**
- ✅ המערכת ממשיכה לעבוד
- ✅ אפשר לבדוק את החדש בלי לשבור את הישן
- ✅ Rollback קל
- ✅ בשלב הבא נעביר את הקריאות למקום החדש ואז נמחק את הישן

### 1.3 עדכון imports בקבצים החדשים

```python
# src/presentation/telegram/helpers/pagination.py
# לפני:
from handlers.states import SOME_STATE

# אחרי:
from src.presentation.telegram.handlers.common.states import SOME_STATE
```

### 1.4 בדיקות

```bash
# וודא שהכל עובד
pytest tests/

# הרץ בוט באופן מקומי
python main.py

# בדוק שכל הפונקציות עובדות
```

### ✅ Checklist שלב 1

- [ ] כל התיקיות נוצרו
- [ ] קבצים הועתקו (לא הוזזו)
- [ ] imports תוקנו בקבצים החדשים
- [ ] כל הטסטים עוברים
- [ ] הבוט עובד מקומית
- [ ] PR נוצר ועבר review
- [ ] Deploy ל-staging
- [ ] Monitor 2-3 ימים

### 📝 PR Template לשלב 1

```markdown
## שלב 1: מבנה תיקיות בסיסי

### מה עשינו?
- יצרנו מבנה תיקיות חדש תחת `src/`
- העתקנו קבצים למקומות החדשים (לא מחקנו ישנים)
- תיקנו imports בקבצים החדשים

### מה לא שינינו?
- ❌ לא שינינו לוגיקה
- ❌ לא מחקנו קבצים ישנים
- ❌ לא שינינו behavior

### איך לבדוק?
1. הרץ `pytest tests/`
2. הרץ בוט מקומית
3. בדוק features: save, view, search

### Rollback Plan
מחק את `src/` - הכל ממשיך לעבוד מהתיקיות הישנות
```

---

## ✂️ שלב 2: פיצול utils.py

**מטרה:** לפצל את utils.py ל-7 קבצים נפרדים

**משך זמן:** 2-3 שבועות
**רמת סיכון:** 🟡 בינונית

### 2.1 ניתוח utils.py

```python
# utils.py נוכחי (1,437 שורות):
#
# שורות 71-149:   CodeErrorLogger
# שורות 151-256:  TimeUtils
# שורות 258-375:  TextUtils
# שורות 400-600:  TelegramUtils
# שורות 650-850:  FileUtils
# שורות 900-1100: CodeUtils (normalize_code, etc.)
# שורות 1100-1437: ValidationUtils, SecurityUtils
```

### 2.2 תכנית פיצול

```
utils.py (1,437 שורות)
    ↓
    ├── domain/services/code_normalizer.py       (normalize_code)
    ├── domain/validation/code_validator.py      (validate_*)
    ├── shared/utils/text_utils.py               (TextUtils)
    ├── shared/utils/time_utils.py               (TimeUtils)
    ├── presentation/telegram/helpers/telegram_formatter.py (TelegramUtils)
    ├── infrastructure/storage/file_utils.py     (FileUtils)
    └── infrastructure/security/hashing.py       (SecurityUtils)
```

### 2.3 פיצול הדרגתי - תת-שלבים

#### Sub-step 2.1: הוצא CodeNormalizer (הכי פשוט)

```python
# 1. צור קובץ חדש
# src/domain/services/code_normalizer.py
import unicodedata

class CodeNormalizer:
    def normalize(self, code: str) -> str:
        # העתק את הלוגיקה מ-utils.py
        if not code:
            return ""

        code = self._remove_bidi(code)
        code = unicodedata.normalize('NFC', code)
        code = code.replace('\r\n', '\n').replace('\r', '\n')

        lines = [line.rstrip() for line in code.split('\n')]
        code = '\n'.join(lines)

        return code.rstrip() + '\n' if code.rstrip() else ''

    def _remove_bidi(self, text: str) -> str:
        markers = ['\u200e', '\u200f', '\u202a', '\u202b', '\u202c']
        for m in markers:
            text = text.replace(m, '')
        return text
```

```python
# 2. צור wrapper ב-utils.py (backwards compatibility)
# utils.py
from src.domain.services.code_normalizer import CodeNormalizer

_normalizer = CodeNormalizer()

def normalize_code(code: str) -> str:
    """
    DEPRECATED: Use CodeNormalizer directly

    This function is kept for backwards compatibility.
    Will be removed in future version.
    """
    return _normalizer.normalize(code)
```

```python
# 3. עדכן קבצים שמשתמשים - אחד אחד!
# handlers/save_flow.py
# לפני:
from utils import normalize_code

# אחרי:
from src.domain.services.code_normalizer import CodeNormalizer

class SaveHandler:
    def __init__(self):
        self.normalizer = CodeNormalizer()

    async def process(self, code):
        normalized = self.normalizer.normalize(code)
```

**איך לבדוק:**
```python
# tests/unit/domain/services/test_code_normalizer.py
def test_normalize_removes_bidi():
    normalizer = CodeNormalizer()
    result = normalizer.normalize("hello\u200eworld")
    assert result == "helloworld\n"

def test_normalize_idempotent():
    normalizer = CodeNormalizer()
    code = "test  \r\n"
    assert normalizer.normalize(normalizer.normalize(code)) == normalizer.normalize(code)
```

#### Sub-step 2.2: הוצא TextUtils

```python
# src/shared/utils/text_utils.py
class TextUtils:
    @staticmethod
    def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
        # העתק מ-utils.py
        if len(text) <= max_length:
            return text
        return text[:max_length - len(suffix)] + suffix

    @staticmethod
    def escape_markdown(text: str, version: int = 2) -> str:
        # העתק מ-utils.py
        if version == 2:
            special_chars = set("_*[]()~`>#+-=|{}.!\\")
            return "".join(("\\" + ch) if ch in special_chars else ch for ch in text)
        else:
            special_chars = set("_*`[()\\")
            return "".join(("\\" + ch) if ch in special_chars else ch for ch in text)
```

```python
# utils.py - wrapper
from src.shared.utils.text_utils import TextUtils as _TextUtils

TextUtils = _TextUtils  # Backwards compatibility
```

#### Sub-step 2.3-2.7: חזור על השלבים לשאר

כל קלאס/מודול:
1. העתק לקובץ חדש
2. כתוב tests
3. צור wrapper ב-utils.py
4. עדכן משתמשים אחד אחד
5. בדוק שהכל עובד

### 2.4 מחיקת utils.py (שלב אחרון!)

**רק אחרי** שכל הקריאות עברו למקומות החדשים:

```bash
# מצא כל הקריאות ל-utils
grep -r "from utils import" . --include="*.py"
grep -r "import utils" . --include="*.py"

# אם אין תוצאות (או רק tests ישנים):
git rm utils.py
```

### ✅ Checklist שלב 2

- [ ] CodeNormalizer עבר למקום חדש
- [ ] TextUtils עבר
- [ ] TimeUtils עבר
- [ ] TelegramUtils עבר (→ telegram_formatter.py)
- [ ] FileUtils עבר
- [ ] SecurityUtils עבר
- [ ] ValidationUtils עבר
- [ ] כל הקריאות מ-utils.py עודכנו
- [ ] utils.py נמחק
- [ ] כל הטסטים עוברים
- [ ] Deploy + monitor

---

## 🎯 שלב 3: יצירת שכבת Domain

**מטרה:** להפריד business logic ל-domain layer

**משך זמן:** 3-4 שבועות
**רמת סיכון:** 🟡 בינונית

### 3.1 יצירת Entities

```python
# src/domain/entities/snippet.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from domain.value_objects.file_name import FileName
from domain.value_objects.programming_language import ProgrammingLanguage

@dataclass
class Snippet:
    """
    Domain entity - represents a code snippet

    This is the BUSINESS representation.
    Different from DB model!
    """
    user_id: int
    filename: FileName
    code: str
    language: ProgrammingLanguage
    description: str = ""
    tags: List[str] = field(default_factory=list)
    version: int = 1
    is_favorite: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Business methods
    def mark_as_favorite(self) -> None:
        """Business rule: marking as favorite updates timestamp"""
        self.is_favorite = True
        self.updated_at = datetime.now(timezone.utc)

    def add_tag(self, tag: str) -> None:
        """Business rule: no duplicate tags"""
        if tag and tag not in self.tags:
            self.tags.append(tag)
            self.updated_at = datetime.now(timezone.utc)

    def update_code(self, new_code: str) -> None:
        """Business rule: updating code increments version"""
        if new_code != self.code:
            self.code = new_code
            self.version += 1
            self.updated_at = datetime.now(timezone.utc)
```

### 3.2 יצירת Value Objects

```python
# src/domain/value_objects/file_name.py
from dataclasses import dataclass
import re

@dataclass(frozen=True)  # Immutable!
class FileName:
    """
    Value object - represents a valid filename

    Business rules:
    - Not empty
    - Max 255 characters
    - No invalid characters
    - Must have extension
    """
    value: str

    def __post_init__(self):
        """Validate on creation"""
        if not self.value:
            raise ValueError("Filename cannot be empty")

        if len(self.value) > 255:
            raise ValueError("Filename too long (max 255)")

        if not re.match(r'^[\w\.\-\_]+\.[a-zA-Z0-9]+$', self.value):
            raise ValueError(f"Invalid filename format: {self.value}")

    @property
    def extension(self) -> str:
        """Get file extension"""
        return self.value.split('.')[-1].lower()

    @property
    def name_without_extension(self) -> str:
        """Get name without extension"""
        return '.'.join(self.value.split('.')[:-1])
```

```python
# src/domain/value_objects/programming_language.py
from dataclasses import dataclass
from typing import Set

@dataclass(frozen=True)
class ProgrammingLanguage:
    """Value object - represents a programming language"""
    value: str

    SUPPORTED_LANGUAGES: Set[str] = {
        'python', 'javascript', 'typescript', 'java', 'cpp',
        'c', 'csharp', 'go', 'rust', 'ruby', 'php', 'swift',
        'kotlin', 'scala', 'sql', 'html', 'css', 'bash'
    }

    def __post_init__(self):
        if self.value.lower() not in self.SUPPORTED_LANGUAGES:
            # Don't fail - just mark as 'other'
            object.__setattr__(self, 'value', 'other')

    @property
    def is_supported(self) -> bool:
        return self.value in self.SUPPORTED_LANGUAGES
```

### 3.3 יצירת Domain Services

כבר עשינו ב-שלב 2:
- ✅ `CodeNormalizer`

צריך להוסיף:

```python
# src/domain/services/language_detector.py
class LanguageDetector:
    """Domain service - detect programming language"""

    EXTENSION_MAP = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.cpp': 'cpp',
        '.c': 'c',
        # ... עוד
    }

    def detect(self, code: str, filename: str) -> str:
        """
        Detect language from code and filename

        Business rules:
        1. First try by extension
        2. Then by content analysis
        3. Default to 'text'
        """
        # Try extension
        for ext, lang in self.EXTENSION_MAP.items():
            if filename.lower().endswith(ext):
                return lang

        # Try content (simple heuristics)
        if 'def ' in code and 'import ' in code:
            return 'python'

        if 'function' in code and ('const ' in code or 'let ' in code):
            return 'javascript'

        # Default
        return 'text'
```

### 3.4 יצירת Repository Interfaces

```python
# src/domain/interfaces/snippet_repository_interface.py
from abc import ABC, abstractmethod
from typing import Optional, List
from domain.entities.snippet import Snippet

class ISnippetRepository(ABC):
    """
    Repository interface - defined by domain
    Implemented by infrastructure
    """

    @abstractmethod
    async def save(self, snippet: Snippet) -> Snippet:
        """Save snippet and return with ID"""
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
    async def search(
        self,
        user_id: int,
        query: str,
        language: Optional[str] = None
    ) -> List[Snippet]:
        """Search snippets"""
        pass

    @abstractmethod
    async def delete(self, snippet_id: str) -> bool:
        """Soft delete snippet"""
        pass
```

### ✅ Checklist שלב 3

- [ ] Entities נוצרו (Snippet, User, Collection)
- [ ] Value Objects נוצרו (FileName, ProgrammingLanguage)
- [ ] Domain Services נוצרו (CodeNormalizer, LanguageDetector)
- [ ] Repository Interfaces הוגדרו
- [ ] Domain Validators נוצרו
- [ ] Domain Exceptions הוגדרו
- [ ] Tests ל-domain (100% coverage!)
- [ ] אין תלויות חיצוניות ב-domain
- [ ] Deploy + monitor

---

## 🔧 שלב 4: רפקטור Services ו-Repositories

**מטרה:** להפריד application logic מ-infrastructure

**משך זמן:** 3-4 שבועות
**רמת סיכון:** 🟠 גבוהה

### 4.1 יצירת Application Services

```python
# src/application/services/snippet_service.py
from typing import Optional, List

from application.dto.create_snippet_dto import CreateSnippetDTO
from application.dto.update_snippet_dto import UpdateSnippetDTO
from application.exceptions.service_exceptions import (
    SnippetNotFoundError,
    InvalidSnippetError
)

from domain.entities.snippet import Snippet
from domain.services.code_normalizer import CodeNormalizer
from domain.services.language_detector import LanguageDetector
from domain.validation.snippet_validator import SnippetValidator
from domain.value_objects.file_name import FileName
from domain.value_objects.programming_language import ProgrammingLanguage
from domain.interfaces.snippet_repository_interface import ISnippetRepository


class SnippetService:
    """
    Application service - orchestrates use cases

    Responsibilities:
    - Coordinate domain + infrastructure
    - DTO → Entity conversion
    - Transaction management
    - Error handling
    """

    def __init__(
        self,
        snippet_repository: ISnippetRepository,
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
        Use case: Create new snippet

        Flow:
        1. Normalize code (domain)
        2. Detect language (domain)
        3. Create entity (domain)
        4. Validate (domain)
        5. Save (infrastructure)
        """
        # 1. Normalize
        normalized_code = self.normalizer.normalize(dto.code)

        # 2. Detect language
        language = self.detector.detect(normalized_code, dto.filename)

        # 3. Create entity
        snippet = Snippet(
            user_id=dto.user_id,
            filename=FileName(dto.filename),
            code=normalized_code,
            language=ProgrammingLanguage(language),
            description=dto.note or "",
            tags=dto.tags or []
        )

        # 4. Validate
        validation_result = self.validator.validate(snippet)
        if not validation_result.is_valid:
            raise InvalidSnippetError(
                message="Snippet validation failed",
                errors=validation_result.errors
            )

        # 5. Save
        saved_snippet = await self.repository.save(snippet)

        return saved_snippet

    async def get_snippet(self, user_id: int, filename: str) -> Optional[Snippet]:
        """Use case: Get snippet by filename"""
        return await self.repository.get_latest_version(user_id, filename)

    async def update_snippet(self, dto: UpdateSnippetDTO) -> Snippet:
        """Use case: Update existing snippet"""
        # Get existing
        existing = await self.repository.get_by_id(dto.snippet_id)
        if not existing:
            raise SnippetNotFoundError(f"Snippet {dto.snippet_id} not found")

        # Update code if provided
        if dto.new_code:
            normalized = self.normalizer.normalize(dto.new_code)
            existing.update_code(normalized)  # Business method!

        # Update description
        if dto.new_description is not None:
            existing.description = dto.new_description

        # Validate
        validation_result = self.validator.validate(existing)
        if not validation_result.is_valid:
            raise InvalidSnippetError(
                message="Updated snippet validation failed",
                errors=validation_result.errors
            )

        # Save
        return await self.repository.save(existing)

    async def search_snippets(
        self,
        user_id: int,
        query: str,
        language: Optional[str] = None
    ) -> List[Snippet]:
        """Use case: Search snippets"""
        return await self.repository.search(user_id, query, language)
```

### 4.2 יצירת DTOs

```python
# src/application/dto/create_snippet_dto.py
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class CreateSnippetDTO:
    """
    DTO for creating snippet

    Transfer data from presentation → application
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
```

### 4.3 רפקטור Repositories

```python
# src/infrastructure/database/mongodb/repositories/snippet_repository.py
from typing import Optional, List
from datetime import datetime, timezone

from domain.entities.snippet import Snippet
from domain.interfaces.snippet_repository_interface import ISnippetRepository
from infrastructure.database.mongodb.models.snippet_model import SnippetModel


class MongoSnippetRepository(ISnippetRepository):
    """
    MongoDB implementation of snippet repository

    Implements interface from domain
    NO business logic here!
    """

    def __init__(self, db_manager):
        self.collection = db_manager.get_collection('code_snippets')

    async def save(self, snippet: Snippet) -> Snippet:
        """
        Save snippet to MongoDB

        NO normalization, NO validation - already done!
        """
        # Map entity → DB model
        db_model = SnippetModel.from_entity(snippet)

        # Check for existing (versioning logic)
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

    async def get_by_id(self, snippet_id: str) -> Optional[Snippet]:
        """Get by MongoDB _id"""
        from bson import ObjectId

        doc = await self.collection.find_one({'_id': ObjectId(snippet_id)})

        if not doc:
            return None

        return SnippetModel.to_entity(doc)

    async def get_latest_version(
        self,
        user_id: int,
        filename: str
    ) -> Optional[Snippet]:
        """Get latest version"""
        doc = await self._find_latest(user_id, filename)

        if not doc:
            return None

        return SnippetModel.to_entity(doc)

    async def search(
        self,
        user_id: int,
        query: str,
        language: Optional[str] = None
    ) -> List[Snippet]:
        """Search using MongoDB text search"""
        match_filter = {
            'user_id': user_id,
            'is_active': True
        }

        if query:
            match_filter['$text'] = {'$search': query}

        if language:
            match_filter['programming_language'] = language

        # Aggregate to get latest versions only
        pipeline = [
            {'$match': match_filter},
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {
                '_id': '$file_name',
                'latest': {'$first': '$$ROOT'}
            }},
            {'$replaceRoot': {'newRoot': '$latest'}},
            {'$limit': 50}
        ]

        docs = await self.collection.aggregate(pipeline).to_list(None)

        return [SnippetModel.to_entity(doc) for doc in docs]

    async def delete(self, snippet_id: str) -> bool:
        """Soft delete"""
        from bson import ObjectId

        result = await self.collection.update_one(
            {'_id': ObjectId(snippet_id)},
            {
                '$set': {
                    'is_active': False,
                    'deleted_at': datetime.now(timezone.utc)
                }
            }
        )

        return result.modified_count > 0

    async def _find_latest(self, user_id: int, filename: str):
        """Internal helper"""
        return await self.collection.find_one(
            {
                'user_id': user_id,
                'file_name': filename,
                'is_active': True
            },
            sort=[('version', -1)]
        )
```

### 4.4 Mapping Layer (Entity ↔ DB Model)

```python
# src/infrastructure/database/mongodb/models/snippet_model.py
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any

from domain.entities.snippet import Snippet
from domain.value_objects.file_name import FileName
from domain.value_objects.programming_language import ProgrammingLanguage


@dataclass
class SnippetModel:
    """
    Database model - MongoDB document

    This is different from domain entity!
    Used only for DB storage.
    """
    user_id: int
    file_name: str  # Plain string
    code: str
    programming_language: str  # Plain string
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
        """
        Map domain entity → DB model

        Extract values from value objects
        """
        return SnippetModel(
            user_id=snippet.user_id,
            file_name=snippet.filename.value,  # Extract from FileName
            code=snippet.code,
            programming_language=snippet.language.value,  # Extract from ProgrammingLanguage
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
        """
        Map DB document → domain entity

        Wrap plain values in value objects
        """
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

### ✅ Checklist שלב 4

- [ ] Application services נוצרו (SnippetService, CollectionService, etc.)
- [ ] DTOs נוצרו לכל use case
- [ ] Repositories ממשים interfaces
- [ ] Mapping layer (Entity ↔ DB Model)
- [ ] אין business logic ב-repositories
- [ ] אין DB queries ב-services
- [ ] Tests לכל שכבה
- [ ] Integration tests
- [ ] Deploy + monitor

---

## 🎨 שלב 5: רפקטור Handlers

**מטרה:** להפוך handlers ל-thin layer

**משך זמן:** 4-5 שבועות
**רמת סיכון:** 🟠 גבוהה

### 5.1 רפקטור Handler אחד (דוגמה)

**לפני:**
```python
# handlers/save_flow.py (498 שורות)
async def save_file_final(update, context, filename, user_id):
    code = context.user_data.get('code_to_save')

    # Business logic
    code = normalize_code(code)

    # More business logic
    detected_language = code_service.detect_language(code, filename)

    # DB access
    from database import db, CodeSnippet
    snippet = CodeSnippet(...)
    success = db.save_code_snippet(snippet)

    # ...
```

**אחרי:**
```python
# src/presentation/telegram/handlers/snippet/save_handler.py
from application.services.snippet_service import SnippetService
from application.dto.create_snippet_dto import CreateSnippetDTO

class SaveSnippetHandler:
    def __init__(self, snippet_service: SnippetService):
        self.snippet_service = snippet_service

    async def save_file_final(self, update, context, filename, user_id):
        """Handler - only I/O"""
        code = context.user_data.get('code_to_save')
        note = context.user_data.get('note_to_save', '')

        # Create DTO
        dto = CreateSnippetDTO(
            user_id=user_id,
            filename=filename,
            code=code,
            note=note
        )

        # Call service
        try:
            snippet = await self.snippet_service.create_snippet(dto)

            await update.message.reply_text(
                f"✅ {snippet.filename.value} נשמר!\n"
                f"🧠 שפה: {snippet.language.value}"
            )

        except InvalidSnippetError as e:
            await update.message.reply_text(f"❌ {e.message}")
```

### 5.2 Dependency Injection Setup

```python
# src/presentation/telegram/bot_app.py
from telegram.ext import Application

from application.services.snippet_service import SnippetService
from domain.services.code_normalizer import CodeNormalizer
from domain.services.language_detector import LanguageDetector
from domain.validation.snippet_validator import SnippetValidator
from infrastructure.database.mongodb.connection import MongoDBManager
from infrastructure.database.mongodb.repositories.snippet_repository import MongoSnippetRepository

from presentation.telegram.handlers.snippet.save_handler import SaveSnippetHandler


class BotApplication:
    """Main bot application with DI"""

    def __init__(self, config):
        self.config = config

        # Infrastructure
        self.db_manager = MongoDBManager(config.MONGODB_URI)

        # Repositories
        self.snippet_repository = MongoSnippetRepository(self.db_manager)

        # Domain services
        self.code_normalizer = CodeNormalizer()
        self.language_detector = LanguageDetector()
        self.snippet_validator = SnippetValidator()

        # Application services
        self.snippet_service = SnippetService(
            snippet_repository=self.snippet_repository,
            code_normalizer=self.code_normalizer,
            language_detector=self.language_detector,
            snippet_validator=self.snippet_validator
        )

        # Handlers
        self.save_handler = SaveSnippetHandler(self.snippet_service)

    def setup_handlers(self, application: Application):
        """Register all handlers"""
        # Save conversation
        save_conv = ConversationHandler(
            entry_points=[CommandHandler('save', self.save_handler.start)],
            states={
                GET_CODE: [MessageHandler(filters.TEXT, self.save_handler.receive_code)],
                # ...
            },
            fallbacks=[CommandHandler('cancel', cancel_handler)]
        )

        application.add_handler(save_conv)
```

### 5.3 פיצול conversation_handlers.py

```python
# conversation_handlers.py (231KB) → פצל לפי features:

# src/presentation/telegram/handlers/snippet/save_conversation.py
def get_save_conversation_handler(save_handler):
    return ConversationHandler(
        entry_points=[CommandHandler('save', save_handler.start)],
        states={
            GET_CODE: [MessageHandler(filters.TEXT, save_handler.receive_code)],
            GET_FILENAME: [MessageHandler(filters.TEXT, save_handler.receive_filename)],
            GET_NOTE: [MessageHandler(filters.TEXT, save_handler.receive_note)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

# src/presentation/telegram/handlers/snippet/edit_conversation.py
def get_edit_conversation_handler(edit_handler):
    # ...

# וכו' - handler לכל feature
```

### ✅ Checklist שלב 5

- [ ] כל ה-handlers הופכו ל-classes עם DI
- [ ] conversation_handlers.py פוצל לקבצים קטנים
- [ ] bot_handlers.py פוצל
- [ ] main.py slim (רק bootstrap)
- [ ] אין business logic ב-handlers
- [ ] אין DB access ב-handlers
- [ ] Handler tests עם mocked services
- [ ] E2E tests
- [ ] Deploy + monitor

---

## 🎬 דוגמה מלאה: Save Flow מקצה לקצה

### Flow המלא בכל השכבות

```
User clicks /save
    ↓
[PRESENTATION] SaveHandler.start()
    ↓
User sends code
    ↓
[PRESENTATION] SaveHandler.receive_code()
    → stores in context
    ↓
User sends filename
    ↓
[PRESENTATION] SaveHandler.receive_filename()
    → creates CreateSnippetDTO
    ↓
[APPLICATION] SnippetService.create_snippet(dto)
    ↓
[DOMAIN] CodeNormalizer.normalize(code)
    ↓
[DOMAIN] LanguageDetector.detect(code, filename)
    ↓
[DOMAIN] Creates Snippet entity
    ↓
[DOMAIN] SnippetValidator.validate(snippet)
    ↓
[INFRASTRUCTURE] MongoSnippetRepository.save(snippet)
    → Maps Snippet → SnippetModel
    → Saves to MongoDB
    → Maps back SnippetModel → Snippet
    ↓
[APPLICATION] Returns Snippet
    ↓
[PRESENTATION] Formats and displays message
    ↓
User sees success message
```

### קוד מלא לכל שכבה

#### 1. Presentation Layer

```python
# src/presentation/telegram/handlers/snippet/save_handler.py
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from application.services.snippet_service import SnippetService
from application.dto.create_snippet_dto import CreateSnippetDTO
from application.exceptions.service_exceptions import InvalidSnippetError

GET_CODE, GET_FILENAME, GET_NOTE = range(3)


class SaveSnippetHandler:
    def __init__(self, snippet_service: SnippetService):
        self.snippet_service = snippet_service

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("📝 שלח קוד")
        return GET_CODE

    async def receive_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        code = update.message.text

        if not code or len(code) < 5:
            await update.message.reply_text("❌ קוד קצר מדי")
            return GET_CODE

        context.user_data['code'] = code
        await update.message.reply_text("💭 שם קובץ?")
        return GET_FILENAME

    async def receive_filename(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        filename = update.message.text.strip()

        if not filename:
            await update.message.reply_text("❌ שם ריק")
            return GET_FILENAME

        context.user_data['filename'] = filename
        await update.message.reply_text("📝 הערה? (או 'דלג')")
        return GET_NOTE

    async def receive_note(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        note = update.message.text.strip()
        note = None if note.lower() in {'דלג', 'skip'} else note

        dto = CreateSnippetDTO(
            user_id=update.effective_user.id,
            filename=context.user_data['filename'],
            code=context.user_data['code'],
            note=note
        )

        try:
            snippet = await self.snippet_service.create_snippet(dto)

            await update.message.reply_text(
                f"✅ {snippet.filename.value} נשמר!\n"
                f"🧠 {snippet.language.value}\n"
                f"📏 {len(snippet.code)} תווים"
            )

            return ConversationHandler.END

        except InvalidSnippetError as e:
            await update.message.reply_text(f"❌ {e.message}")
            return ConversationHandler.END
```

#### 2. Application Layer

```python
# src/application/services/snippet_service.py
from application.dto.create_snippet_dto import CreateSnippetDTO
from application.exceptions.service_exceptions import InvalidSnippetError

from domain.entities.snippet import Snippet
from domain.services.code_normalizer import CodeNormalizer
from domain.services.language_detector import LanguageDetector
from domain.validation.snippet_validator import SnippetValidator
from domain.value_objects.file_name import FileName
from domain.value_objects.programming_language import ProgrammingLanguage
from domain.interfaces.snippet_repository_interface import ISnippetRepository


class SnippetService:
    def __init__(
        self,
        snippet_repository: ISnippetRepository,
        code_normalizer: CodeNormalizer,
        language_detector: LanguageDetector,
        snippet_validator: SnippetValidator
    ):
        self.repository = snippet_repository
        self.normalizer = code_normalizer
        self.detector = language_detector
        self.validator = snippet_validator

    async def create_snippet(self, dto: CreateSnippetDTO) -> Snippet:
        # 1. Normalize (domain)
        normalized = self.normalizer.normalize(dto.code)

        # 2. Detect language (domain)
        language = self.detector.detect(normalized, dto.filename)

        # 3. Create entity (domain)
        snippet = Snippet(
            user_id=dto.user_id,
            filename=FileName(dto.filename),
            code=normalized,
            language=ProgrammingLanguage(language),
            description=dto.note or ""
        )

        # 4. Validate (domain)
        result = self.validator.validate(snippet)
        if not result.is_valid:
            raise InvalidSnippetError(
                message="Validation failed",
                errors=result.errors
            )

        # 5. Save (infrastructure)
        return await self.repository.save(snippet)
```

#### 3. Domain Layer

```python
# src/domain/services/code_normalizer.py
import unicodedata

class CodeNormalizer:
    def normalize(self, code: str) -> str:
        if not code:
            return ""

        code = self._remove_bidi(code)
        code = unicodedata.normalize('NFC', code)
        code = code.replace('\r\n', '\n').replace('\r', '\n')

        lines = [line.rstrip() for line in code.split('\n')]
        code = '\n'.join(lines)

        return code.rstrip() + '\n' if code.rstrip() else ''

    def _remove_bidi(self, text: str) -> str:
        markers = ['\u200e', '\u200f', '\u202a', '\u202b', '\u202c']
        for m in markers:
            text = text.replace(m, '')
        return text
```

```python
# src/domain/services/language_detector.py
class LanguageDetector:
    EXTENSION_MAP = {
        '.py': 'python',
        '.js': 'javascript',
        # ...
    }

    def detect(self, code: str, filename: str) -> str:
        for ext, lang in self.EXTENSION_MAP.items():
            if filename.lower().endswith(ext):
                return lang
        return 'text'
```

```python
# src/domain/validation/snippet_validator.py
from dataclasses import dataclass
from typing import List

@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]

class SnippetValidator:
    MAX_LENGTH = 500_000

    def validate(self, snippet) -> ValidationResult:
        errors = []

        if len(snippet.code) > self.MAX_LENGTH:
            errors.append(f"Code too long (max {self.MAX_LENGTH})")

        if not snippet.filename.value:
            errors.append("Filename required")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors
        )
```

#### 4. Infrastructure Layer

```python
# src/infrastructure/database/mongodb/repositories/snippet_repository.py
from domain.interfaces.snippet_repository_interface import ISnippetRepository
from infrastructure.database.mongodb.models.snippet_model import SnippetModel

class MongoSnippetRepository(ISnippetRepository):
    def __init__(self, db_manager):
        self.collection = db_manager.get_collection('snippets')

    async def save(self, snippet):
        db_model = SnippetModel.from_entity(snippet)

        # Check version
        existing = await self._find_latest(
            snippet.user_id,
            snippet.filename.value
        )
        if existing:
            db_model.version = existing['version'] + 1

        # Save
        result = await self.collection.insert_one(db_model.to_dict())

        # Fetch and return
        doc = await self.collection.find_one({'_id': result.inserted_id})
        return SnippetModel.to_entity(doc)

    async def _find_latest(self, user_id, filename):
        return await self.collection.find_one(
            {'user_id': user_id, 'file_name': filename, 'is_active': True},
            sort=[('version', -1)]
        )
```

---

## 🛠️ כלים ו-Automation

### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: check-layer-violations
        name: Check layer violations
        entry: python scripts/check_layers.py
        language: system
        pass_filenames: false
```

```python
# scripts/check_layers.py
"""Check for layer violations"""
import re
import sys
from pathlib import Path

VIOLATIONS = []

def check_file(filepath):
    """Check single file for violations"""
    content = filepath.read_text()

    # Rule 1: Domain can't import from infrastructure
    if 'src/domain' in str(filepath):
        if re.search(r'from (infrastructure|presentation|application)', content):
            VIOLATIONS.append(f"{filepath}: Domain imports from other layers")

    # Rule 2: Handlers can't import from database
    if 'presentation/telegram/handlers' in str(filepath):
        if re.search(r'from database import', content):
            VIOLATIONS.append(f"{filepath}: Handler imports from database directly")

    # Rule 3: No normalize_code in utils
    if 'utils.py' in str(filepath):
        if 'def normalize_code' in content:
            VIOLATIONS.append(f"{filepath}: normalize_code should be in domain")

# Run checks
for py_file in Path('src').rglob('*.py'):
    check_file(py_file)

if VIOLATIONS:
    print("❌ Layer violations found:")
    for v in VIOLATIONS:
        print(f"  - {v}")
    sys.exit(1)

print("✅ No layer violations")
```

### Dependency Graph Generator

```python
# scripts/generate_dependency_graph.py
"""Generate dependency graph between layers"""
import ast
from pathlib import Path
import networkx as nx
import matplotlib.pyplot as plt

def extract_imports(filepath):
    """Extract all imports from file"""
    tree = ast.parse(filepath.read_text())
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    return imports

# Build graph
G = nx.DiGraph()

for py_file in Path('src').rglob('*.py'):
    layer = str(py_file).split('/')[1]  # presentation/application/domain/infrastructure

    for imp in extract_imports(py_file):
        if imp.startswith('src.'):
            target_layer = imp.split('.')[1]
            G.add_edge(layer, target_layer)

# Draw
nx.draw(G, with_labels=True)
plt.savefig('dependency_graph.png')
print("✅ Graph saved to dependency_graph.png")
```

---

## ❓ FAQ - שאלות נפוצות

### Q: האם צריך לעשות את כל 5 השלבים?
**A:** לא בהכרח. תלוי בגודל הפרויקט ובכאב הראש. אפשר להתחיל רק עם שלבים 1-2 (תיקיות + פיצול utils) ולראות איך זה עובד.

### Q: כמה זמן זה באמת לוקח?
**A:** תלוי בגודל הצוות:
- 1 developer: 4-5 חודשים
- 2-3 developers: 2-3 חודשים
- צוות גדול: 1-2 חודשים

### Q: האם אפשר לעשות את זה בזמן שהמערכת בפרודקשן?
**A:** כן! זה בדיוק למה אנחנו עושים הדרגתי. כל שלב עצמאי ואפשר לעצור בכל נקודה.

### Q: מה עם הקוד הישן במקביל?
**A:** בשלבים הראשונים נשמור גם ישן וגם חדש. רק אחרי שהחדש stable נמחק את הישן.

### Q: איך מטפלים ב-breaking changes?
**A:** יוצרים wrappers/adapters זמניים:
```python
# Old code still works
from utils import normalize_code  # Calls new code behind the scenes

# New code
from domain.services.code_normalizer import CodeNormalizer
```

### Q: מה עם ה-tests?
**A:** כותבים tests חדשים לשכבות החדשות. Tests ישנים ממשיכים לרוץ על הקוד הישן עד שמוחקים אותו.

### Q: האם זה שווה את המאמץ?
**A:** תלוי:
- ✅ שווה אם: הפרויקט ימשיך לגדול, צוות גדול, הרבה features חדשים
- ❌ לא שווה אם: פרויקט חד-פעמי, צוות קטן, פיצ'רים מתייצבים

### Q: מה הסיכון הגדול ביותר?
**A:** לשבור משהו שעובד. לכן:
1. Tests לפני ואחרי
2. Deploy הדרגתי
3. Feature flags
4. Rollback plan

### Q: איך משכנעים את הבוס?
**A:** הראה ROI:
- 🚀 פיצ'רים חדשים יהיו מהירים יותר (פחות coupling)
- 🐛 פחות bugs (separation of concerns)
- 👥 onboarding מהיר יותר (קוד ברור)
- 🧪 testing קל יותר (layers מבודדים)

---

## 🎯 סיכום סופי

### מה קיבלת במדריך?

✅ **חלק 1:** ניתוח מצב נוכחי + זיהוי 5 בעיות מרכזיות
✅ **חלק 2:** ארכיטקטורה ב-4 שכבות + עץ תיקיות מלא + מיפוי קבצים
✅ **חלק 3:** 6 כללי זהב + דוגמאות before/after + checklists + testing
✅ **חלק 4:** מפת דרכים ב-5 שלבים + דוגמה מלאה מקצה לקצה + כלים

### התוצאה הסופית

```
לפני:
├── utils.py (1,437 שורות - 7 נושאים)
├── conversation_handlers.py (231KB - הכל ביחד)
├── handlers/ (ערבוב logic + DB)
└── services/ (חלק infrastructure, חלק business)

אחרי:
src/
├── presentation/      (רק I/O)
├── application/       (רק orchestration)
├── domain/            (רק business logic - Pure Python)
├── infrastructure/    (רק טכנולוגיה)
└── shared/            (utilities)
```

### היתרונות

🚀 **מהירות פיתוח:** פיצ'ר חדש = רק service חדש
🐛 **פחות bugs:** separation of concerns
🧪 **tests קלים:** כל שכבה בנפרד
👥 **onboarding מהיר:** קוד ברור
🔄 **שינויים קלים:** החלף DB? רק infrastructure!
📦 **שימוש חוזר:** domain logic ב-CLI, API, tests

### הצעד הבא שלך

1. **קרא את כל 4 החלקים**
2. **התחל משלב 1** (תיקיות)
3. **עשה PR קטן** (אל תנסה הכל ביחד)
4. **למד מהטעויות** (זה תהליך!)
5. **שתף את הקוד** (code review חשוב!)

---

**בהצלחה!** 🚀

*מסמך זה נוצר ב-18/11/2024 - CodeBot Architecture Refactoring Initiative - Part 4 (Final)*

---

## 📚 משאבים נוספים

- [Clean Architecture - Robert C. Martin](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [Domain-Driven Design](https://martinfowler.com/tags/domain%20driven%20design.html)
- [Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/)
- [Repository Pattern](https://martinfowler.com/eaaCatalog/repository.html)
- [Dependency Injection](https://martinfowler.com/articles/injection.html)
