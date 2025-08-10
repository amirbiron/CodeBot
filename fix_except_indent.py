#!/usr/bin/env python3

# Read the file
with open('/workspace/github_menu_handler.py', 'r') as f:
    lines = f.readlines()

# Fix except statements that have wrong indentation (12 spaces instead of 8)
for i in range(len(lines)):
    line = lines[i]
    
    # Check for except with 12 spaces
    if line.startswith('            except '):  # 12 spaces
        # Change to 8 spaces
        lines[i] = '        ' + line.strip() + '\n'
        print(f"Fixed except at line {i+1}")

# Write the fixed file
with open('/workspace/github_menu_handler.py', 'w') as f:
    f.writelines(lines)

print("\nFixed except indentation issues")

# Check syntax
import subprocess
result = subprocess.run(['python3', '-m', 'py_compile', '/workspace/github_menu_handler.py'], 
                       capture_output=True, text=True)
if result.returncode == 0:
    print("✅ No syntax errors found!")
else:
    print("❌ Still has syntax errors:")
    print(result.stderr[:500])