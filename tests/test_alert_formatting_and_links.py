import importlib
import os

import pytest


@pytest.fixture(autouse=True)
def _webapp_url(monkeypatch):
    """כמו בייצור, יש כתובת ל-WebApp — וממנה נבנים כפתור ה-Dashboard והקישור בשורת ה-Quick Fix.

    אין לה ברירת מחדל (``webapp_url.py``), ולכן בלי השורה הזו ההתראות יוצאות בלי קישורים, וזה נבדק בנפרד
    ב-``tests/test_webapp_url.py``.
    """
    monkeypatch.setenv("WEBAPP_URL", "https://webapp.test")


def _clear_sentry_env(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("SENTRY_ORG", raising=False)
    monkeypatch.delenv("SENTRY_ORG_SLUG", raising=False)
    monkeypatch.delenv("SENTRY_DASHBOARD_URL", raising=False)
    monkeypatch.delenv("SENTRY_PROJECT_URL", raising=False)


def test_forwarder_format_includes_context_and_direct_permalink(monkeypatch):
    _clear_sentry_env(monkeypatch)

    import alert_forwarder as af
    importlib.reload(af)

    alert = {
        "status": "firing",
        "labels": {
            "alertname": "Boom",
            "severity": "error",
            "service": "api",
            "env": "prod",
            "instance": "pod-1",
            "request_id": "rid-1",
        },
        "annotations": {
            "summary": "crashed",
            "sentry_permalink": "https://sentry.io/organizations/acme/issues/1",
        },
        "generatorURL": "http://alert.example/am"
    }

    text = af._format_alert_text(alert)  # noqa: SLF001

    assert "Boom" in text and "ERROR" in text
    assert "service: api" in text
    assert "env: prod" in text
    assert "instance: pod-1" in text
    assert "request_id: rid-1" in text
    # We intentionally avoid showing generatorURL (often internal/non-public) in chat text.
    assert "http://alert.example/am" not in text
    assert "Sentry: https://sentry.io/organizations/acme/issues/1" in text


def test_forwarder_builds_sentry_link_from_request_id(monkeypatch):
    _clear_sentry_env(monkeypatch)
    monkeypatch.setenv("SENTRY_DSN", "https://abc@o123.ingest.sentry.io/1")
    monkeypatch.setenv("SENTRY_ORG", "acme")

    import alert_forwarder as af
    importlib.reload(af)

    alert = {
        "status": "firing",
        "labels": {
            "alertname": "Err",
            "severity": "error",
            "service": "api",
            "request_id": "rid-9",
        },
        "annotations": {"summary": "boom"},
    }

    text = af._format_alert_text(alert)  # noqa: SLF001

    assert "Sentry:" in text
    assert "organizations/acme" in text
    # encoded: request_id:"rid-9"
    assert "request_id%3A%22rid-9%22" in text


def test_forwarder_builds_sentry_link_from_error_signature(monkeypatch):
    _clear_sentry_env(monkeypatch)
    monkeypatch.setenv("SENTRY_DSN", "https://abc@o123.ingest.sentry.io/1")
    monkeypatch.setenv("SENTRY_ORG", "acme")

    import alert_forwarder as af
    importlib.reload(af)

    alert = {
        "status": "firing",
        "labels": {
            "alertname": "Sig",
            "severity": "error",
            "error_signature": "oom_killed",
        },
        "annotations": {"summary": "boom"},
    }

    text = af._format_alert_text(alert)  # noqa: SLF001

    assert "Sentry:" in text
    assert "organizations/acme" in text
    assert "error_signature%3A%22oom_killed%22" in text


def test_forwarder_no_sentry_link_when_not_configured(monkeypatch):
    _clear_sentry_env(monkeypatch)

    import alert_forwarder as af
    importlib.reload(af)

    alert = {
        "status": "firing",
        "labels": {"alertname": "NoSentry", "severity": "warn", "request_id": "rid-x"},
        "annotations": {"summary": "note"},
    }

    text = af._format_alert_text(alert)  # noqa: SLF001
    assert "Sentry:" not in text


def test_forwarder_uses_regional_host_from_dsn(monkeypatch):
    _clear_sentry_env(monkeypatch)
    # Regional DSN host
    monkeypatch.setenv("SENTRY_DSN", "https://abc@o123.ingest.eu.sentry.io/1")
    monkeypatch.setenv("SENTRY_ORG", "acme")

    import alert_forwarder as af
    importlib.reload(af)

    alert = {
        "status": "firing",
        "labels": {"alertname": "Regional", "severity": "error", "request_id": "rid-r"},
        "annotations": {"summary": "boom"},
    }

    text = af._format_alert_text(alert)  # noqa: SLF001
    assert "https://eu.sentry.io/organizations/acme/issues/?query=" in text


def test_alert_manager_format_text_includes_context_and_sentry_link(monkeypatch):
    _clear_sentry_env(monkeypatch)
    monkeypatch.setenv("SENTRY_DSN", "https://abc@o456.ingest.sentry.io/2")
    monkeypatch.setenv("SENTRY_ORG", "orgy")

    import alert_manager as am
    importlib.reload(am)

    text = am._format_text(  # noqa: SLF001
        name="High Error Rate",
        severity="CRITICAL",
        summary="errs>thr",
        details={
            "service": "gateway",
            "env": "staging",
            "request_id": "rid-2",
            "error_signature": "sig1",
            "token": "SECRET",  # must be filtered
        },
    )

    assert "[CRITICAL] High Error Rate" in text
    assert "service: gateway" in text
    assert "env: staging" in text
    assert "request_id: rid-2" in text
    assert "token" not in text and "SECRET" not in text
    # No duplication of promoted fields within details preview
    assert "service=" not in text and "env=" not in text and "request_id=" not in text
    assert "Sentry:" in text and "organizations/orgy" in text and "request_id%3A%22rid-2%22" in text


def test_alert_manager_uses_direct_sentry_permalink_when_provided(monkeypatch):
    _clear_sentry_env(monkeypatch)
    import alert_manager as am
    importlib.reload(am)

    text = am._format_text(  # noqa: SLF001
        name="Latency",
        severity="CRITICAL",
        summary="high latency",
        details={
            "service": "api",
            "sentry_permalink": "https://sentry.io/organizations/acme/issues/42",
        },
    )

    assert "Sentry: https://sentry.io/organizations/acme/issues/42" in text


def test_alert_manager_uses_regional_host_from_dsn(monkeypatch):
    _clear_sentry_env(monkeypatch)
    monkeypatch.setenv("SENTRY_DSN", "https://abc@o987.ingest.us.sentry.io/44")
    monkeypatch.setenv("SENTRY_ORG", "beta")

    import alert_manager as am
    importlib.reload(am)

    text = am._format_text(  # noqa: SLF001
        name="High Latency",
        severity="CRITICAL",
        summary="lat>thr",
        details={"request_id": "rid-y"},
    )

    assert "https://us.sentry.io/organizations/beta/issues/?query=" in text


def test_forwarder_includes_details_preview_when_provided(monkeypatch):
    _clear_sentry_env(monkeypatch)

    import alert_forwarder as af
    importlib.reload(af)

    alert = {
        "status": "firing",
        "labels": {"alertname": "DetailAlert", "severity": "warn"},
        "annotations": {
            "summary": "extra context",
            "details_preview": "cause=spike, region=eu-west",
        },
    }

    text = af._format_alert_text(alert)  # noqa: SLF001

    assert "extra context" in text
    assert "cause=spike" in text
    assert "region=eu-west" in text


def test_internal_alerts_forward_payload_includes_context(monkeypatch):
    _clear_sentry_env(monkeypatch)

    import internal_alerts as ia
    importlib.reload(ia)

    captured = {}

    def _fake_forward(alerts):
        captured["alerts"] = alerts

    monkeypatch.setattr(ia, "forward_alerts", _fake_forward)

    ia.emit_internal_alert(
        name="anomaly_detected",
        severity="error",
        summary="avg_rt high",
        service="api",
        env="prod",
        instance="pod-a",
        request_id="rid-42",
        generator_url="https://grafana/alert",
        error_signature="OOM_KILLED",
        sentry_permalink="https://sentry.io/org/issues/42",
        token="SECRET",
        shard="3",
    )

    alert_list = captured.get("alerts")
    assert alert_list is not None
    assert len(alert_list) == 1
    alert = alert_list[0]

    labels = alert["labels"]
    annotations = alert["annotations"]

    assert labels["service"] == "api"
    assert labels["env"] == "prod"
    assert labels["instance"] == "pod-a"
    assert labels["request_id"] == "rid-42"
    assert alert["generatorURL"] == "https://grafana/alert"
    assert annotations["sentry_permalink"] == "https://sentry.io/org/issues/42"
    assert annotations["error_signature"] == "OOM_KILLED"
    assert "shard=3" in annotations["details_preview"]
    assert "SECRET" not in annotations["details_preview"]


def test_internal_alerts_details_preview_skips_raw_noisy_fields(monkeypatch):
    _clear_sentry_env(monkeypatch)

    import internal_alerts as ia
    import importlib
    importlib.reload(ia)

    captured = {}

    def _fake_forward(alerts):
        captured["alerts"] = alerts

    monkeypatch.setattr(ia, "forward_alerts", _fake_forward)

    # labels doesn't include any of the compact keys, and slow_endpoints is large:
    # details_preview should NOT embed raw dict/list representations.
    ia.emit_internal_alert(
        name="anomaly_detected",
        severity="anomaly",
        summary="avg_rt=3.1s (threshold 3.0s)",
        labels={"something_else": "x"},
        slow_endpoints=[{"method": "GET", "endpoint": "index", "count": 1, "avg_duration": 1.0, "max_duration": 1.0}],
    )

    alert_list = captured.get("alerts") or []
    assert len(alert_list) == 1
    preview = (alert_list[0].get("annotations") or {}).get("details_preview") or ""
    # We should never embed raw dict/list representations for these noisy fields.
    assert "labels={" not in preview
    assert "slow_endpoints=[" not in preview


def _fresh_runbooks(monkeypatch):
    """ה-runbooks מתוך ``config/observability_runbooks.yml`` של הריפו, בלי מה שטסט אחר השאיר בקאש."""
    from pathlib import Path

    from services import observability_dashboard as obs

    monkeypatch.setattr(obs, "_RUNBOOK_PATH", Path("config/observability_runbooks.yml"))
    monkeypatch.setattr(obs, "_RUNBOOK_CACHE", {})
    monkeypatch.setattr(obs, "_RUNBOOK_ALIAS_MAP", {})
    monkeypatch.setattr(obs, "_RUNBOOK_MTIME", 0.0)
    monkeypatch.setattr(obs, "_RUNBOOK_RESOLVED_PATH", None)


def _forwarded(monkeypatch, **alert):
    """מריץ את ``emit_internal_alert`` האמיתי, ומחזיר את ההתראה כפי שהגיעה ל-``alert_forwarder``."""
    import internal_alerts as ia

    captured = []
    monkeypatch.setattr(ia, "forward_alerts", captured.extend)
    ia.emit_internal_alert(**alert)
    [forwarded] = captured
    return forwarded


def test_a_non_critical_alert_with_its_own_runbook_carries_the_quick_fix_line(monkeypatch):
    _clear_sentry_env(monkeypatch)
    _fresh_runbooks(monkeypatch)
    import alert_forwarder as af

    forwarded = _forwarded(
        monkeypatch,
        name="docs_index_approval_needed",
        severity="warn",
        summary="waiting",
        details={"alert_type": "docs_index_approval_needed"},
    )

    link = forwarded["annotations"]["quick_fix"].rsplit(" → ", 1)[1]
    assert link.startswith(("http://", "https://")) and link.endswith("/admin/docs-index")
    text = af._format_alert_text(forwarded, include_dashboard_link=False)  # noqa: SLF001
    assert forwarded["annotations"]["quick_fix"] in text.splitlines()


def test_a_relative_quick_fix_link_points_to_the_same_server_as_the_dashboard_button(monkeypatch):
    """בטלגרם נתיב יחסי אינו קישור. הבסיס הוא ``WEBAPP_URL`` (``webapp_url.py``) — אותו שרת של הכפתור "Open Dashboard"."""
    _clear_sentry_env(monkeypatch)
    _fresh_runbooks(monkeypatch)
    monkeypatch.setenv("WEBAPP_URL", "https://public.example")
    import alert_forwarder as af

    forwarded = _forwarded(
        monkeypatch,
        name="docs_index_approval_needed",
        severity="warn",
        summary="waiting",
        details={"alert_type": "docs_index_approval_needed"},
    )

    assert forwarded["annotations"]["quick_fix"].endswith(" → https://public.example/admin/docs-index")
    assert af._build_public_dashboard_url() == "https://public.example/admin/observability"  # noqa: SLF001


def test_the_quick_fix_line_survives_a_specialized_message_format(monkeypatch):
    """תבנית ייעודית (כאן ``anomaly_detected``) חוזרת מוקדם, ובכל זאת השורה נכנסת — לפני שורת הדשבורד."""
    _clear_sentry_env(monkeypatch)
    import alert_forwarder as af

    alert = {
        "status": "firing",
        "labels": {"alertname": "anomaly_detected", "severity": "anomaly"},
        "annotations": {"summary": "avg_rt=3.1s (threshold 3.0s)", "quick_fix": "Quick Fix: x → https://h/p"},
    }

    lines = af._format_alert_text(alert, include_dashboard_link=True).splitlines()  # noqa: SLF001

    dashboard = f"📊 Dashboard: {af._build_public_dashboard_url()}"  # noqa: SLF001
    assert lines[0] == "🐢 System Anomaly Detected"
    assert lines[-2:] == ["Quick Fix: x → https://h/p", dashboard]


def test_the_direct_telegram_fallback_carries_the_quick_fix_line_too(monkeypatch):
    """כש-``alert_forwarder`` אינו זמין ההודעה יוצאת ישר לטלגרם (``_format_text``), ועם אותה שורה."""
    _clear_sentry_env(monkeypatch)
    _fresh_runbooks(monkeypatch)
    monkeypatch.setenv("ALERT_TELEGRAM_MIN_SEVERITY", "warn")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "chat")
    import internal_alerts as ia

    calls = []

    def _fake_request(method, url, json=None, timeout=5):  # noqa: ARG001
        calls.append(json)
        return None

    monkeypatch.setattr(ia, "request", _fake_request)
    monkeypatch.setattr(ia, "forward_alerts", None)

    ia.emit_internal_alert(
        name="docs_index_approval_needed",
        severity="warn",
        summary="waiting",
        details={"alert_type": "docs_index_approval_needed"},
    )

    [payload] = calls
    [quick_fix] = [line for line in payload["text"].splitlines() if line.startswith("Quick Fix: ")]
    assert quick_fix.endswith("/admin/docs-index")


def test_a_non_critical_alert_without_its_own_runbook_gets_no_quick_fix_line(monkeypatch):
    """בלי runbook משלה ההתראה לא מקבלת את השורה של runbook ברירת המחדל — היא הייתה נכנסת לכל הודעה."""
    _clear_sentry_env(monkeypatch)
    _fresh_runbooks(monkeypatch)
    import alert_forwarder as af

    untyped = _forwarded(monkeypatch, name="disk_low_space", severity="warn", summary="low", free_mb=10)
    unknown = _forwarded(
        monkeypatch, name="x", severity="warn", summary="y", details={"alert_type": "no_runbook_for_this"}
    )

    for forwarded in (untyped, unknown):
        assert "quick_fix" not in forwarded["annotations"]
        assert "Quick Fix:" not in af._format_alert_text(forwarded)  # noqa: SLF001


def test_a_critical_alert_without_its_own_runbook_still_gets_the_default_quick_fix_line(monkeypatch):
    """המסלול הקריטי לא השתנה: runbook ברירת המחדל עדיין נותן לו שורה."""
    _clear_sentry_env(monkeypatch)
    _fresh_runbooks(monkeypatch)
    import alert_manager as am

    text = am._format_text(name="High Latency", severity="CRITICAL", summary="lat>thr", details={})  # noqa: SLF001

    [quick_fix] = [line for line in text.splitlines() if line.startswith("Quick Fix: ")]
    link = quick_fix.rsplit(" → ", 1)[1]
    assert link.startswith(("http://", "https://")) and "/admin/observability?focus_ts=" in link


def test_internal_alerts_respect_min_severity_for_direct_telegram(monkeypatch):
    monkeypatch.setenv("ALERT_TELEGRAM_MIN_SEVERITY", "error")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "chat")

    import internal_alerts as ia
    importlib.reload(ia)

    calls = []

    def _fake_request(method, url, json=None, timeout=5):  # noqa: ARG001
        calls.append({"url": url, "payload": json})
        return None

    monkeypatch.setattr(ia, "request", _fake_request)
    monkeypatch.setattr(ia, "forward_alerts", None)

    ia.emit_internal_alert(name="low", severity="info", summary="skipme")
    assert calls == []

    ia.emit_internal_alert(name="high", severity="error", summary="sendme")
    assert len(calls) == 1
    assert "[ERROR]" in calls[0]["payload"]["text"]
