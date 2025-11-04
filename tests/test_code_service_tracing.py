import services.code_service as code_service


def test_validate_code_input_records_span(monkeypatch):
    recorded: list[dict[str, object]] = []

    def _record(attrs: dict[str, object]) -> None:
        recorded.append(dict(attrs))

    monkeypatch.setattr(code_service, "set_current_span_attributes", _record, raising=False)

    ok, cleaned, msg = code_service.validate_code_input("print('hi')", "demo.py", 123)

    assert ok
    assert cleaned.startswith("print")
    assert any(attrs.get("status") == "ok" for attrs in recorded)
