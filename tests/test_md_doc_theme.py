"""ערכת המסמך — ערכה שחלה רק על כרטיס "תצוגת Markdown" ב-``/md/<id>``, בלי דפדפן.

מה נבדק כאן: הבורר של השורש זהה בכל הקבצים שכותבים אותו; הפענוח של הבחירה; ה-CSS שנבנה לכרטיס ומה שיוצא
מכללי התחביר של ערכת הממשק; השמירה ב-``/api/ui_prefs`` (מה נשמר, מה נדחה, ומכשיר מול כל המכשירים); הבחירה
הנוכחית ב-``GET /api/ui_prefs/md_doc_theme``; העמוד ``/md/<id>`` — ה-HTML, ה-ETag ו-304; ומחיקת ערכה שמנקה את
הבחירה. איך הכרטיס, המודאל והגלריה מתנהגים בדפדפן — ``tests/test_md_doc_theme_browser.py``.

העמודים אמיתיים, דרך ``test_client``, והמסד הוא ``FakeDB``.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from bson import ObjectId

pytest.importorskip("flask")

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeDB  # noqa: E402

from services.theme_parser_service import (  # noqa: E402
    ALLOWED_VARIABLES_WHITELIST,
    MD_DOC_THEME_ROOT_SELECTOR,
    MD_DOC_THEME_UI_CONDITION,
    build_md_doc_theme_css,
    exclude_md_doc_theme_from_hljs_css,
    parse_vscode_theme,
    rebase_hljs_css,
)

REPO = Path(__file__).resolve().parents[1]

#: הקבצים שכותבים את הבורר של השורש בעצמם, כי אינם קוד פייתון. ``MD_DOC_THEME_ROOT_SELECTOR`` מפנה לכאן.
MD_DOC_THEME_SELECTOR_FILES = (
    REPO / "webapp" / "templates" / "base.html",
    REPO / "webapp" / "static" / "css" / "md-content-colors.css",
    REPO / "webapp" / "static" / "css" / "markdown-enhanced.css",
    REPO / "webapp" / "templates" / "md_preview.html",
)

#: התכונה שהכרטיס מקבל כשיש ערכת מסמך. הבורר עצמו (``#mdCard[data-md-doc-theme]``) כתוב ב-CSS של כל עמוד.
CARD_ATTR = 'id="mdCard" data-md-doc-theme=""'

USER_ID = 4242
DOC_THEME_ID = "11111111-2222-3333-4444-555555555555"
UI_THEME_ID = "66666666-7777-8888-9999-000000000000"
SHARED_SLUG = "paper_light"

LIGHT_VSCODE = {
    "name": "Paper",
    "type": "light",
    "colors": {"editor.background": "#f8f6f1", "editor.foreground": "#2b3f6a"},
    "tokenColors": [{"scope": "keyword", "settings": {"foreground": "#5e78e1"}}],
}
DARK_VSCODE = {
    "name": "Swamp",
    "type": "dark",
    "colors": {"editor.background": "#313a36", "editor.foreground": "#e4e3e1"},
    "tokenColors": [{"scope": "keyword", "settings": {"foreground": "#c586c0"}}],
}


def _theme_doc(theme_id: str, vscode: dict, *, active: bool = False, extra_vars: dict | None = None) -> dict:
    parsed = parse_vscode_theme(vscode)
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    return {
        "id": theme_id,
        "name": vscode["name"],
        "is_active": active,
        "variables": {**parsed["variables"], **(extra_vars or {})},
        "syntax_css": parsed["syntax_css"],
        "syntax_colors": parsed["syntax_colors"],
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# הבורר של השורש
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", MD_DOC_THEME_SELECTOR_FILES, ids=lambda p: p.name)
def test_every_file_writes_the_root_selector_exactly_as_the_constant(path):
    """הבורר כתוב בקבצים האלה כטקסט. עותק שנערך באחד מהם היה מפעיל את ערכת המסמך בתנאי אחר — בלי שגיאה."""
    text = path.read_text(encoding="utf-8")
    assert MD_DOC_THEME_ROOT_SELECTOR in text, f"{path.name} אינו כותב את MD_DOC_THEME_ROOT_SELECTOR"
    for match in re.finditer(r"#mdCard\[data-md-doc-theme\]", text):
        assert text[: match.end()].endswith(MD_DOC_THEME_ROOT_SELECTOR), (
            f"{path.name}: מופע של הכרטיס בלי התנאי המלא, בעמדה {match.start()}"
        )


# ---------------------------------------------------------------------------
# הפענוח
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        (f"custom:{DOC_THEME_ID}", f"custom:{DOC_THEME_ID}"),
        (f"  CUSTOM:{DOC_THEME_ID.upper()}  ", f"custom:{DOC_THEME_ID}"),
        (f"shared:{SHARED_SLUG}", f"shared:{SHARED_SLUG}"),
        ("none", ""),
        ("custom", None),
        ("custom:", None),
        ("dark", None),
        ("shared:../x", None),
        ("builtin:classic", None),
        (5, None),
        (["custom:x"], None),
        (None, None),
    ],
)
def test_decode(raw, expected):
    from webapp.app import _decode_md_doc_theme

    assert _decode_md_doc_theme(raw) == expected


# ---------------------------------------------------------------------------
# ה-CSS של הכרטיס
# ---------------------------------------------------------------------------


def test_the_card_css_declares_the_theme_and_unsets_every_other_whitelisted_variable():
    variables = {"--bg-primary": "#f8f6f1", "--text-primary": "#2b3f6a"}
    css = build_md_doc_theme_css(variables, "")
    reset, declared = css.splitlines()

    assert reset.startswith(f":where({MD_DOC_THEME_ROOT_SELECTOR}) {{")
    unset = set(re.findall(r"(--[\w-]+): initial;", reset))
    assert unset == ALLOWED_VARIABLES_WHITELIST - set(variables)
    # ווי הדריסה שערכה אחרת הייתה מעבירה לכרטיס — בפרט צבעי המסמך
    assert "--md-heading-color-override" in unset and "--md-search-capsule-border-override" in unset

    assert declared == f"{MD_DOC_THEME_ROOT_SELECTOR} {{ --bg-primary: #f8f6f1; --text-primary: #2b3f6a; }}"


def test_what_reaches_the_style_block_is_only_whitelisted_colours():
    """הערכים מגיעים מהמסד. כל מה שאינו צבע מהרשימה הלבנה לא מגיע ל-``<style>``."""
    css = build_md_doc_theme_css(
        {
            "--bg-primary": "#fff}</style><script>alert(1)</script>",
            "--text-primary": "url(https://evil.example/x)",
            "--not-whitelisted": "#000",
            "--link-color": "#123456",
        },
        ':root[data-theme-type="custom"] .hljs-keyword { color: #f00; } </style>',
    )
    assert "<" not in css and "url(" not in css and "--not-whitelisted:" not in css
    assert f"{MD_DOC_THEME_ROOT_SELECTOR} {{ --link-color: #123456; }}" in css
    assert "--bg-primary: initial;" in css


def test_the_card_gets_the_theme_syntax_colours_with_the_base_rule():
    syntax = parse_vscode_theme(LIGHT_VSCODE)["syntax_css"]
    css = build_md_doc_theme_css({}, syntax)
    hljs = [line for line in css.splitlines() if ".hljs" in line]

    prefix = f":where({MD_DOC_THEME_ROOT_SELECTOR})"
    assert f"{prefix} .hljs {{ color: #2b3f6a !important; background: #f8f6f1 !important; }}" in hljs
    assert f"{prefix} .hljs-keyword {{ color: #5e78e1 !important; }}" in hljs
    assert all(line.startswith(prefix) for line in hljs), hljs


def test_rebase_keeps_the_base_rule_only_when_asked():
    syntax = parse_vscode_theme(LIGHT_VSCODE)["syntax_css"]
    assert "x .hljs {" not in rebase_hljs_css(syntax, "x")
    assert "x .hljs { color: #2b3f6a !important; background: #f8f6f1 !important; }" in rebase_hljs_css(
        syntax, "x", include_base=True
    )


def test_the_ui_syntax_colours_stop_at_the_card_and_everything_else_is_untouched():
    syntax = parse_vscode_theme(DARK_VSCODE)["syntax_css"]
    out = exclude_md_doc_theme_from_hljs_css(syntax)
    exclusion = f":not(:where({MD_DOC_THEME_ROOT_SELECTOR} *))"

    original = syntax.splitlines()
    rewritten = out.splitlines()
    assert len(original) == len(rewritten)
    hljs_lines = 0
    for before, after in zip(original, rewritten):
        if re.search(r"\s\.hljs(-[\w.-]+)?\s*\{", before):
            hljs_lines += 1
            selector, body = before.split("{", 1)
            assert after == f"{selector.strip()}{exclusion} {{ {body.rsplit('}', 1)[0].strip()} }}"
        else:
            assert after == before
    # הקלט באמת כלל את כל הסוגים: הכלל הבסיסי, כלל טוקן, ושורות שאינן של highlight.js
    assert hljs_lines >= 2 and ".tok-" in out and ".highlight " in out


# ---------------------------------------------------------------------------
# האפליקציה: שמירה, עמוד, מחיקה
# ---------------------------------------------------------------------------


@pytest.fixture
def world(monkeypatch):
    import webapp.app as wa

    db = FakeDB()
    monkeypatch.setattr(wa, "get_db", lambda: db)
    file_id = ObjectId()
    db.users.insert_one({
        "user_id": USER_ID,
        "ui_prefs": {"theme": "custom"},
        "custom_themes": [
            _theme_doc(UI_THEME_ID, DARK_VSCODE, active=True),
            _theme_doc(DOC_THEME_ID, LIGHT_VSCODE),
        ],
    })
    db.shared_themes.insert_one({
        "_id": SHARED_SLUG,
        "name": "Paper (public)",
        "colors": {"--bg-primary": "#fdfdfd", "--text-primary": "#111111"},
        "syntax_css": "",
        "is_active": True,
        "updated_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
    })
    db.code_snippets.insert_one({
        "_id": file_id,
        "user_id": USER_ID,
        "file_name": "doc.md",
        "code": "# כותרת\n\n```python\nif x:\n    pass\n```\n",
        "programming_language": "markdown",
        "version": 1,
        "is_active": True,
    })

    def client():
        c = wa.app.test_client()
        with c.session_transaction() as sess:
            sess["user_id"] = USER_ID
            sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה"}
        return c

    class World:
        pass

    w = World()
    w.db, w.file_id, w.client, w.wa = db, str(file_id), client, wa
    return w


def _stored(world):
    doc = world.db.users.find_one({"user_id": USER_ID})
    return (doc.get("ui_prefs") or {}).get("md_doc_theme", "<absent>")


def _post(client, payload):
    return client.post("/api/ui_prefs", json=payload)


def test_saving_writes_the_pointer_and_answers_with_what_was_stored(world):
    r = _post(world.client(), {"md_doc_theme": f"custom:{DOC_THEME_ID}"})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["md_doc_theme"] == f"custom:{DOC_THEME_ID}"
    assert _stored(world) == f"custom:{DOC_THEME_ID}"


def test_a_public_theme_can_be_the_document_theme(world):
    r = _post(world.client(), {"md_doc_theme": f"shared:{SHARED_SLUG}"})
    assert r.status_code == 200, r.get_json()
    assert _stored(world) == f"shared:{SHARED_SLUG}"


@pytest.mark.parametrize("value", ["custom:deadbeef-0000", "shared:no_such_theme"])
def test_a_theme_that_does_not_exist_is_refused_and_nothing_is_written(world, value):
    r = _post(world.client(), {"md_doc_theme": value})
    assert r.status_code == 404 and r.get_json()["error"] == "md_doc_theme_not_found"
    assert _stored(world) == "<absent>"


@pytest.mark.parametrize("value", ["dark", "none", "", 5, ["x"], {"a": 1}, f"custom:{DOC_THEME_ID} x"])
def test_a_malformed_value_is_refused(world, value):
    r = _post(world.client(), {"md_doc_theme": value})
    assert r.status_code == 400, (value, r.get_json())
    assert _stored(world) == "<absent>"


def test_null_turns_it_off_by_removing_the_field(world):
    c = world.client()
    _post(c, {"md_doc_theme": f"custom:{DOC_THEME_ID}"})
    r = _post(c, {"md_doc_theme": None})
    assert r.status_code == 200 and r.get_json()["md_doc_theme"] is None
    assert _stored(world) == "<absent>"


def test_an_unreachable_database_is_503_and_not_404(world, monkeypatch):
    monkeypatch.setattr(world.wa, "_request_user_doc", lambda _uid: None)
    r = _post(world.client(), {"md_doc_theme": f"custom:{DOC_THEME_ID}"})
    assert r.status_code == 503 and r.get_json()["error"] == "database_unavailable"


def _set_cookie_values(response) -> dict:
    out = {}
    for header in response.headers.getlist("Set-Cookie"):
        name, _, rest = header.partition("=")
        out[name] = rest.split(";", 1)[0]
    return out


def test_device_scope_stays_on_the_device(world):
    r = _post(world.client(), {"md_doc_theme": f"custom:{DOC_THEME_ID}", "md_doc_theme_scope": "device"})
    assert r.status_code == 200, r.get_json()
    cookies = _set_cookie_values(r)
    assert cookies["ui_md_doc_theme"] == f"custom:{DOC_THEME_ID}"
    assert cookies["ui_md_doc_theme_scope"] == "device"
    assert _stored(world) == "<absent>"


# ---------------------------------------------------------------------------
# הבחירה הנוכחית — ``GET /api/ui_prefs/md_doc_theme``, שממנו מודאל הערכות והגלריה קוראים
# ---------------------------------------------------------------------------

STATE_URL = "/api/ui_prefs/md_doc_theme"


def _state(client):
    r = client.get(STATE_URL)
    return r.status_code, r.get_json()


def test_the_state_says_none_when_nothing_is_chosen(world):
    assert _state(world.client()) == (
        200, {"ok": True, "md_doc_theme": None, "scope": "global", "name": None, "found": False}
    )


def test_the_state_names_the_chosen_theme_personal_and_public(world):
    c = world.client()
    _post(c, {"md_doc_theme": f"custom:{DOC_THEME_ID}"})
    assert _state(c) == (
        200, {"ok": True, "md_doc_theme": f"custom:{DOC_THEME_ID}", "scope": "global", "name": "Paper", "found": True}
    )
    _post(c, {"md_doc_theme": f"shared:{SHARED_SLUG}"})
    assert _state(c)[1]["name"] == "Paper (public)"


def test_the_state_marks_a_pointer_to_a_theme_that_is_gone(world):
    world.db.users.update_one({"user_id": USER_ID}, {"$set": {"ui_prefs.md_doc_theme": "custom:gone-theme-id"}})
    assert _state(world.client()) == (
        200, {"ok": True, "md_doc_theme": "custom:gone-theme-id", "scope": "global", "name": None, "found": False}
    )


def test_the_state_is_what_this_device_gets(world):
    world.db.users.update_one({"user_id": USER_ID}, {"$set": {"ui_prefs.md_doc_theme": f"custom:{DOC_THEME_ID}"}})
    c = world.client()
    _post(c, {"md_doc_theme": None, "md_doc_theme_scope": "device"})
    assert _state(c) == (
        200, {"ok": True, "md_doc_theme": None, "scope": "device", "name": None, "found": False}
    )
    # ובמכשיר אחר, בלי ה-cookie — הבחירה שבמסד
    assert _state(world.client())[1]["md_doc_theme"] == f"custom:{DOC_THEME_ID}"


def test_an_unreachable_database_makes_the_state_503_and_not_none(world, monkeypatch):
    # "ללא" על מסד שלא ענה היה מוצג במודאל ובגלריה כאילו אין ערכת מסמך.
    monkeypatch.setattr(world.wa, "_request_user_doc", lambda _uid: None)
    assert _state(world.client()) == (503, {"ok": False, "error": "database_unavailable"})


def test_a_public_theme_that_cannot_be_read_makes_the_state_503(world, monkeypatch):
    c = world.client()
    _post(c, {"md_doc_theme": f"shared:{SHARED_SLUG}", "md_doc_theme_scope": "device"})
    monkeypatch.setattr(world.wa, "get_db", lambda: None)
    assert _state(c) == (503, {"ok": False, "error": "database_unavailable"})


def test_a_choice_that_ends_on_the_device_needs_no_database(world, monkeypatch):
    c = world.client()
    _post(c, {"md_doc_theme": None, "md_doc_theme_scope": "device"})
    monkeypatch.setattr(world.wa, "_request_user_doc", lambda _uid: None)
    status, body = _state(c)
    assert status == 200 and body["md_doc_theme"] is None and body["scope"] == "device"


def test_the_state_needs_a_login(world):
    r = world.wa.app.test_client().get(STATE_URL)
    assert r.status_code == 401


def test_the_modal_gets_the_ui_condition_the_card_selector_is_built_from(world):
    page = _page(world).get_data(as_text=True)
    m = re.search(r'class="theme-picker__modes"[^>]*data-ui-condition="([^"]*)"', page)
    assert m, "המתג של מודאל הערכות לא רונדר"
    assert html.unescape(m.group(1)) == MD_DOC_THEME_UI_CONDITION
    assert MD_DOC_THEME_ROOT_SELECTOR.startswith(f"{MD_DOC_THEME_UI_CONDITION} ")


def _page(world, client=None, **headers):
    c = client or world.client()
    return c.get(f"/md/{world.file_id}", headers=headers)


def test_the_page_carries_the_theme_only_when_one_is_chosen(world):
    plain = _page(world).get_data(as_text=True)
    assert CARD_ATTR not in plain and 'id="md-doc-theme"' not in plain
    # בלי ערכת מסמך — הכללים של ערכת הממשק יוצאים כמו שהם
    assert ":not(:where(" not in plain

    world.db.users.update_one({"user_id": USER_ID}, {"$set": {"ui_prefs.md_doc_theme": f"custom:{DOC_THEME_ID}"}})
    themed = _page(world).get_data(as_text=True)
    assert 'id="mdCard" data-md-doc-theme=""' in themed
    style = re.search(r'<style id="md-doc-theme">(.*?)</style>', themed, re.S).group(1)
    assert "--bg-primary: #f8f6f1;" in style and ".hljs-keyword { color: #5e78e1 !important; }" in style
    # כללי highlight.js של ערכת הממשק לא חלים בתוך הכרטיס
    ui_syntax = re.search(r'<style id="user-custom-syntax">(.*?)</style>', themed, re.S).group(1)
    assert f":root[data-theme-type=\"custom\"] .hljs-keyword:not(:where({MD_DOC_THEME_ROOT_SELECTOR} *))" in ui_syntax


def test_other_pages_get_the_ui_syntax_colours_untouched(world):
    world.db.users.update_one({"user_id": USER_ID}, {"$set": {"ui_prefs.md_doc_theme": f"custom:{DOC_THEME_ID}"}})
    page = world.client().get("/settings/theme-gallery").get_data(as_text=True)
    assert ":not(:where(" not in page


def test_a_device_off_beats_a_stored_choice(world):
    world.db.users.update_one({"user_id": USER_ID}, {"$set": {"ui_prefs.md_doc_theme": f"custom:{DOC_THEME_ID}"}})
    c = world.client()
    r = _post(c, {"md_doc_theme": None, "md_doc_theme_scope": "device"})
    assert _set_cookie_values(r)["ui_md_doc_theme"] == "none"
    assert _stored(world) == f"custom:{DOC_THEME_ID}"  # במסד לא נגעו
    assert CARD_ATTR not in _page(world, c).get_data(as_text=True)
    # ובמכשיר אחר, בלי ה-cookie — הבחירה שבמסד
    assert CARD_ATTR in _page(world).get_data(as_text=True)


def test_a_pointer_to_a_theme_that_is_gone_renders_in_the_ui_theme(world):
    world.db.users.update_one({"user_id": USER_ID}, {"$set": {"ui_prefs.md_doc_theme": "custom:gone-theme-id"}})
    r = _page(world)
    assert r.status_code == 200 and CARD_ATTR not in r.get_data(as_text=True)


def test_the_etag_follows_the_choice_and_the_theme(world):
    c = world.client()
    none_etag = _page(world, c).headers["ETag"]
    assert _page(world, c, **{"If-None-Match": none_etag}).status_code == 304  # הוולידטור עובד

    _post(c, {"md_doc_theme": f"custom:{DOC_THEME_ID}"})
    chosen = _page(world, c, **{"If-None-Match": none_etag})
    assert chosen.status_code == 200, "בחירה בערכת מסמך החזירה 304 עם העמוד הישן"
    chosen_etag = chosen.headers["ETag"]

    # עריכה של הערכה (``update_theme`` מקדם את ``updated_at``) — מראה חדש, ETag חדש
    doc = world.db.users.find_one({"user_id": USER_ID})
    for t in doc["custom_themes"]:
        if t["id"] == DOC_THEME_ID:
            t["updated_at"] = t["updated_at"] + timedelta(minutes=5)
    world.db.users.update_one({"user_id": USER_ID}, {"$set": {"custom_themes": doc["custom_themes"]}})
    edited = _page(world, c, **{"If-None-Match": chosen_etag})
    assert edited.status_code == 200, "עריכה של ערכת המסמך החזירה 304 עם הצבעים הישנים"

    _post(c, {"md_doc_theme": None})
    off = _page(world, c, **{"If-None-Match": edited.headers["ETag"]})
    assert off.status_code == 200 and off.headers["ETag"] == none_etag


# ---------------------------------------------------------------------------
# מחיקת ערכה — מול מונגו אמיתי
#
# ``delete_theme`` מאתר את הערכה ב-``custom_themes.id`` (נתיב לתוך מערך) ומוחק ב-``$pull``, ו-``FakeDB`` לא
# מממש אף אחד מהם — הוא היה עונה 404 על ערכה שקיימת. לכן ``wired_mongo``: הבדיקות רצות ב-CI, שם
# ``NOTE_FONTS_TEST_MONGO_URI`` מוגדר, ומדולגות בלעדיו.
# ---------------------------------------------------------------------------


def _mongo_client(wired_mongo, pointer: str):
    db = wired_mongo.get_db()
    db.users.delete_many({"user_id": USER_ID})
    db.users.insert_one({
        "user_id": USER_ID,
        "ui_prefs": {"md_doc_theme": pointer},
        "custom_themes": [_theme_doc(UI_THEME_ID, DARK_VSCODE), _theme_doc(DOC_THEME_ID, LIGHT_VSCODE)],
    })
    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
    return db, client


def _mongo_pointer(db):
    return (db.users.find_one({"user_id": USER_ID}).get("ui_prefs") or {}).get("md_doc_theme", "<absent>")


def test_deleting_the_document_theme_clears_the_pointer(wired_mongo):
    db, client = _mongo_client(wired_mongo, f"custom:{DOC_THEME_ID}")
    r = client.delete(f"/api/themes/{DOC_THEME_ID}")
    assert r.status_code == 200, r.get_json()
    assert _mongo_pointer(db) == "<absent>"


def test_deleting_another_theme_leaves_the_pointer(wired_mongo):
    db, client = _mongo_client(wired_mongo, f"custom:{DOC_THEME_ID}")
    r = client.delete(f"/api/themes/{UI_THEME_ID}")
    assert r.status_code == 200, r.get_json()
    assert _mongo_pointer(db) == f"custom:{DOC_THEME_ID}"
