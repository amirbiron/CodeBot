# כללי שכבות – CodeBot

מטרה: לשמור גבולות שכבות ברורים ולמנוע תלות מעגלית/דליפת תשתית.

## שכבות
- **domain**: ישויות, שירותים טהורים (ללא IO). אין תלות ב־handlers/infra/services/database.
- **application**: תזמור Use-Cases וממשקים. תלות ל־domain בלבד (לא infra/handlers).
- **infrastructure**: מתאמים ל־DB/חוץ. יכול לתלות ב־domain, לא ב־handlers.
- **handlers (UI/Bot)**: תלות ב־application בלבד. גישה ל־infra דרך ה־Composition Root.

## Composition Root
- `src/infrastructure/composition/get_snippet_service()` הוא נקודת הקמה לשירותים.
- handlers צורכים את השירות דרך ה־container בלבד.

## זיהוי שפה – מקור אמת
- `src/domain/services/language_detector.LanguageDetector` הוא מקור האמת.
- `services.code_service.detect_language` משמש adapter עם fallbacks לתאימות אחורה.
- `utils.detect_language_from_filename` מפנה לדומיין תחילה.

## בדיקות אכיפה
טסטים אוטומטיים ב־`tests/unit/architecture/test_layer_boundaries.py`:
- domain לא מייבא handlers/infra/services/database/webapp.
- application לא מייבא handlers/infra/database/webapp.
- handlers לא מייבאים domain או infra ישירות (למעט `src.infrastructure.composition`).
- infrastructure לא מייבא handlers.

טסטים אלה רצים ב־CI ומונעים רגרסיות מבניות. 

