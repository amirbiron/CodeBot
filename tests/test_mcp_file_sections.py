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
import json

import pytest

from mcp_server import analytics, docs_handlers, handlers
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
                 owner: int = _USER):
        self._code = code
        self._file_name = file_name
        self._language = language
        self._old_code = old_code
        self._owner = owner
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


def _meta(*, version: int = 2, doc_id: str = _DOC_ID, file_name: str = _MD_NAME,
          language: str | None = "markdown") -> dict:
    """המטא-דאטה שתשובה נושאת ב-``file``: המסמך בלי התוכן, עם הכינוי ``language``."""
    meta = {
        "id": doc_id,
        "user_id": _USER,
        "file_name": file_name,
        "version": version,
        "programming_language": language,
        "is_active": True,
    }
    meta["language"] = language
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


async def test_version_and_file_id_choose_the_version_the_section_is_read_from(monkeypatch):
    """הסעיף נקרא מהגרסה שנבחרה — ו-``file_id`` מתעלם מ-``version``, כמו בקריאה מלאה.

    מוטציה שמפילה: לבחור את המסמך ב-``_latest_fresh`` בלי קשר ל-``version``
    — הגרסה הישנה אינה נקראת.
    """
    mcp = _build(monkeypatch)
    old_k11 = "## K11. חריגה נבלעת\n\nגרסה ישנה.\n"

    old = await _call(mcp, file_name=_MD_NAME, version=1, section="K11")
    assert old["content"] == old_k11
    assert old["file"] == _meta(version=1, doc_id=_OLD_DOC_ID)

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
    mcp = _build(monkeypatch, _Dbm("x = 1\n# לא כותרת\n", file_name=file_name,
                                   language=language))
    expected = {"ok": False, "error": handlers.NOT_MARKDOWN,
                "file": _meta(file_name=file_name, language=language), "hint": _HINT}

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
        "file": _meta(),
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
        "file": _meta(),
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
        "file": _meta(),
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
        "file": _meta(),
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
        "file": _meta(),
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


def test_the_request_nets_refuse_what_the_schema_would_have_stopped():
    """רשת מאחורי הסכימה, לקורא שאינו עובר בה — ``handlers`` ו-backend באותה פונקציה.

    מוטציה שמפילה: להסיר את ``isinstance`` על ``toc`` — ``"false"`` (מחרוזת לא
    ריקה) נקרא כמצב המפה.
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


async def test_the_schema_rejects_a_toc_that_is_not_a_boolean(monkeypatch):
    """``StrictBool``: ``"true"``, ``"yes"`` ו-``1`` נדחים בגבול, ולא הופכים ל-``True`` בשקט.

    נמדד מול ``mcp 1.28.1`` ו-``pydantic 2.12.3``. ``ToolError`` ולא ``Exception``:
    מה שנבדק הוא ולידציית הסכימה, ו-``Exception`` היה עובר גם על כל תקלה אחרת.

    מוטציה שמפילה: ``toc: bool`` במקום ``StrictBool`` ב-``server.py``.
    """
    from mcp.server.fastmcp.exceptions import ToolError

    mcp = _build(monkeypatch)

    for bad in ("true", "yes", 1):
        with pytest.raises(ToolError, match="validation error"):
            await _call(mcp, file_name=_MD_NAME, toc=bad)
    for bad in (5, ["K11"]):
        with pytest.raises(ToolError, match="validation error"):
            await _call(mcp, file_name=_MD_NAME, section=bad)


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
    ],
)
def test_a_toc_or_section_read_is_labelled_by_its_mode_and_not_as_full(arguments, expected):
    """``toc`` נספר כ-``outline`` ו-``section`` כ-``section`` — ולעולם לא כ-``full``.

    מוטציה שמפילה: להסיר את ענף ה-``toc`` או ה-``section`` מ-``read_mode_properties``
    — הקריאה מסומנת ``full``, כלומר האירוע אומר "קובץ מלא" על קריאה שלא משכה אותו.
    """
    assert _read_mode(arguments) == {analytics.CK_READ_MODE_KEY: expected}


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

    וכלל ההתאמה בתיאור של ``section`` הוא **``_SECTION_PARAM_DOC`` כמו שהוא** —
    אותו טקסט של ``codekeeper_docs_get_section``, כי זו אותה פונקציה.

    מוטציה שמפילה: למחוק את משפט ההפניה מתיאור הכלי ב-``server.py``.
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
                   "too_large_for_sections", "ignores version"):
        assert marker in toc_doc, marker

    section_doc = props["section"]["description"]
    assert section_doc.startswith("Markdown files only")
    assert srv._SECTION_PARAM_DOC in section_doc
    for marker in ("section_and_query", "section_and_lines", "max_chars_without_section",
                   "offset_without_section", "empty_section", "next_offset",
                   "not_markdown", "too_large_for_sections", "too_many_tokens"):
        assert marker in section_doc, marker


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
