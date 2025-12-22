"""
Visual Rule Engine - מנוע כללים ויזואלי
==========================================
מאפשר הגדרת כללי התראה מורכבים בפורמט JSON והרצתם על נתונים בזמן אמת.
"""

from __future__ import annotations

import logging
import os
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
    # === מדדים (אם קיימים בהתראה/ב-details) ===
    "error_rate": {
        "type": "float",
        "label": "שיעור שגיאות",
        "description": "שיעור שגיאות (למשל 0.05 או 5)",
    },
    "requests_per_minute": {
        "type": "int",
        "label": "בקשות לדקה",
        "description": "מספר בקשות לדקה",
    },
    "latency_avg_ms": {
        "type": "int",
        "label": "Latency ממוצע (ms)",
        "description": "Latency ממוצע במילישניות",
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
    "error_signature_hash": {
        "type": "string",
        "label": "חתימת שגיאה (hash)",
        "description": "Fingerprint (hash) של השגיאה לצורך זיהוי שגיאות חדשות",
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

    @staticmethod
    def _is_verbose(context: EvaluationContext) -> bool:
        """האם להדפיס לוגים מפורטים (לצורכי דיבוג/סימולטור)."""
        try:
            if isinstance(getattr(context, "metadata", None), dict) and bool(context.metadata.get("verbose")):
                return True
        except Exception:
            pass
        raw = (os.getenv("RULES_VERBOSE_LOGGING") or "").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _safe_repr(value: Any, *, limit: int = 220) -> str:
        """תצוגה קצרה ובטוחה ללוג (ללא הצפה)."""
        try:
            text = str(value)
        except Exception:
            text = "<unprintable>"
        text = text.replace("\n", "\\n")
        if len(text) > limit:
            return text[: max(0, limit - 1)] + "…"
        return text

    @staticmethod
    def _is_sensitive_field(field_name: str) -> bool:
        try:
            name = str(field_name or "").lower()
        except Exception:
            return False
        # heuristic בסיסי למניעת דליפת סודות בלוגים
        sensitive_markers = ("token", "password", "secret", "authorization", "api_key", "apikey", "private_key", "key")
        return any(m in name for m in sensitive_markers)

    def _safe_value_for_field(self, field_name: str, value: Any) -> str:
        text = self._safe_repr(value)
        if not text:
            return text
        if self._is_sensitive_field(field_name):
            return "<REDACTED>"
        return text

    def _context_preview(self, context_data: Dict[str, Any]) -> str:
        """Preview קטן של ה-context כדי להבין מה נכנס (בלי להציף לוגים)."""
        if not isinstance(context_data, dict):
            return self._safe_repr(context_data)
        # Keep a small allowlist of common fields; the condition logs will show actual comparisons anyway.
        allow = (
            "alert_name",
            "severity",
            "summary",
            "source",
            "alert_type",
            "project",
            "environment",
            "is_new_error",
            "error_signature_hash",
            "sentry_issue_id",
            "sentry_short_id",
            "action",
        )
        parts: List[str] = []
        for k in allow:
            if k not in context_data:
                continue
            v = context_data.get(k)
            if v in (None, ""):
                continue
            parts.append(f"{k}={self._safe_value_for_field(k, v)}")
        # Always include keys count for context shape
        try:
            keys_count = len(context_data.keys())
        except Exception:
            keys_count = -1
        if parts:
            return f"keys={keys_count}; " + ", ".join(parts)
        return f"keys={keys_count}"

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
        rule_name = str(rule.get("name") or rule_id)
        triggered_conditions: List[str] = []
        verbose = self._is_verbose(context)

        try:
            if verbose:
                logger.warning(
                    "Checking rule '%s' (id=%s) -> incoming_context: %s",
                    rule_name,
                    rule_id,
                    self._context_preview(context.data),
                )

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

            if verbose:
                logger.warning(
                    "Rule '%s' (id=%s) matched=%s, triggered_conditions=%s",
                    rule_name,
                    rule_id,
                    bool(matched),
                    self._safe_repr(triggered_conditions, limit=800),
                )

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
        verbose = self._is_verbose(context)

        # קבלת הערך מההקשר
        actual_value = context.data.get(field_name)
        if actual_value is None:
            if verbose:
                logger.warning(
                    "Checking rule condition -> field '%s' missing in context (operator='%s', expected='%s')",
                    field_name,
                    operator_name,
                    self._safe_value_for_field(field_name, expected_value),
                )
            return False

        # קבלת פונקציית האופרטור
        operator_func = ConditionOperators.get_operator(operator_name)
        if operator_func is None:
            logger.warning(f"Unknown operator: {operator_name}")
            return False

        # 🔧 UI -> Engine: בוליאני יכול להגיע כמחרוזת ("True"/"False")
        # כדי למנוע השוואה של True מול "True", נמיר את expected_value לבוליאני
        # אם actual_value הוא בוליאני וה-expected_value מחרוזת.
        if isinstance(actual_value, bool) and isinstance(expected_value, str):
            raw_expected = expected_value
            normalized = raw_expected.strip().lower()
            if normalized in {"true", "false"}:
                expected_value = normalized == "true"
                if verbose:
                    logger.warning(
                        "Coerced expected_value to bool -> field '%s': '%s' -> %s",
                        field_name,
                        self._safe_value_for_field(field_name, raw_expected),
                        expected_value,
                    )

        # הערכת התנאי
        try:
            if verbose:
                logger.warning(
                    "Checking condition -> field '%s' value '%s' vs '%s' (op=%s)",
                    field_name,
                    self._safe_value_for_field(field_name, actual_value),
                    self._safe_value_for_field(field_name, expected_value),
                    operator_name,
                )
            result = operator_func(actual_value, expected_value)
            if result:
                triggered.append(f"{field_name} {operator_name} {expected_value}")
            elif verbose:
                logger.warning(
                    "Condition failed -> Mismatch: field '%s' value '%s' vs '%s' (op=%s)",
                    field_name,
                    self._safe_value_for_field(field_name, actual_value),
                    self._safe_value_for_field(field_name, expected_value),
                    operator_name,
                )
            return result
        except Exception as e:
            if verbose:
                logger.warning(
                    "Error evaluating condition (fail-closed): field '%s' value '%s' vs '%s' (op=%s) error=%s",
                    field_name,
                    self._safe_value_for_field(field_name, actual_value),
                    self._safe_value_for_field(field_name, expected_value),
                    operator_name,
                    str(e),
                )
            else:
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
        verbose = self._is_verbose(context)

        if not children:
            # AND([]) => True, OR([]) => False. NOT דורש ילד אחד; ניפול ל-False (fail-closed).
            if operator == "AND":
                return True
            if operator == "OR":
                return False
            if operator == "NOT":
                return False
            return False

        # 🔧 תיקון באג #1: הימנעות מ-Short-circuit evaluation
        # הערכת כל הילדים מראש כדי לאסוף את כל התנאים שהותאמו
        # (all/any עם generator מפסיקים בתוצאה הראשונה שקובעת)

        if operator == "AND":
            child_results = [self._evaluate_node(child, context, triggered) for child in children]
            if verbose:
                logger.warning("Group AND evaluated -> results=%s -> %s", child_results, all(child_results))
            return all(child_results)
        if operator == "OR":
            child_results = [self._evaluate_node(child, context, triggered) for child in children]
            if verbose:
                logger.warning("Group OR evaluated -> results=%s -> %s", child_results, any(child_results))
            return any(child_results)
        if operator == "NOT":
            # 🔧 תיקון באג #6: NOT לא מוסיף תנאים שגויים ל-triggered
            # אם הילד מתאים (True), ה-NOT מחזיר False - אז לא נוסיף ל-triggered
            if children:
                # הערכה לרשימה זמנית כדי לא לזהם את triggered
                temp_triggered: List[str] = []
                child_result = self._evaluate_node(children[0], context, temp_triggered)
                not_result = not child_result
                if verbose:
                    logger.warning("Group NOT evaluated -> child=%s -> %s", bool(child_result), bool(not_result))

                # רק אם NOT מחזיר True (כלומר הילד לא התאים), נתעד את זה
                if not_result:
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
            # ולידציה מבנית בסיסית כדי למנוע קבוצות ריקות/NOT לא תקין
            if operator in ("AND", "OR") and not children:
                errors.append(f"{path}: group '{operator}' must have at least one child")
            if operator == "NOT" and len(children) != 1:
                errors.append(f"{path}: group 'NOT' must have exactly one child")
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

