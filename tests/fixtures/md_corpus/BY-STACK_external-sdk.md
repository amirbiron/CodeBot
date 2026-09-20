# BY-STACK: SDKs חיצוניים (Anthropic, Google, Stripe, OAuth, push notifications)

## רלוונטיות — העתק את הקובץ הזה אם בפרויקט יש...
- ✅ קריאות SDK של Anthropic / OpenAI / LLM אחר
- ✅ APIs של Google (Calendar, Gmail, OAuth, Sheets, FCM, web-push)
- ✅ SDKs של Stripe, Twilio, Telegram, Slack, Meta
- ✅ ניתוח של תגובות API, payloads של webhook, או JSON שנוצר על ידי AI
- ✅ אתחול SDK בזמן startup עם env vars / keys
- ⏭ דלג אם: לפרויקט אין אינטגרציות צד שלישי

> Cross-link: **CORE U3** (ולידציה של external input) הוא הכלל הכללי; הקובץ הזה מכסה מופעים ספציפיים ל-SDK. **R4** (שלמות exception של SDK) חי כאן לעומק.

---

## מודל מנטלי

כל SDK חיצוני הוא שני גבולות:
1. **קריאה יוצאת** — הקוד שלך → SDK → רשת. יכול להיכשל עם היררכיית exceptions של ה-SDK, שגיאות רשת, או timeout.
2. **נתונים נכנסים** — SDK → הקוד שלך. יכול להחזיר צורות שונות ב-test/sandbox/prod, יכול לכלול nulls/שדות חסרים, ו-type hints של ה-SDK הם שאפתניים.

קוד הגנתי בשני הגבולות הוא מחיר הכניסה.

---

## דפוס 1 — תפיסת base צר מדי ב-`except` (R4)

```python
try:
  result = await anthropic.messages.create(...)
except RateLimitError:
  await asyncio.sleep(BACKOFF); retry
except _RETRYABLE_ERRORS:
  retry
# ❌ subtypes של APIError (NotFound, BadRequest, Auth) עוברים בלי טיפול
```

### תיקון
תפוס את ה-base class של ה-SDK, ואז עדן:
```python
try:
  result = await anthropic.messages.create(...)
except RateLimitError:
  retry
except APIError as e:
  if e.status_code == 400: handle_bad_request(e)
  else: raise
```

סדר את בלוקי ה-`except` subclass-לפני-superclass.

### Commits אמיתיים
- Noa `c128115` — שלמות exception של Anthropic SDK.
- Noa `95dcce6` — fallback בלע `RateLimitError` כ-`AIError` גנרי.

---

## דפוס 2 — `CancelledError` לא נתפס על ידי `Exception` (Python ≥ 3.8)

```python
results = await asyncio.gather(*tasks, return_exceptions=True)
for r in results:
  if isinstance(r, Exception):  # ❌ מפספס CancelledError
    handle_error(r)
  else:
    count_success += 1  # ❌ tasks מבוטלים נספרים כהצלחה
```

`asyncio.CancelledError` יורש מ-`BaseException` (לא `Exception`) מאז Python 3.8.

### תיקון
```python
for r in results:
  if isinstance(r, BaseException):
    handle_error(r)
```

### Commits אמיתיים
- Shipment-bot `e0f4d59`.

---

## דפוס 3 — `isinstance(r, SendResult)` מול `r is True`

```python
if r is True: count_success += 1  # ❌ אובייקט SendResult, לא bool
```

### תיקון
ממש `__bool__` על מחלקת התוצאה, או השווה במפורש:
```python
if isinstance(r, SendResult) and r.ok: count_success += 1
```

### Commits אמיתיים
- Shipment-bot `11e7379`.

---

## דפוס 4 — אתחול SDK בזמן startup קורס את השרת (R4)

```python
# ב-import time
webpush.set_vapid_details(
  subject=settings.VAPID_EMAIL,
  public_key=settings.VAPID_PUBLIC_KEY,
  private_key=settings.VAPID_PRIVATE_KEY,
)
```

אם `VAPID_EMAIL` חסר prefix של `mailto:`, או keys פגומים, זה זורק ב-import → כל השרת קורס ב-boot. אותו דבר ל-OAuth client init, Stripe client init.

### תיקון
עטוף ב-try/except + ולידציית פורמט:
```python
def init_push():
  try:
    if not settings.VAPID_EMAIL.startswith("mailto:"):
      vapid_email = f"mailto:{settings.VAPID_EMAIL}"
    else:
      vapid_email = settings.VAPID_EMAIL
    webpush.set_vapid_details(subject=vapid_email, public_key=..., private_key=...)
    return True
  except Exception:
    logger.exception("push notifications disabled — VAPID init failed")
    return False
```

הורד את ה-*פיצ'ר*, לא את כל השרת.

### Commits אמיתיים
- routine `e5c26ad`, `2571c91`.

---

## דפוס 5 — regex על JSON של AI / SDK (CORE U3)

```python
match = re.search(r"\{.*\}", ai_response, re.DOTALL)  # ❌ חמדן; נשבר על prose
data = json.loads(match.group(0))
```

`\{.*\}` חמדן. `}` סוגר ב-prose (`"... and finally }"`) דולף לתוך ה-match. אובייקטים מקוננים, escape sequences גם שוברים.

### תיקון
```python
decoder = json.JSONDecoder()
start = ai_response.find("{")
if start < 0: raise ValueError("no JSON")
data, _ = decoder.raw_decode(ai_response[start:])
```

### Commits אמיתיים
- Noa `f27adc1`.

---

## דפוס 6 — isinstance guards על תגובות חיצוניות (CORE U3)

```python
data = response.json()
items = data.get("messages", [])  # ❌ אם data הוא רשימה, .get קורס
```

### תיקון
```python
data = response.json()
if not isinstance(data, dict):
  raise ValueError(f"expected dict, got {type(data)}")
items = data.get("messages", [])
if not isinstance(items, list):
  raise ValueError("messages not a list")
```

### Commits אמיתיים
- EmailFlow `6b7dbeb`, `46d05f7`, `55b4328`, `018b166`.

---

## דפוס 7 — env / config flags של SDK שלא כובדו

חלק מה-SDKs דורשים env-var flags כדי לטפל ב-edge cases של עולם אמיתי:
- `OAUTHLIB_RELAX_TOKEN_SCOPE=1` — סטיית scope של OAuth בספריות Google (Noa `95b82e5`).
- `OAUTHLIB_INSECURE_TRANSPORT=1` — רק ל-dev מקומי (HTTP callbacks).
- `STRIPE_API_VERSION` — pin כדי למנוע שינויי-שבירה שקטים.
- `ANTHROPIC_LOG=debug` — logs verbose.

תעד את אלה בהגדרות הפרויקט שלך והתייחס ל-scope-drift / version-skew כ-events תפעוליים צפויים, לא exceptions.

---

## דפוס 8 — אי-התאמת Pydantic schema על enum חיצוני (מקושר ל-state-machine.md דפוס 4)

```python
class LeadDraft(BaseModel):
  service_category: ServiceCategoryEnum  # strict; דוחה לא מוכר
```
AI מחזיר `"unknown"` → Pydantic דוחה → ה-draft כולו (כולל `full_name` ו-`phone` תקפים) הולך לאיבוד.

### תיקון
לערכי enum ממקור חיצוני, קבל `str | None` ועשה ולידציה idempotent ב-caller. שמור enums strict לשדות פנימיים בלבד.

### Commits אמיתיים
- Noa `7001892`, `f6293e3`, `dc24922`.

---

## דפוס 9 — Walrus + בדיקת truthy על env var

```python
if override := os.environ.get("OVERRIDE_VALUE"):  # ❌ "" הוא falsy אבל override תקף
  apply(override)
```

`""` הוא ערך משמעותי ("override ל-empty"), אבל ה-walrus מתייחס אליו כ-`None`.

### תיקון
```python
override = os.environ.get("OVERRIDE_VALUE")
if override is not None:
  apply(override.strip())
```

### Commits אמיתיים
- Noa `236b072`.

---

## דפוס 10 — אובייקט עצל שנחשב לאימות שקרה

```python
self.github = Github(token)
self.user = self.github.get_user()   # ❌ לא נשלחה שום בקשה
# ...
def is_available(self):
    return self.github is not None and self.user is not None   # ❌ תמיד True
```

`Github.get_user()` ללא ארגומנט מחזיר `AuthenticatedUser` עם `completed=False` — אובייקט עצל. ה-`GET /user` נשלח רק בגישה הראשונה לשדה, דרך `_completeIfNotSet`. כלומר טוקן שנשלל "מתחבר" בהצלחה, `is_available` מחזיר אמת, וה-`except GithubException` שנכתב סביב הקריאה לא רץ לעולם. הכשל מתגלה מאוחר, בניסיון לבצע פעולה, עם הודעה שלא מצביעה על המקור.

### תיקון

הדרך העדיפה היא להגיד ל-SDK לשלוח את הבקשה, במקום לסחוט אותה מגישה לשדה:

```python
self.github = Github(token)
# ``lazy=False`` מעביר ``completed=None``, ולכן ``complete()`` רץ בבנייה
# והבקשה נשלחת כאן. בלי הדגל האובייקט נשאר עצל וטוקן שנשלל עובר כתקין.
self.user = self.github.get_user(lazy=False)
```

שים לב לכיוון: **היעדר** הדגל הוא המצב העצל, והדגל `lazy=False` הוא שמאלץ את הבקשה. זה הפוך ממה שמנחשים כשקוראים רק את השם, ולכן צריך לאמת בספירת בקשות ולא בהיגיון.

החלופה — לגעת בשדה במפורש — עובדת גם היא, וזה מה שיש היום ב-CodeBot:

```python
user = self.github.get_user()
# ``get_user()`` מחזיר אובייקט עצל: הבקשה יוצאת רק בגישה לשדה.
# בלי השורה הבאה טוקן שנשלל היה עובר כתקין. הערך עצמו לא נרשם.
_ = user.login
self.user = user
```

היא נחותה בשני דברים. ראשית, השורה נראית כמו קוד מת ולכן היא חייבת הערה — אחרת היא תוסר בניקוי הבא. במקרה האמיתי היא הוסרה בדיוק כך: הגישה ל-`login` ישבה בתוך `logger.info(...)`, והוסרה כתיקון ל-PII (ראה `bugbot-rules/side-effect-riding-on-log-line.md`). שנית, היא תלויה בבחירת שדה נכונה — ראה למטה.

### מלכודת: לא כל שדה מאלץ בקשה

`NamedUser` ב-PyGithub גוזר את `login` מתוך ה-URL (`/users/{login}`) בלי לפנות לרשת. כלומר `self.github.get_user("octocat", lazy=True).login` מחזיר `"octocat"` ואפס בקשות — "אימות" שלא אימת כלום. במסלול של CodeBot זה לא קורה, כי `AuthenticatedUser` נבנה מ-`/user` ואין שם מה לגזור, אבל מי שיעתיק את הדפוס לשדה או למחלקה אחרת עלול ליפול. שדה שאפשר לגזור ממה שכבר בזיכרון אינו ראיה לתקשורת.

### הטבלה שאומתה (PyGithub 2.9.1)

נמדד בספירת בקשות בפועל, עם `Github(token)` בברירת מחדל:

| קריאה | בקשה בבנייה |
|---|---|
| `get_user()` | לא |
| `get_user(lazy=False)` | כן |
| `get_user(lazy=True)` | לא |
| `get_user("octocat")` | כן |
| `get_user("octocat", lazy=False)` | כן |
| `get_user("octocat", lazy=True)` | לא |

### בדיקה

כפיל שזורק כבר ב-`get_user()` יעבור גם על קוד שאינו מאמת דבר, ויסתיר את הבאג. הכפיל חייב להיכשל **בגישה לשדה**:

```python
class _LazyFailingUser:
    @property
    def login(self):
        raise BadCredentialsException(401, "Bad credentials", None)
```

### סיווג הכשל

PyGithub כבר ממפה את התגובה לתת-מחלקות ב-`Requester.createException` — `RateLimitExceededException` (403 של מכסה), `BadCredentialsException` (401), `TwoFactorException`. להישען על הסיווג שלו במקום לנחש לפי קוד סטטוס: 403 הוא גם הגבלת קצב וגם הרשאה חסרה, ובקשה לחבר טוקן מחדש בגלל מכסה שנגמרה שולחת את המשתמש לתקן משהו תקין.

### Commits אמיתיים
- CodeBot PR #3241 (אוגוסט 2026).

---

## דפוס 11 — פרמטר שאינו קיים ב-API: נכנסים ל-`try` ואף פעם לא מסיימים אותו

```python
try:
    plan = cursor.explain(verbosity=verbosity)   # ❌ אין פרמטר כזה, ומעולם לא היה
except TypeError:
    logger.warning("falling back without execution stats")
    plan = cursor.explain()
```

הצורה הזו **תמיד נראית תקינה בסקירה**: יש טיפול בשגיאות, יש הודעה מסבירה, יש מסלול חלופי. אבל אם החתימה האמיתית היא `def explain(self)`, פייתון נכשל כבר ב**קשירת הארגומנטים** — לפני שהשורה הראשונה בגוף המתודה רצה. כלומר הביצוע כן **נכנס** ל-`try` ומת בשורה הראשונה שבו, ה-`except` הוא **המסלול היחיד שמסתיים אי פעם**, וההודעה שלו מתארת את ההפך ממה שקורה. (זו אינה "קוד מת" במובן המדויק — זה קוד שנכנסים אליו ואף פעם לא מסיימים.)

**האירוע (CodeBot PR #3333):** התפריט "Explain Verbosity" בדשבורד לא עשה כלום — הערך נשלח, הגיע לשירות ונזרק. מונגו הריצה **תמיד** `allPlansExecution` (האפשרות שכתוב לידה "debug בלבד"), גם כשנבחרה "queryPlanner (בטוחה)". גם רעש ה-traceback בלוגי הפרודקשן הגיע משם.

**והחצי המלמד:** קדם לכך PR #2939, שתיקן את הקריאה מ-positional ל-keyword — **טלאי על API שלא קיים**. שינוי סינטקטי סביר למראה, שהאריך את חיי הבאג בשמונה חודשים.

### כלל
`except` שנכתב סביב חתימה — לוודא בקוד הספרייה או בתיעוד **שהחתימה קיימת**, לפני שכותבים את הטיפול. ואם `except` מחזיר תמיד את אותה תוצאה: להריץ פעם אחת עם `raise` במקום הטיפול, ולראות אם משהו בכלל משתנה. ‏`source-driven-development` הוא הכלל הכללי; זה המופע היקר שלו.

### Commits אמיתיים
- CodeBot PR #3333 (ספטמבר 2026); הטלאי המקדים ב-PR #2939.

---

## דפוס 12 — אין מסלול ריענון אחרי 401

השירות נבנה פעם אחת, והטוקן שבתוכו פג באמצע. אין שום מסלול שמרענן אותו, ולכן **401 אחד הורג את הפיצ'ר עד התחברות ידנית**.

**האירוע (CodeBot PR #3035):** `ensure_folder` ושאר פעולות ה-Drive קיבלו את אובייקט השירות פעם אחת. אחרי 401, כל גיבויי ה-Drive של המשתמש נכשלו — לא פעם אחת, אלא מכאן והלאה.

### כלל
לכל לקוח SDK שמחזיק אישורים עם תפוגה — **ולהבחין בין שני כשלים שנראים דומים ואינם**:

| מה חזר | מאיפה | מה זה אומר | מה עושים |
|---|---|---|---|
| `401` **עם** `WWW-Authenticate: Bearer error="invalid_token"` | מ**שרת המשאב**, על הבקשה עצמה | הטוקן פג, נשלל או פגום | לרענן, ולנסות **פעם אחת** |
| `401` **עירום**, בלי פרמטר `error` | מ**שרת המשאב** | *"absence of credentials"* — לא נשלחו אישורים, לא "הטוקן פג" | לא לרענן על סמך זה לבדו |
| `403` עם `error="insufficient_scope"` | מ**שרת המשאב** | חסר scope, לא תפוגה | ריענון לא יעזור. לבקש scope, או להיכשל מפורשות |
| `invalid_grant` | מ**שרת הטוקנים**, על בקשת הריענון | ה-grant עצמו בטל — נשלל, פג, או הוחלף | **לא לנסות שוב עם אותו grant.** להתנתק ולדרוש התחברות מחדש |

**מקור:** RFC 6750 §3.1 מגדיר את `invalid_token` כ-*"The access token provided is expired, revoked, malformed, or invalid for other reasons"*, ואת `insufficient_scope` כ-403. ולגבי 401 עירום — ה-RFC אומר במפורש שכשהבקשה חסרה אישורים, השרת **לא** אמור לכלול קוד שגיאה; כלומר 401 בלי `error` מסמן היעדר אישורים, לא תפוגה. (https://www.rfc-editor.org/rfc/rfc6750)

מכאן שני כללים: **לרענן רק כשיש ראיה מפורשת** — הכותרת, או חוזה מתועד של הספק שאומר שזה מה שהוא שולח בתפוגה (לא כל ספק מקיים את ה-RFC, ולכן קוראים את התיעוד שלו במקום להניח). ו**הבלבול בין 401 ל-`invalid_grant` הוא לולאה**: ריענון שנכשל ב-`invalid_grant` ומנוסה שוב יחזיר `invalid_grant` לנצח.

**והניסיון החוזר מותנה בעצמו:** חוזרים רק על פעולה שידוע שלא בוצעה, או שהיא idempotent. בקשת כתיבה שאולי הגיעה לשרת לפני שהטוקן נדחה אינה מועמדת לניסיון עיוור. וכשהריענון נכשל — **התנתקות מוצהרת** (ניקוי הטוקן, סימון המשתמש כמנותק, הודעה) עדיפה על לקוח שנשאר בזיכרון ומחזיר 401 לנצח.

### Commits אמיתיים
- CodeBot PR #3035 (פברואר 2026).

---

## דפוס 13 — אובייקט SDK שאסור לבדוק אותו בבוליאני

```python
if collection:        # ❌ pymongo זורק NotImplementedError בכוונה
if not default_db:    # ❌ אותו דבר
if collection is not None:   # ✅
```

הזריקה כאן היא **פיצ'ר**: היא מונעת את הבלבול בין "האובייקט קיים" ל"האוסף אינו ריק". אבל היא מגיעה כחריגה במקום מפתיע, ולרוב בתוך `try` שבולע.

**האירוע (CodeBot PR #3199):** שמירת סקילים נכשלה בגלל `if collection:`. ובמופע מוקדם יותר (`4e20f7b5`), הבוט עשה `sys.exit(1)` על מסד תקין לחלוטין.

### כלל
אובייקטים של SDK נבדקים ב-`is None` / `is not None`, לא באמת בוליאנית — גם כשזה נראה מיותר. הצורה הזו נכונה תמיד; הבוליאנית נכונה רק כשה-SDK הסכים לה. ראה גם דפוס 9 בקובץ הזה (walrus + truthy על env var) — אותה משפחה: ‏truthiness שנשענת על הנחה שלא נבדקה.

### Commits אמיתיים
- CodeBot PR #3199 (יולי 2026); מופע מוקדם `4e20f7b5` (אוגוסט 2025).

---

## הפניות צולבות

- **CORE U3** — ולידציה של boundary (תיאוריה כללית)
- **R4** — שלמות exception של SDK (הקובץ הזה הוא ה-deep-dive)
- **BY-STACK/state-machine.md** — אי-התאמת Pydantic schema
- **`bugbot-rules/external-input-isinstance.md`**, **`sdk-error-completeness.md`**, **`sdk-lazy-object-not-validated.md`**
