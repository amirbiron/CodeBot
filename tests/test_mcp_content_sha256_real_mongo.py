"""‏``content_sha256`` מול מונגו אמיתי — הדרך דרך BSON והדרייבר, שהדמה לא עוברת בה.

הטסטים ב-``tests/test_mcp_content_sha256.py`` רצים על הדמה המשותפת, ולכן אינם
רואים את מה ש-BSON ו-pymongo עושים לטקסט בדרך. כאן אותם כלים, דרך ``mcp.call_tool``,
מול ``mongod`` אמיתי: 12 מקרים קשים — BOM, ‏CR בודד, תווי כיווניות, ZWJ, ‏U+2028,
‏NEL/DEL, ‏NUL, ירידות שורה בסוף, escape כטקסט ותווים של ארבעה בתים — והשאלה היא
אם מה שנשלח, מה שבאוסף ומה ש-``get_file`` מחזיר הם אותה מחרוזת, ואם ה-hash בכל
תשובה הוא ה-hash שלה.

**אותה מטריצה עוברת גם ב-``codekeeper_multi_edit_file``**, שבו התווים הקשים יושבים גם
ב-``old_string``: הזוג מוצא אותם רק אם הטקסט חזר מ-BSON בדיוק כמו שנשלח. ולידה שתי
טענות שהדמה אינה יכולה להוכיח — זוג שנכשל אינו משאיר מסמך באוסף האמיתי, וכתיבה
במקום (``update_one`` על ``code``, כמו ``check_file_sync`` ב-
``database/bookmarks_manager.py``) נענית ``conflict`` בשער ``expected_content_sha256``.

**בלי ``NOTE_FONTS_TEST_MONGO_URI`` הקובץ מדולג** (``wired_mongo`` ב-``tests/conftest.py``),
וב-CI הוא מדולג. הפלט של ההרצה המקומית בגוף ה-PR.

אין כאן קלט או פלט לדיסק; כל מה שנכתב הולך למסד הזמני שהפיקסצ'ר יוצר ומוחק.

הרצה מקומית::

    NOTE_FONTS_TEST_MONGO_URI='mongodb://127.0.0.1:27017' \\
        pytest tests/test_mcp_content_sha256_real_mongo.py -v
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

# ‏``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _save_layer_harness import clear_local_cache, load_production_config

pytest.importorskip("mcp")

USER = 7272

CASES = {
    "bom_crlf": "\ufeffline one\r\nline two\r\n",
    "lone_cr": "a\rb\n",
    "rlm_lrm": "גרסה\u200f 2.0\u200e\n",
    "rlo_trojan": "x = '\u202eabc\u202c'\n",
    "zwj_family": "\U0001F468\u200d\U0001F469\u200d\U0001F467\n",
    "line_sep": "a\u2028b\u2029c\n",
    "nel_del": "a\u0085b\x7fc\n",
    "nul": "a\x00b\n",
    "trailing_newlines": "x = 1\n\n\n",
    "no_trailing_newline": "x = 1",
    "escape_text": 'RLM = "\\u200f"\n',
    "hebrew_4byte_mix": "שלום \U0001F600 \U00010348 world\n",
}


class _ManagerOnCollection:
    """``DatabaseManager`` מינימלי מעל ה-collection של מסד הבדיקה, שמאציל ל-``Repository``
    **האמיתי** — כמו ב-``tests/test_mcp_description_age.py``, ומאותה סיבה: המנהל האמיתי
    מתחבר לפי הקונפיג הגלובלי, ואי אפשר להפנות אותו למסד הזמני."""

    def __init__(self, collection):
        self.collection = collection

    def _repo(self):
        from database.repository import Repository

        return Repository(self)

    def save_code_snippet_returning_id(self, snippet):
        return self._repo().save_code_snippet_returning_id(snippet)

    def find_version_by_id(self, doc_id, user_id):
        return self._repo().find_version_by_id(doc_id, user_id)

    def get_latest_version_fresh(self, user_id, file_name):
        return self._repo()._fetch_latest_version(user_id, file_name)

    def get_version(self, user_id, file_name, version):
        return self._repo().get_version(user_id, file_name, version)

    def get_file_by_id(self, file_id):
        return self._repo().get_file_by_id(file_id)


@pytest.fixture
def mongo_db(wired_mongo):
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    return db


@pytest.fixture
def mcp(monkeypatch, mongo_db):
    import mcp.server.auth.middleware.auth_context as auth_context

    import mcp_server.server as srv
    from mcp_server.backend import ProductionBackend

    load_production_config(monkeypatch)
    clear_local_cache()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: USER)
    monkeypatch.setattr(auth_context, "get_access_token", lambda: SimpleNamespace(scopes=["read", "write"]))
    yield srv.build_mcp(ProductionBackend(db_manager=_ManagerOnCollection(mongo_db.code_snippets),
                                          mongo_db=mongo_db))
    clear_local_cache()


def _call(mcp, tool: str, **args) -> dict:
    result = asyncio.run(mcp.call_tool(tool, args))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("case", sorted(CASES))
def test_what_was_sent_what_is_stored_and_what_get_file_returns_are_one_string(mcp, mongo_db, case):
    """שלוש המחרוזות זהות, וה-hash בתשובת הכתיבה ובקריאה הוא ה-hash שלהן."""
    from bson import ObjectId

    sent = CASES[case]
    file_name = f"rt_{case}.txt"
    saved = _call(mcp, "codekeeper_save_file", file_name=file_name, code=sent)
    assert saved["ok"] is True and saved["content_changed"] is False, saved

    stored = mongo_db.code_snippets.find_one({"_id": ObjectId(saved["file"]["id"])})["code"]
    read = _call(mcp, "codekeeper_get_file", file_name=file_name)["file"]
    ranged = _call(mcp, "codekeeper_get_file", file_name=file_name, lines=[1, 10_000])["file"]

    assert stored == sent
    assert read["code"] == stored and ranged["code"] == stored
    assert saved["file"]["content_sha256"] == read["content_sha256"] == ranged["content_sha256"] == _sha(stored)


@pytest.mark.parametrize("case", sorted(CASES))
def test_multi_edit_through_bson_stores_exactly_the_text_it_meant(mcp, mongo_db, case):
    """הזוג הראשון מחפש את התווים הקשים עצמם; השני מחפש מה שקיים רק אחרי הראשון.

    המחרוזת המיועדת מחושבת כאן, בפייתון, ומושווית לשלושה: מה שבאוסף, מה ש-
    ``get_file`` מחזיר, וה-hash בשתי התשובות. וגרסה אחת נוספה — לא אחת לכל זוג.
    """
    from bson import ObjectId

    sent = CASES[case]
    file_name = f"me_{case}.txt"
    assert _call(mcp, "codekeeper_save_file", file_name=file_name, code="start\n" + sent)["ok"] is True
    intended = "start\n" + sent + "<>" + sent

    res = _call(mcp, "codekeeper_multi_edit_file", file_name=file_name, edits=[
        {"old_string": sent, "new_string": sent + "|" + sent},
        {"old_string": "|", "new_string": "<>"},
    ])
    assert res["ok"] is True and res["content_changed"] is False, res
    assert res["edits_applied"] == 2 and res["replacements"] == 2

    stored = mongo_db.code_snippets.find_one({"_id": ObjectId(res["file"]["id"])})["code"]
    read = _call(mcp, "codekeeper_get_file", file_name=file_name)["file"]

    assert stored == intended
    assert read["code"] == stored
    assert res["file"]["content_sha256"] == read["content_sha256"] == _sha(stored)
    assert mongo_db.code_snippets.count_documents({"user_id": USER, "file_name": file_name}) == 2


def test_a_pair_that_fails_leaves_no_document_in_a_real_collection(mcp, mongo_db):
    """זוג שלישי שאינו מתאים: אותו מספר מסמכים, אותו תוכן אחרון, ואפס אירועי התראה."""
    file_name = "all_or_nothing.md"
    assert _call(mcp, "codekeeper_save_file", file_name=file_name, code="alpha\nbeta\n")["ok"] is True
    pushes = mongo_db.push_events.count_documents({})

    res = _call(mcp, "codekeeper_multi_edit_file", file_name=file_name, edits=[
        {"old_string": "alpha", "new_string": "ALPHA"},
        {"old_string": "beta", "new_string": "BETA"},
        {"old_string": "gamma", "new_string": "GAMMA"},
    ])

    assert res["ok"] is False and res["error"] == "no_match" and res["index"] == 2, res
    docs = list(mongo_db.code_snippets.find({"user_id": USER, "file_name": file_name}))
    assert len(docs) == 1 and docs[0]["code"] == "alpha\nbeta\n"
    assert mongo_db.push_events.count_documents({}) == pushes


@pytest.mark.parametrize("tool, arguments", [
    ("codekeeper_edit_file", {"old_string": "beta", "new_string": "BETA"}),
    ("codekeeper_append_file", {"content": "gamma\n"}),
    ("codekeeper_multi_edit_file", {"edits": [{"old_string": "beta", "new_string": "BETA"}]}),
])
def test_a_write_in_place_on_a_real_collection_is_conflict(mcp, mongo_db, tool, arguments):
    """``update_one`` על ``code`` באותו מסמך — הגרסה לא זזה, ה-hash כן, והשער תופס."""
    file_name = "in_place.md"
    saved = _call(mcp, "codekeeper_save_file", file_name=file_name, code="alpha\nbeta\n")
    read = _sha("alpha\nbeta\n")
    mongo_db.code_snippets.update_one({"user_id": USER, "file_name": file_name},
                                      {"$set": {"code": "alpha\nbeta\nsynced\n"}})

    res = _call(mcp, tool, file_name=file_name, expected_content_sha256=read, **arguments)

    assert res["ok"] is False and res["error"] == "conflict", res
    assert res["file"]["version"] == saved["file"]["version"]
    assert res["file"]["content_sha256"] == _sha("alpha\nbeta\nsynced\n")
    assert mongo_db.code_snippets.count_documents({"user_id": USER, "file_name": file_name}) == 1


def test_find_version_by_id_returns_a_document_only_to_its_owner(mongo_db):
    """אותו ``_id`` אמיתי, משתמש אחר — ``None``; הבעלים — המסמך."""
    inserted = mongo_db.code_snippets.insert_one(
        {"user_id": USER, "file_name": "own.md", "code": "שלי\n", "version": 1, "is_active": True})
    manager = _ManagerOnCollection(mongo_db.code_snippets)

    assert manager.find_version_by_id(inserted.inserted_id, USER)["code"] == "שלי\n"
    assert manager.find_version_by_id(inserted.inserted_id, USER + 1) is None
