### מדריך נעילת תלויות (pip-tools)

מסמך זה מסביר איך לנעול תלויות בצורה בטוחה, איך לבדוק, ומה לעשות אם מתגלות בעיות לאחר השינוי.


## לפני שמתחילים
- עבודה בברנץ' נפרד. אל תשנו ישר ב-main.
- ודאו את גרסת Python ההדוקה לסביבת הפרודקשן (למשל 3.10/3.11).
- שמרו עותק של `requirements.txt` הנוכחי (או תלו ב-git).


## תהליך נעילה מומלץ (pip-tools)
1) התקינו pip-tools מקומית/ב-CI:
```bash
pip install pip-tools
```

2) הפכו את הקובץ הנוכחי לקובץ מקור, ונעלו לקובץ requirements.txt עם hashes:
```bash
mv requirements.txt requirements.in
pip-compile --generate-hashes -o requirements.txt requirements.in
```

3) (אופציונלי) פיצול dev/prod:
```bash
echo "-r requirements.txt" > requirements-dev.in
pip-compile --generate-hashes -o requirements-dev.txt requirements-dev.in
```

4) התקנה בסביבה (מקומית/CI/פרודקשן):
```bash
pip install --require-hashes -r requirements.txt
```

5) קיבוע לגרסת Python/פלטפורמה (אם צריך):
```bash
pip-compile --generate-hashes \
  --python-version 3.11 \
  -o requirements.txt requirements.in
```


## בדיקה מהירה לאחר הנעילה
- הריצו את היישום (סטארט הבוט) ובדקו פעולה בסיסית (למשל /start, שמירה, ניתוח/בדיקה של קובץ אחד).
- מריצים smoke-test מינימלי במקום בדיקות מלאות כדי לגלות בעיות רזולבר מוקדם.


## תרחישי תקלה נפוצים ופתרונות

- בעיית רזולבר (pip-compile נכשל עם conflicts):
  - הצמידו ידנית גרסאות בעייתיות ב-`requirements.in` (למשל `cryptography==41.0.5`).
  - נסו שדרוג מבוקר לחבילה אחת:
    ```bash
    pip-compile --generate-hashes -o requirements.txt \
      --upgrade-package urllib3==2.2.2 requirements.in
    ```
  - הוסיפו קובץ constraints אם צריך לקבע תלויות עקיפות.

- Hash mismatch בזמן `pip install --require-hashes`:
  - אל תערכו ידנית את `requirements.txt` הסופי.
  - הריצו `pip-compile` שוב באותה גרסת Python/OS.
  - נקו cache אם צריך: `pip cache purge`.

- כשלי בנייה (wheels חסרים) לחבילות C (למשל cryptography, psycopg2):
  - בדביאן/אובונטו:
    ```bash
    apt-get update && apt-get install -y \
      build-essential python3-dev libffi-dev libssl-dev
    ```
  - באלפיין:
    ```bash
    apk add --no-cache build-base python3-dev libffi-dev openssl-dev
    ```
  - העדיפו wheels תואמים לגרסת ה-Python/פלטפורמה או הצמידו לגרסאות עם wheels זמינים.

- חוסר תאימות גרסת Python:
  - קומפלו עם הדגל המתאים: `--python-version <X.Y>`.
  - ודאו ש-CI/פרודקשן מריצים אותה גרסה.

- בעיות רשת/זמינות PyPI:
  - העלו timeout: `pip --default-timeout=60 install ...`.
  - הגדירו מראה/מראה פרטי עם `PIP_INDEX_URL`/`PIP_EXTRA_INDEX_URL`.


## כיצד לשדרג חבילה ספציפית לאחר הנעילה
- שדרוג ממוקד מבלי לפרק את הנעילה:
```bash
pip-compile --generate-hashes \
  --upgrade-package requests==2.32.3 \
  -o requirements.txt requirements.in
```


## רולבק מהיר
- אם לאחר המיזוג יש כשל:
  - שחזרו את `requirements.txt` הישן (git checkout) או `git revert` ל-commit האחרון ששינה אותו.
  - התקינו שוב: `pip install --require-hashes -r requirements.txt` (הישן).


## טיפים ל-CI/CD
- השתמשו תמיד ב:
```bash
pip install --require-hashes -r requirements.txt
```
- הריצו smoke-test (סטארט הבוט + פקודה אחת) כשלב נפרד.
- אם יש `requirements-dev.txt`, התקינו בנפרד ב-step ייעודי לסביבת הפיתוח בלבד.


## שאלות/תמיכה
- אם רואים שגיאת `ResolutionImpossible`, הוסיפו הצמדה ב-`requirements.in` לחבילה/טווח גרסאות.
- אם רק חבילה אחת יוצרת בעיות, שדרגו או הורידו גרסה נקודתית עם `--upgrade-package`.
- העדיפו לשמור lock מעודכן אחת לתקופה במקום פער גדול בין גרסאות.