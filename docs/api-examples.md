# Code Keeper WebApp – דוגמאות curl מהירות

הכנות מהירות:

```bash
export BASE_URL="http://localhost:5000"
# אם נדרש: העתקו את ערך ה-session cookie מדפדפן
export SESSION_COOKIE="<paste-your-session-cookie>"
```

הוספת/הסרת סימנייה:

```bash
curl -sS -X POST "$BASE_URL/api/bookmarks/<file_id>/toggle" \
  -H "Content-Type: application/json" \
  -H "Cookie: session=$SESSION_COOKIE" \
  -d '{"line_number": 42, "note": "בדיקה", "color": "yellow"}' | jq .
```

קבלת סימניות לקובץ:

```bash
curl -sS "$BASE_URL/api/bookmarks/<file_id>?include_invalid=false" \
  -H "Cookie: session=$SESSION_COOKIE" | jq .
```

כל הסימניות למשתמש (מקובצות):

```bash
curl -sS "$BASE_URL/api/bookmarks/all?limit=100&skip=0" \
  -H "Cookie: session=$SESSION_COOKIE" | jq .
```

עדכון הערה/צבע:

```bash
curl -sS -X PUT "$BASE_URL/api/bookmarks/<file_id>/42/note" \
  -H "Content-Type: application/json" -H "Cookie: session=$SESSION_COOKIE" \
  -d '{"note":"הערה מעודכנת"}' | jq .

curl -sS -X PUT "$BASE_URL/api/bookmarks/<file_id>/42/color" \
  -H "Content-Type: application/json" -H "Cookie: session=$SESSION_COOKIE" \
  -d '{"color":"green"}' | jq .
```

מחיקה:

```bash
curl -sS -X DELETE "$BASE_URL/api/bookmarks/<file_id>/42" -H "Cookie: session=$SESSION_COOKIE" | jq .
curl -sS -X DELETE "$BASE_URL/api/bookmarks/<file_id>/clear" -H "Cookie: session=$SESSION_COOKIE" | jq .
```

סטטיסטיקות והעדפות:

```bash
curl -sS "$BASE_URL/api/bookmarks/stats" -H "Cookie: session=$SESSION_COOKIE" | jq .
curl -sS "$BASE_URL/api/bookmarks/export" -H "Cookie: session=$SESSION_COOKIE"
curl -sS "$BASE_URL/api/bookmarks/prefs" -H "Cookie: session=$SESSION_COOKIE" | jq .

curl -sS -X PUT "$BASE_URL/api/bookmarks/prefs" \
  -H "Content-Type: application/json" -H "Cookie: session=$SESSION_COOKIE" \
  -d '{"default_color":"yellow"}' | jq .
```

קישורים ציבוריים וסטטוס זמינות:

```bash
curl -sS -X POST "$BASE_URL/api/share/<file_id>" -H "Cookie: session=$SESSION_COOKIE" | jq .

curl -sS "$BASE_URL/api/uptime" | jq .
curl -sS "$BASE_URL/api/public_stats" | jq .
```

בריאות ושערי מסמכים:

```bash
curl -sS "$BASE_URL/health" | jq .
# Swagger UI / ReDoc
xdg-open "$BASE_URL/docs" || open "$BASE_URL/docs"
xdg-open "$BASE_URL/redoc" || open "$BASE_URL/redoc"
```
