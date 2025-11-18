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
- handle literal escapes like "\u200B" by stripping hidden characters

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

    _KNOWN_ESCAPE_HEX4 = {
        "200B", "200C", "200D", "2060", "FEFF",  # zero-width set
        "200E", "200F", "202A", "202B", "202C", "202D", "202E",  # directional
        "2066", "2067", "2068", "2069",  # directional isolates
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
            out = self._strip_hidden_escapes(out)

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

        return out

    def _strip_hidden_escapes(self, s: str) -> str:
        """Remove literal unicode escape sequences for hidden/format characters.

        - Removes escapes in KNOWN sets or with Unicode category Cf
        - Handles both \uXXXX and \UXXXXXXXX forms
        """
        def _strip_if_hidden_u4(m: "re.Match[str]") -> str:
            hexcode = m.group(1).upper()
            if hexcode in self._KNOWN_ESCAPE_HEX4:
                return ""
            try:
                ch = chr(int(hexcode, 16))
                cat = unicodedata.category(ch)
                if cat == "Cf":
                    return ""
                # Variation Selectors (FE00..FE0F) are kept by default (compatibility)
            except Exception:
                pass
            return m.group(0)

        def _strip_if_hidden_u8(m: "re.Match[str]") -> str:
            hexcode = m.group(1).upper()
            try:
                ch = chr(int(hexcode, 16))
                if unicodedata.category(ch) == "Cf":
                    return ""
                # Ideographic Variation Selectors (E0100..E01EF) are kept by default
            except Exception:
                pass
            return m.group(0)

        s = re.sub(r"\\u([0-9a-fA-F]{4})", _strip_if_hidden_u4, s)
        s = re.sub(r"\\U([0-9a-fA-F]{8})", _strip_if_hidden_u8, s)
        return s
