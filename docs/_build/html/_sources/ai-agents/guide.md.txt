# 🤖 מדריך לסוכני AI

מטרה: לקצר זמן חיבור של סוכנים לפרויקט, לשמור על איכות ועמידה במדיניות.

---

## נקודת פתיחה מהירה
- קראו את הקובץ `.cursorrules` – הוא מגדיר כללי עבודה, פורמט תשובות וחוקי בטיחות.
- עברו על `docs/ai-guidelines.rst` ו-`docs/quickstart-ai.rst`.

---

## מבנה הפרויקט (בקצרה)
- Python services/bot/webapp – קוד עיקרי
- `docs/` – תיעוד Sphinx (MyST ל-Markdown)
- `tests/` – בדיקות יחידה
- `scripts/` – כלי תחזוקה (ראו להלן)

---

## הוספת פיצ'רים
- שמרו על Conventional Commits
- פתחו PR עם What / Why / Tests ורולבק ברור
- עדכנו דפי תיעוד רלוונטיים והקפידו על build נקי (ללא warnings)

תבנית קומיט קצרה (HEREDOC):

```bash
git commit -m "$(cat <<'EOF'
feat: add X with Y

- Explain why
- Link to docs/ and tests
EOF
)"
```

---

## סקריפטים חשובים
- `scripts/dev_seed.py` – זריעת נתונים לפיתוח
- `scripts/cleanup_repo_tags.py` – ניקוי תגיות ריפו

הריצו בסביבת dev בלבד, ללא sudo, ובנתיבי tmp לקלט/פלט.

---

## מפת דרכים
- עיינו ב-`FEATURE_SUGGESTIONS/IMPROVEMENT_SUGGESTIONS.md` לצירי שיפור הנדסיים.
- שקלו קישור מהדף הראשי של התיעוד אל דף זה כסעיף "Engineering Improvement Roadmap".

---

## GitHub Issues ו-ChatOps
- ניהול Issues וקישורם מתועד בעמודי ChatOps.
- לפעולות בזמן אמת בקשו להריץ פקודות בוט (למשל `/triage <request_id>`), והסתמכו על הפלט כמקור אמת.
