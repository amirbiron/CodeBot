#!/usr/bin/env bash
# codekeeper-primer v2
#
# הוק SessionStart — מושך את "הוראות לסוכן" מ-CodeKeeper ומזריק אותן להקשר.
#
# זה העותק הקנוני של ההוק, ופרויקט חדש מעתיק ממנו. ההסבר המלא — על מה הוא מנסה
# שוב, על מה לא, ומה שורת האזהרה אומרת — בסעיף "פריימר לסוכן" ב-docs/mcp-server.rst.
#
# למה סקריפט ולא הוק מסוג http?
# הוק http הוא קופסה סגורה: הוא מושך URL ומזריק את הגוף, ואין לו דרך להבחין
# בין 204 ("אין הוראות" — מצב תקין) לבין 401 ("הטוקן פג" — תקלה). שניהם יוצאים
# כשתיקה מוחלטת, וההוק נכשל לנצח בלי שאף אחד ידע. התיעוד ב-docs/mcp-server.rst
# מזהיר מפורשות מהמצב הזה. כאן אנחנו קוראים את קוד הסטטוס ומגיבים לפי המשמעות.
#
# כל מה שנכתב ל-stdout נכנס להקשר של המודל. לכן: בהצלחה מדפיסים את הפריימר
# בלבד, ובכשל שורת אבחון אחת — לא stack trace, לא רעש, ולא שורה לכל ניסיון.
# הניסיונות נרשמים ללוג הפרטי (log_diagnostic למטה), ולא ל-stdout.
#
# מתי ההוק רץ: SessionStart נורה לא רק בפתיחת סשן, אלא גם ב-resume, ב-clear,
# אחרי compact וב-fork — וההוק ב-.claude/settings.json מוגדר בלי matcher, כלומר
# רץ בכולם (code.claude.com/docs/en/hooks, הסעיף SessionStart, נקרא ב-2026-09-30).
# לכן ה-retry שלמטה יכול לרוץ גם באמצע סשן, אחרי compact שנפל בחלון של דיפלוי.
# ההערה הזו כאן ולא ליד ההוק, כי settings.json הוא JSON, ואין בו הערות.
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
PRIMER_URL="${CODEKEEPER_PRIMER_URL:-https://codekeepermcp.onrender.com/api/agent/primer}"

# ── זמנים ────────────────────────────────────────────────────────────────────
#
# למה retry: לשירות ה-MCP מחובר דיסק, ולכן דיפלוי שלו אינו בלי השבתה — יש חלון
# של עד כדקה שבו Render מחזיר 502. סשן שנפתח בחלון הזה היה מתחיל בלי הוראות.
# מנסים שוב רק על מה שדיפלוי או רשת רגעית מייצרים: is_transient_http_code
# ו-is_transient_curl_exit למטה. כל השאר מקבל שורת אבחון מיד.
#
# מרווח קבוע בין ניסיונות, בלי backoff: החלון הוא כדקה, ואין מה למתוח.
RETRY_INTERVAL_SECONDS=15
# כמה זמן בסך הכול מוכנים לנסות. ניסיון שהיה מתחיל אחרי שהתקציב נגמר לא מתחיל,
# ולכן המקרה הגרוע הוא התקציב ועוד ניסיון אחד (REQUEST_TIMEOUT_SECONDS).
RETRY_BUDGET_SECONDS=90
# לכל ניסיון: שלב החיבור (DNS, TCP ו-TLS) עד CONNECT_TIMEOUT_SECONDS, והבקשה
# כולה עד REQUEST_TIMEOUT_SECONDS. ב-v1 זה היה ניסיון יחיד של 20 שניות, שנועד
# לשירות "ישן" שמתעורר. עם retry אין בזה צורך: הפריימר קליל, בדיפלוי Render עונה
# 502 מיד, ושירות שמתעורר לאט מקבל ניסיון נוסף במקום המתנה ארוכה אחת.
CONNECT_TIMEOUT_SECONDS=5
REQUEST_TIMEOUT_SECONDS=10
#
# ⚠️ החשבון שחייב להחזיק: RETRY_BUDGET_SECONDS ועוד REQUEST_TIMEOUT_SECONDS קטנים,
# עם מרווח, מה-"timeout" של ההוק ב-.claude/settings.json. הוק שמגיע ל-timeout
# שלו נחתך, והפלט שלו נזרק (code.claude.com/docs/en/hooks, הסעיף Timeouts) —
# כלומר בדיוק הכשל השקט שה-retry בא לתקן, רק דרך התיקון עצמו. החשבון נבדק מול
# settings.json ב-tests/test_codekeeper_primer_hook.py.
#
# והמחיר, במפורש: כשהשרת באמת למטה, כל פתיחת סשן — וגם כל compact — מחכה עד
# התקציב לפני שורת האזהרה. אם זה יקר מדי, מקצרים את התקציב, לא את המרווח.

# לוג אבחון. נועד לענות על שאלה אחת בלבד: האם ההוק בכלל רץ? בלעדיו, הוק שלא
# מורץ (למשל כי לא אושר) והוק שרץ ונכשל נראים זהים לחלוטין מבחוץ. מאז v2 הוא
# גם המקום של הניסיונות: שורה לכל ניסיון, עם קוד הסטטוס וקוד היציאה של curl.
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

# דריסה של המרווח ושל התקציב — לטסטים בלבד, כדי שטסט "כשל מתמשך" לא ימתין את
# התקציב המלא בכל ריצת CI. בלי המשתנים (CODEKEEPER_PRIMER_RETRY_INTERVAL_SECONDS,
# CODEKEEPER_PRIMER_RETRY_BUDGET_SECONDS) — הקבועים שלמעלה.
#
# דריסה יכולה רק לקצר: ערך גדול מהקבוע נדחה, ולכן החשבון מול ה-timeout של ההוק,
# שנבדק על הקבועים, מחזיק גם תחת כל דריסה. וערך שאינו מספר שלם נדחה לפני שהוא
# נוגע בחשבון: חשבון של bash על מחרוזת מהסביבה מריץ פקודות שמוטמעות בה
# (a[$(...)]), ו-08 נקרא כבסיס 8 ונופל. ערך שנדחה נרשם ללוג — בלי הערך עצמו,
# שהגיע מבחוץ — והקבוע נשאר.
#
# $1 שם המשתנה (ללוג), $2 הערך שלו, $3 הקבוע, $4 המינימום.
seconds_override() {
	local name="$1" raw="$2" default="$3" min="$4"
	if [[ -z "$raw" ]]; then
		printf '%s' "$default"
		return
	fi
	# עד שש ספרות לפני החשבון, כדי שמספר ענק לא יגלוש ב-64 ביט. הגבול האמיתי
	# הוא הקבוע, בתנאי שאחריו.
	if [[ "$raw" =~ ^[0-9]{1,6}$ ]] && ((10#$raw >= min && 10#$raw <= default)); then
		printf '%s' "$((10#$raw))"
		return
	fi
	log_diagnostic "ignored ${name}: not an integer between ${min} and ${default}"
	printf '%s' "$default"
}

# קודי יציאה של curl שמשמעותם "לא הגענו לשרת עכשיו, ובעוד רגע אולי כן" — לפי
# הפרק EXIT CODES ב-curl --manual (curl 8.5.0): 6 השם לא נפתר, 7 החיבור נכשל,
# 28 timeout, 35 לחיצת היד של TLS נכשלה, 52 השרת לא ענה כלום, 56 כשל בקבלת
# נתונים. כל קוד אחר לא ישתנה בעוד רגע — 1 פרוטוקול לא נתמך, 3 כתובת פגומה,
# 60 תעודה שלא אומתה — ומקבל שורת אבחון מיד, עם הקוד.
is_transient_curl_exit() {
	case "$1" in
	6 | 7 | 28 | 35 | 52 | 56) return 0 ;;
	*) return 1 ;;
	esac
}

# שם קצר לקוד היציאה, לשורת האבחון (מאותו פרק).
curl_exit_name() {
	case "$1" in
	1) printf 'unsupported protocol' ;;
	3) printf 'malformed URL' ;;
	6) printf 'DNS' ;;
	7) printf 'connection failed' ;;
	28) printf 'timeout' ;;
	35) printf 'TLS handshake' ;;
	52) printf 'empty reply' ;;
	56) printf 'receive failed' ;;
	60) printf 'certificate' ;;
	*) printf 'see EXIT CODES in curl --manual' ;;
	esac
}

# קודי השער שדיפלוי מייצר. 500 לא כאן, בכוונה: הוא באג בשרת ולא דיפלוי, ו-retry
# היה מסתיר אותו מאחורי המתנה של התקציב כולו.
is_transient_http_code() {
	case "$1" in
	502 | 503 | 504) return 0 ;;
	*) return 1 ;;
	esac
}

# סוג המדיה מתוך ערך Content-Type: מה שלפני ה-";", בלי רווחים בקצוות, באותיות
# קטנות — שם הסוג ושם תת-הסוג אינם תלויי רישיות (RFC 6838, סעיף 4.2). נמדד:
# curl מחזיר ב-%{content_type} את הכותרת כפי שנשלחה, למשל "Text/Plain ; charset=utf-8".
media_type_of() {
	local value="${1%%;*}"
	value="${value#"${value%%[![:space:]]*}"}"
	value="${value%"${value##*[![:space:]]}"}"
	printf '%s' "$value" | LC_ALL=C tr '[:upper:]' '[:lower:]'
}

# סוג המדיה כפי שמותר להציג אותו בשורת האבחון. השורה נכנסת להקשר של המודל
# והערך מגיע מהשרת, ולכן מוצג כמו שהוא רק שם שעומד בדקדוק של RFC 6838 סעיף 4.2:
# אות או ספרה, ואחריה עד 126 תווים מתוך אותיות, ספרות ו-!#$&-^_.+ — בכל צד של
# ה-"/". כל ערך אחר מוצג כתיאור, ולא כטקסט של השרת.
displayable_media_type() {
	local re='^[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$'
	if [[ -z "$1" ]]; then
		printf 'חסר'
	elif [[ "$1" =~ $re ]]; then
		printf '%s' "$1"
	else
		printf 'לא תקני'
	fi
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

retry_interval_seconds="$(seconds_override CODEKEEPER_PRIMER_RETRY_INTERVAL_SECONDS \
	"${CODEKEEPER_PRIMER_RETRY_INTERVAL_SECONDS:-}" "$RETRY_INTERVAL_SECONDS" 1)"
retry_budget_seconds="$(seconds_override CODEKEEPER_PRIMER_RETRY_BUDGET_SECONDS \
	"${CODEKEEPER_PRIMER_RETRY_BUDGET_SECONDS:-}" "$RETRY_BUDGET_SECONDS" 0)"

# תקרה על מספר הניסיונות, שנגזרת מאותם שני מספרים: כמה ניסיונות נכנסים בתקציב
# כשכל תשובה מגיעה מיד. כשהשעון תקין היא לא משנה דבר. היא כאן כי $SECONDS נקרא
# משעון המערכת (man bash, SECONDS), ושעון שקופץ אחורה היה מאריך את הלולאה —
# והתקרה מבטיחה שהיא נגמרת בכל מקרה. תמיד יש לפחות ניסיון אחד.
max_attempts=$(((retry_budget_seconds + retry_interval_seconds - 1) / retry_interval_seconds))
if ((max_attempts < 1)); then
	max_attempts=1
fi
log_diagnostic "retry: interval=${retry_interval_seconds}s budget=${retry_budget_seconds}s max_attempts=${max_attempts}"

# קובץ זמני לגוף התשובה, כדי שקוד הסטטוס יגיע נקי דרך -w ולא יעורבב עם התוכן.
# mktemp יוצר קובץ חדש ובלעדי, והמחיקה ב-trap נוגעת רק בו.
body_file="$(mktemp "${TMPDIR:-/tmp}/codekeeper-primer.XXXXXX")" || {
	echo "[CodeKeeper] לא ניתן ליצור קובץ זמני — ההוראות לסוכן לא נטענו."
	log_diagnostic "mktemp failed"
	exit 0
}
trap 'rm -f -- "$body_file"' EXIT

# ── הניסיונות ────────────────────────────────────────────────────────────────
#
# stdout נשאר ריק עד שיש הכרעה: כל ניסיון נרשם ללוג בלבד, ורק אחרי הלולאה מודפס
# דבר אחד — הפריימר, או שורת אבחון אחת.
#
# $SECONDS מאופס כאן, ולא נסמכים על הערך שלו בתחילת הריצה: bash מייבא אותו
# מהסביבה כשהוא מוגדר שם (נמדד: SECONDS=-500 בסביבה, ו-$SECONDS מתחיל ב-500-),
# וערך כזה היה מותח את התקציב מעבר ל-timeout של ההוק.
attempt=0
outcome=""
http_code="000"
content_type=""
curl_exit=0
SECONDS=0
while :; do
	attempt=$((attempt + 1))

	# איפוס הגוף לפני כל ניסיון. curl לא נוגע בקובץ כשהוא נכשל לפני שהגוף הגיע
	# (נמדד: בקוד 7 ובקוד 52 הקובץ נשאר כמו שהיה), ובלי האיפוס גוף של ניסיון
	# קודם — HTML של 502 — היה נשאר בו. היום הגוף נקרא רק אחרי 200 בהעברה
	# שהצליחה, וב-curl 8.5.0 העברה כזו כותבת את הקובץ מחדש גם כשהגוף ריק
	# (src/tool_operate.c: "force creation of an empty output file"). האיפוס
	# מבטיח את זה בלי להישען על גרסה של curl.
	if ! { : >"$body_file"; } 2>/dev/null; then
		echo "[CodeKeeper] לא ניתן לאפס את הקובץ הזמני — ההוראות לסוכן לא נטענו."
		log_diagnostic "body reset failed"
		exit 0
	fi

	# הטוקן מוזרק דרך הרחבת משתנה של bash. זו הסיבה השנייה למעבר מהוק http:
	# שם ה-header נכתב כמחרוזת בקובץ JSON, ואם תחביר ההזרקה לא נתמך הוא נשלח
	# מילולית ("Bearer $CODEKEEPER_PAT") ומקבל 401 — שתיקה נוספת שקשה לאבחן.
	#
	# ההסתעפות היא לפי %{http_code} ולא לפי --fail, שמסתיר את הקוד.
	write_out="$(
		curl --silent --show-error \
			--connect-timeout "$CONNECT_TIMEOUT_SECONDS" \
			--max-time "$REQUEST_TIMEOUT_SECONDS" \
			--header "Authorization: Bearer ${CODEKEEPER_PAT}" \
			--header "Accept: text/plain" \
			--output "$body_file" \
			--write-out '%{http_code} %{content_type}' \
			"$PRIMER_URL" 2>/dev/null
	)"
	# קוד היציאה נשמר מיד: הוא מה שמבדיל כשל רשת זמני (7, 28) מכתובת פגומה (3),
	# ששניהם מגיעים עם http_code של 000.
	curl_exit=$?

	# הפלט של --write-out: קוד הסטטוס, רווח, וה-Content-Type (ריק כשאין). נמדד:
	# curl מדפיס "000 " גם כשהחיבור נכשל. פלט אחר מכל סיבה נקרא כ-000.
	http_code="${write_out%% *}"
	content_type=""
	if [[ "$write_out" == *" "* ]]; then
		content_type="${write_out#* }"
	fi
	if ! [[ "$http_code" =~ ^[0-9][0-9][0-9]$ ]]; then
		http_code="000"
	fi
	log_diagnostic "attempt ${attempt}/${max_attempts} http_code=${http_code} rc=${curl_exit} elapsed=${SECONDS}s"

	if ((curl_exit != 0)); then
		# העברה שנכשלה אינה תשובה, גם אם כבר הגיע קוד סטטוס: הגוף חלקי או חסר.
		if ! is_transient_curl_exit "$curl_exit"; then
			outcome="curl_failed"
			break
		fi
		outcome="network"
	elif is_transient_http_code "$http_code"; then
		outcome="gateway"
	else
		outcome="answered"
		break
	fi

	# ניסיון נוסף רק אם הוא יתחיל לפני שהתקציב נגמר. בודקים לפני ההמתנה, ולא
	# אחריה, כדי לא לחכות מרווח שלם שאין אחריו ניסיון.
	if ((attempt >= max_attempts || SECONDS + retry_interval_seconds >= retry_budget_seconds)); then
		break
	fi
	# sleep שנכשל רק מקדים את הניסיון הבא; תקרת הניסיונות עדיין חוסמת את הלולאה.
	sleep "$retry_interval_seconds" || log_diagnostic "sleep failed"
done
elapsed_seconds=$SECONDS

if ((attempt == 1)); then
	attempts_text="בניסיון אחד"
else
	attempts_text="ב-${attempt} ניסיונות לאורך ${elapsed_seconds} שניות"
fi

case "$outcome" in
gateway)
	log_diagnostic "giving up: http_code=${http_code} after ${attempt} attempts in ${elapsed_seconds}s"
	echo "[CodeKeeper] ההוראות לסוכן לא נטענו — השרת החזיר ${http_code} ${attempts_text} (כנראה דיפלוי). פתחו סשן מחדש בעוד דקה."
	;;
network)
	log_diagnostic "giving up: curl rc=${curl_exit} after ${attempt} attempts in ${elapsed_seconds}s"
	echo "[CodeKeeper] ההוראות לסוכן לא נטענו — לא הצלחתי להגיע לשרת (curl ${curl_exit}, $(curl_exit_name "$curl_exit")) ${attempts_text}. זה כשל ברשת ולא תשובה של השרת — כנראה בעיה בסביבה, לא דיפלוי."
	;;
curl_failed)
	log_diagnostic "curl failed: rc=${curl_exit}, not retried"
	echo "[CodeKeeper] ההוראות לסוכן לא נטענו — curl נכשל בקוד ${curl_exit} ($(curl_exit_name "$curl_exit")). זה לא כשל רשת שעובר מעצמו, ולכן לא ניסיתי שוב — בדקו את CODEKEEPER_PRIMER_URL."
	;;
answered)
	case "$http_code" in
	200)
		# 200 שאינו טקסט פשוט אינו הפריימר: HTML של עמוד שגיאה, של host שגוי או
		# של שירות מושהה היה נכנס להקשר כ"הוראות". השרת מחזיר text/plain.
		media_type="$(media_type_of "$content_type")"
		if [[ "$media_type" != "text/plain" ]]; then
			shown_media_type="$(displayable_media_type "$media_type")"
			log_diagnostic "200 but Content-Type is ${shown_media_type}, not text/plain"
			echo "[CodeKeeper] ההוראות לסוכן לא נטענו — השרת החזיר 200, אבל לא טקסט פשוט (Content-Type: ${shown_media_type}). כנראה עמוד שגיאה או שירות אחר בכתובת הזו — בדקו את CODEKEEPER_PRIMER_URL."
		else
			# גוף שכולו רווחים וירידות שורה הוא גוף ריק. grep מחזיר 0 כשיש תו
			# שאינו רווח, 1 כשאין, ו-2 כשלא הצליח לקרוא — ושלושתם מטופלים.
			# LC_ALL=C: כל בית נבדק כבית, בלי תלות ב-locale של הסביבה.
			LC_ALL=C grep -q -e '[^[:space:]]' -- "$body_file"
			grep_exit=$?
			case "$grep_exit" in
			0)
				# המקרה התקין. הגוף הוא ההוראות עצמן — מדפיסים אותו כפי שהוא, בלי
				# מסגור ובלי כותרת: הפריימר מנוסח כדי להיקרא ישירות על ידי המודל.
				#
				# הגוף נקרא כולו לזיכרון, ורק אז מודפס: cat ישר ל-stdout שנכשל באמצע
				# היה משאיר בהקשר חצי פריימר, בלי שורת אבחון. ה-x בסוף שומר על ירידות
				# השורה שבסוף הגוף, שהחלפת פקודה מורידה. והחלפת פקודה גם משמיטה תווי
				# NUL (נמדד: "a\0b" נהיה "ab") — ולכן גוף שיש בו NUL, שאינו טקסט ממילא,
				# נדחה במפורש לפני הקריאה, ולא נחתך בשקט.
				if ! nul_bytes="$(LC_ALL=C tr -dc '\000' <"$body_file" | wc -c)"; then
					log_diagnostic "reading the body failed: tr"
					echo "[CodeKeeper] ההוראות לסוכן לא נטענו — לא הצלחתי לקרוא את התשובה מהקובץ הזמני."
				elif ((nul_bytes > 0)); then
					log_diagnostic "200 but the body has NUL bytes"
					echo "[CodeKeeper] ההוראות לסוכן לא נטענו — השרת החזיר 200, אבל הגוף אינו טקסט (יש בו תו NUL)."
				elif ! primer_text="$(cat -- "$body_file" && printf x)"; then
					log_diagnostic "reading the body failed: cat"
					echo "[CodeKeeper] ההוראות לסוכן לא נטענו — לא הצלחתי לקרוא את התשובה מהקובץ הזמני."
				else
					printf '%s' "${primer_text%x}"
				fi
				;;
			1)
				log_diagnostic "200 with a blank body"
				echo "[CodeKeeper] ההוראות לסוכן לא נטענו — השרת החזיר 200 עם גוף ריק (כשאין הוראות הוא מחזיר 204, לא 200)."
				;;
			*)
				log_diagnostic "reading the body failed: grep rc=${grep_exit}"
				echo "[CodeKeeper] ההוראות לסוכן לא נטענו — לא הצלחתי לקרוא את התשובה מהקובץ הזמני."
				;;
			esac
		fi
		;;
	204)
		# אין הוראות. זה מצב תקין ומתועד, ולכן שותקים — הודעה כאן הייתה רעש בכל
		# פתיחת סשן של מי שלא מילא את השדה.
		log_diagnostic "204 - empty agent instructions"
		;;
	401 | 403)
		echo "[CodeKeeper] הטוקן נדחה (${http_code}). ההוראות לסוכן לא נטענו — ייתכן שה-PAT פג או בוטל. אפשר להנפיק חדש דרך /connect_claude בבוט."
		;;
	404)
		# בלי הכתובת עצמה: היא מגיעה מהסביבה, ושורת האבחון נכנסת להקשר של המודל —
		# סוד בשורת השאילתה או ב-userinfo היה נכנס איתה (נמדד). שם המשתנה מספיק.
		echo "[CodeKeeper] ההוראות לסוכן לא נטענו — האנדפוינט לא נמצא (404), כנראה כי הכתובת מצביעה על הוובאפ במקום על ה-MCP host. בדקו את CODEKEEPER_PRIMER_URL."
		;;
	*)
		echo "[CodeKeeper] השרת החזיר ${http_code}. ההוראות לסוכן לא נטענו."
		;;
	esac
	;;
esac

exit 0
