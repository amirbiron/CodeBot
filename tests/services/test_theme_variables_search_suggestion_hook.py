"""וו הדריסה של צבע הטקסט בהצעות ההשלמה של החיפוש הגלובלי.

אותו שורש בדיוק של וו האוספים (``test_theme_variables_collections_hook.py``):
ההצעות מרונדרות ב-``webapp/static/js/global_search.js`` כאלמנטי ``<a>``, ולכן
``[data-theme="custom"] a`` שב-``dark-mode.css`` צובע אותן ב-``--primary``
בספציפיות שגוברת על ``.search-suggestion``. רקע התיבה הוא
``--solid-surface-bg``, שנשאר לבן בכל ערכה — ולכן ערכה שה-``--primary`` שלה
בהיר מקבלת טקסט בלתי קריא (נמדד: לבן על לבן, ניגודיות 1.00).

הבדיקות עוברות דרך ה-endpoint עצמו ובודקות את המסמך ש-``import_theme`` דוחף
ל-``update_one`` — כלומר מה שקוד הייצור באמת כותב, ולא ערך שהטסט הרכיב בעצמו.
"""

import json
import types

import pytest

from services.theme_parser_service import (
    ALLOWED_VARIABLES_WHITELIST,
    parse_vscode_theme,
    validate_theme_json,
)
from webapp import app as webapp_app

TOKEN = "--search-suggestion-text-override"
CSS_PATH = "webapp/static/css/global_search.css"

# שלושה מפתחות ב-colors הם המינימום ש-validate_theme_json דורש.
# ``focusBorder`` לבן הוא מה שמייצר את הבאג: הוא ממופה ל---primary.
BASE_COLORS = {
    "editor.background": "#1b2b34",
    "editor.foreground": "#d8dee9",
    "focusBorder": "#ffffff",
}


class _StubUsers:
    def __init__(self):
        self.calls = []

    def find_one(self, *args, **kwargs):
        self.calls.append(("find_one", args, kwargs))
        return {"custom_themes": []}

    def update_one(self, query, update, upsert=False, array_filters=None):
        self.calls.append(("update_one", query, update, upsert, array_filters))
        return types.SimpleNamespace(acknowledged=True, modified_count=1)


class _StubDB:
    def __init__(self):
        self.users = _StubUsers()


@pytest.fixture
def stub_db(monkeypatch):
    db = _StubDB()
    monkeypatch.setattr(webapp_app, "get_db", lambda: db)
    return db


@pytest.fixture
def client(monkeypatch):
    # setitem ולא השמה ישירה: ‏webapp_app.app משותף לכל הסשן, ו-monkeypatch
    # משחזר את הערך הקודם בסיום ה-fixture במקום להשאיר אותו דלוף לטסטים הבאים.
    monkeypatch.setitem(webapp_app.app.config, "TESTING", True)
    with webapp_app.app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 42
            sess["user_data"] = {"id": 42, "first_name": "Tester"}
        yield c


def _theme(variables=None):
    body = {
        "name": "Cobalt Next",
        "type": "dark",
        "colors": dict(BASE_COLORS),
        "tokenColors": [
            {"scope": ["comment"], "settings": {"foreground": "#65737e"}},
        ],
    }
    if variables is not None:
        body["variables"] = variables
    return body


def _pushed_theme(stub_db):
    """המסמך שקוד הייצור דחף ל-DB. זו נקודת האמת, לא תגובת ה-endpoint."""
    for call in stub_db.users.calls:
        if call[0] != "update_one":
            continue
        update = call[2]
        if "$push" in update and "custom_themes" in update["$push"]:
            return update["$push"]["custom_themes"]
    raise AssertionError("לא נמצא $push של custom_themes")


def _css():
    from pathlib import Path

    return Path(CSS_PATH).read_text(encoding="utf-8")


def test_token_is_whitelisted():
    """בלי זה הטוקן מסונן בשקט ולא מגיע ל-CSS."""
    assert TOKEN in ALLOWED_VARIABLES_WHITELIST


def test_token_has_no_default_in_css():
    """הטוקן חייב להישאר בלי ערך ברירת מחדל, אחרת ה-fallback לא נכנס לפעולה
    והדריסה הופכת גורפת — הרגרסיה שתועדה בווו האוספים."""
    css = _css()
    assert f"{TOKEN}:" not in css, "הטוקן קיבל ערך ברירת מחדל — הווו הפך לדריסה גורפת"


def test_every_state_falls_back_to_what_is_painted_today():
    """שלושת המצבים, וכל אחד נופל לערך שנצבע בו היום.

    רגיל ו-hover נדרסים היום על ידי כללי ה-<a> ולכן מקבלים --primary ו-
    --primary-dark; :focus-visible דווקא מנצח אותם כבר היום (‏(0,2,0) מול
    ‏(0,1,1)) ולכן נצבע ב---suggestions-text. ערבוב בין השלושה היה מזיז ערכה
    שאינה מצהירה.
    """
    css = _css()
    assert f"var({TOKEN}, var(--primary))" in css
    assert f"var({TOKEN}, var(--primary-dark))" in css
    assert f"var({TOKEN}, var(--suggestions-text))" in css


def test_all_three_states_are_covered_by_the_hook():
    """מצב חסר = מצב שממשיך להיצבע ב---primary גם בערכה שהצהירה."""
    css = _css()
    base = f'[data-theme-type="custom"] .search-suggestion'
    assert f"{base}{{" in css or f"{base} {{" in css, "המצב הרגיל אינו מכוסה"
    assert f"{base}:hover" in css, ":hover אינו מכוסה"
    assert f"{base}:focus-visible" in css, ":focus-visible אינו מכוסה"


def test_hover_rule_comes_after_focus_visible_rule():
    """שניהם (0,3,0), ולכן כששני המצבים פעילים יחד מנצח האחרון בקובץ.

    היום, כשהשורה גם ב-hover וגם בפוקוס, ‏[data-theme="custom"] a:hover הוא
    ‏(0,2,1) ומנצח — כלומר נצבע --primary-dark. אם כלל ה-hover שלנו יקדים את
    כלל ה-focus, המצב המשולב יתהפך ל---suggestions-text וערכה שאינה מצהירה תזוז.
    """
    css = _css()
    base = '[data-theme-type="custom"] .search-suggestion'
    assert css.index(f"{base}:hover") > css.index(f"{base}:focus-visible")


def test_vscode_mapping_alone_cannot_produce_the_token():
    """אין מפתח VS Code שמוביל לטוקן — ולכן נדרש בלוק variables מפורש."""
    variables = parse_vscode_theme(_theme())["variables"]
    assert TOKEN not in variables
    # ובלעדיו הטקסט נופל ל---primary, שכאן הוא לבן — מקור הבאג.
    assert variables["--primary"] == "#ffffff"


def test_documented_example_passes_validation():
    """הדוגמה שבתיעוד חייבת לעבור את הוולידציה כפי שהיא כתובה."""
    ok, error = validate_theme_json(json.dumps(_theme({TOKEN: "#2e6161"})))
    assert ok, error


def test_malformed_variable_is_rejected_not_silently_dropped():
    """ערך פגום בבלוק variables נדחה במפורש, בשני המסלולים."""
    vscode_ok, vscode_error = validate_theme_json(json.dumps(_theme({TOKEN: "teal"})))
    assert not vscode_ok
    assert TOKEN in vscode_error

    native_ok, native_error = validate_theme_json(
        json.dumps({"name": "x", "variables": {TOKEN: "teal"}})
    )
    assert not native_ok
    assert TOKEN in native_error


def test_import_stores_the_declared_token(client, stub_db):
    """המסלול המרכזי: הטוקן שהערכה הצהירה עליו מגיע למסמך שנשמר."""
    response = client.post(
        "/api/themes/import", json={"json_content": json.dumps(_theme({TOKEN: "#2e6161"}))}
    )
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert response.get_json()["success"] is True

    pushed = _pushed_theme(stub_db)
    assert pushed["variables"].get(TOKEN) == "#2e6161"
    # הדגשת התחביר לא אבדה בדרך
    assert pushed.get("syntax_colors")


def test_import_alongside_the_collections_token(client, stub_db):
    """שני ווי הדריסה חיים באותו בלוק variables ואינם מתנגשים.

    זה המצב בפועל בערכה של המשתמש, שכבר נושאת את טוקן האוספים.
    """
    body = _theme({TOKEN: "#2e6161", "--collections-link-override": "#2e6161"})
    response = client.post("/api/themes/import", json={"json_content": json.dumps(body)})
    assert response.status_code == 200, response.get_data(as_text=True)[:300]

    variables = _pushed_theme(stub_db)["variables"]
    assert variables.get(TOKEN) == "#2e6161"
    assert variables.get("--collections-link-override") == "#2e6161"


def test_import_without_the_block_leaves_the_token_unset(client, stub_db):
    """ערכה שאינה מצהירה — הטוקן נשאר לא מוגדר, וה-CSS נופל ל-fallback."""
    response = client.post("/api/themes/import", json={"json_content": json.dumps(_theme())})
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert TOKEN not in _pushed_theme(stub_db)["variables"]


def test_import_drops_a_non_whitelisted_variable(client, stub_db):
    """טוקן שאינו ברשימה הלבנה אינו נשמר, גם כשערכו תקין."""
    body = _theme({TOKEN: "#2e6161", "--bogus-token": "#ff0000"})
    response = client.post("/api/themes/import", json={"json_content": json.dumps(body)})
    assert response.status_code == 200, response.get_data(as_text=True)[:300]

    variables = _pushed_theme(stub_db)["variables"]
    assert variables.get(TOKEN) == "#2e6161"
    assert "--bogus-token" not in variables


def test_import_rejects_a_malformed_variable_value(client, stub_db):
    """ערך פגום מוחזר עם 400 ומציין את המפתח, במקום 'יובאה בהצלחה'."""
    response = client.post(
        "/api/themes/import", json={"json_content": json.dumps(_theme({TOKEN: "teal"}))}
    )
    assert response.status_code == 400, response.get_data(as_text=True)[:300]
    body = response.get_json()
    assert body["success"] is False
    assert TOKEN in body["error"]
    assert not [c for c in stub_db.users.calls if c[0] == "update_one"]
