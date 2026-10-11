"""וו הדריסה של צבע הטקסט בכפתורי primary.

בערכה מיובאת או משותפת הטקסט של כפתור primary נצבע ב-``--primary`` בכמה מקומות: כפתור
שהוא ``<a>`` נצבע דרך ``[data-theme="custom"] a`` שב-``dark-mode.css`` (ובריחוף דרך
``a:hover``, ב-``--primary-dark``), הכפתורים "ערוך" ו"העתק קוד" נצבעים דרך
``.file-primary-action`` שב-``view_file.html``, ומצבי פוקוס, לחיצה והשבתה — וכל כפתור
בערכה משותפת — נצבעים דרך כללי ה-``!important`` שבבלוק ``primary-btn-states-custom-type``
ב-``base.html``. ``--primary`` מגיע ממפתחות VS Code אחרים לגמרי מאלה שקובעים את רקע הכפתור,
ובערכה שבה השניים יוצאים קרובים הטקסט נבלע (Everforest: ‏``#7fbbb3`` על ``#a7c080``).

הבדיקות טקסטואליות, כמו אלה של שאר ווי הדריסה: הן שומרות על החוזה — רשימה לבנה, בלי ברירת
מחדל בשום מקום, ו-fallback שהוא בדיוק מה שנצבע היום — ולא מודדות את המפל מחדש. בדיקת הייבוא
עוברת דרך ה-endpoint עצמו וקוראת את מה שנשמר במסד, לא את מה שהטסט ביקש לכתוב.
"""

import json
import re
from pathlib import Path

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _css_rules import css_rules, template_css
from _fake_mongo import FakeDB

from services.theme_parser_service import (
    ALLOWED_VARIABLES_WHITELIST,
    FALLBACK_DARK,
    FALLBACK_LIGHT,
    VSCODE_TO_CSS_MAP,
    validate_theme_json,
)
from webapp import app as webapp_app

TOKEN = "--btn-primary-text-override"

REPO_ROOT = Path(__file__).resolve().parents[2]
DARK_MODE_CSS = REPO_ROOT / "webapp/static/css/dark-mode.css"
BASE_HTML = REPO_ROOT / "webapp/templates/base.html"
VIEW_FILE_HTML = REPO_ROOT / "webapp/templates/view_file.html"

#: הבוררים שבהם כלל הקישורים של ``dark-mode.css`` חל על ערכה מיובאת ועל ערכה משותפת.
THEME_SCOPES = ('[data-theme="custom"]', '[data-theme^="shared:"]')

#: כל מה שמתחת לבורר של ערכה מיובאת או משותפת, בכל צורה שהריפו כותב אותו.
_CUSTOM_OR_SHARED = re.compile(r'data-theme(?:-type)?="custom"|data-theme\^="shared:"')


def _dark_mode_rules():
    return css_rules(DARK_MODE_CSS.read_text(encoding="utf-8"))


def _color_of(rules, selector):
    """ערך ה-``color`` של הכלל שהבורר שלו הוא בדיוק ``selector``, והמיקום שלו בקובץ."""
    found = [
        (i, decl["color"])
        for i, (sel, decl) in enumerate(rules)
        if sel == selector and "color" in decl
    ]
    assert len(found) == 1, f"{selector}: {found}"
    return found[0]


def test_token_is_whitelisted():
    """בלי זה הטוקן מסונן בשקט בייבוא ולא מגיע ל-CSS."""
    assert TOKEN in ALLOWED_VARIABLES_WHITELIST


def test_token_is_not_in_the_fallback_dicts():
    """``parse_vscode_theme`` מעתיק את מילון ה-FALLBACK לכל ערכה מיובאת לפני המיפוי.

    טוקן שיושב שם מוגדר בכל ערכה מיובאת, ה-fallback ב-CSS לא רץ אף פעם, והווו הופך לשינוי גורף.
    """
    assert TOKEN not in FALLBACK_DARK
    assert TOKEN not in FALLBACK_LIGHT


def test_no_vscode_key_maps_to_the_token():
    """אין מפתח VS Code שמוביל לטוקן — ולכן הוא מגיע רק מבלוק ``variables`` מפורש."""
    targets = set()
    for css_vars in VSCODE_TO_CSS_MAP.values():
        targets.update(css_vars if isinstance(css_vars, list) else [css_vars])
    assert TOKEN not in targets


def test_no_stylesheet_or_template_gives_the_token_a_value():
    """ערך ברירת מחדל בכל מקום — ``:root`` בתבנית, בלוק בקובץ CSS אחר — מבטל את ה-fallback."""
    sources = list((REPO_ROOT / "webapp/static").rglob("*.css"))
    sources += list((REPO_ROOT / "webapp/templates").rglob("*.html"))
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not re.search(re.escape(TOKEN) + r"\s*:", text), f"{TOKEN} מקבל ערך ב-{path.name}"


@pytest.mark.parametrize("state", ["", ":hover"])
def test_link_hook_falls_back_to_what_the_link_rule_paints(state):
    """רגיל ו-``:hover``, וכל אחד נופל לערך שכלל הקישורים צובע בו היום.

    הערך נקרא מכלל הקישורים עצמו ולא מוקלד כאן: אם הוא ישתנה, ה-fallback של הווו חייב להשתנות
    איתו — אחרת ערכה שאינה מצהירה תקבל צבע אחר מזה שקיבלה לפני הווו.
    """
    rules = _dark_mode_rules()
    for scope in THEME_SCOPES:
        _, painted = _color_of(rules, f"{scope} a{state}")
        _, hooked = _color_of(rules, f"{scope} a:where(.btn-primary){state}")
        assert hooked == f"var({TOKEN}, {painted})", (scope, state, hooked)


@pytest.mark.parametrize("state", ["", ":hover"])
def test_link_hook_comes_after_the_link_rule(state):
    """:where() אינו מוסיף ספציפיות, ולכן לווו ולכלל הקישורים יש אותה ספציפיות — והאחרון בקובץ מנצח.

    כך הווו חל בדיוק במקום שבו כלל הקישורים צובע היום, ולא במקום אחר: כלל ספציפי יותר (כמו
    ``.file-primary-action``) ממשיך לנצח את שניהם. ווו שיקדים את כלל הקישורים לא יחול בכלל.
    """
    rules = _dark_mode_rules()
    for scope in THEME_SCOPES:
        link_at, _ = _color_of(rules, f"{scope} a{state}")
        hook_at, _ = _color_of(rules, f"{scope} a:where(.btn-primary){state}")
        assert hook_at > link_at, (scope, state)


def test_link_hook_covers_every_theme_scope_of_the_link_rule():
    """כל בורר של ערכה מיובאת או משותפת בכלל הקישורים מקבל בורר מקביל בווו — ולא יותר.

    בורר חסר = כפתור שממשיך להיצבע ב---primary גם בערכה שהצהירה. בורר עודף (למשל של ערכה
    מובנית) = שינוי בערכה שאינה יכולה להצהיר בכלל.
    """
    rules = _dark_mode_rules()
    for state in ("", ":hover"):
        link_scopes = {
            sel[: -len(f" a{state}")]
            for sel, decl in rules
            if sel.endswith(f" a{state}") and "color" in decl and _CUSTOM_OR_SHARED.search(sel)
        }
        hook_scopes = {
            sel[: -len(f" a:where(.btn-primary){state}")]
            for sel, _decl in rules
            if sel.endswith(f" a:where(.btn-primary){state}")
        }
        assert link_scopes == set(THEME_SCOPES), link_scopes
        assert hook_scopes == link_scopes, (state, hook_scopes)


def test_important_states_read_the_token_with_todays_fallback():
    """פוקוס, לחיצה, השבתה, והכפתור בערכה משותפת — כללי ה-``!important`` ב-``base.html``.

    הם גוברים על כל כלל אחר, ולכן כל אחד מהם חייב לקרוא את הטוקן בעצמו. ה-fallback הוא
    ``var(--primary)``, מה שהם צבעו לפני הווו.
    """
    rules = css_rules(template_css(BASE_HTML))
    expected = f"var({TOKEN}, var(--primary)) !important"
    selectors = [
        f"{scope} .btn-primary{state}"
        for scope in ('[data-theme-type="custom"]', '[data-theme^="shared:"]')
        for state in (":active", ":focus", ":disabled", ".disabled")
    ]
    selectors += [
        '[data-theme^="shared:"] .btn-primary',
        '[data-theme^="shared:"] .btn-primary:hover',
    ]
    for selector in selectors:
        _, color = _color_of(rules, selector)
        assert color == expected, (selector, color)


def test_file_actions_read_the_token_with_todays_fallback():
    """"ערוך" ו"העתק קוד" נצבעים בכלל משלהם, שגובר על כלל הקישורים — גם ב-``:hover``."""
    rules = css_rules(template_css(VIEW_FILE_HTML))
    selector = ':root[data-theme-type="custom"] .file-actions .file-primary-action'
    _, color = _color_of(rules, selector)
    assert color == f"var({TOKEN}, var(--primary))"


def test_no_custom_theme_rule_paints_primary_button_text_without_the_token():
    """כל כלל שצובע טקסט של כפתור primary ב---primary בערכה מיובאת או משותפת קורא את הטוקן.

    זה מה ששומר על "כל המסכים": כלל חדש כזה בתבנית אחרת — או אחד שהוחזר ל-``var(--primary)``
    — היה משאיר מסך אחד שבו ערכה שהצהירה עדיין מקבלת טקסט שנבלע ברקע.
    """
    sources = [
        (p, css_rules(p.read_text(encoding="utf-8")))
        for p in (REPO_ROOT / "webapp/static").rglob("*.css")
    ]
    sources += [
        (p, css_rules(template_css(p))) for p in (REPO_ROOT / "webapp/templates").rglob("*.html")
    ]
    offenders = []
    for path, rules in sources:
        for selector, decl in rules:
            color = decl.get("color", "")
            if not _CUSTOM_OR_SHARED.search(selector) or "--primary" not in color:
                continue
            if "btn-primary" in selector or "file-primary-action" in selector:
                if TOKEN not in color:
                    offenders.append(f"{path.name}: {selector} {{color: {color}}}")
    assert not offenders, "\n".join(offenders)


def _theme(variables=None):
    """הערכה שבדוגמה ב-``custom_themes_guide.rst``.

    עם ``{TOKEN: "#232a2e"}`` זו הדוגמה כפי שהיא כתובה שם.
    """
    body = {
        "name": "Everforest Dark",
        "type": "dark",
        # שלושה מפתחות ב-colors הם המינימום ש-validate_theme_json דורש. ``notificationsInfoIcon``
        # ממופה ל---primary אחרי ``focusBorder``, ולכן הוא שקובע אותו — כמו בקובץ של Everforest.
        "colors": {
            "editor.background": "#2d353b",
            "button.background": "#a7c080",
            "button.foreground": "#2d353b",
            "focusBorder": "#2d353b00",
            "notificationsInfoIcon.foreground": "#7fbbb3",
        },
        "tokenColors": [],
    }
    if variables is not None:
        body["variables"] = variables
    return body


def test_documented_example_passes_validation():
    """הדוגמה שבתיעוד (``custom_themes_guide.rst``) עוברת את הוולידציה כפי שהיא כתובה."""
    ok, error = validate_theme_json(json.dumps(_theme({TOKEN: "#232a2e"})))
    assert ok, error


def test_malformed_value_is_rejected_and_names_the_key():
    ok, error = validate_theme_json(json.dumps(_theme({TOKEN: "teal"})))
    assert not ok
    assert TOKEN in error


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
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


def _stored_variables(db):
    """המשתנים כפי שנשמרו במסד — לא כפי שהבקשה ביקשה."""
    user = db.users.find_one({"user_id": 42})
    assert user and len(user.get("custom_themes") or []) == 1, user
    return user["custom_themes"][0]["variables"]


def test_import_stores_the_declared_token_next_to_the_other_hooks(client, fake_db):
    """המסלול המרכזי: הטוקן נשמר, יחד עם ווים אחרים באותו בלוק, וה---primary של הערכה לא זז."""
    declared = {
        TOKEN: "#232a2e",
        "--collections-link-override": "#2e6161",
        "--search-suggestion-text-override": "#2e6161",
    }
    response = client.post(
        "/api/themes/import", json={"json_content": json.dumps(_theme(declared))}
    )
    assert response.status_code == 200, response.get_data(as_text=True)[:300]

    stored = _stored_variables(fake_db)
    for key, value in declared.items():
        assert stored.get(key) == value, (key, stored.get(key))
    assert stored.get("--primary") == "#7fbbb3"


def test_import_without_the_block_leaves_the_token_unset(client, fake_db):
    """ערכה שאינה מצהירה — הטוקן לא מוגדר, וכל כלל נופל לערך שנצבע בו היום."""
    response = client.post("/api/themes/import", json={"json_content": json.dumps(_theme())})
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert TOKEN not in _stored_variables(fake_db)
