#!/usr/bin/env python3

# Read the file
with open('/workspace/github_menu_handler.py', 'r') as f:
    lines = f.readlines()

# Remove orphaned lines
fixed_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    
    # Skip orphaned parse_mode='HTML' lines
    if line.strip() == "parse_mode='HTML'":
        print(f"Removed orphaned parse_mode='HTML' at line {i+1}")
        i += 1
        continue
    
    # Skip orphaned closing parentheses
    if line.strip() == ')' and i > 0:
        # Check if this is likely orphaned
        prev_line = lines[i-1].strip()
        if prev_line == 'raise' or prev_line.startswith('raise'):
            print(f"Removed orphaned ')' at line {i+1}")
            i += 1
            continue
    
    fixed_lines.append(line)
    i += 1

# Write the fixed file
with open('/workspace/github_menu_handler.py', 'w') as f:
    f.writelines(fixed_lines)

print("\nFixed orphaned lines")

# Check syntax
import subprocess
result = subprocess.run(['python3', '-m', 'py_compile', '/workspace/github_menu_handler.py'], 
                       capture_output=True, text=True)
if result.returncode == 0:
    print("✅ No syntax errors found!")
else:
    print("❌ Still has syntax errors:")
    print(result.stderr[:500])