#!/usr/bin/env python3
import re

# Read the file
with open('/workspace/github_menu_handler.py', 'r') as f:
    lines = f.readlines()

# Fix common patterns
fixed_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    
    # Fix InlineKeyboardButton lines that end with ))
    if 'InlineKeyboardButton' in line and line.strip().endswith('))'):
        line = line.replace('))', ')]')
        print(f"Fixed InlineKeyboardButton at line {i+1}")
    
    # Remove orphaned bracket/parenthesis lines after raise
    if i > 0 and lines[i-1].strip() == 'raise':
        if line.strip() in [')', '])', '])']:
            print(f"Removed orphaned bracket/parenthesis at line {i+1}")
            i += 1
            continue
        if line.strip().startswith('[InlineKeyboardButton'):
            print(f"Removed orphaned InlineKeyboardButton at line {i+1}")
            i += 1
            continue
    
    fixed_lines.append(line)
    i += 1

# Write the fixed file
with open('/workspace/github_menu_handler.py', 'w') as f:
    f.writelines(fixed_lines)

print("\nFixed bracket/parenthesis issues")

# Check syntax
import subprocess
result = subprocess.run(['python3', '-m', 'py_compile', '/workspace/github_menu_handler.py'], 
                       capture_output=True, text=True)
if result.returncode == 0:
    print("✅ No syntax errors found!")
else:
    print("❌ Still has syntax errors:")
    lines = result.stderr.split('\n')
    for line in lines[:10]:
        print(line)