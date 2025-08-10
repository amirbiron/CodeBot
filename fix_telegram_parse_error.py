#!/usr/bin/env python3
import re

print("🔧 מתקן את בעיית הפרסינג של טלגרם...")

# קרא את הקובץ
with open("github_menu_handler.py", "r", encoding="utf-8") as f:
    content = f.read()

# מצא את הפונקציה show_suggestion_details
lines = content.split("\n")
fixed_lines = []
in_function = False
function_indent = 0

for i, line in enumerate(lines):
    # מצא את תחילת הפונקציה
    if "async def show_suggestion_details" in line:
        in_function = True
        function_indent = len(line) - len(line.lstrip())
        fixed_lines.append(line)
        continue

    # אם אנחנו בתוך הפונקציה
    if in_function:
        # בדוק אם יצאנו מהפונקציה
        if line.strip() and not line.startswith(" " * function_indent) and not line.startswith("\t"):
            in_function = False
        else:
            # תקן parse_mode
            if "parse_mode=" in line:
                if "Markdown" in line or "MARKDOWN" in line:
                    line = line.replace("'Markdown'", "'HTML'")
                    line = line.replace('"Markdown"', '"HTML"')
                    line = line.replace("ParseMode.MARKDOWN", "ParseMode.HTML")
                    line = line.replace("ParseMode.MARKDOWN_V2", "ParseMode.HTML")

            # תקן את הפורמט של ההודעות
            if "message = " in line or "text = " in line:
                # אם זו שורה שמכינה הודעה
                next_lines = []
                j = i
                while j < len(lines) - 1 and (
                    lines[j].endswith("\\") or lines[j + 1].startswith(" " * (function_indent + 4))
                ):
                    next_lines.append(lines[j])
                    j += 1

                # בנה מחדש את ההודעה
                if "**" in line:
                    line = line.replace("**", "")  # הסר זמנית
                if "```" in line:
                    line = line.replace("```python", "\n")
                    line = line.replace("```", "\n")

    fixed_lines.append(line)

# הוסף פונקציה לניקוי טקסט
helper_function = '''
def clean_for_telegram(text):
    """נקה טקסט לשליחה בטלגרם"""
    if not text:
        return ""
    
    # הסר תווי Markdown בעייתיים
    text = str(text)
    
    # החלף תווים בעייתיים
    replacements = {
        '**': '',
        '__': '',
        '```': '',
        '`': '',
        '[': '(',
        ']': ')',
        '_': '-',
        '*': '•'
    }
    
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    return text
'''

# הוסף את הפונקציה אחרי ה-imports
import_end = 0
for i, line in enumerate(fixed_lines):
    if line.startswith("class ") or line.startswith("def ") or line.startswith("async def "):
        import_end = i
        break

if import_end > 0:
    fixed_lines.insert(import_end, helper_function)

# שמור את הקובץ המתוקן
with open("github_menu_handler.py", "w", encoding="utf-8") as f:
    f.write("\n".join(fixed_lines))

print("✅ תיקון הושלם!")

# תיקון נוסף - wrap כל הודעה ב-try/except
additional_fix = '''
# עטוף כל שליחת הודעה ב-try/except
import re

with open('github_menu_handler.py', 'r', encoding='utf-8') as f:
    content = f.read()

# מצא כל מקום של edit_message_text
pattern = r'(await query\.edit_message_text\([^)]+\))'
def wrap_with_try(match):
    return f"""try:
        {match.group(1)}
    except telegram.error.BadRequest as e:
        if "Can't parse entities" in str(e):
            # נסה לשלוח בלי פורמט
            simple_text = clean_for_telegram(message) if 'message' in locals() else "הצעה לשיפור"
            await query.edit_message_text(simple_text)
        else:
            raise"""

content = re.sub(pattern, wrap_with_try, content)

with open('github_menu_handler.py', 'w', encoding='utf-8') as f:
    f.write(content)
'''

exec(additional_fix)

print("✅ הוספת error handling!")
