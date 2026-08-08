#!/usr/bin/env bash
#
# הוק SessionStart — מושך את "הוראות לסוכן" מ-CodeKeeper ומזריק אותן להקשר.
#
# למה סקריפט ולא הוק מסוג http?
# הוק http הוא קופסה סגורה: הוא מושך URL ומזריק את הגוף, ואין לו דרך להבחין
# בין 204 ("אין הוראות" — מצב תקין) לבין 401 ("הטוקן פג" — תקלה). שניהם יוצאים
# כשתיקה מוחלטת, וההוק נכשל לנצח בלי שאף אחד ידע. התיעוד ב-docs/mcp-server.rst
# מזהיר מפורשות מהמצב הזה. כאן אנחנו קוראים את קוד הסטטוס ומגיבים לפי המשמעות.
#
# כל מה שנכתב ל-stdout נכנס להקשר של המודל. לכן: בהצלחה מדפיסים את הפריימר
# בלבד, ובכשל שורת אבחון קצרה — לא stack trace ולא רעש.
#
# הסקריפט תמיד יוצא ב-0. כשל במשיכת הפריימר הוא לא סיבה להפיל פתיחת סשן.

set -uo pipefail
IFS=$'\n\t'

# מתנתקים משורש הריפו מיד. כל הנתיבים כאן מוחלטים ממילא, אבל הוק רץ אוטומטית
# בכל פתיחת סשן — ואם מישהו יוסיף בעתיד נתיב יחסי, הוא ייפול לתיקייה זמנית
# ולא לעץ המקור. הגנה מבנית, בהתאם לכלל "פקודות אוטומטיות רק בתיקיות tmp".
cd -- "${TMPDIR:-/tmp}" 2>/dev/null || true

# ברירת המחדל היא ה-MCP host. חשוב: האנדפוינט חי רק שם — הצבעה על הוובאפ
# מחזירה 404. ניתן לעקוף דרך CODEKEEPER_PRIMER_URL בהגדרות הסביבה.
PRIMER_URL="${CODEKEEPER_PRIMER_URL:-https://codekeeper-mcp.onrender.com/api/agent/primer}"

# תקרה נדיבה יותר מ-10 שניות: השירות רץ על Render ויכול להיות "ישן", וההתעוררות
# לבדה אוכלת כמה שניות. עדיין קצר מספיק כדי לא לעכב פתיחת סשן באופן מורגש.
REQUEST_TIMEOUT_SECONDS=20

# לוג אבחון. נועד לענות על שאלה אחת בלבד: האם ההוק בכלל רץ? בלעדיו, הוק שלא
# מורץ (למשל כי לא אושר) והוק שרץ ונכשל נראים זהים לחלוטין מבחוץ.
#
# הלוג יושב בתיקייה פרטית למשתמש ולא ב-/tmp המשותף. הסיבה: ‎>>‎ הולך אחרי
# symlink, ולכן נתיב צפוי ב-/tmp מאפשר למשתמש מקומי אחר להשתיל שם קישור
# ולגרום לנו לצרף שורות לקובץ שלו. XDG_STATE_HOME הוא המקום התקני לנתוני
# ריצה מתמשכים, והתיקייה נוצרת עם 0700.
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/codekeeper"
LOG_FILE="$LOG_DIR/primer-hook.log"

log_diagnostic() {
	# נכשל בשקט בכל שלב — לוג הוא נחמדות, לא תנאי להרצת ההוק.
	(
		umask 077
		mkdir -p -- "$LOG_DIR" 2>/dev/null || exit 0
		# חגורה נוספת מעבר לתיקייה הפרטית: אם משום מה יש שם symlink, לא כותבים.
		[[ -L "$LOG_FILE" ]] && exit 0
		printf '%s | %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >>"$LOG_FILE" 2>/dev/null
	) || true
}

log_diagnostic "hook invoked"

if ! command -v curl >/dev/null 2>&1; then
	echo "[CodeKeeper] curl לא מותקן בסביבה — לא ניתן למשוך את ההוראות לסוכן."
	log_diagnostic "curl missing"
	exit 0
fi

if [[ -z "${CODEKEEPER_PAT:-}" ]]; then
	echo "[CodeKeeper] משתנה הסביבה CODEKEEPER_PAT לא מוגדר — ההוראות לסוכן לא נטענו."
	log_diagnostic "CODEKEEPER_PAT missing"
	exit 0
fi

# קובץ זמני לגוף התשובה, כדי שקוד הסטטוס יגיע נקי דרך -w ולא יעורבב עם התוכן.
# mktemp יוצר קובץ חדש ובלעדי, והמחיקה ב-trap נוגעת רק בו.
body_file="$(mktemp "${TMPDIR:-/tmp}/codekeeper-primer.XXXXXX")" || {
	echo "[CodeKeeper] לא ניתן ליצור קובץ זמני — ההוראות לסוכן לא נטענו."
	log_diagnostic "mktemp failed"
	exit 0
}
trap 'rm -f -- "$body_file"' EXIT

# הטוקן מוזרק דרך הרחבת משתנה של bash. זו הסיבה השנייה למעבר מהוק http:
# שם ה-header נכתב כמחרוזת בקובץ JSON, ואם תחביר ההזרקה לא נתמך הוא נשלח
# מילולית ("Bearer $CODEKEEPER_PAT") ומקבל 401 — שתיקה נוספת שקשה לאבחן.
http_code="$(
	curl --silent --show-error \
		--max-time "$REQUEST_TIMEOUT_SECONDS" \
		--header "Authorization: Bearer ${CODEKEEPER_PAT}" \
		--header "Accept: text/plain" \
		--output "$body_file" \
		--write-out '%{http_code}' \
		"$PRIMER_URL" 2>/dev/null
)" || http_code="000"

log_diagnostic "http_code=${http_code}"

case "$http_code" in
200)
	# המקרה התקין. הגוף הוא ההוראות עצמן — מדפיסים אותו כפי שהוא, בלי מסגור
	# ובלי כותרת: הפריימר מנוסח כדי להיקרא ישירות על ידי המודל.
	cat -- "$body_file"
	;;
204)
	# אין הוראות. זה מצב תקין ומתועד, ולכן שותקים — הודעה כאן הייתה רעש בכל
	# פתיחת סשן של מי שלא מילא את השדה.
	log_diagnostic "204 - empty agent instructions"
	;;
401)
	echo "[CodeKeeper] הטוקן נדחה (401). ההוראות לסוכן לא נטענו — ייתכן שה-PAT פג או בוטל. אפשר להנפיק חדש דרך /connect_claude בבוט."
	;;
404)
	echo "[CodeKeeper] האנדפוינט לא נמצא (404) בכתובת ${PRIMER_URL} — סביר שה-URL מצביע על הוובאפ במקום על ה-MCP host. ההוראות לסוכן לא נטענו."
	;;
000)
	echo "[CodeKeeper] לא הצלחתי להגיע לשרת תוך ${REQUEST_TIMEOUT_SECONDS} שניות. ההוראות לסוכן לא נטענו."
	;;
*)
	echo "[CodeKeeper] השרת החזיר ${http_code}. ההוראות לסוכן לא נטענו."
	;;
esac

exit 0
