from __future__ import annotations

import re


class ReminderValidator:
    # Allow common letters, whitespace, Hebrew, punctuation and basic symbols
    pattern = re.compile(r"^[\w\sא-ת\.\,\;\:\!\?\'\"\(\)\-\/\\]+$")

    def validate_text(self, text: str) -> bool:
        try:
            if not isinstance(text, str):
                return False
            if not text:
                return True
            if len(text) > 2000:
                return False
            return bool(self.pattern.match(text))
        except Exception:
            return False
