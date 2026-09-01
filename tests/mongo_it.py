"""‏harness משותף לבדיקות שרצות מול **מונגו אמיתי**.

מתי הן רצות: כש-``MONGODB_URL`` מוגדר והשרת נענה. ב-CI זה תמיד — הג'וב
``Unit Tests`` מרים ``mongo:6.0`` כשירות (ראו ``.github/workflows/ci.yml``).
מקומית הן מדלגות, כדי שהרצה רגילה תישאר מהירה.

**למה זה כאן ולא משוכפל בכל קובץ:** ה-harness הזה חזר מילה במילה בשני
קבצים, וכפילות של קוד בדיקה היא כפילות של **החלטות בטיחות** — סורג
המחיקה, ה-``tz_aware``, ותנאי הדילוג. עותק שמתעדכן לבד הוא בדיוק המקום
שבו הבדיקה מפסיקה לרוץ בשקט.

``tz_aware=True`` אינו פרט טכני: בלעדיו pymongo מחזיר ``datetime`` נאיבי,
והשוואות בין תאריכים שנשלפו למודעים-לאזור זורקות ``TypeError`` — שנבלע
ב-``except Exception`` ומשתיק את הבדיקה במקום להפיל אותה.

**בטיחות מחיקה:** כל הרצה עובדת על מסד עם שם ייחודי משלה, וה-teardown
מוודא שהשם תואם לתחילית הצפויה לפני ``drop_database``. מסד שלא נוצר כאן
לא נמחק כאן.
"""

from __future__ import annotations

import os
import uuid
from datetime import timezone
from typing import Iterator

import pytest

pymongo = pytest.importorskip("pymongo")

from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402

MONGO_URL = os.environ.get("MONGODB_URL", "").strip()


def server_is_reachable(url: str) -> bool:
    """האם יש שרת בקצה השני. בלי זה הבדיקות היו נתלות עד timeout ארוך."""
    if not url:
        return False
    try:
        client = pymongo.MongoClient(
            url, serverSelectionTimeoutMS=2000, tz_aware=True, tzinfo=timezone.utc
        )
        client.admin.command("ping")
        client.close()
        return True
    except (ServerSelectionTimeoutError, Exception):
        return False


#: נמדד פעם אחת בטעינת המודול, ולא פעם לכל קובץ בדיקות.
MONGO_AVAILABLE = server_is_reachable(MONGO_URL)

#: ``pytestmark = requires_mongo`` בראש קובץ בדיקות שדורש מונגו אמיתי.
requires_mongo = pytest.mark.skipif(
    not MONGO_AVAILABLE,
    reason="דורש MONGODB_URL עם שרת מונגו נגיש (קיים ב-CI, לא בהכרח מקומית)",
)


def make_mongo_db_fixture(prefix: str):
    """מייצר fixture ``mongo_db`` עם תחילית ייעודית לקובץ הקורא.

    התחילית אינה קוסמטית — היא הסורג שמונע מחיקה של מסד שלא נוצר כאן,
    ולכן היא פרמטר מפורש ולא ערך משותף.
    """
    if not prefix:
        raise ValueError("חובה תחילית ייעודית — היא סורג הבטיחות של המחיקה")

    @pytest.fixture
    def mongo_db() -> Iterator["pymongo.database.Database"]:
        name = f"{prefix}{uuid.uuid4().hex[:12]}"
        client = pymongo.MongoClient(MONGO_URL, tz_aware=True, tzinfo=timezone.utc)
        db = client[name]
        try:
            yield db
        finally:
            assert name.startswith(prefix), f"סירוב למחוק מסד שאינו של הבדיקות: {name}"
            try:
                client.drop_database(name)
            finally:
                client.close()

    return mongo_db
