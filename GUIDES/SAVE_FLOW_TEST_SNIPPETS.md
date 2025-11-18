# בדיקות ידניות לזרימת שמירה בבוט (save_flow)

מסמך זה מרכז קטעי קוד ותסריטי בדיקה מומלצים ל־/save, גם במסלול הישן וגם במסלול החדש (ארכיטקטורה שכבתית) המופעל בדגל.

## הפעלת המסלול החדש (פיילוט)

1. הגדר משתנה סביבה לפני הרצת הבוט:
   - `USE_NEW_SAVE_FLOW=1`
2. הרץ כרגיל. אם הדגל לא מוגדר, הבוט יעבוד במסלול הישן ללא שינוי.

המסלול החדש מחליף את בדיקת קובץ קיים ואת שמירת הקובץ דרך שכבות Application/Domain/Infrastructure, עם תאימות מלאה למסכי ההצלחה הקיימים.

---

## תסריט בסיסי – Python

- פקודה: `/save`
- קוד:
```python
def add(a, b):
    return a + b

if __name__ == "__main__":
    print(add(2, 3))
```
- שם קובץ: `script.py`
- הערה: אופציונלי
- צפוי:
  - שפה מזוהה: `python`
  - נרמול שורות ל־LF, הסרת רווחי סוף שורה
  - שמירה מוצלחת + הופעת כפתורי פעולה

## תסריט בסיסי – JavaScript

- קוד:
```javascript
function hello(name) {
  console.log(`hello, ${name}`)
}
hello('world')
```
- שם קובץ: `app.js`
- צפוי: `javascript`

## TypeScript קצר

```typescript
const sum = (a: number, b: number) => a + b;
export default sum;
```
- שם קובץ: `sum.ts`
- צפוי: `typescript`

## HTML קצר

```html
<!doctype html>
<html>
  <head><meta charset="utf-8" /></head>
  <body><h1>שלום</h1></body>
</html>
```
- שם קובץ: `index.html`
- צפוי: `html`

---

## נרמול – תווים נסתרים וכיווניות

1) לוגיקת נרמול של תווי כיווניות/רוחב־אפס:

- קוד (הדבק באמת את התו הנסתר U+200E בין hello ל-world):
```python
print("hello‎world")
```
- שם קובץ: `bidi.py`
- צפוי: תווי כיווניות יוסרו; יוצג `helloworld` בקוד הנשמר.

2) לוגיקת נרמול של רצפים מילוליים (escaped) של יוניקוד:

- קוד (כולל רצף מילולי):
```python
text = "hidden=\u200B"
print(text)
```
- שם קובץ: `escaped_hidden.py`
- צפוי: הרצף `\u200B` המייצג תו מוסתר (Cf) יוסר בטקסט הנשמר.

3) רווח קשיח (NBSP):

- קוד (הדבק NBSP U+00A0 בין שני המילים):
```python
print("foo bar")
```
- שם קובץ: `nbsp.py`
- צפוי: NBSP יוחלף ברווח רגיל.

4) סוף שורה ו־CRLF:

- קוד עם CRLF (Windows) ורווחים בסוף שורה – אפשר להדביק:
```python
print("a")  \r\n
print("b")  
```
- שם קובץ: `eol.py`
- צפוי: המרה ל־LF והסרת רווחי סוף שורה.

> הערה: ייתכנו שינויים קלים בתצוגת אימוג'ים כאשר יש ואריאציות יוניקוד (Variation Selectors), זה תקין לשלב זה.

---

## בדיקת אזהרת סודות (Long Collect)

במצב איסוף ארוך (תפריט “✍️ איסוף קוד ארוך”):

1. שלח קטע עם טוקן GitHub:
```text
ghp_abcdefghijklmnopqrstuvwxyz1234567890abcd
```
2. אמורה להופיע אזהרה על זיהוי דפוס סודי. איחד/י עם `/done` והמשך לשם קובץ.

---

## בדיקת שם קובץ, כפילויות וגרסאות

1. שמור קובץ בשם `dup.py` עם:
```python
print("v1")
```
2. נסה לשמור שוב `dup.py` עם:
```python
print("v2")
```
3. צפוי: במסך בחירת שם יופיע מסר “קובץ קיים” ואופציות (החלף/שנה שם/בטל). אם מחליפים, גרסה צריכה לעלות (בדוק בתפריט “📚 היסטוריה”).

---

## הערות ארוכות וחיתוך

- בתיבת ההערה, הדבק טקסט ארוך מאוד (> 280 תווים). הצפוי: ההערה תיחתך באופן אלגנטי והממשק מציין זאת.

---

## בדיקות רגרסיה במסלול הישן

כבה את הדגל `USE_NEW_SAVE_FLOW` והריץ את אותם תסריטים:
- ודא שההתנהגות זהה פונקציונלית (זיהוי שפה, נרמול, כפתורי פעולה, היסטוריית גרסאות).
- שים לב להבדלים קלים אפשריים בנרמול תווים נסתרים – זה צפוי ומנוטר.

---

## צ'קליסט קבלה מהירה

- [ ] שמירה מוצלחת ל־Python/JS/TS/HTML
- [ ] נרמול: כיווניות, NBSP, רווחי סוף שורה, CRLF → LF
- [ ] אזהרת סודות ב־Long Collect
- [ ] כפילויות: מסר ואופציות תקינים
- [ ] גרסאות: עלייה ב־version ונראות בהיסטוריה
- [ ] זמנים/ביצועים: אין האטה חריגה לעומת הבייסליין

---

## תקלות שכדאי לשים אליהן לב

- חריגות `save_file_failed`, `db_*_error` בלוגים
- זיהוי שפה לא צפוי (בעיקר קבצים לא סטנדרטיים)
- תלונות על “נעלמו תווים” (RTL/ריווח) – פתחו אישו עם קטע מינימלי משחזר


## מקרי קצה לזיהוי שפה (סיומת מול תוכן)

> המטרה: לוודא שזיהוי השפה עקבי והגיוני. ברירת המחדל היא לפי סיומת, אך כאשר יש אותות תוכן חזקים לשפה אחרת – התוכן אמור לגבור או שתופיע הצעת בחירה, לעולם לא נפילה ל-`text` במקרה של קוד “טהור”.

### A. Markdown רגיל – צריך להישאר Markdown

- קוד להדבקה:
```markdown
# כותרת

- רשימה
- עוד פריט

קישור: [דוגמה](https://example.com)
```
- שם קובץ: `doc.md`
- צפוי: `markdown`

### B. `.md` שמכיל קוד Python “טהור” (ללא גדרות Markdown)

- קוד להדבקה (תואם למקרה שדווח):
```python
"""
Mongo Distributed Lock – מניעת telegram.error.Conflict

רעיון:
- קולקציה אחת bot_locks
- SERVICE_ID מי נועל, INSTANCE_ID מי מריץ
- לוק יש expiresAt + TTL לנעילות יתומות
"""

import os, asyncio
from datetime import datetime, timedelta
from pymongo import MongoClient, ReturnDocument

URI = os.getenv("MONGODB_URI")
SERVICE_ID = os.getenv("SERVICE_ID", "codebot-prod")
INSTANCE_ID = os.getenv("RENDER_INSTANCE_ID", "local")
LEASE = int(os.getenv("LOCK_LEASE_SECONDS", "60"))
RETRY = int(os.getenv("LOCK_RETRY_SECONDS", "20"))

col = MongoClient(URI)["codebot"]["bot_locks"]
col.create_index("expiresAt", expireAfterSeconds=0)

async def acquire_lock():
    """רכישת לוק – חוזר רק כשהאינסטנס הוא הבעלים."""
    while True:
        now = datetime.utcnow()
        exp = now + timedelta(seconds=LEASE)

        doc = col.find_one_and_update(
            {
                "_id": SERVICE_ID,
                "$or": [
                    {"expiresAt": {"$lte": now}},   # תפוס אבל פג תוקף
                    {"owner": INSTANCE_ID},           # חידוש
                ],
            },
            {"$set": {"owner": INSTANCE_ID, "expiresAt": exp, "updatedAt": now}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        if doc["owner"] == INSTANCE_ID:
            print(f"✅ lock by {INSTANCE_ID} until {exp}")
            return

        print(f"🔒 held by {doc['owner']} – retry in {RETRY}s")
        await asyncio.sleep(RETRY)

async def heartbeat():
    """שמירת בעלות – רענון expiresAt. מאבד? יוצא."""
    interval = max(5, int(LEASE * 0.4))

    while True:
        await asyncio.sleep(interval)
        now = datetime.utcnow()
        exp = now + timedelta(seconds=LEASE)

        doc = col.find_one_and_update(
            {"_id": SERVICE_ID, "owner": INSTANCE_ID},
            {"$set": {"expiresAt": exp, "updatedAt": now}},
            return_document=ReturnDocument.AFTER,
        )

        if not doc:
            print("⚠️ lost lock – exit")
            os._exit(0)

        print(f"💓 heartbeat → {exp}")

async def main():
    await acquire_lock()
    asyncio.create_task(heartbeat())

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()

if __name__ == "__main__":
    asyncio.run(main())
```
- שם קובץ: `Block.md`
- צפוי: `python` (או הצעת בחירה ל-`python`), לא `text`.

### C. `.py` שמכיל Markdown

- קוד להדבקה:
```text
# כותרת Markdown

- רשימה
- פריט נוסף

```
- שם קובץ: `notes.py`
- צפוי: ברירת מחדל `python` (לפי סיומת). אם תוצג הצעה לשנות ל־`markdown` עקב אותות תוכן – זה גם תקין. לא אמור להיסווג ל־`text`.

### D. Python עם shebang – ללא סיומת

- קוד להדבקה:
```python
#!/usr/bin/env python3
print("hello")
```
- שם קובץ: `run` (ללא סיומת)
- צפוי: `python`

---

## דוגמאות לשפות/פורמטים נפוצים (בדיקת זיהוי מהירה)

### Shell (bash)

```bash
#!/usr/bin/env bash
set -euo pipefail
echo "ok"
```
- שם קובץ: `script.sh` או ללא סיומת `script`
- צפוי: `shell`

### Dockerfile (ללא סיומת)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
CMD ["python", "main.py"]
```
- שם קובץ: `Dockerfile`
- צפוי: `dockerfile`

### YAML (GitHub Actions)

```yaml
name: ci
on: [push, pull_request]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
```
- שם קובץ: `.github/workflows/ci.yml`
- צפוי: `yaml`

### JSON

```json
{
  "name": "demo",
  "version": "1.0.0",
  "private": true
}
```
- שם קובץ: `package.json`
- צפוי: `json`

### TOML

```toml
[tool.black]
line-length = 100
target-version = ["py311"]
```
- שם קובץ: `pyproject.toml`
- צפוי: `toml`

### INI

```ini
[server]
port = 8080
host = 0.0.0.0
```
- שם קובץ: `settings.ini`
- צפוי: `ini`

### dotenv

```dotenv
SECRET_KEY=abc123
DEBUG=false
```
- שם קובץ: `.env`
- צפוי: `dotenv`

### Makefile (ללא סיומת)

```makefile
.PHONY: all
all:
	@echo "build"
```
- שם קובץ: `Makefile`
- צפוי: `makefile`

### SQL

```sql
CREATE TABLE users (id INT PRIMARY KEY, name TEXT);
SELECT * FROM users WHERE id = 1;
```
- שם קובץ: `schema.sql`
- צפוי: `sql`

### HTML/CSS קצר

```html
<!doctype html>
<html>
  <head>
    <style>body { font-family: sans-serif; }</style>
  </head>
  <body><h1>שלום</h1></body>
</html>
```
- שם קובץ: `page.html`
- צפוי: `html`

### TypeScript

```typescript
type User = { id: number; name: string };
export const greet = (u: User) => `hi ${u.name}`;
```
- שם קובץ: `types.ts`
- צפוי: `typescript`

### Rust

```rust
fn main() { println!("hello"); }
```
- שם קובץ: `main.rs`
- צפוי: `rust`

---

## מקרים נוספים לבדיקה ידנית (תווים וגדלים)

- קובץ גדול (1000+ שורות) לבדיקת איסוף ארוך: שכפל שורת קוד קצרה עד שמתקבלת הודעת איסוף ארוך, ודא שאין דילוגים/בליעות.
- RTL ו-NBSP: שלבו טקסט בעברית עם NBSP (U+00A0) ובדקו שהנרמול תקין ושלא “נעלמים” תווים משמעותיים.
- קבצים ללא סיומת: ודאו שהshebang/תוכן מוביל לזיהוי נכון ולא ל-`text`.

