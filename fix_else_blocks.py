#!/usr/bin/env python3

# Read the file
with open("/workspace/github_menu_handler.py", "r") as f:
    lines = f.readlines()

# Fix else blocks that are at wrong indentation
for i in range(len(lines)):
    if i > 0 and lines[i].strip() == "else:":
        # Check if this else is at 8 spaces but the line after is at 20 spaces
        if lines[i].startswith("        else:") and i + 1 < len(lines):
            next_line = lines[i + 1]
            if next_line.startswith("                    "):  # 20 spaces
                # This else should be at 16 spaces
                lines[i] = "                else:\n"
                print(f"Fixed else at line {i+1} to 16 spaces")

# Write the fixed file
with open("/workspace/github_menu_handler.py", "w") as f:
    f.writelines(lines)

print("\nFixed else blocks")

# Check syntax
import subprocess

result = subprocess.run(
    ["python3", "-m", "py_compile", "/workspace/github_menu_handler.py"], capture_output=True, text=True
)
if result.returncode == 0:
    print("✅ No syntax errors found!")
else:
    print("❌ Still has syntax errors:")
    print(result.stderr[:500])
