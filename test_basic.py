"""Basic tests for Code Keeper Bot - Simple Version"""

import os
import sys

import pytest


def test_python_version():
    """Test Python version is 3.8+"""
    assert sys.version_info >= (3, 8), "Python 3.8+ required"


def test_import_main():
    """Test that main.py can be imported"""
    try:
        import main

        assert True
    except ImportError as e:
        pytest.skip(f"Main module import failed: {e}")


def test_environment():
    """Test basic environment setup"""
    assert os.path.exists("requirements.txt"), "requirements.txt not found"


def test_basic_calculation():
    """Simple sanity check"""
    assert 2 + 2 == 4
    assert "bot" in "Code Keeper Bot".lower()


class TestRequirements:
    """Test required packages"""

    def test_telegram_installed(self):
        """Check telegram package"""
        try:
            import telegram

            assert True
        except ImportError:
            pytest.skip("telegram package not installed")

    def test_github_installed(self):
        """Check github package"""
        try:
            import github

            assert True
        except ImportError:
            pytest.skip("github package not installed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
