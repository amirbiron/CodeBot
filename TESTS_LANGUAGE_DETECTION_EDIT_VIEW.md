# בדיקות – זיהוי שפה בזרימות עריכה/תצוגה

מסמך זה מרכז מה לבדוק ידנית ומה מכוסה אוטומטית בטסטים.

## מה לבדוק
- שמירה/עריכה (regular):
  - doc.md עם Markdown רגיל נשמר/מתעדכן כ־markdown
  - Block.md עם Python מובהק (import/def/class) נשמר/מתעדכן כ־python
  - Taskfile (ללא סיומת) עם YAML – נשמר/מתעדכן כ־yaml
  - .ENV עם KEY=VALUE – נשמר/מתעדכן כ־env
  - run/start עם `#!/usr/bin/env bash` – נשמר/מתעדכן כ־bash
- עריכת קובץ גדול (large file):
  - run/start עם shebang bash – נשמר כ־bash
- תצוגה (view):
  - קובץ שמור עם שפה לא אמינה (text) – מזוהה מחדש ומוצג עם שפה נכונה (yaml/env/bash/python)
  - doc.md עם Markdown רגיל – יוצג כ־markdown (ולא “python”)

## דוגמאות קוד

### Markdown רגיל (צריך להיות markdown)
```markdown
# כותרת

- רשימה
- עוד פריט

קישור: [דוגמה](https://example.com)
```

### Python מובהק (יכול לגבור על .md)
```python
def main():
    import os
    return 1
```

### Bash עם shebang
```bash
#!/usr/bin/env bash
set -e
echo "🚀 Starting bot..."
python main.py
```

### Taskfile (YAML) ללא סיומת
```yaml
version: '3'
tasks:
  run:
    desc: Run the bot
    cmds:
      - python main.py
```

### ENV
```dotenv
# === Bot Configuration ===
BOT_TOKEN=
OWNER_CHAT_ID=
```

## מה הטסטים האוטומטיים מכסים
- עריכת קובץ גדול עם shebang → bash
- עריכת קובץ רגיל: Taskfile → yaml, .ENV → env
- תצוגת קובץ כששמור כ־text: YAML/ENV/Bash/Python מזוהים מחדש ומוצגים עם שפה נכונה
- תצוגת Markdown רגיל נשארת markdown
