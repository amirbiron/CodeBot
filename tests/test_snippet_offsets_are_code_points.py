"""חיתוך ומדידה של טקסט בצינורות ה-snippet נעשים בתווים, לא בבייטים.

**למה הקובץ הזה קיים.** ``$regexFind`` מחזיר ``idx`` כאינדקס **תווים** (code
point index, מפורש בתיעוד של מונגו), והקוד הזין אותו ל-``$substrBytes``, שמצפה
ל**בייטים**. באנגלית שתי היחידות זהות ולכן זה עבר סקירה; בעברית כל אות היא שני
בייטים, גבול החיתוך נוחת באמצע תו, ומונגו זורקת ומפילה את כל האגרגציה. בחיפוש
זה הוריד את המערכת לסריקה מלאה בלי אינדקס, ובשיתוף זה החזיר 404 "קובץ לא נמצא"
על קובץ שקיים.

**מה הקובץ הזה בודק, ומה לא.** הוא מקליט את הצינור ש**נשלח בפועל** ל-``aggregate``
משני אתרי הקריאה, ובודק עליו תכונת יחידות. הוא אינו מריץ את הצינור, ולכן אינו
יכול להוכיח שמונגו מקבלת אותו ואינו תופס שגיאת off-by-one — לשם כך יש את
``tests/test_snippet_hebrew_offsets_mongo.py``, שמדלג כשאין מונגו זמין.

מה כן: הקלטה של האובייקט האמיתי שנמסר לדרייבר תופסת תיקון שהוחל על helper שאינו
מחווט, או רק על אחד משני האתרים — שתי אפשרויות שקריאת קוד המקור הייתה "מאמתת".
"""

from __future__ import annotations

import pytest
from bson import ObjectId

BYTE_OPS = {"$strLenBytes", "$substrBytes", "$indexOfBytes"}
CP_OPS = {"$strLenCP", "$substrCP", "$indexOfCP"}

#: שדות שהמדידה בהם היא על **טקסט**, ולכן חייבת להיות בתווים.
TEXT_FIELDS = ("snippet_preview", "_match_len", "_has_code_match")

#: ביטויים שנגזרים מ-``$regexFind.idx``, שהוא אינדקס תווים. כל חישוב שנשען
#: עליהם חייב להישאר במרחב התווים.
CODE_POINT_SOURCES = ("$_m.idx", "$_match_idx", "$_snippet_start")


def _ops(expr) -> set:
    """כל שמות האופרטורים בתת-העץ."""
    found = set()
    if isinstance(expr, dict):
        for key, value in expr.items():
            if isinstance(key, str) and key.startswith("$"):
                found.add(key)
            found |= _ops(value)
    elif isinstance(expr, (list, tuple)):
        for item in expr:
            found |= _ops(item)
    return found


def _fields(pipeline) -> dict:
    """שם שדה ← הביטוי שמחשב אותו, מכל שלבי ``$addFields``/``$set``."""
    out = {}
    for stage in pipeline or []:
        if isinstance(stage, dict):
            for key in ("$addFields", "$set"):
                inner = stage.get(key)
                if isinstance(inner, dict):
                    out.update(inner)
    return out


def _mentions(expr, needles) -> bool:
    """האם הביטוי מפנה לאחד מהשדות הנתונים (בכל עומק)."""
    if isinstance(expr, str):
        return expr in needles
    if isinstance(expr, dict):
        return any(_mentions(v, needles) for v in expr.values())
    if isinstance(expr, (list, tuple)):
        return any(_mentions(item, needles) for item in expr)
    return False


def assert_text_fields_use_code_points(pipeline) -> None:
    fields = _fields(pipeline)
    for name in TEXT_FIELDS:
        if name not in fields:
            continue
        used = _ops(fields[name])
        offending = used & BYTE_OPS
        assert not offending, (
            f"השדה {name!r} מודד טקסט ב{sorted(offending)} — יחידת בייטים. "
            f"בעברית זה חותך באמצע אות ומפיל את השאילתה."
        )
        assert used & CP_OPS, (
            f"השדה {name!r} אמור להימדד בתווים, ואין בו אף אופרטור מ-{sorted(CP_OPS)}: "
            f"{fields[name]!r}"
        )


def assert_code_point_indices_never_meet_byte_operators(pipeline) -> None:
    """התכונה הכללית — תופסת גם את השדה הבא שמישהו יוסיף."""
    for name, expr in _fields(pipeline).items():
        if not _mentions(expr, CODE_POINT_SOURCES):
            continue
        offending = _ops(expr) & BYTE_OPS
        assert not offending, (
            f"השדה {name!r} נגזר מאינדקס תווים ובכל זאת משתמש ב{sorted(offending)}. "
            f"$regexFind.idx הוא code point index — ערבוב היחידות הוא הבאג עצמו."
        )


def assert_file_size_is_still_bytes(pipeline) -> None:
    """נעילת היקף: ``file_size`` הוא גודל אחסון, ובייטים הם היחידה הנכונה בו.

    בלי האסרשן הזה, "הרחבה" של התיקון ל-``$strLenCP`` הייתה מדווחת קבצים
    עבריים בחצי גודלם — בשקט.
    """
    expr = _fields(pipeline).get("file_size")
    if expr is None:
        return
    assert "$strLenBytes" in _ops(expr), (
        f"file_size חייב להישאר בבייטים; התקבל {expr!r}"
    )


def check_pipeline(pipeline) -> None:
    assert_text_fields_use_code_points(pipeline)
    assert_code_point_indices_never_meet_byte_operators(pipeline)
    assert_file_size_is_still_bytes(pipeline)


# --------------------------------------------------------------------------
# מסלול החיפוש
# --------------------------------------------------------------------------


class _CapturingCodeSnippets:
    """מקליט כל צינור שנשלח, ויכול להיכשל במספר הקריאות הראשונות."""

    def __init__(self, fail_times: int = 0) -> None:
        self.pipelines: list = []
        self.fail_times = fail_times
        self.calls = 0

    def aggregate(self, pipeline, **_kwargs):
        self.calls += 1
        self.pipelines.append(list(pipeline or []))
        if self.calls <= self.fail_times:
            raise RuntimeError(f"forced failure (call {self.calls})")
        return []


class _FakeDB:
    def __init__(self, collection):
        self.code_snippets = collection


def _run_search(monkeypatch, fail_times: int = 0):
    import webapp.app as wa

    collection = _CapturingCodeSnippets(fail_times=fail_times)
    # בלי זה מנוע החיפוש עונה קודם והצינור לא נבנה כלל.
    monkeypatch.setattr(wa, "search_engine", None, raising=False)
    monkeypatch.setattr(wa, "get_db", lambda: _FakeDB(collection), raising=True)
    wa._safe_search(6865105071, "שלום", limit=50)
    assert collection.pipelines, "לא נלכד אף צינור — הסטאב לא חובר"
    return collection


def test_the_search_pipeline_measures_text_in_code_points(monkeypatch):
    for pipeline in _run_search(monkeypatch).pipelines:
        check_pipeline(pipeline)


def test_the_regex_fallback_sends_the_same_corrected_stages(monkeypatch):
    """``pipeline2 = list(pipeline)`` הוא העתק רדוד שחולק את אותם שלבים.

    כלומר תיקון אחד מכסה את שתי ההרצות. הטסט קיים כדי שהעובדה הזו תישבר
    ברעש אם מישהו יבנה את הפולבאק מחדש במקום להעתיק.
    """
    collection = _run_search(monkeypatch, fail_times=1)
    assert collection.calls >= 2, "הפולבאק לא רץ, אז אין מה לבדוק"
    for pipeline in collection.pipelines:
        check_pipeline(pipeline)


# --------------------------------------------------------------------------
# מסלול השיתוף
# --------------------------------------------------------------------------

FILE_ID = "0123456789abcdef01234567"
USER_ID = 4242


class _ShareCodeSnippets:
    def __init__(self):
        self.pipelines: list = []

    def find_one(self, *_a, **_k):
        return {
            "_id": ObjectId(FILE_ID),
            "user_id": USER_ID,
            "file_name": "demo.py",
            "programming_language": "python",
            "description": "",
            "code": "print(1)",
        }

    def aggregate(self, pipeline):
        self.pipelines.append(list(pipeline or []))
        return [{
            "file_name": "demo.py",
            "programming_language": "python",
            "description": "",
            "file_size": 8,
            "lines_count": 1,
            "snippet_preview": "print(1)",
        }]


class _InternalShares:
    def __init__(self):
        self.docs: list = []

    def create_index(self, *_a, **_k):
        return "idx"

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return type("_R", (), {"inserted_id": 1})()


class _ShareDB:
    def __init__(self, snippets):
        self.code_snippets = snippets
        self.internal_shares = _InternalShares()


def test_the_share_preview_pipeline_measures_text_in_code_points(monkeypatch):
    import webapp.app as wa

    snippets = _ShareCodeSnippets()
    monkeypatch.setattr(wa, "get_db", lambda: _ShareDB(snippets), raising=True)

    client = wa.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "Test"}
    resp = client.post(f"/api/share/{FILE_ID}", json={})

    # הראוט כולו עטוף ב-try/except → 500. סטטוס מפורש כדי שסטאב חסר יהיה
    # רועש ולא ייראה כמו ההתנהגות הנבדקת.
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert snippets.pipelines, "לא נלכד אף צינור בשיתוף"
    for pipeline in snippets.pipelines:
        check_pipeline(pipeline)


# --------------------------------------------------------------------------
# הבודק עצמו
# --------------------------------------------------------------------------


def test_the_checker_rejects_the_pipeline_that_shipped_the_bug():
    """בלי זה אפשר לרוקן את הבודק והסוויטה תישאר ירוקה."""
    buggy = [
        {"$addFields": {"_m": {"$regexFind": {"input": "$code", "regex": "x"}}}},
        {"$addFields": {
            "_has_code_match": {"$gt": [{"$strLenBytes": {"$ifNull": ["$_m.match", ""]}}, 0]},
            "_match_idx": {"$ifNull": ["$_m.idx", 0]},
            "_match_len": {"$strLenBytes": {"$ifNull": ["$_m.match", ""]}},
        }},
        {"$addFields": {"_snippet_start": {"$max": [0, {"$subtract": ["$_match_idx", 50]}]}}},
        {"$addFields": {
            "snippet_preview": {"$substrBytes": ["$code", "$_snippet_start", 200]},
            "file_size": {"$ifNull": ["$file_size", {"$strLenBytes": "$code"}]},
        }},
    ]
    with pytest.raises(AssertionError):
        assert_text_fields_use_code_points(buggy)
    with pytest.raises(AssertionError):
        assert_code_point_indices_never_meet_byte_operators(buggy)
    # ונעילת ההיקף דווקא **עוברת** על אותו צינור — היא לא אמורה להשתנות
    assert_file_size_is_still_bytes(buggy)


def test_the_scope_pin_rejects_a_widened_fix():
    """מי שיחליף גם את ``file_size`` יידע על כך מיד."""
    widened = [{"$addFields": {"file_size": {"$ifNull": ["$file_size", {"$strLenCP": "$code"}]}}}]
    with pytest.raises(AssertionError):
        assert_file_size_is_still_bytes(widened)
