#!/usr/bin/env python3
import re

# Read the file
with open("/workspace/github_menu_handler.py", "r") as f:
    lines = f.readlines()

# Track if we're in a try block and need to close parentheses
i = 0
while i < len(lines):
    line = lines[i]

    # Fix missing closing parentheses for await query.edit_message_text
    if (
        "await query.edit_message_text(" in line
        or "await query.answer" in line
        or "await update.message.reply_text(" in line
    ):
        # Check if this line starts a multi-line call
        if not line.rstrip().endswith(")"):
            # Find where this call should end (before except or another statement)
            j = i + 1
            paren_count = line.count("(") - line.count(")")
            while j < len(lines) and paren_count > 0:
                paren_count += lines[j].count("(") - lines[j].count(")")
                if "except" in lines[j] and paren_count > 0:
                    # Need to close the parenthesis before except
                    lines[j - 1] = lines[j - 1].rstrip() + ")\n"
                    print(f"Added closing parenthesis before line {j+1}")
                    paren_count -= 1
                j += 1

    # Fix indentation for lines after try:
    if line.strip() == "try:":
        indent = len(line) - len(line.lstrip())
        # Check next lines
        if i + 1 < len(lines):
            next_line = lines[i + 1]
            if "await" in next_line or "with" in next_line or "if" in next_line:
                next_indent = len(next_line) - len(next_line.lstrip())
                if next_indent != indent + 4:
                    lines[i + 1] = " " * (indent + 4) + next_line.lstrip()
                    print(f"Fixed indentation at line {i + 2}")

    # Fix indentation for except blocks
    if "except" in line and ":" in line:
        # Find the matching try
        j = i - 1
        try_indent = None
        while j >= 0:
            if lines[j].strip().startswith("try:"):
                try_indent = len(lines[j]) - len(lines[j].lstrip())
                break
            j -= 1

        if try_indent is not None:
            except_indent = len(line) - len(line.lstrip())
            if except_indent != try_indent:
                lines[i] = " " * try_indent + line.lstrip()
                print(f"Fixed except indentation at line {i + 1}")

            # Fix the content of except block
            if i + 1 < len(lines):
                k = i + 1
                while (
                    k < len(lines)
                    and lines[k].strip()
                    and not lines[k].strip().startswith("except")
                    and not lines[k].strip().startswith("else:")
                    and not lines[k].strip().startswith("finally:")
                ):
                    if (
                        lines[k].strip().startswith("if")
                        or lines[k].strip().startswith("raise")
                        or lines[k].strip().startswith("#")
                    ):
                        content_indent = len(lines[k]) - len(lines[k].lstrip())
                        if content_indent != try_indent + 4:
                            lines[k] = " " * (try_indent + 4) + lines[k].lstrip()
                            print(f"Fixed except block content indentation at line {k + 1}")
                    k += 1

    i += 1

# Write the fixed file
with open("/workspace/github_menu_handler.py", "w") as f:
    f.writelines(lines)

print("Done fixing syntax and indentation issues")
