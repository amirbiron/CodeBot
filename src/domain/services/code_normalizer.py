"""
Domain service: normalize code content.

Pure Python only. Mirrors default behavior of utils.normalize_code with defaults:
- strip BOM
- normalize CRLF/CR to LF
- replace NBSP/NNBSP with space
- replace Unicode space separators (Zs) with ASCII space
- remove zero-width and directional marks
- remove control/format characters except \t, \n, \r
- trim trailing whitespace per line
- drop trailing newline characters introduced by per-line trimming
- handle literal escapes like "\\u200B" by stripping hidden characters

Note: intentionally does NOT force a trailing newline to preserve legacy behavior.
"""

from __future__ import annotations

import unicodedata
import re
from typing import Any


class CodeNormalizer:
    """Normalize code strings into a safe, consistent form.

    The implementation avoids any framework or I/O dependencies.
    """

    _ZERO_WIDTH = {
        "\u200B",  # ZWSP
        "\u200C",  # ZWNJ
        "\u200D",  # ZWJ
        "\u2060",  # WJ
        "\uFEFF",  # ZWNBSP/BOM
    }

    _DIRECTIONAL = {
        "\u200E",  # LRM
        "\u200F",  # RLM
        "\u202A",  # LRE
        "\u202B",  # RLE
        "\u202C",  # PDF
        "\u202D",  # LRO
        "\u202E",  # RLO
        "\u2066",  # LRI
        "\u2067",  # RLI
        "\u2068",  # FSI
        "\u2069",  # PDI
    }

    def normalize(self, text: Any) -> str:
        """Normalize code text.

        If text is not a string, returns an empty string for None or the original
        value for non-string inputs (mirrors legacy behavior as closely as practical).
        """
        if not isinstance(text, str):
            return text if text is not None else ""

        out = text

        # Handle sequences like "\\u200B" and "\\U0001F600" that represent hidden/format chars literally
        if ("\\u" in out) or ("\\U" in out):
            out = strip_hidden_escapes(out)

        # 1) Strip BOM at start
        if out.startswith("\ufeff"):
            out = out.lstrip("\ufeff")

        # 2) Normalize newlines to LF
        out = out.replace("\r\n", "\n").replace("\r", "\n")

        # 3) Replace NBSP/NNBSP with regular space
        out = out.replace("\u00A0", " ").replace("\u202F", " ")

        # 4) Replace all Unicode space separators (Zs) with ASCII space
        try:
            out = "".join(" " if unicodedata.category(ch) == "Zs" else ch for ch in out)
        except Exception:
            pass

        # 5) Remove zero-width and directional formatting characters, and control/format chars
        def _keep_char(ch: str) -> bool:
            # Keep tabs/newlines/carriage returns
            if ch in ("\t", "\n", "\r"):
                return True
            if ch in self._ZERO_WIDTH:
                return False
            if ch in self._DIRECTIONAL:
                return False
            cat = unicodedata.category(ch)
            # Drop control characters (Cc) except the kept whitespace above
            if cat == "Cc" and ch not in ("\t", "\n", "\r"):
                return False
            # Drop other format characters (Cf)
            if cat == "Cf":
                return False
            return True

        out = "".join(ch for ch in out if _keep_char(ch))

        # 6) Trim trailing whitespace for each line
        out = "\n".join(line.rstrip(" \t") for line in out.split("\n"))

        # 7) Drop trailing newline characters so we don't force a newline at EOF
        out = out.rstrip("\n")

        return out

    # ``_strip_hidden_escapes`` היה כאן כמתודה, עם ``_KNOWN_ESCAPE_HEX4`` — עותק
    # שני של אותה פונקציה ואותה רשימה מ-``utils.normalize_code`` (#3427).
    # ההגדרה האחת היא :func:`strip_hidden_escapes` למטה, ושני הצרכנים קוראים לה.


# תווי Variation Selector: ``Mn`` ולא ``Cf``, ולכן בדיקת הקטגוריה אינה תופסת
# אותם והם צריכים תנאי משלהם — שנדלק רק לפי בקשה.
_VS_HEX4 = range(0xFE00, 0xFE0F + 1)
_IDEOGRAPHIC_VS = range(0xE0100, 0xE01EF + 1)

_ESCAPE_U4 = re.compile(r"\\u([0-9a-fA-F]{4})")
_ESCAPE_U8 = re.compile(r"\\U([0-9a-fA-F]{8})")


def strip_hidden_escapes(s: str, *, remove_variation_selectors: bool = False) -> str:
    """מסיר רצפי בריחה טקסטואליים (``\\uXXXX``, ``\\UXXXXXXXX``) שמייצגים תווי פורמט.

    **ההגדרה היחידה, לשני הצרכנים** — :meth:`CodeNormalizer.normalize` ו-
    ``utils.normalize_code`` (#3427). עד אז כל אחד מהם החזיק עותק של אותה
    פונקציה, ולפניה רשימה של 16 קודים "ידועים" (``_KNOWN_ESCAPE_HEX4`` /
    ``known_hex4``) שנבדקה לפני בדיקת הקטגוריה. נמדד: כל 16 הערכים הם
    ``Cf``, כלומר הרשימה לא הוסיפה דבר על ``unicodedata.category`` — מסלול
    מהיר שאיש לא מדד, בשני עותקים שהיו צריכים להסכים לנצח. ומי שהיה מוסיף
    קוד לרשימה באחד הקבצים לא היה משנה דבר בפועל, ומסיק שהתיקון עבד.
    **רשימה היא העתק של ידע שצריך להסכים עם עצמו; קטגוריה היא הגדרה
    שמתעדכנת עם התקן** — ולכן נשארה הקטגוריה לבדה.

    - ``Cf`` (format) מוסר תמיד, בשתי הצורות.
    - Variation Selectors (``U+FE00``–``U+FE0F`` ו-``U+E0100``–``U+E01EF``)
      הם ``Mn`` ולא ``Cf``, ולכן הם ענף נפרד שנדלק רק עם
      ``remove_variation_selectors=True`` — ברירת המחדל שומרת אותם, כמו קודם
      בשני הצרכנים. **ההחלטה היא על קוד התו, לא על צורת הכתיב:** ``\\U0000FE0F``
      הוא אותו תו כמו ``\\uFE0F`` ומקבל אותה תשובה. עד סקירת #3443 הענף הארוך
      בדק רק את הטווח האידאוגרפי, כאילו הכתיב קובע את הטווח.
    - רצף שאינו מתפענח לקוד תו (``\\uZZZZ`` אינו תואם את הביטוי; ``chr``
      מעבר לטווח) נשאר כמות שהוא.
    """

    def _is_hidden(code: int) -> bool:
        # הכלל האחד לשתי הצורות. ``chr`` מרים ``ValueError``/``OverflowError``
        # מעל U+10FFFF — הצורה הארוכה היא היחידה שיכולה להגיע לשם, והיא תופסת.
        if unicodedata.category(chr(code)) == "Cf":
            return True
        return remove_variation_selectors and (code in _VS_HEX4 or code in _IDEOGRAPHIC_VS)

    def _strip_if_hidden_u4(m: "re.Match[str]") -> str:
        return "" if _is_hidden(int(m.group(1), 16)) else m.group(0)

    def _strip_if_hidden_u8(m: "re.Match[str]") -> str:
        try:
            hidden = _is_hidden(int(m.group(1), 16))
        except (ValueError, OverflowError):
            return m.group(0)  # מעבר לטווח Unicode — לא תו, נשאר כמות שהוא
        return "" if hidden else m.group(0)

    s = _ESCAPE_U4.sub(_strip_if_hidden_u4, s)
    s = _ESCAPE_U8.sub(_strip_if_hidden_u8, s)
    return s
