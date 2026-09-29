"""מצבי ``toc`` ו-``section`` ב-``codekeeper_get_file`` — קריאה לפי סעיף בקובץ Markdown שמור.

הבדיקות עוברות דרך **ממשק ה-MCP** (``mcp.call_tool``) מעל ``ProductionBackend``
אמיתי ודמה של שכבת המסד, כי זה הממשק שהסוכן מפעיל בפועל. מעטות טהורות במכוון —
רשתות הוולידציה שמאחורי הסכימה, והתווית של האנליטיקס — כי שם מה שנבדק הוא
פונקציה ולא זרימה.

חמש קבוצות:

1. **התנהגות** — מפה, סעיף, מזהה, עימוד, גרסה ומזהה קובץ.
2. **סירובים** — כל זוג מצבים בקוד משלו, פרמטר בלי המצב שלו, קובץ שאינו
   Markdown, קובץ גדול מכדי לפרסר, וכל סירוב של הפרסר.
3. **שימוש חוזר** — שני הכלים עוברים באותן פונקציות בדיוק, ולא בעותק.
4. **תוספתיות** — קריאה בלי הפרמטרים החדשים מחזירה בדיוק את מה שחזר קודם.
5. **אכיפה** — התווית באנליטיקס, והתיאורים שהסוכן קורא.

כל בדיקה כאן הורצה על הקוד **שלפני** התוספת (T2), וגם תחת מוטציה נקודתית
שמבטלת בדיוק את מה שהיא בודקת; המוטציה כתובה בגוף כל בדיקה.
"""

import functools
import hashlib
import itertools
import json
import random

import pytest
from pydantic import ValidationError

from mcp_server import analytics, answer_fit, answer_size, docs_handlers, handlers, read_batch
from services import doc_sections, md_parser

pytest.importorskip("mcp")


# ---------------------------------------------------------------------------
# עזרים
# ---------------------------------------------------------------------------

_USER = 7
_OTHER_USER = 8
_MD_NAME = "Handoff.md"
_DOC_ID = "doc-v2"
_OLD_DOC_ID = "doc-v1"

# הקובץ שרוב הבדיקות קוראות. מספרי השורות בהערות הם מה שהבדיקות נוקבות בו.
_LINES = [
    "# מדריך",                # 1
    "",                       # 2
    "פתיחה.",                 # 3
    "",                       # 4
    "## K11. חריגה נבלעת",    # 5
    "",                       # 6
    "גוף K11.",               # 7
    "",                       # 8
    "### תת-סעיף",            # 9
    "",                       # 10
    "עומק.",                  # 11
    "",                       # 12
    "## K12 כפול",            # 13
    "",                       # 14
    "ראשון.",                 # 15
    "",                       # 16
    "## K12 כפול",            # 17
    "",                       # 18
    "שני.",                   # 19
]
# השורה האחרונה ריקה (הקובץ נגמר ב-``\n``), ולכן הקובץ הוא 20 שורות.
_MD = "\n".join(_LINES) + "\n"
# הגרסה הקודמת של אותו קובץ — תוכן אחר, כדי שיהיה אפשר לדעת איזו נקראה.
_OLD_MD = "# מדריך\n\n## K11. חריגה נבלעת\n\nגרסה ישנה.\n"


def _source(text: str, start: int, end: int) -> str:
    """שורות ``start``..``end`` של ``text`` (כולל, מ-1) — בדיוק כמו ``lines=``."""
    return "\n".join(text.split("\n")[start - 1:end])


class _Dbm:
    """דמה של שכבת המסד: קובץ אחד בשתי גרסאות, לפי שם / גרסה / מזהה.

    שלוש השיטות הן שלוש השיטות ש-``ProductionBackend.get_file`` קורא, באותן
    חתימות בדיוק כמו ב-``database/manager.py``. ``get_file_by_id`` **אינה
    מסננת לפי משתמש**, בדיוק כמו האמיתית — הבעלות נאכפת ב-backend, וזה מה
    שהופך את הבדיקה עליה למשמעותית. ``calls`` רושם כל פנייה, כדי שבדיקה
    תוכל לומר "הבקשה נדחתה לפני שנגענו במסד".
    """

    def __init__(self, code: str = _MD, *, file_name: str = _MD_NAME,
                 language: str | None = "markdown", old_code: str | None = _OLD_MD,
                 owner: int = _USER, extra: dict | None = None):
        self._code = code
        self._file_name = file_name
        self._language = language
        self._old_code = old_code
        self._owner = owner
        # שדות מטא-דאטה נוספים, כמו במסמך אמיתי (``tags``, ``description``) — ריק כברירת מחדל.
        self._extra = dict(extra or {})
        self.calls: list[str] = []

    def _doc(self, code: str, version: int, doc_id: str) -> dict:
        return {
            "_id": doc_id,
            "user_id": self._owner,
            "file_name": self._file_name,
            "version": version,
            "code": code,
            "programming_language": self._language,
            "is_active": True,
            **self._extra,
        }

    def get_latest_version_fresh(self, user_id: int, file_name: str):
        self.calls.append("get_latest_version_fresh")
        if user_id != self._owner or file_name != self._file_name:
            return None
        return self._doc(self._code, 2, _DOC_ID)

    def get_version(self, user_id: int, file_name: str, version: int):
        self.calls.append("get_version")
        if user_id != self._owner or file_name != self._file_name:
            return None
        if version == 2:
            return self._doc(self._code, 2, _DOC_ID)
        if version == 1 and self._old_code is not None:
            return self._doc(self._old_code, 1, _OLD_DOC_ID)
        return None

    def get_file_by_id(self, file_id: str):
        self.calls.append("get_file_by_id")
        if file_id == _DOC_ID:
            return self._doc(self._code, 2, _DOC_ID)
        if file_id == _OLD_DOC_ID and self._old_code is not None:
            return self._doc(self._old_code, 1, _OLD_DOC_ID)
        return None


class _RepoText:
    """ריפו מראה שמגיש טקסט אחד לכל נתיב — בשביל ``codekeeper_docs_get_section``.

    החתימה היא של ``RepoBackend.get_file`` (``mcp_server/repo_backend.py``), כולל
    הפרמטרים שהכלי אינו מעביר, כדי שקריאה שתתחיל להעביר אחד מהם לא תיבלע כאן.
    """

    def __init__(self, text: str):
        self._text = text

    def get_file(self, *, repo, path, ref=None, lines=None, outline=False,
                 symbol=None, page=1, per_page=100, snapshot=None):
        return {"ok": True, "status": "ok",
                "file": {"path": path, "ref": "HEAD", "resolved_commit": "c0ffee"},
                "content": self._text}


def _build(monkeypatch, dbm: _Dbm | None = None, repo_backend=None):
    """שרת MCP אמיתי מעל ``ProductionBackend`` אמיתי."""
    import mcp_server.server as srv
    from mcp_server.backend import ProductionBackend

    # ``build_mcp`` קורא ל-``instrument_mcp_server``, שזורק מחוץ לפרודקשן כשאין
    # קונפיגורציית PostHog — הקיבוע הוא כדי שהבדיקה לא תעבור או תיפול לפי
    # ה-``ENVIRONMENT`` של מי שהריץ אותה.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: _USER)
    return srv.build_mcp(
        ProductionBackend(db_manager=dbm if dbm is not None else _Dbm()),
        repo_backend=repo_backend if repo_backend is not None else object(),
    )


def _payload(result):
    """התשובה של הכלי, מפוענחת — ``FastMCP.call_tool`` של ``mcp 1.28.1`` מחזיר בלוקים."""
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


async def _call(mcp, **arguments):
    return _payload(await mcp.call_tool("codekeeper_get_file", arguments))


def _sections_only(dbm: _Dbm, *, toc: bool = False, section: str | None = None):
    """``_apply_sections_to_file`` על הגרסה האחרונה של הדמה — **בלי** ``_fit_with_file_meta`` מעליו.

    מאז ריוויו Han על #3492 (WARN-001) הכלי אינו מחזיר סירוב שהמטא-דאטה לבדה גרמה לו: הוא
    מנסה שוב בלעדיה. החשבון של הסירוב (``bytes = size + reserve_bytes``) עדיין רץ בניסיון
    הראשון, והטסטים שבודקים אותו קוראים לו כאן ישירות, עם התיאור כמנוף. ``toc`` כאן רק
    אומר "בלי ``section``", כמו בכלי. מחזיר את התשובה ואת הבתים שלה כפי שהכלי היה שולח.
    """
    from mcp_server import backend as backend_mod

    assert toc != (section is not None), "toc או section, כמו בכלי"
    out = backend_mod._full(dbm._doc(dbm._code, 2, _DOC_ID))
    answer = backend_mod._apply_sections_to_file(out, section=section, max_chars=None, offset=None)
    return answer, len(answer_size.wire_json(answer))


async def _call_sent(mcp, tool="codekeeper_get_file", **arguments):
    """התשובה **ומספר הבתים שלה כפי שה-SDK שלח אותה** — בלוק הטקסט עצמו, לא הערכה."""
    result = await mcp.call_tool(tool, arguments)
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text), len(blocks[0].text.encode("utf-8"))


def _wide_lines(char: str, count: int, width: int = 80) -> str:
    """``count`` פעמים ``char``, בשורות של ``width`` — גוף של סעיף ארוך בתו אחד."""
    body = char * count
    return "\n".join(body[i:i + width] for i in range(0, len(body), width))


def _deep_hebrew_map(count: int = docs_handlers._TOC_MAX, width: int = 120) -> str:
    """``count`` כותרות עבריות ברוחב ``width``, בקינון שחוזר על עומק 1 עד 6.

    המפה גדלה פי כמה מהקובץ, כי כל פריט בה נושא את כל ה-breadcrumb שלו — בעומק
    שש אותה כותרת נכתבת שש פעמים. ובדיוק ``_TOC_MAX`` כותרות, כדי שהתקרה במספר
    פריטים לא תחתוך כלום: מה שנחתך כאן, נחתך בגלל הבתים.
    """
    return "".join("#" * (1 + i % 6) + " " + (f"{i} " + "כותרת " * 40)[:width] + "\n\nפסקה.\n\n"
                   for i in range(count))


def _distinct_cjk(length: int) -> str:
    """``length`` תווי CJK שונים זה מזה — כותרת ארוכה ש-``difflib`` לא יתעלם ממנה.

    ל-``SequenceMatcher`` יש ``autojunk``: במחרוזת של יותר מ-200 תווים, תו שמופיע ביותר
    מאחוז ממנה נחשב זבל. כותרת של תו אחד שחוזר הייתה מקבלת יחס נמוך ואפס הצעות.
    """
    return "".join(chr(0x4E00 + i) for i in range(length))


def _meta(*, code: str = _MD, version: int = 2, doc_id: str = _DOC_ID,
          file_name: str = _MD_NAME, language: str | None = "markdown") -> dict:
    """המטא-דאטה שתשובה נושאת ב-``file``: המסמך בלי התוכן, עם הכינוי ``language``.

    ``content_sha256`` הוא של ``code`` — התוכן **המלא** של המסמך שנקרא, לא של המפה
    או הסעיף שחזרו — ומחושב כאן ביד, ולא דרך הפונקציה של ``backend``.
    """
    meta = {
        "id": doc_id,
        "user_id": _USER,
        "file_name": file_name,
        "version": version,
        "programming_language": language,
        "is_active": True,
    }
    meta["language"] = language
    meta["content_sha256"] = hashlib.sha256(code.encode("utf-8")).hexdigest()
    return meta


_HINT = handlers.SECTIONS_UNAVAILABLE_HINT


# ---------------------------------------------------------------------------
# 1. התנהגות
# ---------------------------------------------------------------------------


async def test_toc_returns_the_heading_map_instead_of_the_content(monkeypatch):
    """``toc=true`` מחזיר את מפת הכותרות, ולא את הקובץ.

    כל פריט נושא ``approx_bytes`` — גודל הסעיף בבתים — כדי שסוכן יוכל לבחור
    סעיף בלי לקרוא אותו. הערך כאן מחושב מהמקור ביד, ולא מאותה פונקציה.

    מוטציה שמפילה: להוריד את ``toc`` מהתנאי ב-``ProductionBackend.get_file``
    (``if section is not None``) — הקובץ המלא חוזר, ואין ``toc``.
    """
    mcp = _build(monkeypatch)

    out = await _call(mcp, file_name=_MD_NAME, toc=True)

    assert out["found"] is True and out["status"] == "toc"
    assert out["ok"] is True and out["mode"] == "toc"
    assert out["file"] == _meta()
    assert "content" not in out and "code" not in out
    assert out["section_count"] == 5 and out["toc_truncated"] is False
    assert [(t["title"], t["level"], t["line_range"]) for t in out["toc"]] == [
        ("מדריך", 1, [1, 20]),
        ("K11. חריגה נבלעת", 2, [5, 12]),
        ("תת-סעיף", 3, [9, 12]),
        ("K12 כפול", 2, [13, 16]),
        ("K12 כפול", 2, [17, 20]),
    ]
    k11 = out["toc"][1]
    assert k11["breadcrumb"] == ["מדריך", "K11. חריגה נבלעת"]
    assert k11["approx_bytes"] == len(_source(_MD, 5, 12).encode("utf-8"))


async def test_section_returns_one_section_with_its_navigation(monkeypatch):
    """``section`` מחזיר סעיף אחד — עם תת-הסעיפים שלו — ואת הניווט סביבו.

    מוטציה שמפילה: להוריד את ``section`` מהתנאי ב-``ProductionBackend.get_file``
    — הקובץ המלא חוזר.
    """
    mcp = _build(monkeypatch)

    out = await _call(mcp, file_name=_MD_NAME, section="K11. חריגה נבלעת")

    assert out["found"] is True and out["status"] == "section"
    assert out["ok"] is True and out["mode"] == "section"
    assert out["file"] == _meta()
    assert out["section"] == "K11. חריגה נבלעת"
    assert out["breadcrumb"] == ["מדריך", "K11. חריגה נבלעת"]
    assert out["level"] == 2 and out["line_range"] == [5, 12]
    assert out["content"] == _source(_MD, 5, 12)
    assert out["include_subsections"] is True
    assert out["truncated"] is False and out["offset"] == 0
    assert out["subsections"] == [{"title": "תת-סעיף", "level": 3, "line_range": [9, 12]}]
    assert out["neighbors"] == {
        "prev": None,
        "next": {"title": "K12 כפול", "level": 2, "line_range": [13, 16]},
    }


async def test_an_identifier_finds_the_heading_that_opens_with_it(monkeypatch):
    """``section="K11"`` מוצא את ``K11. חריגה נבלעת`` — אותו כלל של ``docs_get_section``.

    מה שנבדק כאן הוא שהכלל **הגיע** לכלי הזה: ההתאמה עצמה נבדקת ב-
    ``tests/test_doc_sections.py``, והשיתוף — בבדיקת השימוש החוזר למטה.
    """
    mcp = _build(monkeypatch)

    by_id = await _call(mcp, file_name=_MD_NAME, section="K11")
    by_title = await _call(mcp, file_name=_MD_NAME, section="K11. חריגה נבלעת")

    assert by_id == by_title


async def test_a_missing_heading_answers_with_the_map_and_a_repeated_one_with_candidates(
        monkeypatch):
    """לעולם לא רק "לא נמצא": מפה והצעות, או מועמדים עם breadcrumb.

    והתשובה נושאת את ``file`` גם בסירוב — הקורא יודע איזה קובץ ואיזו גרסה נבדקו.
    אין בה ``found`` ו-``status``: זה סירוב (``ok: false``), והוא עובר כמו שהוא.
    """
    mcp = _build(monkeypatch)

    missing = await _call(mcp, file_name=_MD_NAME, section="K99")
    assert missing["ok"] is False and missing["error"] == "section_not_found"
    assert missing["requested"] == "K99"
    assert missing["file"] == _meta()
    assert [t["title"] for t in missing["toc"]][:2] == ["מדריך", "K11. חריגה נבלעת"]
    assert "found" not in missing and "status" not in missing

    repeated = await _call(mcp, file_name=_MD_NAME, section="K12 כפול")
    assert repeated["ok"] is False and repeated["error"] == "ambiguous_section"
    assert repeated["file"] == _meta()
    assert [c["line_range"] for c in repeated["candidates"]] == [[13, 16], [17, 20]]


async def test_a_long_section_is_paged_with_max_chars_and_offset(monkeypatch):
    """``max_chars`` חותך, ``offset`` ממשיך, והחלקים מתחברים בדיוק לסעיף.

    וההצמדה היא של ``docs_handlers`` — ``max_chars=10`` נצמד ל-``MAX_CHARS_MIN``,
    כמו ב-``codekeeper_docs_get_section``.

    מוטציה שמפילה: לא להעביר את ``max_chars``/``offset`` מ-``_apply_sections_to_file``
    ל-``answer_section`` — הסעיף חוזר שלם בחלק הראשון.
    """
    body = "".join(f"שורה {i} — " + "טקסט עברי ארוך. " * 8 + "\n" for i in range(12))
    text = "# ארוך\n\n" + body
    total_lines = text.count("\n") + 1
    full = _source(text, 1, total_lines)
    assert len(full) > 2 * docs_handlers.MAX_CHARS_MIN, "הנחת המקרה: הסעיף ארוך מעמוד אחד"
    mcp = _build(monkeypatch, _Dbm(text))

    first = await _call(mcp, file_name=_MD_NAME, section="ארוך", max_chars=600)
    assert first["content"] == full[:600]
    assert first["truncated"] is True and first["next_offset"] == 600
    assert first["remaining_chars"] == len(full) - 600

    rest = await _call(mcp, file_name=_MD_NAME, section="ארוך",
                       offset=first["next_offset"], max_chars=docs_handlers.MAX_CHARS_MAX)
    assert rest["offset"] == 600 and rest["truncated"] is False
    assert first["content"] + rest["content"] == full

    clamped = await _call(mcp, file_name=_MD_NAME, section="ארוך", max_chars=10)
    assert len(clamped["content"]) == docs_handlers.MAX_CHARS_MIN


@pytest.mark.parametrize("char", ["汉", "😀", "\x01"], ids=["cjk", "emoji", "control"])
async def test_a_page_of_wide_characters_ends_early_inside_the_byte_budget(monkeypatch, char):
    """עמוד של ``MAX_CHARS_MAX`` תווים רחבים נגמר מוקדם — בתוך ``OUTPUT_BYTE_BUDGET``.

    ``max_chars`` סופר תווים, והתקציב הוא בתים **כפי שנשלחו**: תו CJK הוא שלושה
    בתים, אימוג'י ארבעה, ותו בקרה הוא שישה ב-JSON (``\\u0001``). לכן עמוד מלא עבר
    את התקציב, והבדיקה מודדת את בלוק הטקסט שה-SDK החזיר, ולא הערכה. העמוד מתחיל
    בתחילת הסעיף, ``next_offset`` הוא איפה שהוא באמת נגמר, ו-``truncation_reason``
    אומר למה חזרו פחות מ-``max_chars``.

    על הקוד שלפני התיקון, בדיוק המקרים האלה: עמוד ה-CJK יצא ב-299,373 בתים, עמוד
    האימוג'י ב-398,132 ועמוד תווי הבקרה ב-595,650. ותווי הבקרה הם גם מה שתפס את
    הגרסה הראשונה של התיקון — ראו ``_fit_page``.
    מוטציה שמפילה: להחזיר את ``base`` ב-``_answer_from_document`` בלי ``_fit_page``.
    """
    text = "# רחב\n\n" + _wide_lines(char, 120_000) + "\n"
    full = _source(text, 1, text.count("\n") + 1)
    mcp = _build(monkeypatch, _Dbm(text))

    out, sent = await _call_sent(mcp, file_name=_MD_NAME, section="רחב",
                                 max_chars=docs_handlers.MAX_CHARS_MAX)

    assert sent <= answer_size.OUTPUT_BYTE_BUDGET
    assert out["truncated"] is True and out["truncation_reason"] == "byte_budget"
    assert 0 < len(out["content"]) < docs_handlers.MAX_CHARS_MAX
    assert out["content"] == full[:len(out["content"])]
    assert out["next_offset"] == len(out["content"])
    assert out["remaining_chars"] == len(full) - out["next_offset"]


async def test_paging_by_bytes_loses_nothing(monkeypatch):
    """ממשיכים מ-``next_offset`` עד ש-``truncated`` כבה — והעמודים מתחברים בדיוק לסעיף.

    זה מה שמבדיל עמוד שנגמר מוקדם מחיתוך: שום תו לא נופל בין עמוד לעמוד, כל
    עמוד בתוך התקציב, וכל קריאה מתקדמת.

    מוטציה שמפילה: לחשב ב-``_fit_page`` את ``next_offset`` מאורך העמוד לפני
    החיתוך — העמוד הבא מדלג על מה שנחתך, והחיבור אינו הסעיף.
    """
    text = "# רחב\n\n" + _wide_lines("汉", 150_000) + "\n"
    full = _source(text, 1, text.count("\n") + 1)
    mcp = _build(monkeypatch, _Dbm(text))

    pages: list[str] = []
    offset = 0
    while True:
        out, sent = await _call_sent(mcp, file_name=_MD_NAME, section="רחב", offset=offset,
                                     max_chars=docs_handlers.MAX_CHARS_MAX)
        assert sent <= answer_size.OUTPUT_BYTE_BUDGET
        assert out["offset"] == offset
        pages.append(out["content"])
        if not out["truncated"]:
            break
        assert out["next_offset"] > offset
        offset = out["next_offset"]

    assert len(pages) >= 2
    assert "".join(pages) == full


async def test_the_page_leaves_room_for_found_and_status(monkeypatch):
    """העמוד נחתך אל התקציב **פחות המעטפת** — ולכן התשובה כפי שיצאה נכנסת, וצמוד לגבול.

    שורה אחת בלי שורות חדשות: כל תו הוא שלושה בתים גם ב-UTF-8 וגם ב-JSON, ולכן
    העמוד נגמר עד כדי תו אחד מהגבול שהוא קיבל — ו-``found``/``status``, שנוספים
    אחרי ``answer_section``, הם מה שמכריע אם התשובה נכנסת. והצמידות נבדקת גם היא:
    עמוד שנגמר הרבה לפני הגבול היה נכנס תמיד, ולא היה מוכיח כלום.

    מוטציה שמפילה: ``reserve_bytes=0`` ב-``_apply_sections_to_file`` — העמוד נחתך אל
    ``OUTPUT_BYTE_BUDGET`` לפני העטיפה, והעטיפה דוחפת אותו מעבר.
    """
    text = "# רחב\n\n" + "汉" * 120_000 + "\n"
    mcp = _build(monkeypatch, _Dbm(text))

    out, sent = await _call_sent(mcp, file_name=_MD_NAME, section="רחב",
                                 max_chars=docs_handlers.MAX_CHARS_MAX)

    assert out["found"] is True and out["status"] == "section"
    assert out["truncation_reason"] == "byte_budget"
    assert sent <= answer_size.OUTPUT_BYTE_BUDGET
    assert answer_size.OUTPUT_BYTE_BUDGET - sent < 16


async def test_a_page_that_fits_is_left_exactly_as_it_was(monkeypatch):
    """עמוד שנכנס בתקציב אינו משתנה: ``max_chars`` תווים, ובלי ``truncation_reason``.

    עברית היא שני בתים לתו, ולכן עמוד מלא של ``MAX_CHARS_MAX`` תווים נכנס. זו
    שמירה על ההתנהגות הקיימת ולא בדיקה של התיקון — היא עוברת גם על הקוד שלפניו,
    בכוונה, והאפס-דיף על קורפוס התיעוד הוא אותה טענה בקנה מידה.

    מוטציה שמפילה: לחתוך ב-``_fit_page`` גם כשהעמוד נכנס (בלי ה-``return`` המוקדם).
    """
    text = "# עברית\n\n" + _wide_lines("ש", 120_000) + "\n"
    mcp = _build(monkeypatch, _Dbm(text))

    out, sent = await _call_sent(mcp, file_name=_MD_NAME, section="עברית",
                                 max_chars=docs_handlers.MAX_CHARS_MAX)

    assert sent <= answer_size.OUTPUT_BYTE_BUDGET
    assert len(out["content"]) == docs_handlers.MAX_CHARS_MAX
    assert out["next_offset"] == docs_handlers.MAX_CHARS_MAX
    assert "truncation_reason" not in out


async def test_subsections_are_capped_like_the_map(monkeypatch):
    """``subsections`` חסום ב-``_TOC_MAX``, בסדר המסמך, עם ``subsections_truncated`` — רק כשנחתך.

    תת-הסעיפים הם שורות מאותה מפה, ולכן אותה תקרה. בלעדיה זה היה השדה היחיד בתשובה
    בלי גבול: על הקוד שלפני התיקון, סעיף עם 7,000 תת-סעיפים יצא בתשובה של כמיליון
    בתים, ורובם הרשימה. בדיוק בגובה התקרה אין דגל: הוא אומר שנחתך משהו, לא שהרשימה
    מלאה.

    מוטציה שמפילה: להחזיר את ``direct_subsections`` בלי ``_capped``.
    """
    cap = docs_handlers._TOC_MAX
    many = "# שורש\n" + "".join(f"## כותרת {i:04d}\n" for i in range(cap + 600))
    mcp = _build(monkeypatch, _Dbm(many))

    out, sent = await _call_sent(mcp, file_name=_MD_NAME, section="שורש")

    assert sent <= answer_size.OUTPUT_BYTE_BUDGET
    assert [s["title"] for s in out["subsections"]] == [f"כותרת {i:04d}" for i in range(cap)]
    assert out["subsections_truncated"] is True

    exactly = "# שורש\n" + "".join(f"## כותרת {i:04d}\n" for i in range(cap))
    mcp = _build(monkeypatch, _Dbm(exactly))
    out = await _call(mcp, file_name=_MD_NAME, section="שורש")
    assert len(out["subsections"]) == cap
    assert "subsections_truncated" not in out


async def test_a_map_that_does_not_fit_is_cut_from_the_end_inside_the_budget(monkeypatch):
    """מפה גדולה מהתקציב נחתכת מהסוף: קידומת של המפה המלאה, בסדר המסמך, בתוך התקציב.

    ``_TOC_MAX`` כותרות עבריות בקינון עמוק — התקרה במספר פריטים אינה חותכת כלום, ולכן
    ``toc_truncated`` דלוק כאן רק בגלל הבתים. ``section_count`` נשאר מספר הכותרות
    כולן, כדי שהקורא יידע כמה חסר. והקידומת היא **הארוכה ביותר** שנכנסת: עוד כותרת
    אחת הייתה עוברת את התקציב — אחרת חיתוך מוקדם מדי היה עובר את הבדיקה.
    על הקוד שלפני התיקון המפה הזו — מקובץ של 93,906 בתים — יצאה שלמה, ב-472,517 בתים.

    מוטציה שמפילה: להחזיר את תשובת המפה ב-``_answer_from_document`` בלי ``_fit_or_refuse``.
    """
    text = _deep_hebrew_map()
    full = doc_sections.build_toc(md_parser.parse_document(text))
    mcp = _build(monkeypatch, _Dbm(text))

    out, sent = await _call_sent(mcp, file_name=_MD_NAME, toc=True)

    assert out["found"] is True and out["status"] == "toc"
    assert sent <= answer_size.OUTPUT_BYTE_BUDGET
    kept = len(out["toc"])
    assert 0 < kept < len(full) == docs_handlers._TOC_MAX
    assert out["toc"] == full[:kept]
    assert out["toc_truncated"] is True
    assert out["section_count"] == len(full)
    one_more = {**out, "toc": full[:kept + 1]}
    assert len(answer_size.wire_json(one_more)) > answer_size.OUTPUT_BYTE_BUDGET


async def test_a_miss_gives_up_the_map_before_the_suggestions(monkeypatch):
    """``section_not_found`` שאינו נכנס מקצר קודם את המפה — וההצעות נשארות כמו שהן.

    המפה היא מלאי, וההצעות הן התשובה לשאלה שנשאלה; לכן המפה נחתכת ראשונה. ההצעות
    כאן זהות למה ש-``suggest`` מחזיר בלי שום תקציב — כולל הדגל שלהן, שנדלק כבר בגלל
    התקרה במספר פריטים ולא בגלל הבתים. על הקוד שלפני התיקון: 484,079 בתים.

    מוטציה שמפילה: להפוך את סדר החיתוך ב-``section_not_found`` (הצעות לפני המפה).
    """
    text = _deep_hebrew_map()
    doc = md_parser.parse_document(text)
    full = doc_sections.build_toc(doc)
    near = full[7]["title"] + "ק"
    expected = doc_sections.suggest(doc, near, n=doc_sections.MAX_IDENTIFIER_SUGGESTIONS)
    assert expected.titles, "הנחת המקרה: יש הצעות"
    mcp = _build(monkeypatch, _Dbm(text))

    out, sent = await _call_sent(mcp, file_name=_MD_NAME, section=near)

    assert out["error"] == "section_not_found"
    assert sent <= answer_size.OUTPUT_BYTE_BUDGET
    assert out["toc_truncated"] is True and len(out["toc"]) < len(full)
    assert out["toc"] == full[:len(out["toc"])]
    assert out["suggestions"] == list(expected.titles)
    assert out.get("suggestions_truncated", False) is expected.truncated


async def test_suggestions_are_cut_only_after_the_map_is_empty(monkeypatch):
    """קובץ עוין: 48 כותרות ארוכות שקרובות כולן לשאילתה ארוכה. **שתי הגנות פועלות** —
    ``suggest`` נחתך בתקציב העבודה (``SUGGEST_WORK_BUDGET``, WARN-001), והמפה נחתכת
    לפני ההצעות בהתאמת הבתים (דגלה דלוק — הוויתור עליה קדם).

    עד WARN-001 החיתוך של ``suggest`` על קלט כזה היה רק בבתים (879,509 בתים לפני
    ``_fit_lists``); היום תקציב העבודה חוסם קודם — ``len(cand)·Q`` על כל מועמד
    תואם-אורך עובר את התקציב כבר ב-48 כותרות ארוכות, ולכן ההצעות קטנות יותר והמפה
    נחתכת חלקית ולא בהכרח מתרוקנת. סדר הוויתור (מפה לפני הצעות) נבדק ב-
    ``test_a_miss_gives_up_the_map_before_the_suggestions``, וחיתוך רשימה שנייה
    (מועמדים) ב-``test_candidates_are_cut_from_the_end_in_document_order``.
    """
    heading = _distinct_cjk(2000)
    text = "".join(f"# {heading} {i:02d}\n\nגוף.\n\n" for i in range(48))
    doc = md_parser.parse_document(text)
    query = heading + " zz"
    expected = doc_sections.suggest(doc, query, n=doc_sections.MAX_IDENTIFIER_SUGGESTIONS)
    assert 0 < len(expected.titles) < 48 and expected.truncated, "תקציב העבודה חוסם את suggest"
    mcp = _build(monkeypatch, _Dbm(text))

    out, sent = await _call_sent(mcp, file_name=_MD_NAME, section=query)

    assert out["error"] == "section_not_found"
    assert sent <= answer_size.OUTPUT_BYTE_BUDGET
    assert out["toc_truncated"] is True                 # המפה נחתכה ראשונה (לחץ הבתים)
    kept = len(out["suggestions"])
    assert 0 < kept < 48
    assert out["suggestions"] == list(expected.titles[:kept])
    assert out["suggestions_truncated"] is True         # תקציב העבודה חסם את suggest


async def test_candidates_are_cut_from_the_end_in_document_order(monkeypatch):
    """מועמדים שאינם נכנסים נחתכים מהסוף, בסדר המסמך — והדרך למי שנחתך עובדת.

    48 כותרות שנפתחות ב-``K7.``, כל אחת תחת הורה ארוך: פחות מ-``_CANDIDATES_MAX``,
    ולכן ``candidates_truncated`` דלוק רק בגלל הבתים. מה שחסר הוא תמיד הסוף — וזה
    מה שהתיאור מבטיח — ומועמד שנחתך נמצא בשם הכותרת המלא, שכאן אינו חוזר, כמו שהתיאור אומר. בלי
    זה חיתוך היה מעלים בדיוק את המועמד שחיפשו, בלי לומר איך מגיעים אליו. על הקוד
    שלפני התיקון: 297,484 בתים.

    מוטציה שמפילה: להחזיר את תשובת ``ambiguous_section`` בלי ``_fit_or_refuse``.
    """
    parent = _distinct_cjk(2000)
    text = "".join(f"# {parent} {i:02d}\n\n## K7. כפול {i:02d}\n\nגוף.\n\n" for i in range(48))
    doc = md_parser.parse_document(text)
    matches = doc_sections.find_sections(doc, "K7")
    assert len(matches) == 48 < docs_handlers._CANDIDATES_MAX, "הנחת המקרה"
    mcp = _build(monkeypatch, _Dbm(text))

    out, sent = await _call_sent(mcp, file_name=_MD_NAME, section="K7")

    assert out["error"] == "ambiguous_section"
    assert sent <= answer_size.OUTPUT_BYTE_BUDGET
    starts = [c["line_range"][0] for c in out["candidates"]]
    assert 0 < len(starts) < len(matches)
    assert starts == [s.heading_line for s in matches][:len(starts)]
    assert out["candidates_truncated"] is True

    last = await _call(mcp, file_name=_MD_NAME, section=matches[-1].title)
    assert last["status"] == "section" and last["line_range"][0] == matches[-1].heading_line


def _map_cut_before(tail: str) -> str:
    """קובץ שהמפה שלו נחתכת ב-``_TOC_MAX`` בדיוק לפני ``tail`` — מה שב-``tail`` אינו במפה."""
    return ("# ראשי\n\n"
            + "".join(f"## פרק {i}\n\nגוף {i}.\n\n" for i in range(docs_handlers._TOC_MAX - 1))
            + tail)


async def test_a_repeated_heading_past_the_cut_is_read_by_its_candidates_line_range(monkeypatch):
    """כותרת שנחתכה מהמפה ושמה חוזר: השם מחזיר ``ambiguous_section``, וטווח המועמד קורא אותה.

    התרחיש מהריוויו: המפה נחתכת ב-``_TOC_MAX``, ושתי כותרות באותו שם יושבות אחרי החיתוך — אינן
    במפה, ושאלה בשמן אינה מחזירה אף אחת מהן. זה בכוונה, הכלי אינו מנחש; אבל התיאור של ``toc``
    הבטיח ש"כותרת שנחתכה נקראת בשמה", וכאן זה לא נכון. הדרך האמיתית היא ``line_range`` שכל מועמד
    נושא, ו-``lines`` עליו מחזיר בדיוק את שורות הסעיף.

    עוברת גם על הקוד שלפני תיקון התיאורים, בכוונה: ההתנהגות לא השתנתה — היא מה שהתיאורים מבטיחים
    עכשיו, והבדיקה מחזיקה אותם לה. על הטקסט הישן נופלת בדיקת המשטחים,
    ``test_every_surface_says_a_repeated_name_never_reaches_its_heading``.

    מוטציה שמפילה: להסיר את ``line_range`` מהמועמדים ב-``_answer_from_document``.
    """
    text = _map_cut_before("## סיכום\n\nראשון.\n\n## סיכום\n\nשני.\n")
    matches = doc_sections.find_sections(md_parser.parse_document(text), "סיכום")
    mcp = _build(monkeypatch, _Dbm(text))

    toc = await _call(mcp, file_name=_MD_NAME, toc=True)
    assert toc["toc_truncated"] is True and toc["section_count"] == docs_handlers._TOC_MAX + 2
    assert "סיכום" not in [item["title"] for item in toc["toc"]]

    out = await _call(mcp, file_name=_MD_NAME, section="סיכום")
    assert out["error"] == "ambiguous_section"
    assert ([c["line_range"] for c in out["candidates"]]
            == [[s.heading_line, s.end_line] for s in matches])
    pages = [(await _call(mcp, file_name=_MD_NAME, lines=c["line_range"]))["file"]["code"]
             for c in out["candidates"]]
    assert pages == [_source(text, *c["line_range"]) for c in out["candidates"]]
    assert [page.split("\n")[2] for page in pages] == ["ראשון.", "שני."]


async def test_a_repeated_heading_missing_from_both_cut_lists_is_found_with_query(monkeypatch):
    """כותרת שחסרה גם ברשימת המועמדים וגם במפה: ``query`` מוצא את השורה שלה, ו-``lines`` קורא אותה.

    יותר מ-``_CANDIDATES_MAX`` כותרות באותו שם, כולן אחרי חיתוך המפה: האחרונה אינה באף רשימה,
    ואף שם אינו מגיע אליה. התיאור מפנה כאן ל-``query``, שמחזיר את השורות שמחזיקות את הטקסט שלה —
    והבדיקה מוודאת שהדרך הזו קיימת ומגיעה בדיוק לסעיף.

    עוברת גם על הקוד שלפני תיקון התיאורים, מאותה סיבה כמו הבדיקה שמעליה.

    מוטציה שמפילה: ``query`` שמתעלם מ-``max_results`` ומחזיר תמיד ``QUERY_RESULTS_DEFAULT`` שורות —
    הכותרת האחרונה נשארת מחוץ לתשובה.
    """
    repeats = docs_handlers._CANDIDATES_MAX + 10
    text = _map_cut_before("".join(f"## סיכום\n\nמספר {j}.\n\n" for j in range(repeats)))
    matches = doc_sections.find_sections(md_parser.parse_document(text), "סיכום")
    assert len(matches) == repeats, "הנחת המקרה"
    assert handlers.QUERY_RESULTS_DEFAULT < repeats <= handlers.QUERY_RESULTS_MAX, "הנחת המקרה"
    last = matches[-1]
    mcp = _build(monkeypatch, _Dbm(text))

    out = await _call(mcp, file_name=_MD_NAME, section="סיכום")
    assert out["candidates_truncated"] is True
    assert last.heading_line not in [c["line_range"][0] for c in out["candidates"]]
    toc = await _call(mcp, file_name=_MD_NAME, toc=True)
    assert last.heading_line not in [item["line_range"][0] for item in toc["toc"]]

    found = await _call(mcp, file_name=_MD_NAME, query="## סיכום",
                        max_results=handlers.QUERY_RESULTS_MAX)
    assert last.heading_line in [row["line"] for row in found["results"]]
    page = await _call(mcp, file_name=_MD_NAME, lines=[last.heading_line, last.end_line])
    assert page["file"]["code"] == _source(text, last.heading_line, last.end_line)
    assert f"מספר {repeats - 1}." in page["file"]["code"]


async def test_a_repeated_heading_is_read_through_a_parent_named_in_its_breadcrumb(monkeypatch):
    """בכלי התיעוד, בלי ``lines``: כותרת ששמה חוזר נקראת דרך ההורה שב-``breadcrumb`` שלה.

    ``codekeeper_docs_get_section`` פתוח לכל משתמש, ו-``codekeeper_get_repo_file`` — שקורא טווח
    שורות — לאדמין בלבד. וב-amir-bug-patterns אותה כותרת משנה חוזרת תחת דפוס אחרי דפוס. לכן
    התיאור המשותף מציע גם דרך שאינה ``line_range``: ההורה שב-``breadcrumb`` של המועמד, שהתוכן
    שלו כולל כברירת מחדל את תת-הסעיפים.

    עוברת גם על הקוד שלפני תיקון התיאורים — ההתנהגות לא השתנתה.

    מוטציה שמפילה: ``breadcrumb`` של מועמד בלי ההורים, רק הכותרת עצמה.
    """
    monkeypatch.setenv("MCP_DOCS_REPO", "CodeBot,amir-bug-patterns")
    text = ("# דפוסים\n\n## K1. ראשון\n\n### איך זה נראה\n\nאחד.\n\n"
            "## K2. שני\n\n### איך זה נראה\n\nשניים.\n")
    mcp = _build(monkeypatch, repo_backend=_RepoText(text))

    async def docs(**arguments):
        arguments = {"path": "x.md", "repo": "amir-bug-patterns", **arguments}
        return _payload(await mcp.call_tool("codekeeper_docs_get_section", arguments))

    out = await docs(section="איך זה נראה")
    assert out["error"] == "ambiguous_section"
    second = out["candidates"][1]
    assert second["breadcrumb"] == ["דפוסים", "K2. שני", "איך זה נראה"]

    parent = await docs(section=second["breadcrumb"][-2])
    assert parent["mode"] == "section"
    assert "### איך זה נראה\n\nשניים." in parent["content"]


async def test_version_and_file_id_choose_the_version_the_section_is_read_from(monkeypatch):
    """הסעיף נקרא מהגרסה שנבחרה — ו-``file_id`` מתעלם מ-``version``, כמו בקריאה מלאה.

    מוטציה שמפילה: לבחור את המסמך ב-``_latest_fresh`` בלי קשר ל-``version``
    — הגרסה הישנה אינה נקראת.
    """
    mcp = _build(monkeypatch)
    old_k11 = "## K11. חריגה נבלעת\n\nגרסה ישנה.\n"

    old = await _call(mcp, file_name=_MD_NAME, version=1, section="K11")
    assert old["content"] == old_k11
    assert old["file"] == _meta(code=_OLD_MD, version=1, doc_id=_OLD_DOC_ID)

    by_old_id = await _call(mcp, file_id=_OLD_DOC_ID, version=2, section="K11")
    assert by_old_id["content"] == old_k11 and by_old_id["file"]["version"] == 1

    by_id = await _call(mcp, file_id=_DOC_ID, toc=True)
    assert by_id["file"] == _meta() and by_id["section_count"] == 5


async def test_a_file_of_another_user_is_not_found_in_either_mode(monkeypatch):
    """הרשאות: רק קובץ של המשתמש עצמו. ``get_file_by_id`` אינו מסנן, וה-backend כן.

    מוטציה שמפילה: להסיר את בדיקת הבעלות אחרי ``get_file_by_id`` — המפה של
    קובץ זר חוזרת.
    """
    mcp = _build(monkeypatch, _Dbm(owner=_OTHER_USER))

    assert await _call(mcp, file_id=_DOC_ID, toc=True) == {"found": False}
    assert await _call(mcp, file_id=_DOC_ID, section="K11") == {"found": False}
    assert await _call(mcp, file_name=_MD_NAME, toc=True) == {"found": False}


async def test_a_section_is_the_exact_source_text_even_with_crlf_and_a_bom(monkeypatch):
    """טקסט סעיף זהה בית-בית לקריאת ``lines=`` על הטווח שלו — גם ב-CRLF ועם BOM.

    זו ההבטחה ש-``line_range`` שימושי: סוכן שקיבל סעיף וקורא אחר כך את אותו
    טווח ב-``lines=`` מקבל את אותו טקסט בדיוק, ולא גרסה מנורמלת שלו.

    מוטציה שמפילה: להחזיר ב-``services/md_parser.py`` את ``lines`` מהטקסט
    המנורמל (``normalized.split("\\n")``) — ה-``\\r`` וה-BOM נעלמים מהסעיף.
    """
    text = "﻿# פתיחה\r\n\r\nטקסט\r\n\r\n## שני\r\n\r\nעוד\r\n"
    mcp = _build(monkeypatch, _Dbm(text))

    for title in ("פתיחה", "שני"):
        section = await _call(mcp, file_name=_MD_NAME, section=title)
        start, end = section["line_range"]
        ranged = await _call(mcp, file_name=_MD_NAME, lines=[start, end])
        assert section["content"] == ranged["file"]["code"]
    # ושני התווים שהנרמול היה מוחק באמת נמצאים בו.
    first = await _call(mcp, file_name=_MD_NAME, section="פתיחה")
    assert first["content"].startswith("﻿# פתיחה\r")


# ---------------------------------------------------------------------------
# 2. סירובים
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"toc": True, "section": "K11"}, handlers.TOC_AND_SECTION),
        ({"toc": True, "query": "K11"}, handlers.TOC_AND_QUERY),
        ({"toc": True, "lines": [1, 2]}, handlers.TOC_AND_LINES),
        ({"section": "K11", "query": "K11"}, handlers.SECTION_AND_QUERY),
        ({"section": "K11", "lines": [1, 2]}, handlers.SECTION_AND_LINES),
        # הזוג הישן — אותו קוד כמו לפני התוספת.
        ({"query": "K11", "lines": [1, 2]}, handlers.QUERY_AND_LINES),
        # שלושה מצבים: הזוג הראשון לפי הסדר, ותמיד אותו אחד.
        ({"toc": True, "section": "K11", "query": "x"}, handlers.TOC_AND_SECTION),
        ({"section": "K11", "query": "x", "lines": [1, 2]}, handlers.SECTION_AND_QUERY),
        # ערך פסול לא מקדים את ההתנגשות: ``section`` ריק עם ``query`` הוא זוג.
        ({"section": "", "query": "x"}, handlers.SECTION_AND_QUERY),
    ],
)
async def test_each_pair_of_modes_is_refused_by_its_own_code_before_the_db(
        monkeypatch, arguments, code):
    """ארבעת מצבי הקריאה אינם מצטברים, וכל זוג נדחה בקוד משלו.

    ``toc=false`` מפורש אינו מצב — ולכן ``{"toc": false, "section": ...}`` אינו
    זוג (נבדק בבדיקת התוספתיות). והסירוב קורה **לפני** המסד: ``calls`` ריק.

    מוטציה שמפילה: להסיר זוג מ-``_EXCLUSIVE_READ_MODES`` — המקרה שלו חוזר
    כסעיף, כמפה או כמופעים, והפרמטר השני נבלע בשקט.
    """
    dbm = _Dbm()
    mcp = _build(monkeypatch, dbm)

    assert await _call(mcp, file_name=_MD_NAME, **arguments) == {"ok": False, "error": code}
    assert dbm.calls == []


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"max_chars": 600}, handlers.MAX_CHARS_WITHOUT_SECTION),
        ({"offset": 5}, handlers.OFFSET_WITHOUT_SECTION),
        ({"max_chars": 600, "offset": 5}, handlers.MAX_CHARS_WITHOUT_SECTION),
        # המפה אינה מעומדת — ``max_chars`` איתה הוא פרמטר שהיה נבלע.
        ({"toc": True, "max_chars": 600}, handlers.MAX_CHARS_WITHOUT_SECTION),
        ({"toc": True, "offset": 5}, handlers.OFFSET_WITHOUT_SECTION),
        ({"lines": [1, 2], "offset": 0}, handlers.OFFSET_WITHOUT_SECTION),
    ],
)
async def test_paging_without_a_section_is_refused(monkeypatch, arguments, code):
    """``max_chars`` ו-``offset`` מעמדים סעיף — בלי ``section`` הם נדחים, ולא נבלעים.

    ``offset=0`` הוא ערך ולא "לא נשלח": גם הוא נדחה.

    מוטציה שמפילה: להסיר את הבדיקה ``if section is None`` ב-``file_read_request_error``
    — הקריאה מחזירה את הקובץ או את המפה, ומתעלמת מהפרמטר.
    """
    mcp = _build(monkeypatch)

    assert await _call(mcp, file_name=_MD_NAME, **arguments) == {"ok": False, "error": code}


@pytest.mark.parametrize("section", ["", "   ", "\t\n"])
async def test_an_empty_section_is_refused_with_a_pointer_to_the_map(monkeypatch, section):
    """``section`` ריק אינו "בלי ``section``" ואינו מפה בשקט — הוא סירוב שמפנה ל-``toc=true``.

    זה ההבדל המכוון מ-``codekeeper_docs_get_section``, שם ``section`` ריק מחזיר
    את ה-TOC: כאן המפה היא מצב נפרד.

    מוטציה שמפילה: להחזיר ``None`` על ``section`` ריק ב-``file_section_error`` —
    התשובה היא מפה (``mode: toc``) במקום סירוב.
    """
    mcp = _build(monkeypatch)

    assert await _call(mcp, file_name=_MD_NAME, section=section) == {
        "ok": False,
        "error": handlers.SECTION_EMPTY,
        "hint": "pass toc=true for the heading map, then one of its titles as section",
    }


async def test_a_blank_section_longer_than_the_ceiling_is_refused_for_its_length(monkeypatch):
    """קודם אורך, אחר כך תוכן (#3472, SUGG-001) — כמו ב-``codekeeper_docs_get_section``.

    ``section`` של רווחים בלבד, ארוך מ-``MAX_SECTION_CHARS``, היה ``empty_section`` כאן
    ו-``section_too_long`` בכלי התיעוד — שני כלים שעונים באותה פונקציה, ושתי שגיאות לאותו
    קלט. עכשיו הוא ``section_too_long`` בשניהם, עם המטא-דאטה של הקובץ כמו כל סירוב אחרי
    הקריאה. ובאורך התקרה בדיוק — ``empty_section`` כמו קודם: זה ההבדל המכוון מכלי התיעוד,
    ששם ``section`` ריק הוא המפה.

    נופלת על הקוד שלפני התיקון: הקלט הארוך חוזר ``empty_section``.

    מוטציה שמפילה: להחזיר ``SECTION_EMPTY`` מ-``file_section_error`` על כל ``section`` של
    רווחים, בלי בדיקת האורך.
    """
    ceiling = docs_handlers.MAX_SECTION_CHARS
    monkeypatch.setenv("MCP_DOCS_REPO", "CodeBot,amir-bug-patterns")
    mcp = _build(monkeypatch, repo_backend=_RepoText(_MD))
    blank = " " * (ceiling + 1)

    from_file = await _call(mcp, file_name=_MD_NAME, section=blank)
    from_docs = _payload(await mcp.call_tool(
        "codekeeper_docs_get_section",
        {"path": "x.md", "repo": "amir-bug-patterns", "section": blank}))

    assert from_file == {"ok": False, "file": _meta(), "includes": [],
                         "error": "section_too_long", "max_chars": ceiling,
                         "actual_chars": ceiling + 1}
    for key in ("ok", "error", "max_chars", "actual_chars"):
        assert from_docs[key] == from_file[key], key
    at_the_ceiling = await _call(mcp, file_name=_MD_NAME, section=" " * ceiling)
    assert at_the_ceiling["error"] == handlers.SECTION_EMPTY


@pytest.mark.parametrize(
    ("file_name", "language"),
    [("tool.py", "python"), ("notes.txt", "text"), ("notes.mdx", None)],
)
async def test_a_file_that_is_not_markdown_is_refused_and_not_returned_whole(
        monkeypatch, file_name, language):
    """קובץ שאינו Markdown מקבל ``not_markdown`` עם הפניה — לא את הקובץ המלא בשקט.

    מוטציה שמפילה: להסיר את בדיקת ``is_markdown_file`` מ-``_apply_sections_to_file``
    — הקובץ מפורסר כ-Markdown ומחזיר מפה.
    """
    code = "x = 1\n# לא כותרת\n"
    mcp = _build(monkeypatch, _Dbm(code, file_name=file_name, language=language))
    expected = {"ok": False, "error": handlers.NOT_MARKDOWN,
                "file": _meta(code=code, file_name=file_name, language=language), "hint": _HINT}

    assert await _call(mcp, file_name=file_name, toc=True) == expected
    assert await _call(mcp, file_name=file_name, section="לא כותרת") == expected


@pytest.mark.parametrize(
    ("file_name", "language"),
    [
        ("notes", "markdown"),     # השפה לבדה מספיקה
        ("notes", "md"),
        ("NOTES.MD", "text"),      # הסיומת לבדה מספיקה, בלי תלות ברישיות
        ("notes.markdown", None),
    ],
)
async def test_markdown_is_recognised_by_its_language_or_by_its_name(
        monkeypatch, file_name, language):
    """הכלל של הוובאפ: שפה ``markdown``/``md`` **או** סיומת ``.md``/``.markdown``.

    מוטציה שמפילה: לבדוק רק את השפה (או רק את השם) — חצי מהמקרים נדחים.
    """
    mcp = _build(monkeypatch, _Dbm("# כותרת\n\nגוף.\n", file_name=file_name,
                                   language=language))

    out = await _call(mcp, file_name=file_name, toc=True)

    assert out["ok"] is True and out["status"] == "toc"
    assert [t["title"] for t in out["toc"]] == ["כותרת"]


def test_the_backend_decides_markdown_by_the_shared_rule_and_not_a_copy():
    """כלל אחד בשני המקומות — ``webapp/app.py`` וכלי הקבצים — ולא עותק שני.

    מוטציה שמפילה: להגדיר ב-``mcp_server/backend.py`` פונקציה מקומית באותו שם.
    """
    from mcp_server import backend as backend_mod
    from services import markdown_files

    assert backend_mod.is_markdown_file is markdown_files.is_markdown_file


async def test_a_file_too_large_to_parse_is_refused_by_its_utf8_bytes_before_parsing(
        monkeypatch):
    """התקרה נמדדת **בבתים** של UTF-8, ונבדקת **לפני** הפרסור.

    התקרה מוקטנת במקום להגדיל את הקלט, מהנימוק שכתוב ב-
    ``tests/test_mcp_docs_handlers.py`` על ``MAX_SECTIONS``: קלט אמיתי מעל
    512,000 בתים בכל ריצה עולה, והמחיר צמוד לקבוע.

    הקובץ העברי כאן קצר מהתקרה **בתווים** וארוך ממנה **בבתים** — ולכן הוא
    ההבדל בין השניים. והקובץ שבדיוק בגודל התקרה עובר: התנאי הוא ``>``.

    מוטציות שמפילות: ``len(code)`` במקום ``len(code.encode("utf-8"))`` — הקובץ
    העברי עובר ומפורסר; והזזת הבדיקה אל אחרי הפרסור — הפרסר נקרא.
    """
    from mcp_server import backend as backend_mod

    ceiling = 40
    monkeypatch.setattr(backend_mod, "MAX_FILE_SIZE_FOR_DISPLAY", ceiling)
    parsed: list[str] = []
    real = md_parser.parse_document

    def spy(text, **kwargs):
        parsed.append(text)
        return real(text, **kwargs)

    monkeypatch.setattr(md_parser, "parse_document", spy)

    hebrew = "# " + "א" * 25
    assert len(hebrew) <= ceiling < len(hebrew.encode("utf-8")), "הנחת המקרה"
    mcp = _build(monkeypatch, _Dbm(hebrew))
    assert await _call(mcp, file_name=_MD_NAME, toc=True) == {
        "ok": False,
        "error": handlers.TOO_LARGE_FOR_SECTIONS,
        "bytes": len(hebrew.encode("utf-8")),
        "max": ceiling,
        "file": _meta(code=hebrew),
        "hint": _HINT,
    }
    assert parsed == []

    exact = "# " + "a" * (ceiling - 2)
    assert len(exact.encode("utf-8")) == ceiling
    mcp = _build(monkeypatch, _Dbm(exact))
    assert (await _call(mcp, file_name=_MD_NAME, toc=True))["ok"] is True
    assert parsed == [exact]


def test_the_size_ceiling_is_the_one_the_read_pool_budgets_a_parse_for():
    """התקרה היא ``MAX_FILE_SIZE_FOR_DISPLAY`` — הקלט הגדול ביותר שמאגר הקריאות מתקצב.

    ``_PARSE_COST_BYTES`` ב-``server.py`` מקצה לכל חוט את עלות הפרסור של קלט
    בגודל הזה. תקרה אחרת כאן הייתה נותנת לקובץ שמור לעבור את ההנחה שהמאגר
    נבנה עליה, בלי שום בדיקה שתצעק.

    מוטציה שמפילה: לכתוב את התקרה כמספר ב-``mcp_server/backend.py``.
    """
    from mcp_server import backend as backend_mod
    from mcp_server import server as srv
    from services import git_mirror_service

    assert backend_mod.MAX_FILE_SIZE_FOR_DISPLAY == git_mirror_service.MAX_FILE_SIZE_FOR_DISPLAY
    assert srv._PARSE_COST_BYTES == (
        srv._PARSE_RSS_PER_INPUT_BYTE * backend_mod.MAX_FILE_SIZE_FOR_DISPLAY
    )


async def test_a_file_over_the_line_ceiling_is_refused_with_the_count_and_a_pointer(
        monkeypatch):
    """``too_many_lines`` בתצורת הייצור, עם ``hint`` — בקובץ שמור אין ריפו לתקן בו.

    **ההשוואה היא על התשובה כולה**, כמו בבדיקה המקבילה של ``docs_get_section``.

    מוטציה שמפילה: לא להוסיף ``hint`` לסירוב של הפרסר ב-``_apply_sections_to_file``.
    """
    text = "# כותרת\n" + "שורה\n" * md_parser.MAX_LINES
    mcp = _build(monkeypatch, _Dbm(text))

    assert await _call(mcp, file_name=_MD_NAME, toc=True) == {
        "ok": False,
        "error": "too_many_lines",
        "max": md_parser.MAX_LINES,
        "file": _meta(code=text),
        "total_lines": text.count("\n") + 1,
        "hint": _HINT,
    }


async def test_a_file_over_the_token_ceiling_is_refused_with_the_line_it_reached(monkeypatch):
    """``too_many_tokens`` בתצורת הייצור, על טבלה אחת שעוברת את ``MAX_TOKENS``.

    אותו קלט ואותה הגדרה של ``line`` כמו ב-
    ``tests/test_mcp_docs_handlers.py::test_a_markdown_file_over_the_token_ceiling_is_refused_with_the_line_it_reached``.
    """
    columns, rows = 16, 1_000
    text = ("|" + "|".join(" h " for _ in range(columns)) + "|\n"
            + "|" + "|".join("---" for _ in range(columns)) + "|\n"
            + ("|" + "|".join(" x " for _ in range(columns)) + "|\n") * rows)
    full = md_parser._MD.parse(text)
    assert len(full) > md_parser.MAX_TOKENS, "הנחת המקרה: הטבלה עוברת את התקרה"
    expected_line = next(t.map[0] + 1 for t in reversed(full[:md_parser.MAX_TOKENS])
                         if t.map is not None)
    mcp = _build(monkeypatch, _Dbm(text))

    assert await _call(mcp, file_name=_MD_NAME, section="h") == {
        "ok": False,
        "error": "too_many_tokens",
        "max": md_parser.MAX_TOKENS,
        "file": _meta(code=text),
        "line": expected_line,
        "hint": _HINT,
    }


async def test_mixed_line_endings_and_too_many_headings_are_refused_by_name(monkeypatch):
    """שני הסירובים האחרים של הפרסר — באותה צורה, עם ``line`` ועם ``hint``.

    תקרת הכותרות מונמכת ב-``partial``, מהנימוק שכתוב ב-
    ``tests/test_mcp_docs_handlers.py``: ``MAX_SECTIONS`` אינה ניתנת להשגה
    תחת תקרת השורות. ה-``line`` הצפוי נלקח מהחריגה עצמה — מה שנבדק כאן הוא
    שהכלי **ממפה** אותה, לא איך הפרסר מחשב שורה.

    מוטציה שמפילה: לעטוף את הפרסור ב-``_apply_sections_to_file`` בלי המיפוי
    (קריאה ישירה ל-``md_parser.parse_document``) — החריגה בורחת מהכלי.
    """
    mixed = "# א\n\n## ב\rטקסט\n\n## ג\n"
    with pytest.raises(doc_sections.InconsistentLineEndings) as caught:
        md_parser.parse_document(mixed)
    mcp = _build(monkeypatch, _Dbm(mixed))
    assert await _call(mcp, file_name=_MD_NAME, toc=True) == {
        "ok": False,
        "error": "inconsistent_line_endings",
        "file": _meta(code=mixed),
        "line": caught.value.args[0],
        "hint": _HINT,
    }

    lowered = functools.partial(md_parser.parse_document, max_sections=5)
    many = "".join(f"# כותרת {i}\n\n" for i in range(6))
    with pytest.raises(doc_sections.TooManySections) as caught:
        lowered(many)
    monkeypatch.setattr(md_parser, "parse_document", lowered)
    mcp = _build(monkeypatch, _Dbm(many))
    assert await _call(mcp, file_name=_MD_NAME, section="כותרת 1") == {
        "ok": False,
        "error": "too_many_sections",
        "max": doc_sections.MAX_SECTIONS,
        "file": _meta(code=many),
        "line": caught.value.args[0],
        "hint": _HINT,
    }


async def test_a_section_longer_than_the_ceiling_is_refused_as_in_the_docs_tool(monkeypatch):
    """``section_too_long`` מגיע גם לכאן, מאותה פונקציה — ``_answer_from_document``.

    התשובה נושאת את ``file`` ולא ``hint``: היא סירוב של השאלה, לא של הקובץ, והקובץ
    קריא בכל מצב. באורך התקרה בדיוק השאילתה מגיעה להתאמה.

    מוטציה שמפילה: להסיר את בדיקת האורך מ-``_answer_from_document`` — התשובה היא
    ``section_not_found`` עם הד של השאילתה.
    """
    mcp = _build(monkeypatch)
    ceiling = docs_handlers.MAX_SECTION_CHARS

    assert await _call(mcp, file_name=_MD_NAME, section="K" * (ceiling + 1)) == {
        "ok": False, "file": _meta(), "includes": [], "error": "section_too_long",
        "max_chars": ceiling, "actual_chars": ceiling + 1}
    at_the_ceiling = await _call(mcp, file_name=_MD_NAME, section="K" * ceiling)
    assert at_the_ceiling["error"] == "section_not_found"


async def test_a_section_whose_headings_alone_do_not_fit_is_refused_with_its_lines(
    monkeypatch,
):
    """``section_too_large`` — כשגם עמוד **ריק** של הסעיף אינו נכנס בתקציב.

    ``_TOC_MAX`` תת-סעיפים שכל אחד מהם כותרת באורך של פסקה: הרשימה לבדה גדולה
    מ-``OUTPUT_BYTE_BUDGET``, ואין תוכן שאפשר לקצר כדי להיכנס. עמוד ריק עם
    ``next_offset`` שלא זז היה שולח קורא ממושמע ללולאה אינסופית, ולכן זה סירוב —
    עם ``bytes`` מעל ``max``, עם ``line_range`` של הסעיף כדי לקרוא אותו ב-``lines``,
    ועם ה-``hint`` של קובץ שמור.

    מוטציה שמפילה: להחזיר מ-``_fit_page`` את העמוד גם כשהתוכן שלו התרוקן.
    """
    title = "汉" * 240
    text = "# שורש\n" + "".join(f"## {title} {i}\n" for i in range(docs_handlers._TOC_MAX))
    from mcp_server import backend as backend_mod

    assert len(text.encode("utf-8")) < backend_mod.MAX_FILE_SIZE_FOR_DISPLAY, "הנחה: הקובץ נפרסר"
    mcp = _build(monkeypatch, _Dbm(text))
    toc = await _call(mcp, file_name=_MD_NAME, toc=True)

    out = await _call(mcp, file_name=_MD_NAME, section="שורש")

    assert out["ok"] is False and out["error"] == docs_handlers.SECTION_TOO_LARGE
    assert out["file"] == _meta(code=text) and out["hint"] == _HINT
    assert out["bytes"] > out["max"] == answer_size.OUTPUT_BYTE_BUDGET
    assert out["line_range"] == toc["toc"][0]["line_range"]
    assert "content" not in out


#: תיאור ארוך מהתקציב כולו. **מחרוזת ולא רשימה**, ולכן אף אחד מהחיתוכים אינו נוגע בה:
#: לא הרשימות של התשובה, ולא ``file.tags`` של סירוב. זו הדרך היחידה שנשארה ל-
#: ``answer_too_large`` בקובץ שמור, והשורש שלה — כותבים שאינם אוכפים את התקרה — ב-#3489.
_HUGE_DESCRIPTION = "汉" * 90_000

#: תגית אחת שגם לבדה גדולה מהתקציב — הקלט של #3470. ``update_file_metadata_in`` אינו
#: מגביל כמה תגיות ובאיזה אורך (#3489), ולכן זה קלט שאפשר לשמור.
_HUGE_TAGS = ["汉" * 90_000]


@pytest.mark.parametrize(
    "arguments",
    [{"toc": True}, {"section": "K99"}, {"section": "K12 כפול"}],
    ids=["toc", "section_not_found", "ambiguous_section"],
)
def test_an_answer_that_does_not_fit_even_with_empty_lists_is_refused(arguments):
    """``answer_too_large`` — כשגם אחרי שכל הרשימות רוקנו התשובה גדולה מהתקציב.

    מה שנשאר אז הוא החלק הקבוע, וכאן זה התיאור של הקובץ — מחרוזת, ולכן אין בה מה
    לחתוך. הענף ניתן להגעה ואינו תנאי מת. זה סירוב מפורש ולא תשובה גדולה בשקט — עם
    ``bytes`` מעל ``max``, עם ``file`` כמו כל תשובה, ועם ה-``hint`` של קובץ שמור. בשלוש
    הצורות שנושאות רשימות, כי כולן עוברות באותו מקום.

    **והסירוב עצמו נכנס בתקציב** (#3460, #3489 בצד הקריאה): התיאור יורד ממנו שלם,
    ובמקומו ``file.description_bytes`` — כמה בתים הוא היה. עד #3460 התיאור נשאר, והסירוב
    עצמו עבר את התקציב. נופלת על הקוד שלפני: שם ``description`` בסירוב ו-``description_bytes``
    אינו קיים.

    **ותגיות כבר אינן הדרך לכאן** (#3472, SUGG-002): רשימה שבתוך ``file`` מוותרת על
    פריטים בסירוב — ראו ``test_a_refusal_gives_up_the_file_tags_first_and_says_so``. עד
    #3472 הבדיקה הזו נשענה על תגית ענקית. וקובץ שאין לו ``tags`` בכלל אינו מקבל
    ``tags: []`` ודגל בגלל שהסירוב שלו גדול.

    **והכלי עצמו כבר אינו מחזיר את הסירוב הזה** (ריוויו Han על #3492, WARN-001): כשהתיאור
    לבדו הוא מה שלא נכנס, הוא יורד גם מהתשובה המוצלחת — ראו
    ``test_a_huge_description_leaves_the_file_readable_in_every_mode`` ב-
    ``tests/test_mcp_answer_size.py``. הסירוב עדיין נבנה בניסיון הראשון, ולכן הוא נבדק
    כאן ישירות (:func:`_sections_only`).

    מוטציה שמפילה: להחזיר מ-``_fit_or_refuse`` את התשובה גם כש-``fit_lists`` מחזיר ``None``.
    """
    from mcp_server import backend as backend_mod

    out, sent = _sections_only(_Dbm(extra={"description": _HUGE_DESCRIPTION}), **arguments)

    assert out["ok"] is False and out["error"] == answer_size.ANSWER_TOO_LARGE
    assert out["bytes"] > out["max"] == answer_size.OUTPUT_BYTE_BUDGET
    assert sent <= answer_size.OUTPUT_BYTE_BUDGET
    # התיאור ירד, ולכן הסירוב מפנה גם לכלי שמתקן אותו (ריוויו Han על #3492).
    assert out["hint"] == answer_fit.with_note(_HINT, backend_mod._DESCRIPTION_LEFT_OUT)
    assert out["file"]["id"] == _DOC_ID and "description" not in out["file"]
    assert out["file"]["description_bytes"] == len(_HUGE_DESCRIPTION.encode("utf-8"))
    assert "tags" not in out["file"] and "tags_truncated" not in out["file"]
    assert not {"toc", "suggestions", "candidates", "requested"} & out.keys()


def _bytes_at(arguments, dbm_for):
    """שלוש תשובות: תיאור ארוך בהרבה מהתקציב, התיאור שבו ``bytes`` הוא ``budget + 1``, ואחד פחות.

    ``bytes`` לינארי באורך תיאור ב-ASCII — כל תו הוא בית אחד, ושום שדה אחר בסירוב אינו
    תלוי בו. לכן מדידה אחת בתיאור ארוך נותנת את האורך שבו ``bytes`` הוא ``budget + 1``
    בדיוק, **בלי לחשב את המעטפת בטסט**. **והתשובה בתו אחד פחות היא העוגן:** האורך נגזר
    מ-``bytes`` עצמו, ולכן לבדו הוא מעגלי — ``bytes`` שמוזז בקבוע היה מזיז איתו את
    האורך, והכול היה עובר. התשובה שמתחתיו מראה איפה **ההחלטה** נופלת: אם שם אין סירוב,
    האורך הזה הוא הסף האמיתי, ו-``bytes`` בו הוא בדיוק מה שהושווה לתקציב.
    """
    far = 300_000
    first = _sections_only(dbm_for(far), **arguments)[0]
    length = far - (first["bytes"] - (answer_size.OUTPUT_BYTE_BUDGET + 1))
    window = _sections_only(dbm_for(length), **arguments)[0]
    below = _sections_only(dbm_for(length - 1), **arguments)[0]
    return first, window, below


#: קובץ בלי מזהים: שאילתה שאין לה כותרת קרובה מקבלת בו ``suggestions`` ריק (ראו
#: ``_SECTION_PARAM_DOC``). במקרה החלון זה מה שנחוץ — ראו הבדיקה שמתחת.
_NO_IDENTIFIERS = "# אלפא\n\nגוף.\n\n## בטא\n\nעוד.\n"
#: סעיף שגופו ארוך מכל שדות החיתוך שעמוד ריק נושא (``truncated``, הסיבה, ``next_offset``).
_ONE_LONG_SECTION = "# גדול\n\n" + "y" * 5_000 + "\n"


@pytest.mark.parametrize(
    ("code_text", "arguments", "error"),
    [
        (_MD, {"toc": True}, answer_size.ANSWER_TOO_LARGE),
        (_NO_IDENTIFIERS, {"section": "zzzz"}, answer_size.ANSWER_TOO_LARGE),
        (_MD, {"section": "K12 כפול"}, answer_size.ANSWER_TOO_LARGE),
        (_ONE_LONG_SECTION, {"section": "גדול"}, docs_handlers.SECTION_TOO_LARGE),
    ],
    ids=["toc", "section_not_found", "ambiguous_section", "section"],
)
def test_every_budget_refusal_reports_bytes_over_the_documented_max(code_text, arguments, error):
    """``bytes > max`` בכל סירוב שנולד מהתקציב, ו-``max`` הוא ``OUTPUT_BYTE_BUDGET`` עצמו.

    עד #3472 (SUGG-008) ``max`` היה התקציב פחות המעטפת של ``found``/``status`` —
    255,964 במצב ``toc`` ו-255,960 במצב ``section`` — מספר שאינו כתוב בשום תיעוד. עכשיו
    ``max`` הוא המספר המתועד, ו-``bytes`` כולל את המעטפת, כך ש-``bytes > max`` הוא בדיוק
    ההחלטה שנפלה.

    **והמקרה שבסף** — ``bytes`` שהוא ``budget + 1`` בדיוק, ותו אחד פחות בתיאור אין
    סירוב: זה הסף שבו ההחלטה נופלת, ובו התשובה בלי המעטפת **כן** נכנסת בתקציב — המעטפת
    היא שמוציאה אותה. זה המקרה שמוטציה "``bytes`` בלי המעטפת" מפילה: שם ``bytes`` היה
    ``max`` או פחות. **והוא מה שמצא באג בסירוב של העמוד** (#3472): ``section_too_large``
    מדד את ``bytes`` על צורה קצרה בכמה בתים מזו שההחלטה מדדה, ובלי התו הראשון, ולכן
    בסף שלו אמר ``bytes`` קטן מ-``max`` — 255,997 מול 256,000 כאן, ו-255,957 מול 255,960
    ב-main. ראו :func:`~mcp_server.docs_handlers._fit_page`.

    **הקבצים נבחרו כך שהסף קיים.** ``bytes`` הוא גודל התשובה כשכל הרשימות ריקות **ועם
    הדגלים שלהן** — ודגל עולה בתים. בקובץ עם מזהים, ``section_not_found`` נושא הצעות
    קצרות, ורשימה של שתי הצעות זולה מהדגל שמחליף אותה: תשובה בגודל הזה נכנסת כשהמפה
    ריקה וההצעות שלמות, ולכן אינה סירוב. ועמוד של סעיף קצר קטן מעמוד ריק שנושא את שדות
    החיתוך. שני המקרים הם התנהגות נכונה של החיתוך, ולא של ``bytes``.

    נופלת על הקוד שלפני התיקון: ``max`` יוצא קטן מ-``OUTPUT_BYTE_BUDGET``, ובסעיף גם הסף.

    מוטציות שמפילות: ``"bytes": size`` במקום ``size + reserve_bytes`` ב-``_fit_or_refuse``
    או בסירוב ``section_too_large`` של ``_answer_from_document``; ו-``_fit_page`` שמחזיר
    בסירוב את גודל העמוד הריק בלי התו הראשון.
    """
    budget = answer_size.OUTPUT_BYTE_BUDGET

    def dbm_for(length):
        return _Dbm(code_text, extra={"description": "x" * length})

    # ישירות, בלי ``_fit_with_file_meta``: בכלי תיאור כזה יורד וההחלטה אינה נופלת כאן
    # (ריוויו Han על #3492, WARN-001) — ראו :func:`_sections_only`.
    far, at_threshold, below = _bytes_at(arguments, dbm_for)

    for out in (far, at_threshold):
        assert out["ok"] is False and out["error"] == error
        assert out["max"] == budget
        assert out["bytes"] > out["max"]
    assert at_threshold["bytes"] == budget + 1
    assert below.get("error") != error, "תו אחד פחות עדיין נדחה — האורך אינו הסף"


async def test_the_docs_tool_reports_its_budget_refusal_against_the_same_max(monkeypatch):
    """``codekeeper_docs_get_section`` — אותו ``max``, ו-``bytes`` מעליו. אין לו מעטפת.

    אותו קלט של ``test_a_section_whose_headings_alone_do_not_fit_is_refused_with_its_lines``:
    כותרות באורך של פסקאות, שגם עמוד ריק שלהן אינו נכנס.
    """
    monkeypatch.setenv("MCP_DOCS_REPO", "CodeBot,amir-bug-patterns")
    title = "汉" * 240
    text = "# שורש\n" + "".join(f"## {title} {i}\n" for i in range(docs_handlers._TOC_MAX))
    mcp = _build(monkeypatch, repo_backend=_RepoText(text))

    out = _payload(await mcp.call_tool(
        "codekeeper_docs_get_section",
        {"path": "x.md", "repo": "amir-bug-patterns", "section": "שורש"}))

    assert out["ok"] is False and out["error"] == docs_handlers.SECTION_TOO_LARGE
    assert out["bytes"] > out["max"] == answer_size.OUTPUT_BYTE_BUDGET


def _huge_tags_cases():
    """כל סירוב שנושא את ``file``, עם הקלט שמביא אליו. ``(id, dbm, arguments, setup)``."""
    mixed = "# א\n\n## ב\rטקסט\n\n## ג\n"
    return [
        ("toc", {}, {"toc": True}, None),
        ("section", {}, {"section": "K11"}, None),
        ("section_not_found", {}, {"section": "K99"}, None),
        ("ambiguous_section", {}, {"section": "K12 כפול"}, None),
        ("section_too_long", {}, {"section": "K" * (docs_handlers.MAX_SECTION_CHARS + 1)}, None),
        ("not_markdown", {"code": "x = 1\n", "file_name": "tool.py", "language": "python"},
         {"toc": True}, None),
        ("too_large_for_sections", {}, {"toc": True}, "shrink_ceiling"),
        ("inconsistent_line_endings", {"code": mixed}, {"toc": True}, None),
    ]


@pytest.mark.parametrize(
    ("dbm_kwargs", "arguments", "setup"),
    [case[1:] for case in _huge_tags_cases()],
    ids=[case[0] for case in _huge_tags_cases()],
)
async def test_a_refusal_gives_up_the_file_tags_first_and_says_so(
    monkeypatch, dbm_kwargs, arguments, setup,
):
    """תגית ענקית יורדת מהתשובה — ``file.tags: []`` ו-``file.tags_truncated: true`` — ושאר התשובה שלמה.

    עד #3472 כל סירוב נשא את המטא-דאטה כמו שהיא, ותגית ענקית שלחה סירוב של כ-270KB —
    מעל ``OUTPUT_BYTE_BUDGET``, בלי שום סימן. #3472 (SUGG-002) הוריד את התגיות מהסירוב,
    והמפה והסעיף — שהיו תשובה מוצלחת עם תגית קטנה — הפכו לסירוב של התקציב. **מאז ריוויו Han
    על #3492 (WARN-001) גם הם מוותרים על התגיות ולא על התשובה:** התגית לבדה היא מה שלא נכנס,
    ולכן המפה והסעיף חוזרים, עם אותו ויתור ואותו סימן.

    **ובכל צורה זה ההבדל היחיד** — התשובה זהה לזו של אותו קובץ עם תגית קטנה, פרט לתגיות.
    ב-``section_not_found`` וב-``ambiguous_section`` זה אומר שהתגיות יורדות **ראשונות**:
    המפה, ההצעות והמועמדים נשארים שלמים.

    נופלת על הקוד שלפני #3472: התגית חוזרת שלמה, והתשובה כפי שנשלחה מעל התקציב. ועל הקוד
    שלפני WARN-001: המפה והסעיף הם ``answer_too_large``/``section_too_large``.

    מוטציות שמפילות: ``_FILE_REFUSAL_CUTS = ()``; להחזיר את ``not_markdown`` ישירות, בלי
    ``refuse``; ו-``refusal_cuts`` **אחרי** המפה וההצעות ב-``section_not_found`` — המפה
    מתרוקנת לפני התגיות.
    """
    from mcp_server import backend as backend_mod

    if setup == "shrink_ceiling":
        monkeypatch.setattr(backend_mod, "MAX_FILE_SIZE_FOR_DISPLAY", 40)

    small_mcp = _build(monkeypatch, _Dbm(**dbm_kwargs, extra={"tags": ["קטן"]}))
    small = await _call(small_mcp, file_name=_meta_name(dbm_kwargs), **arguments)
    huge_mcp = _build(monkeypatch, _Dbm(**dbm_kwargs, extra={"tags": _HUGE_TAGS}))

    out, sent = await _call_sent(huge_mcp, file_name=_meta_name(dbm_kwargs), **arguments)

    assert sent <= answer_size.OUTPUT_BYTE_BUDGET
    assert out["file"]["tags"] == [] and out["file"]["tags_truncated"] is True
    assert out == {**small, "file": {**small["file"], "tags": [], "tags_truncated": True}}


def _meta_name(dbm_kwargs):
    """השם שהדמה שומרת את הקובץ בו — ברירת המחדל, או מה שהמקרה ביקש."""
    return dbm_kwargs.get("file_name", _MD_NAME)


@pytest.mark.parametrize(
    ("text", "arguments", "cut"),
    [
        (_deep_hebrew_map(), {"toc": True}, ("toc_truncated", True)),
        ("# רחב\n\n" + _wide_lines("汉", 120_000) + "\n",
         {"section": "רחב", "max_chars": docs_handlers.MAX_CHARS_MAX},
         ("truncation_reason", "byte_budget")),
    ],
    ids=["toc", "section"],
)
async def test_a_successful_reply_carries_the_file_metadata_whole(
    monkeypatch, text, arguments, cut,
):
    """תשובה מוצלחת אינה מוותרת על מטא-דאטה כשהתוכן עצמו הוא מה שגדול — היא חותכת את עצמה.

    תגיות של כ-60KB, ומפה או עמוד שלא נכנסים גם בלעדיהן: המפה נחתכת מהסוף והעמוד נגמר
    מוקדם, והתגיות נשארות שלמות. מאז ריוויו Han על #3492 (WARN-001) תשובה מוצלחת מוותרת
    על התגיות רק כשהן לבדן דוחפות אותה מעל התקציב, או כשהן גדולות מכל שאר התשובה — וכאן
    אף אחד מהשניים אינו נכון. התשובה כפי שנשלחה בתוך התקציב.

    זה הגבול של התיקון ולא התיקון עצמו, ולכן עובר גם על הקוד שלפני #3472 — שם שום דבר
    לא חתך תגיות.

    מוטציה שמפילה: להעביר את ``refusal_cuts`` גם ל-``cuts`` של המפה ב-
    ``_answer_from_document`` — התגיות נחתכות לפני המפה.
    """
    tags = ["汉" * 20_000]
    mcp = _build(monkeypatch, _Dbm(text, extra={"tags": tags}))

    out, sent = await _call_sent(mcp, file_name=_MD_NAME, **arguments)

    assert sent <= answer_size.OUTPUT_BYTE_BUDGET
    key, value = cut
    assert out["ok"] is True and out[key] == value
    assert out["file"]["tags"] == tags and "tags_truncated" not in out["file"]


async def test_a_miss_and_a_repeated_name_carry_no_hint(monkeypatch):
    """ה-``hint`` שמפנה ל-``lines``/``query`` אינו ב-``section_not_found`` וב-``ambiguous_section``.

    הוא שייך לסירובים שבהם הקובץ אינו קריא לפי סעיפים (``not_markdown``, סירובי הפרסר,
    ``section_too_large``, ``answer_too_large``). כאן הקובץ קריא, והתשובה עצמה נושאת את
    הדרך הלאה — המפה וההצעות, או המועמדים עם ``line_range``. הפניה ל-``lines`` הייתה
    שולחת את הקורא לקרוא את הקובץ כולו במקום לבחור כותרת. (וכשהתגיות נחתכו בסירוב
    כזה — אותו דבר: ``test_a_refusal_gives_up_the_file_tags_first_and_says_so`` משווה את
    התשובה כולה לזו של אותו קובץ עם תגית קטנה.)

    זה מקבע החלטה קיימת ולא תיקון (#3472, SUGG-011), ולכן עובר גם על הקוד שלפני #3472.

    מוטציה שמפילה: להוסיף את ה-``hint`` לכל סירוב ב-``_apply_sections_to_file``.
    """
    mcp = _build(monkeypatch)
    for section in ("K99", "K12 כפול"):
        out = await _call(mcp, file_name=_MD_NAME, section=section)
        assert out["ok"] is False and "hint" not in out, section


@pytest.mark.parametrize("stored", [b"# bytes\n", 12345], ids=["bytes", "int"])
async def test_stored_content_that_is_not_a_string_fails_loudly(monkeypatch, stored):
    """תוכן שמור שאינו מחרוזת נופל בקול, ואינו מומר למחרוזת ומפורסר.

    אין מסלול שמירה שכותב תוכן כזה — ב-1,100 מסמכי ה-Markdown השמורים אין אף אחד
    (PR #3470) — ולכן זה חוזה שנשבר ולא קלט שנדחה, והענף הוא בדיוק ענף שאיש לא מריץ
    עד היום שבו הוא נחוץ. ``_json_safe`` מעביר ``bytes`` ומספר כמו שהם, ולכן שניהם
    מגיעים לבדיקה. ההודעה נושאת את שם הטיפוס בלבד, בלי תוכן.

    הבדיקה יושבת ב-``_full``, ולכן חלה על כל מצבי הקריאה ועל העריכה וההוספה —
    ``tests/test_mcp_content_sha256.py`` מכסה את השאר.

    מוטציה שמפילה: להחליף את ה-``raise`` ב-``_full`` בהמרה
    (``code = out["code"] = str(code)``) — מפה של משהו שאינו הקובץ חוזרת בלי חריגה.
    """
    from mcp.server.fastmcp.exceptions import ToolError

    mcp = _build(monkeypatch, _Dbm(stored))

    with pytest.raises(ToolError, match=f"stored file content is {type(stored).__name__}, not str"):
        await mcp.call_tool("codekeeper_get_file", {"file_name": _MD_NAME, "toc": True})


def test_the_request_nets_refuse_what_the_schema_would_have_stopped():
    """רשת מאחורי הסכימה, לקורא שאינו עובר בה — ``handlers`` ו-backend באותה פונקציה.

    ב-``toc`` הסכימה אינה עוצרת ``"false"`` אלא ממירה אותו ל-``False`` (#3472, WARN-002).
    קורא שעוקף אותה אינו מקבל את ההמרה, ובלי הרשת ``"false"`` — מחרוזת לא ריקה — היה
    נקרא אצלו כמצב המפה. לכן הרשת דוחה כל מה שאינו ``bool``, ואינה ממירה בעצמה.

    מוטציה שמפילה: להסיר את ``isinstance`` על ``toc`` — ``"false"`` נקרא כמצב המפה.
    """
    from mcp_server.backend import ProductionBackend

    def request(**overrides):
        base = {"query": None, "lines": None, "context_lines": None, "max_results": None}
        return handlers.file_read_request_error(**{**base, **overrides})

    assert request(section=5) == handlers.SECTION_INVALID
    assert request(section=["K11"]) == handlers.SECTION_INVALID
    for bad_toc in ("true", "false", 1, 0, None):
        assert request(toc=bad_toc) == handlers.TOC_INVALID
    assert request(toc=True) is None and request(section="K11") is None

    backend = ProductionBackend(db_manager=_Dbm())
    assert backend.get_file(_USER, file_name=_MD_NAME, toc="false") == {
        "ok": False, "error": handlers.TOC_INVALID}


async def test_toc_is_read_like_every_other_flag_and_only_nonsense_is_refused(monkeypatch):
    """``toc`` הוא ``bool`` רגיל, כמו ``outline`` (#3472, WARN-002).

    ``"true"``, ``"yes"``, ``"1"`` ו-``1`` נותנים **בדיוק** את המפה של ``toc=true``;
    ``"false"``, ``"no"``, ``"0"`` ו-``0`` — בדיוק את הקובץ המלא של קריאה בלי ``toc``. עד
    #3472 ``toc`` היה ``StrictBool``, והמחרוזת ``"true"`` — שמגיעה לכלי כמו שהיא, כי
    ``pre_parse_json`` זורק פענוח שנותן ``int`` — נדחתה בשגיאת ולידציה: לקוח ששולח דגלים
    כמחרוזות נחסם בכניסה לפיצ'ר, בזמן ש-``outline="true"`` אצלו עבד. מה שאינו בוליאני
    בשום קריאה — ``"maybe"``, ``2``, ``null``, ``""`` — עדיין נדחה, ו-``section`` שאינו
    מחרוזת גם. ``ToolError`` ולא ``Exception``: מה שנבדק הוא ולידציית הסכימה. ובסכימה
    ``toc`` נראה בדיוק כמו ``outline``.

    נופלת על הקוד שלפני התיקון: ``"true"`` זורק.

    מוטציה שמפילה: להחזיר ``StrictBool`` ל-``toc`` ב-``server.py``.
    """
    from mcp.server.fastmcp.exceptions import ToolError

    mcp = _build(monkeypatch)
    as_map = await _call(mcp, file_name=_MD_NAME, toc=True)
    whole = await _call(mcp, file_name=_MD_NAME)
    assert as_map["status"] == "toc" and whole["file"]["code"] == _MD

    for sent in ("true", "yes", "1", 1):
        assert await _call(mcp, file_name=_MD_NAME, toc=sent) == as_map, sent
    for sent in ("false", "no", "0", 0):
        assert await _call(mcp, file_name=_MD_NAME, toc=sent) == whole, sent
    for bad in ("maybe", 2, None, ""):
        with pytest.raises(ToolError, match="validation error"):
            await _call(mcp, file_name=_MD_NAME, toc=bad)
    for bad in (5, ["K11"]):
        with pytest.raises(ToolError, match="validation error"):
            await _call(mcp, file_name=_MD_NAME, section=bad)

    def shape(tool, name):
        prop = mcp._tool_manager.get_tool(tool).parameters["properties"][name]
        return {k: v for k, v in prop.items() if k not in ("title", "description")}

    assert shape("codekeeper_get_file", "toc") == shape("codekeeper_get_repo_file", "outline")


# ---------------------------------------------------------------------------
# 3. שימוש חוזר
# ---------------------------------------------------------------------------


async def test_both_tools_answer_through_the_same_functions(monkeypatch):
    """``codekeeper_get_file`` ו-``codekeeper_docs_get_section`` עוברים באותן שתי פונקציות.

    ``docs_handlers.parse_with_refusals`` (פרסור ומיפוי הסירובים) ו-
    ``docs_handlers._answer_from_document`` (התאמה, חיתוך ובניית התשובה). על
    אותו טקסט ואותה שאלה, שדות הסעיף זהים בשני הכלים.

    מוטציה שמפילה: לפרסר ב-backend ישירות (``md_parser.parse_document``) או
    לבנות שם את התשובה — ה-spy רואה רק את כלי ה-docs.
    """
    monkeypatch.setenv("MCP_DOCS_REPO", "CodeBot,amir-bug-patterns")
    parsed_for: list[str] = []
    answered_for: list[str] = []
    real_parse = docs_handlers.parse_with_refusals
    real_answer = docs_handlers._answer_from_document

    def parse_spy(parser, content, context):
        parsed_for.append("file" if "file" in context else "docs")
        return real_parse(parser, content, context)

    def answer_spy(doc, **kwargs):
        answered_for.append("file" if "file" in kwargs["context"] else "docs")
        return real_answer(doc, **kwargs)

    monkeypatch.setattr(docs_handlers, "parse_with_refusals", parse_spy)
    monkeypatch.setattr(docs_handlers, "_answer_from_document", answer_spy)
    mcp = _build(monkeypatch, repo_backend=_RepoText(_MD))

    from_file = await _call(mcp, file_name=_MD_NAME, section="K11")
    from_docs = _payload(await mcp.call_tool(
        "codekeeper_docs_get_section",
        {"path": "x.md", "repo": "amir-bug-patterns", "section": "K11"}))

    assert parsed_for == ["file", "docs"]
    assert answered_for == ["file", "docs"]
    for key in ("mode", "section", "breadcrumb", "level", "line_range", "content",
                "include_subsections", "offset", "truncated", "subsections", "neighbors"):
        assert from_file[key] == from_docs[key], key


def test_the_file_metadata_drops_heavy_fields_through_the_one_function():
    """``_file_meta`` מסיר את השדות הכבדים דרך ``_strip_heavy`` — לא בעותק משלו (SUGG-006).

    עד #3472 היו שני נוסחים של אותה הסרה: ``_file_meta`` שטוח, ו-``_strip_heavy`` רקורסיבי.
    על מסמך של היום הם זהים, ולכן ההבדל נראה רק בשדה כבד בתוך אובייקט מקונן — מה שנוסח
    שטוח היה מפספס בשקט ביום שיתווסף.

    נופלת על הקוד שלפני התיקון: ``code`` המקונן נשאר.

    מוטציה שמפילה: להחזיר ל-``_file_meta`` את ההסרה השטוחה.
    """
    from mcp_server import backend as backend_mod

    heavy = sorted(backend_mod._HEAVY_FIELDS)[0]
    out = {"id": "x", heavy: "full text", "nested": {heavy: "deep", "kept": 1}, "tags": ["a"]}

    meta = backend_mod._file_meta(out)

    assert meta == backend_mod._strip_heavy(out)
    assert heavy not in meta and meta["nested"] == {"kept": 1} and meta["tags"] == ["a"]


async def test_the_docs_tool_fits_its_page_to_the_same_budget(monkeypatch):
    """``codekeeper_docs_get_section`` מקבל את אותו חיתוך, כי הוא ב-``_answer_from_document``.

    לכלי התיעוד אין ``found``/``status``, ולכן הוא אינו שומר להם מקום — והעמוד שלו
    על אותו טקסט אינו קצר מזה של ``codekeeper_get_file``. שניהם בתוך התקציב כפי
    שנשלחו, ושניהם אומרים למה.

    מוטציה שמפילה: לחתוך רק ב-``_apply_sections_to_file`` ולא בפונקציה המשותפת —
    תשובת כלי התיעוד עוברת את התקציב.
    """
    monkeypatch.setenv("MCP_DOCS_REPO", "CodeBot,amir-bug-patterns")
    text = "# רחב\n\n" + _wide_lines("汉", 120_000) + "\n"
    mcp = _build(monkeypatch, _Dbm(text), repo_backend=_RepoText(text))

    from_file, file_sent = await _call_sent(mcp, file_name=_MD_NAME, section="רחב",
                                            max_chars=docs_handlers.MAX_CHARS_MAX)
    from_docs, docs_sent = await _call_sent(
        mcp, "codekeeper_docs_get_section", path="x.md", repo="amir-bug-patterns",
        section="רחב", max_chars=docs_handlers.MAX_CHARS_MAX)

    assert docs_sent <= answer_size.OUTPUT_BYTE_BUDGET
    assert file_sent <= answer_size.OUTPUT_BYTE_BUDGET
    assert from_docs["truncation_reason"] == from_file["truncation_reason"] == "byte_budget"
    assert from_docs["content"].startswith(from_file["content"])


async def test_the_docs_tool_fits_its_map_to_the_same_budget(monkeypatch):
    """גם המפה של ``codekeeper_docs_get_section`` נחתכת — כי החיתוך ב-``_answer_from_document``.

    מוטציה שמפילה: לחתוך את המפה רק ב-``_apply_sections_to_file`` ולא בפונקציה המשותפת.
    """
    monkeypatch.setenv("MCP_DOCS_REPO", "CodeBot,amir-bug-patterns")
    text = _deep_hebrew_map()
    full = doc_sections.build_toc(md_parser.parse_document(text))
    mcp = _build(monkeypatch, _Dbm(text), repo_backend=_RepoText(text))

    out, sent = await _call_sent(mcp, "codekeeper_docs_get_section", path="x.md",
                                 repo="amir-bug-patterns")

    assert sent <= answer_size.OUTPUT_BYTE_BUDGET
    assert out["mode"] == "toc" and out["toc_truncated"] is True
    assert 0 < len(out["toc"]) < len(full)
    assert out["toc"] == full[:len(out["toc"])]


def test_fit_lists_keeps_the_longest_prefix_and_gives_up_lists_in_order():
    """``_fit_lists`` על תשובה מלאכותית — ארבעת המקרים, והגבול המדויק בכל אחד.

    פונקציה טהורה, ולכן הקריאה הישירה היא הממשק שלה. התקציב נגזר מגודל התשובה עצמה,
    כדי שכל מקרה ייפול בדיוק במקום שהוא בודק: (1) נכנסת — חוזרת כמו שהיא, בלי דגלים;
    (2) מספיק לקצר את הרשימה הראשונה — השנייה שלמה; (3) גם ריקה הראשונה אינה מספיקה
    — היא ריקה ודגלה דלוק, והשנייה מתקצרת; (4) גם שתיהן ריקות אינן מספיקות — ``None``;
    (5) רשימה שכבר ריקה אינה "נחתכת" ואינה מדליקה דגל — הדגל אומר שחסר משהו.
    ובכל חיתוך, פריט אחד נוסף כבר לא היה נכנס — הקידומת היא הארוכה ביותר.

    מוטציה שמפילה: ``_longest_fitting_prefix`` שמחזיר ``lo - 1`` (חיתוך מוקדם מדי),
    ``_fit_lists`` שממשיך לרשימה הבאה לפני שבדק את הקודמת, או בלי הדילוג על רשימה ריקה.
    """
    wire = answer_size.wire_json
    cuts = (("a", "a_cut"), ("b", "b_cut"))
    answer = {"ok": False, "a": [f"a{i}-" + "x" * 90 for i in range(10)],
              "b": [f"b{i}-" + "y" * 90 for i in range(10)]}

    def size(**changes):
        return len(wire({**answer, **changes}))

    same, measured = answer_fit.fit_lists(answer, cuts=cuts, budget=size())
    assert same is answer and measured == size()

    budget = size(a=answer["a"][:4], a_cut=True)
    out, measured = answer_fit.fit_lists(answer, cuts=cuts, budget=budget)
    assert out["a"] == answer["a"][:4] and out["a_cut"] is True
    assert out["b"] == answer["b"] and "b_cut" not in out
    assert measured == len(wire(out)) <= budget < size(a=answer["a"][:5], a_cut=True)

    budget = size(a=[], a_cut=True, b=answer["b"][:6], b_cut=True)
    out, measured = answer_fit.fit_lists(answer, cuts=cuts, budget=budget)
    assert out["a"] == [] and out["a_cut"] is True
    assert out["b"] == answer["b"][:6] and out["b_cut"] is True
    assert measured <= budget < size(a=[], a_cut=True, b=answer["b"][:7], b_cut=True)

    floor = size(a=[], a_cut=True, b=[], b_cut=True)
    out, measured = answer_fit.fit_lists(answer, cuts=cuts, budget=floor - 1)
    assert out is None and measured == floor

    empty_first = {**answer, "a": []}
    budget = len(wire({**empty_first, "b": answer["b"][:3], "b_cut": True}))
    out, _ = answer_fit.fit_lists(empty_first, cuts=cuts, budget=budget)
    assert out["a"] == [] and "a_cut" not in out
    assert out["b"] == answer["b"][:3] and out["b_cut"] is True


def test_fit_lists_never_serializes_more_than_the_budget_plus_one_item(monkeypatch):
    """שכבה 1 של SEC-001: המחרוזת הגדולה ביותר ש-``_fit_lists`` בונה אי-פעם היא
    התקציב ועוד פריט בודד — לעולם לא התשובה המלאה.

    זה מה שמסיר את ה-OOM: מפה שאינה נכנסת נחתכת **בלי** לסדרל אותה במלואה כדי
    למדוד אותה. הספייה סופרת **כל** קריאת ``wire_json`` — גם אלה שבתוך
    ``list_item_cost`` (לכן היא מחליפה את שני השמות) — ולוקחת את המקסימום. תקציב
    זעיר וקלט זעיר: אין צורך בקובץ ענק כדי להוכיח שהצורה הישנה בנתה את התשובה
    המלאה.

    מוטציה שמפילה (וגם הקוד שלפני התיקון): ``len(wire_json(answer))`` על התשובה
    המלאה בתחילת ``_fit_lists`` — המקסימום קופץ לגודל התשובה כולה, הרבה מעל
    התקציב ועוד פריט, והאסרשן נופל.
    """
    budget = 2000
    toc = [{"title": f"כותרת {i} " + "x" * 60, "level": 2,
            "breadcrumb": ["מסמך", f"כותרת {i} " + "x" * 60],
            "line_range": [i, i + 1], "approx_bytes": 80} for i in range(40)]
    answer = {"ok": True, "file": {"id": "x"}, "includes": [], "mode": "toc",
              "toc": toc, "toc_truncated": False, "section_count": len(toc)}

    real_wire = answer_size.wire_json
    largest_item = max(len(real_wire(item)) for item in toc)
    # הנחת המקרה: התשובה המלאה גדולה בהרבה מהתקציב ועוד פריט — כך שהצורה הישנה,
    # שסדרלה אותה במלואה, בונה מחרוזת מעל הסף שהטסט בודק.
    assert len(real_wire(answer)) > budget + largest_item

    sizes: list[int] = []

    def spy(value):
        out = real_wire(value)
        sizes.append(len(out))
        return out

    monkeypatch.setattr(docs_handlers, "wire_json", spy)
    monkeypatch.setattr(answer_size, "wire_json", spy)
    fitted, size = answer_fit.fit_lists(
        answer, cuts=(("toc", "toc_truncated"),), budget=budget)

    assert sizes, "הספייה לא נקראה — הטסט אינו בודק כלום"
    assert max(sizes) <= budget + largest_item
    assert fitted is not None and size <= budget and fitted["toc_truncated"] is True
    assert fitted["toc"] == toc[:len(fitted["toc"])] and fitted["toc"]  # קידומת בסדר המסמך


def _fit_lists_before_depth(answer, *, cuts, budget):
    """``_fit_lists`` כפי שהיה ב-main ב-``7d4c874``, לפני שלמד לרדת רמה (#3472) — **עותק קפוא**.

    אורקל, ולכן הוא אינו קורא לשום דבר שהשינוי נגע בו: עלות הפריט ועלות הרשימה הלא-ריקה
    כתובות כאן כמו שהיו אז, במספרים (``4``, ``",\\n    "``, ``"\\n  "``), ולא דרך
    ``list_item_cost``/``nonempty_list_bytes`` של היום. רק ``wire_json`` משותף — השינוי לא
    נגע בה, והיא הסריאליזציה ששתי הצורות מודדות.
    """
    wire = answer_size.wire_json

    def cost(item):
        text = wire(item)
        return len(text) + 4 * text.count(b"\n") + len(",\n    ")

    nonempty = len("\n  ")
    list_keys = [key for key, _ in cuts]
    flag_of = dict(cuts)
    base = {**answer, **{key: [] for key in list_keys}}
    item_costs = {key: [cost(item) for item in answer[key]] for key in list_keys}
    total = len(wire(base)) + sum(
        nonempty + sum(item_costs[key]) for key in list_keys if answer[key])
    if total <= budget + len(list_keys):
        real = len(wire(answer))
        if real <= budget:
            return answer, real
    kept = {key: list(answer[key]) for key in list_keys}
    flags = {}
    running = total
    for key, flag in cuts:
        if running <= budget:
            break
        items, costs = kept[key], item_costs[key]
        while items and running > budget:
            running -= costs[len(items) - 1]
            items.pop()
            flags[flag] = True
            if not items:
                running -= nonempty
    fitted = {**answer, **kept, **flags}
    size = len(wire(fitted))
    while size > budget:
        trimmable = next((key for key in list_keys if kept[key]), None)
        if trimmable is None:
            return None, size
        kept[trimmable].pop()
        flags[flag_of[trimmable]] = True
        fitted = {**answer, **kept, **flags}
        size = len(wire(fitted))
    return fitted, size


def _random_value(rng, depth=0):
    """ערך JSON אקראי — מחרוזות בעברית, CJK, אימוג'י ותווי בקרה, ומבנים מקוננים.

    מבנים מקוננים הם מה שנותן לפריט שורות פנימיות, ושם עלות ההזחה לפי העומק נמדדת.
    """
    atoms = ["", "x", "שלום", "汉字", "😀", "\x01", 'a"b', "a\nb", 0, 7, None, True, 2.5]
    roll = rng.random()
    if depth > 2 or roll < 0.35:
        return rng.choice(atoms)
    if roll < 0.7:
        return {f"k{i}": _random_value(rng, depth + 1) for i in range(rng.randint(0, 3))}
    return [_random_value(rng, depth + 1) for _ in range(rng.randint(0, 3))]


def test_fit_lists_at_depth_zero_decides_exactly_as_before_the_depth_was_added():
    """בעומק 0 — כל הקוראים עד #3472 — ``_fit_lists`` מחליט בדיוק כמו לפני שלמד לרדת רמה.

    אותם קלטים בדיוק דרך הצורה של היום ודרך העותק הקפוא של הצורה הקודמת
    (:func:`_fit_lists_before_depth`), על **כל** תקציב בין הקטן מהמינימום לגדול מהתשובה
    המלאה, בית אחרי בית: אותה תשובה (אותו אובייקט כשנכנסה, אותם בתים כשנחתכה), אותו
    גודל, ואותו ``None``. תקציב שנופל בין שתי החלטות הוא בדיוק המקום שבו עלות שגויה בבית
    אחד משנה החלטה — ולכן הסריקה בית-בית, ולא דגימה.

    זו בדיקת שקילות ולא בדיקה של תיקון: הצורה הקודמת היא האורקל, ולכן היא עוברת גם על
    הקוד שלפני #3472. הכוח שלה במוטציות.

    מוטציות שמפילות: ``list_item_cost(item, depth=len(path))`` במקום ``len(path) - 1`` ב-
    ``_fit_lists``; ``nonempty_list_bytes(len(path))``; ``_list_item_indent`` שמחזיר
    ``_WIRE_INDENT * (1 + depth)``.
    """
    rng = random.Random(3472)
    wire = answer_size.wire_json
    keys = ("toc", "suggestions", "candidates")
    compared = 0
    for _ in range(8):
        chosen = keys[:rng.randint(1, 3)]
        answer = {"ok": rng.choice([True, False]), "file": {"id": "x", "tags": ["a"]},
                  "includes": []}
        for key in chosen:
            answer[key] = [_random_value(rng) for _ in range(rng.randint(0, 6))]
        cuts = tuple((key, f"{key}_truncated") for key in chosen)
        full = len(wire(answer))
        smallest = len(wire({**answer, **{key: [] for key in chosen},
                             **{flag: True for _, flag in cuts}}))
        for budget in range(smallest - 3, full + 3):
            now, now_size = answer_fit.fit_lists(answer, cuts=cuts, budget=budget)
            before, before_size = _fit_lists_before_depth(answer, cuts=cuts, budget=budget)
            assert now_size == before_size, budget
            assert (now is None) == (before is None), budget
            assert (now is answer) == (before is answer), budget
            if now is not None:
                assert wire(now) == wire(before), budget
            compared += 1
    assert compared > 500, "הסריקה לא רצה — הטסט אינו בודק כלום"


def test_the_cost_of_a_list_item_is_measured_at_the_depth_it_sits():
    """עלות רשימה שיושבת רמה אחת פנימה — ``file.tags`` — מדויקת כמו בראש התשובה.

    ``list_item_cost`` עם ``depth`` ועוד ``nonempty_list_bytes`` של אותו עומק, מעל גודל
    התשובה עם הרשימה ריקה, הם **בדיוק** גודל התשובה האמיתי ועוד פסיק אחד — בעומק 0 ובעומק
    1. הפסיק הוא החסם העליון שהנוסחה מתעדת (לפריט הראשון אין פסיק מוביל), ושום דבר מעבר
    לו: עלות גבוהה מדי הייתה חותכת פריטים שנכנסים, ונמוכה מדי — מבטיחה "נכנס" על תשובה
    שאינה נכנסת. פריטים מקוננים, כי ההזחה של שורה פנימית היא מה שתלוי בעומק.

    נופלת על הקוד שלפני #3472: אין ``depth`` ואין ``nonempty_list_bytes``.

    מוטציות שמפילות: ``list_item_cost`` שמתעלם מ-``depth``; ``nonempty_list_bytes`` שמחזיר
    ``len("\\n") + _WIRE_INDENT * (2 + depth)``.
    """
    rng = random.Random(3489)
    wire = answer_size.wire_json

    def at_depth_0(items):
        return {"ok": False, "tags": items, "error": "e"}

    def at_depth_1(items):
        return {"ok": False, "file": {"id": "x", "tags": items, "version": 2}, "error": "e"}

    for _ in range(300):
        items = [_random_value(rng) for _ in range(rng.randint(1, 6))]
        for depth, place in ((0, at_depth_0), (1, at_depth_1)):
            empty = len(wire(place([])))
            real = len(wire(place(items)))
            estimate = empty + answer_size.nonempty_list_bytes(depth) + sum(
                answer_size.list_item_cost(item, depth=depth) for item in items)
            assert estimate == real + len(","), (depth, items)


# ---------------------------------------------------------------------------
# 3b. תקרת כותרת בודדת (SEC-001 שכבה 2) — חוסמת את מגבר ה-breadcrumb בשורש
# ---------------------------------------------------------------------------

_CEIL = doc_sections.MAX_TITLE_CHARS


def test_the_title_ceiling_equals_the_section_query_ceiling():
    """שני הקבועים שווים — ``services`` אינו מייבא מ-``mcp_server``, ולכן טסט ולא
    ייבוא. דריפט ביניהם שובר את ה-round-trip: אילו תקרת הכותרת הייתה קטנה מתקרת
    השאילתה, כותרת שנחתכה קצר יותר לא הייתה מתאימה לשאילתה שמדביקה אותה.
    """
    assert doc_sections.MAX_TITLE_CHARS == docs_handlers.MAX_SECTION_CHARS


async def test_a_heading_over_the_ceiling_is_truncated_flagged_and_matches_itself(monkeypatch):
    """כותרת מעל התקרה נחתכת במפה עם ``title_truncated``, וה-``line_range`` שלם —
    והדבקת הכותרת כפי שהוצגה ל-``section=`` מוצאת את הסעיף (round-trip).

    מוטציה שמפילה: להסיר את הקיצוב ב-``_finalize`` — הכותרת חוזרת במלואה בלי דגל,
    וגם התשובה תופחת (זה בדיוק מה ששכבה 2 מונעת).
    """
    long_title = "ת" * (_CEIL + 500)
    md = f"# מסמך\n\n## {long_title}\n\nגוף הסעיף.\n"
    mcp = _build(monkeypatch, _Dbm(code=md))

    toc = await _call(mcp, file_name=_MD_NAME, toc=True)
    entry = next(e for e in toc["toc"] if e.get("title_truncated"))
    assert len(entry["title"]) <= _CEIL and entry["title_truncated"] is True

    ans = await _call(mcp, file_name=_MD_NAME, section=entry["title"])
    assert ans.get("status") == "section"
    assert ans["section"] == entry["title"] and ans.get("title_truncated") is True
    assert ans["line_range"] == entry["line_range"]


async def test_the_ceiling_applies_to_breadcrumb_copies_not_only_the_heading(monkeypatch):
    """התקרה חלה גם על עותקי ה-breadcrumb: כותרת-אב ארוכה נחתכת גם בתוך ה-
    breadcrumb של הילד, לא רק בשורה של עצמה — כי הקיצוב במקור, לפני בניית ה-
    breadcrumb. זה מה שסוגר את מגבר ה-breadcrumb בשורש.
    """
    parent = "ת" * (_CEIL + 500)
    md = f"# {parent}\n\n## ילד\n\nגוף.\n"
    mcp = _build(monkeypatch, _Dbm(code=md))

    toc = await _call(mcp, file_name=_MD_NAME, toc=True)
    child = next(e for e in toc["toc"] if e["title"] == "ילד")
    assert child["breadcrumb"][0] == parent[:_CEIL] and len(child["breadcrumb"][0]) <= _CEIL


async def test_two_headings_sharing_a_prefix_over_the_ceiling_are_ambiguous(monkeypatch):
    """כשכמה כותרות חולקות קידומת ארוכה מהתקרה, בקשה לפי הקידומת מחזירה מועמדים —
    התנהגות חדשה שנולדת מהתקרה עצמה, לא מקלט המשתמש (מתועדת ב-mcp-server.rst).
    שני המועמדים נושאים ``line_range`` כדי לקרוא אותם בפועל.
    """
    shared = "ת" * (_CEIL + 200)
    md = f"# מסמך\n\n## {shared} ALPHA\n\na\n\n## {shared} BETA\n\nb\n"
    mcp = _build(monkeypatch, _Dbm(code=md))

    toc = await _call(mcp, file_name=_MD_NAME, toc=True)
    capped = next(e["title"] for e in toc["toc"] if e.get("title_truncated"))
    ans = await _call(mcp, file_name=_MD_NAME, section=capped)
    assert ans["error"] == "ambiguous_section" and len(ans["candidates"]) >= 2
    assert all("line_range" in c for c in ans["candidates"])
    # ושני המועמדים נושאים ``title_truncated`` — אחרת שתי כותרות שונות שחולקות
    # קידומת מעל התקרה נראות זהות ובלי סימן שהשם חלקי (ממצא Greptile).
    assert all(c.get("title_truncated") is True for c in ans["candidates"])


@pytest.mark.parametrize("title", [
    "אָ" * _CEIL,               # עברית עם ניקוד (בסיס + סימן צירוף)
    "中" * (_CEIL + 50),             # CJK — נקודות-קוד בודדות
    "👨‍👩‍👧" * _CEIL,      # אמוג'י משפחה עם ZWJ
])
def test_the_ceiling_cut_is_safe_for_hebrew_cjk_and_emoji(title):
    """קיצוץ בטוח: על גבול תו, בלי שארית תלויה, ותמיד UTF-8 תקין — נבדק על שלושת
    סוגי התוכן שבהם חיתוך נאיבי היה שובר אשכול (כמו במתאם העמוד לתקציב).
    """
    cut = doc_sections._truncate_title(title)
    assert 0 < len(cut) <= _CEIL
    cut.encode("utf-8")  # לא זורק — אין חצי-תו
    assert not doc_sections._is_dangling_mark(cut[-1])  # אין סימן צירוף/ZWJ תלוי בסוף


async def test_subsections_and_neighbors_carry_the_truncation_flag(monkeypatch):
    """``subsections`` ו-``neighbors`` נושאים ``title_truncated`` כשכותרתם נחתכה —
    אותה מוסכמה כמו במפה ובתשובת הסעיף. בלעדיו ניווט דרכם מציג שם חתוך בלי סימן
    שהוא חלקי, וכותרות שונות בעלות קידומת משותפת נראות זהות (ממצא Greptile).

    מוטציה שמפילה (וזה גם הקוד שלפני התיקון): ``_section_ref`` בלי ``_title_flag``.
    """
    long_child = "ת" * (_CEIL + 300)
    long_sib = "א" * (_CEIL + 300)
    md = (f"# מסמך\n\n## הורה\n\nגוף.\n\n"
          f"### {long_child}\n\nעומק.\n\n"
          f"## {long_sib}\n\nאחרי.\n")
    mcp = _build(monkeypatch, _Dbm(code=md))

    out = await _call(mcp, file_name=_MD_NAME, section="הורה")

    sub = out["subsections"][0]
    assert len(sub["title"]) <= _CEIL and sub.get("title_truncated") is True
    nxt = out["neighbors"]["next"]
    assert len(nxt["title"]) <= _CEIL and nxt.get("title_truncated") is True


async def test_a_truncated_breadcrumb_element_reads_like_the_heading_itself(monkeypatch):
    """הדבקת **רכיב breadcrumb** של כותרת מקוצצת ל-``section=`` מתנהגת בדיוק כמו הדבקת
    הכותרת עצמה — הן אותה מחרוזת, כי הקיצוב במקור (``_finalize``) קורה לפני בניית
    ה-breadcrumb. אחרת יש שני מקורות לאותה מחרוזת עם שתי התנהגויות.

    נועל-חוזה (guard): עובר על הקוד הנוכחי ומגן מפני דריפט עתידי — אינו תופס את באג
    ה-Greptile, אלא מקבע את דרישת ה-round-trip.
    """
    parent = "ת" * (_CEIL + 500)
    md = f"# {parent}\n\n## ילד\n\nגוף.\n"
    mcp = _build(monkeypatch, _Dbm(code=md))

    crumb = (await _call(mcp, file_name=_MD_NAME, section="ילד"))["breadcrumb"][0]
    heading = next(e["title"] for e in
                   (await _call(mcp, file_name=_MD_NAME, toc=True))["toc"]
                   if e.get("title_truncated"))
    assert crumb == heading  # רכיב ה-breadcrumb הוא אותה מחרוזת כמו הכותרת במפה

    by_crumb = await _call(mcp, file_name=_MD_NAME, section=crumb)
    by_heading = await _call(mcp, file_name=_MD_NAME, section=heading)
    assert by_crumb == by_heading
    assert by_crumb.get("status") == "section" and by_crumb.get("title_truncated") is True


async def test_a_shared_truncated_breadcrumb_element_is_ambiguous_like_the_heading(monkeypatch):
    """המשך אותו חוזה כשהמחרוזת המקוצצת משותפת לכמה אבות: הדבקת רכיב ה-breadcrumb
    מחזירה ``ambiguous_section`` — בדיוק כמו הדבקת הכותרת מהמפה. "מתאימה, או מחזירה
    מועמדים", ולשתי הדרכים אותה תשובה בדיוק.
    """
    shared = "ת" * (_CEIL + 200)
    md = (f"# {shared} A\n\n## בן א\n\nx\n\n"
          f"# {shared} B\n\n## בן ב\n\ny\n")
    mcp = _build(monkeypatch, _Dbm(code=md))

    crumb = (await _call(mcp, file_name=_MD_NAME, section="בן א"))["breadcrumb"][0]
    heading = next(e["title"] for e in
                   (await _call(mcp, file_name=_MD_NAME, toc=True))["toc"]
                   if e.get("title_truncated"))
    assert crumb == heading

    by_crumb = await _call(mcp, file_name=_MD_NAME, section=crumb)
    by_heading = await _call(mcp, file_name=_MD_NAME, section=heading)
    assert by_crumb["error"] == "ambiguous_section"
    assert by_crumb == by_heading


# ---------------------------------------------------------------------------
# 4. תוספתיות
# ---------------------------------------------------------------------------


async def test_a_call_without_the_new_modes_returns_what_it_returned_before(monkeypatch):
    """בלי ``toc``/``section`` — אותה תשובה כמו לפני התוספת, גם עם ``toc=false`` מפורש.

    מוטציה שמפילה: ``if toc is not None`` במקום ``if toc`` ב-``server.py`` —
    ``toc=false`` מחזיר את המעטפת במקום ``{"found", "file"}``.
    """
    mcp = _build(monkeypatch)

    plain = await _call(mcp, file_name=_MD_NAME)
    assert set(plain) == {"found", "file"}
    assert plain["file"]["code"] == _MD
    assert await _call(mcp, file_name=_MD_NAME, toc=False) == plain
    assert await _call(mcp, file_name=_MD_NAME, section=None) == plain

    ranged = await _call(mcp, file_name=_MD_NAME, toc=False, lines=[5, 7])
    assert ranged["file"]["code"] == _source(_MD, 5, 7)
    queried = await _call(mcp, file_name=_MD_NAME, toc=False, query="K11")
    assert queried["status"] == "query" and queried["count"] == 2

    # ``toc=false`` עם ``section`` הוא מצב הסעיף, ולא זוג.
    section = await _call(mcp, file_name=_MD_NAME, toc=False, section="K11")
    assert section["status"] == "section"


async def test_the_new_parameters_are_optional_and_typed_as_declared(monkeypatch):
    """הסכימה היא מה שהלקוח רואה, ולכן היא נבדקת ולא מונחת.

    אף פרמטר חדש אינו ``required``. ``toc`` בוליאני עם ``false``; ``section``
    באותה צורה כמו ``query``; ``max_chars`` ו-``offset`` מספר או ``null``.
    """
    mcp = _build(monkeypatch)
    tools = {tool.name: (tool.inputSchema or {}) for tool in await mcp.list_tools()}
    schema = tools["codekeeper_get_file"]
    props = schema["properties"]

    def shape(prop):
        return {k: v for k, v in prop.items() if k not in ("title", "description")}

    assert not set(schema.get("required") or ()) & {"toc", "section", "max_chars", "offset"}
    assert shape(props["toc"]) == {"type": "boolean", "default": False}
    assert shape(props["section"]) == shape(props["query"])
    for name in ("max_chars", "offset"):
        assert shape(props[name]) == {
            "anyOf": [{"type": "integer"}, {"type": "null"}], "default": None}


# ---------------------------------------------------------------------------
# 5. אכיפה — האנליטיקס והתיאורים
# ---------------------------------------------------------------------------


def _read_mode(arguments):
    return analytics.read_mode_properties(
        {"method": "tools/call",
         "params": {"name": "codekeeper_get_file", "arguments": arguments}})


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"toc": True}, analytics.READ_MODE_OUTLINE),
        ({"section": "K11"}, analytics.READ_MODE_SECTION),
        # ``section`` ריק נדחה בכלי — ובכל זאת הוא ביקש סעיף, לא קובץ.
        ({"section": ""}, analytics.READ_MODE_SECTION),
        # זוגות שהכלי דוחה נספרים לפי המצב הראשון בקוד הסירוב שלהם.
        ({"toc": True, "section": "K11"}, analytics.READ_MODE_OUTLINE),
        ({"toc": True, "lines": [1, 2]}, analytics.READ_MODE_OUTLINE),
        ({"section": "K11", "query": "x"}, analytics.READ_MODE_SECTION),
        ({"section": "K11", "lines": [1, 2]}, analytics.READ_MODE_SECTION),
        # ``toc=false`` אינו מפה.
        ({"toc": False}, analytics.READ_MODE_FULL),
        ({"toc": False, "lines": [1, 2]}, analytics.READ_MODE_RANGE),
        # דגל במחרוזת נקרא כמו שהכלי קורא אותו (#3472): ``"false"`` הוא קריאה מלאה.
        ({"toc": "true"}, analytics.READ_MODE_OUTLINE),
        ({"toc": "false"}, analytics.READ_MODE_FULL),
        ({"toc": "0", "lines": [1, 2]}, analytics.READ_MODE_RANGE),
        ({"toc": "no", "section": "K11"}, analytics.READ_MODE_SECTION),
    ],
)
def test_a_toc_or_section_read_is_labelled_by_its_mode_and_not_as_full(arguments, expected):
    """``toc`` נספר כ-``outline`` ו-``section`` כ-``section`` — ולעולם לא כ-``full``.

    מוטציה שמפילה: להסיר את ענף ה-``toc`` או ה-``section`` מ-``read_mode_properties``
    — הקריאה מסומנת ``full``, כלומר האירוע אומר "קובץ מלא" על קריאה שלא משכה אותו.
    """
    assert _read_mode(arguments) == {analytics.CK_READ_MODE_KEY: expected}


#: ערכים גולמיים של דגל, כמו שהם יכולים להגיע בארגומנטים — כל צורה שהוולידציה ממירה,
#: וכל צורה שהיא דוחה. ``"null"`` ו-``"[]"`` הם מחרוזות ש-``pre_parse_json`` מפענח למשהו
#: שאינו סקלר, ולכן כאן הוא כן מחליף את המחרוזת.
_RAW_FLAG_VALUES = (
    True, False, "true", "false", "True", "FALSE", "yes", "No", "1", "0", 1, 0, 1.0, 0.0,
    "on", "off", "t", "f", "y", "n", None, 2, 0.5, "maybe", "", [], {}, "null", "[]",
)


@pytest.mark.parametrize(
    ("tool", "flag", "required"),
    [("codekeeper_get_file", "toc", {}),
     ("codekeeper_get_repo_file", "outline", {"repo": "CodeBot", "path": "a.py"})],
)
async def test_the_read_mode_reads_a_flag_the_way_the_tool_validates_it(
    monkeypatch, tool, flag, required,
):
    """התווית נגזרת מאותה קריאה של הדגל שהכלי עושה — לכל ערך, ובשני הכלים (#3472).

    האורקל הוא הכלי עצמו: ``pre_parse_json`` ו-``arg_model`` של הכלי הרשום — אותן שתי
    קריאות ש-``call_fn_with_arg_validation`` עושה (``mcp 1.28.1``), כולל ה-``pre_parse_json``
    של השרת. ערך שנקרא ``True`` — מפה (``outline``); ``False`` — קריאה מלאה (``full``);
    ונדחה — קריאה שלא קראה דבר, ולכן במצב הזול (``outline``), כמו זוג מצבים שנדחה. וב-
    ``codekeeper_get_file`` האורקל עצמו נבדק מול קריאה אמיתית לכלי.

    **הבאג קיים מלפני #3472 ב-``outline``:** ``outline="false"`` קורא את הקובץ המלא,
    והאנליטיקס — שבדק אמת-שקר של פייתון — תייג אותו ``outline``. ``toc`` הצטרף אליו כשהפסיק
    להיות strict. ו-``null`` בדגל נדחה בכלי, בשונה ממפתח שלא נשלח.

    נופלת על הקוד שלפני התיקון: ``"false"`` מתויג ``outline``.

    מוטציות שמפילות: ``return bool(value)`` ב-``_flag_requested``; ``arguments.get`` במקום
    הבדיקה ``not in arguments`` ב-``_mode_requested`` — ``null`` מתויג ``full``.
    """
    from mcp.server.fastmcp.exceptions import ToolError

    mcp = _build(monkeypatch)
    meta = mcp._tool_manager.get_tool(tool).fn_metadata
    whole = await _call(mcp, file_name=_MD_NAME)

    for sent in _RAW_FLAG_VALUES:
        try:
            read = getattr(meta.arg_model.model_validate(
                meta.pre_parse_json({**required, flag: sent})), flag)
        except ValidationError:
            read = None
        expected = analytics.READ_MODE_FULL if read is False else analytics.READ_MODE_OUTLINE
        label = analytics.read_mode_properties(
            {"method": "tools/call", "params": {"name": tool, "arguments": {flag: sent}}})
        assert label == {analytics.CK_READ_MODE_KEY: expected}, sent

        if tool == "codekeeper_get_file":
            if read is None:
                with pytest.raises(ToolError, match="validation error"):
                    await _call(mcp, file_name=_MD_NAME, toc=sent)
            else:
                out = await _call(mcp, file_name=_MD_NAME, toc=sent)
                assert (out.get("status") == "toc") if read else (out == whole), sent

    absent = analytics.read_mode_properties(
        {"method": "tools/call", "params": {"name": tool, "arguments": dict(required)}})
    assert absent == {analytics.CK_READ_MODE_KEY: analytics.READ_MODE_FULL}


def test_the_pairs_and_the_label_order_come_from_one_structure():
    """הזוגות שהכלי דוחה והסדר שבו האנליטיקס מתייג — שניהם מ-``FILE_READ_MODES`` (SUGG-005).

    עד #3472 הסדר היה כתוב פעמיים — ``_EXCLUSIVE_READ_MODES`` ושרשרת ``if`` באנליטיקס —
    וטסט הוא שסיכם ביניהם. עכשיו האנליטיקס מקבל **את אותו אובייקט**, הזוגות הם הצירופים
    שלו בסדר שלו, וכל קוד זוג נפתח במצב שקודם בסדר. ולכן קריאה שנדחתה כזוג מתויגת לפי
    המצב הראשון בקוד הסירוב שלה — לכל אחד מששת הזוגות, ולא רק לאלה שבטבלה למעלה.

    נופלת על הקוד שלפני התיקון: אין ``FILE_READ_MODES``.

    מוטציה שמפילה: לתת לאנליטיקס עותק משלו של הסדר, או לכתוב את ``_EXCLUSIVE_READ_MODES``
    שוב כטבלה.
    """
    order = [mode.param for mode in handlers.FILE_READ_MODES]
    sample = {"toc": True, "section": "K11", "query": "x", "lines": [1, 2]}

    assert analytics._TOOL_READ_MODES["codekeeper_get_file"] is handlers.FILE_READ_MODES
    assert ([(first, second) for first, second, _ in handlers._EXCLUSIVE_READ_MODES]
            == list(itertools.combinations(order, 2)))
    for first, second, code in handlers._EXCLUSIVE_READ_MODES:
        assert code == f"{first}_and_{second}"
        pair = {first: sample[first], second: sample[second]}
        assert _read_mode(pair) == _read_mode({first: sample[first]}), code


def test_the_section_label_passes_the_gate_and_the_other_tool_does_not_own_it():
    """התווית החדשה עוברת את השער, ו-``section`` של כלי הריפו אינו נקרא.

    ``codekeeper_get_repo_file`` אינו מצהיר על ``section``; הקולבק מקבל את
    הארגומנטים הגולמיים, ולכן מפתח תועה מגיע אליו — והשיוך הוא מה שמונע ספירה
    שלו. ו-``codekeeper_docs_get_section`` אינו כלי קריאת קובץ כלל.
    """
    assert analytics.READ_MODE_SECTION in analytics._ALLOWED_CUSTOM_PROPERTIES[
        analytics.CK_READ_MODE_KEY]
    stray = analytics.read_mode_properties(
        {"method": "tools/call",
         "params": {"name": "codekeeper_get_repo_file",
                    "arguments": {"repo": "r", "path": "p", "section": "K11", "toc": True}}})
    assert stray == {analytics.CK_READ_MODE_KEY: analytics.READ_MODE_FULL}
    docs = analytics.read_mode_properties(
        {"method": "tools/call",
         "params": {"name": "codekeeper_docs_get_section",
                    "arguments": {"path": "x.md", "section": "K11"}}})
    assert docs is None


async def test_the_tool_points_at_toc_and_section_and_the_parameters_carry_the_detail(
        monkeypatch):
    """שרשרת הגילוי: תיאור הכלי מפנה לשני הפרמטרים בשמם, והפרמטרים נושאים את הפירוט.

    ‏``"toc" in description`` לבדו אינו מספיק — הוא עובר גם על הדוגמה ``toc=true``.
    הבדיקה היא על ההפניה לשם הפרמטרים.

    **וכלל ההתאמה של ``section`` אינו מועתק — יש אליו הפניה** (#3472, YAGNI-002). עד #3472
    ``_SECTION_PARAM_DOC`` שובץ כאן כמו שהוא, כ-3,000 תווים שנסעו בכל ``tools/list``. שני
    הקצוות של ההפניה נאכפים, כמו בכלים האחים ב-``tests/test_mcp_server_build.py``: שהתיאור
    מפנה לפרמטר ``section`` של ``codekeeper_docs_get_section`` בשמו — השם נשתל מהקבוע — ושאותו
    כלי רשום **באותו שרת**, והפרמטר שלו נושא את הכלל.

    מוטציות שמפילות: למחוק את משפט ההפניה מתיאור הכלי ב-``server.py``; לשבץ שוב את
    ``_SECTION_PARAM_DOC`` בתיאור של ``section``; למחוק את ההפניה לכלי האח.
    """
    from mcp_server import server as srv

    mcp = _build(monkeypatch)
    tool = mcp._tool_manager.get_tool("codekeeper_get_file")
    props = tool.parameters["properties"]

    assert "toc and section parameters" in tool.description
    assert len(tool.description) <= 1_400

    toc_doc = props["toc"]["description"]
    for marker in ("Markdown files only", "approx_bytes", "toc_and_section",
                   "toc_and_query", "toc_and_lines", "not_markdown",
                   "too_large_for_sections", "ignores version", "tags_truncated"):
        assert marker in toc_doc, marker

    section_doc = props["section"]["description"]
    assert srv._SECTION_PARAM_DOC not in section_doc
    assert f"`section` parameter of {docs_handlers.SECTION_TOOL_NAME}" in section_doc
    sibling = mcp._tool_manager.get_tool(docs_handlers.SECTION_TOOL_NAME)
    assert sibling is not None, "ההפניה היא לכלי שאינו רשום בשרת הזה"
    assert sibling.parameters["properties"]["section"]["description"] == srv._SECTION_PARAM_DOC
    for marker in ("Markdown files only", "section_and_query", "section_and_lines",
                   "max_chars_without_section", "offset_without_section", "empty_section",
                   "next_offset", "not_markdown", "too_large_for_sections", "too_many_tokens",
                   "tags_truncated"):
        assert marker in section_doc, marker


def test_both_mode_docs_open_with_the_instruction_to_pin_the_version():
    """``toc`` ו-``section`` נפתחים בהוראה להעביר ``file_id`` בקריאות ההמשך (#3472, WARN-003).

    קריאה בכמה שלבים — מפה, סעיף, העמוד הבא, ``lines`` על ``line_range`` — לפי
    ``file_name`` קוראת בכל שלב את הגרסה האחרונה, וגרסה ששמר סשן אחר באמצע נותנת עמוד
    שנפתח באמצע מילה. **בתחילת** התיאור ולא בסופו: ההערה ליד ``_TOOL_DESCRIPTION_MAX_CHARS``
    ב-``server.py`` מתעדת לקוח שמקצר תיאור פרמטר לכ-120 תווים, ולכן ההוראה עצמה — עד
    ``file_id=file.id`` — נכנסת בהם. וגם עמוד התיעוד אומר אותו דבר.

    נופלת על הקוד שלפני התיקון: המשפט אינו קיים.

    מוטציה שמפילה: להעביר את ``_FILE_ID_FOLLOW_UP`` לסוף אחד התיאורים.
    """
    from pathlib import Path

    from mcp_server import server as srv

    instruction = "should pass file_id=file.id"
    for doc in (srv._FILE_TOC_DOC, srv._FILE_SECTION_DOC):
        assert doc.startswith(srv._FILE_ID_FOLLOW_UP)
        assert doc.index(instruction) + len(instruction) <= 120
    page = (Path(__file__).resolve().parent.parent / "docs" / "mcp-server.rst").read_text(
        encoding="utf-8")
    assert "``file_id=file.id``" in page


def test_the_paging_numbers_in_the_section_doc_come_from_the_constants(monkeypatch):
    """ברירת המחדל והגבולות של ``max_chars`` נשתלים מ-``docs_handlers``, ולא נכתבים כטקסט.

    בכלי הזה ברירת המחדל בסכימה היא ``null``, ולכן התיאור הוא המקום היחיד שבו
    הסוכן רואה אותה. הבדיקה בונה את התיאור מחדש עם קבועים אחרים ורואה את הטקסט
    זז — השוואה לערכים של היום הייתה עוברת גם על טקסט קשיח.

    מוטציה שמפילה: לכתוב ``12000`` כטקסט ב-``_build_file_sections_docs``.
    """
    from mcp_server import server as srv

    assert f"default {docs_handlers.MAX_CHARS_DEFAULT}," in srv._FILE_SECTION_DOC
    monkeypatch.setattr(docs_handlers, "MAX_CHARS_DEFAULT", 4321)
    monkeypatch.setattr(docs_handlers, "MAX_CHARS_MIN", 21)
    monkeypatch.setattr(docs_handlers, "MAX_CHARS_MAX", 8765)
    _, rebuilt = srv._build_file_sections_docs()
    assert "(default 4321, 21-8765)" in rebuilt


def test_the_byte_budget_numbers_in_the_section_doc_come_from_the_constants(monkeypatch):
    """התקציב והתקרה על ``subsections`` נשתלים מהקבועים — כמו מספרי העימוד שמעל.

    וגם בתיאור של ``toc``: שתי הסיבות של ``toc_truncated`` נוקבות בשני הקבועים.

    מוטציה שמפילה: לכתוב ``256000`` או ``400`` כטקסט ב-``_build_file_sections_docs``.
    """
    from mcp_server import server as srv

    assert f"cut to fit {answer_size.OUTPUT_BYTE_BUDGET} bytes" in srv._FILE_SECTION_DOC
    # העלה ולא ``repo_handlers``: התיאור קורא את התקציב מ-``answer_size`` עצמו (ריוויו Han
    # על #3492, SUGG-002) — עד אז הטסט הזה החליף ערך בייצוא-משנה ועבר בזכותו.
    monkeypatch.setattr(answer_size, "OUTPUT_BYTE_BUDGET", 1234)
    monkeypatch.setattr(docs_handlers, "_TOC_MAX", 56)
    toc_doc, rebuilt = srv._build_file_sections_docs()
    assert "cut to fit 1234 bytes" in rebuilt
    assert "subsections lists at most 56," in rebuilt
    assert "at 56 headings, or earlier so the reply fits 1234 bytes" in toc_doc


def test_the_list_limits_in_the_section_doc_come_from_the_constants():
    """תיאור ``section`` המשותף נוקב בתקרת המועמדים ובתקציב — מהקבועים, לא מוקלדים.

    זה היה "at most 50" כטקסט; היום שני המספרים שווים, וביום שהקבוע ישתנה התיאור
    היה מבטיח מספר אחר מהקוד. ``_SECTION_PARAM_DOC`` נבנה בזמן הייבוא, ולכן הבדיקה
    היא על הערכים של היום — אותה צורה כמו הבדיקה על ``MAX_IDENTIFIER_SUGGESTIONS``.

    מוטציה שמפילה: לכתוב ``50`` או ``256000`` כטקסט ולשנות את הקבוע.
    """
    from mcp_server import server as srv

    assert (f"at most {docs_handlers._CANDIDATES_MAX}, and fewer when the reply would not "
            f"fit {answer_size.OUTPUT_BYTE_BUDGET} bytes as sent") in srv._SECTION_PARAM_DOC
    assert (f"so the reply fits {answer_size.OUTPUT_BYTE_BUDGET} bytes as sent"
            in srv._SECTION_PARAM_DOC)
    assert answer_size.ANSWER_TOO_LARGE in srv._SECTION_PARAM_DOC


#: הכלל "כותרת ששמה המלא חוזר אינה נענית בשמה", והדרך אליה — בכל משטח שהקורא רואה.
#:
#: **המשטחים הבטיחו את ההפך, וזה מה שהטסט שמתחתם קיים בשבילו.** התיאור של ``toc`` אמר "A heading
#: past the cut is still readable by its name", והעמוד אמר אותו דבר — אבל שם שחוזר בקובץ מחזיר
#: ``ambiguous_section`` תמיד, והמפה שנחתכה כבר אינה מראה את הטווח. קורא שסמך על המשפט נתקע בלי
#: דרך כתובה. לכל משטח שני סמנים, באותה שיטה של ``_SUGGESTION_RULE_SURFACES`` ב-
#: ``tests/test_mcp_server_build.py``: הפסוקית שהיא הכלל, והפסוקית שהיא הדרך — ולא מונח שמופיע
#: בהסבר, כי מונח כזה שורד גם מחיקה של הכלל עצמו.
#:
#: **``_FILE_SECTION_DOC`` נושא מאז #3472 הפניה לכלל, ולא את הכלל** (YAGNI-002): הכלל כתוב
#: פעם אחת, ב-``_SECTION_PARAM_DOC``, והסמן של המשטח הזה הוא ש"repeated names" נמנה בהפניה
#: לשם. שני הקצוות של ההפניה נאכפים ב-
#: ``test_the_tool_points_at_toc_and_section_and_the_parameters_carry_the_detail``.
_REPEATED_NAME_SURFACES = (
    ("_SECTION_PARAM_DOC", "is never returned by that name", "read it by its line_range"),
    ("_FILE_SECTION_DOC", "repeated names", "a line_range is read with lines="),
    ("_FILE_TOC_DOC", "when no other heading has that name",
     "lines= reads the line_range each candidate carries"),
    ("docs/mcp-server.rst", "לעולם אינה נענית בשמה", "שמחזיר בדיוק את טקסט הסעיף"),
)


def test_every_surface_says_a_repeated_name_never_reaches_its_heading():
    """כל משטח אומר ששם שחוזר אינו מגיע לכותרת, ואיך כן מגיעים — ואינו יכול לחזור להבטחה הישנה בשקט.

    נופלת על הטקסט שלפני התיקון: אף משטח לא נשא את הכלל. ההתנהגות שהסמנים מתארים נבדקת בשלוש
    הבדיקות של כותרת שחוזרת, ליד ``test_candidates_are_cut_from_the_end_in_document_order``.

    מוטציה שמפילה: להחזיר לתיאור של ``toc`` את המשפט "still readable by its name, and query
    finds its line".
    """
    from pathlib import Path

    from mcp_server import server as srv

    texts = {
        "_SECTION_PARAM_DOC": srv._SECTION_PARAM_DOC,
        "_FILE_SECTION_DOC": srv._FILE_SECTION_DOC,
        "_FILE_TOC_DOC": srv._FILE_TOC_DOC,
        "docs/mcp-server.rst": (Path(__file__).resolve().parent.parent / "docs" / "mcp-server.rst")
        .read_text(encoding="utf-8"),
    }
    for name, rule, way in _REPEATED_NAME_SURFACES:
        assert rule in texts[name], f"{name}: חסר הכלל"
        assert way in texts[name], f"{name}: חסרה הדרך"


def test_the_byte_budget_has_one_measure_and_one_word():
    """המדידה "כפי שנשלח" היא פונקציה אחת, והסיבה ``byte_budget`` היא מילה אחת.

    ``read_batch`` מודד את הבאץ' ו-``docs_handlers`` את עמוד הסעיף — באותה
    ``wire_json``, ולא בשני עותקים של הנוסחה (R6). והמילה שמסבירה עמוד שנגמר מוקדם
    היא אותה מילה של ``unread_reason`` בבאץ' ושל ``truncation_reason`` בחיפוש.

    מוטציה שמפילה: להחזיר ל-``read_batch`` פונקציה ``_wire`` משלו, או לאיית את
    הסיבה אחרת. **ששני המודולים מייבאים אותן ישירות מ-``answer_size``, בלי שם שני**,
    נאכף ב-``tests/test_mcp_answer_size.py`` על כל מודול בחבילה (ריוויו Han על #3492).
    """
    assert read_batch.answer_size.wire_json is answer_size.wire_json
    assert docs_handlers.wire_json is answer_size.wire_json
    assert answer_size.BYTE_BUDGET_REASON == "byte_budget"
