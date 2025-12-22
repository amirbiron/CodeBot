"""
Unit tests for the Visual Rule Engine
"""

import pytest

from services.rule_engine import (
    ConditionOperators,
    EvaluationContext,
    RuleEngine,
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
                "value": 0.05,
            },
            "actions": [{"type": "send_alert", "severity": "critical"}],
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
                            {"type": "condition", "field": "requests_per_minute", "operator": "gt", "value": 1000},
                        ],
                    },
                    {"type": "condition", "field": "latency_avg_ms", "operator": "gt", "value": 500},
                ],
            },
            "actions": [{"type": "send_alert", "severity": "critical"}],
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
        context = EvaluationContext(
            data={"error_rate": 0.08, "requests_per_minute": 1500, "latency_avg_ms": 200}
        )
        result = engine.evaluate(complex_rule, context)

        assert result.matched is True

    def test_complex_rule_or_branch(self, engine, complex_rule):
        """בדיקה שהכלל מתאים כאשר ה-OR branch מתקיים."""
        context = EvaluationContext(
            data={"error_rate": 0.01, "requests_per_minute": 500, "latency_avg_ms": 600}
        )
        result = engine.evaluate(complex_rule, context)

        assert result.matched is True

    def test_complex_rule_not_matches(self, engine, complex_rule):
        """בדיקה שהכלל לא מתאים כאשר אף branch לא מתקיים."""
        context = EvaluationContext(
            data={"error_rate": 0.01, "requests_per_minute": 500, "latency_avg_ms": 200}
        )
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
                "value": 0.05,
            },
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
                ],
            },
            "actions": [],
        }

        context = EvaluationContext(data={f"field_{i}": i + 1 for i in range(100)})
        result = engine.evaluate(rule, context)

        # וודא שההערכה מהירה (פחות מ-10ms)
        assert result.evaluation_time_ms < 10

