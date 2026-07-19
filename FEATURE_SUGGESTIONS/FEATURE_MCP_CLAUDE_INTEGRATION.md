# חיבור Claude.ai ל‑CodeKeeper דרך MCP — מסמך תכנון

> **סטטוס:** פאזה 0 (MVP קריאה‑בלבד + PAT) **מומשה** — ראו `mcp_server/`. פאזות 1–3 עדיין בתכנון.
> **ענף פיתוח:** `claude/mcp-codekeeper-webapp-ldnzsg`
> **מתי להשתמש:** לפני מימוש חיבור MCP; מסמך זה הוא מקור האמת לתכנון.
> **ראו גם:** `mcp_server/README.md` (שימוש), [CodeBot – Project Docs](https://amirbiron.github.io/CodeBot/), `CLAUDE.md` (מדיניות מחייבת).

> **מצב מימוש (פאזה 0):** נכתבה חבילת `mcp_server/` (שרת FastMCP קריאה‑בלבד עם 7 כלים
> ל‑`code_snippets` + `collections`), אימות PAT מעל קולקשן `mcp_tokens`, סקריפט
> `scripts/mcp_issue_token.py`, וטסטים `tests/test_mcp_*.py`. **הערת סטייה מהמסמך:**
> מאגר הטוקנים נמצא ב‑`mcp_server/token_store.py` (ולא `database/mcp_tokens.py`), כדי
> שהמודולים יהיו נטולי תלויות כבדות וניתנים לבדיקה בבידוד. פקודת הבוט `/connect_claude`
> ו‑OAuth (Claude.ai) יגיעו בפאזות הבאות.

---

## 1. תקציר מנהלים (What / Why)

**What:** לחשוף את הקבצים והקוד ששמורים ב‑CodeKeeper (מסד `code_snippets`) ל‑Claude.ai דרך **שרת MCP מרוחק** (Model Context Protocol). כך משתמש יוכל לחבר את החשבון שלו ב‑Claude, ולבקש מ‑Claude לקרוא/לחפש (ובהמשך גם לשמור) קבצים ישירות מהמאגר האישי שלו.

**Why:** היום הקבצים נגישים רק דרך הבוט בטלגרם ודרך הוובאפ. חיבור MCP הופך את המאגר האישי למקור הקשר (context) חי בתוך Claude — בלי להעתיק‑להדביק, עם שמירה על בעלות והרשאות לכל משתמש.

**הגישה המומלצת (פשוט ואמין קודם):** להתחיל מ‑MVP קריאה‑בלבד עם טוקן אישי (PAT) שנבדק מול Claude Code/Desktop, ורק אחר כך להוסיף OAuth מלא שהופך אותו ל‑Connector אמיתי של Claude.ai. כתיבה מגיעה בשלב האחרון, מאחורי הרשאה מפורשת.

---

## 2. רקע — מה כבר קיים היום (וזה עוזר מאוד)

### 2.1 שכבת נתונים נקייה בתוך התהליך
יש API סינכרוני נקי שאפשר לייבא ולהשתמש בו ישירות, בלי לעבור דרך ה‑HTTP של הוובאפ:

```python
from database import db  # DatabaseManager singleton (database/__init__.py:11)

db.get_user_files(user_id, limit=50, skip=0)      # רשימה, ללא שדות כבדים
db.get_latest_version(user_id, file_name)          # תוכן מלא של קובץ
db.get_file_by_id(file_id)                          # תוכן מלא לפי _id
db.search_code(user_id, query, programming_language=None, tags=None, limit=20)
db.get_all_versions(user_id, file_name)            # היסטוריית גרסאות
db.save_file(user_id, file_name, code, programming_language, extra_tags=None)
db.delete_file(user_id, file_name)                 # מחיקה רכה (recycle bin)
```

מקורות: `database/repository.py` (למשל `get_user_files:846`, `get_latest_version:781`, `search_code:925`, `save_file:682`, `save_code_snippet:201`), delegation ב‑`database/manager.py`.

**נקודה קריטית:** אין אימות בשכבת ה‑DB — כל שיטה מסוננת לפי `user_id` אבל **סומכת על הקורא** שיעביר `user_id` נכון. לכן שרת ה‑MCP חייב לגזור את `user_id` מהטוקן בלבד, ואף פעם לא מקלט של הלקוח.

### 2.2 מודל הנתונים של קובץ
קולקשן `code_snippets` (dataclass `CodeSnippet` ב‑`database/models.py:9`):

| שדה | תיאור |
|------|--------|
| `user_id` (int) | מזהה טלגרם של הבעלים (מפתח הבידוד) |
| `file_name` | זהות לוגית; גרסאות חולקות שם |
| `code` | תוכן (שדה כבד) |
| `programming_language` | שפה |
| `tags`, `description` | מטא‑דאטה; תגית `repo:*` = קובץ שיובא מ‑GitHub |
| `version`, `is_active` | ניהול גרסאות (append‑only) + מחיקה רכה |
| `file_size`, `lines_count` | מחושבים בזמן שמירה (`repository.py:247,252`) |
| `is_favorite`, `is_pinned` | מועדפים/נעיצה |

קבצים גדולים יושבים ב‑`large_files` (שדה `content` במקום `code`, replace‑on‑save).

### 2.3 אימות וזהות (היום — סשן בלבד)
- הכל נשען על **cookie סשן חתום** בשם `session`, ומזהה יחיד `session['user_id']`.
- `login_required` — `webapp/app.py:3204`; `get_current_user_id` — `webapp/app.py:3249`.
- **אין** JWT, אין PAT, אין OAuth‑provider, אין CORS, אין CSRF framework (תלויות: `Flask==3.1.2`, בלי `flask-login`/`flask-cors`/`authlib`).

**גשרי טוקנים שכבר עובדים (הבסיס להרחבה):**
1. `webapp_tokens` — טוקן התחברות **חד‑פעמי, 5 דקות**. הבוט מנפיק (`conversation_handlers.py:299` — `sha256(f"{user_id}:{time}:{secret}")[:32]`), הוובאפ ממיר לסשן ב‑`GET /auth/token` (`webapp/routes/auth_routes.py:202`).
2. `remember_tokens` — טוקן ארוך‑טווח (`secrets.token_urlsafe(32)`), עם cookie `remember_me` והתחברות‑מחדש ב‑`try_persistent_login()` (`webapp/app.py:3371`).
3. `DB_HEALTH_TOKEN` — סוד תפעולי משותף (Bearer), **לא לכל משתמש** (`webapp/app.py:4927`).

הסודות המשותפים בין הבוט לוובאפ: `BOT_TOKEN`, `SECRET_KEY`, `WEBAPP_LOGIN_SECRET`, `MONGODB_URL`.

### 2.4 פריסה
- הוובאפ רץ תחת **gunicorn + gevent** (WSGI), מודול `app:app`, worker יחיד כברירת מחדל (רגיש לזיכרון ב‑Render). ראו `scripts/start_webapp.sh`.
- בתלויות כבר יש `uvicorn==0.38.0` ו‑`asgiref==3.8.1` (מתאים ל‑ASGI/Streamable‑HTTP).
- הבוט הוא תהליך נפרד (`python main.py`); יש גם push‑worker (Node).

---

## 3. מה Claude.ai דורש כדי להתחבר (Custom Connector = Remote MCP)

- **תעבורה:** Streamable HTTP (לא stdio — stdio זה רק Claude Desktop מקומי).
- **אימות:** **OAuth 2.1 + PKCE (S256)** — חובה. עם רישום לקוח דינמי (**DCR**, RFC 7591) או CIMD / credentials מוחזקים ע"י Anthropic.
- **Discovery:** Protected Resource Metadata (RFC 9728) ב‑`/.well-known/oauth-protected-resource`, ו‑Authorization Server Metadata ב‑`/.well-known/oauth-authorization-server`.
- **Refresh tokens:** רוטציה עבור public clients.
- **רשת:** טווח ה‑egress של Anthropic חייב להגיע לשרת.
- **תוכניות:** Claude Pro/Max/Team/Enterprise.

מקורות: [Claude Help Center — custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp), [Authentication for connectors](https://claude.com/docs/connectors/building/authentication).

---

## 4. ארכיטקטורה מוצעת

```
┌────────────┐   OAuth 2.1 (PKCE)   ┌──────────────────────────┐
│  Claude.ai │ ───────────────────► │  שרת MCP חדש (שירות נפרד) │
│ (Connector)│   Streamable HTTP    │  Python + ASGI (uvicorn) │
└────────────┘                      │  - tools: list/search/get│
                                    │  - resources: file://…   │
                                    │  - גוזר user_id מהטוקן    │
                                    └───────────┬──────────────┘
                                                │ import ישיר
                                                ▼
                                    ┌──────────────────────────┐
                                    │  database/  →  MongoDB    │
                                    │  code_snippets (per user) │
                                    └──────────────────────────┘
```

**למה שירות נפרד ולא בתוך הוובאפ:**
- ה‑worker של הוובאפ יחיד ורגיש לזיכרון ב‑Render — לא רוצים להעמיס עליו SSE ארוך‑טווח.
- MCP נוח יותר כ‑ASGI (`uvicorn`), בעוד הוובאפ הוא WSGI.
- בידוד = פחות סיכון; אפשר לתת הרשאות קריאה בלבד ל‑DB בשלב א'.
- שיתוף פשוט: אותו `MONGODB_URL` ואותם סודות דרך ENV ב‑Render.

**חלופה (לא מומלצת לפרודקשן):** stdio מקומי מול Claude Desktop שמתחבר ישר ל‑Mongo — טוב ל‑POC אבל חושף credentials במכונת המשתמש ולא עונה על "Claude.ai בוובאפ".

---

## 5. הכלים והמשאבים (MCP surface)

### 5.1 Tools
| כלי | קלט | פלט | נשען על |
|-----|-----|-----|---------|
| `list_files` | `limit`, `page`, `language?`, `tag?` | רשימת מטא‑דאטה (בלי `code`) | `get_user_files` |
| `search_code` | `query`, `language?`, `type?` | תוצאות + snippet קצר | `search_code` |
| `get_file` | `file_name` \| `file_id`, `version?` | תוכן מלא + מטא‑דאטה | `get_latest_version` / `get_file_by_id` |
| `list_versions` | `file_name` | היסטוריית גרסאות | `get_all_versions` |
| `get_version_diff` | `file_id`, `left?`, `right?` | diff בין גרסאות | `webapp/app.py:3264` (compare) |
| `list_collections` | — | אוספים של המשתמש | `collections_manager` |
| `save_file` *(פאזה 3)* | `file_name`, `code`, `language`, `tags?`, `description?` | גרסה חדשה | `save_file` |
| `delete_file` *(פאזה 3)* | `file_name` | מחיקה רכה | `delete_file` |

### 5.2 Resources (אופציונלי, מומלץ)
לחשוף כל קובץ כ‑`codekeeper://file/{file_name}` כדי לאפשר תיוג `@` של קובץ בתוך Claude. רשימת המשאבים = `get_user_files` (בלי תוכן), והקריאה בפועל = `get_latest_version`.

### 5.3 עקרונות תגובה
- לכבד את **חוק ה‑Smart Projection** (`CLAUDE.md`): ברשימות/חיפוש **לא** למשוך `code`/`content` — רק מטא‑דאטה + snippet. תוכן מלא רק ב‑`get_file` מפורש.
- לסנן `repo:*` בברירת מחדל (כמו `/api/files`), עם דגל אופציונלי לכלול.

---

## 6. אימות — שתי פאזות

### פאזה 0 — Personal Access Token (הכי פשוט ואמין; מתחילים כאן)
1. פקודת בוט חדשה `/connect_claude` שמנפיקה טוקן אקראי ארוך (`secrets.token_urlsafe(32)`), שומרת ב‑קולקשן חדש `mcp_tokens`:
   ```json
   { "token_hash": "sha256(...)", "user_id": 12345,
     "scopes": ["read"], "created_at": "...", "last_used_at": "...",
     "expires_at": null, "revoked": false, "label": "Claude.ai" }
   ```
   (שומרים **hash** של הטוקן, לא את הטוקן עצמו — מציגים למשתמש פעם אחת בלבד.)
2. שרת ה‑MCP מקבל `Authorization: Bearer <token>`, מאמת מול `mcp_tokens`, וגוזר `user_id`.
3. עובד **מיד** מול Claude Code / Claude Desktop (שתומכים בכותרות), ומוכיח את כל הצינור.

זה הדפוס שכבר קיים ב‑`webapp_tokens`/`conversation_handlers.py:299` — רק ארוך‑טווח, מרובה‑שימוש, וניתן לביטול (revoke).

### פאזה 1 — OAuth 2.1 (מה שהופך אותו ל‑Connector של Claude.ai)
- מכיוון שהזהות כבר קיימת דרך טלגרם, מסך ה‑`/authorize` **משתמש בסשן הטלגרם הקיים**: אם המשתמש כבר מחובר לוובאפ — מציגים מסך אישור (consent) ומנפיקים authorization code; אם לא — שולחים אותו לזרימת ההתחברות הקיימת ואז חוזרים.
- להנפיק access token (קצר) + refresh token (עם רוטציה), קשורים ל‑`user_id` ול‑`scopes`.
- להגיש `/.well-known/oauth-protected-resource` ו‑`/.well-known/oauth-authorization-server`, ולתמוך ב‑DCR.
- מימוש מומלץ: `authlib` (יש כבר `google-auth-oauthlib` באקוסיסטם) או שכבת ה‑Auth המובנית של MCP Python SDK / FastMCP.

**חשוב:** access/refresh tokens נשמרים גם הם רק כ‑hash, וה‑`user_id` לעולם לא מגיע מהלקוח אלא מהטוקן שאומת.

---

## 7. פערים ב‑API ה‑HTTP — ולמה ה‑DB בתוך התהליך פותר אותם
מיפוי הקוד העלה שני חורים ב‑REST הקיים:
1. **אין endpoint JSON שמחזיר תוכן מלא לפי id לבעלים** (רק `GET /download/<id>` כ‑text/plain).
2. **אין endpoint JSON ליצירת קובץ** (עריכה נעשית דרך טופס HTML `POST /edit/<id>`).

מכיוון ששרת ה‑MCP ניגש ישירות ל‑`database` (`get_file_by_id`, `save_file`) — **שני הפערים נעלמים** בלי לתקן קודם את הוובאפ. זו עוד סיבה להעדיף גישת in‑process על פני עטיפת ה‑HTTP.

---

## 8. אבטחה ופרטיות
- **בידוד לפי `user_id` בכל כלי** — נגזר מהטוקן בלבד; לעולם לא מקלט לקוח.
- **קריאה‑בלבד כברירת מחדל**; כתיבה/מחיקה מאחורי `scope` נפרד ואישור מפורש (פאזה 3).
- **טוקנים כ‑hash** ב‑DB; הצגה חד‑פעמית; אפשרות revoke ורשימת חיבורים פעילים.
- **Rate limiting** (יש כבר `Flask-Limiter`; לשירות ה‑MCP נגדיר מגבלות משלו).
- **בלי סודות/PII בלוגים** — השחרה, לפי מדיניות `CLAUDE.md`.
- לכבד Smart Projection — לא לשלוף `code` ברשימות (גם ביצועים וגם צמצום חשיפה).

---

## 9. תשתית ופריסה
- **שירות Render חדש** (web, ASGI) — למשל `code-keeper-mcp`, `dockerfilePath`/`startCommand` = `uvicorn mcp_server.app:app`.
- **ENV משותף:** `MONGODB_URL`, `DATABASE_NAME`, `SECRET_KEY`/`WEBAPP_LOGIN_SECRET`, ו‑ENV ייעודי ל‑OAuth (issuer URL, טווח תוקף וכו').
- **תלויות חדשות** (בקובצי `requirements/`): `mcp` (MCP Python SDK / FastMCP), ובפאזה 1 גם `authlib`.
- **תיקייה חדשה** מוצעת: `mcp_server/` בשורש (או תת‑שירות תחת `services/`), עם `app.py`, `auth.py`, `tools.py`, `resources.py`.

---

## 10. מפת דרכים, בדיקות והערכת מאמץ

| שלב | תוכן | הערכה | בדיקות |
|------|------|-------|--------|
| א' | MVP קריאה‑בלבד: שרת MCP + `list_files`/`search_code`/`get_file`/`list_versions` + `/connect_claude` + `mcp_tokens` | ~2–3 ימים | יחידה לכל כלי (mongomock/tmp), בדיקת בידוד `user_id`, ריצה מול Claude Code |
| ב' | OAuth 2.1: authorize/token/register + `.well-known` + מסך consent (מעל סשן טלגרם) | ~3–5 ימים | זרימת OAuth מקצה‑לקצה, רוטציית refresh, בדיקת discovery |
| ג' | כתיבה: `save_file`/`delete_file` מאחורי scope, rate limiting, מסך "חיבורים פעילים" + revoke | ~1–2 ימים | בדיקות כתיבה על tmp בלבד, אישור scope, revoke |

**בדיקות — לפי `CLAUDE.md`:** לעבוד רק על תיקיות זמניות, בלי מחיקות ב‑root, בידוד לכל טסט. לפני תיקוני טסטים — לעיין ב‑[CodeBot Docs](https://amirbiron.github.io/CodeBot/).

---

## 11. סיכונים ו‑Rollback
- **חשיפת נתונים אישיים** → מיטיגציה: read‑only כברירת מחדל, scopes, טוקנים ניתנים לביטול, בידוד `user_id` נבדק בטסטים.
- **עומס זיכרון** → שירות נפרד, לא בתוך worker הוובאפ.
- **מורכבות OAuth** → מתחילים מ‑PAT (פאזה 0) שמוכיח ערך בלי OAuth.
- **Rollback:** השירות נפרד — ביטול פריסה של `code-keeper-mcp` וביטול טוקנים (`mcp_tokens.revoked=true`) מנתק הכול בלי לגעת בבוט/וובאפ.

---

## 12. שאלות פתוחות להחלטה
1. **מאיפה מתחילים** — MVP+PAT (מומלץ) / ישר ל‑OAuth / רק מסמך זה לאישור?
2. **קריאה‑בלבד או גם כתיבה** בשלב הראשון? (המלצה: קריאה‑בלבד).
3. **היקף** — רק `code_snippets`, או גם collections/bookmarks/large_files?
4. **שם ודומיין** לשירות ה‑MCP ב‑Render.

---

## 13. מקורות
- [Claude Help Center — Get started with custom connectors using remote MCP](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
- [Claude Docs — Authentication for connectors](https://claude.com/docs/connectors/building/authentication)
- [CodeBot – Project Docs](https://amirbiron.github.io/CodeBot/)
