#!/usr/bin/env python3

# Read the file
with open('/workspace/github_menu_handler.py', 'r') as f:
    lines = f.readlines()

# Fix try-except blocks where except is at wrong indentation
fixed_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    
    # If we find an except at 8 spaces, check if it should be at 12
    if line.startswith('        except '):  # 8 spaces
        # Look back for the matching try
        j = i - 1
        while j >= 0:
            if 'try:' in lines[j]:
                # Check the indentation of the try
                try_indent = len(lines[j]) - len(lines[j].lstrip())
                if try_indent == 12:  # try is at 12 spaces
                    # except should also be at 12 spaces
                    lines[i] = '            ' + line.strip() + '\n'
                    print(f"Fixed except at line {i+1} to match try at 12 spaces")
                break
            j -= 1
    
    fixed_lines.append(lines[i])
    i += 1

# Write the fixed file
with open('/workspace/github_menu_handler.py', 'w') as f:
    f.writelines(fixed_lines)

print("\nFixed try-except indentation issues")

# Check syntax
import subprocess
result = subprocess.run(['python3', '-m', 'py_compile', '/workspace/github_menu_handler.py'], 
                       capture_output=True, text=True)
if result.returncode == 0:
    print("✅ No syntax errors found!")
else:
    print("❌ Still has syntax errors:")
    print(result.stderr[:500])