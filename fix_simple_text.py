#!/usr/bin/env python3

# Read the file
with open("/workspace/github_menu_handler.py", "r") as f:
    lines = f.readlines()

# Fix all simple_text lines that are incorrectly indented
for i in range(len(lines)):
    if "simple_text = clean_for_telegram" in lines[i]:
        # This line should have the same indentation as the comment above it
        if i > 0 and "# נסה לשלוח בלי פורמט" in lines[i - 1]:
            comment_indent = len(lines[i - 1]) - len(lines[i - 1].lstrip())
            lines[i] = " " * comment_indent + lines[i].strip() + "\n"
            # Also fix the next line (await query.edit_message_text)
            if i + 1 < len(lines) and "await query.edit_message_text(simple_text)" in lines[i + 1]:
                lines[i + 1] = " " * comment_indent + lines[i + 1].strip() + "\n"

# Write the fixed file
with open("/workspace/github_menu_handler.py", "w") as f:
    f.writelines(lines)

print("Fixed all simple_text indentation issues")

# Check syntax
import subprocess

result = subprocess.run(
    ["python3", "-m", "py_compile", "/workspace/github_menu_handler.py"], capture_output=True, text=True
)
if result.returncode == 0:
    print("✅ No syntax errors found!")
else:
    print("❌ Still has syntax errors:")
    print(result.stderr)
