## 🤝 מדריך תרומה מקוצר (GitHub)

ברוכים הבאים! כאן תמצאו גרסת on‑boarding קצרה ונוחה לתרומות דרך GitHub.
למדריך המלא, המעוצב באתר התיעוד, עברו ל‑[מדריך תרומה המלא](https://amirbiron.github.io/CodeBot/contributing.html) או ל‑[Quickstart לתרומה](https://amirbiron.github.io/CodeBot/quickstart-contrib.html).

---

### מה מהריצים לפני PR
- **התקנה מקומית**:
  ```bash
  git clone https://github.com/amirbiron/CodeBot.git
  cd CodeBot
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  ```
- **הרצת טסטים (IO רק ב‑tmp)**:
  ```bash
  export DISABLE_ACTIVITY_REPORTER=1
  export DISABLE_DB=1
  export BOT_TOKEN=x
  export MONGODB_URL='mongodb://localhost:27017/test'
  pytest -q
  ```
- **בדיקת Docs (אופציונלי אך מומלץ)**:
  ```bash
  sphinx-build -b html docs docs/_build/html -W --keep-going
  ```

### כללי קומיטים וענפים
- **Conventional Commits**: `feat|fix|docs|test|refactor|chore|perf`
- מומלץ ענפים בסגנון: `feat/...`, `fix/...`, `chore/...`
- קומיט עם HEREDOC (שומר על פורמט ברור):
  ```bash
  git commit -m "$(cat <<'EOF'
  docs: add GitHub-friendly contributing guide

  - Link to full docs site
  - Add PR checklist & CI expectations
  EOF
  )"
  ```

### צ'ק‑ליסט לפני פתיחת PR
- [ ] טסטים ירוקים מקומית, וב‑CI יופיעו סטטוסים:
  - "🔍 Code Quality & Security"
  - "🧪 Unit Tests (3.11)"
  - "🧪 Unit Tests (3.12)"
- [ ] הודעת קומיט בסגנון Conventional Commits
- [ ] בלי סודות/PII בקוד או בדיפים
- [ ] עדכון תיעוד רלוונטי (אם צריך)
- [ ] תיאור PR קצר וברור: What / Why / Tests / Rollback
- [ ] לצרף צילום/וידאו ל‑UI (אם רלוונטי)

ראו גם תבנית ה‑PR ב‑`/.github/pull_request_template.md`.

### הנחיות חשובות לטסטים/סקריפטים
- לעבוד רק על תיקיות זמניות (pytest: `tmp_path`) – אין כתיבה/מחיקה ב‑root.
- להימנע מ‑`rm -rf` גורף; להשתמש ב‑allowlist לתיקיית עבודה אחת בלבד.
- אין לשנות `cwd` סתם; אם חייבים – לשמור/לשחזר, ולהשתמש בנתיבים מוחלטים.

למידע מפורט, קראו את: [סגנון ומחיקות בטוחות בטסטים](https://amirbiron.github.io/CodeBot/testing.html).

### קישורים מהירים
- **מדריך תרומה מלא**: https://amirbiron.github.io/CodeBot/contributing.html
- **Quickstart לתרומה**: https://amirbiron.github.io/CodeBot/quickstart-contrib.html
- **מדריך כתיבת מסמכים**: https://amirbiron.github.io/CodeBot/doc-authoring.html
- **בדיקות (Testing)**: https://amirbiron.github.io/CodeBot/testing.html
- **CI/CD**: https://amirbiron.github.io/CodeBot/ci-cd.html
- **הנחיות AI/CodeBot**: https://amirbiron.github.io/CodeBot/ai-guidelines.html

---

### שאלות?
- פתחו Issue / Discussion, או צרו קשר לפי ה‑README. תודה שאתם תורמים! 💚
