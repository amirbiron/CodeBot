# CodeKeeper MCP Server (פאזה 0 — קריאה בלבד)

שרת [MCP](https://modelcontextprotocol.io) קטן שחושף את **הקבצים והאוספים**
השמורים של המשתמש ל‑Claude (Claude Code / Claude Desktop כרגע; Claude.ai דרך
OAuth בפאזה הבאה). קריאה בלבד — אין כלי כתיבה/מחיקה.

> תכנון מלא: `FEATURE_SUGGESTIONS/FEATURE_MCP_CLAUDE_INTEGRATION.md`

---

## מה זה עושה

ניגש ישירות לשכבת ה‑DB הקיימת (`database.db` + `CollectionsManager`), מסונן
תמיד לפי ה‑`user_id` שנגזר מהטוקן. מכבד את חוק ה‑Smart Projection: רשימות/חיפוש
לא מחזירים את שדה ה‑`code` הכבד — תוכן מלא רק ב‑`get_file`.

### הכלים (Tools)

| כלי | תיאור |
|-----|-------|
| `list_files` | רשימת קבצים (מטא‑דאטה בלבד), עם עימוד |
| `search_code` | חיפוש טקסט בקוד → מטא‑דאטה של קבצים תואמים |
| `get_file` | תוכן מלא של קובץ לפי `file_name` או `file_id` (אופציונלי: גרסה) |
| `list_versions` | היסטוריית גרסאות של קובץ (מטא‑דאטה) |
| `list_collections` | האוספים של המשתמש |
| `get_collection` | אוסף בודד לפי id |
| `get_collection_items` | הקבצים בתוך אוסף (עם עימוד/סינון תיקייה) |

---

## אימות (Personal Access Token)

הזדהות היא `Authorization: Bearer <token>`. הטוקן נשמר כ‑**hash בלבד** בקולקשן
`mcp_tokens`, קשור ל‑`user_id`, וניתן לביטול. ה‑`user_id` נגזר תמיד מהטוקן —
לעולם לא מקלט הלקוח.

### הנפקת טוקן

**הדרך הפשוטה — מתוך הבוט:** שלחו `/connect_claude` בצ'אט פרטי עם הבוט. תקבלו טוקן
מוכן + פקודת חיבור מוכנה להעתקה. (הפקודה זמינה בצ'אט פרטי בלבד כדי שהטוקן לא ידלוף.)

**לאופס/בדיקות (CLI):**
```bash
MONGODB_URL="..." python scripts/mcp_issue_token.py --user-id <TELEGRAM_ID> --label "Claude Desktop"
```
הטוקן מוצג **פעם אחת בלבד** — שמרו אותו.

---

## הרצה מקומית
```bash
pip install -r requirements/development.txt
MONGODB_URL="..." uvicorn mcp_server.app:app --host 0.0.0.0 --port 8000
```
- נקודת הקצה של MCP: `POST/GET /mcp` (Streamable HTTP).
- בריאות (ללא אימות): `GET /healthz`.

---

## חיבור מ‑Claude Code
```bash
claude mcp add --transport http codekeeper http://localhost:8000/mcp \
  --header "Authorization: Bearer <token>"
```

## חיבור מ‑Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "codekeeper": {
      "type": "http",
      "url": "https://<your-host>/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

> **Claude.ai (וובאפ):** דורש OAuth 2.1 — זו פאזה 1, עדיין לא כאן. PAT עובד היום
> מול Claude Code / Claude Desktop.

---

## פריסה (Render)
שירות web נפרד (ASGI), משתף את אותו `MONGODB_URL` ואת אותם סודות:
```text
Start command:  uvicorn mcp_server.app:app --host 0.0.0.0 --port $PORT
Health check:   /healthz
```
ENV: `MONGODB_URL` (משותף), ו‑`MCP_SERVER_URL` (ה‑URL הציבורי של השירות — משמש את
`/connect_claude` בבוט כדי לבנות את פקודת החיבור). מומלץ שירות נפרד (ולא בתוך הוובאפ)
כי ה‑worker של הוובאפ יחיד ורגיש לזיכרון.

---

## מבנה הקוד

| קובץ | תפקיד |
|------|-------|
| `token_store.py` | ניהול PAT (הנפקה/אימות/ביטול) מעל `mcp_tokens` |
| `backend.py` | גישה לנתונים + סריאליזציה (Smart Projection, בדיקת בעלות) |
| `handlers.py` | לוגיקת הכלים הטהורה (ולידציה/clamping) — יעד הטסטים |
| `auth.py` | middleware של Bearer + `current_user_id(ctx)` |
| `server.py` | חיווט FastMCP: כלים + אפליקציית ASGI מאומתת |
| `app.py` | נקודת כניסה: `app = create_app()` |

טסטים: `tests/test_mcp_*.py` (fakes ידניים, בלי MongoDB אמיתי).
