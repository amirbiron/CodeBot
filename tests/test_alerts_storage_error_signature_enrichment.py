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


def test_compute_error_signature_normalizes_memory_addresses_and_paths():
    from monitoring.alerts_storage import compute_error_signature

    e1 = {
        "error_type": "TypeError",
        "file": "/home/ubuntu/app/service.py",
        "line": 123,
        "error_message": "Object <Foo at 0x7f1234567890> is not callable (see /home/ubuntu/app/service.py:123)",
        "stack_trace": 'Traceback (most recent call last):\n  File "/home/ubuntu/app/service.py", line 123, in run\n    x = Foo()\nTypeError: <Foo at 0x7f1234567890> is not callable',
    }
    e2 = {
        "error_type": "TypeError",
        "file": "/srv/app/service.py",
        "line": 123,
        "error_message": "Object <Foo at 0x7fDEADBEEF00> is not callable (see /srv/app/service.py:999)",
        "stack_trace": 'Traceback (most recent call last):\n  File "/srv/app/service.py", line 999, in run\n    x = Foo()\nTypeError: <Foo at 0x7fDEADBEEF00> is not callable',
    }

    s1 = compute_error_signature(e1)
    s2 = compute_error_signature(e2)
    assert s1 == s2
    assert len(s1) == 16


def test_is_new_error_false_on_second_alert_when_only_memory_addresses_change(monkeypatch):
    import monitoring.alerts_storage as als

    seen: set[str] = set()

    def _fake_is_new(signature: str) -> bool:
        if signature in seen:
            return False
        seen.add(signature)
        return True

    monkeypatch.setattr(als, "is_new_error", _fake_is_new)

    a1 = {
        "error_type": "ValueError",
        "file": "/home/user/app/handler.py",
        "line": 10,
        "error_message": "Bad value <Bar at 0x7f1111111111>",
        "stack_trace": 'Traceback (most recent call last):\n  File "/home/user/app/handler.py", line 10, in h\n    raise ValueError("x")\nValueError: Bad value <Bar at 0x7f1111111111>',
    }
    a2 = {
        "error_type": "ValueError",
        "file": "/srv/app/handler.py",
        "line": 10,
        "error_message": "Bad value <Bar at 0x7f2222222222>",
        "stack_trace": 'Traceback (most recent call last):\n  File "/srv/app/handler.py", line 11, in h\n    raise ValueError("x")\nValueError: Bad value <Bar at 0x7f2222222222>',
    }

    als.enrich_alert_with_signature(a1)
    als.enrich_alert_with_signature(a2)

    assert a1["error_signature_hash"] == a2["error_signature_hash"]
    assert a1["is_new_error"] is True
    assert a2["is_new_error"] is False


def test_compute_error_signature_uses_sentry_issue_id_when_present():
    from monitoring.alerts_storage import compute_error_signature

    sig = compute_error_signature({"sentry_issue_id": "12345"})
    assert sig
    assert len(sig) == 16


def test_compute_error_signature_finds_sentry_issue_id_inside_error_data():
    from monitoring.alerts_storage import compute_error_signature

    sig = compute_error_signature({"error_data": {"sentry_issue_id": "999"}})
    assert sig
    assert len(sig) == 16


def test_compute_error_signature_finds_sentry_issue_id_deep_inside_original_payload():
    """
    רגרסיה: בעבר החיפוש היה עד עומק קטן/עם allowlist של מפתחות,
    ולכן sentry_issue_id עמוק בתוך payload מקונן לא נמצא והחתימה יצאה ריקה.
    """
    from monitoring.alerts_storage import compute_error_signature

    payload = {
        "payload": {
            "l1": {
                "l2": {
                    "l3": {
                        "l4": {
                            "l5": {
                                "l6": {
                                    "l7": {
                                        "l8": {
                                            "sentry_issue_id": "DEEP-12345",
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    sig = compute_error_signature(payload)
    assert sig
    assert len(sig) == 16


def test_compute_error_signature_finds_sentry_issue_id_inside_list_payload():
    from monitoring.alerts_storage import compute_error_signature

    sig = compute_error_signature({"payload": [{"x": {"sentry_issue_id": "LIST-777"}}]})
    assert sig
    assert len(sig) == 16


def test_compute_error_signature_ignores_whitespace_sentry_issue_id_and_falls_back_to_issue_id():
    from monitoring.alerts_storage import compute_error_signature

    sig = compute_error_signature({"error_data": {"sentry_issue_id": "   ", "issue_id": "12345"}})
    assert sig
    assert len(sig) == 16


def test_enrich_alert_with_signature_does_not_trust_is_new_error_without_hash(monkeypatch):
    """
    הגנה מפני payloads שמגיעים עם is_new_error=True מראש (למשל sentry_polling),
    אבל בלי hash — במקרה כזה חייבים לפנות ל-DB (או לפונקציית is_new_error) כדי להחליט.
    """
    import monitoring.alerts_storage as als

    calls = {"count": 0}

    def _fake_is_new(_sig: str) -> bool:
        calls["count"] += 1
        return False

    monkeypatch.setattr(als, "is_new_error", _fake_is_new)

    details = {"is_new_error": True, "error_data": {"sentry_issue_id": "12345"}}
    als.enrich_alert_with_signature(details)

    assert calls["count"] == 1
    assert details["error_signature_hash"]
    assert details["is_new_error"] is False


def test_enrich_alert_with_signature_does_not_add_signature_fields_when_no_signal(monkeypatch):
    import monitoring.alerts_storage as als

    # אם אין חתימה, אסור לפנות ל-DB בכלל
    monkeypatch.setattr(
        als,
        "is_new_error",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("should not be called")),
    )

    details = {
        "labels": ["observability", "grafana"],
        "slow_endpoints": [],
        "sentry_issue_id": "",
        "summary": "",
    }
    als.enrich_alert_with_signature(details)

    assert "error_signature_hash" not in details
    assert "is_new_error" not in details
    # אל תוסיף error_signature אם אין תוכן אמיתי
    assert "error_signature" not in details


def test_enrich_alert_with_signature_preserves_sentry_fields_and_only_adds_signature(monkeypatch):
    import monitoring.alerts_storage as als

    monkeypatch.setattr(als, "is_new_error", lambda *_a, **_k: True)

    details = {
        "sentry_issue_id": "12345",
        "sentry_first_seen": "2025-12-01T00:00:00Z",
        "labels": ["a", "b"],
    }
    als.enrich_alert_with_signature(details)

    assert details["sentry_issue_id"] == "12345"
    assert details["sentry_first_seen"] == "2025-12-01T00:00:00Z"
    assert details["labels"] == ["a", "b"]
    assert details["error_signature_hash"]
    assert details["error_signature"]
    assert details["is_new_error"] is True


def test_sanitize_details_preserves_lists_for_labels_and_slow_endpoints():
    from monitoring.alerts_storage import _sanitize_details

    raw = {
        "labels": ["observability", "sentry"],
        "slow_endpoints": ["/api/v1/users", "/healthz"],
        # חשוב: גם רשימות ריקות לא אמורות להפוך ל-"" או להיעלם
        "slow_endpoints_empty": [],
    }

    clean = _sanitize_details(raw)

    assert isinstance(clean["labels"], list)
    assert clean["labels"] == ["observability", "sentry"]

    assert isinstance(clean["slow_endpoints"], list)
    assert clean["slow_endpoints"] == ["/api/v1/users", "/healthz"]

    assert "slow_endpoints_empty" in clean
    assert isinstance(clean["slow_endpoints_empty"], list)
    assert clean["slow_endpoints_empty"] == []


def test_sanitize_details_does_not_drop_deep_lists_when_depth_limit_reached():
    """
    רגרסיה: כשהגענו ל-depth limit, הסניטייזר היה מחזיר [] / {} וכך מאבד מידע.
    אנחנו רוצים לשמור dict/list כ-JSON תקין גם אם לא נכנסים לרקורסיה נוספת.
    """
    from monitoring.alerts_storage import _sanitize_details

    raw = {"a": {"b": {"c": {"d": {"e": {"f": {"slow_endpoints": ["/x", "/y"]}}}}}}}
    clean = _sanitize_details(raw)

    assert isinstance(clean["a"], dict)
    assert clean["a"]["b"]["c"]["d"]["e"]["f"]["slow_endpoints"] == ["/x", "/y"]


def test_sanitize_details_redacts_sensitive_keys_even_at_depth_limit():
    """
    רגרסיה: בקצה העומק אנחנו עושים העתקה שטוחה כדי לא לשבור JSON,
    אבל עדיין חייבים לבצע Redaction שטחי למפתחות רגישים (password/token/secret וכו').
    """
    from monitoring.alerts_storage import _sanitize_details

    raw = {"a": {"b": {"c": {"d": {"e": {"f": {"wrapper": {"password": "secret"}}}}}}}}
    clean = _sanitize_details(raw)

    assert clean["a"]["b"]["c"]["d"]["e"]["f"]["wrapper"]["password"] == "<REDACTED>"
