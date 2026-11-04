"""הגרסה האחרונה של קובץ — הכלל שרשימת הקבצים בוובאפ והגיבוי האישי חולקים.

ב-Ck כל עריכה יוצרת מסמך חדש ב-``code_snippets``, ושמירת גרסה חדשה אינה מכבה את הקודמת: כל הגרסאות של קובץ נשארות ``is_active``. לכן כל מקום שמציג או מייצא "את הקובץ" צריך לבחור גרסה אחת מתוכן, ושני מקומות שבוחרים אחרת מציגים שני קבצים שונים באותו שם. רשימת הקבצים בוובאפ (``_latest_version_per_file_stages`` ב-``webapp/app.py``) והגיבוי האישי (``Repository.iter_latest_active_versions``) קוראים את הכלל מכאן, כדי שהגיבוי ישמור בדיוק את הגרסה שהמשתמש רואה ברשימה.

המודול טהור בכוונה — ``typing`` ותו לא, בלי Flask ובלי מסד. אותה תבנית של ``file_dates`` ו-``file_description``, ומאותה סיבה: ייבוא מ-``database.repository`` ברמת המודול מפיל את ``import webapp.app`` בסביבה בלי ``MONGODB_URL``, ולכן קבוע שיושב שם היה מחייב בוובאפ ``try/except`` עם עותק fallback — כלומר שני עותקים של הכלל, בדיוק מה שהמודול הזה בא למנוע.

⚠️ **לא כל הקוד בוחר כך.** יש מקומות ששוברים שוויון לפי ``updated_at`` לפני ``_id`` (למשל ``database.manager.is_latest_active_snippet`` וצינור החיפוש ב-``search_engine.py``), ויש צינורות ב-``database/repository.py`` שלוקחים ``$first`` אחרי מיון לפי ``version`` בלבד, בלי שובר שוויון — וכך גם ``Repository._fetch_latest_version``, הקריאה לפי שם, שממיינת לפי ``version`` בלבד. בשתי גרסאות עם אותו ``version`` הם יכולים לבחור גרסה אחרת מזו שכאן. הם לא אוחדו עם הכלל הזה: איחוד משנה את מה שהם מחזירים, וזה שינוי נפרד.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

#: מי מועמד בכלל להיות "הגרסה האחרונה": גרסה שאינה בסל המיחזור. מחיקה רכה מעבירה את גרסאות הקובץ ל-``is_active: False`` (``Repository.delete_file``), והן נשארות באוסף עד שה-TTL של הסל מוחק אותן. ``Repository._fetch_latest_version`` — הקריאה לפי שם — מסנן לפי המילון הזה, ו-:func:`is_active_version` שואל את אותה שאלה על מסמך שכבר נקרא. שני הצדדים קוראים מכאן, כדי שלא ייווצר פרדיקט שני של "בסל".
ACTIVE_VERSION_FILTER: Dict[str, bool] = {"is_active": True}


def is_active_version(doc: Mapping[str, Any]) -> bool:
    """האם המסמך עונה על :data:`ACTIVE_VERSION_FILTER` — כלומר אינו בסל המיחזור.

    ``is`` ולא ``==``: הערכים במסנן בוליאניים, וכל הכותבים ל-``code_snippets`` כותבים ``is_active`` בוליאני (``CodeSnippet.is_active: bool``). בפייתון ``1 == True``, ולכן ``==`` היה מכריז "פעיל" על ערך שאינו בוליאני. אם מסנן השוויון של מונגו מתאים ל-``1`` מול ``true`` — לא מתועד במפורש בעמודי ``$eq`` וסדר ההשוואה של BSON, ולא נמדד כאן; ערך כזה מחוץ לחוזה של הכותבים.
    """
    return all(doc.get(field) is value for field, value in ACTIVE_VERSION_FILTER.items())


#: ``sortBy`` של ``$top`` שבוחר את הגרסה האחרונה בתוך ``$group`` לפי ``file_name``: ``version`` הגבוה, ובשוויון — ``_id`` הגבוה. ``_id`` כשובר שוויון הוא ההמלצה של תיעוד ``$top``, כי בלעדיו הבחירה בין שני מסמכים שווים אינה מוגדרת (https://www.mongodb.com/docs/manual/reference/operator/aggregation/top/). הקוראים מעבירים עותק (``dict(LATEST_VERSION_SORT_BY)``), כדי שקורא שמשנה את המילון שקיבל לא ישנה אותו לכל השאר.
LATEST_VERSION_SORT_BY: Dict[str, int] = {"version": -1, "_id": -1}
