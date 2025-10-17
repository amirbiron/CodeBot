# 🤖 Code Keeper Bot - בוט שומר קבצי קוד

בוט טלגרם חכם ומתקדם לשמירה, ניהול ושיתוף קטעי קוד בצורה מסודרת ונוחה.

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-blue.svg)](https://t.me/my_code_keeper_bot)
[![WebApp](https://img.shields.io/badge/WebApp-Visit-blueviolet.svg)](https://code-keeper-webapp.onrender.com)
[![MongoDB](https://img.shields.io/badge/MongoDB-Database-green.svg)](https://mongodb.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/Docs-Website-blueviolet.svg)](https://amirbiron.github.io/CodeBot/)
[![RTD](https://readthedocs.org/projects/codebot/badge/?version=latest)](https://codebot.readthedocs.io/en/latest/?badge=latest)

<!-- CI/CD Badges -->
[![CI](https://github.com/amirbiron/CodeBot/actions/workflows/ci.yml/badge.svg)](https://github.com/amirbiron/CodeBot/actions/workflows/ci.yml)
[![Deploy](https://github.com/amirbiron/CodeBot/actions/workflows/deploy.yml/badge.svg)](https://github.com/amirbiron/CodeBot/actions/workflows/deploy.yml)
[![Security Scan](https://github.com/amirbiron/CodeBot/actions/workflows/security-scan.yml/badge.svg)](https://github.com/amirbiron/CodeBot/actions/workflows/security-scan.yml)
[![Performance Tests](https://github.com/amirbiron/CodeBot/actions/workflows/performance-tests.yml/badge.svg)](https://github.com/amirbiron/CodeBot/actions/workflows/performance-tests.yml)

[![Coverage](https://img.shields.io/codecov/c/github/amirbiron/CodeBot?branch=main)](https://app.codecov.io/gh/amirbiron/CodeBot/branch/main)

## 📋 תוכן עניינים

- התחלה מהירה
  - [✨ פיצ'רים עיקריים](#-פיצרים-עיקריים)
  - [🔧 דרישות מערכת](#-דרישות-מערכת)
  - [📦 התקנה](#-התקנה)
  - [⚙️ הגדרה](#️-הגדרה)
  - [🚀 הפעלה](#-איפה-להפעיל)
- שימוש
  - [📚 שימוש בסיסי](#-שימוש)
  - [📖 פקודות זמינות](#-פקודות-זמינות)
  - [🔍 דוגמאות שימוש](#-דוגמאות-שימוש)
  - [🧹 ניקוי קוד אוטומטי](#-ניקוי-קוד-אוטומטי)
  - [🏷️ נקודת שמירה בגיט](#-נקודת-שמירה-בגיט-git-checkpoint)
- מתקדם
  - [📖 תיעוד API](#-תיעוד-api)
  - [🛠️ פתרון בעיות](#️-פתרון-בעיות)
  - [📈 ביצועים](#-ביצועים)
  - [🔁 עדכוני תלויות ומיזוג אוטומטי](#-עדכוני-תלויות-ומיזוג-אוטומטי)
- תרומה וקהילה
  - [🤝 תרומה](#-תרומה)
  - [📞 תמיכה](#-תמיכה)
  - [📋 מצב הפרויקט](#-מצב-הפרויקט)
- משפטי
  - [🔒 אבטחה](#-אבטחה)
  - [📊 אנליטיקה](#-אנליטיקה)
  - [📄 רישיון](#-רישיון)

## ✨ פיצ'רים עיקריים

### 💾 ניהול קוד חכם
- **זיהוי שפה אוטומטי** - תמיכה ב-20+ שפות תכנות
- **הדגשת תחביר צבעונית** - תצוגה ברורה של הקוד
- **ניהול גרסאות מתקדם** - שמירת כל השינויים
- **השוואת גרסאות** - diff מפורט בין גרסאות

### 🏷️ ארגון ותיוג
- **תגיות גמישות** - ארגון קבצים לפי נושאים
- **תיאורים מפורטים** - הסבר לכל קטע קוד
- **חיפוש מתקדם** - מנוע חיפוש רב-ממדי
- **מיון וסינון** - מציאת הקוד המתאים במהירות

### 🌐 שיתוף ושיתוף פעולה
- **GitHub Gist** - שיתוף ישיר לגיסטים
- **Pastebin** - שיתוף ב-Pastebin
- **שיתוף פנימי** - לינקים זמניים מאובטחים
- **ייצוא לפורמטים** - ZIP, JSON, HTML

### 📊 ניתוח ואבחון
- **ניתוח קוד** - סטטיסטיקות מפורטות
- **בדיקת תחביר** - זיהוי שגיאות
- **מדדי מורכבות** - הערכת איכות הקוד
- **חילוץ פונקציות** - רשימת הפונקציות בקוד

### 💾 גיבוי ושחזור
- **גיבויים אוטומטיים** - שמירה תקופתית
- **ייצוא מלא** - כל הקבצים בפורמטים שונים
- **שחזור נתונים** - החזרת קבצים מגיבוי
- **דחיסה חכמה** - חיסכון במקום

## 🔧 דרישות מערכת

### תוכנה נדרשת
- **Python 3.9+** - שפת התכנות
- **MongoDB 4.4+** - מסד נתונים
- **Git** - לשכפול הפרויקט

### משאבי מערכת
- **RAM**: מינימום 512MB, מומלץ 1GB+
- **דיסק**: מינימום 1GB שטח פנוי
- **רשת**: חיבור יציב לאינטרנט

### חשבונות נדרשים
- **Telegram Bot** - יצירת בוט ב-BotFather
- **MongoDB** - מסד נתונים (מקומי או Atlas)
- **GitHub** (אופציונלי) - לשיתוף ב-Gist
- **Pastebin** (אופציונלי) - לשיתוף ב-Pastebin

## 📦 התקנה

### 1. שכפול הפרויקט

```bash
git clone https://github.com/yourusername/code-keeper-bot.git
cd code-keeper-bot
```

### 2. יצירת סביבה וירטואלית

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. התקנת תלויות

```bash
pip install -r requirements/production.txt -c constraints.txt
```

> מבנה דרישות חדש:
> - `requirements/base.txt` – תלויות בסיס משותפות.
> - `requirements/production.txt` – מרחיב את base לייצור.
> - `requirements/development.txt` – מרחיב את production לכלי פיתוח/טסטים.
> - `constraints.txt` – נוצר אוטומטית בבילד (`pip freeze`) ומשמש כ‑constraints לנעילה.

### 4. הורדת מודלי שפה נוספים (אופציונלי)

```bash
# עבור זיהוי שפות טוב יותר
python -m spacy download en_core_web_sm
python -m nltk.downloader punkt
```

## ⚙️ הגדרה

### 1. יצירת בוט טלגרם

1. פתח שיחה עם [@BotFather](https://t.me/BotFather)
2. שלח `/newbot`
3. בחר שם לבוט (למשל: "My Code Keeper")
4. בחר username (למשל: "my_code_keeper_bot")
5. שמור את הטוקן שתקבל

### 2. הגדרת MongoDB

#### MongoDB מקומי
```bash
# התקנה ב-Ubuntu/Debian
sudo apt-get install mongodb

# התקנה ב-macOS
brew install mongodb-community

# הפעלה
sudo systemctl start mongodb
```

#### MongoDB Atlas (ענן)
1. הרשם ב-[MongoDB Atlas](https://cloud.mongodb.com)
2. צור cluster חדש (Free Tier)
3. הגדר משתמש ומסיסמה
4. קבל connection string

### 3. הגדרת משתני סביבה

```bash
# העתק את קובץ הדוגמה
cp .env.example .env

# ערוך את הקובץ
nano .env
```

מלא את הערכים הבסיסיים:
```env
BOT_TOKEN=your_bot_token_here
MONGODB_URL=mongodb://localhost:27017/code_keeper_bot

# Admins & Chat restrictions (אופציונלי)
# מנהלים רשאים להריץ פקודות ChatOps רגישות (/errors, /triage, /rate_limit ...)
ADMIN_USER_IDS=123456789,987654321
# ניתן לאפשר הפעלה רק בצ'אטים מסוימים (השאירו ריק כדי לא להגביל)
ALLOWED_CHAT_IDS=-1001234567890
# Rate limit עדין לפקודות רגישות (שניות)
SENSITIVE_COMMAND_COOLDOWN_SEC=5
```

### 4. הגדרות אינטגרציה (אופציונלי)

#### GitHub Gist
1. עבור ל-[GitHub Settings > Tokens](https://github.com/settings/tokens)
2. צור Personal Access Token
3. בחר הרשאת `gist`
4. הוסף ל-.env: `GITHUB_TOKEN=your_token`

#### Pastebin
1. הרשם ב-[Pastebin](https://pastebin.com)
2. עבור ל-[API Documentation](https://pastebin.com/doc_api)
3. קבל API Key
4. הוסף ל-.env: `PASTEBIN_API_KEY=your_key`

 

## 🎯 איפה להפעיל?

| 🏠 **פיתוח מקומי** | 🌟 **Render.com** | 🐳 **VPS עם Docker** |
|---|---|---|
| ✅ חינם לחלוטין | ✅ חינם (עם הגבלות) | ❌ מחיר שרת |
| ✅ שליטה מלאה | ✅ פשוט ומהיר | ✅ שליטה מלאה |
| ❌ לא זמין 24/7 | ✅ זמין 24/7 | ✅ זמין 24/7 |
| ✅ מושלם לפיתוח | ✅ מושלם לייצור | ✅ גמישות מלאה |
| `docker-compose.dev.yml` | `render.yaml` | `docker-compose.yml` |

**💡 המלצה:** התחל עם Render לייצור וfork מקומי לפיתוח!

---

### הפעלה רגילה
```bash
python main.py
```

### הפעלה עם לוגים מפורטים
```bash
LOG_LEVEL=DEBUG python main.py
```

### 🏠 פיתוח מקומי

לפיתוח מקומי עם Docker:

```bash
# שכפול הפרויקט
git clone https://github.com/yourusername/code-keeper-bot.git
cd code-keeper-bot

# הכנת environment לפיתוח
cp .env.example .env.dev
# ערוך .env.dev עם BOT_TOKEN

# הפעלת סביבת פיתוח מקומית
docker-compose -f docker-compose.dev.yml --env-file .env.dev up

# גישה ל-MongoDB UI: http://localhost:8081
```

**מה כלול בסביבת פיתוח:**
- 📊 MongoDB local עם Mongo Express UI
- ⚡ Redis local לקאש
- 🔄 Hot reload על שינוי קבצים
- 🐛 Debug mode מופעל
- 📋 Logs מפורטים

### 🌟 פריסה לRender.com (מומלץ!)

Render הוא הפלטפורמה הטובה ביותר לפריסת הבוט:

#### שלב 1: הכנת מסד נתונים
1. הרשם ל-[MongoDB Atlas](https://cloud.mongodb.com) (חינם)
2. צור cluster חדש (Free Tier)
3. הגדר משתמש ומסיסמה
4. קבל connection string

#### שלב 2: פריסה לRender
1. הרשם ל-[Render.com](https://render.com)
2. התחבר עם GitHub account
3. לחץ על **"Background Worker"**
4. בחר את ה-repository שלך
5. מלא את ההגדרות:
   ```
   Name: code-keeper-bot
   Region: US East (Ohio) 
   Branch: main
   Dockerfile Path: ./Dockerfile
   ```

#### שלב 3: הגדרת משתני סביבה
ב-Render Dashboard → Environment Variables:
```
BOT_TOKEN=your_bot_token_here
MONGODB_URL=your_mongodb_atlas_connection_string
GITHUB_TOKEN=your_github_token (אופציונלי)
PASTEBIN_API_KEY=your_pastebin_key (אופציונלי)
LOG_LEVEL=INFO
```

#### שלב 4: הפעלה אוטומטית
- Render יבנה ויפרוס אוטומטית
- כל push ל-main יפעיל deployment חדש
- הבוט יפעל 24/7 ללא תשלום!

### הפעלה כשירות (Linux)

יצירת קובץ systemd:
```bash
sudo nano /etc/systemd/system/code-keeper-bot.service
```

תוכן הקובץ:
```ini
[Unit]
Description=Code Keeper Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/code-keeper-bot
Environment=PATH=/path/to/code-keeper-bot/venv/bin
ExecStart=/path/to/code-keeper-bot/venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

הפעלה:
```bash
sudo systemctl enable code-keeper-bot
sudo systemctl start code-keeper-bot
sudo systemctl status code-keeper-bot
```

### הפעלה ב-Docker (אופציונלי)

```dockerfile
# Dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements/ ./requirements/
RUN pip install -r requirements/production.txt -c constraints.txt || \
    (pip install -r requirements/production.txt && pip freeze | sort > constraints.txt && \
     pip install -r requirements/production.txt -c constraints.txt)

COPY . .
CMD ["python", "main.py"]
```

```bash
# בניה והפעלה
docker build -t code-keeper-bot .
docker run -d --env-file .env code-keeper-bot
```

## 📚 שימוש

### התחלת עבודה
1. שלח `/start` לבוט
2. קבל הודעת ברוכים הבאים
3. שלח `/help` לעזרה מפורטת

### שמירת קוד ראשון
```
/save hello.py
```
לאחר מכן שלח את הקוד:
```python
def hello_world():
    print("Hello, World!")
    return "success"

if __name__ == "__main__":
    hello_world()
```

### הוספת תגיות
```
/save api_client.py #python #api #client
```

### חיפוש קוד
```
/search python          # חיפוש לפי שפה
/search #api            # חיפוש לפי תגית
/search function        # חיפוש חופשי
```

## 📖 פקודות זמינות

### פקודות בסיסיות
| פקודה | תיאור | דוגמה |
|-------|-------|---------|
| `/start` | התחלת עבודה עם הבוט | `/start` |
| `/help` | עזרה מפורטת | `/help` |
| `/save` | שמירת קטע קוד | `/save script.py` |
| `/list` | רשימת כל הקבצים | `/list` |
| `/stats` | סטטיסטיקות אישיות | `/stats` |

### פקודות צפייה וניהול
| פקודה | תיאור | דוגמה |
|-------|-------|---------|
| `/show` | הצגת קובץ עם אפשרויות | `/show script.py` |
| `/edit` | עריכת קובץ קיים | `/edit script.py` |
| `/delete` | מחיקת קובץ | `/delete script.py` |
| `/rename` | שינוי שם קובץ | `/rename old.py new.py` |
| `/copy` | העתקת קובץ | `/copy script.py backup.py` |

### פקודות גרסאות
| פקודה | תיאור | דוגמה |
|-------|-------|---------|
| `/versions` | כל גרסאות הקובץ | `/versions script.py` |
| `/restore` | שחזור גרסה | `/restore script.py 3` |
| `/diff` | השוואת גרסאות | `/diff script.py 1 2` |

### פקודות חיפוש
| פקודה | תיאור | דוגמה |
|-------|-------|---------|
| `/search` | חיפוש מתקדם | `/search api` |
| `/tags` | כל התגיות שלך | `/tags` |
| `/languages` | שפות שבשימוש | `/languages` |
| `/recent` | קבצים אחרונים | `/recent 7` |

### פקודות שיתוף וייצוא
| פקודה | תיאור | דוגמה |
|-------|-------|---------|
| `/share` | שיתוף קובץ | `/share script.py` |
| `/export` | ייצוא קבצים | `/export zip` |
| `/download` | הורדת קובץ | `/download script.py` |

### פקודות ניתוח
| פקודה | תיאור | דוגמה |
|-------|-------|---------|
| `/analyze` | ניתוח מתקדם | `/analyze script.py` |
| `/validate` | בדיקת תחביר | `/validate script.py` |

### ChatOps (מנהלים בלבד)
| פקודה | תיאור |
|-------|-------|
| `/status` | בדיקות בריאות בסיסיות |
| `/errors` | שגיאות אחרונות (Sentry תחילה, עם Fallback) |
| `/triage` | דוח חקירה מקוצר + קישורי Grafana |
| `/rate_limit` | מצב Rate Limit של GitHub |
| `/enable_backoff` / `/disable_backoff` | שליטת Backoff ל-GitHub |
| `/minify` | דחיסת קוד | `/minify script.js` |

## 🔍 דוגמאות שימוש

### שמירת קוד Python עם תגיות
```
👤 /save web_scraper.py #python #scraping #requests

🤖 מוכן לשמור את web_scraper.py
   🏷️ תגיות: python, scraping, requests
   אנא שלח את קטע הקוד:

👤 import requests
from bs4 import BeautifulSoup

def scrape_website(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    return soup.get_text()

🤖 ✅ נשמר בהצלחה!
   📁 web_scraper.py
   🔤 שפה: python
   🏷️ תגיות: python, scraping, requests
   📊 גודל: 156 תווים
```

### חיפוש והצגה
```
👤 /search scraping

🤖 🔍 תוצאות חיפוש עבור: scraping

   1. web_scraper.py
   🔤 python | 📅 05/08
   📝 Web scraping utility

👤 /show web_scraper.py

🤖 📄 web_scraper.py
   
   [כפתורים אינטראקטיביים:]
   🎨 הדגשה צבעונית | 📊 ניתוח
   ✏️ עריכה | 🌐 שיתוף
   📋 העתקה | 📥 הורדה
```

### ניתוח קוד
```
👤 /analyze web_scraper.py

🤖 📊 ניתוח קוד עבור: web_scraper.py

   📏 מדדי גודל:
   • סה"כ שורות: 8
   • שורות קוד: 6
   • שורות הערות: 0
   • שורות ריקות: 2

   🔧 מבנה קוד:
   • פונקציות: 1
   • מחלקות: 0
   • ניקוד מורכבות: 2

   🔧 פונקציות שנמצאו:
   • scrape_website() (שורה 4)

   💡 הצעות לשיפור:
   • הוסף יותר הערות לקוד
```

### שיתוף ב-GitHub Gist
```
👤 /share web_scraper.py

🤖 🌐 שיתוף קובץ: web_scraper.py
   🔤 שפה: python
   📏 גודל: 156 תווים
   
   בחר אופן שיתוף:
   [🐙 GitHub Gist] [📋 Pastebin]
   [📱 קישור פנימי] [❌ ביטול]

👤 [לוחץ על GitHub Gist]

🤖 🐙 שותף ב-GitHub Gist!
   📄 קובץ: web_scraper.py
   🔗 קישור: https://gist.github.com/user/abc123
```

## 🏷️ נקודת שמירה בגיט (Git Checkpoint)
- **מה זה עושה?** לחיצה על הכפתור "נקודת שמירה בגיט" יוצרת תגית (tag) קלת-משקל על ה-HEAD של ברירת המחדל בריפו הנבחר, בשם בפורמט `checkpoint-YYYYMMDD-HHMMSS`.
- אם יצירת תגית נחסמת (למשל עקב הגנות), המערכת תיצור אוטומטית ענף (branch) בשם דומה כגיבוי.
- ניתן לשנות את הקידומת (`checkpoint`) באמצעות משתנה הסביבה `GIT_CHECKPOINT_PREFIX`.

#### איך לחזור לנקודת שמירה
בחר אחת מהאפשרויות:
- **ב-Git מקומי (tag):**
  1. משיכת תגיות האחרונות:
     ```bash
     git fetch --tags
     ```
  2. מעבר לנקודת שמירה כ-tag (קריאה בלבד):
     ```bash
     git checkout tags/checkpoint-YYYYMMDD-HHMMSS
     ```
  3. ליצירת ענף מהנקודה:
     ```bash
     git checkout -b restore-from-checkpoint
     ```

- **ב-Git מקומי (fallback לענף):**
  אם נוצר ענף במקום תגית, ניתן לעבור אליו ישירות:
  ```bash
  git fetch origin
  git checkout checkpoint-YYYYMMDD-HHMMSS
  ```
  אם השם כולל קידומת מותאמת, החלף את `checkpoint` בקידומת שהגדרת.

- **שחזור מלא של ברירת המחדל ל-tag (פעולה מסוכנת):**
  אם ברצונך להעביר את ענף ברירת המחדל אחורה ל-tag (מוחק היסטוריה קדימה):
  ```bash
  # ודא שיש לך הרשאות דחיפה
  git checkout main  # או שם ברירת המחדל
  git reset --hard tags/checkpoint-YYYYMMDD-HHMMSS
  git push --force-with-lease origin HEAD
  ```
  מומלץ לבצע זאת רק אם אתה מבין את ההשלכות על שותפים אחרים.

- **ב-GitHub UI:**
  - עבור ל-"Tags" בריפו, מצא את `checkpoint-...`, ולחץ "Create release" או צור branch מה-tag דרך הכפתור המתאים.
  - אם נוצר ענף כגיבוי, עבור ללשונית "Branches" ותוכל ליצור ממנו PR או לשנותו כנדרש.

> הערות:
> - יצירת נקודת שמירה יוצרת רפרנס (ref) לסנאפשוט של ה-commit הנוכחי (tag או branch), לא קובץ חדש.
> - לשינוי הקידומת לשם נקודת שמירה, הגדר משתנה סביבה למשל: `GIT_CHECKPOINT_PREFIX=snap`.

## 🧹 ניקוי קוד אוטומטי

הבוט מנקה תווים נסתרים ומנרמל את הקוד אוטומטית לפני שמירה, כדי למנוע דלטות מבלבלות ותקלות הדבקה.

- **מה מנורמל**:
  - הסרת BOM בתחילת הקובץ
  - המרת שורות ל-LF (CRLF/CR → LF)
  - החלפת NBSP/NNBSP לרווח רגיל
  - הסרת תווי רוחב‑אפס (ZWSP/ZWNJ/ZWJ) וסימוני כיוון (LRM/RLM/LRE/RLE/PDF/RLO/LRO/LRI/RLI/FSI/PDI)
  - הסרת תווי בקרה לא מודפסים (Cc) מלבד טאב/שורה חדשה
  - הסרת רווחים בסוף שורות

- **היכן חל**: כל מסלולי השמירה (`save_code_snippet`, `save_file`, `save_large_file`).

- **ברירת מחדל**: פעיל.

- **כיבוי/הפעלה**: באמצעות משתנה סביבה `NORMALIZE_CODE_ON_SAVE`.

```env
# .env
NORMALIZE_CODE_ON_SAVE=false  # לכיבוי (ברירת מחדל: true)
```

הניקוי אינו משנה לוגיקת קוד, אך עשוי להשפיע על דיפים (הסרת רווחי סוף שורה/תווים נסתרים).

## 📖 תיעוד API

### 📚 תיעוד מקיף ומפורט

הפרויקט כולל תיעוד API מלא שנוצר עם Sphinx, המספק:

- **תיעוד אוטומטי** - נוצר מ-docstrings בקוד
- **דוגמאות קוד** - דוגמאות מעשיות לכל פונקציה
- **API Reference** - תיעוד מפורט של כל המודולים
- **מדריכי שימוש** - הסברים מפורטים על השימוש

### 🛠️ בניית התיעוד

```bash
# התקנת תלויות תיעוד
pip install sphinx sphinx-rtd-theme sphinx-autodoc-typehints sphinxcontrib-napoleon

# בניית התיעוד
./build_docs.sh

# או ידנית:
cd docs
make html
```

התיעוד יהיה זמין ב: `docs/_build/html/index.html`

### 📂 מבנה התיעוד

```
docs/
├── index.rst           # דף הבית
├── installation.rst    # מדריך התקנה
├── configuration.rst   # הגדרות תצורה
├── examples.rst        # דוגמאות שימוש
├── api/               # תיעוד API
├── modules/           # תיעוד מודולים
├── handlers/          # תיעוד handlers
├── services/          # תיעוד services
└── database/          # תיעוד מסד נתונים
```

### 🌐 תיעוד אונליין

התיעוד זמין גם באופן מקוון:
- [Read the Docs](https://codebot.readthedocs.io/en/latest/)
- [GitHub Pages](https://amirbiron.github.io/CodeBot/)

### ✏️ תרומה לתיעוד

לשיפור התיעוד:
1. הוסף docstrings למודולים חדשים
2. עדכן דוגמאות קוד
3. תקן שגיאות כתיב
4. הוסף הסברים נוספים

ראה [docs/README.md](docs/README.md) למידע נוסף.

<!-- duplicated block ends here: removing duplicate below -->

<!-- removed duplicate examples block (second occurrence) -->

## 🛠️ פתרון בעיות

### בעיות נפוצות

#### הבוט לא מגיב ב-Render
```bash
# בדיקת לוגים ב-Render Dashboard
# Render Dashboard → Service → Logs

# בדיקת environment variables
# Render Dashboard → Service → Environment
# וודא ש-BOT_TOKEN מוגדר נכון

# בדיקת health endpoint
curl https://your-app-name.onrender.com/health
```

#### שגיאות מסד נתונים ב-MongoDB Atlas
```bash
# בדיקת connection string
# וודא שאין תווים מיוחדים לא מקודדים בסיסמה
# ב-Atlas → Database → Connect → Drivers

# בדיקת Network Access
# Atlas → Network Access → Add IP Address → Allow Access From Anywhere

# בדיקת Database User
# Atlas → Database Access → וודא שיש user עם readWrite permissions
```

#### Render sleep mode (Free Plan)
```bash
# הבוט נרדם אחרי 15 דקות חוסר פעילות
# פתרון 1: שדרג ל-Starter Plan ($7/month) לalways-on
# פתרון 2: שימוש ב-cron job לping כל 10 דקות:

# הוסף ב-GitHub Actions:
# name: Keep Render Awake
# on:
#   schedule:
#     - cron: '*/10 * * * *'
# jobs:
#   ping:
#     runs-on: ubuntu-latest
#     steps:
#       - run: curl https://your-app-name.onrender.com/health
```

#### בעיות זיכרון
```bash
# Render Free: 512MB RAM
# אם הבוט צורך יותר זיכרון:
# 1. שדרג ל-Starter Plan (2GB RAM)
# 2. או בדוק שימוש זיכרון:
python -c "
from utils import get_memory_usage
print(get_memory_usage())
"
```

### הפעלת מצב דיבוג ב-Render
```bash
# ב-Render Environment Variables:
DEBUG=true
LOG_LEVEL=DEBUG

# צפייה בלוגים לייב:
# Render Dashboard → Service → Logs → Live Logs
```

### בדיקת קונפיגורציה
```bash
python -c "
from config import config
import json
print(json.dumps(config.__dict__, indent=2, default=str))
"
```

### ניקוי מלא
```bash
# עצירת הבוט
pkill -f "python main.py"

# ניקוי לוגים
rm -f bot.log

# ניקוי קאש Python
find . -name "*.pyc" -delete
find . -name "__pycache__" -exec rm -rf {} +

# הפעלה מחדש
python main.py
```

## 📈 ביצועים

### מדדי ביצועים
- **זמן תגובה**: < 200ms לפקודות בסיסיות
- **קיבולת**: תמיכה ב-10,000+ קבצים למשתמש
- **זיכרון**: שימוש ממוצע 100-200MB
- **דיסק**: דחיסה אוטומטית של גיבויים

### אופטימיזציות
- **אינדקס מסד נתונים** - חיפוש מהיר
- **קאש זמני** - פחות שאילתות למסד
- **עיבוד אסינכרוני** - ביצועים טובים יותר
- **דחיסה חכמה** - חיסכון במקום

### ניטור
```bash
# סטטיסטיקות בזמן אמת
python -c "
from database import db
from utils import get_memory_usage
print('קבצים במערכת:', db.collection.count_documents({}))
print('זיכרון:', get_memory_usage())
"
```

### 🔁 עדכוני תלויות ומיזוג אוטומטי
- Dependabot יוצר PRs לעדכוני pip אחת לשבוע.
- ה-CI מוסיף בדיקה בשם "✅ Branch Protection Gate" כדי לסמן בכלל ההגנה של `main`.
- כדי לאפשר Auto‑merge לעדכוני patch: אפשר "Allow auto‑merge" והוסף Secret בשם `DEPENDABOT_AUTOMERGE` עם הערך `true`.
- כדי להימנע מפריסה בזמן עבודה: השאר PR כ‑Draft או כבה זמנית Auto Deploy ב‑Render לפני מיזוג ל‑`main`.

[מדריך מלא: עדכוני תלויות ומיזוג אוטומטי](docs/auto-updates-and-auto-merge.md)

## 🤝 תרומה

מוזמנים לתרום לפרויקט! 

### איך לתרום
1. עשו Fork לפרויקט
2. צרו branch חדש (`git checkout -b feature/amazing-feature`)
3. בצעו Commit לשינויים (`git commit -m 'Add amazing feature'`)
4. דחפו ל-branch (`git push origin feature/amazing-feature`)
5. פתחו Pull Request

### הנחיות פיתוח
- עקבו אחר PEP 8 style guide
- הוסיפו tests לפיצ'רים חדשים
- עדכנו את התיעוד
- בדקו שהקוד עובד לפני Pull Request

### רעיונות לשיפור
- תמיכה בשפות תכנות נוספות
- אינטגרציה עם GitLab/Bitbucket
- הרצת קוד ב-sandbox
- אפליקציית web נלווית
- תמיכה ב-voice messages
- בוט Discord נוסף

## 📞 תמיכה

### דרכי יצירת קשר
- **Issues**: [GitHub Issues](https://github.com/yourusername/code-keeper-bot/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/code-keeper-bot/discussions)
- **Email**: amirbiron@gmail.com
- **Telegram**: [@moominAmir](https://t.me/moominAmir)

### קהילה
- [Telegram Group](https://t.me/+nh9skKRgTEVkZmJk)

## 📋 מצב הפרויקט

### גרסה נוכחית: 1.0.0

### מה עובד:
- ✅ שמירה וניהול קבצים
- ✅ זיהוי שפות אוטומטי
- ✅ חיפוש מתקדם
- ✅ ניהול גרסאות
- ✅ שיתוף ב-Gist/Pastebin
- ✅ גיבויים ויצוא
- ✅ ניתוח קוד

### בפיתוח:
- 🚧 הרצת קוד מאובטחת
- 🚧 אפליקציית web
- 🚧 תמיכה ב-voice messages
- 🚧 אינטגרציה עם IDE-ים

### מתוכנן:
- 📅 תמיכה רב-לשונית
- 📅 ממשק ניהול admin
- 📅 סטטיסטיקות מתקדמות
- 📅 AI code suggestions

## 🔒 אבטחה

- **טוקנים מוצפנים**: אם מוגדר משתנה סביבה `TOKEN_ENC_KEY` (מפתח Fernet), טוקני GitHub נשמרים מוצפנים במסד הנתונים ומפוענחים רק בעת שימוש. ראו: `docs/SECURITY_TOKENS.md`.
- **טשטוש בלוגים**: המסנן מסיר טוקנים וערכים רגישים מכל הודעות הלוג.
- **מחיקה קלה**: ניתן למחוק את הטוקן בכל עת מהתפריט.
- **שקיפות**: הקוד פתוח; אין שליחה של הטוקן לשירותים חיצוניים פרט ל-GitHub API הנדרש לפעולה שביקשת.

המלצות:
- הפעלו את הבוט בסביבה משלכם והגדירו `TOKEN_ENC_KEY` (מפתח באורך 32 בתים base64 או מפתח Fernet).
- העניקו לטוקן ההרשאות המינימליות הנדרשות.

## 📊 אנליטיקה

הבוט אוסף נתונים בסיסיים לשיפור השירות:
- מספר קבצים שנשמרו
- שפות תכנות פופולריות
- פקודות נפוצות
- זמני תגובה

**לא נאספים:**
- תוכן הקוד עצמו
- מידע אישי
- היסטוריית שיחות

## 📄 רישיון

פרויקט זה מופץ תחת רישיון MIT. ראו את קובץ [LICENSE](LICENSE) לפרטים מלאים.

```
MIT License

Copyright (c) 2024 Code Keeper Bot

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 🎉 תודות

תודה מיוחדת לכל התורמים והמשתמשים שעוזרים לשפר את הבוט!

### Libraries Used
- [python-telegram-bot](https://python-telegram-bot.org/) - Telegram Bot API
- [pymongo](https://pymongo.readthedocs.io/) - MongoDB driver
- [pygments](https://pygments.org/) - Syntax highlighting
- [fuzzywuzzy](https://github.com/seatgeek/fuzzywuzzy) - Fuzzy string matching

---

**📧 נשמח לשמוע מכם! אם יש שאלות, רעיונות או בעיות - אל תהססו לפנות.**

**🌟 אם הבוט עוזר לכם, נשמח לכוכב ב-GitHub!**

---

*נבנה באהבה ל-developers 💚*

