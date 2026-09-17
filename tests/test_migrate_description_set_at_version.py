"""המיגרציה שמשחזרת את חותמת גיל התיאור לקבצים שנשמרו לפני שהשדה קיים.

שני חצאים, ובכוונה בשני סגנונות. **ההיגיון** נבדק על שרשרות בנויות ביד,
כי המקרים שמעניינים בו — חור באמצע הרצף, תיאור שהתחלף באמצע — הם בדיוק
אלה שאי אפשר לייצר דרך מסלול השמירה: הוא לעולם אינו מדלג על מספר גרסה.
**הכתיבה** נבדקת מול מונגו אמיתי, כי ההבטחה שלה היא על מה ששורד הרצה
שנייה, ודמה תחזיר את מה שכתבו בה.

בלי ``NOTE_FONTS_TEST_MONGO_URI`` החצי השני מדולג והראשון עדיין רץ.

הרצה מקומית::

    NOTE_FONTS_TEST_MONGO_URI='mongodb://127.0.0.1:27017' \\
        pytest tests/test_migrate_description_set_at_version.py -v
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from file_description import DESCRIPTION_SET_AT_VERSION_FIELD

USER_ID = 8675
FILE_NAME = "code-review-mcp-to-thread-PR3390.md"
DESCRIPTION = "סיכום הריוויו, האימות היריב טרם הושלם"


def _module():
    """טוען את הסקריפט לפי נתיב — ``scripts/`` אינו חבילה.

    אותה תבנית כמו ``tests/test_migrate_note_colors.py``. ייבוא רגיל היה
    דורש להפוך את ``scripts`` לחבילה בשביל טסט אחד.
    """
    path = Path(__file__).resolve().parents[1] / "scripts" / "migrate_description_set_at_version.py"
    spec = importlib.util.spec_from_file_location("migrate_description_set_at_version", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _chain(*pairs):
    """שרשרת גרסאות מזוגות ``(version, description)``."""
    return [{"version": v, "description": d} for v, d in pairs]


# --------------------------------------------------------------------------
# ההיגיון
# --------------------------------------------------------------------------


def test_an_unbroken_run_of_the_same_description_dates_back_to_its_first_version():
    """הליכה אחורה כל עוד התיאור זהה — התשובה היא תחילת הרצף.

    זה המקרה שהמיגרציה קיימת בשבילו: קובץ שתיאורו נכתב פעם אחת ונגרר
    אחריו דרך עשר עריכות.
    """
    stamp = _module().stamp_from_version_chain(
        _chain((1, DESCRIPTION), (2, DESCRIPTION), (3, DESCRIPTION))
    )
    assert stamp == 1


def test_a_run_that_starts_mid_history_dates_to_where_the_text_changed():
    """התיאור התחלף בגרסה 3 — ולכן זו הגרסה שבה הוא נקבע.

    ``2`` כאן היה אומר שהתיאור הנוכחי קיים מאז גרסה 2, וזה פשוט לא נכון:
    בגרסה 2 היה כתוב משהו אחר.
    """
    stamp = _module().stamp_from_version_chain(
        _chain((1, "ישן"), (2, "ישן"), (3, DESCRIPTION), (4, DESCRIPTION))
    )
    assert stamp == 3


def test_a_hole_in_the_version_numbers_is_unknown_and_never_a_guess():
    """**זה האסרשן החשוב בקובץ.**

    מספור הגרסאות רץ על כל המסמכים של אותו שם קובץ כולל אלה שבסל
    המיחזור, ולכן גרסה 2 שנמחקה משאירה חור. התיאור בגרסה 2 הוא מה
    שהיה קובע אם הרצף מתחיל ב-1 או ב-3, והוא איננו.

    ``None`` הוא התשובה, והגיל יישאר ``null``. מימוש שהיה "משלים" — מדלג
    על החור וממשיך אחורה, או עוצר ומחזיר 3 — היה ממציא מספר. זו בדיוק
    הטענה שאסור להמציא, ואי אפשר לייצר את המקרה הזה דרך מסלול השמירה.
    """
    stamp = _module().stamp_from_version_chain(
        _chain((1, DESCRIPTION), (3, DESCRIPTION), (4, DESCRIPTION))
    )
    assert stamp is None


def test_a_version_that_never_had_a_description_stops_the_run():
    """גרסה בלי תיאור היא **שוני**, לא חור.

    ההבחנה אינה תיאורטית: קובץ נשמר בלי תיאור, ואחרי שלוש עריכות מישהו
    הוסיף אחד. הגרסה שבה הוא הוסף היא התשובה הנכונה, ומימוש שהיה מדלג
    על מסמכים בלי תיאור היה מחזיר ``None`` — כלומר מוותר על קובץ שהתשובה
    עליו ידועה לגמרי.
    """
    stamp = _module().stamp_from_version_chain(
        _chain((1, ""), (2, ""), (3, DESCRIPTION))
    )
    assert stamp == 3


def test_a_malformed_version_number_is_skipped_and_never_crashes_the_run():
    """מסמך עם ``version`` שאינו מספר מדולג — בשני חצאי הסקריפט.

    **מיגרציה שקורסת באמצע גרועה במיוחד**, כי היא כבר כתבה לחלק
    מהקבצים ומי שמריץ אותה שוב אינו יודע איפה היא עצרה. קודם היו כאן
    שתי תשובות שונות לאותה שאלה: בניית השרשרת סיננה ערך פגום, ובחירת
    הגרסה האחרונה עשתה עליו ``int(...)`` וזרקה ``ValueError``.

    שתיהן שואלות עכשיו את אותה שאלה, ולכן שתיהן נבדקות כאן על אותם
    נתונים.
    """
    module = _module()
    chain = [
        {"version": 1, "description": DESCRIPTION},
        {"version": "bad", "description": DESCRIPTION},
        {"version": 2, "description": DESCRIPTION},
    ]

    assert module.stamp_from_version_chain(chain) == 1
    assert module._latest_version_doc(chain) == {"version": 2, "description": DESCRIPTION}

    # ומספר שנשמר כמחרוזת הוא ערך תקף ולא פגום — מסמכים ישנים במונגו
    # נושאים כאלה, וסינון שלהם היה מוותר על קבצים שהתשובה עליהם ידועה.
    assert module._latest_version_doc([{"version": "3"}, {"version": 1}]) == {"version": "3"}


def test_the_migration_survives_a_malformed_version_in_the_collection(wired_mongo):
    """ואותו דבר מקצה לקצה, על מסמך פגום שיושב במסד.

    הבדיקה שמעל היא על הפונקציות; זו על ``migrate`` עצמה, כי הקריסה
    הייתה שם — בבחירת הגרסה האחרונה — ולא בהיגיון השרשרת.
    """
    collection = _seed(wired_mongo, DESCRIPTION, DESCRIPTION)
    collection.insert_one({
        "user_id": USER_ID, "file_name": FILE_NAME, "code": "# פגום\n",
        "programming_language": "markdown", "description": DESCRIPTION,
        "tags": [], "version": "bad", "is_active": True,
    })

    counters = _module().migrate(collection)

    assert counters["stamped"] == 1, counters
    assert _stamps(collection)[1] == 1


def test_a_single_version_file_dates_to_itself():
    assert _module().stamp_from_version_chain(_chain((1, DESCRIPTION))) == 1


def test_a_file_whose_latest_version_has_no_description_gets_nothing():
    """אין תיאור בגרסה האחרונה — אין מה לתארך, גם אם לקודמות היה."""
    stamp = _module().stamp_from_version_chain(
        _chain((1, DESCRIPTION), (2, ""))
    )
    assert stamp is None


# --------------------------------------------------------------------------
# הכתיבה
# --------------------------------------------------------------------------


def _seed(wired_mongo, *descriptions, versions=None):
    collection = wired_mongo.get_db().code_snippets
    collection.delete_many({})
    numbers = versions or range(1, len(descriptions) + 1)
    for version, description in zip(numbers, descriptions, strict=True):
        collection.insert_one({
            "user_id": USER_ID, "file_name": FILE_NAME,
            "code": f"# גרסה {version}\n", "programming_language": "markdown",
            "description": description, "tags": [], "version": version,
            "is_active": True,
        })
    return collection


def _stamps(collection):
    return {
        d["version"]: d.get(DESCRIPTION_SET_AT_VERSION_FIELD)
        for d in collection.find({"user_id": USER_ID, "file_name": FILE_NAME})
    }


def test_the_migration_stamps_every_version_in_the_run(wired_mongo):
    """כל הגרסאות ברצף מקבלות את החותמת, לא רק האחרונה.

    כולן נושאות את אותו תיאור, ולכן אותה חותמת נכונה לכולן — וכך גם
    ``codekeeper_get_file`` עם ``version`` מפורש מחזיר גיל ולא ``null``.
    """
    collection = _seed(wired_mongo, DESCRIPTION, DESCRIPTION, DESCRIPTION)

    counters = _module().migrate(collection)

    assert _stamps(collection) == {1: 1, 2: 1, 3: 1}
    assert counters["stamped"] == 1 and counters["documents_written"] == 3, counters


def test_versions_before_the_run_are_left_alone(wired_mongo):
    """גרסאות שנשאו תיאור אחר אינן מקבלות את החותמת של הרצף הנוכחי."""
    collection = _seed(wired_mongo, "ישן", DESCRIPTION, DESCRIPTION)

    _module().migrate(collection)

    assert _stamps(collection) == {1: None, 2: 2, 3: 2}


def test_a_broken_chain_is_left_without_a_stamp_and_counted_as_unknown(wired_mongo):
    """שרשרת קטועה — לא נכתב כלום, והדוח אומר למה.

    המונה הנפרד אינו קישוט: בלעדיו "לא קיבל חותמת" נראה זהה עבור קובץ
    בלי תיאור ועבור קובץ שההיסטוריה שלו חסרה, ואי אפשר לקרוא את הדוח.
    """
    collection = _seed(
        wired_mongo, DESCRIPTION, DESCRIPTION, versions=[1, 3],
    )

    counters = _module().migrate(collection)

    assert _stamps(collection) == {1: None, 3: None}
    assert counters["unknown"] == 1 and counters["stamped"] == 0, counters


def test_running_it_twice_changes_nothing_the_second_time(wired_mongo):
    """אידמפוטנטית — ולא רק "לא קורסת"."""
    collection = _seed(wired_mongo, DESCRIPTION, DESCRIPTION)

    first = _module().migrate(collection)
    before = _stamps(collection)
    second = _module().migrate(collection)

    assert _stamps(collection) == before
    assert first["stamped"] == 1 and second["stamped"] == 0, (first, second)
    # ``already_complete`` ולא ``backfilled``: לא היה מה להשלים.
    assert second["already_complete"] == 1, second
    assert second["documents_written"] == 0, second


def test_a_run_that_was_interrupted_is_completed_by_running_it_again(wired_mongo):
    """**"ניתנת להרצה חוזרת" נבדקת במצב שבו היא באמת נחוצה.**

    ``update_many`` אינו אטומי בין מסמכים: קריסה באמצע משאירה חלק
    מהשרשרת כתוב וחלק לא. הצורה הקודמת דילגה על קובץ שלגרסתו האחרונה
    יש חותמת — ולכן דווקא אחרי קטיעה, ההרצה החוזרת לא השלימה כלום
    וספרה את הקובץ כ"כבר מתוארך". כלומר ההבטמה החזיקה רק כשלא היה בה
    צורך.

    המצב כאן הוא בדיוק מה שקטיעה משאירה: הגרסה האחרונה נכתבה, הקודמות
    לא.
    """
    collection = _seed(wired_mongo, DESCRIPTION, DESCRIPTION, DESCRIPTION)
    collection.update_one(
        {"version": 3}, {"$set": {DESCRIPTION_SET_AT_VERSION_FIELD: 1}}
    )

    counters = _module().migrate(collection)

    assert _stamps(collection) == {1: 1, 2: 1, 3: 1}, "ההרצה החוזרת לא השלימה"
    assert counters["backfilled"] == 1, counters
    assert counters["documents_written"] == 2, counters


def test_a_version_stored_as_a_string_is_stamped_like_any_other(wired_mongo):
    """**מסמך עם ``version`` כמחרוזת נשמט בשקט, ודווקא הוא החשוב.**

    ``normalized_version`` מקבל מספר שנשמר כמחרוזת **במכוון** — מסמכים
    ישנים במונגו נושאים כאלה. הפילטר שכתב את החותמת השתמש ב-``$gte``
    מספרי, ומונגו משווה בין טיפוסים לפי סדר טיפוסים: מספר אינו מתאים
    למחרוזת. נמדד מול MongoDB 7.0.14 — על שרשרת ``1, "2", 3`` העדכון
    נגע בשניים והשאיר את ``"2"`` בלי חותמת.

    שני חצאים של אותה מיגרציה החזיקו שתי תשובות שונות לאותה שאלה,
    והחצי שכותב הוא זה שהחמיץ.
    """
    collection = wired_mongo.get_db().code_snippets
    collection.delete_many({})
    for version in (1, "2", 3):
        collection.insert_one({
            "user_id": USER_ID, "file_name": FILE_NAME, "code": "# גרסה\n",
            "programming_language": "markdown", "description": DESCRIPTION,
            "tags": [], "version": version, "is_active": True,
        })

    counters = _module().migrate(collection)

    stamps = {
        str(d["version"]): d.get(DESCRIPTION_SET_AT_VERSION_FIELD)
        for d in collection.find({"user_id": USER_ID, "file_name": FILE_NAME})
    }
    assert stamps == {"1": 1, "2": 1, "3": 1}, stamps
    assert counters["documents_written"] == 3, counters


def test_it_never_overwrites_a_stamp_an_in_place_update_moved(wired_mongo):
    """**זה מה שהופך את האידמפוטנטיות לבטוחה ולא רק לנוחה.**

    ``codekeeper_update_file_description`` מזיז את החותמת בלי ליצור
    גרסה, ולכן שרשרת הגרסאות כבר לא מתארת אותה: כל הגרסאות נושאות את
    אותו תיאור, ולפי השרשרת החותמת הייתה 1. הרצה שנייה שהייתה מחשבת
    מחדש הייתה מחזירה את הגיל מ-0 ל-2 ומוחקת עדכון אמיתי.
    """
    collection = _seed(wired_mongo, DESCRIPTION, DESCRIPTION, DESCRIPTION)
    collection.update_one(
        {"version": 3}, {"$set": {DESCRIPTION_SET_AT_VERSION_FIELD: 3}}
    )

    _module().migrate(collection)

    assert _stamps(collection)[3] == 3, "המיגרציה דרסה חותמת שעודכנה ידנית"


def test_dry_run_reports_without_writing(wired_mongo):
    collection = _seed(wired_mongo, DESCRIPTION, DESCRIPTION)

    counters = _module().migrate(collection, dry_run=True)

    assert counters["stamped"] == 1, counters
    assert counters["documents_written"] == 0, counters
    assert _stamps(collection) == {1: None, 2: None}


def test_a_file_with_no_description_is_counted_separately_and_left_alone(wired_mongo):
    collection = _seed(wired_mongo, "", "")

    counters = _module().migrate(collection)

    assert counters["no_description"] == 1 and counters["stamped"] == 0, counters
    assert _stamps(collection) == {1: None, 2: None}


#: הקצה השני — שאחרי המיגרציה הגיל באמת מגיע לסוכן — נבדק ב-
#: ``tests/test_mcp_description_age.py``, שם יושב החיווט של שרת ה-MCP.
#: ייבוא בין קובצי בדיקה בשביל בדיקה אחת היה עולה יותר ממה שהוא חוסך.
