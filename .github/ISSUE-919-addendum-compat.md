## השלמה למדריך Issue #919 – תאימות טסטים ושכבת Facade

### למה זה חשוב
פיצול הקבצים הגדולים חייב לשמור על "חוזה ציבורי" (Public API) זהה עבור המודולים הקיימים כדי לא לשבור עשרות טסטים שמייבאים ישירות שמות מהקבצים: `github_menu_handler.py`, `main.py`, `conversation_handlers.py`.

הפתרון: להשאיר קבצי facade דקים באותם שמות קבצים שמבצעים re-export של כל הסמלים הציבוריים שהיו זמינים לפני הפיצול. כך אפשר להוציא לוגיקה למבנה מודולרי חדש, בלי לשנות את נקודות הכניסה של הטסטים.

---

## מה חייב להישמר (חוזה ציבורי)

### 1) github_menu_handler
- חייב להמשיך לייצא: `GitHubMenuHandler`, וגם את הקבועים: `REPO_SELECT`, `FILE_UPLOAD`, `FOLDER_SELECT`.
- הטסטים מבצעים monkeypatch ישירות על אובייקטים ברמת המודול:
  - `gh.TelegramUtils.safe_edit_message_text`, `gh.TelegramUtils.safe_edit_message_reply_markup`
  - `gh.requests.get`
  - `gh.secrets.token_urlsafe`
- המשמעות: אחרי הפיצול, עדיין צריך שהשמות הללו יהיו נגישים דרך המודול `github_menu_handler` בדיוק באותו נתיב.

### 2) main
- הטסטים מייבאים ישירות: `CodeKeeperBot`, `ApplicationHandlerStop`, ולעיתים פונקציות כמו `log_user_activity`.
- אם הקוד עובר ל־`bot/…`, יש להשאיר `main.py` כ־facade שמייצא את אותם שמות.

### 3) conversation_handlers
- הטסטים מייבאים ומריצים שמות רבים: `MAIN_KEYBOARD`, `handle_callback_query`, `get_save_conversation_handler`, פונקציות `show_*`, ועוד.
- יש לבצע re-export מפורש של כל השמות שפורסמו בעבר. מומלץ להגדיר `__all__` כדי להבטיח יציבות.

---

## דוגמאות קוד – שכבת תאימות (facade)

להלן דוגמאות שיועילו אחרי שמוציאים את הלוגיקה לתיקיות החדשות. התאימו לשמות שתחליטו עליהם במבנה המודולרי שלכם.

### github/__init__.py
```python
# github/__init__.py
# מאגד מחלקות משנה וחשוב: מייצא גם קבועים לצורכי תאימות

from .browser import GitHubBrowser
from .upload import GitHubUploader
from .download import GitHubDownloader
from .analyzer import GitHubAnalyzer
from .pr_manager import GitHubPRManager
from .delete_manager import GitHubDeleteManager
from .notifications import GitHubNotifications
from .backup_restore import GitHubBackupRestore
from .import_export import GitHubImportExport
from .checkpoints import GitHubCheckpoints
from .constants import REPO_SELECT, FILE_UPLOAD, FOLDER_SELECT

class GitHubMenuHandler(
    GitHubBrowser,
    GitHubUploader,
    GitHubDownloader,
    GitHubAnalyzer,
    GitHubPRManager,
    GitHubDeleteManager,
    GitHubNotifications,
    GitHubBackupRestore,
    GitHubImportExport,
    GitHubCheckpoints,
):
    pass

__all__ = [
    'GitHubMenuHandler',
    'REPO_SELECT', 'FILE_UPLOAD', 'FOLDER_SELECT',
]
```

### github_menu_handler.py (facade תואם לאחור)
```python
# github_menu_handler.py
# נקודת כניסה היסטורית – מייצאת את אותו API לצורך טסטים וקוד קיים

from github import GitHubMenuHandler, REPO_SELECT, FILE_UPLOAD, FOLDER_SELECT
from utils import TelegramUtils  # כדי לא לשבור monkeypatching בטסטים
import requests  # כדי לא לשבור monkeypatching של requests.get
import secrets   # כדי לא לשבור monkeypatching של secrets.token_urlsafe

__all__ = [
    'GitHubMenuHandler',
    'REPO_SELECT', 'FILE_UPLOAD', 'FOLDER_SELECT',
    'TelegramUtils', 'requests', 'secrets',
]
```

### main.py (facade לאחר פיצול ל־bot/*)
```python
# main.py
# אם CodeKeeperBot/לוגיקה עוברים ל־bot/, עדיין מייצאים אותם כאן

from bot.app import CodeKeeperBot  # היכן שהמחלקה החדשה
from telegram.ext import ApplicationHandlerStop

# אם העברתם את הפונקציה לקבוץ middleware חדש
try:
    from bot.middleware.logging import log_user_activity  # דוגמה – להתאים בפועל
except Exception:  # אם לא הועבר עדיין
    from .somewhere import log_user_activity  # השאירו נקודת ייבוא נכונה זמנית

__all__ = ['CodeKeeperBot', 'ApplicationHandlerStop', 'log_user_activity']
```

### conversation_handlers.py (facade מייצא שמות היסטוריים)
```python
# conversation_handlers.py
# מייבא מהמבנה החדש ומייצא שמות היסטוריים שנצרכים בטסטים

from conversations.handler import get_main_conversation_handler as get_save_conversation_handler
from conversations.main_menu import (
    MAIN_KEYBOARD,
    handle_callback_query,
    # הוסיפו כאן את כל show_* ו־handlers נוספים שהטסטים דורשים
)
# ניתן לייבא עוד פונקציות/קבועים מתתי־מודולים לפי הצורך

__all__ = [
    'MAIN_KEYBOARD',
    'handle_callback_query',
    'get_save_conversation_handler',
    # 'show_all_files', 'show_by_repo_menu', 'show_by_repo_menu_callback', ...
]
```

טיפ: כדי לא לפספס שמות, רצוי לרוץ פעם אחת וללקט שמות שהטסטים מייבאים בפועל (ראו פקודות להלן), ואז למלא את `__all__` בהתאם.

---

## צ'קליסט אימות מהיר (לפני הרצת כל הטסטים)

### ייבוא בסיסי
```bash
python - << 'PY'
from github_menu_handler import GitHubMenuHandler, REPO_SELECT, FILE_UPLOAD, FOLDER_SELECT
import github_menu_handler as gh
assert hasattr(gh, 'TelegramUtils') and hasattr(gh, 'requests') and hasattr(gh, 'secrets')
print('github_menu_handler ✅')

from main import CodeKeeperBot, ApplicationHandlerStop, log_user_activity
print('main ✅')

from conversation_handlers import MAIN_KEYBOARD, get_save_conversation_handler, handle_callback_query
print('conversation_handlers ✅')
PY
```

### הרצת תתי־חבילות טסטים בשלבים
```bash
# שלב GitHub menu handler
pytest -q tests/test_github_* tests/test_notifications_* --maxfail=1

# שלב main
pytest -q tests/test_main_* tests/test_lock_* --maxfail=1

# שלב conversation handlers
pytest -q tests/test_conversation_* tests/test_regular_files_* --maxfail=1
```

### עזר: לקט שמות שמיובאים מהמודולים (לעזור למלא __all__)
```bash
# שמות שמיובאים מ-conversation_handlers בקבצי הטסטים
rg -n "from\\s+conversation_handlers\\s+import\\s+([\\w_,\\s]+)" tests

# שימושים במודול github_menu_handler עם קיצור gh
rg -n "\\bgh\\.[A-Za-z_]+" tests
```

---

## נקודות רגישות שכדאי לשים לב אליהן
- **Monkeypatch בטסטים**: הטסטים נוגעים ישירות באובייקטים ברמת מודול (`gh.TelegramUtils`, `gh.requests`, `gh.secrets`). אסור שייעלמו.
- **קבועים של מצבים**: `REPO_SELECT`, `FILE_UPLOAD`, `FOLDER_SELECT` חייבים להיות זמינים גם אחרי הפיצול דרך `github_menu_handler`.
- **ייצוא מפורש**: הגדירו `__all__` בקבצי facade כדי להבטיח יציבות ולהימנע מייבוא חלקי מקרי.
- **יחידות קטנות**: פצלו בפנים כמה שרוצים; כל עוד ה־facade מציג את אותו API, הטסטים לא ירגישו שינוי.

---

## מה להוסיף ל־PR (Acceptance Criteria)
- **ייבוא שמות ציבוריים מהמודולים הישנים עובד ללא שינוי**.
- **טסטים ירוקים** בכל שלבי הפיצול (רצוי לפצל ל־3 PRים קטנים בסדר: GitHub → main → conversations).
- **ללא שינויי טסטים** (אלא אם חיקוי קוד/שמות לא אפשרי – אז לתעד חריג נקודתי).

---

## סיכום
- **שמרו על נקודת כניסה זהה** (facade) לכל אחד משלושת הקבצים הגדולים.
- **הוציאו את הלוגיקה למודולים חדשים**, אבל השאירו re-export מדויק של כל הסמלים הציבוריים שהטסטים והקוד הקיים משתמשים בהם.
- כך תרוויחו פירוק מודולרי בלי לשלם בשבירת טסטים.
