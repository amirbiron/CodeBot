"""‏``query`` ב-``codekeeper_get_file`` — חיפוש בתוך קובץ פרטי.

הבדיקות עוברות דרך **ממשק ה-MCP** (``mcp.call_tool``) ולא דרך הפונקציות
הפנימיות, כי זה הממשק שהצרכן מפעיל בפועל. שתיים מהן טהורות במכוון —
תקרת הבתים וספירת הקבועים — כי שם מה שנבדק הוא חישוב ולא זרימה.

שלוש קבוצות:

1. **התנהגות** — הפרמטר עושה את מה שהוא מבטיח.
2. **תוספתיות** — קריאה **בלי** הפרמטר מחזירה בדיוק את מה שהוחזר קודם.
3. **אכיפה** — הקבועים והתווית של האנליטיקס לא יכולים להיסחף בשקט.

כל בדיקה כאן הורצה גם על הקוד **שלפני** התוספת, וגם תחת מוטציה נקודתית
שמבטלת בדיוק את מה שהיא בודקת. פירוט המוטציות בגוף הבדיקות.
"""

import json
import logging

import pytest

from mcp_server import analytics, handlers, repo_handlers

pytest.importorskip("mcp")


# ---------------------------------------------------------------------------
# עזרים
# ---------------------------------------------------------------------------

_USER = 7
_FILE = "CobaltNext.json"
_DOC_ID = "abc123"


class _Dbm:
    """דמה של שכבת ה-DB: מחזירה מסמך אחד, לפי שם / מזהה / גרסה.

    ``get_latest_version_fresh`` ולא ``get_latest_version`` — זה המסלול
    ש-``_latest_fresh`` בוחר כשהוא קיים, וזה המסלול שרץ בפרודקשן.

    שלוש השיטות מכסות את שלושת מסלולי הבחירה ב-``ProductionBackend.get_file``,
    כי ``query`` רץ **אחרי** הבחירה ולכן הוא מבטיח את אותה תשובה בכל אחד מהם.
    ``get_file_by_id`` אינה מסננת לפי משתמש, בדיוק כמו האמיתית — הבעלות
    נאכפת ב-backend, וזה מה שהופך את הבדיקה עליה למשמעותית.
    """

    def __init__(self, code: str, extra: dict | None = None, old_code: str | None = None):
        self._code = code
        self._extra = extra or {}
        self._old_code = old_code

    def _doc(self, code: str, version: int) -> dict:
        return {
            "_id": _DOC_ID,
            "user_id": _USER,
            "file_name": _FILE,
            "version": version,
            "code": code,
            "programming_language": "json",
            "is_active": True,
            **self._extra,
        }

    def get_latest_version_fresh(self, user_id, file_name):
        if file_name != _FILE:
            return None
        return self._doc(self._code, 2)

    def get_file_by_id(self, file_id):
        if file_id != _DOC_ID:
            return None
        return self._doc(self._code, 2)

    def get_version(self, user_id, file_name, version):
        if file_name != _FILE or version != 1 or self._old_code is None:
            return None
        return self._doc(self._old_code, 1)


def _build(monkeypatch, code: str, extra: dict | None = None, old_code: str | None = None):
    """שרת MCP אמיתי מעל ``ProductionBackend`` אמיתי."""
    import mcp_server.server as srv
    from mcp_server.backend import ProductionBackend

    # ``build_mcp`` קורא ל-``instrument_mcp_server``, שזורק מחוץ לפרודקשן כשאין
    # קונפיגורציית PostHog. הקיבוע כאן הוא כדי שהבדיקה לא תעבור או תיפול לפי
    # ה-``ENVIRONMENT`` של מי שהריץ אותה.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: _USER)
    # ``repo_backend`` הוא ``object()`` ולא דמה: כלי הריפו נרשמים רק כשהוא
    # אינו ``None``, וגופם רץ רק בקריאה בפועל — שאין כאן. הוא נדרש כדי
    # שהבדיקה על הסכימה תוכל להשוות מול ``codekeeper_search_repo``, ודגל
    # האדמין כדי שהוא לא יסונן מרשימת הכלים.
    mcp = srv.build_mcp(
        ProductionBackend(db_manager=_Dbm(code, extra, old_code)), repo_backend=object()
    )
    mcp._request_is_admin = lambda: True
    return mcp


def _payload(result):
    """התשובה של הכלי, מפוענחת.

    נמדד מול ``mcp 1.28.1`` — הגרסה שנעולה ב-``requirements/base.txt``:
    ``FastMCP.call_tool`` מחזיר רשימת בלוקי תוכן. ההסתעפות על ``tuple``
    היא בשביל גרסאות שמחזירות ``(content, structured)``, כדי שעדכון גרסה
    ייפול על מה שבאמת השתנה ולא כאן.
    """
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


async def _call(mcp, **arguments):
    return _payload(await mcp.call_tool("codekeeper_get_file", arguments))


_SAMPLE = (
    "\n".join(
        [
            "{",
            '  "alpha": 1,',
            '  "beta": 2,',
            '  "gamma": 3,',
            '  "BETA_UPPER": 4,',
            "}",
        ]
    )
    + "\n"
)


# ===========================================================================
# 1. התנהגות
# ===========================================================================


async def test_query_returns_the_hits_and_not_the_content(monkeypatch):
    """העיקר כולו: מופעים במקום תוכן.

    מוטציה שמפילה: להשאיר את ``_HEAVY_FIELDS`` בתשובה ב-
    ``_apply_query_to_file`` — ואז ``code`` חוזר, כלומר הכלי מושך את הקובץ
    המלא בדיוק כמו קודם ורק מוסיף לו רשימה.
    """
    mcp = _build(monkeypatch, _SAMPLE)

    out = await _call(mcp, file_name=_FILE, query="gamma")

    assert out["found"] is True
    assert out["status"] == "query"
    assert out["query"] == "gamma"
    assert out["count"] == 1
    assert out["total"] == 1
    assert out["truncated"] is False
    assert out["results"] == [{"line": 4, "snippet": '"gamma": 3,'}]
    # המטא-דאטה נשארת, התוכן יורד — בשני השמות שהוא יכול לשבת בהם.
    assert out["file"]["file_name"] == _FILE
    assert "code" not in out["file"]
    assert "content" not in out["file"]


async def test_matching_ignores_case_like_search_repo_does(monkeypatch):
    """‏``codekeeper_search_repo`` מריץ ``git grep -i``; אותה סמנטיקה כאן.

    מוטציה שמפילה: להסיר את ה-``casefold`` ב-``scan_file_query`` — ואז
    ``BETA_UPPER`` לא נתפס והספירה יורדת ל-1.
    """
    mcp = _build(monkeypatch, _SAMPLE)

    out = await _call(mcp, file_name=_FILE, query="beta")

    assert [r["line"] for r in out["results"]] == [3, 5]


async def test_context_lines_add_the_window_and_clip_at_the_edges(monkeypatch):
    """אותם שני מפתחות ואותה סמנטיקה כמו ב-``codekeeper_search_repo``."""
    mcp = _build(monkeypatch, _SAMPLE)

    out = await _call(mcp, file_name=_FILE, query="alpha", context_lines=2)

    hit = out["results"][0]
    assert hit["line"] == 2
    # שורה 2 בקובץ: לפניה יש רק אחת, אז החלון נחתך בקצה ואינו מרופד.
    assert hit["context_before"] == ["{"]
    assert hit["context_after"] == ['"beta": 2,', '"gamma": 3,']


async def test_without_context_lines_the_row_keeps_exactly_the_two_keys(monkeypatch):
    """תוספתיות בתוך התוספת: בלי ``context_lines`` אין מפתחות הקשר בכלל.

    זה מה שמשאיר את צורת הרשומה זהה לזו של ``codekeeper_search_repo`` בלי
    הפרמטר — שם ושם, שני המפתחות מתווספים רק כשביקשו אותם.
    """
    mcp = _build(monkeypatch, _SAMPLE)

    out = await _call(mcp, file_name=_FILE, query="alpha")

    assert sorted(out["results"][0]) == ["line", "snippet"]


# ===========================================================================
# 2. שלוש ההחלטות
# ===========================================================================


async def test_query_together_with_lines_is_refused_explicitly(monkeypatch):
    """שני מצבי קריאה שאינם מצטברים — ואף אחד מהם אינו מתעלם בשקט.

    מוטציה שמפילה: להסיר את הבדיקה בראש ``ProductionBackend.get_file``.
    אז הקריאה **מצליחה** ומחזירה מופעים, בזמן שהקורא ביקש גם טווח ואין
    בתשובה שום סימן שהטווח לא קרה. לכן הבדיקה אינה מסתפקת ב-``ok is False``
    אלא גם שוללת במפורש את שתי התשובות ה"תקינות".
    """
    mcp = _build(monkeypatch, _SAMPLE)

    out = await _call(mcp, file_name=_FILE, query="beta", lines=[1, 2])

    assert out == {"ok": False, "error": "query_and_lines"}
    assert "results" not in out  # לא נענה כאילו רק ``query`` הועבר
    assert "range" not in out  # ולא כאילו רק ``lines`` הועבר


async def test_zero_matches_is_a_success_with_an_empty_list(monkeypatch):
    """ "לא נמצא" ו"לא נתמך" הם שני מצבים שונים.

    מוטציה שמפילה: להחזיר ``{"ok": False, "error": "no_matches"}`` כשאין
    מופעים. קורא שמסתעף על ``ok`` היה מתייחס לקובץ תקין כאל כשל.
    """
    mcp = _build(monkeypatch, _SAMPLE)

    out = await _call(mcp, file_name=_FILE, query="לא-קיים-בקובץ")

    assert out["found"] is True
    assert out["status"] == "query"
    assert out["results"] == []
    assert out["count"] == 0
    assert out["total"] == 0
    assert out["truncated"] is False
    assert "ok" not in out and "error" not in out


async def test_an_empty_query_is_refused_and_never_read_as_absent(monkeypatch):
    """‏``query`` של רווחים אינו "בלי ``query``".

    מוטציה שמפילה: ש-``file_query_error`` תחזיר ``None`` על מחרוזת ריקה.
    אז הקריאה נופלת למסלול הרגיל ומחזירה את **הקובץ המלא** — תשובה תקינה
    לגמרי לקורא שביקש מופעים, בלי שום סימן שמה שביקש לא קרה.
    """
    mcp = _build(monkeypatch, _SAMPLE)

    out = await _call(mcp, file_name=_FILE, query="   ")

    assert out == {"ok": False, "error": "query_too_short"}


async def test_the_match_ceiling_is_declared_and_not_a_silent_cut(monkeypatch):
    """חריגה מהתקרה מוצהרת: ``total`` אומר כמה יש, ``truncated`` שהוחזר פחות.

    מוטציה שמפילה: לאתחל ``truncated = False`` במקום ``total > max_results``.
    אז התשובה נראית שלמה — 50 מופעים בלי שום סימן שיש עוד.
    """
    code = "\n".join(f"hit {i}" for i in range(500))
    mcp = _build(monkeypatch, code)

    out = await _call(mcp, file_name=_FILE, query="hit")

    assert out["total"] == 500
    assert out["count"] == handlers.QUERY_RESULTS_DEFAULT
    assert out["truncated"] is True


async def test_max_results_above_the_ceiling_is_clamped_not_rejected(monkeypatch):
    """ההצמדה היא המדיניות המוצהרת בשכבה הזו, ולא דחייה."""
    code = "\n".join(f"hit {i}" for i in range(500))
    mcp = _build(monkeypatch, code)

    out = await _call(mcp, file_name=_FILE, query="hit", max_results=10_000)

    assert out["count"] == handlers.QUERY_RESULTS_MAX
    assert out["truncated"] is True


async def test_the_output_byte_budget_stops_and_says_so(monkeypatch):
    """תקציב הבתים חוסם לפני התקרה, ומסמן — לא חותך בשקט.

    מוטציה שמפילה: להסיר את בדיקת ``used > byte_budget``. אז התשובה מגיעה
    ל-100 רשומות ולמאות אלפי בתים, כלומר חוצה את התקציב שכל שאר הכלים
    בשרת הזה נשפטים מולו.
    """
    line = "hit " + ("x" * 400)
    code = "\n".join([line] * 100)
    mcp = _build(monkeypatch, code)

    out = await _call(mcp, file_name=_FILE, query="hit", max_results=100, context_lines=10)

    assert out["total"] == 100
    assert out["count"] < 100
    assert out["truncated"] is True
    measured = len(json.dumps(out["results"], ensure_ascii=False).encode("utf-8"))
    assert measured <= handlers.QUERY_OUTPUT_BYTE_BUDGET


# ===========================================================================
# 3. עברית: התקרה נמדדת בבתים
# ===========================================================================


def _longest_prefix_within(text: str, max_bytes: int) -> str:
    """מונה בלתי תלוי: מוסיף תו-תו עד שהתקציב נגמר.

    לא קורא ל-``clip_to_bytes``, בכוונה. בדיקה שגוזרת גם את הציפייה וגם את
    התוצאה מאותו מימוש עוברת גם על מימוש שבור.
    """
    out: list[str] = []
    used = 0
    for char in text:
        size = len(char.encode("utf-8"))
        if used + size > max_bytes:
            break
        out.append(char)
        used += size
    return "".join(out)


def test_a_non_string_query_is_refused_by_the_net_behind_the_schema():
    """הסכימה כבר דוחה את זה, וזו רשת שנייה לקורא שאינו עובר דרכה.

    נמדד מול ``pydantic 2.12.3`` — הגרסה שנעולה ב-``requirements/base.txt``:
    ``str | None`` דוחה ``int``, ``float``, ``bool``, ``list`` ו-``dict``
    ב-``string_type``, ולכן דרך ה-MCP הערכים האלה לא מגיעים לקוד בכלל. הבדיקה
    היא על הרשת עצמה, באותה מוסכמה שכבר חלה על בדיקת ה-``bool`` ב-
    ``normalize_line_range``.
    """
    for bad in (5, 5.0, True, ["x"], {"a": 1}, None):
        assert handlers.file_query_error(bad) == handlers.QUERY_INVALID, bad
    # ומחרוזת שמישה עוברת — אחרת הבדיקה הייתה עוברת גם על פונקציה שדוחה הכול.
    assert handlers.file_query_error("x") is None
    assert handlers.file_query_error("    return") is None  # הזחה היא שאילתה תקפה


def test_the_snippet_ceiling_is_bytes_and_the_cut_lands_on_a_character():
    """‏המספר 500 בא מ-``codekeeper_search_repo``; היחידה היא מה שהוחלף.

    הקלט בנוי כך שגבול ה-500 בתים נוחת **באמצע תו**: שני תווים עבריים
    (2 בתים כל אחד) ואחריהם תווים בני 3 בתים, ולכן 500 אינו מתחלק בגבול
    תו. זה המקרה שבו ``encode()[:n]`` לבדו מחזיר רצף פגום.

    שתי מוטציות שמפילות:
    ‏(א) ``text[:max_bytes]`` — חיתוך בתווים; הרשומה תופחת פי שלושה בבתים.
    ‏(ב) החזרת ``encoded[:max_bytes]`` בלי פענוח — התוצאה אינה ``str``.
    """
    line = "שש" + "ℵ" * 250
    assert len(line.encode("utf-8")) > handlers.QUERY_SNIPPET_MAX_BYTES  # הקלט אכן חורג

    clipped = handlers.clip_to_bytes(line, handlers.QUERY_SNIPPET_MAX_BYTES)

    expected = _longest_prefix_within(line, handlers.QUERY_SNIPPET_MAX_BYTES)
    assert clipped == expected
    assert len(clipped.encode("utf-8")) <= handlers.QUERY_SNIPPET_MAX_BYTES
    # מה שמפריד בין השתיים: החסם בתווים היה מחזיר 500 תווים, כלומר יותר
    # מ-1400 בתים. מספר התווים כאן קטן מהחסם דווקא מפני שהוא נמדד בבתים.
    assert len(clipped) < handlers.QUERY_SNIPPET_MAX_BYTES
    # וגבול החיתוך נחת על תו: מה שיצא הוא תחילית אמיתית, בלי תו החלפה.
    assert line.startswith(clipped)
    assert "�" not in clipped


async def test_a_hebrew_snippet_comes_back_whole_through_the_tool(monkeypatch):
    """אותה תקרה, הפעם מקצה לקצה — כולל הסריאליזציה ל-JSON.

    חיתוך באמצע תו לא היה נופל בסורק עצמו אלא כאן, בפענוח אצל הצרכן.
    """
    long_line = "שורה " + "ארוכה " * 200
    mcp = _build(monkeypatch, f"ראש\n{long_line}\nזנב\n")

    out = await _call(mcp, file_name=_FILE, query="ארוכה")

    snippet = out["results"][0]["snippet"]
    assert isinstance(snippet, str)
    assert len(snippet.encode("utf-8")) <= handlers.QUERY_SNIPPET_MAX_BYTES
    assert long_line.startswith(snippet)
    assert "�" not in snippet


# ===========================================================================
# 4. השרשור: מ-``query`` ל-``lines``
# ===========================================================================


async def test_a_reported_line_can_be_read_back_with_lines(monkeypatch):
    """הערך היחיד של העיגון הוא שאפשר להמשיך ממנו לטווח.

    הקובץ כאן מכיל ``\\x0c`` (form feed), ולא סתם: ``splitlines()`` מפצל גם
    עליו ואילו ``split("\\n")`` לא, ולכן שתי החלוקות נותנות מספרי שורות
    שונים לאותה שורה.

    מוטציה שמפילה: ``splitlines()`` ב-``scan_file_query``. ההתאמה עדיין
    נמצאת, ``line`` עדיין נראה תקין — אבל קריאת הטווח על המספר הזה מחזירה
    שורה אחרת, או ``range_out_of_bounds`` בקצה הקובץ. כלומר עיגון שמצביע
    לשומקום, בלי שום שגיאה שמישהו יראה.
    """
    code = "ראשונה\x0cשנייה\nMAX_NOTE_CHARS = 20000\nאחרונה\n"
    mcp = _build(monkeypatch, code)

    found = await _call(mcp, file_name=_FILE, query="MAX_NOTE_CHARS")
    line = found["results"][0]["line"]

    exact = await _call(mcp, file_name=_FILE, lines=[line, line])

    assert exact["found"] is True
    assert exact["file"]["code"] == "MAX_NOTE_CHARS = 20000"
    assert exact["file"]["range"]["start"] == line


# ===========================================================================
# 5. תוספתיות
# ===========================================================================


async def test_a_call_without_query_is_unchanged(monkeypatch):
    """הבדיקה ששומרת על הצרכנים הקיימים.

    בלי ``query`` התשובה היא בדיוק המעטפת הישנה: ``found`` ו-``file`` בלבד,
    התוכן בפנים, ובלי אף שדה מהתשובה החדשה.
    """
    mcp = _build(monkeypatch, _SAMPLE)

    out = await _call(mcp, file_name=_FILE)

    assert sorted(out) == ["file", "found"]
    assert out["file"]["code"] == _SAMPLE
    for added in ("status", "query", "count", "total", "results", "truncated"):
        assert added not in out


async def test_a_document_field_named_status_does_not_change_the_envelope(monkeypatch):
    """צורת התשובה נגזרת ממה שביקשו, ולא משדה במסמך של המשתמש.

    מוטציה שמפילה: להסתעף ב-``server.py`` על ``doc.get("status") == "query"``
    במקום על ``query is not None``. אז מסמך שנושא במקרה שדה בשם הזה חוזר
    בלי המעטפת — ``found`` ו-``file`` נעלמים, וצרכן שמסתעף עליהם נשבר.
    """
    mcp = _build(monkeypatch, _SAMPLE, extra={"status": "query"})

    out = await _call(mcp, file_name=_FILE)

    assert sorted(out) == ["file", "found"]
    assert out["file"]["status"] == "query"  # השדה עצמו עובר כמות שהוא
    assert out["file"]["code"] == _SAMPLE


async def test_a_range_read_is_unchanged(monkeypatch):
    """ואותו דבר לקריאת טווח — ``query`` לא נכנס למסלול שלה."""
    mcp = _build(monkeypatch, _SAMPLE)

    out = await _call(mcp, file_name=_FILE, lines=[2, 3])

    assert sorted(out) == ["file", "found"]
    assert out["file"]["code"] == '  "alpha": 1,\n  "beta": 2,'
    assert out["file"]["range"]["total_lines"] == handlers.count_lines(_SAMPLE)
    assert "status" not in out


# ===========================================================================
# 6. אכיפה
# ===========================================================================


def test_the_query_ceilings_match_the_repo_tool_and_their_stated_values():
    """הקבועים משוכפלים בין שני המודולים, ולכן נאכפים ולא נזכרים.

    **שתי בדיקות ולא אחת, וזה העיקר כאן.** שוויון בין שני העותקים אוכף
    *עקביות*: הוא נשאר ירוק גם אם שניהם ישונו יחד לערך שגוי. לכן כל ערך
    מעוגן גם למספר ליטרלי שכתוב בשורה הזו — אותו מספר שמופיע בטבלת
    הקבועים ב-``docs/mcp-server.rst``. שינוי מכוון של תקרה נוגע בשלושה
    מקומות בכוונה תחילה, והשלישי הוא התיעוד.
    """
    assert handlers.QUERY_RESULTS_DEFAULT == repo_handlers.SEARCH_RESULTS_DEFAULT == 50
    assert handlers.QUERY_RESULTS_MAX == repo_handlers.SEARCH_RESULTS_MAX == 100
    assert handlers.QUERY_CONTEXT_LINES_MAX == repo_handlers.CONTEXT_LINES_MAX == 10
    assert handlers.QUERY_OUTPUT_BYTE_BUDGET == repo_handlers.OUTPUT_BYTE_BUDGET == 256_000
    # תקרת ה-snippet היא המספר של ``codekeeper_search_repo`` ביחידה אחרת,
    # ולכן היא מעוגנת למספר בלבד — אין לה בן-זוג לייבא.
    assert handlers.QUERY_SNIPPET_MAX_BYTES == 500


def test_a_query_read_is_not_counted_as_a_full_file_read():
    """‏``ck_read_mode`` — התווית שהעמודה של האנליטיקס נשענת עליה.

    מוטציה שמפילה: להסיר את ענף ה-``query`` מ-``read_mode_properties``.
    הקריאה נופלת ל-``full``, כלומר קריאה שלא משכה תוכן כלל נספרת כקריאת
    קובץ מלא — וזו בדיוק העמודה שהמאפיין נבנה כדי למדוד.
    """
    request = {
        "method": "tools/call",
        "params": {"name": "codekeeper_get_file", "arguments": {"query": "x"}},
    }

    assert analytics.read_mode_properties(request) == {
        analytics.CK_READ_MODE_KEY: analytics.READ_MODE_QUERY
    }
    # והתווית עוברת את השער — מאפיין משלנו אינו ברשימת ההיתר של ``$mcp_``.
    assert (
        analytics.READ_MODE_QUERY
        in analytics._ALLOWED_CUSTOM_PROPERTIES[analytics.CK_READ_MODE_KEY]
    )


def test_a_rejected_query_and_lines_call_counts_as_the_cheap_read():
    """‏``query`` נבדק לפני ``lines``, כי הקריאה הזו לא קראה תוכן בכלל."""
    request = {
        "method": "tools/call",
        "params": {
            "name": "codekeeper_get_file",
            "arguments": {"query": "x", "lines": [1, 2]},
        },
    }

    assert analytics.read_mode_properties(request) == {
        analytics.CK_READ_MODE_KEY: analytics.READ_MODE_QUERY
    }


def test_the_search_tool_keeps_its_own_query_out_of_the_read_mode_column():
    """‏``codekeeper_search_code`` נושא פרמטר באותו שם, ואינו קריאת קובץ.

    מה שמגן עליו הוא ``FILE_READ_TOOLS`` ולא שם הפרמטר, ולכן זה נבדק.
    """
    request = {
        "method": "tools/call",
        "params": {"name": "codekeeper_search_code", "arguments": {"query": "x"}},
    }

    assert analytics.read_mode_properties(request) is None


async def test_the_schema_rejects_the_wrong_types_on_the_real_call_path(monkeypatch):
    """הדחייה נבדקת דרך הכלי, ולא רק מול ``TypeAdapter``.

    ``context_lines`` הוא ``StrictInt`` ו-``max_results`` אינו — **בדיוק** כמו
    ב-``codekeeper_search_repo``, ולכן האסימטריה הזו היא החלטת עקביות ולא
    מקרה, ומגיעה לה בדיקה. נמדד מול ``pydantic 2.12.3`` ו-``mcp 1.28.1``.

    מוטציה שמפילה: להחליף את ``context_lines: StrictInt`` ב-``int``. אז
    ``context_lines=true`` מתקבל ונעשה ``1`` בשקט — קריאה שביקשה משהו אחר
    וקיבלה תשובה תקינה בלי שום סימן.
    """
    from mcp.server.fastmcp.exceptions import ToolError

    mcp = _build(monkeypatch, _SAMPLE)

    # ``ToolError`` ולא ``Exception``: הדחייה שנבדקת כאן היא ולידציית סכימה,
    # ו-``Exception`` היה עובר גם על שגיאת ייבוא, על נפילת הדמה או על כל
    # תקלה אחרת בדרך — כלומר הבדיקה הייתה ירוקה בלי לבדוק את מה שהיא
    # מתיימרת לבדוק. הטיפוס והטקסט נמדדו מול ``mcp 1.28.1``.
    for bad in ({"query": 5}, {"query": True}, {"query": ["a"]}):
        with pytest.raises(ToolError, match="validation error"):
            await _call(mcp, file_name=_FILE, **bad)
    for bad_ctx in (True, 1.5, "2"):
        with pytest.raises(ToolError, match="validation error"):
            await _call(mcp, file_name=_FILE, query="alpha", context_lines=bad_ctx)

    # ``context_lines`` מעל התקרה **נצמד** ואינו נדחה — זו המדיניות המוצהרת.
    out = await _call(mcp, file_name=_FILE, query="alpha", context_lines=99)
    assert out["count"] == 1
    assert len(out["results"][0]["context_after"]) <= handlers.QUERY_CONTEXT_LINES_MAX


async def test_the_tool_schema_declares_the_new_parameters_compatibly(monkeypatch):
    """הסכימה היא מה שהלקוח רואה, ולכן היא נבדקת ולא מונחת.

    ``query`` מקבל את אותה צורה בדיוק כמו ``file_name`` ו-``symbol``
    הקיימים, ו-``context_lines`` את זו של ``codekeeper_search_repo``. אף
    פרמטר אינו ``required``, ולכן לקוח קיים אינו נשבר.
    """
    mcp = _build(monkeypatch, _SAMPLE)

    tools = {tool.name: (tool.inputSchema or {}) for tool in await mcp.list_tools()}
    schema = tools["codekeeper_get_file"]
    props = schema.get("properties") or {}

    def _shape(prop):
        """הצורה בלי ``title`` ובלי ``description`` — שניהם תצוגה ולא חוזה.

        ‏``title`` הוא שם הפרמטר בצורה קריאה. ``description`` הצטרף אליו
        כשהפירוט על ``query`` עבר מתיאור הכלי ל-``Field(description=...)``
        של הפרמטר, כי התיאור המאוחד הגיע ל-1,726 תווים ונחתך אצל הלקוח.

        **ההחרגה אינה מחלישה את מה שהטסט שומר עליו, וזה נמדד:** ההפרש
        היחיד בין ``query`` ל-``file_name`` הוא המפתח ``description``
        בלבד — ``anyOf`` (מחרוזת או null) ו-``default`` זהים בית-בית,
        ו-``required`` בסכימה הוא ``None``. כלומר תאימות הטיפוס
        והאופציונליות, שתי הטענות של הטסט, נשארות נאכפות; מה שהוחרג הוא
        מטא-דאטה שאינו חלק מחוזה הקריאה ולקוח קיים אינו נשבר ממנו.
        """
        return {
            key: val
            for key, val in prop.items()
            if key not in ("title", "description")
        }

    # אותה צורה בדיוק כמו מחרוזת אופציונלית שכבר קיימת בכלי הזה.
    assert _shape(props["query"]) == _shape(props["file_name"])

    # ‏``context_lines`` ו-``max_results`` **סוטים במכוון** מ-
    # ``codekeeper_search_repo``: שם ברירת המחדל היא הערך עצמו (0 ו-50),
    # וכאן היא ``null``. ההבדל אינו קוסמטי — הוא מה שמאפשר להבדיל בין
    # "לא נשלח" לבין "נשלח בדיוק הערך הזה", ובלעדיו אי אפשר לדחות פרמטר
    # שהועבר בלי ``query``: הוא היה נבלע כברירת מחדל ונזרק בשקט. הטיפוס
    # עצמו נשאר מספר שלם בשני הכלים, ו-``StrictInt`` אינו נראה בסכימה.
    search_props = tools["codekeeper_search_repo"].get("properties") or {}
    for name in ("context_lines", "max_results"):
        assert props[name]["default"] is None
        assert props[name]["anyOf"] == [{"type": "integer"}, {"type": "null"}]
        assert search_props[name]["default"] is not None
    assert not schema.get("required")


# ===========================================================================
# 4. סירוב מפורש במקום שתיקה — תיקוני הריוויו
#
# שלוש הבדיקות הראשונות כאן חולקות שורש אחד: **פרמטר שהתקבל ולא עשה את מה
# שהקורא ביקש, בלי שום סימן.** פעם אחת שאילתה שלא יכלה להתאים, פעם אחת
# פרמטר שנזרק, ופעם אחת קריאה שנספרה בעמודת אנליטיקס לא נכונה. בכל שלוש
# התשובה נראתה תקינה, וזה מה שהופך אותן למסוכנות יותר משגיאה.
# ===========================================================================


async def test_a_multi_line_query_is_refused_and_not_reported_as_zero_matches(monkeypatch):
    """ביטוי שפרוס על שתי שורות **נמצא** בקובץ, וההתאמה נעשית לפי שורה.

    בלי הסירוב הזה ``query in text`` הוא אמת בעוד התשובה מדווחת
    ``total: 0`` **כהצלחה** — "לא נמצא" בטוח על ביטוי שקיים. זה בדיוק מה
    שסוכן מייצר כשהוא מדביק קטע מקובץ שקרא לפני רגע, ולכן זה לא קצה.

    מוטציה שמפילה: להסיר את ``if "\\n" in query`` מ-``file_query_error``.
    אז הקריאה חוזרת ``ok`` עם ``total: 0`` והשוואת הסירוב כאן נופלת.
    """
    mcp = _build(monkeypatch, _SAMPLE)
    needle = '"alpha": 1,\n  "beta"'
    # זו השורה שהופכת את האפס לשקר ולא לתשובה: הביטוי באמת בתוך הקובץ.
    assert needle in _SAMPLE

    assert await _call(mcp, file_name=_FILE, query=needle) == {
        "ok": False,
        "error": handlers.QUERY_MULTILINE,
    }

    # והצד השני, כדי שהסירוב לא יתרחב בשקט: שאילתה חד-שורתית עובדת.
    out = await _call(mcp, file_name=_FILE, query='"alpha"')
    assert out["total"] == 1


async def test_context_lines_and_max_results_are_refused_without_query(monkeypatch):
    """פרמטר שמתאר **איך להציג מופעים** חסר משמעות כשאין מופעים.

    זו אותה הכרעה שמאחורי ``query_and_lines``: שני מצבים שאינם מצטברים
    נדחים במפורש, ואין הנמכה חשאית של אחד מהם. פרמטר שהתקבל ונזרק הוא
    אותה שתיקה בדיוק.

    מוטציה שמפילה: להחזיר ל-``handlers.get_file`` הצמדה של ``None`` ל-0
    ול-50. אז "לא נשלח" ו"נשלח 0" נראים זהים ב-backend, הסירוב אינו יכול
    לפעול, וארבע ההשוואות כאן נופלות.
    """
    mcp = _build(monkeypatch, _SAMPLE)

    assert await _call(mcp, file_name=_FILE, context_lines=5) == {
        "ok": False,
        "error": handlers.CONTEXT_LINES_WITHOUT_QUERY,
    }
    assert await _call(mcp, file_name=_FILE, max_results=7) == {
        "ok": False,
        "error": handlers.MAX_RESULTS_WITHOUT_QUERY,
    }
    # גם לצד ``lines``: ``context_lines`` אינו חלק מקריאת טווח.
    assert await _call(mcp, file_name=_FILE, lines=[1, 2], context_lines=5) == {
        "ok": False,
        "error": handlers.CONTEXT_LINES_WITHOUT_QUERY,
    }
    # ו-**0 אינו "לא נשלח"**. זו הבדיקה שמוכיחה שההבחנה אמיתית ולא נשענת
    # על ערך שבמקרה שווה לברירת המחדל הישנה.
    assert await _call(mcp, file_name=_FILE, context_lines=0) == {
        "ok": False,
        "error": handlers.CONTEXT_LINES_WITHOUT_QUERY,
    }

    # ובלי אף אחד מהם — בדיוק מה שהכלי החזיר לפני כל זה.
    plain = await _call(mcp, file_name=_FILE)
    assert set(plain) == {"found", "file"}
    assert plain["file"]["code"] == _SAMPLE


def test_the_read_mode_column_reads_only_the_parameter_each_tool_declares(caplog):
    """‏``outline`` שייך לכלי הריפו ו-``query`` לכלי הקבצים — לא להפך.

    הקולבק מקבל את מילון הארגומנטים **הגולמי**, לפני ש-pydantic מסלק ממנו
    מפתחות שאינם בסכימה של הכלי. לכן מפתח תועה של הכלי האחר מגיע לכאן,
    והתשובה נספרת בעמודה הלא נכונה: לא רק שהעמודה שלו מתנפחת, אלא ששתי
    האחרות יוצאות חסרות באותה מידה. שום שגיאה אינה נראית.

    מוטציה שמפילה: להחזיר את הבדיקה הלא-מותנית של ``outline`` / ``query``
    (כלומר להתעלם מ-``_TOOL_READ_MODE_PARAMS``). ארבע ההשוואות הראשונות
    כאן נופלות — שתיים לכל כיוון.
    """

    def mode(name, arguments):
        return analytics.read_mode_properties(
            {"method": "tools/call", "params": {"name": name, "arguments": arguments}}
        )

    key = analytics.CK_READ_MODE_KEY

    # ``outline`` אינו פרמטר של ``codekeeper_get_file``.
    assert mode("codekeeper_get_file", {"outline": True}) == {key: analytics.READ_MODE_FULL}
    assert mode("codekeeper_get_file", {"outline": True, "lines": [1, 2]}) == {
        key: analytics.READ_MODE_RANGE
    }
    # ``query`` אינו פרמטר של ``codekeeper_get_repo_file``.
    assert mode("codekeeper_get_repo_file", {"query": "x"}) == {key: analytics.READ_MODE_FULL}
    assert mode("codekeeper_get_repo_file", {"query": "x", "lines": [1, 2]}) == {
        key: analytics.READ_MODE_RANGE
    }

    # וכל כלי כן נספר לפי הפרמטר שבאמת שלו.
    assert mode("codekeeper_get_file", {"query": "x"}) == {key: analytics.READ_MODE_QUERY}
    assert mode("codekeeper_get_repo_file", {"outline": True}) == {key: analytics.READ_MODE_OUTLINE}

    # שם כלי שאינו מחרוזת: ``dict.get`` מגבב את המפתח, וערך לא-hashable
    # מייצר ``TypeError``.
    #
    # **מה שנבדק כאן הוא הלוג ולא ערך ההחזרה**, ובכוונה. ה-``except`` שעוטף
    # את הפונקציה מחזיר ``None`` בכל מקרה, ולכן השוואה ל-``None`` לבדה
    # עוברת גם בלי ההגנה — כלומר אינה מסוגלת ליפול על מה שהיא בודקת.
    # ההבדל האמיתי נמדד: בלי ההגנה כל אירוע כזה כותב אזהרה עם traceback,
    # ועם ההגנה התשובה היא "זו אינה קריאת קובץ" בלי שום רעש.
    with caplog.at_level(logging.WARNING, logger="mcp_server.analytics"):
        assert mode(["codekeeper_get_file"], {"query": "x"}) is None
        assert mode({"a": 1}, {"query": "x"}) is None
    assert caplog.records == []


async def test_the_read_mode_map_matches_the_schemas_the_tools_declare(monkeypatch):
    """המפה נגזרת מהסכימה, ולא מהזיכרון של מי שכתב אותה.

    ``analytics.py`` אינו יכול לייבא מ-``server.py`` (ייבוא מעגלי), ולכן
    שיוך הפרמטרים כתוב שם ביד. כאן נשאלים הכלים הרשומים עצמם אילו פרמטרי
    קריאה הם מצהירים עליהם בפועל. כלי שיקבל מחר ``query`` בלי שהמפה
    תעודכן מפיל את הבדיקה, במקום להיספר בעמודה הלא נכונה בשקט.

    ``lines`` הוא מה שמגדיר "קריאת תוכן קובץ", וזו אותה הגדרה שכבר משמשת
    את הבדיקה המקבילה על ``FILE_READ_TOOLS``.
    """
    mcp = _build(monkeypatch, _SAMPLE)

    read_mode_params = {"outline", "query", "lines"}
    declared = {}
    for tool in await mcp.list_tools():
        owned = set((tool.inputSchema or {}).get("properties") or {}) & read_mode_params
        if "lines" in owned:
            declared[tool.name] = frozenset(owned)

    assert declared == analytics._TOOL_READ_MODE_PARAMS
    assert frozenset(declared) == analytics.FILE_READ_TOOLS


def test_the_tool_description_takes_its_ceilings_from_the_constants(monkeypatch):
    """המספרים שהסוכן קורא נשתלים מהקבועים, ואינם כתובים כטקסט.

    בלי זה, העלאת ``QUERY_RESULTS_MAX`` משאירה את התיאור מבטיח את המספר
    הישן והסוויטה נשארת ירוקה — כלומר כל סוכן מגביל את עצמו לתקרה שכבר
    אינה התקרה. אותה מוסכמה שכבר נאכפת על תיאור הכלי האח ב-
    ``tests/test_mcp_server_build.py``.

    הבדיקה מריצה את הבנייה מחדש עם קבועים אחרים במקום להסתפק בהשוואה
    לערכים הנוכחיים: השוואה כזו עוברת גם על טקסט קשיח שבמקרה נכון היום,
    כלומר אינה מסוגלת ליפול על מה שהיא אמורה לתפוס.

    מוטציה שמפילה: להחזיר את המספרים כטקסט קשיח ב-``_build_query_doc``.
    """
    from mcp_server import server

    assert f"as far as {handlers.QUERY_RESULTS_MAX}" in server._QUERY_DOC

    monkeypatch.setattr(handlers, "QUERY_RESULTS_DEFAULT", 7)
    monkeypatch.setattr(handlers, "QUERY_RESULTS_MAX", 123)
    monkeypatch.setattr(handlers, "QUERY_CONTEXT_LINES_MAX", 4)
    rebuilt = server._build_query_doc()

    assert "7 hits come back by default" in rebuilt
    assert "as far as 123" in rebuilt
    assert "(0-4)" in rebuilt
    assert "as far as 100" not in rebuilt


async def test_query_answers_the_same_way_on_every_document_selection_path(monkeypatch):
    """‏``query`` רץ **אחרי** בחירת המסמך, ולכן שלושת המסלולים שקולים.

    זו טענה שהייתה כתובה ולא נבדקה. ``file_id`` ו-``version`` לא הופיעו
    באף בדיקה בקובץ הזה, וכך גם קובץ חסר — כלומר שלושה מסלולי תשובה על
    קוד חדש עברו בלי כיסוי. ההתנהגות נכונה בכולם, ומה שנוסף כאן הוא
    השמירה עליה.
    """
    mcp = _build(monkeypatch, _SAMPLE, old_code='{\n  "alpha": 99,\n}\n')

    # קובץ חסר: "לא נמצא", ולא מעטפת שגיאה.
    assert await _call(mcp, file_name="nope.json", query="alpha") == {"found": False}

    # והשער קודם לקריאה למסד — גם כשהקובץ אינו קיים בכלל.
    assert await _call(mcp, file_name="nope.json", query="a", lines=[1, 2]) == {
        "ok": False,
        "error": handlers.QUERY_AND_LINES,
    }
    assert await _call(mcp, file_name="nope.json", query="  ") == {
        "ok": False,
        "error": handlers.QUERY_TOO_SHORT,
    }

    # לפי מזהה: אותו מסמך, אותה תשובה.
    by_id = await _call(mcp, file_id=_DOC_ID, query="alpha")
    by_name = await _call(mcp, file_name=_FILE, query="alpha")
    assert by_id["results"] == by_name["results"]
    assert by_id["file"]["version"] == 2

    # לפי גרסה: החיפוש רץ על **התוכן של הגרסה שנבחרה**, לא על האחרונה.
    old = await _call(mcp, file_name=_FILE, version=1, query="99")
    assert old["file"]["version"] == 1
    assert old["total"] == 1
    # ואותה שאילתה על הגרסה האחרונה אינה מוצאת דבר — כלומר באמת נסרק
    # תוכן אחר, ולא אותו מסמך עם מספר גרסה שונה.
    assert (await _call(mcp, file_name=_FILE, query="99"))["total"] == 0


async def test_a_malformed_request_is_refused_even_when_no_file_was_named(monkeypatch):
    """בקשה פגומה היא פגומה בלי קשר לקובץ שהיא נוקבת בו.

    ``{"found": false}`` היא תשובה על **קובץ**. קריאה ששכחה גם את שם הקובץ
    וגם העבירה ``query`` יחד עם ``lines`` קיבלה אותה — כלומר "הקובץ אינו
    קיים" על קריאה שלא נקבה בשום קובץ. הסוכן קורא את זה כתשובה על הקובץ
    שלו והולך לחפש אותו, במקום לתקן את צורת הקריאה. אותה מחלקה בדיוק שאר
    התיקונים בקובץ הזה עוסקים בה.

    מוטציה שמפילה: להחזיר את בדיקת המזהה ב-``handlers.get_file`` לפני
    הקריאה ל-``file_query_request_error``.
    """
    mcp = _build(monkeypatch, _SAMPLE)

    assert await _call(mcp, query="a", lines=[1, 2]) == {
        "ok": False,
        "error": handlers.QUERY_AND_LINES,
    }
    assert await _call(mcp, query="   ") == {"ok": False, "error": handlers.QUERY_TOO_SHORT}
    assert await _call(mcp, query="a\nb") == {"ok": False, "error": handlers.QUERY_MULTILINE}
    assert await _call(mcp, context_lines=5) == {
        "ok": False,
        "error": handlers.CONTEXT_LINES_WITHOUT_QUERY,
    }
    assert await _call(mcp, max_results=7) == {
        "ok": False,
        "error": handlers.MAX_RESULTS_WITHOUT_QUERY,
    }

    # וקריאה שלא ביקשה דבר נשארת "לא נמצא" ואינה הופכת לשגיאה.
    assert await _call(mcp) == {"found": False}


def test_both_layers_refuse_through_the_same_function():
    """לסולם הסירוב יש בעל בית אחד, ולא שני עותקים שיכולים להיפרד.

    הבדיקה תופסת את שני המצבים שבהם זה נשבר. הראשון: שכבת ה-handlers
    מפסיקה לסרב ומעבירה בקשה פגומה הלאה — כאן זה נראה כ-backend מזויף
    שהיה מחזיר מסמך על ``query``+``lines``. השני: ה-backend מקבל עותק
    משלו של אותה לוגיקה, וזיהוי האובייקט מפסיק להתקיים.
    """
    from mcp_server import backend as backend_mod

    class _Fake:
        """backend שאינו יודע דבר על ולידציה — הוא פשוט מחזיר מסמך."""

        def __init__(self):
            self.called = False

        def get_file(self, *args, **kwargs):
            self.called = True
            return {"file_name": _FILE, "code": _SAMPLE}

    fake = _Fake()
    assert handlers.get_file(fake, _USER, file_name=_FILE, query="a", lines=[1, 2]) == {
        "ok": False,
        "error": handlers.QUERY_AND_LINES,
    }
    assert fake.called is False

    # ושזו אותה פונקציה בדיוק, ולא שם זהה על שני מימושים.
    assert backend_mod.file_query_request_error is handlers.file_query_request_error
