# מדריך מימוש: זיהוי שגיאות בלוגים של Render, הורדת רעש, וקיבוץ התראות

מסמך זה מתרגם את ההחלטות שנקבעו ב־issue #1184 והתגובה המצוטטת למימוש פרקטי בקוד של CodeBot. המטרה: לזהות שגיאות בזמן-כמעט-אמת, להפחית רעש, ולהפיק התראות מקובצות וברורות.

## יעדים
- זיהוי דפוסי שגיאה משמעותיים (OOM, Crash, TLS/DNS, DB/Redis, 5xx, Python/Node).
- Allowlist לרעש ידוע (499, "Broken pipe", "context canceled") כדי לצמצם false positives.
- הפקת התראות חכמות ומקובצות (grouping/dedup) עם מונה מופעים וחלון זמן.

## ארכיטקטורה – היכן ליישם בקוד
- צריבה/זרימה של לוגים קיימת מגיעה ל־`monitoring/` ו/או ל־`alert_manager.py`.
- נשלב:
  - Registry של Regex (קריטי/רשת/אפל׳/רעש) בקובץ קונפיג אחד טעין-דינמית.
  - מסנן רעש Allowlist לפני יצירת אירוע.
  - Fingerprint וקיבוץ בתוך חלון זמן מתגלגל ב־`alert_manager`.
  - ניסוח הודעות התראה ידידותיות (summary במקום "שורה חריגה").

המלצה: קובץ קונפיג יעודי (YAML) תחת `config/error_signatures.yml`.

## קובץ קונפיג – רשימות Regex לדירוג ולקלסיפיקציה
דוגמה ראשונית:

```yaml
critical:
  - "Out of memory|OOMKilled|memory limit exceeded"
  - "Too many open files|ENFILE|EMFILE"
  - "No space left on device|ENOSPC"
  - "certificate verify failed|x509: .* expired"
  - "Exited with code (?!0)\\d+"
network_db:
  - "ECONNRESET|ETIMEDOUT|EAI_AGAIN|socket hang up"
  - "SQLITE_BUSY|deadlock|could not obtain lock"
app_runtime:
  - "Traceback \\(|UnhandledPromiseRejection|TypeError:|ReferenceError:|gunicorn.*worker timeout|uvicorn.error"
noise_allowlist:
  - "client disconnected|Broken pipe|499|context canceled"
```

כלל: הוסיפו/עדכנו דפוסים לאורך הזמן; שמרו קטגוריות קצרות וברורות.

## טעינת קונפיג ושימוש בו
טעינה חד־פעמית עם ריענון מחזורי (למשל כל 60 שנ׳) או Trigger דרך ChatOps.

```python
# example: monitoring/error_signatures.py
from pathlib import Path
import yaml
import re
from typing import Dict, List, Pattern

class ErrorSignatures:
    def __init__(self, path: str):
        self.path = Path(path)
        self.compiled: Dict[str, List[Pattern[str]]] = {}
        self.allowlist: List[Pattern[str]] = []
        self._load()

    def _compile_list(self, patterns: List[str]) -> List[Pattern[str]]:
        return [re.compile(p, re.IGNORECASE) for p in patterns]

    def _load(self) -> None:
        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        self.compiled = {
            k: self._compile_list(v) for k, v in data.items() if k != "noise_allowlist"
        }
        self.allowlist = self._compile_list(data.get("noise_allowlist", []))

    def classify(self, line: str) -> str | None:
        for category, patterns in self.compiled.items():
            if any(p.search(line) for p in patterns):
                return category
        return None

    def is_noise(self, line: str) -> bool:
        return any(p.search(line) for p in self.allowlist)
```

שילוב בקולט הלוגים/המנתח:

```python
signatures = ErrorSignatures("config/error_signatures.yml")

def analyze_log_line(line: str) -> dict | None:
    if signatures.is_noise(line):
        return None  # סינון רעש ידוע

    category = signatures.classify(line)
    if not category:
        return None  # לא אירוע מעניין

    return {
        "category": category,
        "fingerprint": compute_fingerprint(line, category),
        "raw": line,
    }
```

## Fingerprint וקיבוץ (grouping/dedup)
מפתח קיבוץ מומלץ: שילוב של `category` + תבנית קנונית מהשורה (למשל קבוצת ה־regex שתפסה) + הקשר אופציונלי כמו `route`/`target`. כאשר אין JSON מובנה, ניתן לנרמל מהטקסט.

```python
import hashlib
import re

_CANONICALS = [
    re.compile(r"(Out of memory|OOMKilled)", re.I),
    re.compile(r"(gunicorn.*worker timeout)", re.I),
    re.compile(r"(certificate verify failed|x509: .* expired)", re.I),
    re.compile(r"(ECONNRESET|ETIMEDOUT|EAI_AGAIN)", re.I),
]

def canonicalize(line: str) -> str:
    for rx in _CANONICALS:
        m = rx.search(line)
        if m:
            return m.group(1).lower()
    return "generic"

def compute_fingerprint(line: str, category: str) -> str:
    canon = canonicalize(line)
    basis = f"{category}|{canon}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
```

ב־`alert_manager`: נהל חלון זמן מתגלגל (למשל 5 דקות) עם מילון `fingerprint -> counter, first_seen, last_seen, samples`.
- אם מגיע אירוע חדש עם אותו fingerprint בתוך החלון: העלה מונה, עדכן `last_seen`, ושמור עד 3 דוגמאות טקסט.
- כאשר המונה עובר סף (ראו פרק ספים): הפק התראה אחת מקובצת.

## ניסוח התראות חכמות
במקום התראת "שורה חריגה", נשתמש בתמצית:
- "התגלו N שגיאות 500 ב־T דקות האחרונות" (כאשר category=HTTP 5xx)
- "Gunicorn Crash/Worker timeout — M מופעים, מאז HH:MM" (app_runtime)
- "TLS expired מול <target> — פעם ראשונה היום" (critical)

דוגמה להרכבת הודעה:

```python
def render_alert_title(category: str, count: int, window_min: int) -> str:
    if category == "critical":
        return f"התראה קריטית — {count} מופעים ב-{window_min} דק'"
    if category == "app_runtime":
        return f"שגיאות אפליקציה — {count} ב-{window_min} דק'"
    if category == "network_db":
        return f"בעיות רשת/DB — {count} ב-{window_min} דק'"
    return f"התראות — {count} ב-{window_min} דק'"

def render_alert_body(sample_lines: list[str], fingerprint: str, first_seen: str, last_seen: str) -> str:
    head = "\n".join(sample_lines[:3])
    return (
        f"Fingerprint: {fingerprint}\n"
        f"חלון: {first_seen} → {last_seen}\n"
        f"דוגמאות:\n{head}"
    )
```

שליחת ההתרעה תעשה דרך המנגנון הקיים (Telegram/ChatOps/Sentry/וכו').

## ספים והורדת רעש
- סף ברירת מחדל להתראה: `N=3` מופעים באותו fingerprint בתוך 5 דק'.
- קטגוריות קריטיות (OOM/TLS/ENOSPC/Exit code!=0): התרעה מידית גם ב־N=1.
- Allowlist: סנן "499", "Broken pipe", "context canceled" לפני כל עיבוד.
- Rate limiting: אל תשגר יותר מהתרעה אחת לכל fingerprint כל `cooldown` (למשל 10 דק').

פרמטרים בקונפיג (`config/alerts.yml`):
```yaml
window_minutes: 5
min_count_default: 3
cooldown_minutes: 10
immediate_categories:
  - critical
```

## בדיקות
- יחידה: פונקציות `classify`, `is_noise`, `compute_fingerprint`, קיבוץ חלון זמן.
- אינטגרציה: הזרמת לוגים מדומים עם דפוסים שונים ובדיקת יצירת התרעות מקובצות.
- שמרו על כללי “הימנעות ממחיקות קבצים בטסטים” — קלט/פלט תחת `tmp` בלבד.

## פריסה הדרגתית (Rollout)
1) PoC מקומי: הזינו `render logs --service ... --since 1h` לצינור הניתוח ובדקו ספייקים ידועים.
2) דרגתו לרצה אמיתית: הפעלת קיבוץ + Allowlist, בלי שליחת התראות — רק מטריקות.
3) Enable Alerts: הפעלת שליחה ל־ChatOps בקצב מוגבל; כוונון ספים.
4) הרחבת רשימת הדפוסים ושיפור canonicalization בהתאם לנתונים אמיתיים.

## קישור לתיעוד
- עיינו ב־CodeBot – Project Docs: `https://amirbiron.github.io/CodeBot/`
- מומלץ להוסיף עמוד Docs ייעודי (RTD) עם Saved Queries ודשבורדים לדוגמה.

## נספח: חיפוש מהיר בזמן אמת (ל־PoC)
```bash
render logs --service "$SERVICE" --since 1h | rg -n "(error|fatal|Traceback|UnhandledPromiseRejection|5\\d\\d)"
```
