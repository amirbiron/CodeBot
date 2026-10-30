"""שכפול mirror שחסר בדיסק, לפי הרשומות ב-``repo_metadata`` — החלק שמשותף לשירות ה-MCP ולוובאפ.

שני שירותים מחזיקים עותק של ה-mirrors, כל אחד בדיסק שלו, ושניהם ממלאים דיסק שחסרים בו mirrors מאותו מקור:
הרשומות שהוובאפ כותב בייבוא. שירות ה-MCP עושה את זה בכל מעבר של ה-autosync (``refresh_once``
ב-``mcp_server/repo_autosync.py``), והוובאפ פעם אחת בעלייה (``fill_missing_mirrors``
ב-``services/repo_sync_service.py``).
מה ששניהם עושים זהה — לקרוא את הרשומות מה-primary, ולשכפל ריפו שאין לו mirror — ולכן הוא כאן, פעם אחת. מה ששונה
ביניהם נשאר אצל כל אחד: ה-MCP גם מושך ומוחק mirrors שאין להם רשומה, והוובאפ רק משכפל, כי את המשיכה עושה ה-worker שלו
(שגם מאנדקס), ואת ההסרה עושה ``unmirror_repo``.

**שום דבר כאן לא כותב למסד.** השכפול הוא ``init_mirror`` בלבד — לא ``initial_import``, שדורס את ``last_synced_sha``,
את ``repo_url`` ואת ``default_branch`` ומאנדקס את כל הריפו מחדש.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

#: השדות שנקראים מכל רשומה.
REPO_RECORD_FIELDS = {"_id": 0, "repo_name": 1, "repo_url": 1, "default_branch": 1, "last_synced_sha": 1}

CLONE_EXISTS = "exists"
CLONE_CLONED = "cloned"
CLONE_NO_URL = "no_url"
CLONE_FAILED = "failed"


class MirrorCloner(Protocol):
    """מה ש-:func:`clone_if_missing` צריך משירות ה-mirrors (``GitMirrorService``)."""

    def mirror_exists(self, repo_name: str) -> bool: ...

    def init_mirror(self, repo_url: str, repo_name: str) -> Dict[str, Any]: ...


@dataclass(frozen=True)
class CloneOutcome:
    """``status`` הוא אחד מ-``CLONE_*``. ``message`` קיים רק ב-``CLONE_FAILED``, ואחרי :func:`redact`."""

    status: str
    message: str = ""


# ניקוי ללוג (הגנה כפולה): ``_run_git_command`` כבר מנקה את ה-stderr של git, אבל ההודעה כאן מגיעה מתלות שמוזרקת
# לפי צורה — ולכן מנקים credentials בעצמנו לפני שמשהו מגיע ללוג (CLAUDE.md: בלי סודות בלוגים).
_URL_CRED_RE = re.compile(r"(https?://)[^/@\s]+@")
_GH_TOKEN_RE = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")


def redact(text: Any) -> str:
    """מוחק userinfo מכתובות וצורות של טוקן GitHub. נכשל-סגור: בכל תקלה פנימית מחזיר placeholder, לא את הטקסט."""
    try:
        s = str(text or "")
        s = _URL_CRED_RE.sub(r"\1***@", s)
        return _GH_TOKEN_RE.sub("***", s)
    except Exception:
        return "<redacted>"


def _primary_repo_metadata(db: Any) -> Any:
    from pymongo import ReadPreference  # lazy, like Repository.find_version_by_id

    return db["repo_metadata"].with_options(read_preference=ReadPreference.PRIMARY)


def read_repo_records(db: Any) -> List[Dict[str, Any]]:
    """כל הרשומות ב-``repo_metadata``, **מה-primary במפורש** (``ReadPreference.PRIMARY``). זורק בכשל — הקורא מחליט.

    מה-primary כי הקוראים מסיקים מהרשימה גם מה **לא** רשום: ה-MCP מוחק לפיה mirrors. כשבכתובת החיבור יש
    ``readPreference``, הקריאה הייתה יכולה להגיע למשני שעוד לא התעדכן ולהשמיט ריפו שנוסף זה עתה — והמחיקה הייתה
    פוגעת בו.
    """
    return list(_primary_repo_metadata(db).find({}, REPO_RECORD_FIELDS))


def read_repo_record(db: Any, repo_name: str) -> Optional[Dict[str, Any]]:
    """הרשומה של ``repo_name`` עכשיו, מה-primary, או ``None`` כשאין. זורק בכשל.

    ``repo_name`` ייחודי ב-``repo_metadata`` (אינדקס ייחודי שנוצר בעליית שירות ה-MCP, ``RepoBackend``), ולכן
    ``find_one`` כאן הוא הרשומה עצמה ולא נציג שנבחר מכמה.
    """
    return _primary_repo_metadata(db).find_one({"repo_name": repo_name}, REPO_RECORD_FIELDS)


def clone_if_missing(name: str, url: str, mirror: MirrorCloner) -> CloneOutcome:
    """משכפל את ``name`` מ-``url`` אם אין לו mirror בדיסק. לא נוגע ב-mirror שקיים, ולא במסד.

    ``init_mirror`` אידמפוטנטי: mirror תקין שכבר קיים חוזר כהצלחה עם ``already_existed``, ואז התוצאה כאן היא
    ``CLONE_EXISTS`` ולא ``CLONE_CLONED`` — מישהו אחר יצר אותו בין הבדיקה לשכפול, למשל תהליך אחר שמשכפל באותו
    רגע. בכשל ``init_mirror`` מוחק את מה ששכפול חלקי השאיר.
    """
    if mirror.mirror_exists(name):
        return CloneOutcome(CLONE_EXISTS)
    if not url:
        return CloneOutcome(CLONE_NO_URL)
    res = mirror.init_mirror(url, name) or {}
    if res.get("success"):
        return CloneOutcome(CLONE_EXISTS if res.get("already_existed") else CLONE_CLONED)
    return CloneOutcome(CLONE_FAILED, redact(res.get("message")))
