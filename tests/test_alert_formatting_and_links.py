import importlib
import os


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
    assert "http://alert.example/am" in text
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
