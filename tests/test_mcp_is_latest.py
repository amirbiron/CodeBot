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
    :func:`test_a_tie_on_the_top_number_reads_null_for_the_tied_versions`.
    """
    old_id, new_id = _two_versions(mcp)

    new = _read(mcp, file_id=new_id)
    assert new["file"]["is_latest"] is True and new["file"]["code"] == V2

    old = _read(mcp, file_id=old_id)
    assert old["file"]["is_latest"] is False
    assert old["file"]["code"] == V1 and old["file"]["content_sha256"] == _sha(V1)


def test_a_tie_on_the_top_number_reads_null_for_the_tied_versions(mcp, store):
    """שני מסמכים פעילים עם המספר העליון — ``null`` לשניהם, ו-``false`` לגרסה הישנה.

    מצב כזה קיים בפרודקשן (``Repository.iter_latest_active_versions``: חמש גרסאות פעילות באותו
    ``version`` ב-17.10.2026). הקריאה לפי שם ממיינת לפי ``version`` בלבד, ולכן לא מוגדר איזה
    מהשניים היא מחזירה: ``true`` לאחד מהם היה ניחוש, וגם עלול לא להתאים לקריאה הבאה לפי שם
    (ריוויו CodeRabbit על #3649). הגרסה הישנה אינה בתיקו, ולכן היא ``false`` בוודאות.

    מוטציות שמפילות: להשמיט את זיהוי התיקו — אחד מהשניים ``true``; ולהשוות ``version``
    במקום ``_id`` — שניהם ``true``.
    """
    old_id, new_id = _two_versions(mcp)
    twin = {**latest(store.code_snippets, USER, NAME), "code": "תאום\n"}
    twin.pop("_id")
    store.code_snippets.insert_one(twin)
    same_number = [str(d["_id"]) for d in store.code_snippets.docs if d["version"] == 2]
    assert len(same_number) == 2

    for doc_id in same_number:
        out = _read(mcp, file_id=doc_id)
        assert "is_latest" in out["file"] and out["file"]["is_latest"] is None
    assert _read(mcp, file_id=old_id)["file"]["is_latest"] is False


def test_a_tie_below_the_top_does_not_blur_the_answer(mcp, store):
    """תיקו על מספר **ישן** אינו תיקו על הראש: הגרסה העליונה ``true``, ושתי הישנות ``false``.

    מוטציה שמפילה: לזהות תיקו לפי המספר של הגרסה שנקראה מול השני בסדר, ולא לפי שני
    הראשונים — הישנות יוצאות ``null``.
    """
    first = _call(mcp, "codekeeper_save_file", file_name=NAME, code=V1)
    old_twin = {**latest(store.code_snippets, USER, NAME), "code": "תאום ישן\n"}
    old_twin.pop("_id")
    store.code_snippets.insert_one(old_twin)
    second = _call(mcp, "codekeeper_edit_file", file_name=NAME, old_string="טיוטה ראשונה",
                   new_string="נוסח שני")
    assert second["ok"] is True and second["file"]["version"] == 2

    assert _read(mcp, file_id=second["file"]["id"])["file"]["is_latest"] is True
    for doc_id in [str(d["_id"]) for d in store.code_snippets.docs if d["version"] == 1]:
        assert _read(mcp, file_id=doc_id)["file"]["is_latest"] is False
    assert first["file"]["version"] == 1


def test_the_id_that_was_latest_reads_false_after_a_new_version_while_the_cache_still_has_it(
    mcp, store, monkeypatch
):
    """לפי ``write-from-cached-read``, סעיף 4 בתיקון: מחממים את הגטר המקוּש, שומרים גרסה חדשה
    בלי שהקאש מתבטל, **מוודאים שהקאש עדיין זוכר את הישנה** — ורק אז קוראים לפי האיידי שלה.

    ביטול הקאש מדומה ככושל, אחרת השמירה עצמה הייתה מנקה אותו והבדיקה לא הייתה בודקת כלום;
    והאוסף עטוף ב-``StableKeyCollection``, אחרת הקאש בדמה לא היה ישן גם בלי שום ביטול (ראו שם).

    מוטציה שמפילה: הגטר המקוּש (``dbm.get_latest_version``) במקום ``get_latest_version_ids_fresh``
    ב-``_is_latest_field`` — הגרסה שנדרסה מסומנת ``true``.
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

    מוטציה שמפילה: להשמיט את בדיקת ``is_active_version`` — השאילתה לפי שם לא מוצאת גרסה
    פעילה, והשדה יוצא ``null``.
    """
    old_id, new_id = _two_versions(mcp)
    # הסל כמו שמחיקה רכה משאירה אותו: ``is_active: False`` על כל הגרסאות (``file_deletion``).
    # ``Repository.delete_file`` עצמו עובר ב-``distinct``, שהדמה המשותפת אינה מממשת.
    store.code_snippets.update_many({"user_id": USER, "file_name": NAME}, {"$set": {"is_active": False}})

    real = store.dbm.get_latest_version_ids_fresh
    lookups: list[tuple] = []

    def counted(*args, **kwargs):
        lookups.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(store.dbm, "get_latest_version_ids_fresh", counted)
    for doc_id in (old_id, new_id):
        out = _read(mcp, file_id=doc_id)
        assert out["found"] is True and out["file"]["is_active"] is False
        assert "is_latest" not in out["file"]
    assert lookups == []


def test_a_newer_version_in_the_recycle_bin_does_not_make_the_active_one_stale(mcp, store):
    """גרסה פעילה, וגרסה עם מספר גבוה יותר **בסל** — הפעילה היא האחרונה, כמו בקריאה לפי שם.

    השאילתה של ``Repository._fetch_latest_version`` מסננת לפי ``ACTIVE_VERSION_FILTER``, אבל
    המסלול שלה לאוסף בזיכרון — זה שרץ בטסטים — לא סינן כלום, והחזיר את הגרסה שבסל כ"אחרונה":
    בטסטים קריאה לפי שם החזירה קובץ אחר מהייצור. עכשיו שני המסלולים, וגם
    ``_fetch_latest_version_ids``, עוברים ב-``Repository._in_memory_latest_order``.

    נופל על הקוד שלפני: ``false``, וגם הקריאה לפי השם מחזירה את הגרסה שבסל.
    """
    first = _call(mcp, "codekeeper_save_file", file_name=NAME, code=V1)
    active_id = first["file"]["id"]
    trashed = {**latest(store.code_snippets, USER, NAME), "version": 2, "code": V2, "is_active": False}
    trashed.pop("_id")
    store.code_snippets.insert_one(trashed)

    assert _read(mcp, file_name=NAME)["file"]["id"] == active_id
    assert _read(mcp, file_id=active_id)["file"]["is_latest"] is True


class _NoMemoryPath:
    """האוסף בלי ``docs`` — כדי שהקריאה תגיע לשאילתה במסד ולא למסלול של האוסף בזיכרון.

    ``find`` עם ``file_name`` בשאילתה נרשם ב-``finds`` (בלי ``self``), ונענה לפי ``answer``.
    ``with_options`` נרשם ומחזיר את העטיפה עצמה — אחרת הוא היה מחזיר את האוסף הפנימי, והקריאה
    הייתה עוקפת את העטיפה. כל השאר עובר לאוסף הפנימי כמו שהוא.
    """

    def __init__(self, inner, answer):
        self._inner = inner
        self._answer = answer
        self.finds: list[dict] = []
        self.options: list[dict] = []

    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return self

    def find(self, q=None, *args, **kwargs):
        if q and "file_name" in q:
            self.finds.append({"q": q, "args": args, **kwargs})
            return self._answer(self._inner)
        return self._inner.find(q, *args, **kwargs)

    def __getattr__(self, name):
        if name == "docs" or name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._inner, name)


def test_when_the_lookup_by_name_fails_the_read_still_answers_with_null(mcp, store, monkeypatch):
    """השאילתה לפי שם נכשלת (``PyMongoError``) — הקריאה לפי איידי מצליחה, ו-``is_latest`` הוא ``null``.

    הכשל אמיתי ועובר ב-``Repository._fetch_latest_version_ids`` האמיתי, שתופס ``PyMongoError``
    ומחזיר ``None``. קריאה לפי ``_id`` עוברת כרגיל.

    ``null`` ולא ``false``: ``false`` היה שולח את הסוכן לקרוא שוב לפי שם בלי סיבה. ולא נעדר:
    נעדר נראה כמו גרסה שבסל.

    מוטציה שמפילה: ``bool(heads) and ...`` במקום ``None`` — השדה יוצא ``false``.
    """
    from pymongo.errors import PyMongoError

    old_id, new_id = _two_versions(mcp)

    def fails(inner):
        raise PyMongoError("simulated failure of the lookup by name")

    collection = _NoMemoryPath(store.code_snippets, fails)
    monkeypatch.setattr(store.dbm, "collection", collection)
    out = _read(mcp, file_id=new_id)

    assert out["found"] is True and out["file"]["code"] == V2
    assert "is_latest" in out["file"] and out["file"]["is_latest"] is None
    assert len(collection.finds) == 1 and collection.finds[0]["q"]["file_name"] == NAME


def test_the_lookup_asks_the_primary_for_two_ids_in_the_order_of_the_read_by_name(mcp, store, monkeypatch):
    """המסלול במסד, כפי שהוא נשלח ל-pymongo: אותו מסנן ואותו מיון של הקריאה לפי שם, היטלה ל-
    ``_id`` ו-``version`` בלבד, שני מסמכים, ומה-primary.

    **בלי התוכן** (ריוויו Cubic על #3649): עד התיקון ההשוואה נשענה על ``_latest_fresh``, שמושכת את
    המסמך כולו — עד ``MAX_CODE_SIZE`` תווים בכל קריאה לפי איידי — בשביל ``_id``. **מה-primary**
    (ריוויו CodeRabbit): ``readPreference`` בכתובת החיבור היה יכול להפנות את השאלה למשני שעוד לא
    ראה את השמירה האחרונה.

    "אותו מסנן ואותו מיון" נבדק מול הקריאה לפי שם עצמה, דרך אותה עטיפה: ``find_one`` שלה נרשם
    ומושווה. שתיהן קוראות את ``Repository._latest_by_name_filter`` ואת ``_LATEST_BY_NAME_SORT``.

    לא נבדק כאן מול ``mongod`` אמיתי — רק שהקריאה ל-pymongo היא זו (``find(filter, projection,
    sort=..., limit=...)``, הפרמטרים של ``Cursor`` ב-pymongo 4.15.3).
    """
    from pymongo import ReadPreference

    old_id, new_id = _two_versions(mcp)

    def top_two(inner):
        ordered = sorted((d for d in inner.docs if d.get("is_active") is True),
                         key=lambda d: d["version"], reverse=True)
        return iter([{"_id": d["_id"], "version": d["version"]} for d in ordered[:2]])

    collection = _NoMemoryPath(store.code_snippets, top_two)
    by_name_calls: list[dict] = []
    real_find_one = store.code_snippets.find_one

    def find_one(q=None, *args, **kwargs):
        if q and "file_name" in q:
            by_name_calls.append({"q": q, **kwargs})
        return real_find_one(q, *args, **kwargs)

    monkeypatch.setattr(store.code_snippets, "find_one", find_one)
    monkeypatch.setattr(store.dbm, "collection", collection)

    assert _read(mcp, file_id=new_id)["file"]["is_latest"] is True
    assert _read(mcp, file_id=old_id)["file"]["is_latest"] is False

    lookup = collection.finds[0]
    assert lookup["args"] == ({"_id": 1, "version": 1},)
    assert lookup["limit"] == 2
    assert collection.options[0] == {"read_preference": ReadPreference.PRIMARY}

    store.dbm.get_latest_version_fresh(USER, NAME)  # הקריאה לפי שם, דרך אותה עטיפה
    assert lookup["q"] == by_name_calls[-1]["q"] == {"user_id": USER, "file_name": NAME, "is_active": True}
    assert lookup["sort"] == by_name_calls[-1]["sort"]


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
