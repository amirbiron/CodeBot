#!/usr/bin/env python3
import re

# Read the file
with open("/workspace/github_menu_handler.py", "r") as f:
    lines = f.readlines()

# Fix patterns where await query.edit_message_text is not properly indented after try:
i = 0
while i < len(lines):
    # Check if current line is "try:" with proper indentation
    if lines[i].strip() == "try:":
        indent = len(lines[i]) - len(lines[i].lstrip())
        # Check if next line starts with await query.edit_message_text but has wrong indentation
        if i + 1 < len(lines):
            next_line = lines[i + 1]
            if (
                "await query.edit_message_text" in next_line
                or "await query.answer" in next_line
                or "await update.message" in next_line
            ):
                # Check if it doesn't have the proper indentation (should be indent + 4)
                next_indent = len(next_line) - len(next_line.lstrip())
                if next_indent != indent + 4:
                    # Fix the indentation
                    lines[i + 1] = " " * (indent + 4) + next_line.lstrip()
                    print(f"Fixed indentation at line {i + 2}")

    # Also check for except blocks that are not properly indented
    if "except telegram.error.BadRequest as e:" in lines[i] or "except Exception as e:" in lines[i]:
        # Find the matching try block
        j = i - 1
        while j >= 0:
            if lines[j].strip() == "try:":
                try_indent = len(lines[j]) - len(lines[j].lstrip())
                except_indent = len(lines[i]) - len(lines[i].lstrip())
                if except_indent != try_indent:
                    lines[i] = " " * try_indent + lines[i].lstrip()
                    print(f"Fixed except indentation at line {i + 1}")
                break
            j -= 1

    i += 1

# Write the fixed file
with open("/workspace/github_menu_handler.py", "w") as f:
    f.writelines(lines)

print("Done fixing indentation issues")
