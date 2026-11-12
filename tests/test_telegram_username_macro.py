"""שם משתמש בטלגרם מוצג עם "@" לפניו — המאקרו ``telegram_username`` ומי שמשתמש בו.

העמודים כתובים מימין לשמאל, ו-"@" ידני לפני שם הוצג בצד הלא נכון ("moominAmir@").
המאקרו ב-``webapp/templates/components/telegram_username.html`` מבודד את השם ב-
``<bdi dir="ltr">``. כאן נבדק הפלט שלו, העמוד שבו התקלה דווחה (``/settings``) כפי
שהראוט מגיש אותו, ושאין בתבניות "@" ידני לפני שם משתמש — כלומר שאף עמוד לא חזר
לצורה הישנה. **איפה ה-"@" נוחת על המסך** — זה הדפדפן, ונמדד ב-
``tests/test_telegram_username_browser.py``.
"""

import pathlib
import re

import pytest

TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "webapp" / "templates"
IMPORT = '{% from "components/telegram_username.html" import telegram_username %}'
USER_ID = 7164


def _render(value):
    from webapp import app as webapp_app

    with webapp_app.app.app_context():
        tpl = webapp_app.app.jinja_env.from_string(IMPORT + "{{ telegram_username(value) }}")
        return tpl.render(value=value)


@pytest.mark.parametrize("value", ["moominAmir", "@moominAmir"], ids=["plain", "already-prefixed"])
def test_the_macro_puts_one_at_sign_inside_an_ltr_isolate(value):
    assert _render(value) == '<bdi dir="ltr">@moominAmir</bdi>'


def test_the_macro_escapes_the_name():
    assert _render("<b>x</b>") == '<bdi dir="ltr">@&lt;b&gt;x&lt;/b&gt;</bdi>'


#: "@" שנכתב ביד לפני ביטוי: ``@{{ ... }}`` או ``'@' ~ ...``.
_HAND_WRITTEN = re.compile(r"""@\{\{|['"]@['"]\s*~""")


#: המאקרו עצמו — המקום היחיד שמותר לו לכתוב את ה-"@".
MACRO = TEMPLATES / "components" / "telegram_username.html"


def test_no_template_writes_the_at_sign_by_hand():
    offenders = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        if path == MACRO:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _HAND_WRITTEN.search(line):
                offenders.append(f"{path.relative_to(TEMPLATES)}:{lineno}: {line.strip()}")
    assert not offenders, "השתמשו ב-telegram_username במקום:\n" + "\n".join(offenders)


def test_the_guard_can_fail():
    """המוטציה: השורה הישנה מ-``settings.html`` נתפסת."""
    assert _HAND_WRITTEN.search("        {% if user.username %} @{{ user.username }} {% else %}")
    assert _HAND_WRITTEN.search("{{ it.username and ('@' ~ it.username) }}")


def test_the_settings_page_shows_the_username_through_the_macro(monkeypatch):
    """העמוד מהדיווח, כפי שהראוט מגיש אותו."""
    pytest.importorskip("flask")
    from _fake_mongo import FakeDB
    from webapp import app as webapp_app

    db = FakeDB()
    db["users"].insert_one({"user_id": USER_ID, "username": "moominAmir", "first_name": "בדיקה"})
    monkeypatch.setattr(webapp_app, "get_db", lambda: db, raising=True)
    with webapp_app.app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = USER_ID
            sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה", "username": "moominAmir"}
        response = client.get("/settings")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    section = html[html.index("שם משתמש בטלגרם"):]
    assert section[:400].count('<bdi dir="ltr">@moominAmir</bdi>') == 1, section[:400]
