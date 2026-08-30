# CodeKeeper MCP Server

שרת [MCP](https://modelcontextprotocol.io) שחושף את **הקבצים והאוספים** השמורים של
המשתמש ל‑Claude — גם **Claude.ai** (Custom Connector דרך OAuth) וגם **Claude Code /
Claude Desktop** (טוקן אישי). קריאה זמינה תמיד; **כתיבה** (יצירה/עדכון קובץ) מאחורי
הרשאת `write` מפורשת. אין מחיקה.

> תכנון מלא: `FEATURE_SUGGESTIONS/FEATURE_MCP_CLAUDE_INTEGRATION.md`

---

## מה זה עושה

ניגש ישירות לשכבת ה‑DB הקיימת (`database.db` + `CollectionsManager`), מסונן תמיד לפי
ה‑`user_id` שנגזר מהטוקן. מכבד את חוק ה‑Smart Projection: רשימות/חיפוש לא מחזירים את
שדה ה‑`code` הכבד — תוכן מלא רק ב‑`get_file`.

### הכלים (Tools)

כל הכלים מקודמים ב‑`codekeeper_` (מונע התנגשות עם connectors אחרים). כולם read-only
פרט לכלי הכתיבה `codekeeper_save_file`/`codekeeper_edit_file`/`codekeeper_append_file`/
`codekeeper_add_to_collection` וכלי הפתקים `codekeeper_create_note`/
`codekeeper_update_note`/`codekeeper_note_str_replace` (דורשים הרשאת `write`).

| כלי | תיאור |
|-----|-------|
| `codekeeper_list_files` | רשימת קבצים (מטא‑דאטה בלבד), עם עימוד |
| `codekeeper_search_code` | חיפוש טקסט בקוד → מטא‑דאטה של קבצים תואמים |
| `codekeeper_get_file` | תוכן מלא של קובץ לפי `file_name` או `file_id` (אופציונלי: גרסה) |
| `codekeeper_save_file` | **כתיבה:** יצירה/עדכון קובץ לפי `file_name` (גרסה חדשה, לא דורס; בכפוף ל‑`MAX_CODE_SIZE`, ברירת מחדל 100K תווים וניתן להגדלה). דורש `write` |
| `codekeeper_edit_file` | **כתיבה:** מצא‑והחלף מדויק (`old_string`→`new_string`, אופציונלית `replace_all`) בלי לשלוח את כל הקובץ; גרסה חדשה, משמר שפה/תיאור/תגיות. דורש `write` |
| `codekeeper_append_file` | **כתיבה:** הוספת טקסט לסוף קובץ קיים (מוסיף שורת‑הפרדה אם צריך); גרסה חדשה. דורש `write` |
| `codekeeper_list_versions` | היסטוריית גרסאות של קובץ (מטא‑דאטה) |
| `codekeeper_list_notes` | פתקים דביקים של קובץ (לפי `file_name`) — אותם פתקים שמוצגים ב‑UI של הוובאפ |
| `codekeeper_create_note` | **כתיבה:** יצירת פתק דביק על קובץ קיים; `line` אופציונלי מעגן לשורת מקור (בלעדיו הפתק צף). דורש `write` |
| `codekeeper_update_note` | **כתיבה:** עדכון חלקי של פתק לפי `note_id` (תוכן/שורה/צבע/מוזער) — דורס במקום, אבל התוכן הקודם נשמר כגרסה. דורש `write` |
| `codekeeper_note_str_replace` | **כתיבה:** מצא‑והחלף מדויק **בתוך פתק** (`old_string`→`new_string`, אופציונלית `replace_all`) בלי לשלוח את כל הגוף. אותה סמנטיקה ואותם נוסחי שגיאה כמו `edit_file`. דורש `write` |
| `codekeeper_list_note_versions` | הגרסאות הקודמות של פתק (מטא‑דאטה בלבד), החדשה תחילה |
| `codekeeper_get_note_version` | תוכן של גרסה קודמת אחת; השחזור הוא `update_note` עם התוכן שנקרא |
| `codekeeper_list_collections` | האוספים של המשתמש |
| `codekeeper_get_collection` | אוסף בודד לפי id |
| `codekeeper_get_collection_items` | הקבצים בתוך אוסף (עם עימוד/סינון תיקייה) |
| `codekeeper_add_to_collection` | **כתיבה:** שיוך קובץ שמור קיים לאוסף קיים. `save_file` **אינו** משייך — זו הקריאה השנייה שמשלימה אותו. נכשל במפורש כשהאוסף או הקובץ אינם קיימים. דורש `write` |
| `codekeeper_docs_get_section` | סקשן בודד מקובץ RST של התיעוד (במקום קובץ שלם); בלי `section` מחזיר עץ כותרות. כולל breadcrumb/תת‑סקשנים/שכנים לניווט. עדיף על `codekeeper_get_repo_file` ל‑`docs/*.rst` |

> **היסטוריית פתקים.** כל עדכון **שמשנה** את ה‑`content` שומר את הגוף הקודם באוסף
> `sticky_note_versions` **לפני** הדריסה — עד 20 גרסאות לפתק (עדכון עם תוכן זהה אינו
> מייצר גרסה, כדי שכפילות לא תדחוף החוצה גרסה שעוד אפשר לשחזר). כשל צילום **עוצר**
> את העדכון (`snapshot_failed`): דריסה אחרי צילום שנכשל היא בדיוק אובדן הנתונים
> שהמנגנון בא למנוע; דריסה שלא קרתה אחרי צילום שהצליח מוחקת את הצילום בחזרה.
> `destructiveHint` נשאר `True` כי אחרי 20 עריכות המקור נדחף החוצה. אוסף נפרד ולא
> מערך מוטבע — שלוש פונקציות הרשימה קוראות בלי פרויקציה.

### כלי אדמין — דפדפן הריפו (פאזה ד', קריאה בלבד)

חמישה כלים **לאדמין בלבד** (`ADMIN_USER_IDS`): ארבעה מעל ה‑Repo Sync Engine (bare
mirrors), ומפת פתקי הריפו שקוראת מ‑`sticky_notes` בלבד. למשתמש שאינו אדמין כולם גם
מוסתרים מ‑`tools/list` וגם חסומים בגוף הכלי (fail‑closed).

| כלי | תיאור |
|-----|-------|
| `codekeeper_list_repos` | רשימת הריפואים המשוקפים (מטא‑דאטה) |
| `codekeeper_list_repo_tree` | נתיבי קבצים בריפו (עימוד, סינון תיקייה/ref; בלי תוכן) |
| `codekeeper_get_repo_file` | תוכן קובץ בודד (עד 500KB; בינארי ⇒ מטא‑דאטה בלבד) |
| `codekeeper_search_repo` | חיפוש טקסט בריפו (snippet קצר, עם תקרות) |
| `codekeeper_list_repo_note_paths` | **מפת גילוי:** אילו קבצים בריפו נושאים פתקים, וכמה על כל אחד. בלעדיה `list_repo_notes` דורש לדעת את הנתיב מראש |

- **מדיניות סודות (חובה):** נתיבים כמו `.env*`, `*.pem`, `id_rsa*` נחסמים/מושמטים בכל
  הכלים; הרחבה דרך `MCP_REPO_DENYLIST_EXTRA` (CSV globs).
- **sync רץ ברקע?** כלי שנכשל בזמן sync מחזיר `sync_in_progress` + `retry_after` —
  סימן לנסות שוב, לא להסיק שהקובץ לא קיים.

#### רענון אוטומטי (autosync) — בלי cron ובלי שירות נוסף

שירות ה‑MCP מריץ **thread רקע** (אותו דפוס כמו ה‑worker בוובאפ) שמחזיק את ה‑mirrors
המקומיים שלו טריים לבד:

```text
merge ל-main → GitHub webhook → הוובאפ מסנכרן את הדיסק שלו וכותב last_synced_sha ל-Mongo
            → ה-autosync ב-MCP מזהה שה-SHA המקומי שונה → git fetch לדיסק של ה-MCP
```

- ריפו שקיים ב‑`repo_metadata` אך חסר בדיסק המקומי — **משוכפל אוטומטית** מ‑`repo_url`
  (אין צורך ב‑`initial_import` ידני בצד ה‑MCP).
- שליטה: `MCP_REPO_AUTOSYNC` (ברירת מחדל פעיל; `0` מכבה), `MCP_REPO_AUTOSYNC_INTERVAL`
  (ברירת מחדל 300ש'). בזמן clone/fetch מקומי הכלים מחזירים `sync_in_progress`.
- **ENV נדרשים בשירות ה‑MCP:** `REPO_MIRROR_PATH` (+דיסק מצורף — ב‑Render דיסק הוא
  פר‑שירות; בלי דיסק זה עובד אבל משוכפל מחדש אחרי כל deploy), ו‑`GITHUB_TOKENS`/
  `GITHUB_TOKEN` לריפואים פרטיים. **אין צורך** ב‑`GITHUB_WEBHOOK_SECRET` כאן —
  ה‑webhook ממשיך להגיע לוובאפ בלבד.

---

## אימות — שני מסלולים (מאוחדים תחת `load_access_token`)

1. **OAuth 2.1** — עבור **Claude.ai** (Custom Connector). זרימה מלאה: DCR + PKCE +
   authorize + consent + token. הזהות נקבעת דרך **התחברות טלגרם בוובאפ**.
2. **Personal Access Token (PAT)** — עבור **Claude Code / Desktop**. `Authorization:
   Bearer ckmcp_…`, נשמר כ‑hash בקולקשן `mcp_tokens`, ניתן לביטול.

ה‑`user_id` נגזר **תמיד** מהטוקן — לעולם לא מקלט הלקוח.

**הרשאות (scopes):** `read` (ברירת מחדל) ו‑`write`. כלי הכתיבה בודק `write` בזמן ריצה;
טוקן קריאה בלבד יקבל שגיאת `insufficient_scope` (ולא ייכתב דבר). איך משיגים כתיבה — ראו למטה.

> ⚠️ **ראוט שאינו `/mcp` אינו מוגן אוטומטית.** במצב OAuth ה‑`PATAuthMiddleware` לא
> מותקן כלל, וה‑SDK עוטף רק את ה‑mount של `/mcp` — ולכן ראוט שנרשם ידנית
> ל‑`app.router.routes` (כמו `/healthz`) מוגש **בלי אימות**. כל ראוט חדש שאסור שיהיה
> ציבורי חייב לקרוא ל‑`authenticate_bearer` בגוף שלו. ראו `auth.py` ו‑`primer.py`.

---

## פריימר לסוכן — `GET /api/agent/primer`

אנדפוינט HTTP רגיל (לא כלי MCP) שמחזיר **טקסט חופשי** שהסוכן קורא בפתיחת סשן:

```bash
curl -sS -H "Authorization: Bearer $CODEKEEPER_PAT" \
  https://<MCP-HOST>/api/agent/primer
```

- **Content-Type:** `text/plain; charset=utf-8` — לא JSON. הגוף נקרא ע"י המודל כפי שהוא.
- **תוכן:** שדה "הוראות לסוכן" מעמוד ההגדרות בוובאפ, ואחריו שורת מצב קצרה עם שלושת
  הקבצים האחרונים שנשמרו ומתי.
- **`204`** כששדה ההוראות ריק (ולא `200` עם גוף ריק). **`401`** בלי טוקן תקין.
- **תקרת 24KB:** חריגה ⇒ חיתוך + שורה שמודיעה על כך. לעולם לא שגיאה.
- **Cache 60 שניות** לכל משתמש (`Cache-Control: private, max-age=60`).
- **סינון סודות** על כל הגוף לפני ההחזרה.

התקרה וה‑TTL קבועים בקוד ואינם משתני סביבה — ראו את ה‑docstring של `primer.py` להסבר.

> ⚠️ **ה‑URL הוא של ה‑MCP host, לא של הוובאפ.** הוובאפ יחזיר `404`. הוק שמושך את
> הפריימר בפתיחת סשן ושותק בכל כשל ייכשל לנצח בשקט — הבחינו בין `204` (אין פריימר,
> שתיקה נכונה) לבין `404`/`401` (תקלה).

### משיכה אוטומטית בפתיחת סשן

**למה ההוק יושב בריפו ולא רק בפלאגין.** אותה התנהגות ארוזה גם כפלאגין
([`amirbiron/codekeeper-plugin`](https://github.com/amirbiron/codekeeper-plugin)), אבל
קונטיינר של סשן Claude Code בדפדפן עולה עם `SKIP_PLUGIN_MARKETPLACE=true` ואינו טוען
פלאגינים מהמרקטפלייס כלל: אין תיקיית `plugins`, אין `CLAUDE_PLUGIN_ROOT`, וההוק של
הפלאגין לא רץ — ומכיוון שלא רץ, גם אינו יכול לדווח על כך. סקילים ברמת חשבון כן
מסונכרנים לסביבות האלה; פלאגינים לא. העותק שבריפו הוא מה שגורם לפריימר להיטען שם.
הראיות ובדיקות ההבחנה מרוכזות ב‑[codekeeper-plugin#3](https://github.com/amirbiron/codekeeper-plugin/pull/3).

`.claude/settings.json` בשורש הריפו מגדיר `SessionStart` hook מסוג `command`
שמריץ את `.claude/hooks/codekeeper-primer.sh` בכל פתיחת סשן של Claude Code על
הריפו הזה. הסקריפט מבצע את ה‑`curl` בעצמו, קורא את קוד הסטטוס ומגיב לפי המשמעות.

**למה סקריפט ולא hook מסוג `http`.** הוק `http` מזריק את גוף התשובה ותו לא: אין לו
דרך להבחין בין `204` (אין הוראות — שתיקה נכונה) לבין `401`/`404` (תקלה). שניהם
יוצאים כשתיקה, וההוק נכשל לנצח בלי לומר מילה — בדיוק האזהרה שבסעיף הקודם. הסקריפט
מדפיס את הפריימר ב‑`200`, שותק ב‑`204`, ומדפיס שורת אבחון אחת בכל כשל אחר.

- **הרצה.** הפקודה היא `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/codekeeper-primer.sh`.
  הקריאה דרך `bash` במפורש מייתרת הרשאת הרצה על הקובץ — כך הוא עובד גם כשנוצר
  דרך ממשק הווב של GitHub, שאינו מאפשר להדליק את הביט הזה.
- **משתני סביבה.** הסקריפט יורש את סביבת הסשן ומשתמש ב‑`CODEKEEPER_PAT`
  (הטוקן) וב‑`CODEKEEPER_PRIMER_URL` (יעד חלופי, ברירת מחדל: ה‑MCP host).
  אין כאן `allowedEnvVars` — זו הצהרה של hook מסוג `http` בלבד.
- **מי שלא הגדיר `CODEKEEPER_PAT`** לא צריך לעשות דבר: הסקריפט מזהה זאת, מדפיס
  שורה אחת ויוצא **לפני** הקריאה לרשת. הוא לא שולח כותרת ריקה ולא מקבל `401`.
- **כשל אינו חוסם.** הסקריפט תמיד יוצא ב‑`0`; פריימר שלא נטען לא מפיל פתיחת סשן.
- **סוד לא נשמר בגיט.** הקובץ מכיל את *שם* המשתנה בלבד; הערך נקרא בזמן ריצה.
- **לוג אבחון** נכתב ל‑`${XDG_STATE_HOME:-~/.local/state}/codekeeper/primer-hook.log`
  (תיקייה פרטית, `0700`). הוא עונה על שאלה אחת: האם ההוק בכלל רץ.

> ⚠️ **גבול האבטחה השתנה עם המעבר ל‑`command`.** להוק מסוג `http` הייתה הגנה
> ייעודית — `allowedHttpHookUrls` ב‑`~/.claude/settings.json` האישי, שהגדרות
> פרויקט לא יכולות לעקוף. **להוק מסוג `command` אין מקבילה:** הסקריפט יושב בריפו,
> ומי שמשנה אותו (או מריץ סשן על fork) יכול להפנות את הטוקן ליעד אחר. לכן יש
> להתייחס ל‑`.claude/hooks/` כאל קוד שרץ עם הסביבה שלכם, ולסקור בו כל שינוי
> באותה רמת קפדנות כמו קוד ייצור. מי שמעדיף את ההגנה הקשיחה יכול להשאיר את
> הסקריפט מחוץ לריפו ולהחזיק אותו ב‑`~/.claude/hooks/` האישי.

הכלל `Bash(curl:*)` אינו נדרש כאן ואינו מוגדר בכוונה: הוקים מורצים על ידי המעטפת
ואינם עוברים דרך מנגנון ההרשאות של כלי ה‑Bash. הוספתו הייתה מרחיבה את מה שהמודל
עצמו רשאי להריץ — עם `CODEKEEPER_PAT` בסביבה, זו דרך לשלוח את הטוקן ליעד שרירותי.

---

## חיבור מ‑Claude.ai (OAuth)

ב‑Claude.ai → Settings → Connectors → **Add custom connector**: הזן **Name** ו‑
**Remote MCP server URL** = `https://<mcp-host>/mcp`. זהו — Claude יבצע DCR + OAuth
לבד, יפנה אותך להתחברות טלגרם ולמסך אישור, ויתחבר. (אין צורך למלא OAuth Client
ID/Secret.) דורש שמצב OAuth יהיה מוגדר בפריסה — ראו למטה.

## חיבור מ‑Claude Code (PAT)
```bash
claude mcp add --transport http codekeeper https://<mcp-host>/mcp \
  --header "Authorization: Bearer <token>"
```

## חיבור מ‑Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "codekeeper": {
      "type": "http",
      "url": "https://<mcp-host>/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

### הנפקת PAT
**מתוך הבוט:** `/connect_claude` בצ'אט פרטי → טוקן קריאה + פקודת חיבור מוכנה.
`/connect_claude write` → טוקן עם הרשאת **כתיבה** (יצירה/עדכון).
**CLI (אופס):** `MONGODB_URL="..." python scripts/mcp_issue_token.py --user-id <TELEGRAM_ID>`
(הוסיפו `--write` לטוקן כתיבה). הטוקן מוצג **פעם אחת בלבד**.

### הרשאת כתיבה ל‑Claude.ai
כדי ש‑Claude.ai יבקש `write`, ה‑connector צריך להירשם מחדש (DCR) עם ההרשאה — לא ניתן
לכפות זאת מצד השרת. אם כבר חיברת connector לקריאה, **הסר והוסף אותו מחדש** ואשר את מסך
ההרשאה (קריאה **וכתיבה**). מסלול ה‑PAT (`/connect_claude write`) מבטיח כתיבה ל‑Claude Code
ללא תלות בהתנהגות הלקוח.

---

## הרצה מקומית
```bash
pip install -r requirements/development.txt
MONGODB_URL="..." uvicorn mcp_server.app:app --host 0.0.0.0 --port 8000
```
- נקודת הקצה של MCP: `POST/GET /mcp` (Streamable HTTP).
- בריאות (ללא אימות): `GET /healthz`.

---

## פריסה (Render)

שירות web נפרד (ASGI). **חייב להתחבר לאותו MongoDB כמו הבוט/הוובאפ** — אחרת טוקנים
לא יימצאו.
```text
Start command:  uvicorn mcp_server.app:app --host 0.0.0.0 --port $PORT
Health check:   /healthz
```

**מצב PAT‑only (Claude Code/Desktop בלבד) — מינימלי:**
- `MONGODB_URL` + `DATABASE_NAME` — זהים לבוט/וובאפ (ברירת מחדל `code_keeper_bot`).
- `BOT_TOKEN` — נדרש רק כדי שמודול ה‑`config` המשותף ייטען.
- `MCP_SERVER_NAME` — אופציונלי.

**מצב OAuth (מוסיף תמיכה ב‑Claude.ai)** — נדלק אוטומטית כשמוגדרים גם:
- `MCP_SERVER_URL` = ה‑URL הציבורי (**https**) של שירות ה‑MCP (למשל `https://codekeeper-mcp.onrender.com`).
- `WEBAPP_URL` = ה‑URL הציבורי של הוובאפ (למסך התחברות הטלגרם).
- `SECRET_KEY` = **אותו ערך כמו הוובאפ** (חותם/מאמת את זהות המשתמש בין השירותים).

**בנוסף, על שירות הוובאפ** יש להגדיר `MCP_SERVER_URL` (לשער open‑redirect ב‑`/oauth/identify`),
ועל **שירות הבוט** `MCP_SERVER_URL` (עבור `/connect_claude`).

> `MCP_ALLOWED_HOSTS` (CSV, wildcard) אופציונלי לנעילת בדיקת ה‑Host; ריק = כבוי (מתאים לשרת ציבורי מוגן‑טוקן).

---

## זרימת ה‑OAuth (בקצרה)
```text
Claude.ai → /authorize → provider יוצר txn → הפניה ל-webapp /oauth/identify
   → התחברות טלגרם → חתימת HMAC של user_id → MCP /oauth/consent (מסך אישור)
   → מנפיק code → /token (SDK מאמת PKCE) → access+refresh tokens
   → קריאות tools עם ה-access token (subject = user_id)
```

---

## מבנה הקוד

| קובץ | תפקיד |
|------|-------|
| `token_store.py` | ניהול PAT מעל `mcp_tokens` |
| `backend.py` | גישה לנתונים + סריאליזציה (Smart Projection, בדיקת בעלות) |
| `handlers.py` | לוגיקת הכלים הטהורה — יעד הטסטים |
| `auth.py` | `current_user_id` (OAuth/PAT) + PAT middleware (fallback) + `authenticate_bearer` לראוטים שאינם `/mcp` |
| `oauth_store.py` | אחסון clients/codes/tokens/txns (hash) |
| `oauth_provider.py` | מימוש חוזה ה‑OAuth של ה‑SDK (כולל PAT מאוחד) |
| `oauth_identity.py` | חתימת/אימות זהות HMAC (משותף עם הוובאפ) |
| `oauth_routes.py` | מסך ה‑consent + הנפקת code |
| `primer.py` | `GET /api/agent/primer` — פריימר טקסט לסוכן (24KB, cache 60ש׳, סינון סודות) |
| `server.py` | חיווט FastMCP: כלים + OAuth + ASGI |
| `app.py` | נקודת כניסה: בוחר PAT/OAuth לפי ENV |

צד הוובאפ: `webapp/routes/auth_routes.py` → `/oauth/identify` (גשר הזהות).
טסטים: `tests/test_mcp_*.py` + `tests/test_webapp_oauth_identify.py` (fakes ידניים).
