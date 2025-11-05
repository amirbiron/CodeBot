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


def test_validate_code_input_handles_non_string_input(monkeypatch):
    recorded: list[dict[str, object]] = []

    def _record(attrs: dict[str, object]) -> None:
        recorded.append(dict(attrs))

    class DummyProcessor:
        def validate_code_input(self, code, file_name, user_id):
            return False, "", "קלט קוד לא תקין או ריק"

    monkeypatch.setattr(code_service, "set_current_span_attributes", _record, raising=False)
    monkeypatch.setattr(code_service, "code_processor", DummyProcessor(), raising=False)

    ok, cleaned, msg = code_service.validate_code_input(123, "demo.py", 123)

    assert not ok
    assert cleaned == ""
    assert msg == "קלט קוד לא תקין או ריק"

    span_records = [attrs for attrs in recorded if "status" in attrs]
    assert span_records, "ציפינו לסטטוס span"
    assert any(attrs.get("status") == "error" for attrs in span_records)
    assert any(attrs.get("code.length.original") == 0 for attrs in span_records)
    assert any("error.message" in attrs for attrs in span_records)
