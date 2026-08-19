#!/usr/bin/env bash
# פרסום AI-MAP.md אחרי שינוי תיעוד ב-main, דרך GitHub Contents API.
#
# למה API ולא git: פרסום דרך git דורש כתיבה ל-root של ה-checkout,
# commit, ואז דחיפה — ובכשל דחיפה גם rebase, ענף אוטומציה ו-PR. כל
# השרשרת הזו נשענה על PAT בעל admin:repo, שהיה נחשף לכל קוד שרץ בשלב.
# קריאת API אחת מחליפה את הכול: המפה נוצרת בתיקייה זמנית בלבד, אין
# כתיבה ב-root, אין git מאומת, ואין שום צורך ב-PAT — GITHUB_TOKEN
# עם contents:write מספיק. ה-sha של הקובץ הקיים משמש כנעילה
# אופטימית: שינוי מקביל מחזיר 409 והריצה נכשלת ברעש במקום לדרוס.
#
# קלט (env): GH_TOKEN, GITHUB_REPOSITORY
set -euo pipefail

WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT
MAP="${WORKDIR}/AI-MAP.md"

# המחולל רץ בלי הטוקן בסביבה, וכותב אך ורק לתיקייה הזמנית
env -u GH_TOKEN python3 scripts/generate_ai_map.py --out "${MAP}"

if diff -q AI-MAP.md "${MAP}" >/dev/null 2>&1; then
  echo "המפה עדכנית — אין מה לפרסם"
  exit 0
fi

# sha של הקובץ הקיים; ריק אם הקובץ עדיין לא קיים ב-main
sha="$(gh api "repos/${GITHUB_REPOSITORY}/contents/AI-MAP.md" --jq .sha 2>/dev/null || true)"

args=(
  -X PUT "repos/${GITHUB_REPOSITORY}/contents/AI-MAP.md"
  -f "message=docs: רענון אוטומטי של AI-MAP.md"
  -f "content=$(base64 -w0 "${MAP}")"
)
[ -n "${sha}" ] && args+=(-f "sha=${sha}")

if gh api "${args[@]}" --jq .commit.sha; then
  echo "המפה פורסמה ל-main"
  exit 0
fi

# כשל אמיתי: הגנת ענף שחוסמת גם את GITHUB_TOKEN, מרוץ (409), או תקלת
# API. לא בולעים — מפילים ברעש כדי שהמצב יגיע להתראה ולא יישאר שקט.
echo "::error::פרסום AI-MAP.md נכשל. אם main מוגן מפני דחיפות בוט, רעננו את המפה ידנית (python3 scripts/generate_ai_map.py --out AI-MAP.md) או התאימו את הגנת הענף. הריצה הבאה תנסה שוב."
exit 1
