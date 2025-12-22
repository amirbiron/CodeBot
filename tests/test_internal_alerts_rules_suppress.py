import importlib


def test_internal_alerts_suppress_rule_skips_forwarding(monkeypatch):
    """
    מכסה את האינטגרציה: internal_alerts.emit_internal_alert -> rules_evaluator
    כאשר כלל מחזיר suppress, צריך לעצור לפני forward_alerts/Telegram.
    """
    from services import rules_evaluator as reval

    def _fake_evaluate(alert_payload):
        # מחזירים evaluation שמצביע חזרה על אותו dict כדי ש-execute_matched_actions יסמן אותו
        return {
            "matched": True,
            "alert_data": alert_payload,
            "rules": [{"rule_id": "r-suppress", "actions": [{"type": "suppress"}]}],
        }

    monkeypatch.setattr(reval, "evaluate_alert_rules", _fake_evaluate)

    import internal_alerts as ia
    importlib.reload(ia)

    forwarded = []

    def _fake_forward(_alerts):
        forwarded.append("called")

    monkeypatch.setattr(ia, "forward_alerts", _fake_forward)
    # ודא שה-fallback הישיר לטלגרם לא יופעל בטעות
    monkeypatch.setattr(ia, "request", None)
    monkeypatch.delenv("ALERT_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ALERT_TELEGRAM_CHAT_ID", raising=False)

    ia.emit_internal_alert(name="Boom", severity="error", summary="x", details={"a": 1})
    assert forwarded == []
