import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
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
        now = datetime.utcnow()
        one_min_ago = now - timedelta(seconds=60)
        async with self._lock:
            entries = self._requests[user_id]
            # נקה בקשות ישנות מהחלון
            i = 0
            for i in range(len(entries)):
                if entries[i] > one_min_ago:
                    break
            if i > 0:
                del entries[:i]

            if len(entries) >= self.max_per_minute:
                return False

            entries.append(now)
            return True

