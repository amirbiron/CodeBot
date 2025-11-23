# תכנית בדיקות לבוט – Composition Root (Container) לשירות Snippet

מסמך זה מתאר בדיקות ידניות מהירות לבוט לאחר העברת יצירת התלויות ל־Container דומייני/אפליקטיבי. המטרה: לוודא שה־handlers צורכים את השירות מאותה נקודת אמת, בלי לשנות לוגיקה.

## איך לבדוק
- **מטרה**: שמירה עובדת, השפה מזוהה נכון, ותצוגה/עריכה ממשיכות כרגיל.
- **מה לחפש**:
  - ההודעה אחרי שמירה מציגה שפה נכונה.
  - תצוגת קוד (Preview) צובעת נכון.
  - עריכה לא שוברת את השפה השמורה.
  - לא מופיעות שגיאות ב־logs על יבוא/הקמה של השירות.

## סט דוגמאות לשמירה (Copy/Paste)

1) Bash – קובץ ללא סיומת (`run`)

```bash
#!/usr/bin/env bash
python main.py
```

- שם קובץ: `run`
- צפוי: שפה `bash`

2) Bash משודרג – `start`

```bash
#!/usr/bin/env bash
set -e
echo "🚀 Starting bot..."
python main.py
```

- שם קובץ: `start`
- צפוי: שפה `bash`

3) Taskfile – YAML ללא סיומת

```yaml
version: '3'
tasks:
  run:
    desc: Run the bot
    cmds:
      - python main.py
  install:
    desc: Install dependencies
    cmds:
      - pip install -r requirements.txt
```

- שם קובץ: `Taskfile`
- צפוי: שפה `yaml`

4) סביבה – `.env`

```ini
# === Bot Configuration ===
BOT_TOKEN=
OWNER_CHAT_ID=
```

- שם קובץ: `.env`
- צפוי: שפה `env`

5) Markdown רגיל – `doc.md`

```
# כותרת

- רשימה
- עוד פריט

קישור: [דוגמה](https://example.com)
```

- שם קובץ: `doc.md`
- צפוי: שפה `markdown`

6) Python בתוך `.md` – `Block.md` (תוכן פייתון מובהק)

```python
import os, asyncio

def main():
    print("hi")
```

- שם קובץ: `Block.md`
- צפוי: שפה `python` (אם אין סימני Markdown חזקים)

## בדיקות נוספות
- הצג קוד אחרי שמירה → וודא שה־preview צבוע לפי השפה.
- ערוך את אותו קובץ → שמירה חוזרת מציגה שפה עקבית.
- קבצים מיוחדים: `Dockerfile`, `Makefile`, `.gitignore`, `.dockerignore` → שפה תואמת שם הקובץ.

## תקלות שכדאי לעקוב אחריהן
- הבוט מציג `text` במקום שפה צפויה (בדוק shebang/שם/תוכן).
- חריגות Import על `src.infrastructure.composition`.
- זיהוי `.md` כפייתון למרות Markdown בולט (כותרות/רשימות/גדרות קוד).

