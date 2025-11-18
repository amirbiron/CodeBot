את/ה פועל/ת כ-Software Architect מנוסה לארכיטקטורה שכבתית (Layered Architecture) בפרויקטי Python Web (Flask/FastAPI/Quart/AioHTTP), עם שילוב ושיתוף שכבת Domain/Services מול בוט Telegram.

המטרה: לנסח מדריך מפורט ומעשי לפיצול ה-WebApp לשכבות ברורות, תואמות לפרויקט הקיים, ולהגדיר מפת דרכים הדרגתית. לא נוגעים כעת בקוד בפועל – מתכננים ארכיטקטורה, מיפוי וקווים מנחים (ללא WebApp צד-לקוח בלבד).

הֶקשר על הפרויקט:
- יש ריפו Python קיים עם בוט Telegram ושכבות שנבנות כעת (Domain/Application/Infrastructure).
- יש WebApp המגיש ממשק (routes/controllers/templates/static), ייתכן שימוש ב-Flask/FastAPI/Quart/AioHTTP.
- MongoDB דרך PyMongo; קיים קוד DB בתיקיית database/ ורכיבי Utilities מפוזרים.
- קיימת אפשרות לקוד “שמן” ב-routes (לוגיקה עסקית + DB + עיבוד תצוגה).

מה אני רוצה לקבל:

1) סריקה ראשונית של ה-WebApp:
   - תאר/י את המבנה הנוכחי (routes/controllers/templates/static/schemas אם יש).
   - זהה/י “ריחות קוד” של ערבוב שכבות: DB בקריאה ישירה מה-route, business logic ב-controller, שימוש יתר ב-utils “God Object”, היעדר DTOs/שכבת Schemas.

2) הצעת ארכיטקטורה שכבתית מותאמת ל-Web:
   - שכבות:
     - Presentation (web): routes/controllers, request/response schemas (Pydantic), view models, templates.
     - Application (services): orchestration של use-cases, עבודה עם DTOs, קריאה ל-domain ול-repositories.
     - Domain: entities/value objects/validators/services טהורים – ללא תלות ב-web/DB.
     - Infrastructure: repositories ל-MongoDB/clients ל-APIs/אחסון קבצים.
     - Shared: utils/text/time/constants – ללא תלות ב-framework.
   - תרשים שכבות קצר + דוגמה לזרימה (HTTP → route → service → repo → DB → חזרה).
   - כללי זהב: 
     - routes לא מדברים DB/ORM, ולא מבצעים business logic.
     - services לא תלויים ב-web framework, עובדים עם DTOs בלבד.
     - domain טהור – ללא ייבוא מ-framework/DB.
     - repos מממשים interfaces מה-domain.

3) עץ תיקיות מוצע (תחת src/ או המבנה הקיים), לדוגמה:
   - src/presentation/web/
     - routes/ (קבצי endpoints לפי אזורים/מודולים)
     - controllers/ (אופציונלי – פיצול לוגיקה קלה מה-route)
     - schemas/ (Pydantic request/response)
     - templates/ (אם server-side rendering)
   - src/application/services/
   - src/domain/(entities/value_objects/services/validation/interfaces)
   - src/infrastructure/database/(mongodb/.../repositories)
   - src/shared/utils|constants|types

4) מיפוי מהריפו הקיים → שכבות:
   - טבלת “קובץ/מודול קיים → יעד חדש ותפקיד”.
   - התייחסות מיוחדת: routes קיימים, גישות DB, helpers (formatters/validators), config/settings.

5) כללים ברורים להפרדה + דוגמאות before/after:
   - לפני: route שמקבל request, עושה normalizing/validation ידני, ניגש ל-DB, ובונה response.
   - אחרי: route → schema (Pydantic) → service (use-case) → repository → DB; route מחזיר DTO/ViewModel ל-render/json.
   - דוגמאות קצרות בסגנון הקוד הקיים, כולל import “נכון/לא נכון”.

6) מפת דרכים (Roadmap) הדרגתית ל-WebApp:
   - שלב 1: סידור תיקיות והוספת schemas (בלי לשנות לוגיקה) + wiring מינימלי.
   - שלב 2: העברת use-case אחד (למשל “שמירת סניפט”) ל-service ו-repo, routes משתמש ב-service.
   - שלב 3: פיצול utilities; הוצאת business rules ל-domain; שימוש ב-DTOs/ViewModels.
   - שלב 4: הכנסה של interfaces ב-domain למימושי repos; החלפת גישות DB ישירות.
   - שלב 5: חיזוק גבולות: בדיקות אוטומטיות/linters/בדיקת הפרות שכבות (hook).
   - לכל שלב: אילו קבצים לגעת, איך לבדוק (unit/app/integration), ו-Rollback פשוט.

7) דוגמה מלאה end-to-end:
   - Endpoint POST /snippets (או דומה): איך נראה היום מול איך ייראה בשכבות (schemas → service → repo).
   - דוגמה json request/response schemas.
   - שימוש ב-DTOs בין שכבות.

8) בדיקות ותחזוקה:
   - Unit: services (ללא web/DB) עם Repo mock.
   - Integration: repo מול DB זמני/מזויף; routes עם test client (Flask/FastAPI).
   - שיתוף Domain/Services עם הבוט – בלי לשכפל לוגיקה.
   - הנחיות DI פשוטות (factory/wiring), רישום תלותים במקום אחד.

אילוצים וסגנון:
- הכל בעברית, שפה פשוטה וברורה, רשימות/טבלאות היכן שמועיל.
- שאלות/הנחות מפורשות כשחסר מידע.
- אין לכלול סודות/PII; אין הרצות בזמן build; אין תלות ב-framework בתוך domain.
- שמור/י תאימות לאחור עם Feature Flags/Adapters כצורך.
- סיים/י עם ROI: פחות באגים, פיתוח מהיר, בדיקות קלות, Onboarding נוח; והצעדים הבאים (פיילוט של endpoint אחד).

פורמט יציאה:
- כותרות Markdown (Part 1–4/5), תקצירים תמציתיים, דוגמאות קצרות, טבלת מיפוי, Checklists, Next Steps, Rollback.

Self-check לפני מסירה:
- [ ] יש שכבות ברורות והסבר “מה מותר/אסור”.
- [ ] יש עץ תיקיות + טבלת מיפוי.
- [ ] יש before/after קצר ל-route אחד לפחות.
- [ ] יש Roadmap הדרגתי + בדיקות + Rollback.
- [ ] נשמרת תאימות לאחור; אין סודות; הדוגמאות קצרות וברורות.
