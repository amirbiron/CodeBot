"""מפת סימבולים ב-``codekeeper_get_repo_file``.

הרקע: ``webapp/app.py`` הוא 20,035 שורות. בלי מפה, סוכן שמחפש בו פונקציה
קורא טווח ומנחש. עם מפה הוא מקבל שורת התחלה וסיום ועובר ל-``lines=``.
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import subprocess
import sys
import time
import tokenize
from collections import Counter

import pytest

from mcp_server import repo_handlers
from mcp_server.outline import extract_outline

# ---------------------------------------------------------------------------
# כלל מרחב השמות
#
# מרחב שמות בפייתון הוא פונקציה או מחלקה. ``if``/``try``/``with`` אינם.
# הכלל הזה החליף שלושה מקרים פרטיים — מתודות, פונקציות מקוננות, ומחלקות
# fallback בתוך ``except ImportError`` — והוא מה שהופך את המפה לשלמה.
# ---------------------------------------------------------------------------


def _names(text, **kw):
    return [row["name"] for row in extract_outline(text, "x.py", **kw)["symbols"]]


def _names_of(result):
    """השמות מתוך תשובה של ``extract_outline`` שכבר נקראה על נתיב אחר."""
    return [row["name"] for row in result["symbols"]]


def test_a_nested_function_is_prefixed_by_the_function_that_holds_it():
    """``build_mcp`` ב-``mcp_server/server.py`` מכילה 24 כלים מקוננים.

    בלי ירידה לעומק, אאוטליין של הקובץ הזה החזיר 9 סימבולים במקום 38,
    ו-``build_mcp`` נראתה כבלוק אטום של 513 שורות. סוכן שביקש מפה כדי
    למצוא כלי לערוך — קיבל מפה שהכלי לא נמצא בה.
    """
    assert _names("def outer():\n    def inner():\n        pass\n") == [
        "outer",
        "outer.inner",
    ]


def test_a_method_is_the_same_rule_at_depth_two():
    assert _names("class C:\n    def m(self):\n        pass\n") == ["C", "C.m"]


def test_a_control_block_is_not_a_namespace_and_adds_no_prefix():
    """זה הפער השני, ונמצא רק אחרי שהראשון תוקן.

    רקורסיה שיורדת רק לתוך גופי פונקציות ומחלקות עדיין החמיצה 62
    סימבולים ב-``webapp/app.py``, כי ``_Missing``, ``_NoCache`` ו-
    ``_NativeThread`` מוגדרות בתוך ``except ImportError`` — דפוס
    ה-fallback הרגיל. ``try`` אינו מרחב שמות, ולכן אין תחילית.
    """
    text = (
        "try:\n"
        "    from x import Thing\n"
        "except ImportError:\n"
        "    class Thing:\n"
        "        def method(self):\n"
        "            pass\n"
    )

    assert _names(text) == ["Thing", "Thing.method"]


@pytest.mark.parametrize(
    "block", ["if True:", "with open('f') as f:", "for i in []:", "while True:"]
)
def test_no_control_block_introduces_a_namespace(block):
    assert _names(f"{block}\n    def f():\n        pass\n") == ["f"]


def test_an_async_function_is_a_symbol_like_any_other():
    assert _names("async def f():\n    async def g():\n        pass\n") == [
        "f",
        "f.g",
    ]


# ---------------------------------------------------------------------------
# המונה הבלתי תלוי
#
# ``ast.walk`` הוא אותה ספרייה שהמימוש משתמש בה, ולכן השוואה מולו קרובה
# מדי להשוואת פונקציה לעצמה. ``tokenize`` הוא **לקסר**: הוא לא בונה עץ,
# הוא סופר אסימונים בזרם התווים. זה מונה שנגזר ממקור אחר לגמרי.
# ---------------------------------------------------------------------------


def _count_definitions_by_tokenize(text: str) -> int:
    return sum(
        1
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.NAME and token.string in ("def", "class")
    )


#: **הנתיבים נגזרים מהקובץ הזה ולא מספריית העבודה.** כשהם היו יחסיים,
#: הרצה מספרייה אחרת לא נכשלה — היא **דילגה**: נמדד, 124 עוברים ו-17
#: מדולגים במקום 141, והחבילה דיווחה ירוק. בין המדולגים היו שלושת המונים
#: שרצים על כל התבניות, כלומר כל ההגנה על הבאגים שתוקנו כאן נעלמה בשקט.
#: זו המוסכמה שכבר קיימת בריפו, ראו ``tests/test_dashboard_admin_repos.py``.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

_REAL_FILES = [
    "mcp_server/server.py",
    "mcp_server/repo_backend.py",
    "database/manager.py",
    "webapp/app.py",
    "main.py",
]


@pytest.mark.parametrize("relative", _REAL_FILES)
def test_the_outline_finds_every_definition_in_a_real_file(relative):
    """הבדיקה שהייתה תופסת את שני הפערים מלכתחילה.

    היא רצה על קבצי הריפו עצמם ולא על דוגמאות, כי שני הפערים התגלו
    דווקא במבנים שקיימים כאן ולא במבנים שחשבתי עליהם.
    """
    path = _REPO_ROOT / relative
    if not path.exists():  # pragma: no cover - הריפו תמיד מכיל אותם
        pytest.skip(f"{relative} לא קיים")
    text = path.read_text(encoding="utf-8")

    found = extract_outline(text, relative)

    assert found["total"] == _count_definitions_by_tokenize(text), relative


def test_the_independent_counter_can_actually_fail():
    """מונה שלא מסוגל להפיל מימוש שגוי אינו ראיה.

    הגרסה שירדה רק לתוך גופי פונקציות מוצגת כאן במפורש, ו-``tokenize``
    סופר יותר ממה שהיא מוצאת.
    """
    text = (
        "try:\n"
        "    class Stub:\n"
        "        def m(self):\n"
        "            pass\n"
        "except ImportError:\n"
        "    Stub = None\n"
    )

    shallow = [n for n in ast.parse(text).body if isinstance(n, ast.ClassDef)]

    assert shallow == []  # ``class`` יושבת בתוך ``try``, לא ב-``body``
    assert _count_definitions_by_tokenize(text) == 2
    assert extract_outline(text, "x.py")["total"] == 2


# ---------------------------------------------------------------------------
# מעטרים
# ---------------------------------------------------------------------------


def test_the_range_starts_at_the_decorator_and_not_at_the_def():
    """ב-``webapp/app.py`` 203 מתוך 408 הפונקציות ברמה העליונה מעוטרות.

    ``node.lineno`` מצביע על ה-``def``, ולכן טווח שנקרא לפי האאוטליין היה
    מתחיל שורה אחרי ``@app.route(...)`` — כלומר מחמיץ בדיוק את מה שמזהה
    את הנתיב.
    """
    text = "@app.route('/x')\n@wraps(f)\ndef view():\n    pass\n"

    symbols = extract_outline(text, "x.py")["symbols"]

    assert symbols[0]["start"] == 1
    assert symbols[0]["end"] == 4


# ---------------------------------------------------------------------------
# שמות אינם ייחודיים
# ---------------------------------------------------------------------------


def test_two_symbols_may_share_a_full_name_and_both_survive():
    """נגזרת ישירה של כלל מרחב השמות: ``if``/``else`` אינם מרחב.

    זה לא תרחיש מומצא — ב-``webapp/app.py`` וב-``main.py`` יש היום שישה
    מקרים כאלה, למשל ``login_required.decorated_function`` בשורות 3448
    ו-3465. כל שלב שיחזיק את הסימבולים ב-dict לפי שם ימחק אחד מהם בשקט.
    """
    text = (
        "import sys\n"
        "if sys.version_info >= (3, 11):\n"
        "    def parse():\n"
        "        pass\n"
        "else:\n"
        "    def parse():\n"
        "        pass\n"
    )

    symbols = extract_outline(text, "x.py")["symbols"]

    assert [row["name"] for row in symbols] == ["parse", "parse"]
    assert [row["start"] for row in symbols] == [3, 6]


def test_real_duplicate_names_in_the_repo_are_not_collapsed():
    """כל שם כפול מוחזר במספר המופעים המלא שלו.

    הטסט נגזר מהסימבולים עצמם ולא ננעל על שם ספציפי: ``app.py`` משתנה,
    והתכונה שנבדקת היא שאף שלב לא ממפתח לפי שם — לא איזה שם במקרה כפול.
    """
    path = _REPO_ROOT / "webapp" / "app.py"
    if not path.exists():  # pragma: no cover
        pytest.skip("webapp/app.py לא קיים")

    text = path.read_text(encoding="utf-8")
    symbols = extract_outline(text, "webapp/app.py")["symbols"]

    # העוגן הבלתי תלוי. הגרסה הקודמת של הטסט הזה גזרה גם את הציפייה וגם
    # את הבדיקה מאותה רשימה, ולכן ``len(rows) == occurrences`` היה
    # טאוטולוגיה: קריסה **חלקית** — שם כפול אחד שנעלם ואחר שנשאר — הייתה
    # עוברת. הספירה מול ה-לקסר היא מה שתופס כל קריסה, מלאה או חלקית.
    assert len(symbols) == _count_definitions_by_tokenize(text)

    repeated = {name: n for name, n in Counter(r["name"] for r in symbols).items() if n > 1}

    assert repeated, "אין שמות כפולים — הטסט מאבד את מה שהוא בודק"
    for name in repeated:
        starts = {row["start"] for row in symbols if row["name"] == name}
        assert len(starts) == repeated[name]


# ---------------------------------------------------------------------------
# הסדר, ומה שהעימוד נשען עליו
# ---------------------------------------------------------------------------


def test_symbols_are_ordered_by_start_line():
    text = "def b():\n    pass\n\n\ndef a():\n    pass\n"

    starts = [row["start"] for row in extract_outline(text, "x.py")["symbols"]]

    assert starts == sorted(starts)


def test_the_order_is_stable_across_calls():
    """עימוד בלי סדר יציב הוא באג ממתין: סימבול יכול לדלג בין עמודים."""
    path = _REPO_ROOT / "webapp" / "app.py"
    if not path.exists():  # pragma: no cover
        pytest.skip("webapp/app.py לא קיים")
    text = path.read_text(encoding="utf-8")

    first = extract_outline(text, "webapp/app.py")["symbols"]
    second = extract_outline(text, "webapp/app.py")["symbols"]

    assert first == second


# ---------------------------------------------------------------------------
# ``symbol=`` — החוזה
# ---------------------------------------------------------------------------


def test_the_filter_matches_the_full_name_so_a_namespace_returns_its_children():
    """``symbol="C"`` מחזיר גם את המחלקה וגם את מה שבתוכה.

    זו התנהגות מכוונת — "תן לי הכול תחת המרחב הזה" — ולכן היא מקובעת
    ולא נשארת תופעת לוואי של התאמת תת-מחרוזת.
    """
    text = "class Outer:\n    def inner(self):\n        pass\n\n\ndef other():\n    pass\n"

    assert _names(text, symbol="Outer") == ["Outer", "Outer.inner"]


def test_the_filter_is_case_insensitive():
    assert _names("def ApiHandler():\n    pass\n", symbol="apihandler") == ["ApiHandler"]


def test_total_counts_matches_and_not_the_whole_file():
    """העימוד נשען על ``total``. אם הוא סופר את הקובץ ולא את ההתאמות,
    הקורא יבקש עמוד שני שלא קיים."""
    text = "def alpha():\n    pass\n\n\ndef beta():\n    pass\n\n\ndef gamma():\n    pass\n"

    assert extract_outline(text, "x.py")["total"] == 3
    assert extract_outline(text, "x.py", symbol="alpha")["total"] == 1


# ---------------------------------------------------------------------------
# ערוץ הכשל
# ---------------------------------------------------------------------------


def test_a_non_python_file_says_so_instead_of_returning_nothing():
    assert extract_outline("Title\n=====\n", "docs/page.rst") == {
        "status": "no_outline",
        "reason": "unsupported_language",
    }


@pytest.mark.parametrize(
    "text",
    [
        "def f(:\n    pass\n",       # תחביר שבור
        "print 'hello'\n",           # פייתון 2
        "def f():\n    x = '\ud800'\n",  # surrogate — UnicodeEncodeError, לא SyntaxError
    ],
)
def test_unparsable_input_is_reported_and_never_raised(text):
    """``except SyntaxError`` לבדו היה מפיל את הכלי על השלישי.

    סוג החריגה תלוי-גרסה: בייט אפס הוא ``SyntaxError`` ב-3.11
    ו-``ValueError`` במקומות אחרים. מניית סוגים היא הגישה השברירית, ולכן
    ההרחבה גורפת — אבל **רק** סביב הפרסינג.
    """
    result = extract_outline(text, "x.py")

    assert result["status"] == "no_outline"
    assert result["reason"] == "parse_error"
    assert result["error_type"]


def test_the_reason_names_the_exception_class():
    """``except`` רחב בלי שם המחלקה הורג את היכולת לאבחן."""
    result = extract_outline("def f():\n    x = '\ud800'\n", "x.py")

    assert result["error_type"] == "UnicodeEncodeError"


def test_a_bug_in_the_traversal_is_not_swallowed_as_no_outline(monkeypatch):
    """ההרחבה עוטפת את הפרסינג בלבד, ובכוונה.

    אילו היא עטפה את כל הפונקציה, ``AttributeError`` על צומת לא צפוי היה
    חוזר כ-``no_outline`` וקובץ תקין היה נראה כאילו אין לו סימבולים —
    בדיוק הכישלון השקט של K11, שכבה אחת פנימה.

    ``_collect`` עברה ל-``outline_scanners.python`` כשהחילוץ פוצל לסורק
    לכל שפה. **הטענה לא השתנתה** — רק כתובת המטרה של ה-monkeypatch.
    """
    import mcp_server.outline as module
    import mcp_server.outline_scanners.python as scanner

    def _explode(_tree, _lines):
        raise AttributeError("boom")

    monkeypatch.setattr(scanner, "_collect", _explode)

    with pytest.raises(AttributeError):
        module.extract_outline("def f():\n    pass\n", "x.py")


def test_a_file_the_router_does_not_recognise_never_reaches_a_scanner(monkeypatch):
    """הראוטר מכריע לפי הסיומת, ולא מנסה לפרוס ונופל.

    זו ההבחנה שקל לאבד: מימוש שקורא לסורק הפייתון תמיד ומסתמך על
    ``SyntaxError`` כדי להחזיר ``unsupported_language`` נראה עובד — עד
    שקובץ CSS **כן** נפרס במקרה כפייתון תקין (``a{}`` אינו, אבל
    ``# comment`` הוא), ואז מוחזרת מפה ריקה עם ``status: ok`` במקום
    הצהרה שהשפה לא נתמכת.

    הסורק מוחלף כאן במלכודת שזורקת: אם הראוטר נגע בו על ``.css``, הטסט
    נופל בקול במקום להחזיר את התשובה הנכונה במקרה.
    """
    import mcp_server.outline as module
    import mcp_server.outline_scanners.python as scanner

    def _trap(_text):
        raise AssertionError("סורק הפייתון נקרא על קובץ שאינו פייתון")

    monkeypatch.setattr(scanner, "extract", _trap)
    monkeypatch.setitem(module._SCANNERS, ".py", _trap)

    assert module.extract_outline("x{}", "styles.css") == {
        "status": "no_outline",
        "reason": "unsupported_language",
    }

    # ואותה מלכודת **כן** נתפסת על ``.py``, אחרת הטסט היה עובר גם על
    # ראוטר שלא קורא לאף סורק לעולם.
    with pytest.raises(AssertionError):
        module.extract_outline("x{}", "mod.py")


def test_the_router_sorts_what_a_scanner_hands_it_back_unsorted():
    """המיון הוא חוזה חוצה-מודולים, ועד עכשיו לא היה לו טסט.

    ``_collect`` עובר על העץ עם מחסנית LIFO, ולכן מה שהוא מחזיר **אינו**
    ממוין: סימבול מקונן חוזר אחרי אח שמופיע אחריו בקובץ. על
    ``webapp/app.py`` זה 523 מתוך 526 סימבולים מחוץ למקום, ועמוד ראשון
    שמכיל שמות אחרים לגמרי.

    הטסטים הקיימים לא יכלו לתפוס את זה: ``test_symbols_are_ordered_by_start_line``
    משתמש בשתי הגדרות ברמה העליונה, שהסדר הגולמי שלהן כבר ממוין;
    ``test_the_order_is_stable_across_calls`` משווה שתי קריאות לפונקציה
    טהורה ודטרמיניסטית, ולכן עובר גם בלי מיון בכלל. נמדד: מחיקת שורת
    ``rows.sort`` משאירה את כל 64 הטסטים ירוקים.

    הקלט כאן הוא המינימלי שבו הסדר הגולמי שונה מהממוין: ``[1, 6, 2]``
    מול ``[1, 2, 6]``.
    """
    from mcp_server.outline_scanners.python import extract

    text = "def outer():\n    def inner():\n        pass\n\n\ndef top():\n    pass\n"

    # העוגן הבלתי תלוי: הסורק **באמת** מחזיר לא-ממוין. בלי הקביעה הזו
    # הטסט היה עלול לעבור על קלט שממילא מגיע ממוין, ואז הוא לא בודק כלום.
    raw = [row["start"] for row in extract(text)["symbols"]]
    assert raw != sorted(raw), "הקלט מגיע ממוין — הטסט מאבד את מה שהוא בודק"

    ordered = extract_outline(text, "x.py")["symbols"]

    assert [row["start"] for row in ordered] == [1, 2, 6]
    assert [row["name"] for row in ordered] == ["outer", "outer.inner", "top"]


def test_the_longest_matching_suffix_wins_and_not_the_first_registered():
    """הכלל קיים בשביל סיומת מורכבת שעוד לא נוספה, ולכן הוא לא מוגן מאליו.

    עם הטבלה של היום התוצאה זהה בכל סדר, כי ``.py`` אינו סיומת של
    ``.pyi``. כלומר מי ש"יפשט" את הלולאה חזרה לאיטרציה רגילה על המילון
    לא יראה שום טסט נופל — ואז ``.html.j2`` ינותב לסורק של ``.j2``
    בשקט. הטסט רושם שתי סיומות חופפות ומקבע את הכלל בזמן שהוא עוד זול.
    """
    import mcp_server.outline as module

    monkey = {".j2": lambda _t: {"symbols": [{"name": "generic", "start": 1, "end": 1}]},
              ".html.j2": lambda _t: {"symbols": [{"name": "specific", "start": 1, "end": 1}]}}

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module, "_SCANNERS", monkey)

        assert _names_of(module.extract_outline("x", "page.html.j2")) == ["specific"]
        assert _names_of(module.extract_outline("x", "page.j2")) == ["generic"]


@pytest.mark.parametrize(
    "shape",
    [
        {"status": "error", "reason": "tree_sitter_missing"},  # status שאינו בחוזה
        {},                                                     # מילון בלי כלום
        {"symbols": None},                                      # המפתח קיים, הערך לא
        None,                                                   # לא מילון בכלל
        [],                                                     # ולא רצף
    ],
    ids=["other-status", "empty-dict", "symbols-is-none", "none", "list"],
)
def test_a_scanner_returning_a_shape_outside_the_contract_fails_loudly(shape):
    """סורק שבור נופל בקול ועם אבחון — לא ב-``KeyError`` סתום.

    הבדיקה הקודמת הייתה ``status == "no_outline"`` ואז ``result["symbols"]``,
    כלומר היא כיסתה בדיוק את שתי הצורות שהיו קיימות. צורה שלישית הפילה
    ``KeyError('symbols')`` או ``AttributeError`` — ו**שום שלב במסלול לא
    עוטף בחריגה**: לא ``_outline_response`` ולא ``RepoBackend.get_file``.
    כלומר החריגה הייתה בורחת דרך הכלי, בלי לומר מי הסורק ומה הוא החזיר.

    הבחירה היא ליפול, לא לבלוע: קלט פגום חוזר כערך, באג שלנו נופל. מה
    שהיה חסר הוא האבחון, ולכן נבדק גם שההודעה נוקבת בנתיב.
    """
    import mcp_server.outline as module

    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(module._SCANNERS, ".py", lambda _t: shape)

        with pytest.raises(TypeError, match="mod.py"):
            module.extract_outline("x", "mod.py")


@pytest.mark.parametrize(
    ("label", "shape"),
    [
        ("no-end", {"symbols": [{"name": "f", "start": 1}]}),
        ("no-start", {"symbols": [{"name": "f", "end": 3}]}),
        ("no-name", {"symbols": [{"start": 1, "end": 3}]}),
        ("start-is-str", {"symbols": [{"name": "f", "start": "1", "end": 3}]}),
        ("end-is-none", {"symbols": [{"name": "f", "start": 1, "end": None}]}),
        ("row-is-not-a-dict", {"symbols": ["oops"]}),
        ("no-outline-without-reason", {"status": "no_outline"}),
    ],
)
def test_a_malformed_symbol_record_is_caught_before_it_reaches_the_client(label, shape):
    """הבדיקה על **תוכן** הרשימה, ולא רק על כך שהיא רשימה.

    הבדיקה החיצונית לבדה עצרה שלוש צורות ופספסה את הרביעית, שהיא
    החמורה מכולן: נמדד שרשומה **בלי** ``end`` עברה את כל המסלול והגיעה
    ללקוח כ-``{"ok": true, "status": "outline", "symbols": [{"name": "f",
    "start": 1}]}`` — תשובה שנראית שלמה לגמרי. ה-``sort`` נוגע רק ב-
    ``start`` וב-``name``, ולכן ``end`` לא נבדק בשום מקום לאורך המסלול,
    והוא בדיוק השדה שכל הפיצ'ר קיים בשבילו: ממנו נגזר ה-``lines=`` הבא.

    השאר נפלו ב-``KeyError`` או ב-``TypeError`` סתומים שלא אמרו איזו
    רשומה פגומה. עכשיו כולן עוברות באותו אבחון, עם המקום ברשימה.
    """
    import mcp_server.outline as module

    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(module._SCANNERS, ".py", lambda _t, _v=shape: _v)

        with pytest.raises(TypeError, match="mod.py"):
            module.extract_outline("x", "mod.py")


def test_the_diagnostic_names_which_record_is_malformed_and_not_only_that_one_is():
    """אבחון שלא אומר איפה הבעיה הוא KeyError עם ניסוח יפה יותר.

    על קובץ אמיתי יש מאות רשומות. "משהו לא בסדר" בלי מיקום היה משאיר
    את הקורא לחפש ידנית, וזו בדיוק הסיבה שהמסלול הזה זורק ולא בולע.
    """
    import mcp_server.outline as module

    rows = [{"name": f"f{i}", "start": i, "end": i} for i in range(5)]
    rows[3] = {"name": "broken", "start": 3}  # חסר end

    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(module._SCANNERS, ".py", lambda _t: {"symbols": rows})

        with pytest.raises(TypeError) as caught:
            module.extract_outline("x", "mod.py")

    assert "3" in str(caught.value)
    assert "broken" in str(caught.value)


def test_the_two_shapes_the_contract_does_allow_are_not_rejected():
    """הצד השני של אותו חוזה, ובטסט נפרד ובכוונה.

    ``{"status": "no_outline", ...}`` היא צורה **חוקית**, ולכן היא לא
    שייכת לרשימת הצורות הפסולות שלמעלה — טסט ששמו "נופל בקול" שמכיל
    מקרה שאינו אמור ליפול הוא טסט ששמו סותר את מה שהוא בודק. האכיפה
    שנוספה כאן אסור לה להדק יותר מדי ולדחות כשל לגיטימי של סורק.
    """
    import mcp_server.outline as module

    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(
            module._SCANNERS, ".py",
            lambda _t: {"status": "no_outline", "reason": "parse_error", "line": 7},
        )

        assert module.extract_outline("x", "mod.py") == {
            "status": "no_outline",
            "reason": "parse_error",
            "line": 7,
        }

    with pytest.MonkeyPatch.context() as patch:
        # רשימה ריקה של סימבולים היא הצלחה, לא כשל: קובץ פייתון תקין
        # בלי אף הגדרה הוא מקרה אמיתי ונפוץ.
        patch.setitem(module._SCANNERS, ".py", lambda _t: {"symbols": []})

        assert module.extract_outline("x", "mod.py") == {
            "status": "ok",
            "symbols": [],
            "total": 0,
        }


def test_a_lone_carriage_return_is_refused_instead_of_raising_indexerror():
    """שתי הגדרות של "שורה" שנפרדות, וסירוב מפורש במקום מפה שקרית.

    ``ast.parse`` סופר עם universal newlines ולכן ``\\r`` בודד הוא אצלו
    שורה חדשה; ``apply_line_range`` מפצל ב-``split("\\n")``, וההערה שם
    מנמקת למה — ``file.lines_count`` נספר כך ומשותף עם הוובאפ.

    נמדד על הקלט הזה לפני התיקון: ``ast`` דיווח על ``def`` בשורה 5 בטקסט
    ש-``split("\\n")`` רואה כשורה **אחת**, ו-``_start_line`` נפל ב-
    ``IndexError`` שבורח דרך הכלי — אף שלב במסלול לא עוטף בחריגה.

    התיקון אינו רק להימנע מהנפילה: מפה שהייתה חוזרת עם שורה 5 מצביעה
    למקום ש-``lines=[5, 6]`` לא מגיע אליו, וזה הערך היחיד של המפה.
    """
    text = "x = 1\rx = 2\rx = 3\r@deco\rdef f():\r    pass\r"

    # העוגן הבלתי תלוי: השתיים באמת חלוקות על הקלט הזה. בלי הקביעה הזו
    # הטסט היה עלול לעבור על קלט שאין בו מחלוקת מלכתחילה.
    assert len(text.split("\n")) == 1
    assert ast.parse(text).body[-1].lineno == 5

    assert extract_outline(text, "x.py") == {
        "status": "no_outline",
        "reason": "inconsistent_line_endings",
    }


def test_crlf_is_not_refused_because_both_counts_agree_on_it():
    """הצד השני, ובטסט נפרד: CRLF הוא המקרה הנפוץ וחייב להמשיך לעבוד.

    סירוב גורף לכל ``\\r`` היה מבטל את האאוטליין לכל קובץ שנוצר ב-Windows
    — ובלי שום סיבה, כי שם ``split("\\n")`` ו-``ast`` מספרים את אותן
    שורות בדיוק. ההבחנה היא ``\\r`` בודד, לא ``\\r`` בכלל.
    """
    text = "x = 1\r\nx = 2\r\n@deco\r\ndef f():\r\n    pass\r\n"

    # העוגן: השורה ש-``ast`` מצביע עליה היא אותה שורה גם ב-``split("\n")``.
    # זו ההסכמה עצמה, ולא נגזרת ממנה.
    definition = ast.parse(text).body[-1]
    assert text.split("\n")[definition.lineno - 1].strip() == "def f():"

    found = extract_outline(text, "x.py")

    assert found["status"] == "ok"
    assert found["symbols"] == [{"name": "f", "start": 3, "end": 5}]


def test_the_outline_never_points_at_a_line_the_range_read_cannot_reach():
    """המאפיין שמאחורי הסירוב, ולא רק הסירוב עצמו.

    זו הסיבה שהטסט הזה קיים בנוסף לשניים שמעליו: הם מקבעים את ההתנהגות,
    והוא מקבע את **הטענה** — כל שורה שהמפה מחזירה חייבת להיות שורה
    שקריאת טווח יכולה להגיע אליה, כי אחרת המפה חסרת ערך. הוא ייכשל על
    כל מימוש עתידי שיבחר "לתקן" את ה-``IndexError`` בלי לפתור את
    אי-ההסכמה — למשל בהחלפה ל-``splitlines()``, שתחזיר מפה תקינה למראה
    עם שורות שהטווח לא מגיע אליהן.
    """
    from mcp_server.handlers import apply_line_range

    for text in (
        "x = 1\rx = 2\r@deco\rdef f():\r    pass\r",       # CR בודד
        "x = 1\r\n@deco\r\ndef f():\r\n    pass\r\n",      # CRLF
        "x = 1\n@deco\ndef f():\n    pass\n",              # LF
    ):
        found = extract_outline(text, "x.py")
        if found["status"] != "ok":
            continue  # נדחה במפורש — אין מפה, ולכן אין למה להצביע

        for row in found["symbols"]:
            sliced = apply_line_range(text, row["start"], row["end"])

            assert not isinstance(sliced, str), f"{row} נדחה בקריאת טווח"
            assert "def f" in sliced["text"], f"{row} הצביע על טקסט אחר"


def test_deep_nesting_does_not_raise_from_our_side():
    """מחסנית מפורשת ולא רקורסיה: קינון עמוק אינו ``RecursionError`` שלנו."""
    text = "".join(f"{' ' * (4 * i)}def f{i}():\n" for i in range(60))
    text += " " * (4 * 60) + "pass\n"

    result = extract_outline(text, "x.py")

    assert result["status"] == "ok"
    assert result["total"] == 60


# ---------------------------------------------------------------------------
# הצרכן הוא לקוח MCP
#
# ``claude-md-snippets/testing.md`` כלל 1: הבדיקה עוברת דרך אותו ממשק כמו
# הצרכן. הטסטים למעלה בודקים את החילוץ; אלה בודקים את הכלי.
# ---------------------------------------------------------------------------


class _Mirror:
    def __init__(self, text):
        self._text = text

    def get_file_at_commit(self, repo, path, commit, **k):
        return {
            "success": True,
            "file_path": path,
            "resolved_commit": "abc123",
            "is_binary": False,
            "content": self._text,
            "encoding": "utf-8",
            "size": len(self._text),
            "lines": self._text.count("\n") + 1,
        }

    def get_default_branch(self, repo):
        return "main"


def _backend(text):
    from mcp_server.repo_backend import RepoBackend

    return RepoBackend(mirror=_Mirror(text))


_SAMPLE = "".join(f"def f{i}():\n    pass\n\n\n" for i in range(250))


def test_the_tool_returns_an_outline_status_and_a_page():
    out = repo_handlers.get_repo_file(
        _backend(_SAMPLE), repo="r", path="a.py", outline=True
    )

    assert out["status"] == "outline"
    assert out["total"] == 250
    assert len(out["symbols"]) == repo_handlers.OUTLINE_PER_PAGE_DEFAULT


def test_paging_walks_forward_without_gaps_or_repeats():
    backend = _backend(_SAMPLE)

    first = repo_handlers.get_repo_file(
        backend, repo="r", path="a.py", outline=True, page=1, per_page=100
    )["symbols"]
    second = repo_handlers.get_repo_file(
        backend, repo="r", path="a.py", outline=True, page=2, per_page=100
    )["symbols"]

    assert first[-1]["start"] < second[0]["start"]
    assert not ({r["name"] for r in first} & {r["name"] for r in second})


def test_per_page_is_clamped_to_the_outline_ceiling_and_not_the_tree_one():
    """``TREE_PER_PAGE_MAX`` הוא 1000, ורשומת סימבול שוקלת יותר מנתיב."""
    out = repo_handlers.get_repo_file(
        _backend(_SAMPLE), repo="r", path="a.py", outline=True, per_page=99_999
    )

    assert out["per_page"] == repo_handlers.OUTLINE_PER_PAGE_MAX


def test_reading_without_outline_is_untouched():
    """תוספתיות: בלי הפרמטר התשובה היא בדיוק זו של היום."""
    out = repo_handlers.get_repo_file(_backend("def f():\n    pass\n"), repo="r", path="a.py")

    assert out["status"] == "ok"
    assert out["content"] == "def f():\n    pass\n"
    assert "symbols" not in out
    assert "total" not in out


def test_the_outline_and_a_range_read_agree_on_where_a_symbol_lives():
    """המסלול השלם: מפה ← טווח. אם הם לא מסכימים, המפה חסרת ערך."""
    text = "def a():\n    pass\n\n\n@deco\ndef b():\n    return 1\n"
    backend = _backend(text)

    found = repo_handlers.get_repo_file(
        backend, repo="r", path="a.py", outline=True, symbol="b"
    )["symbols"][0]
    body = repo_handlers.get_repo_file(
        backend, repo="r", path="a.py", lines=[found["start"], found["end"]]
    )["content"]

    assert body == "@deco\ndef b():\n    return 1"


def test_an_unsupported_language_reaches_the_caller_as_a_status():
    out = repo_handlers.get_repo_file(
        _backend("Title\n=====\n"), repo="r", path="page.rst", outline=True
    )

    assert out == {
        "ok": True,
        "file": out["file"],
        "status": "no_outline",
        "reason": "unsupported_language",
    }


# ---------------------------------------------------------------------------
# מול git אמיתי
# ---------------------------------------------------------------------------


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_a_decorated_tool_is_findable_through_a_real_mirror(tmp_path):
    """הטסט שהיה תופס את הפער מלכתחילה, בצורתו הכללית.

    כל הכתיבה תחת ``tmp_path``; אין מחיקה ואין נגיעה בעץ העבודה.
    """
    work = tmp_path / "work"
    work.mkdir()
    (work / "srv.py").write_text(
        "def register(mcp):\n"
        "    @mcp.tool(name='x')\n"
        "    def get_repo_file(path):\n"
        "        return path\n",
        encoding="utf-8",
    )
    _git("init", "-q", "-b", "main", cwd=work)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=work)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init", cwd=work)

    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    subprocess.run(
        ["git", "clone", "--quiet", "--mirror", str(work), str(mirrors / "demo.git")],
        check=True,
        capture_output=True,
    )

    from mcp_server.repo_backend import RepoBackend
    from services.git_mirror_service import GitMirrorService

    backend = RepoBackend(mirror=GitMirrorService(base_path=str(mirrors)))
    out = backend.get_file(repo="demo", path="srv.py", outline=True)

    names = {row["name"] for row in out["symbols"]}
    assert "register.get_repo_file" in names
    found = next(r for r in out["symbols"] if r["name"] == "register.get_repo_file")
    assert found["start"] == 2  # שורת ה-``@mcp.tool``, לא ה-``def``


# ---------------------------------------------------------------------------
# נרמול הקלט
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", [".py", ".PY", ".Py", ".pyi", ".PYI"])
def test_a_python_file_is_recognised_whatever_the_case_of_its_suffix(suffix):
    """``.pyi`` הוא פייתון תקין, והוא נפוץ הרבה יותר מסיומת באותיות גדולות."""
    assert extract_outline("def f():\n    pass\n", f"mod{suffix}")["status"] == "ok"


def test_a_unicode_name_is_matched_case_insensitively():
    """``lower`` מפספסת מיפויים של יותר מתו אחד; ``casefold`` לא."""
    assert _names("def straße():\n    pass\n", symbol="STRASSE") == ["straße"]


def test_a_multiline_parenthesised_decorator_still_anchors_at_the_at_sign():
    """``d.lineno`` הוא שורת ה**ביטוי**, לא שורת ה-``@``.

    בכתיב הרגיל הם זהים. ב-``@(`` עם ירידת שורה הביטוי מתחיל שורה מאוחר
    יותר, וטווח שנגזר מהאאוטליין היה מחמיץ את השורה הראשונה של הסימבול.
    התחביר הזה אינו מופיע בריפו אפילו פעם אחת, אבל התיקון הוא ארבע שורות
    בלי תלות חדשה — זול יותר מלתעד מגבלה ידועה.
    """
    text = "@(\n    deco\n)\ndef f():\n    pass\n"

    assert extract_outline(text, "x.py")["symbols"][0]["start"] == 1


def test_an_undecorated_symbol_is_not_dragged_backwards():
    """הסריקה אחורה רצה רק כשיש מעטר, ולא בולעת שורות שכנות."""
    text = "@deco\ndef a():\n    pass\n\n\ndef b():\n    pass\n"

    symbols = extract_outline(text, "x.py")["symbols"]

    assert symbols[0]["start"] == 1
    assert symbols[1]["start"] == 6


# ---------------------------------------------------------------------------
# העימוד — בטוח בהוכחה, לא בתקווה
# ---------------------------------------------------------------------------


#: תו CJK תופס שלושה בתים ב-UTF-8. זה בדיוק המקרה שהוכחה שנשענה על
#: ספירת **תווים** פספסה.
_CJK = "\u5b57"


def _wide_symbol(index: int) -> str:
    return "def " + _CJK * 181 + f"{index}():\n    pass\n"


def test_an_oversized_page_is_rejected_and_never_silently_trimmed():
    """הגרסה הקודמת "הוכיחה" שעמוד נכנס בתקציב על ידי חסימת אורך השם
    ב-200 **תווים**. זה נשבר בשני מקומות: שם ב-CJK הוא שלושה בתים לתו,
    כך שעמוד מקסימלי הגיע ל-323,000 בתים מול תקציב של 256,000; והקיצוץ
    הרס את הזהות. עכשיו נמדדים בתים אמיתיים, והעמוד נדחה במקום להיחתך.
    """
    text = "".join(_wide_symbol(i) for i in range(500))

    out = repo_handlers.get_repo_file(
        _backend(text), repo="r", path="a.py", outline=True, per_page=500
    )

    assert out["ok"] is False
    assert out["error"] == "page_too_large"
    assert out["bytes"] > out["max"] == repo_handlers.OUTPUT_BYTE_BUDGET


def test_a_smaller_page_of_the_same_file_succeeds_and_fits():
    """הדחייה אומרת לקורא מה לעשות, וזה באמת עובד."""
    import json

    text = "".join(_wide_symbol(i) for i in range(500))

    out = repo_handlers.get_repo_file(
        _backend(text), repo="r", path="a.py", outline=True, per_page=100
    )

    assert out["status"] == "outline"
    serialized = json.dumps(out["symbols"], ensure_ascii=False).encode("utf-8")
    assert len(serialized) <= repo_handlers.OUTPUT_BYTE_BUDGET


def test_a_long_name_keeps_its_identity_so_the_filter_still_finds_it():
    """קיצוץ השם שבר את ``symbol=``: חיפוש בשם המלא החזיר אפס תוצאות.

    מזהה שנחתך אינו מזהה, ושני שמות ארוכים ושונים היו יכולים להתנגש בו.
    """
    deep = "".join(f"{' ' * (4 * i)}def name{i}():\n" for i in range(60))
    deep += " " * (4 * 60) + "pass\n"
    full = ".".join(f"name{i}" for i in range(60))

    assert len(full) > 200
    assert _names(deep, symbol=full) == [full]


def test_no_symbol_is_unreachable_across_pages():
    """המאפיין שהעימוד קיים בשבילו: איחוד כל העמודים הוא כל הסימבולים."""
    backend = _backend(_SAMPLE)
    seen = []
    for page in range(1, 6):
        seen += repo_handlers.get_repo_file(
            backend, repo="r", path="a.py", outline=True, page=page, per_page=50
        )["symbols"]

    every = repo_handlers.get_repo_file(
        backend, repo="r", path="a.py", outline=True, per_page=500
    )["symbols"]

    assert seen == every[: len(seen)]
    assert len(seen) == 250


@pytest.mark.parametrize("page", [0, -5, "x", None, 1.5])
def test_a_direct_caller_cannot_slice_with_a_bad_page(page):
    """``get_file`` הוא API ציבורי, ולא רק מה שהמטפל קורא לו.

    זו בדיוק ההגנה ש-``list_tree`` עושה בכוונה, עם הערה כתובה, ושמסלול
    האאוטליין דילג עליה.
    """
    from mcp_server.repo_backend import RepoBackend

    backend = RepoBackend(mirror=_Mirror(_SAMPLE))

    out = backend.get_file(repo="r", path="a.py", outline=True, page=page)

    assert out["page"] == 1
    assert out["symbols"][0]["name"] == "f0"


@pytest.mark.parametrize("per_page", ["x", None, [1]])
def test_a_non_numeric_per_page_falls_back_to_the_default(per_page):
    from mcp_server.repo_backend import RepoBackend

    backend = RepoBackend(mirror=_Mirror(_SAMPLE))

    out = backend.get_file(repo="r", path="a.py", outline=True, per_page=per_page)

    assert out["per_page"] == repo_handlers.OUTLINE_PER_PAGE_DEFAULT


@pytest.mark.parametrize("per_page", [0, -1])
def test_a_non_positive_per_page_becomes_the_smallest_valid_page(per_page):
    """אותה נוסחה בדיוק כמו ב-``list_tree``, ובכוונה.

    אפס אינו "לא מספר" — הוא מספר מחוץ לתחום, ולכן הוא נצבט לגבול הקרוב
    ולא נופל לברירת המחדל. יישור למוסכמה של הקובץ עדיף על התנהגות שנייה
    שנראית סבירה לבדה.
    """
    from mcp_server.repo_backend import RepoBackend

    backend = RepoBackend(mirror=_Mirror(_SAMPLE))

    out = backend.get_file(repo="r", path="a.py", outline=True, per_page=per_page)

    assert out["per_page"] == 1
    assert len(out["symbols"]) == 1


def test_the_response_does_not_carry_a_truncated_flag():
    """שדה שתמיד ``false`` מסמן משהו אחר ממה שאותה מילה מסמנת בכלי השכן.

    ב-``list_repo_tree`` ``truncated`` פירושו "התקציב חתך בתוך העמוד".
    כאן אין חיתוך, ולכן אין שדה — ``total`` הוא מה שאומר אם יש עוד עמודים.
    """
    out = repo_handlers.get_repo_file(
        _backend(_SAMPLE), repo="r", path="a.py", outline=True
    )

    assert "truncated" not in out


# ---------------------------------------------------------------------------
# ``lines`` ו-``outline`` אינם מצטברים
# ---------------------------------------------------------------------------


def test_asking_for_both_a_range_and_an_outline_is_rejected():
    """התעלמות שקטה מפרמטר שהקורא העביר היא הכשל השקט מהצד השני.

    הוא היה מקבל תשובה תקינה, בלי שום סימן שהטווח שביקש לא נקרא.
    """
    out = repo_handlers.get_repo_file(
        _backend(_SAMPLE), repo="r", path="a.py", outline=True, lines=[1, 5]
    )

    assert out == {"ok": False, "error": "outline_and_lines"}


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("comment", "@(\n    # note\n    deco\n)\ndef f():\n    pass\n"),
        ("blank", "@(\n\n    deco\n)\ndef f():\n    pass\n"),
    ],
)
def test_a_decorator_split_by_a_comment_or_blank_line_still_anchors_at_the_at_sign(
    label, text
):
    """הסריקה אחורה מדלגת על שורות ריקות והערות, אבל רק אם היא נוחתת על ``@``."""
    assert extract_outline(text, "x.py")["symbols"][0]["start"] == 1


def test_a_leading_comment_does_not_drag_an_undecorated_symbol_backwards():
    """הדילוג לא בולע שורות כשאין ``@`` בסוף המסלול."""
    text = "# a note\n\ndef f():\n    pass\n"

    assert extract_outline(text, "x.py")["symbols"][0]["start"] == 3


# ---------------------------------------------------------------------------
# HTML / Jinja
#
# תבנית Jinja אינה HTML תקין, וזה לא פגם: תגית שנפתחת בענף אחד של
# ``{% if %}`` ונסגרת באחר היא הכתיב הרגיל. פרסר DOM "מתקן" את זה בשקט
# ומחזיר שורות שאינן במקום; סורק טוקנים שטוח לא מנסה לאזן ולכן לא משקר.
# ---------------------------------------------------------------------------

_TEMPLATES = _REPO_ROOT / "webapp" / "templates"


def _html(text, **kw):
    return extract_outline(text, "page.html", **kw)


def test_a_nested_tag_without_an_id_does_not_close_the_one_that_has_it():
    """המבחן שמסוגל להיכשל, ולכן הוא ראשון.

    מימוש שדוחף למחסנית **רק** אלמנטים בעלי ``id`` אך שולף על כל תגית
    סוגרת נראה זהה כמעט תמיד. הוא נשבר בדיוק כאן: התגית הסוגרת הפנימית
    שולפת את ``#a`` ונותנת לו את שורה 2 במקום 3. מעקב העומק חייב להיות
    שלם גם כשהדיווח מסונן.
    """
    symbols = _html('<div id="a">\n<div></div>\n</div>\n')["symbols"]

    assert symbols == [{"name": "div#a", "start": 1, "end": 3}]


def test_a_tag_written_inside_a_javascript_string_is_not_a_symbol():
    """``base.html:2545`` מכיל בדיוק את זה, ולכן זה לא תרחיש מומצא:

        '  <div class="modal-body" id="recentFilesList">' +

    הוא יושב בתוך בלוק ``<script>``, ומפה שסופרת אותו כאלמנט מפנה לשורה
    שאין בה תגית.
    """
    text = '<script>\nvar h = \'<div id="row">\';\nfunction go() {}\n</script>\n'

    names = [row["name"] for row in _html(text)["symbols"]]

    assert "div#row" not in names
    assert "go" in names, "הפונקציה שאחרי המחרוזת נבלעה"


def test_a_definition_written_inside_a_javascript_string_is_not_a_function():
    """מה שמצב המחרוזת באמת מונע, ובטסט משלו.

    הטסט שמעליו מקבע התנהגות אמיתית, אבל אינו רגיש למצב המחרוזת: תגית
    בתוך בלוק ``<script>`` אינה נכנסת למפה כי הבלוק כולו נקרא כטקסט
    גולמי, ולא בגלל המחרוזת. הרגישות היא כאן — ``function`` שכתוב בתוך
    מחרוזת אינו הגדרה, ובלי המצב הוא היה נספר.
    """
    text = '<script>\nvar s = "function fake() {}";\nfunction real() {}\n</script>\n'

    names = [row["name"] for row in _html(text)["symbols"]]

    assert names == ["script", "real"]


def test_dead_code_inside_comments_never_enters_the_map():
    """שני סוגי ההערות, ושתיהן רב-שורתיות ב-``base.html``."""
    text = (
        '<!-- <div id="dead">\n'
        '     <div id="alsodead"></div> -->\n'
        '{# <div id="jinjadead"></div> #}\n'
        '<div id="live"></div>\n'
    )

    assert [row["name"] for row in _html(text)["symbols"]] == ["div#live"]


def test_tags_unbalanced_across_if_branches_neither_raise_nor_shift_lines():
    """הכתיב הרגיל בתבנית, ולכן הוא לא יכול להפיל את הסריקה.

    ``<div id="x">`` נפתח בענף אחד ואינו נסגר בו. תגית סוגרת בלי התאמה
    אסור לה לרוקן את המחסנית — אחרת כל שורות ה-``end`` שמתחת מוסטות.
    ``#x`` מדווח עד סוף הקובץ, וזו התשובה הכנה: הוא באמת לא נסגר.
    """
    # ``span`` ולא ``div`` שני, ובכוונה: כששני הפתוחים הם מאותו סוג, גם
    # שליפה עיוורת מראש המחסנית פוגעת במקרה בנכון. כאן ה-``</div>``
    # מדלג מעל ה-``span`` שמעליו, וזה מה שמפריד בין השתיים.
    text = (
        "{% if a %}\n"
        '<div id="x">\n'
        "{% else %}\n"
        '<span id="y">\n'
        "{% endif %}\n"
        "</div>\n"
        '<div id="after"></div>\n'
    )

    symbols = _html(text)["symbols"]

    assert {row["name"]: (row["start"], row["end"]) for row in symbols} == {
        # ``#x`` נסגר על ידי ה-``</div>``, וה-``span`` שנפתח בענף השני
        # ולא נסגר מדווח עד אותה שורה — לא נזרק ולא מסיט.
        "div#x": (2, 6),
        "span#y": (4, 6),
        "div#after": (7, 7),
    }


def test_a_closing_script_tag_inside_a_js_string_still_ends_the_block():
    """כלל שקט, ולכן הוא מקובע ולא רק כתוב.

    נמדד מול Chromium: ``<script>var s = "</script>";</script>`` מחזיר
    תוכן אלמנט של ``'var s = "'`` — האלמנט **נגמר בתוך המחרוזת**, וכל
    השאר הופך לטקסט HTML. המפרט אומר את אותו דבר במפורש ומורה לכתוב
    ``\\x3C/script`` בתוך literals.

    המימוש האינטואיטיבי הוא ההפוך — לחפש את הסוגר תוך כיבוד מחרוזות —
    והוא **לא זורק שגיאה**, רק מותח את הבלוק עד הסוגר הבא. כאן זה היה
    ``end=4`` במקום 2, ו-``after`` היה נספר כפונקציה למרות שאינו קוד.
    """
    text = '<script>\nvar s = "</script>";\nfunction after() {}\n</script>\n'

    symbols = _html(text)["symbols"]

    assert symbols == [{"name": "script", "start": 1, "end": 2}]


def test_a_regex_literal_holding_a_quote_does_not_swallow_the_code_after_it():
    """``base.html`` מכיל ``.replace(/"/g, ...)`` בשלושה מקומות.

    בלי מצב ל-regex literal, המרכאה שבתוכו פותחת מחרוזת ובולעת את הקוד
    עד המרכאה הבאה — כלומר ``b`` נעלמת מהמפה בשקט.
    """
    text = (
        "<script>\n"
        "function a() { return x.replace(/\"/g, ''); }\n"
        "function b() {}\n"
        "</script>\n"
    )

    names = [row["name"] for row in _html(text)["symbols"]]

    assert names == ["script", "a", "b"]


@pytest.mark.parametrize(
    ("attribute", "scanned"),
    [
        ("", True),
        (' type="module"', True),
        (' type="text/javascript"', True),
        (' type="TEXT/JAVASCRIPT"', True),
        (' type="application/json"', False),
        (' type="importmap"', False),
        # ``essence match`` — פרמטר אחרי הסוג פוסל אותו. נמדד ב-Chromium:
        # סקריפט כזה **אינו רץ**.
        (' type="text/javascript; charset=utf-8"', False),
    ],
)
def test_only_a_javascript_script_block_is_scanned_for_functions(attribute, scanned):
    """``base.html`` מכיל ארבעה ``application/json`` ושני ``module``.

    בלוק נתונים שנסרק כקוד מייצר סימבולים ממחרוזות שבמקרה נראות כהגדרות.
    רשימת ה-MIME types נלקחה מ-``mimesniff.spec.whatwg.org`` ואומתה
    אחת-אחת מול Chromium.
    """
    text = f"<script{attribute}>\nfunction f() {{}}\n</script>\n"

    names = [row["name"] for row in _html(text)["symbols"]]

    assert ("f" in names) is scanned


@pytest.mark.parametrize("tag", ["br", "img", "input", "meta", "link", "hr", "param"])
def test_a_void_element_is_never_pushed_onto_the_stack(tag):
    """אלמנט void שנדחף למחסנית לא ייסגר לעולם ויסיט את מי שמעליו.

    ``param`` כאן בכוונה: WHATWG הוציא אותו מרשימת ה-void כמיושן,
    ו-Chromium **עדיין** מתייחס אליו כך — נמדד. הקלט הוא קובץ שמישהו
    כתב, ומי שכתב ``<param>`` בתבנית ישנה התכוון ל-void.
    """
    # ל-void **יש** ``id`` כאן, ובכוונה: בלי ``id`` הוא נשלף בשקט יחד עם
    # העוטף והתוצאה זהה בשני המימושים. ההבדל נראה רק בשורת ה-``end``
    # שלו — 2 כשהוא void, 3 כשהוא נדחף למחסנית וממתין לסוגר שלא יבוא.
    text = f'<div id="outer">\n<{tag} id="inner">\n</div>\n'

    symbols = _html(text)["symbols"]

    assert {row["name"]: (row["start"], row["end"]) for row in symbols} == {
        "div#outer": (1, 3),
        f"{tag}#inner": (2, 2),
    }


def test_an_attribute_value_containing_an_angle_bracket_does_not_split_the_tag():
    """``<div title="a > b">`` הוא תגית אחת.

    חיפוש ``>`` בלי לכבד מחרוזות היה חותך אותה באמצע, וכל מה שאחריה היה
    נקרא כטקסט — כולל תגיות אמיתיות שהיו נעלמות מהמפה.
    """
    text = '<div title="a > b" id="real">\n</div>\n<div id="after"></div>\n'

    names = [row["name"] for row in _html(text)["symbols"]]

    assert names == ["div#real", "div#after"]


def test_the_jinja_keyword_and_its_argument_are_read_from_the_same_string():
    """באג שנתפס על הקובץ האמיתי: ``block content`` חזר כ-``block k``.

    החיפוש רץ על מחרוזת מנוקה וה-slice על המקורית, וההיסט של ה-``strip``
    הזיז את הגבול בדיוק במספר הרווחים שהוסרו.
    """
    text = (
        '{% extends "base.html" %}\n'
        "{% block content %}\n"
        "{% if x %}\n"
        "{% endif %}\n"
        "{% endblock %}\n"
        "{% macro nv(value) -%}\n"
        "{%- endmacro %}\n"
        '{% include "y.html" %}\n'
    )

    symbols = _html(text)["symbols"]

    assert {row["name"]: (row["start"], row["end"]) for row in symbols} == {
        "extends base.html": (1, 1),
        "block content": (2, 5),
        "macro nv": (6, 7),
        "include y.html": (8, 8),
    }


def test_an_endif_does_not_close_the_block_that_opened_before_it():
    """``{% endif %}`` שסוגר ``{% block %}`` היה נותן לו טווח קצר מדי.

    ב-``base.html`` יש 319 ``{% if %}`` מול 175 ``{% block %}``, ורובם
    מקוננים זה בזה.
    """
    text = "{% block outer %}\n{% if a %}\n{% endif %}\n{% endblock %}\n"

    symbols = _html(text)["symbols"]

    assert symbols == [{"name": "block outer", "start": 1, "end": 4}]


# ---------------------------------------------------------------------------
# קבצים אמיתיים
# ---------------------------------------------------------------------------


def test_every_function_in_the_real_base_template_is_found():
    """``base.html`` הוא הקריטריון: 221KB ו-5,225 שורות.

    המונה כאן נגזר ממקור אחר לגמרי — חיפוש טקסטואלי על שלוש הצורות
    שמופיעות בקובץ — ולא מהסורק. הן זרות זו לזו מספיק כדי שהתאמה ביניהן
    לא תהיה טאוטולוגיה.
    """
    path = _TEMPLATES / "base.html"
    if not path.exists():  # pragma: no cover
        pytest.skip("base.html לא קיים")
    text = path.read_text(encoding="utf-8")

    declared = set(re.findall(r"(?:^|[^\w.$])function\s+([A-Za-z_$][\w$]*)\s*\(", text))
    assigned = set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
                              r"(?:async\s+)?(?:function\b|\([^)]*\)\s*=>)", text))

    found = {row["name"] for row in _js_symbols(text)}

    # **חסם עליון, לא שוויון** — ובדיוק מאותה סיבה שהמונה של ``id="``
    # הוא חסם: הביטוי ``\([^)]*\)\s*=>`` עוצר ב-``)`` הראשון, ולכן הוא
    # מתאים גם ל-IIFE — ``const x = (() => {...})()`` — שאינו הגדרת
    # פונקציה אלא הצבה של הערך שהיא החזירה. ב-``base.html`` יש שניים
    # כאלה, ושניהם מחזירים בוליאני: ``localKill`` ו-``isMobileViewport``.
    #
    # כל הפרש חייב הסבר, ולא "בערך נכון": השם שנדחה חייב להיות כתוב
    # בקובץ כ-IIFE. פונקציה אמיתית שתיעלם תיפול כאן.
    assert found <= declared | assigned

    for rejected in (declared | assigned) - found:
        assert re.search(rf"\b{re.escape(rejected)}\s*=\s*\(\s*\(", text), \
            f"{rejected!r} נעדר מהמפה ואינו IIFE"


def test_no_script_block_is_returned_as_one_opaque_symbol():
    """הקריטריון שהוגדר מראש ככישלון.

    ב-``base.html`` יש בלוק סקריפט בן מאות שורות. אם הוא מוחזר כסימבול
    אחד, המפה נותנת גבול ולא ניווט — היא לא ירדה לרזולוציה שעורכים בה.
    """
    path = _TEMPLATES / "base.html"
    if not path.exists():  # pragma: no cover
        pytest.skip("base.html לא קיים")

    symbols = extract_outline(path.read_text(encoding="utf-8"), str(path))["symbols"]
    blocks = [row for row in symbols if row["name"].startswith("script")]
    biggest = max(blocks, key=lambda row: row["end"] - row["start"])

    assert biggest["end"] - biggest["start"] > 200, "הקובץ השתנה — אין בלוק גדול"

    inside = [
        row for row in symbols
        if biggest["start"] < row["start"] <= biggest["end"]
        and not row["name"].startswith(("script", "style"))
        and "#" not in row["name"]
    ]

    assert len(inside) >= 10, f"{biggest} הוחזר כבלוק אטום"


def test_the_ids_found_are_exactly_the_real_ones_and_not_those_in_strings():
    """המונה הטקסטואלי הוא **חסם עליון**, לא ציפייה.

    ``grep`` על ``id="`` סופר גם ``data-theme-id`` (כי ``-`` הוא גבול
    מילה) וגם ``id=`` בתוך מחרוזות JS. הסורק חייב להחזיר **פחות**, וכל
    הפרש חייב להיות מוסבר — לא "בערך נכון".
    """
    path = _TEMPLATES / "base.html"
    if not path.exists():  # pragma: no cover
        pytest.skip("base.html לא קיים")
    text = path.read_text(encoding="utf-8")

    upper_bound = set(re.findall(r'\bid="([^"]*)"', text))
    found = {row["name"].split("#", 1)[1] for row in extract_outline(text, str(path))["symbols"]
             if "#" in row["name"]}

    assert found < upper_bound, "הסורק לא סינן כלום — או שהוא ממציא"

    for rejected in upper_bound - found:
        # כל דחייה היא או תכונה שאינה ``id``, או ערך שנבנה בזמן ריצה
        # (Jinja או template literal) — ואף אחד מהם אינו עוגן שאפשר לנווט אליו.
        assert "{{" in rejected or "${" in rejected or f'data-{rejected}' in text \
            or f'-id="{rejected}"' in text or f"id=\"{rejected}\"' " in text \
            or f"id=\"{rejected}\">' " in text, f"דחייה לא מוסברת: {rejected!r}"


@pytest.mark.parametrize(
    "relative", ["base.html", "components/editor_components.html", "admin_mcp.html"]
)
def test_a_real_template_yields_a_map_without_raising(relative):
    """שלושה קבצים שנבחרו לפי מה שיש בהם ולא באקראי.

    ``base.html`` אינו מכיל אף ``{% macro %}`` — כל העשרה בפרויקט יושבים
    בשני האחרים — ולכן הוא לבדו לא מכסה אותם. ``admin_mcp.html`` הוא
    היחיד עם whitespace control (``{%- ... -%}``).
    """
    path = _TEMPLATES / relative
    if not path.exists():  # pragma: no cover
        pytest.skip(f"{relative} לא קיים")

    found = extract_outline(path.read_text(encoding="utf-8"), str(path))

    assert found["status"] == "ok"
    assert found["total"] > 0
    for row in found["symbols"]:
        assert row["start"] <= row["end"], row


# ---------------------------------------------------------------------------
# ארבעת הבאגים בסורק ה-JavaScript, ושלושת המונים שהיו תופסים אותם
#
# הטסט הקודם על ``base.html`` עבר למרות 136 טווחים שגויים ושלוש פונקציות
# שנעלמו, משתי סיבות נפרדות: הוא סופר **כמות** ולא בודק טווח, והוא רץ על
# **קובץ אחד**. שני החורים נסגרים כאן.
# ---------------------------------------------------------------------------


def _js_symbols(text):
    """רק הגדרות הפונקציות, בלי הגבולות ובלי תגיות Jinja."""
    return [
        row for row in extract_outline(text, "page.html")["symbols"]
        if "#" not in row["name"]
        and not row["name"].startswith(("script", "style", "block ", "macro ",
                                        "extends ", "include ", "import ", "from "))
    ]


def test_a_default_parameter_value_does_not_close_the_function_at_its_signature():
    """באג 1 — הנפוץ מכולם: 136 מתוך 841 ההגדרות בכל התבניות.

    ``function f(a, opts = {})`` מכיל ``{`` שאינו פותח את גוף הפונקציה.
    העומק נלכד ברגע ההתאמה, כשהסורק עדיין **בתוך רשימת הפרמטרים**, ולכן
    ה-``}`` שסוגר את ברירת המחדל סגר את הפונקציה כולה. נמדד על
    ``base.html:3485``: ``openWizard`` חזר עם ``end == start == 3485``
    במקום להגיע ל-3518, וכך גם ``closeWizard``, ``maybeOpen`` ו-``startTour``.

    זה בדיוק השדה שכל הפיצ'ר קיים בשבילו — ממנו נגזר ה-``lines=`` הבא.
    """
    text = ("<script>\n"
            "function openWizard(reason, opts = {}) {\n"
            "  a();\n"
            "}\n"
            "function next() {}\n"
            "</script>\n")

    assert _js_symbols(text) == [
        {"name": "openWizard", "start": 2, "end": 4},
        {"name": "next", "start": 5, "end": 5},
    ]


def test_a_destructured_parameter_is_not_a_body_either():
    """אותו שורש, צורה שנייה: ``{`` של destructuring גם הוא בחתימה."""
    text = "<script>\nfunction draw({ x, y }) {\n  paint();\n}\n</script>\n"

    assert _js_symbols(text) == [{"name": "draw", "start": 2, "end": 4}]


def test_a_brace_inside_a_template_substitution_does_not_end_the_string():
    """באג 2 — פונקציות **נעלמות מהמפה לגמרי**, וזה גרוע מטווח שגוי.

    ``nesting`` עלה רק על ``${`` וירד על כל ``}``, ולכן אובייקט בתוך
    ``${...}`` הוריד אותו לאפס בטרם עת. משם ה-backtick הבא נקרא כסוגר של
    המחרוזת החיצונית, והסורק המשיך לקרוא טקסט כאילו הוא קוד.

    שלוש פונקציות אמיתיות אבדו כך: ``renderStoryCell``,
    ``renderAiExplainCell`` ו-``executedFunction``.
    """
    text = "<script>\nvar h = `${ {a: 1}.a }`;\nfunction real() {}\n</script>\n"

    assert [row["name"] for row in _js_symbols(text)] == ["real"]


def test_a_string_inside_a_template_substitution_does_not_end_it_either():
    """נגזרת של אותו תיקון: ``}`` בתוך מחרוזת מקוננת אינו סוגר את ``${``."""
    text = "<script>\nvar h = `${ f('}') }`;\nfunction real() {}\n</script>\n"

    assert [row["name"] for row in _js_symbols(text)] == ["real"]


@pytest.mark.parametrize(
    ("label", "before"),
    [("string", 'var s = "abc"'), ("call", "init()"), ("index", "var x = arr[0]")],
)
def test_a_definition_after_a_value_without_a_semicolon_is_still_found(label, before):
    """באג 3 — משתנה אחד ששירת שתי שאלות שונות.

    ``previous`` היה התו הלא-רווח האחרון. ל-regex זו השאלה **הנכונה**
    (``x /2`` הוא חילוק), אבל לגבול מזהה צריך את התו ה**צמוד**. לכן
    הגדרה שישבה אחרי ערך בלי נקודה-פסיק נחסמה: הטוקן האחרון היה ``c``
    או ``)`` או ``]``, והבדיקה החליטה שאנחנו באמצע מזהה.

    0 מופעים בתבניות היום, אבל **כן** ב-JS עצמאי: ``editor-manager.js``
    החזיר שלושה סימבולים בלבד.
    """
    text = f"<script>\n{before}\nfunction foo() {{ return 1; }}\n</script>\n"

    assert [row["name"] for row in _js_symbols(text)] == ["foo"]


def test_a_word_ending_in_function_is_still_not_a_definition():
    """הצד השני של אותו תיקון: הגבול חייב להמשיך לחסום.

    בדיקה על התו הצמוד מרחיבה את מה שנתפס, ולכן הטסט הזה מוודא שהיא לא
    הרחיבה יותר מדי — ``myfunction`` אינו ``function``.
    """
    text = "<script>\nvar myfunction = 1;\nvar xfunction foo() {}\n</script>\n"

    assert _js_symbols(text) == []


def test_a_character_whose_lowercase_is_longer_does_not_shift_the_script_boundary():
    """באג 4 — התיקון הזה הוא היחיד שנכנס בזכות ההקצאה ולא בזכות באג נצפה.

    החיפוש רץ על ``text.lower()`` והאינדקס שחזר שימש לחיתוך ולספירת
    שורות ב-``text`` המקורי. ``str.lower()`` יכול לשנות **אורך**:
    ``İ`` (U+0130, I טורקית עם נקודה) הופך לשני תווים. בתבניות הפרויקט
    אין היום אף תו כזה, ולכן הבאג אינו ניתן להגעה — וזו בדיוק הסיבה
    שה-fixture הזה קיים. בלעדיו התיקון נכון היום ויוחזר בשקט בעוד שנה.

    לפני התיקון, על הקלט הזה: ה-``script`` דווח עם ``end: 5`` במקום 4,
    ו-``div#x`` **נעלם מהמפה לגמרי**.
    """
    assert len("İ".lower()) == 2, "התו כבר לא משנה אורך — הטסט איבד את מה שהוא בודק"

    text = ("İ" * 20 + "\n"
            "<script>\n"
            "function f() {}\n"
            "</script>\n"
            '<div id="x">\n'
            "</div>\n")

    assert extract_outline(text, "page.html")["symbols"] == [
        {"name": "script", "start": 2, "end": 4},
        {"name": "f", "start": 3, "end": 3},
        {"name": "div#x", "start": 5, "end": 6},
    ]


def test_an_assignment_of_a_call_result_is_not_reported_as_a_function():
    """נמצא על ידי המונה, ולא על ידי מי שכתב את הרג'קס.

    ``const md = (a ? b : (() => ({x})))({...})`` הוא הצבה של תוצאת
    קריאה. הרג'קס התאים לו כי ``[^)]*`` עצר ב-``)`` הראשון ומצא ``=>``
    אחריו. כיבוד רמת קינון אחת פותר, ובדרך גם מרוויח: ``(a, b = (1)) =>``
    נתפס עכשיו ולא היה נתפס קודם.
    """
    text = "<script>\nconst md = (w.x ? w.x : (() => ({r: 1})))({b: true});\n</script>\n"

    assert _js_symbols(text) == []

    nested = "<script>\nconst k = (a, b = (1)) => a;\n</script>\n"
    assert [row["name"] for row in _js_symbols(nested)] == ["k"]


# ---------------------------------------------------------------------------
# שלושת המונים
#
# אף אחד מהם אינו מיותר, ולא ניתן להחליף אחד בשני: פונקציה שנעלמה מהמפה
# אין לה טווח, ולכן מונה הטווחים עיוור אליה לחלוטין. שניים מהם רצים על
# **כל** התבניות ולא על ``base.html`` בלבד — זה החור שאפשר לבאגים לשרוד.
# ---------------------------------------------------------------------------


def _templates():
    """כל התבניות. **תיקייה שקיימת ומחזירה אפס קבצים היא כישלון, לא דילוג.**

    דילוג הוא הדבר הנכון רק כשאין תיקיית תבניות בכלל — למשל בהתקנה
    חלקית. תיקייה שקיימת וריקה פירושה שמשהו נשבר, ודילוג עליה מחביא
    בדיוק את מה שהמונים שלמטה קיימים כדי לתפוס.
    """
    if not _TEMPLATES.is_dir():  # pragma: no cover - הריפו תמיד מכיל אותה
        pytest.skip(f"{_TEMPLATES} אינה קיימת")
    found = sorted(_TEMPLATES.rglob("*.html"))

    assert found, f"{_TEMPLATES} קיימת אך אין בה תבניות"

    return found


def test_a_function_that_opens_a_body_on_its_line_never_ends_on_that_line():
    """מונה 1 — תופס את באג 1, על כל התבניות.

    הטענה נגזרת מהטקסט ולא מהמימוש: שורה שנגמרת ב-``{`` פותחת גוף, ולכן
    הגוף נמשך לפחות לשורה הבאה. אין כאן סף ואין חריגים.

    ריצת בקרה על הקוד שלפני התיקון: **68 מתוך 773**. אחריו: 0 מתוך 771.
    """
    broken = []
    for path in _templates():
        lines = path.read_text(encoding="utf-8").split("\n")
        for row in _js_symbols(path.read_text(encoding="utf-8")):
            opening = re.sub(r"//[^\n]*$", "", lines[row["start"] - 1]).rstrip()
            if opening.endswith("{") and row["end"] <= row["start"]:
                broken.append((path.name, row))

    assert broken == []


def test_no_definition_inside_a_script_block_is_missing_from_the_map():
    """מונה 2 — תופס את באגים 2 ו-3, על כל התבניות.

    מונה הטווחים לא יכול לתפוס פונקציה שנעלמה, ורשימת שמות ידנית מגנה על
    שלושת המקרים שכבר נמצאו ולא על הבא. זה החסם העליון, באותה תבנית של
    ``id="``.

    הספירה מוגבלת ל**תוך גבולות בלוקי הסקריפט**, וזה נמדד ולא הונח: חסם
    על הקובץ כולו התמלא ברעש שאינו קוד — ``font_preview.html`` מכיל שש
    הגדרות בתוך ``<code>`` ואף ``<script>`` אחד, ו-``compare_paste.html``
    מכיל ``function hello(`` בטקסט הדגמה.
    """
    missing = []
    for path in _templates():
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        symbols = extract_outline(text, str(path))["symbols"]
        known = {row["name"].split(".")[-1] for row in _js_symbols(text)}
        for block in symbols:
            if not block["name"].startswith("script") or block["end"] <= block["start"]:
                continue
            body = "\n".join(lines[block["start"] : block["end"] - 1])
            for found in re.finditer(r"(?:^|[^\w.$])function\s+([A-Za-z_$][\w$]*)\s*\(", body):
                if found.group(1) not in known:
                    missing.append((path.name, found.group(1)))

    assert missing == []


def test_the_three_functions_that_had_vanished_are_back():
    """דרישה **נוספת** על המונה, לא במקומו.

    היא מקבעת בדיוק את המקרים שנמצאו, אבל היא לא הייתה תופסת את הבא
    בתור — לשם כך קיים המונה שמעליה.
    """
    for relative, expected in (
        ("admin_observability.html", {"renderStoryCell", "renderAiExplainCell"}),
        ("md_preview.html", {"executedFunction"}),
    ):
        path = _TEMPLATES / relative
        if not path.exists():  # pragma: no cover
            pytest.skip(f"{relative} לא קיים")

        names = {row["name"] for row in _js_symbols(path.read_text(encoding="utf-8"))}

        assert expected <= names, f"{relative}: חסרות {expected - names}"


# ---------------------------------------------------------------------------
# PR 1.2 — חמשת הממצאים הקריטיים ושתי בעיות האבטחה מסקירת הקוד
#
# כל אחד מהטסטים כאן הורץ על הקוד שלפני התיקון ואומת שהוא נופל שם. טסט
# שנכתב יחד עם תיקון ולא הוכח שהוא מסוגל להיכשל אינו ראיה, הוא קישוט.
#
# ארבעה מחמשת הקריטיים הם אפס מופעים בתבניות של הפרויקט היום — נמדד. הם
# נכנסים בכל זאת כי ``codekeeper_get_repo_file`` משרת כל ריפו ממורר, וכל
# אחת מהצורות האלה היא JavaScript או HTML רגיל לחלוטין.
# ---------------------------------------------------------------------------


def _definitions(text):
    """הסימבולים שהם הגדרות בקוד, בלי עוגני תגיות ובלי תגיות Jinja.

    התחילית נקלפת (``script#x.initColors`` ← ``initColors``) במקום לסנן
    על ``#``, כדי שפונקציה בתוך בלוק בעל ``id`` **תיכנס** ולא תיעלם.
    """
    out = []
    for row in extract_outline(text, "page.html")["symbols"]:
        bare = row["name"].rsplit(".", 1)[-1]
        if "#" in bare or " " in bare:
            continue
        out.append((bare, row["start"], row["end"]))
    return sorted(out)


def test_a_line_continuation_inside_a_js_string_does_not_shift_the_lines_after_it():
    """באג 1 מהסקירה, מנגנון א׳ — ``\\`` ואחריו שורה חדשה אמיתית.

    זה המשך שורה חוקי ב-JavaScript. הדילוג על התו שאחרי ``\\`` הזיז את
    האינדקס בשניים ולא ספר את ה-``\\n`` שביניהם, ולכן ``after`` דווח
    בשורה 3 — שורה שאין בה שום פונקציה — במקום 4.
    """
    text = (
        "<script>\n"
        "var s = 'a\\\n"
        "b';\n"
        "function after() {\n"
        "  return 1;\n"
        "}\n"
        "</script>\n"
    )

    assert _definitions(text) == [("after", 4, 6), ("script", 1, 7)]


def test_a_signature_spread_over_several_lines_does_not_shift_the_rest_of_the_block():
    """באג 1 מהסקירה, מנגנון ב׳ — ``index = match.end()`` על התאמה רב-שורתית.

    הסגנון שכל פורמטר מייצר כשרשימת הפרמטרים ארוכה. הרג'קס בולע את
    השורות החדשות שבתוך ההתאמה, והמונה לא התקדם — ולכן ``handler`` דווח
    ``2..4``, כלומר נגמר בתוך רשימת הפרמטרים שלו עצמו.

    **הסחף אינו מקומי**, וזה מה שהופך אותו לחמור: גם ``afterwards``,
    שיושב אחריו וכתוב תקין לחלוטין, דווח ``5..7`` במקום ``8..10``.
    """
    text = (
        "<script>\n"
        "const handler = (\n"
        "  a,\n"
        "  b,\n"
        ") => {\n"
        "  a();\n"
        "};\n"
        "function afterwards() {\n"
        "  z();\n"
        "}\n"
        "</script>\n"
    )

    assert _definitions(text) == [
        ("afterwards", 8, 10),
        ("handler", 2, 7),
        ("script", 1, 11),
    ]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("const f = function (a, o = {}) {\n  z();\n};\n", id="const"),
        pytest.param("var f = function ({x, y}) {\n  z();\n};\n", id="destructured"),
        pytest.param("let f = async function (a = {}) {\n  z();\n};\n", id="async"),
    ],
)
def test_a_default_value_in_an_assigned_function_expression_does_not_close_it_early(source):
    """באג 2 מהסקירה — התיקון של באג "ברירת מחדל סוגרת בחתימה" היה חלקי.

    ``signature`` נקבע מ**צורת הטקסט שהותאם** (``group(0)`` שנגמר ב-``(``),
    והחלופה ``function\\b`` ב-``_JS_ASSIGNED`` אינה בולעת את ה-``(``. לכן
    בצורת ביטוי מוצב התיקון לא חל בכלל, וה-``}`` שסוגר את ברירת המחדל סגר
    את הפונקציה כולה — ``end == start``, בדיוק הפלט שהטסט על צורת ההצהרה
    קיים כדי לחסום.

    המונה "0 מתוך 771" היה ירוק בזכות מזל בקלט: שלושת ביטויי הפונקציה
    המוצבים בתבניות הם ``window.X = function (…)``, צורה שהרג'קס דורש
    לפניה ``const``/``let``/``var`` ולכן אינו מזהה בכלל.
    """
    assert _definitions(f"<script>\n{source}</script>\n") == [
        ("f", 2, 4),
        ("script", 1, 5),
    ]


def test_an_unclosed_jinja_tag_does_not_erase_a_well_formed_one_below_it():
    """באג 3 מהסקירה — ``_skip_past`` גנב את הסוגר של השכנה.

    שגיאת הקלדה אחת, ``{% if broken`` בלי ``%}``, ו-``text.find`` החזיר
    את ה-``%}`` של ``{% block real %}`` שמתחתיה. כל מה שביניהן הפך
    ל"טקסט הארגומנט" של השבורה, ה-``{% endblock %}`` לא מצא למה להתאים,
    והפלט היה ``symbols: []`` — עם ``status: "ok"`` ובלי שום סימן.

    זה המצב שה-docstring של המודול מגדיר כגרוע מכולם: מפה חסרה שנראית
    שלמה.
    """
    text = (
        "before\n"
        "{% if broken\n"
        "some html\n"
        "{% block real %}\n"
        "content\n"
        "{% endblock %}\n"
        "after\n"
    )
    result = _html(text)

    assert result["symbols"] == [{"name": "block real", "start": 4, "end": 6}]


def test_a_truncated_jinja_tag_does_not_produce_a_mangled_name():
    """נלווה לבאג 3 — החיתוך של ``%}`` היה בלתי מותנה.

    הקורא עשה ``text[index + 2 : stop - 2]`` בלי לשאול אם הסוגר נמצא
    בכלל, ולכן ``{% block content`` החזיר ``block conte`` ו-``{% block xy``
    החזיר שם ריק. תגית שלא נסגרה אינה תגית, ולכן היא אינה סימבול.
    """
    assert _html("{% block content")["symbols"] == []
    assert _html("{% block xy")["symbols"] == []


def test_an_unbalanced_paren_in_a_signature_does_not_silence_the_rest_of_the_block():
    """באג 4 מהסקירה — ``signature`` שלא חזר לאפס השתיק את כל מה שאחריו.

    הענף ``if signature: … continue`` לא ניסה להתאים הגדרות חדשות, ולכן
    סוגר עגול אחד שלא נסגר גרם לכל פונקציה שאחריו באותו בלוק לא להיות
    מזוהה בכלל. בלוקי סקריפט כאן מגיעים למאות שורות.

    ההתאוששות אינה "התעלמות מהשגיאה": ``bad`` עצמה עדיין מתקלקלת, כי
    החתימה שלה לא נסגרת. ההבדל הוא שהיא מתקלקלת לבדה.
    """
    text = (
        "<script>\n"
        "function bad(a, (b {\n"
        "  x();\n"
        "}\n"
        "function after() {\n"
        "  y();\n"
        "}\n"
        "</script>\n"
    )
    found = dict((name, (start, end)) for name, start, end in _definitions(text))

    assert found["after"] == (5, 7)


def test_an_id_inside_another_attributes_value_does_not_become_the_anchor():
    """באג 5 מהסקירה, תוצאה א׳ — רג'קס על מחרוזת התכונות הגולמית.

    נמדד ב-Chromium 141.0.7390.37: ``id`` הוא ``real``. הגרסה הקודמת
    החזירה ``div#decoy"`` — שם שכולל מרכאה ו**אינו קיים בקובץ בכלל**.
    """
    assert _html('<div title="x id=decoy" id="real">\n</div>\n')["symbols"] == [
        {"name": "div#real", "start": 1, "end": 2}
    ]
    assert _html('<div data-tpl="<span id=inner>" id="real">\n</div>\n')["symbols"] == [
        {"name": "div#real", "start": 1, "end": 2}
    ]


def test_a_type_inside_another_attributes_value_does_not_hide_the_scripts_functions():
    """באג 5 מהסקירה, תוצאה ב׳ — וזו החמורה מהשתיים.

    ``type=`` שיושב בתוך ערך של תכונה אחרת גרם ל-``_is_javascript``
    להחזיר ``False``, ואז הבלוק דווח כגבול בלבד ו**כל הפונקציות שבתוכו
    נעלמו**. נמדד ב-Chromium: הבלוק הזה **רץ** כ-JavaScript.
    """
    text = (
        '<script data-note="see type=text/plain">\n'
        "function reallyReal() {\n"
        "  z();\n"
        "}\n"
        "</script>\n"
    )

    assert _definitions(text) == [("reallyReal", 2, 4), ("script", 1, 5)]


def test_an_unquoted_attribute_value_ending_in_a_slash_is_not_self_closing():
    """WARN-004 מהסקירה — הלוכסן שייך לערך, לא לתגית.

    נמדד ב-Chromium 141.0.7390.37: ``<a id="k" href=/>text</a>`` נותן
    ``href="/"`` ואת הטקסט **בתוך** ה-``<a>``. לפי הטוקנייזר של WHATWG
    ערך לא מצוטט נגמר ברווח או ב-``>`` בלבד. הגרסה הקודמת בדקה
    ``endswith("/")`` על המחרוזת הגולמית, ולכן החזירה ``1..1`` ולא דחפה
    את התגית למחסנית — כך שה-``</a>`` שאחריה גם לא מצא התאמה.

    המקרה השני הוא ההגנה מפני תיקון-יתר: ``/>`` על אלמנט ב-SVG **כן**
    סוגר את עצמו, ושם ההתנהגות הקיימת נכונה.
    """
    assert _html('<a id="k" href=/>\ntext\n</a>\n')["symbols"] == [
        {"name": "a#k", "start": 1, "end": 3}
    ]
    assert _html('<svg>\n<path id="p" d="M0 0" />\n</svg>\n')["symbols"] == [
        {"name": "path#p", "start": 2, "end": 2}
    ]


def test_a_run_of_whitespace_after_the_function_keyword_stays_linear():
    """SEC-001 מהסקירה — backtracking ריבועי ב-``_JS_FUNCTION``.

    ``\\s*\\*?\\s*`` הם שני ``\\s*`` צמודים שמופרדים באטום אופציונלי: על
    רצף רווחים באורך *m* יש O(m) דרכים לפצל אותו, וכל פיצול נבדק מחדש מול
    ``[A-Za-z_$]`` שנכשל. נמדד על הקוד הישן: 0.63 שניות ל-10KB, 2.53
    ל-20KB, 9.98 ל-40KB — פי ארבע לכל הכפלה, כלומר סדר גודל של שבוע
    בתקרת ה-10MB שהכלי מתיר.

    התקציב כאן רחב פי מאות ממה שהתיקון צריך (נמדד: 0.01 שניות) ופי מאות
    פחות ממה שהבאג נותן, כדי שהטסט לא יהיה שביר על מכונה עמוסה.
    """
    text = "<script>\nfunction" + " " * 40_000 + "\n</script>\n"

    started = time.perf_counter()
    _html(text)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0, f"{elapsed:.2f} שניות — הריבועיות חזרה"


def test_deeply_nested_template_literals_do_not_raise_from_our_side():
    """SEC-002 מהסקירה — רקורסיה בלי חסם ב-``_skip_string``.

    כל מחרוזת שנפתחת בתוך ``${…}`` נכנסה למסגרת חדשה, שלושה בתים לרמה,
    ולכן קובץ של כ-3KB הפיל ``RecursionError`` שאיש לא תפס לאורך המסלול
    עד לקוח ה-MCP. זה סתר את מה שהמודול מצהיר על עצמו — שערוץ הכשל הוא
    ערך ההחזרה ולא חריגה — ואת ``test_deep_nesting_does_not_raise_from_our_side``
    שהפרויקט כבר קיבע לסורק הפייתון.

    999 רמות אינן מספר שרירותי: הן מעל מגבלת הרקורסיה של CPython, שהיא
    1000 כברירת מחדל. הטסט מאמת את המגבלה כדי שלא יאבד את מה שהוא בודק.
    """
    assert sys.getrecursionlimit() <= 1000, "מגבלת הרקורסיה הועלתה — הטסט איבד את מה שהוא בודק"

    result = _html("<script>\n" + "`${" * 999 + "\n</script>\n")

    assert result["status"] == "ok"


def test_every_definition_is_reported_on_a_line_that_actually_contains_its_name():
    """המונה הרביעי — אורקל שנגזר מהטקסט, לא מהמימוש, על כל התבניות.

    הטענה היא הדבר הפשוט ביותר שכל הפיצ'ר מבטיח: ``start`` שחוזר למפה
    הוא שורה שאפשר להזין ל-``lines=``, ולכן השם שדווח חייב להיות כתוב
    בה. שלושת המונים שמעליו עיוורים לזה — מונה הטווח בודק רק שורות
    שנגמרות ב-``{``, וחתימה רב-שורתית נגמרת ב-``(``; ומונה ההגדרות
    החסרות סופר **כמה** נמצאו ולא **איפה**.

    **מה שהמונה הזה אינו: ראיה לתיקון של באג 1.** הרצתי אותו על הקוד
    שלפני התיקון והוא **עבר**. זה לא פגם בו אלא עובדה על הקורפוס, והיא
    נמדדה: אין בכל 66 התבניות אף חתימה רב-שורתית ואף ``\\`` שאחריו שורה
    חדשה, ולכן הפלט של הישן והחדש על כל הקורפוס זהה — 2,125 סימבולים,
    אפס הבדלים. שום מונה ברמת הקורפוס אינו יכול להבדיל ביניהם. מה שכן
    מוכיח את התיקון הם שני הטסטים המכוונים שלמעלה, ושניהם נופלים על
    הקוד הישן.

    התפקיד שלו הוא קדימה: התבנית הראשונה שתיכתב בסגנון שמייצר את הצורה
    הזאת, או שינוי עתידי בסורק שיחזיר את הסחף, נתפסים כאן.
    """
    misplaced = []
    for path in _templates():
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        for name, start, _ in _definitions(text):
            if name not in lines[start - 1]:
                misplaced.append((path.name, name, start, lines[start - 1].strip()[:60]))

    assert misplaced == []


def test_a_jinja_block_closed_over_by_an_ancestor_is_reported_and_not_dropped():
    """סימבול שנמחק בשקט — אותה מחלקת כשל, בפונקציה האחות.

    ``{% block x %}`` שנפתח בתוך ``{% if %}`` ולא נסגר לפני ה-``{% endif %}``
    נעלם מהמפה לגמרי: ה-``endif`` שלף את ה-``if`` ומחק איתו את כל מה
    שהיה מעליו במחסנית, בלי לדווח. ``_close_tag`` עושה את זה נכון
    למחסנית ה-HTML מהיום הראשון — הוא מדווח את מי שהיה פתוח בפנים עד
    שורת הסגירה — ובמחסנית ה-Jinja זה פשוט היה חסר.

    זה גם סתר את ``docs/mcp-server.rst``, שמבטיח שתגית שלא נסגרה מדווחת
    עד סוף הקובץ. הבטחה שמתקיימת כשאין ``{% endif %}`` כלל, ולא התקיימה
    כשיש.

    נמדד: בכל התבניות של הפרויקט ``block`` ו-``endblock`` מאוזנים, ולכן
    זה אינו ניתן להגעה כאן היום.
    """
    text = "{% if a %}\n{% block x %}\ntext\n{% endif %}\n"

    assert _html(text)["symbols"] == [{"name": "block x", "start": 2, "end": 4}]

    # בקרה: בלי ``{% endif %}`` בכלל, הדיווח עד סוף הקובץ עבד גם קודם.
    assert _html("{% if a %}\n{% block x %}\ntext\n")["symbols"] == [
        {"name": "block x", "start": 2, "end": 4}
    ]


# ---------------------------------------------------------------------------
# שני ממצאי הריוויו על PR 1.2
#
# שניהם פרה-קיימים — הם היו שבורים גם לפני PR 1.2 — ושניהם אפס מופעים
# בתבניות של הפרויקט. הם נכנסים כי הכלי משרת כל ריפו ממורר, וגם כי השני
# הוא חור בהגנה ולא באג בפלט.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("function foo()\n{\n  z();\n}\n", ("foo", 2, 5), id="declaration"),
        pytest.param(
            "const foo = function ()\n{\n  z();\n};\n", ("foo", 2, 5), id="expression"
        ),
        pytest.param("const foo = (a) =>\n{\n  z();\n};\n", ("foo", 2, 5), id="arrow"),
        pytest.param(
            "function foo()\n// why\n{\n  z();\n}\n", ("foo", 2, 6), id="line-comment"
        ),
        pytest.param(
            "const foo = (a) =>\n/* why */\n{\n  z();\n};\n",
            ("foo", 2, 6),
            id="block-comment",
        ),
    ],
)
def test_a_body_brace_on_its_own_line_does_not_close_the_function_at_its_signature(
    body, expected
):
    """סגנון Allman — ``{`` בשורה נפרדת — החזיר ``end == start``.

    הענף שסוגר פונקציה בסוף שורה קיים בשביל חץ בלי גוף מסולסל
    (``const f = x => x + 1``), שאין דבר אחר שיסגור אותו. הוא לא הבחין בין
    "אין גוף מסולסל" לבין "הגוף מתחיל בשורה הבאה", ולכן שלוש הצורות —
    הצהרה, ביטוי מוצב וחץ — חזרו כטווח באורך שורה אחת על פונקציה שלמה.

    **הכלל אומת ב-Node 22.22.2 דרך ``new Function``, ולא נכתב מהזיכרון:**
    ``function`` בכל צורותיו הוא ``SyntaxError`` בלי גוף בסוגריים
    מסולסלים, ולכן צורה כזאת חייבת להמתין תמיד. רק חץ יכול בלי סוגריים.

    **שני מקרי ההערה אינם קישוט.** באותה הרצה נמדד ש-
    ``function foo()\\n// why\\n{\\n}`` הוא JavaScript **תקין**. ההצעה
    המקורית — "אל תסגור אם התו הלא-רווח הבא הוא ``{``" — נכשלת עליו, כי
    התו הבא הוא ``/``. לכן הקורא-קדימה מדלג גם הערות.
    """
    found = [row for row in _definitions(f"<script>\n{body}</script>\n") if row[0] != "script"]

    assert found == [expected]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("const f = x => x + 1;\n", ("f", 2, 2), id="expression-body"),
        pytest.param("const f = (a, b = (1)) => a;\n", ("f", 2, 2), id="nested-parens"),
        pytest.param("const f = a => foo(\n  1);\n", ("f", 2, 3), id="wrapped-call"),
        pytest.param("function f() {\n  z();\n}\n", ("f", 2, 4), id="k-and-r"),
    ],
)
def test_the_forms_that_do_end_on_their_line_still_do(body, expected):
    """בקרה על תיקון-יתר, וזה הסיכון האמיתי של השינוי הזה.

    חץ עם גוף ביטוי **חייב** להמשיך להיסגר בסוף השורה — אין לו ``{``
    שיסגור אותו, ומימוש שיפסיק לסגור אותו יגרור אותו עד סוף הבלוק.

    ``wrapped-call`` הוא המקרה שמראה למה מבחן הסוגריים העגולים עדיין
    נחוץ לצד הדגל החדש: ``const f = a => foo(`` שנמשך לשורה הבאה הוא גוף
    ביטוי שטרם נגמר, והסוגר הפתוח הוא מה שמונע סגירה מוקדמת.
    """
    found = [row for row in _definitions(f"<script>\n{body}</script>\n") if row[0] != "script"]

    assert found == [expected]


def test_the_templates_are_found_from_any_working_directory(monkeypatch, tmp_path):
    """החור בהגנה עצמה, ולא באג בפלט — ולכן הוא החמור מהשניים.

    ``_TEMPLATES`` היה נתיב **יחסי**, ולכן הרצה מספרייה אחרת לא נכשלה אלא
    **דילגה**. נמדד: 124 עוברים ו-17 מדולגים במקום 141, והחבילה דיווחה
    ירוק. בין המדולגים היו שלושת המונים שרצים על כל התבניות — כלומר כל
    ההגנה שנבנתה על באגי הסורק נעלמה בשקט, ומי שהסתכל על הפלט ראה ירוק.

    זה אותו דפוס שנתפס כאן כבר פעמיים: מונה שרץ על קובץ אחד במקום על כל
    הקורפוס, ובדיקה שהתקיימה על מחרוזת ולא על האלמנט. **ירוק שאינו אומר
    את מה שנראה שהוא אומר.**

    הטענה היא על ``_TEMPLATES`` **ישירות** ולא דרך ``_templates()``, וזה
    מכוון: על הקוד שלפני התיקון ``_templates()`` היה עושה ``skip`` אחרי
    ה-``chdir``, והטסט הזה היה מדולג במקום ליפול — כלומר חוזר בדיוק על
    הדפוס שהוא קיים כדי לתפוס.
    """
    expected = _templates()
    assert expected, "לא נמצאו תבניות בכלל — הטסט איבד את מה שהוא בודק"

    monkeypatch.chdir(tmp_path)

    assert sorted(_TEMPLATES.rglob("*.html")) == expected
    assert _templates() == expected
