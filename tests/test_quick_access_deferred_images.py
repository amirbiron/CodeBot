"""שומר על דחיית טעינת התמונות בחלונית קיצורי הדרך.

אייקון דפדפן הקוד הוא 6MB, והוא ירד ב**כל טעינת עמוד** בוובאפ — לכל
אדמין, בכל דף. הסתרת החלונית לא מנעה את זה: היא מוסתרת ב-``opacity``
ו-``visibility``, ואפילו ``display: none`` לא מונע הורדה של ``<img src>``.
נמדד בכרומיום: בקשה אחת בטעינת העמוד, ``content-length`` 5.90MB,
ו-``img.complete === true`` עוד לפני שנגעו בכפתור.

הפתרון: ``data-src`` במקום ``src``, ו-``loadDeferredImages`` שמציב את
ה-``src`` בפתיחה הראשונה של החלונית. ``<img>`` בלי ``src`` אינו שולח בקשה.

הבדיקה טקסטואלית — היא שומרת על ההחלטה, לא מודדת אותה מחדש. אותה גישה
כמו ``test_note_boards_api`` שקורא את קובץ ה-JS כטקסט.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

BASE_HTML = Path(__file__).resolve().parent.parent / "webapp/templates/base.html"

# ה-``<img>`` היחיד בחלונית קיצורי הדרך. אם ייווספו עוד — ``loadDeferredImages``
# גנרי על ``img[data-src]`` ויטפל גם בהם, והבדיקה כאן תמשיך לתפוס ``src`` נוקשה.
DEFERRED_ICON = "icons/repo-browser-icon.png"

_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)


def _html_without_jinja_comments() -> str:
    """ההערה בתבנית מזכירה את ``src`` בכוונה, כדי להסביר למה הוא לא שם.

    בלי ההסרה הזו הבדיקה הייתה נכשלת על התיעוד של עצמה — בדיוק המלכודת
    שכבר נפלתי בה בשומר ה-CSS.
    """
    return _JINJA_COMMENT.sub("", BASE_HTML.read_text(encoding="utf-8"))


def _img_tags_with(fragment: str, html: str):
    return re.findall(r"<img\b[^>]*" + re.escape(fragment) + r"[^>]*>", html)


def test_base_html_exists():
    assert BASE_HTML.is_file(), f"לא נמצא {BASE_HTML}"


def test_heavy_icon_is_deferred_not_eager():
    """הקובץ הכבד חייב להגיע כ-``data-src``, ולא כ-``src``."""
    html = _html_without_jinja_comments()
    tags = _img_tags_with(DEFERRED_ICON, html)
    assert tags, f"לא נמצא <img> שמפנה ל-{DEFERRED_ICON} — האם הנתיב השתנה?"
    # ``(?<![-\w])`` ולא ``\b``: מקף הוא גבול מילה, ולכן ``\bsrc`` תופס גם
    # את ``data-src`` — כלומר הבדיקה הייתה נכשלת דווקא על התיקון.
    eager = [t for t in tags if re.search(r"(?<![-\w])src\s*=", t)]
    assert not eager, (
        f"``{DEFERRED_ICON}`` הוא 6MB. עם ``src`` הוא יורד בכל טעינת עמוד "
        f"בוובאפ, גם כשהחלונית סגורה — הסתרה ב-CSS אינה מונעת הורדה. "
        f"השתמשו ב-``data-src``. התגיות שנמצאו: {eager}"
    )
    assert any("data-src=" in t for t in tags), "חסר ``data-src`` על התגית"


def test_loader_exists_and_is_called_on_open():
    """מי שמציב את ה-``src``, ומאיפה הוא נקרא."""
    html = BASE_HTML.read_text(encoding="utf-8")
    assert "function loadDeferredImages(" in html, "חסרה הפונקציה ``loadDeferredImages``"
    assert "img[data-src]" in html, "הפונקציה חייבת לסרוק ``img[data-src]``"

    # הקריאה חייבת לשבת בענף הפתיחה של ``toggleQuickAccess`` — הפונקציה
    # היחידה שמוסיפה ``active`` ל-``quickAccessDropdown``.
    body = html.split("function toggleQuickAccess(", 1)
    assert len(body) == 2, "לא נמצאה ``toggleQuickAccess``"
    assert "loadDeferredImages(dropdown)" in body[1].split("function ", 1)[0], (
        "``loadDeferredImages`` אינה נקראת בתוך ``toggleQuickAccess`` — "
        "בלי זה התמונה לעולם לא תקבל ``src``"
    )


def test_loader_is_one_shot():
    """``data-src`` מוסר לפני ההצבה, ולכן פתיחה חוזרת אינה מציבה שוב."""
    html = BASE_HTML.read_text(encoding="utf-8")
    fn = html.split("function loadDeferredImages(", 1)[1].split("\n        function ", 1)[0]
    remove_at = fn.find("removeAttribute('data-src')")
    assign_at = fn.find("img.src = src")
    assert remove_at != -1, "חסר ``removeAttribute('data-src')``"
    assert assign_at != -1, "חסרה ההצבה ``img.src = src``"
    assert remove_at < assign_at, "ההסרה חייבת לקדום להצבה, אחרת הבדיקה החד-פעמית מיותרת"


@pytest.mark.parametrize(
    "bad_html",
    [
        # הצורה שהייתה בקוד לפני התיקון
        '<img src="{{ url_for(\'static\', filename=\'icons/repo-browser-icon.png\') }}" alt="">',
        # ניסוח שמחזיק גם data-src וגם src — נראה תקין, ומוריד בכל זאת
        '<img data-src="x" src="{{ url_for(\'static\', filename=\'icons/repo-browser-icon.png\') }}">',
    ],
)
def test_the_guard_can_actually_fail(bad_html, tmp_path, monkeypatch):
    """בדיקה שלא מסוגלת להיכשל אינה בדיקה."""
    fake = tmp_path / "base.html"
    fake.write_text(BASE_HTML.read_text(encoding="utf-8") + "\n" + bad_html, encoding="utf-8")
    monkeypatch.setattr(f"{__name__}.BASE_HTML", fake)
    with pytest.raises(AssertionError):
        test_heavy_icon_is_deferred_not_eager()
