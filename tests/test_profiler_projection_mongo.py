"""האם השאילתה השמורה היא **אותה שאילתה** — לפי מונגו, לא לפי דעתי.

הצרכן של ``query_raw`` אינו מילון בפייתון אלא ``explain`` של מונגו: כפתור
הניתוח בדשבורד לוקח את הפייפליין השמור, מעביר אותו ב-``_fix_pipeline_for_explain``,
ושולח אותו למסד. בדיקה שמאשרת שהמילון "נראה נכון" אינה נוגעת באף שלב
מהמסלול הזה — זה בדיוק ``TESTING-PATTERNS.md`` T1(a).

**מה מונגו נותנת לנו כאן.** ל-``explain`` יש שדה ``queryShapeHash``: טביעת
אצבע של **צורת השאילתה**. שתי שאילתות עם אותו hash הן אותה שאילתה מבחינת
המנוע. זה הופך "האם שימרנו את השאילתה" משאלה של שיפוט לשאלה של השוואה.

**ולמה שתי השוואות ולא אחת.** "השמורה שווה לאמיתית" לבדה תעבור גם אם
ה-hash מתעלם מ-``$project`` לגמרי — ואז הבדיקה מוודאת שהשוואת מחרוזות
עובדת ותו לא. לכן יש כאן גם בקרה שלילית: אותה שאילתה עם היטלה **אחרת**
חייבת לקבל hash **שונה**. בלי הצד הזה הראשון אינו ראיה.

נמדד ידנית מול MongoDB 8.0.32 לפני שהבדיקה נכתבה, ושלושת הערכים אכן
נבדלים זה מזה::

    היטלה מורעלת ("<value>")      E6E56114DD6F1BE1…
    היטלה אמיתית (4 שדות)         312C72B3CD327BB5…
    היטלה אחרת (3 שדות)           B48196ED20013F1E…

**מתי הבדיקה רצה:** כש-``MONGODB_URL`` מוגדר, השרת נענה, **והגרסה שלו 8.0
ומעלה**. גרסה נמוכה מזו אינה דילוג אלא כשל מפורש — ראו
``_require_query_shape_hash_support``.

ב-CI של ה-PR זה אינו קורה: הג'וב ``Unit Tests`` ב-``.github/workflows/ci.yml``
רץ ``runs-on: ubuntu-latest`` בלי ``container:``, והשירות ``mongodb`` מוגדר
בלי ``ports:``, ולכן שם השירות אינו נפתר כלל והבדיקה מדלגת בשקט. **אחרי
מיזוג זה כן קורה:** ``.github/workflows/deploy.yml`` מריץ את אותה חבילה על
push ל-``main``, ושם לשירות יש ``ports:`` וה-``MONGODB_URL`` מצביע
ל-``localhost`` — כלומר שרת נגיש, והבדיקה רצה במלואה.
``docs/testing.rst`` מתעד את שני המצבים. הכיסוי שכן רץ בכל מקום נמצא
ב-``tests/test_profiler_projection_is_replayable.py``.

**בטיחות:** הבדיקה יוצרת מסד חד-פעמי עם תחילית ייחודית, ומוחקת רק אותו.
היא אינה כותבת מסמכים — ``queryShapeHash`` נגזר מצורת הפקודה ולא מהנתונים.
"""

from __future__ import annotations

import os
import uuid
from datetime import timezone
from unittest.mock import MagicMock

import pytest

pymongo = pytest.importorskip("pymongo")

from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402

from services.query_profiler_service import PersistentQueryProfilerService  # noqa: E402

#: תחילית מסדי הבדיקה. ה-teardown מוחק **רק** מסד שמתחיל בה.
_TEST_DB_PREFIX = "codebot_profiler_it_"

_MONGO_URL = os.environ.get("MONGODB_URL", "").strip()

ME = 6865105071


#: ⚠️ **הדילוג ברמת המודול נשען על ה-ENV בלבד, ואינו נוגע ברשת.** בדיקת
#: נגישות כאן הייתה פותחת חיבור בכל **איסוף** של pytest, גם בהרצה שאינה
#: כוללת את הקובץ הזה. הנגישות נבדקת ב-fixture, כשהבדיקה באמת עומדת לרוץ.
pytestmark = pytest.mark.skipif(
    not _MONGO_URL,
    reason="דורש MONGODB_URL",
)


def _connect_or_skip():
    """לקוח מחובר, או דילוג — **רק** כששרת אינו נגיש.

    ⚠️ ``except Exception`` גורף כאן היה הופך כל תקלת קונפיגורציה לדילוג עם
    סיבה שקרית: ``mongodb+srv://`` בלי ``dnspython`` זורק ``ConfigurationError``,
    ואימות שגוי זורק ``OperationFailure`` — שניהם היו מדווחים "שרת לא נגיש",
    ושתי הבדיקות כאן, שהן ההוכחה **היחידה** מקצה לקצה לתיקון, היו נעלמות
    בשקט. לכן נתפסת רק אי-נגישות אמיתית, וכל השאר עולה בקול.
    """
    client = pymongo.MongoClient(_MONGO_URL, serverSelectionTimeoutMS=2000, tz_aware=True, tzinfo=timezone.utc)
    try:
        client.admin.command("ping")
    except ServerSelectionTimeoutError as exc:
        client.close()
        pytest.skip(f"שרת מונגו אינו נגיש ב-MONGODB_URL: {exc}")
    except Exception:
        client.close()
        raise
    return client


#: גרסת השרת המינימלית שהבדיקות בקובץ הזה דורשות, כ-``(major, minor)``.
#: ``queryShapeHash`` נוסף לפלט של ``explain`` ב-MongoDB 8.0 ולא לפני כן —
#: *"queryShapeHash, starting in MongoDB 8.0"* — ולכן מול 6.0 השדה פשוט אינו
#: שם, וכל ההשוואה שכאן נשענת עליו מתרוקנת מתוכן.
#: מקור: https://www.mongodb.com/docs/manual/reference/command/explain/
_MIN_SERVER_VERSION = (8, 0)


def _require_query_shape_hash_support(client) -> None:
    """נכשל **בקול** כששרת הבדיקות נמוך מ-8.0, במקום להיראות כמו באג בקוד.

    בלי השער הזה הכשל היחיד שרואים הוא ``explain לא החזיר queryShapeHash``
    מתוך ``_shape_hash`` — הודעה שמצביעה על קוד הייצור בזמן שהשורש הוא גרסת
    השרת, וכך זה אכן נראה בכל ריצה של ``deploy.yml`` כל עוד השירות שם היה
    ``mongo:6.0``.

    **ובמכוון זה כשל ולא ``skip``.** דילוג היה צובע את הריצה בירוק בזמן
    שההשוואה היחידה שמוכיחה את התיקון אינה מתבצעת — כלומר מסתיר כיסוי שהלך
    לאיבוד, בדיוק בסביבה שאמורה לבדוק את המנוע שהפרודקשן מריץ.

    ``buildInfo`` מגיע מחוץ לתהליך, ולכן הצורה שלו נבדקת לפני ההשוואה:
    ``tuple(parts[:2]) < (8, 0)`` על רשימה שיש בה מחרוזת זורק ``TypeError``,
    ותקלה סתומה כזאת הייתה מחליפה בדיוק את ההודעה הברורה שהשער הזה נועד לתת.
    נמדד מול 8.0.32 ומול 6.0.28: ``versionArray`` הוא ארבעה שלמים, למשל
    ``[8, 0, 32, 0]`` ו-``[6, 0, 28, 0]``.
    מקור לשדה: https://www.mongodb.com/docs/manual/reference/command/buildInfo/
    """
    info = client.admin.command("buildInfo")
    reported = info.get("version")
    parts = info.get("versionArray")
    if (
        not isinstance(parts, list)
        or len(parts) < 2
        or not all(isinstance(part, int) for part in parts[:2])
    ):
        pytest.fail(
            f"‏buildInfo לא החזיר versionArray שאפשר להשוות: {parts!r} "
            f"(version={reported!r}). הבדיקה דורשת שרת בגרסה 8.0 ומעלה, "
            "ובלי מספר גרסה אין דרך לוודא שזה מה שרץ."
        )
    if tuple(parts[:2]) < _MIN_SERVER_VERSION:
        wanted = ".".join(str(part) for part in _MIN_SERVER_VERSION)
        pytest.fail(
            f"השרת בגרסה {reported}, הבדיקה דורשת {wanted} ומעלה כי "
            "queryShapeHash קיים רק שם — בפלט של explain הוא נוסף ב-MongoDB 8.0, "
            "ובגרסה מוקדמת יותר השדה כלל אינו חוזר ואין מה להשוות. "
            "הפרודקשן רץ על Atlas 8.0, ולכן גם ה-CI וגם שני קבצי ה-docker-compose "
            "מרימים mongo:8.0; שרת נמוך מזה בודק מנוע אחר מזה שבפרודקשן. "
            "זה כשל ולא דילוג במכוון — דילוג היה מסתיר את הכיסוי שהלך לאיבוד."
        )


#: הפייפליין שנשמר בפועל ב-``slow_queries_log``, על כל 15 הרשומות.
PRODUCTION_FILE_LIST = [
    {"$match": {"user_id": ME, "is_active": True}},
    {"$sort": {"file_name": 1, "version": -1}},
    {"$group": {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}},
    {"$replaceRoot": {"newRoot": "$latest"}},
    {"$sort": {"updated_at": -1}},
    {"$project": {"file_name": 1, "programming_language": 1, "tags": 1, "code": 1}},
    {"$limit": 200},
]

#: אותה שאילתה, היטלה אחרת — ``code`` הושמט. הבקרה השלילית.
A_DIFFERENT_PROJECTION = list(PRODUCTION_FILE_LIST)
A_DIFFERENT_PROJECTION[5] = {"$project": {"file_name": 1, "programming_language": 1, "tags": 1}}


#: שם האוסף. הוא אינו נוצר ואינו נכתב: ``explain`` על אוסף שאינו קיים מחזיר
#: תוכנית ``EOF`` **ועדיין נושא** ``queryShapeHash``, כי ה-hash נגזר מצורת
#: הפקודה ולא מהנתונים. נמדד מול MongoDB 8.0.32.
_COLLECTION = "code_snippets"


@pytest.fixture
def test_db():
    name = f"{_TEST_DB_PREFIX}{uuid.uuid4().hex[:12]}"
    client = _connect_or_skip()
    try:
        # שער הגרסה לפני ה-``yield``: בלעדיו הבדיקה מגיעה עד ``_shape_hash``
        # ונכשלת שם על שדה חסר, וזה נראה כמו באג בקוד הייצור ולא כמו פער
        # סביבה. הוא יושב בתוך ה-``try`` כדי שה-``finally`` יסגור את הלקוח
        # גם כשהוא נכשל; ``drop_database`` על מסד שלא נוצר הוא no-op.
        _require_query_shape_hash_support(client)
        yield client[name]
    finally:
        # סורג בטיחות: מוחקים רק מסד שנוצר כאן
        assert name.startswith(_TEST_DB_PREFIX), f"סירוב למחוק מסד שאינו של הבדיקות: {name}"
        try:
            client.drop_database(name)
        finally:
            client.close()


@pytest.fixture
def svc(monkeypatch, test_db):
    monkeypatch.setenv("PROFILER_UNREDACTED_USER_IDS", str(ME))
    manager = MagicMock()
    manager.db = test_db
    return PersistentQueryProfilerService(db_manager=manager, slow_threshold_ms=100)


def _shape_hash(service, pipeline):
    """‏``queryShapeHash`` של הפייפליין, דרך **קוד הייצור עצמו**.

    שני השלבים כאן הם בדיוק מה ש-``get_aggregation_explain`` מריצה, ובאותו
    סדר: ``_fix_pipeline_for_explain`` (שמתקנת ``$limit``/``$skip`` שנשארו
    placeholder) ואז ``_run_explain_command``. בנייה ידנית של פקודת
    ``explain`` כאן הייתה יוצרת מסלול שאף צרכן אינו מריץ — וזו בדיוק
    הטעות ש-``TESTING-PATTERNS.md`` T1 מתעד.
    """
    fixed = service._fix_pipeline_for_explain(pipeline)
    result = service._run_explain_command(
        {"aggregate": _COLLECTION, "pipeline": fixed, "cursor": {}}, "queryPlanner"
    )
    shape = result.get("queryShapeHash")
    assert shape, (
        f"‏explain לא החזיר queryShapeHash: {sorted(result)}. "
        "שרת מתחת ל-8.0 נתפס כבר בפיקסצ'ר, אז הודעה מכאן פירושה משהו אחר."
    )
    return shape


def test_the_saved_query_is_the_same_query(svc):
    """הצד החיובי: מה שנשמר מנותח כמו מה שרץ."""
    raw, _owner, reason = svc._decide_raw_query("aggregate", {"pipeline": PRODUCTION_FILE_LIST})
    assert reason is None, f"השאילתה נדחתה: {reason}"

    saved = _shape_hash(svc, raw["pipeline"])
    actual = _shape_hash(svc, PRODUCTION_FILE_LIST)

    assert saved == actual, (
        "הפייפליין השמור מנותח כשאילתה אחרת מזו שרצה.\n"
        f"  שמור:  {saved}\n"
        f"  אמיתי: {actual}\n"
        f"  ההיטלה שנשמרה: {raw['pipeline'][5]}"
    )


def test_and_the_hash_would_have_noticed_a_different_projection(svc):
    """הצד השני, שבלעדיו הראשון אינו ראיה.

    אם ``queryShapeHash`` היה מתעלם מ-``$project``, הבדיקה שמעל הייתה
    עוברת גם על הקוד השבור. כאן מוכיחים שהוא **כן** מבחין.
    """
    actual = _shape_hash(svc, PRODUCTION_FILE_LIST)
    different = _shape_hash(svc, A_DIFFERENT_PROJECTION)

    assert actual != different, (
        "‏queryShapeHash זהה לשתי היטלות שונות — כלומר הוא אינו רגיש להיטלה, "
        "והבדיקה שמעל אינה מוכיחה דבר."
    )
