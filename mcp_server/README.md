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
פרט ל‑`codekeeper_save_file` (כתיבה — דורש הרשאת `write`).

| כלי | תיאור |
|-----|-------|
| `codekeeper_list_files` | רשימת קבצים (מטא‑דאטה בלבד), עם עימוד |
| `codekeeper_search_code` | חיפוש טקסט בקוד → מטא‑דאטה של קבצים תואמים |
| `codekeeper_get_file` | תוכן מלא של קובץ לפי `file_name` או `file_id` (אופציונלי: גרסה) |
| `codekeeper_save_file` | **כתיבה:** יצירה/עדכון קובץ לפי `file_name` (גרסה חדשה, לא דורס; עד 100KB). דורש `write` |
| `codekeeper_list_versions` | היסטוריית גרסאות של קובץ (מטא‑דאטה) |
| `codekeeper_list_collections` | האוספים של המשתמש |
| `codekeeper_get_collection` | אוסף בודד לפי id |
| `codekeeper_get_collection_items` | הקבצים בתוך אוסף (עם עימוד/סינון תיקייה) |

---

## אימות — שני מסלולים (מאוחדים תחת `load_access_token`)

1. **OAuth 2.1** — עבור **Claude.ai** (Custom Connector). זרימה מלאה: DCR + PKCE +
   authorize + consent + token. הזהות נקבעת דרך **התחברות טלגרם בוובאפ**.
2. **Personal Access Token (PAT)** — עבור **Claude Code / Desktop**. `Authorization:
   Bearer ckmcp_…`, נשמר כ‑hash בקולקשן `mcp_tokens`, ניתן לביטול.

ה‑`user_id` נגזר **תמיד** מהטוקן — לעולם לא מקלט הלקוח.

**הרשאות (scopes):** `read` (ברירת מחדל) ו‑`write`. כלי הכתיבה בודק `write` בזמן ריצה;
טוקן קריאה בלבד יקבל שגיאת `insufficient_scope` (ולא ייכתב דבר). איך משיגים כתיבה — ראו למטה.

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
| `auth.py` | `current_user_id` (OAuth/PAT) + PAT middleware (fallback) |
| `oauth_store.py` | אחסון clients/codes/tokens/txns (hash) |
| `oauth_provider.py` | מימוש חוזה ה‑OAuth של ה‑SDK (כולל PAT מאוחד) |
| `oauth_identity.py` | חתימת/אימות זהות HMAC (משותף עם הוובאפ) |
| `oauth_routes.py` | מסך ה‑consent + הנפקת code |
| `server.py` | חיווט FastMCP: כלים + OAuth + ASGI |
| `app.py` | נקודת כניסה: בוחר PAT/OAuth לפי ENV |

צד הוובאפ: `webapp/routes/auth_routes.py` → `/oauth/identify` (גשר הזהות).
טסטים: `tests/test_mcp_*.py` + `tests/test_webapp_oauth_identify.py` (fakes ידניים).
