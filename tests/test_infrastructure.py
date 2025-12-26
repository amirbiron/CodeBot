"""
Infrastructure Tests for Code Tools
===================================
בדיקות שפיות (Sanity Checks) לוודא שהסביבה מוכנה ושהכלים החיצוניים (Black, Flake8 וכו') מותקנים וזמינים.
"""

import shutil
import subprocess
import pytest
import sys
from pathlib import Path

# נסיון לייבא את השירות - בהנחה שיצרת את הקובץ לפי המדריך
try:
    from services.code_formatter_service import CodeFormatterService

    SERVICE_AVAILABLE = True
except ImportError:
    SERVICE_AVAILABLE = False


class TestEnvironmentTools:
    """בדיקה שהכלים הבינאריים מותקנים בסביבה (Path)."""

    def test_python_version(self):
        """בדיקה שאנחנו רצים על גרסת פייתון תקינה."""
        assert sys.version_info >= (3, 8), "נדרש Python 3.8 ומעלה"

    @pytest.mark.parametrize("tool_name", ["black", "flake8", "isort", "autopep8"])
    def test_tool_executable_exists(self, tool_name):
        """
        בדיקה שהקובץ הבינארי של הכלי קיים ב-PATH.
        אם זה נכשל -> ודא שהתקנת את requirements.txt
        """
        executable_path = shutil.which(tool_name)
        assert executable_path is not None, f"הכלי {tool_name} לא נמצא ב-PATH. האם הרצת pip install?"

    @pytest.mark.parametrize("tool_name", ["black", "flake8", "isort", "autopep8"])
    def test_tool_runnable(self, tool_name):
        """
        בדיקה שהכלי אכן רץ ומחזיר גרסה (לא קורס בהפעלה).
        """
        try:
            # מריצים פקודת version פשוטה
            result = subprocess.run([tool_name, "--version"], capture_output=True, text=True, timeout=5)
            assert result.returncode == 0, f"הכלי {tool_name} נכשל בריצה (Exit code {result.returncode})"
            assert len(result.stdout) > 0, f"הכלי {tool_name} לא החזיר פלט"

        except FileNotFoundError:
            pytest.fail(f"הכלי {tool_name} לא נמצא (FileNotFoundError)")
        except Exception as e:
            pytest.fail(f"שגיאה בהרצת {tool_name}: {e}")


@pytest.mark.skipif(not SERVICE_AVAILABLE, reason="services.code_formatter_service טרם נוצר")
class TestServiceIntegration:
    """בדיקה שהשירות שלנו יודע לדבר עם הכלים."""

    def test_service_initialization(self):
        """בדיקה שהשירות עולה בלי שגיאות."""
        service = CodeFormatterService()
        assert service is not None

    def test_service_detects_tools(self):
        """בדיקה שהשירות מזהה שהכלים זמינים (is_tool_available)."""
        service = CodeFormatterService()

        # אנחנו מצפים שכל הכלים יהיו זמינים בסביבת הפיתוח
        missing_tools = []
        for tool in ["black", "flake8", "isort", "autopep8"]:
            if not service.is_tool_available(tool):
                missing_tools.append(tool)

        assert not missing_tools, f"השירות לא זיהה את הכלים הבאים: {missing_tools}"

    def test_service_simple_format_call(self):
        """בדיקת אינטגרציה מינימלית: שליחה וקבלה של קוד."""
        service = CodeFormatterService()

        # קוד פשוט אך לא מעוצב
        ugly_code = "x=1+   2"

        # הרצה אמיתית מול black
        result = service.format_code(ugly_code, tool="black")

        assert result.success is True, f"הפרמוט נכשל: {result.error_message}"
        assert result.formatted_code.strip() == "x = 1 + 2"
        assert result.tool_used == "black"

