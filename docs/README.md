# 📖 תיעוד API - Code Keeper Bot

תיעוד מקיף ומפורט עבור Code Keeper Bot.

## 🚀 בניית התיעוד

### דרישות
- Python 3.9+
- Sphinx
- sphinx-rtd-theme

### התקנה (venv מומלץ)
```bash
python -m venv .venv-docs
source .venv-docs/bin/activate
pip install -r docs/requirements.txt
```

### בניית התיעוד
```bash
make -C docs html
# או:
sphinx-build -b html docs docs/_build/html
```

### תצוגה מקומית
```bash
python -m http.server -d docs/_build/html 8000
# ואז לגלוש ל: http://localhost:8000
```

התיעוד יהיה זמין ב: `docs/_build/html/index.html`

## 📚 מבנה התיעוד

```
docs/
├── index.rst           # דף הבית
├── installation.rst    # מדריך התקנה
├── configuration.rst   # הגדרות תצורה
├── examples.rst        # דוגמאות שימוש
├── api/               # תיעוד API
│   └── index.rst
├── modules/           # תיעוד מודולים
│   └── index.rst
├── handlers/          # תיעוד handlers
│   └── index.rst
├── services/          # תיעוד services
│   └── index.rst
└── database/          # תיעוד מסד נתונים
    └── index.rst
```

## ✨ תכונות

- **תיעוד אוטומטי**: נוצר מ-docstrings בקוד
- **דוגמאות קוד**: דוגמאות מעשיות לכל פונקציה
- **חיפוש מובנה**: חיפוש מהיר בתיעוד
- **תמיכה בעברית**: תיעוד דו-לשוני
- **עיצוב רספונסיבי**: נראה טוב בכל מכשיר

## 🔄 עדכון התיעוד

לאחר שינויים בקוד:

1. **עדכן docstrings**:
   ```python
   def my_function(param1: str, param2: int) -> bool:
       """
       תיאור קצר של הפונקציה.
       
       Args:
           param1: תיאור הפרמטר הראשון
           param2: תיאור הפרמטר השני
       
       Returns:
           bool: תיאור הערך המוחזר
       
       Example:
           >>> my_function("test", 42)
           True
       """
   ```

2. **בנה מחדש**:
   ```bash
   make clean
   make html
   ```

## 🌐 פרסום התיעוד

### GitHub Pages
```bash
# העתק את התיעוד לענף gh-pages
cp -r _build/html/* ../docs-gh-pages/
git add .
git commit -m "Update documentation"
git push origin gh-pages
```

### Read the Docs
1. חבר את הריפו ל-Read the Docs
2. הגדר את `docs/conf.py` כקובץ התצורה
3. התיעוד יתעדכן אוטומטית

## 📝 כתיבת תיעוד טוב

### עקרונות
- **ברור ותמציתי**: הסבר מה הפונקציה עושה בשורה אחת
- **פרמטרים מפורטים**: תאר כל פרמטר וסוגו
- **דוגמאות**: הוסף דוגמאות שימוש
- **אזהרות**: ציין מגבלות או דרישות מיוחדות

### פורמט Docstring (Google Style)
```python
"""
תיאור קצר בשורה אחת.

תיאור מפורט יותר אם נדרש.
יכול להיות מספר שורות.

Args:
    param1 (type): תיאור הפרמטר
    param2 (type, optional): פרמטר אופציונלי. ברירת מחדל: None

Returns:
    type: תיאור הערך המוחזר

Raises:
    ExceptionType: מתי נזרקת החריגה

Example:
    >>> function_name(param1="value")
    "result"

Note:
    הערה חשובה על השימוש

Warning:
    אזהרה על שימוש לא נכון
"""
```

## 🐛 פתרון בעיות

### שגיאות בבנייה
- ודא שכל התלויות מותקנות
- בדוק תחביר RST בקבצי התיעוד
- הרץ `sphinx-build -b html . _build/html -W` לראות אזהרות

### תיעוד חסר
- ודא ש-`__init__.py` קיים בכל תיקייה
- בדוק שה-imports בקובץ `conf.py` נכונים
- השתמש ב-`autodoc_mock_imports` לתלויות חיצוניות

## 📚 משאבים נוספים

- [Sphinx Documentation](https://www.sphinx-doc.org/)
- [Read the Docs Theme](https://sphinx-rtd-theme.readthedocs.io/)
- [Google Style Docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- [reStructuredText Primer](https://www.sphinx-doc.org/en/master/usage/restructuredtext/basics.html)

## 🤝 תרומה לתיעוד

1. Fork את הפרויקט
2. הוסף/עדכן תיעוד
3. ודא שהבנייה עוברת ללא שגיאות
4. שלח Pull Request

---

נוצר עם ❤️ עבור Code Keeper Bot