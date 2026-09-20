# דפוסים חוזרים (RECURRING)

דפוסים שאושרו ב**שני פרויקטי מקור שונים** — סיגנל חזק, אבל בסיס הראיות צר יותר מ-CORE. (הניסוח המקורי היה "2 מתוך 3", מהתקופה שבה היו שלושה מסמכי מקור; מאז נוספו עוד, והבר המופעל הוא מה שהכלל התכוון אליו: שני **פרויקטים** שונים — לא יחס מספרי, ולא שני מסמכים של אותו פרויקט.) החל אם הפרויקט שלך תואם ל-stack. כל ערך מציין את הפרויקטים הספציפיים, כדי שתוכל לשפוט אם הדפוס סביר להיות רלוונטי.

> **הערה על PII leakage:** הוא מסווג כ-RECURRING לפי תדירות (EmailFlow + 8-Projects), אבל החומרה מקדמת אותו ל-`CRITICAL-PATTERNS.md` K7. הכלל המלא חי שם; ראה גם הסעיף בסוף לקרוס-רפרנס.

---

## R1. lifecycle של AsyncSession ב-SQLAlchemy

**תדירות:** 2/3 מקורות (EmailFlow + 8-Projects/Shipment-bot)
**חומרה:** MEDIUM — קריסות `MissingGreenlet`, שחיתות נתונים שקטה

### איך זה נראה
SQLAlchemy async (`AsyncSession`, `async_sessionmaker`) יש לו כללי lifecycle שתופסים מפתחים לא מוכנים:
- attributes של אובייקט ORM שניגשים אליהם *אחרי* `await session.rollback()` זורקים `MissingGreenlet`.
- `AsyncSession` אחד שמשותף בין tasks concurrent דרך `asyncio.gather` → race / שחיתות (sessions לא בטוחים ל-thread או ל-task).
- אחרי `await session.commit()` בלולאה, גישה מחדש לאותה שורת ORM מחזירה attributes ישנים (commit מרענן רק את ה-PK; דורש `await session.refresh(row)` מפורש).
- `joinedload` + `with_for_update` אינם תואמים (SQLAlchemy זורק).
- `Engine` singleton שמקושר ל-event loop אחד נכשל ב-Celery task השני (שמקבל loop חדש).

### דוגמאות אמיתיות
- **EmailFlow (`0fdd247`):** `MissingGreenlet` בגישה ל-attribute של ORM אחרי rollback.
- **EmailFlow (`018b166`):** `asyncio.gather` משתף session בין tasks → שחיתות.
- **EmailFlow (`0e6dc85`):** embedding job ניגש ל-attributes ישנים אחרי commit בתוך לולאה.
- **Shipment-bot (`85d7a8e`):** לולאה על `expiring` deliveries אחרי `db.commit()` — `MissingGreenlet`.
- **Shipment-bot (`0f30963`):** Celery singleton engine קשור ל-event loop ישן → task שני תמיד נכשל.
- **Shipment-bot (`4352bac`):** `joinedload` + `with_for_update` זרק.

### כלל לזיהוי
1. לעולם אל תעביר את אותו `AsyncSession` ל-tasks concurrent מרובים דרך `asyncio.gather` / `asyncio.create_task` — כל task פותח את שלו עם `async with sessionmaker() as session:`.
2. אחרי `await session.rollback()` (מפורש או מ-exception): אל תיגש ל-attributes של ORM. חלץ `.id` / primitives **לפני** rollback, או `session.expunge(obj)` כדי לנתק.
3. אחרי `await session.commit()` בתוך לולאה, קרא ל-`await session.refresh(row)` לפני גישה מחדש ל-attributes.
4. `joinedload` עם locking → השתמש ב-`contains_eager` במקום.
5. Celery tasks: צור engine חדש בתוך ה-task (או השתמש ב-connection pool שמתחדש ל-loop הנוכחי).

### False positives
- SQLAlchemy סינכרוני (`sessionmaker` רגיל) — כללים שונים לחלוטין.
- session ב-FastAPI scope של dependency per-request — בטוח כל עוד אין `gather`.

### מצב מומלץ
**strict** לקוד שעושה `await session.commit()` בתוך לולאה או משתמש ב-`asyncio.gather`.

### ראה גם
- `BY-STACK/async-orm.md` — כיסוי מלא עם קוד

---

## R2. דפדוף בלי tiebreaker משני

**תדירות:** 2/3 מקורות (EmailFlow + 8-Projects/Shipment-bot)
**חומרה:** MEDIUM — דפדוף מדלג/מכפיל שורות, ranking לא דטרמיניסטי

### איך זה נראה
`ORDER BY ts.desc()` (או `score.desc()`) ואחריו `LIMIT` / `OFFSET` או cursor pagination. שורות עם אותו ערך ראשי מקבלות סדר לא מוגדר ב-Postgres → בין דפים, ה-ties מתערבבים מחדש → שורה יכולה להופיע פעמיים או להידלג.

### דוגמאות אמיתיות
- **EmailFlow (`d84daca`):** `Lead.order_by(updated_at.desc())` בלבד → leads עם אותו timestamp קיבלו סדר אקראי → דפדוף בלולאה.
- **EmailFlow (`3987818`):** CAS query דרש tuple `(timestamp, created_at)` כדי להתאים ל-selector.
- **EmailFlow (`a0c4603`):** Drafter ranking בלי tiebreaker משני → ranking לא דטרמיניסטי.
- **Shipment-bot (`c0c1b74`):** Audit log מדפדף לפי timestamp בלבד → שורות התערבבו בין דפים.

### כלל לזיהוי
כל `order_by(...)` / raw `ORDER BY` שאחריו `LIMIT` / `OFFSET` / cursor pagination חייב לכלול **לפחות שתי expressions**:
1. השדה הסמנטי (`created_at.desc()`, `score.desc()`).
2. המפתח הראשי כ-tiebreaker (`Model.id.desc()` או `.asc()`).

ל-CAS עם סמנטיקה של "latest", ה-tiebreaker חייב להתאים בין ה-selector ל-verifier.

### False positives
- Queries בלי `LIMIT` — סדר פחות קריטי.
- אגרגציות (`GROUP BY` + `SUM`).
- queries של שורה יחידה (`.first()`, `.scalar_one_or_none()`) על עמודה ייחודית.

### מצב מומלץ
**warning** (strict מוסיף `.id` לכל query, כולל אגרגציות, ומייצר רעש).

### ראה גם
- `BY-STACK/postgres.md`
- `bugbot-rules/pagination-tiebreaker.md`

---

## R3. quirks של Browser API / DOM

**תדירות:** 2/3 מקורות (Noa + 8-Projects)
**חומרה:** MEDIUM — UX שבור, מדי פעם אובדן נתונים

### איך זה נראה
ל-APIs של הדפדפן יש סמנטיקה לא מובנת מאליה שתופסת מפתחים שקוראים אותן כאילו היו APIs של Node:
- `window.open("mailto:...")` מחזיר `null` ב-Chrome (handoff של protocol מערכת, **לא** popup blocker). קוד שמפרש `null` כ-"חסום" מבטל את הפעולה הלגיטימית.
- `navigator.clipboard.writeText(...)` דורש HTTPS; זורק על HTTP. בלי try/catch → שגיאת console + כשל UX שקט.
- Tooltip / dropdown נסגר מיד על click כי ה-click מבעבע ל-parent שמחליף state.
- CSS reset גלובלי (`* { margin: 0; padding: 0 }`) יש לו specificity גבוה יותר ממחלקות utility של Tailwind כמו `space-y-6`.
- דליפת `URL.createObjectURL` — blob URL לעולם לא משוחרר, מצטבר לכל render.
- `setTimeout(fn, delay)` עם `delay = NaN` — שגיאת React / delay אינסופי.

### דוגמאות אמיתיות
- **Noa (`f635304`):** `window.open("mailto:...")` החזיר `null` ב-Chrome; popup-blocker guard ביטל flow של `mark_sent`.
- **Noa (`f4769bf`):** כפתור `BOOKED` הוצג אחרי `slot_start + 30min` במקום `slot_end` — שובר מפגשים קצרים.
- **Markdown-Academy (`b97d3f5`):** כפתור Copy קרא ל-`navigator.clipboard.writeText` בלי try/catch; נשבר ב-HTTP.
- **Markdown-Academy (`315154e`):** Tooltip נסגר על click כי parent תפס propagation; נדרש `stopPropagation()`.
- **Web (`c586691`):** CSS reset גלובלי `* { margin: 0; padding: 0 }` דרס utilities של Tailwind.
- **Web (`f5cbaf9`):** Blob URL של תמונת profile לא משוחרר על unmount.

### כלל לזיהוי
1. `window.open(url, ...)` ואחריו `if (!win)` שמבטל flow → דווח אם `url` מתחיל ב-`mailto:`, `tel:`, `sms:`, `file:`. ל-protocols מערכת, השתמש ב-`<a>` עם `.click()`.
2. `navigator.clipboard.*` בלי try/catch → דווח.
3. `URL.createObjectURL` בלי `URL.revokeObjectURL` מתאים ב-cleanup של `useEffect` / `componentWillUnmount` / `addEventListener('unload', ...)`.
4. `setTimeout(fn, delay)` / `setInterval(fn, delay)` / `new Date(value)` בלי הגנת `isFinite(delay)` ל-delay/value ממקור חיצוני.
5. `* { margin: 0; padding: 0 }` גלובלי בפרויקט שמשתמש ב-framework utility CSS (Tailwind, UnoCSS) → דווח.

### מצב מומלץ
**warning** — רוב הבאגים הם UX, לא אובדן נתונים.

### ראה גם
- `BY-STACK/browser-handoff.md`
- `bugbot-rules/window-open-protocol-handoff.md`

---

## R4. שלמות exception של External SDK

**תדירות:** 2/3 מקורות (Noa + 8-Projects)
**חומרה:** MEDIUM — בליעה שקטה / קריסת startup

### איך זה נראה
SDKs זורקים היררכיות exception רחבות, ו-subclasses של `BaseException` (`asyncio.CancelledError`) לא יושבים תחת `Exception`. הקוד תופס base צר מדי, נותן ל-subclasses לפרוץ, או בולע הכל דרך `Exception` ומונה לא נכון.

### דוגמאות אמיתיות
- **Noa (`c128115`):** `_complete` תפס `RateLimitError` + `_RETRYABLE`; subtypes אחרים של `anthropic.APIError` (`NotFound`, `BadRequest`, `Auth`) עברו בלי טיפול.
- **Noa (`95dcce6`):** Fallback תפס `RateLimitError` כ-`AIError` גנרי → ה-caller לא סימן `pending_classification`.
- **Noa (`95b82e5`):** OAuth scope drift טופל כקטלני; נדרש `OAUTHLIB_RELAX_TOKEN_SCOPE=1`.
- **Shipment-bot (`e0f4d59`):** `isinstance(r, Exception)` לא תפס `CancelledError` (subclass של `BaseException`) → tasks מבוטלים נספרו כהצלחה.
- **routine (`2571c91` / `e5c26ad`):** מפתחות VAPID פגומים → exception לא נתפס ב-`setVapidDetails` → השרת קרס בעלייה.

### כלל לזיהוי
1. לכל קריאת SDK חיצוני, ה-`except` צריך לתפוס את ה-base class המתועד של ה-SDK (`anthropic.APIError`, `googleapiclient.errors.HttpError`, `stripe.error.StripeError`).
2. סדר את בלוקי ה-`except` subclass-לפני-superclass (`RateLimitError` לפני `APIError`).
3. לתוצאות של collection של tasks async (`asyncio.gather(return_exceptions=True)`): בדוק `isinstance(r, BaseException)`, לא `Exception` (CancelledError אינו Exception ב-3.8+).
4. אתחול SDK בזמן startup (VAPID keys, OAuth client, Stripe key) חייב להיות עטוף ב-try/except + ולידציית פורמט; כשלים מורידים את הפיצ'ר הרלוונטי, לא קורסים את כל השרת.
5. תעד וכבד env flags של SDK (`OAUTHLIB_RELAX_TOKEN_SCOPE`, `STRIPE_API_VERSION`, וכו').

### מצב מומלץ
**strict** בכל גבולות ה-SDK.

### ראה גם
- `BY-STACK/external-sdk.md`
- `bugbot-rules/sdk-error-completeness.md`

---

## R5. שגיאות scope של filter

**תדירות:** 2/3 מקורות (Noa + 8-Projects/Facebook-Leads-New)
**חומרה:** MEDIUM — UI ריק / cron בלולאה אינסופית / משתמש חסום שעדיין מקבל leads

### איך זה נראה
filter (DB `WHERE`, regex, JS `.filter()`) או צר מדי (מוציא מקרים לגיטימיים) או מופעל בסדר שגוי (filters מאוחרים דורסים מוקדמים).

### דוגמאות אמיתיות
- **Noa (`f635304`):** רשימה ידנית סוננה ל-WhatsApp בלבד; lead שמעדיף email ראה רשימה ריקה.
- **Noa (`d526948`):** סינון `channel + audience` ביחד חסם templates תקפים.
- **Noa (`95dcce6`):** Domain blacklist עם exact-match פספס subdomains (`mail.mailchimp.com`).
- **Noa (`c608a85`):** סינון retry של cron על `lead_id IS NULL` תפס שורות spam/not_business שלעולם לא יקבלו lead_id → לולאה אינסופית.
- **Noa (`2b978aa`):** סינון cron `count < MAX` הוציא שורות תקועות ב-`count==MAX` → תקועות pending לנצח.
- **Facebook-Leads-New (`24ad356`):** סינון blocked-publisher רץ *אחרי* בדיקת `force_send` → blocked publisher עם מילת מפתח `force_send` עדיין שלח leads.

### כלל לזיהוי
לכל filter (`WHERE`, regex, `.filter()`):
1. **שלמות:** האם הוא מכסה את כל ה-input variants הצפויים? (סינון channel שמפספס lead שמעדיף email; regex על email שמפספס RFC 2822 display name; domain blacklist עם exact match במקום `endswith` ל-subdomains).
2. **States סופיים ל-cron:** כלול עמודות "done" מפורשות (`processing_status`, `archived_at`), לא heuristics של "IS NULL" שתופסות states סופיים שלעולם לא יתמלאו.
3. **סדר filter:** filters של security / block / deny רצים *קודם*, לפני כל override "force send / always include".

### מצב מומלץ
**strict** ל-filters של cron שמגדירים reprocessing של שורות.
**warning** ל-filters של UI (false positives שכיחים — לפעמים צמצום scope הוא הפיצ'ר).

### ראה גם
- `BY-STACK/cron-jobs.md` — דפוס terminal-state
- `bugbot-rules/filter-too-narrow.md`

---

## R6. עותק שני של כלל — והם נסחפים

**תדירות:** 2 פרויקטים (CodeBot + Campaign AI)
**חומרה:** MEDIUM — אינו באג ברגע הכתיבה. הוא הופך לבאג בתיקון הבא

### איך זה נראה
אותו כלל — פורמוט, סינון, חישוב, רשימת ערכים — נכתב פעם שנייה במקום להיקרא מהמקום שבו הוא כבר קיים. שני העותקים נכונים ביום הראשון. ואז אחד מהם מתוקן.

### דוגמאות אמיתיות
- **CodeBot (PR #3345):** פורמוט גודל קובץ בחמישה מקומות — שני קבצי Python ושלושה קבצי JS. הם נסחפו: `105.0 KB` ו-`582.0 B` (ספרה אחרי הנקודה גם כשהיא אפס), והערך נקרא בסדר שגוי בהקשר עברי.
- **CodeBot (PR #3217):** אייקוני שפה בחמישה מקומות עם כיסוי שונה — אותו קובץ קיבל אייקון אחד בדף הקבצים ואחר בחיפוש.
- **CodeBot (PR #3358):** שאילתת המחיקה בשלושה עותקים, והוובאפ כלל לא עובר דרך `database/repository.py` — ולכן השכפול בין הבוט לווב אינו נראה בקריאת קוד אחת.
- **CodeBot (PR #3365):** תוסף מארקדאון משוכפל תו-בתו בין `md_preview` ל-`live-preview.js` — כשהתוסף הפיל את התצוגה, ה-Live Preview היה שבור בדיוק באותה צורה.
- **CodeBot (PR #3237):** `before_send` של Sentry בשני עותקים שהתחילו להתפצל — וכך אירועי transactions עקפו ניקוי סודות ש"כבר תוקן".
- **Campaign AI (`8ceaf0b`):** רשימת סוגי ההתראות שוכפלה בין Python ל-SQL → המונה בדשבורד סטה מהאכיפה בפועל.

### כלל לזיהוי
1. לפני כתיבת פונקציה שמחשבת, מפרמטת, מסננת או ממפה משהו — `grep` על **שם התופעה**, לא על שם הפונקציה: `format_file_size`, `bulk-delete`, `lang_icon`, `humanize`. יש עותק → מאחדים.
2. שני קבצים שמכילים את אותה רשימת ערכים או את אותו מיפוי — במיוחד כשאחד מהם הוא מיגרציה, סכימה, תבנית או קובץ JS.
3. לוגיקה שקיימת גם בצד השרת וגם בצד הלקוח: הכשל אינו שהיא כפולה, אלא שאין מה שיצעק כשהן נפרדות.

### מצב מומלץ
**warning.** העותק השני לגיטימי לפעמים (שפות שונות, גבולות שירות). מה שאינו לגיטימי הוא עותק שני **בלי מנגנון שמגלה סחיפה**: כשהשכפול בלתי נמנע — טסט שקורא את שני המקורות ומשווה. זה מה ש-Campaign AI עשה, והוא הופך סחיפה מתקווה לכשל CI.

### ראה גם
- `bugbot-rules/duplicate-rule-second-copy.md`
- `docs/source-projects/codebot-history-scan-patterns.md` P23

---

## R7. זמן נקרא בלי אזור זמן, או מתויג בלי להמיר

**תדירות:** 2 פרויקטים (CodeBot + Campaign AI)
**חומרה:** MEDIUM — כל תצוגת תאריך במערכת שגויה, או תאריך תקף נדחה. נכון ברוב שעות היממה, ולכן עובר סקירה

### איך זה נראה
שני חצאים של אותה טעות:
- **תיוג בלי המרה.** הערך נשמר UTC נאיבי. הקוד מדביק תווית (`replace(tzinfo=timezone.utc)`) אבל לא מזיז את השעון (`astimezone`). התאריך המוצג נכון בשעון, שגוי באזור.
- **"היום" לפי המכונה.** ‏`datetime.now()` בלי ארגומנט אזור זמן, ו-`date.today()` **תמיד** — הוא אינו מקבל ארגומנטים כלל (`TypeError: date.today() takes no arguments`), ולכן אין דרך להפוך אותו למודע-אזור. על שרת שחי ב-UTC שניהם מחזירים את היום הלא נכון בשעות שלפני חצות.

### דוגמאות אמיתיות
- **CodeBot (PR #3228):** מונגו שומרת UTC נאיבי; הקוד תייג ולא המיר. **כל** תאריך בוובאפ הוצג שעתיים אחורה בחורף ושלוש בקיץ — עמוד הקובץ, היסטוריית הגרסאות, ההשוואה, רשימת הקבצים, סל המחזור, הדשבורד, הטיימליין, דוחות האדמין ועמוד השיתוף הציבורי.
- **Campaign AI (`ba83880`):** `SpecialDayInput` השתמש ב-`date.today()`; שעון השרת ב-Render הוא UTC → תאריך ישראלי תקף נדחה בשעות שלפני חצות.

### כלל לזיהוי
1. `replace(tzinfo=...)` שאין אחריו `astimezone(...)` במסלול אל התצוגה.
2. ‏`datetime.now()` בלי ארגומנט אזור זמן — בקוד שרת, בברירת מחדל של שדה, או בהשוואה מול ערך שהגיע מהמשתמש. ‏**וכל `date.today()`**, בלי יוצא מן הכלל: אין לו פרמטר אזור זמן, ולכן כל שימוש בו בהקשר שהמשתמש רואה הוא ממצא. החלופה: `datetime.now(<אזור>).date()`.
3. ערך זמן שנכתב למסד בלי `tzinfo`, ונקרא במקום אחר כאילו הוא מקומי.
4. פורמוט בצד הלקוח שמניח שהערך שהגיע מה-API הוא מקומי — בלי `Z` או offset במחרוזת.

### מצב מומלץ
**strict** לכל דבר שהמשתמש רואה או שמשווים אותו לקלט של המשתמש. שני כללים: **קלט** — ערך נאיבי שנקרא מהמסד מקבל `replace(tzinfo=timezone.utc)`, כי הוא *באמת* UTC. **פלט** — כל הצגה עוברת `astimezone(<אזור התצוגה>)`, ו"היום" הוא `datetime.now(<האזור העסקי>).date()`.

### ראה גם
- `bugbot-rules/naive-datetime-no-conversion.md`
- `BY-STACK/cron-jobs.md` דפוס 8 — קצוות זמן ב-jobs תקופתיים

---

## R8. עבודה ומטען שאינם פרופורציונליים לתשובה

**תדירות:** 2 פרויקטים (CodeBot + Campaign AI)
**חומרה:** MEDIUM-HIGH — אינו מפיל כלום, ולכן שום טסט לא צועק. נמדד: 191 שניות לחיפוש אחד

### איך זה נראה
הקוד מביא, בונה או מחזיר הרבה יותר ממה שהתשובה דורשת. ארבע צורות:
1. **ההיטלה אחרי המיון.** השדה הכבד מוסר בסוף הצינור, ולכן הוא נגרר דרך `$sort` / `$group` / `JOIN`.
2. **שליפה פר-פריט בלולאה** (N+1), ולרוב בלי היטלה — כלומר כל המסמך לכל פריט.
3. **בנייה לפני שבודקים אם צריך.** אינדקס, קאש או אגרגציה נבנים לפני הענף שמחליט אם בכלל קוראים מהם.
4. **סריאלייזר עם רשימה שחורה.** מעתיק כל שדה ומסנן כמה שמות — ולכן כל שדה חדש במסמך נכנס לתשובה מעצמו.

### דוגמאות אמיתיות
- **CodeBot (PR #3336):** `$project` שמסיר את `code` הוצב אחרי `$sort`+`$group` → תקציב 100MB נגמר, שגיאה 292, ונפילה למסלול `skip` שסורק 4,000 מסמכים במנות. `/files` לקח 3.1–3.4 שניות בטעינה רגילה.
- **CodeBot (PR #3361):** שליפת קובץ-קובץ, שלוש קפיצות רשת לכל קובץ, `find_one` בלי היטלה, ו-`limit` שהוחל בסוף → **191.74 שניות**; הוובאפ ביקש 10 תוצאות והמערכת משכה 745 מסמכים.
- **CodeBot (PR #3351):** האינדקס בזיכרון נבנה לפני הבדיקה איזה סוג חיפוש התבקש; ברירת המחדל של הוובאפ כלל לא קוראת ממנו. מה שהסתיר את זה: פרמטר `index` שהועבר ומעולם לא נקרא.
- **CodeBot (PR #3318):** `_clean` עם denylist בן ארבעה שמות → וקטור של 768 floats (~10KB) בכל קריאה של שלושה כלי MCP, פי 25 מהתוכן בקריאת טווח קצרה.
- **Campaign AI (`#163`):** `create_client` חדש בכל קריאת DB — חיבור TLS חדש בכל פעם.
- **Campaign AI (`#169`):** `/health`, שנדגם כל ~5 שניות, החזיר את כל ה-OpenAPI schema של PostgREST — עשרות KB בכל קריאה.

### כלל לזיהוי
1. `find` / `SELECT *` בתוך לולאה, או קריאה למסד בתוך `for`.
2. שלב שמסיר שדות שממוקם אחרי שלב שממיין, מקבץ או מצרף.
3. שאילתה על אוסף שיש בו שדה גדול (`code`, `content`, `embedding`, `html`) בלי היטלה מפורשת.
4. סריאלייזר שכתוב כ"העתק הכל וסנן שמות" — במקום "בנה מהשדות האלה".
5. עבודה יקרה (אינדקס, קאש, אגרגציה) שנעשית לפני `if` שמחליט אם משתמשים בה.
6. `limit` שמוחל אחרי הסינון והמיון בקוד, ולא בשאילתה.

### מצב מומלץ
**warning** ברוב המקומות; **strict** במסלול שנקרא בכל טעינת עמוד או בכל בקשה, ובכל endpoint של בדיקת דופק. השאלה שחושפת: *מה מהמטען הזה ייקרא בפועל?* — ואם התשובה "חלק", ההיטלה שייכת לתחילת הצינור.

### ראה גם
- `BY-STACK/mongodb.md` — הצורות 1–2 בצינור אגרגציה, עם השגיאות בשמן
- `bugbot-rules/work-disproportionate-to-answer.md`

---

## R9. מדד שמערבב מקורות — ומניע פעולה אוטומטית

**תדירות:** 2 פרויקטים (CodeBot + Campaign AI)
**חומרה:** HIGH כשמנגנון אוטומטי פועל לפיו — ריסטארט, scaling, השתקת התראות

### איך זה נראה
המספר נבנה מדגימות שאינן מאותו עולם, והקוד שמחשב אותו נכון לגמרי. מה ששבור הוא ההתאמה בין השם של המדד למה שהוא באמת סופר — ולכן אי אפשר לראות את זה בקריאת הפונקציה, רק בשאלה "מה נכלל כאן".

### דוגמאות אמיתיות
- **CodeBot (PR #2740):** EWMA של זמן תגובה עודכן גם על 5xx ועל טיימאאוטים של gateway → "זמן תגובה ממוצע" תיאר גם בקשות שלא הוגשו, ו-`anomaly_detected` נדלק לפיו.
- **CodeBot (PR #2750):** בריאות ה-worker נמדדה בלי לתחום למקור פנימי → תקלות של שירותים חיצוניים ופתיחות Circuit Breaker נספרו כבריאות שלו, **והמנוע החזוי הפעיל ריסטארט על worker בריא**. ובאותו מקום: הספים חושבו על דגימות פנימיות והמספר ה"נוכחי" לא — שני צדדי ההשוואה לא מאותה אוכלוסייה.
- **CodeBot (PR #1193):** `first_ts` נקבע גם על שורות שהגיעו בתוך חלון הצינון → אחרי ההתראה הראשונה על קטגוריה, התראות נוספות עליה **לא נשלחו כלל**. התקלה נמשכה והמוניטור שתק.
- **CodeBot (PR #2429):** תגיות התראה נכתבו לפי שרשרת fallback (`alert_uid` → `uid` → `id` → `_id`, ממורות ל-`str`) ונקראו לפי `alert["alert_uid"]` בלבד → רשימת תגיות ריקה, תמיד, לחלק מההתראות.
- **Campaign AI (`#84`, `#85`):** `starting_metric` שלא רוענן (baseline מרחף), ומדד איכות שנמדד מול חלון מתגלגל במקום מול baseline קבוע — כך שהחלון "שלפני" היה בפועל החלון שאחרי השינוי.

### כלל לזיהוי
1. מדד שמניע פעולה אוטומטית ואין לידו הגדרה מפורשת של מה נכלל בו ומה לא.
2. ממוצע / אחוזון שמתעדכן **בכל** אירוע, כולל אירועים שלא הושלמו.
3. השוואה בין שני מספרים שנדגמו בצורה שונה (סף מול "נוכחי", לפני מול אחרי).
4. מזהה שנכתב דרך שרשרת fallback ונקרא דרך מפתח יחיד — או להפך.
5. מצב שמדכא התראות (cooldown, dedup, `first_ts`) שנכתב גם על אירועים שדוכאו.

### מצב מומלץ
**strict** לכל מדד שמפעיל ריסטארט, scaling, חיוב או השתקה; **warning** לדשבורדים. מזהה נכתב ונקרא דרך **פונקציה אחת**. ולכל מנגנון דיכוי — הבדיקה היא *"מתי ההתראה הבאה כן תצא?"*, כי הכשל בו שקט לחלוטין.

### ראה גם
- `BY-STACK/observability.md` — ה-deep-dive
- `bugbot-rules/metric-mixes-sources.md`
- `bugbot-rules/background-thread-liveness.md` — הצד המשלים: שם השאלה אם המדווח בכלל חי

---

## ראה גם (cross-tier)

- **K7 / PII בלוגים** — לפי תדירות זה RECURRING (EmailFlow P5 + 8-Projects C6/C24/C57), אבל לפי חומרה CRITICAL. הכלל המלא ב-`CRITICAL-PATTERNS.md`.
