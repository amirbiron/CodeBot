import pytest


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "classic"),
        ("", "classic"),
        ("classic", "classic"),
        ("ocean", "ocean"),
        ("dark", "dark"),
        ("rose-pine-dawn", "rose-pine-dawn"),
        ("custom", "classic"),  # לא נתמך כברירת מחדל
        ("shared:tokyo-night", "shared:tokyo-night"),
        ("shared:ab", "shared:ab"),
        ("shared:INVALID", "shared:invalid"),  # מנורמל לאותיות קטנות
        ("shared:..", "classic"),
        ("shared:", "classic"),
        ("not-a-theme", "classic"),
    ],
)
def test_normalize_default_ui_theme_raw(raw, expected):
    from webapp.ui_theme_defaults import normalize_default_ui_theme_raw

    assert normalize_default_ui_theme_raw(raw) == expected


def test_get_default_ui_theme_raw_reads_env(monkeypatch):
    from webapp.ui_theme_defaults import get_default_ui_theme_raw

    monkeypatch.setenv("DEFAULT_UI_THEME", "ocean")
    assert get_default_ui_theme_raw() == "ocean"

    monkeypatch.setenv("DEFAULT_UI_THEME", "shared:tokyo-night")
    assert get_default_ui_theme_raw() == "shared:tokyo-night"

    monkeypatch.setenv("DEFAULT_UI_THEME", "INVALID")
    assert get_default_ui_theme_raw() == "classic"


def test_get_default_ui_theme_parts_builtin(monkeypatch):
    from webapp.ui_theme_defaults import get_default_ui_theme_parts

    monkeypatch.setenv("DEFAULT_UI_THEME", "ocean")
    theme_type, theme_id, theme_attr = get_default_ui_theme_parts()
    assert theme_type == "builtin"
    assert theme_id == "ocean"
    assert theme_attr == "ocean"


def test_get_default_ui_theme_parts_shared(monkeypatch):
    from webapp.ui_theme_defaults import get_default_ui_theme_parts

    monkeypatch.setenv("DEFAULT_UI_THEME", "shared:tokyo-night")
    theme_type, theme_id, theme_attr = get_default_ui_theme_parts()
    assert theme_type == "shared"
    assert theme_id == "tokyo-night"
    assert theme_attr == "shared:tokyo-night"

