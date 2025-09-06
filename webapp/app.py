#!/usr/bin/env python3
from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
    <title>Code Keeper Bot - שומר הקוד שלך</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .container {
            text-align: center;
            padding: 3rem;
            background: rgba(255,255,255,0.1);
            border-radius: 30px;
            backdrop-filter: blur(20px);
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 600px;
            margin: 20px;
        }
        h1 { 
            font-size: 3.5rem; 
            margin-bottom: 1rem;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        }
        .emoji { font-size: 5rem; margin-bottom: 1rem; }
        p { font-size: 1.3rem; margin: 2rem 0; }
        .buttons {
            display: flex;
            gap: 1rem;
            justify-content: center;
            flex-wrap: wrap;
        }
        a {
            display: inline-block;
            padding: 15px 30px;
            background: white;
            color: #667eea;
            text-decoration: none;
            border-radius: 30px;
            font-weight: bold;
            transition: transform 0.3s;
        }
        a:hover { transform: scale(1.05); }
        .telegram-btn {
            background: #0088cc;
            color: white;
        }
        .status {
            background: rgba(255,255,255,0.2);
            padding: 1rem;
            border-radius: 15px;
            margin: 2rem 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="emoji">🚀</div>
        <h1>Code Keeper Bot</h1>
        <p>המקום המושלם לשמור ולנהל את קטעי הקוד שלך!</p>
        
        <div class="status">
            <p>🟢 השרת פעיל | גרסה 1.0.0 | מאובטח 🔒</p>
        </div>
        
        <div class="buttons">
            <a href="https://t.me/CodeKeeperBot" target="_blank" class="telegram-btn">
                💬 פתח את הבוט בטלגרם
            </a>
            <a href="/health">
                ❤️ בדיקת תקינות
            </a>
        </div>
        
        <p style="font-size: 1rem; opacity: 0.8; margin-top: 3rem;">
            בקרוב: ממשק ניהול מלא! 🎉
        </p>
    </div>
</body>
</html>'''

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'message': 'Web app is running!',
        'version': '1.0.0'
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
