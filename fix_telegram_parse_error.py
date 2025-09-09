#!/usr/bin/env python3
"""
כלי עזר לתיקון בעיות Parse בטלגרם בקבצי ההנדלר.

מודול זה מספק פונקציות עזר לביצוע תיקונים אוטומטיים בקובץ
`github_menu_handler.py`. הייבוא של המודול אינו מבצע שינויים
בפועל; לשם כך יש להריץ את הסקריפט כ־main או לקרוא לפונקציות ישירות.
"""

import re
from typing import List


def clean_for_telegram(text: str) -> str:
    """ניקוי טקסט לשליחה בטלגרם (הסרת תווי Markdown בעייתיים)."""
    if not text:
        return ""
    text = str(text)
    replacements = {
        "**": "",
        "__": "",
        "```": "",
        "`": "",
        "[": "(",
        "]": ")",
        "_": "-",
        "*": "•",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def apply_fix(file_path: str = "github_menu_handler.py") -> None:
    """מיישם תיקוני parse_mode ותבניות הודעה בתוך פונקציית ההצגה."""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines: List[str] = content.split("\n")
    fixed_lines: List[str] = []
    in_function = False
    function_indent = 0

    for i, line in enumerate(lines):
        if "async def show_suggestion_details" in line:
            in_function = True
            function_indent = len(line) - len(line.lstrip())
            fixed_lines.append(line)
            continue

        if in_function:
            if line.strip() and not line.startswith(" " * function_indent) and not line.startswith("\t"):
                in_function = False
            else:
                if "parse_mode=" in line:
                    if "Markdown" in line or "MARKDOWN" in line:
                        line = line.replace("'Markdown'", "'HTML'")
                        line = line.replace('"Markdown"', '"HTML"')
                        line = line.replace("ParseMode.MARKDOWN", "ParseMode.HTML")
                        line = line.replace("ParseMode.MARKDOWN_V2", "ParseMode.HTML")
                if "message = " in line or "text = " in line:
                    if "**" in line:
                        line = line.replace("**", "")
                    if "```" in line:
                        line = line.replace("```python", "\n")
                        line = line.replace("```", "\n")

        fixed_lines.append(line)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(fixed_lines))


def wrap_edit_message_calls(file_path: str = "github_menu_handler.py") -> None:
    """עוטף קריאות edit_message_text ב־try/except ומנקה טקסט בעת שגיאת פרסינג."""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = r"(await query\.edit_message_text\([^)]+\))"

    def _wrap(match: re.Match) -> str:
        call = match.group(1)
        return (
            "try:\n"
            f"        {call}\n"
            "    except telegram.error.BadRequest as e:\n"
            "        if \"Can't parse entities\" in str(e):\n"
            "            simple_text = clean_for_telegram(locals().get('message', 'הצעה לשיפור'))\n"
            "            await query.edit_message_text(simple_text)\n"
            "        else:\n"
            "            raise"
        )

    new_content = re.sub(pattern, _wrap, content)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)


if __name__ == "__main__":
    # הרצה ידנית בלבד
    apply_fix()
    wrap_edit_message_calls()
    print("✅ תיקונים הוחלו בהצלחה על github_menu_handler.py")