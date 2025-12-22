def test_compute_error_signature_returns_empty_when_no_signal():
    from monitoring.alerts_storage import compute_error_signature

    assert compute_error_signature({}) == ""
    assert compute_error_signature({"error_type": "", "file": "", "line": ""}) == ""


def test_compute_error_signature_uses_only_first_three_stack_lines():
    from monitoring.alerts_storage import compute_error_signature

    base = {
        "error_type": "ConnectionError",
        "file": "api.py",
        "line": 42,
        "stack_trace": "L1\nL2\nL3\nL4\nL5",
    }
    s1 = compute_error_signature(base)
    s2 = compute_error_signature({**base, "stack_trace": "L1\nL2\nL3\nDIFFERENT\nDIFFERENT"})
    assert s1 == s2
    assert len(s1) == 16


def test_enrich_alert_with_signature_preserves_existing_error_signature(monkeypatch):
    import monitoring.alerts_storage as als

    monkeypatch.setattr(als, "is_new_error", lambda *_a, **_k: True)

    details = {
        "error_signature": "OOM_KILLED",
        "error_type": "OOM",
        "file": "worker.py",
        "line": 10,
        "stack_trace": "a\nb\nc\nd",
    }
    als.enrich_alert_with_signature(details)
    assert details["error_signature"] == "OOM_KILLED"
    assert details["error_signature_hash"]
    assert details["is_new_error"] is True


def test_enrich_alert_with_signature_is_idempotent(monkeypatch):
    import monitoring.alerts_storage as als

    calls = {"count": 0}

    def _counting(*_a, **_k):
        calls["count"] += 1
        return True

    monkeypatch.setattr(als, "is_new_error", _counting)

    details = {"error_type": "E", "file": "f.py", "line": 1, "stack_trace": "x"}
    als.enrich_alert_with_signature(details)
    assert calls["count"] == 1

    # Second call should not hit DB again because is_new_error already present
    monkeypatch.setattr(als, "is_new_error", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("should not be called")))
    als.enrich_alert_with_signature(details)
    assert details["is_new_error"] in (True, False)
