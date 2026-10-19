"""חיפוש שרת של pymongo שהתחיל בתוך ``freeze_time`` עדיין מוותר בזמן — גם אחרי שההקפאה נגמרת.

**למה הקובץ הזה קיים.** ב-CI של #3585 (ריצה 39171604667) נתקעו שמונה
טסטים על ``Timeout >60.0s``. תהליכון רקע נכנס לחיפוש שרת מונגו בזמן ש-
``tests/test_israel_timezone_display.py`` הקפיא את הזמן, והחזיק את ``_DB_INIT_LOCK`` לתמיד.
‏freezegun מקפיא את ``time.monotonic`` לכל התהליכונים, ו-pymongo מחשב ממנו את המועד האחרון של
החיפוש: מהשעון המזויף זה כ-1.79 מיליארד, והשעון האמיתי לא מגיע לשם. ``tests/conftest.py`` מוסיף
את ``pymongo`` לרשימת ההתעלמות של freezegun, והקובץ הזה מוכיח שזה עובד.

**ולמה תהליכון ולא קריאה ישירה.** הכשל דורש שהחיפוש **יתחיל** בזמן מוקפא **וימשיך** אחריו.
בתהליכון אחד אי אפשר לצאת מההקפאה בזמן שהוא חסום בחיפוש. ההקפאה נשארת עד שהתהליכון מסיים או
עד שנייה אחת — ארוך פי שלושה מהתקרה — כך שהמועד האחרון נקבע בוודאות בזמן מוקפא, בלי להמר על תזמון.
"""

from __future__ import annotations

import threading

from freezegun import freeze_time
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError

#: ``.invalid`` שמור לשמות שאינם נפתרים לעולם (RFC 2606, סעיף 2).
UNREACHABLE = "mongodb://no-such-host.invalid:27017"
SELECTION_TIMEOUT_MS = 300


def test_a_server_search_that_starts_inside_freeze_time_still_gives_up():
    outcome: dict = {}

    def dial() -> None:
        client = MongoClient(UNREACHABLE, serverSelectionTimeoutMS=SELECTION_TIMEOUT_MS)
        try:
            client.server_info()
            outcome["result"] = "connected"
        except ServerSelectionTimeoutError:
            outcome["result"] = "gave_up"
        finally:
            client.close()

    searcher = threading.Thread(target=dial, name="mongo-search-in-frozen-time", daemon=True)
    with freeze_time("2026-08-13 22:30:00"):
        searcher.start()
        searcher.join(1.0)
    searcher.join(5.0)

    assert not searcher.is_alive(), (
        "חיפוש השרת עדיין רץ אחרי שההקפאה נגמרה — pymongo מחשב את המועד האחרון מהשעון "
        "המוקפא. ודאו ש-tests/conftest.py מוסיף את pymongo ל-ignore list של freezegun."
    )
    assert outcome == {"result": "gave_up"}
