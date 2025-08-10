#!/usr/bin/env python3

# Read the file
with open("/workspace/github_menu_handler.py", "r") as f:
    lines = f.readlines()

# Fix all indentation issues
i = 0
while i < len(lines):
    line = lines[i]
    stripped = line.strip()

    # Fix lines that should be indented more
    if i > 0:
        prev_line = lines[i - 1].strip()
        prev_indent = len(lines[i - 1]) - len(lines[i - 1].lstrip())
        curr_indent = len(line) - len(line.lstrip())

        # If previous line ends with : (like if, for, while, try, except, etc.)
        if prev_line.endswith(":") and not stripped.startswith("#"):
            # Current line should be indented 4 spaces more than previous
            if curr_indent <= prev_indent and stripped:
                lines[i] = " " * (prev_indent + 4) + stripped + "\n"
                print(f"Fixed indentation at line {i+1}: {stripped[:50]}")

        # Special case: if we have else or elif or except at wrong indentation
        if stripped.startswith(("else:", "elif ", "except ", "finally:")):
            # Find the matching if/try block
            j = i - 1
            while j >= 0:
                check_line = lines[j].strip()
                check_indent = len(lines[j]) - len(lines[j].lstrip())
                if check_line.startswith(("if ", "try:", "elif ", "for ", "while ")):
                    if curr_indent != check_indent:
                        lines[i] = " " * check_indent + stripped + "\n"
                        print(f"Fixed else/except/elif indentation at line {i+1}")
                    break
                j -= 1

    i += 1

# Write the fixed file
with open("/workspace/github_menu_handler.py", "w") as f:
    f.writelines(lines)

print("\nDone fixing all indentation issues")
print("\nNow checking syntax...")

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
