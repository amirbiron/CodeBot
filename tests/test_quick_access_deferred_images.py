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


OPEN_BRANCH_HEAD = "if (dropdown.classList.contains(\'active\')) {"


def _open_branch_of_toggle_quick_access(html: str) -> str:
    """גוף הענף ``if (dropdown.classList.contains('active')) { ... }``.

    התאמת סוגריים ולא ``split`` על טקסט: הענף מכיל פונקציה מקוננת
    (``closer``) עם סוגריים משלה, ולכן חיפוש נאיבי של ``}`` היה נעצר
    באמצע ומחזיר בלוק חלקי.
    """
    fn = html.find("function toggleQuickAccess(")
    assert fn != -1, "לא נמצאה ``toggleQuickAccess``"
    head = html.find(OPEN_BRANCH_HEAD, fn)
    assert head != -1, "לא נמצא ענף הפתיחה בתוך ``toggleQuickAccess``"
    i = html.index("{", head + len(OPEN_BRANCH_HEAD) - 1)
    depth = 0
    for j in range(i, len(html)):
        if html[j] == "{":
            depth += 1
        elif html[j] == "}":
            depth -= 1
            if depth == 0:
                return html[i : j + 1]
    raise AssertionError("ענף הפתיחה אינו נסגר")


def test_loader_exists_and_is_called_on_open():
    """מי שמציב את ה-``src``, ומאיפה בדיוק הוא נקרא.

    **הבדיקה על הענף, לא על הפונקציה כולה.** ניסוח קודם כאן בדק רק
    ש-``loadDeferredImages(dropdown)`` מופיע איפשהו ב-``toggleQuickAccess``,
    וזה חלש מדי: נמדד בדפדפן שהעלאת הקריאה אל מעל ``const dropdown``
    מפילה את הפונקציה כולה על ``ReferenceError`` — החלונית לא נפתחת
    (``dropdownActive: false``) והאייקון לא נטען כלל — והבדיקה הישנה עברה.

    (העברה מתונה יותר, אל מחוץ ל-``if`` אבל אחרי ההגדרה, נמדדה כבלתי
    מזיקה: הלחיצה הראשונה תמיד פותחת, ולכן הטעינה קורית בכל מקרה. הבדיקה
    כאן פוסלת גם אותה — בכוונה, כי המיקום בענף הוא מה שההערה בקוד
    מצהירה, וקוד שסותר את ההערה שלו הוא ממצא בפני עצמו.)
    """
    html = BASE_HTML.read_text(encoding="utf-8")
    assert "function loadDeferredImages(" in html, "חסרה הפונקציה ``loadDeferredImages``"
    assert "img[data-src]" in html, "הפונקציה חייבת לסרוק ``img[data-src]``"

    branch = _open_branch_of_toggle_quick_access(html)
    assert "loadDeferredImages(dropdown)" in branch, (
        "``loadDeferredImages(dropdown)`` אינה בענף הפתיחה של "
        "``toggleQuickAccess``. שם היא חייבת לשבת: אחרי ש-``dropdown`` "
        "הוגדר, ורק כשהחלונית נפתחת."
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


# שני המיקומים נמדדו בדפדפן, ולא הומצאו: הראשון מפיל את הפונקציה כולה
# ומשאיר את החלונית סגורה, השני בלתי מזיק אבל סותר את ההערה שבקוד.
# שניהם עברו את הניסוח הקודם של הבדיקה.
_ORIGINAL_CALL = """            if (dropdown.classList.contains('active')) {
                // לפני המיקום: התמונה תופסת מקום שמור מראש (רוחב וגובה
                // בסגנון), ולכן ההצבה אינה משנה את הגאומטריה שמחושבת מיד
                // אחריה ב-``ensureQuickAccessVisible``.
                loadDeferredImages(dropdown);"""

_MOVED_OUT_OF_BRANCH = """            loadDeferredImages(dropdown);
            if (dropdown.classList.contains('active')) {"""


@pytest.mark.parametrize(
    "label,replacement",
    [
        # נמדד: dropdownActive=false, naturalWidth=0 — שבור לגמרי
        ("הקריאה מעל ``const dropdown``", None),
        # נמדד: 8/8 בדפדפן — לא מזיק, אבל סותר את ההערה בקוד
        ("הקריאה מחוץ לענף הפתיחה", _MOVED_OUT_OF_BRANCH),
    ],
)
def test_open_branch_guard_can_actually_fail(label, replacement, tmp_path, monkeypatch):
    """הבדיקה החדשה חייבת ליפול על שני המיקומים. הישנה עברה את שניהם."""
    html = BASE_HTML.read_text(encoding="utf-8")
    assert html.count(_ORIGINAL_CALL) == 1, "הקריאה בענף הפתיחה השתנתה — עדכנו את המוטציה"

    if replacement is None:
        html = html.replace(_ORIGINAL_CALL, "            if (dropdown.classList.contains('active')) {")
        html = html.replace(
            "        function toggleQuickAccess(ev) {\n",
            "        function toggleQuickAccess(ev) {\n            loadDeferredImages(dropdown);\n",
            1,
        )
    else:
        html = html.replace(_ORIGINAL_CALL, replacement)

    fake = tmp_path / "base.html"
    fake.write_text(html, encoding="utf-8")
    monkeypatch.setattr(f"{__name__}.BASE_HTML", fake)
    with pytest.raises(AssertionError):
        test_loader_exists_and_is_called_on_open()
