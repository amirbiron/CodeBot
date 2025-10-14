import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List


class RateLimiter:
    """מגביל קצב פשוט בזיכרון לפי משתמש.

    - חלון מתגלגל של 60 שניות
    - ללא תלות חיצונית
    """

    def __init__(self, max_per_minute: int = 30) -> None:
        self.max_per_minute = max(1, int(max_per_minute or 30))
        self._requests: Dict[int, List[datetime]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check_rate_limit(self, user_id: int) -> bool:
        """מחזיר True אם מותר להמשיך, אחרת False."""
        now = datetime.now(timezone.utc)
        one_min_ago = now - timedelta(seconds=60)
        async with self._lock:
            entries = self._requests[user_id]
            # נקה בקשות ישנות מהחלון (תיקון off-by-one כאשר כל הערכים פגי-תוקף)
            delete_upto = len(entries)
            for idx, ts in enumerate(entries):
                if ts > one_min_ago:
                    delete_upto = idx
                    break
            if delete_upto > 0:
                del entries[:delete_upto]

            if len(entries) >= self.max_per_minute:
                return False

            entries.append(now)
            return True

