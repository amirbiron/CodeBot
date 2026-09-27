"""הוובאפ שומר את מה שהמשתמש כתב — דרך הטופס, כמו שהדפדפן שולח אותו.

**הטופס נגזר מה-HTML שהשרת מחזיר** (T1): הטסט טוען את ``/edit/<id>`` ואת
``/upload``, קורא מה-``<form>`` את ``method``, ``enctype``, ``action`` ואת שמות
השדות, ושולח את הערכים שהם מחזיקים — וב-textarea את מה שהמשתמש "הקליד".

**ושולח כמו דפדפן, לא כמו ה-test client.** werkzeug כותב ערך טקסט כמו שהוא
(``stream_encode_multipart`` ב-``werkzeug/test.py``, גרסה 3.1.8). דפדפן לא: לפי
HTML Living Standard, סעיף 4.10.22.8, בכל ערך שאינו קובץ כל LF הופך ל-CRLF לפני
השליחה (נמדד ב-Chromium 141). ``_browser_value`` מחיל את הכלל הזה על ערכי
הטקסט, ולא על קבצים — גם התקן לא נוגע בהם.

**מה נבדק:** מה שנשמר באוסף זהה לערך שהיה ב-textarea. קובץ שמעלים נשמר בית
בבית, כולל BOM ו-CRLF. עד ספטמבר 2026 שני המסלולים עברו ``normalize_code``,
שמחק RLM, רצפי escape, newlines בסוף ורווחים בסוף שורה.

מוסכמת הריפו: דמה בעבודת יד, בלי mongomock, בלי ייבוא מ-conftest. תווי
כיווניות כתובים רק כ-escapes (H1).
"""

from __future__ import annotations

import io
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeDB

from webapp import app as webapp_app

USER_ID = 616
FILE_OID = ObjectId("0123456789abcdef0123abcd")

RLM, ALM, ZWJ = "\u200f", "\u061c", "\u200d"
FAMILY = "\U0001F468" + ZWJ + "\U0001F469" + ZWJ + "\U0001F467"

# (שם הקובץ, מה שהמשתמש הקליד ב-textarea). בלי CR: ערך של textarea לא יכול
# להחזיק CR (נמדד), ולכן אין דרך להקליד אותו — ראו ``_textarea_api_value``.
CASES = {
    "rlm_mid_line": ("notes.md", "גרסה" + RLM + " 2.0 יצאה\n"),
    "rlm_line_start": ("notes.md", "שורה ראשונה\n" + RLM + "(1) פריט\n"),
    "alm": ("arabic.md", "العربية" + ALM + " 123\n"),
    "escape_in_python_string": ("marks.py", 'RLM = "\\u200f"\nprint(len(RLM))\n'),
    "regex_escape_range": ("guard.py", 'HIDDEN = re.compile(r"[\\u200b-\\u200f\\u202a-\\u202e]")\n'),
    "one_trailing_newline": ("one.py", "x = 1\n"),
    "three_trailing_newlines": ("three.py", "x = 1\n\n\n"),
    "md_hard_break": ("poem.md", "שורה עם שבירה  \nהשורה הבאה\n"),
    "family_emoji": ("emoji.py", "print('" + FAMILY + "')\n"),
}


class _FormReader(HTMLParser):
    """ה-``<form>`` עם ``id`` נתון, כפי שדפדפן היה מגיש אותו בלי JavaScript.

    שדות "מוצלחים" בלבד: ``input`` עם שם (תיבת סימון רק כשהיא מסומנת, בלי
    כפתורים), ``textarea``, ו-``select`` עם האפשרות המסומנת או הראשונה.
    ``input type=file`` נאסף בנפרד — בשליחה הוא חלק ריק עם ``filename=""``.
    """

    def __init__(self, form_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.form_id = form_id
        self.attrs: Optional[Dict[str, Optional[str]]] = None
        self.fields: List[Tuple[str, str]] = []
        self.textareas: set = set()
        self.file_inputs: List[str] = []
        self._inside = False
        self._textarea: Optional[List[Any]] = None
        self._select: Optional[List[Any]] = None
        self._option: Optional[List[Any]] = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and a.get("id") == self.form_id:
            self.attrs, self._inside = a, True
            return
        if not self._inside:
            return
        name = a.get("name")
        if tag == "input" and name:
            kind = (a.get("type") or "text").lower()
            if kind == "file":
                self.file_inputs.append(name)
            elif kind in ("checkbox", "radio"):
                if "checked" in a:
                    self.fields.append((name, a.get("value") or "on"))
            elif kind not in ("submit", "button", "image", "reset"):
                self.fields.append((name, a.get("value") or ""))
        elif tag == "textarea" and name:
            self._textarea = [name, []]
        elif tag == "select" and name:
            self._select = [name, []]
        elif tag == "option" and self._select is not None:
            self._option = [a.get("value"), "selected" in a, []]

    def handle_data(self, data):
        if self._textarea is not None:
            self._textarea[1].append(data)
        if self._option is not None:
            self._option[2].append(data)

    def handle_endtag(self, tag):
        if tag == "form" and self._inside:
            self._inside = False
        elif tag == "textarea" and self._textarea is not None:
            name, chunks = self._textarea
            value = "".join(chunks)
            # מפענח HTML מתעלם מ-LF אחד שבא מיד אחרי תג הפתיחה של textarea
            # (נמדד ב-Chromium, ראו tests/test_webapp_edit_browser_preserves_content.py).
            if value.startswith("\n"):
                value = value[1:]
            self.fields.append((name, value))
            self.textareas.add(name)
            self._textarea = None
        elif tag == "option" and self._option is not None:
            value, selected, chunks = self._option
            self._select[1].append((value if value is not None else "".join(chunks).strip(), selected))
            self._option = None
        elif tag == "select" and self._select is not None:
            name, options = self._select
            chosen = next((v for v, sel in options if sel), options[0][0] if options else None)
            if chosen is not None:
                self.fields.append((name, chosen))
            self._select = None


def _textarea_api_value(typed: str) -> str:
    """מה שה-textarea מחזיק אחרי הקלדה: בלי CR (נמדד ב-Chromium 141)."""
    return typed.replace("\r\n", "\n").replace("\r", "\n")


def _browser_value(value: str) -> str:
    """HTML Living Standard, סעיף 4.10.22.8: כל CR ו-LF בודדים הופכים ל-CRLF."""
    return re.sub(r"\r\n|\r|\n", "\r\n", value)


def _submit_like_a_browser(client, page_url: str, form_id: str, typed: Dict[str, str], files=None):
    """טוען את העמוד, קורא ממנו את הטופס, ומגיש אותו כמו דפדפן."""
    page = client.get(page_url)
    assert page.status_code == 200, page.status_code
    reader = _FormReader(form_id)
    reader.feed(page.get_data(as_text=True))
    assert reader.attrs is not None, f"לא נמצא <form id={form_id}> בעמוד"
    assert (reader.attrs.get("method") or "get").lower() == "post"
    enctype = reader.attrs.get("enctype") or "application/x-www-form-urlencoded"
    # HTML Living Standard, אלגוריתם שליחת הטופס: "If action is the empty
    # string, let action be the URL of the form document."
    action = reader.attrs.get("action") or page_url

    names = [name for name, _ in reader.fields]
    assert len(names) == len(set(names)), f"שם שדה כפול בטופס: {names}"
    assert set(typed) <= set(names), f"הטופס אינו מחזיק את השדות {set(typed) - set(names)}"
    data: Dict[str, Any] = {}
    for name, value in reader.fields:
        value = typed.get(name, value)
        if name in reader.textareas:
            value = _textarea_api_value(value)
        data[name] = _browser_value(value)
    for name in reader.file_inputs:
        data[name] = (files or {}).get(name, (io.BytesIO(b""), ""))
    return client.post(action, data=data, content_type=enctype, follow_redirects=False)


def _existing_doc(**overrides) -> Dict[str, Any]:
    doc = {
        "_id": FILE_OID,
        "user_id": USER_ID,
        "file_name": "existing.md",
        "programming_language": "markdown",
        "code": "before\n",
        "description": "",
        "tags": [],
        "version": 1,
        "is_active": True,
    }
    doc.update(overrides)
    return doc


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(webapp_app, "get_db", lambda: fake)
    return fake


@pytest.fixture
def client(db):
    c = webapp_app.app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "Test"}
    return c


def _newest(db, file_name: str) -> Dict[str, Any]:
    docs = [d for d in db["code_snippets"].docs if d.get("file_name") == file_name and d.get("user_id") == USER_ID]
    assert docs, f"{file_name} לא נשמר כלל"
    return max(docs, key=lambda d: int(d.get("version", 0) or 0))


@pytest.mark.parametrize("case", sorted(CASES))
def test_edit_saves_the_textarea_value_as_is(monkeypatch, db, client, case):
    file_name, typed = CASES[case]
    existing = _existing_doc(file_name=file_name)
    db["code_snippets"].insert_one(dict(existing))
    monkeypatch.setattr(
        webapp_app,
        "_get_user_any_file_by_id",
        lambda db_ref, user_id, file_id: (dict(existing), "regular"),
    )

    resp = _submit_like_a_browser(client, f"/edit/{FILE_OID}", "editForm", {"code": typed})
    assert resp.status_code in (200, 302), resp.status_code

    saved = _newest(db, file_name)
    assert saved["version"] == 2, "ציפינו לגרסה חדשה"
    assert saved["code"] == _textarea_api_value(typed)


@pytest.mark.parametrize("case", sorted(CASES))
def test_upload_saves_the_textarea_value_as_is(db, client, case):
    file_name, typed = CASES[case]
    resp = _submit_like_a_browser(client, "/upload", "uploadForm", {"file_name": file_name, "code": typed})
    assert resp.status_code in (200, 302), resp.status_code
    assert _newest(db, file_name)["code"] == _textarea_api_value(typed)


def test_an_uploaded_file_is_saved_byte_for_byte(db, client):
    """הקובץ עצמו לא עובר את הקידוד של הטופס, ולכן גם לא את הפענוח — BOM ו-CRLF נשארים."""
    raw = "\ufeff# windows file\r\nx = 1\r\n".encode("utf-8")
    resp = _submit_like_a_browser(
        client,
        "/upload",
        "uploadForm",
        {"file_name": "from_disk.py"},
        files={"code_file": (io.BytesIO(raw), "from_disk.py")},
    )
    assert resp.status_code in (200, 302), resp.status_code
    assert _newest(db, "from_disk.py")["code"] == raw.decode("utf-8")


def test_whitespace_only_code_is_still_refused(db, client):
    """הבדיקה "יש תוכן" נשענה עד היום על הנרמול. עכשיו היא ``strip`` — והתוכן עצמו לא משתנה."""
    resp = _submit_like_a_browser(client, "/upload", "uploadForm", {"file_name": "blank.py", "code": "  \n\t\n"})
    assert resp.status_code == 200
    assert not [d for d in db["code_snippets"].docs if d.get("file_name") == "blank.py"]
    assert "יש להזין תוכן קוד" in resp.get_data(as_text=True)
