"""
טעינת רשימת הריפוים שמוצגת בדשבורד לאדמין.

המודול מכוון להיות עצמאי – הוא לא מייבא את Flask או את שכבת ה-DB –
כדי שאפשר יהיה לבדוק אותו ישירות ובלי להעלות את כל האפליקציה.

הרשימה נטענת מ-config/admin_repos.yaml. שים לב: הפונקציות כאן אינן
בודקות הרשאות, והאחריות לכך היא של הקורא (ראו dashboard_routes).
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import yaml

logger = logging.getLogger(__name__)

ADMIN_REPOS_PATH = Path(__file__).parent.parent / 'config' / 'admin_repos.yaml'

DEFAULT_ICON = '📦'
CACHE_TTL_SECONDS = 300  # 5 דקות

# הערך ההתחלתי הוא None ולא [] בכוונה: רשימה ריקה היא תוצאה חוקית לגמרי
# (קובץ בלי ריפוים, או קובץ חסר/פגום). אילו היינו מזהים cache hit לפי
# truthiness, היא לעולם לא הייתה נחשבת כזו – מה שהיה גורם לקריאת דיסק
# ולפענוח YAML בכל בקשת דשבורד, ולהצפת הלוג באזהרות.
_cache: Optional[List[Dict[str, Any]]] = None
_cache_time: float = 0.0
_cache_lock = threading.Lock()


def is_safe_external_url(url: Any) -> bool:
    """
    מוודא שהקישור הוא http/https עם דומיין תקין.

    חוסם סכמות מסוכנות כמו javascript: או data: שעלולות להגיע מהקובץ
    ולהפוך לקישור שרץ כקוד בדף.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc)


def _store(repos: List[Dict[str, Any]], now: float) -> List[Dict[str, Any]]:
    """שומר תוצאה ב-cache (כולל תוצאה ריקה) ומחזיר עותק שלה."""
    global _cache, _cache_time
    with _cache_lock:
        _cache = repos
        _cache_time = now
    return list(repos)


def reset_cache() -> None:
    """מאפס את ה-cache. נועד לבדיקות ולטעינה מחדש יזומה."""
    global _cache, _cache_time
    with _cache_lock:
        _cache = None
        _cache_time = 0.0


def _parse_repos(raw_repos: Any) -> List[Dict[str, Any]]:
    """ממיר את התוכן הגולמי של ה-YAML לרשימת ריפוים מנורמלת."""
    if not isinstance(raw_repos, list):
        return []

    processed: List[Dict[str, Any]] = []
    for repo in raw_repos:
        if not isinstance(repo, dict):
            continue

        name = str(repo.get('name', '') or '').strip()
        url = str(repo.get('url', '') or '').strip()
        if not name or not url:
            continue

        # דילוג על קישורים לא בטוחים במקום להציג אותם למשתמש
        if not is_safe_external_url(url):
            logger.warning("Skipping admin repo with unsafe url: %s", name)
            continue

        processed.append({
            'name': name,
            'url': url,
            'description': str(repo.get('description', '') or '').strip(),
            'icon': str(repo.get('icon', '') or '').strip() or DEFAULT_ICON,
            'badge': str(repo.get('badge', '') or '').strip(),
        })
    return processed


def load_admin_repos() -> List[Dict[str, Any]]:
    """
    טוען את רשימת הריפוים של האדמין מקובץ YAML (עם cache).

    מחזיר רשימה ריקה אם הקובץ חסר או פגום – הדשבורד לא אמור ליפול בגלל זה.
    """
    now = time.time()

    with _cache_lock:
        # הבדיקה היא על "האם נטען אי פעם" ולא על תוכן הרשימה,
        # כדי שגם תוצאה ריקה תיחשב cache hit תקין.
        if _cache is not None and (now - _cache_time) < CACHE_TTL_SECONDS:
            return list(_cache)

    try:
        if not ADMIN_REPOS_PATH.exists():
            return _store([], now)

        with open(ADMIN_REPOS_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        raw_repos = data.get('repos', []) if isinstance(data, dict) else []
        return _store(_parse_repos(raw_repos), now)

    except Exception as e:
        # גם כישלון נשמר ב-cache למשך ה-TTL, אחרת קובץ פגום היה גורם
        # לניסיון פענוח ולאזהרה בלוג בכל בקשת דשבורד של אדמין.
        logger.warning("Failed to load admin_repos.yaml: %s", e)
        return _store([], now)
