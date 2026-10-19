"""עמוד שיתוף ציבורי, בתצוגת קוד — כל פעולה בו מובילה לנתיב ציבורי שעובד.

**למה הקובץ הזה קיים.** מאז הגרסה הראשונה של השיתוף (#449) ``/share/<share_id>`` מרנדר את
התבנית של עמוד הקובץ של הבעלים, ``view_file.html``, ושם כל כפתור בנוי מ-``file.id`` — שבעמוד
שיתוף הוא מזהה השיתוף ולא מזהה קובץ. לאורך השנה נוספו לתבנית כפתורי בעלים בלי שאיש חשב על
העמוד הציבורי, ולכן "ערוך", "תצוגת Markdown", "הורד" ו"השוואת גרסאות" הובילו ל-
``/edit/<share_id>``, ``/md/<share_id>``, ``/download/<share_id>``: אורח הופנה להתחברות,
ומשתמש מחובר קיבל 404. לצידם הופיעו מועדפים, אוסף, תיאור, היסטוריה, סל ושיתוף מחדש.
"העתק קוד" לא קיבל את הטקסט הגולמי וגירד אותו מה-HTML, ו-``/share/<id>/download`` עבד רק
לשיתוף ששדה ה-``mode`` שלו ``download`` — שאף כפתור בוובאפ לא יצר. עד #3585 אף אחד לא הגיע
לכפתורים האלה, כי הקובץ נקטע אחרי כמה עשרות שורות.

**למה הבדיקה מבנית ולא רשימה של כפתורים שבורים.** הכשל לא היה כפתור אחד אלא כיוון: כל כפתור
חדש בעמוד הבעלים דלף לעמוד הציבורי. לכן סרגל הפעולות של העמוד הציבורי נבדק מול רשימה סגורה
(``PUBLIC_ACTIONS``), וכל קישור שנושא את מזהה השיתוף חייב להוביל לנתיב ציבורי שעונה 200. כפתור
שיתווסף לעמוד הבעלים בלי ``{% if not is_public %}`` יפיל את הטסט, ומי שמוסיף אותו יחליט במודע.

השיתופים נוצרים דרך הראוט עצמו, עם אותו גוף בקשה שהכפתורים שולחים, ושיתוף הבוט דרך הכותב
האמיתי שלו — כמו ב-``tests/test_public_share_full_content.py``. דמה בעבודת יד (``_fake_mongo``).
"""

from __future__ import annotations

import re
import types
from html.parser import HTMLParser
from urllib.parse import urlparse

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeDB

from webapp import app as webapp_app

OWNER_ID = 6150
VISITOR_ID = 6151
FILE_OID = ObjectId("0123456789abcdef0123ab02")

#: תווים ש-HTML מקודד (``<``, ``&``, גרשיים), עברית, וטאב — כדי שהעתקה שעוברת דרך ה-HTML ולא
#: דרך הטקסט הגולמי תיראה מיד. קובץ הפייתון **מתחיל בשורה ריקה**: הדפדפן בולע שורה חדשה אחת
#: שצמודה לתגית הפתיחה של ``<textarea>``, ועד התיקון הזה השורה הזו נעלמה בהעתקה.
SHARED_CODE = {
    "md": "# מדריך\n\nif a < b && c > d:\n\t\"quoted\" & 'single'\n",
    "py": "\ndef f(a, b):\n\treturn a < b and \"x\" != '&'\n# שורה בעברית\n",
}
FILE_NAMES = {"md": "guide.md", "py": "values.py"}
LANGUAGES = {"md": "markdown", "py": "python"}

#: הפעולות שיש להן נתיב ציבורי — ``data-overflow-id`` בסרגל של ``view_file.html``.
PUBLIC_ACTIONS = {
    "md": {"copy", "markdown", "reader", "download"},
    "py": {"copy", "download"},
}

#: הנתיבים הציבוריים של שיתוף: ``public_share``, ``public_reader_mode``, ``public_share_download``.
PUBLIC_ROUTE = r"^/(?:share/{sid}(?:/download)?|read/share/{sid})$"


class _Page(HTMLParser):
    """כל תגית פתיחה עם המאפיינים שלה, ותוכן ``<textarea id="rawCode">`` — כפי שהדפדפן קורא אותו.

    ‏``html.parser`` אינו בונה עץ לפי התקן, ולכן הוא לא בולע את השורה החדשה שצמודה לתגית
    הפתיחה של ``<textarea>`` (HTML Living Standard, ה-"in body" insertion mode). ``raw_code``
    מחקה כאן את הדפדפן: בלי זה הטסט היה בודק מחרוזת אחרת מזו ש"העתק קוד" מעתיק. ההתנהגות
    נמדדה ב-Chromium: ``'\\n\\nx'`` צמוד לתגית נקרא ``'\\nx'``.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict]] = []
        self.raw_code: str | None = None
        self._in_raw = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.elements.append((tag, attrs))
        if tag == "textarea" and attrs.get("id") == "rawCode":
            self._in_raw = True
            self.raw_code = ""

    def handle_endtag(self, tag):
        if tag == "textarea":
            self._in_raw = False

    def handle_data(self, data):
        if self._in_raw:
            if not self.raw_code and data.startswith("\n"):
                data = data[1:]
            self.raw_code += data


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(webapp_app, "get_db", lambda: fake)
    return fake


def _client_as(user_id: int | None):
    client = webapp_app.app.test_client()
    if user_id is not None:
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_data"] = {"id": user_id, "first_name": "Test"}
    return client


def _seed_file(db, kind: str) -> str:
    db["code_snippets"].insert_one({
        "_id": FILE_OID,
        "user_id": OWNER_ID,
        "file_name": FILE_NAMES[kind],
        "code": SHARED_CODE[kind],
        "programming_language": LANGUAGES[kind],
        "version": 1,
        "is_active": True,
    })
    return str(FILE_OID)


def _share_from_the_webapp(db, kind: str, *, permanent: bool = False) -> str:
    """יוצר שיתוף בדיוק כמו הכפתורים (``requestShareLink`` ב-``view_file.html``) ומחזיר את מזהה השיתוף."""
    resp = _client_as(OWNER_ID).post(
        f"/api/share/{_seed_file(db, kind)}",
        json={"type": "permanent" if permanent else "temporary", "permanent": permanent},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return urlparse(resp.get_json()["url"]).path.rsplit("/", 1)[-1]


def _public_page(client, share_id: str) -> _Page:
    resp = client.get(f"/share/{share_id}")
    assert resp.status_code == 200
    page = _Page()
    page.feed(resp.get_data(as_text=True))
    return page


VISITORS = pytest.mark.parametrize("visitor", [None, VISITOR_ID], ids=["guest", "member"])
KINDS = pytest.mark.parametrize("kind", ["md", "py"])


@VISITORS
@KINDS
def test_the_action_bar_holds_only_actions_with_a_public_route(db, visitor, kind):
    share_id = _share_from_the_webapp(db, kind)

    page = _public_page(_client_as(visitor), share_id)

    actions = {attrs["data-overflow-id"] for _tag, attrs in page.elements if "data-overflow-id" in attrs}
    assert actions == PUBLIC_ACTIONS[kind], (
        "פעולה בסרגל של העמוד הציבורי שלא הוחלט עליה. אם יש לה נתיב ציבורי — הוסיפו אותה "
        "ל-PUBLIC_ACTIONS; אם היא פעולת בעלים — עטפו אותה ב-{% if not is_public %} ב-view_file.html."
    )
    # התפריט ⋮ ופריטיו, אזור השיתוף והסימניות — כולם פעולות בעלים
    assert not [attrs for _tag, attrs in page.elements if "data-menu-action" in attrs]
    assert not [attrs for _tag, attrs in page.elements if attrs.get("id") in {
        "fileActionsMenuButton", "shareLinkModal", "editDescriptionModal",
        "historyModal", "trashConfirmModal", "fileId",
    }]


@VISITORS
@KINDS
def test_every_link_that_carries_the_share_id_leads_to_a_public_route_that_answers(db, visitor, kind):
    share_id = _share_from_the_webapp(db, kind)
    client = _client_as(visitor)
    public_route = re.compile(PUBLIC_ROUTE.format(sid=re.escape(share_id)))

    page = _public_page(client, share_id)

    links = [
        value
        for _tag, attrs in page.elements
        for name, value in attrs.items()
        if value and share_id in value and (name in {"href", "action", "formaction"} or name.endswith("-href"))
    ]
    expected = {f"/share/{share_id}/download"}
    if kind == "md":
        expected |= {f"/share/{share_id}?view=md", f"/read/share/{share_id}"}
    assert set(links) == expected
    for link in links:
        assert public_route.match(urlparse(link).path), link
        assert client.get(link).status_code == 200, link
    # כפתור שקורא לפונקציה עם מזהה הקובץ (``openExportModal('<id>')``) הוא אותו כשל בלי href
    assert not [attrs["onclick"] for _tag, attrs in page.elements if share_id in (attrs.get("onclick") or "")]


@KINDS
def test_copy_code_copies_the_shared_text_and_not_the_rendered_page(db, kind):
    share_id = _share_from_the_webapp(db, kind)

    page = _public_page(_client_as(None), share_id)

    assert page.raw_code == SHARED_CODE[kind]


@pytest.mark.parametrize("permanent", [False, True], ids=["temporary", "permanent"])
def test_a_share_from_the_webapp_downloads_the_whole_file(db, permanent):
    share_id = _share_from_the_webapp(db, "md", permanent=permanent)

    resp = _client_as(None).get(f"/share/{share_id}/download")

    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == SHARED_CODE["md"]
    assert resp.headers["Content-Disposition"].startswith("attachment")
    assert "guide.md" in resp.headers["Content-Disposition"]


def test_a_share_made_by_the_bot_downloads_too(db, monkeypatch):
    """שיתוף הבוט אינו נושא ``mode`` בכלל, ולכן עד התיקון ההורדה שלו החזירה 404."""
    import database
    import integrations

    monkeypatch.setattr(
        database, "db",
        types.SimpleNamespace(internal_shares_collection=db["internal_shares"]),
        raising=False,
    )
    result = integrations.CodeSharingService()._create_internal_share(
        "values.py", SHARED_CODE["py"], "python", "שיתוף פנימי של values.py",
    )
    share_id = urlparse(result["url"]).path.rsplit("/", 1)[-1]

    resp = _client_as(None).get(f"/share/{share_id}/download")

    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == SHARED_CODE["py"]


def test_a_share_without_content_cannot_be_downloaded_and_is_counted(db, monkeypatch):
    events = []
    monkeypatch.setattr(webapp_app, "emit_event", lambda name, *_a, **fields: events.append((name, fields)))
    db["internal_shares"].insert_one({
        "share_id": "nocontent02",
        "file_name": "guide.md",
        "language": "markdown",
        "mode": "download",
        "source_file_id": FILE_OID,
    })

    assert _client_as(None).get("/share/nocontent02/download").status_code == 404
    assert [name for name, _fields in events if name == "share_without_content"] == ["share_without_content"]


def test_a_new_share_no_longer_records_a_mode(db):
    """``mode`` קבע רק אם ההורדה פתוחה. שדה שנשמר בלי שאיש קורא אותו היה מתאר הרשאה שאינה קיימת."""
    share_id = _share_from_the_webapp(db, "md")

    stored = db["internal_shares"].find_one({"share_id": share_id})

    assert "mode" not in stored


def test_the_owner_page_keeps_its_owner_actions(db):
    """הצד השני של אותה תבנית: ``is_public`` לא דולף לעמוד הבעלים."""
    file_id = _seed_file(db, "md")

    resp = _client_as(OWNER_ID).get(f"/file/{file_id}?nc=1")

    assert resp.status_code == 200
    page = _Page()
    page.feed(resp.get_data(as_text=True))
    actions = {attrs["data-overflow-id"] for _tag, attrs in page.elements if "data-overflow-id" in attrs}
    assert {"edit", "copy", "markdown", "download", "collection", "back"} <= actions
    assert "reader" not in actions
    hrefs = {attrs.get("href") for _tag, attrs in page.elements}
    assert {f"/edit/{file_id}", f"/md/{file_id}", f"/download/{file_id}"} <= hrefs
    assert any(attrs.get("data-menu-action") == "share" for _tag, attrs in page.elements)
