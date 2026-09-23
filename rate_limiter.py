import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List


class RateLimiter:
    """מגביל קצב פשוט בזיכרון לפי משתמש.

    - חלון מתגלגל של 60 שניות
    - ללא תלות חיצונית
    """

    def __init__(self, max_per_minute: int = 30) -> None:
        self.max_per_minute = max(1, int(max_per_minute or 30))
        # מילון רגיל ולא ``defaultdict``: רשומה נוצרת רק כשקריאה אושרה
        # (``check_rate_limit``), ולא לכל זהות ששאלו עליה — ראו ``_live_entries``.
        self._requests: Dict[int, List[datetime]] = {}
        self._lock = asyncio.Lock()

    def _live_entries(self, user_id: int, now: datetime) -> List[datetime]:
        """הרשומות של המשתמש שעדיין בחלון, אחרי ניקוי הישנות — נקרא תחת המנעול.

        ניקוי אחד לשלוש השאלות (מותר? כמה בשימוש? כמה לחכות?), במקום שלושה
        עותקים של אותה לולאה שצריכים להסכים זה עם זה לנצח. הרשומות נשמרות
        בסדר הזמן, ולכן הראשונה שעדיין בחלון היא הגבול, ומה שלפניה נמחק
        (תיקון off-by-one כאשר כל הערכים פגי-תוקף: אז נמחק הכול).

        **ואינו יוצר רשומה למי ששואלים עליו בלבד.** עם ``defaultdict`` הקריאה
        ``self._requests[user_id]`` יצרה מפתח קבוע לכל זהות ש-``get_current_usage_ratio``
        או ``seconds_until_allowed`` נשאלו עליה (סקירת שבעת ה-PRים, SUGG-011);
        עכשיו זהות בלי רשומה מקבלת רשימה ריקה שאינה נשמרת, ומפתח שהחלון שלו
        התרוקן נמחק. מי ששומר הוא ``check_rate_limit``, וברגע האישור בלבד.
        """
        entries = self._requests.get(user_id)
        if entries is None:
            return []
        one_min_ago = now - timedelta(seconds=60)
        delete_upto = len(entries)
        for idx, ts in enumerate(entries):
            if ts > one_min_ago:
                delete_upto = idx
                break
        if delete_upto > 0:
            del entries[:delete_upto]
        if not entries:
            del self._requests[user_id]
        return entries

    def _require_weight(self, weight: int) -> int:
        """המשקל כמספר שלם בטווח ``1..max_per_minute`` — אחרת ``ValueError``.

        **שגיאה ולא סירוב**, כי משקל אינו מגיע מהמשתמש אלא מהקוד שקורא לכאן:
        משקל 0 היה מאשר קריאה בלי לחייב אותה, ומשקל גדול מהחלון היה נדחה לנצח
        ו-``seconds_until_allowed`` לא היה יכול לומר מתי יתפנה מקום. שניהם באג
        אצל הקורא, והקורא הוא מי שצריך לשמוע עליו — לא הלקוח שלו.
        """
        weight = int(weight)
        if weight < 1 or weight > self.max_per_minute:
            raise ValueError(
                f"weight must be between 1 and {self.max_per_minute}, got {weight}")
        return weight

    async def check_rate_limit(self, user_id: int, weight: int = 1) -> bool:
        """מחזיר True אם מותר להמשיך, אחרת False.

        ``weight`` — כמה יחידות הקריאה צורכת. **הכול או כלום, תחת המנעול:**
        אם אין מקום לכל היחידות, לא נרשמת אף אחת. חיוב יחידה-יחידה בלולאה היה
        משאיר חלון בין יחידה ליחידה שקריאה אחרת של אותה זהות נכנסת בו (U1),
        וקריאה שנדחתה באמצע הייתה משאירה אחריה יחידות ששולמו על עבודה שלא
        נעשתה. ברירת המחדל 1 היא ההתנהגות שהייתה כאן תמיד, ולכן הבוט
        (``main.py``, ``bot_handlers.py``) אינו משתנה.
        """
        weight = self._require_weight(weight)
        now = datetime.now(timezone.utc)
        async with self._lock:
            entries = self._live_entries(user_id, now)
            if len(entries) + weight > self.max_per_minute:
                return False
            entries.extend([now] * weight)
            # הרשימה עשויה להיות חדשה, או כזו ש-``_live_entries`` ניתק כשהתרוקנה.
            self._requests[user_id] = entries
            return True

    async def get_current_usage_ratio(self, user_id: int) -> float:
        """מחזיר יחס שימוש נוכחי בחלון (0.0–1.0).

        מנקה ערכים ישנים לפני החישוב כדי לשקף את החלון המתגלגל של 60 שניות.
        """
        now = datetime.now(timezone.utc)
        async with self._lock:
            used = len(self._live_entries(user_id, now))
            limit = max(1, int(self.max_per_minute))
            return min(1.0, float(used) / float(limit))

    async def seconds_until_allowed(self, user_id: int, weight: int = 1) -> float:
        """כמה שניות עד שהחלון משחרר מקום ל-``weight`` יחידות — ‏0.0 כשיש מקום כבר עכשיו.

        הרשומות בחלון שמורות בסדר הזמן, והן פגות באותו סדר. כדי ש-``weight``
        יחידות ייכנסו צריכות לפוג ``len + weight - max`` רשומות, ולכן התשובה
        היא הזמן שנותר לאחרונה מביניהן. במשקל 1 זו בדיוק התשובה שהייתה כאן
        תמיד — הרשומה הישנה ביותר — וזו התשובה שסירוב יכול לשאת החוצה
        כ-``retry_after`` במקום "נסה שוב" סתמי.
        """
        weight = self._require_weight(weight)
        now = datetime.now(timezone.utc)
        async with self._lock:
            entries = self._live_entries(user_id, now)
            must_expire = len(entries) + weight - self.max_per_minute
            if must_expire <= 0:
                return 0.0
            last_to_go = entries[must_expire - 1]
            return max(0.0, (last_to_go + timedelta(seconds=60) - now).total_seconds())
