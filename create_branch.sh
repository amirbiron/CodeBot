#!/bin/bash

# Script ליצירת ענף והעלאה ל-GitHub
# הרץ את זה במחשב המקומי שלך, לא ב-Render!

echo "🚀 מתחיל יצירת ענף ל-Web App..."

# בדוק שאנחנו בתיקייה הנכונה
if [ ! -f "main.py" ]; then
    echo "❌ שגיאה: לא נמצא main.py. האם אתה בתיקיית הפרויקט?"
    exit 1
fi

# שמור שינויים קיימים אם יש
echo "📦 שומר שינויים קיימים..."
git stash

# עבור ל-main ועדכן
echo "🔄 עובר ל-main branch..."
git checkout main
git pull origin main

# צור ענף חדש
echo "🌿 יוצר ענף חדש feature/webapp..."
git checkout -b feature/webapp

# החזר שינויים אם היו
if git stash list | grep -q "stash@{0}"; then
    echo "📥 מחזיר שינויים שמורים..."
    git stash pop
fi

# הוסף את כל השינויים
echo "➕ מוסיף את כל הקבצים החדשים..."
git add webapp/
git add requirements.txt
git add render.yaml
git add Procfile
git add WEBAPP_SETUP_GUIDE.md
git add create_branch.sh

# הצג סטטוס
echo "📊 סטטוס נוכחי:"
git status --short

# בצע commit
echo "💾 מבצע commit..."
git commit -m "Add Web Application for Code Keeper Bot

Features:
- Flask web application with modern Glass Morphism UI
- Telegram authentication with JWT tokens
- User dashboard with statistics
- File management (view, search, download)
- Responsive design with RTL Hebrew support
- API endpoints for future extensions
- Prism.js syntax highlighting
- Health check endpoint

Technical:
- Updated requirements.txt with Flask dependencies
- Updated render.yaml for web service deployment
- Created 11 new templates with Tailwind CSS
- Added comprehensive error handling
- Added setup guide and documentation"

# שאל אם לדחוף
echo ""
echo "✅ Commit נוצר בהצלחה!"
echo ""
read -p "האם לדחוף את הענף ל-GitHub? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🚀 דוחף ל-GitHub..."
    git push origin feature/webapp
    
    echo ""
    echo "🎉 הענף נדחף בהצלחה!"
    echo ""
    echo "📌 הצעדים הבאים:"
    echo "1. לך ל-GitHub repository שלך"
    echo "2. תראה הודעה 'Compare & pull request'"
    echo "3. לחץ עליה וצור Pull Request"
    echo ""
    echo "🔗 או לך ישירות ל:"
    echo "https://github.com/YOUR_USERNAME/YOUR_REPO/compare/feature/webapp"
else
    echo "⏸️  הענף נוצר מקומית אבל לא נדחף."
    echo "כדי לדחוף מאוחר יותר, הרץ:"
    echo "git push origin feature/webapp"
fi

echo ""
echo "✨ סיימנו!"