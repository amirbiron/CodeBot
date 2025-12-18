# מדריך מימוש: מנוע כללים ויזואלי (Visual Rule Engine)

> **מטרה:** לאפשר למשתמשים לבנות כללי התראה מורכבים בממשק Drag & Drop, ללא צורך בכתיבת קוד.

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

```python
AVAILABLE_FIELDS = {
    # מדדי ביצועים
    "error_rate": {"type": "float", "label": "שיעור שגיאות", "unit": "%"},
    "latency_avg_ms": {"type": "float", "label": "Latency ממוצע", "unit": "ms"},
    "latency_p95_ms": {"type": "float", "label": "Latency P95", "unit": "ms"},
    "latency_p99_ms": {"type": "float", "label": "Latency P99", "unit": "ms"},
    "requests_per_minute": {"type": "int", "label": "בקשות לדקה", "unit": "req/min"},
    
    # משאבי מערכת
    "cpu_percent": {"type": "float", "label": "ניצול CPU", "unit": "%"},
    "memory_percent": {"type": "float", "label": "ניצול זיכרון", "unit": "%"},
    "disk_percent": {"type": "float", "label": "ניצול דיסק", "unit": "%"},
    
    # מידע הקשרי
    "service_name": {"type": "string", "label": "שם השירות"},
    "environment": {"type": "string", "label": "סביבה"},
    "user_id": {"type": "string", "label": "מזהה משתמש"},
    "alert_type": {"type": "string", "label": "סוג התראה"},
    
    # זמן
    "hour_of_day": {"type": "int", "label": "שעה ביום", "min": 0, "max": 23},
    "day_of_week": {"type": "int", "label": "יום בשבוע", "min": 0, "max": 6}
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

```python
"""
Rules Storage - אחסון כללים ב-MongoDB
======================================
מספק ממשק לשמירה, טעינה ועדכון כללים.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# הגדרות ברירת מחדל
RULES_COLLECTION = "visual_rules"
RULES_TTL_DAYS = 365  # שמירת כללים לשנה


class RulesStorage:
    """
    מנהל אחסון כללים ב-MongoDB.
    
    משתלב עם תשתית ה-MongoDB הקיימת (ראה monitoring/alerts_storage.py).
    """
    
    def __init__(self, db):
        """
        Args:
            db: MongoDB database instance (מתקבל מ-get_database())
        """
        self._db = db
        self._collection = db[RULES_COLLECTION]
        self._ensure_indexes()
    
    def _ensure_indexes(self) -> None:
        """יצירת אינדקסים נדרשים."""
        try:
            # אינדקס ייחודי על rule_id
            self._collection.create_index("rule_id", unique=True)
            # אינדקס על enabled לשליפה מהירה של כללים פעילים
            self._collection.create_index("enabled")
            # אינדקס על tags לסינון
            self._collection.create_index("metadata.tags")
            # אינדקס על created_by
            self._collection.create_index("created_by")
        except Exception as e:
            logger.error(f"Failed to create indexes: {e}")
    
    async def save_rule(self, rule: Dict[str, Any]) -> str:
        """
        שומר או מעדכן כלל.
        
        Args:
            rule: הגדרת הכלל
            
        Returns:
            rule_id
        """
        rule_id = rule.get("rule_id")
        if not rule_id:
            import uuid
            rule_id = f"rule_{uuid.uuid4().hex[:12]}"
            rule["rule_id"] = rule_id
        
        now = datetime.now(timezone.utc)
        rule["updated_at"] = now.isoformat()
        if "created_at" not in rule:
            rule["created_at"] = now.isoformat()
        
        await self._collection.update_one(
            {"rule_id": rule_id},
            {"$set": rule},
            upsert=True
        )
        
        logger.info(f"Saved rule: {rule_id}")
        return rule_id
    
    async def get_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """מחזיר כלל לפי ID."""
        doc = await self._collection.find_one({"rule_id": rule_id})
        if doc:
            doc.pop("_id", None)
        return doc
    
    async def get_enabled_rules(self) -> List[Dict[str, Any]]:
        """מחזיר את כל הכללים הפעילים."""
        cursor = self._collection.find({"enabled": True})
        rules = []
        async for doc in cursor:
            doc.pop("_id", None)
            rules.append(doc)
        return rules
    
    async def list_rules(
        self,
        enabled_only: bool = False,
        tags: Optional[List[str]] = None,
        created_by: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        מחזיר רשימת כללים עם סינון.
        
        Args:
            enabled_only: רק כללים פעילים
            tags: סינון לפי תגיות
            created_by: סינון לפי יוצר
            limit: מקסימום תוצאות
            offset: דילוג על תוצאות ראשונות
        """
        query: Dict[str, Any] = {}
        
        if enabled_only:
            query["enabled"] = True
        if tags:
            query["metadata.tags"] = {"$all": tags}
        if created_by:
            query["created_by"] = created_by
        
        cursor = self._collection.find(query).skip(offset).limit(limit)
        cursor = cursor.sort("updated_at", -1)
        
        rules = []
        async for doc in cursor:
            doc.pop("_id", None)
            rules.append(doc)
        return rules
    
    async def delete_rule(self, rule_id: str) -> bool:
        """מוחק כלל."""
        result = await self._collection.delete_one({"rule_id": rule_id})
        deleted = result.deleted_count > 0
        if deleted:
            logger.info(f"Deleted rule: {rule_id}")
        return deleted
    
    async def toggle_rule(self, rule_id: str, enabled: bool) -> bool:
        """מפעיל/מכבה כלל."""
        result = await self._collection.update_one(
            {"rule_id": rule_id},
            {"$set": {"enabled": enabled, "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        return result.modified_count > 0
    
    async def count_rules(self, enabled_only: bool = False) -> int:
        """מחזיר מספר הכללים."""
        query = {"enabled": True} if enabled_only else {}
        return await self._collection.count_documents(query)


# =============================================================================
# Factory function
# =============================================================================

_storage: Optional[RulesStorage] = None

async def get_rules_storage() -> RulesStorage:
    """מחזיר את מנהל האחסון (singleton)."""
    global _storage
    if _storage is None:
        from database.manager import get_database
        db = await get_database()
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
        this.container.innerHTML = `
            <div class="rule-builder">
                <div class="rule-builder__toolbar">
                    <button class="btn btn-sm" data-add="condition">+ תנאי</button>
                    <button class="btn btn-sm" data-add="group-and">+ קבוצת AND</button>
                    <button class="btn btn-sm" data-add="group-or">+ קבוצת OR</button>
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
    
    createAction() {
        return {
            type: 'send_alert',
            severity: 'warning',
            channel: 'default'
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
        const operators = [
            { value: 'eq', label: '=' },
            { value: 'ne', label: '≠' },
            { value: 'gt', label: '>' },
            { value: 'gte', label: '≥' },
            { value: 'lt', label: '<' },
            { value: 'lte', label: '≤' },
            { value: 'contains', label: 'מכיל' },
            { value: 'regex', label: 'RegEx' }
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
    
    renderGroupBlock(group, depth) {
        const isAnd = group.operator === 'AND';
        const className = isAnd ? 'group-and' : 'group-or';
        const label = isAnd ? 'וגם (AND)' : 'או (OR)';
        
        const childrenHtml = group.children
            .map(child => this.renderConditions(child, depth + 1))
            .join('');
        
        return `
            <div class="block group-block ${className}" data-type="group" data-operator="${group.operator}">
                <div class="block__header">
                    <span class="block__icon">${isAnd ? '🔗' : '🔀'}</span>
                    <span class="block__title">${label}</span>
                    <button class="block__add-child" data-action="add-condition">+ תנאי</button>
                    <button class="block__delete" data-action="delete">×</button>
                </div>
                <div class="block__children" data-drop-zone="group">
                    ${childrenHtml || '<p class="empty-hint">גרור תנאים לכאן</p>'}
                </div>
            </div>
        `;
    }
    
    renderActions(actions) {
        return actions.map((action, index) => `
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
                </div>
            </div>
        `).join('');
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

### הוספה ל-`services/webserver.py`

```python
# =============================================================================
# Visual Rules API
# =============================================================================

async def rules_list_view(request: web.Request) -> web.Response:
    """GET /api/rules - רשימת כללים"""
    from services.rules_storage import get_rules_storage
    
    storage = await get_rules_storage()
    
    # פרמטרים
    enabled_only = request.query.get("enabled") == "true"
    tags = request.query.getall("tag", [])
    
    # 🔧 תיקון באג #5: טיפול ב-ValueError עבור פרמטרים לא תקינים
    try:
        limit = min(int(request.query.get("limit", 50)), 200)
    except (ValueError, TypeError):
        return web.json_response({
            "error": "Invalid 'limit' parameter - must be an integer"
        }, status=400)
    
    try:
        offset = int(request.query.get("offset", 0))
    except (ValueError, TypeError):
        return web.json_response({
            "error": "Invalid 'offset' parameter - must be an integer"
        }, status=400)
    
    # בדיקת ערכים שליליים
    if limit < 0 or offset < 0:
        return web.json_response({
            "error": "Parameters 'limit' and 'offset' must be non-negative"
        }, status=400)
    
    rules = await storage.list_rules(
        enabled_only=enabled_only,
        tags=tags or None,
        limit=limit,
        offset=offset
    )
    count = await storage.count_rules(enabled_only=enabled_only)
    
    return web.json_response({
        "rules": rules,
        "total": count,
        "limit": limit,
        "offset": offset
    })


async def rules_get_view(request: web.Request) -> web.Response:
    """GET /api/rules/{rule_id} - קבלת כלל ספציפי"""
    from services.rules_storage import get_rules_storage
    
    rule_id = request.match_info["rule_id"]
    storage = await get_rules_storage()
    
    rule = await storage.get_rule(rule_id)
    if not rule:
        return web.json_response({"error": "Rule not found"}, status=404)
    
    return web.json_response(rule)


async def rules_create_view(request: web.Request) -> web.Response:
    """POST /api/rules - יצירת כלל חדש"""
    from services.rules_storage import get_rules_storage
    from services.rule_engine import get_rule_engine
    
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    
    # ולידציה
    engine = get_rule_engine()
    errors = engine.validate_rule(data)
    if errors:
        return web.json_response({"error": "Validation failed", "details": errors}, status=400)
    
    # שמירה
    storage = await get_rules_storage()
    rule_id = await storage.save_rule(data)
    
    return web.json_response({"rule_id": rule_id, "message": "Rule created"}, status=201)


async def rules_update_view(request: web.Request) -> web.Response:
    """PUT /api/rules/{rule_id} - עדכון כלל"""
    from services.rules_storage import get_rules_storage
    from services.rule_engine import get_rule_engine
    
    rule_id = request.match_info["rule_id"]
    
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    
    # וידוא שה-rule_id תואם
    data["rule_id"] = rule_id
    
    # ולידציה
    engine = get_rule_engine()
    errors = engine.validate_rule(data)
    if errors:
        return web.json_response({"error": "Validation failed", "details": errors}, status=400)
    
    # עדכון
    storage = await get_rules_storage()
    await storage.save_rule(data)
    
    return web.json_response({"rule_id": rule_id, "message": "Rule updated"})


async def rules_delete_view(request: web.Request) -> web.Response:
    """DELETE /api/rules/{rule_id} - מחיקת כלל"""
    from services.rules_storage import get_rules_storage
    
    rule_id = request.match_info["rule_id"]
    storage = await get_rules_storage()
    
    deleted = await storage.delete_rule(rule_id)
    if not deleted:
        return web.json_response({"error": "Rule not found"}, status=404)
    
    return web.json_response({"message": "Rule deleted"})


async def rules_toggle_view(request: web.Request) -> web.Response:
    """POST /api/rules/{rule_id}/toggle - הפעלה/כיבוי כלל"""
    from services.rules_storage import get_rules_storage
    
    rule_id = request.match_info["rule_id"]
    
    try:
        data = await request.json()
        enabled = data.get("enabled", True)
    except Exception:
        enabled = True
    
    storage = await get_rules_storage()
    success = await storage.toggle_rule(rule_id, enabled)
    
    if not success:
        return web.json_response({"error": "Rule not found"}, status=404)
    
    return web.json_response({"rule_id": rule_id, "enabled": enabled})


async def rules_test_view(request: web.Request) -> web.Response:
    """POST /api/rules/test - בדיקת כלל על נתוני דמה"""
    from services.rule_engine import get_rule_engine, EvaluationContext
    
    try:
        data = await request.json()
        rule = data.get("rule", {})
        test_data = data.get("data", {})
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    
    engine = get_rule_engine()
    
    # ולידציה
    errors = engine.validate_rule(rule)
    if errors:
        return web.json_response({
            "valid": False,
            "errors": errors
        })
    
    # הערכה על נתוני הבדיקה
    context = EvaluationContext(data=test_data)
    result = engine.evaluate(rule, context)
    
    return web.json_response({
        "valid": True,
        "matched": result.matched,
        "triggered_conditions": result.triggered_conditions,
        "actions": result.actions_to_execute,
        "evaluation_time_ms": result.evaluation_time_ms
    })


async def rules_available_fields_view(request: web.Request) -> web.Response:
    """GET /api/rules/fields - שדות זמינים"""
    from services.rule_engine import AVAILABLE_FIELDS
    
    fields = [
        {"name": k, **v}
        for k, v in AVAILABLE_FIELDS.items()
    ]
    
    return web.json_response({"fields": fields})


# =============================================================================
# Routes Registration
# =============================================================================

def setup_rules_routes(app: web.Application) -> None:
    """הגדרת routes עבור מנוע הכללים."""
    app.router.add_get("/api/rules", rules_list_view)
    app.router.add_post("/api/rules", rules_create_view)
    app.router.add_get("/api/rules/fields", rules_available_fields_view)
    app.router.add_post("/api/rules/test", rules_test_view)
    app.router.add_get("/api/rules/{rule_id}", rules_get_view)
    app.router.add_put("/api/rules/{rule_id}", rules_update_view)
    app.router.add_delete("/api/rules/{rule_id}", rules_delete_view)
    app.router.add_post("/api/rules/{rule_id}/toggle", rules_toggle_view)
```

---

## אינטגרציה עם המערכת הקיימת

### 1. שילוב עם `alerts_storage.py`

הכללים יופעלו אוטומטית כאשר מתקבלת התראה חדשה:

```python
# בקובץ monitoring/alerts_storage.py - הוספה לפונקציית record_alert

async def record_alert(alert_data: Dict[str, Any]) -> str:
    """רישום התראה חדשה עם הערכת כללים ויזואליים."""
    # ... קוד קיים ...
    
    # הערכת כללים ויזואליים
    await _evaluate_visual_rules(alert_data)
    
    return alert_id


async def _evaluate_visual_rules(alert_data: Dict[str, Any]) -> None:
    """מעריך את כל הכללים הפעילים על ההתראה."""
    from services.rules_storage import get_rules_storage
    from services.rule_engine import get_rule_engine, EvaluationContext
    
    try:
        storage = await get_rules_storage()
        engine = get_rule_engine()
        
        # טעינת כללים פעילים
        rules = await storage.get_enabled_rules()
        
        # יצירת הקשר מנתוני ההתראה
        context = EvaluationContext(data={
            "alert_type": alert_data.get("alert_type", ""),
            "severity": alert_data.get("severity", ""),
            "error_rate": alert_data.get("metrics", {}).get("error_rate", 0),
            "latency_avg_ms": alert_data.get("metrics", {}).get("latency", 0),
            "service_name": alert_data.get("service", ""),
            # ... שדות נוספים לפי הצורך
        })
        
        # הערכת כל כלל
        for rule in rules:
            result = engine.evaluate(rule, context)
            if result.matched:
                await _execute_rule_actions(rule, result, alert_data)
                
    except Exception as e:
        logger.error(f"Error evaluating visual rules: {e}")


async def _execute_rule_actions(
    rule: Dict[str, Any], 
    result: Any, 
    alert_data: Dict[str, Any]
) -> None:
    """מבצע את הפעולות של כלל שהותאם."""
    for action in result.actions_to_execute:
        action_type = action.get("type")
        
        if action_type == "send_alert":
            # שליחת התראה מותאמת
            await _send_custom_alert(action, alert_data, result)
        elif action_type == "suppress":
            # השתקת ההתראה
            alert_data["suppressed"] = True
            alert_data["suppressed_by_rule"] = rule.get("rule_id")
        elif action_type == "webhook":
            # קריאה ל-webhook
            await _call_webhook(action, alert_data)
        # ... פעולות נוספות
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

```html
{% extends "base.html" %}

{% block title %}מנהל כללים{% endblock %}

{% block head %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/rule-builder.css') }}">
<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js"></script>
{% endblock %}

{% block content %}
<div class="container py-4">
    <div class="row mb-4">
        <div class="col">
            <h1>🎯 מנהל כללים ויזואלי</h1>
            <p class="text-muted">בנה כללי התראה מותאמים אישית בממשק Drag & Drop</p>
        </div>
        <div class="col-auto">
            <button id="save-rule" class="btn btn-primary">💾 שמור כלל</button>
            <button id="test-rule" class="btn btn-secondary">🧪 בדוק כלל</button>
        </div>
    </div>
    
    <div class="row mb-4">
        <div class="col-md-4">
            <div class="card">
                <div class="card-header">
                    <h5>📋 פרטי הכלל</h5>
                </div>
                <div class="card-body">
                    <div class="mb-3">
                        <label class="form-label">שם הכלל</label>
                        <input type="text" id="rule-name" class="form-control" placeholder="כלל חדש">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">תיאור</label>
                        <textarea id="rule-description" class="form-control" rows="2"></textarea>
                    </div>
                    <div class="form-check form-switch">
                        <input class="form-check-input" type="checkbox" id="rule-enabled" checked>
                        <label class="form-check-label" for="rule-enabled">כלל פעיל</label>
                    </div>
                </div>
            </div>
        </div>
        <div class="col-md-8">
            <div class="card">
                <div class="card-header">
                    <h5>🔧 בונה הכלל</h5>
                </div>
                <div class="card-body">
                    <div id="rule-builder"></div>
                </div>
            </div>
        </div>
    </div>
    
    <div class="row">
        <div class="col">
            <div class="card">
                <div class="card-header">
                    <h5>📜 כללים קיימים</h5>
                </div>
                <div class="card-body">
                    <table class="table table-hover" id="rules-table">
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
    </div>
</div>

<!-- Test Modal -->
<div class="modal fade" id="test-modal" tabindex="-1">
    <div class="modal-dialog modal-lg">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title">🧪 בדיקת כלל</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <div class="mb-3">
                    <label class="form-label">נתוני בדיקה (JSON)</label>
                    <textarea id="test-data" class="form-control font-monospace" rows="6">{
  "error_rate": 0.08,
  "latency_avg_ms": 600,
  "requests_per_minute": 1500,
  "service_name": "api-gateway"
}</textarea>
                </div>
                <div id="test-result" class="alert" style="display: none;"></div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">סגור</button>
                <button type="button" class="btn btn-primary" id="run-test">הרץ בדיקה</button>
            </div>
        </div>
    </div>
</div>

<script src="{{ url_for('static', filename='js/rule-builder.js') }}"></script>
<script>
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
    
    // בדיקת כלל
    document.getElementById('test-rule').addEventListener('click', () => {
        new bootstrap.Modal(document.getElementById('test-modal')).show();
    });
    
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
            resultDiv.className = 'alert alert-success';
            resultDiv.innerHTML = `
                <strong>✅ הכלל התאים!</strong><br>
                תנאים שהופעלו: ${result.triggered_conditions.join(', ')}<br>
                פעולות: ${result.actions.map(a => a.type).join(', ')}<br>
                זמן הערכה: ${result.evaluation_time_ms.toFixed(2)}ms
            `;
        } else {
            resultDiv.className = 'alert alert-warning';
            resultDiv.innerHTML = `
                <strong>❌ הכלל לא התאים</strong><br>
                הנתונים לא עמדו בתנאים.
            `;
        }
    });
    
    // טעינת כללים קיימים
    async function loadRules() {
        const response = await fetch('/api/rules');
        const { rules } = await response.json();
        
        const tbody = document.querySelector('#rules-table tbody');
        tbody.innerHTML = rules.map(rule => `
            <tr>
                <td><strong>${rule.name || rule.rule_id}</strong></td>
                <td>
                    <span class="badge ${rule.enabled ? 'bg-success' : 'bg-secondary'}">
                        ${rule.enabled ? 'פעיל' : 'מושבת'}
                    </span>
                </td>
                <td>${countConditions(rule.conditions)} תנאים</td>
                <td>${new Date(rule.updated_at).toLocaleString('he-IL')}</td>
                <td>
                    <button class="btn btn-sm btn-outline-primary" onclick="editRule('${rule.rule_id}')">
                        ✏️ ערוך
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteRule('${rule.rule_id}')">
                        🗑️ מחק
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
        
        # בניית כותרת
        title = self._render_template(
            action_config.get("title_template", "🐛 [Auto] New Error: {{error_message}}"),
            alert_data
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
    
    def _render_template(self, template: str, data: Dict[str, Any]) -> str:
        """מחליף placeholders בתבנית."""
        result = template
        for key, value in data.items():
            placeholder = "{{" + key + "}}"
            if placeholder in result:
                # חיטוי ערכים ארוכים
                str_value = str(value)
                if len(str_value) > 100:
                    str_value = str_value[:97] + "..."
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
        """מחפש Issue קיים פתוח עם אותה חתימת שגיאה."""
        try:
            async with aiohttp.ClientSession() as session:
                # חיפוש ב-Issues פתוחים
                search_query = f"repo:{self.repo} is:issue is:open in:body {error_signature}"
                url = f"{GITHUB_API_URL}/search/issues?q={search_query}"
                
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
    
    def test_render_template_truncates_long_values(self, action):
        template = "{{long_value}}"
        data = {"long_value": "x" * 200}
        
        result = action._render_template(template, data)
        
        assert len(result) <= 103  # 100 + "..."
    
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
