"""‏``content_sha256`` ו-``content_changed`` — רשת הביטחון על התוכן, דרך ממשק ה-MCP.

**הבדיקות עוברות דרך ``mcp.call_tool``** על שרת MCP אמיתי (``build_mcp``), מעל
``ProductionBackend``, ``DatabaseManager`` ו-``Repository`` אמיתיים, עם ``config.py``
של הייצור (``tests/_save_layer_harness.py``). רק האוספים מוחלפים בדמה המשותפת
(``tests/_fake_mongo.py``). זה המסלול שסוכן מפעיל, וזה מה שמודדים עליו.

**ה-hash בכל בדיקה כאן מחושב ביד** — ``hashlib`` על השדה כפי שנקרא **ישירות מהאוסף**
— ולא דרך הפונקציה של ``backend``. טסט שמשווה את הפונקציה לעצמה היה עובר גם על
hash שמחושב מהקלט, וזה בדיוק הכשל שהשדה בא לתפוס.

שש קבוצות:

1. **התאמה** — כל כלי כתיבה וכל מצב של ``get_file`` מחזירים את ה-hash של מה שבאוסף.
2. **הרשת תופסת (T2)** — שכבה שמשנה את התוכן בדרך לאוסף מדליקה ``content_changed``,
   עם סיכום מדויק, וה-hash הוא של מה שנשמר ולא של מה שנשלח.
3. **הקריאה החוזרת** — לפי ``_id`` ולא לפי שם, לא מהקאש, רק של המשתמש, מה-primary,
   ו-``null`` כשהיא נכשלת במסד (ורק אז).
4. **תוכן שאינו מחרוזת** נופל בקול בכל מצב קריאה ובעריכה ובהוספה.
5. **תקציב** — תשובות ``toc`` ו-``section`` שנוחתות ליד התקציב נשארות בתוכו עם השדה.
6. **שומרים** — מבני (AST) על בניית ``file`` ב-backend, והנוסחה שבתיאורי הכלים.

כל בדיקה הורצה על הקוד שלפני השינוי, וכל מוטציה שכתובה בגוף בדיקה הורצה על עותק
(``git worktree``) והפילה אותה. הפלטים בגוף ה-PR.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

# ‏``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _save_layer_harness import clear_local_cache, install_fake_collections, latest, load_production_config

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402

USER = 6262
NAME = "safety-net.md"
RLM = "‏"
ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# עזרים
# ---------------------------------------------------------------------------


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
    # PostHog — אותו קיבוע כמו ב-``tests/test_save_preserves_content_mcp.py``.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: USER)
    monkeypatch.setattr(auth_context, "get_access_token", lambda: SimpleNamespace(scopes=["read", "write"]))
    return srv.build_mcp(ProductionBackend(db_manager=store.dbm, mongo_db=store.raw))


def _call(mcp, tool: str, **args) -> dict:
    """התשובה כפי שהלקוח מקבל אותה: בלוק הטקסט של ``call_tool``, מפוענח."""
    result = asyncio.run(mcp.call_tool(tool, args))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def _call_sent(mcp, tool: str, **args) -> tuple[dict, int]:
    """התשובה **ומספר הבתים שלה כפי שה-SDK שלח אותה** — הטקסט עצמו, לא הערכה."""
    result = asyncio.run(mcp.call_tool(tool, args))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text), len(blocks[0].text.encode("utf-8"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stored_by_id(store, file_id: str) -> dict:
    """המסמך שהתשובה מצביעה עליו, ישירות מהאוסף — מקור האמת."""
    docs = [d for d in store.code_snippets.docs if str(d.get("_id")) == file_id]
    assert len(docs) == 1, f"אין באוסף מסמך אחד עם _id={file_id}: {len(docs)}"
    return docs[0]


def _seed(store, code, *, file_name=NAME, version=1, **extra) -> dict:
    """מסמך ישירות באוסף, בצורה שמסלול השמירה כותב — בשביל תוכן שאף כלי לא היה מקבל."""
    doc = {"user_id": USER, "file_name": file_name, "version": version, "is_active": True,
           "programming_language": "markdown", **extra}
    if code is not None:
        doc["code"] = code
    store.code_snippets.insert_one(doc)
    return doc


# ---------------------------------------------------------------------------
# 1. התאמה
# ---------------------------------------------------------------------------

#: תוכן שכל שכבה בדרך הייתה יכולה לשנות בשקט: תווי כיווניות, ירידות שורה בסוף,
#: CRLF, BOM, ותווים של ארבעה בתים (אימוג'י משפחה עם ZWJ).
CASES = {
    "rlm": "גרסה" + RLM + " 2.0 יצאה\n",
    "three_trailing_newlines": "x = 1\n\n\n",
    "no_trailing_newline": "x = 1",
    "crlf": "line one\r\nline two\r\n",
    "bom": "﻿# כותרת\n",
    "four_byte": "print('\U0001F468‍\U0001F469‍\U0001F467 \U00010348')\n",
}


@pytest.mark.parametrize("case", sorted(CASES))
@pytest.mark.parametrize("tool", ["codekeeper_save_file", "codekeeper_edit_file", "codekeeper_append_file"])
def test_every_write_tool_returns_the_hash_of_what_the_collection_holds(mcp, store, tool, case):
    """ה-hash בתשובת הכתיבה שווה ל-sha256 של ``code`` כפי שהוא יושב באוסף.

    לעריכה ולהוספה ה"כוונה" היא הקובץ שנבנה מהבסיס: אחרי ההחלפה, או הבסיס ועוד
    התוספת (הבסיס נגמר ב-``\\n``, ולכן בלי מפריד).
    """
    text = CASES[case]
    if tool == "codekeeper_save_file":
        intended = text
        res = _call(mcp, tool, file_name=NAME, code=text)
    elif tool == "codekeeper_edit_file":
        assert _call(mcp, "codekeeper_save_file", file_name=NAME, code="head\n" + text)["ok"] is True
        intended = "HEAD\n" + text
        res = _call(mcp, tool, file_name=NAME, old_string="head", new_string="HEAD")
    else:
        assert _call(mcp, "codekeeper_save_file", file_name=NAME, code="head\n")["ok"] is True
        intended = "head\n" + text
        res = _call(mcp, tool, file_name=NAME, content=text)

    assert res["ok"] is True, res
    stored = _stored_by_id(store, res["file"]["id"])["code"]
    assert stored == intended
    assert res["file"]["content_sha256"] == _sha(stored)
    assert res["content_changed"] is False and "content_diff" not in res
    assert "code" not in res["file"]  # Smart Projection: התוכן לא חוזר בתשובת כתיבה


def test_a_file_at_the_size_ceiling_gets_its_hash_on_write_and_on_read(mcp, store):
    """קובץ בדיוק בתקרה של ``MAX_CODE_SIZE`` — עברית ותווים של ארבעה בתים."""
    from mcp_server import handlers

    ceiling = handlers.max_code_size()
    text = ("שלום \U0001F600\n" * ceiling)[:ceiling]
    assert len(text) == ceiling

    res = _call(mcp, "codekeeper_save_file", file_name="big.txt", code=text)
    assert res["ok"] is True, res
    stored = _stored_by_id(store, res["file"]["id"])["code"]
    assert res["file"]["content_sha256"] == _sha(stored) == _sha(text)

    read = _call(mcp, "codekeeper_get_file", file_name="big.txt", lines=[1, 1])
    assert read["file"]["content_sha256"] == _sha(stored)


_MD = "# כותרת\n\nפתיחה" + RLM + ".\n\n## סעיף\n\nגוף.\n"


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"lines": [1, 1]},
        {"query": "סעיף"},
        {"toc": True},
        {"section": "סעיף"},
        {"section": "אין כזה"},  # סירוב שנושא ``file``
    ],
    ids=["full", "lines", "query", "toc", "section", "section_not_found"],
)
def test_get_file_returns_the_hash_of_the_whole_version_in_every_mode(mcp, store, arguments):
    """בכל מצב ה-hash הוא של **הקובץ המלא**, גם כשחוזר רק חלק ממנו — ולא של החלק."""
    saved = _call(mcp, "codekeeper_save_file", file_name=NAME, code=_MD)
    stored = _stored_by_id(store, saved["file"]["id"])["code"]

    out = _call(mcp, "codekeeper_get_file", file_name=NAME, **arguments)

    assert out["file"]["content_sha256"] == _sha(stored)
    if arguments == {}:
        assert out["file"]["code"] == stored
    if "lines" in arguments:
        assert out["file"]["code"] == "# כותרת"  # חזרה שורה אחת, וה-hash עדיין של הכול
    if "section" in arguments and arguments["section"] == "אין כזה":
        assert out["ok"] is False and out["error"] == "section_not_found"


def test_the_refusal_for_a_file_that_is_not_markdown_carries_the_hash(mcp, store):
    saved = _call(mcp, "codekeeper_save_file", file_name="tool.py", code="x = 1\n", language="python")
    out = _call(mcp, "codekeeper_get_file", file_name="tool.py", toc=True)
    assert out["error"] == "not_markdown"
    assert out["file"]["content_sha256"] == _sha(_stored_by_id(store, saved["file"]["id"])["code"])


def test_file_id_and_version_return_the_hash_of_the_version_they_choose(mcp, store, monkeypatch):
    """``version=N`` ו-``file_id`` — ה-hash של **אותה** גרסה, לא של האחרונה.

    ``get_file_by_id`` ממיר ``ObjectId(file_id)``, והדמה המשותפת נותנת ``_id`` מספרי.
    לכן כאן ה-insert נותן ``ObjectId`` כשאין ``_id`` — כמו pymongo, שמייצר אותו בצד הלקוח.
    """
    from bson import ObjectId

    real = store.code_snippets.insert_one
    monkeypatch.setattr(store.code_snippets, "insert_one",
                        lambda doc: real({"_id": ObjectId(), **doc}))
    first = _call(mcp, "codekeeper_save_file", file_name=NAME, code="גרסה ראשונה\n")
    second = _call(mcp, "codekeeper_append_file", file_name=NAME, content="תוספת\n")
    v1 = _stored_by_id(store, first["file"]["id"])["code"]
    v2 = _stored_by_id(store, second["file"]["id"])["code"]
    assert v1 != v2

    by_version = _call(mcp, "codekeeper_get_file", file_name=NAME, version=1, lines=[1, 1])
    assert by_version["file"]["version"] == 1 and by_version["file"]["content_sha256"] == _sha(v1)
    by_id = _call(mcp, "codekeeper_get_file", file_id=first["file"]["id"])
    assert by_id["file"]["content_sha256"] == _sha(v1)
    latest_read = _call(mcp, "codekeeper_get_file", file_name=NAME)
    assert latest_read["file"]["content_sha256"] == _sha(v2) == second["file"]["content_sha256"]


def test_list_versions_carries_no_hash(mcp, store):
    """רשימה מחזירה מטא-דאטה בלבד. hash לכל גרסה היה מחייב את התוכן של כולן.

    מוטציה שמפילה: לחשב את ה-hash ב-``_clean`` "כשיש תוכן" — ``get_all_versions``
    מושך את התוכן של כל הגרסאות בלי היטלה, ולכן כל גרסה ברשימה הייתה מקבלת hash.
    """
    _call(mcp, "codekeeper_save_file", file_name=NAME, code="א\n")
    _call(mcp, "codekeeper_append_file", file_name=NAME, content="ב\n")
    out = _call(mcp, "codekeeper_list_versions", file_name=NAME)
    assert out["count"] == 2
    for version in out["versions"]:
        assert "content_sha256" not in version and "code" not in version


# ---------------------------------------------------------------------------
# 2. הרשת תופסת — T2
# ---------------------------------------------------------------------------


def _lose_the_first_rlm_on_the_way(monkeypatch, collection):
    """שכבה בדרך לאוסף שמוחקת RLM אחד — בדיוק המחיקה שהתגלתה רק בזכות ``file_size``."""
    real = collection.insert_one

    def insert_one(doc):
        return real({**doc, "code": doc["code"].replace(RLM, "", 1)})

    monkeypatch.setattr(collection, "insert_one", insert_one)


@pytest.mark.parametrize("tool", ["codekeeper_save_file", "codekeeper_edit_file", "codekeeper_append_file"])
def test_a_layer_that_changes_the_content_on_the_way_is_reported(mcp, store, monkeypatch, tool):
    """הטסט שמוכיח שהרשת תופסת: ``content_changed``, סיכום מדויק, ו-hash של מה שנשמר.

    הצפי מחושב מהמחרוזות ביד (המיקום של ה-RLM), ולא מאותה פונקציה.

    **המוטציה שחייבת להפיל אותו — hash שמחושב מהקלט:** ב-``save_file`` להעביר ל-
    ``_full`` את הקלט במקום את מה שנקרא (``_full({**stored, "code": code})``). זה
    המימוש השגוי שהכי קל לכתוב, והוא תמיד "תקין". מוטציה שנייה, עדינה יותר: להשאיר
    את ההשוואה ולדרוס רק את ``content_sha256`` ב-``_content_sha256(code)``.
    """
    if tool == "codekeeper_save_file":
        intended = "שורה ראשונה\nשם" + RLM + ": ערך\n"
        _lose_the_first_rlm_on_the_way(monkeypatch, store.code_snippets)
        res = _call(mcp, tool, file_name=NAME, code=intended)
    elif tool == "codekeeper_edit_file":
        base = "שורה ראשונה\nשם" + RLM + ": ערך\nטיוטה\n"
        assert _call(mcp, "codekeeper_save_file", file_name=NAME, code=base)["ok"] is True
        _lose_the_first_rlm_on_the_way(monkeypatch, store.code_snippets)
        intended = base.replace("טיוטה", "סופי")
        res = _call(mcp, tool, file_name=NAME, old_string="טיוטה", new_string="סופי")
    else:
        base = "שורה ראשונה\nשם" + RLM + ": ערך"  # בלי ירידת שורה בסוף: ההוספה מוסיפה מפריד
        assert _call(mcp, "codekeeper_save_file", file_name=NAME, code=base)["ok"] is True
        _lose_the_first_rlm_on_the_way(monkeypatch, store.code_snippets)
        intended = base + "\n" + "סוף\n"
        res = _call(mcp, tool, file_name=NAME, content="סוף\n")

    stored = _stored_by_id(store, res["file"]["id"])["code"]
    assert stored == intended.replace(RLM, "", 1), "הנחת המקרה: השכבה מחקה RLM אחד"
    before = intended[:intended.index(RLM)]

    assert res["ok"] is True
    assert res["content_changed"] is True
    assert res["content_diff"] == {
        "line": before.count("\n") + 1,
        "offset_bytes": len(before.encode("utf-8")),
        "intended_bytes": 3,
        "stored_bytes": 0,
        "intended_code_points": ["U+200F"],
        "stored_code_points": [],
        "code_points_truncated": False,
        "intended_total_bytes": len(intended.encode("utf-8")),
        "stored_total_bytes": len(intended.encode("utf-8")) - 3,
    }
    assert res["file"]["content_sha256"] == _sha(stored)
    assert res["file"]["content_sha256"] != _sha(intended)


def test_the_summary_is_cheap_and_matches_a_plain_scan_across_block_edges():
    """``_content_diff`` מול סריקה תמימה, תו אחרי תו — בכל גבול של בלוק הסריקה.

    הסיכום רץ בתור הכתיבה, שיש בו חוט אחד לכל השירות, ולכן הוא סורק בבלוקים ואז
    מחפש בינארית בתוך הבלוק. כאן הוא מושווה לחיפוש הפשוט ביותר שאפשר, על מחיקה,
    הוספה והחלפה בכל גבול של בלוק ובקצוות, ועל חלון ארוך מהתקרה (``code_points_truncated``).

    מוטציה שמפילה: ``start + 1`` במקום ``start`` בגבול התחתון של החיפוש הבינארי ב-
    ``_common_prefix_len`` — ההבדל בתחילת בלוק מדווח תו אחד מאוחר מדי.
    """
    from mcp_server.backend import (
        _DIFF_SCAN_BLOCK,
        CONTENT_DIFF_MAX_CODE_POINTS,
        _content_diff,
    )

    def plain(intended, stored):
        prefix = 0
        while prefix < min(len(intended), len(stored)) and intended[prefix] == stored[prefix]:
            prefix += 1
        suffix = 0
        limit = min(len(intended), len(stored)) - prefix
        while suffix < limit and intended[-1 - suffix] == stored[-1 - suffix]:
            suffix += 1
        a, b = intended[prefix:len(intended) - suffix], stored[prefix:len(stored) - suffix]
        cap = CONTENT_DIFF_MAX_CODE_POINTS
        return {
            "line": intended[:prefix].count("\n") + 1,
            "offset_bytes": len(intended[:prefix].encode("utf-8")),
            "intended_bytes": len(a.encode("utf-8")),
            "stored_bytes": len(b.encode("utf-8")),
            "intended_code_points": [f"U+{ord(c):04X}" for c in a[:cap]],
            "stored_code_points": [f"U+{ord(c):04X}" for c in b[:cap]],
            "code_points_truncated": len(a) > cap or len(b) > cap,
            "intended_total_bytes": len(intended.encode("utf-8")),
            "stored_total_bytes": len(stored.encode("utf-8")),
        }

    base = "".join(f"{i % 10}שורה\n" for i in range(3 * _DIFF_SCAN_BLOCK // 5))
    assert len(base) > 2 * _DIFF_SCAN_BLOCK + 2
    edges = [0, 1, _DIFF_SCAN_BLOCK - 1, _DIFF_SCAN_BLOCK, _DIFF_SCAN_BLOCK + 1,
             2 * _DIFF_SCAN_BLOCK, len(base) - _DIFF_SCAN_BLOCK, len(base) - 1]
    cases = []
    for p in edges:
        cases.append((base, base[:p] + base[p + 1:]))              # מחיקה
        cases.append((base, base[:p] + RLM + base[p:]))            # הוספה
        cases.append((base, base[:p] + "\U0001F600" + base[p + 1:]))  # החלפה בתו של 4 בתים
    cases.append((base, base + "\n"))                               # ירידת שורה בסוף
    cases.append((base, base[:-1]))
    cases.append((base, "﻿" + base))                           # BOM בהתחלה
    cases.append((base, base[:100] + "x" * 50 + base[200:]))        # חלון ארוך מהתקרה
    cases.append(("", "a"))
    cases.append(("a", ""))
    for intended, stored in cases:
        assert _content_diff(intended, stored) == plain(intended, stored)


# ---------------------------------------------------------------------------
# 3. הקריאה החוזרת
# ---------------------------------------------------------------------------


def test_the_read_back_is_this_writes_document_even_when_another_version_lands_first(
        mcp, store, monkeypatch):
    """בוט ששומר גרסה משלו בין ה-insert לקריאה החוזרת — והתשובה עדיין על מה שהכלי כתב.

    קריאה "של האחרונה" הייתה מחזירה את התוכן של הבוט, ו-``content_changed`` היה
    נדלק על שינוי שהכלי לא עשה. הסדר נבנה בתוך ``insert_one``, ולכן הוא דטרמיניסטי.

    מוטציה שמפילה: קריאה חוזרת לפי שם (``_latest_fresh(dbm, user_id, file_name)``)
    במקום ``find_version_by_id``.
    """
    base = "בסיס\n"
    assert _call(mcp, "codekeeper_save_file", file_name=NAME, code=base)["ok"] is True
    real = store.code_snippets.insert_one

    def insert_then_the_bot_saves(doc):
        result = real(doc)
        real({**doc, "code": "הגרסה של הבוט\n", "version": doc["version"] + 1})
        return result

    monkeypatch.setattr(store.code_snippets, "insert_one", insert_then_the_bot_saves)
    res = _call(mcp, "codekeeper_append_file", file_name=NAME, content="תוספת\n")

    assert res["ok"] is True and res["content_changed"] is False
    assert res["file"]["version"] == 2
    assert res["file"]["content_sha256"] == _sha(base + "תוספת\n")
    assert latest(store.code_snippets, USER, NAME)["code"] == "הגרסה של הבוט\n", "הנחת המקרה"


class _StableKeyCollection:
    """הדמה המשותפת, מאחורי טביעת קאש יציבה — כמו ``Collection`` של pymongo.

    ``@cached`` בונה את המפתח מטביעה של ``__dict__`` של ה-``Repository``, והטביעה
    יורדת עד האוסף. בדמה המשותפת ``docs`` נכנס אליה כ-``[len=N]``, ולכן **כל insert
    מחליף את המפתח**, והגטר המקוּש מחטיא אחרי כל כתיבה — נמדד: אחרי insert ישיר הוא
    החזיר את הערך החדש, כלומר בדמה הקאש אינו יכול להיות ישן. באוסף אמיתי הטביעה
    אינה תלויה בתוכן. לאובייקט בלי ``__dict__`` הטביעה היא שם המחלקה ו-``repr``, ולכן
    היא יציבה; שמות dunder לא מועברים, אחרת ``__dict__`` של הדמה דולף דרך ``__getattr__``.
    כל השאר עובר לדמה כמו שהוא.
    """

    __slots__ = ("_inner",)

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_inner"), name)

    def __repr__(self):
        return "StableKeyCollection(code_snippets)"


def test_the_read_back_does_not_come_from_a_stale_cache(mcp, store, monkeypatch):
    """לפי ``write-from-cached-read``, סעיף 4 בתיקון: מחממים, משנים ישירות, מוודאים שהקאש
    **עדיין** ישן — ורק אז כותבים. ביטול הקאש מדומה ככושל, אחרת הכתיבה עצמה הייתה
    מנקה אותו והבדיקה לא הייתה בודקת כלום. והאוסף עטוף ב-:class:`_StableKeyCollection`,
    אחרת הקאש לא היה ישן גם בלי שום ביטול (ראו שם).

    מוטציה שמפילה: קריאה חוזרת דרך הגטר המקוּש (``dbm.get_latest_version``).
    """
    import database.repository as repository_module

    dbm = store.dbm
    monkeypatch.setattr(dbm, "collection", _StableKeyCollection(store.code_snippets))
    old = "גרסה ישנה\n"
    assert _call(mcp, "codekeeper_save_file", file_name=NAME, code=old)["ok"] is True
    assert dbm.get_latest_version(USER, NAME)["code"] == old  # מחממים את הגטר המקוּש

    # גרסה שנכתבה במסלול אחר, ישירות לאוסף ובלי ביטול קאש.
    newer = "גרסה מהוובאפ\n"
    current = latest(store.code_snippets, USER, NAME)
    store.code_snippets.insert_one({**{k: v for k, v in current.items() if k != "_id"},
                                    "code": newer, "version": current["version"] + 1})
    assert dbm.get_latest_version(USER, NAME)["code"] == old, "הקאש לא מחזיק ערך ישן — הבדיקה לא בודקת כלום"

    monkeypatch.setattr(repository_module.cache, "invalidate_user_cache", lambda user_id: 0)
    monkeypatch.setattr(repository_module.cache, "invalidate_file_related", lambda file_id, user_id=None: 0)
    res = _call(mcp, "codekeeper_append_file", file_name=NAME, content="שורה נוספת\n")

    stored = _stored_by_id(store, res["file"]["id"])["code"]
    assert stored == newer + "שורה נוספת\n"
    assert res["file"]["content_sha256"] == _sha(stored)
    assert res["content_changed"] is False
    # והקאש עדיין ישן: את התשובה נתן האוסף, לא הוא.
    assert dbm.get_latest_version(USER, NAME)["code"] == old


def test_the_write_path_never_puts_a_version_in_the_cache(mcp, store):
    """שלושת כלי הכתיבה לא משאירים מפתח ``latest_version`` בקאש — כמו ב-
    ``tests/test_edit_file_accumulates.py``: חזק מ"הקאש התפנה", כי הוא דורש שהערך
    לא ייכנס לקאש מלכתחילה.
    """
    import cache_manager

    clear_local_cache()
    assert _call(mcp, "codekeeper_save_file", file_name=NAME, code="א\n")["ok"] is True
    assert _call(mcp, "codekeeper_edit_file", file_name=NAME, old_string="א", new_string="ב")["ok"] is True
    assert _call(mcp, "codekeeper_append_file", file_name=NAME, content="ג\n")["ok"] is True

    leftovers = [k for k in cache_manager._local_cache_store if "latest_version" in k]
    assert not leftovers, f"מסלול הכתיבה נשען על קאש גרסאות: {leftovers}"


def _the_read_back(query) -> bool:
    """השאילתה של ``find_version_by_id`` — ``_id`` ו-``user_id``, ושום דבר אחר."""
    return isinstance(query, dict) and set(query) == {"_id", "user_id"}


@pytest.mark.parametrize("failure", ["database_error", "not_found"])
def test_a_read_back_that_fails_reports_null_and_no_hash(mcp, store, monkeypatch, failure):
    """הכתיבה קרתה, ולכן ``ok: true`` — אבל אין בידינו את מה שנשמר.

    ``content_changed: null``, ``file`` מינימלי **בלי hash**, ולא hash מהקלט. ``ok:
    false`` כאן היה שולח סוכן לנסות שוב — וליצור גרסה כפולה.
    """
    from pymongo.errors import AutoReconnect

    real_find_one = store.code_snippets.find_one

    def find_one(query=None, *args, **kwargs):
        if _the_read_back(query):
            if failure == "database_error":
                raise AutoReconnect("connection reset during read-back")
            return None
        return real_find_one(query, *args, **kwargs)

    monkeypatch.setattr(store.code_snippets, "find_one", find_one)
    res = _call(mcp, "codekeeper_save_file", file_name=NAME, code="תוכן\n")

    stored = latest(store.code_snippets, USER, NAME)
    assert stored["code"] == "תוכן\n", "הנחת המקרה: הכתיבה עצמה קרתה"
    assert res["ok"] is True and res["created"] is True
    assert res["content_changed"] is None and "content_diff" not in res
    assert res["file"] == {"id": str(stored["_id"]), "file_name": NAME, "version": stored["version"]}


def test_an_error_that_is_not_the_databases_is_not_reported_as_a_failed_read(mcp, store, monkeypatch):
    """רק שגיאת מסד היא "לא הצלחתי לקרוא". באג — כאן ``TypeError`` — עולה בקול.

    אחרת דמה בלי ``with_options`` (כזו הייתה ``tests/_fake_mongo.py`` עד השינוי הזה)
    הייתה מדווחת ``null`` על כל שמירה, וטסט שבודק רק ``ok`` היה עובר עליה.

    מוטציה שמפילה: להרחיב את ה-``except`` בקריאה החוזרת ל-``Exception``.
    """
    real_find_one = store.code_snippets.find_one

    def find_one(query=None, *args, **kwargs):
        if _the_read_back(query):
            raise TypeError("a bug, not a database failure")
        return real_find_one(query, *args, **kwargs)

    monkeypatch.setattr(store.code_snippets, "find_one", find_one)
    with pytest.raises(ToolError, match="a bug, not a database failure"):
        asyncio.run(mcp.call_tool("codekeeper_save_file", {"file_name": NAME, "code": "תוכן\n"}))


def test_find_version_by_id_returns_a_document_only_to_its_owner(store):
    """``user_id`` הוא חלק מהשאילתה: אותו ``_id``, משתמש אחר — ``None``.

    מוטציה שמפילה: להוריד את ``user_id`` מהשאילתה ב-``Repository.find_version_by_id``.
    """
    inserted = store.code_snippets.insert_one(
        {"user_id": USER, "file_name": NAME, "code": "שלי\n", "version": 1, "is_active": True})

    assert store.dbm.find_version_by_id(inserted.inserted_id, USER)["code"] == "שלי\n"
    assert store.dbm.find_version_by_id(inserted.inserted_id, USER + 1) is None


def test_find_version_by_id_asks_the_primary(store, monkeypatch):
    """``ReadPreference.PRIMARY`` מפורש — בלי תלות ב-``readPreference`` שבכתובת החיבור.

    מוטציה שמפילה: ``self.manager.collection.find_one(...)`` בלי ``with_options``.
    """
    from pymongo import ReadPreference

    asked = []
    real = store.code_snippets.with_options

    def with_options(**options):
        asked.append(options)
        return real(**options)

    monkeypatch.setattr(store.code_snippets, "with_options", with_options)
    store.dbm.find_version_by_id(12345, USER)
    assert asked == [{"read_preference": ReadPreference.PRIMARY}]


# ---------------------------------------------------------------------------
# 4. תוכן שאינו מחרוזת
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stored", [b"# bytes\n", None], ids=["bytes", "missing"])
@pytest.mark.parametrize(
    "arguments",
    [{}, {"lines": [1, 1]}, {"query": "bytes"}, {"toc": True}, {"section": "bytes"}],
    ids=["full", "lines", "query", "toc", "section"],
)
def test_stored_content_that_is_not_a_string_fails_loudly_in_every_read_mode(
        mcp, store, stored, arguments):
    """מצב שלא אמור לקרות נשמע, ואינו נראה כמו קובץ ריק — בכל מצב קריאה.

    עד השינוי הזה ``lines`` ו-``query`` התייחסו לתוכן כזה בשקט כאל מחרוזת ריקה, ושדה
    חסר נראה כקובץ ריק גם במפה. ההודעה נושאת את שם הטיפוס בלבד, בלי תוכן.

    מוטציה שמפילה: להחזיר ``code = out.get("code") or ""`` ב-``_full`` במקום הבדיקה.
    """
    _seed(store, stored)
    type_name = type(stored).__name__
    with pytest.raises(ToolError, match=f"stored file content is {type_name}, not str"):
        asyncio.run(mcp.call_tool("codekeeper_get_file", {"file_name": NAME, **arguments}))


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [("codekeeper_edit_file", {"old_string": "a", "new_string": "b"}),
     ("codekeeper_append_file", {"content": "tail\n"})],
    ids=["edit", "append"],
)
def test_edit_and_append_on_content_that_is_not_a_string_fail_before_writing(
        mcp, store, tool, arguments):
    """העריכה וההוספה קוראות את הבסיס דרך אותו ``_full`` — ונופלות לפני כתיבה.

    עד השינוי הזה הן החזירו ``empty_file``, כלומר "הקובץ ריק", על קובץ שאינו ריק.
    """
    _seed(store, b"a\n")
    with pytest.raises(ToolError, match="stored file content is bytes, not str"):
        asyncio.run(mcp.call_tool(tool, {"file_name": NAME, **arguments}))
    assert len(store.code_snippets.docs) == 1, "נכתבה גרסה על בסיס שאינו מחרוזת"


# ---------------------------------------------------------------------------
# 5. תקציב — toc ו-section
# ---------------------------------------------------------------------------

#: מה ששדה ה-hash מוסיף ל-``file`` כפי שהוא נשלח (``indent=2``, ``file`` בעומק 1):
#: פסיק, ירידת שורה, ארבעה רווחים, המפתח במירכאות, ``": "`` ו-64 תווי hex במירכאות.
_HASH_WIRE_BYTES = len(',\n    "content_sha256": ""') + 64


def test_a_toc_answer_near_the_budget_stays_within_it_with_the_hash(mcp, store):
    """מפה שנחתכת לתקציב נשארת בתוכו גם עם ה-hash — כי הוא נמדד יחד עם כל השאר.

    המפה נחתכת בפריטים שלמים (כ-780 בתים כל אחד כאן), ולכן המרחק מהתקציב נע בין
    אפס לגודל פריט. סוויפ על אורך ה-``description`` — שיושב ב-``file`` — מזיז את
    התשובה בית אחרי בית, ובאחד הצעדים היא נוחתת קרוב לתקציב יותר מגודל השדה. הטענה
    השנייה מוודאת שזה אכן קרה, אחרת הבדיקה לא הייתה בודקת כלום.

    מוטציה שמפילה: לבנות את ``context`` ב-``_apply_sections_to_file`` בלי ה-hash,
    ולהוסיף אותו ל-``file`` של התשובה אחרי ``answer_section``.
    """
    from mcp_server.repo_handlers import OUTPUT_BYTE_BUDGET

    text = "".join(f"# {i:03d} " + "t" * 300 + "\n\nbody\n\n" for i in range(400))
    margins = []
    for extra in range(0, 841, 60):
        store.code_snippets.docs.clear()
        _seed(store, text, description="d" * extra)
        out, size = _call_sent(mcp, "codekeeper_get_file", file_name=NAME, toc=True)
        assert out["status"] == "toc" and out["toc_truncated"] is True, out.get("error")
        assert out["file"]["content_sha256"] == _sha(text)
        assert size <= OUTPUT_BYTE_BUDGET, f"description={extra}: {size} > {OUTPUT_BYTE_BUDGET}"
        margins.append(OUTPUT_BYTE_BUDGET - size)
    assert min(margins) < _HASH_WIRE_BYTES, f"אף צעד לא נחת ליד התקציב: {margins}"


def test_a_section_page_packed_to_the_budget_stays_within_it_with_the_hash(mcp, store):
    """עמוד סעיף שנחתך לתקציב נחתך לפי תו — ולכן יושב צמוד אליו, והשדה נמדד בתוכו.

    מוטציה שמפילה: אותה מוטציה כמו במפה — ה-hash נוסף אחרי ``answer_section``.
    """
    from mcp_server import docs_handlers
    from mcp_server.repo_handlers import OUTPUT_BYTE_BUDGET

    text = "# S\n\n" + "\n".join(["汉" * 100] * 1100) + "\n"
    _seed(store, text)
    out, size = _call_sent(mcp, "codekeeper_get_file", file_name=NAME, section="S",
                           max_chars=docs_handlers.MAX_CHARS_MAX)

    assert out["status"] == "section" and out["truncation_reason"] == "byte_budget"
    assert out["file"]["content_sha256"] == _sha(text)
    assert size <= OUTPUT_BYTE_BUDGET
    assert OUTPUT_BYTE_BUDGET - size < _HASH_WIRE_BYTES, "הנחת המקרה: העמוד צמוד לתקציב"


# ---------------------------------------------------------------------------
# 6. שומרים
# ---------------------------------------------------------------------------

_BACKEND = ROOT / "mcp_server" / "backend.py"
#: מי מותר לו לקרוא ל-``_clean``: הסריאלייזר של קובץ בודד, ושלוש הרשימות — שבהן אין hash.
_CLEAN_CALLERS = frozenset({"_full", "list_files", "search_code", "list_versions"})
#: שתי הדרכים לבנות ``file`` ב-backend.
_FILE_BUILDERS = frozenset({"_file_meta", "_unverified_saved_file"})


def _called(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _builds_file_properly(value: ast.AST) -> bool:
    return isinstance(value, ast.Call) and _called(value.func) in _FILE_BUILDERS


def _offences(source: str) -> tuple[list[str], int]:
    """(הפרות, כמה ``file`` נבנו כמו שצריך).

    ``file`` נתפס בשלוש צורות: מפתח במילון (``{"file": ...}``), השמה
    (``out["file"] = ...``) ו-``dict(file=...)``.
    """
    offences: list[str] = []
    proper = 0

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.functions: list[str] = []

        def _in(self) -> str:
            return self.functions[-1] if self.functions else "<module>"

        def visit_FunctionDef(self, node):
            self.functions.append(node.name)
            self.generic_visit(node)
            self.functions.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def _file_value(self, value, line):
            nonlocal proper
            if _builds_file_properly(value):
                proper += 1
            else:
                offences.append(f"{line}: file שנבנה ב-{self._in()} בלי _file_meta")

        def visit_Call(self, node):
            name = _called(node.func)
            if name == "_clean" and self._in() not in _CLEAN_CALLERS:
                offences.append(f"{node.lineno}: _clean ב-{self._in()}")
            if name == "_unverified_saved_file" and self._in() != "save_file":
                offences.append(f"{node.lineno}: _unverified_saved_file ב-{self._in()}")
            if name == "dict":
                for keyword in node.keywords:
                    if keyword.arg == "file":
                        self._file_value(keyword.value, node.lineno)
            self.generic_visit(node)

        def visit_Dict(self, node):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "file":
                    self._file_value(value, node.lineno)
            self.generic_visit(node)

        def visit_Assign(self, node):
            for target in node.targets:
                if (isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "file"):
                    self._file_value(node.value, node.lineno)
            self.generic_visit(node)

    _Visitor().visit(ast.parse(source))
    return offences, proper


def test_every_file_object_in_the_backend_passes_the_point_that_adds_the_hash():
    """שומר מבני: כלי קבצים שיתווסף מחר לא ידלג על ``content_sha256``.

    ה-hash נוסף במקום אחד (``_full``), ו-``file`` בלי תוכן נבנה במקום אחד
    (``_file_meta``). מסלול שקורא ל-``_clean`` ישירות, או שבונה ``file`` ביד, עוקף את
    שניהם — ומחזיר קובץ בלי hash ובלי שום סימן שמשהו חסר.

    מוטציות שמפילות: ``save_file`` שמחזיר ``"file": _clean(stored)``; ומסלול חדש שבונה
    ``{"file": {"id": ...}}`` ביד.
    """
    offences, proper = _offences(_BACKEND.read_text(encoding="utf-8"))
    assert proper >= 4, f"הסריקה מצאה רק {proper} בניות תקינות — היא כנראה לא רואה את הקוד"
    assert not offences, "file שעוקף את נקודת ה-hash:\n" + "\n".join(offences)


def test_the_scanner_catches_every_form_it_claims_to():
    """בלי זה, סורק שבור היה עובר על ה-backend בירוק."""
    caught = [
        "def save_file():\n    return {'ok': True, 'file': _clean(doc)}",
        "def new_tool():\n    return {'file': {'id': 'x'}}",
        "def new_tool():\n    out['file'] = meta",
        "def new_tool():\n    return dict(file=meta)",
        "def get_file():\n    return _unverified_saved_file(1, file_name='a', version=1)",
    ]
    for snippet in caught:
        assert _offences(snippet)[0], snippet
    allowed = (
        "def _full(doc):\n    return _clean(doc, include_code=True)\n"
        "def save_file():\n    return {'file': _file_meta(out)}, {'file': _unverified_saved_file(1)}\n"
        "# {'file': _clean(doc)} בהערה אינו קוד\n"
    )
    assert _offences(allowed) == ([], 2)


def test_the_formula_in_the_tool_descriptions_is_what_the_server_computes(monkeypatch):
    """הנוסחה שהסוכן מריץ, כפי שהיא כתובה בתיאורים, נותנת את מה ש-``_full`` מחזיר.

    והיא יושבת בתיאור של ``get_file`` ושל שלושת כלי הכתיבה; ``list_versions``
    מפנה ל-``version=N`` עם ``lines=[1, 1]``.
    """
    import mcp_server.server as srv
    from mcp_server.backend import _full

    monkeypatch.setenv("ENVIRONMENT", "production")  # ``build_mcp`` בלי PostHog — ראו ``mcp``

    sample = "﻿שורה" + RLM + "\r\n\U0001F600\n"
    agent_side = eval(srv._CONTENT_SHA256_CHECK, {"__builtins__": {}, "hashlib": hashlib, "text": sample})
    assert agent_side == _full({"_id": "x", "code": sample})["content_sha256"]

    class _Nothing:
        def __getattr__(self, _name):
            return lambda *a, **k: {}

    tools = {t.name: t.description for t in srv.build_mcp(_Nothing())._tool_manager.list_tools()}
    for name in ("codekeeper_get_file", "codekeeper_save_file", "codekeeper_edit_file",
                 "codekeeper_append_file"):
        assert srv._CONTENT_SHA256_CHECK in tools[name], name
    for name in ("codekeeper_save_file", "codekeeper_edit_file", "codekeeper_append_file"):
        assert "content_changed" in tools[name], name
    assert "version=N" in tools["codekeeper_list_versions"]
    assert "lines=[1, 1]" in tools["codekeeper_list_versions"]
