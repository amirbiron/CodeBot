"""``codekeeper_update_file_description`` — עדכון תיאור בלי גרסה חדשה.

**הבדיקות עוברות דרך ``mcp.call_tool``**, כלומר המסלול שלקוח MCP אמיתי
מפעיל: הסכימה, שער ההרשאות, העברת הזהות המאומתת, והעטיפה שמוציאה את גוף
הכלי מה-event loop. קריאה ישירה ל-``handlers.update_file_description``
הייתה מדלגת על כל ארבעתם — ראו כלל 1 ב-``claude-md-snippets/testing.md``:
הבדיקה עוברת דרך אותו ממשק כמו הצרכן.

**ומול מונגו אמיתי**, כי ההבטחה המרכזית של הכלי אינה על צורת התשובה אלא
על מה שקרה במסד: שהתיאור זז ושהתוכן ומספר הגרסה **לא**. דמה שמחזירה
מילון לא יכולה להפריך את זה — היא תחזיר בדיוק את מה שנכתב בה. לכן הקובץ
משתמש בפיקסצ'ר ``wired_mongo``, ובלי ``NOTE_FONTS_TEST_MONGO_URI`` הוא
מדולג (אותו הסדר כמו ``tests/test_snippet_hebrew_offsets_mongo.py``).

**מה כן מוחלף בדמה, ומה לא.** ה-``DatabaseManager`` בלבד, כי הוא מתחבר
לפי הקונפיג הגלובלי ואי אפשר להפנות אותו למסד הבדיקה. הדמה מחזיקה את
ה-collection האמיתי ומאצילה ל-``Repository`` **האמיתי** — כלומר מסלול
הכתיבה שרץ כאן הוא מסלול הייצור, לא חיקוי שלו. שאר השרשרת —
``ProductionBackend``, ``handlers``, ``build_mcp`` — אמיתית כולה.

אין כאן קלט או פלט לדיסק; כל מה שנכתב הולך למסד הזמני שהפיקסצ'ר יוצר
ומוחק, ו-``tmp_path`` אינו נדרש.

הרצה מקומית::

    NOTE_FONTS_TEST_MONGO_URI='mongodb://127.0.0.1:27017' \\
        pytest tests/test_mcp_update_file_description.py -v
"""

from __future__ import annotations

import contextlib
import json
import types
from datetime import datetime, timezone

import pytest

pytest.importorskip("mcp")

from mcp.server.auth.middleware.auth_context import (  # noqa: E402
    auth_context_var,
)
from mcp.server.auth.provider import AccessToken  # noqa: E402
from mcp.server.lowlevel.server import request_ctx  # noqa: E402
from mcp.shared.context import RequestContext  # noqa: E402

USER_ID = 4242
FILE_NAME = "code-review-mcp-to-thread-PR3390.md"
OLD_DESCRIPTION = "מעבר האימות היריב טרם הושלם"
NEW_DESCRIPTION = "האימות היריב הושלם"
BODY_V1 = "# גרסה ראשונה\n"
BODY_V2 = "# גרסה שנייה — האימות היריב הושלם\n"


# --------------------------------------------------------------------------
# חיווט
# --------------------------------------------------------------------------


class _ManagerOnCollection:
    """``DatabaseManager`` מינימלי שמצביע על ה-collection של מסד הבדיקה.

    **הדמה מאצילה ל-``Repository`` האמיתי ואינה מחקה אותו.** זה ההבדל בין
    בדיקה שמאמתת את מסלול הכתיבה לבין בדיקה שמאמתת את עצמה: אילו המתודה
    כאן הייתה כותבת ``update_one`` משלה, כל באג ב-``update_file_metadata_in``
    היה עובר מתחתיה.

    היא קיימת רק מפני ש-``DatabaseManager`` האמיתי בונה את החיבור שלו
    מהקונפיג הגלובלי ואין דרך להפנות אותו למסד הזמני של הפיקסצ'ר.
    """

    def __init__(self, collection):
        self.collection = collection

    def update_file_metadata(self, user_id, **kwargs):
        from database.repository import Repository

        return Repository(self).update_file_metadata(user_id, **kwargs)


def _seed(wired_mongo, *, versions=1, description=OLD_DESCRIPTION):
    """קובץ עם ``versions`` גרסאות, כולן נושאות את אותו תיאור ישן."""
    collection = wired_mongo.get_db().code_snippets
    collection.delete_many({})
    stamp = datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)
    bodies = [BODY_V1, BODY_V2]
    for v in range(1, versions + 1):
        collection.insert_one({
            "user_id": USER_ID,
            "file_name": FILE_NAME,
            "code": bodies[(v - 1) % len(bodies)],
            "programming_language": "markdown",
            "description": description,
            "tags": ["review"],
            "version": v,
            "is_active": True,
            "created_at": stamp,
            "updated_at": stamp,
        })
    return collection


def _build_mcp(collection):
    from mcp_server.backend import ProductionBackend
    from mcp_server.server import build_mcp

    backend = ProductionBackend(db_manager=_ManagerOnCollection(collection))
    return build_mcp(backend)


@contextlib.contextmanager
def as_agent(scopes):
    """הקשר בקשה + אימות, בדיוק כפי ש-``FastMCP.call_tool`` רואה אותו.

    **מנהל הקשר ולא פיקסצ'ר, וזה לא סגנון.** ``ContextVar.reset`` דורש
    שה-token יוחזר ב**אותו** ``Context`` שבו נוצר. פיקסצ'ר סינכרוני
    שעושה ``set`` לפני ה-``yield`` ו-``reset`` אחריו חוצה את הגבול של
    הטסט האסינכרוני, ו-pytest-asyncio מריץ את גוף הטסט בהקשר משלו —
    ``ValueError: was created in a different Context``. ``with`` בתוך
    הטסט שומר את שני הצדדים באותו הקשר.

    ``scopes`` הוא פרמטר כדי שבדיקת ההרשאה תיכנס עם טוקן קריאה-בלבד
    דרך אותו מנגנון בדיוק, ולא בעקיפה שלו.
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


async def _call(mcp, *, scopes=("read", "write"), **arguments):
    """קורא לכלי דרך ``mcp.call_tool``, בתוך הקשר מאומת, ומפענח את התשובה.

    ``scopes`` נמצא כאן ולא בפיקסצ'ר כדי שההקשר ייפתח וייסגר **בתוך**
    הקורוטינה של הטסט — ראו :func:`as_agent`.

    **הפענוח אינו נוחות — הוא חלק ממה שנבדק.** הכלי מוצהר כמחזיר
    ``dict``, ולכן ``FuncMetadata.output_schema`` שלו הוא ``None``
    (נמדד, mcp 1.28.1) ו-``call_tool`` מחזיר **רק** תוכן לא-מובנה: בלוק
    טקסט אחד שנושא את המילון כ-JSON. זה מה שהלקוח מקבל בפועל, ולכן זה
    מה שהבדיקות טוענות עליו. פירוק ל-``(content, structured)`` היה עובד
    רק אילו הוגדרה סכימת פלט, והיה נשבר כאן בלי שום קשר להתנהגות הכלי.
    """
    with as_agent(scopes):
        content = await mcp.call_tool("codekeeper_update_file_description", arguments)
    assert len(content) == 1, content
    return json.loads(content[0].text)


# --------------------------------------------------------------------------
# ההבטחה: התיאור זז, התוכן ומספר הגרסה לא
# --------------------------------------------------------------------------


async def test_the_description_changes_while_content_and_version_stay_put(wired_mongo):
    """מה שהכלי מבטיח, נקרא בחזרה מהמסד ולא מהתשובה שלו.

    **שלושה אסרשנים ולא אחד, כי שלושתם יכולים להישבר בנפרד:** התיאור
    יכול לא להשתנות (הכתיבה החטיאה), התוכן יכול להשתנות (מישהו החליף
    את המסלול ב-``save_file``), ומספר הגרסה יכול לקפוץ (נוצרה גרסה, מה
    שתיאור הכלי מבטיח במפורש שלא יקרה).

    וגם **מספר המסמכים** נבדק: גרסה חדשה היא מסמך חדש, ולכן ספירה שעלתה
    היא הראיה הישירה ביותר לכך שנוצרה גרסה — גם אם במקרה היא נשאה את
    אותו מספר.
    """
    collection = _seed(wired_mongo)
    mcp = _build_mcp(collection)

    result = await _call(mcp, file_name=FILE_NAME, description=NEW_DESCRIPTION)
    assert result["ok"] is True, result

    docs = list(collection.find({"user_id": USER_ID, "file_name": FILE_NAME}))
    assert len(docs) == 1, f"נוצר מסמך נוסף — כלומר גרסה: {[d['version'] for d in docs]}"
    assert docs[0]["description"] == NEW_DESCRIPTION
    assert docs[0]["code"] == BODY_V1, "התוכן זז"
    assert docs[0]["version"] == 1, "מספר הגרסה זז"


async def test_the_reply_reports_the_unchanged_version_and_the_lost_previous_value(wired_mongo):
    """התשובה נושאת את התיאור הקודם — **המקום היחיד שבו הוא עוד קיים**.

    זה לא נוחות: אין גרסה חדשה, ולכן הערך הקודם אינו נשמר בשום מקום
    ואינו ניתן לשחזור אחרי הקריאה הזו. ``version_created: False`` נאמר
    במפורש כדי שסוכן לא יסיק מהצלחה שנוצרה גרסה שאפשר לחזור אליה.
    """
    collection = _seed(wired_mongo)
    mcp = _build_mcp(collection)

    result = await _call(mcp, file_name=FILE_NAME, description=NEW_DESCRIPTION)

    assert result["previous_description"] == OLD_DESCRIPTION
    assert result["description"] == NEW_DESCRIPTION
    assert result["version"] == 1, "מספר הגרסה שדווח אינו זה שבמסד"
    assert result["version_created"] is False
    assert result["file_name"] == FILE_NAME


async def test_only_the_latest_version_is_updated_and_earlier_ones_keep_the_old_text(wired_mongo):
    """הסייג שתיאור הכלי מצהיר עליו — נבדק, ולא רק נכתב.

    **הערה שמבטיחה תכונה דורשת בדיקה לתכונה** (כלל 4 ב-
    ``claude-md-snippets/testing.md``). התיאור אומר "רק הגרסה האחרונה
    מתעדכנת, וקריאה של גרסה קודמת מחזירה את התיאור הישן"; בלי הבדיקה
    הזו זו הצהרת כוונה, ומימוש עם ``update_many`` היה עובר את כל שאר
    הקובץ בלי להיתפס.
    """
    collection = _seed(wired_mongo, versions=2)
    mcp = _build_mcp(collection)

    assert (await _call(
        mcp, file_name=FILE_NAME, description=NEW_DESCRIPTION
    ))["ok"] is True

    by_version = {
        d["version"]: d
        for d in collection.find({"user_id": USER_ID, "file_name": FILE_NAME})
    }
    assert by_version[2]["description"] == NEW_DESCRIPTION, "הגרסה האחרונה לא עודכנה"
    assert by_version[1]["description"] == OLD_DESCRIPTION, "גרסה קודמת נדרסה"
    assert by_version[1]["code"] == BODY_V1
    assert by_version[2]["code"] == BODY_V2


class _RecordingCollection:
    """collection שמקליט את הקריאה ומחזיר מסמך קבוע.

    היא מחליפה **רק** את מונגו, ולא שום שכבה מעליה: הקריאה עדיין נכנסת
    דרך ``mcp.call_tool`` ועוברת את השער, את ``handlers`` ואת
    ``update_file_metadata_in``. מה שנטען עליו הוא מה שהשכבה הזו שולחת
    למסד.
    """

    def __init__(self):
        self.calls = []

    def find_one_and_update(self, query, update, **kwargs):
        self.calls.append({"query": query, "update": update, **kwargs})
        return {"_id": "x", "file_name": FILE_NAME, "version": 7,
                "description": OLD_DESCRIPTION, "tags": []}


async def test_the_latest_version_is_chosen_by_an_explicit_sort_not_by_luck():
    """``sort=[("version", -1)]`` נשלח למונגו — **טענה על השאילתה**.

    **למה זה לא נבדק בהתנהגות, וזה הממצא המעניין כאן.** הרצתי את
    הבדיקה ההתנהגותית שמעל על מימוש **בלי** ה-``sort``, והיא עברה.
    הסיבה נמדדה מול MongoDB 7.0.14: כשקיים ``idx_snippets_latest_version``
    (``user_id, is_active, file_name, version DESC``) המתכנן סורק אותו,
    וה-``DESC`` מגיש את הגרסה הגבוהה ראשונה גם בלי שביקשנו מיון. על
    אותם נתונים בדיוק **בלי** האינדקס נבחרה גרסה 1 — כלומר השגויה.

    המשמעות: מימוש בלי ``sort`` הוא באג רדום שהאינדקס מסתיר, ובדיקה
    התנהגותית מול מסד עם אינדקסים **אינה מסוגלת** לתפוס אותו. זה כיסוי
    מדומה, ולכן הטענה כאן היא על מה שנשלח ולא על מה שחזר.

    ``projection`` נטען באותה נשימה: בלעדיו מונגו מחזירה את המסמך כולו,
    כולל ``code``, וזו משיכת קובץ שלם בשביל שדה טקסט אחד.
    """
    from mcp_server.backend import ProductionBackend
    from mcp_server.server import build_mcp

    collection = _RecordingCollection()
    mcp = build_mcp(ProductionBackend(db_manager=_ManagerOnCollection(collection)))

    await _call(mcp, file_name=FILE_NAME, description=NEW_DESCRIPTION)

    assert len(collection.calls) == 1, collection.calls
    call = collection.calls[0]
    assert call["sort"] == [("version", -1)], (
        "בלי מיון מפורש, המסמך הנבחר תלוי בכך שהמתכנן יבחר אינדקס "
        f"שמסתיים ב-version DESC: {call.get('sort')}"
    )
    assert call["query"] == {
        "user_id": USER_ID, "file_name": FILE_NAME, "is_active": True,
    }, call["query"]
    assert "code" not in (call["projection"] or {}), (
        f"הקובץ המלא נמשך בשביל עדכון תיאור: {call['projection']}"
    )
    assert set(call["update"]) == {"$set"}, call["update"]


# --------------------------------------------------------------------------
# סירובים
# --------------------------------------------------------------------------


async def test_a_file_that_does_not_exist_is_reported_as_not_found(wired_mongo):
    """שם שאינו קיים מוחזר כ-``not_found`` ואינו יוצר קובץ.

    האסרשן השני אינו מיותר: ``upsert=True`` הוא ברירת מחדל שקל להוסיף
    בטעות, ובלעדיו הבדיקה הייתה עוברת גם על מימוש שיוצר מסמך חדש ואז
    "מוצא" אותו.
    """
    collection = _seed(wired_mongo)
    mcp = _build_mcp(collection)

    result = await _call(mcp, file_name="אין-כזה-קובץ.md", description="כלשהו")

    assert result["ok"] is False
    assert result["error"] == "not_found", result
    assert collection.count_documents({"file_name": "אין-כזה-קובץ.md"}) == 0


async def test_a_read_only_token_is_refused_and_nothing_is_written(wired_mongo):
    """טוקן בלי ``write`` נדחה — **ושום דבר לא נכתב**.

    שני קצוות, ובכוונה. הראשון הוא שהקריאה נכשלת; השני, החשוב יותר, הוא
    שהמסד לא זז. בדיקה שטוענת רק על השגיאה הייתה עוברת גם על מימוש
    שכותב ואז מחזיר שגיאה — כלומר בדיוק הכשל שהשער נועד למנוע.

    ``ToolError`` ולא ``PermissionError``: ה-SDK עוטף חריגה מגוף כלי
    ומגיש אותה ללקוח כתוצאת שגיאה. זה מה שהצרכן רואה, ולכן זה מה
    שנטען כאן.
    """
    from mcp.server.fastmcp.exceptions import ToolError

    collection = _seed(wired_mongo)
    mcp = _build_mcp(collection)

    with pytest.raises(ToolError):
        await _call(
            mcp, scopes=["read"], file_name=FILE_NAME, description=NEW_DESCRIPTION
        )

    doc = collection.find_one({"user_id": USER_ID, "file_name": FILE_NAME})
    assert doc["description"] == OLD_DESCRIPTION, "נכתב למרות שההרשאה נדחתה"


async def test_an_over_long_description_is_refused_instead_of_truncated(wired_mongo):
    """תיאור ארוך מדי נדחה, ואינו נחתך בשקט.

    **זו ההבחנה בין שני הערוצים.** הראוט בוובאפ חותך, כי אדם רואה את
    התוצאה. סוכן אינו רואה אותה, וחיתוך שקט הוא טקסט שאבד בלי שיידע —
    לכן כאן זו שגיאה שנושאת את המגבלה, והמסד נשאר על הערך הישן.
    """
    from database.repository import FILE_DESCRIPTION_MAX_CHARS

    collection = _seed(wired_mongo)
    mcp = _build_mcp(collection)

    too_long = "א" * (FILE_DESCRIPTION_MAX_CHARS + 1)
    result = await _call(mcp, file_name=FILE_NAME, description=too_long)

    assert result["ok"] is False
    assert result["error"] == "description_too_long", result
    assert result["max"] == FILE_DESCRIPTION_MAX_CHARS
    doc = collection.find_one({"user_id": USER_ID, "file_name": FILE_NAME})
    assert doc["description"] == OLD_DESCRIPTION, "נכתב תיאור חתוך"


async def test_a_file_belonging_to_someone_else_is_not_reachable(wired_mongo):
    """הבעלות נאכפת בפילטר של הכתיבה עצמה.

    הזהות מגיעה מהטוקן המאומת ולעולם לא מארגומנט של הכלי, ולכן קובץ של
    משתמש אחר נראה בדיוק כמו קובץ שאינו קיים. הבדיקה מוודאת גם שהמסמך
    של האחר לא זז — ``not_found`` שחוזר **אחרי** כתיבה הוא עדיין דליפה.
    """
    collection = _seed(wired_mongo)
    collection.update_many({"file_name": FILE_NAME}, {"$set": {"user_id": USER_ID + 1}})
    mcp = _build_mcp(collection)

    result = await _call(mcp, file_name=FILE_NAME, description=NEW_DESCRIPTION)

    assert result["ok"] is False
    assert result["error"] == "not_found", result
    doc = collection.find_one({"file_name": FILE_NAME})
    assert doc["description"] == OLD_DESCRIPTION
    assert doc["user_id"] == USER_ID + 1


async def test_an_empty_description_clears_the_field(wired_mongo):
    """מחרוזת ריקה היא בקשה תקפה ולא "שדה חסר".

    זה מה שהסנטינל ``_UNSET`` ב-``update_file_metadata_in`` קיים בשבילו:
    ``""`` ו-``None`` היו מתפרשים כ"אל תיגע", ואז "נקה את התיאור" לא
    הייתה ניתנת לביטוי כלל.
    """
    collection = _seed(wired_mongo)
    mcp = _build_mcp(collection)

    result = await _call(mcp, file_name=FILE_NAME, description="   ")

    assert result["ok"] is True, result
    assert result["description"] == ""
    assert collection.find_one({"user_id": USER_ID})["description"] == ""


# --------------------------------------------------------------------------
# מטא-דאטה של הכלי
# --------------------------------------------------------------------------


async def test_the_tool_declares_itself_a_writer_so_it_takes_the_write_queue():
    """הסיווג ככותב נגזר מ-``readOnlyHint`` ולא מרשימת שמות.

    ``_declares_write`` בונה על האנוטציה הזו כדי לשלוח את הכלי
    ל-``_WRITE_POOL``. הבדיקה טוענת על **המקור** של הסיווג (השדה) ולא
    על התוצאה בלבד, כי זו הצורה שמונעת מהכלי הבא להיווסף בלי תור.

    ``destructiveHint`` הוא ``True`` כאן לא כזהירות אלא כעובדה: אין
    היסטוריה, ולכן התיאור הקודם אובד בכתיבה.
    """
    from mcp_server.server import _declares_write, build_mcp

    class _Fake:
        def __getattr__(self, _n):
            return lambda *a, **k: {}

    mcp = build_mcp(_Fake())
    tool = mcp._tool_manager.get_tool("codekeeper_update_file_description")

    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.idempotentHint is True
    assert _declares_write(tool.annotations) is True


async def test_the_tool_description_says_what_it_does_not_do():
    """התיאור אומר במפורש את שלושת הדברים שאינם קורים.

    סוכן שקורא רק "מעדכן תיאור" יניח שנוצרה גרסה ושאפשר לחזור אחורה.
    שלוש ההצהרות האלה הן מה שמונע את ההנחה, ולכן הן נאכפות ולא
    מסתמכות על כך שאיש לא ימחק אותן בעריכה הבאה.
    """
    from mcp_server.server import build_mcp

    class _Fake:
        def __getattr__(self, _n):
            return lambda *a, **k: {}

    description = build_mcp(_Fake())._tool_manager.get_tool(
        "codekeeper_update_file_description"
    ).description

    assert "NO NEW VERSION IS CREATED" in description
    assert "NOT kept in history" in description
    assert "Only the latest version is updated" in description


async def test_save_file_points_at_this_tool_for_an_existing_file():
    """``codekeeper_save_file`` מפנה לכאן, ובשני המקומות שסוכן מגיע אליהם.

    תיאור הכלי הוא מה שסוכן קורא **לפני** שהוא בוחר, והודעת
    ``file_exists`` היא מה שהוא מקבל **אחרי** שבחר לא נכון. הפניה רק
    באחד מהם משאירה את המסלול שגרם לאישו הזה מלכתחילה: סוכן שרצה לרענן
    תיאור, ניסה ``save_file``, ונדחה בלי לדעת לאן ללכת.
    """
    from mcp_server.server import build_mcp

    class _Fake:
        def __getattr__(self, _n):
            return lambda *a, **k: {}

    save_desc = build_mcp(_Fake())._tool_manager.get_tool(
        "codekeeper_save_file"
    ).description
    assert "codekeeper_update_file_description" in save_desc

    # והקצה השני: ההודעה שמוחזרת בפועל כשהשם תפוס.
    from mcp_server import handlers

    class _ExistsBackend:
        def file_exists(self, user_id, *, file_name):
            return True

    refusal = handlers.save_file(
        _ExistsBackend(), USER_ID, file_name=FILE_NAME, code="x", language="markdown"
    )
    assert refusal["error"] == "file_exists"
    assert "codekeeper_update_file_description" in refusal["message"]


async def test_the_shared_write_path_import_stays_inside_the_route():
    """הייבוא של מסלול הכתיבה המשותף אינו ברמת המודול ב-``webapp/app.py``.

    **נמדד, לא הונח.** הגרסה הראשונה של השינוי הזה ייבאה את
    ``update_file_metadata_in`` בראש ``webapp/app.py``, וזה **הפיל את
    ``import webapp.app``** בסביבה בלי ``MONGODB_URL``: ``database``
    בונה ``DatabaseManager`` בזמן ייבוא, ו-``config`` דורש את המשתנה.
    לפני השינוי הייבוא הזה עבר; אחריו לא. ה-``try/except`` שעוטף את
    ``HEAVY_FIELDS_EXCLUDE_PROJECTION`` בראש אותו קובץ קיים בדיוק בשביל
    המצב הזה, ואני פשוט לא הלכתי אחריו.

    הטענה היא על **המיקום** ולא על התוצאה, כי הרצת הייבוא בתת-תהליך
    נקייה מ-ENV היא בדיקה יקרה ושברירית — בעוד שהמיקום הוא מה שקובע.
    שורת ייבוא ברמת המודול מזוהה בהזחה אפס.
    """
    import pathlib
    import re

    source = pathlib.Path("webapp/app.py").read_text(encoding="utf-8")
    top_level = re.findall(
        r"^from database\.repository import.*$", source, flags=re.MULTILINE
    )
    offenders = [line for line in top_level if not line.startswith((" ", "\t"))]

    # ‏``HEAVY_FIELDS_EXCLUDE_PROJECTION`` הוא החריג המותר: הוא בתוך
    # ``try/except`` עם fallback, ולכן כשל ייבוא שלו אינו מפיל את המודול.
    offenders = [line for line in offenders if "HEAVY_FIELDS" not in line]

    assert offenders == [], (
        "ייבוא מ-database.repository ברמת המודול מפיל את import webapp.app "
        f"בסביבה בלי MONGODB_URL: {offenders}"
    )
    assert "        from database.repository import (" in source, (
        "הייבוא בתוך הראוט נעלם — המסלול המשותף כבר אינו מחובר"
    )
