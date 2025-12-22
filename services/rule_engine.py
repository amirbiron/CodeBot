"""
Visual Rule Engine - מנוע כללים ויזואלי
==========================================
מאפשר הגדרת כללי התראה מורכבים בפורמט JSON והרצתם על נתונים בזמן אמת.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# שדות זמינים (מבוסס על המערכת הקיימת)
# =============================================================================

AVAILABLE_FIELDS = {
    # === שדות בסיסיים מההתראות (monitoring/alerts_storage.py) ===
    "alert_name": {
        "type": "string",
        "label": "שם ההתראה",
        "description": "שם ההתראה כפי שמופיע ב-internal_alerts",
    },
    "severity": {
        "type": "string",
        "label": "רמת חומרה",
        "description": "info, warning, critical, anomaly",
        "enum": ["info", "warning", "critical", "anomaly"],
    },
    "summary": {
        "type": "string",
        "label": "תיאור קצר",
        "description": "תיאור ההתראה",
    },
    "source": {
        "type": "string",
        "label": "מקור",
        "description": "מקור ההתראה (sentry, internal, external)",
    },
    "is_silenced": {
        "type": "boolean",
        "label": "מושתק",
        "description": "האם ההתראה הושתקה",
    },
    # === שדות מ-details (מידע מפורט) ===
    "alert_type": {
        "type": "string",
        "label": "סוג התראה",
        "description": "sentry_issue, deployment_event, וכו'",
    },
    "sentry_issue_id": {
        "type": "string",
        "label": "Sentry Issue ID",
        "description": "מזהה ה-Issue ב-Sentry",
    },
    "sentry_short_id": {
        "type": "string",
        "label": "Sentry Short ID",
        "description": "מזהה קצר כמו PROJECT-123",
    },
    "project": {
        "type": "string",
        "label": "פרויקט",
        "description": "שם הפרויקט (Sentry/GitLab)",
    },
    "environment": {
        "type": "string",
        "label": "סביבה",
        "description": "production, staging, development",
    },
    "error_signature": {
        "type": "string",
        "label": "חתימת שגיאה",
        "description": "Hash ייחודי לזיהוי שגיאות חוזרות",
    },
    # 🆕 שדות לזיהוי שגיאות חדשות
    "is_new_error": {
        "type": "boolean",
        "label": "שגיאה חדשה",
        "description": "האם זו הפעם הראשונה שרואים את השגיאה",
    },
    "error_message": {
        "type": "string",
        "label": "הודעת שגיאה",
        "description": "טקסט השגיאה המלא",
    },
    "stack_trace": {
        "type": "string",
        "label": "Stack Trace",
        "description": "ה-stack trace המלא",
    },
    "first_seen_at": {
        "type": "datetime",
        "label": "נראה לראשונה",
        "description": "מתי השגיאה נראתה לראשונה",
    },
    "occurrence_count": {
        "type": "int",
        "label": "מספר הופעות",
        "description": "כמה פעמים השגיאה הופיעה",
    },
    "culprit": {
        "type": "string",
        "label": "מיקום השגיאה",
        "description": "הפונקציה/קובץ שגרם לשגיאה",
    },
    "action": {
        "type": "string",
        "label": "פעולה",
        "description": "triggered, resolved, וכו'",
    },
    # === שדות זמן (מחושבים) ===
    "hour_of_day": {
        "type": "int",
        "label": "שעה ביום",
        "min": 0,
        "max": 23,
        "description": "שעה נוכחית (UTC)",
    },
    "day_of_week": {
        "type": "int",
        "label": "יום בשבוע",
        "min": 0,
        "max": 6,
        "description": "0=ראשון, 6=שבת",
    },
}


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
            r"\(\.\+\)\+",  # (a+)+
            r"\(\.\*\)\+",  # (.*)+
            r"\(\[.+\]\+\)\+",  # ([a-z]+)+
            r"\(\.\+\)\*",  # (a+)*
        ]
        for dangerous in dangerous_patterns:
            if re.search(dangerous, pattern_str):
                logger.warning("Potentially dangerous regex pattern detected, rejecting")
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
                    evaluation_time_ms=(time.perf_counter() - start_time) * 1000,
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
                evaluation_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        except Exception as e:
            logger.error(f"Error evaluating rule {rule_id}: {e}")
            return EvaluationResult(
                rule_id=rule_id,
                matched=False,
                triggered_conditions=[],
                actions_to_execute=[],
                evaluation_time_ms=(time.perf_counter() - start_time) * 1000,
                error=str(e),
            )

    def _evaluate_node(
        self,
        node: Dict[str, Any],
        context: EvaluationContext,
        triggered: List[str],
    ) -> bool:
        """מעריך צומת בעץ התנאים (רקורסיבי)."""
        node_type = node.get("type")

        if node_type == "condition":
            return self._evaluate_condition(node, context, triggered)
        if node_type == "group":
            return self._evaluate_group(node, context, triggered)
        logger.warning(f"Unknown node type: {node_type}")
        return False

    def _evaluate_condition(
        self,
        condition: Dict[str, Any],
        context: EvaluationContext,
        triggered: List[str],
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
        triggered: List[str],
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
            child_results = [self._evaluate_node(child, context, triggered) for child in children]
            return all(child_results)
        if operator == "OR":
            child_results = [self._evaluate_node(child, context, triggered) for child in children]
            return any(child_results)
        if operator == "NOT":
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
        for field_name in required_fields:
            if field_name not in rule:
                errors.append(f"Missing required field: {field_name}")

        # בדיקת מבנה התנאים
        conditions = rule.get("conditions", {})
        self._validate_node(conditions, errors, path="conditions")

        # בדיקת פעולות
        actions = rule.get("actions", [])
        for i, action in enumerate(actions):
            if "type" not in action:
                errors.append(f"Action {i}: missing 'type' field")

        return errors

    def _validate_node(self, node: Dict[str, Any], errors: List[str], path: str) -> None:
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

