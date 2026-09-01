"""Unit tests for the pure tool handlers (input validation + clamping)."""

from mcp_server import handlers


class _RecordingBackend:
    def __init__(self):
        self.calls = []

    def list_files(self, user_id, *, page, per_page):
        self.calls.append(("list_files", user_id, page, per_page))
        return {"files": [], "total": 0, "page": page, "per_page": per_page}

    def search_code(self, user_id, *, query, language, limit):
        self.calls.append(("search", user_id, query, language, limit))
        return []

    def get_file(self, user_id, *, file_name, file_id, version):
        self.calls.append(("get_file", user_id, file_name, file_id, version))
        return None

    def list_versions(self, user_id, *, file_name):
        self.calls.append(("versions", user_id, file_name))
        return []

    def list_collections(self, user_id, *, limit):
        self.calls.append(("list_coll", user_id, limit))
        return {}

    def get_collection(self, user_id, *, collection_id):
        self.calls.append(("get_coll", user_id, collection_id))
        return {}

    def get_collection_items(self, user_id, *, collection_id, page, per_page, folder):
        self.calls.append(("items", user_id, collection_id, page, per_page, folder))
        return {}

    def save_file(self, user_id, *, file_name, code, programming_language, description):
        self.calls.append(("save", user_id, file_name, code, programming_language, description))
        return {"ok": True, "created": True, "file": {"file_name": file_name, "version": 1}}


def test_list_files_clamps_page_and_per_page():
    be = _RecordingBackend()
    handlers.list_files(be, 1, page=0, per_page=99999)
    assert be.calls[0] == ("list_files", 1, 1, 200)  # page floored, per_page capped


def test_search_empty_query_short_circuits():
    be = _RecordingBackend()
    assert handlers.search_code(be, 1, query="   ") == []
    assert be.calls == []  # backend not touched


def test_search_limit_capped():
    be = _RecordingBackend()
    handlers.search_code(be, 1, query="x", limit=10_000)
    assert be.calls[0] == ("search", 1, "x", None, 100)


def test_get_file_requires_an_identifier():
    be = _RecordingBackend()
    assert handlers.get_file(be, 1) is None
    assert be.calls == []


def test_list_versions_requires_name():
    be = _RecordingBackend()
    assert handlers.list_versions(be, 1, file_name="") == []
    assert be.calls == []


def test_get_collection_items_missing_id_errors_without_call():
    be = _RecordingBackend()
    out = handlers.get_collection_items(be, 1, collection_id="")
    assert out["ok"] is False
    assert be.calls == []


def test_collections_limit_capped():
    be = _RecordingBackend()
    handlers.list_collections(be, 1, limit=10_000)
    assert be.calls[0] == ("list_coll", 1, 500)


def test_save_file_rejects_missing_name():
    be = _RecordingBackend()
    assert handlers.save_file(be, 7, file_name="  ", code="x") == {
        "ok": False,
        "error": "missing_file_name",
    }
    assert be.calls == []  # backend never touched on rejection


def test_save_file_rejects_empty_code():
    be = _RecordingBackend()
    assert handlers.save_file(be, 7, file_name="a.py", code="") == {
        "ok": False,
        "error": "empty_code",
    }
    assert be.calls == []


def test_save_file_rejects_oversize():
    be = _RecordingBackend()
    out = handlers.save_file(be, 7, file_name="a.py", code="x" * 100_001)
    assert out["ok"] is False and out["error"] == "code_too_large"
    assert be.calls == []


def test_save_file_passes_explicit_language_and_trims_name():
    be = _RecordingBackend()
    out = handlers.save_file(be, 7, file_name=" a.py ", code="print(1)", language="python")
    assert out["ok"] is True
    assert be.calls[0] == ("save", 7, "a.py", "print(1)", "python", "")


def test_save_file_fills_a_language_when_omitted():
    be = _RecordingBackend()
    handlers.save_file(be, 7, file_name="a.py", code="print(1)")
    call = be.calls[0]
    assert call[0] == "save" and call[4]  # a non-empty language was resolved


class _BackendWithExistingFile(_RecordingBackend):
    """‏``get_file`` מחזיר מסמך — כלומר הקובץ כבר קיים."""

    def get_file(self, user_id, *, file_name=None, file_id=None, version=None):
        self.calls.append(("get_file", user_id, file_name))
        return {"file_name": file_name, "code": "# תוכן קיים", "version": 3}


class _BackendWhoseLookupFails(_RecordingBackend):
    """‏``get_file`` נכשל — בדיקת קיום שבורה אינה חוסמת שמירה של קובץ חדש."""

    def get_file(self, user_id, *, file_name=None, file_id=None, version=None):
        raise RuntimeError("lookup down")


def test_save_file_is_blocked_when_the_name_already_exists():
    """שמירה על שם קיים נחסמת, ומפנה לכלי העריכה.

    היא הייתה יוצרת גרסה חדשה, והתוכן הקודם היה נעלם משני המקומות שבהם
    מחפשים אותו — החיפוש מקבץ לגרסה האחרונה לכל שם קובץ, ועמוד הקובץ
    מציג אותה בלבד. קובץ ותיק שחלק שם עם מה שנשמר עכשיו הפך לבלתי נגיש
    בלי שהכותב ידע שדרס משהו.
    """
    be = _BackendWithExistingFile()
    result = handlers.save_file(be, 7, file_name="amir.md", code="# חדש")

    assert result["ok"] is False
    assert result["error"] == "file_exists"
    assert result["file_name"] == "amir.md"
    # ההפניה חייבת להיות לשמות כלים אמיתיים, אחרת היא שולחת למקום שאינו קיים
    assert "codekeeper_edit_file" in result["message"]
    assert "codekeeper_append_file" in result["message"]
    # ובעיקר: לא נכתב דבר
    assert not any(c[0] == "save" for c in be.calls), be.calls


def test_save_file_still_creates_a_genuinely_new_file():
    """הכיוון ההפוך — אחרת החסימה הייתה הופכת את הכלי לחסר תועלת."""
    be = _RecordingBackend()
    result = handlers.save_file(be, 7, file_name="new.py", code="print(1)")

    assert result["ok"] is True
    assert any(c[0] == "save" for c in be.calls), be.calls


def test_a_failed_existence_check_does_not_block_a_save():
    """בדיקת קיום שנכשלה אינה הופכת שמירה לחסומה.

    זה המצב היחיד שבו דריסה עדיין אפשרית, והבחירה מודעת: לחסום כל שמירה
    בגלל תקלת קריאה היה משתק את הכלי לגמרי.
    """
    be = _BackendWhoseLookupFails()
    result = handlers.save_file(be, 7, file_name="a.py", code="x")

    assert result["ok"] is True
    assert any(c[0] == "save" for c in be.calls), be.calls
