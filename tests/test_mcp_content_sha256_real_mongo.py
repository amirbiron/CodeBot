"""‏``content_sha256`` מול מונגו אמיתי — הדרך דרך BSON והדרייבר, שהדמה לא עוברת בה.

הטסטים ב-``tests/test_mcp_content_sha256.py`` רצים על הדמה המשותפת, ולכן אינם
רואים את מה ש-BSON ו-pymongo עושים לטקסט בדרך. כאן אותם כלים, דרך ``mcp.call_tool``,
מול ``mongod`` אמיתי: 12 מקרים קשים — BOM, ‏CR בודד, תווי כיווניות, ZWJ, ‏U+2028,
‏NEL/DEL, ‏NUL, ירידות שורה בסוף, escape כטקסט ותווים של ארבעה בתים — והשאלה היא
אם מה שנשלח, מה שבאוסף ומה ש-``get_file`` מחזיר הם אותה מחרוזת, ואם ה-hash בכל
תשובה הוא ה-hash שלה.

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


def test_find_version_by_id_returns_a_document_only_to_its_owner(mongo_db):
    """אותו ``_id`` אמיתי, משתמש אחר — ``None``; הבעלים — המסמך."""
    inserted = mongo_db.code_snippets.insert_one(
        {"user_id": USER, "file_name": "own.md", "code": "שלי\n", "version": 1, "is_active": True})
    manager = _ManagerOnCollection(mongo_db.code_snippets)

    assert manager.find_version_by_id(inserted.inserted_id, USER)["code"] == "שלי\n"
    assert manager.find_version_by_id(inserted.inserted_id, USER + 1) is None
