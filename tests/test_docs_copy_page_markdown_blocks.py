from pathlib import Path


def test_docs_copy_page_uses_webapp_admonition_syntax():
    """
    בדיקה בסיסית כדי לוודא שכפתור "העתק תוכן הדף" בדוקס
    מייצר admonitions בפורמט הווב-אפ (::: type ... :::) ולא בפורמט MkDocs (!!!).
    """
    js = Path("docs/_static/copy-page.js").read_text(encoding="utf-8")
    assert "::: ${type}" in js
    assert "!!!" not in js

