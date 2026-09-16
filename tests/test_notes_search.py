"""בדיקות לחיפוש הפתקים בוובאפ.

**שתי שכבות, ובכוונה.**

*הצורה* של הצינור נבדקת על מה ש**אתר הקריאה שולח בפועל** ל-``aggregate``,
ולא על ערך ההחזרה של פונקציית הבנייה. אפשר לכתוב בונה נכון לחלוטין ולשכוח
לחבר אליו את הראוט, והבדיקה הייתה ירוקה — הלקח מתועד ב-
``tests/test_files_pipelines_drop_heavy_fields_early.py``, שנכתב אחרי
שבדיוק זה קרה.

*ההתנהגות* נבדקת מול מפרש קטן של שלבי האגרגציה שהצינור הזה משתמש בהם.
המפרש מדמה את **מונגו**, לא את מה שנוח: ``$substrCP`` חותך בתווים,
``$substrBytes`` חותך בבייטים **וזורק** כשהגבול נוחת באמצע תו, ורג'קס
בתוך ``$in`` מתנהג כמו ``$regex``. בלי הנאמנות הזו הבדיקות לא היו מסוגלות
ליפול על הבאגים שהן קיימות בשבילם.
"""

import re

import pytest

flask = pytest.importorskip("flask")

from sticky_notes_target import NOTE_COLOR_ORDER, NOTE_SEARCH_PREVIEW_CHARS  # noqa: E402


# --------------------------------------------------------------------------
# מפרש אגרגציה מינימלי — נאמן למונגו, לא נוח לבדיקה
# --------------------------------------------------------------------------

class _MongoLikeError(Exception):
    """מה שמונגו זורקת כשגבול חיתוך בבייטים נוחת באמצע תו UTF-8."""


_MISSING = object()


def _get_path(doc, path):
    cur = doc
    for part in str(path).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _evaluate(expr, doc):
    """הערכת ביטוי אגרגציה. מכיר רק את האופרטורים שהצינור הזה שולח."""
    if isinstance(expr, str) and expr.startswith("$"):
        value = _get_path(doc, expr[1:])
        return value
    if not isinstance(expr, dict):
        return expr

    (op, arg), = expr.items()

    if op == "$ifNull":
        first = _evaluate(arg[0], doc)
        return _evaluate(arg[1], doc) if first is _MISSING or first is None else first
    if op == "$literal":
        return arg
    if op == "$gt":
        left, right = _evaluate(arg[0], doc), _evaluate(arg[1], doc)
        return left > right
    if op == "$regexMatch":
        source = _evaluate(arg["input"], doc)
        if source is _MISSING:
            # מונגו דורשת מחרוזת; שדה חסר הוא שגיאה ולא ``false``. זו הסיבה
            # ש-``$ifNull`` עוטף את ``title`` בצינור האמיתי.
            raise _MongoLikeError("$regexMatch needs a string input")
        flags = re.IGNORECASE if "i" in str(arg.get("options") or "") else 0
        return re.search(arg["regex"], str(source), flags) is not None
    if op == "$strLenCP":
        return len(str(_evaluate(arg, doc)))
    if op == "$strLenBytes":
        return len(str(_evaluate(arg, doc)).encode("utf-8"))
    if op == "$substrCP":
        source = str(_evaluate(arg[0], doc))
        start, count = int(arg[1]), int(arg[2])
        return source[start:start + count]
    if op == "$substrBytes":
        # **בכוונה מדויק.** ``$substrBytes`` על גבול שנוחת באמצע אות עברית
        # מחזיר ``Location28657``, ולא טקסט קצוץ — ולכן מוטציה שמחליפה את
        # ``$substrCP`` בו **חייבת** להיכשל ולא "רק להיראות אחרת".
        raw = str(_evaluate(arg[0], doc)).encode("utf-8")
        start, count = int(arg[1]), int(arg[2])
        chunk = raw[start:start + count]
        try:
            return chunk.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _MongoLikeError(
                "Location28657: index is in the middle of a UTF-8 character"
            ) from exc
    raise NotImplementedError(f"אופרטור שאינו נתמך במפרש: {op}")


def _value_matches(value, condition):
    if isinstance(condition, re.Pattern):
        return isinstance(value, str) and condition.search(value) is not None
    if not isinstance(condition, dict) or not any(k.startswith("$") for k in condition):
        return value == condition

    for op, operand in condition.items():
        if op == "$exists":
            if (value is not _MISSING) != bool(operand):
                return False
        elif op == "$regex":
            flags = re.IGNORECASE if "i" in str(condition.get("$options") or "") else 0
            if not isinstance(value, str) or re.search(operand, value, flags) is None:
                return False
        elif op == "$options":
            continue
        elif op == "$in":
            if not any(_value_matches(value, alt) for alt in operand):
                return False
        elif op == "$eq":
            if value != operand:
                return False
        else:
            raise NotImplementedError(f"אופרטור שאילתה שאינו נתמך: {op}")
    return True


def _doc_matches(doc, query):
    for key, condition in query.items():
        if key == "$or":
            if not any(_doc_matches(doc, branch) for branch in condition):
                return False
        elif key == "$and":
            if not all(_doc_matches(doc, branch) for branch in condition):
                return False
        else:
            if not _value_matches(_get_path(doc, key), condition):
                return False
    return True


def _run_pipeline(docs, pipeline):
    rows = [dict(d) for d in docs]
    for stage in pipeline:
        (name, spec), = stage.items()
        if name == "$match":
            rows = [d for d in rows if _doc_matches(d, spec)]
        elif name == "$addFields":
            for row in rows:
                for field, expr in spec.items():
                    row[field] = _evaluate(expr, row)
        elif name == "$project":
            excluded = [k for k, v in spec.items() if not v]
            assert excluded and len(excluded) == len(spec), "המפרש תומך רק ב-$project בהחרגה"
            rows = [{k: v for k, v in d.items() if k not in excluded} for d in rows]
        elif name == "$sort":
            for field, direction in reversed(list(spec.items())):
                rows.sort(key=lambda d: _sort_key(d.get(field)), reverse=direction < 0)
        elif name == "$limit":
            rows = rows[:int(spec)]
        elif name == "$unset":
            drop = [spec] if isinstance(spec, str) else list(spec)
            rows = [{k: v for k, v in d.items() if k not in drop} for d in rows]
        else:
            raise NotImplementedError(f"שלב שאינו נתמך במפרש: {name}")
    return rows


def _sort_key(value):
    """סדר ה-BSON במידה שהצינור נשען עליה: ``false`` לפני ``true``."""
    if isinstance(value, bool):
        return (1, int(value))
    if value is None:
        return (0, 0)
    return (2, value)


# --------------------------------------------------------------------------
# סטאבים והתקנה
# --------------------------------------------------------------------------

class _StubNotes:
    def __init__(self, docs):
        self.docs = [dict(d) for d in docs]
        #: **כל צינור שנשלח בפועל** — זו הדלת שהמשתמש עובר בה.
        self.pipelines = []

    def aggregate(self, pipeline):
        self.pipelines.append(pipeline)
        return iter(_run_pipeline(self.docs, pipeline))


class _StubDB:
    def __init__(self, docs):
        self.sticky_notes = _StubNotes(docs)


USER = 7
OTHER_USER = 8

#: גוף עברי ארוך מ-200 **תווים** — כלומר מעל 400 בייטים.
LONG_HEBREW = "שורה של טקסט בעברית שנועדה להיות ארוכה מספיק כדי להיחתך. " * 8


def _note(**over):
    doc = {
        "_id": over.pop("_id", "a" * 24),
        "user_id": USER,
        "content": "תוכן",
        "color": "yellow",
        "board_id": "b1",
        "updated_at": 1,
    }
    doc.update(over)
    return doc


def _make_client(monkeypatch, docs):
    from webapp import sticky_notes_api

    db = _StubDB(docs)
    monkeypatch.setattr(sticky_notes_api, "get_db", lambda: db)
    monkeypatch.setattr(sticky_notes_api, "_ensure_indexes", lambda: None)

    app = flask.Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sticky_notes_api.sticky_notes_bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER
    client.db = db
    return client


@pytest.fixture
def client(monkeypatch):
    return _make_client(monkeypatch, [])


def _search(client, **params):
    from urllib.parse import urlencode
    return client.get("/api/sticky-notes/search?" + urlencode(params))


# --------------------------------------------------------------------------
# דירוג
# --------------------------------------------------------------------------

def test_a_match_in_the_title_outranks_a_newer_match_in_the_body(monkeypatch):
    """כותרת מנצחת גוף — **גם כשהפתק השני עודכן אחריו**.

    זו כל ההחלטה על הדירוג. הפתק שהמילה בגוף שלו נבחר כאן כעדכני יותר
    בכוונה: בלי ``_title_hit`` במיון, ``updated_at`` לבדו היה מעלה אותו
    לראש — כלומר מוטציה שמסירה את שדה הדירוג **מסדרת מחדש** ואינה רק
    מאבדת שדה.

    נופלת אם ``_title_hit`` יוסר מה-``$sort``, או אם כיוונו יתהפך.
    """
    client = _make_client(monkeypatch, [
        _note(_id="title-hit", title="פתק על מיגרציה", content="לא רלוונטי", updated_at=1),
        _note(_id="body-hit", content="כאן כתובה המילה מיגרציה בגוף", updated_at=99),
    ])

    body = _search(client, q="מיגרציה").get_json()

    assert [r["id"] for r in body["results"]] == ["title-hit", "body-hit"]


def test_within_the_same_group_the_newest_note_is_first(monkeypatch):
    """ובתוך כל קבוצה — לפי עדכון אחרון.

    נופלת אם ``updated_at`` ייעלם מהמיון או שכיוונו יתהפך.
    """
    client = _make_client(monkeypatch, [
        _note(_id="old", content="מיגרציה", updated_at=1),
        _note(_id="new", content="מיגרציה", updated_at=99),
    ])

    body = _search(client, q="מיגרציה").get_json()

    assert [r["id"] for r in body["results"]] == ["new", "old"]


# --------------------------------------------------------------------------
# הגוף אינו יוצא, והוא יורד לפני המיון
# --------------------------------------------------------------------------

def test_the_note_body_never_leaves_the_database(monkeypatch):
    """התשובה נושאת תצוגה מקדימה, **ולעולם לא את הגוף**.

    שתי טענות, ושתיהן נחוצות: שהשדה הוחרג בגבול המסד (ולא נשמט בסריאלייזר),
    ושהתוכן המלא אינו מופיע בשום מקום בתשובה.

    נופלת אם ``$project`` יוסר מהצינור.
    """
    client = _make_client(monkeypatch, [_note(content=LONG_HEBREW)])

    resp = _search(client, q="שורה")
    body = resp.get_json()

    stages = [next(iter(s)) for s in client.db.sticky_notes.pipelines[0]]
    assert "$project" in stages
    projected = client.db.sticky_notes.pipelines[0][stages.index("$project")]["$project"]
    assert projected == {"content": 0}

    assert "content" not in body["results"][0]
    assert LONG_HEBREW not in resp.get_data(as_text=True)


def test_the_body_is_dropped_before_the_sort(monkeypatch):
    """סדר השלבים: ``$project`` **לפני** ``$sort``.

    בסדר ההפוך מונגו החזירה בפרודקשן 292
    (``QueryExceededMemoryLimitNoDiskUseAllowed``) והקוד נפל למסלול איטי;
    ``allowDiskUse`` אינו מציל כי Atlas מתעלם ממנו ב-Flex. הבדיקה כאן היא
    על **הסדר**, ולא רק על הנוכחות, כי צינור שמכיל את שני השלבים בסדר הלא
    נכון עובר כל בדיקת נוכחות.

    נופלת אם ה-``$project`` יוזז אחרי המיון.
    """
    client = _make_client(monkeypatch, [_note()])
    _search(client, q="תוכן")

    stages = [next(iter(s)) for s in client.db.sticky_notes.pipelines[0]]
    assert stages.index("$project") < stages.index("$sort")


# --------------------------------------------------------------------------
# עברית: תווים, לא בייטים
# --------------------------------------------------------------------------

def test_the_preview_is_cut_in_characters_not_bytes(monkeypatch):
    """‏200 **תווים**, גם כשכל אות היא שני בייטים.

    זה ``amir-bug-patterns`` H6, והאירוע קרה בריפו הזה: אינדקס שנספר
    בתווים נכנס לאופרטור שמודד בבייטים, מונגו זרקה, והמשתמש קיבל "לא
    נמצאו תוצאות" על חיפוש שמעולם לא רץ.

    נופלת אם ``$substrCP`` יוחלף ב-``$substrBytes`` — המפרש זורק בדיוק
    כמו מונגו — וגם אם התקרה עצמה תשתנה.
    """
    client = _make_client(monkeypatch, [_note(content=LONG_HEBREW)])

    hit = _search(client, q="שורה").get_json()["results"][0]

    assert len(hit["preview"]) == NOTE_SEARCH_PREVIEW_CHARS
    assert hit["preview"] == LONG_HEBREW[:NOTE_SEARCH_PREVIEW_CHARS]
    assert hit["preview_truncated"] is True


def test_a_note_that_fits_in_characters_but_not_in_bytes_is_not_truncated(monkeypatch):
    """הגודל נמדד ב**תווים**, וזה נבדק בדיוק במרווח שבו שתי היחידות חלוקות.

    **המרווח הזה הוא כל הבדיקה.** פתק קצר סתם היה עובר גם על מדידה
    בבייטים — הגרסה הראשונה של הבדיקה הזו נכתבה כך, ומוטציה שהחליפה
    ``$strLenCP`` ב-``$strLenBytes`` **עברה אותה**. אות עברית היא שני
    בייטים, ולכן פתק של 150 תווים תופס 270 בייטים: הוא נכנס בתקרה של 200
    תווים ואינו נכנס בתקרה של 200 בייטים. רק שם ההבדל נראה.

    נופלת אם ``$strLenCP`` יוחלף ב-``$strLenBytes``, ואם ההשוואה תהפוך
    ל-``$gte``.
    """
    fits = "מילה " * 30
    assert len(fits) <= NOTE_SEARCH_PREVIEW_CHARS < len(fits.encode("utf-8")), (
        "התנאי המקדים: הפתק חייב לשבת **בין** שתי היחידות, אחרת הבדיקה "
        "אינה מסוגלת ליפול"
    )
    client = _make_client(monkeypatch, [_note(content=fits)])

    hit = _search(client, q="מילה").get_json()["results"][0]

    assert hit["preview"] == fits
    assert hit["preview_truncated"] is False


# --------------------------------------------------------------------------
# בעלות
# --------------------------------------------------------------------------

def test_another_users_note_is_never_returned(monkeypatch):
    """הפתק של מישהו אחר אינו חוזר — גם כשהמילה בו בדיוק.

    נופלת אם ``user_id`` יוסר מה-``$match``, או אם הוא יילקח מפרמטר
    בבקשה במקום מהסשן.
    """
    client = _make_client(monkeypatch, [
        _note(_id="mine", content="סוד משותף"),
        _note(_id="theirs", user_id=OTHER_USER, content="סוד משותף"),
    ])

    body = _search(client, q="סוד").get_json()

    assert [r["id"] for r in body["results"]] == ["mine"]
    assert client.db.sticky_notes.pipelines[0][0]["$match"]["user_id"] == USER


def test_a_user_id_in_the_query_string_is_ignored(monkeypatch):
    """ואי אפשר להחליף משתמש דרך ה-URL.

    נופלת אם מישהו יקרא ``request.args`` במקום ``session``.
    """
    client = _make_client(monkeypatch, [_note(_id="theirs", user_id=OTHER_USER, content="סוד")])

    body = _search(client, q="סוד", user_id=OTHER_USER).get_json()

    assert body["results"] == []


# --------------------------------------------------------------------------
# סינון צבע
# --------------------------------------------------------------------------

@pytest.mark.parametrize("stored", [
    "yellow", "#ffffcc", "#FFFFCC", "#FfFfCc", "#ffc", "#FFC", "#ffffccff", "#ffcf",
])
def test_the_colour_filter_catches_every_spelling(monkeypatch, stored):
    """כל צורת כתיבה של הצהוב — אותה תוצאה.

    **זה לא תיאורטי.** במסד היום 176 פתקים שמורים כ-``#FFFFCC`` באותיות
    גדולות, בעוד שהפלטה מחזיקה ``#ffffcc`` — כלומר סינון שמשווה למזהה
    בלבד היה מחזיר אפס, בלי שגיאה ובלי סימן.

    נופלת אם ה-``$in`` יוחלף בשוויון, ואם הרג'קס יאבד את הדגל ``i``.
    """
    client = _make_client(monkeypatch, [_note(content="מיגרציה", color=stored)])

    body = _search(client, q="מיגרציה", color="yellow").get_json()

    assert len(body["results"]) == 1, f"{stored!r} לא נתפס"


def test_the_colour_filter_does_not_catch_a_different_shade(monkeypatch):
    """ושני הצהובים נשארים נפרדים.

    ``#ffffba`` אינו צורת כתיבה של ``#ffffcc`` אלא צבע אחר בפלטה. רג'קס
    רחב מדי היה מאחד אותם ומחזיר תשובה שגויה דווקא כשהמסנן עובד.

    נופלת אם הרג'קס יאבד את העיגון או יתרחב.
    """
    client = _make_client(monkeypatch, [
        _note(_id="canonical", content="מיגרציה", color="#FFFFCC"),
        _note(_id="other", content="מיגרציה", color="#ffffba"),
    ])

    body = _search(client, q="מיגרציה", color="yellow").get_json()

    assert [r["id"] for r in body["results"]] == ["canonical"]


def test_the_colour_filter_is_an_and_not_an_or(monkeypatch):
    """הצבע מצטמצם, ואינו מוסיף.

    אילו הצבע היה נכנס כענף ב-``$or`` של המחטים, כל פתק צהוב היה חוזר גם
    בלי המילה. נופלת בדיוק על זה.
    """
    client = _make_client(monkeypatch, [
        _note(_id="word-and-colour", content="מיגרציה", color="yellow"),
        _note(_id="colour-only", content="משהו אחר לגמרי", color="yellow"),
    ])

    body = _search(client, q="מיגרציה", color="yellow").get_json()

    assert [r["id"] for r in body["results"]] == ["word-and-colour"]


def test_an_unknown_colour_is_refused_with_the_list_of_valid_ids(monkeypatch):
    """צבע שאינו בפלטה נדחה, **ורשימת החוקיים בתשובה**.

    מסנן שנשלח ולא הוחל הוא תשובה לשאלה אחרת. אותה הכרעה כבר מקודדת
    ב-``mcp_server/handlers`` עבור כתיבה.

    נופלת אם הערך יישמט בשקט, או אם הרשימה תיעלם מהתשובה.
    """
    client = _make_client(monkeypatch, [_note(content="מיגרציה")])

    resp = _search(client, q="מיגרציה", color="turquoise")

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "invalid_color"
    assert body["allowed"] == list(NOTE_COLOR_ORDER)
    assert client.db.sticky_notes.pipelines == [], "שאילתה לא הייתה אמורה לרוץ"


# --------------------------------------------------------------------------
# המחט עצמה
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_an_empty_query_is_refused_and_does_not_become_everything(monkeypatch, raw):
    """מחט ריקה אינה "הכול".

    רג'קס ריק תופס כל פתק, ומחט של רווחים תופסת כל פתק שיש בו רווח —
    כלומר תשובה לשאלה שלא נשאלה. ``_sanitize_text`` מסירה תווי בקרה ולא
    רווחים, ולכן ה-``.strip()`` בראוט הוא מה שמפריד בין השניים.

    נופלת אם ה-``.strip()`` יוסר, או אם הבדיקה תוחלף ב"שלח בכל מקרה".
    """
    client = _make_client(monkeypatch, [_note()])

    resp = _search(client, q=raw)

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "empty_query"
    assert client.db.sticky_notes.pipelines == [], "שאילתה לא הייתה אמורה לרוץ"


@pytest.mark.parametrize("needle,stored,expected", [
    ("config.py", "ראו config.py", 1),
    ("config.py", "ראו configXpy", 0),
    ("a(", "הביטוי a( נשבר", 1),
])
def test_regex_metacharacters_in_the_query_are_literal(monkeypatch, needle, stored, expected):
    """מה שהמשתמש הקליד הוא טקסט, לא דפוס.

    בלי ``re.escape``, ``config.py`` היה תופס גם ``configXpy``, ו-``a(``
    היה מפיל את מונגו בשגיאת פרסור.

    נופלת אם ``re.escape`` יוסר מהפילטר או מ-``$regexMatch``.
    """
    client = _make_client(monkeypatch, [_note(content=stored)])

    body = _search(client, q=needle).get_json()

    assert len(body["results"]) == expected


def test_a_note_without_a_title_is_found_and_does_not_break_the_ranking(monkeypatch):
    """פתק בלי שם — הרוב במסד — נמצא, ואינו מפיל את הדירוג.

    ``title`` אינו קיים כשדה ברוב המסמכים, ו-``$regexMatch`` על שדה חסר
    זורק במונגו במקום להחזיר ``false``. ``$ifNull`` הוא מה שמונע את זה.

    נופלת אם ה-``$ifNull`` סביב ``$title`` יוסר — המפרש זורק בדיוק כמו
    מונגו.
    """
    client = _make_client(monkeypatch, [_note(_id="untitled", content="מילה בגוף בלבד")])

    resp = _search(client, q="מילה")

    assert resp.status_code == 200
    body = resp.get_json()
    assert [r["id"] for r in body["results"]] == ["untitled"]
    assert body["results"][0]["title"] == ""


# --------------------------------------------------------------------------
# תקרות
# --------------------------------------------------------------------------

def test_the_limit_is_capped_however_large_the_request(monkeypatch):
    """‏``limit`` מגיע מה-URL, ולכן הוא נחסם.

    בלי תקרה בקשה אחת גוררת את כל מכסת המשתמש לתוך המיון ולתוך התשובה.

    נופלת אם החסם העליון יוסר.
    """
    from webapp import sticky_notes_api

    client = _make_client(monkeypatch, [_note()])
    _search(client, q="תוכן", limit=100000)

    stages = {next(iter(s)): s for s in client.db.sticky_notes.pipelines[0]}
    assert stages["$limit"]["$limit"] == sticky_notes_api.NOTE_SEARCH_MAX_LIMIT + 1


@pytest.mark.parametrize("raw", ["abc", "0", "-5", ""])
def test_a_nonsense_limit_falls_back_and_does_not_fail_the_request(monkeypatch, raw):
    """‏``?limit=abc`` הוא ברירת מחדל, לא 500.

    נופלת אם ה-``int()`` יישאר חשוף, או אם הערכים הלא חוקיים יעברו.
    """
    from webapp import sticky_notes_api

    client = _make_client(monkeypatch, [_note()])
    resp = _search(client, q="תוכן", limit=raw)

    assert resp.status_code == 200
    stages = {next(iter(s)): s for s in client.db.sticky_notes.pipelines[0]}
    assert stages["$limit"]["$limit"] == sticky_notes_api.NOTE_SEARCH_DEFAULT_LIMIT + 1


def test_the_sentinel_row_reports_truncation_and_is_not_returned(monkeypatch):
    """שורת הסנטינל היא **ראיה** שיש עוד, ואינה נספרת בתשובה.

    ``limit + 1`` נשלח, והשורה הנוספת נחתכת בפייתון. ספירה ששווה לתקרה
    היא ניחוש; שורה שחזרה היא עובדה.

    נופלת אם ה-``+ 1`` יוסר, או אם השורה הנוספת תדלוף לתשובה.
    """
    docs = [_note(_id=f"n{i}", content="מיגרציה", updated_at=i) for i in range(5)]
    client = _make_client(monkeypatch, docs)

    body = _search(client, q="מיגרציה", limit=3).get_json()

    assert body["truncated"] is True
    assert body["count"] == 3
    assert len(body["results"]) == 3


def test_no_truncation_flag_when_everything_fits(monkeypatch):
    """וכשהכול נכנס — אין "יש עוד".

    נופלת אם ``truncated`` ייגזר מהשוואה לתקרה במקום מהשורה הנוספת.
    """
    docs = [_note(_id=f"n{i}", content="מיגרציה", updated_at=i) for i in range(3)]
    client = _make_client(monkeypatch, docs)

    body = _search(client, q="מיגרציה", limit=3).get_json()

    assert body["truncated"] is False
    assert body["count"] == 3


# --------------------------------------------------------------------------
# זהות התוצאה
# --------------------------------------------------------------------------

def test_the_result_links_through_the_single_permalink_builder(monkeypatch):
    """הקישור הוא ``/note/<id>`` ואינו מורכב משדות היעד.

    ``boards_ui.note_permalink`` הוא הבונה היחיד, והוא מכיר את שלושת
    הסוגים. צרכן שמרכיב URL בעצמו הוא בדיוק מה שהפונקציה ההיא נכתבה כדי
    לבטל — ופתק לוח, שאין לו ``file_id``, היה נוחת בשורש האתר.

    נופלת אם מישהו יחזור לבנות ``/md/<file_id>`` כאן.
    """
    client = _make_client(monkeypatch, [
        _note(_id="b" * 24, content="מיגרציה", board_id="brd"),
    ])

    hit = _search(client, q="מיגרציה").get_json()["results"][0]

    assert hit["url"] == "/note/" + "b" * 24
    assert hit["target"] == "board"


def test_a_legacy_colour_is_reported_as_itself_and_not_as_a_palette_id(monkeypatch):
    """צבע שאינו בפלטה מוצג כמות שהוא, ו-``color_id`` ריק.

    נופלת אם ``note_color_id`` יתחיל להמציא מזהה לגוון שאינו בפלטה.
    """
    client = _make_client(monkeypatch, [_note(content="מיגרציה", color="#AABBCC")])

    hit = _search(client, q="מיגרציה").get_json()["results"][0]

    assert hit["color"] == "#aabbcc"
    assert hit["color_id"] == ""
