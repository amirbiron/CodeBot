"""מחרוזת שנשלחת לכלי מגיעה אליו כמחרוזת — גם כשהיא נראית כמו JSON (#3471).

לפני הוולידציה ה-SDK מריץ ``FuncMetadata.pre_parse_json``: על כל ארגומנט שהוא
מחרוזת, ושה-annotation של השדה שלו אינו ``str`` **בדיוק**, הוא מנסה
``json.loads``. בפרמטר ``str | None`` זה היה הבאג: ``"null"`` נהיה ``None``,
כלומר "לא נשלח", ו-``query="null"`` החזיר את הקובץ המלא; ``"[1, 2]"`` ו-
``'{"a": 1}'`` נהיו רשימה ומילון ונדחו כ"לא מחרוזת". התיקון יושב ב-
``AdminAwareFastMCP.add_tool`` (``mcp_server/server.py``, ``_RawStringMetadata``).

**כל טסט כאן עובר דרך ``call_tool``** — ההמרה קורית לפני שגוף הכלי רץ, ולכן
טסט מול הפונקציה ישירות אינו מסוגל ליפול עליה.

שש קבוצות:

1. **כל פרמטר מחרוזת בכל כלי רשום** מקבל את שלושת הערכים כמו שנשלחו. הרשימה
   נגזרת מהסכימה שהשרת מצהיר ללקוח — קוד של pydantic, בנפרד מהכלל שנבדק —
   ולא מרשימת האישו; רשימת האישו רק נבדקת שהיא מוכלת במה שכוסה.
2. **בקרה שלילית** — פרמטר שאינו מקבל ``str`` ממשיך לקבל JSON כמחרוזת, כי זה
   מה ש-Claude Desktop שולח. תיקון שמבטל את הפענוח גורף עובר את קבוצה 1 ונופל כאן.
3. **קצה לקצה**, עם גוף הכלי האמיתי: ``query="null"``, כותרת ששמה ``null``, קובץ
   ששמו ``null``, ``codekeeper_docs_get_section``, ופתק שנכתב בו ``null`` — עם
   קריאה חוזרת של מה שנכתב.
4. **PostHog דלוק** — ה-session האמיתי והסכימות של הייצור, עם ``context`` מוזרק.
5. **הכלל ברישום** — כל צורת annotation מקבלת הכרעה מפורשת, וצורה שאין לה הכרעה
   נכונה (``str | list[str]``, ``Any``, צורה לא מוכרת) מפילה את הרישום.
6. **ה-SDK** — הגרסה הנעוצה היא המותקנת, התפר שהתיקון נשען עליו עדיין נקרא, וה-SDK
   לבדו עדיין ממיר (אחרת התיקון מיותר, וזה צריך להיראות).

**ריצת בקרה.** על הקוד שלפני התיקון (``5d7fdc2``) נופלת כל בדיקה כאן, חוץ מאלה
שאמורות לעבור בשני המצבים: הבקרה השלילית, ``str`` בדיוק (ה-SDK מדלג עליו גם
בלעדינו), שני שומרי ה-SDK — הגרסה הנעוצה, וה-SDK לבדו שעדיין ממיר — והבדיקה שרשימת
האישו מוכלת, שהיא חסם על הכיסוי ולא על התיקון. כל מוטציה שמבטלת חלק מהכלל הורצה
על עותק (``git worktree``) והפילה בדיקה כאן; הרשימה והפלטים בגוף ה-PR.
"""

import functools
import importlib.metadata
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, Literal, Optional

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp import Context, FastMCP  # noqa: E402
from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import mcp_server.server as srv  # noqa: E402
from mcp_server import analytics  # noqa: E402
from mcp_server.backend import ProductionBackend  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
USER = 7
DOC = "doc.md"
NOTE_ID = "a" * 24

#: שלושת הצורות שה-SDK מחליף: ``None``, רשימה ומילון. ``"true"`` ו-``"123"``
#: אינם כאן בכוונה — ה-SDK משאיר אותם כמחרוזת גם בלי התיקון (נמדד), ולכן טסט
#: עליהם לא היה מסוגל ליפול.
JSON_LOOKING = ["null", "[1, 2]", '{"a": 1}']

#: הרשימה מאישו #3471 — 28 פרמטרים של "מחרוזת או ``null``" ב-13 כלים, כפי שנספרו
#: על ``c11d428``. הטסט אינו סופר אותם: הוא עובר על הכלים הרשומים, ובודק רק
#: שהרשימה הזו מוכלת במה שכוסה.
ISSUE_3471 = frozenset(
    {
        "codekeeper_add_to_collection.folder",
        "codekeeper_add_to_collection.note",
        "codekeeper_create_board_note.color",
        "codekeeper_create_board_note.mode",
        "codekeeper_create_board_note.title",
        "codekeeper_create_note.anchor_text",
        "codekeeper_create_note.color",
        "codekeeper_create_repo_note.color",
        "codekeeper_create_repo_note.mode",
        "codekeeper_create_repo_note.title",
        "codekeeper_docs_get_section.ref",
        "codekeeper_docs_get_section.repo",
        "codekeeper_docs_get_section.section",
        "codekeeper_get_collection_items.folder",
        "codekeeper_get_file.file_id",
        "codekeeper_get_file.file_name",
        "codekeeper_get_file.query",
        "codekeeper_get_file.section",
        "codekeeper_get_repo_file.ref",
        "codekeeper_get_repo_file.symbol",
        "codekeeper_list_repo_tree.path",
        "codekeeper_list_repo_tree.ref",
        "codekeeper_save_file.language",
        "codekeeper_search_code.language",
        "codekeeper_search_repo.file_pattern",
        "codekeeper_update_note.anchor_text",
        "codekeeper_update_note.color",
        "codekeeper_update_note.content",
    }
)

#: קובץ Markdown שמור: כותרת ששמה ``null``, ושורה שמחזיקה את שלוש המחרוזות —
#: כדי שחיפוש מילולי שלהן ימצא משהו, ולא רק "לא ייכשל".
MD = '# מסמך\n\nפתיחה.\n\n## null\n\nהערך null ברשימה [1, 2] ובאובייקט {"a": 1}.\n'

#: עמוד RST עם כותרת ששמה ``null``, בשביל ``codekeeper_docs_get_section``.
RST = "מסמך\n====\n\nפתיחה.\n\nnull\n----\n\nגוף הסעיף.\n"


# ---------------------------------------------------------------------------
# עזרים
# ---------------------------------------------------------------------------


class _Dbm:
    """דמה של שכבת ה-DB מתחת ל-``ProductionBackend``: קובץ ``doc.md``, וקובץ
    נוסף ששמו ``null`` — כדי ש-``file_name="null"`` יוכל להימצא.

    ``get_latest_version_fresh`` ולא ``get_latest_version``: זה המסלול ש-
    ``_latest_fresh`` בוחר כשהוא קיים, והוא שרץ בפרודקשן.
    """

    def _doc(self, name: str) -> dict:
        return {
            "_id": "id-" + name,
            "user_id": USER,
            "file_name": name,
            "version": 1,
            "code": MD,
            "programming_language": "markdown",
            "is_active": True,
        }

    def get_latest_version_fresh(self, user_id, file_name):
        return self._doc(file_name) if file_name in (DOC, "null") else None

    def get_file_by_id(self, file_id):
        return None

    def get_version(self, user_id, file_name, version):
        return None


class _TextRepoBackend:
    """מחקה ``RepoBackend.get_file`` ומחזיר את ``RST`` לכל נתיב."""

    def get_file(self, *, repo, path, ref=None, lines=None):
        return {
            "ok": True,
            "status": "ok",
            "file": {"path": path, "ref": "HEAD", "resolved_commit": "c0ffee"},
            "content": RST,
        }


class _NotesBackend:
    """``update_note`` בלבד: שומר את השדות שהגיעו לשכבת הכתיבה.

    ``notes`` הוא המצב שהטסט קורא **אחרי** הכתיבה — ולא התשובה של הכלי, שמעידה
    רק שהבקשה התקבלה.
    """

    def __init__(self):
        self.notes: dict[str, dict] = {}

    def update_note(self, user_id, *, note_id, fields):
        self.notes.setdefault(note_id, {}).update(fields)
        return {"ok": True, "note": {"id": note_id}}


class _NoBody:
    """backend שאף גוף כלי לא מגיע אליו — הגופים מוחלפים במרגל."""

    def __getattr__(self, _name):
        raise AssertionError("a tool body ran although it was replaced by the spy")


def _build(monkeypatch, backend, *, repo_backend=None, rate_limit_per_minute=None):
    """שרת MCP אמיתי (``build_mcp``) עם כל הכלים שלו.

    ``ENVIRONMENT=production``: ``build_mcp`` קורא ל-``instrument_mcp_server``,
    שזורק מחוץ לפרודקשן כשאין קונפיגורציית PostHog — הקיבוע כדי שהטסט לא יעבור
    או ייפול לפי הסביבה של מי שהריץ אותו.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: USER)
    kwargs = {}
    if rate_limit_per_minute is not None:
        kwargs["rate_limit_per_minute"] = rate_limit_per_minute
    mcp = srv.build_mcp(backend, repo_backend=repo_backend, **kwargs)
    monkeypatch.setattr(mcp, "_request_is_admin", lambda: True)
    return mcp


def _payload(result) -> dict:
    """התשובה כפי שהלקוח מקבל אותה: בלוק הטקסט של ``call_tool``, מפוענח."""
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def _spy_on_bodies(mcp) -> dict[str, dict]:
    """מחליף את גוף כל כלי במרגל, ומחזיר מה כל כלי קיבל.

    המרגל יושב **במקום הגוף** — אחרי ``pre_parse_json``, אחרי הוולידציה, בנקודה
    שבה הכלי מקבל את הארגומנטים שלו. ``functools.wraps`` שומר את החתימה, ולכן
    גם PostHog, שמחליט אם להסיר את ``context`` לפי החתימה, רואה בדיוק מה שהוא
    רואה בייצור.
    """
    received: dict[str, dict] = {}
    for tool in mcp._tool_manager.list_tools():

        @functools.wraps(tool.fn)
        async def spy(*_args, _tool=tool.name, **kwargs):
            received[_tool] = kwargs
            return {}

        tool.fn = spy
    return received


def _kinds(schema: dict) -> list:
    """הטיפוסים שהסכימה של פרמטר מקבלת — ישירות או מתוך ``anyOf``."""
    return [alt.get("type") for alt in schema.get("anyOf", [schema])]


def _string_params(parameters: dict) -> list[str]:
    """הפרמטרים שהסכימה המוצהרת מקבלת בהם מחרוזת.

    **נגזר מהסכימה ולא מה-annotation.** את הסכימה בונה pydantic מה-annotation,
    בקוד שלו; הכלל שנבדק קורא את ה-annotation בקוד שלנו. כך הרשימה אינה נגזרת
    מאותו מקור שהיא בודקת, וטעות בכלל לא הייתה משתקפת גם ברשימה.
    """
    return [name for name, schema in parameters["properties"].items() if "string" in _kinds(schema)]


def _filler(schema: dict):
    """ערך תקין לפרמטר חובה שאינו הנבדק. טיפוס שאין לו כאן ערך נופל בקול."""
    values = {"string": "x", "integer": 1, "boolean": False, "array": []}
    return values[_kinds(schema)[0]]


def _string_parameters_of(mcp) -> list[tuple[str, str]]:
    return [
        (tool.name, param)
        for tool in sorted(mcp._tool_manager.list_tools(), key=lambda t: t.name)
        for param in _string_params(tool.parameters)
    ]


def _arguments(parameters: dict, param: str, value: str) -> dict:
    required = [name for name in parameters.get("required", []) if name != param]
    args = {name: _filler(parameters["properties"][name]) for name in required}
    args[param] = value
    return args


# ===========================================================================
# 1. כל פרמטר מחרוזת בכל כלי רשום
# ===========================================================================


@pytest.mark.parametrize("value", JSON_LOOKING)
async def test_every_string_parameter_of_every_tool_receives_what_was_sent(monkeypatch, value):
    """לכל כלי רשום ולכל פרמטר שמקבל מחרוזת: הכלי מקבל את המחרוזת כמו שנשלחה.

    עובר על הכלים הרשומים ולא על רשימה, ולכן פרמטר שיתווסף מחר נבדק מאליו.
    כל הכשלים נאספים לפני ה-assert, כדי שההודעה תראה את כל ההיקף ולא את הראשון.
    """
    mcp = _build(monkeypatch, _NoBody(), repo_backend=_NoBody())
    received = _spy_on_bodies(mcp)
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}

    wrong = []
    for name, param in _string_parameters_of(mcp):
        received.pop(name, None)
        try:
            await mcp.call_tool(name, _arguments(tools[name].parameters, param, value))
        except ToolError as exc:
            # כך ה-SDK מדווח על ולידציה שנכשלה — ``"[1, 2]"`` שנהיה רשימה. נאסף
            # ומדווח ב-assert למטה; חריגה מכל סוג אחר היא באג בטסט, ועולה.
            wrong.append(f"{name}.{param}: {str(exc)[:80]}")
            continue
        got = received[name].get(param)
        if type(got) is not str or got != value:
            wrong.append(f"{name}.{param}: sent {value!r}, the tool received {got!r}")

    assert wrong == [], "\n".join(wrong)


def test_the_parameters_listed_in_the_issue_are_among_those_covered(monkeypatch):
    """כל הפרמטרים שברשימת האישו (``ISSUE_3471``) נמצאים בין אלה שהטסט למעלה עובר עליהם.

    **חסם ולא ספירה.** פרמטר מחרוזת שיתווסף לא ישבור את זה; פרמטר מהרשימה
    ששמו ישתנה או שיימחק — כן, ואז ברור מה קרה.
    """
    mcp = _build(monkeypatch, _NoBody(), repo_backend=_NoBody())
    covered = {f"{name}.{param}" for name, param in _string_parameters_of(mcp)}

    assert ISSUE_3471 <= covered, sorted(ISSUE_3471 - covered)


# ===========================================================================
# 2. בקרה שלילית — מה שחייב להמשיך לעבוד
# ===========================================================================


async def test_a_list_sent_as_json_text_is_still_a_list_where_no_str_is_accepted(monkeypatch):
    """ה-SDK מפענח כי Claude Desktop שולח רשימות ומילונים כמחרוזות JSON.

    ``lines`` (``StrictLines | None``) ו-``items`` (``list[Any]``) אינם מקבלים
    ``str``, ולכן הפענוח שלהם נשאר. תיקון שמדלג על הפענוח לכל הפרמטרים היה עובר
    את כל קבוצה 1 — וכאן ``lines`` היה מגיע כמחרוזת ונדחה בוולידציה.
    """
    mcp = _build(monkeypatch, _NoBody(), repo_backend=_NoBody())
    received = _spy_on_bodies(mcp)
    items = [{"kind": "section", "path": "mcp-server"}, {"kind": "file", "repo": "r", "path": "p"}]

    await mcp.call_tool("codekeeper_get_file", {"file_name": DOC, "lines": "[5, 10]"})
    await mcp.call_tool("codekeeper_get_repo_file", {"repo": "r", "path": "p", "lines": "[5, 10]"})
    await mcp.call_tool("codekeeper_read_batch", {"items": json.dumps(items)})

    assert received["codekeeper_get_file"]["lines"] == [5, 10]
    assert received["codekeeper_get_repo_file"]["lines"] == [5, 10]
    assert received["codekeeper_read_batch"]["items"] == items


# ===========================================================================
# 3. קצה לקצה, עם גוף הכלי האמיתי
# ===========================================================================


async def test_query_null_searches_for_null_and_does_not_return_the_file(monkeypatch):
    """התרחיש מהאישו: ``query="null"`` החזיר את הקובץ המלא, בלי שום סימן."""
    mcp = _build(monkeypatch, ProductionBackend(db_manager=_Dbm()))

    out = _payload(await mcp.call_tool("codekeeper_get_file", {"file_name": DOC, "query": "null"}))

    assert out.get("status") == "query", out
    assert [hit["line"] for hit in out["results"]] == [5, 7]
    assert "code" not in out["file"]


@pytest.mark.parametrize("text", ["[1, 2]", '{"a": 1}'])
async def test_a_query_that_looks_like_json_is_a_literal_search(monkeypatch, text):
    """מערך או אובייקט JSON ב-``query`` נדחו בוולידציה כ"לא מחרוזת"."""
    mcp = _build(monkeypatch, ProductionBackend(db_manager=_Dbm()))

    out = _payload(await mcp.call_tool("codekeeper_get_file", {"file_name": DOC, "query": text}))

    assert out.get("status") == "query", out
    assert [hit["line"] for hit in out["results"]] == [7]


async def test_a_heading_named_null_is_read_by_its_name(monkeypatch):
    """``section="null"`` החזיר את הקובץ המלא; עכשיו הוא הסעיף ששמו ``null``."""
    mcp = _build(monkeypatch, ProductionBackend(db_manager=_Dbm()))

    args = {"file_name": DOC, "section": "null"}
    out = _payload(await mcp.call_tool("codekeeper_get_file", args))

    assert out.get("status") == "section", out
    assert out["section"] == "null"
    assert out["content"].startswith("## null\n")


async def test_a_file_named_null_is_read_by_its_name(monkeypatch):
    """``file_name="null"`` נהיה "לא נשלח", והתשובה הייתה ``{"found": false}``."""
    mcp = _build(monkeypatch, ProductionBackend(db_manager=_Dbm()))

    out = _payload(await mcp.call_tool("codekeeper_get_file", {"file_name": "null"}))

    assert out["found"] is True, out
    assert out["file"]["file_name"] == "null"


async def test_docs_section_null_is_the_section_and_not_the_map(monkeypatch):
    """``codekeeper_docs_get_section`` החזיר את עץ הכותרות, כאילו לא ביקשו סעיף."""
    mcp = _build(monkeypatch, _NoBody(), repo_backend=_TextRepoBackend())

    out = _payload(
        await mcp.call_tool("codekeeper_docs_get_section", {"path": "page.rst", "section": "null"})
    )

    assert out.get("mode") == "section", out
    assert out["section"] == "null"


async def test_a_note_body_of_null_is_written_as_the_word(monkeypatch):
    """כלי כתיבה, שהאישו לא מדד: ``content="null"`` הגיע כ-``None``.

    ``None`` ב-``update_note`` פירושו "אל תשנה את הגוף" — ובקריאה שאין בה שדה
    אחר התשובה הייתה ``no_fields_to_update``. הבדיקה קוראת את מה שהגיע לשכבת
    הכתיבה, ולא את התשובה של הכלי.
    """
    import mcp.server.auth.middleware.auth_context as auth_context

    token = SimpleNamespace(scopes=["read", "write"])
    monkeypatch.setattr(auth_context, "get_access_token", lambda: token)
    notes = _NotesBackend()
    mcp = _build(monkeypatch, notes)

    args = {"note_id": NOTE_ID, "content": "null"}
    out = _payload(await mcp.call_tool("codekeeper_update_note", args))

    assert out["ok"] is True, out
    assert notes.notes[NOTE_ID]["content"] == "null"


# ===========================================================================
# 4. PostHog דלוק — הסכימות של הייצור
# ===========================================================================


async def test_with_posthog_on_every_string_still_arrives_as_sent(monkeypatch):
    """אותה בדיקה כמו בקבוצה 1, בתצורה שהייצור רץ בה.

    בלי קונפיגורציית PostHog האינסטרומנטציה אינה רצה, והסכימות בטסטים אינן
    הסכימות של הייצור: שם כל כלי מקבל פרמטר ``context`` מסוג מחרוזת, ו-PostHog
    עוטף את ``ToolManager.call_tool`` ומסיר אותו לפני הכלי. כאן היא דלוקה, עם
    לקוח ``Posthog`` אמיתי (``send=False`` — שום דבר לא יוצא לרשת), וכל קריאה
    עוברת ב-session אמיתי של הפרוטוקול. ``rate_limit_per_minute=0`` מכבה את
    המגביל במפורש: ב-session יש זהות, ומאות קריאות בשנייה היו נחסמות.
    """
    from mcp.shared.memory import create_connected_server_and_client_session
    from posthog import Posthog

    client = Posthog(
        "phc_test_token_not_real",
        host="https://us.i.posthog.com",
        send=False,
        before_send=analytics.scrub_mcp_payload,
        enable_exception_autocapture=False,
        capture_exception_code_variables=False,
    )
    monkeypatch.setattr(analytics, "_CLIENT", client)
    monkeypatch.setattr(analytics, "_ANALYTICS", None)
    mcp = _build(monkeypatch, _NoBody(), repo_backend=_NoBody(), rate_limit_per_minute=0)
    received = _spy_on_bodies(mcp)
    intent = "checking that a text argument reaches the tool unchanged"

    wrong = []
    try:
        async with create_connected_server_and_client_session(mcp._mcp_server) as session:
            listed = {tool.name: tool.inputSchema for tool in (await session.list_tools()).tools}
            # ההוכחה שהאינסטרומנטציה באמת דלוקה: ``context`` בכל סכימה, כחובה.
            # ``get_more_tools`` הוא הכלי הווירטואלי של ``report_missing``.
            registered = {tool.name for tool in mcp._tool_manager.list_tools()}
            assert registered <= set(listed)
            for name in registered:
                assert "context" in listed[name]["properties"], name
                assert "context" in listed[name].get("required", []), name

            for name in sorted(registered):
                for param in _string_params(listed[name]):
                    if param == "context":
                        continue
                    for value in JSON_LOOKING:
                        args = _arguments(listed[name], param, value)
                        args["context"] = intent
                        received.pop(name, None)
                        result = await session.call_tool(name, args)
                        if result.isError:
                            wrong.append(f"{name}.{param}: {result.content[0].text[:80]}")
                            continue
                        got = received[name].get(param)
                        if type(got) is not str or got != value:
                            wrong.append(f"{name}.{param}: sent {value!r}, received {got!r}")
                        if "context" in received[name]:
                            wrong.append(f"{name}: the injected context reached the tool")

            # והבקרה השלילית באותה תצורה.
            result = await session.call_tool(
                "codekeeper_get_file", {"file_name": DOC, "lines": "[5, 10]", "context": intent}
            )
            assert not result.isError, result.content
            assert received["codekeeper_get_file"]["lines"] == [5, 10]
        await analytics._drain()
    finally:
        client.shutdown()

    assert wrong == [], "\n".join(wrong)


# ===========================================================================
# 5. הכלל ברישום
# ===========================================================================


class _Model(BaseModel):
    a: int = 0


def _probe(annotation, default=None):
    """כלי דמה שמחזיר את מה שקיבל ואת הטיפוס שלו."""

    def probe(ctx: Context, x=default) -> dict:
        return {"type": type(x).__name__, "value": x}

    probe.__annotations__["x"] = annotation
    return probe


def _register(annotation, default=None) -> srv.AdminAwareFastMCP:
    mcp = srv.AdminAwareFastMCP("t")
    mcp.add_tool(_probe(annotation, default), name="probe", annotations={"readOnlyHint": True})
    return mcp


async def _send(mcp, value) -> dict:
    return _payload(await mcp.call_tool("probe", {"x": value}))


_BESIDE = "str beside"
_ANYTHING = "takes a string and everything"
_UNKNOWN = "is not a shape this rule decides"


@pytest.mark.parametrize(
    "annotation, reason",
    [
        (str | list[str], _BESIDE),
        (str | dict[str, int], _BESIDE),
        (str | tuple[int, int], _BESIDE),
        (str | set[str], _BESIDE),
        (str | _Model | None, _BESIDE),
        (Any, _ANYTHING),
        (str | Any, _ANYTHING),
        (object, _ANYTHING),
        (Literal["a", "b"], _UNKNOWN),
        # ``Optional`` ולא ``| None`` בכוונה — הכתיב של ``typing.Union``.
        (Optional[Literal["null"]], _UNKNOWN),  # noqa: UP045
    ],
    ids=repr,
)
def test_a_shape_without_a_right_answer_fails_the_registration(annotation, reason):
    """``str`` ליד משהו שהפענוח מייצר, ``Any``, וצורה שהכלל לא מכיר — ``TypeError``.

    ``str | list[str]`` הוא המקרה מהתוכנית: דילוג שובר רשימה שנשלחה כמחרוזת
    JSON, ופענוח מחזיר את #3471. ``Literal`` אינו שם — הוא צורה שהכלל אינו
    מכריע עליה, ולכן הוא מסרב ולא מנחש. **הסיבה נבדקת לכל צורה**, כי שלוש
    הסיבות הן שלוש הכרעות נפרדות: ``Any`` היה נדחה גם כ"צורה לא מוכרת", ובלי
    הבדיקה על הסיבה מחיקת ההכרעה המפורשת עליו לא הייתה מפילה כלום. והכלי **אינו
    רשום** אחרי הסירוב, בדיוק כמו כלי כתיבה אסינכרוני ב-``_offload_to_thread``.
    """
    mcp = srv.AdminAwareFastMCP("t")

    with pytest.raises(TypeError) as refused:
        mcp.add_tool(_probe(annotation), name="probe", annotations={"readOnlyHint": True})

    message = str(refused.value)
    assert message.startswith("'probe': "), message
    assert f"x: {annotation!r} (" in message, message
    assert reason in message, message
    assert "#3471" in message
    assert mcp._tool_manager.get_tool("probe") is None


@pytest.mark.parametrize(
    "annotation",
    [
        str,
        str | None,
        # שני הכתיבים של איחוד הם שני טיפוסים שונים בזמן ריצה (``typing.Union``
        # מול ``types.UnionType``), ו-``Optional`` הוא הראשון — לכן לא ``| None``.
        Optional[str],  # noqa: UP045
        str | int | None,
        str | float,
        str | bool,
        Annotated[str | None, Field(description="text")],
    ],
    ids=repr,
)
@pytest.mark.parametrize("value", JSON_LOOKING)
async def test_text_with_scalars_beside_it_reaches_the_tool_as_sent(annotation, value):
    """``str`` לבד, או ליד ``None``/``int``/``float``/``bool`` — מדלגים על הפענוח.

    ליד מספר או בוליאני אין מה לאבד: פענוח שמחזיר אחד מהם הוא בדיוק המקרה שה-SDK
    זורק בעצמו. ``Annotated`` מקולף — כך מוצהרים ``query`` ו-``section``.
    """
    mcp = _register(annotation)

    out = await _send(mcp, value)

    assert out == {"type": "str", "value": value}


@pytest.mark.parametrize(
    "annotation, sent, expected",
    [
        (list[int] | None, "[1, 2]", [1, 2]),
        (list[int], "[1, 2]", [1, 2]),
        (dict[str, int] | None, '{"a": 1}', {"a": 1}),
        (_Model | None, '{"a": 1}', {"a": 1}),
        (int | None, "null", None),
    ],
    ids=repr,
)
async def test_without_str_the_sdk_still_parses(annotation, sent, expected):
    """בלי ``str`` באיחוד — הפענוח של ה-SDK נשאר, כמו שהיה."""
    mcp = _register(annotation)

    out = await _send(mcp, sent)

    assert out["value"] == expected


async def test_a_parameter_the_sdk_renames_keeps_its_string_too():
    """פרמטר שמצל על מתודה של ``BaseModel`` מקבל alias מה-SDK.

    ``json`` נהיה השדה ``field_json`` עם alias ``json``, והלקוח שולח ``json``.
    ``pre_parse_json`` ממפה את שני השמות, ולכן גם הכלל חייב — אחרת הפרמטר הזה
    היה נשאר עם הבאג בשקט.
    """

    def probe(ctx: Context, json: str | None = None) -> dict:
        return {"type": type(json).__name__, "value": json}

    mcp = srv.AdminAwareFastMCP("t")
    mcp.add_tool(probe, name="probe", annotations={"readOnlyHint": True})
    fields = mcp._tool_manager.get_tool("probe").fn_metadata.arg_model.model_fields
    assert fields["field_json"].alias == "json"  # התנאי שהבדיקה נשענת עליו

    out = _payload(await mcp.call_tool("probe", {"json": "null"}))

    assert out == {"type": "str", "value": "null"}


def test_metadata_the_sdk_builds_differently_fails_the_registration(monkeypatch):
    """ה-SDK התחיל לבנות מטא-דאטה ממחלקה אחרת — הרישום נופל, ולא מעתיק בשקט.

    ההחלפה מעתיקה את השדות של ``FuncMetadata`` לתת-מחלקה שלה. מחלקה שה-SDK
    יוסיף הייתה מאבדת בהעתקה את מה שהיא מוסיפה, בלי שום סימן.
    """
    import mcp.server.fastmcp.tools.base as tools_base

    class _NewerMetadata(tools_base.FuncMetadata):
        pass

    original = tools_base.func_metadata
    fields = tools_base.FuncMetadata.model_fields

    def newer(*args, **kwargs):
        built = original(*args, **kwargs)
        return _NewerMetadata(**{name: getattr(built, name) for name in fields})

    monkeypatch.setattr(tools_base, "func_metadata", newer)
    mcp = srv.AdminAwareFastMCP("t")

    with pytest.raises(TypeError, match="_NewerMetadata"):
        mcp.add_tool(_probe(str | None), name="probe", annotations={"readOnlyHint": True})

    assert mcp._tool_manager.get_tool("probe") is None


# ===========================================================================
# 6. ה-SDK
# ===========================================================================


def test_the_pinned_sdk_is_the_one_installed():
    """התיקון נשען על ``FuncMetadata.pre_parse_json`` כפי שהוא ב-``mcp 1.28.1``.

    טסט שרץ על גרסה אחרת מזו שבייצור בודק תצורה שאף אחד לא מריץ. הנעיצה נקראת
    מ-``requirements/base.txt``, שממנו גם ה-Dockerfile וגם ה-CI מתקינים.
    """
    base = (ROOT / "requirements" / "base.txt").read_text(encoding="utf-8")
    pinned = re.search(r"^mcp==(\S+)$", base, re.MULTILINE)

    assert pinned, "mcp אינו נעוץ ישירות ב-requirements/base.txt"
    assert pinned.group(1) == importlib.metadata.version("mcp")


async def test_the_sdk_still_calls_the_pre_parse_on_the_metadata_object(monkeypatch):
    """התפר: ה-SDK קורא ל-``self.pre_parse_json`` בכל קריאת כלי.

    אם גרסה עתידית תזיז את הפענוח למקום אחר, ההחלפה של המטא-דאטה לא תיקרא —
    והבאג יחזור בלי שגיאה. כאן זה נופל: הקריאה נספרת.
    """
    calls = []
    original = srv._RawStringMetadata.pre_parse_json

    def counting(self, data):
        calls.append(dict(data))
        return original(self, data)

    monkeypatch.setattr(srv._RawStringMetadata, "pre_parse_json", counting)
    mcp = _register(str | None)

    out = await _send(mcp, "null")

    assert calls == [{"x": "null"}]
    assert out == {"type": "str", "value": "null"}


def test_every_registered_tool_carries_the_string_preserving_metadata(monkeypatch):
    """אין מסלול רישום שעוקף את ``add_tool``.

    כלי שנרשם בדרך אחרת היה מקבל את המטא-דאטה של ה-SDK ואת הבאג. אותו עיקרון
    כמו ``test_every_registered_tool_is_a_coroutine_function``.
    """
    mcp = _build(monkeypatch, _NoBody(), repo_backend=_NoBody())
    tools = mcp._tool_manager.list_tools()

    assert tools
    assert [t.name for t in tools if type(t.fn_metadata) is not srv._RawStringMetadata] == []


async def test_the_sdk_alone_still_turns_null_into_none():
    """בקרה: בלי השכבה שלנו, ה-SDK עדיין ממיר — ולכן היא נחוצה.

    ``FastMCP`` הרגיל, לא ``AdminAwareFastMCP``. אם גרסה של ה-SDK תתקן את זה
    בעצמה, הטסט הזה ייפול — וזה הסימן לבדוק אם ``_RawStringMetadata`` עדיין
    נחוצה, ולעדכן את התיעוד שמתאר את ההמרה.
    """
    plain = FastMCP("plain")

    def probe(x: str | None = None) -> dict:
        return {"type": type(x).__name__, "value": x}

    plain.add_tool(probe, name="probe")

    out = _payload(await plain.call_tool("probe", {"x": "null"}))

    assert out == {"type": "NoneType", "value": None}
