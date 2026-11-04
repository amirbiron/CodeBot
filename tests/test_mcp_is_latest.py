"""``file.is_latest`` בקריאה לפי ``file_id`` ב-``codekeeper_get_file``.

``file_id`` מזהה מסמך גרסה אחד, וקריאה לפיו מחזירה את הגרסה הזו גם כשכבר יש חדשה. השדה
אומר אם זו הגרסה שקריאה לפי השם הייתה מחזירה באותו רגע: ``true``, ``false``, ``null``
כשהבדיקה לא הצליחה, ונעדר לגרסה שבסל. ההגדרה ב-``_is_latest_field`` ב-
``mcp_server/backend.py``, והתיעוד ב-``docs/mcp-server-state.rst`` (``mcp-is-latest``).

**דרך הממשק שהסוכן מפעיל:** ``mcp.call_tool`` על שרת MCP אמיתי (``build_mcp``), מעל
``ProductionBackend``, ``DatabaseManager`` ו-``Repository`` אמיתיים — אותה הרכבה של
``tests/test_save_preserves_content_mcp.py``. רק האוספים הם הדמה המשותפת
(``tests/_fake_mongo.py``), ולכן הקריאה לפי שם היא ``Repository._fetch_latest_version``
האמיתית, והגטר המקוּש הוא ה-``@cached`` האמיתי.

``get_file_by_id`` ממיר ``ObjectId(file_id)``, והדמה נותנת ``_id`` מספרי — ולכן ה-insert
נותן ``ObjectId`` כשאין ``_id``, כמו pymongo (אותה החלפה של
``tests/test_mcp_content_sha256.py``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _save_layer_harness import (
    StableKeyCollection,
    clear_local_cache,
    install_fake_collections,
    latest,
    load_production_config,
)

pytest.importorskip("mcp")

USER = 6262
NAME = "notes.md"
V1 = "# כותרת\n\n## K11. חריגה נבלעת\n\nטיוטה ראשונה.\n"
V2 = V1.replace("טיוטה ראשונה", "נוסח שני")


@pytest.fixture
def store(monkeypatch):
    from bson import ObjectId

    load_production_config(monkeypatch)
    harness = install_fake_collections(monkeypatch)
    real = harness.code_snippets.insert_one
    monkeypatch.setattr(harness.code_snippets, "insert_one", lambda doc: real({"_id": ObjectId(), **doc}))
    yield harness
    clear_local_cache()


@pytest.fixture
def mcp(monkeypatch, store):
    import mcp.server.auth.middleware.auth_context as auth_context

    import mcp_server.server as srv
    from mcp_server.backend import ProductionBackend

    # ``build_mcp`` קורא ל-``instrument_mcp_server``, שזורק מחוץ לפרודקשן בלי PostHog.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: USER)
    monkeypatch.setattr(auth_context, "get_access_token", lambda: SimpleNamespace(scopes=["read", "write"]))
    return srv.build_mcp(ProductionBackend(db_manager=store.dbm, mongo_db=store.raw))


def _call(mcp, tool: str, **args) -> dict:
    result = asyncio.run(mcp.call_tool(tool, args))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def _read(mcp, **args) -> dict:
    return _call(mcp, "codekeeper_get_file", **args)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _two_versions(mcp) -> tuple[str, str]:
    """גרסה 1 בשמירה, גרסה 2 בעריכה — דרך הכלים. מחזיר את שני המזהים."""
    first = _call(mcp, "codekeeper_save_file", file_name=NAME, code=V1)
    assert first["ok"] is True, first
    second = _call(mcp, "codekeeper_edit_file", file_name=NAME, old_string="טיוטה ראשונה",
                   new_string="נוסח שני")
    assert second["ok"] is True and second["file"]["version"] == 2, second
    return first["file"]["id"], second["file"]["id"]


def _without_is_latest(answer: dict) -> dict:
    """התשובה בלי ``file.is_latest`` — ההבדל היחיד שמותר בין קריאה לפי איידי לקריאה לפי שם."""
    return {**answer, "file": {k: v for k, v in answer["file"].items() if k != "is_latest"}}


#: כל מצבי הקריאה, כפי שהסוכן מעביר אותם. ``query`` מוצא שורה בשתי הגרסאות, ו-``section``
#: קיים בשתיהן — כך שאותה בקשה עונה על הגרסה הישנה ועל החדשה.
MODES = {
    "whole": {},
    "lines": {"lines": [1, 1]},
    "query": {"query": "K11"},
    "toc": {"toc": True},
    "section": {"section": "K11"},
}


def test_the_latest_id_reads_true_and_an_older_id_false(mcp, store):
    """המזהה של הגרסה האחרונה — ``true``; של גרסה ישנה — ``false``, והתוכן שלה חוזר כמו שהוא.

    נופל על הקוד שלפני השדה: אין ``is_latest`` בתשובה. כאן לשתי הגרסאות מספרים שונים, ולכן
    השוואת ``_id`` והשוואת מספרים עונות אותו דבר; את ההבדל ביניהן בודק
    :func:`test_two_active_versions_with_one_number_give_true_to_one_of_them`.
    """
    old_id, new_id = _two_versions(mcp)

    new = _read(mcp, file_id=new_id)
    assert new["file"]["is_latest"] is True and new["file"]["code"] == V2

    old = _read(mcp, file_id=old_id)
    assert old["file"]["is_latest"] is False
    assert old["file"]["code"] == V1 and old["file"]["content_sha256"] == _sha(V1)


def test_two_active_versions_with_one_number_give_true_to_one_of_them(mcp, store):
    """שני מסמכים פעילים עם אותו ``version`` — השדה עונה על **זהות**, ולכן ``true`` לאחד בלבד:
    זה שקריאה לפי השם מחזירה.

    מצב כזה קיים בפרודקשן (``Repository.iter_latest_active_versions``: חמש גרסאות פעילות
    באותו ``version`` ב-17.10.2026). הקריאה לפי שם ממיינת לפי ``version`` בלבד, ולכן איזה
    מהשניים היא בוחרת נקבע אצלה — הטסט לא מניח איזה, רק שזה שהיא בחרה הוא ה-``true``.

    מוטציה שמפילה: ``latest.get("version") == doc.get("version")`` — שניהם ``true``.
    """
    old_id, new_id = _two_versions(mcp)
    twin = {**latest(store.code_snippets, USER, NAME), "code": "תאום\n"}
    twin.pop("_id")
    store.code_snippets.insert_one(twin)

    chosen = _read(mcp, file_name=NAME)["file"]["id"]
    same_number = [str(d["_id"]) for d in store.code_snippets.docs if d["version"] == 2]
    assert len(same_number) == 2 and chosen in same_number

    answers = {doc_id: _read(mcp, file_id=doc_id)["file"]["is_latest"] for doc_id in same_number}
    assert answers == {doc_id: doc_id == chosen for doc_id in same_number}
    assert _read(mcp, file_id=old_id)["file"]["is_latest"] is False


def test_the_id_that_was_latest_reads_false_after_a_new_version_while_the_cache_still_has_it(
    mcp, store, monkeypatch
):
    """לפי ``write-from-cached-read``, סעיף 4 בתיקון: מחממים את הגטר המקוּש, שומרים גרסה חדשה
    בלי שהקאש מתבטל, **מוודאים שהקאש עדיין זוכר את הישנה** — ורק אז קוראים לפי האיידי שלה.

    ביטול הקאש מדומה ככושל, אחרת השמירה עצמה הייתה מנקה אותו והבדיקה לא הייתה בודקת כלום;
    והאוסף עטוף ב-``StableKeyCollection``, אחרת הקאש בדמה לא היה ישן גם בלי שום ביטול (ראו שם).

    מוטציה שמפילה: ``dbm.get_latest_version`` (המקוּש) במקום ``_latest_fresh`` ב-
    ``_is_latest_field`` — הגרסה שנדרסה מסומנת ``true``.
    """
    import database.repository as repository_module

    dbm = store.dbm
    monkeypatch.setattr(dbm, "collection", StableKeyCollection(store.code_snippets))
    first = _call(mcp, "codekeeper_save_file", file_name=NAME, code=V1)
    first_id = first["file"]["id"]
    assert _read(mcp, file_id=first_id)["file"]["is_latest"] is True
    assert str(dbm.get_latest_version(USER, NAME)["_id"]) == first_id  # מחממים את הגטר המקוּש

    monkeypatch.setattr(repository_module.cache, "invalidate_user_cache", lambda user_id: 0)
    monkeypatch.setattr(repository_module.cache, "invalidate_file_related", lambda file_id, user_id=None: 0)
    second = _call(mcp, "codekeeper_edit_file", file_name=NAME, old_string="טיוטה ראשונה",
                   new_string="נוסח שני")
    assert second["ok"] is True and second["file"]["version"] == 2
    assert str(dbm.get_latest_version(USER, NAME)["_id"]) == first_id, (
        "הקאש לא מחזיק ערך ישן — הבדיקה לא בודקת כלום")

    assert _read(mcp, file_id=first_id)["file"]["is_latest"] is False
    assert _read(mcp, file_id=second["file"]["id"])["file"]["is_latest"] is True


def test_a_version_in_the_recycle_bin_carries_no_is_latest_and_costs_no_lookup(mcp, store, monkeypatch):
    """גרסה בסל: ``file`` חוזר עם ``is_active: false``, **בלי** ``is_latest`` — ובלי שאילתה לפי שם.

    ``false`` היה מטעה (גם לקובץ שבסל יש גרסה אחרונה), ו-``null`` היה אומר "לא נבדק" על
    משהו שאין מה לבדוק בו. "בסל" הוא ``file_versions.is_active_version``, ולכן התשובה ידועה
    בלי לשאול את המסד — וזה מה שהספירה כאן בודקת.

    מוטציה שמפילה: להשמיט את בדיקת ``is_active_version`` — ``_latest_fresh`` לא מוצא גרסה
    פעילה, והשדה יוצא ``null``.
    """
    old_id, new_id = _two_versions(mcp)
    # הסל כמו שמחיקה רכה משאירה אותו: ``is_active: False`` על כל הגרסאות (``file_deletion``).
    # ``Repository.delete_file`` עצמו עובר ב-``distinct``, שהדמה המשותפת אינה מממשת.
    store.code_snippets.update_many({"user_id": USER, "file_name": NAME}, {"$set": {"is_active": False}})

    real = store.dbm.get_latest_version_fresh
    lookups: list[tuple] = []

    def counted(*args, **kwargs):
        lookups.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(store.dbm, "get_latest_version_fresh", counted)
    for doc_id in (old_id, new_id):
        out = _read(mcp, file_id=doc_id)
        assert out["found"] is True and out["file"]["is_active"] is False
        assert "is_latest" not in out["file"]
    assert lookups == []


def test_a_newer_version_in_the_recycle_bin_does_not_make_the_active_one_stale(mcp, store):
    """גרסה פעילה, וגרסה עם מספר גבוה יותר **בסל** — הפעילה היא האחרונה, כמו בקריאה לפי שם.

    השאילתה של ``Repository._fetch_latest_version`` מסננת לפי ``ACTIVE_VERSION_FILTER``, אבל
    המסלול שלה לאוסף בזיכרון — זה שרץ בטסטים — לא סינן כלום, והחזיר את הגרסה שבסל כ"אחרונה":
    בטסטים קריאה לפי שם החזירה קובץ אחר מהייצור. עכשיו שני המסלולים שואלים את
    ``is_active_version``.

    נופל על הקוד שלפני: ``false``, וגם הקריאה לפי השם מחזירה את הגרסה שבסל.
    """
    first = _call(mcp, "codekeeper_save_file", file_name=NAME, code=V1)
    active_id = first["file"]["id"]
    trashed = {**latest(store.code_snippets, USER, NAME), "version": 2, "code": V2, "is_active": False}
    trashed.pop("_id")
    store.code_snippets.insert_one(trashed)

    assert _read(mcp, file_name=NAME)["file"]["id"] == active_id
    assert _read(mcp, file_id=active_id)["file"]["is_latest"] is True


def test_when_the_lookup_by_name_fails_the_read_still_answers_with_null(mcp, store, monkeypatch):
    """השאילתה לפי שם נכשלת (``PyMongoError``) — הקריאה לפי איידי מצליחה, ו-``is_latest`` הוא ``null``.

    הכשל אמיתי ועובר ב-``Repository._fetch_latest_version`` האמיתי, שתופס אותו ומחזיר ``None``:
    האוסף נעטף כך ש-``find_one`` עם ``file_name`` בשאילתה נכשל, וקריאה לפי ``_id`` עוברת. בלי
    ``docs`` בעטיפה, כדי שהקריאה תגיע לשאילתה ולא למסלול של האוסף בזיכרון.

    ``null`` ולא ``false``: ``false`` היה שולח את הסוכן לקרוא שוב לפי שם בלי סיבה. ולא נעדר:
    נעדר נראה כמו גרסה שבסל.

    מוטציה שמפילה: ``bool(latest) and ...`` במקום ``None`` — השדה יוצא ``false``.
    """
    from pymongo.errors import PyMongoError

    old_id, new_id = _two_versions(mcp)
    attempts: list[dict] = []

    class _LookupByNameFails:
        def __init__(self, inner):
            self._inner = inner

        def find_one(self, q=None, *args, **kwargs):
            if q and "file_name" in q:
                attempts.append(q)
                raise PyMongoError("simulated failure of the lookup by name")
            return self._inner.find_one(q, *args, **kwargs)

        def __getattr__(self, name):
            if name == "docs" or name.startswith("__"):
                raise AttributeError(name)
            return getattr(self._inner, name)

    monkeypatch.setattr(store.dbm, "collection", _LookupByNameFails(store.code_snippets))
    out = _read(mcp, file_id=new_id)

    assert out["found"] is True and out["file"]["code"] == V2
    assert "is_latest" in out["file"] and out["file"]["is_latest"] is None
    assert len(attempts) == 1 and attempts[0]["file_name"] == NAME


@pytest.mark.parametrize("mode", sorted(MODES))
def test_every_read_mode_carries_it(mcp, store, mode):
    """מלא, ``lines``, ``query``, ``toc`` ו-``section`` — ``file.is_latest`` בכולם, משם אחד.

    נופל על הקוד שלפני השדה בכל אחד מהמצבים.
    מוטציה שמפילה: להוסיף את השדה רק לתשובה המלאה (ב-``server.py``) — ארבעת האחרים בלעדיו.
    """
    old_id, new_id = _two_versions(mcp)

    assert _read(mcp, file_id=new_id, **MODES[mode])["file"]["is_latest"] is True
    assert _read(mcp, file_id=old_id, **MODES[mode])["file"]["is_latest"] is False


def test_a_refusal_that_carries_file_carries_it(mcp, store):
    """``answer_too_large`` על קריאה מלאה נושא ``file`` בלי התוכן — ובו ``is_latest``.

    הקובץ נכתב ישירות לאוסף: מגבלת הגודל של מסלולי השמירה (``MAX_CODE_SIZE``) קטנה מתקרת
    התשובה, וכאן נבדקת הקריאה ולא הכתיבה.
    """
    from bson import ObjectId

    from mcp_server.answer_size import OUTPUT_BYTE_BUDGET

    line = "x" * 99 + "\n"
    big = line * (OUTPUT_BYTE_BUDGET // len(line) + 10)
    ids = []
    for version in (1, 2):
        doc_id = ObjectId()
        store.code_snippets.insert_one({
            "_id": doc_id, "user_id": USER, "file_name": "big.txt", "version": version,
            "code": big, "programming_language": "text", "is_active": True,
        })
        ids.append(str(doc_id))

    for doc_id, expected in zip(ids, (False, True)):
        out = _read(mcp, file_id=doc_id)
        assert out["ok"] is False and out["error"] == "answer_too_large", out
        assert "code" not in out["file"] and out["file"]["is_latest"] is expected


@pytest.mark.parametrize("mode", sorted(MODES))
def test_a_read_by_name_is_the_read_by_id_without_the_field(mcp, store, mode):
    """לפי שם, עם ``version`` ובלעדיו: בלי ``is_latest``, וכל השאר זהה לקריאה לפי איידי של אותה גרסה.

    מי שמעביר ``file_name`` (ו-``version``) ביקש גרסה ויודע את זה; השדה מכוון לאיידי שנגרר
    מסשן קודם. השוויון לקריאה לפי איידי בלי השדה אומר שהשדה הוא ההבדל היחיד.

    עובר גם על הקוד שלפני השינוי: זה טסט על מה ש**לא** השתנה.
    מוטציה שמפילה: לחשב את השדה גם בענף של ``file_name``.
    """
    old_id, new_id = _two_versions(mcp)

    by_name = _read(mcp, file_name=NAME, **MODES[mode])
    assert "is_latest" not in by_name["file"]
    assert by_name == _without_is_latest(_read(mcp, file_id=new_id, **MODES[mode]))

    by_version = _read(mcp, file_name=NAME, version=1, **MODES[mode])
    assert "is_latest" not in by_version["file"]
    assert by_version == _without_is_latest(_read(mcp, file_id=old_id, **MODES[mode]))


def test_the_file_id_parameter_says_what_the_field_means(mcp):
    """המשפט על השדה יושב בתיאור ``file_id`` — אחרי המשפט הראשון ולפני פקודת ההורדה — ולא
    בתיאור הכלי, שקרוב לתקרה (``_TOOL_DESCRIPTION_MAX_CHARS`` ב-``tests/test_mcp_server_build.py``).

    המשפט הראשון נשאר כמו שהוא: לקוח שמקצר תיאור פרמטר רואה רק אותו
    (``tests/test_mcp_downloads.py``).
    """
    tool = mcp._tool_manager.get_tool("codekeeper_get_file")
    doc = tool.parameters["properties"]["file_id"]["description"]
    first, rest = doc.split(". ", 1)

    assert "is_latest" not in first and "codekeeper_list_versions" in first
    assert "file.is_latest" in rest and rest.index("file.is_latest") < rest.index("curl ")
    for word in ("false", "null", "recycle bin"):
        assert word in rest.split("curl ")[0]
    assert "is_latest" not in tool.description
