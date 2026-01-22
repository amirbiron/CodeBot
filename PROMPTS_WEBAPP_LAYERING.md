# פרומפט: תכנון פיצול WebApp לשכבות

> **מטרת הפרומפט:** כשמריצים אותו, מקבלים **מדריך תכנון** מפורט (כמו ARCHITECTURE_ANALYSIS_PART1-4.md).  
> לא נוגעים בקוד בפועל – רק מתכננים ארכיטקטורה ומפת דרכים.

---

את/ה פועל/ת כ-Software Architect מנוסה לארכיטקטורה שכבתית (Layered Architecture) בפרויקטי Python Web (Flask/FastAPI/Quart/AioHTTP), עם שילוב ושיתוף שכבת Domain/Services מול בוט Telegram.

**המטרה:** לנסח מדריך מפורט ומעשי לפיצול ה-WebApp לשכבות ברורות, תואמות לפרויקט הקיים, ולהגדיר מפת דרכים הדרגתית.  
**לא נוגעים כעת בקוד בפועל** – מתכננים ארכיטקטורה, מיפוי וקווים מנחים בלבד.

---

## הקשר על הפרויקט

### תשתית קיימת (הושלמה - ינואר 2026)

הבוט עבר פיצול מלא לשכבות. קיימים:

```
src/
├── domain/                          # שכבת Domain (טהורה)
│   ├── entities/snippet.py          # Snippet entity
│   ├── interfaces/                  # Repository interfaces
│   └── services/
│       ├── language_detector.py     # מקור אמת לזיהוי שפה
│       └── code_normalizer.py       # נרמול קוד
│
├── application/                     # שכבת Application
│   ├── dto/create_snippet_dto.py    # DTOs
│   └── services/snippet_service.py  # SnippetService
│
└── infrastructure/                  # שכבת Infrastructure
    ├── composition/
    │   ├── container.py             # Composition Root: get_snippet_service()
    │   └── files_facade.py          # FilesFacade: 50+ פעולות DB
    └── database/mongodb/repositories/
        └── snippet_repository.py    # מימוש Repository
```

**נקודות כניסה זמינות:**
- `get_snippet_service()` – שירות מלא לניהול snippets
- `get_files_facade()` – facade ל-DB עם 50+ פעולות

**טסטים ארכיטקטוניים:** 6 טסטים ב-`tests/unit/architecture/test_layer_boundaries.py` אוכפים גבולות שכבות.

### מצב ה-WebApp הנוכחי

- WebApp ב-Flask המגיש ממשק (routes/templates/static)
- MongoDB דרך PyMongo; גישה דרך `get_db()` ישירות מה-routes
- ~189 קריאות `get_db()` ב-webapp (רובן ב-`app.py`)
- קיימת אפשרות לקוד "שמן" ב-routes (לוגיקה עסקית + DB + עיבוד תצוגה)
- אפס שימוש ב-Facade/Service הקיימים

---

## מה אני רוצה לקבל

### 1) סריקה ראשונית של ה-WebApp
- תאר/י את המבנה הנוכחי (routes/controllers/templates/static/schemas אם יש)
- זהה/י "ריחות קוד" של ערבוב שכבות:
  - DB בקריאה ישירה מה-route
  - business logic ב-controller
  - שימוש יתר ב-utils "God Object"
  - היעדר DTOs/שכבת Schemas

### 2) ניתוח פערים: תשתית קיימת מול צרכי WebApp
- אילו פעולות DB נדרשות ב-WebApp?
- אילו כבר קיימות ב-`FilesFacade`?
- אילו חסרות ודורשות הרחבה?
- טבלת מיפוי: פעולה → קיים/חסר

### 3) הצעת ארכיטקטורה שכבתית מותאמת ל-Web
שכבות (בהתאמה לקיים):
- **Presentation (web):** routes, request/response schemas (Pydantic), view models, templates
- **Application (services):** orchestration של use-cases, עבודה עם DTOs, קריאה ל-domain ול-repositories – **שימוש ב-SnippetService הקיים**
- **Domain:** entities/value objects/validators/services טהורים – **שימוש ב-LanguageDetector/CodeNormalizer הקיימים**
- **Infrastructure:** repositories + **FilesFacade הקיים** + הרחבות לפי הצורך
- **Shared:** utils/text/time/constants

תרשים שכבות קצר + דוגמה לזרימה (HTTP → route → Facade/Service → DB → חזרה)

**כללי זהב:**
- routes לא מדברים DB/ORM, ולא מבצעים business logic
- routes משתמשים ב-`get_files_facade()` או `get_snippet_service()` בלבד
- services לא תלויים ב-web framework, עובדים עם DTOs בלבד
- domain טהור – ללא ייבוא מ-framework/DB

### 4) עץ תיקיות מוצע
התייחסות למבנה הקיים (`webapp/`) ולשילוב עם `src/`:
- היכן יישבו schemas חדשים?
- האם צריך controllers נפרדים או הכל ב-routes?
- איך משתלב עם `src/infrastructure/composition/`?

### 5) מיפוי מהריפו הקיים → שכבות
טבלת "קובץ/מודול קיים → יעד חדש ותפקיד":
- `webapp/app.py` – אילו פונקציות ללאן
- `webapp/*_api.py` – כל API file
- `webapp/routes/` – קבצי routes נוספים
- התייחסות מיוחדת: גישות DB, helpers, config

### 6) כללים ברורים להפרדה + דוגמאות before/after
- **לפני:** route שמקבל request, עושה validation ידני, ניגש ל-DB ישירות, ובונה response
- **אחרי:** route → schema (Pydantic) → Facade/Service → DB; route מחזיר DTO/ViewModel

דוגמאות קצרות בסגנון הקוד הקיים, כולל import "נכון/לא נכון"

### 7) מפת דרכים (Roadmap) הדרגתית ל-WebApp
- **שלב 1:** מיפוי פערים + הרחבת Facade (אם נדרש)
- **שלב 2:** פיילוט – endpoint אחד עובר ל-Facade
- **שלב 3:** החלפה הדרגתית בקובץ הראשי (`app.py`)
- **שלב 4:** טיהור APIs נוספים (`*_api.py`)
- **שלב 5:** הוספת schemas (Pydantic) – אופציונלי
- **שלב 6:** הקשחה – טסטים ארכיטקטוניים ל-webapp

לכל שלב:
- אילו קבצים נוגעים
- איך לבדוק (unit/integration)
- Rollback פשוט

### 8) דוגמה מלאה end-to-end
Endpoint אחד (למשל `GET /api/files` או `POST /save`):
- איך נראה היום
- איך ייראה אחרי שימוש ב-Facade
- דוגמת request/response

### 9) בדיקות ותחזוקה
- Unit: services (ללא web/DB) עם mock
- Integration: routes עם test client
- **שיתוף Domain/Services עם הבוט** – בלי לשכפל לוגיקה
- הרחבת טסטים ארכיטקטוניים קיימים ל-webapp

---

## אילוצים וסגנון

- הכל בעברית, שפה פשוטה וברורה, רשימות/טבלאות היכן שמועיל
- שאלות/הנחות מפורשות כשחסר מידע
- אין לכלול סודות/PII; אין הרצות בזמן build; אין תלות ב-framework בתוך domain
- שמור/י תאימות לאחור עם Feature Flags/Adapters כצורך
- **לא להריץ Prettier על קבצי Jinja** (`webapp/templates/**`)
- סיים/י עם ROI: פחות באגים, פיתוח מהיר, בדיקות קלות, Onboarding נוח; והצעדים הבאים

---

## פורמט יציאה

- כותרות Markdown (Part 1–4/5)
- תקצירים תמציתיים
- דוגמאות קצרות
- טבלת מיפוי
- Checklists
- Next Steps
- Rollback

---

## Self-check לפני מסירה

- [ ] יש סריקה של מצב ה-WebApp הנוכחי
- [ ] יש ניתוח פערים: Facade קיים מול צרכים
- [ ] יש שכבות ברורות והסבר "מה מותר/אסור"
- [ ] יש עץ תיקיות + טבלת מיפוי
- [ ] יש before/after קצר ל-route אחד לפחות
- [ ] יש Roadmap הדרגתי + בדיקות + Rollback
- [ ] מודגש שימוש בתשתית הקיימת (לא בנייה מאפס)
- [ ] נשמרת תאימות לאחור; אין סודות; הדוגמאות קצרות וברורות
