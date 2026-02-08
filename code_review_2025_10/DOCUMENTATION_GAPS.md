# 📋 פערי תיעוד - סריקת דצמבר 2025

> **תאריך סריקה:** דצמבר 2025  
> **מטרה:** זיהוי מודולים, שירותים וקבצים שחסרים באתר התיעוד  
> **אתר התיעוד:** [CodeBot – Project Docs](https://amirbiron.github.io/CodeBot/)

---

## 🔴 רמה 1 - מודולים שלמים שחסרים לחלוטין

### 1. תיקיית `src/` - Clean Architecture

תיקיה שלמה עם ארכיטקטורה נקייה שלא מתועדת כלל:

| קובץ | תיאור |
|------|-------|
| `domain/services/code_normalizer.py` | נירמול קוד (הסרת BOM, תווים נסתרים, CRLF→LF) |
| `domain/services/language_detector.py` | זיהוי שפות תכנות לפי תוכן ושם קובץ |
| `domain/entities/snippet.py` | מודל ישות Snippet |
| `application/services/snippet_service.py` | שירות אפליקטיבי לניהול סניפטים |
| `application/dto/create_snippet_dto.py` | DTO ליצירת סניפט |
| `infrastructure/database/mongodb/` | שכבת MongoDB Repository |
| `infrastructure/composition/container.py` | Dependency Injection Container |
| `infrastructure/composition/files_facade.py` | Facade לעבודה עם קבצים |

**המלצה:** יש ליצור עמוד `docs/architecture/clean-architecture.rst` שמסביר את הארכיטקטורה הנקייה.

---

### 2. תיקיית `tools/` - כלי עזר למפתחים

| קובץ | תיאור |
|------|-------|
| `analyze_queries.py` | כלי לניתוח שאילתות MongoDB איטיות (profiler, explain) |
| `dup_scan.py` | כלי לסריקת קבצים כפולים בפרויקט |

**דוגמת שימוש:**
```bash
# ניתוח שאילתות איטיות
MONGODB_URL=mongodb://localhost:27017 DATABASE_NAME=code_keeper_bot \
  python tools/analyze_queries.py --duration 60 --min-ms 100

# סריקת כפילויות
python tools/dup_scan.py --path . --include "*.py" --min-lines 5
```

---

### 3. תיקיית `scripts/` - סקריפטים

| קובץ | תיאור |
|------|-------|
| `cleanup_repo_tags.py` | ניקוי תגיות מיותרות |
| `dev_seed.py` | זריעת נתוני פיתוח ל-DB |
| `import_snippets_from_markdown.py` | ייבוא סניפטים מקבצי Markdown |
| `migrate_workspace_collections.py` | מיגרציה של אוספים בין workspaces |
| `run_log_aggregator.py` | הפעלת אגרגטור לוגים |
| `start_webapp.sh` | סקריפט הפעלת ה-WebApp |
| `start_with_worker.sh` | סקריפט הפעלה עם Worker |

---

### 4. תיקיית `i18n/` - בינאום

| קובץ | תיאור |
|------|-------|
| `__init__.py` | אתחול מודול בינאום |
| `strings_he.py` | מחרוזות בעברית |

**חסר:** הסבר על מנגנון התרגום ואיך להוסיף שפות חדשות.

---

## 🟠 רמה 2 - שירותים (`services/`) לא מתועדים

השירותים הבאים קיימים אך **לא מופיעים** ב-`docs/services/index.rst`:

| קובץ | תיאור | הערות |
|------|-------|-------|
| `ai_explain_service.py` | שירות AI לניתוח התראות באמצעות Claude | יש `api/ai_explain.md` אבל לא ב-services index |
| `community_library_service.py` | ספריית הקהילה - הגשה, אישור ודחיית פריטים | חדש יחסית |
| `image_generator.py` | יצירת תמונות קוד (PIL/Playwright/WeasyPrint) | תומך בתמות שונות |
| `snippet_library_service.py` | ספריית הסניפטים + Built-in snippets | כולל ~20 סניפטים מובנים |
| `observability_http.py` | HTTP Observability endpoints | |

### פירוט שירותים חשובים:

#### `ai_explain_service.py`
- אינטגרציה עם Anthropic Claude API
- Fallback בין מודלים (claude-sonnet-4.5 → claude-opus-4.5 → ...)
- Sanitization של מידע רגיש לפני שליחה ל-AI
- יצירת הסברים להתראות (root_cause, actions, signals)

#### `image_generator.py`
- יצירת תמונות קוד מקצועיות בסגנון Carbon
- תמות: dark, light, github, monokai, gruvbox, one_dark, dracula
- מנועי רינדור: Playwright (מועדף) → WeasyPrint → PIL
- תמיכה ב-syntax highlighting עם Pygments

#### `snippet_library_service.py`
- ניהול ספריית סניפטים ציבורית
- סניפטים Built-in (TimeUtils, TextUtils, TelegramUtils ועוד)
- Submit/Approve/Reject workflow
- סינון לפי שפה וחיפוש טקסט

---

## 🟠 רמה 3 - מודולי Monitoring חסרים

ב-`monitoring/` יש מודולים חשובים שאין להם תיעוד ייעודי:

| קובץ | תיאור |
|------|-------|
| `error_signatures.py` | מנוע סיווג שגיאות לפי חתימות regex וטקסונומיה |
| `incident_story_storage.py` | אחסון סיפורי אירועים (MongoDB/File fallback) |
| `log_analyzer.py` | אגרגטור לוגים - קיבוץ, fingerprinting, cooldown, alerting |

### פירוט:

#### `error_signatures.py`
- טעינת חתימות מ-`config/error_signatures.yml`
- סיווג לפי קטגוריות (retryable, critical, transient, config...)
- תמיכה ב-noise allowlist
- API: `match()`, `classify()`, `is_noise()`

#### `log_analyzer.py` (LogEventAggregator)
- קיבוץ אירועי לוג דומים לפי fingerprint
- Canonicalization להסרת משתנים (UUIDs, timestamps, numbers)
- Rolling window וחלון cooldown למניעת spam
- אינטגרציה עם `internal_alerts` לשליחת התראות

---

## 🟠 רמה 4 - מערכת תזכורות (`reminders/`)

מודול שלם שחסר לו עמוד תיעוד מקיף:

| קובץ | תיאור |
|------|-------|
| `database.py` | שכבת DB לתזכורות |
| `handlers.py` | Telegram handlers לתזכורות |
| `models.py` | מודלים (Reminder, ReminderStatus) |
| `scheduler.py` | מתזמן תזכורות |
| `validators.py` | ולידציה של קלט |
| `utils.py` | עזרים (פרסור תאריכים, פורמט) |

**המלצה:** יש ליצור `docs/user/reminders.rst` עם מדריך למשתמש ו-`docs/api/reminders.rst` עם API Reference.

---

## 🟠 רמה 5 - קבצי קונפיגורציה (`config/`)

קבצי קונפיגורציה לא מתועדים:

| קובץ | תיאור |
|------|-------|
| `alert_graph_sources.json` | מקורות גרפים להתראות (Prometheus queries) |
| `alert_quick_fixes.json` | תיקונים מהירים להתראות (ChatOps commands) |
| `alerts.yml` | הגדרות התראות (window, min_count, cooldown) |
| `error_signatures.yml` | חתימות שגיאות לסיווג לפי קטגוריות |
| `image_settings.yaml` | הגדרות יצירת תמונות (theme, font, dimensions) |

**המלצה:** להוסיף סקשן ב-`docs/configuration.rst` שמתאר כל קובץ.

---

## 🟡 רמה 6 - WebApp - מודולים נוספים

מודולים ב-`webapp/` שלא מופיעים בתיעוד:

| קובץ | תיאור |
|------|-------|
| `activity_tracker.py` | מעקב פעילות משתמשים |
| `community_library_api.py` | REST API לספריית קהילה |
| `community_library_ui.py` | UI routes לספריית קהילה |
| `config_radar.py` | Config Radar - מעקב שינויי קונפיגורציה |
| `push_api.py` | Web Push Notifications API |
| `snippet_library_api.py` | REST API לספריית סניפטים |
| `snippet_library_ui.py` | UI routes לספריית סניפטים |
| `workspace_api.py` | API לניהול Workspace |

---

## 🟡 רמה 7 - Handlers נוספים

| קובץ | תיאור |
|------|-------|
| `handlers/drive/utils.py` | עזרים ל-Google Drive handler |
| `handlers/github/menu.py` | תפריט GitHub בבוט |
| `handlers/github/__init__.py` | אתחול GitHub handlers |

---

## 🟡 רמה 8 - דברים קטנים אך חשובים

| פריט | תיאור |
|------|-------|
| `worker/` | Cloudflare Worker לתמיכה ב-WebApp |
| `push_worker/` | Service Worker ל-Web Push |
| `chatops/ratelimit.py` | Rate limiting ל-ChatOps |
| `database/bookmarks_manager.py` | ניהול סימניות (יש API, חסר מדריך) |
| `database/collections_manager.py` | ניהול אוספים (יש API, חסר מדריך) |

---

## 📊 סיכום כמותי

| קטגוריה | מספר פריטים חסרים |
|---------|-------------------|
| מודולים/תיקיות שלמים | 4 תיקיות |
| Services חסרים | 5 שירותים |
| Monitoring | 3 מודולים |
| קונפיגורציה | 5 קבצים |
| WebApp מודולים | 8 מודולים |
| Scripts/Tools | 9 קבצים |
| Handlers | 3 קבצים |
| אחר | 5 פריטים |
| **סה"כ** | **~42 פריטים** |

---

## 💡 המלצות לפעולה

### עדיפות גבוהה 🔴

1. **Clean Architecture** - הוסף `docs/architecture/clean-architecture.rst`:
   - הסבר על מבנה תיקיית `src/`
   - תרשים שכבות (Domain → Application → Infrastructure)
   - דוגמאות שימוש

2. **מערכת תזכורות** - הוסף `docs/user/reminders.rst`:
   - מדריך למשתמש
   - פקודות בבוט
   - API Reference

3. **עדכן Services Index** - ערוך `docs/services/index.rst`:
   - הוסף את 5 השירותים החסרים
   - קישורים לעמודי API

### עדיפות בינונית 🟠

4. **כלי פיתוח** - הוסף `docs/development/tools.rst`:
   - `analyze_queries.py` - מדריך שימוש
   - `dup_scan.py` - מדריך שימוש

5. **סקריפטים** - הוסף `docs/development/scripts.rst`:
   - תיאור כל סקריפט
   - דוגמאות הרצה

6. **קונפיגורציה** - עדכן `docs/configuration.rst`:
   - הוסף סקשן לכל קובץ ב-`config/`
   - דוגמאות YAML/JSON

7. **Monitoring** - הוסף `docs/observability/log-aggregator.rst`:
   - הסבר על מנוע ה-fingerprinting
   - הגדרת חתימות שגיאות

### עדיפות נמוכה 🟡

8. **בינאום** - הוסף `docs/development/i18n.rst`:
   - מנגנון התרגום
   - איך להוסיף שפה

9. **WebApp מודולים** - הרחב `docs/webapp/`:
   - עמודים לכל API (community, snippets, push)

10. **Workers** - הוסף `docs/deployment/workers.rst`:
    - Cloudflare Worker
    - Push Worker

---

## 🔗 קישורים רלוונטיים

- [אתר התיעוד](https://amirbiron.github.io/CodeBot/)
- [docs/index.rst](/workspace/docs/index.rst) - תוכן עניינים ראשי
- [docs/services/index.rst](/workspace/docs/services/index.rst) - אינדקס שירותים
- [docs/configuration.rst](/workspace/docs/configuration.rst) - קונפיגורציה

---

## 📝 הערות

- חלק מהמודולים יש להם עמודי API אוטומטיים (`docs/api/*.rst`) אך חסר להם מדריך שימוש
- התיעוד הקיים איכותי, הפערים הם בעיקר במודולים חדשים יחסית
- מומלץ לעדכן את התיעוד כחלק מכל PR שמוסיף פיצ'ר חדש
