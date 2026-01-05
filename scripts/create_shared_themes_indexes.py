"""
scripts/create_shared_themes_indexes.py

יצירת אינדקסים ל-Shared Themes (shared_themes collection).

מימוש לפי GUIDES/SHARED_THEME_LIBRARY_GUIDE.md.
"""

from __future__ import annotations


def main() -> int:
    # import מאוחר כדי לא לטעון את כל האפליקציה אם לא צריך
    from webapp.app import ensure_shared_themes_indexes, get_db

    # הבטח חיבור + יצירת אינדקסים
    _ = get_db()
    ensure_shared_themes_indexes()
    print("✅ shared_themes indexes ensured")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

