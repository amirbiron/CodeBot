"""
Tests for JSON Formatter Service
================================
"""

import json

import pytest

from services.json_formatter_service import JsonFormatterService


@pytest.fixture
def service() -> JsonFormatterService:
    return JsonFormatterService()


class TestFormatJson:
    def test_format_simple_object(self, service: JsonFormatterService) -> None:
        input_json = '{"a":1,"b":2}'
        result = service.format_json(input_json)
        assert result == '{\n  "a": 1,\n  "b": 2\n}'

    def test_format_with_custom_indent(self, service: JsonFormatterService) -> None:
        input_json = '{"a":1}'
        result = service.format_json(input_json, indent=4)
        assert '    "a"' in result

    def test_format_with_sort_keys(self, service: JsonFormatterService) -> None:
        input_json = '{"z":1,"a":2}'
        result = service.format_json(input_json, sort_keys=True)
        lines = result.split("\n")
        assert '"a"' in lines[1]
        assert '"z"' in lines[2]

    def test_format_invalid_json_raises(self, service: JsonFormatterService) -> None:
        with pytest.raises(json.JSONDecodeError):
            service.format_json("not json")

    def test_format_unicode(self, service: JsonFormatterService) -> None:
        input_json = '{"שם":"ערך"}'
        result = service.format_json(input_json)
        assert "שם" in result
        assert "ערך" in result


class TestMinifyJson:
    def test_minify_simple(self, service: JsonFormatterService) -> None:
        input_json = '{\n  "a": 1,\n  "b": 2\n}'
        result = service.minify_json(input_json)
        assert result == '{"a":1,"b":2}'

    def test_minify_removes_all_whitespace(self, service: JsonFormatterService) -> None:
        input_json = '{\n    "key"   :   "value"   \n}'
        result = service.minify_json(input_json)
        assert " " not in result
        assert "\n" not in result


class TestValidateJson:
    def test_validate_valid_json(self, service: JsonFormatterService) -> None:
        result = service.validate_json('{"valid": true}')
        assert result.is_valid is True
        assert result.error_message is None

    def test_validate_invalid_json(self, service: JsonFormatterService) -> None:
        result = service.validate_json("{invalid}")
        assert result.is_valid is False
        assert result.error_message is not None
        assert result.error_line is not None
        assert result.error_column is not None


class TestGetJsonStats:
    def test_stats_simple_object(self, service: JsonFormatterService) -> None:
        stats = service.get_json_stats('{"a": 1, "b": "text"}')
        assert stats.total_keys == 2
        assert stats.number_count == 1
        assert stats.string_count == 1

    def test_stats_nested_object(self, service: JsonFormatterService) -> None:
        json_str = '{"outer": {"inner": {"deep": 1}}}'
        stats = service.get_json_stats(json_str)
        assert stats.max_depth == 3
        assert stats.object_count == 3

    def test_stats_array(self, service: JsonFormatterService) -> None:
        stats = service.get_json_stats("[1, 2, 3, null, true]")
        assert stats.array_count == 1
        assert stats.number_count == 3
        assert stats.null_count == 1
        assert stats.boolean_count == 1


class TestFixCommonErrors:
    def test_fix_trailing_comma(self, service: JsonFormatterService) -> None:
        json_str = '{"a": 1,}'
        fixed, fixes = service.fix_common_errors(json_str)
        assert json.loads(fixed)
        assert "הוסרו פסיקים" in " ".join(fixes)

    def test_fix_single_quotes(self, service: JsonFormatterService) -> None:
        json_str = "{'a': 'value'}"
        fixed, fixes = service.fix_common_errors(json_str)
        assert json.loads(fixed)
        assert "מירכאות" in " ".join(fixes)

    def test_fix_single_quotes_does_not_corrupt_apostrophes_in_double_quoted_strings(
        self, service: JsonFormatterService
    ) -> None:
        json_str = """{'name': "John's book"}"""
        fixed, _fixes = service.fix_common_errors(json_str)
        parsed = json.loads(fixed)
        assert parsed["name"] == "John's book"

    def test_fix_signed_infinity(self, service: JsonFormatterService) -> None:
        json_str = '{"value": -Infinity}'
        fixed, fixes = service.fix_common_errors(json_str)
        parsed = json.loads(fixed)
        assert parsed["value"] is None
        assert "infinity" in " ".join(fixes).lower()

    def test_fix_signed_nan(self, service: JsonFormatterService) -> None:
        json_str = '{"value": -NaN}'
        fixed, fixes = service.fix_common_errors(json_str)
        parsed = json.loads(fixed)
        assert parsed["value"] is None
        assert "nan" in " ".join(fixes).lower()

    def test_fix_undefined(self, service: JsonFormatterService) -> None:
        json_str = '{"a": undefined}'
        fixed, fixes = service.fix_common_errors(json_str)
        assert json.loads(fixed)
        assert "undefined" in " ".join(fixes).lower()

    def test_fix_does_not_modify_valid_json_with_comma_brace_in_string(self, service: JsonFormatterService) -> None:
        json_str = '{"msg": "x,}"}'
        fixed, fixes = service.fix_common_errors(json_str)
        assert fixed == json_str
        assert fixes == []

    def test_fix_does_not_modify_valid_json_with_undefined_like_text_in_string(self, service: JsonFormatterService) -> None:
        json_str = '{"desc": ": undefined}"}'
        fixed, fixes = service.fix_common_errors(json_str)
        assert fixed == json_str
        assert fixes == []

