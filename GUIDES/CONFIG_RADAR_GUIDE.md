# 📡 Config Radar – מדריך למנהלי מערכת

מסך **Config Radar** מספק הצצה ויזואלית לכל קבצי הקונפיגורציה הקריטיים שנמצאים בריפו בלבד (`alerts.yml`, `error_signatures.yml`, `image_settings.yaml`). המטרה היא לאפשר למנהלים לזהות במהירות אילו ערכים פעילים כרגע, מתי עודכנו, ומה מצבה של הסכמה.

---

## ✨ איך מגיעים למסך?

1. היכנסו ל-WebApp עם משתמש שיש לו הרשאת `is_admin`.
2. פתחו את `/settings`.
3. תופיע לשונית חדשה בשם **Config Radar** עם שלוש כרטיסיות: התראות, חתימות שגיאה והגדרות תמונה.

---

## 🧭 פירוט הכרטיסיות

### 1. Alerts Overview
- מציג את `window_minutes`, `min_count_default` ו-`cooldown_minutes`.
- רשימת הקטגוריות המוגדרות כ-`immediate` מסומנת בבירור.
- הטבלה משלבת את קטגוריות `error_signatures.yml` כדי להראות מי מהן immediate ומה ברירת המחדל של חומרה/מדיניות.

### 2. Error Signatures
- בראש הכרטיסייה מוצגת ה-Noise Allowlist עם Regexים מודגשים.
- כל קטגוריה נפתחת כ-accordion ומציגה את החתימות, חומרה, מדיניות ותיאור.
- שגיאות בוולידציה (למשל Regex שבור) מוצגות כחלק מחיווי הסטטוס.

### 3. Image Settings
- מראה ערכי ברירת מחדל (ערכת נושא, סגנון, רוחב, גופן).
- מציג את המגבלות הקריטיות: מספר שורות מקסימלי ל-preview ול-image_all, תקציב תווים, מספר תמונות ועוד.
- רשימות הפורמטים והרוחבים הזמינים מוצגות כ-Chips.

---

## ✅ ולידציה + Git Info

- בכל טעינה (או בלחיצה על **Validate Schema**) נשלחת בקשת GET ל-`/api/config/radar`.
- התגובה מאחדת את כל הקבצים ומוסיפה:
  - `git` metadata לכל קובץ (`path`, `last_commit`, `last_updated`, `author`).
  - אובייקט `validation` עם סטטוס כולל ורשימת בעיות (כולל פירוט שדה/קובץ).
- הכניסה ל-API מוגבלת למשתמשים אדמינים ומסומנת כ-read only.

---

## 🌐 API Reference

```
GET /api/config/radar
Headers: Cookie Session רגיל
Response:
{
  "ok": true,
  "checked_at": "...",
  "alerts": {...},
  "error_signatures": {...},
  "image_settings": {...},
  "validation": {
    "status": "ok" | "error",
    "issues": [
      {"file": "error_signatures.yml", "field": "...", "message": "..."}
    ],
    "files": {"config/alerts.yml": {"status": "ok", "issues": []}, ...}
  }
}
```

> טיפ: ה-UI משתמש באותו Endpoint גם עבור Validate, כך שכל קריאה היא snapshot עדכני מה-Git.

---

## 🛟 מתי להשתמש?

- לפני Deploy: וודאו שאין בעיות בסכמה (Regex שבור, ערכים חסרים וכו').
- בעת חקירה: בדקו אם קטגוריה מסומנת כ-immediate או איזה מגבלת תמונה חלה.
- בעת שינוי קונפיג: ודאו שהערך נטען כמצופה ושמרו מעקב אחר commit אחרון.
