"""כפתורי הפתקים בעמוד הקבצים: חיפוש בפתקים ולוחות הפתקים.

שני הכפתורים מציירים את אותו דף ב-SVG, ובחיפוש הזכוכית המגדלת נחתכת מתוכו
ב-``mask``. שם ה-``mask`` מופיע פעמיים — בהגדרה וב-``url(#...)`` שמפנה
אליה — ושגיאת הקלדה ביניהם אינה מייצרת שום שגיאה: האייקון פשוט נראה אחרת
או נעלם. הבדיקה כאן טקסטואלית, כי אין בריפו דפדפן ל-CI; מה שהחיתוך באמת
עושה על המסך נמדד בדפדפן כשהכפתורים נוספו.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

FILES_HTML = Path(__file__).resolve().parent.parent / "webapp/templates/files.html"


def _refs_and_ids(html: str) -> tuple[set[str], set[str]]:
    refs = set(re.findall(r"url\(#([\w-]+)\)", html))
    ids = set(re.findall(r'\bid="([\w-]+)"', html))
    return refs, ids


def test_every_svg_reference_points_at_an_id_in_the_template():
    refs, ids = _refs_and_ids(FILES_HTML.read_text(encoding="utf-8"))
    assert refs, "לא נמצא אף ``url(#...)`` — האם אייקון החיפוש בפתקים הוסר?"
    missing = refs - ids
    assert not missing, f"הפניות ל-id שאינו קיים בתבנית: {sorted(missing)}"


def test_both_note_buttons_are_on_the_page():
    html = FILES_HTML.read_text(encoding="utf-8")
    assert 'href="/notes/search"' in html
    assert 'href="/boards"' in html


def test_the_reference_guard_can_actually_fail(tmp_path, monkeypatch):
    """מוטציה: שם ה-``mask`` בהגדרה משתנה, וההפניה נשארת."""
    html = FILES_HTML.read_text(encoding="utf-8")
    refs, _ = _refs_and_ids(html)
    name = sorted(refs)[0]
    needle = f'id="{name}"'
    assert html.count(needle) == 1, "המוטציה מניחה הגדרה אחת בדיוק"
    mutated = html.replace(needle, f'id="{name}-typo"', 1)
    fake = tmp_path / "files.html"
    fake.write_text(mutated, encoding="utf-8")
    monkeypatch.setattr(f"{__name__}.FILES_HTML", fake)
    with pytest.raises(AssertionError):
        test_every_svg_reference_points_at_an_id_in_the_template()
