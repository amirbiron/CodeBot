#!/usr/bin/env python3

# Read the file
with open("/workspace/github_menu_handler.py", "r") as f:
    lines = f.readlines()

# Fix all elif and else statements that have 16 spaces (should have 8)
for i in range(len(lines)):
    line = lines[i]

    # Check for elif with 16 spaces
    if line.startswith("                elif "):  # 16 spaces
        lines[i] = "        " + line.strip() + "\n"
        print(f"Fixed elif at line {i+1}")

    # Check for else with 16 spaces
    elif line.startswith("                else:"):  # 16 spaces
        # But make sure it's not inside another block
        if i > 0 and not lines[i - 1].strip().endswith(":"):
            lines[i] = "        " + line.strip() + "\n"
            print(f"Fixed else at line {i+1}")

# Write the fixed file
with open("/workspace/github_menu_handler.py", "w") as f:
    f.writelines(lines)

print("\nFixed all remaining elif/else indentation issues")

# Check syntax
import subprocess

result = subprocess.run(
    ["python3", "-m", "py_compile", "/workspace/github_menu_handler.py"], capture_output=True, text=True
)
if result.returncode == 0:
    print("✅ No syntax errors found!")
else:
    print("❌ Still has syntax errors:")
    # Only show first error
    lines = result.stderr.split("\n")
    for line in lines[:5]:
        print(line)
