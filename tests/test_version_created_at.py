"""זמן שמירת הגרסה הוא שדה משלו, והעברת נעיצה אינה נוגעת בהיסטוריה.

**למה זה קיים.** כל "גרסה" היא מסמך נפרד ב-``code_snippets``, ותצוגת
ההיסטוריה הציגה לכל אחת את ``updated_at`` שלה. אבל ``updated_at`` הוא שדה
של ה**קובץ** ולא של השורה, ומישהו רשאי לכתוב אותו מחדש: שמירה של קובץ
**נעוץ** העבירה את הנעיצה לגרסה החדשה, ובאותו ``$set`` חתמה את שעתה על כל
הגרסאות הקודמות. התוצאה בפרודקשן — 21 גרסאות של אותו קובץ שכולן הציגו
"04:52 16/09", הרגע שבו נשמרה הגרסה ה-20.

שתי הבדיקות המרכזיות כאן נכשלות על הקוד שלפני התיקון: אחת על החותמות
שזזו, ואחת על היעדר ``version_created_at``.

מוסכמת הריפו: fakes בעבודת יד, בלי mongomock, בלי ייבוא מ-conftest.
"""

import types
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

from file_dates import VERSION_CREATED_AT_FIELD, version_created_at

ORIGINAL = datetime(2020, 1, 1, 8, 30, tzinfo=timezone.utc)


class _Result:
    def __init__(self, inserted_id: Any = None, matched: int = 0, modified: int = 0):
        self.inserted_id = inserted_id
        self.matched_count = matched
        self.modified_count = modified


class InMemoryCollection:
    """אוסף Mongo מינימלי: ``find_one`` עם sort/projection, insert, update."""

    def __init__(self) -> None:
        self.docs: List[Dict[str, Any]] = []
        self.fail_update_many = False

    def insert_one(self, doc: Dict[str, Any]):
        doc = dict(doc)
        doc.setdefault("_id", f"id_{len(self.docs) + 1}")
        doc.setdefault("is_active", True)
        self.docs.append(doc)
        return _Result(inserted_id=doc["_id"])

    def find_one(self, query: Dict[str, Any], projection=None, sort=None):
        items = self._filter(query)
        if sort:
            for key, direction in reversed(list(sort)):
                items.sort(key=lambda d: d.get(key, 0), reverse=(direction < 0))
        if not items:
            return None
        doc = dict(items[0])
        if projection:
            keep = {k for k, v in projection.items() if v}
            if keep:
                doc = {k: v for k, v in doc.items() if k in keep or k == "_id"}
        return doc

    def find(self, query: Dict[str, Any], projection=None):
        return [dict(d) for d in self._filter(query)]

    def update_one(self, query: Dict[str, Any], update: Dict[str, Any]):
        items = self._filter(query)
        if not items:
            return _Result(matched=0, modified=0)
        items[0].update(update.get("$set", {}))
        return _Result(matched=1, modified=1)

    def update_many(self, query: Dict[str, Any], update: Dict[str, Any]):
        if self.fail_update_many:
            raise RuntimeError("mongo is down")
        items = self._filter(query)
        set_data = update.get("$set", {})
        for doc in items:
            doc.update(set_data)
        return _Result(matched=len(items), modified=len(items))

    def _filter(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        def matches(doc: Dict[str, Any]) -> bool:
            for key, expected in query.items():
                if isinstance(expected, dict) and "$ne" in expected:
                    if doc.get(key) == expected["$ne"]:
                        return False
                # ``$in`` — ירושת המועדף (``file_favorite.py``) שואלת את כל השמות של הקובץ בשאילתה אחת. בלי זה ``doc.get(key) != expected`` משווה ערך למילון, לעולם אינו מתאים, והקובץ נראה לא מסומן.
                elif isinstance(expected, dict) and "$in" in expected:
                    if doc.get(key) not in list(expected["$in"]):
                        return False
                elif doc.get(key) != expected:
                    return False
            return True

        return [d for d in self.docs if matches(d)]


class FakeManager:
    def __init__(self) -> None:
        self.collection = InMemoryCollection()
        self.large_files_collection = InMemoryCollection()
        self.db = types.SimpleNamespace()


@pytest.fixture()
def repo():
    from database.repository import Repository

    return Repository(FakeManager())


def _snippet(**overrides):
    from database.models import CodeSnippet

    kwargs: Dict[str, Any] = {
        "user_id": 1,
        "file_name": "handoff.md",
        "code": "# שלום\n",
        "programming_language": "markdown",
    }
    kwargs.update(overrides)
    return CodeSnippet(**kwargs)


def _seed_pinned(collection: InMemoryCollection, versions: int = 3) -> List[datetime]:
    """כמה גרסאות היסטוריות, כל אחת עם חותמת משלה. האחרונה נעוצה."""
    stamps: List[datetime] = []
    for v in range(1, versions + 1):
        stamp = ORIGINAL + timedelta(days=v)
        stamps.append(stamp)
        collection.insert_one({
            "user_id": 1,
            "file_name": "handoff.md",
            "code": f"# גרסה {v}\n",
            "programming_language": "markdown",
            "version": v,
            "is_active": True,
            "created_at": ORIGINAL,
            "updated_at": stamp,
            VERSION_CREATED_AT_FIELD: stamp,
            "is_pinned": v == versions,
            "pinned_at": ORIGINAL if v == versions else None,
            "pin_order": 6 if v == versions else 0,
        })
    return stamps


def _versions(collection: InMemoryCollection, file_name: str = "handoff.md") -> List[Dict[str, Any]]:
    docs = [d for d in collection.docs if d.get("file_name") == file_name]
    return sorted(docs, key=lambda d: int(d.get("version", 0) or 0))


# --- הבאג עצמו ------------------------------------------------------------


def test_saving_a_pinned_file_does_not_restamp_older_versions(repo):
    """הבאג שדווח: שמירה של קובץ נעוץ חתמה את שעתה על כל ההיסטוריה."""
    before = _seed_pinned(repo.manager.collection, versions=3)

    assert repo.save_code_snippet(_snippet(code="# גרסה 4\n")) is True

    docs = _versions(repo.manager.collection)
    assert [d["version"] for d in docs] == [1, 2, 3, 4]
    assert [d["updated_at"] for d in docs[:3]] == before, "החותמות של הגרסאות הישנות זזו"


def test_three_pinned_saves_keep_every_earlier_stamp(repo):
    """שלוש עריכות ברצף — אחרי השלישית הזמנים של הישנות עדיין לא זזו."""
    before = _seed_pinned(repo.manager.collection, versions=2)

    for n in range(3, 6):
        assert repo.save_code_snippet(_snippet(code=f"# גרסה {n}\n")) is True

    docs = _versions(repo.manager.collection)
    assert [d["version"] for d in docs] == [1, 2, 3, 4, 5]
    assert [d["updated_at"] for d in docs[:2]] == before
    # ולכל גרסה חדשה זמן שמירה משלה, ולא חותמת משותפת.
    saved = [d[VERSION_CREATED_AT_FIELD] for d in docs[2:]]
    assert len(set(saved)) == len(saved), saved


def test_pin_still_moves_to_the_new_version(repo):
    """ההצמדה עוברת קדימה כמו קודם — התיקון לא ויתר על ההתנהגות הזו."""
    _seed_pinned(repo.manager.collection, versions=3)

    assert repo.save_code_snippet(_snippet(code="# גרסה 4\n")) is True

    docs = _versions(repo.manager.collection)
    assert [bool(d.get("is_pinned")) for d in docs] == [False, False, False, True]
    assert docs[-1].get("pin_order") == 6, "סדר הנעיצה נשמר בהעברה"
    assert docs[-1].get("pinned_at") == ORIGINAL, "מועד הנעיצה המקורי נשמר"


def test_favorite_file_is_not_touched_by_the_pin_path(repo):
    """קובץ מועדף שאינו נעוץ: מסלול העברת הנעיצה לא נדלק בכלל."""
    stamp = ORIGINAL + timedelta(days=1)
    repo.manager.collection.insert_one({
        "user_id": 1,
        "file_name": "handoff.md",
        "code": "# גרסה 1\n",
        "programming_language": "markdown",
        "version": 1,
        "is_active": True,
        "created_at": ORIGINAL,
        "updated_at": stamp,
        VERSION_CREATED_AT_FIELD: stamp,
        "is_favorite": True,
        "favorited_at": ORIGINAL,
    })

    assert repo.save_code_snippet(_snippet(code="# גרסה 2\n")) is True

    docs = _versions(repo.manager.collection)
    assert docs[0]["updated_at"] == stamp
    assert bool(docs[-1].get("is_favorite")) is True, "המועדף עבר לגרסה החדשה"


# --- השדה החדש ------------------------------------------------------------


def test_every_saved_version_carries_its_own_write_time(repo):
    """כל גרסה נושאת ``version_created_at``, גם הראשונה."""
    assert repo.save_code_snippet(_snippet(file_name="new.md")) is True
    assert repo.save_code_snippet(_snippet(file_name="new.md", code="#2\n")) is True

    docs = _versions(repo.manager.collection, "new.md")
    for doc in docs:
        assert isinstance(doc.get(VERSION_CREATED_AT_FIELD), datetime), doc


def test_restored_backup_row_gets_the_write_time_not_the_backup_time(repo):
    """שחזור מגיבוי נושא ``updated_at`` היסטורי — והשורה נכתבה עכשיו.

    בלי ההפרדה הזו היסטוריה של קובץ משוחזר הייתה יוצאת מהסדר: גרסה 2
    מוצגת כמוקדמת מגרסה 1.
    """
    from database.models import CodeSnippet

    old = datetime(2019, 5, 5, 12, 0, tzinfo=timezone.utc)
    snippet = CodeSnippet(
        user_id=1,
        file_name="restored.md",
        code="# מהגיבוי\n",
        programming_language="markdown",
        created_at=old,
        updated_at=old,
    )
    assert repo.save_code_snippet(snippet) is True

    doc = _versions(repo.manager.collection, "restored.md")[0]
    assert doc["updated_at"] == old, "התאריך מהגיבוי נשמר"
    assert doc[VERSION_CREATED_AT_FIELD] > old, "זמן הכתיבה הוא עכשיו"


# --- הקורא ----------------------------------------------------------------


def test_reader_prefers_the_stored_field():
    stamp = datetime(2021, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert version_created_at({VERSION_CREATED_AT_FIELD: stamp, "updated_at": ORIGINAL}) == stamp


def test_reader_falls_back_to_the_objectid_for_legacy_rows():
    """מסמך ישן בלי השדה: הזמן נגזר מה-ObjectId, לא מה-``updated_at`` הדרוס."""
    ObjectId = pytest.importorskip("bson").ObjectId
    oid = ObjectId()
    clobbered = datetime.now(timezone.utc) + timedelta(days=30)

    got = version_created_at({"_id": oid, "updated_at": clobbered})

    assert got == oid.generation_time
    assert got != clobbered


def test_reader_falls_back_to_updated_at_without_a_real_objectid():
    """מזהה מחרוזתי (סטאבים, ייבוא) — לא מחזירים ערך שאינו תאריך."""
    assert version_created_at({"_id": "id_1", "updated_at": ORIGINAL}) == ORIGINAL


def test_reader_rejects_non_dict():
    assert version_created_at(None) is None
    assert version_created_at("not a doc") is None


# --- העברת הנעיצה כמסלול משותף -------------------------------------------


def test_transfer_pin_clears_only_the_pinned_rows():
    from database.repository import transfer_pin_to_new_version

    coll = InMemoryCollection()
    _seed_pinned(coll, versions=3)
    new = coll.insert_one({
        "user_id": 1, "file_name": "handoff.md", "version": 4,
        "is_active": True, "is_pinned": True, "updated_at": ORIGINAL,
    })

    errors = transfer_pin_to_new_version(
        coll, 1, file_name="handoff.md", new_version_id=new.inserted_id
    )

    assert errors == []
    docs = _versions(coll)
    assert [bool(d.get("is_pinned")) for d in docs] == [False, False, False, True]
    assert all("updated_at" in d for d in docs)
    assert docs[2]["updated_at"] == ORIGINAL + timedelta(days=3), "חותמת ההיסטוריה לא זזה"


def test_transfer_pin_also_clears_the_previous_file_name():
    """עריכה ששינתה גם את השם — הנעיצה על השם הישן חייבת להתנקות."""
    from database.repository import transfer_pin_to_new_version

    coll = InMemoryCollection()
    coll.insert_one({
        "user_id": 1, "file_name": "old.md", "version": 1,
        "is_active": True, "is_pinned": True, "pin_order": 2,
    })
    new = coll.insert_one({
        "user_id": 1, "file_name": "new.md", "version": 2,
        "is_active": True, "is_pinned": True, "pin_order": 2,
    })

    errors = transfer_pin_to_new_version(
        coll, 1, file_name="new.md", new_version_id=new.inserted_id,
        previous_file_name="old.md",
    )

    assert errors == []
    old_doc = [d for d in coll.docs if d["file_name"] == "old.md"][0]
    assert bool(old_doc.get("is_pinned")) is False


def test_transfer_pin_reports_failure_instead_of_swallowing_it():
    """ערוץ הכשל הוא ערך ההחזרה, ולעולם לא חריגה — ולא שקט."""
    from database.repository import transfer_pin_to_new_version

    coll = InMemoryCollection()
    coll.fail_update_many = True

    errors = transfer_pin_to_new_version(
        coll, 1, file_name="handoff.md", new_version_id="x"
    )

    assert len(errors) == 1
    assert errors[0]["scope"] == "current_name"
    assert "mongo is down" in errors[0]["error"]


def test_save_emits_an_event_when_the_unpin_fails(repo, monkeypatch):
    """כשל בהעברת הנעיצה אינו מבטל את השמירה, אבל גם אינו נבלע."""
    import database.repository as repository_module

    _seed_pinned(repo.manager.collection, versions=2)
    repo.manager.collection.fail_update_many = True

    seen: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        repository_module, "emit_event",
        lambda event, severity="info", **fields: seen.append({"event": event, **fields}),
    )

    assert repo.save_code_snippet(_snippet(code="# גרסה 3\n")) is True
    assert [e["event"] for e in seen] == ["save_snippet_unpin_failed"]


# --- שינוי שם --------------------------------------------------------------


def test_rename_does_not_restamp_history(repo):
    """שינוי שם נוגע בכל הגרסאות — אבל רק בשם שלהן."""
    before = _seed_pinned(repo.manager.collection, versions=3)

    assert repo.rename_file(1, "handoff.md", "handoff-v2.md") is True

    docs = _versions(repo.manager.collection, "handoff-v2.md")
    assert len(docs) == 3
    assert [d["updated_at"] for d in docs[:2]] == before[:2], "היסטוריה נחתמה מחדש"


def test_rename_refreshes_the_latest_version_only(repo):
    """הקובץ **כן** השתנה — ולכן הגרסה האחרונה מקבלת חותמת חדשה."""
    before = _seed_pinned(repo.manager.collection, versions=3)

    assert repo.rename_file(1, "handoff.md", "handoff-v2.md") is True

    docs = _versions(repo.manager.collection, "handoff-v2.md")
    assert docs[-1]["updated_at"] > before[-1]


@pytest.fixture(autouse=True)
def _no_autocomplete_cache(monkeypatch):
    """מנטרל את אינוולידציית ה-autocomplete — היא אינה נושא הבדיקה."""
    try:
        import autocomplete_manager
    except Exception:  # pragma: no cover - סביבה בלי המודול
        return
    monkeypatch.setattr(
        autocomplete_manager.autocomplete, "invalidate_cache", lambda *a, **k: None,
        raising=False,
    )
