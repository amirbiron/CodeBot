"""‏``description_age_versions`` — כמה גרסאות עברו מאז שהתיאור נקבע.

**הבדיקות עוברות דרך ``mcp.call_tool``**, כלומר המסלול שלקוח MCP אמיתי
מפעיל — הסכימה, שער ההרשאות, העברת הזהות המאומתת, והעטיפה שמוציאה את גוף
הכלי מה-event loop. קריאה ישירה ל-``handlers`` הייתה מדלגת על כל ארבעתם
(כלל 1 ב-``claude-md-snippets/testing.md``: הבדיקה עוברת דרך אותו ממשק
כמו הצרכן). הראוט של הוובאפ נבדק דרך ה-HTTP client מאותה סיבה בדיוק.

**ומול מונגו אמיתי.** ההבטחה של השדה אינה על צורת התשובה אלא על מה
שקורה במסד לאורך **כמה** כתיבות: שהחותמת נשארת במקומה בשלוש עריכות
רצופות, ושהיא זזה כשהתיאור זז. דמה שמחזירה מילון אינה יכולה להפריך את
זה — היא תחזיר את מה שנכתב בה. לכן ``wired_mongo``, ובלי
``NOTE_FONTS_TEST_MONGO_URI`` הקובץ מדולג.

**מה מוחלף בדמה ומה לא.** ה-``DatabaseManager`` בלבד, כי הוא מתחבר לפי
הקונפיג הגלובלי ואי אפשר להפנות אותו למסד הבדיקה. הדמה מחזיקה את
ה-collection האמיתי ומאצילה ל-``Repository`` **האמיתי**, כך שמסלול
הכתיבה שרץ כאן הוא מסלול הייצור. שאר השרשרת — ``ProductionBackend``,
``handlers``, ``build_mcp`` — אמיתית כולה.

אין כאן קלט או פלט לדיסק; כל מה שנכתב הולך למסד הזמני שהפיקסצ'ר יוצר
ומוחק.

הרצה מקומית::

    NOTE_FONTS_TEST_MONGO_URI='mongodb://127.0.0.1:27017' \\
        pytest tests/test_mcp_description_age.py -v
"""

from __future__ import annotations

import ast
import contextlib
import json
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp.server.auth.middleware.auth_context import (  # noqa: E402
    auth_context_var,
)
from mcp.server.auth.provider import AccessToken  # noqa: E402
from mcp.server.lowlevel.server import request_ctx  # noqa: E402
from mcp.shared.context import RequestContext  # noqa: E402

from file_description import (  # noqa: E402
    DESCRIPTION_AGE_FIELD,
    DESCRIPTION_SET_AT_VERSION_FIELD,
    description_stamp_for_new_version,
)

USER_ID = 5150
FILE_NAME = "code-review-mcp-to-thread-PR3390.md"
DESCRIPTION = "סיכום הריוויו, האימות היריב טרם הושלם"
REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# חיווט
# --------------------------------------------------------------------------


class _ManagerOnCollection:
    """``DatabaseManager`` מינימלי שמצביע על ה-collection של מסד הבדיקה.

    **מאציל ל-``Repository`` האמיתי ואינו מחקה אותו.** זה ההבדל בין בדיקה
    שמאמתת את מסלול הכתיבה לבין בדיקה שמאמתת את עצמה: אילו המתודות כאן
    היו כותבות בעצמן, כל באג בגזירת החותמת היה עובר מתחתיהן.
    """

    def __init__(self, collection):
        self.collection = collection

    def _repo(self):
        from database.repository import Repository

        return Repository(self)

    def save_code_snippet(self, snippet):
        return self._repo().save_code_snippet(snippet)

    def get_latest_version(self, user_id, file_name):
        return self._repo().get_latest_version(user_id, file_name)

    def get_latest_version_fresh(self, user_id, file_name):
        # ``_fetch_latest_version`` ולא ``get_latest_version``, בדיוק כמו
        # ה-``DatabaseManager`` האמיתי: השנייה מקושטת ב-``@cached`` ל-180
        # שניות. דמה שהייתה מאצילה אליה הופכת את "טרי" ל"אולי ישן" —
        # וטסט שכותב למסד מחוץ למסלול (מיגרציה) היה קורא ערך שנשמר לפניה
        # ונופל על משהו שאין לו קשר למה שנבדק.
        return self._repo()._fetch_latest_version(user_id, file_name)

    def get_version(self, user_id, file_name, version):
        return self._repo().get_version(user_id, file_name, version)

    def get_all_versions(self, user_id, file_name):
        return self._repo().get_all_versions(user_id, file_name)

    def get_file_by_id(self, file_id):
        return self._repo().get_file_by_id(file_id)

    def get_regular_files_paginated(self, user_id, page=1, per_page=10):
        return self._repo().get_regular_files_paginated(user_id, page, per_page)

    def search_code(self, user_id, query, programming_language=None, tags=None, limit=20):
        return self._repo().search_code(
            user_id, query, programming_language=programming_language,
            tags=tags, limit=limit,
        )

    def update_file_metadata(self, user_id, **kwargs):
        return self._repo().update_file_metadata(user_id, **kwargs)


def _fresh_collection(wired_mongo):
    collection = wired_mongo.get_db().code_snippets
    collection.delete_many({})
    return collection


def _build_mcp(wired_mongo):
    """שרת MCP מלא מעל מסד הבדיקה.

    ``mongo_db`` מועבר ולא רק ``db_manager``, כי ``file_exists`` — השער
    ש-``codekeeper_save_file`` עובר בו — מריץ שאילתה מוקרנת על ההַנְדֶל
    הגולמי ולא דרך ה-repository. בלעדיו הוא מחזיר ``None`` והשמירה
    נדחית ב-``existence_check_unavailable``, וזה **בדיוק** מה שהחוזה שלו
    מבטיח: "לא הצלחתי לברר" אינו "הקובץ אינו קיים".
    """
    from mcp_server.backend import ProductionBackend
    from mcp_server.server import build_mcp

    db = wired_mongo.get_db()
    return build_mcp(
        ProductionBackend(db_manager=_ManagerOnCollection(db.code_snippets), mongo_db=db)
    )


@contextlib.contextmanager
def as_agent(scopes=("read", "write")):
    """הקשר בקשה + אימות, בדיוק כפי ש-``FastMCP.call_tool`` רואה אותו.

    מנהל הקשר ולא פיקסצ'ר: ``ContextVar.reset`` דורש שה-token יוחזר
    ב**אותו** ``Context`` שבו נוצר, ו-pytest-asyncio מריץ את גוף הטסט
    בהקשר משלו. ``with`` בתוך הטסט שומר את שני הצדדים באותו הקשר.
    """
    request = types.SimpleNamespace(
        state=types.SimpleNamespace(user_id=USER_ID, scopes=list(scopes))
    )
    rc = RequestContext(
        request_id=1, meta=None, session=None, lifespan_context=None, request=request
    )
    token = AccessToken(
        token="t", client_id=f"user-{USER_ID}", scopes=list(scopes), expires_at=None
    )
    rc_tok = request_ctx.set(rc)
    auth_tok = auth_context_var.set(types.SimpleNamespace(access_token=token))
    try:
        yield
    finally:
        auth_context_var.reset(auth_tok)
        request_ctx.reset(rc_tok)


async def _call(mcp, tool, **arguments):
    """קורא לכלי דרך ``mcp.call_tool`` ומפענח את התשובה.

    הכלים מוצהרים כמחזירים ``dict``, ולכן ``output_schema`` שלהם הוא
    ``None`` ו-``call_tool`` מחזיר בלוק טקסט אחד שנושא את המילון כ-JSON.
    זה מה שהלקוח מקבל בפועל, ולכן זה מה שנטען עליו.
    """
    with as_agent():
        content = await mcp.call_tool(tool, arguments)
    assert len(content) == 1, content
    return json.loads(content[0].text)


async def _age_from_get_file(mcp, file_name=FILE_NAME, **extra):
    out = await _call(mcp, "codekeeper_get_file", file_name=file_name, **extra)
    assert out.get("found") is True, out
    return out["file"]


# --------------------------------------------------------------------------
# ההבטחה: הגיל סופר עריכות, ומתאפס כשהתיאור זז
# --------------------------------------------------------------------------


async def test_a_new_file_with_a_description_starts_at_age_zero(wired_mongo):
    """יצירה — התיאור נקבע עכשיו, ולכן אפס הוא טענה נכונה.

    אפס הוא הערך היחיד שאסור להמציא, ולכן זה גם המקרה היחיד שמייצר
    אותו: הגרסה הראשונה של הקובץ **היא** הגרסה שבה התיאור נכתב.
    """
    _fresh_collection(wired_mongo)
    mcp = _build_mcp(wired_mongo)

    saved = await _call(
        mcp, "codekeeper_save_file",
        file_name=FILE_NAME, code="# גרסה ראשונה\n", description=DESCRIPTION,
    )
    assert saved["ok"] is True, saved

    assert (await _age_from_get_file(mcp))[DESCRIPTION_AGE_FIELD] == 0


async def test_three_edits_that_do_not_touch_the_description_make_it_three_versions_old(
    wired_mongo,
):
    """**זו הבדיקה המרכזית בקובץ.**

    ``codekeeper_edit_file`` מעתיק את התיאור הקיים לגרסה החדשה, וזו
    ברירת מחדל נכונה — עריכת שורת קוד אינה מבטלת תיאור. מה שהיה חסר הוא
    שהעתקה כזו **תיראה**: בלי החותמת, תיאור שנכתב בגרסה 1 נראה בגרסה 4
    בדיוק כמו תיאור שנכתב אתמול.

    הגיל נקרא מ-``codekeeper_get_file``, כלומר מהמסד ולא מהתשובה של
    כלי הכתיבה, ומספר הגרסה נטען לצידו: 3 בלי לדעת שהקובץ הגיע לגרסה 4
    אינו אומר דבר.
    """
    _fresh_collection(wired_mongo)
    mcp = _build_mcp(wired_mongo)
    await _call(
        mcp, "codekeeper_save_file",
        file_name=FILE_NAME, code="שורה 0\n", description=DESCRIPTION,
    )

    for index in range(3):
        out = await _call(
            mcp, "codekeeper_edit_file", file_name=FILE_NAME,
            old_string=f"שורה {index}", new_string=f"שורה {index + 1}",
        )
        assert out["ok"] is True, out

    doc = await _age_from_get_file(mcp)
    assert doc["version"] == 4, doc["version"]
    assert doc[DESCRIPTION_AGE_FIELD] == 3, (
        "העתקת התיאור לגרסה חדשה איפסה את הגיל — כלומר השדה מדווח 'עדכני' "
        f"בדיוק על המקרה שהוא נועד לחשוף: {doc}"
    )
    assert doc["description"] == DESCRIPTION, "התיאור עצמו זז"


async def test_append_ages_the_description_exactly_like_an_edit(wired_mongo):
    """‏``codekeeper_append_file`` הוא מסלול שני לאותה העתקה.

    שני הכלים עוברים ב-``_resave_edited``, אבל מה שמכריע את החותמת הוא
    מסלול השמירה ולא הכלי — ולכן הכיסוי חייב להראות ששניהם מגיעים לאותו
    מקום, ולא רק זה שנבדק קודם.
    """
    _fresh_collection(wired_mongo)
    mcp = _build_mcp(wired_mongo)
    await _call(
        mcp, "codekeeper_save_file",
        file_name=FILE_NAME, code="# כותרת\n", description=DESCRIPTION,
    )

    await _call(mcp, "codekeeper_append_file", file_name=FILE_NAME, content="עוד שורה\n")
    await _call(mcp, "codekeeper_append_file", file_name=FILE_NAME, content="ועוד אחת\n")

    doc = await _age_from_get_file(mcp)
    assert (doc["version"], doc[DESCRIPTION_AGE_FIELD]) == (3, 2), doc


async def test_updating_the_description_resets_the_age_without_moving_the_version(
    wired_mongo,
):
    """התיקון מאפס את הסימן — ולא יוצר גרסה.

    שני האסרשנים יחד הם הנקודה: כלי שהיה מאפס את הגיל על ידי יצירת גרסה
    חדשה היה "מצליח" בבדיקה הראשונה ושובר את ההבטחה המרכזית של
    ``codekeeper_update_file_description``.
    """
    _fresh_collection(wired_mongo)
    mcp = _build_mcp(wired_mongo)
    await _call(
        mcp, "codekeeper_save_file",
        file_name=FILE_NAME, code="שורה 0\n", description=DESCRIPTION,
    )
    for index in range(3):
        await _call(
            mcp, "codekeeper_edit_file", file_name=FILE_NAME,
            old_string=f"שורה {index}", new_string=f"שורה {index + 1}",
        )
    assert (await _age_from_get_file(mcp))[DESCRIPTION_AGE_FIELD] == 3

    out = await _call(
        mcp, "codekeeper_update_file_description",
        file_name=FILE_NAME, description="האימות היריב הושלם",
    )
    assert out["ok"] is True and out["version_created"] is False, out
    assert out["unchanged"] is False, out

    doc = await _age_from_get_file(mcp)
    assert doc[DESCRIPTION_AGE_FIELD] == 0, doc
    assert doc["version"] == 4, "הכלי יצר גרסה, בניגוד למה שהוא מבטיח"


async def test_sending_the_same_description_marks_it_checked_and_says_so(wired_mongo):
    """שליחת אותו טקסט היא אישור שהתיאור נבדק — ומתועדת ככזו.

    **זה הפוך מהכלל של גרסה חדשה, וזו הכרעה ולא חוסר עקביות.** עריכה
    שמעתיקה תיאור אינה אומרת דבר על התוכן; קריאה מפורשת לכלי אומרת
    שמישהו השווה ביניהם. ``unchanged`` הוא מה שמונע מהאיפוס להיראות כמו
    שינוי שלא היה: הוא אומר "רק החותמת זזה".
    """
    _fresh_collection(wired_mongo)
    mcp = _build_mcp(wired_mongo)
    await _call(
        mcp, "codekeeper_save_file",
        file_name=FILE_NAME, code="שורה 0\n", description=DESCRIPTION,
    )
    await _call(
        mcp, "codekeeper_edit_file", file_name=FILE_NAME,
        old_string="שורה 0", new_string="שורה 1",
    )
    assert (await _age_from_get_file(mcp))[DESCRIPTION_AGE_FIELD] == 1

    out = await _call(
        mcp, "codekeeper_update_file_description",
        file_name=FILE_NAME, description=DESCRIPTION,
    )
    assert out["unchanged"] is True, out
    assert out["description"] == out["previous_description"] == DESCRIPTION

    assert (await _age_from_get_file(mcp))[DESCRIPTION_AGE_FIELD] == 0


async def test_clearing_the_description_removes_the_stamp_instead_of_zeroing_it(
    wired_mongo,
):
    """תיאור ריק מסיר את החותמת מהמסמך — ולא משאיר גיל 0 על כלום.

    האסרשן על המסמך עצמו אינו מיותר לצד זה על התשובה: חותמת שנשארה
    במסמך הייתה חוזרת לחיים ברגע שמישהו יכתוב תיאור חדש בעדכון שעובר
    בהשוואה לקודם, ומייצרת גיל שנמדד מאירוע שכבר לא רלוונטי.
    """
    collection = _fresh_collection(wired_mongo)
    mcp = _build_mcp(wired_mongo)
    await _call(
        mcp, "codekeeper_save_file",
        file_name=FILE_NAME, code="שורה 0\n", description=DESCRIPTION,
    )

    out = await _call(
        mcp, "codekeeper_update_file_description", file_name=FILE_NAME, description="",
    )
    assert out["ok"] is True, out

    stored = collection.find_one({"user_id": USER_ID, "file_name": FILE_NAME})
    assert DESCRIPTION_SET_AT_VERSION_FIELD not in stored, (
        f"החותמת שרדה תיאור שנוקה: {stored.get(DESCRIPTION_SET_AT_VERSION_FIELD)}"
    )
    assert DESCRIPTION_AGE_FIELD not in (await _age_from_get_file(mcp))


async def test_a_description_that_looks_like_a_field_path_is_stored_as_text(wired_mongo):
    """‏``"$code"`` כתיאור נשמר כטקסט, ולא כתוכן הקובץ.

    **זה נבדק בהתנהגות ולא רק בצורת השאילתה, וזה לא כפילות.** מאז
    שהעדכון הוא pipeline, מחרוזת שמתחילה ב-``$`` היא **נתיב שדה** בעיני
    מונגו. בלי ``$literal``, התיאור שהמשתמש הקליד היה מוחלף בערך של
    השדה שהוא במקרה נקרא כמוהו — הקובץ המלא, בשדה שתקרת האורך שלו היא
    500 תווים. הטענה על צורת השאילתה חיה ב-
    ``test_mcp_update_file_description.py``; כאן נבדק מה **יצא**.
    """
    collection = _fresh_collection(wired_mongo)
    mcp = _build_mcp(wired_mongo)
    await _call(
        mcp, "codekeeper_save_file",
        file_name=FILE_NAME, code="תוכן אמיתי\n", description=DESCRIPTION,
    )

    out = await _call(
        mcp, "codekeeper_update_file_description",
        file_name=FILE_NAME, description="$code",
    )
    assert out["ok"] is True, out

    stored = collection.find_one({"user_id": USER_ID, "file_name": FILE_NAME})
    assert stored["description"] == "$code", (
        f"התיאור פוענח כנתיב שדה ולא כטקסט: {stored['description']!r}"
    )
    assert stored["code"] == "תוכן אמיתי\n", "התוכן נפגע"


async def test_a_file_without_a_description_does_not_carry_the_field_at_all(wired_mongo):
    """אין תיאור, אין מה לבדוק — ולכן גם לא ``null``.

    ``null`` הוא קריאה לפעולה ("יש כאן תיאור ואיני יודע בן כמה הוא"),
    והיעדר השדה הוא שקט. לשפוך את שניהם ל-``null`` היה מייצר התראה על
    כל קובץ שמעולם לא תואר.
    """
    _fresh_collection(wired_mongo)
    mcp = _build_mcp(wired_mongo)
    await _call(
        mcp, "codekeeper_save_file",
        file_name="ללא-תיאור.md", code="# כלום\n", description="",
    )

    doc = await _age_from_get_file(mcp, file_name="ללא-תיאור.md")
    assert DESCRIPTION_AGE_FIELD not in doc, doc


async def test_a_file_written_before_the_field_existed_reports_null_and_never_zero(
    wired_mongo,
):
    """קובץ ישן בלי חותמת — ``null``, וגם אחרי שעורכים אותו.

    האסרשן השני הוא העיקר. עריכה של קובץ כזה מעתיקה תיאור שאיננו יודעים
    מתי נכתב, ומימוש שהיה "משלים" חותמת בגרסה החדשה היה הופך אי-ידיעה
    לטענה — והטענה הגרועה ביותר האפשרית, שהתיאור נכתב עכשיו.
    """
    collection = _fresh_collection(wired_mongo)
    stamp = datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)
    for version in (1, 2, 3):
        collection.insert_one({
            "user_id": USER_ID, "file_name": FILE_NAME, "code": f"# גרסה {version}\n",
            "programming_language": "markdown", "description": DESCRIPTION,
            "tags": [], "version": version, "is_active": True,
            "created_at": stamp, "updated_at": stamp,
        })
    mcp = _build_mcp(wired_mongo)

    assert (await _age_from_get_file(mcp))[DESCRIPTION_AGE_FIELD] is None

    await _call(
        mcp, "codekeeper_edit_file", file_name=FILE_NAME,
        old_string="גרסה 3", new_string="גרסה 3 ערוכה",
    )
    doc = await _age_from_get_file(mcp)
    assert doc["version"] == 4
    assert doc[DESCRIPTION_AGE_FIELD] is None, (
        f"אי-ידיעה הפכה לטענה אחרי עריכה: {doc[DESCRIPTION_AGE_FIELD]}"
    )


# --------------------------------------------------------------------------
# השדה מגיע גם לרשימות ולחיפוש — שני המסלולים שבהם הוא הכי נחוץ
# --------------------------------------------------------------------------


async def test_list_files_and_search_carry_the_age_too(wired_mongo):
    """**בלי זה השדה היה חסר דווקא במסלול שהוא נועד לו.**

    הרעיון הוא לזהות תיאור מיושן *בלי לקרוא את כל הקובץ*, כלומר מתוך
    רשימה. ההיטלות של שני המסלולים האלה מונות שדות מפורשות, ו-``version``
    לא היה בהן — כלומר הגיל היה מחושב מ-``None`` וחוזר ``null`` בכל שורה.
    זה היה נראה כמו פיצ'ר שעובד.
    """
    # אינדקס הטקסט נוצר בפרודקשן על ידי ``DatabaseManager`` בעליית
    # התהליך, ומסד הבדיקה נוצר ריק. בלעדיו ``$text`` זורק,
    # ‏``search_code`` בולע ומחזיר ``[]`` — כלומר הבדיקה הייתה נכשלת על
    # "אין תוצאות" ומסתירה את השאלה האמיתית, מה יש **בתוך** תוצאה.
    collection = _fresh_collection(wired_mongo)
    collection.create_index(
        [("file_name", "text"), ("description", "text"),
         ("tags", "text"), ("code", "text")],
        name="search_text_idx",
    )
    mcp = _build_mcp(wired_mongo)
    await _call(
        mcp, "codekeeper_save_file",
        file_name=FILE_NAME, code="handoff שורה 0\n", description=DESCRIPTION,
    )
    for index in range(2):
        await _call(
            mcp, "codekeeper_edit_file", file_name=FILE_NAME,
            old_string=f"שורה {index}", new_string=f"שורה {index + 1}",
        )

    listed = await _call(mcp, "codekeeper_list_files")
    row = next(f for f in listed["files"] if f["file_name"] == FILE_NAME)
    assert row[DESCRIPTION_AGE_FIELD] == 2, row

    found = await _call(mcp, "codekeeper_search_code", query="handoff")
    hit = next(r for r in found["results"] if r["file_name"] == FILE_NAME)
    assert hit[DESCRIPTION_AGE_FIELD] == 2, hit


async def test_the_raw_stamp_is_not_part_of_the_tool_output(wired_mongo):
    """החותמת הגולמית היא פרט אחסון, לא ממשק.

    שני שדות שאומרים את אותו דבר מכריחים סוכן להכריע ביניהם, והוא יכריע
    לפעמים לרעה. הבדיקה נוגעת בשלושת המסלולים כי ``_clean`` משותף להם
    ושינוי בו נופל בכולם יחד — וזו בדיוק הסיבה שהוא המקום הנכון.
    """
    _fresh_collection(wired_mongo)
    mcp = _build_mcp(wired_mongo)
    await _call(
        mcp, "codekeeper_save_file",
        file_name=FILE_NAME, code="handoff\n", description=DESCRIPTION,
    )

    listed = await _call(mcp, "codekeeper_list_files")
    found = await _call(mcp, "codekeeper_search_code", query="handoff")
    rows = listed["files"] + found["results"] + [await _age_from_get_file(mcp)]
    for row in rows:
        assert DESCRIPTION_SET_AT_VERSION_FIELD not in row, row


# --------------------------------------------------------------------------
# הכלל חל גם על מסלולי הכתיבה של הוובאפ
# --------------------------------------------------------------------------


def test_editing_in_the_webapp_with_a_new_description_resets_the_age(wired_mongo):
    """הראוט שהדפדפן מפעיל — ולא ה-MCP — כותב את אותה חותמת.

    **זה לא כיסוי כפול.** עריכה בוובאפ אינה עוברת ב-``save_code_snippet``
    אלא כותבת ``insert_one`` משלה, ולכן היא מסלול כתיבה **נפרד** שיכול
    להישבר לבד. בלי הבדיקה הזו, עריכת תיאור מהדפדפן הייתה יכולה להשאיר
    חותמת ישנה, והשדה היה מדווח "ישן" על תיאור שנכתב לפני רגע.
    """
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    stamp = datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)
    for version in (1, 2):
        db.code_snippets.insert_one({
            "user_id": USER_ID, "file_name": "amir.md", "code": f"# גרסה {version}\n",
            "programming_language": "markdown", "description": DESCRIPTION,
            "tags": [], "version": version, "is_active": True,
            "created_at": stamp, "updated_at": stamp,
            DESCRIPTION_SET_AT_VERSION_FIELD: 1,
        })

    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}
    latest = db.code_snippets.find_one({"file_name": "amir.md", "version": 2})

    resp = client.post(f"/edit/{latest['_id']}", data={
        "file_name": "amir.md",
        "code": "# גרסה 3\n",
        "description": "תיאור חדש לגמרי",
        "language": "markdown",
    }, follow_redirects=False)
    assert resp.status_code in (200, 302), resp.get_data(as_text=True)[:400]

    saved = db.code_snippets.find_one({"file_name": "amir.md", "version": 3})
    assert saved is not None, "הראוט לא כתב גרסה חדשה"
    assert saved.get(DESCRIPTION_SET_AT_VERSION_FIELD) == 3, (
        f"תיאור חדש בדפדפן לא איפס את החותמת: {saved.get(DESCRIPTION_SET_AT_VERSION_FIELD)}"
    )


def test_saving_a_shared_document_stamps_it_like_every_other_write(wired_mongo):
    """המסלול השישי — ``webapp/collections_api.py``.

    **הוא נמצא רק כשנכתב הטסט השומר שמתחת**, אחרי שמיפוי ידני של הקוד
    מצא חמישה. לכן הוא מקבל בדיקה התנהגותית משלו ולא רק כיסוי מבני:
    שומר שבודק שהקוד **מזכיר** את הכלל אינו יכול לתפוס מימוש שקורא לו
    ומשליך את התוצאה, וזו בדיוק הצורה שמוטציה מייצרת.

    שני הכיוונים בקריאה אחת: שמירה ראשונה קובעת חותמת, ושמירה שנייה עם
    אותו תיאור ותוכן אחר משאירה אותה במקומה.
    """
    from webapp.collections_api import _save_shared_document_to_user

    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    shared = {"file_name": "shared.md", "content": "# ראשון\n",
              "language": "markdown", "description": DESCRIPTION}

    first = _save_shared_document_to_user(db, user_id=USER_ID, doc=shared)
    assert first["ok"] is True, first
    stored = db.code_snippets.find_one({"file_name": "shared.md", "version": 1})
    assert stored.get(DESCRIPTION_SET_AT_VERSION_FIELD) == 1, (
        f"מסלול השיתוף כתב גרסה בלי חותמת: {stored}"
    )

    second = _save_shared_document_to_user(
        db, user_id=USER_ID, doc={**shared, "content": "# שני\n"},
    )
    assert second["ok"] is True, second
    stored = db.code_snippets.find_one({"file_name": "shared.md", "version": 2})
    assert stored.get(DESCRIPTION_SET_AT_VERSION_FIELD) == 1, (
        f"שמירה שנייה עם אותו תיאור איפסה את הגיל: {stored}"
    )


def test_editing_in_the_webapp_without_touching_the_description_keeps_the_stamp(
    wired_mongo,
):
    """ואותו ראוט, כשהתיאור **לא** זז — החותמת הישנה שורדת.

    שני הכיוונים נבדקים כי הם נשברים בנפרד: מימוש שכותב תמיד את הגרסה
    החדשה עובר את הבדיקה שמעל ונופל כאן, ומימוש שאינו כותב כלום עושה
    את ההפך.
    """
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    stamp = datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)
    db.code_snippets.insert_one({
        "user_id": USER_ID, "file_name": "amir.md", "code": "# גרסה 1\n",
        "programming_language": "markdown", "description": DESCRIPTION,
        "tags": [], "version": 1, "is_active": True,
        "created_at": stamp, "updated_at": stamp,
        DESCRIPTION_SET_AT_VERSION_FIELD: 1,
    })

    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}
    latest = db.code_snippets.find_one({"file_name": "amir.md", "version": 1})

    resp = client.post(f"/edit/{latest['_id']}", data={
        "file_name": "amir.md",
        "code": "# גרסה 2\n",
        "description": DESCRIPTION,
        "language": "markdown",
    }, follow_redirects=False)
    assert resp.status_code in (200, 302), resp.get_data(as_text=True)[:400]

    saved = db.code_snippets.find_one({"file_name": "amir.md", "version": 2})
    assert saved is not None, "הראוט לא כתב גרסה חדשה"
    assert saved.get(DESCRIPTION_SET_AT_VERSION_FIELD) == 1, (
        f"עריכה בדפדפן איפסה את הגיל: {saved.get(DESCRIPTION_SET_AT_VERSION_FIELD)}"
    )


async def test_an_old_file_reports_a_real_age_once_the_migration_has_run(wired_mongo):
    """הקצה השני של המיגרציה: מה שסוכן רואה אחריה.

    ההיגיון של המיגרציה נבדק ב-
    ``tests/test_migrate_description_set_at_version.py``, על שרשרות
    בנויות ביד. מה שנבדק **כאן** הוא שהחותמת שהיא כותבת היא אותה חותמת
    שמסלול הקריאה מחפש: מיגרציה שכתבה שם מעט אחר, או שדה שאינו נמשך
    בהיטלה, היו עוברות את כל הקובץ ההוא בירוק ומשאירות ``null`` בכלי.
    """
    import importlib.util

    collection = _fresh_collection(wired_mongo)
    for version in (1, 2, 3, 4):
        collection.insert_one({
            "user_id": USER_ID, "file_name": FILE_NAME,
            "code": f"# גרסה {version}\n", "programming_language": "markdown",
            "description": DESCRIPTION, "tags": [], "version": version,
            "is_active": True,
        })
    mcp = _build_mcp(wired_mongo)
    assert (await _age_from_get_file(mcp))[DESCRIPTION_AGE_FIELD] is None

    script = REPO_ROOT / "scripts" / "migrate_description_set_at_version.py"
    spec = importlib.util.spec_from_file_location("migrate_desc_stamp", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.migrate(collection)

    assert (await _age_from_get_file(mcp))[DESCRIPTION_AGE_FIELD] == 3


# --------------------------------------------------------------------------
# שומר: אין מסלול שכותב גרסה בלי לקבוע חותמת
# --------------------------------------------------------------------------


#: הקבצים שמותר להם לכתוב מסמך גרסה ל-``code_snippets``, ומה כל אחד חייב
#: להזכיר כדי שהכתיבה תיחשב מכוסה.
_VERSION_WRITERS = {
    "database/repository.py": "description_stamp_for_new_version",
    "webapp/app.py": "_attach_description_stamp",
    "webapp/collections_api.py": "description_stamp_for_new_version",
}


def _functions_inserting_versions(tree: ast.AST):
    """שמות הפונקציות שמריצות ``insert_one`` על אוסף הקבצים, והגוף שלהן.

    הזיהוי הוא על **צורת הקריאה** ולא על שם הפונקציה: ``x.code_snippets
    .insert_one(...)`` בוובאפ, ו-``...collection.insert_one(...)`` בשכבת
    ה-repository. רשימת שמות מאושרים הייתה מתיישנת ברגע שנוסף מסלול —
    כלומר בדיוק ברגע שהיא נחוצה.
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            func = inner.func
            if not isinstance(func, ast.Attribute) or func.attr != "insert_one":
                continue
            owner = func.value
            if not isinstance(owner, ast.Attribute):
                continue
            if owner.attr not in ("code_snippets", "collection"):
                continue
            yield node
            break


def test_every_path_that_writes_a_version_also_sets_the_stamp():
    """שומר מבני: מסלול כתיבה חדש לא יכול להישכח בשקט.

    **זו הרגרסיה שכבר קרתה פעמיים בריפו הזה**, על ``created_at`` ועל
    ``updated_at``: התיקון נעשה בשכבת ה-DB, והוובאפ — שמחזיק מימוש
    מקביל — המשיך כמנהגו. מיפוי ידני לפני המימוש הזה מצא חמישה מסלולי
    ``insert_one``, ומסלול שישי (``webapp/collections_api.py``) נמצא רק
    כשהטסט הזה נכתב. זה מה שהוא בא למנוע.

    הבדיקה היא על **הכלה בגוף הפונקציה** ולא על סדר או מיקום, כי מה
    שנאכף הוא שהמסלול מחובר לכלל המשותף — לא איך הוא נראה. שינוי שם של
    העוזר מפיל אותה, וזה בסדר: שם הוא בדיוק מה שהיא מצביעה עליו.
    """
    offenders = []
    for relative_path, required in _VERSION_WRITERS.items():
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for function in _functions_inserting_versions(tree):
            body = ast.get_source_segment(source, function) or ""
            if required not in body:
                offenders.append(f"{relative_path}::{function.name}")

    assert offenders == [], (
        "מסלול שכותב גרסה חדשה ואינו קובע את חותמת התיאור — כלומר עריכה "
        "שתאפס את הגיל בשקט, או תשאיר חותמת של קובץ אחר: " + ", ".join(offenders)
    )


def test_no_file_outside_the_known_writers_inserts_a_version():
    """ואף קובץ אחר בכלל אינו כותב ל-``code_snippets``.

    הטסט שמעליו מוודא שהמסלולים הידועים מחוברים; זה מוודא שהרשימה
    **שלמה**. בלעדיו, מסלול שביעי בקובץ חדש היה עובר בלי להיתפס, כי
    הקובץ שלו כלל לא נסרק.

    הסריקה מדלגת על ``tests/`` ועל ``node_modules`` — טסט שמזריק נתונים
    הוא לא מסלול ייצור — ועל ``large_files``, שאינו ממוספר בגרסאות כלל.
    """
    allowed = set(_VERSION_WRITERS)
    offenders = []
    for path in REPO_ROOT.rglob("*.py"):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in allowed:
            continue
        if relative.startswith(("tests/", "node_modules/", "scripts/")):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "code_snippets" not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "insert_one":
                continue
            owner = func.value
            if isinstance(owner, ast.Attribute) and owner.attr == "code_snippets":
                offenders.append(relative)
                break

    assert offenders == [], (
        "קובץ שכותב מסמך גרסה ואינו ברשימת המסלולים המכוסים — הוסיפו אותו "
        f"ל-_VERSION_WRITERS יחד עם חיבור לכלל החותמת: {sorted(set(offenders))}"
    )


# --------------------------------------------------------------------------
# הכלל הטהור — המקרים שקשה להעמיד במסד
# --------------------------------------------------------------------------


def test_the_rule_inherits_the_stamp_only_when_the_text_is_identical():
    """ארבעת הענפים של הכלל, בלי מסד.

    הם נבדקים גם בהתנהגות שמעל; כאן הם נבדקים **ישירות**, כי בדיקה
    התנהגותית שנופלת אינה אומרת באיזה ענף — וארבעה ענפים שמתנהגים אותו
    דבר ברוב המקרים הם בדיוק המקום שבו כיסוי נראה רחב יותר ממה שהוא.
    """
    # מסמך **מלא**, עם ``version``, כי כך נראה כל מסמך שמסלולי הכתיבה
    # מעבירים לכאן בפועל: שבעתם שולפים ב-``find_one`` בלי היטלה. פיקסצ'ר
    # שמשמיט את השדה בודק צורה שאף צרכן אינו מייצר.
    previous = {"description": "ישן", "version": 8, DESCRIPTION_SET_AT_VERSION_FIELD: 2}

    assert description_stamp_for_new_version(None, "חדש", 1) == 1
    assert description_stamp_for_new_version(previous, "ישן", 9) == 2
    assert description_stamp_for_new_version(previous, "אחר", 9) == 9
    assert description_stamp_for_new_version(previous, "", 9) is None
    assert description_stamp_for_new_version(
        {"description": "ישן", "version": 8}, "ישן", 9
    ) is None
    assert description_stamp_for_new_version(previous, 42, 9) is None


def test_a_stamp_newer_than_the_document_it_sits_on_is_not_inherited():
    """**חותמת נבדקת מול המסמך שהיא יושבת עליו, לא רק מול הגרסה החדשה.**

    מסמך גרסה 5 שנושא חותמת 6 הוא נתון פגום — אין מסלול קוד שמייצר
    אותו. אבל בדיקה מול הגרסה החדשה בלבד מחמיצה אותו בדיוק ברגע הגרוע:
    בשמירה הבאה הגרסה החדשה היא 6, ה-6 עובר את הסף ויורש, והמסמך החדש
    יוצא עם חותמת ששווה למספר שלו — כלומר **גיל 0**. זה הערך היחיד
    שאסור להמציא, ואי-ידיעה הייתה מתחפשת ל"התיאור נכתב עכשיו".

    ``version`` חסר במסמך הקודם נופל לאותו ענף מאותה סיבה: בלי לדעת על
    איזו גרסה החותמת יושבת אין מול מה לאמת אותה.
    """
    corrupt = {"description": "ד", "version": 5, DESCRIPTION_SET_AT_VERSION_FIELD: 6}
    assert description_stamp_for_new_version(corrupt, "ד", 6) is None, (
        "חותמת מהעתיד ירשה, והגרסה החדשה קיבלה גיל 0 על תיאור שאיננו "
        "יודעים מתי נכתב"
    )

    no_version = {"description": "ד", DESCRIPTION_SET_AT_VERSION_FIELD: 3}
    assert description_stamp_for_new_version(no_version, "ד", 9) is None

    # ותקין נשאר תקין, כולל הגבול: חותמת ששווה לגרסה של המסמך שלה.
    at_boundary = {"description": "ד", "version": 5, DESCRIPTION_SET_AT_VERSION_FIELD: 5}
    assert description_stamp_for_new_version(at_boundary, "ד", 6) == 5


def test_a_stamp_from_the_future_is_treated_as_unknown_not_as_a_negative_age():
    """חותמת גבוהה ממספר הגרסה היא נתון פגום, לא ידיעה.

    גיל שלילי היה נקרא כמו "תיאור מהעתיד" ומתפרש בכל צרכן אחרת. אין
    מסלול קוד שמייצר את המצב הזה, וזו בדיוק הסיבה לבדוק אותו כאן: אם
    הוא בכל זאת יגיע מהמסד, זו התשובה שאנחנו רוצים.
    """
    from file_description import description_age_versions

    assert description_age_versions(
        {"version": 3, DESCRIPTION_SET_AT_VERSION_FIELD: 7}
    ) is None
    assert description_age_versions(
        {"version": 3, DESCRIPTION_SET_AT_VERSION_FIELD: True}
    ) is None
    assert description_age_versions({"version": 3}) is None


def test_a_document_with_no_version_number_carries_no_age_field_at_all():
    """קובץ גדול (``large_files``) נשמר בדריסה ואין לו ``version``.

    שם ``null`` היה שולח את הסוכן לבדוק משהו שאין בו מה לבדוק: לא חסרה
    לנו ידיעה, פשוט אין מושג כזה. ``{}`` — כלומר שדה שלא מופיע — הוא
    התשובה, ולכן ההבחנה חיה ב-``description_age_field`` ולא בקוראים.
    """
    from file_description import description_age_field

    assert description_age_field({"description": "יש תיאור"}) == {}
    assert description_age_field({"description": "", "version": 4}) == {}
    assert description_age_field({"description": "יש", "version": 4}) == {
        DESCRIPTION_AGE_FIELD: None
    }


def test_a_non_finite_version_number_does_not_crash_the_read_path():
    """‏``version: Infinity`` מדולג ולא מפיל את כל הרשימה.

    ‏BSON יודע לאחסן ``double`` אינסופי, ו-``int(float("inf"))`` זורק
    ``OverflowError`` — שאינו ``ValueError`` ואינו ``TypeError``.
    **הפער נראה מכוסה דווקא מפני ש-``NaN`` כן עובר בשלום** (הוא
    ``ValueError``), ולכן בדיקה על ``NaN`` לבדה הייתה מאשרת מימוש שבור.

    הנזק אינו מקומי: ``normalized_version`` רץ ב-``_clean``, כלומר על
    **כל** מסמך קובץ בכל מסלול קריאה. מסמך פגום יחיד היה מפיל את
    ``codekeeper_list_files`` כולו, לא רק את עצמו.
    """
    from file_description import description_age_field, normalized_version

    for value in (float("inf"), float("-inf"), float("nan")):
        assert normalized_version(value) is None, value

    assert description_age_field({"description": "יש", "version": float("inf")}) == {}
    # ומסמך תקין לצידו עדיין מקבל תשובה — הדילוג הוא על הפגום בלבד.
    assert description_age_field(
        {"description": "יש", "version": 4, DESCRIPTION_SET_AT_VERSION_FIELD: 1}
    ) == {DESCRIPTION_AGE_FIELD: 3}
