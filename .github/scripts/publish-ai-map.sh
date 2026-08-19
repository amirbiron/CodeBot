#!/usr/bin/env bash
# פרסום AI-MAP.md אחרי שינוי תיעוד ב-main. מחולץ מ-ai-map.yml כדי
# שמדיניות הדחיפה/fallback לא תהיה צמודה לשלב הקומיט, וכדי שכל הזרימה
# תרוץ תחת set -euo pipefail — כשל של כל פקודת פרסום מפיל את הריצה.
#
# גבולות אבטחה (הסיבה למבנה):
# - checkout רץ עם persist-credentials: false — אין טוקן ב-.git/config.
# - הדחיפות משתמשות ב-URL אינליין עם הטוקן; שום דבר לא נשמר בדיסק.
# - כל הרצה של המחולל מנוקה מ-GH_TOKEN עם env -u — קוד הריפו לעולם לא
#   רואה את הסוד, גם לא דרך הסביבה.
#
# קלט (env): GH_TOKEN, HAS_PAT ("true"/"false"), GITHUB_REPOSITORY
set -euo pipefail

AUTH_URL="https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
BRANCH="automation/ai-map-refresh"

regen() {
  # המחולל רץ בלי הסוד בסביבה — בכוונה, ראו כותרת הקובץ
  env -u GH_TOKEN python3 scripts/generate_ai_map.py --out AI-MAP.md
}

fail_without_pat() {
  # PR שנדחף/נוצר ב-GITHUB_TOKEN אינו מפעיל את בדיקות החובה. בלי PAT
  # הריצה חייבת להיכשל ברעש — PR תקוע בשקט הוא בדיוק מה שאסור.
  if [ "${HAS_PAT}" != "true" ]; then
    echo "::error::$1 (אין REPO_ADMIN_TOKEN). סגרו ופתחו מחדש את ה-PR להפעלת הבדיקות, או הגדירו את הסוד."
    exit 1
  fi
}

# git diff מפספס קובץ שאינו tracked עדיין; porcelain תופס את שניהם
if [ -z "$(git status --porcelain -- AI-MAP.md)" ]; then
  echo "המפה עדכנית — אין מה לקמט"
  exit 0
fi

git config user.name "github-actions"
git config user.email "actions@github.com"
git add AI-MAP.md
git commit -m "docs: רענון אוטומטי של AI-MAP.md"

# ניסיון ראשון: דחיפה ישירה (עובדת כשאין הגנת ענף חוסמת)
if git push "${AUTH_URL}" HEAD:main; then
  echo "נדחף ישירות ל-main"
  exit 0
fi

# non-fast-forward: תיעוד חדש נכנס בינתיים. אחרי ה-rebase המפה שנוצרה
# כבר מיושנת — מייצרים מחדש ומעדכנים את הקומיט, אחרת היינו דוחפים מפה
# ישנה על תיעוד חדש (והקומיט שלנו לא מפעיל ריצה נוספת, כי הוא נוגע רק
# ב-AI-MAP.md שאינו ב-paths).
if git pull --rebase "${AUTH_URL}" main; then
  regen
  git add AI-MAP.md
  git commit --amend --no-edit
  if git push "${AUTH_URL}" HEAD:main; then
    echo "נדחף אחרי rebase וייצור מחדש"
    exit 0
  fi
else
  # rebase כושל משאיר את עץ העבודה באמצע rebase וכל פקודה הבאה נכשלת
  # בשגיאה מבלבלת — מנקים לפני ה-fallback
  git rebase --abort || true
fi

# הגנת ענף דחתה את הדחיפה — נפילה מבוקרת לענף אוטומציה + PR. הענף נבנה
# מ-origin/main נקי והמפה מיוצרת בו מחדש: קומיט אחד בדיוק, בלי היסטוריה
# מקומית חלקית. הענף קבוע כדי שריצות חוזרות יעדכנו את אותו PR.
echo "דחיפה ישירה נדחתה — עובר לענף אוטומציה"
git fetch "${AUTH_URL}" main
git checkout -B "${BRANCH}" FETCH_HEAD
regen
if [ -z "$(git status --porcelain -- AI-MAP.md)" ]; then
  echo "אחרי הסנכרון המפה כבר עדכנית ב-main — אין צורך ב-PR"
  exit 0
fi
git add AI-MAP.md
git commit -m "docs: רענון אוטומטי של AI-MAP.md"
git push -f "${AUTH_URL}" "HEAD:refs/heads/${BRANCH}"

# gh pr list מחזיר רשימה ריקה כשאין PR ונכשל ברעש על שגיאת API/הרשאה —
# בניגוד ל-pr view, שבו כשל אמיתי נראה כמו "אין PR"
state=$(gh pr list --head "${BRANCH}" --base main --state open --json state --jq '.[0].state // "NONE"')
if [ "${state}" = "OPEN" ]; then
  echo "PR פתוח כבר קיים — הענף עודכן והוא התעדכן בו"
  fail_without_pat "ה-PR עודכן אבל בדיקות החובה לא ירוצו עליו"
  exit 0
fi
gh pr create \
  --title "docs: רענון אוטומטי של AI-MAP.md" \
  --body "$(printf 'רענון מפת התיעוד אחרי שינוי ב-docs/. נוצר אוטומטית על ידי ai-map.yml כי דחיפה ישירה ל-main נדחתה (הגנת ענף).\n\nאם בדיקות החובה לא הופעלו (PR שנוצר ב-GITHUB_TOKEN אינו מפעיל אותן) — סגרו ופתחו מחדש את ה-PR, או הגדירו את הסוד REPO_ADMIN_TOKEN כדי שזה יקרה אוטומטית.')" \
  --base main --head "${BRANCH}"
fail_without_pat "נוצר PR אבל בדיקות החובה לא ירוצו עליו"
