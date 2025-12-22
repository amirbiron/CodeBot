# מדריך מימוש: מנוע כללים ויזואלי (Visual Rule Engine)

> **מטרה:** לאפשר למשתמשים לבנות כללי התראה מורכבים בממשק Drag & Drop, ללא צורך בכתיבת קוד.

---

## ⚠️ הערות חשובות לפני מימוש

> **תאימות עם הפרויקט הקיים:**
>
> - **מיקום ה-API:** הפרויקט משתמש ב-**Flask** (`webapp/app.py`) כשרת ה-WebApp הראשי, ולא ב-aiohttp.
>   ה-aiohttp (`services/webserver.py`) משמש לשירותים פנימיים (metrics, health, Sentry webhook) ולא ל-UI.
>   **לכן: ה-API של מנוע הכללים יתווסף ל-Flask (`webapp/app.py` או Blueprint נפרד).**
>
> - **מסד הנתונים:** הפרויקט משתמש ב-**PyMongo סינכרוני** (לא Motor async).
>   **לכן: הקוד צריך להיות סינכרוני עם `get_db()` הקיים ב-webapp.**
>
> - **עיצוב:** הפרויקט לא משתמש ב-Bootstrap אלא ב-CSS מותאם אישית + Font Awesome.
>   **לכן: התבניות יורשות מ-`base.html` ומשתמשות במשתני ה-CSS הקיימים.**

---

## 📝 שינויים מגרסה קודמת (2025-12-22)

| # | תיקון | פירוט |
|---|-------|-------|
| 1 | **מיקום ה-API** | שונה מ-aiohttp (`services/webserver.py`) ל-**Flask Blueprint** (`webapp/rules_api.py`) |
| 2 | **סוג ה-DB** | שונה ממודל async (Motor) ל-**PyMongo סינכרוני** (תואם ל-Flask) |
| 3 | **NOT operator** | נוספה תמיכה מלאה ב-**קבוצת NOT** בפרונט (כפתור, עיצוב, לוגיקה) |
| 4 | **אופרטורים נוספים** | נוספו: `not_contains`, `starts_with`, `ends_with`, `in`, `not_in` לרשימת האופרטורים ב-UI |
| 5 | **שדות Action** | הובהרו שדות ה-Action: `type` (חובה), `severity` (חובה), `channel`, `message_template` (אופציונלי) |
| 6 | **אינטגרציה עם התראות** | תוקן למבנה הקיים (`name`, `severity`, `summary`, `details`) + מיפוי שדות מפורש |
| 7 | **URL encoding** | תוקן ב-`_find_existing_issue` - שימוש ב-`urllib.parse.quote` |
| 8 | **Bootstrap → CSS קיים** | התבנית שוכתבה ללא Bootstrap, עם סגנונות מותאמים ו-Modal פשוט |
| 9 | **admin_required** | תוקן לבדוק גם login וגם `ADMIN_USER_IDS` (לא רק login!) |
| 10 | **asyncio.run nested** | תוקן `_create_github_issue` - שימוש ב-`ThreadPoolExecutor` במקום `asyncio.run()` |

---

## 📋 תוכן עניינים

1. [סקירה כללית](#סקירה-כללית)
2. [מבנה JSON לכללים](#מבנה-json-לכללים)
3. [Backend - מימוש Python](#backend---מימוש-python)
4. [Frontend - ממשק Drag & Drop](#frontend---ממשק-drag--drop)
5. [אינטגרציה עם המערכת הקיימת](#אינטגרציה-עם-המערכת-הקיימת)
6. [API Endpoints](#api-endpoints)
7. [דוגמאות שימוש](#דוגמאות-שימוש)
8. [בדיקות](#בדיקות)

---

## סקירה כללית

### הרעיון המרכזי

המערכת מאפשרת בניית כללי "אם-אז" (If-This-Then-That) מורכבים באופן ויזואלי:

```
אם (שיעור השגיאות > 5% וגם תעבורה > 1000 בקשות/דקה) 
או (Latency > 500ms)
אז → שלח התראה קריטית לצוות DevOps
```

### סוגי אבני בניין

| סוג | תפקיד | דוגמה |
|-----|-------|-------|
| **Condition** | בדיקה בסיסית: שדה + אופרטור + ערך | `latency > 500` |
| **Group** | אופרטור לוגי שמחבר תנאים | `AND`, `OR` |
| **Action** | מה קורה כשהתנאים מתקיימים | `send_alert`, `create_ticket` |

---

## מבנה JSON לכללים

### סכמה בסיסית

```json
{
  "version": 1,
  "rule_id": "rule_12345",
  "name": "High Error Rate Alert",
  "description": "התראה על שיעור שגיאות גבוה בשילוב עם עומס",
  "enabled": true,
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:00Z",
  "created_by": "user_id",
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
            "field": "error_rate",
            "operator": "gt",
            "value": 0.05
          },
          {
            "type": "condition",
            "field": "requests_per_minute",
            "operator": "gt",
            "value": 1000
          }
        ]
      },
      {
        "type": "condition",
        "field": "latency_avg_ms",
        "operator": "gt",
        "value": 500
      }
    ]
  },
  "actions": [
    {
      "type": "send_alert",
      "severity": "critical",
      "channel": "devops",
      "message_template": "🚨 {{rule_name}}: {{triggered_conditions}}"
    }
  ],
  "metadata": {
    "tags": ["production", "api"],
    "cooldown_minutes": 15
  }
}
```

### סוגי Operators נתמכים

```python
CONDITION_OPERATORS = {
    "eq": "שווה ל",
    "ne": "שונה מ",
    "gt": "גדול מ",
    "gte": "גדול או שווה ל",
    "lt": "קטן מ",
    "lte": "קטן או שווה ל",
    "contains": "מכיל",
    "not_contains": "לא מכיל",
    "starts_with": "מתחיל ב",
    "ends_with": "מסתיים ב",
    "regex": "תואם ביטוי רגולרי",
    "in": "נמצא ברשימה",
    "not_in": "לא נמצא ברשימה"
}

LOGICAL_OPERATORS = {
    "AND": "כל התנאים חייבים להתקיים",
    "OR": "לפחות תנאי אחד חייב להתקיים",
    "NOT": "היפוך התנאי"
}
```

### שדות זמינים (מבוסס על המערכת הקיימת)

> **🔧 תיקון קריטי:** השדות מתאימים למבנה ההתראות הקיים ב-`monitoring/alerts_storage.py`.
> ראה גם את `services/rules_evaluator.py` לפירוט המיפוי המלא.

```python
AVAILABLE_FIELDS = {
    # === שדות בסיסיים מההתראות (monitoring/alerts_storage.py) ===
    "alert_name": {
        "type": "string", 
        "label": "שם ההתראה",
        "description": "שם ההתראה כפי שמופיע ב-internal_alerts"
    },
    "severity": {
        "type": "string", 
        "label": "רמת חומרה",
        "description": "info, warning, critical, anomaly",
        "enum": ["info", "warning", "critical", "anomaly"]
    },
    "summary": {
        "type": "string", 
        "label": "תיאור קצר",
        "description": "תיאור ההתראה"
    },
    "source": {
        "type": "string", 
        "label": "מקור",
        "description": "מקור ההתראה (sentry, internal, external)"
    },
    "is_silenced": {
        "type": "boolean", 
        "label": "מושתק",
        "description": "האם ההתראה הושתקה"
    },
    
    # === שדות מ-details (מידע מפורט) ===
    "alert_type": {
        "type": "string", 
        "label": "סוג התראה",
        "description": "sentry_issue, deployment_event, וכו'"
    },
    "sentry_issue_id": {
        "type": "string", 
        "label": "Sentry Issue ID",
        "description": "מזהה ה-Issue ב-Sentry"
    },
    "sentry_short_id": {
        "type": "string", 
        "label": "Sentry Short ID",
        "description": "מזהה קצר כמו PROJECT-123"
    },
    "project": {
        "type": "string", 
        "label": "פרויקט",
        "description": "שם הפרויקט (Sentry/GitLab)"
    },
    "environment": {
        "type": "string", 
        "label": "סביבה",
        "description": "production, staging, development"
    },
    "error_signature": {
        "type": "string", 
        "label": "חתימת שגיאה",
        "description": "Hash ייחודי לזיהוי שגיאות חוזרות"
    },
    "culprit": {
        "type": "string", 
        "label": "מיקום השגיאה",
        "description": "הפונקציה/קובץ שגרם לשגיאה"
    },
    "action": {
        "type": "string", 
        "label": "פעולה",
        "description": "triggered, resolved, וכו'"
    },
    
    # === שדות זמן (מחושבים) ===
    "hour_of_day": {
        "type": "int", 
        "label": "שעה ביום", 
        "min": 0, 
        "max": 23,
        "description": "שעה נוכחית (UTC)"
    },
    "day_of_week": {
        "type": "int", 
        "label": "יום בשבוע", 
        "min": 0, 
        "max": 6,
        "description": "0=ראשון, 6=שבת"
    }
}
```

---

## Backend - מימוש Python

### קובץ: `services/rule_engine.py`

```python
"""
Visual Rule Engine - מנוע כללים ויזואלי
==========================================
מאפשר הגדרת כללי התראה מורכבים בפורמט JSON והרצתם על נתונים בזמן אמת.
"""

from __future__ import annotations

import re
import logging
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# =============================================================================
# מבני נתונים
# =============================================================================

@dataclass
class EvaluationContext:
    """הקשר להערכת כללים - מכיל את כל הנתונים הזמינים."""
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """תוצאת הערכת כלל."""
    rule_id: str
    matched: bool
    triggered_conditions: List[str]
    actions_to_execute: List[Dict[str, Any]]
    evaluation_time_ms: float
    error: Optional[str] = None


# =============================================================================
# אופרטורים
# =============================================================================

class ConditionOperators:
    """אוסף פונקציות השוואה לתנאים."""
    
    @staticmethod
    def eq(actual: Any, expected: Any) -> bool:
        return actual == expected
    
    @staticmethod
    def ne(actual: Any, expected: Any) -> bool:
        return actual != expected
    
    @staticmethod
    def gt(actual: Any, expected: Any) -> bool:
        return float(actual) > float(expected)
    
    @staticmethod
    def gte(actual: Any, expected: Any) -> bool:
        return float(actual) >= float(expected)
    
    @staticmethod
    def lt(actual: Any, expected: Any) -> bool:
        return float(actual) < float(expected)
    
    @staticmethod
    def lte(actual: Any, expected: Any) -> bool:
        return float(actual) <= float(expected)
    
    @staticmethod
    def contains(actual: Any, expected: Any) -> bool:
        return str(expected) in str(actual)
    
    @staticmethod
    def not_contains(actual: Any, expected: Any) -> bool:
        return str(expected) not in str(actual)
    
    @staticmethod
    def starts_with(actual: Any, expected: Any) -> bool:
        return str(actual).startswith(str(expected))
    
    @staticmethod
    def ends_with(actual: Any, expected: Any) -> bool:
        return str(actual).endswith(str(expected))
    
    @staticmethod
    def regex(actual: Any, expected: Any) -> bool:
        """
        התאמת ביטוי רגולרי עם הגנות מפני ReDoS.
        
        🔧 תיקון באג #2: מניעת ReDoS (Regular Expression Denial of Service)
        - הגבלת אורך הדפוס למניעת דפוסים מורכבים מדי
        - הגבלת אורך המחרוזת הנבדקת
        - Timeout באמצעות signal (Linux) או חלופה
        """
        import signal
        
        MAX_PATTERN_LENGTH = 200
        MAX_INPUT_LENGTH = 10000
        REGEX_TIMEOUT_SECONDS = 1
        
        pattern_str = str(expected)
        actual_str = str(actual)
        
        # בדיקות אורך בסיסיות
        if len(pattern_str) > MAX_PATTERN_LENGTH:
            logger.warning(f"Regex pattern too long ({len(pattern_str)} chars), rejecting")
            return False
        if len(actual_str) > MAX_INPUT_LENGTH:
            logger.warning(f"Input too long for regex ({len(actual_str)} chars), truncating")
            actual_str = actual_str[:MAX_INPUT_LENGTH]
        
        # זיהוי דפוסים מסוכנים (catastrophic backtracking)
        dangerous_patterns = [
            r'\(\.\+\)\+',      # (a+)+
            r'\(\.\*\)\+',      # (.*)+
            r'\(\[.+\]\+\)\+',  # ([a-z]+)+
            r'\(\.\+\)\*',      # (a+)*
        ]
        for dangerous in dangerous_patterns:
            if re.search(dangerous, pattern_str):
                logger.warning(f"Potentially dangerous regex pattern detected, rejecting")
                return False
        
        def timeout_handler(signum, frame):
            raise TimeoutError("Regex evaluation timed out")
        
        try:
            # נסה להגדיר timeout (עובד רק על Linux/Unix)
            old_handler = None
            try:
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(REGEX_TIMEOUT_SECONDS)
            except (ValueError, AttributeError):
                # Windows או סביבה ללא תמיכה ב-signal
                pass
            
            try:
                result = bool(re.search(pattern_str, actual_str))
            finally:
                # ביטול ה-alarm
                try:
                    signal.alarm(0)
                    if old_handler is not None:
                        signal.signal(signal.SIGALRM, old_handler)
                except (ValueError, AttributeError):
                    pass
            
            return result
            
        except TimeoutError:
            logger.error(f"Regex evaluation timed out for pattern: {pattern_str[:50]}...")
            return False
        except re.error as e:
            logger.warning(f"Invalid regex pattern: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error in regex evaluation: {e}")
            return False
    
    @staticmethod
    def in_list(actual: Any, expected: List[Any]) -> bool:
        return actual in expected
    
    @staticmethod
    def not_in_list(actual: Any, expected: List[Any]) -> bool:
        return actual not in expected
    
    @classmethod
    def get_operator(cls, name: str) -> Optional[Callable]:
        """מחזיר פונקציית אופרטור לפי שם."""
        operators = {
            "eq": cls.eq,
            "ne": cls.ne,
            "gt": cls.gt,
            "gte": cls.gte,
            "lt": cls.lt,
            "lte": cls.lte,
            "contains": cls.contains,
            "not_contains": cls.not_contains,
            "starts_with": cls.starts_with,
            "ends_with": cls.ends_with,
            "regex": cls.regex,
            "in": cls.in_list,
            "not_in": cls.not_in_list,
        }
        return operators.get(name)


# =============================================================================
# מנוע הערכת כללים
# =============================================================================

class RuleEngine:
    """
    מנוע להערכת כללים מורכבים.
    
    דוגמה לשימוש:
    ```python
    engine = RuleEngine()
    rule = {...}  # JSON rule definition
    context = EvaluationContext(data={"error_rate": 0.08, "latency_avg_ms": 600})
    result = engine.evaluate(rule, context)
    if result.matched:
        for action in result.actions_to_execute:
            execute_action(action)
    ```
    """
    
    def __init__(self):
        self._validators: Dict[str, Callable] = {}
        self._action_handlers: Dict[str, Callable] = {}
    
    def register_action_handler(self, action_type: str, handler: Callable) -> None:
        """רישום handler לסוג פעולה."""
        self._action_handlers[action_type] = handler
    
    def evaluate(self, rule: Dict[str, Any], context: EvaluationContext) -> EvaluationResult:
        """
        מעריך כלל על הקשר נתון.
        
        Args:
            rule: הגדרת הכלל בפורמט JSON
            context: הקשר הערכה עם הנתונים
            
        Returns:
            EvaluationResult עם תוצאות ההערכה
        """
        import time
        start_time = time.perf_counter()
        
        rule_id = rule.get("rule_id", "unknown")
        triggered_conditions: List[str] = []
        
        try:
            # בדיקה אם הכלל מופעל
            if not rule.get("enabled", True):
                return EvaluationResult(
                    rule_id=rule_id,
                    matched=False,
                    triggered_conditions=[],
                    actions_to_execute=[],
                    evaluation_time_ms=(time.perf_counter() - start_time) * 1000
                )
            
            # הערכת התנאים
            conditions = rule.get("conditions", {})
            matched = self._evaluate_node(conditions, context, triggered_conditions)
            
            # החזרת התוצאה
            actions = rule.get("actions", []) if matched else []
            
            return EvaluationResult(
                rule_id=rule_id,
                matched=matched,
                triggered_conditions=triggered_conditions,
                actions_to_execute=actions,
                evaluation_time_ms=(time.perf_counter() - start_time) * 1000
            )
            
        except Exception as e:
            logger.error(f"Error evaluating rule {rule_id}: {e}")
            return EvaluationResult(
                rule_id=rule_id,
                matched=False,
                triggered_conditions=[],
                actions_to_execute=[],
                evaluation_time_ms=(time.perf_counter() - start_time) * 1000,
                error=str(e)
            )
    
    def _evaluate_node(
        self, 
        node: Dict[str, Any], 
        context: EvaluationContext,
        triggered: List[str]
    ) -> bool:
        """מעריך צומת בעץ התנאים (רקורסיבי)."""
        node_type = node.get("type")
        
        if node_type == "condition":
            return self._evaluate_condition(node, context, triggered)
        elif node_type == "group":
            return self._evaluate_group(node, context, triggered)
        else:
            logger.warning(f"Unknown node type: {node_type}")
            return False
    
    def _evaluate_condition(
        self, 
        condition: Dict[str, Any], 
        context: EvaluationContext,
        triggered: List[str]
    ) -> bool:
        """מעריך תנאי בודד."""
        field_name = condition.get("field", "")
        operator_name = condition.get("operator", "")
        expected_value = condition.get("value")
        
        # קבלת הערך מההקשר
        actual_value = context.data.get(field_name)
        if actual_value is None:
            logger.debug(f"Field '{field_name}' not found in context")
            return False
        
        # קבלת פונקציית האופרטור
        operator_func = ConditionOperators.get_operator(operator_name)
        if operator_func is None:
            logger.warning(f"Unknown operator: {operator_name}")
            return False
        
        # הערכת התנאי
        try:
            result = operator_func(actual_value, expected_value)
            if result:
                triggered.append(f"{field_name} {operator_name} {expected_value}")
            return result
        except Exception as e:
            logger.error(f"Error evaluating condition: {e}")
            return False
    
    def _evaluate_group(
        self, 
        group: Dict[str, Any], 
        context: EvaluationContext,
        triggered: List[str]
    ) -> bool:
        """מעריך קבוצת תנאים עם אופרטור לוגי."""
        operator = group.get("operator", "AND").upper()
        children = group.get("children", [])
        
        if not children:
            return True
        
        # 🔧 תיקון באג #1: הימנעות מ-Short-circuit evaluation
        # הערכת כל הילדים מראש כדי לאסוף את כל התנאים שהותאמו
        # (all/any עם generator מפסיקים בתוצאה הראשונה שקובעת)
        
        if operator == "AND":
            child_results = [
                self._evaluate_node(child, context, triggered) 
                for child in children
            ]
            return all(child_results)
        elif operator == "OR":
            child_results = [
                self._evaluate_node(child, context, triggered) 
                for child in children
            ]
            return any(child_results)
        elif operator == "NOT":
            # 🔧 תיקון באג #6: NOT לא מוסיף תנאים שגויים ל-triggered
            # אם הילד מתאים (True), ה-NOT מחזיר False - אז לא נוסיף ל-triggered
            if children:
                # הערכה לרשימה זמנית כדי לא לזהם את triggered
                temp_triggered: List[str] = []
                child_result = self._evaluate_node(children[0], context, temp_triggered)
                not_result = not child_result
                
                # רק אם NOT מחזיר True (כלומר הילד לא התאים), נתעד את זה
                if not_result and temp_triggered:
                    triggered.append(f"NOT({', '.join(temp_triggered)})")
                elif not_result:
                    triggered.append("NOT(condition not matched)")
                    
                return not_result
            return True
        else:
            logger.warning(f"Unknown logical operator: {operator}")
            return False
    
    def validate_rule(self, rule: Dict[str, Any]) -> List[str]:
        """
        מאמת תקינות כלל.
        
        Returns:
            רשימת שגיאות (ריקה אם הכלל תקין)
        """
        errors: List[str] = []
        
        # בדיקת שדות חובה
        required_fields = ["rule_id", "name", "conditions"]
        for field in required_fields:
            if field not in rule:
                errors.append(f"Missing required field: {field}")
        
        # בדיקת מבנה התנאים
        conditions = rule.get("conditions", {})
        self._validate_node(conditions, errors, path="conditions")
        
        # בדיקת פעולות
        actions = rule.get("actions", [])
        for i, action in enumerate(actions):
            if "type" not in action:
                errors.append(f"Action {i}: missing 'type' field")
        
        return errors
    
    def _validate_node(
        self, 
        node: Dict[str, Any], 
        errors: List[str], 
        path: str
    ) -> None:
        """מאמת צומת בעץ התנאים (רקורסיבי)."""
        node_type = node.get("type")
        
        if node_type == "condition":
            if "field" not in node:
                errors.append(f"{path}: condition missing 'field'")
            if "operator" not in node:
                errors.append(f"{path}: condition missing 'operator'")
            if "value" not in node:
                errors.append(f"{path}: condition missing 'value'")
            
            # בדיקת אופרטור תקין
            op = node.get("operator")
            if op and ConditionOperators.get_operator(op) is None:
                errors.append(f"{path}: unknown operator '{op}'")
                
        elif node_type == "group":
            operator = node.get("operator", "").upper()
            if operator not in ("AND", "OR", "NOT"):
                errors.append(f"{path}: invalid group operator '{operator}'")
            
            children = node.get("children", [])
            for i, child in enumerate(children):
                self._validate_node(child, errors, f"{path}.children[{i}]")
        else:
            errors.append(f"{path}: unknown node type '{node_type}'")


# =============================================================================
# Singleton instance
# =============================================================================

_engine: Optional[RuleEngine] = None

def get_rule_engine() -> RuleEngine:
    """מחזיר את מנוע הכללים (singleton)."""
    global _engine
    if _engine is None:
        _engine = RuleEngine()
    return _engine
```

### קובץ: `services/rules_storage.py`

> **שינוי קריטי:** הקוד הוא **סינכרוני** (PyMongo) ולא async (Motor), כדי להתאים ל-Flask ולתשתית הקיימת.

```python
"""
Rules Storage - אחסון כללים ב-MongoDB (סינכרוני)
=================================================
מספק ממשק לשמירה, טעינה ועדכון כללים.

🔧 הערה: הפרויקט משתמש ב-PyMongo (sync), לא ב-Motor (async).
   לכן כל הפונקציות הן סינכרוניות.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# הגדרות ברירת מחדל
RULES_COLLECTION = "visual_rules"


class RulesStorage:
    """
    מנהל אחסון כללים ב-MongoDB.
    
    משתלב עם תשתית ה-MongoDB הקיימת (ראה monitoring/alerts_storage.py).
    
    🔧 שימוש:
    ```python
    from webapp.app import get_db
    storage = RulesStorage(get_db())
    rules = storage.list_rules()
    ```
    """
    
    def __init__(self, db):
        """
        Args:
            db: MongoDB database instance (מתקבל מ-get_db() ב-webapp/app.py)
        """
        self._db = db
        self._collection = db[RULES_COLLECTION]
        self._ensure_indexes()
    
    def _ensure_indexes(self) -> None:
        """יצירת אינדקסים נדרשים."""
        try:
            self._collection.create_index("rule_id", unique=True)
            self._collection.create_index("enabled")
            self._collection.create_index("metadata.tags")
            self._collection.create_index("created_by")
        except Exception as e:
            logger.error(f"Failed to create indexes: {e}")
    
    def save_rule(self, rule: Dict[str, Any]) -> str:
        """שומר או מעדכן כלל (sync)."""
        rule_id = rule.get("rule_id")
        if not rule_id:
            rule_id = f"rule_{uuid.uuid4().hex[:12]}"
            rule["rule_id"] = rule_id
        
        now = datetime.now(timezone.utc)
        rule["updated_at"] = now.isoformat()
        if "created_at" not in rule:
            rule["created_at"] = now.isoformat()
        
        self._collection.update_one(
            {"rule_id": rule_id},
            {"$set": rule},
            upsert=True
        )
        
        logger.info(f"Saved rule: {rule_id}")
        return rule_id
    
    def get_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """מחזיר כלל לפי ID (sync)."""
        doc = self._collection.find_one({"rule_id": rule_id})
        if doc:
            doc.pop("_id", None)
        return doc
    
    def get_enabled_rules(self) -> List[Dict[str, Any]]:
        """מחזיר את כל הכללים הפעילים (sync)."""
        cursor = self._collection.find({"enabled": True})
        rules = []
        for doc in cursor:
            doc.pop("_id", None)
            rules.append(doc)
        return rules
    
    def list_rules(
        self,
        enabled_only: bool = False,
        tags: Optional[List[str]] = None,
        created_by: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """מחזיר רשימת כללים עם סינון (sync)."""
        query: Dict[str, Any] = {}
        
        if enabled_only:
            query["enabled"] = True
        if tags:
            query["metadata.tags"] = {"$all": tags}
        if created_by:
            query["created_by"] = created_by
        
        cursor = (
            self._collection.find(query)
            .skip(offset)
            .limit(limit)
            .sort("updated_at", -1)
        )
        
        rules = []
        for doc in cursor:
            doc.pop("_id", None)
            rules.append(doc)
        return rules
    
    def delete_rule(self, rule_id: str) -> bool:
        """מוחק כלל (sync)."""
        result = self._collection.delete_one({"rule_id": rule_id})
        deleted = result.deleted_count > 0
        if deleted:
            logger.info(f"Deleted rule: {rule_id}")
        return deleted
    
    def toggle_rule(self, rule_id: str, enabled: bool) -> bool:
        """מפעיל/מכבה כלל (sync)."""
        result = self._collection.update_one(
            {"rule_id": rule_id},
            {"$set": {"enabled": enabled, "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        return result.modified_count > 0
    
    def count_rules(self, enabled_only: bool = False) -> int:
        """מחזיר מספר הכללים (sync)."""
        query = {"enabled": True} if enabled_only else {}
        return self._collection.count_documents(query)


# =============================================================================
# Factory function - תואם ל-Flask/PyMongo
# =============================================================================

_storage: Optional[RulesStorage] = None

def get_rules_storage(db=None) -> RulesStorage:
    """
    מחזיר את מנהל האחסון (singleton).
    
    Args:
        db: אופציונלי - אם לא מועבר, משתמש ב-get_db() מ-webapp/app.py
        
    🔧 שימוש ב-Flask route:
    ```python
    @app.route('/api/rules')
    def rules_list():
        storage = get_rules_storage(get_db())
        return jsonify(storage.list_rules())
    ```
    """
    global _storage
    if _storage is None:
        if db is None:
            # Lazy import כדי למנוע circular imports
            from webapp.app import get_db
            db = get_db()
        _storage = RulesStorage(db)
    return _storage
```

---

## Frontend - ממשק Drag & Drop

### קובץ: `webapp/static/js/rule-builder.js`

```javascript
/**
 * Visual Rule Builder
 * ממשק Drag & Drop לבניית כללים ויזואליים
 */

class RuleBuilder {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.options = {
            onRuleChange: () => {},
            availableFields: [],
            availableActions: [],
            ...options
        };
        
        this.rule = {
            conditions: { type: 'group', operator: 'AND', children: [] },
            actions: []
        };
        
        this.init();
    }
    
    /**
     * 🔧 תיקון באג #3: פונקציית Escape למניעת XSS
     * מקודדת תווים מיוחדים ב-HTML כדי למנוע הזרקת סקריפטים
     */
    htmlEscape(str) {
        if (str === null || str === undefined) return '';
        if (typeof str !== 'string') str = String(str);
        
        const escapeMap = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;',
            '/': '&#x2F;',
            '`': '&#x60;',
            '=': '&#x3D;'
        };
        
        return str.replace(/[&<>"'`=\/]/g, char => escapeMap[char]);
    }
    
    init() {
        // 🔧 תיקון: הוספת כפתור NOT לממשק
        this.container.innerHTML = `
            <div class="rule-builder">
                <div class="rule-builder__toolbar">
                    <button class="btn btn-sm" data-add="condition">+ תנאי</button>
                    <button class="btn btn-sm" data-add="group-and">+ קבוצת AND</button>
                    <button class="btn btn-sm" data-add="group-or">+ קבוצת OR</button>
                    <button class="btn btn-sm" data-add="group-not">🚫 קבוצת NOT</button>
                    <button class="btn btn-sm" data-add="action">+ פעולה</button>
                </div>
                <div class="rule-builder__canvas" data-drop-zone="root">
                    <div class="conditions-area">
                        <h4>תנאים (IF)</h4>
                        <div class="conditions-container" data-drop-zone="conditions"></div>
                    </div>
                    <div class="actions-area">
                        <h4>פעולות (THEN)</h4>
                        <div class="actions-container" data-drop-zone="actions"></div>
                    </div>
                </div>
                <div class="rule-builder__preview">
                    <h4>תצוגה מקדימה</h4>
                    <pre class="json-preview"></pre>
                </div>
            </div>
        `;
        
        this.setupEventListeners();
        this.setupDragAndDrop();
        this.render();
    }
    
    setupEventListeners() {
        // כפתורי הוספה
        this.container.querySelectorAll('[data-add]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const type = e.target.dataset.add;
                this.addBlock(type);
            });
        });
    }
    
    setupDragAndDrop() {
        // הגדרת Sortable.js או ספריית D&D אחרת
        const conditionsContainer = this.container.querySelector('.conditions-container');
        const actionsContainer = this.container.querySelector('.actions-container');
        
        if (typeof Sortable !== 'undefined') {
            new Sortable(conditionsContainer, {
                group: 'conditions',
                animation: 150,
                ghostClass: 'sortable-ghost',
                onEnd: () => this.syncFromDOM()
            });
            
            new Sortable(actionsContainer, {
                group: 'actions',
                animation: 150,
                ghostClass: 'sortable-ghost',
                onEnd: () => this.syncFromDOM()
            });
        }
    }
    
    addBlock(type) {
        switch (type) {
            case 'condition':
                this.rule.conditions.children.push(this.createCondition());
                break;
            case 'group-and':
                this.rule.conditions.children.push(this.createGroup('AND'));
                break;
            case 'group-or':
                this.rule.conditions.children.push(this.createGroup('OR'));
                break;
            // 🔧 תיקון: הוספת תמיכה ב-NOT operator
            case 'group-not':
                this.rule.conditions.children.push(this.createGroup('NOT'));
                break;
            case 'action':
                this.rule.actions.push(this.createAction());
                break;
        }
        this.render();
        this.notifyChange();
    }
    
    createCondition() {
        return {
            type: 'condition',
            field: '',
            operator: 'eq',
            value: ''
        };
    }
    
    createGroup(operator) {
        return {
            type: 'group',
            operator: operator,
            children: []
        };
    }
    
    /**
     * 🔧 תיקון: שדות Action מלאים בהתאם לסכמה
     * 
     * שדות נדרשים:
     * - type: סוג הפעולה (send_alert, create_ticket, webhook, suppress, create_github_issue)
     * - severity: רמת חומרה (info, warning, critical)
     * 
     * שדות אופציונליים (לפי סוג):
     * - channel: ערוץ יעד (telegram, slack, email)
     * - message_template: תבנית הודעה עם placeholders כמו {{rule_name}}, {{triggered_conditions}}
     * - labels: תגיות (למשל עבור GitHub Issues)
     * - assignees: רשימת assignees (עבור GitHub Issues)
     * - webhook_url: כתובת ה-webhook (עבור type=webhook)
     */
    createAction() {
        return {
            type: 'send_alert',
            severity: 'warning',
            channel: 'default',
            message_template: '🔔 {{rule_name}}: {{triggered_conditions}}'
        };
    }
    
    render() {
        // רינדור תנאים
        const conditionsHtml = this.renderConditions(this.rule.conditions);
        this.container.querySelector('.conditions-container').innerHTML = conditionsHtml;
        
        // רינדור פעולות
        const actionsHtml = this.renderActions(this.rule.actions);
        this.container.querySelector('.actions-container').innerHTML = actionsHtml;
        
        // עדכון תצוגה מקדימה
        this.container.querySelector('.json-preview').textContent = 
            JSON.stringify(this.rule, null, 2);
        
        // הוספת event listeners לאלמנטים חדשים
        this.attachBlockEvents();
    }
    
    renderConditions(node, depth = 0) {
        if (node.type === 'condition') {
            return this.renderConditionBlock(node);
        } else if (node.type === 'group') {
            return this.renderGroupBlock(node, depth);
        }
        return '';
    }
    
    renderConditionBlock(condition) {
        const fields = this.options.availableFields;
        // 🔧 תיקון: רשימה מלאה של כל האופרטורים הנתמכים ב-Backend
        const operators = [
            { value: 'eq', label: '= שווה' },
            { value: 'ne', label: '≠ שונה' },
            { value: 'gt', label: '> גדול מ' },
            { value: 'gte', label: '≥ גדול או שווה' },
            { value: 'lt', label: '< קטן מ' },
            { value: 'lte', label: '≤ קטן או שווה' },
            { value: 'contains', label: 'מכיל' },
            { value: 'not_contains', label: 'לא מכיל' },
            { value: 'starts_with', label: 'מתחיל ב' },
            { value: 'ends_with', label: 'מסתיים ב' },
            { value: 'regex', label: 'RegEx' },
            { value: 'in', label: 'נמצא ברשימה' },
            { value: 'not_in', label: 'לא נמצא ברשימה' }
        ];
        
        return `
            <div class="block condition-block" draggable="true" data-type="condition">
                <div class="block__header">
                    <span class="block__icon">📊</span>
                    <span class="block__title">תנאי</span>
                    <button class="block__delete" data-action="delete">×</button>
                </div>
                <div class="block__content">
                    <select class="field-select" data-bind="field">
                        <option value="">בחר שדה...</option>
                        ${fields.map(f => `
                            <option value="${f.name}" ${condition.field === f.name ? 'selected' : ''}>
                                ${f.label}
                            </option>
                        `).join('')}
                    </select>
                    <select class="operator-select" data-bind="operator">
                        ${operators.map(op => `
                            <option value="${op.value}" ${condition.operator === op.value ? 'selected' : ''}>
                                ${op.label}
                            </option>
                        `).join('')}
                    </select>
                    <input type="text" class="value-input" data-bind="value" 
                           value="${this.htmlEscape(condition.value)}" placeholder="ערך">
                </div>
            </div>
        `;
    }
    
    /**
     * 🔧 תיקון: תמיכה מלאה ב-NOT operator
     * - NOT מקבל רק ילד אחד
     * - עיצוב ייחודי לקבוצת NOT
     */
    renderGroupBlock(group, depth) {
        const operator = group.operator;
        let className, label, icon;
        
        switch (operator) {
            case 'AND':
                className = 'group-and';
                label = 'וגם (AND)';
                icon = '🔗';
                break;
            case 'OR':
                className = 'group-or';
                label = 'או (OR)';
                icon = '🔀';
                break;
            case 'NOT':
                className = 'group-not';
                label = 'היפוך (NOT)';
                icon = '🚫';
                break;
            default:
                className = 'group-and';
                label = operator;
                icon = '❓';
        }
        
        const childrenHtml = group.children
            .map(child => this.renderConditions(child, depth + 1))
            .join('');
        
        // NOT מקבל רק ילד אחד
        const showAddButton = operator !== 'NOT' || group.children.length === 0;
        const hint = operator === 'NOT' 
            ? '<p class="empty-hint">גרור תנאי אחד לכאן (NOT הופך את התוצאה)</p>'
            : '<p class="empty-hint">גרור תנאים לכאן</p>';
        
        return `
            <div class="block group-block ${className}" data-type="group" data-operator="${operator}">
                <div class="block__header">
                    <span class="block__icon">${icon}</span>
                    <span class="block__title">${label}</span>
                    ${showAddButton ? '<button class="block__add-child" data-action="add-condition">+ תנאי</button>' : ''}
                    <button class="block__delete" data-action="delete">×</button>
                </div>
                <div class="block__children" data-drop-zone="group">
                    ${childrenHtml || hint}
                </div>
            </div>
        `;
    }
    
    /**
     * 🔧 תיקון: רינדור Action עם כל השדות הנדרשים
     * 
     * שדות UI מלאים:
     * - type: סוג הפעולה (חובה)
     * - severity: רמת חומרה (חובה)
     * - channel: ערוץ יעד (אופציונלי, מוצג עבור send_alert)
     * - message_template: תבנית הודעה (אופציונלי, מוצג עבור send_alert)
     */
    renderActions(actions) {
        return actions.map((action, index) => {
            const showChannelAndTemplate = action.type === 'send_alert';
            
            return `
                <div class="block action-block" data-type="action" data-index="${index}">
                    <div class="block__header">
                        <span class="block__icon">⚡</span>
                        <span class="block__title">פעולה</span>
                        <button class="block__delete" data-action="delete">×</button>
                    </div>
                    <div class="block__content">
                        <select class="action-type-select" data-bind="type">
                            <option value="send_alert" ${action.type === 'send_alert' ? 'selected' : ''}>
                                📢 שלח התראה
                            </option>
                            <option value="create_github_issue" ${action.type === 'create_github_issue' ? 'selected' : ''}>
                                🐛 צור GitHub Issue
                            </option>
                            <option value="create_ticket" ${action.type === 'create_ticket' ? 'selected' : ''}>
                                🎫 צור טיקט
                            </option>
                            <option value="webhook" ${action.type === 'webhook' ? 'selected' : ''}>
                                🔗 קרא ל-Webhook
                            </option>
                            <option value="suppress" ${action.type === 'suppress' ? 'selected' : ''}>
                                🔇 השתק התראות
                            </option>
                        </select>
                        <select class="severity-select" data-bind="severity">
                            <option value="info" ${action.severity === 'info' ? 'selected' : ''}>ℹ️ Info</option>
                            <option value="warning" ${action.severity === 'warning' ? 'selected' : ''}>⚠️ Warning</option>
                            <option value="critical" ${action.severity === 'critical' ? 'selected' : ''}>🔴 Critical</option>
                        </select>
                        ${showChannelAndTemplate ? `
                            <select class="channel-select" data-bind="channel">
                                <option value="default" ${action.channel === 'default' ? 'selected' : ''}>ברירת מחדל</option>
                                <option value="telegram" ${action.channel === 'telegram' ? 'selected' : ''}>📱 Telegram</option>
                                <option value="slack" ${action.channel === 'slack' ? 'selected' : ''}>💬 Slack</option>
                                <option value="email" ${action.channel === 'email' ? 'selected' : ''}>📧 Email</option>
                            </select>
                            <input type="text" class="message-template-input" data-bind="message_template" 
                                   value="${this.htmlEscape(action.message_template || '')}" 
                                   placeholder="תבנית הודעה: {{rule_name}}, {{triggered_conditions}}">
                        ` : ''}
                    </div>
                </div>
            `;
        }).join('');
    }
    
    attachBlockEvents() {
        // מחיקת בלוקים
        this.container.querySelectorAll('[data-action="delete"]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const block = e.target.closest('.block');
                this.deleteBlock(block);
            });
        });
        
        // שינויים בשדות
        this.container.querySelectorAll('[data-bind]').forEach(input => {
            input.addEventListener('change', () => this.syncFromDOM());
        });
        
        // הוספת תנאי לקבוצה
        this.container.querySelectorAll('[data-action="add-condition"]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const block = e.target.closest('.group-block');
                this.addConditionToGroup(block);
            });
        });
    }
    
    syncFromDOM() {
        // סנכרון מצב ה-DOM חזרה ל-rule object
        // ... (לוגיקה מורכבת יותר בהתאם למבנה)
        this.notifyChange();
    }
    
    deleteBlock(blockElement) {
        // מחיקת בלוק מה-rule
        // ... (לוגיקה למציאת ומחיקת הבלוק)
        this.render();
        this.notifyChange();
    }
    
    addConditionToGroup(groupElement) {
        // הוספת תנאי לקבוצה
        // ... (לוגיקה למציאת הקבוצה והוספת תנאי)
        this.render();
        this.notifyChange();
    }
    
    notifyChange() {
        this.options.onRuleChange(this.rule);
    }
    
    // API ציבורי
    
    getRule() {
        return JSON.parse(JSON.stringify(this.rule));
    }
    
    setRule(rule) {
        this.rule = JSON.parse(JSON.stringify(rule));
        this.render();
    }
    
    validate() {
        const errors = [];
        const conditions = this.rule.conditions;
        
        // 🔧 תיקון באג #4: תמיכה בתנאי בודד (לא רק קבוצה)
        // בדיקת מבנה התנאים - יכול להיות group או condition בודד
        if (!conditions || !conditions.type) {
            errors.push('מבנה התנאים אינו תקין');
        } else if (conditions.type === 'group') {
            // אם זו קבוצה, בדוק שיש לפחות תנאי אחד
            if (!conditions.children || conditions.children.length === 0) {
                errors.push('חובה להוסיף לפחות תנאי אחד לקבוצה');
            }
        } else if (conditions.type === 'condition') {
            // תנאי בודד תקין - ממשיך לבדיקת השדות
        } else {
            errors.push(`סוג תנאי לא מוכר: ${conditions.type}`);
        }
        
        // בדיקת פעולות
        if (this.rule.actions.length === 0) {
            errors.push('חובה להוסיף לפחות פעולה אחת');
        }
        
        // בדיקת שדות חסרים (רקורסיבית)
        if (conditions && conditions.type) {
            this.validateNode(conditions, errors);
        }
        
        return errors;
    }
    
    validateNode(node, errors) {
        if (!node || !node.type) return;
        
        if (node.type === 'condition') {
            if (!node.field) errors.push('תנאי חסר שדה');
            if (node.value === '' || node.value === undefined || node.value === null) {
                errors.push('תנאי חסר ערך');
            }
        } else if (node.type === 'group') {
            // 🔧 בדיקה שיש children לפני הגישה אליהם
            if (node.children && Array.isArray(node.children)) {
                node.children.forEach(child => this.validateNode(child, errors));
            }
        }
    }
}

// ייצוא
if (typeof module !== 'undefined' && module.exports) {
    module.exports = RuleBuilder;
}
```

### קובץ: `webapp/static/css/rule-builder.css`

```css
/* ==========================================================================
   Visual Rule Builder Styles
   ========================================================================== */

.rule-builder {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    font-family: var(--font-family, 'Heebo', sans-serif);
    direction: rtl;
}

/* Toolbar */
.rule-builder__toolbar {
    display: flex;
    gap: 0.5rem;
    padding: 0.75rem;
    background: var(--surface-color, #f8f9fa);
    border-radius: 8px;
    flex-wrap: wrap;
}

.rule-builder__toolbar .btn {
    padding: 0.5rem 1rem;
    border: 1px solid var(--border-color, #dee2e6);
    border-radius: 6px;
    background: var(--bg-color, #fff);
    cursor: pointer;
    transition: all 0.2s;
}

.rule-builder__toolbar .btn:hover {
    background: var(--primary-light, #e3f2fd);
    border-color: var(--primary-color, #2196f3);
}

/* Canvas */
.rule-builder__canvas {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    min-height: 300px;
}

.conditions-area,
.actions-area {
    padding: 1rem;
    background: var(--surface-color, #f8f9fa);
    border-radius: 8px;
    border: 2px dashed var(--border-color, #dee2e6);
}

.conditions-area h4,
.actions-area h4 {
    margin: 0 0 1rem;
    color: var(--text-secondary, #666);
    font-size: 0.875rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.conditions-container,
.actions-container {
    min-height: 200px;
}

/* Blocks */
.block {
    margin-bottom: 0.5rem;
    border-radius: 8px;
    background: var(--bg-color, #fff);
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    cursor: grab;
    transition: all 0.2s;
}

.block:active {
    cursor: grabbing;
}

.block:hover {
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

.block__header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    background: var(--surface-color, #f0f0f0);
    border-radius: 8px 8px 0 0;
    border-bottom: 1px solid var(--border-color, #dee2e6);
}

.block__icon {
    font-size: 1.25rem;
}

.block__title {
    flex: 1;
    font-weight: 500;
}

.block__delete,
.block__add-child {
    padding: 0.25rem 0.5rem;
    border: none;
    border-radius: 4px;
    background: transparent;
    cursor: pointer;
    font-size: 0.875rem;
}

.block__delete:hover {
    background: var(--danger-light, #ffebee);
    color: var(--danger-color, #f44336);
}

.block__add-child:hover {
    background: var(--success-light, #e8f5e9);
    color: var(--success-color, #4caf50);
}

.block__content {
    padding: 0.75rem;
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
}

.block__content select,
.block__content input {
    padding: 0.5rem;
    border: 1px solid var(--border-color, #dee2e6);
    border-radius: 4px;
    font-size: 0.875rem;
    min-width: 100px;
}

/* Condition Block */
.condition-block {
    border-right: 4px solid var(--info-color, #2196f3);
}

/* Group Blocks */
.group-block {
    padding-bottom: 0.5rem;
}

.group-and {
    border-right: 4px solid var(--success-color, #4caf50);
}

.group-or {
    border-right: 4px solid var(--warning-color, #ff9800);
}

/* 🔧 תיקון: עיצוב עבור קבוצת NOT */
.group-not {
    border-right: 4px solid var(--danger-color, #f44336);
    background: var(--danger-light, rgba(244, 67, 54, 0.05));
}

.group-not .block__header {
    background: var(--danger-light, rgba(244, 67, 54, 0.1));
}

.block__children {
    padding: 0.75rem;
    margin: 0 0.5rem 0.5rem;
    background: rgba(0,0,0,0.02);
    border-radius: 6px;
    min-height: 60px;
}

.empty-hint {
    color: var(--text-secondary, #999);
    text-align: center;
    font-size: 0.875rem;
    margin: 1rem 0;
}

/* Action Block */
.action-block {
    border-right: 4px solid var(--secondary-color, #9c27b0);
}

/* Preview */
.rule-builder__preview {
    padding: 1rem;
    background: var(--surface-color, #263238);
    border-radius: 8px;
    color: var(--text-light, #eceff1);
}

.rule-builder__preview h4 {
    margin: 0 0 0.75rem;
    font-size: 0.875rem;
    color: var(--text-secondary, #90a4ae);
}

.json-preview {
    margin: 0;
    padding: 1rem;
    background: var(--code-bg, #1e272c);
    border-radius: 6px;
    font-family: 'Fira Code', monospace;
    font-size: 0.75rem;
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre-wrap;
    color: var(--code-color, #a5d6a7);
}

/* Drag & Drop States */
.sortable-ghost {
    opacity: 0.4;
}

.sortable-chosen {
    box-shadow: 0 8px 24px rgba(0,0,0,0.2);
}

/* Responsive */
@media (max-width: 768px) {
    .rule-builder__canvas {
        grid-template-columns: 1fr;
    }
    
    .block__content {
        flex-direction: column;
    }
    
    .block__content select,
    .block__content input {
        width: 100%;
    }
}
```

---

## API Endpoints

### יצירת Blueprint ב-Flask: `webapp/rules_api.py`

> **שינוי קריטי:** ה-API נוסף כ-**Flask Blueprint** (לא aiohttp) כי הפרויקט משתמש ב-Flask.

```python
"""
Visual Rules API - Flask Blueprint
===================================
API לניהול כללים ויזואליים.

🔧 שימוש: הוסף ל-webapp/app.py:
    from webapp.rules_api import rules_bp
    app.register_blueprint(rules_bp, url_prefix='/api/rules')
"""

from flask import Blueprint, jsonify, request, g
from functools import wraps
import logging

from services.rules_storage import get_rules_storage
from services.rule_engine import get_rule_engine, EvaluationContext, AVAILABLE_FIELDS

logger = logging.getLogger(__name__)

rules_bp = Blueprint('rules', __name__)


def get_db():
    """קבלת חיבור DB (יבוא מ-webapp/app.py)."""
    # Lazy import כדי למנוע circular imports
    from webapp.app import get_db as app_get_db
    return app_get_db()


def admin_required(f):
    """
    דקורטור לבדיקת הרשאות admin.
    
    🔧 חשוב: משתמש בלוגיקה הקיימת של webapp/app.py!
    בודק גם login וגם שהמשתמש נמצא ב-ADMIN_USER_IDS.
    
    אפשרות 1 (מומלצת): שימוש בדקורטור הקיים:
        from webapp.app import admin_required
        
    אפשרות 2: מימוש מקומי (תואם לקיים):
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        import os
        from flask import session, abort
        
        # 1. בדיקת login
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": "unauthorized", "message": "נדרשת התחברות"}), 401
        
        # 2. בדיקת admin (חובה! לא אופציונלי!)
        admin_ids_env = os.getenv('ADMIN_USER_IDS', '')
        admin_ids_list = admin_ids_env.split(',') if admin_ids_env else []
        admin_ids = [int(x.strip()) for x in admin_ids_list if x.strip().isdigit()]
        
        if user_id not in admin_ids:
            return jsonify({"error": "forbidden", "message": "אין הרשאת אדמין"}), 403
        
        return f(*args, **kwargs)
    return decorated


# 🔧 אלטרנטיבה מומלצת: ייבוא הדקורטור הקיים במקום כתיבה מחדש:
# from webapp.app import admin_required


@rules_bp.route('', methods=['GET'])
@admin_required
def rules_list():
    """GET /api/rules - רשימת כללים"""
    storage = get_rules_storage(get_db())
    
    enabled_only = request.args.get("enabled") == "true"
    tags = request.args.getlist("tag")
    
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid limit/offset parameter"}), 400
    
    if limit < 0 or offset < 0:
        return jsonify({"error": "limit and offset must be non-negative"}), 400
    
    rules = storage.list_rules(
        enabled_only=enabled_only,
        tags=tags or None,
        limit=limit,
        offset=offset
    )
    count = storage.count_rules(enabled_only=enabled_only)
    
    return jsonify({
        "rules": rules,
        "total": count,
        "limit": limit,
        "offset": offset
    })


@rules_bp.route('/fields', methods=['GET'])
@admin_required
def rules_available_fields():
    """GET /api/rules/fields - שדות זמינים"""
    fields = [{"name": k, **v} for k, v in AVAILABLE_FIELDS.items()]
    return jsonify({"fields": fields})


@rules_bp.route('/test', methods=['POST'])
@admin_required
def rules_test():
    """POST /api/rules/test - בדיקת כלל על נתוני דמה"""
    try:
        data = request.get_json()
        rule = data.get("rule", {})
        test_data = data.get("data", {})
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400
    
    engine = get_rule_engine()
    errors = engine.validate_rule(rule)
    
    if errors:
        return jsonify({"valid": False, "errors": errors})
    
    context = EvaluationContext(data=test_data)
    result = engine.evaluate(rule, context)
    
    return jsonify({
        "valid": True,
        "matched": result.matched,
        "triggered_conditions": result.triggered_conditions,
        "actions": result.actions_to_execute,
        "evaluation_time_ms": result.evaluation_time_ms
    })


@rules_bp.route('/<rule_id>', methods=['GET'])
@admin_required
def rules_get(rule_id):
    """GET /api/rules/{rule_id} - קבלת כלל ספציפי"""
    storage = get_rules_storage(get_db())
    rule = storage.get_rule(rule_id)
    
    if not rule:
        return jsonify({"error": "Rule not found"}), 404
    
    return jsonify(rule)


@rules_bp.route('', methods=['POST'])
@admin_required
def rules_create():
    """POST /api/rules - יצירת כלל חדש"""
    try:
        data = request.get_json()
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400
    
    engine = get_rule_engine()
    errors = engine.validate_rule(data)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400
    
    storage = get_rules_storage(get_db())
    rule_id = storage.save_rule(data)
    
    return jsonify({"rule_id": rule_id, "message": "Rule created"}), 201


@rules_bp.route('/<rule_id>', methods=['PUT'])
@admin_required
def rules_update(rule_id):
    """PUT /api/rules/{rule_id} - עדכון כלל"""
    try:
        data = request.get_json()
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400
    
    data["rule_id"] = rule_id
    
    engine = get_rule_engine()
    errors = engine.validate_rule(data)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400
    
    storage = get_rules_storage(get_db())
    storage.save_rule(data)
    
    return jsonify({"rule_id": rule_id, "message": "Rule updated"})


@rules_bp.route('/<rule_id>', methods=['DELETE'])
@admin_required
def rules_delete(rule_id):
    """DELETE /api/rules/{rule_id} - מחיקת כלל"""
    storage = get_rules_storage(get_db())
    deleted = storage.delete_rule(rule_id)
    
    if not deleted:
        return jsonify({"error": "Rule not found"}), 404
    
    return jsonify({"message": "Rule deleted"})


@rules_bp.route('/<rule_id>/toggle', methods=['POST'])
@admin_required
def rules_toggle(rule_id):
    """POST /api/rules/{rule_id}/toggle - הפעלה/כיבוי כלל"""
    try:
        data = request.get_json() or {}
        enabled = data.get("enabled", True)
    except Exception:
        enabled = True
    
    storage = get_rules_storage(get_db())
    success = storage.toggle_rule(rule_id, enabled)
    
    if not success:
        return jsonify({"error": "Rule not found"}), 404
    
    return jsonify({"rule_id": rule_id, "enabled": enabled})
```

### רישום ה-Blueprint ב-`webapp/app.py`

```python
# הוסף בסוף הייבואים:
from webapp.rules_api import rules_bp

# הוסף לפני if __name__ == "__main__":
app.register_blueprint(rules_bp, url_prefix='/api/rules')
```

---

## אינטגרציה עם המערכת הקיימת

> **🔧 שינוי קריטי:** האינטגרציה היא **סינכרונית** (תואמת ל-PyMongo ול-Flask).
> 
> **מיפוי שדות:** מערכת ההתראות הקיימת (`monitoring/alerts_storage.py`) משתמשת בשדות:
> - `name` - שם ההתראה
> - `severity` - רמת חומרה (info/warning/critical/anomaly)
> - `summary` - תיאור קצר
> - `details` - dict עם פרטים נוספים (כולל sentry_issue_id, error_signature, וכו')
> - `alert_type` - סוג ההתראה (sentry_issue, deployment_event, וכו')
> - `endpoint` - endpoint רלוונטי (אם קיים)
> - `silenced` - האם ההתראה הושתקה

### 1. שילוב עם `internal_alerts.py`

נקודת החיבור הטובה ביותר היא `internal_alerts.py` שמטפל בהתראות לפני שליחה:

```python
# יצירת קובץ חדש: services/rules_evaluator.py

"""
Rules Evaluator - הערכת כללים על התראות נכנסות
================================================
מחבר בין מערכת ההתראות לבין מנוע הכללים.

🔧 הערה: סינכרוני לחלוטין (PyMongo).
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def evaluate_alert_rules(alert_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    מעריך את כל הכללים הפעילים על התראה נכנסת.
    
    Args:
        alert_data: נתוני ההתראה מ-internal_alerts או monitoring/alerts_storage
        
    Returns:
        dict עם תוצאות ההערכה, או None אם אין כללים מתאימים
        
    🔧 מיפוי שדות מההתראות הקיימות ל-EvaluationContext:
    ```
    ההתראה המקורית           ←→    שדה ב-context
    ─────────────────────────────────────────────────
    name                     ←→    alert_name
    severity                 ←→    severity  
    summary                  ←→    summary
    details.alert_type       ←→    alert_type
    details.sentry_issue_id  ←→    sentry_issue_id
    details.sentry_short_id  ←→    sentry_short_id
    details.project          ←→    project
    details.environment      ←→    environment
    details.error_signature  ←→    error_signature
    source                   ←→    source
    silenced                 ←→    is_silenced
    ```
    """
    try:
        from webapp.app import get_db
        from services.rules_storage import get_rules_storage
        from services.rule_engine import get_rule_engine, EvaluationContext
        
        # קבלת כללים פעילים
        storage = get_rules_storage(get_db())
        rules = storage.get_enabled_rules()
        
        if not rules:
            return None
        
        # בניית context מההתראה
        details = alert_data.get("details", {}) or {}
        
        context_data = {
            # שדות בסיסיים מההתראה
            "alert_name": str(alert_data.get("name", "")),
            "severity": str(alert_data.get("severity", "info")).lower(),
            "summary": str(alert_data.get("summary", "")),
            "source": str(alert_data.get("source", "")),
            "is_silenced": bool(alert_data.get("silenced", False)),
            
            # שדות מ-details
            "alert_type": str(details.get("alert_type", "")),
            "sentry_issue_id": str(details.get("sentry_issue_id", "")),
            "sentry_short_id": str(details.get("sentry_short_id", "")),
            "sentry_permalink": str(details.get("sentry_permalink", "")),
            "project": str(details.get("project", "")),
            "environment": str(details.get("environment", "")),
            "error_signature": str(details.get("error_signature", "")),
            "culprit": str(details.get("culprit", "")),
            "action": str(details.get("action", "")),
        }
        
        # הערכת כללים
        engine = get_rule_engine()
        matched_rules: List[Dict[str, Any]] = []
        
        for rule in rules:
            try:
                context = EvaluationContext(data=context_data)
                result = engine.evaluate(rule, context)
                
                if result.matched:
                    matched_rules.append({
                        "rule_id": rule.get("rule_id"),
                        "rule_name": rule.get("name"),
                        "triggered_conditions": result.triggered_conditions,
                        "actions": result.actions_to_execute,
                    })
            except Exception as e:
                logger.warning(f"Error evaluating rule {rule.get('rule_id')}: {e}")
                continue
        
        if matched_rules:
            return {
                "matched": True,
                "rules": matched_rules,
                "alert_data": alert_data,
            }
        
        return None
        
    except Exception as e:
        logger.error(f"Error in evaluate_alert_rules: {e}")
        return None


def execute_matched_actions(evaluation_result: Dict[str, Any]) -> None:
    """
    מבצע את הפעולות של כללים שהותאמו.
    
    Args:
        evaluation_result: תוצאת evaluate_alert_rules()
    """
    if not evaluation_result or not evaluation_result.get("matched"):
        return
    
    alert_data = evaluation_result.get("alert_data", {})
    
    for matched_rule in evaluation_result.get("rules", []):
        for action in matched_rule.get("actions", []):
            try:
                action_type = action.get("type", "")
                
                if action_type == "suppress":
                    # סימון ההתראה כמושתקת
                    alert_data["silenced"] = True
                    alert_data["silenced_by_rule"] = matched_rule.get("rule_id")
                    logger.info(f"Alert suppressed by rule: {matched_rule.get('rule_id')}")
                    
                elif action_type == "send_alert":
                    # שליחה להתראה נוספת (לערוץ ספציפי)
                    _send_custom_notification(action, alert_data, matched_rule)
                    
                elif action_type == "create_github_issue":
                    # יצירת GitHub Issue
                    _create_github_issue(action, alert_data, matched_rule)
                    
                elif action_type == "webhook":
                    _call_webhook(action, alert_data)
                    
            except Exception as e:
                logger.error(f"Error executing action {action_type}: {e}")


def _send_custom_notification(action: Dict, alert_data: Dict, matched_rule: Dict) -> None:
    """שולח התראה מותאמת לערוץ ספציפי."""
    try:
        channel = action.get("channel", "default")
        severity = action.get("severity", alert_data.get("severity", "info"))
        template = action.get("message_template", "{{rule_name}}: {{summary}}")
        
        # החלפת placeholders
        message = template.replace("{{rule_name}}", matched_rule.get("rule_name", ""))
        message = message.replace("{{summary}}", alert_data.get("summary", ""))
        message = message.replace("{{triggered_conditions}}", 
                                  ", ".join(matched_rule.get("triggered_conditions", [])))
        
        logger.info(f"Custom notification [{channel}]: {message[:100]}...")
        # כאן תוסיף את הלוגיקה לשליחה בפועל לערוץ המתאים
        
    except Exception as e:
        logger.error(f"Error sending custom notification: {e}")


def _create_github_issue(action: Dict, alert_data: Dict, matched_rule: Dict) -> None:
    """
    יוצר GitHub Issue (ראה github_issue_action.py).
    
    🔧 תיקון באג: asyncio.run() נכשל ב-nested event loop!
    - Flask עם ASGI (Hypercorn/uvicorn) כבר מריץ event loop
    - asyncio.run() יזרוק RuntimeError במקרה כזה
    
    פתרון: שימוש ב-ThreadPoolExecutor להרצת async code.
    """
    try:
        from services.github_issue_action import GitHubIssueAction
        from concurrent.futures import ThreadPoolExecutor
        import asyncio
        
        handler = GitHubIssueAction()
        triggered = matched_rule.get("triggered_conditions", [])
        
        def run_async():
            """הרצה בתוך thread חדש עם event loop נקי."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    handler.execute(action, alert_data, triggered)
                )
            finally:
                loop.close()
        
        # הרצה ב-thread pool כדי לא לחסום את ה-request
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_async)
            result = future.result(timeout=30)  # timeout לבטיחות
            
            if result and not result.get("success"):
                logger.warning(f"GitHub issue creation failed: {result.get('error')}")
            elif result and result.get("success"):
                logger.info(f"GitHub issue created: {result.get('issue_url')}")
                
    except Exception as e:
        logger.error(f"Error creating GitHub issue: {e}")


def _call_webhook(action: Dict, alert_data: Dict) -> None:
    """קריאה ל-webhook."""
    try:
        import requests
        url = action.get("webhook_url", "")
        if url:
            requests.post(url, json=alert_data, timeout=10)
    except Exception as e:
        logger.error(f"Error calling webhook: {e}")
```

### 2. נקודת ההפעלה ב-`internal_alerts.py`

```python
# הוסף ל-internal_alerts.py לפני שליחת ההתראה:

def emit_internal_alert(...):
    # ... קוד קיים ...
    
    # 🔧 הערכת כללים ויזואליים לפני שליחה
    try:
        from services.rules_evaluator import evaluate_alert_rules, execute_matched_actions
        
        alert_payload = {
            "name": name,
            "severity": severity,
            "summary": summary,
            "details": {...},  # פרטים נוספים
        }
        
        evaluation = evaluate_alert_rules(alert_payload)
        if evaluation:
            execute_matched_actions(evaluation)
            
            # אם הכלל דרש suppress, לא נשלח
            if alert_payload.get("silenced"):
                logger.info(f"Alert silenced by rule: {alert_payload.get('silenced_by_rule')}")
                return  # דלג על שליחה
                
    except Exception as e:
        logger.warning(f"Rules evaluation failed: {e}")
    
    # ... המשך שליחת ההתראה ...
```

### 2. שילוב עם `observability_dashboard.py`

הוספת תמיכה בכללים לדשבורד:

```python
# בקובץ services/observability_dashboard.py

async def get_rule_suggestions_for_alert(alert: Dict[str, Any]) -> List[Dict[str, Any]]:
    """מציע כללים רלוונטיים על בסיס התראה."""
    suggestions = []
    
    alert_type = alert.get("alert_type", "")
    
    # הצעת כלל לפי סוג ההתראה
    if "error" in alert_type.lower():
        suggestions.append({
            "name": f"כלל מותאם ל-{alert_type}",
            "template": {
                "conditions": {
                    "type": "group",
                    "operator": "AND",
                    "children": [
                        {
                            "type": "condition",
                            "field": "alert_type",
                            "operator": "eq",
                            "value": alert_type
                        },
                        {
                            "type": "condition",
                            "field": "error_rate",
                            "operator": "gt",
                            "value": 0.05
                        }
                    ]
                },
                "actions": [
                    {"type": "send_alert", "severity": "critical"}
                ]
            }
        })
    
    return suggestions
```

### 3. תבנית Jinja לממשק

קובץ: `webapp/templates/admin_rules.html`

> **🔧 הערה חשובה:** הפרויקט **אינו** משתמש ב-Bootstrap!  
> התבנית למטה משתמשת ב-CSS הקיים של הפרויקט (משתנים מ-`base.html`).
> עבור Modal, משתמשים במודל פשוט עם CSS מותאם במקום Bootstrap Modal.

```html
{% extends "base.html" %}

{% block title %}מנהל כללים{% endblock %}

{% block head %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/rule-builder.css') }}">
<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js"></script>
<style>
    /* 🔧 סגנונות מותאמים לפרויקט (ללא Bootstrap) */
    .rules-page { padding: 1.5rem; max-width: 1400px; margin: 0 auto; }
    .rules-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; flex-wrap: wrap; gap: 1rem; }
    .rules-header h1 { margin: 0; font-size: 1.5rem; color: var(--text-primary, #333); }
    .rules-header p { margin: 0.25rem 0 0; color: var(--text-secondary, #666); font-size: 0.9rem; }
    .rules-actions { display: flex; gap: 0.5rem; }
    
    .rules-grid { display: grid; grid-template-columns: 350px 1fr; gap: 1.5rem; margin-bottom: 1.5rem; }
    @media (max-width: 900px) { .rules-grid { grid-template-columns: 1fr; } }
    
    .rules-card { background: var(--card-bg, #fff); border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); overflow: hidden; }
    .rules-card__header { padding: 0.75rem 1rem; background: var(--surface-color, #f8f9fa); border-bottom: 1px solid var(--border-color, #e0e0e0); }
    .rules-card__header h3 { margin: 0; font-size: 1rem; font-weight: 600; }
    .rules-card__body { padding: 1rem; }
    
    .form-group { margin-bottom: 1rem; }
    .form-group label { display: block; margin-bottom: 0.25rem; font-weight: 500; font-size: 0.875rem; }
    .form-group input, .form-group textarea { width: 100%; padding: 0.5rem; border: 1px solid var(--border-color, #ddd); border-radius: 4px; font-size: 0.9rem; }
    .form-group input:focus, .form-group textarea:focus { outline: none; border-color: var(--primary, #667eea); }
    
    .toggle-switch { display: flex; align-items: center; gap: 0.5rem; }
    .toggle-switch input[type="checkbox"] { width: 40px; height: 22px; appearance: none; background: #ccc; border-radius: 11px; cursor: pointer; transition: background 0.2s; }
    .toggle-switch input[type="checkbox"]:checked { background: var(--success-color, #4caf50); }
    
    .rules-table { width: 100%; border-collapse: collapse; }
    .rules-table th, .rules-table td { padding: 0.75rem; text-align: right; border-bottom: 1px solid var(--border-color, #eee); }
    .rules-table th { background: var(--surface-color, #f8f9fa); font-weight: 600; font-size: 0.8rem; text-transform: uppercase; }
    .rules-table tbody tr:hover { background: var(--hover-bg, rgba(0,0,0,0.02)); }
    
    .status-badge { display: inline-block; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 500; }
    .status-badge--active { background: var(--success-light, #e8f5e9); color: var(--success-color, #4caf50); }
    .status-badge--inactive { background: var(--surface-color, #f0f0f0); color: var(--text-secondary, #666); }
    
    /* Modal פשוט ללא Bootstrap */
    .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 1000; justify-content: center; align-items: center; }
    .modal-overlay.active { display: flex; }
    .modal-box { background: var(--card-bg, #fff); border-radius: 8px; max-width: 600px; width: 90%; max-height: 80vh; overflow: auto; }
    .modal-header { padding: 1rem; border-bottom: 1px solid var(--border-color, #e0e0e0); display: flex; justify-content: space-between; align-items: center; }
    .modal-header h3 { margin: 0; font-size: 1.1rem; }
    .modal-close { background: none; border: none; font-size: 1.5rem; cursor: pointer; color: var(--text-secondary, #666); }
    .modal-body { padding: 1rem; }
    .modal-footer { padding: 1rem; border-top: 1px solid var(--border-color, #e0e0e0); display: flex; justify-content: flex-end; gap: 0.5rem; }
    
    .test-result { margin-top: 1rem; padding: 1rem; border-radius: 6px; display: none; }
    .test-result--success { background: var(--success-light, #e8f5e9); border: 1px solid var(--success-color, #4caf50); }
    .test-result--warning { background: var(--warning-light, #fff3e0); border: 1px solid var(--warning-color, #ff9800); }
</style>
{% endblock %}

{% block content %}
<div class="rules-page">
    <div class="rules-header">
        <div>
            <h1>🎯 מנהל כללים ויזואלי</h1>
            <p>בנה כללי התראה מותאמים אישית בממשק Drag & Drop</p>
        </div>
        <div class="rules-actions">
            <button id="save-rule" class="btn btn-primary"><i class="fas fa-save"></i> שמור כלל</button>
            <button id="test-rule" class="btn btn-secondary"><i class="fas fa-flask"></i> בדוק כלל</button>
        </div>
    </div>
    
    <div class="rules-grid">
        <div class="rules-card">
            <div class="rules-card__header">
                <h3>📋 פרטי הכלל</h3>
            </div>
            <div class="rules-card__body">
                <div class="form-group">
                    <label for="rule-name">שם הכלל</label>
                    <input type="text" id="rule-name" placeholder="כלל חדש">
                </div>
                <div class="form-group">
                    <label for="rule-description">תיאור</label>
                    <textarea id="rule-description" rows="2"></textarea>
                </div>
                <div class="toggle-switch">
                    <input type="checkbox" id="rule-enabled" checked>
                    <label for="rule-enabled">כלל פעיל</label>
                </div>
            </div>
        </div>
        
        <div class="rules-card">
            <div class="rules-card__header">
                <h3>🔧 בונה הכלל</h3>
            </div>
            <div class="rules-card__body">
                <div id="rule-builder"></div>
            </div>
        </div>
    </div>
    
    <div class="rules-card">
        <div class="rules-card__header">
            <h3>📜 כללים קיימים</h3>
        </div>
        <div class="rules-card__body">
            <table class="rules-table" id="rules-table">
                <thead>
                    <tr>
                        <th>שם</th>
                        <th>סטטוס</th>
                        <th>תנאים</th>
                        <th>עדכון אחרון</th>
                        <th>פעולות</th>
                    </tr>
                </thead>
                <tbody>
                    <!-- Populated by JS -->
                </tbody>
            </table>
        </div>
    </div>
</div>

<!-- Test Modal (ללא Bootstrap) -->
<div class="modal-overlay" id="test-modal">
    <div class="modal-box">
        <div class="modal-header">
            <h3>🧪 בדיקת כלל</h3>
            <button class="modal-close" onclick="closeTestModal()">&times;</button>
        </div>
        <div class="modal-body">
            <div class="form-group">
                <label>נתוני בדיקה (JSON)</label>
                <textarea id="test-data" rows="8" style="font-family: monospace;">{
  "alert_name": "Test Alert",
  "severity": "warning",
  "alert_type": "sentry_issue",
  "project": "api-gateway",
  "environment": "production"
}</textarea>
            </div>
            <div id="test-result" class="test-result"></div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeTestModal()">סגור</button>
            <button class="btn btn-primary" id="run-test">הרץ בדיקה</button>
        </div>
    </div>
</div>

<script src="{{ url_for('static', filename='js/rule-builder.js') }}"></script>
<script>
// 🔧 Modal פשוט ללא Bootstrap
function openTestModal() {
    document.getElementById('test-modal').classList.add('active');
}
function closeTestModal() {
    document.getElementById('test-modal').classList.remove('active');
}

document.addEventListener('DOMContentLoaded', async function() {
    // טעינת שדות זמינים
    const fieldsResponse = await fetch('/api/rules/fields');
    const { fields } = await fieldsResponse.json();
    
    // אתחול בונה הכללים
    const builder = new RuleBuilder('rule-builder', {
        availableFields: fields,
        onRuleChange: (rule) => {
            console.log('Rule changed:', rule);
        }
    });
    
    // שמירת כלל
    document.getElementById('save-rule').addEventListener('click', async () => {
        const rule = builder.getRule();
        rule.name = document.getElementById('rule-name').value;
        rule.description = document.getElementById('rule-description').value;
        rule.enabled = document.getElementById('rule-enabled').checked;
        
        const errors = builder.validate();
        if (errors.length > 0) {
            alert('שגיאות: ' + errors.join('\n'));
            return;
        }
        
        const response = await fetch('/api/rules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(rule)
        });
        
        if (response.ok) {
            alert('הכלל נשמר בהצלחה!');
            loadRules();
        } else {
            const error = await response.json();
            alert('שגיאה: ' + (error.details || error.error));
        }
    });
    
    // בדיקת כלל - פתיחת Modal
    document.getElementById('test-rule').addEventListener('click', openTestModal);
    
    document.getElementById('run-test').addEventListener('click', async () => {
        const rule = builder.getRule();
        let testData;
        
        try {
            testData = JSON.parse(document.getElementById('test-data').value);
        } catch (e) {
            alert('JSON לא תקין');
            return;
        }
        
        const response = await fetch('/api/rules/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rule, data: testData })
        });
        
        const result = await response.json();
        const resultDiv = document.getElementById('test-result');
        resultDiv.style.display = 'block';
        
        if (result.matched) {
            resultDiv.className = 'test-result test-result--success';
            resultDiv.innerHTML = `
                <strong>✅ הכלל התאים!</strong><br>
                תנאים שהופעלו: ${result.triggered_conditions.join(', ')}<br>
                פעולות: ${result.actions.map(a => a.type).join(', ')}<br>
                זמן הערכה: ${result.evaluation_time_ms.toFixed(2)}ms
            `;
        } else {
            resultDiv.className = 'test-result test-result--warning';
            resultDiv.innerHTML = `
                <strong>❌ הכלל לא התאים</strong><br>
                הנתונים לא עמדו בתנאים.
            `;
        }
    });
    
    // טעינת כללים קיימים (🔧 ללא Bootstrap classes)
    async function loadRules() {
        const response = await fetch('/api/rules');
        const { rules } = await response.json();
        
        const tbody = document.querySelector('#rules-table tbody');
        tbody.innerHTML = rules.map(rule => `
            <tr>
                <td><strong>${rule.name || rule.rule_id}</strong></td>
                <td>
                    <span class="status-badge ${rule.enabled ? 'status-badge--active' : 'status-badge--inactive'}">
                        ${rule.enabled ? 'פעיל' : 'מושבת'}
                    </span>
                </td>
                <td>${countConditions(rule.conditions)} תנאים</td>
                <td>${new Date(rule.updated_at).toLocaleString('he-IL')}</td>
                <td>
                    <button class="btn btn-sm" onclick="editRule('${rule.rule_id}')">
                        <i class="fas fa-edit"></i> ערוך
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="deleteRule('${rule.rule_id}')">
                        <i class="fas fa-trash"></i> מחק
                    </button>
                </td>
            </tr>
        `).join('');
    }
    
    function countConditions(node) {
        if (!node) return 0;
        if (node.type === 'condition') return 1;
        if (node.type === 'group') {
            return (node.children || []).reduce((sum, child) => sum + countConditions(child), 0);
        }
        return 0;
    }
    
    window.editRule = async (ruleId) => {
        const response = await fetch(`/api/rules/${ruleId}`);
        const rule = await response.json();
        
        document.getElementById('rule-name').value = rule.name || '';
        document.getElementById('rule-description').value = rule.description || '';
        document.getElementById('rule-enabled').checked = rule.enabled;
        builder.setRule(rule);
    };
    
    window.deleteRule = async (ruleId) => {
        if (!confirm('למחוק את הכלל?')) return;
        
        await fetch(`/api/rules/${ruleId}`, { method: 'DELETE' });
        loadRules();
    };
    
    // טעינה ראשונית
    loadRules();
});
</script>
{% endblock %}
```

---

## בדיקות

### קובץ: `tests/test_rule_engine.py`

```python
"""
Unit tests for the Visual Rule Engine
"""

import pytest
from datetime import datetime, timezone

from services.rule_engine import (
    RuleEngine,
    EvaluationContext,
    ConditionOperators,
)


class TestConditionOperators:
    """בדיקות לאופרטורי תנאים."""
    
    def test_eq(self):
        assert ConditionOperators.eq(5, 5) is True
        assert ConditionOperators.eq(5, 6) is False
        assert ConditionOperators.eq("hello", "hello") is True
    
    def test_gt(self):
        assert ConditionOperators.gt(10, 5) is True
        assert ConditionOperators.gt(5, 10) is False
        assert ConditionOperators.gt(5, 5) is False
    
    def test_contains(self):
        assert ConditionOperators.contains("hello world", "world") is True
        assert ConditionOperators.contains("hello", "xyz") is False
    
    def test_regex(self):
        assert ConditionOperators.regex("error-500", r"error-\d+") is True
        assert ConditionOperators.regex("success", r"error-\d+") is False
    
    def test_in_list(self):
        assert ConditionOperators.in_list("a", ["a", "b", "c"]) is True
        assert ConditionOperators.in_list("d", ["a", "b", "c"]) is False


class TestRuleEngine:
    """בדיקות למנוע הכללים."""
    
    @pytest.fixture
    def engine(self):
        return RuleEngine()
    
    @pytest.fixture
    def simple_rule(self):
        return {
            "rule_id": "test_rule_1",
            "name": "Test Rule",
            "enabled": True,
            "conditions": {
                "type": "condition",
                "field": "error_rate",
                "operator": "gt",
                "value": 0.05
            },
            "actions": [
                {"type": "send_alert", "severity": "critical"}
            ]
        }
    
    @pytest.fixture
    def complex_rule(self):
        return {
            "rule_id": "test_rule_2",
            "name": "Complex Rule",
            "enabled": True,
            "conditions": {
                "type": "group",
                "operator": "OR",
                "children": [
                    {
                        "type": "group",
                        "operator": "AND",
                        "children": [
                            {"type": "condition", "field": "error_rate", "operator": "gt", "value": 0.05},
                            {"type": "condition", "field": "requests_per_minute", "operator": "gt", "value": 1000}
                        ]
                    },
                    {"type": "condition", "field": "latency_avg_ms", "operator": "gt", "value": 500}
                ]
            },
            "actions": [
                {"type": "send_alert", "severity": "critical"}
            ]
        }
    
    def test_simple_rule_matches(self, engine, simple_rule):
        context = EvaluationContext(data={"error_rate": 0.08})
        result = engine.evaluate(simple_rule, context)
        
        assert result.matched is True
        assert len(result.triggered_conditions) == 1
        assert len(result.actions_to_execute) == 1
    
    def test_simple_rule_not_matches(self, engine, simple_rule):
        context = EvaluationContext(data={"error_rate": 0.02})
        result = engine.evaluate(simple_rule, context)
        
        assert result.matched is False
        assert len(result.actions_to_execute) == 0
    
    def test_complex_rule_and_branch(self, engine, complex_rule):
        """בדיקה שהכלל מתאים כאשר ה-AND branch מתקיים."""
        context = EvaluationContext(data={
            "error_rate": 0.08,
            "requests_per_minute": 1500,
            "latency_avg_ms": 200
        })
        result = engine.evaluate(complex_rule, context)
        
        assert result.matched is True
    
    def test_complex_rule_or_branch(self, engine, complex_rule):
        """בדיקה שהכלל מתאים כאשר ה-OR branch מתקיים."""
        context = EvaluationContext(data={
            "error_rate": 0.01,
            "requests_per_minute": 500,
            "latency_avg_ms": 600
        })
        result = engine.evaluate(complex_rule, context)
        
        assert result.matched is True
    
    def test_complex_rule_not_matches(self, engine, complex_rule):
        """בדיקה שהכלל לא מתאים כאשר אף branch לא מתקיים."""
        context = EvaluationContext(data={
            "error_rate": 0.01,
            "requests_per_minute": 500,
            "latency_avg_ms": 200
        })
        result = engine.evaluate(complex_rule, context)
        
        assert result.matched is False
    
    def test_disabled_rule(self, engine, simple_rule):
        simple_rule["enabled"] = False
        context = EvaluationContext(data={"error_rate": 0.08})
        result = engine.evaluate(simple_rule, context)
        
        assert result.matched is False
    
    def test_missing_field(self, engine, simple_rule):
        context = EvaluationContext(data={})  # no error_rate
        result = engine.evaluate(simple_rule, context)
        
        assert result.matched is False
    
    def test_validation_valid_rule(self, engine, simple_rule):
        errors = engine.validate_rule(simple_rule)
        assert len(errors) == 0
    
    def test_validation_missing_fields(self, engine):
        invalid_rule = {"name": "Test"}  # missing rule_id, conditions
        errors = engine.validate_rule(invalid_rule)
        
        assert len(errors) > 0
        assert any("rule_id" in e for e in errors)
        assert any("conditions" in e for e in errors)
    
    def test_validation_invalid_operator(self, engine):
        rule = {
            "rule_id": "test",
            "name": "Test",
            "conditions": {
                "type": "condition",
                "field": "error_rate",
                "operator": "invalid_op",
                "value": 0.05
            }
        }
        errors = engine.validate_rule(rule)
        
        assert any("operator" in e for e in errors)


class TestEvaluationPerformance:
    """בדיקות ביצועים."""
    
    def test_evaluation_time(self):
        engine = RuleEngine()
        
        # כלל מורכב עם הרבה תנאים
        rule = {
            "rule_id": "perf_test",
            "name": "Performance Test",
            "enabled": True,
            "conditions": {
                "type": "group",
                "operator": "AND",
                "children": [
                    {"type": "condition", "field": f"field_{i}", "operator": "gt", "value": i}
                    for i in range(100)
                ]
            },
            "actions": []
        }
        
        context = EvaluationContext(data={f"field_{i}": i + 1 for i in range(100)})
        result = engine.evaluate(rule, context)
        
        # וודא שההערכה מהירה (פחות מ-10ms)
        assert result.evaluation_time_ms < 10
```

---

## מימוש מורחב: פתיחת GitHub Issue אוטומטית

> **תרחיש:** כאשר מזוהה שגיאה חדשה (שלא נראתה מעולם), המערכת פותחת Issue אוטומטי ב-GitHub עם כל המידע הרלוונטי.

### שלב 1: הוספת שדות נדרשים

הוסף ל-`AVAILABLE_FIELDS` ב-`services/rule_engine.py`:

```python
AVAILABLE_FIELDS = {
    # ... שדות קיימים ...
    
    # 🆕 שדות לזיהוי שגיאות חדשות
    "error_signature": {
        "type": "string",
        "label": "חתימת שגיאה",
        "description": "Hash ייחודי של השגיאה (מבוסס על stack trace)"
    },
    "is_new_error": {
        "type": "boolean",
        "label": "שגיאה חדשה",
        "description": "האם זו הפעם הראשונה שרואים את השגיאה"
    },
    "error_message": {
        "type": "string",
        "label": "הודעת שגיאה",
        "description": "טקסט השגיאה המלא"
    },
    "stack_trace": {
        "type": "string",
        "label": "Stack Trace",
        "description": "ה-stack trace המלא"
    },
    "first_seen_at": {
        "type": "datetime",
        "label": "נראה לראשונה",
        "description": "מתי השגיאה נראתה לראשונה"
    },
    "occurrence_count": {
        "type": "int",
        "label": "מספר הופעות",
        "description": "כמה פעמים השגיאה הופיעה"
    },
}
```

### שלב 2: יצירת Action Handler ל-GitHub

צור קובץ `services/github_issue_action.py`:

```python
"""
GitHub Issue Action Handler
===========================
פותח Issues אוטומטיים ב-GitHub כאשר כלל מתאים.
"""

import os
import logging
import aiohttp
from typing import Any, Dict, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# הגדרות
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "owner/repo")  # לדוגמה: "amirbiron/CodeBot"
GITHUB_API_URL = "https://api.github.com"


class GitHubIssueAction:
    """
    Handler ליצירת GitHub Issues.
    
    דוגמת שימוש בכלל:
    ```json
    {
        "type": "create_github_issue",
        "labels": ["auto-generated", "bug"],
        "assignees": ["username"],
        "title_template": "🐛 [Auto] {{error_type}}: {{error_message}}",
        "body_template": "..."
    }
    ```
    """
    
    def __init__(self, token: str = GITHUB_TOKEN, repo: str = GITHUB_REPO):
        self.token = token
        self.repo = repo
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json"
        }
    
    async def execute(
        self,
        action_config: Dict[str, Any],
        alert_data: Dict[str, Any],
        triggered_conditions: list
    ) -> Dict[str, Any]:
        """
        מבצע את הפעולה - פותח Issue ב-GitHub.
        
        Args:
            action_config: הגדרות הפעולה מהכלל
            alert_data: נתוני ההתראה/שגיאה
            triggered_conditions: התנאים שהופעלו
            
        Returns:
            dict עם תוצאת הפעולה (issue_url, issue_number, וכו')
        """
        if not self.token:
            logger.error("GitHub token not configured")
            return {"success": False, "error": "GitHub token not configured"}
        
        # בניית כותרת (עם קיצור - כותרות GitHub מוגבלות)
        title = self._render_template(
            action_config.get("title_template", "🐛 [Auto] New Error: {{error_message}}"),
            alert_data,
            truncate_long_values=True,  # קיצור רק בכותרת
            max_length=80
        )
        
        # בניית גוף ה-Issue
        body = self._build_issue_body(action_config, alert_data, triggered_conditions)
        
        # Labels
        labels = action_config.get("labels", ["auto-generated", "bug"])
        
        # Assignees
        assignees = action_config.get("assignees", [])
        
        # בדיקה אם כבר קיים Issue פתוח לשגיאה זו
        error_signature = alert_data.get("error_signature", "")
        if error_signature:
            existing = await self._find_existing_issue(error_signature)
            if existing:
                logger.info(f"Issue already exists for error {error_signature}: #{existing['number']}")
                # עדכון ה-Issue הקיים עם הופעה חדשה
                await self._add_occurrence_comment(existing["number"], alert_data)
                return {
                    "success": True,
                    "action": "updated_existing",
                    "issue_number": existing["number"],
                    "issue_url": existing["html_url"]
                }
        
        # יצירת Issue חדש
        issue_data = {
            "title": title[:256],  # GitHub limit
            "body": body,
            "labels": labels,
        }
        
        if assignees:
            issue_data["assignees"] = assignees
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GITHUB_API_URL}/repos/{self.repo}/issues"
                async with session.post(url, json=issue_data, headers=self.headers) as resp:
                    if resp.status == 201:
                        result = await resp.json()
                        logger.info(f"Created GitHub issue #{result['number']}: {result['html_url']}")
                        return {
                            "success": True,
                            "action": "created",
                            "issue_number": result["number"],
                            "issue_url": result["html_url"]
                        }
                    else:
                        error_text = await resp.text()
                        logger.error(f"Failed to create issue: {resp.status} - {error_text}")
                        return {"success": False, "error": error_text}
                        
        except Exception as e:
            logger.error(f"Error creating GitHub issue: {e}")
            return {"success": False, "error": str(e)}
    
    def _render_template(
        self, 
        template: str, 
        data: Dict[str, Any],
        truncate_long_values: bool = False,
        max_length: int = 100
    ) -> str:
        """
        מחליף placeholders בתבנית.
        
        Args:
            template: תבנית עם {{placeholders}}
            data: מילון ערכים
            truncate_long_values: האם לקצר ערכים ארוכים (לכותרות בלבד)
            max_length: אורך מקסימלי כשמקצרים
        """
        result = template
        for key, value in data.items():
            placeholder = "{{" + key + "}}"
            if placeholder in result:
                str_value = str(value)
                # קיצור רק אם התבקש במפורש (לכותרות)
                if truncate_long_values and len(str_value) > max_length:
                    str_value = str_value[:max_length - 3] + "..."
                result = result.replace(placeholder, str_value)
        return result
    
    def _build_issue_body(
        self,
        action_config: Dict[str, Any],
        alert_data: Dict[str, Any],
        triggered_conditions: list
    ) -> str:
        """בונה את גוף ה-Issue בפורמט Markdown."""
        
        # תבנית ברירת מחדל
        default_template = """## 🐛 שגיאה אוטומטית

> Issue זה נוצר אוטומטית על ידי מערכת הניטור.

### פרטי השגיאה

| שדה | ערך |
|-----|-----|
| **סוג** | `{{alert_type}}` |
| **שירות** | `{{service_name}}` |
| **סביבה** | `{{environment}}` |
| **זמן** | {{timestamp}} |
| **חתימה** | `{{error_signature}}` |

### הודעת השגיאה

```
{{error_message}}
```

### Stack Trace

<details>
<summary>לחץ להרחבה</summary>

```
{{stack_trace}}
```

</details>

### תנאים שהופעלו

{{triggered_conditions_list}}

### מידע נוסף

- **Error Rate:** {{error_rate}}%
- **Latency:** {{latency_avg_ms}}ms
- **מספר הופעות:** {{occurrence_count}}

---

<sub>🤖 נוצר אוטומטית ע"י Visual Rule Engine | כלל: `{{rule_name}}`</sub>
"""
        
        template = action_config.get("body_template", default_template)
        
        # הוספת רשימת תנאים
        conditions_list = "\n".join([f"- ✅ `{c}`" for c in triggered_conditions])
        alert_data["triggered_conditions_list"] = conditions_list or "- (אין תנאים)"
        
        # הוספת timestamp
        alert_data["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # רינדור התבנית
        body = self._render_template(template, alert_data)
        
        # הגבלת אורך
        if len(body) > 65000:  # GitHub limit ~65535
            body = body[:64000] + "\n\n...(truncated)"
        
        return body
    
    async def _find_existing_issue(self, error_signature: str) -> Optional[Dict[str, Any]]:
        """מחפש Issue קיים פתוח עם אותה חתימת שגיאה.
        
        🔧 תיקון באג: URL encoding נכון של search query.
        """
        try:
            # 🔧 תיקון: שימוש ב-urllib.parse.quote לקידוד נכון של ה-query
            from urllib.parse import quote
            
            async with aiohttp.ClientSession() as session:
                # חיפוש ב-Issues פתוחים
                search_query = f"repo:{self.repo} is:issue is:open in:body {error_signature}"
                # קידוד נכון של ה-query string
                encoded_query = quote(search_query, safe='')
                url = f"{GITHUB_API_URL}/search/issues?q={encoded_query}"
                
                async with session.get(url, headers=self.headers) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("total_count", 0) > 0:
                            return result["items"][0]
            return None
        except Exception as e:
            logger.warning(f"Error searching for existing issue: {e}")
            return None
    
    async def _add_occurrence_comment(self, issue_number: int, alert_data: Dict[str, Any]) -> None:
        """מוסיף תגובה ל-Issue קיים על הופעה נוספת."""
        comment_body = f"""### 🔄 הופעה נוספת

| שדה | ערך |
|-----|-----|
| **זמן** | {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")} |
| **Error Rate** | {alert_data.get("error_rate", "N/A")}% |
| **סה"כ הופעות** | {alert_data.get("occurrence_count", "N/A")} |
"""
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GITHUB_API_URL}/repos/{self.repo}/issues/{issue_number}/comments"
                async with session.post(url, json={"body": comment_body}, headers=self.headers) as resp:
                    if resp.status == 201:
                        logger.info(f"Added occurrence comment to issue #{issue_number}")
        except Exception as e:
            logger.warning(f"Failed to add comment to issue #{issue_number}: {e}")


# =============================================================================
# רישום ה-Action במנוע
# =============================================================================

def register_github_action(engine):
    """רושם את ה-action במנוע הכללים."""
    handler = GitHubIssueAction()
    engine.register_action_handler("create_github_issue", handler.execute)
```

### שלב 3: אינטגרציה עם זיהוי שגיאות חדשות

הוסף ל-`monitoring/alerts_storage.py`:

```python
import hashlib

def compute_error_signature(error_data: Dict[str, Any]) -> str:
    """
    מחשב חתימה ייחודית לשגיאה.
    
    החתימה מבוססת על:
    - סוג השגיאה
    - שם הקובץ והשורה (אם יש)
    - 3 השורות הראשונות של ה-stack trace
    """
    components = [
        error_data.get("error_type", ""),
        error_data.get("file", ""),
        str(error_data.get("line", "")),
    ]
    
    # הוספת stack trace מנורמל
    stack = error_data.get("stack_trace", "")
    if stack:
        # לקיחת 3 שורות ראשונות
        lines = [l.strip() for l in stack.split("\n") if l.strip()][:3]
        components.extend(lines)
    
    signature_input = "|".join(components)
    return hashlib.sha256(signature_input.encode()).hexdigest()[:16]


async def is_new_error(signature: str) -> bool:
    """בודק אם השגיאה חדשה (לא נראתה ב-30 יום האחרונים)."""
    from database.manager import get_database
    from datetime import datetime, timedelta
    
    db = await get_database()
    collection = db["error_signatures"]
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    
    existing = await collection.find_one({
        "signature": signature,
        "last_seen": {"$gte": cutoff}
    })
    
    # עדכון/הוספת הרשומה
    await collection.update_one(
        {"signature": signature},
        {
            "$set": {"last_seen": datetime.now(timezone.utc)},
            "$inc": {"count": 1},
            "$setOnInsert": {"first_seen": datetime.now(timezone.utc)}
        },
        upsert=True
    )
    
    return existing is None


async def enrich_alert_with_signature(alert_data: Dict[str, Any]) -> Dict[str, Any]:
    """מעשיר את נתוני ההתראה עם חתימה ומידע על חדשות."""
    signature = compute_error_signature(alert_data)
    is_new = await is_new_error(signature)
    
    alert_data["error_signature"] = signature
    alert_data["is_new_error"] = is_new
    
    return alert_data
```

### שלב 4: דוגמה לכלל JSON

```json
{
  "version": 1,
  "rule_id": "auto_github_issue_new_errors",
  "name": "פתיחת Issue לשגיאות חדשות",
  "description": "פותח Issue אוטומטי ב-GitHub כאשר מזוהה שגיאה שלא נראתה מעולם",
  "enabled": true,
  "conditions": {
    "type": "group",
    "operator": "AND",
    "children": [
      {
        "type": "condition",
        "field": "is_new_error",
        "operator": "eq",
        "value": true
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
      "type": "create_github_issue",
      "labels": ["auto-generated", "bug", "needs-triage"],
      "assignees": [],
      "title_template": "🐛 [Auto] {{service_name}}: {{error_message}}"
    },
    {
      "type": "send_alert",
      "severity": "warning",
      "channel": "errors",
      "message_template": "📋 Issue נפתח אוטומטית: {{error_signature}}"
    }
  ],
  "metadata": {
    "tags": ["automation", "github"],
    "cooldown_minutes": 5
  }
}
```

### שלב 5: הגדרת משתני סביבה

הוסף ל-`.env` או להגדרות הסביבה:

```bash
# GitHub Integration
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
GITHUB_REPO=owner/repo-name
```

### שלב 6: בדיקות

הוסף ל-`tests/test_github_issue_action.py`:

```python
"""
Tests for GitHub Issue Action
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.github_issue_action import GitHubIssueAction


class TestGitHubIssueAction:
    """בדיקות ל-GitHub Issue Action."""
    
    @pytest.fixture
    def action(self):
        return GitHubIssueAction(token="test_token", repo="test/repo")
    
    @pytest.fixture
    def sample_alert(self):
        return {
            "alert_type": "error",
            "service_name": "api-gateway",
            "environment": "production",
            "error_message": "Connection refused",
            "error_signature": "abc123def456",
            "stack_trace": "Traceback...",
            "error_rate": 0.05,
            "latency_avg_ms": 200,
            "occurrence_count": 1,
            "rule_name": "Test Rule"
        }
    
    @pytest.fixture
    def sample_action_config(self):
        return {
            "type": "create_github_issue",
            "labels": ["auto-generated", "bug"],
            "title_template": "🐛 {{service_name}}: {{error_message}}"
        }
    
    def test_render_template(self, action):
        template = "Error in {{service_name}}: {{error_message}}"
        data = {"service_name": "api", "error_message": "timeout"}
        
        result = action._render_template(template, data)
        
        assert result == "Error in api: timeout"
    
    def test_render_template_preserves_long_values_by_default(self, action):
        """ודא שערכים ארוכים נשמרים בגוף (stack trace וכו')."""
        template = "{{stack_trace}}"
        long_trace = "x" * 5000
        data = {"stack_trace": long_trace}
        
        result = action._render_template(template, data)
        
        assert result == long_trace  # לא מקוצר!
        assert len(result) == 5000
    
    def test_render_template_truncates_when_requested(self, action):
        """ודא שקיצור עובד כשמתבקש (לכותרות)."""
        template = "{{error_message}}"
        data = {"error_message": "x" * 200}
        
        result = action._render_template(template, data, truncate_long_values=True, max_length=100)
        
        assert len(result) == 100  # 97 + "..."
        assert result.endswith("...")
    
    def test_build_issue_body(self, action, sample_action_config, sample_alert):
        triggered = ["is_new_error eq true", "environment eq production"]
        
        body = action._build_issue_body(sample_action_config, sample_alert, triggered)
        
        assert "api-gateway" in body
        assert "Connection refused" in body
        assert "abc123def456" in body
        assert "✅" in body  # triggered conditions
    
    @pytest.mark.asyncio
    async def test_execute_creates_issue(self, action, sample_action_config, sample_alert):
        with patch("aiohttp.ClientSession") as mock_session:
            # Mock successful response
            mock_response = AsyncMock()
            mock_response.status = 201
            mock_response.json = AsyncMock(return_value={
                "number": 42,
                "html_url": "https://github.com/test/repo/issues/42"
            })
            
            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = mock_response
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value.status = 200
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value.json = AsyncMock(
                return_value={"total_count": 0}
            )
            
            result = await action.execute(sample_action_config, sample_alert, [])
            
            assert result["success"] is True
            assert result["issue_number"] == 42
    
    @pytest.mark.asyncio
    async def test_execute_without_token(self):
        action = GitHubIssueAction(token="", repo="test/repo")
        
        result = await action.execute({}, {}, [])
        
        assert result["success"] is False
        assert "token" in result["error"].lower()


class TestErrorSignature:
    """בדיקות לחישוב חתימת שגיאה."""
    
    def test_compute_signature_consistency(self):
        from monitoring.alerts_storage import compute_error_signature
        
        error1 = {
            "error_type": "ConnectionError",
            "file": "api.py",
            "line": 42,
            "stack_trace": "Line 1\nLine 2\nLine 3"
        }
        
        sig1 = compute_error_signature(error1)
        sig2 = compute_error_signature(error1)
        
        assert sig1 == sig2  # Same input = same signature
    
    def test_different_errors_different_signatures(self):
        from monitoring.alerts_storage import compute_error_signature
        
        error1 = {"error_type": "ConnectionError", "file": "api.py"}
        error2 = {"error_type": "TimeoutError", "file": "api.py"}
        
        assert compute_error_signature(error1) != compute_error_signature(error2)
```

### תרשים זרימה

```
┌─────────────────────┐
│  שגיאה חדשה נכנסת   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ חישוב error_signature│
│ (hash של stack trace)│
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ בדיקה: האם ראינו    │
│ את החתימה ב-30 יום? │
└──────────┬──────────┘
           │
     ┌─────┴─────┐
     │           │
    כן          לא
     │           │
     ▼           ▼
┌─────────┐  ┌─────────────────┐
│ is_new  │  │ is_new_error    │
│ = false │  │ = true          │
└─────────┘  └────────┬────────┘
                      │
                      ▼
              ┌───────────────┐
              │ Rule Engine   │
              │ מעריך כללים   │
              └───────┬───────┘
                      │
                      ▼ (כלל מתאים)
              ┌───────────────────┐
              │ create_github_issue│
              └───────┬───────────┘
                      │
           ┌──────────┴──────────┐
           │                     │
    Issue קיים?              Issue חדש
           │                     │
           ▼                     ▼
    ┌─────────────┐      ┌─────────────┐
    │ הוסף תגובה  │      │ צור Issue   │
    │ על הופעה   │      │ עם labels   │
    └─────────────┘      └─────────────┘
```

---

## סיכום

### קבצים שיש ליצור/לעדכן:

| קובץ | פעולה | תיאור |
|------|-------|-------|
| `services/rule_engine.py` | יצירה | מנוע הערכת כללים |
| `services/rules_storage.py` | יצירה | אחסון כללים ב-MongoDB |
| `services/github_issue_action.py` | יצירה | 🆕 Action לפתיחת GitHub Issues |
| `services/webserver.py` | עדכון | הוספת API endpoints |
| `webapp/static/js/rule-builder.js` | יצירה | ממשק Drag & Drop |
| `webapp/static/css/rule-builder.css` | יצירה | עיצוב הממשק |
| `webapp/templates/admin_rules.html` | יצירה | תבנית הדף |
| `monitoring/alerts_storage.py` | עדכון | אינטגרציה + חתימות שגיאה |
| `tests/test_rule_engine.py` | יצירה | בדיקות יחידה |
| `tests/test_github_issue_action.py` | יצירה | 🆕 בדיקות ל-GitHub Action |

### שלבי מימוש מומלצים:

1. **שלב 1**: מימוש `rule_engine.py` עם בדיקות
2. **שלב 2**: מימוש `rules_storage.py`
3. **שלב 3**: הוספת API endpoints
4. **שלב 4**: מימוש Frontend בסיסי
5. **שלב 5**: אינטגרציה עם מערכת ההתראות
6. **שלב 6**: שיפורים ו-UX

### תלויות נדרשות:

```txt
# אין תלויות חדשות נדרשות - המערכת משתמשת בתשתית הקיימת
# motor/pymongo - כבר קיים
# aiohttp - כבר קיים
```

---

*מדריך זה נכתב בהתאם לארכיטקטורה הקיימת של הפרויקט ומשתלב עם:*
- *`monitoring/alerts_storage.py` - אחסון התראות*
- *`services/observability_dashboard.py` - דשבורד observability*
- *`config/alert_quick_fixes.json` - פעולות מהירות*
- *`config/observability_runbooks.yml` - runbooks*
