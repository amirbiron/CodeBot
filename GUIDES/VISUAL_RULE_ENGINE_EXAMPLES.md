# דוגמאות כללים שימושיים למנוע הכללים הויזואלי

> **מטרת המסמך:** אוסף כללים מוכנים לשימוש שאפשר להעתיק, להתאים ולהשתמש בהם מיידית.
> 
> **ראו גם:** [מדריך מנוע הכללים](./VISUAL_RULE_ENGINE_GUIDE.md) | [תיעוד מלא](../docs/visual-rule-engine.rst)

---

## 📋 תוכן עניינים

1. [ניהול רעש (Noise Management)](#-ניהול-רעש-noise-management)
2. [סינון לפי סביבה](#-סינון-לפי-סביבה)
3. [התראות חכמות לפי זמן](#-התראות-חכמות-לפי-זמן)
4. [אוטומציה עם GitHub](#-אוטומציה-עם-github)
5. [Webhooks לשירותים חיצוניים](#-webhooks-לשירותים-חיצוניים)
6. [זיהוי בעיות ביצועים](#-זיהוי-בעיות-ביצועים)
7. [ניתוב לפי פרויקט/צוות](#-ניתוב-לפי-פרויקטצוות)
8. [כללים מתקדמים עם Regex](#-כללים-מתקדמים-עם-regex)

---

## 🔇 ניהול רעש (Noise Management)

### 1. השתקת התראות Info בכל הסביבות

**מתי להשתמש:** כשיש יותר מדי התראות Info שמרעישות את הערוץ.

```json
{
  "name": "השתק התראות Info",
  "enabled": true,
  "conditions": {
    "type": "condition",
    "field": "severity",
    "operator": "eq",
    "value": "info"
  },
  "actions": [
    {
      "type": "suppress"
    }
  ]
}
```

---

### 2. השתקת התראות "Test" או "Debug"

**מתי להשתמש:** כשיש התראות בדיקה שלא צריכות להגיע לערוץ.

```json
{
  "name": "השתק התראות בדיקה",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "OR",
    "children": [
      {
        "type": "condition",
        "field": "alert_name",
        "operator": "contains",
        "value": "test"
      },
      {
        "type": "condition",
        "field": "alert_name",
        "operator": "contains",
        "value": "debug"
      },
      {
        "type": "condition",
        "field": "summary",
        "operator": "contains",
        "value": "[TEST]"
      }
    ]
  },
  "actions": [
    {
      "type": "suppress"
    }
  ]
}
```

---

### 3. השתקת התראות חוזרות (לפי מספר הופעות)

**מתי להשתמש:** כשרוצים לראות רק שגיאות חדשות ולא שגיאות שכבר ידועות.

```json
{
  "name": "השתק שגיאות ישנות עם הרבה הופעות",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "AND",
    "children": [
      {
        "type": "condition",
        "field": "is_new_error",
        "operator": "eq",
        "value": "False"
      },
      {
        "type": "condition",
        "field": "occurrence_count",
        "operator": "gt",
        "value": 100
      }
    ]
  },
  "actions": [
    {
      "type": "suppress"
    }
  ]
}
```

---

## 🌍 סינון לפי סביבה

### 4. השתקת כל ההתראות מסביבת פיתוח

**מתי להשתמש:** כשלא רוצים לקבל התראות מסביבת Development.

```json
{
  "name": "השתק סביבת פיתוח",
  "enabled": true,
  "conditions": {
    "type": "condition",
    "field": "environment",
    "operator": "eq",
    "value": "development"
  },
  "actions": [
    {
      "type": "suppress"
    }
  ]
}
```

---

### 5. רק התראות קריטיות מסביבת Production

**מתי להשתמש:** כשרוצים לקבל רק התראות חשובות מהפרודקשן.

```json
{
  "name": "רק התראות קריטיות מפרודקשן",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "AND",
    "children": [
      {
        "type": "condition",
        "field": "environment",
        "operator": "eq",
        "value": "production"
      },
      {
        "type": "condition",
        "field": "severity",
        "operator": "ne",
        "value": "critical"
      }
    ]
  },
  "actions": [
    {
      "type": "suppress"
    }
  ]
}
```

> **הסבר:** הכלל משתיק הכל *חוץ* מהתראות קריטיות בפרודקשן.

---

### 6. השתקת Staging ו-Development יחד

**מתי להשתמש:** כשרוצים לקבל התראות רק מפרודקשן.

```json
{
  "name": "השתק סביבות לא-פרודקשן",
  "enabled": true,
  "conditions": {
    "type": "condition",
    "field": "environment",
    "operator": "in",
    "value": ["development", "staging", "test", "local"]
  },
  "actions": [
    {
      "type": "suppress"
    }
  ]
}
```

---

## ⏰ התראות חכמות לפי זמן

### 7. התראות רק בשעות העבודה (08:00-18:00)

**מתי להשתמש:** כשרוצים שהתראות לא-קריטיות יגיעו רק בשעות העבודה.

```json
{
  "name": "השתק מחוץ לשעות עבודה (לא קריטי)",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "AND",
    "children": [
      {
        "type": "condition",
        "field": "severity",
        "operator": "ne",
        "value": "critical"
      },
      {
        "type": "group",
        "operator": "OR",
        "children": [
          {
            "type": "condition",
            "field": "hour_of_day",
            "operator": "lt",
            "value": 8
          },
          {
            "type": "condition",
            "field": "hour_of_day",
            "operator": "gt",
            "value": 18
          }
        ]
      }
    ]
  },
  "actions": [
    {
      "type": "suppress"
    }
  ]
}
```

> **הערה:** `hour_of_day` הוא ב-UTC. התאימו לפי אזור הזמן שלכם.

---

### 8. השתקת התראות בסופי שבוע (לא קריטי)

**מתי להשתמש:** כשלא רוצים להטריד את הצוות בסופ"ש עם התראות לא-דחופות.

```json
{
  "name": "השתק סופ\"ש (לא קריטי)",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "AND",
    "children": [
      {
        "type": "condition",
        "field": "severity",
        "operator": "ne",
        "value": "critical"
      },
      {
        "type": "condition",
        "field": "day_of_week",
        "operator": "in",
        "value": [5, 6]
      }
    ]
  },
  "actions": [
    {
      "type": "suppress"
    }
  ]
}
```

> **הסבר:** `day_of_week` הוא 0=ראשון עד 6=שבת. כאן 5=שישי, 6=שבת.

---

### 9. התראה מיוחדת בשעות לילה

**מתי להשתמש:** כשרוצים לקבל התראה מיוחדת על שגיאות קריטיות בלילה.

```json
{
  "name": "התראת לילה מיוחדת",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "AND",
    "children": [
      {
        "type": "condition",
        "field": "severity",
        "operator": "eq",
        "value": "critical"
      },
      {
        "type": "group",
        "operator": "OR",
        "children": [
          {
            "type": "condition",
            "field": "hour_of_day",
            "operator": "lt",
            "value": 6
          },
          {
            "type": "condition",
            "field": "hour_of_day",
            "operator": "gte",
            "value": 23
          }
        ]
      }
    ]
  },
  "actions": [
    {
      "type": "send_alert",
      "channel": "telegram",
      "severity": "critical",
      "message_template": "🚨 התראת לילה! {{summary}}\n\nשעה: {{hour_of_day}}:00 UTC"
    }
  ]
}
```

---

## 📝 אוטומציה עם GitHub

### 10. פתיחת Issue לכל שגיאת Sentry חדשה

**מתי להשתמש:** כשרוצים לעקוב אחרי כל שגיאה חדשה בריפו.

```json
{
  "name": "פתח Issue לשגיאת Sentry חדשה",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "AND",
    "children": [
      {
        "type": "condition",
        "field": "alert_type",
        "operator": "eq",
        "value": "sentry_issue"
      },
      {
        "type": "condition",
        "field": "is_new_error",
        "operator": "eq",
        "value": "True"
      }
    ]
  },
  "actions": [
    {
      "type": "create_github_issue",
      "title_template": "[Sentry] {{summary}}",
      "severity": "bug"
    }
  ]
}
```

---

### 11. Issue רק לשגיאות קריטיות בפרודקשן

**מתי להשתמש:** כשרוצים Issues רק לדברים באמת חשובים.

```json
{
  "name": "Issue לשגיאה קריטית בפרודקשן",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "AND",
    "children": [
      {
        "type": "condition",
        "field": "severity",
        "operator": "eq",
        "value": "critical"
      },
      {
        "type": "condition",
        "field": "environment",
        "operator": "eq",
        "value": "production"
      },
      {
        "type": "condition",
        "field": "is_new_error",
        "operator": "eq",
        "value": "True"
      }
    ]
  },
  "actions": [
    {
      "type": "create_github_issue",
      "title_template": "🔥 [CRITICAL] {{summary}}",
      "severity": "critical"
    }
  ]
}
```

---

### 12. Issue לשגיאות מפרויקט ספציפי

**מתי להשתמש:** כשיש פרויקט שדורש מעקב צמוד יותר.

```json
{
  "name": "Issue לפרויקט API Gateway",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "AND",
    "children": [
      {
        "type": "condition",
        "field": "project",
        "operator": "eq",
        "value": "api-gateway"
      },
      {
        "type": "condition",
        "field": "severity",
        "operator": "in",
        "value": ["critical", "warning"]
      }
    ]
  },
  "actions": [
    {
      "type": "create_github_issue",
      "title_template": "[API Gateway] {{summary}}",
      "severity": "high-priority"
    }
  ]
}
```

---

## 🌐 Webhooks לשירותים חיצוניים

### 13. שליחה ל-Slack Webhook

**מתי להשתמש:** כשיש ערוץ Slack נפרד להתראות.

```json
{
  "name": "שלח ל-Slack על התראה קריטית",
  "enabled": true,
  "conditions": {
    "type": "condition",
    "field": "severity",
    "operator": "eq",
    "value": "critical"
  },
  "actions": [
    {
      "type": "webhook",
      "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
    }
  ]
}
```

---

### 14. Webhook ל-PagerDuty

**מתי להשתמש:** כשיש אינטגרציה עם PagerDuty לתורנות.

```json
{
  "name": "PagerDuty לשגיאות קריטיות",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "AND",
    "children": [
      {
        "type": "condition",
        "field": "severity",
        "operator": "eq",
        "value": "critical"
      },
      {
        "type": "condition",
        "field": "environment",
        "operator": "eq",
        "value": "production"
      }
    ]
  },
  "actions": [
    {
      "type": "webhook",
      "webhook_url": "https://events.pagerduty.com/generic/2010-04-15/create_event.json"
    }
  ]
}
```

---

### 15. Webhook מותנה לפי פרויקט

**מתי להשתמש:** כשכל צוות רוצה לקבל התראות רק על הפרויקטים שלו.

```json
{
  "name": "Webhook לצוות Payments",
  "enabled": true,
  "conditions": {
    "type": "condition",
    "field": "project",
    "operator": "in",
    "value": ["payments-service", "billing-api", "checkout"]
  },
  "actions": [
    {
      "type": "webhook",
      "webhook_url": "https://hooks.example.com/payments-team"
    }
  ]
}
```

---

## 📈 זיהוי בעיות ביצועים

### 16. התראה על Latency גבוה

**מתי להשתמש:** כשרוצים לזהות האטות בזמן תגובה.

```json
{
  "name": "התראה על Latency גבוה",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "AND",
    "children": [
      {
        "type": "condition",
        "field": "latency_avg_ms",
        "operator": "gt",
        "value": 1000
      },
      {
        "type": "condition",
        "field": "environment",
        "operator": "eq",
        "value": "production"
      }
    ]
  },
  "actions": [
    {
      "type": "send_alert",
      "channel": "telegram",
      "severity": "warning",
      "message_template": "⚠️ Latency גבוה!\n\nממוצע: {{latency_avg_ms}}ms\nסביבה: {{environment}}"
    }
  ]
}
```

---

### 17. התראה על שיעור שגיאות גבוה + עומס

**מתי להשתמש:** כשרוצים לזהות מצב קריטי של שגיאות בעומס גבוה.

```json
{
  "name": "שגיאות גבוהות בעומס",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "AND",
    "children": [
      {
        "type": "condition",
        "field": "error_rate",
        "operator": "gt",
        "value": 0.05
      },
      {
        "type": "condition",
        "field": "requests_per_minute",
        "operator": "gt",
        "value": 500
      }
    ]
  },
  "actions": [
    {
      "type": "send_alert",
      "channel": "telegram",
      "severity": "critical",
      "message_template": "🔥 שיעור שגיאות גבוה בעומס!\n\nשיעור: {{error_rate}}%\nבקשות/דקה: {{requests_per_minute}}"
    },
    {
      "type": "create_github_issue",
      "title_template": "[Performance] High error rate under load",
      "severity": "critical"
    }
  ]
}
```

---

### 18. אנומליה בביצועים

**מתי להשתמש:** כשיש התראות אנומליה אוטומטיות מהמערכת.

```json
{
  "name": "טיפול באנומליות",
  "enabled": true,
  "conditions": {
    "type": "condition",
    "field": "severity",
    "operator": "eq",
    "value": "anomaly"
  },
  "actions": [
    {
      "type": "send_alert",
      "channel": "telegram",
      "severity": "warning",
      "message_template": "🔍 זוהתה אנומליה!\n\n{{summary}}\n\nמקור: {{source}}"
    }
  ]
}
```

---

## 🏢 ניתוב לפי פרויקט/צוות

### 19. התראות ספציפיות לפרויקט

**מתי להשתמש:** כשרוצים הודעה מותאמת לכל פרויקט.

```json
{
  "name": "התראות פרויקט Mobile App",
  "enabled": true,
  "conditions": {
    "type": "condition",
    "field": "project",
    "operator": "eq",
    "value": "mobile-app"
  },
  "actions": [
    {
      "type": "send_alert",
      "channel": "telegram",
      "severity": "warning",
      "message_template": "📱 [Mobile App] {{summary}}\n\nסביבה: {{environment}}\nחומרה: {{severity}}"
    }
  ]
}
```

---

### 20. השתקת פרויקטים ספציפיים

**מתי להשתמש:** כשיש פרויקטים שלא צריכים התראות (לדוגמה: פרויקטי בדיקה).

```json
{
  "name": "השתק פרויקטי בדיקה",
  "enabled": true,
  "conditions": {
    "type": "condition",
    "field": "project",
    "operator": "in",
    "value": ["test-project", "sandbox", "demo-app", "playground"]
  },
  "actions": [
    {
      "type": "suppress"
    }
  ]
}
```

---

### 21. ניתוב לפי סיומת פרויקט

**מתי להשתמש:** כשיש קונבנציית שמות לפרויקטים (למשל `-prod`, `-staging`).

```json
{
  "name": "השתק פרויקטים שמסתיימים ב-dev",
  "enabled": true,
  "conditions": {
    "type": "condition",
    "field": "project",
    "operator": "ends_with",
    "value": "-dev"
  },
  "actions": [
    {
      "type": "suppress"
    }
  ]
}
```

---

## 🔤 כללים מתקדמים עם Regex

### 22. זיהוי שגיאות Timeout

**מתי להשתמש:** כשרוצים לתפוס כל סוגי שגיאות ה-Timeout.

```json
{
  "name": "זהה שגיאות Timeout",
  "enabled": true,
  "conditions": {
    "type": "condition",
    "field": "error_message",
    "operator": "regex",
    "value": "(?i)(timeout|timed out|connection reset|read timeout)"
  },
  "actions": [
    {
      "type": "send_alert",
      "channel": "telegram",
      "severity": "warning",
      "message_template": "⏱️ זוהתה שגיאת Timeout!\n\n{{error_message}}\n\nמיקום: {{culprit}}"
    }
  ]
}
```

---

### 23. זיהוי שגיאות Database

**מתי להשתמש:** כשרוצים לתפוס שגיאות מסד נתונים.

```json
{
  "name": "שגיאות Database",
  "enabled": true,
  "conditions": {
    "type": "condition",
    "field": "error_message",
    "operator": "regex",
    "value": "(?i)(database|mongodb|mysql|postgres|sql|connection pool|deadlock)"
  },
  "actions": [
    {
      "type": "send_alert",
      "channel": "telegram",
      "severity": "critical",
      "message_template": "🗄️ שגיאת Database!\n\n{{error_message}}\n\nפרויקט: {{project}}"
    },
    {
      "type": "create_github_issue",
      "title_template": "[DB] {{summary}}",
      "severity": "critical"
    }
  ]
}
```

---

### 24. זיהוי שגיאות אימות

**מתי להשתמש:** כשרוצים לעקוב אחרי שגיאות אימות/הרשאות.

```json
{
  "name": "שגיאות אימות",
  "enabled": true,
  "conditions": {
    "type": "condition",
    "field": "error_message",
    "operator": "regex",
    "value": "(?i)(unauthorized|forbidden|authentication|invalid token|expired token|access denied)"
  },
  "actions": [
    {
      "type": "send_alert",
      "channel": "telegram",
      "severity": "warning",
      "message_template": "🔐 שגיאת אימות!\n\n{{error_message}}\n\nמקור: {{source}}"
    }
  ]
}
```

---

### 25. זיהוי OutOfMemory או Resource Exhaustion

**מתי להשתמש:** כשרוצים לתפוס בעיות משאבים.

```json
{
  "name": "בעיות משאבים",
  "enabled": true,
  "conditions": {
    "type": "condition",
    "field": "error_message",
    "operator": "regex",
    "value": "(?i)(out of memory|oom|memory limit|heap|gc overhead|resource exhausted|too many)"
  },
  "actions": [
    {
      "type": "send_alert",
      "channel": "telegram",
      "severity": "critical",
      "message_template": "💾 בעיית משאבים!\n\n{{error_message}}\n\nסביבה: {{environment}}\nפרויקט: {{project}}"
    },
    {
      "type": "create_github_issue",
      "title_template": "[Resources] {{summary}}",
      "severity": "critical"
    }
  ]
}
```

---

## 🔗 כללים משולבים (מתקדם)

### 26. כלל מורכב: התראה מותאמת לפי חומרה + סביבה + זמן

**מתי להשתמש:** כשרוצים לוגיקה מורכבת.

```json
{
  "name": "התראה חכמה מותאמת",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "OR",
    "children": [
      {
        "type": "group",
        "operator": "AND",
        "children": [
          {
            "type": "condition",
            "field": "severity",
            "operator": "eq",
            "value": "critical"
          },
          {
            "type": "condition",
            "field": "environment",
            "operator": "eq",
            "value": "production"
          }
        ]
      },
      {
        "type": "group",
        "operator": "AND",
        "children": [
          {
            "type": "condition",
            "field": "severity",
            "operator": "eq",
            "value": "warning"
          },
          {
            "type": "condition",
            "field": "environment",
            "operator": "eq",
            "value": "production"
          },
          {
            "type": "condition",
            "field": "hour_of_day",
            "operator": "gte",
            "value": 8
          },
          {
            "type": "condition",
            "field": "hour_of_day",
            "operator": "lte",
            "value": 18
          }
        ]
      }
    ]
  },
  "actions": [
    {
      "type": "send_alert",
      "channel": "telegram",
      "severity": "warning",
      "message_template": "📢 {{severity}}: {{summary}}\n\nסביבה: {{environment}}\nשעה: {{hour_of_day}}:00"
    }
  ]
}
```

> **הסבר:** 
> - שגיאות קריטיות בפרודקשן - תמיד מתריעים
> - שגיאות Warning בפרודקשן - רק בשעות העבודה (08:00-18:00)

---

### 27. NOT: כל מה שלא מפרודקשן

**מתי להשתמש:** כשרוצים להשתיק הכל חוץ מפרודקשן.

```json
{
  "name": "השתק מה שלא פרודקשן",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "NOT",
    "children": [
      {
        "type": "condition",
        "field": "environment",
        "operator": "eq",
        "value": "production"
      }
    ]
  },
  "actions": [
    {
      "type": "suppress"
    }
  ]
}
```

---

## 📌 טיפים ושיטות עבודה מומלצות

### סדר הכללים
כללי `suppress` צריכים להיות ראשונים - הם עוצרים את ההתראה לגמרי.

### בדיקה לפני הפעלה
תמיד השתמשו בסימולטור (כפתור Test) לפני שמפעילים כלל חדש.

### התחילו פשוט
התחילו עם כלל פשוט ובנו בהדרגה לוגיקה מורכבת יותר.

### שמות ברורים
תנו שמות ברורים לכללים שמתארים מה הם עושים.

### Regex בזהירות
אופרטור `regex` יכול להאט את הביצועים. השתמשו בו רק כשצריך.

---

## 🔗 קישורים

- [מדריך מנוע הכללים המלא](./VISUAL_RULE_ENGINE_GUIDE.md)
- [תיעוד טכני](../docs/visual-rule-engine.rst)
- [API Reference](../docs/_build/html/visual-rule-engine.html)
