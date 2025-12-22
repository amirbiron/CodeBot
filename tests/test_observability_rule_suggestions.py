import pytest


@pytest.mark.asyncio
async def test_get_rule_suggestions_for_alert_returns_template_for_error():
    from services.observability_dashboard import get_rule_suggestions_for_alert

    suggestions = await get_rule_suggestions_for_alert({"alert_type": "error_spike"})
    assert suggestions
    assert "template" in suggestions[0]
    tmpl = suggestions[0]["template"]
    assert tmpl["conditions"]["type"] == "group"
    assert tmpl["actions"][0]["type"] == "send_alert"


@pytest.mark.asyncio
async def test_get_rule_suggestions_for_alert_empty_for_non_error():
    from services.observability_dashboard import get_rule_suggestions_for_alert

    suggestions = await get_rule_suggestions_for_alert({"alert_type": "deployment_event"})
    assert suggestions == []
