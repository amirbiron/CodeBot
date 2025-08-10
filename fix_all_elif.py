#!/usr/bin/env python3

# Read the file
with open("/workspace/github_menu_handler.py", "r") as f:
    lines = f.readlines()

# Fix all elif statements that have wrong indentation (20 spaces instead of 8)
for i in range(len(lines)):
    line = lines[i]
    # Check if this is an elif with 20 spaces indentation
    if line.startswith("                    elif "):  # 20 spaces
        # Change to 8 spaces
        lines[i] = "        " + line.strip() + "\n"
        print(f"Fixed elif at line {i+1}")

        # Also fix the content after elif
        j = i + 1
        while j < len(lines):
            next_line = lines[j]
            # If we hit another elif or else, stop
            if "elif " in next_line or next_line.strip().startswith("else:"):
                break
            # If line has 24 spaces, change to 12
            if next_line.startswith("                        "):  # 24 spaces
                lines[j] = "            " + next_line.strip() + "\n"
                print(f"  Fixed content at line {j+1}")
            j += 1

# Write the fixed file
with open("/workspace/github_menu_handler.py", "w") as f:
    f.writelines(lines)

print("\nFixed all elif indentation issues")

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
