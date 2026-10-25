"""הדף של "הגרסה האחרונה לכל קובץ" מול **מונגו אמיתי** — כמה בייטים המיון מחזיק, ומה חוזר.

מה ש-``tests/test_repository_latest_page.py`` בודק על צורת הצינור, כאן נמדד במסד: ``explain`` על
הצינורות **שהמתודות שלחו** (נרשמו בדרך, ולא עותק שלהם), והשדה ``totalDataSizeSortedBytesEstimate``
של המיון — אותה מדידה שבה נמצאה הבעיה על האשכול (20,106,444 בתים ל-``get_user_file_names`` של
המשתמש הראשי). הגבול כאן הוא שלושה גופי קבצים: הקלט של המיון אינו אמור לגדול עם הקוד בכלל, וכל
הקבצים יחד חוצים אותו בפער גדול. בצורה הקודמת כל אחת מהמתודות נופלת עליו.

ולצד המדידה — שהתשובה נכונה: הגרסה האחרונה הפעילה של כל קובץ, בסדר הנכון, עם השדות שהתבקשו, ועם
הקוד של **הגרסה הזו** כשהוא התבקש.

**מדלגים רק על "אין שרת"** (``_note_threads_harness.mongo_reachable``): כתובת שגויה או אימות שנכשל
מפילים, כי הם תקלת תצורה ולא היעדר שירות.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("pymongo")

from bson.codec_options import CodecOptions, DatetimeConversion  # noqa: E402
from pymongo import ASCENDING, DESCENDING, TEXT  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _note_threads_harness import mongo_reachable, temp_database  # noqa: E402

from database.repository import Repository  # noqa: E402

pytestmark = pytest.mark.skipif(not mongo_reachable(), reason="דורש MONGODB_URL עם שרת מונגו נגיש")

USER = 7
FILES = 40
#: גוף של כ-20KB לגרסה — סדר הגודל שבו התקרה נחצתה אצל המשתמש הראשי (836 קבצים).
BODY = ("def f(x):\n    return x * 2  # שורה בעברית\n" * 600)[:20000]
BODY_BYTES = len(BODY.encode("utf-8"))
_EXPLAIN_CODEC = CodecOptions(datetime_conversion=DatetimeConversion.DATETIME_AUTO, tz_aware=True)


class _Recording:
    """האוסף האמיתי, ו-``aggregate`` נרשם — הצינור שהמתודה שלחה."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.pipelines: list[list] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def aggregate(self, pipeline: Any, *args: Any, **kwargs: Any) -> Any:
        self.pipelines.append(list(pipeline))
        return self._real.aggregate(pipeline, *args, **kwargs)


@pytest.fixture
def seeded():
    """``FILES`` קבצים בשתי גרסאות — זמני עדכון שונים כולם, כדי שהסדר יהיה מוגדר. כל שביעי
    מועדף, עשרת הראשונים בתגית ריפו, ובקובץ אחד הגרסה האחרונה כבר לא פעילה."""
    with temp_database("codebot_latest_page_") as db:
        coll = db.code_snippets
        # כמו ב-``database/manager.py``: ``idx_snippets_latest_version`` ו-``search_text_idx``.
        coll.create_index([("user_id", ASCENDING), ("is_active", ASCENDING), ("file_name", ASCENDING),
                           ("version", DESCENDING)], name="idx_snippets_latest_version")
        coll.create_index([("file_name", TEXT), ("description", TEXT), ("tags", TEXT), ("code", TEXT)],
                          name="search_text_idx")
        base = datetime(2026, 10, 1, tzinfo=timezone.utc)
        docs = []
        for i in range(FILES):
            for version in (1, 2):
                docs.append({
                    "user_id": USER, "file_name": f"file_{i:03d}.py", "version": version,
                    "is_active": not (i == 5 and version == 2),
                    "code": f"# {i}.{version}\n" + BODY, "programming_language": "python",
                    "description": f"תיאור {i}", "tags": ["repo:me/proj"] if i < 10 else ["x"],
                    "is_favorite": i % 7 == 0,
                    "favorited_at": base + timedelta(hours=i) if i % 7 == 0 else None,
                    "updated_at": base + timedelta(minutes=((i * 17) % FILES) * 10 + version),
                })
        docs.append({"user_id": USER + 1, "file_name": "other.py", "version": 1, "is_active": True,
                     "code": BODY, "updated_at": base + timedelta(days=9)})
        coll.insert_many(docs)
        recording = _Recording(coll)
        yield SimpleNamespace(db=db, coll=coll, recording=recording,
                              repo=Repository(SimpleNamespace(collection=recording, db=db)))


def _latest(coll) -> dict[str, dict]:
    """מקור האמת לבדיקה, בפייתון: הגרסה הפעילה הגבוהה של כל קובץ של המשתמש."""
    out: dict[str, dict] = {}
    for doc in coll.find({"user_id": USER, "is_active": True}):
        name = doc["file_name"]
        if name not in out or doc["version"] > out[name]["version"]:
            out[name] = doc
    return out


def _sorted_bytes(db, pipeline: list) -> list[int]:
    explain = db.command("explain", {"aggregate": "code_snippets", "pipeline": pipeline, "cursor": {}},
                         verbosity="executionStats", codec_options=_EXPLAIN_CODEC)
    found: list[int] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "totalDataSizeSortedBytesEstimate":
                    found.append(value)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(explain)
    return found


CALLERS = {
    "get_user_files": lambda r: r.get_user_files(USER, 1000),
    "get_user_files+code": lambda r: r.get_user_files(USER, 1000, projection={"file_name": 1, "code": 1, "_id": 1}),
    "get_user_files_by_repo": lambda r: r.get_user_files_by_repo(USER, "repo:me/proj", 1, 500),
    "search_code": lambda r: r.search_code(USER, "return", limit=1000),
    "get_user_file_names": lambda r: r.get_user_file_names(USER, 1000),
    "get_favorites": lambda r: r.get_favorites(USER, limit=1000),
}


@pytest.mark.parametrize("call", list(CALLERS.values()), ids=list(CALLERS))
def test_the_sort_holds_only_what_the_page_needs(seeded, call):
    """נופל על הצורה הקודמת: שם המיון החזיק את כל הקבצים עם הקוד — עשרות גופים."""
    rows = call(seeded.repo)
    assert rows, "המתודה החזירה ריק — הבדיקה אינה מודדת דבר"

    pipeline = seeded.recording.pipelines[0]
    sorted_bytes = _sorted_bytes(seeded.db, pipeline)
    assert sorted_bytes, "אין מיון בתוכנית — הבדיקה אינה מודדת דבר"
    assert max(sorted_bytes) < 3 * BODY_BYTES, sorted_bytes


def test_the_plain_list_is_the_latest_active_version_of_each_file_newest_first(seeded):
    rows = seeded.repo.get_user_files(USER, 1000)
    latest = _latest(seeded.coll)

    assert [row["_id"] for row in rows] == [
        doc["_id"] for doc in sorted(latest.values(), key=lambda d: d["updated_at"], reverse=True)
    ]
    assert all("code" not in row for row in rows)


def test_a_page_in_the_middle_is_the_same_slice_of_the_same_order(seeded):
    everything = [row["_id"] for row in seeded.repo.get_user_files(USER, 1000)]
    page = [row["_id"] for row in seeded.repo.get_user_files(USER, 10, skip=10)]
    assert page == everything[10:20]


def test_the_drive_backup_gets_the_code_of_the_latest_version_and_nothing_else(seeded):
    """המסלול הכבד: הקוד נשלף אחרי העימוד, ב-``find`` — וחוזר הקוד של **הגרסה שבעמוד**, באותו
    סדר, ועם השדות שהתבקשו בלבד (``updated_at``, ששימש למיון, אינו בתשובה)."""
    rows = seeded.repo.get_user_files(USER, 1000, projection={"file_name": 1, "tags": 1, "code": 1, "_id": 1})
    latest = _latest(seeded.coll)

    assert len(rows) == len(latest)
    for row in rows:
        assert set(row) == {"_id", "file_name", "tags", "code"}, row.keys()
        assert row["code"] == latest[row["file_name"]]["code"]
    order = [doc["_id"] for doc in sorted(latest.values(), key=lambda d: d["updated_at"], reverse=True)]
    assert [row["_id"] for row in rows] == order


def test_the_names_come_newest_first_without_the_sort_field(seeded):
    names = seeded.repo.get_user_file_names(USER, 1000)
    latest = _latest(seeded.coll)
    assert names == [d["file_name"] for d in sorted(latest.values(), key=lambda d: d["updated_at"], reverse=True)]


def test_the_favorites_come_with_their_code_newest_favorite_first(seeded):
    rows = seeded.repo.get_favorites(USER, limit=1000)
    favorites = [d for d in _latest(seeded.coll).values() if d.get("is_favorite")]

    assert [row["_id"] for row in rows] == [
        d["_id"] for d in sorted(favorites, key=lambda d: d["favorited_at"], reverse=True)
    ]
    assert all(row["code"] == next(f["code"] for f in favorites if f["_id"] == row["_id"]) for row in rows)
