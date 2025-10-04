# 📦 ניהול תלויות ואבטחה

## 🔍 סקירת requirements.txt

### מצב נוכחי
- **139 שורות** dependencies
- חלקן לא בשימוש פעיל
- גרסאות ישנות במקרים מסוימים
- bloated - תלויות שלא נחוצות לייצור

---

## ⚠️ בעיות שזוהו

### 1. תלויות שלא נחוצות

```python
# requirements.txt
docker==6.1.3              # ❌ למה בוט צריך Docker SDK?
subprocess32==3.5.4        # ❌ Python 2 compatibility (deprecated)
alembic==1.13.1           # ❌ אין migrations בפרויקט
celery==5.3.4             # ❌ לא בשימוש (אין worker tasks)
pandas==2.1.4             # ❌ overkill לעיבוד קבצים
xlsxwriter==3.1.9         # ❌ אין ייצוא Excel
openpyxl==3.1.2           # ❌ אין קריאת Excel
asyncio-mqtt==0.13.0      # ❌ אין MQTT
aioredis==2.0.1           # ⚠️ deprecated! use redis[asyncio]
```

**הערכה**: ~15 תלויות מיותרות = ~200MB installation

---

### 2. גרסאות ישנות / בעיות תאימות

```python
pendulum==2.1.2; python_version < '3.12'  # ⚠️ מיושן
pendulum>=3.0.0; python_version >= '3.12' # conditional dependency - מסובך
```

---

### 3. חוסר הפרדה: dev vs prod

כל התלויות בקובץ אחד:
- pytest, black, flake8 (dev) מותקנים גם ב-production
- זמן build ארוך
- שטח דיסק מבוזבז

---

## ✅ פתרונות

### 1. פיצול requirements

```
requirements/
├── base.txt          # shared
├── production.txt    # prod only
└── development.txt   # dev only
```

**requirements/base.txt** (core dependencies):
```python
# Core Telegram Bot
python-telegram-bot[job-queue]==20.7

# Database
pymongo==4.10.1
motor==3.3.2

# Code Processing
pygments==2.17.2
python-magic==0.4.27
chardet==5.2.0
langdetect==1.0.9

# Web & APIs
requests==2.31.0
aiohttp==3.9.5
httpx==0.25.2

# File Processing
python-dotenv==1.0.0
aiofiles==23.2.1

# Search & Text
fuzzywuzzy==0.18.0
python-levenshtein==0.23.0

# Utilities
python-dateutil==2.8.2
pytz==2023.3
arrow==1.3.0

# Security
bcrypt==4.1.2
cryptography==42.0.5

# Logging
structlog==23.2.0
sentry-sdk==1.39.2

# Cache (optional but common)
redis==5.0.4
```

**requirements/production.txt**:
```python
-r base.txt

# Production-specific
gunicorn==23.0.0
uvicorn==0.24.0
whitenoise==6.6.0

# Optional: Google/GitHub if configured
google-api-python-client==2.141.0
google-auth==2.34.0
google-auth-oauthlib==1.2.1
PyGithub==2.1.1
```

**requirements/development.txt**:
```python
-r production.txt  # includes everything

# Testing
pytest==7.4.3
pytest-asyncio==0.21.1
pytest-cov==4.1.0
pytest-mock==3.15.1
faker==19.12.0
freezegun==1.2.2

# Code Quality
black==23.11.0
flake8==6.1.0
mypy==1.7.1
bandit==1.7.5

# Documentation
sphinx==7.4.7
sphinx-rtd-theme==2.0.0
```

---

### 2. Poetry במקום pip (אופציונלי אבל מומלץ)

```toml
# pyproject.toml
[tool.poetry]
name = "code-keeper-bot"
version = "1.0.0"
description = "Telegram bot for managing code snippets"

[tool.poetry.dependencies]
python = "^3.11"
python-telegram-bot = {version = "20.7", extras = ["job-queue"]}
pymongo = "4.10.1"
# ... core dependencies

[tool.poetry.group.dev.dependencies]
pytest = "^7.4.3"
black = "^23.11.0"
# ... dev dependencies

[tool.poetry.group.optional.dependencies]
# For GitHub integration
PyGithub = "2.1.1"
# For Drive integration  
google-api-python-client = "2.141.0"
```

**יתרונות**:
- `poetry.lock` מבטיח builds reproducible
- ניהול versions אוטומטי
- virtual envs מובנה
- פקודות פשוטות: `poetry add`, `poetry install`

---

### 3. Dependency Security Scanning

#### GitHub Dependabot (כבר קיים ✅)
```yaml
# .github/dependabot.yml (exists)
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
```

#### Safety - בדיקת vulnerabilities
```bash
# הוסף ל-CI
pip install safety
safety check --json

# או עם poetry
poetry add --group dev safety
poetry run safety check
```

#### Snyk
```yaml
# .github/workflows/security.yml
- name: Run Snyk
  uses: snyk/actions/python@master
  env:
    SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
```

---

### 4. Lock Files

**ליצור constraints.txt עדכני**:
```bash
# freeze exact versions
pip freeze > constraints.txt

# אחר כך בהתקנה:
pip install -r requirements/production.txt -c constraints.txt
```

**או עם pip-tools**:
```bash
pip install pip-tools

# קומפילציה:
pip-compile requirements/production.in --output-file requirements/production.txt

# sync environment:
pip-sync requirements/production.txt
```

---

## 🗑️ תלויות להסרה

### מיידי (לא בשימוש):
```python
docker==6.1.3
subprocess32==3.5.4      # Python 2 only
alembic==1.13.1
celery==5.3.4
pandas==2.1.4
xlsxwriter==3.1.9
openpyxl==3.1.2
asyncio-mqtt==0.13.0
aioredis==2.0.1          # deprecated
memory-profiler==0.61.0  # dev tool
```

**הערכה**: חיסכון ~180MB + זמן build

### שקול (תלוי בשימוש):
```python
cairosvg==2.7.1          # רק אם יש syntax highlighting לתמונות
textstat==0.7.3          # statistics על טקסט - נדיר
gitpython==3.1.41        # רק אם יש Git operations
beautifulsoup4==4.12.2   # web scraping - נדרש?
markdown==3.5.1          # formatting - נדרש?
html2text==2020.1.16     # conversions - נדרש?
```

---

## 🔄 תהליך עדכון תלויות

### שבועי (אוטומטי):
- Dependabot יוצר PRs
- CI מריץ טסטים
- אם ירוק → merge

### חודשי (ידני):
```bash
# רשימת תלויות מיושנות
pip list --outdated

# או
poetry show --outdated

# עדכון major versions (זהיר!)
pip install --upgrade <package>
poetry update <package>

# הרצת טסטים מלאים
pytest
```

### רבעוני (audit):
```bash
# בדיקת security
safety check
snyk test

# ניקוי תלויות מיותרות
pip-autoremove -l  # list unused
pip-autoremove <package>
```

---

## 📊 CI/CD Integration

```yaml
# .github/workflows/dependencies.yml
name: Dependency Check

on:
  schedule:
    - cron: '0 0 * * 0'  # שבועי
  pull_request:
    paths:
      - 'requirements/**'
      - 'pyproject.toml'
      - 'poetry.lock'

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Install dependencies
        run: pip install safety pip-audit
      
      - name: Safety check
        run: safety check --json
      
      - name: Pip audit
        run: pip-audit
      
      - name: Check for outdated
        run: pip list --outdated > outdated.txt
      
      - name: Upload report
        uses: actions/upload-artifact@v3
        with:
          name: dependency-report
          path: outdated.txt
```

---

## 📋 תוכנית פעולה

### מיידי (שבוע 1):
- [ ] הסרת 10 תלויות מיותרות
- [ ] פיצול requirements: base/prod/dev
- [ ] הוספת safety check ל-CI
- [ ] עדכון README עם הנחיות התקנה חדשות

### קצר טווח (חודש 1):
- [ ] Poetry migration (אופציונלי)
- [ ] Snyk integration
- [ ] Dependency dashboard
- [ ] Policy: בדיקת security לפני merge

### ארוך טווח:
- [ ] אוטומציה מלאה של updates
- [ ] SLA: critical vulnerabilities < 24h
- [ ] תיעוד dependency choices

---

## 💡 Best Practices

1. **Pin all versions** - לא `requests>=2.0`, אלא `requests==2.31.0`
2. **Use constraints file** - reproducible builds
3. **Separate dev/prod** - קל יותר ומהיר יותר
4. **Security first** - סריקה שבועית
5. **Document why** - למה כל תלות נחוצה
6. **Minimal is better** - פחות dependencies = פחות surface attack

---

## 🎯 תוצאה צפויה

**לפני:**
- 139 תלויות
- ~500MB installation
- 5 דקות build
- CVEs לא ידועים

**אחרי:**
- ~80 תלויות (core + prod)
- ~300MB installation
- 3 דקות build
- 0 CVEs known
- עדכונים אוטומטיים

---

**Remember**: Dependencies are liabilities, not assets 🎯
