"""Unit tests for ProductionBackend: serialization + the critical ownership check."""

from mcp_server.backend import ProductionBackend, _full


class _FakeDbManager:
    def __init__(self, files=None, by_id=None, versions=None, search=None, fail_save=False):
        self._files = files or []
        self._by_id = by_id or {}
        self._versions = versions or []
        self._search = search or []
        self._fail_save = fail_save
        self.saved = None  # last CodeSnippet passed to save_code_snippet

    def get_regular_files_paginated(self, user_id, page, per_page):
        return list(self._files), len(self._files)

    def search_code(self, user_id, query, programming_language=None, limit=20):
        return list(self._search)

    def get_file_by_id(self, file_id):
        return self._by_id.get(file_id)

    def get_latest_version(self, user_id, file_name):
        return next((f for f in self._files if f.get("file_name") == file_name), None)

    def get_version(self, user_id, file_name, version):
        return next(
            (
                v
                for v in self._versions
                if v.get("file_name") == file_name and v.get("version") == version
            ),
            None,
        )

    def get_all_versions(self, user_id, file_name):
        return [v for v in self._versions if v.get("file_name") == file_name]

    def save_code_snippet(self, snippet):
        self.saved = snippet  # capture the real CodeSnippet for assertions
        if self._fail_save:
            return False
        prev = self.get_latest_version(snippet.user_id, snippet.file_name)
        version = (prev.get("version", 0) + 1) if prev else 1
        # Replace the same-name entry so the post-save re-fetch sees the new version.
        self._files = [f for f in self._files if f.get("file_name") != snippet.file_name]
        self._files.append(
            {
                "_id": "new",
                "file_name": snippet.file_name,
                "programming_language": snippet.programming_language,
                "version": version,
                "file_size": len(snippet.code.encode("utf-8")),
                "lines_count": len(snippet.code.split("\n")),
                "description": snippet.description,
            }
        )
        return True


def test_list_files_excludes_heavy_code_field():
    dbm = _FakeDbManager(
        files=[
            {
                "_id": "a",
                "file_name": "x.py",
                "code": "secret",
                "programming_language": "python",
                "file_size": 6,
            }
        ]
    )
    out = ProductionBackend(db_manager=dbm).list_files(7, page=1, per_page=50)
    assert out["total"] == 1
    f = out["files"][0]
    assert "code" not in f
    assert f["id"] == "a"
    assert f["file_name"] == "x.py"
    assert f["language"] == "python"


def test_search_excludes_code():
    dbm = _FakeDbManager(
        search=[{"_id": "s1", "file_name": "y.py", "programming_language": "python"}]
    )
    rows = ProductionBackend(db_manager=dbm).search_code(7, query="y")
    assert rows and "code" not in rows[0]
    assert rows[0]["id"] == "s1"


def test_get_file_by_id_enforces_ownership():
    dbm = _FakeDbManager(
        by_id={"f1": {"_id": "f1", "user_id": 999, "file_name": "o.py", "code": "x"}}
    )
    be = ProductionBackend(db_manager=dbm)
    # Requesting user is not the owner -> denied.
    assert be.get_file(7, file_id="f1") is None
    # Owner gets full content.
    got = be.get_file(999, file_id="f1")
    assert got is not None and got["code"] == "x"


def test_get_file_by_name_returns_full_content():
    dbm = _FakeDbManager(
        files=[{"_id": "a", "file_name": "x.py", "code": "print(1)", "user_id": 7}]
    )
    doc = ProductionBackend(db_manager=dbm).get_file(7, file_name="x.py")
    assert doc["code"] == "print(1)"


def test_get_specific_version():
    dbm = _FakeDbManager(
        versions=[{"_id": "v2", "file_name": "x.py", "version": 2, "code": "v2code"}]
    )
    doc = ProductionBackend(db_manager=dbm).get_file(7, file_name="x.py", version=2)
    assert doc["version"] == 2 and doc["code"] == "v2code"


def test_large_file_content_mapped_to_code():
    assert _full({"_id": "a", "content": "blob"})["code"] == "blob"


def test_collections_delegate_to_manager():
    class _FakeCM:
        def list_collections(self, user_id, limit=100):
            return {"seen": (user_id, limit)}

        def get_collection(self, user_id, collection_id):
            return {"seen": (user_id, collection_id)}

        def get_collection_items(
            self, user_id, collection_id, page=1, per_page=20, folder_filter=None
        ):
            return {"seen": (user_id, collection_id, page, per_page, folder_filter)}

    be = ProductionBackend(collections_manager=_FakeCM())
    assert be.list_collections(3, limit=50)["seen"] == (3, 50)
    assert be.get_collection(3, collection_id="c1")["seen"] == (3, "c1")
    assert be.get_collection_items(3, collection_id="c1", page=2, per_page=10, folder="f")[
        "seen"
    ] == (3, "c1", 2, 10, "f")


def test_save_file_creates_new_file():
    dbm = _FakeDbManager()
    out = ProductionBackend(db_manager=dbm).save_file(
        7,
        file_name="new.py",
        code="print(1)\nprint(2)",
        programming_language="python",
        description="hi",
    )
    assert out["ok"] is True and out["created"] is True
    f = out["file"]
    assert f["version"] == 1 and f["file_name"] == "new.py" and f["language"] == "python"
    assert "code" not in f  # Smart Projection: never echo the body back
    # the real CodeSnippet reached the DB with the expected fields
    assert dbm.saved.user_id == 7 and dbm.saved.code == "print(1)\nprint(2)"
    assert dbm.saved.programming_language == "python" and dbm.saved.description == "hi"


def test_save_file_refuses_existing_without_explicit_flag():
    """שם קיים בלי ``update_existing`` — סירוב מוסבר, בלי כתיבה.

    ה-upsert השקט נשך: שמירת תוכן חדש על שם שכבר מחזיק משהו אחר מסתירה
    את התוכן הישן מחיפוש ומהתצוגה (שניהם קוראים גרסה אחרונה בלבד).
    """
    dbm = _FakeDbManager(files=[{"_id": "a", "file_name": "x.py", "version": 1}])
    out = ProductionBackend(db_manager=dbm).save_file(
        7, file_name="x.py", code="v2", programming_language="python"
    )
    assert out["ok"] is False and out["error"] == "file_exists"
    assert out["latest_version"] == 1
    assert "edit_file" in out["hint"] and "update_existing" in out["hint"]
    assert dbm.saved is None  # הסירוב קרה לפני כל כתיבה


def test_save_file_updates_existing_bumps_version():
    dbm = _FakeDbManager(files=[{"_id": "a", "file_name": "x.py", "version": 1}])
    out = ProductionBackend(db_manager=dbm).save_file(
        7, file_name="x.py", code="v2", programming_language="python", update_existing=True
    )
    assert out["ok"] is True and out["created"] is False
    assert out["file"]["version"] == 2  # append-only: new version, not overwrite


def test_save_file_reports_failure():
    dbm = _FakeDbManager(fail_save=True)
    out = ProductionBackend(db_manager=dbm).save_file(
        7, file_name="x.py", code="c", programming_language="python"
    )
    assert out == {"ok": False, "error": "save_failed"}


def test_collection_items_strip_heavy_fields():
    class _LeakyCM:
        def get_collection_items(
            self, user_id, collection_id, page=1, per_page=20, folder_filter=None
        ):
            return {
                "ok": True,
                "items": [{"id": "1", "file_name": "a.py", "code": "LEAK", "content": "LEAK2"}],
            }

    be = ProductionBackend(collections_manager=_LeakyCM())
    out = be.get_collection_items(3, collection_id="c1")
    item = out["items"][0]
    assert "code" not in item and "content" not in item
    assert item["file_name"] == "a.py"


# ---------------------------------------------------------------------------
# הפריימר: הוראות הסוכן + הקבצים האחרונים
# ---------------------------------------------------------------------------
class _FakeCursor:
    """מחקה קורסור pymongo — שומר את הקריאות כדי לאמת את צורת השאילתה."""

    def __init__(self, rows, log):
        self._rows = rows
        self._log = log

    def sort(self, key, direction):
        self._log["sort"] = (key, direction)
        return self

    def limit(self, n):
        self._log["limit"] = n
        return self

    def __iter__(self):
        return iter(self._rows)


class _FakeColl:
    def __init__(self, rows=None, doc=None):
        self._rows = rows or []
        self._doc = doc
        self.log = {}

    def find(self, query, projection=None):
        self.log["query"] = query
        self.log["projection"] = projection
        return _FakeCursor(self._rows, self.log)

    def find_one(self, query, projection=None):
        self.log["query"] = query
        self.log["projection"] = projection
        return self._doc


class _FakeMongo:
    def __init__(self, **colls):
        self._colls = colls

    def __getitem__(self, name):
        return self._colls[name]


def test_get_agent_instructions_reads_user_preferences():
    prefs = _FakeColl(doc={"agent_instructions": "תמיד בעברית"})
    be = ProductionBackend(mongo_db=_FakeMongo(user_preferences=prefs))
    assert be.get_agent_instructions(7) == "תמיד בעברית"
    assert prefs.log["query"] == {"user_id": 7}


def test_get_agent_instructions_missing_document_returns_empty_string():
    be = ProductionBackend(mongo_db=_FakeMongo(user_preferences=_FakeColl(doc=None)))
    assert be.get_agent_instructions(7) == ""


def test_get_agent_instructions_ignores_a_non_string_value():
    be = ProductionBackend(
        mongo_db=_FakeMongo(user_preferences=_FakeColl(doc={"agent_instructions": 42}))
    )
    assert be.get_agent_instructions(7) == ""


def test_recent_files_dedupes_versions_and_keeps_the_newest():
    rows = [
        {"file_name": "a.py", "created_at": "t5"},
        {"file_name": "a.py", "created_at": "t4"},  # גרסה ישנה של אותו קובץ
        {"file_name": "b.js", "created_at": "t3"},
        {"file_name": "a.py", "created_at": "t2"},
        {"file_name": "c.md", "created_at": "t1"},
        {"file_name": "d.txt", "created_at": "t0"},
    ]
    coll = _FakeColl(rows=rows)
    be = ProductionBackend(mongo_db=_FakeMongo(code_snippets=coll))
    out = be.recent_files(7, limit=3)
    assert [f["file_name"] for f in out] == ["a.py", "b.js", "c.md"]
    assert out[0]["saved_at"] == "t5"  # הגרסה החדשה, לא הישנה


def test_recent_files_query_matches_the_existing_index():
    """user_id + is_active + מיון על created_at ⇒ user_active_created_at_idx."""
    coll = _FakeColl(rows=[])
    ProductionBackend(mongo_db=_FakeMongo(code_snippets=coll)).recent_files(7, limit=3)
    assert coll.log["query"] == {"user_id": 7, "is_active": True}
    assert coll.log["sort"] == ("created_at", -1)
    # Smart Projection: שום שדה תוכן כבד לא נשלף לרשימה
    assert "code" not in (coll.log["projection"] or {})
    assert coll.log["limit"] >= 3


def test_recent_files_skips_blank_names():
    coll = _FakeColl(rows=[{"file_name": "  ", "created_at": "t"}, {"file_name": "ok.py"}])
    out = ProductionBackend(mongo_db=_FakeMongo(code_snippets=coll)).recent_files(7, limit=3)
    assert [f["file_name"] for f in out] == ["ok.py"]


def test_recent_files_returns_empty_on_db_error():
    class _Boom:
        def find(self, *a, **k):
            raise RuntimeError("mongo down")

    be = ProductionBackend(mongo_db=_FakeMongo(code_snippets=_Boom()))
    assert be.recent_files(7, limit=3) == []


def test_recent_files_survives_a_cursor_that_fails_mid_iteration():
    """קורסור pymongo עצל: השאילתה יוצאת לרשת באיטרציה, לא ב-``find()``.

    ``try`` שעוטף רק את בניית הקורסור היה מפספס בדיוק את השגיאות שקורות
    בפרודקשן (AutoReconnect / ExecutionTimeout).
    """

    class _BoomCursor:
        def sort(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def __iter__(self):
            raise RuntimeError("mongo down mid-cursor")

    class _LazyBoom:
        def find(self, *a, **k):
            return _BoomCursor()

    be = ProductionBackend(mongo_db=_FakeMongo(code_snippets=_LazyBoom()))
    assert be.recent_files(7, limit=3) == []


def test_recent_files_zero_limit_does_no_query():
    coll = _FakeColl(rows=[{"file_name": "a.py"}])
    assert ProductionBackend(mongo_db=_FakeMongo(code_snippets=coll)).recent_files(7, limit=0) == []
    assert coll.log == {}


# ── add_to_collection: חוזה ערך ההחזרה של add_items ────────────────────


def test_a_non_dict_add_items_result_fails_cleanly_not_with_a_crash():
    """‏``add_items`` שמחזירה ערך אמת שאינו dict היא כשל חוזה — לא קריסה.

    הקוד הקודם עשה ``(res or {}).get`` — על ``True`` או מחרוזת זה
    ``AttributeError`` שמפיל את הכלי במקום להחזיר שגיאה מסודרת.
    """

    class _CM:
        def get_collection(self, user_id, collection_id):
            return {"ok": True, "collection": {"id": collection_id}}

        def add_items(self, user_id, collection_id, items):
            return True  # ערך אמת שאינו dict

    class _DBM:
        def get_latest_version_fresh(self, user_id, file_name):
            return {"file_name": file_name, "code": "x"}

    be = ProductionBackend(db_manager=_DBM(), collections_manager=_CM())
    res = be.add_to_collection(7, collection_id="a" * 24, file_name="a.py")
    assert res == {"ok": False, "error": "add_failed"}
