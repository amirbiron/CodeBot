"""האינדקס של הסריקה של גיבויי ה-Drive בוובאפ — מול הפילטר שהסריקה באמת שולחת.

``webapp/backup_scheduler.py`` תופס כל כמה דקות משתמשים שהגיע זמן הגיבוי שלהם (``_drive_claim_filter``), על כל אוסף ``users``. בלי אינדקס זו סריקה מלאה בכל פעם. הבדיקה כאן מקבעת שמסלול העלייה (``DatabaseManager._create_indexes``) מבקש אינדקס על שני השדות של הפילטר, בסדר ESR: קודם השדה שהפילטר בודק בשוויון (``$in``), ואחריו השדה שהוא בודק בטווח. שינוי שם של שדה, או פילטר שמוסיף שדה, מפיל אותה.

שהאינדקס הזה הוא מה שמונגו בוחרת לפילטר — ``explain`` — נבדק מול שרת אמיתי ב-``tests/test_webapp_drive_scan_index_mongo.py``.
"""

from __future__ import annotations

import types

import drive_owner
from database.manager import DatabaseManager
from webapp.backup_scheduler import _drive_claim_filter

INDEX_NAME = "users_webapp_drive_schedule"


class _Coll:
    def create_indexes(self, indexes):
        return None

    def list_indexes(self):
        return []


class _DB:
    def __getitem__(self, name):
        return _Coll()


def requested_scan_index() -> list:
    """המפתחות שמסלול העלייה מבקש לאינדקס של הסריקה — בשמו, באוסף ``users``."""
    requested = []
    fake_self = types.SimpleNamespace(
        collection=_Coll(),
        large_files_collection=_Coll(),
        db=_DB(),
        backup_ratings_collection=_Coll(),
        internal_shares_collection=_Coll(),
        community_library_collection=_Coll(),
        snippets_collection=_Coll(),
        safe_create_index=lambda collection, keys, **kwargs: requested.append((collection, list(keys), kwargs)),
    )
    DatabaseManager._create_indexes(fake_self)
    matches = [keys for collection, keys, kwargs in requested if collection == "users" and kwargs.get("name") == INDEX_NAME]
    assert len(matches) == 1, f"מסלול העלייה מבקש את {INDEX_NAME} {len(matches)} פעמים"
    return matches[0]


def test_startup_requests_an_index_on_the_fields_of_the_scan_filter_equality_first():
    scan_filter = _drive_claim_filter("2026-10-05T00:00:00+00:00")
    equality = [field for field, cond in scan_filter.items() if "$in" in cond]
    ranged = [field for field, cond in scan_filter.items() if "$lte" in cond]
    assert len(equality) == 1 and len(ranged) == 1 and set(scan_filter) == set(equality + ranged)

    assert requested_scan_index() == [(equality[0], 1), (ranged[0], 1)]


def test_the_scan_filter_reads_the_webapp_schedule_only():
    prefs_field = drive_owner.drive_fields(drive_owner.WEBAPP).prefs
    assert all(field.startswith(f"{prefs_field}.") for field in _drive_claim_filter("2026-10-05T00:00:00+00:00"))
