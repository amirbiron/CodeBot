
import logging
import sys
from services.rule_engine import RuleEngine, EvaluationContext

# Setup logging to see output
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

def reproduce():
    engine = RuleEngine()
    
    # Base rule structure
    base_rule = {
        'conditions': {
            'type': 'group',
            'operator': 'AND',
            'children': [
                {
                    'type': 'condition',
                    'field': 'alert_type',
                    'operator': 'contains',
                    'value': 'sentry_issue'
                }
            ]
        },
        'actions': [{'type': 'log'}]
    }

    # Data
    data = {
        'alert_name': 'Test Alert',
        'alert_type': 'sentry_issue',
        'project': 'api-gateway'
    }
    context = EvaluationContext(data=data)

    print("\n--- Test 1: Standard Case (Should Match) ---")
    result = engine.evaluate(base_rule, context)
    print(f"Result: {result.matched}, Triggered: {result.triggered_conditions}")

    print("\n--- Test 2: Enabled is explicitly None (Should Fail?) ---")
    rule_none_enabled = base_rule.copy()
    rule_none_enabled['enabled'] = None
    result = engine.evaluate(rule_none_enabled, context)
    print(f"Result: {result.matched} (Expected False if None causes issues)")

    print("\n--- Test 3: Alert Type missing in Data (Should Fail) ---")
    context_missing = EvaluationContext(data={'alert_name': 'foo'})
    result = engine.evaluate(base_rule, context_missing)
    print(f"Result: {result.matched}")

    print("\n--- Test 4: Alert Type is None in Data (Should Fail) ---")
    context_none = EvaluationContext(data={'alert_type': None})
    result = engine.evaluate(base_rule, context_none)
    print(f"Result: {result.matched}")
    
    print("\n--- Test 5: Rule Conditions missing type (Should Fail) ---")
    rule_no_type = {
        'conditions': {
             # missing type: group
             'operator': 'AND',
             'children': []
        }
    }
    result = engine.evaluate(rule_no_type, context)
    print(f"Result: {result.matched}")

if __name__ == "__main__":
    reproduce()
