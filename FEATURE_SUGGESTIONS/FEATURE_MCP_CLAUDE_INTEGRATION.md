# חיבור Claude.ai ל‑CodeKeeper דרך MCP — מסמך תכנון

> **סטטוס:** פאזות 0 (PAT) **+** 1 (OAuth 2.1 ל‑Claude.ai) **+** 3 (כתיבה save-only) **+** ד' (דפדפן ריפו לאדמין, קריאה בלבד) **מומשו** — ראו `mcp_server/`. מחיקה וכתיבת אוספים עדיין בתכנון.
> **ענף פיתוח:** `claude/mcp-codekeeper-webapp-ldnzsg`
> **מתי להשתמש:** לפני מימוש חיבור MCP; מסמך זה הוא מקור האמת לתכנון.
> **ראו גם:** `mcp_server/README.md` (שימוש), [CodeBot – Project Docs](https://amirbiron.github.io/CodeBot/), `CLAUDE.md` (מדיניות מחייבת).
>
> **מצב מימוש (פאזות 0–1–3):** חבילת `mcp_server/` (שרת FastMCP, 8 כלים ל‑
> `code_snippets` + `collections` — 7 קריאה + `codekeeper_save_file` לכתיבה). **אימות מאוחד**
> דרך `load_access_token`: PAT (`ckmcp_`, ל‑Claude Code/Desktop) **וגם** OAuth 2.1 מלא
> (DCR+PKCE, ל‑Claude.ai) עם גשר זהות דרך התחברות הטלגרם בוובאפ (`/oauth/identify` →
> `/oauth/consent`). פקודת בוט `/connect_claude` (`write` לטוקן כתיבה). **כתיבה** מאחורי
> scope `write` מפורש (יצירה/עדכון בלבד — append-only, גרסה חדשה, לא דורס). אכיפה ידנית
> ב‑handler (ל‑SDK אין scope פר‑כלי). **הערה ל‑Claude.ai:** קבלת `write` דורשת רישום DCR
> מחדש — יש להסיר ולהוסיף את ה‑connector. **הערת סטייה:** מאגרי הטוקנים ב‑`mcp_server/`
> (ולא `database/`), לבדיקוּת בבידוד. נותר: מחיקה וכתיבת אוספים. אומת מקצה‑לקצה מקומית
> ובפרודקשן (Claude Code על 682 קבצים אמיתיים).

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

```text
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
| ד' | דפדפן הריפו (אדמין בלבד): `list_repos`/`list_repo_tree`/`get_repo_file`/`search_repo` מעל Repo Sync Engine + `require_admin` + סינון tools/list + מדיניות סודות (13.5) — ראו סעיף 13 | ~2–3 ימים | יחידה עם mirror מזויף/tmp, בדיקת fail‑closed לאדמין, מדיניות סודות (כל כלל + מקרי קצה + מדיניות‑חסרה), ברירות מחדל/תקרות/clamp, תקציב פלט, timeout, snippet בלבד בחיפוש |

**מיפוי ומצב (קנוני):** שלב א' = פאזה 0 (✅ מומש) · שלב ב' = פאזה 1 (✅ מומש) · שלב ג' = פאזה 3 (✅ מומש חלקית — save‑only; מחיקה טרם) · שלב ד' = פאזה ד' (✅ מומש — קריאה בלבד, אדמין).

**בדיקות — לפי `CLAUDE.md`:** לעבוד רק על תיקיות זמניות, בלי מחיקות ב‑root, בידוד לכל טסט. לפני תיקוני טסטים — לעיין ב‑[CodeBot Docs](https://amirbiron.github.io/CodeBot/).

---

## 11. סיכונים ו‑Rollback
- **חשיפת נתונים אישיים** → מיטיגציה: read‑only כברירת מחדל, scopes, טוקנים ניתנים לביטול, בידוד `user_id` נבדק בטסטים.
- **עומס זיכרון** → שירות נפרד, לא בתוך worker הוובאפ.
- **מורכבות OAuth** → מתחילים מ‑PAT (פאזה 0) שמוכיח ערך בלי OAuth.
- **Rollback:** השירות נפרד — ביטול פריסה של `code-keeper-mcp` וביטול טוקנים (`mcp_tokens.revoked=true`) מנתק הכול בלי לגעת בבוט/וובאפ.

---

## 12. שאלות פתוחות להחלטה
1. **מאיפה מתחילים** — ✅ **הוחלט:** MVP+PAT (פאזה 0 = שלב א' במפת הדרכים); OAuth 2.1 נדחה לשלב נפרד — ומומש בפועל (פאזה 1 = שלב ב'). ראו שורת המיפוי בסעיף 10.
2. **קריאה‑בלבד או גם כתיבה** בשלב הראשון? — ⏳ **עדיין פתוחה** (המלצה: קריאה‑בלבד).
3. **היקף** — ✅ **הוחלט:** `code_snippets` **וגם** `collections`; לא ריפו/bookmarks/large_files בפאזה א'.
4. **דפדפן הריפו** — ✅ **הוחלט:** פיצ'ר **אדמין בלבד** (משתמש יחיד), כמקור נתונים נפרד — ראו סעיף 13 (פאזה ד').
5. **שם ודומיין** לשירות ה‑MCP ב‑Render.

---

## 13. פאזה ד': מקור נתונים שני — דפדפן הריפו (אדמין בלבד)

> **סטטוס:** ✅ **מומש** (קריאה בלבד) — `mcp_server/repo_backend.py`, `repo_handlers.py`,
> `repo_policy.py`, `require_admin` + `AdminAwareFastMCP` ב‑`server.py`/`auth.py`.
> אינו משנה את היקף פאזה א'.

### 13.1 למה זה שווה
הריפואים המשוקפים (Repo Sync Engine) מכילים את התיעוד, הקוד ומסמכי התכנון של כל הפרויקטים.
חשיפתם ל‑MCP מאפשרת ל‑Claude לקרוא מהם ישירות — במקום העתק‑הדבק או צילומי מסך.

**הבחנה חשובה:** זה **לא** אותו מקור כמו קבצי `repo:*` שבתוך `code_snippets` (יבוא GitHub
חד‑פעמי לקבצים האישיים; ראו 2.2 ו‑5.3 — שם הם דווקא מסוננים בברירת מחדל). דפדפן הריפו קורא
ממקור נפרד לגמרי: **bare mirrors על הדיסק** (`REPO_MIRROR_PATH`, ברירת מחדל `/var/data/repos`;
ריפו = `{base}/{repo_name}.git`, `services/git_mirror_service.py:322`) + metadata ב‑Mongo
(`repo_metadata`, `repo_files`), כשהמפתח הוא **שם ריפו לוגי** — לא `user_id`.

### 13.2 מודל ההרשאות — אדמין בלבד, fail‑closed
- **זהות מהטוקן בלבד** — כמו `user_id` בשאר הכלים (`current_user_id`, `mcp_server/auth.py:74`);
  לעולם לא מקלט הלקוח.
- **ברירת המחדל היא דחייה**: אין הקשר אדמין ודאי ⇒ הכלי נכשל בקול. בלי תוצאה חלקית, בלי
  נפילה שקטה למשתמש אחר.
- **מנגנון האדמין הקיים (ממצא מהקוד):** מקור אמת יחיד — ENV `ADMIN_USER_IDS` (CSV של
  user_ids). **אין** דגל אדמין ב‑DB. מימושים קיימים: `webapp/app.py:4077` (`is_admin`),
  `chatops/permissions.py:41`, ו‑`config.py:188` (שדה `ADMIN_USER_IDS` + ולידטור `:413`).
  לשירות ה‑MCP הדרך הקנונית: `int(user_id) in config.ADMIN_USER_IDS` (ה‑config כבר מיובא
  ב‑`mcp_server/handlers.py`). **במפורש לא** מכבדים את מפלט‑החירום
  `CHATOPS_ALLOW_ALL_IF_NO_ADMINS` (`chatops/permissions.py:51-53`) — רשימה ריקה פירושה
  שאין אדמין והכלים כבויים. מוצע helper `require_admin(ctx)` במתכונת `require_write`
  (`mcp_server/auth.py:121`).
- **הסתרה ב‑tools/list (ממצא SDK, `mcp==1.28.1`):** רשימת הכלים סטטית כברירת מחדל, אבל
  הקשר האימות זמין גם בתוך handler של list_tools — ולכן אפשר לסנן: תת‑מחלקה של FastMCP
  שדורסת `list_tools` ומחזירה את כלי הריפו רק לאדמין. **אזהרה: הסתרה ≠ בקרת גישה** —
  כלי שהוסתר מהרשימה עדיין ניתן לקריאה ישירה בשמו (ה‑dispatcher מריץ גם כלי שאינו ברשימה),
  ולכן `require_admin` בגוף **כל** כלי הוא החסם האמיתי; ההסתרה היא UX בלבד. חלופה שמסירה
  גם קריאוּת: מופע FastMCP נפרד לאדמין (מסלול/URL נפרד) — כבדה יותר, מתועדת כחלופה.

### 13.3 הכלים המוצעים (MCP surface לריפו)

| כלי | קלט | פלט | נשען על |
|-----|-----|-----|---------|
| `list_repos` | `limit?` | רשימת ריפואים + מטא‑דאטה (שם, default_branch, last_sync_time, total_files, sync_status; בלי תוכן) | **חסרה פונקציית שירות** — הלוגיקה כיום inline ב‑route `api_list_repos` (`webapp/routes/repo_browser.py:739`) מעל `repo_metadata`; גודל/sha מ‑`get_mirror_info` (`services/git_mirror_service.py:618`) |
| `list_repo_tree` | `repo`, `path?`, `ref?`, `page?`, `per_page?` | נתיבים + מטא‑דאטה, **בלי תוכן**, עם עימוד | **חסר ככלי שלם** — אבני בניין: `list_all_files` (`git_mirror_service.py:842`; ls‑tree שטוח, ref‑aware, בלי עימוד/סינון) + `get_file_info` (`:865`); חלופת אינדקס: `api_tree` (`repo_browser.py:148`; רמה אחת, Mongo בלבד) |
| `get_repo_file` | `repo`, `path`, `ref?` | תוכן מלא + מטא‑דאטה; תקרת 500KB; בינארי ⇒ מטא‑דאטה בלבד | **קיים** — `get_file_at_commit` (`git_mirror_service.py:1165`; תקרה `MAX_FILE_SIZE_FOR_DISPLAY`:30, זיהוי בינארי `:961`, ולידציית נתיב `:750`); פתרון ref דרך `repo_metadata.default_branch` / `get_current_sha` (`:649`) |
| `search_repo` | `repo`, `query`, `file_pattern?`, `max_results?` | שורות תואמות (path+line+snippet ≤500 תווים) עם תקרות ודגל `truncated` | **קיים** — `search_with_git_grep` (`git_mirror_service.py:1793`; סטרימינג `:1912`) או `RepoSearchService.search` (`services/repo_search_service.py:43`; פותר `refs/heads/<default_branch>`) |

### 13.4 גודל ו‑Smart Projection
ריפו הוא עץ שלם, לא קטע קוד — ולכן ההקפדה כאן חשובה כפליים:
- `list_repo_tree` יכול להחזיר אלפי נתיבים ⇒ **עימוד + סינון תיקייה/ref חובה**, ואסור להחזיר תוכן קבצים.
- `get_repo_file` עם תקרת גודל ברורה (קיימת: 500KB) וטיפול מוגדר בבינארי/גדול‑מדי (מטא‑דאטה + שגיאה נקייה).
- `search_repo` עם תקרת תוצאות ו‑snippet קצר בלבד (קיים: ≤500 תווים לשורה, ≤20 התאמות לקובץ) — לא קבצים מלאים.
- הכל בכפוף ל**חוק ה‑Smart Projection** (5.3): תוכן מלא רק בבקשה מפורשת (`get_repo_file`).

**ברירות מחדל ותקרות בצד השרת (מחייב במימוש):** ערכים מחוץ לטווח **נחתכים** (clamp) —
לא נדחים — באותו דפוס `_clamp` שכבר נהוג ב‑`mcp_server/handlers.py`; קלט לא‑תקין ⇒ ברירת מחדל.

| כלי | פרמטר | ברירת מחדל | תקרה |
|-----|--------|-------------|-------|
| `list_repos` | `limit` | 50 | 200 |
| `list_repo_tree` | `per_page` (+`page`≥1) | 200 | 1000 |
| `search_repo` | `max_results` | 50 | 100 |

- `max_results` תוחם את **סך כל ההתאמות** בתשובה (התקרה הפנימית של ≤20 התאמות לקובץ נשארת
  בנוסף, לא במקום). ה‑timeout של החיפוש (10s ב‑`search_with_git_grep`) נקבע בצד השרת ואינו
  ניתן להגדלה מהלקוח.
- **תקציב פלט לתשובה**: תשובות עץ/חיפוש מוגבלות גם בבייטים (סדר גודל ~256KB) — חריגה ⇒
  קיטום עם `truncated: true` וסיבת קיטום; `get_repo_file` חסום ממילא בתקרת ה‑500KB.

**מעטפת תגובה יציבה ל‑`get_repo_file`** (עוטפת את `get_file_at_commit`, משמרת את תקרת
ה‑500KB וזיהוי הבינארי):
- הצלחה: `{ok: true, status: "ok", file: {path, ref, resolved_commit, size, lines, encoding}, content}`.
- בינארי: `{ok: true, status: "binary", file: {…}}` — **בלי** `content`.
- גדול‑מדי: `{ok: true, status: "too_large", file: {…, size}, max: 512000}` — **בלי** `content`.
- לא נמצא / ref לא תקין: `{ok: false, error: "not_found"}`; נתיב חסום במדיניות: `{ok: false, error: "path_denied"}`.
- כשל בזמן sync פעיל: `{ok: false, error: "sync_in_progress", retry_after: 30}` — הקורא מוזמן לנסות שוב, לא להסיק היעדר.
כך לקוח MCP מבחין בין כל התוצאות בלי לנחש מהיעדר שדות.

### 13.5 מדיניות סינון סודות — חובה, fail‑closed
סינון הסודות הוא **תנאי מקדים להפעלת הכלים**, לא תוספת: כלי הריפו לא נדלקים לפני
שהמדיניות והטסטים שלה קיימים.
- **היקף:** המדיניות חלה על כל שלושת משטחי הקריאה — `get_repo_file` **חוסם** נתיב תואם
  (`path_denied`), `list_repo_tree` **משמיט** נתיבים תואמים מהרשימה, ו‑`search_repo` **מדלג**
  עליהם בחיפוש.
- **נרמול לפני התאמה:** `normpath` + התאמה case‑insensitive, גם על הנתיב המלא וגם על
  ה‑basename — כך שמכוסים גם נתיבים מקוננים (`config/.env`, `a/b/id_rsa`) וגם וריאציות
  רישיות (`.ENV`). (הגנת traversal כבר קיימת — `_validate_repo_file_path`,
  `git_mirror_service.py:750` — והמדיניות נוספת מעליה.)
- **רשימת בסיס (ניתנת להרחבה בקונפיג):** `.env*`, `*.pem`, `*.key`, `id_rsa*`/`id_ed25519*`,
  `secrets.*`, `credentials*`, `*.p12`/`*.pfx`, `.netrc`, `.npmrc` — שמות מקובלים לחומר
  סודות, כולל שמות חלופיים; הרשימה היא baseline ומורחבת לפי הצורך.
- **fail‑closed:** אם המדיניות לא נטענה (קונפיג חסר/שגוי) — כלי הקריאה **מסרבים להגיש
  תוכן** ומחזירים שגיאה מפורשת; לעולם לא מגישים בלי סינון.
- **טסטים ייעודיים (חלק מהגדרת ה‑Done):** כיסוי לכל כלל ברשימה + מקרי קצה — נתיב מקונן,
  רישיות, `secrets.yaml` לעומת `secrets_test.py`, basename מול נתיב מלא, ומצב מדיניות‑חסרה
  (חייב להיכשל סגור).

### 13.6 פערים מול המימוש הקיים
מיפוי הקוד העלה את הפערים הבאים:
1. **אין פונקציית שירות `list_repos`** — הלוגיקה קיימת רק כ‑route (לא ניתנת לקריאה כפונקציה); נדרש handler דק.
2. **אין עץ עם עימוד/סינון‑תיקייה מה‑bare repo** — `list_all_files` שטוח ולא מעומד; `api_tree` נשען על אינדקס Mongo בלבד (רמה אחת).
3. **אין רשימת branches/refs** — `for-each-ref` רץ רק inline ב‑initial_import (`services/repo_sync_service.py:539-619`) ואינו חשוף.
4. **אין שכבת אדמין ב‑MCP** — `require_admin` וסינון tools/list הם עבודה חדשה (ראו 13.2).
5. **אין denylist/redaction על נתיבי הקריאה** — ראו המדיניות המחייבת ב‑13.5 והסיכון ב‑13.7.
6. **ל‑`repo_metadata` אין אינדקס** — ✅ נסגר כחלק מהמימוש (`list_repos` רץ עליו בכל קריאה):
   אינדקס unique על `repo_name` נוצר גם ב‑`scripts/create_repo_indexes.py` וגם best‑effort
   באתחול ה‑backend (`mcp_server/repo_backend.py`).

כמו בסעיף 7 — הגישה ה‑in‑process (ישירות ל‑`GitMirrorService`) מייתרת תיקון מוקדם של
ה‑HTTP: הפערים נסגרים בשכבת ה‑MCP עצמה.

### 13.7 סיכונים
- 🔴 **דליפת קוד/סודות דרך קבצים בריפו**: נתיבי הקריאה יגישו כל קובץ שקיים ב‑mirror —
  כולל `.env` משוקף, מפתחות וכד'. `_sanitize_output` (`git_mirror_service.py:261`) מנקה רק
  את טוקן ה‑GitHub מפלט git עצמו, לא תוכן קבצים; `should_index` (`services/code_indexer.py:181`)
  הוא פילטר רלוונטיות לאינדקס — לא בקרת אבטחה. ⇒ מדיניות הסינון ב‑13.5 היא **תנאי מקדים
  מחייב** להפעלת הכלים (fail‑closed); הרחבה אפשרית שנשארת פתוחה: redaction גם בתוכן.
- **עומס דיסק/זיכרון בריפואים גדולים** — ממתן קיים: חיפוש בסטרימינג (`:1912`, תוכנן ל‑512MB
  ב‑Render) + התקרות של 13.4.
- **מרוץ מול sync**: אין נעילת קריאה (fetch/gc יכולים לרוץ במקביל, `repo_sync_service.py:202`) —
  הכלים סופגים כשל חולף ומחזירים שגיאה נקייה **עם אינדיקציה ש‑sync רץ**:
  `{"error": "sync_in_progress", "retry_after": 30}` (נבדק מול `sync_jobs.status="running"`),
  כדי שהמודל הקורא יידע לחזור אחרי המתנה קצרה ולא יסיק בטעות שהקובץ/הריפו לא קיימים.
- **הרחבת ה‑surface מעבר לנבדק**: כלים קריאים גם כשמוסתרים (13.2) ⇒ שער אדמין בגוף כל
  כלי — חובה, לא אופציה; והפיצ'ר כולו נשאר קריאה‑בלבד.

---

## 14. מקורות
- [Claude Help Center — Get started with custom connectors using remote MCP](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
- [Claude Docs — Authentication for connectors](https://claude.com/docs/connectors/building/authentication)
- [CodeBot – Project Docs](https://amirbiron.github.io/CodeBot/)
