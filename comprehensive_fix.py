#!/usr/bin/env python3
import re

# Read the file
with open("/workspace/github_menu_handler.py", "r") as f:
    lines = f.readlines()

# Track the expected indentation level based on control structures
indent_stack = [0]  # Stack to track indentation levels
fixed_lines = []
i = 0

while i < len(lines):
    line = lines[i]
    stripped = line.strip()

    if not stripped or stripped.startswith("#"):
        # Empty line or comment - preserve as is
        fixed_lines.append(line)
        i += 1
        continue

    # Calculate current expected indentation
    expected_indent = indent_stack[-1]

    # Check for dedenting keywords
    if stripped.startswith(("else:", "elif ", "except ", "finally:")):
        # These should be at the same level as their matching if/try
        if len(indent_stack) > 1:
            indent_stack.pop()
            expected_indent = indent_stack[-1]

    # Apply the indentation
    if stripped:
        actual_indent = len(line) - len(line.lstrip())
        if actual_indent != expected_indent:
            print(f"Fixed indentation at line {i+1}: expected {expected_indent}, was {actual_indent}")
            line = " " * expected_indent + stripped + "\n"

    fixed_lines.append(line)

    # Check if this line introduces a new indentation level
    if stripped.endswith(":") and not stripped.startswith("#"):
        # This is a control structure, increase indent for next lines
        indent_stack.append(expected_indent + 4)

    # Check for dedenting after certain statements
    if stripped in ["return", "break", "continue", "raise", "pass"]:
        if len(indent_stack) > 1:
            indent_stack.pop()

    i += 1

# Write the fixed file
with open("/workspace/github_menu_handler_fixed.py", "w") as f:
    f.writelines(fixed_lines)

print("\nCreated fixed version: github_menu_handler_fixed.py")

# Check syntax
import subprocess

result = subprocess.run(
    ["python3", "-m", "py_compile", "/workspace/github_menu_handler_fixed.py"], capture_output=True, text=True
)
if result.returncode == 0:
    print("✅ No syntax errors found in fixed version!")
    # Replace the original with the fixed version
    import shutil

    shutil.copy("/workspace/github_menu_handler_fixed.py", "/workspace/github_menu_handler.py")
    print("✅ Replaced original file with fixed version")
else:
    print("❌ Still has syntax errors in fixed version:")
    print(result.stderr[:1000])
