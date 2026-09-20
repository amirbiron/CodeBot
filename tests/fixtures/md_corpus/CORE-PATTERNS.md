# דפוסים מרכזיים (CORE)

דפוסי באגים אוניברסליים — אלה מופיעים ב**כל שלושת** מסמכי המקור (Noa_Leads, EmailFlow, וסט 8-הפרויקטים) על stacks שונים, פרויקטים שונים וטווחי זמן שונים. הם משקפים הרגלים אישיים וחוסרי שיקול דעת, לא בעיות ספציפיות לפרויקט. **החל אותם על כל פרויקט חדש, ללא קשר ל-stack.**

מוסכמת הספירה: `X/3 מקורות` מתייחסת תמיד לשלושת מסמכי ההצלבה המקוריים. מסמכי מקור מאוחרים (Markdown-Docs, CodeBot) שמוסיפים ראיות לדפוס קיים מסומנים בשורת התדירות כתוספת מפורשת — הם מחזקים את הדפוס אבל לא משנים את הקיבוץ ל-tiers.

לכל דפוס: commits אמיתיים מצוטטים, כלל זיהוי גנרי, false positives, ומצב אכיפה מומלץ.

---

## U1. Race conditions / async TOCTOU

**תדירות:** 3/3 מקורות, ~15 מופעים
**פרויקטים:** Noa_Leads, EmailFlow, Shipment-bot, Facebook-Leads-New, Markdown-Academy, routine
**חומרה:** HIGH

### איך זה נראה
נתיבי קוד concurrent קוראים מצב משותף, מסתעפים לפיו, ואז כותבים — בלי atomicity. מתבטא כ:
- כפילויות מ-webhooks / queue workers / cron + beat scheduler מקבילים.
- `await` חסר שגורם ל-coroutines להיות truthy תמיד.
- בדיקת lock שמתבצעת *מחוץ* ל-lock שהיא אמורה לשמור.
- Cursors / CAS שמשתמשים ב-`=` במקום `IS NULL` על עמודות nullable.

### וריאציות של הדפוס
אותו root cause, מופעים שונים. כולם נפתרים על ידי UNIQUE constraint + transaction lock (או CAS), אבל זיהוי הוריאציה הספציפית עוזר ב-debug:

- **(a) שורת DB לא נוצרת לפני external call** — הקוד קורא ל-`await client.X()` (Gmail draft, SMS, payment, webhook emit) *לפני* הכנסת שורת "intent" מקומית עם UNIQUE constraint. at-least-once delivery (Pub/Sub, retries, parallel workers) יוצרת orphans בצד החיצוני.
- **(b) פער check-then-act בין קריאה לכתיבה** — הקוד עושה `SELECT ... WHERE status='pending'`, מסתעף, ואז `UPDATE ... WHERE id=:id`. שני runners עוברים את הקריאה, שניהם מריצים את ה-update, שניהם מבצעים את הפעולה.
- **(c) Cursor / CAS column לא מתקדם atomically** — webhook קורא `sync_token`, קורא ל-API חיצוני, וכותב חזרה `next_sync_token` ב-statement נפרד. שני webhooks מתחרים על ה-cursor; שניהם מחילים את אותם deltas.
- **(d) `await` חסר על predicate async** — פונקציה async נקראת בהקשר בוליאני (`if foo():`); ה-coroutine תמיד truthy, אז ה-gate אף פעם לא חוסם.

ב-debug — זהה קודם את הוריאציה. התיקון מאותה משפחה (CAS / UNIQUE / lock), אבל המיקום הנכון שונה.

### דוגמאות אמיתיות
- **Noa (`33af59e`):** שני webhooks מקבילים של Google Calendar קראו את אותו `sync_token`, החילו deltas → שורות Activity כפולות. תיקון: optimistic lock + CAS (`WHERE history_id = expected_old`).
- **Noa (`cf99698`):** CAS על `WHERE history_id = expected_old` לא טיפל ב-`NULL` ב-Postgres → cursor תקוע לנצח.
- **EmailFlow (`f847a44`):** תשעה Pub/Sub workers מקבילים יצרו Gmail draft לפני שאחד הספיק לעשות commit → 9 drafts יתומים. תיקון: INSERT מקומי עם `UNIQUE` *לפני* הקריאה ל-Gmail.
- **Shipment-bot (`457eea1`):** `SELECT ... WHERE status='PENDING'` ואז `UPDATE`; ה-beat scheduler ו-`send_message.delay()` שניהם בחרו את השורה → ה-OTP נשלח פעמיים. תיקון: atomic `UPDATE ... WHERE status='PENDING' RETURNING id`, בדיקת rowcount.
- **Shipment-bot (`f1e0fbb`):** `_is_ip_blocked()` הפך ל-async, אבל הקורא לא הוסיף `await` → ה-coroutine תמיד truthy → כל webhook החזיר 429.
- **Facebook-Leads-New (`5823724`):** `_check_daily_limit()` רץ מחוץ ל-`scan_lock` → שתי קריאות מקבילות עברו את הבדיקה, שתיהן הריצו scans.
- **Markdown-Academy (`7c955f1`):** עליית השרת קראה ל-seed כמה פעמים במקביל בלי הגנה → שיעורים נוצרו פעמיים.

### כלל לזיהוי (להעתקה ל-CLAUDE.md / bugbot)
דווח על כל אחד מהבאים:
1. `await session.commit()` ולאחריו `await client.X()` (קריאה חיצונית בלתי הפיכה) בלי INSERT מקדים עם UNIQUE constraint או row lock.
2. `SELECT` / ORM `.scalar()` שמחזיר state, ואז סעיף, ואז `UPDATE` על אותה שורה בלי `WHERE` על הערך שנקרא (אין CAS).
3. פונקציית `async def` שנקראת בלי `await` ושימוש בה בהקשר בוליאני (`if foo():`).
4. critical section מוגן ב-lock שבו precondition נבדק *לפני* רכישת ה-lock.
5. CAS / cursor שמושווה עם `=` כשהערך יכול להיות `NULL` (Postgres: `col = NULL` הוא `NULL`, לא `TRUE` — חייב להסתעף עם `IS NULL`).

### False positives
- קריאות חיצוניות read-only (status fetch, analytics fire-and-forget) — אין צורך ב-reserve.
- script של תהליך יחיד בלי runners concurrent — race תיאורטי.
- כתיבה משתמשת ב-`INSERT ... ON CONFLICT` או UNIQUE שכבר תופס כפילויות.
- הקריאה מתבצעת בתוך בלוק `SELECT FOR UPDATE`.

### מצב מומלץ
**strict** ל-webhook handlers, queue/Celery tasks, cron jobs, payment / messaging / OTP flows.
**warning** לכלי admin פנימיים ו-scripts בריצה יחידה.

### ראה גם
- `BY-STACK/webhooks.md` — ספציפיות Pub/Sub at-least-once, signature, idempotency
- `BY-STACK/async-orm.md` — דפוסי CAS ב-SQLAlchemy, advisory locks
- `BY-STACK/cron-jobs.md` — race conditions בצד ה-cron
- `bugbot-rules/race-toctou.md` — prompt עצמאי

---

## U2. סנכרון state ב-React / stale closure

**תדירות:** 3/3 מקורות, ~6 מופעים
**פרויקטים:** Noa_Leads (frontend), EmailFlow (frontend), routine, Web
**חומרה:** MEDIUM (שובר UX; data corruption כשה-status נשלח חזרה ל-backend)

### איך זה נראה
`useState` מקומי שמאותחל מ-prop שמשתנה, ולא מסונכרן מחדש; או callback שתופס משתנה ישן; או hooks שנקראים אחרי early return ושוברים את Rules of Hooks.

### דוגמאות אמיתיות
- **Noa (`3fc0ec6`):** `useEffect` עם dep על reference של אובייקט הופעל מחדש ודרס edits של המשתמש.
- **Noa (`b360c66`):** `renderTemplate` async ללא בדיקת cancelled flag → preview ישן דרס את ה-UI.
- **EmailFlow (`e968135`):** `useState` אחרי `return` מוקדם → ספירת hooks משתנה → React crash.
- **EmailFlow (`02f633a`):** חסר `key={conversationId}` ב-`ReplyBox` → state עבר משיחה לשיחה.
- **EmailFlow (`d84daca` + `3987818`):** dropdown של status סונכרן רק על `leadId`; refetch של רשימה עדכן status ב-DB אבל ה-dropdown נשאר על ערך ישן → save שלח `expected_status` שגוי → pipeline חזר אחורה.
- **routine (`259c2a3`):** `activeChildId` חסר מ-deps של `useCallback` → אחרי החלפת ילד, פעולה השפיעה על הילד הקודם.
- **Web (`2e5c480`):** אחרי email verification רק `token` עודכן ב-`localStorage`; `refreshToken` נשאר ישן → reauth נשבר.

### כלל לזיהוי
דווח על כל אחד מהבאים:
1. `const [s, setS] = useState(props.X)` כש-`props.X` יכול להשתנות, וגם אין `useEffect([props.X])` resync וגם אין `key={...}` על הקומפוננטה.
2. `useState` / `useEffect` / `useCallback` / `useMemo` שנקראים אחרי `if (...) return null;` או כל early return.
3. `useCallback` / `useMemo` שגוף הפונקציה שלהם מתייחס ל-prop או state שלא נמצא ב-dependency array.
4. עדכון חלקי של ערך multi-field (למשל עדכון `token` בלי `refreshToken`).
5. `setState` אחרי `await` בלי בדיקת cancellation flag.

### False positives
- state מקומי בלבד (modal פתוח/סגור, theme toggle) — לא תלוי בנתונים חיצוניים.
- inputs uncontrolled עם `defaultValue` — מכוון.
- קומפוננטה שמקבלת prop פעם אחת ב-mount (למשל `user.id`) — אין צורך ב-sync.
- ה-dep array מדלג בכוונה על identity לא יציב (למשל אובייקט mutation של TanStack) — כדאי שתהיה הערת תיעוד מסבירה.

### מצב מומלץ
**warning** (strict מייצר רעש גבוה על state מקומי לגיטימי).

### ראה גם
- `BY-STACK/react-frontend.md` — deep-dive עם שלושת דפוסי ה-resync
- `bugbot-rules/react-stale-state-on-prop.md`

---

## U3. ולידציה של external input / boundary

**תדירות:** 3/3 מקורות + Markdown-Docs (מקור מאוחר), ~13 מופעים
**פרויקטים:** Noa_Leads, EmailFlow, Shipment-bot, Facebook-Leads-New, routine, Markdown-Docs
**חומרה:** MEDIUM (קריסות בטראפיק אמיתי) / HIGH (כשמשולב עם SQL או eval)

### איך זה נראה
הקוד מניח שקלט חיצוני (תשובות API, payloads של webhook, output של AI, משתני סביבה) במבנה הצפוי — אין `isinstance` guard, אין בדיקת NaN/Inf, regex תופס יותר מדי, subclass של exception ב-SDK לא נתפס.

### דוגמאות אמיתיות
- **Noa (`c128115`):** `_complete` תפס רק `RateLimitError` + `_RETRYABLE`; subtypes אחרים של `anthropic.APIError` (NotFound, BadRequest, Auth) עברו בלי טיפול.
- **Noa (`95dcce6`):** domain blacklist השתמש ב-exact match על host של email → `mail.mailchimp.com` לא נחסם.
- **Noa (`f27adc1`):** regex חמדן `\{.*\}` על תגובת JSON של AI נשבר על `}` סוגר ב-prose.
- **Noa (`7001892`):** `LeadDraft.service_category` כ-`StrEnum` דחה ערך לא מוכר → אובדן full_name + phone באותו שדה.
- **EmailFlow (`6b7dbeb`):** `headers["list-unsubscribe"].strip()` קרס כשהערך לא היה str (MIME מקולקל).
- **EmailFlow (`46d05f7`):** `parsed_json.get(...)` קרס כי `parsed_json` היה רשימה, לא dict.
- **EmailFlow (`55b4328`):** `parse_webhook` קיבל `messages: None` במקום רשימה.
- **EmailFlow (`e432866`):** `setTimeout(fn, delay)` עם NaN → React crash.
- **Shipment-bot (`97bf0bc`):** `AmountValidator` לא בדק NaN/Inf; `NaN < 0` הוא `False`, `NaN > max` הוא `False` → NaN נכנס לארנק כסכום.
- **Facebook-Leads-New (`fadc0dc`):** `\b` ב-Python triple-quoted string הוא backspace, לא word boundary → ה-regex לא רץ.
- **routine (`e5c26ad` / `2571c91`):** מפתחות VAPID פגומים / חסר prefix של `mailto:` → exception לא נתפס ב-`setVapidDetails` → השרת קורס בעלייה.
- **Markdown-Docs (P5):** `form-action` נבנה מ-`urlsplit(redirect_uri).netloc` — שכולל userinfo, שאינו `host-source` חוקי ב-CSP. דפדפן שפוסל את ההנחיה חוסם את הטופס בשקט. גם התיקון הראשון (לחתוך userinfo) נפל — IPv6 בסוגריים גם הוא מחוץ לדקדוק. הפתרון: אימות allowlist מול הדקדוק עצמו.

### כלל לזיהוי
לפני כל `.get()`, `.append()`, `.strip()`, `[key]`, או iteration על ערך חיצוני, חייב:
1. `isinstance(obj, dict)` אם מצפים ל-dict.
2. `isinstance(items, list)` אם מצפים לרשימה.
3. `isinstance(value, str)` לפני `.strip() / .lower() / .split()`.
4. למספרים: `isinstance(n, (int, float))` + `math.isfinite(n)` + בדיקת טווח.
5. ל-regex על טקסט חיצוני: raw strings (`r"..."`) ו-word boundaries; עדיף `json.JSONDecoder().raw_decode()` על regex ל-JSON משובץ.
6. לקריאות SDK: לתפוס את ה-base class של ה-SDK (`anthropic.APIError`, `googleapiclient.errors.HttpError`), לסדר את ה-`except` subclass-לפני-superclass.
7. לאתחול SDK בזמן startup (VAPID keys, env vars, OAuth secrets): לעטוף את האתחול ב-try/except + לוודא פורמט ב-boot.
8. להזרקת ערך חיצוני למחרוזת עם דקדוק ללא הפרדת נתונים/קוד (CSP, כותרות HTTP, שמות קבצים): שתי בדיקות, לא אחת. (א) תחביר — הערך ניתן לביטוי בדקדוק היעד, ב-`fullmatch` מול הדקדוק עצמו ולא בניקוי תווים אסורים (blocklist לעולם אינו שלם, וערך פגום בהנחיית מדיניות גרוע מערך חסר). (ב) סמנטיקה — הערך גם מורשה: מופיע ב-allowlist של origins/סכמות/ספריות מותרות. `evil.com` הוא host-source תקין תחבירית — רק הבדיקה השנייה עוצרת אותו. לא חל על SQL/shell — שם קיימת הפרדה אמיתית (parameterized queries, `shell=False`) וולידציה אינה תחליף לה.

9. לבדיקת **שייכות** על ערך חיצוני (`value in <frozenset>`): בדיקת טיפוס **לפני** בדיקת החברות. `in` על קבוצה או מילון מחשב `hash(value)`, וערך לא-hashable זורק `TypeError` במקום להחזיר `False` — כלומר הוולידציה קורסת לפני שהספיקה לומר מה לא תקין, והמשתמש מקבל 500 במקום 400. השורה נראית תמימה בדיוק מפני שהיא נראית כמו שאלה שמחזירה כן/לא.

### False positives
- מבני נתונים פנימיים שנוצרו על ידי הקוד שלנו (קלט FastAPI שעבר ולידציית Pydantic כבר נבדק ב-isinstance).
- נתיבי `logger.debug` שלא ירוצו בפרודקשן.
- `except` צר ב-propagation מכוון (למשל `AppException` שמגיע ל-FastAPI).

### מצב מומלץ
**warning** במשך שבועיים על קוד קיים, ואז **strict** לקוד חדש בגבולות מודולים.

### ראה גם
- `BY-STACK/external-sdk.md`
- `bugbot-rules/external-input-isinstance.md`
- `bugbot-rules/sdk-error-completeness.md`
- `bugbot-rules/blanket-policy-silent-block.md` §3–4 — זווית הדקדוק (P5)
- `docs/source-projects/markdown-docs-mcp-patterns.md` P5 — ההיגיון המלא, כולל למה לא חותכים userinfo

---

## U4. SQL / Postgres edge cases

**תדירות:** 3/3 מקורות, ~8 מופעים
**פרויקטים:** Noa_Leads, EmailFlow, Shipment-bot, Facebook-Leads-New, routine
**חומרה:** MEDIUM–HIGH

### איך זה נראה
סמנטיקה של Postgres / SQLAlchemy / SQL כללי מפתיעה את המפתח:
- `col = NULL` מחזיר `NULL`, לא `TRUE`.
- `VARCHAR(N)` קטן מדי לערך enum חדש → INSERT נכשל בפרודקשן, לא ב-SQLite של dev.
- עמודת `Integer` קטנה מדי ל-IDs ממערכות חיצוניות (Telegram, Stripe).
- `ORDER BY` על עמודה לא ייחודית = סדר לא מוגדר ב-ties → דפדוף מדלג/מכפיל.
- `LIKE` מתאים `_` ו-`%` כ-wildcards ב-prefix שהמשתמש סיפק.
- `postgresql_ops` ב-SQLAlchemy בשימוש שגוי ככיוון מיון.
- `ANY(:ids)` עם מערך מחרוזות על עמודת UUID נכשל בלי cast.

### דוגמאות אמיתיות
- **Noa (`cf99698`):** CAS `WHERE col = NULL` לא תופס NULL — צריך הסתעפות `IS NULL`.
- **Noa (`2c8263a`):** `VARCHAR(20)` קטן מדי לערך חדש של `StrEnum` → INSERT נכשל.
- **Noa (`98e8d18`):** `postgresql_ops={"col": "DESC"}` שגוי (זה למחלקות אופרטור); להשתמש ב-`desc("col")`.
- **Noa (`244286d`):** `ANY(:ids)` עם מערך מחרוזות על עמודת UUID נכשל בלי cast.
- **EmailFlow (`d84daca`):** `Lead.order_by(updated_at.desc())` בלבד — leads עם אותו timestamp קיבלו סדר אקראי → דפדוף בלולאה.
- **EmailFlow (`dfdf975`):** `.strip()` על Column expression לא רץ ב-SQL; היה צריך `func.trim(...)`.
- **Shipment-bot (`b16b99f`):** `entity_id` כ-`Integer`; IDs של Telegram חורגים מ-2³¹ → INSERT נכשל.
- **Shipment-bot (`c0c1b74`):** דפדוף audit log מוין רק לפי timestamp → שורות התערבבו בין דפים.
- **Facebook-Leads-New (`2f45eca`):** `LIKE 'test_key%'` תפס `testXkey` כי `_` הוא wildcard.

### כלל לזיהוי
1. ב-CAS / `UPDATE ... WHERE col = :val` כש-`col` nullable: הסתעפות `is None` → להשתמש ב-`col.is_(None)`.
2. כל עמודת `String(N)` / `VARCHAR(N)` שמתמלאת מ-enum: לאכוף `N >= max(len(v) for v in EnumClass)` (בדיקת CI או טסט).
3. IDs של Telegram / חיצוניים → `BigInteger` (`BIGINT`).
4. כל `ORDER BY` שאחריו `LIMIT`/`OFFSET` או cursor pagination חייב tiebreaker שני, בדרך כלל המפתח הראשי (`.id`).
5. כל `LIKE` עם prefix מהמשתמש חייב לברוח מ-`_` ו-`%`, או להשתמש ב-`=` מדויק.
6. פעולות מחרוזת של Python (`.strip()`, `.lower()`) על Column expressions → להשתמש ב-`func.trim()`, `func.lower()`.

### False positives
- אגרגציות (`GROUP BY` + `SUM`) — אין צורך ב-tiebreaker לדפדוף.
- `.first()` של שורה יחידה על עמודה ייחודית.
- עדכוני ORM דרך `session.merge` — לא raw SQL.

### מצב מומלץ
**strict** ל-nullability, escape של `LIKE`, ובדיקות גודל עמודות.
**warning** ל-tiebreaker חסר בדפדוף ב-queries לא מדפדפים.

### ראה גם
- `BY-STACK/postgres.md` — כיסוי מלא של SQL/Alembic/דפדוף
- `bugbot-rules/postgres-null-cas.md`, `pagination-tiebreaker.md`, `like-wildcard-injection.md`

---

## U5. עדכוני atomic חלקיים / סטייה ב-linked fields

**תדירות:** 3/3 מקורות, ~10 מופעים
**פרויקטים:** Noa_Leads, EmailFlow, Shipment-bot, routine, Web
**חומרה:** HIGH (שחיתות נתונים שקטה + צרכנים downstream תלויים ב-cascade)

### איך זה נראה
פעולה לוגית דורשת עדכון של N שדות מקושרים atomically. הקוד מעדכן `N-1` ושוכח את השאר. השדה ה"שכוח" נקרא מאוחר יותר על ידי cron, dashboard, או flow אחר → אי-עקביות שקטה.

### דוגמאות אמיתיות
- **Noa (`bd2b105`):** chip קבע `PROPOSAL_SENT` ועקף את ה-`ProposalSentConfirmModal` flow.
- **Noa (`75b430a`):** chip קבע `PROPOSAL_SENT` בלי לכתוב `proposal_sent_at` → `check_stuck_proposals` נשבר.
- **Noa (`df530f3`):** `apply_chip` עדכן status אבל שכח `last_outbound_at` + `last_activity_type`.
- **Noa (`4cc5a09`):** `apply_chip` לא סגר tasks ישנים ב-`AUTO_CLOSE_TASK_TYPES` + אין dedup.
- **Noa (`04cb101`):** `_apply_reschedule` עם `rowcount=0` השאיר booking בלי activity log → cron התייחס לזה כאילו לא קרה.
- **EmailFlow (`f847a44`):** Pub/Sub draft נוצר חיצונית לפני commit מקומי → orphans בכשל חלקי.
- **EmailFlow (`75c0a47`):** audit row נכתב לפני `client.send_draft()` — אם השליחה נכשלה, ה-compliance trail שיקר.
- **routine (`01c61ac`):** `handleMorningTimeChange` שלח רק `hour`, לא את ה-`enabled` flag; בקשות מקבילות דרסו זו את זו.
- **Web (`2e5c480`):** רק `token` עודכן ב-`localStorage`; `refreshToken` נשאר מההרשמה → reauth נשבר.

### כלל לזיהוי
לכל פונקציה שמעדכנת status / "phase" / lifecycle column של ישות, ודא שגם **רשימת השדות האחים הקנונית** מתעדכנת באותה טרנזקציה. דוגמאות ספציפיות לפרויקט:
- שינוי status → `last_outbound_at`, `last_activity_type`, `proposal_sent_at`, סגירת `AUTO_CLOSE_TASK_TYPES`, log activity, ביטול cache.
- קריאה חיצונית → או INSERT מקומי קודם עם `UNIQUE` *לפני* הקריאה, או כתיבת audit log עם `metadata.applied=false` בכשל.
- רענון token → גם `access` וגם `refresh` בכתיבה atomic אחת (`localStorage.setItem` הוא per-key; השתמש ב-JSON blob אחד או בשתי כתיבות בטרנזקציה).
- submit חלקי של טופס → שלח אובייקט מלא או השתמש ב-server-side merge עם field mask מפורש.

### False positives
- migrations / scripts של backfill (one-shot, לא touchpoints טרנזקציוניים).
- נתיבים read-only.
- עדכוני שדה יחיד שבאמת עצמאיים (למשל `last_viewed_at` לא קשור לכלום).

### מצב מומלץ
**strict** בתוך `apply_chip` / `mark_*_sent` / נקודות כניסה של state-machine.
**warning** במקומות אחרים.

### ראה גם
- `BY-STACK/state-machine.md` — checklist של שלמות touchpoint
- `BY-STACK/webhooks.md` — דפוס reserve-then-fill
- `bugbot-rules/linked-field-atomicity.md`

---

## U6. סטייה בין migration ל-schema

**תדירות:** 3/3 מקורות, ~6 מופעים
**פרויקטים:** Noa_Leads, EmailFlow, Shipment-bot, Markdown-Academy, routine
**חומרה:** MEDIUM (שובר deploys טריים; שורד ב-CI אם הטסטים משתמשים רק ב-DB ממוגרר)

### איך זה נראה
שינויי schema חיים בשני מקומות: migration של Alembic / Knex וגם `__table_args__` של מודל SQLAlchemy / ORM. שני המקומות נסחפים; DB טרי (test, dev, prod-from-scratch) מסתיים עם schema שונה מ-DB של פרודקשן אחרי migrations הדרגתיים.

### דוגמאות אמיתיות
- **Noa (`2c8263a`):** migration הוסיף ערך enum חדש אבל העמודה `VARCHAR(20)` קצרה מדי.
- **EmailFlow (`40f855d`):** FTS index רק ב-migration, לא ב-`__table_args__` של המודל → DB טרי בלי index.
- **EmailFlow (`a3a3134`):** revision id של Alembic ארוך יותר מ-`VARCHAR(32)` של `alembic_version.version_num` → migration נכשל ב-deploy טרי של Render.
- **EmailFlow (`f143e1c`):** migration עם `DROP COLUMN` אבל הקוד עדיין משתמש בה.
- **EmailFlow (`3f43d91`):** `CHECK` constraint ממוין שונה ב-migration לעומת המודל.
- **routine (`80c1fc4`):** migration השתמש ב-`ADD COLUMN IF NOT EXISTS` — לא נתמך ב-MySQL.
- **routine (`7a4e879`):** migration רץ `ALTER TABLE` על טבלה לא קיימת ב-deploy ראשון.
- **routine (`230e0c1`):** קובץ migration כפול + חסר SSL config.
- **Shipment-bot (`b16b99f`):** אי-התאמת טיפוס עמודה (`Integer` קטן מדי ל-Telegram IDs).

### כלל לזיהוי
1. כל `Index(...)`, `CheckConstraint(...)`, `UniqueConstraint(...)` ב-migration חייב להופיע זהה ב-`__table_args__` של המודל.
2. `DROP COLUMN` ב-PR שעוד יש בו הפניות לעמודה במקומות אחרים → דווח.
3. אורך revision id של Alembic ≤ 32.
4. פרויקטי MySQL: בלי `IF NOT EXISTS` ב-`ADD COLUMN` (syntax של PG בלבד); בלי `ADD COLUMN IF NOT EXISTS`.
5. עמודות `String(N)` / `VARCHAR(N)` שמתמלאות מ-enum → טסט CI שבודק `N >= max(len(value) for value in Enum)`.
6. migrations הם additive כשהקוד הישן עדיין משתמש בעמודה — שינוי הרסני בא ב-migration *נפרד* מאוחר יותר אחרי שהקוד הוסר.

### False positives
- migrations של data בלבד (backfill, fixup) — אין שינוי schema.
- test fixtures עם `extend_existing=True`.

### מצב מומלץ
**strict** להתאמה בין migration ל-model.
**warning** לאורך revision id ול-syntax של MySQL (CI תופס בכל מקרה).

### ראה גם
- `BY-STACK/postgres.md` — כיסוי מלא של migrations
- `bugbot-rules/migration-model-drift.md`
