#!/bin/bash

# Script לתיקון בעיות אבטחה ודחיפה לענף חדש
echo "🔧 מתקן בעיות אבטחה ודוחף לענף חדש..."

# שם הענף החדש
NEW_BRANCH="feature/webapp-security-fixes"

# בדוק שאנחנו בתיקייה הנכונה
if [ ! -f "main.py" ]; then
    echo "❌ שגיאה: לא נמצא main.py. האם אתה בתיקיית הפרויקט?"
    exit 1
fi

echo "📦 שומר שינויים קיימים..."
git stash

echo "🔄 עובר ל-main branch..."
git checkout main
git pull origin main

echo "🌿 יוצר ענף חדש ${NEW_BRANCH}..."
git checkout -b ${NEW_BRANCH}

echo "📥 מחזיר שינויים..."
git stash pop 2>/dev/null || true

echo "➕ מוסיף את כל הקבצים..."
git add webapp/
git add requirements.txt
git add render.yaml
git add Procfile
git add WEBAPP_SETUP_GUIDE.md
git add create_branch.sh
git add fix_security_and_push.sh

echo "💾 מבצע commit עם תיקוני האבטחה..."
git commit -m "Add Web Application with security fixes

Features:
- Flask web application with Glass Morphism UI
- Telegram authentication using proper HMAC-SHA256
- Enhanced JWT tokens with jti, aud, and iss claims
- User dashboard and file management
- Responsive design with RTL Hebrew support
- API endpoints for future extensions
- Prism.js syntax highlighting

Security Fixes:
- Fixed Telegram auth to use HMAC-SHA256 instead of simple hash
- Fixed timezone issues - now using UTC consistently
- Added JWT security claims (jti, aud, iss)
- Removed duplicate script loading
- Improved error handling to prevent information exposure
- Better error messages with Glass Morphism styling

Technical:
- Updated requirements.txt with Flask dependencies
- Updated render.yaml for web service deployment
- Created comprehensive setup documentation"

echo "🚀 דוחף לענף החדש..."
git push origin ${NEW_BRANCH} --force

echo ""
echo "✅ הענף נדחף בהצלחה!"
echo ""
echo "📌 הצעדים הבאים:"
echo "1. לך ל-GitHub"
echo "2. צור Pull Request חדש מ-${NEW_BRANCH} ל-main"
echo "3. הבדיקות האוטומטיות אמורות לעבור עכשיו!"
echo ""
echo "🔗 לינק ישיר ליצירת PR:"
echo "https://github.com/amirbiron/CodeBot/compare/main...${NEW_BRANCH}"
echo ""
echo "✨ בהצלחה!"