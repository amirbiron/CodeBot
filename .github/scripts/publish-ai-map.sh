#!/usr/bin/env bash
# פרסום AI-MAP.md אחרי שינוי תיעוד ב-main, דרך GitHub Contents API.
#
# עקרונות הזרימה, כל אחד תולדה של באג אמיתי:
#
# 1. המפה הטרייה נוצרת בתיקייה זמנית בלבד ומושווית מול AI-MAP.md
#    המקומט שב-checkout. אסור לאף שלב לכתוב את המפה ל-workspace לפני
#    ההשוואה — זה רומס את הבסיס וההשוואה יוצאת תמיד "עדכני" (ה-no-op
#    הירוק שסבב הריוויו התשיעי פספס ובדיקת הקבלה תופסת).
# 2. אין שום GET ל-API. הנעילה האופטימית היא ה-blob של הקובץ בקומיט
#    שעליו רץ ה-checkout, מ-git המקומי: git rev-parse הוא דטרמיניסטי —
#    כישלון שלו פירושו "הקובץ לא קיים ב-HEAD" (יצירה ראשונה), בניגוד
#    ל-GET שכשל רשת/הרשאה שלו התחזה ל"קובץ לא קיים".
# 3. מקור (docs.github.com/en/rest/repos/contents, Create or update
#    file contents): "sha — Required if you are updating a file. The
#    blob SHA of the file being replaced." קודי הכשל המתועדים: 404,
#    409, 422. עדכון מקביל ב-main אחרי הקומיט שלנו ← ה-sha כבר לא
#    תואם ← ה-API מחזיר כשל, הריצה אדומה, והריצה הבאה (שתרוץ על
#    הקומיט החדש) תיישר. שום דריסה שקטה.
# 4. המחולל רץ בלי GH_TOKEN בסביבה (env -u) — קוד הריפו לא רואה את
#    הסוד בשום ערוץ.
#
# קלט (env): GH_TOKEN, GITHUB_REPOSITORY
set -euo pipefail

WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT
MAP="${WORKDIR}/AI-MAP.md"

env -u GH_TOKEN python3 scripts/generate_ai_map.py --out "${MAP}"

if [ -f AI-MAP.md ] && diff -q AI-MAP.md "${MAP}" >/dev/null; then
  echo "המפה עדכנית — אין מה לפרסם"
  exit 0
fi

if sha="$(git rev-parse --verify -q "HEAD:AI-MAP.md")"; then
  :
else
  sha=""  # הקובץ אינו ב-HEAD — יצירה ראשונה, PUT בלי sha
fi

args=(
  -X PUT "repos/${GITHUB_REPOSITORY}/contents/AI-MAP.md"
  -f "message=docs: רענון אוטומטי של AI-MAP.md"
  -f "content=$(base64 -w0 "${MAP}")"
)
if [ -n "${sha}" ]; then
  args+=(-f "sha=${sha}")
fi

if gh api "${args[@]}" --jq .commit.sha; then
  echo "המפה פורסמה ל-main"
  exit 0
fi

echo "::error::פרסום AI-MAP.md נכשל (קונפליקט מול עדכון מקביל, הגנת ענף, או תקלת API). הריצה הבאה על main תנסה שוב; לרענון ידני: python3 scripts/generate_ai_map.py --out AI-MAP.md"
exit 1
