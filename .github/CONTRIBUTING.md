# 🤝 מדריך תרומה מהיר

ברוכים הבאים לקהילת CodeBot! 🎉  
זהו מדריך on-boarding מקוצר לתרומות דרך GitHub.

> 📘 **רוצים פרטים נוספים?**  
> עברו ל[מדריך התרומה המלא](https://amirbiron.github.io/CodeBot/contributing.html) או ל[Quickstart](https://amirbiron.github.io/CodeBot/quickstart-contrib.html)

---

## 🚀 התחלה מהירה

### 1️⃣ הקמת סביבת פיתוח

```bash
# שכפול הפרויקט
git clone https://github.com/amirbiron/CodeBot.git
cd CodeBot

# יצירת סביבה וירטואלית
python -m venv .venv
source .venv/bin/activate  # ב-Windows: .venv\Scripts\activate

# התקנת תלויות
pip install -r requirements.txt
```

### 2️⃣ הרצת בדיקות

```bash
# הגדרת משתני סביבה
export DISABLE_ACTIVITY_REPORTER=1
export DISABLE_DB=1
export BOT_TOKEN=dummy_token
export MONGODB_URL='mongodb://localhost:27017/test'

# הרצת הטסטים
pytest -q
```

### 3️⃣ בדיקת תיעוד (אופציונלי אך מומלץ)

```bash
sphinx-build -b html docs docs/_build/html -W --keep-going
```

---

## 📝 כללי עבודה

### סגנון קומיטים - Conventional Commits

השתמשו בפורמט הבא להודעות commit:

| סוג | תיאור | דוגמה |
|-----|--------|-------|
| `feat` | פיצ'ר חדש | `feat: add export to CSV` |
| `fix` | תיקון באג | `fix: resolve timezone issue` |
| `docs` | שינוי בתיעוד | `docs: update installation guide` |
| `test` | הוספת/שיפור טסטים | `test: add unit tests for parser` |
| `refactor` | שינוי מבנה ללא שינוי פונקציונליות | `refactor: simplify error handling` |
| `chore` | משימות תחזוקה | `chore: update dependencies` |
| `perf` | שיפור ביצועים | `perf: optimize database queries` |

### שמות ענפים

מומלץ להשתמש בסגנון:
- `feat/feature-name` - לפיצ'רים חדשים
- `fix/bug-description` - לתיקוני באגים
- `docs/topic` - לשינויים בתיעוד
- `refactor/component-name` - לרפקטורינג

### כתיבת commit מפורט

לקומיט עם תיאור רב-שורות:

```bash
git commit -m "$(cat <<'EOF'
docs: add GitHub-friendly contributing guide

- Link to full docs site
- Add PR checklist & CI expectations
- Improve formatting and structure
EOF
)"
```

---

## ✅ צ'ק-ליסט לפני פתיחת PR

לפני שאתם פוחים Pull Request, ודאו ש:

- [ ] **כל הטסטים עוברים** מקומית, ודאו שה-CI יעבור
- [ ] **הודעת commit** בפורמט Conventional Commits
- [ ] **אין סודות או מידע רגיש** בקוד (API keys, tokens, PII)
- [ ] **תיעוד עודכן** במידת הצורך
- [ ] **תיאור PR ברור** הכולל:
  - 🎯 מה השתנה (What)
  - 🤔 למה השינוי נדרש (Why)
  - 🧪 איך בדקתם (Tests)
  - 🔄 איך לחזור לאחור במקרה הצורך (Rollback)
- [ ] **צילום מסך/וידאו** לשינויי UI (במידה ורלוונטי)

> 💡 **טיפ:** ראו את תבנית ה-PR המלאה ב-`/.github/pull_request_template.md`

---

## 🎯 בדיקות CI/CD

ה-PR שלכם יעבור את הבדיקות הבאות:

| בדיקה | תיאור |
|-------|--------|
| 🔍 **Code Quality & Security** | בדיקת איכות קוד ופרצות אבטחה |
| 🧪 **Unit Tests (3.11)** | טסטים על Python 3.11 |
| 🧪 **Unit Tests (3.12)** | טסטים על Python 3.12 |

---

## 🛡️ הנחיות בטיחות לטסטים

### עבודה עם קבצים

✅ **מומלץ:**
```python
def test_something(tmp_path):
    # עבודה בתיקייה זמנית
    test_file = tmp_path / "test.txt"
    test_file.write_text("content")
```

❌ **לא מומלץ:**
```python
# אל תכתבו לתיקייה הראשית!
with open("test.txt", "w") as f:
    f.write("content")
```

### מחיקת קבצים

✅ **מומלץ:**
```python
# מחיקה ספציפית
if temp_dir.exists() and temp_dir.is_dir():
    shutil.rmtree(temp_dir)
```

❌ **לא מומלץ:**
```python
# מחיקה גורפת - מסוכן!
os.system("rm -rf *")
```

### שינוי תיקיית עבודה

✅ **מומלץ:**
```python
# שימוש בנתיבים מוחלטים
abs_path = Path.cwd() / "relative" / "path"
```

❌ **לא מומלץ:**
```python
# שינוי cwd - רק אם באמת חייבים
os.chdir("/some/path")  # זכרו לשחזר!
```

> 📖 למידע מפורט: [מדריך בדיקות ומחיקות בטוחות](https://amirbiron.github.io/CodeBot/testing.html)

---

## 📚 משאבים נוספים

| נושא | קישור |
|------|--------|
| 📖 מדריך תרומה מלא | [contributing.html](https://amirbiron.github.io/CodeBot/contributing.html) |
| ⚡ Quickstart לתרומה | [quickstart-contrib.html](https://amirbiron.github.io/CodeBot/quickstart-contrib.html) |
| ✍️ כתיבת מסמכים | [doc-authoring.html](https://amirbiron.github.io/CodeBot/doc-authoring.html) |
| 🧪 מדריך בדיקות | [testing.html](https://amirbiron.github.io/CodeBot/testing.html) |
| 🔄 CI/CD | [ci-cd.html](https://amirbiron.github.io/CodeBot/ci-cd.html) |
| 🤖 הנחיות AI | [ai-guidelines.html](https://amirbiron.github.io/CodeBot/ai-guidelines.html) |

---

## 💬 צריכים עזרה?

- 🐛 **מצאתם באג?** פתחו [Issue](https://github.com/amirbiron/CodeBot/issues/new)
- 💡 **יש רעיון?** התחילו [Discussion](https://github.com/amirbiron/CodeBot/discussions)
- 📧 **שאלה אישית?** צרו קשר לפי פרטים ב-README

**תודה שאתם תורמים לפרויקט!💚**
