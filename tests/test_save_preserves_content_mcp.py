"""כלי הכתיבה של ה-MCP שומרים בדיוק את מה שנשלח.

**דרך הממשק שהסוכן מפעיל:** ``mcp.call_tool`` על שרת MCP אמיתי (``build_mcp``),
מעל ``ProductionBackend``, ``DatabaseManager`` ו-``Repository`` אמיתיים. רק
האוספים הם הדמה המשותפת (``tests/_fake_mongo.py``). מה שנשמר נקרא ישירות
מהאוסף, לא מתשובת הכלי.

**בתצורת הייצור, ולא של הטסטים:** ``config.py`` של השורש, ולא ``tests/config.py``
— למה זה קובע, ב-docstring של ``tests/_save_layer_harness.py``.

**הרשאת הכתיבה עוברת בשער האמיתי:** ``require_write`` לא מוחלף. הטוקן שמוחזר
מ-``get_access_token`` נושא ``write``, כמו ב-``tests/test_mcp_require_write.py``.

תווי כיווניות ורוחב-אפס כתובים רק כ-escapes (H1: תו כזה בקובץ מקור מפיל את
bandit ב-B613).
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _save_layer_harness import clear_local_cache, install_fake_collections, latest, load_production_config

pytest.importorskip("mcp")

USER = 5151

RLM, ALM, ZWJ = "\u200f", "\u061c", "\u200d"
FAMILY = "\U0001F468" + ZWJ + "\U0001F469" + ZWJ + "\U0001F467"

# (שם הקובץ, התוכן). כל אחד מהם שונה בשמירה של היום — ראו את ה-docstring.
CASES = {
    "rlm_mid_line": ("notes.md", "גרסה" + RLM + " 2.0 יצאה\n"),
    "rlm_line_start": ("notes.md", "שורה ראשונה\n" + RLM + "(1) פריט\n"),
    "alm": ("arabic.md", "العربية" + ALM + " 123\n"),
    "escape_in_python_string": ("marks.py", 'RLM = "\\u200f"\nprint(len(RLM))\n'),
    "regex_escape_range": ("guard.py", 'HIDDEN = re.compile(r"[\\u200b-\\u200f\\u202a-\\u202e]")\n'),
    "one_trailing_newline": ("one.py", "x = 1\n"),
    "three_trailing_newlines": ("three.py", "x = 1\n\n\n"),
    "md_hard_break": ("poem.md", "שורה עם שבירה  \nהשורה הבאה\n"),
    "family_emoji": ("emoji.py", "print('" + FAMILY + "')\n"),
    "crlf_kept": ("windows.txt", "line one\r\nline two\r\n"),
}


@pytest.fixture
def store(monkeypatch):
    load_production_config(monkeypatch)
    yield install_fake_collections(monkeypatch)
    clear_local_cache()


@pytest.fixture
def mcp(monkeypatch, store):
    import mcp.server.auth.middleware.auth_context as auth_context

    import mcp_server.server as srv
    from mcp_server.backend import ProductionBackend

    # ``build_mcp`` קורא ל-``instrument_mcp_server``, שזורק מחוץ לפרודקשן בלי
    # PostHog — אותו קיבוע כמו ב-``tests/test_mcp_file_query.py::_build``.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: USER)
    monkeypatch.setattr(auth_context, "get_access_token", lambda: SimpleNamespace(scopes=["read", "write"]))
    return srv.build_mcp(ProductionBackend(db_manager=store.dbm, mongo_db=store.raw))


def _call(mcp, tool: str, **args) -> dict:
    """``FastMCP.call_tool(name, arguments)`` — mcp 1.28.1, ``mcp/server/fastmcp/server.py``.

    מחזיר רשימת בלוקי תוכן; ההסתעפות על ``tuple`` היא לגרסאות שמחזירות
    ``(content, structured)``, כמו ב-``tests/test_mcp_file_query.py::_payload``.
    """
    result = asyncio.run(mcp.call_tool(tool, args))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def _stored(store, file_name: str) -> dict:
    return latest(store.code_snippets, USER, file_name)


@pytest.mark.parametrize("case", sorted(CASES))
def test_save_file_stores_exactly_what_was_sent(mcp, store, case):
    file_name, sent = CASES[case]
    res = _call(mcp, "codekeeper_save_file", file_name=file_name, code=sent)
    assert res.get("ok") is True, res
    assert _stored(store, file_name)["code"] == sent


@pytest.mark.parametrize("case", sorted(CASES))
def test_append_file_keeps_both_the_existing_body_and_the_appended_text(mcp, store, case):
    file_name, sent = CASES[case]
    base = "base " + RLM + "line\n"
    assert _call(mcp, "codekeeper_save_file", file_name=file_name, code=base).get("ok") is True
    res = _call(mcp, "codekeeper_append_file", file_name=file_name, content=sent)
    assert res.get("ok") is True, res
    # ``base`` נגמר ב-newline, ולכן ``append_file`` לא מוסיף מפריד.
    assert _stored(store, file_name)["code"] == base + sent


def test_edit_file_changes_only_the_replaced_word(mcp, store):
    """עריכה של מילה בשורה 1 לא נוגעת בשורה 3, שיש בה RLM וסוף שורה של Windows."""
    original = "title: draft\nplain line\nגרסה" + RLM + " 2.0  \r\n\n"
    assert _call(mcp, "codekeeper_save_file", file_name="edit.md", code=original).get("ok") is True
    res = _call(mcp, "codekeeper_edit_file", file_name="edit.md", old_string="draft", new_string="final")
    assert res.get("ok") is True, res
    assert _stored(store, "edit.md")["code"] == original.replace("draft", "final")


def test_edit_file_finds_an_old_string_that_contains_rlm(mcp, store):
    """עד היום ה-RLM נמחק בשמירה, ו-``old_string`` שהכיל אותו החזיר ``no_match``."""
    original = "שם" + RLM + ": ערך\n"
    assert _call(mcp, "codekeeper_save_file", file_name="rlm.md", code=original).get("ok") is True
    res = _call(mcp, "codekeeper_edit_file", file_name="rlm.md", old_string="שם" + RLM + ":", new_string="שם חדש:")
    assert res.get("ok") is True, res
    assert _stored(store, "rlm.md")["code"] == "שם חדש: ערך\n"
