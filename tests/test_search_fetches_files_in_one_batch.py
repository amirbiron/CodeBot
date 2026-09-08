"""החיפוש שולף את הקבצים המתאימים בבת אחת, ולא קובץ-קובץ.

**למה הקובץ הזה קיים.** חיפוש "טקסט" של שם קובץ מלא לקח בפרודקשן
**191.74 שניות**. ``_text_search`` ו-``_function_search`` שלפו כל קובץ
מתאים בשאילתה נפרדת (``db.get_latest_version``), וכל שליפה כזו עולה שלוש
קפיצות רשת: GET ל-Redis (``@cached``), ``find_one`` בלי היטלה — כלומר כל
ה-``code`` — ואז SETEX. על 745 קבצים פעילים זה 745 סיבובים כדי להחזיר
עשר תוצאות, כי ``limit`` מוחל רק בסוף.

**הבדיקות כאן סופרות קריאות, לא זמן.** זמן הוא מדד רועש ב-CI; מספר
הפניות ל-DB הוא הסיבה עצמה, והוא דטרמיניסטי. הדמה נכתבת כאן ביד ואינה
נוגעת במונגו, ולכן כל הקובץ רץ ב-CI.

**המספר 745 אינו שרירותי** — זה גודל הקורפוס האמיתי שנמדד אצל המשתמש
שדיווח, ולכן גם מספר המנות בבדיקה הוא מה שיקרה אצלו בפועל.
"""

from __future__ import annotations

import pytest

import search_engine as se

USER_ID = 4242
#: גודל הקורפוס שנמדד בפרודקשן אצל המשתמש שדיווח על 191 השניות.
CORPUS = 745


def _doc(file_name: str) -> dict:
    now = se.datetime.now(se.timezone.utc)
    # שם פונקציה חייב להיות מזהה חוקי: ``function_index`` נבנה דרך
    # ``code_processor.extract_functions``, וקוד שאינו נפרס אינו מייצר אף ערך.
    ident = file_name.replace(".", "_").replace("-", "_")
    return {
        "_id": f"id-{file_name}",
        "file_name": file_name,
        "code": f"def helper_{ident}():\n    return 'needle'\n",
        "programming_language": "python",
        "tags": [],
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }


class _LegacyDB:
    """דמה כמו חמש הדמויות שכבר בריפו: ``get_latest_version`` בלבד.

    היא **אינה** יורשת את המתודה המקובצת, ולכן ``getattr`` עליה מחזיר
    ``None`` — בדיוק המצב שנפילת-התאימות נועדה לו.
    """

    def __init__(self, file_names):
        self.docs = {name: _doc(name) for name in file_names}
        self.per_file_calls = 0
        self.batch_calls: list[list[str]] = []

    def get_user_files(self, user_id, limit=200, *, skip=0, projection=None):
        if skip:
            return []
        return [dict(d) for d in self.docs.values()]

    def get_latest_version(self, user_id, file_name):
        self.per_file_calls += 1
        doc = self.docs.get(file_name)
        return dict(doc) if doc else None


class _CountingDB(_LegacyDB):
    """דמה עדכנית, שסופרת בנפרד שליפה בודדת ושליפה מקובצת.

    ``batched_raises`` מדמה תקלת מונגו חולפת: המתודה **קיימת** וזורקת.
    זה המקרה שאסור שיפעיל נפילה-לאחור.
    """

    def __init__(self, file_names, *, batched_raises: bool = False):
        super().__init__(file_names)
        self._batched_raises = batched_raises

    def get_latest_versions_by_names(self, user_id, file_names, *, projection=None,
                                     chunk_size=None):
        names = list(file_names)
        self.batch_calls.append(names)
        if self._batched_raises:
            raise RuntimeError("תקלת מונגו חולפת")
        return {n: dict(self.docs[n]) for n in names if n in self.docs}


def _wire(monkeypatch, db):
    monkeypatch.setattr(se, "db", db, raising=False)
    return se.AdvancedSearchEngine()


def _index_over(engine, db):
    """בונה אינדקס בזיכרון מעל הדמה, בלי לגעת ב-DB אמיתי."""
    return engine.get_index(USER_ID)


@pytest.fixture
def counting_db(monkeypatch):
    def _make(*, legacy: bool = False, **kwargs):
        names = [f"file_{i:04d}.py" for i in range(CORPUS)]
        db = _LegacyDB(names) if legacy else _CountingDB(names, **kwargs)
        return db, _wire(monkeypatch, db)
    return _make


@pytest.mark.parametrize("branch", ["text", "function"])
def test_a_matching_corpus_is_fetched_in_batches_not_file_by_file(counting_db, branch):
    """**זו הבדיקה שנופלת על הקוד הנוכחי.**

    שני הענפים נבדקים כי הבלוק בהם **זהה מילה במילה** — תיקון של אחד בלבד
    היה משאיר את הבאג חי בשני.
    """
    db, engine = counting_db()
    index = _index_over(engine, db)

    if branch == "text":
        results = engine._text_search("needle", index, USER_ID)
    else:
        results = engine._function_search("helper", index, USER_ID)

    assert results, "החיפוש לא החזיר דבר — הבדיקה אינה בודקת את מה שהיא טוענת"
    assert db.per_file_calls == 0, (
        f"{db.per_file_calls} שליפות בודדות. כל אחת היא שלוש קפיצות רשת, "
        f"וזה בדיוק מה שייצר 191 שניות"
    )
    assert db.batch_calls, "לא נעשתה שום שליפה מקובצת"


def test_the_whole_corpus_is_asked_for_in_one_call(counting_db):
    """מנוע החיפוש מוסר את כל השמות בבקשה אחת.

    **החלוקה למנות אינה כאן.** היא באחריות ``Repository``, כי היא נובעת
    מגבולות של מונגו — לא מלוגיקת חיפוש. הדמה כאן מחליפה את שכבת ה-DB
    כולה, ולכן היא רואה בקשה אחת עם כל השמות; הבדיקה של המנות עצמן יושבת
    ב-``tests/test_repository_batch_latest_versions.py``, מול הצינור שנשלח
    בפועל.
    """
    db, engine = counting_db()
    engine._text_search("needle", _index_over(engine, db), USER_ID)

    assert len(db.batch_calls) == 1, (
        f"ציפיתי לבקשה אחת מהמנוע, התקבלו {len(db.batch_calls)}"
    )
    asked = db.batch_calls[0]
    assert len(asked) == len(set(asked)) == CORPUS, (
        "המנוע ביקש כפילויות או החסיר שמות"
    )


def test_a_failing_batch_does_not_fall_back_to_fetching_one_by_one(counting_db):
    """**הבדיקה שמונעת נפילה-לאחור מסוכנת.**

    נפילה-לאחור על **חריגה** הייתה הופכת כל תקלת מונגו חולפת ל-745 שליפות
    סדרתיות — כלומר מחזירה את 191 השניות ומחזיקה worker תפוס שלוש דקות.
    זה גרוע מכישלון מהיר.

    ``search`` העוטפת כבר מטפלת: היא רושמת ``שגיאה בחיפוש``, פולטת
    ``search_error`` ומחזירה רשימה ריקה — ובוובאפ ``_safe_search`` נופל
    משם ל-``$text`` של מונגו. כלומר יש מסלול חלופי אמיתי, מהיר ומתועד.
    """
    db, engine = counting_db(batched_raises=True)
    index = _index_over(engine, db)

    with pytest.raises(RuntimeError):
        engine._text_search("needle", index, USER_ID)

    assert db.per_file_calls == 0, (
        f"החריגה גררה {db.per_file_calls} שליפות בודדות — בדיוק הנפילה-לאחור "
        f"שהחזירה את הבאג בשקט"
    )


def test_the_whole_search_reports_the_failure_instead_of_grinding(counting_db, caplog):
    """נעילת ההתנהגות מקצה לקצה: כשל מהיר ומדווח, לא טחינה."""
    db, engine = counting_db(batched_raises=True)

    with caplog.at_level("ERROR", logger="search_engine"):
        results = engine.search(user_id=USER_ID, query="needle",
                                search_type=se.SearchType.TEXT, limit=10)

    assert results == []
    assert db.per_file_calls == 0
    assert "שגיאה בחיפוש" in caplog.text, "הכשל לא נרשם, ואז הוא בלתי נראה"


def test_an_old_stub_without_the_batch_method_still_works(counting_db):
    """תאימות לדמויות ישנות — וזו **הסיבה היחידה** לנפילה-לאחור.

    חמישה קובצי בדיקה בריפו מריצים את המסלולים האלה עם דמויות שחושפות
    ``get_latest_version`` בלבד. היעדר המתודה הוא מצב סטטי וידוע; חריגה
    ממנה אינה, ולכן היא אינה מפעילה את המסלול הזה.
    """
    db, engine = counting_db(legacy=True)
    assert not hasattr(db, "get_latest_versions_by_names")

    results = engine._text_search("needle", _index_over(engine, db), USER_ID)

    assert results, "המסלול הישן לא רץ, כלומר דמויות קיימות היו נשברות"
    assert db.per_file_calls > 0


def test_the_real_manager_exposes_the_batch_method():
    """בלי זה, נפילת-התאימות הייתה מחזירה את 191 השניות **בשקט**.

    כל הבדיקות שמעל משתמשות בדמה. אם ``DatabaseManager`` האמיתי לא היה
    חושף את המתודה, הפרודקשן היה נופל למסלול הישן וכל הסוויטה הייתה
    נשארת ירוקה.
    """
    from database.manager import DatabaseManager

    assert callable(getattr(DatabaseManager, "get_latest_versions_by_names", None)), (
        "DatabaseManager אינו חושף את המתודה — הפרודקשן ייפול למסלול הישן"
    )


def test_the_projection_keeps_code_and_drops_the_embedding():
    """נעילת היקף על ההיטלה, לשני הכיוונים.

    ``code`` **חייב** להישאר, בניגוד לכלל ה-Smart Projection: ``_apply_filters``
    נשען על ``result.content`` לשלושה מסננים ו-``_sort_results`` על אורכו.
    בלעדיו הם היו מסננים על מחרוזת ריקה — תשובות שגויות בשקט.

    ``snippetEmbedding`` (~3KB למסמך) חייב לרדת; איש אינו קורא אותו
    מ-``SearchResult``.
    """
    proj = se.SEARCH_RESULT_PROJECTION

    assert proj.get("code") == 1, "בלי code המסננים והמיון עובדים על מחרוזת ריקה"
    assert "snippetEmbedding" not in proj

    # בדיוק השדות ש-_create_search_result קורא, לא יותר ולא פחות
    assert set(proj) == {
        "_id", "file_name", "code", "programming_language",
        "tags", "version", "created_at", "updated_at",
    }
