# הוספת ריפו חדש לדפדפן הקוד

מדריך מהיר וקצר לחיבור ריפו GitHub חדש ל-Repo Browser של Code Keeper, כולל סנכרון אוטומטי בכל push.

> **טיפ מנוסיון:** אם ניסיתם עם Classic PAT ולא הצליח (403/404 מוזרים) – עברו ל-**Fine-grained Personal Access Token**. בפועל זה מה שעבד באופן יציב.

---

## מה נקבל בסוף

- הריפו מאונדקס במסד הנתונים ונגיש דרך `/repo` ב-webapp.
- **סנכרון אוטומטי**: כל `push` לענף הראשי מרענן את האינדקס תוך שניות (דרך webhook).
- טוקן פר-ארגון: אפשר לחבר ריפואים מכמה ארגונים שונים במקביל.

---

## דרישות מקדימות (חד-פעמי)

- **דיסק ב-Render**: השירות `code-keeper-webapp` חייב דיסק מחובר (ברירת מחדל: `/var/data/repos`) – שם נשמרים ה-mirrors.
- **`GITHUB_WEBHOOK_SECRET`** מוגדר ב-Render Environment – ערך אקראי חזק, לדוגמה:
  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"
  ```
  אותו ערך יוגדר גם בכל webhook. בלעדיו כל webhook נדחה עם 401.

---

## שלב 1 · יצירת Fine-grained Token

1. GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens** → **Generate new token**.
2. **Resource owner**: החשבון או הארגון שאליו שייך הריפו (למשל `Campaign-AI4U` או `amirbiron`).
3. **Repository access**: `Only select repositories` → בחר את הריפו/ים הספציפיים.
4. **Repository permissions** – שים על **Read-only** את:
   - `Contents` (חובה – בשביל clone/fetch)
   - `Metadata` (מתווסף אוטומטית)
5. **Generate token** → **העתק את הטוקן** (מוצג פעם אחת בלבד!). מתחיל ב-`github_pat_...`.

> אם הריפו תחת ארגון עם **SSO אכיפה** – בעמוד הטוקנים שלך לחץ **Configure SSO** ליד הטוקן החדש ו-**Authorize** לארגון.

---

## שלב 2 · הוספת הטוקן ל-Render

ברנדר → שירות `code-keeper-webapp` → **Environment**.

### מקרה א: זה הריפו הראשון שלכם
הגדר משתנה יחיד:
```
GITHUB_TOKEN=github_pat_...
```

### מקרה ב: כבר יש ריפואים מארגונים אחרים
השתמש ב-**`GITHUB_TOKENS`** (מיפוי owner→token). כל שורה = ארגון אחד:
```
GITHUB_TOKENS=Campaign-AI4U=github_pat_AAA,amirbiron=github_pat_BBB
```
או ב-JSON:
```
GITHUB_TOKENS={"Campaign-AI4U": "github_pat_AAA", "amirbiron": "github_pat_BBB"}
```

**המפתח = הבעלים בדיוק כמו שהוא ב-URL** של הריפו (`https://github.com/<כאן-הבעלים>/<repo>`).
לא צריך למחוק את `GITHUB_TOKEN` – הוא ישמש כ-fallback אם הבעלים לא נמצא ב-mapping.

**Save Changes** → המתן שרנדר יסיים redeploy.

---

## שלב 3 · הרצת ייבוא ראשוני בשל של Render

`Dashboard → code-keeper-webapp → Shell`:

```bash
cd ~/project/src
python3 - <<'PY'
from services.repo_sync_service import initial_import
from database.db_manager import get_db

res = initial_import(
    "https://github.com/<OWNER>/<REPO>.git",
    "<REPO>",
    get_db(),
)
print(res)
PY
```

החלף `<OWNER>` ו-`<REPO>` בערכים אמיתיים. שים לב:
- הפרמטר השני (`"<REPO>"`) יהיה **השם שהריפו יופיע איתו** ב-Repo Browser.
- התהליך סינכרוני – ייקח מ-כמה שניות עד כמה דקות תלוי בגודל. חכה עד `print(res)`.
- **הצלחה** נראית כמו `{'success': True, 'files_indexed': ..., 'default_branch': 'main', ...}`.
- **כישלון על אימות** (`Authentication failed`) – חזור לשלב 1/2 וודא שהטוקן מתאים לארגון וסקופ `Contents: Read`.

---

## שלב 4 · הגדרת webhook (סנכרון אוטומטי בכל push)

בעמוד הריפו ב-GitHub → **Settings → Webhooks → Add webhook**:

- **Payload URL**: `https://code-keeper-webapp.onrender.com/api/webhooks/github`
- **Content type**: `application/json`
- **Secret**: אותו ערך של `GITHUB_WEBHOOK_SECRET` ברנדר.
- **SSL verification**: Enable.
- **Which events?** → **Just the push event**.
- **Active** ✅ → **Add webhook**.

מיד אחרי היצירה GitHub שולח אירוע `ping`. בלשונית **Recent Deliveries** אמור להופיע ✅ עם **200**. עשה push לענף הראשי → אירוע נוסף עם **202** ("queued") = סנכרון רץ ברקע.

> הסנכרון מופעל **רק על push ל-default branch**. push לענפים אחרים מתעלמים ממנו בכוונה.

---

## אימות מהיר

1. פתח את ה-webapp: `/repo` – הריפו החדש צריך להופיע ברשימה.
2. עשה push קטן ל-main → תוך כמה שניות האינדקס מתעדכן.
3. אם משהו לא עלה – בדוק ב-Render **Logs** אחרי `services.repo_sync_service` או `services.git_mirror_service`.

---

## פתרון תקלות נפוצות

| תסמין | משמעות | פתרון |
|---|---|---|
| `Authentication failed` / 403 בשל | הטוקן אינו רואה את הריפו | בדוק שהטוקן שייך לבעלים הנכון + `Contents: Read` + SSO Authorized |
| `Mirror already exists` + `Available refs/heads: []` | mirror ריק/שבור מנסיון קודם | הרץ `unmirror_repo("<REPO>", get_db())` ואז `initial_import` שוב |
| webhook: `401` ב-Recent Deliveries | ה-secret לא תואם | ודא ש-`GITHUB_WEBHOOK_SECRET` ברנדר זהה בדיוק ל-secret ב-webhook |
| webhook: אין deliveries בכלל | Payload URL שגוי / שירות לא זמין | בדוק URL, ובעמוד השירות ברנדר שהוא Live |
| push לא מסנכרן | הפוש היה לענף לא-ראשי | מוגדר בכוונה – רק default branch מפעיל סנכרון |

### ניקוי mirror שבור (הפקודה השימושית ביותר)
```bash
cd ~/project/src
python3 - <<'PY'
from services.repo_sync_service import unmirror_repo
from database.db_manager import get_db
print(unmirror_repo("<REPO>", get_db()))
PY
```
אחרי זה אפשר להריץ מחדש את `initial_import` נקי לגמרי.

---

## הערות אבטחה

- **טוקנים ב-env בלבד** – לא ב-repo, לא בלוגים.
- Fine-grained tokens עדיפים על Classic: הרשאה מדויקת פר-ריפו + פקיעה קצרה.
- החליפו טוקנים מדי כמה חודשים (רוטציה).
- אם טוקן דלף – **Revoke** ב-GitHub מיד, וצור חדש.
