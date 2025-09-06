#!/bin/bash

echo "🚀 Creating Web App files..."

# Create directories
mkdir -p webapp/templates

# Create __init__.py
cat > webapp/__init__.py << 'EOF'
"""
Web Application for Code Keeper Bot
ממשק ווב לבוט שומר קבצי קוד
"""

__version__ = "1.0.0"
EOF

echo "✅ Created webapp/__init__.py"

# Create a simple app.py for now
cat > webapp/app.py << 'EOF'
#!/usr/bin/env python3
from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
EOF

echo "✅ Created webapp/app.py"

# Create a simple template
cat > webapp/templates/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head>
    <title>Code Keeper Web App</title>
</head>
<body>
    <h1>Code Keeper Bot - Web Interface</h1>
    <p>Coming soon...</p>
</body>
</html>
EOF

echo "✅ Created webapp/templates/index.html"

echo "🎉 All files created!"
ls -la webapp/
