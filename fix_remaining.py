#!/usr/bin/env python3
import re

# Read the file
with open("/workspace/github_menu_handler.py", "r") as f:
    content = f.read()

# Fix specific patterns
lines = content.split("\n")
fixed_lines = []
i = 0

while i < len(lines):
    line = lines[i]

    # Fix comments that are not properly indented after if/for/while/try statements
    if i > 0 and lines[i - 1].strip().endswith(":"):
        if line.strip().startswith("#"):
            # This is a comment after a colon, fix indentation
            prev_indent = len(lines[i - 1]) - len(lines[i - 1].lstrip())
            fixed_lines.append(" " * (prev_indent + 4) + line.strip())
            i += 1
            continue

    # Fix lines with "raise," which should be just "raise"
    if line.strip() == "raise," or line.strip() == 'raise:",':
        indent = len(line) - len(line.lstrip())
        fixed_lines.append(" " * indent + "raise")
        i += 1
        continue

    # Fix lines with "raise]," which should be just "raise"
    if "raise]," in line or "raise]" in line:
        line = line.replace("raise],", "raise").replace("raise]", "raise")

    fixed_lines.append(line)
    i += 1

# Write the fixed content
with open("/workspace/github_menu_handler.py", "w") as f:
    f.write("\n".join(fixed_lines))

print("Fixed remaining syntax issues")

# Now check the file
import subprocess

result = subprocess.run(
    ["python3", "-m", "py_compile", "/workspace/github_menu_handler.py"], capture_output=True, text=True
)
if result.returncode == 0:
    print("✅ No syntax errors found!")
else:
    print("❌ Still has syntax errors:")
    print(result.stderr[:500])
