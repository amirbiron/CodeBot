# דפוסי באגים חוזרים — Noa_Leads CRM

> **מקור:** ניתוח 47 קומיטי תיקון בין 2026-05-24 ל-2026-05-25 (bugbot/cursor reviews + bug fixes). חלקם מכילים מספר ממצאים — סה"כ ~70+ baseline bugs.
>
> **מטרה:** Custom rules ל-bugbot חדש (לא Cursor) שייתפס דפוסי באגים שחוזרים בפרויקט. כל rule כולל prompt מדויק + תרחישי false-positive ל-tuning.
>
> **מודל גזירה:** דירוג priority לפי תדירות × severity. P1 = חוזר 5+ פעמים *או* פעמיים עם severity High; P2 = 3-4 חזרות; P3 = 2 חזרות + medium/low.

---

## P1 — Pattern 1: Side-effects חסרים בשינוי סטטוס / state transition

**תדירות:** 8 קומיטים (~15% מכל ה-fixes).

**דוגמאות:**
- `bd2b105` — chip שמציב PROPOSAL_SENT עוקף את ProposalSentConfirmModal flow.
- `3312957` — chip target_status BOOKING_PENDING/BOOKED ללא Booking row → ליד "תקוע".
- `75b384a` (#1) — apply_chip לא חסם BOOKED + approved booking → Calendar event יתום.
- `75b430a` (#2) — chip מציב PROPOSAL_SENT לא כתב proposal_sent_at → check_stuck_proposals שובר.
- `694bc91` (#1) — chip מוציא מ-BOOKING_PENDING; ה-Booking נשאר pending_approval ונשכח.
- `244286d` (#2) — apply_chip מאבד BOOKING_PENDING context (אותו תרחיש).
- `1c4eb3a` (#2) — apply_chip booking guard רץ רק כשהסטטוס משתנה, לא תמיד.
- `df530f3` (#1) — apply_chip לא עדכן last_outbound_at + last_activity_type.

**סיבה שורשית:** בקוד הזה יש "סטטוסים מקושרים" — קביעה אחת של `lead.status`/Task/Booking דורסת מצב של פיצ'ר אחר. כל ערך target גורר חוזה (BOOKING_PENDING ⇒ Booking pending row; PROPOSAL_SENT ⇒ proposal_sent_at; WON/LOST ⇒ closure_reason). מי שכותב "פעולה חדשה" שמשנה סטטוס שוכח את הצד השני.

CLAUDE.md כלל 13 כבר מנסח את זה — אבל החזרה כל-כך מתמדת מצביעה שצריך אכיפה אוטומטית.

**Custom rule prompt:**
```
בכל שינוי של `Lead.status` (UPDATE / `.status =` / dict עם key 'status'),
חפש בקובץ הנוכחי או בפונקציה הקוראת:
1. אם target ∈ {PROPOSAL_SENT}: ודא ש-`proposal_sent_at` נכתב באותה
   transaction (COALESCE לשמירה על הראשון).
2. אם target ∈ {BOOKING_PENDING, BOOKED}: ודא שיש Booking row תואם
   *או* שהקוד דוחה את הפעולה במפורש (ValidationError) במקום להציב
   את הסטטוס ישירות.
3. אם target ∈ {WON, LOST, ARCHIVED}: ודא שהקוד עובר דרך close_lead
   (לא הצבה ישירה).
4. אם current ∈ {BOOKING_PENDING, BOOKED} ויש Booking active: ודא שיש
   טיפול cascade (REJECT/CANCEL/block) או הודעה למשתמש לטפל קודם.
5. אם הפעולה נחשבת "touchpoint" (chip, action, mark_sent): ודא שגם
   `last_outbound_at` ו-`last_activity_type` מתעדכנים באותה
   transaction.

דווח כל UPDATE שמשנה status בלי שאחד מהבדיקות הרלוונטיות נראית
בסקופ ה-AST של הפונקציה הקוראת.
```

**False positives:**
- ⚠️ פעולה שיוצרת ליד חדש (`Lead(status=...)`) — initial creation, לא טרנזישן. ה-rule יזהה ויאשים בטעות. סינון: רק UPDATE / setattr על instance קיים.
- ⚠️ migration scripts שעושים backfill — לא flow אמיתי. סינון: לא להריץ ב-`alembic/versions/`.
- ⚠️ ROLLBACK של פעולה (set status back) — אין side-effects לטפל בהם. סינון: לאפשר reversal דרך close_lead/reopen_lead.

**Mode מומלץ:** Warning (זיהוי תרחיש = שווה review, גם עם false positives). אל תפעיל strict — חוסם cleanups לגיטימיים.

---

## P1 — Pattern 2: Filter exclusion יוצר רשימה ריקה לתרחישים לגיטימיים

**תדירות:** 7 קומיטים.

**דוגמאות:**
- `f635304` (#1) — manual list מסונן ל-WA, ליד email-pref ראה ריק.
- `d526948` (#1+#5) — סינון channel+audience יחד חוסם תבניות לגיטימיות.
- `ad34858` — domain blacklist exact-match לא תפס subdomains (mail.mailchimp.com).
- `95dcce6` (#1) — regex `@([\w.-]+)$` לא תפס "Name <addr>" RFC 2822.
- `c608a85` — cron retry filter על `lead_id IS NULL` תפס גם spam/not_business → loop.
- `2b978aa` — cron filter על `count < MAX` החריג רשומות שתקועות ב-count==MAX.
- `76b20b3` (#1) — סדר ההמרה גרם ל-`split('\n')` להחזיר list של 1 → filter dead.

**סיבה שורשית:** Filter (DB / regex / array) שנכתב לתרחיש אחד ומתעלם מ-variants לגיטימיים. הסכנה הקריטית: בעיני המתכנת ה-filter מצמצם, אבל לעיתים הוא **חוסם המשך flow** (cron loop, empty UI, מיילים חסרים).

**Custom rule prompt:**
```
לכל filter על אוסף (rows בDB, items בlist, regex match), שאל את 3 השאלות:

1. **completeness**: האם הסינון מבטיח כיסוי לכל ערכי הקלט הצפויים? למשל:
   - WHERE channel = 'whatsapp' → מה קורה אם המקור email-pref?
   - regex `@(...)$` → מה אם הקלט כולל `>` בסוף (RFC 2822 display name)?
   - WHERE col IS NULL → מה אם הסטטוס terminal (spam/not_business) שגם משאיר NULL?

2. **terminal states**: לכל cron filter, ודא שתנאי "סופי" (לא צריך
   עיבוד נוסף) נכלל בfilter. הסטנדרט: עמודת processing_status / done /
   archived מפורשת, לא הסתמכות על "lead_id IS NULL".

3. **subdomain / wildcard**: לכל blacklist domain string, ודא שמטופלים
   גם subdomains (`endswith("." + root)`) ולא רק exact match.

דווח filter / regex / WHERE / .filter() / .find() שמחזיר 0 rows
ב-edge case לגיטימי שלא נחסם במפורש בתיעוד.
```

**False positives:**
- ⚠️ Filter מכוון לצמצום (e.g. owner-scoped, role-scoped) — שם הצמצום הוא הפיצ'ר. סינון: דרוש שה-filter יהיה על שדה enum/string ולא על FK.
- ⚠️ Filter על ערכים פנימיים (debug, admin) — לא רלוונטי לרגרסיה.

**Mode מומלץ:** Warning עם דרישת justification בקומנט. הכלל בוסר false-positive אבל זיהוי "filter שצמצם מדי" שווה לבדוק.

---

## P1 — Pattern 3: Race conditions ב-async/concurrent flows

**תדירות:** 7 קומיטים.

**דוגמאות:**
- `33af59e` — שני webhooks מקבילים קוראים אותו sync_token, מחילים אותם deltas, activities כפולים. תיקון: optimistic locking + CAS.
- `04cb101` — _apply_reschedule rowcount=0 השאיר booking בלי activity → cron יצר task לפני שהפגישה קרתה.
- `cf99698` — CAS על `history_id = expected_old` לא תופס NULL ב-Postgres → cursor תקוע לעד.
- `b360c66` — async `await renderTemplate` בלי בדיקת `cancelled` flag → preview ישן דרס UI חדש.
- `3fc0ec6` — useEffect עם dep על object רענן ודרס edits של משתמש.
- `0aff4a1` (#1) — webhook החזיר מוקדם ב-changes ריק; ה-sync_token החדש לא נשמר → loop אינסופי.
- `7444dd9` (#1) — Promise.all timing סבוך, setLoading נסגר לפני שhe-render מוכן.

**סיבה שורשית:** כל פיצ'ר עם webhooks / multi-tenant / cron / async-rendering דורש תכנון אטומיות. בקוד הזה ספציפית — Pub/Sub Push יכול להגיע במקביל; Google Calendar שולח עדכונים בקצב; cron jobs ב-Render אינם locked. CLAUDE.md כללים 2+8 נוסחו בדיוק על זה אבל החזרה מצביעה שהכלל "תרחישי race קודם" לא נאכף בכל פיצ'ר.

**Custom rule prompt:**
```
לכל פיצ'ר חדש או שינוי קיים שכולל אחד מאלה — חפש סימנים שתרחישי race
נשקלו במפורש:

* webhook handler (POST /webhooks/...)
* cron job (`backend/jobs/*.py`)
* read-then-write דרך SQLAlchemy (SELECT ואז UPDATE)
* setState בתוך async function ב-React component
* useEffect cleanup שצריך לבטל in-flight requests

לכל מקרה כזה, חייב להופיע אחד מאלה:
1. **Optimistic lock / CAS**: UPDATE עם WHERE על ערך ישן (`WHERE col = expected_old`).
   ⚠️ ודא שגם NULL מטופל (`IS NULL` כשהערך הצפוי הוא None).
2. **`cancelled` flag** (React) — useEffect מחזיר cleanup שמסמן ביטול;
   כל setState מותנה ב-`if (!cancelled)`.
3. **idempotency key** — INSERT עם ON CONFLICT (UNIQUE constraint).
4. **`SELECT FOR UPDATE`** (Postgres row lock) — רק במקרים שלא ניתן
   אחרת.

אם אין סימן לאחד מאלה, דווח על "race not addressed" עם הצעת התיקון.

בנוסף: לכל cancel-flag pattern, ודא שכל `setState` *אחרי* `await`
מותנה בבדיקה. await באמצע = window לטעות.
```

**False positives:**
- ⚠️ Single-tenant SQLite dev environment — race תיאורטי. סינון: רק ב-routes שמסומנים כפרודקשן (webhooks, cron).
- ⚠️ `useEffect` עם deps פרימיטיביים — לא צריך cancel. סינון: לדרוש cancel רק כשיש await בפונקציה.

**Mode מומלץ:** Strict ל-webhooks/cron, Warning ל-React effects.

---

## P1 — Pattern 4: Schema default דורס intent של ה-caller

**תדירות:** 5 קומיטים.

**דוגמאות:**
- `3203410` (#1) — `LeadCreate.preferred_contact` ברירת מחדל WHATSAPP, ליד מ-EMAIL נשמר עם WHATSAPP. הקוד לא העביר במפורש → default נכנס בלי קריאה ידנית.
- `7001892` — `LeadDraft.service_category: ServiceCategory` (StrEnum) דחה כל ערך לא ידוע → איבוד full_name + phone על שדה אחד.
- `f6293e3` — `LeadDraft.full_name: str` חובה דחה null שה-AI החזיר → cron retry → manual_review מיותר.
- `dc24922` (#1) — `TodayActionItem.service_category: str` חובה, אבל ה-Lead nullable → Pydantic validation נופל ב-/dashboard.
- `236b072` (#1) — walrus `if override := env.get(...)` היה False על `""` ולא רק None.

**סיבה שורשית:** Pydantic schemas הם חוזים נוקשים, אבל ה-callers מתייחסים אליהם כ-"data class" עם defaults הגיוניים. כשה-default לא תואם לכוונה (preferred_contact=WHATSAPP לליד EMAIL), הבאג שקט — אין הודעת שגיאה.

הצורה הקנונית של הבאג: caller A חושב "השדה אופציונלי", caller B חושב "אם לא ציינתי = default", ה-schema גובה את default. אם A הוא flow ספציפי (email intake) ו-default הוא של flow אחר (WhatsApp UI), חוזר חוסר התאמה.

**Custom rule prompt:**
```
לכל BaseModel/Pydantic schema:

1. שדה עם default value (`= "X"` או `= Field(default=...)`) שמיוצג
   באנגלית טכנית (enum, str, bool):
   חפש את כל ה-callers שמייצרים instance בלי השדה הזה. דווח:
   "Caller X לא מציין `field`; ה-default `Y` יחול. ודא שזו ההתנהגות
   הצפויה לערוץ/source של ה-caller (e.g. flow מ-email לא רוצה
   default של WhatsApp)."

2. שדה enum (StrEnum / Literal): אם הוא nullable במודל הDB אבל
   non-nullable בסכמת Read/Update, הסכמות יקרסו על rows קיימים.
   דווח אי-עקביות בין nullability של DB column ל-Pydantic.

3. שדה enum שמקבל ערך מ-external source (AI response, webhook,
   user input): שקול אם דחיית ערך לא צפוי = איבוד כל ה-data
   הסובבת. אם כן — דווח "השדה צריך להיות `str | None` עם
   validation idempotent ב-caller, לא enum נוקשה".

4. Walrus / truthy on env vars: `if x := env.get(...)` מתעלם מ-
   `""` שהוא falsy אבל not-None. דווח: "השתמש ב-
   `if x is not None and x.strip():` להבחנה מפורשת".
```

**False positives:**
- ⚠️ Defaults פנימיים שלא נחשפים ל-callers חיצוניים (private util classes) — סינון: רק על schemas שמיוצאים מ-`app/schemas/`.
- ⚠️ Defaults שתעדפתם בכוונה אחרת (e.g. priority_level=NORMAL זה default סביר לכל source). ה-rule יעלה אבל המתכנת יכול לסגור עם justification.

**Mode מומלץ:** Warning. Strict ייצור הרבה רעש על defaults שהם פשוט "תמיד הגיוניים" (created_at, is_active).

---

## P2 — Pattern 5: Cron lacks terminal state → infinite loop

**תדירות:** 4 קומיטים, כל אחד severity Medium+.

**דוגמאות:**
- `c608a85` — cron retry סרק `lead_id IS NULL`; tagger 'spam' ו-'not_business' השאירו NULL לעד → לולאה.
- `2b978aa` — cron filter `count < MAX` לא תפס רשומות תקועות ב-count==MAX אחרי manual_review_lead failure → row stuck pending לנצח.
- `1c4eb3a` (#1) — check_warm_followups לא בדק "task created after last_outbound" → loop כל שעה אחרי שhe-task הקודם הושלם.
- `8bfa977` (#1) — detect_dormant לא דילג על לידים עם FIRST_RESPONSE/RETRY_CALL פתוחים → 2 reminders בכפילות.

**סיבה שורשית:** cron בלי "exit condition" מפורש. כלומר: על מה Filter ה-cron מסתמך כדי לדעת ש-row "מטופל"? ב-Noa_Leads, התשובות העדיפות הן `processing_status` column ייעודי או `created_at > last_outbound_at` (touchpoint freshness).

הזיהוי הוא ב-pattern: cron query → לוקח batch → מבצע פעולה. אם הפעולה לא יוצרת mark שמוציא את ה-row מה-query הבא, ה-row יחזור.

**Custom rule prompt:**
```
לכל קובץ ב-`jobs/` (כל קרון):

1. זהה את ה-query הראשי: `select(Model).where(...)`.
2. עבור על תנאי ה-WHERE. שאל: "אם ה-cron הריץ ופעולה הצליחה, איזה תנאי
   הופך ל-False כתוצאה?"
   * אם התשובה היא "ערך X נכתב לעמודה" → ודא שהפעולה אכן כותבת אותו.
   * אם התשובה היא "lead_id יתעדכן" אבל ה-cron גם תופס terminal rows
     (spam/not_business שאין להם lead) → דווח: "ה-filter תופס גם
     terminal states שלא ייעלמו לעולם — נדרשת עמודת status ייעודית".
3. אם ה-cron יכול לעבד את אותו row 2+ פעמים, ודא שיש ספירת attempts
   עם MAX או "exhausted" flag. ודא שכשמגיעים ל-MAX, המסלול לא
   נשאר בכוונה ב-pending (כלומר: או terminal state, או הצמדה למצב
   recovery ייעודי).

כלל אצבע: כל cron query חייב לכלול filter על `processing_status` /
`done_at` / `mark_<role>` שמופיע ב-DB אחרי הצלחה. lead_id IS NULL,
count < MAX, status IN (...) — אלה signals חלקיים שעלולים לחזור על
state טרמינלי.
```

**False positives:**
- ⚠️ cron של pure reporting (יוצא log, אין שינוי DB) — לא בעיה לחזור. סינון: רק על crons שעושים INSERT/UPDATE.

**Mode מומלץ:** Strict. cron loops גורמים ל-API spam ועלות AI.

---

## P2 — Pattern 6: Touchpoint לא comprehensive (חסר field/auto-close/cache)

**תדירות:** 4 קומיטים, רובם Medium.

**דוגמאות:**
- `df530f3` (#1) — apply_chip שכח last_outbound_at + last_activity_type.
- `4cc5a09` — apply_chip לא סגר tasks ישנים מ-AUTO_CLOSE_TASK_TYPES + לא de-dup.
- `c99a47a` — LECTURE_INQUIRY חסר מהרשימה הקנונית של AUTO_CLOSE.
- `3312957` (#2) — chip task ללא assigned_to → לא מופיע ב-owner-scoped views.

**סיבה שורשית:** "touchpoint" (כל פעולת outbound של נועה: chip, action, mark_sent) מצריך עדכון ~6 שדות באטומיות:
1. `lead.last_outbound_at`
2. `lead.last_activity_type`
3. סגירת tasks מ-AUTO_CLOSE_TASK_TYPES
4. יצירת task חדש עם `assigned_to=lead.owner_id`
5. activity record
6. cache invalidation (next_action_due_at)

מי שמוסיף flow חדש מתעלם מ-1-2 פריטים → באג שקט.

CLAUDE.md כללים 12+14 כתובים על זה במפורש. החזרה כל-כך מתמדת מצביעה שהכלל הכתוב לא מספיק — צריך בדיקה אוטומטית.

**Custom rule prompt:**
```
פונקציה מסומנת כ"touchpoint" אם היא עונה על אחד מאלה:
- name מכיל `apply_chip`, `mark_*_sent`, `perform_action`
- היא יוצרת activity מסוג TEMPLATE_MARKED_SENT / PROPOSAL_SENT / CHIP_APPLIED
- היא קוראת ל-`_close_addressed_tasks` או דומה

לכל touchpoint, ודא שהיא עושה את כל 6 הצעדים בtransaction אחד:

1. `lead.last_outbound_at = now()` (UTC)
2. `lead.last_activity_type = ActivityType.<X>.value`
3. סגירת כל פתוח/snoozed task ב-AUTO_CLOSE_TASK_TYPES (DONE)
4. אם נוצר task חדש: `assigned_to = lead.owner_id`, `due_at` ב-UTC
   (`.astimezone(timezone.utc)`)
5. log_activity עם activity_type, performed_by, content
6. `sync_lead_next_action_cache(db, lead_id)` אחרי flush ולפני commit

חיפוש בקובץ peer (apply_chip / lead_actions.perform_action):
- האם כל ה-6 השלבים נראים? אם חסר אחד → דווח עם השוואה ל-peer.

בנוסף: לכל `Task(...)` creation, ודא 5 השדות הבסיסיים:
- `assigned_to` (לרוב lead.owner_id)
- `due_at` ב-UTC
- `origin_rule` ייחודי וברור
- type מ-enum (לא string hardcoded)
- ודא ש-`sync_lead_next_action_cache` נקרא אחרי
```

**False positives:**
- ⚠️ פעולה פנימית בלבד (e.g. webhook sync — לא touchpoint של נועה) — סינון לפי name pattern.
- ⚠️ Task שנוצר ע"י cron אוטומטי (FIRST_RESPONSE, WARM_FOLLOWUP) — אין `owner_id` חיצוני, לא בא מהמשתמש. סינון: רק על calls מ-route handlers.

**Mode מומלץ:** Warning. בדיקות אלה הן contextual; strict mode יציף false positives.

---

## P2 — Pattern 7: AI / external SDK — error type completeness

**תדירות:** 4 קומיטים.

**דוגמאות:**
- `c128115` — `_complete` תפס רק RateLimitError + _RETRYABLE; AnthropicAPIError אחרים (NotFound, BadRequest, Auth) propagating uncaught → caller שמצפה ל-AIError בלבד נשבר.
- `95dcce6` (#3) — fallback path בלע RateLimitError כ-AIError גנרי → caller לא ידע לסמן pending_classification.
- `f27adc1` — regex `\{.*\}` greedy על JSON response של AI; trailing `}` שבר parse.
- `95b82e5` — OAuth scope-drift: `oauthlib` מטפל ב-drift כ-security warning ומכשיל. צריך `OAUTHLIB_RELAX_TOKEN_SCOPE=1`.

**סיבה שורשית:** SDKs של ספריות חיצוניות (anthropic, oauthlib, google-auth) מטילים שגיאות במגוון רחב; הקוד תופס תת-קבוצה והשאר propagating. caller שמסמן את החוזה "רק AIError" נקרע על שגיאות אחרות.

**Custom rule prompt:**
```
לכל קריאה ל-SDK חיצוני (anthropic, google.*, oauthlib, requests, googleapiclient):

1. ודא שיש wrapper שמוגדר את ה-error contract של ה-caller (e.g.
   "רק AIError + AIRateLimitError"). חפש את ה-class הבסיס של ה-SDK
   (e.g. anthropic.APIError) ודרוש except על ה-base class כsafety
   net אחרון.

2. סדר ה-`except`-ים חשוב: subclass לפני superclass.
   - RateLimitError לפני APIError.
   - הוסף תיעוד כשהסדר משמעותי (e.g. "InternalServerError יורש מ-
     APIError; חייב לעבור דרך _RETRYABLE קודם").

3. אזהרות SDK שמכשילות בtoken exchange (oauthlib's Warning class):
   חפש env vars או config flags המקובלים של ה-SDK (OAUTHLIB_RELAX_TOKEN_SCOPE
   וכו'). הוסף הערה למקור (link ל-docs).

4. JSON / regex על תשובות AI:
   `json.JSONDecoder().raw_decode()` עם `find("{")` — לא regex.
   רגקסים על JSON שבירים על trailing prose, nested objects, או escape
   sequences.
```

**False positives:**
- ⚠️ קוד שמטרת ה-narrow except היא לאפשר propagation כוונה (e.g. AppException שצריך להגיע ל-FastAPI handler). סינון: ה-rule רץ רק כשיש wrapper class או raise בקטע ה-catch.

**Mode מומלץ:** Warning. error contracts הם hard to define automatically.

---

## P2 — Pattern 8: SQL nullability + Postgres-specific edge cases

**תדירות:** 5 קומיטים.

**דוגמאות:**
- `cf99698` — `WHERE col = NULL` לא תופס NULL. צריך `IS NULL` ב-CAS.
- `2c8263a` — VARCHAR(20) קטן מערך enum חדש → INSERT failure.
- `98e8d18` — `postgresql_ops` (לoperator classes) misused כdef של DESC sort.
- `244286d` — `ANY(:ids)` עם array של strings על UUID column נכשל ללא cast.
- `7444dd9` (#3) — `if "  " ` truthy ב-Python אבל לא ב-edit flow → drift.

**סיבה שורשית:** Postgres ו-SQLAlchemy יש להם semantics לא-אינטואיטיביים: NULL = NULL מחזיר NULL (לא TRUE), implicit casting on `WHERE col = value` שונה מ-`ANY(array)`, postgresql-specific keyword params (`postgresql_ops`, `postgresql_where`).

**Custom rule prompt:**
````
1. CAS UPDATE / DELETE עם value שיכול להיות None:
   `WHERE col = :val` לא תופס NULL. ודא שיש branch מפורש:
   ```python
   if expected_old is None:
       where_clause = Model.col.is_(None)
   else:
       where_clause = Model.col == expected_old
```
   דווח על UPDATE/DELETE עם WHERE על עמודה nullable, בלי הבדלה.

2. בדיקת truthy על שדה string מ-DB:
   `if value:` truthy גם על "  " (whitespace). אם ה-edit flow מנרמל
   ל-NULL, יש drift. דווח: "הוסף `.strip()` או השווה ל-NULL מפורש".

3. VARCHAR(N) מול StrEnum values:
   חפש קומבינציות של `String(length=N)` עם enum שיש בו value ארוך
   מ-N. דווח גם על column attribute וגם על אורך הערכים בenum.

4. PostgreSQL ANY/ALL with cast:
   `WHERE id = ANY(:uuid_array)` נכשל אם המערך הוא strings ו-column
   הוא UUID. ה-pattern הבטוח: `WHERE id::text = ANY(:str_array)`.
   דווח על ANY/ALL ללא cast מפורש כשה-column הוא UUID.

5. Index definitions:
   - `postgresql_ops={"col": "DESC"}` היא טעות (operator classes,
     לא sort). השתמש ב-`desc("col")` מ-sqlalchemy.
   - לכל partial index ב-migration, ודא שגם `__table_args__` ב-
     model מכיל אותו (אחרת alembic autogenerate ימחק אותו).
````

**False positives:**
- ⚠️ ORM updates דרך session.merge() / session.flush() — לא raw SQL, ה-rule לא רלוונטי.
- ⚠️ migrations שלא משנים schema, רק data backfill — לא בעיה.

**Mode מומלץ:** Strict. ה-bugs האלה חוזרים על עצמם כי הם counterintuitive.

---

## P3 — Pattern 9: Activity log = source of truth (גם בכשל UPDATE)

**תדירות:** 3 קומיטים.

**דוגמאות:**
- `04cb101` — _apply_reschedule rowcount=0 לא רשם activity → cron עיבד את הפגישה כאילו לא נדחתה.
- `0aff4a1` (#1) — webhook החזיר ב-changes ריק בלי persist token → loop.
- `0aff4a1` (#2) — `last_activity_type` בעמודה לא תאם ל-activity log type (meeting_rejected vs MEETING_CANCELED).

**סיבה שורשית:** ה-activity log הוא ה-record של *intent* (מה ש-Google אמר, מה שהמשתמש ביקש), לא רק של *outcome* (מה ש-DB שמר). cron jobs / dashboards / מיון תלויים בו. אם UPDATE על השורה הראשית נכשל (race, rowcount=0), חייב לרשום activity עם `metadata.applied=false` כדי שתהליכים downstream ידעו שהאירוע קרה גם אם לא הוחל.

CLAUDE.md כלל 9 כתוב על זה.

**Custom rule prompt:**
```
פונקציה שמטפלת ב-webhook event / sync action / external trigger:

1. אם יש UPDATE / INSERT עם `rowcount` שיכול להיות 0 (race, CAS,
   filter דוחה), חפש אחריו `log_activity(...)`.
   * אם ה-log רק במסלול הsuccess (else branch בלי log) — דווח:
     "rowcount=0 מצריך activity log עם metadata.applied=false. אחרת
     ה-event יאבד signal ל-cron/dashboard".

2. webhook handler שיוצא מוקדם (changes==[] / status==304) חייב
   לעדכן את ה-cursor (sync_token / history_id) גם בתוצאה ריקה.
   אם Google/Gmail נתן next_token חדש, חוסר persist = loop.

3. עמודות "last_X" על entity:
   - last_activity_type חייב להיות ערך מ-ActivityType enum (תוצאת
     `.value`), זהה ל-type של ה-activity שנכתב לטבלת activities.
   - אם רושמים activity עם `MEETING_CANCELED`, ה-`last_activity_type`
     בעמודה חייב להיות `meeting_canceled` (לא `meeting_rejected`).
   דווח אי-עקביות בין activity type ב-log ל-value בעמודה.
```

**False positives:**
- ⚠️ Read-only handlers (לא משנים DB) — לא רלוונטי.

**Mode מומלץ:** Warning. ה-rule דורש הבנת flow; strict ייצור רעש.

---

## P3 — Pattern 10: Browser API quirks / external protocol handoff

**תדירות:** 2 קומיטים, אבל מסוכנים (UX critical).

**דוגמאות:**
- `f635304` (#2) — `window.open("mailto:...")` מחזיר null בChrome — לא popup blocker, אלא handoff ל-system protocol. popup guard ביטל את mark_sent בטעות.
- `f4769bf` — BOOKED button היה מופיע אחרי `slot_start + 30 min` במקום `slot_end`; פגישות קצרות נשברו.

**Custom rule prompt:**
```
1. `window.open(url, ...)`:
   - אם ה-URL הוא `mailto:`, `tel:`, `sms:`, `file:` — `window.open`
     מחזיר null בדפדפנים רבים. אסור להשתמש ב-`!win` כסימן לpopup
     blocker. השתמש ב-anchor element + `.click()` להpotocols של
     המערכת.
   - אם ה-URL הוא `http(s)://` בלבד — popup guard מותר.
   דווח על `window.open` עם URL שיכול להיות protocol handler ועם
   `if (!win)` שמבטל פעולה.

2. setTimeout / setInterval בעבודה עם זמני event (slot_start, slot_end):
   - השתמש בערך הסופי האמיתי, לא בקירוב (`+30min`).
   - אם הפעולה מבוססת על "אחרי שהאירוע נגמר", חישוב מ-`slot_end`.
   - בנגיעה ב-state אחרי `await`, ודא שה-component עוד mounted (cancel flag).
```

**False positives:**
- ⚠️ הקוד שעטר במפורש את ה-handoff כ-best-effort (e.g. console.log+continue) — לא בעיה.

**Mode מומלץ:** Warning.

---

## P3 — Pattern 11: שדה ב-schema/payload לא מגיע לכתיבה הסופית

**תדירות:** 3 קומיטים, severity Medium (איבוד נתונים שקט, feature appears complete).

**דוגמאות:**
- `TBD-gmail-intake` — Gmail intake מילא `lead_message` בסיכום AI במקום ב-raw של הלקוח. ה-schema קיבל את השדה, ה-route העביר אותו, אבל ה-mapping בכתיבה הקצה לעמודה את ה-source הלא נכון (סיכום במקום הטקסט הגולמי).
- `TBD-is-returning-customer` — `is_returning_customer` הוגדר ב-`LeadCreate`, נשלח מ-`NewLeadModal` ב-UI, אבל פונקציית יצירת ה-Lead לא מיפתה אותו ל-`Lead(is_returning_customer=...)` → תמיד נשמר `False` (ה-DB default).
- `TBD-followup-interval` — שדה של מרווח followup (`followup_interval_days` / equivalent) עבר את ה-schema ואת ה-UI, אבל פונקציית בניית ה-Lead / Rule לא העבירה אותו ל-row → תמיד נשמר ערך ברירת המחדל. המשתמש בחר interval אחד, המערכת המשיכה לפי ה-default.

**סיבה שורשית:** schema-to-write drift. שכבות ה-input (Pydantic + frontend) מתעדכנות עם שדה חדש, אבל שכבת ה-CRUD ש**בונה את ה-row** לא מתעדכנת יחד. אין שגיאת validation (השדה התקבל), אין שגיאת DB (default קיים בעמודה או nullable) → ה-feature נראה שלם אבל ה-DB שומר default בשקט.

זה **לא** Pattern 4 (schema default דורס intent): שם ה-caller לא שלח את השדה. כאן השדה **כן נשלח** ועבר את כל הסכמה — רק הכתיבה שכחה אותו. זה גם **לא** linked-field atomicity: לא מדובר בקבוצת שדות מקושרים, אלא בשדה בודד שנשמט בנקודת הסיום.

CLAUDE.md הקיים לא מכסה את זה במפורש — אכיפה דורשת CI grep / bugbot rule.

**Custom rule prompt:** ראה `bugbot-rules/input-field-not-persisted.md` ל-detection signature מלא (5 קריטריונים) + 4 false positives.

עיקרון לזיהוי מהיר:
```
לכל BaseModel ב-schemas/ ששמו מסתיים ב-Create / Update:
  1. אסוף `model_fields` של הסכמה.
  2. אתר את ה-CRUD function שמקבל את הסכמה כפרמטר.
  3. חשב set difference: schema fields - assigned columns ב-Model(...).
  4. אם ההפרש כולל שדה non-Optional ולא-derived — דווח.
  
בנוסף: בכל diff שמוסיף שדה ל-*Create schema, ודא שיש שינוי תואם
ב-CRUD layer (`crud_*.py` או `services/*.py`) באותו PR.

Wrong-source mapping (וריאציה 2): חפש Model(...)/dict assignments
שמקבלים ערך משדה payload בעל שם דומה אבל סמנטיקה שונה
(summary במקום raw, classification במקום input).
```

**False positives:**
- ⚠️ שדות **derived** שנגזרים מ-fields אחרים בקוד (לא מגיעים מ-payload). סינון: רק שדות שמופיעים גם ב-schema וגם ב-frontend payload.
- ⚠️ Audit columns שמתמלאים אוטומטית (`created_at`, `updated_at`, `created_by_id`).
- ⚠️ PATCH endpoints שכותבים subset מכוון של שדות (לא יוצרים entity חדש).

**Mode מומלץ:** Warning. CI grep חוקי, אבל false positives על שדות derived / audit שכיחים מספיק כדי שלא להפוך ל-strict.

---

## P3 — Pattern 12: React state stale על prop / localStorage key (resync חסר)

**תדירות:** 2 קומיטים, severity Medium-High (UI מציג ערך ישן; submit שולח נתונים שגויים חזרה לשרת).

**דוגמאות:**
- `TBD-followup-rules` — `FollowupRulesSection` מאתחל state מקומי מ-prop, אבל ה-prop משתנה אחרי save (parent refetch מהשרת). state המקומי לא מסונכרן → ה-UI ממשיך להציג את הערכים הישנים שהמשתמש שלח. הפתרון הקנוני: `useEffect([prop], () => setState(prop))` או `key={...}` ב-parent (force remount).
- `TBD-use-local-storage` — `useLocalStorage` hook לא מאפס את ה-state כש-ה-key prop משתנה ואין ערך שמור ב-localStorage. רכיב שעובר בין identifiers (לדוגמה lead-ל-lead, או tab-ל-tab) ממשיך להציג את ה-state של הקודם. סינכרון חסר ב-effect שמאזין ל-key change ומפיל ל-`defaultValue` במקרה של miss.

**סיבה שורשית:** הדפוס הקלאסי של React — `useState(props.X)` או `useState(() => readFromLS(key))` מאתחל פעם אחת ב-mount, אבל ה-prop יכול להשתנות. ללא `key={X}` ב-parent או `useEffect([X], () => setState(...))`, ה-state המקומי "תקוע" על הערך הראשון. ב-`useLocalStorage` הסיכון מוגבר כי ה-key משמש כמזהה זהות של ה-state — מעבר בין entities מצריך reset ל-default אם אין ערך שמור.

**Custom rule prompt:** ראה `bugbot-rules/react-stale-state-on-prop.md` ו-CORE U2 (`claude-md-snippets/universal.md` סעיף 2, `BY-STACK/react-frontend.md` דפוס 1). הכלל הקיים מכסה את שני המקרים — אין צורך ב-rule חדש.

**False positives:**
- ⚠️ state מקומי טהור (modal פתוח/סגור, theme toggle) — לא צריך resync.
- ⚠️ props שלא משתנים אחרי mount (`user.id` קבוע).
- ⚠️ uncontrolled inputs עם `defaultValue`.

**Mode מומלץ:** Warning. strict ייצור רעש על כל `useState(props.X)` בכוונה לא מסונכרן.

**Cross-tier:** הדפוס כבר ב-`CORE-PATTERNS.md` U2 (3/3 מקורות: EmailFlow + Web + עכשיו Noa מאושר במפורש). שני המופעים החדשים מחזקים את בסיס הראיות; commits נוספו גם ל-`BY-STACK/react-frontend.md` דפוס 1.

---

## P3 — Pattern 13: דליפת לידים סגורים / terminal-state לרשימות אקטיביות

**תדירות:** 2 קומיטים, severity Medium-High (UI מציג לידים סגורים כאקטיביים; race יוצר notifications/tasks ללידים שכבר נסגרו).

**דוגמאות:**
- `TBD-archive-truthy` — `if closed:` (Python truthy) במקום `if closed is True` באחת מ-archive queries. העמודה nullable: `None` (לא נקבע), `False`, או `True`. truthy תפס רק `True`, ו-`None` נחשב "לא סגור" כך שלידים שעדיין לא קיבלו ערך מפורש (drift היסטורי) הופיעו כאקטיביים בטעות. שווה ערך: filter שהיה צריך להיות מפורש (`closed is True` או `is_active = True`) נשבר על Python truthy semantics.
- `TBD-needs-attention-race` — `needs_attention` cron בדק לידים שהיו פתוחים בזמן ה-`SELECT`, ויצר task. במקביל, פעולה אחרת סגרה את הליד. ה-cron כתב את ה-task **אחרי** הסגירה (race) → task נוצר על ליד שכבר סגור → notification פייק למשתמש. אין CAS על `status` בכתיבת ה-task / אין `SELECT FOR UPDATE` על הליד.

**סיבה שורשית:** שני sub-mechanisms ל-leak אחד:
1. **Filter truthy על nullable boolean** — Python `if x:` לא מבחין בין `False` ל-`None`. כש-העמודה nullable, החלק של `None` יכול ליפול בצד הלא צפוי של ה-filter. דרוש `is True` / `is None` מפורש.
2. **Race נגד terminal transition** — בין `SELECT` ל-`UPDATE`/`INSERT`, terminal status יכול להשתנות. בלי CAS (`WHERE status NOT IN (CLOSED, ARCHIVED, WON, LOST)`) או `SELECT FOR UPDATE`, ה-writer דוחס ערך שגוי על ליד שכבר סגור.

**Custom rule prompts:**
- ל-truthy: ראה `bugbot-rules/filter-too-narrow.md` (קריטריון #6 — truthy על nullable boolean — נוסף יחד עם הדפוס הזה).
- ל-race: ראה `bugbot-rules/race-toctou.md` (קריטריונים 1+4 — CAS על terminal state, או `SELECT FOR UPDATE`).

**False positives:**
- ⚠️ עמודות boolean **non-nullable** עם default מוגדר — truthy בסדר כי ה-domain רק `True`/`False`.
- ⚠️ Cron שכותב לטבלת audit-only שלא משפיעה על UI — race פחות חמור.

**Mode מומלץ:** Strict לכל cron / handler שכותב על entity עם terminal states (`closed`, `archived`, `won`, `lost`). Warning ל-UI filters.

**הערה:** הדפוס הזה לא הצריך rule חדש — שני המנגנונים מכוסים על ידי כלל קיים שהורחב (`filter-too-narrow`) וכלל קיים שלא דרש שינוי (`race-toctou`). הרישום ב-source doc חיוני כי הצירוף "closed leads leak" יחזור על עצמו ב-Noa_Leads גם בעתיד וכדאי שייקרא מ-Pattern 13.

---

## P3 — Pattern 14: React + משאב async חיצוני (mic / camera / socket) — guard + cleanup חסרים

**תדירות:** 1 קומיט עם 3 sub-bugs, severity Medium-High (דליפת hardware, פעולות במקביל, state corruption).

**דוגמאות:**
- `TBD-voice-recorder-button` — `VoiceRecorderButton` הציג שלוש בעיות בקומפוננטה אחת:
  1. **לחיצה כפולה יצרה הקלטות מקבילות.** אין guard של "in-flight" — לחיצה שנייה לפני שהראשונה התייצבה התחילה `getUserMedia` שני, ושני `MediaRecorder` רצו במקביל.
  2. **סגירת מודאל המשיכה להעלות.** unmount של ה-modal לא ביטל את ה-upload-in-flight (אין `AbortController`). ה-component התפרק, אבל ה-`await fetch(...)` המשיך ועדכן state ש-React כבר העלים → React warning + side effects לא רצויים.
  3. **מיקרופון דלף.** ה-stream של `getUserMedia` לא קיבל `stream.getTracks().forEach(t => t.stop())` בכל מסלולי היציאה (stop / שגיאה / unmount). LED של המיקרופון נשאר דולק אחרי שהמשתמש סגר את המודאל.

**סיבה שורשית:** React + משאב async חיצוני (mic, camera, WebSocket, EventSource, MediaRecorder, AudioContext, AbortController ל-fetch ארוך) מצריך **שלוש** הגנות שחיות יחד:
1. **Action-in-flight guard** — `useRef` שמסמן שפעולה מתחילה; double-click לא יתחיל פעולה שנייה. reset ב-`finally`.
2. **Mounted guard אחרי `await`** — `let cancelled = false; return () => { cancelled = true; }` ב-`useEffect`, וכל `setState` אחרי await מותנה ב-`if (!cancelled)`.
3. **Cleanup עקבי בכל מסלולי היציאה** — `releaseResource()` idempotent שנקראת מ-stop button, מ-`catch`, ומ-`useEffect cleanup`. חסר אפילו מסלול אחד = leak.

הדפוס מופיע כל פעם שיש משאב חיצוני שהדפדפן לא משחרר אוטומטית — בניגוד ל-`setTimeout` (משוחרר ב-GC) או fetch קצר רגיל (אין side effects כשה-promise פוקע). הסיכון הייחודי: hardware (מיקרופון/מצלמה) ופרטיות.

**Custom rule prompt:** ראה `bugbot-rules/react-async-media-resource.md` — detection signature מלא של 5 קריטריונים + 5 false-positive filters.

**False positives:**
- ⚠️ קומפוננטות עם משאב שמשוחרר אוטומטית (fetch קצר בלי side effects).
- ⚠️ קומפוננטות שאינן ניתנות ל-unmount באמצע (single-shot recorder במסך מלא).
- ⚠️ `getUserMedia` ב-app-level singleton שמנוהל מחוץ ל-component lifecycle.
- ⚠️ Custom hook (`useMicrophone`, `useSocket`) שמטפל פנימית — בדוק את ה-hook פעם אחת.

**Mode מומלץ:** Strict לכל קומפוננטה שמשתמשת ב-`navigator.mediaDevices.*`, `new WebSocket(...)`, `new EventSource(...)`, `new MediaRecorder(...)`, `new AudioContext(...)`, או `new AbortController()` שמועבר ל-fetch ארוך.

---

## דירוג סופי

| Priority | Pattern | תדירות | Severity range | Mode מומלץ |
|---------|---------|---------|----------------|------------|
| **P1** | 1. Status transition side-effects | 8 | Medium-High | Warning |
| **P1** | 2. Filter exclusion → empty list | 7 | Medium-High | Warning |
| **P1** | 3. Race conditions async/concurrent | 7 | High | Strict (webhooks/cron) + Warning (React) |
| **P1** | 4. Schema default overriding intent | 5 | Medium | Warning |
| **P2** | 5. Cron lacks terminal state | 4 | Medium | Strict |
| **P2** | 6. Touchpoint not comprehensive | 4 | Medium | Warning |
| **P2** | 7. SDK error type completeness | 4 | Medium | Warning |
| **P2** | 8. SQL nullability + PG edge cases | 5 | Medium-High | Strict |
| **P3** | 9. Activity log as source of truth | 3 | Medium | Warning |
| **P3** | 10. Browser protocol handoff | 2 | Medium | Warning |
| **P3** | 11. שדה ב-schema/payload לא מגיע לכתיבה הסופית | 3 | Medium | Warning |
| **P3** | 12. React state stale על prop / localStorage key | 2 | Medium-High | Warning |
| **P3** | 13. Terminal-state leak (סגורים בקריאות אקטיביות) | 2 | Medium-High | Strict (cron) / Warning (UI) |
| **P3** | 14. React + משאב async חיצוני (mic / camera / socket) | 1 | Medium-High | Strict |

## הערה כללית על false-positive tuning

כל ה-rules כתובים עם הקשר ספציפי ל-Noa_Leads (CRM, מערכת אחת, RTL/Hebrew). בbugbot חדש שאינו cursor-style — אם הוא תומך ב-`context filters` (e.g. "only run on files matching `backend/app/services/*.py`"), כדאי להגביל:
- Patterns 1, 6: רק `backend/app/services/`, `backend/app/api/routes/`.
- Pattern 3 webhooks: `backend/app/api/routes/*webhook*`, `backend/jobs/`.
- Pattern 3 React: `frontend/components/`, `frontend/app/`.
- Pattern 5: רק `backend/jobs/*.py`.
- Pattern 8: רק `backend/app/models/`, `backend/alembic/versions/`, `backend/app/services/`.

ה-rules כתובים בצורה שניתן להגדיר אותם כפרומפט אחד ארוך — אבל יותר מועיל לפצל ל-10 rules נפרדים, כל אחד עם ה-context filter שלו, כך שה-bugbot יכול לציין איזה rule נכשל וה-developer ידע לאן להסתכל.
