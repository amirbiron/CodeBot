## מדריך: עדכוני תלויות אוטומטיים ומיזוג אוטומטי

מדריך זה מסביר איך הוגדרו עדכוני תלות אוטומטיים (Dependabot), איך מפעילים/מכבים מיזוג אוטומטי אחרי בדיקות ירוקות, ואיך להימנע מפריסה לא צפויה בזמן עבודה.

### מה קיים בריפו
- Dependabot: `.github/dependabot.yml`
  - אקוסיסטמים: pip + docker
- תיקייה: `/` (קובצי `requirements/*.txt` ו־`Dockerfile`)
  - תדירות: weekly (יום ד׳, 02:00–02:30 UTC)

- מיזוג אוטומטי ל־Dependabot: `.github/workflows/dependabot-auto-merge.yml`
  - מאשר ומפעיל Auto‑merge לעדכוני patch; minor מאושר אם מוגדר כ־security או לפי allowlist.
  - מאופשר רק כשה־Secret `DEPENDABOT_AUTOMERGE`=true.
  - נשען על "Allow auto‑merge" וכללי Branch protection.

- CI ל־PRים: `.github/workflows/ci.yml`
  - רץ על Pull Request בלבד (לא על push ל־main) כדי למנוע כפילות.
  - כולל: "🔍 Code Quality & Security", "Unit Tests" (פייתון 3.11/3.12), וכן hadolint, gitleaks, semgrep, yamllint, lychee, ועוד.

- Build/Deploy: `.github/workflows/deploy.yml`
  - רץ על push ל־main/develop ו/או על תגיות `v*`, או ידנית.
  - כולל Trivy על תמונת הדוקר לאחר build והעלאה לרג׳יסטרי (SARIF ל־Security). אינו רץ על PR.

- סריקות אבטחה מתוזמנות ו־PR‑Triggered: `.github/workflows/security-scan.yml`
  - רץ אוטומטית פעם בחודש (1 לחודש, 02:00 UTC): Trivy על הריפו ועל התמונה, CodeQL, Issue מסכם, והתראת טלגרם אם מוגדרים סודות.
- רץ גם על PR שמשנה `Dockerfile`/`requirements/*.txt`/`constraints*.txt` כדי לחשוף CVEs לפני merge.

### שלבי הגדרה (UI בלבד)
1) פתיחת PR כ־Draft כדי להפעיל CI
   - Pull requests → New pull request
   - base: `main`, compare: הענף שלך
   - Create draft pull request
   - המתן שהריצה תסתיים (הבדיקות ירוקות)

   ![Create Draft PR](images/create-draft-pr.svg)

2) הגדרת Branch protection ל־`main`
   - Repo → Settings → Branches → Add rule (או עריכת כלל קיים)
   - Branch name pattern: `main`
   - סמן:
     - Require a pull request before merging
     - Require status checks to pass before merging
       - בחר את הסטטוסים הנדרשים שמגיעים מ־ci.yml. הרשימה נמצאת ב-`docs/ci-cd.rst`, ולא מועתקת לכאן כדי שלא תתיישן.
       - מומלץ: Require branches to be up to date before merging
     - Require conversation resolution before merging (מומלץ)
   
   ![Branch Protection Rule](images/branch-protection-rule.svg)
   - השאר Require approvals כבוי אם רוצים שמיזוג Dependabot יהיה אוטומטי.

3) הפעלת Auto‑merge הכללי בגיטהאב
   - Settings → General → Pull requests → Enable "Allow auto‑merge"

   ![Allow Auto Merge](images/allow-auto-merge-setting.svg)

4) הפעלה/כיבוי של מיזוג אוטומטי ל‑Dependabot
   - Repo → Settings → Secrets and variables → Actions → New repository secret
   - Name: `DEPENDABOT_AUTOMERGE`
   - Secret: `true`
   - כדי לכבות בכל עת: מחיקה או שינוי לערך שאינו `true`.

   ![Add Secret](images/add-secret-dependabot-automerge.svg)

### איך זה עובד בפועל
- Dependabot פותח PRים לעדכוני pip ו־docker פעם בשבוע.
- על PR: רץ CI מלא. אם הכל ירוק, וכללי ההגנה מתקיימים, ו־`DEPENDABOT_AUTOMERGE`=true – יבוצע Auto‑merge לעדכוני patch (ו/או minor לפי כללים ב־workflow).
- על push לענפים ראשיים: רץ deploy, כולל סריקת Trivy לתמונה והעלאת תוצאות ל־Security.
- חודשי: רץ סריקת Security יזומה (Trivy + CodeQL) ומייצר Issue מסכם.

### זהירות לגבי פריסה (Render)
- בקובץ `render.yaml` מוגדר `autoDeploy: true` לשירות הראשי.
- מיזוג ל־`main` ב־GitHub עלול לגרום ל־Render לבצע Deploy ולבצע ריסטארט קצר לשירות (עלול לנתק שיחה פעילה).
- כדי להימנע מפריסה לא צפויה בזמן עבודה:
  - השאר PR כ־Draft עד לזמן מתאים.
  - או כבה זמנית Auto Deploy ב־Render (Service → Settings → Auto Deploy: Off), מזג, ואז החזר ל־On.
  - או מזג בשעות שקטות.

### הרחבות אופציונליות
- מיזוג גם ל־minor (במקום patch בלבד):
  - עדכון תנאי הוורקפלואו שיאפשר גם `version-update:semver-minor`.
  - מומלץ להשאיר approvals כבוי אם רוצים לשמור על אוטומציה מלאה.

### פתרון תקלות
- "No checks have been added" בכללי ההגנה:
  - ודא שיש לפחות ריצה אחת של ה־CI על PR (גם Draft מספיק).
  - רענן את העמוד ואז בחר את הסטטוסים הנדרשים מרשימת ה־checks (הרשימה ב-`docs/ci-cd.rst`).

- "There isn’t anything to compare" כשפותחים PR:
  - ודא שה־base הוא `main` וה־compare הוא הענף שלך.
  - נסה "switch base & compare" אם צריך.

- Auto‑merge לא קורה:
  - בדוק ש־"Allow auto‑merge" מופעל בהגדרות הרפו.
  - ודא ש־`DEPENDABOT_AUTOMERGE`=true כסוד ריפוזיטורי.
  - בדוק שכל הבדיקות ירוקות וכללי ההגנה מתקיימים.

  

### צ'ק־ליסט מהיר
- [ ] הגדרת Branch protection ל־`main` עם הסטטוסים הנדרשים מ־ci.yml (הרשימה ב-`docs/ci-cd.rst`)
- [ ] הפעלת "Allow auto‑merge" (Settings → General → Pull requests)
- [ ] הוספת Secret: `DEPENDABOT_AUTOMERGE`=true (כשרוצים אוטומרג׳ ל־patch)
- [ ] לשקול כיבוי זמני של Auto Deploy ב־Render לפני מיזוגים ל־`main`

אם צריך, אפשר להרחיב/לצמצם את האוטומציה לפי מדיניות הצוות (לדוגמה, לאפשר minor, לדרוש approvals, או להוסיף חריגות).

