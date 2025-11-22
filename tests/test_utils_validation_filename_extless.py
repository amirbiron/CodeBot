from utils import ValidationUtils


def test_accepts_extensionless_and_dotfiles():
    assert ValidationUtils.is_valid_filename("Dockerfile") is True
    assert ValidationUtils.is_valid_filename("Makefile") is True
    assert ValidationUtils.is_valid_filename("run") is True
    assert ValidationUtils.is_valid_filename(".gitignore") is True


def test_rejects_dots_only_and_invalid_chars():
    assert ValidationUtils.is_valid_filename(".") is False
    assert ValidationUtils.is_valid_filename("..") is False
    assert ValidationUtils.is_valid_filename("////") is False
    assert ValidationUtils.is_valid_filename("a/b") is False


def test_rejects_only_punctuation_underscores_dashes():
    assert ValidationUtils.is_valid_filename("___") is False
    assert ValidationUtils.is_valid_filename("---") is False
    assert ValidationUtils.is_valid_filename("__--__") is False


def test_allows_regular_names_and_with_extension():
    assert ValidationUtils.is_valid_filename("script.py") is True
    assert ValidationUtils.is_valid_filename("__init__.py") is True
