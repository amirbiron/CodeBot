"""אינדקס התיעוד לחיפוש בוובאפ: סעיפים ונתחים מקובץ הייצוא, ומעבר שמיישר את המסד אליהם.

**מאיפה.** קובץ הייצוא של אתר התיעוד (``services/docs_export_client.py``) — כל סעיף בכל עמוד,
כמארקדאון, מאותה בנייה שנפרסת. מהקובץ נבנות כאן הרשומות האלה:

* **סעיף** (:data:`~services.docs_search_contract.SECTIONS_COLLECTION`) — מה שכרטיס בחיפוש מציג:
  העמוד, העוגן, שביל הכותרות והמארקדאון.
* **נתח** (:data:`~services.docs_search_contract.CHUNKS_COLLECTION`) — הטקסט שנשלח להטמעה והווקטור
  שלו: שביל הכותרות, שורה ריקה, והגוף (או חלק ממנו) — עד ``CHUNK_MAX_BYTES`` של
  ``services/chunking_service.py``, אותו תקציב בתים של הסניפטים ומאותה סיבה (Gemini חותך בשקט
  מעבר לתקרת הטוקנים).
* **עמוד** (:data:`~services.docs_search_contract.PAGES_COLLECTION`) — עמוד rst שלם, מורכב מכל
  הסעיפים שלו לפי הסדר בקובץ (:func:`page_markdown`), למסך התצוגה המרונדרת בדפדפן הריפו. לא מסעיפי
  החיפוש: אלה מדלגים על סעיף בלי טקסט או של קישורים בלבד, וביומן עדכונים הם עדכונים ולא סעיפים.
  עמוד לא מוטמע, ולכן הוא אינו עולה דבר ואינו משפיע על האישור. עם העמוד נשמרים הקבצים האחרים שהוא
  נבנה מהם (``dependencies`` בקובץ הייצוא), כדי שדפדפן הריפו יידע מתי העמוד ישן מהם.

**המפתחות יציבים** ואינם כוללים את העוגן: סעיף מזוהה לפי קובץ המקור, שביל הכותרות ומספר סידורי
לשביל שחוזר באותו עמוד, ונתח לפי הסעיף ומספר החלק. עוגן שזז (מספר רץ של Sphinx) מעדכן את רשומת
הסעיף בלבד, בלי הטמעה מחדש. ``sha256`` של טקסט הנתח קובע אם צריך הטמעה.

**יומן עדכונים** (:data:`UPDATE_LOG_SOURCES`, היום What's New): ביומן כזה היחידה היא עדכון אחד ולא יום
שלם — כל פריט ברשימה ברמה העליונה של סעיף הוא רשומה משלו. הכותרת שלה היא הפתיח המודגש של העדכון,
השביל הוא שביל היום ועוד הפתיח, והכתובת שלה קופצת לפתיח בתוך היום (``link_text``). הפרטים
ב-:func:`_update_log_units`. כש*כללים* כאלה משתנים — מה שהופך את הקובץ לרשומות — עולה
:data:`RECORDS_VERSION`, והאינדקס נחשב לא שלם עד שמעבר בונה אותו מחדש.

**המעבר** (:func:`run_pass`) משווה את הרצוי (מהקובץ) לקיים (מהמסד, מה-primary, בלי הווקטורים),
ומיישר: מטמיע רק מה שחדש או השתנה, ומוחק מה שהקובץ כבר לא מכיר. מחיקה נעשית רק כשהקובץ מכיר
לפחות רשומה אחת מהקיימות (``one-way-sync-orphans`` ב-amir-bug-patterns: בדיקת חפיפה, בלי סף
"פער גדול"). כל אוספי הרשומות ייעודיים, והמעבר הוא הכותב היחיד שלהם, ולכן כל מה שבהם הוא דבר
שהמעבר יצר ומותר לו למחוק. קובץ שנבנה **לפני** הקובץ שכבר הוחל אינו מוחל (:data:`CODE_OLDER_EXPORT`):
עותק ישן ממטמון האתר, או webhook של פריסה קודמת שהגיע באיחור, לא מחזירים את האינדקס אחורה.

**ריצה.** מעבר רץ ב-thread ברקע, אחד בכל פעם, תחת lease במסמך המצב. בקשה שמגיעה בזמן שמעבר
רץ נשמרת ב-``pending`` ורצה אחריו (:func:`request_pass`). ‏lease של מעבר שנקטע (התהליך עלה מחדש)
פג מעצמו אחרי :data:`LEASE_SECONDS`.

**שומר עלות.** מעבר אוטומטי שיש לו יותר מ-:data:`APPROVAL_THRESHOLD_CHUNKS` נתחים להטמעה — או
מילוי ראשון, או החלפת מודל — לא משנה כלום ועובר ל-``awaiting_approval`` עם תוכנית וטביעת אצבע.
מעבר מאושר רץ רק אם התוכנית זהה לזו שאושרה. כשהאינדקס *נכנס* להמתנה נשלחת התראה לבוט
(:data:`ALERT_APPROVAL_NEEDED`); מעבר שעוצר שוב בזמן שהוא כבר מחכה אינו שולח עוד אחת.

**מה נכתב למסמך המצב** (:data:`STATE_ID` ב-:data:`~services.docs_search_contract.STATE_COLLECTION`)
נגזר מקריאה חוזרת של המסד ולא ממה שהמעבר ביקש לכתוב: ``indexed_source_commit`` מתאפס לפני הכתיבה
הראשונה, ונקבע רק כשכל הסעיפים והנתחים הרצויים קיימים, עם ה-sha והמודל הנכונים. בין שני הרגעים
האינדקס "חלקי", והמצב אומר את זה.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import math
import re
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, TypeGuard

from markdown_it import MarkdownIt
from pymongo import ReadPreference, ReplaceOne, ReturnDocument
from pymongo.errors import OperationFailure, PyMongoError

from internal_alerts import emit_internal_alert
from observability import emit_event
from services import docs_search_contract as contract
from services.chunking_service import CHUNK_MAX_BYTES, split_code_to_chunks
from services.docs_export_client import (
    BREADCRUMB_SEPARATOR,
    MAX_BREADCRUMB_BYTES,
    MAX_TITLE_BYTES,
    DocPage,
    DocSection,
    ExportDocument,
    ExportFetch,
    ExportFetchError,
    fetch_export,
    new_export_http_client,
)
from services.embedding_service import (
    EMBEDDING_DETAIL_DEADLINE_EXCEEDED,
    EMBEDDING_DETAIL_MISSING_API_KEY,
    FAILURE_MODEL_MISSING,
    FAILURE_PERMANENT,
    FAILURE_QUOTA,
    FAILURE_TRANSIENT,
    GEMINI_MAX_BATCH_REQUESTS,
    SyncEmbeddingClient,
    classify_embedding_status,
    compute_content_hash,
    is_dimension_mismatch,
)
from services.semantic_embedding_settings import get_embedding_settings, make_embedding_key

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# מספרים
# ---------------------------------------------------------------------------

#: מעל כמה נתחים להטמעה מעבר אוטומטי עוצר ומחכה לאישור. הערך שאושר בתוכנית (7.10.2026):
#: הרבה מעל מה שקומיט תיעוד רגיל משנה, והרבה מתחת למילוי של האתר כולו.
APPROVAL_THRESHOLD_CHUNKS = 300

#: עמודים שהם יומן עדכונים, לפי קובץ המקור (``source_path`` בקובץ הייצוא): בהם כל עדכון — פריט ברשימה
#: ברמה העליונה של סעיף — נכנס לאינדקס כרשומה משלו (:func:`_update_log_units`). הצהרה מפורשת ולא זיהוי
#: לפי מבנה הטקסט: עמוד רגיל שיש בו רשימה לא מתפרק לפריטים.
UPDATE_LOG_SOURCES = frozenset({"docs/whats-new.rst"})

#: הגרסה של הכללים שהופכים את הקובץ לרשומות (:func:`build_records`). עולה בכל שינוי שגורם לאותו קובץ
#: לתת רשומות או נתחים אחרים. היא נשמרת במסמך המצב כשמעבר מסתיים (``indexed_records_version``), ו-
#: :func:`is_index_complete` דורש אותה — ולכן אחרי פריסה של כללים חדשים מעבר אוטומטי אינו נעצר על
#: "הקובץ לא השתנה" (304), אלא בונה את התוכנית מחדש. 2 — רשומה לכל עדכון ביומן עדכונים. 3 — עמודים
#: מורכבים (:data:`~services.docs_search_contract.PAGES_COLLECTION`).
RECORDS_VERSION = 3

#: הרמה העמוקה ביותר שיש לה כותרת במארקדאון, ושיש לה תגית ב-HTML. סעיף עמוק יותר מקבל באתר ``h6``
#: (``section_title_tags`` ב-``docutils/writers/_html_base.py``, docutils 0.21.2), ולכן גם בעמוד המורכב.
MAX_HEADING_LEVEL = 6

#: תקרה למעבר כולו. נבדקת לפני כל אצווה, ומועברת ללקוח ההטמעות כדדליין של כל בקשה.
PASS_DEADLINE_SECONDS = 20 * 60

#: משך ה-lease. מתחדש לפני כל אצווה, ולכן הוא צריך להיות ארוך מאצווה אחת במקרה הגרוע
#: (``MAX_RETRIES`` ניסיונות של ``REQUEST_TIMEOUT`` ב-``services/embedding_service.py``).
LEASE_SECONDS = 5 * 60

#: כמה מסמכים בכל כתיבה, מחיקה או קריאה לפי ``_id`` שאינה של וקטורים.
DB_BATCH_SIZE = 500

#: ה-``_id`` של מסמך המצב.
STATE_ID = "docs"

# הטריגרים — מי ביקש את המעבר.
TRIGGER_DEPLOY = "deploy"              # webhook של פריסת האתר, עם הקומיט
TRIGGER_PUSH = "push"                  # רשת ביטחון: webhook של push לענף הראשי של ריפו המקור
TRIGGER_MANUAL_CHECK = "manual_check"  # הכפתור "בדוק עכשיו" — כמו מעבר אוטומטי
TRIGGER_APPROVED = "approved"          # הכפתור "התחל" בעמוד האדמין, עם טביעת האצבע שאושרה
TRIGGERS = frozenset({TRIGGER_DEPLOY, TRIGGER_PUSH, TRIGGER_MANUAL_CHECK, TRIGGER_APPROVED})

# הסטטוסים של מעבר.
STATUS_RUNNING = "running"
STATUS_COMPLETE = "complete"
STATUS_UNCHANGED = "unchanged"
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_PAUSED_QUOTA = "paused_quota"
STATUS_FAILED = "failed"
STATUS_STOPPED = "stopped"

# למה מעבר מחכה לאישור.
APPROVAL_FIRST_FILL = "first_fill_or_model_change"
APPROVAL_OVER_THRESHOLD = "over_threshold"

#: שם ההתראה לבוט (וה-``alert_type`` שלה) כשמעבר נכנס להמתנה לאישור (:func:`_alert_approval_needed`). שונה
#: בכוונה מהאירוע ``docs_index_awaiting_approval``: האירוע נשלח בכל מעבר שעוצר, וההתראה רק בכניסה להמתנה.
#: ה-runbook שלה ב-``config/observability_runbooks.yml`` נושא את אותו שם.
ALERT_APPROVAL_NEEDED = "docs_index_approval_needed"

# קודי המעבר עצמו (קודי הקובץ הם ``EXPORT_*`` של ``services/docs_export_client.py``).
CODE_INVALID_REQUEST = "invalid_request"
CODE_MISSING_API_KEY = "missing_api_key"
CODE_SETTINGS_UNAVAILABLE = "settings_unavailable"
CODE_DATABASE_ERROR = "database_error"
CODE_EMBEDDING_QUOTA = "embedding_quota"
CODE_EMBEDDING_REJECTED = "embedding_rejected"
CODE_EMBEDDING_MODEL_MISSING = "embedding_model_missing"
CODE_EMBEDDING_DIMENSION_MISMATCH = "embedding_dimension_mismatch"
CODE_EMBEDDING_UNAVAILABLE = "embedding_unavailable"
CODE_EMBEDDING_UNKNOWN_STATUS = "embedding_unknown_status"
CODE_DEADLINE_EXCEEDED = "deadline_exceeded"
CODE_WRITE_MISMATCH = "write_mismatch"
CODE_VERIFY_MISMATCH = "verify_mismatch"
CODE_APPROVAL_MISMATCH = "plan_changed"
CODE_OLDER_EXPORT = "older_export"
CODE_LEASE_LOST = "lease_lost"
CODE_UNEXPECTED = "unexpected_error"

#: טביעת האצבע של תוכנית: ``sha256`` ב-hex. גם הדקדוק של מה שהאדמין שולח לאישור.
FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")


def is_fingerprint(value: object) -> TypeGuard[str]:
    """האם הערך הוא טביעת אצבע של תוכנית: 64 תווי hex קטנים, ולא שום דבר אחר."""
    return isinstance(value, str) and FINGERPRINT_RE.fullmatch(value) is not None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Any) -> Optional[datetime]:
    """חותמת זמן שנקראה מהמסד, עם אזור זמן. מונגו שומר UTC, ולקוח שלא הוגדר ``tz_aware``
    מחזיר אותה נאיבית — התיוג כאן נכון כי הערך באמת UTC (R7, "קלט")."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# סעיפים ונתחים
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionRecord:
    """סעיף שנכנס לאינדקס — רק סעיף שיש לו לפחות נתח אחד."""

    id: str
    page_path: str
    source_path: str
    page_title: str
    anchor: str
    title: str
    breadcrumb: Tuple[str, ...]
    level: int
    markdown: str
    #: טקסט בתוך הסעיף שהקישור לרשומה קופץ אליו (``section_url`` ב-``services/docs_search_contract.py``):
    #: הפתיח של עדכון ביומן עדכונים. ריק — הקישור מוביל לעוגן בלבד.
    link_text: str = ""

    def content(self) -> Dict[str, Any]:
        """השדות שהכרטיס מציג. רשימה אחת, שממנה נבנים גם המסמך וגם :attr:`record_sha` —
        שדה שנוסף כאן נכנס לשניהם יחד, ושינוי בו מעדכן את המסמך."""
        return {
            "page_path": self.page_path,
            "source_path": self.source_path,
            "page_title": self.page_title,
            "anchor": self.anchor,
            "title": self.title,
            "breadcrumb": list(self.breadcrumb),
            "level": self.level,
            "markdown": self.markdown,
            "link_text": self.link_text,
        }

    @property
    def record_sha(self) -> str:
        return compute_content_hash(_canonical_json(self.content()))

    def document(self) -> Dict[str, Any]:
        return {"_id": self.id, **self.content(), "record_sha": self.record_sha}


@dataclass(frozen=True)
class ChunkRecord:
    """נתח שמוטמע: הטקסט, ה-sha שלו, ולאיזה סעיף הוא שייך.

    כל השדות שנשמרים במסמך הנתח נקבעים מה-``_id`` שלו או מהטקסט, ולכן נתח שלא נכתב מחדש לא יכול
    להתיישן. מה שתלוי בסעיף כולו — למשל כמה חלקים יש לו — לא נשמר כאן: הוא משתנה כשהסעיף מתארך,
    בלי שהנתחים הישנים שלו נכתבים, וסופרים אותו לפי ``section_id`` כשצריך.
    """

    id: str
    section_id: str
    part: int
    text: str
    content_sha: str


@dataclass(frozen=True)
class PageRecord:
    """עמוד rst שלם, כמו שהתצוגה המרונדרת בדפדפן הריפו מציגה אותו. המפתח הוא קובץ המקור, כי זה מה
    שהדפדפן יודע: הנתיב של הקובץ בריפו."""

    source_path: str
    page_path: str
    title: str
    markdown: str
    #: הקבצים האחרים בריפו שהעמוד נבנה מהם, כמו שהם בקובץ הייצוא (:attr:`~services.docs_export_client.DocPage.dependencies`).
    dependencies: Tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return self.source_path

    def content(self) -> Dict[str, Any]:
        """השדות של העמוד. רשימה אחת, שממנה נבנים גם המסמך וגם :attr:`record_sha`, כמו ב-
        :meth:`SectionRecord.content`."""
        return {
            "source_path": self.source_path,
            "page_path": self.page_path,
            "title": self.title,
            "markdown": self.markdown,
            "dependencies": list(self.dependencies),
        }

    @property
    def record_sha(self) -> str:
        return compute_content_hash(_canonical_json(self.content()))

    def document(self) -> Dict[str, Any]:
        return {"_id": self.id, **self.content(), "record_sha": self.record_sha}


_MD_LINK = r"!?\[[^\]\n]*\]\([^)\s]+\)"
_LINK_RE = re.compile(rf"{_MD_LINK}|https?://\S+")
_LIST_MARKER_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
#: פתיחה או סגירה של בלוק הערה (``::: warning`` / ``:::``), כמו שכפתור ההעתקה מייצא אותו.
_ADMONITION_FENCE_RE = re.compile(r"^:::(?:\s*[\w-]+)?$")
#: מה שמותר לבוא אחרי הקישורים בשורה של קישורים: פיסוק בלבד, או מקף ואחריו תיאור.
_LINK_TAIL_RE = re.compile(r"^[\s.,;:]*(?:[—–-].*)?$")


def is_links_only(markdown: str) -> bool:
    """האם הגוף של הסעיף הוא רשימת הפניות בלבד — "ראו גם", תוכן עניינים — ואין בו טקסט משלו.

    הכלל של שלב 0 (7.10.2026), שהוסב ממקור ה-rst למארקדאון של הייצוא: כל שורה שאינה
    ריקה, אחרי סימן רשימה אופציונלי, היא קישור אחד או יותר, ואחריהם לכל היותר פיסוק או מקף עם
    תיאור ("— הפרטים של..."). שורות שפותחות וסוגרות בלוק הערה אינן תוכן. סעיף כזה לא מוטמע:
    בשלב 0 אף סעיף מהסוג הזה לא עלה לשלוש התוצאות הראשונות של אף שאילתה.
    """
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    content = [line for line in lines if not _ADMONITION_FENCE_RE.match(line)]
    if not content:
        return False
    for line in content:
        rest = _LIST_MARKER_RE.sub("", line, count=1)
        if not _LINK_RE.search(rest):
            return False
        if not _LINK_TAIL_RE.match(_LINK_RE.sub("", rest)):
            return False
    return True


def _has_text(markdown: str) -> bool:
    return any(
        line.strip() and not _ADMONITION_FENCE_RE.match(line.strip())
        for line in markdown.splitlines()
    )


def _stable_id(*parts: Any) -> str:
    """``_id`` של רשומה: ``sha256`` של המפתח היציב — אורך קבוע ותווים בטוחים, גם כשהשביל עברי וארוך."""
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_records(document: ExportDocument) -> Tuple[List[SectionRecord], List[ChunkRecord]]:
    """הסעיפים והנתחים הרצויים, לפי סדר הקובץ. סעיף ריק או של קישורים בלבד מדולג.

    בעמוד של :data:`UPDATE_LOG_SOURCES` הרשומות הן העדכונים ולא הסעיפים (:func:`_update_log_units`).

    זורק ``ValueError`` כשתקציב הנתח קטן מהשביל (``CHUNK_MAX_BYTES`` שהוגדר נמוך מדי), או
    כשנתח יוצא גדול מהתקציב — שניהם תקלות תצורה או באג, לא קלט.
    """
    sections: List[SectionRecord] = []
    chunks: List[ChunkRecord] = []
    for page in document.pages:
        seen: Dict[Tuple[str, ...], int] = {}
        units = (
            _update_log_units(page)
            if page.source_path in UPDATE_LOG_SOURCES
            else (
                _RecordUnit(section, section.breadcrumb, section.title, section.markdown)
                for section in page.sections
            )
        )
        for unit in units:
            ordinal = seen.get(unit.breadcrumb, 0)
            seen[unit.breadcrumb] = ordinal + 1
            body = unit.markdown.strip("\n")
            # לעדכון עם פתיח יש טקסט גם כשאין לו גוף: הפתיח הוא בשביל, וממנו בראש כל נתח.
            if not unit.link_text and (not _has_text(body) or is_links_only(body)):
                continue
            section_id = _stable_id(page.source_path, list(unit.breadcrumb), ordinal)
            texts = _chunk_texts(unit.breadcrumb, body)
            for part, text in enumerate(texts):
                chunks.append(
                    ChunkRecord(
                        id=_stable_id(section_id, part),
                        section_id=section_id,
                        part=part,
                        text=text,
                        content_sha=compute_content_hash(text),
                    )
                )
            sections.append(
                SectionRecord(
                    id=section_id,
                    page_path=page.path,
                    source_path=page.source_path,
                    page_title=page.title,
                    anchor=unit.section.anchor,
                    title=unit.title,
                    breadcrumb=unit.breadcrumb,
                    level=len(unit.breadcrumb),
                    markdown=unit.markdown,
                    link_text=unit.link_text,
                )
            )
    return sections, chunks


def page_markdown(page: DocPage) -> str:
    """העמוד כולו כמארקדאון: כל סעיף לפי הסדר בקובץ, הכותרת שלו ברמה שלו, ואחריה הגוף שלו.

    כל הסעיפים נכנסים — גם כותרת שאין תחתיה טקסט משלה אלא רק תתי-סעיפים, וגם "ראו גם", ששניהם לא
    נכנסים לחיפוש. הסדר הוא הסדר בקובץ, שהוא הסדר בעמוד (``querySelectorAll`` בסקריפט הייצוא). הגוף
    של סעיף אינו כולל את תתי-הסעיפים שלו, וב-docutils הגוף של סעיף בא תמיד לפני תתי-הסעיפים שלו (מודל
    התוכן של ``section``), ולכן הצירוף נותן את העמוד כמו שהוא. הכותרת היא ``title_markdown``, כך שקוד
    והדגשה בתוכה נשארים. רמה עמוקה מ-
    :data:`MAX_HEADING_LEVEL` נכתבת ברמה הזו, כמו שהאתר מציג אותה.
    """
    parts: List[str] = []
    for section in page.sections:
        parts.append("#" * min(section.level, MAX_HEADING_LEVEL) + " " + section.title_markdown)
        body = section.markdown.strip("\n")
        if body:
            parts.append(body)
    return "\n\n".join(parts) + "\n"


def build_pages(document: ExportDocument) -> List[PageRecord]:
    """העמודים הרצויים, לפי סדר הקובץ: עמוד לכל קובץ מקור ב-
    :data:`~services.docs_search_contract.PAGE_SOURCE_SUFFIXES`."""
    return [
        PageRecord(
            source_path=page.source_path,
            page_path=page.path,
            title=page.title,
            markdown=page_markdown(page),
            dependencies=page.dependencies,
        )
        for page in document.pages
        if PurePosixPath(page.source_path).suffix in contract.PAGE_SOURCE_SUFFIXES
    ]


@dataclass(frozen=True)
class _RecordUnit:
    """מה שהופך לרשומה אחת: סעיף שלם, או עדכון אחד מתוך סעיף ביומן עדכונים (``section`` הוא הסעיף
    שהוא בתוכו, ומשם העוגן)."""

    section: DocSection
    breadcrumb: Tuple[str, ...]
    title: str
    markdown: str
    link_text: str = ""


def _update_log_units(page: DocPage) -> Iterator[_RecordUnit]:
    """הרשומות של עמוד שהוא יומן עדכונים: רשומה לכל עדכון, ורשומה אחת לכל מה שבסעיף מחוץ לעדכונים.

    * **עדכון עם פתיח** (:func:`_headline`) — הכותרת היא הפתיח, השביל הוא שביל היום ועוד הפתיח (ולכן
      הוא בראש כל נתח, גם של עדכון ארוך שמתחלק), הגוף הוא שאר העדכון — כמו שסעיף נשמר בלי הכותרת
      שלו — והקישור קופץ לפתיח.
    * **עדכון בלי פתיח, או שהפתיח שלו אינו שמיש** — רשומה בשם של היום, עם העדכון כולו ובלי קפיצה.
      פתיח אינו שמיש כשהוא חוזר בעמוד, בהשוואה של הדפדפן (:func:`_match_key`): אז הוא תווית ("מגבלה
      ידועה:") ולא שם של עדכון אחד, וקפיצה אליו הייתה מגיעה להופעה הראשונה שלו. הוא אינו שמיש גם כשהוא
      ארוך מהתקרות של כותרת ושל שביל בקובץ הייצוא (``MAX_TITLE_BYTES``, ``MAX_BREADCRUMB_BYTES``). רק
      המקרה הזה נרשם בלוג, והפתיח לא נחתך.
    * **מה שמחוץ לרשימות** (פסקה אחרי הבולטים) — רשומה אחת בשם של היום.
    """
    split = [(section, *_split_updates(section.markdown)) for section in page.sections]
    # הטקסט שהעמוד מציג, בהשוואה של הדפדפן — פעם אחת לעמוד, ולא לכל עדכון: ``_match_key`` עובר על כל תו
    # בפייתון, וכשהוא רץ על העמוד כולו בכל בדיקה, ``build_records`` על הייצוא של 11.10.2026 לקח 7.1 שניות.
    shown_key = _match_key(
        "\n".join(
            _shown_text(block)
            for _section, updates, outside in split
            for text in (*updates, outside)
            for block in _BLANK_LINE_RE.split(text)
            if block.strip()
        )
    )
    for section, updates, outside in split:
        for update in updates:
            title, rest = _headline(update)
            if title is not None and _usable_headline(page, section, title, shown_key):
                yield _RecordUnit(section, section.breadcrumb + (title,), title, rest, title)
            else:
                yield _RecordUnit(section, section.breadcrumb, section.title, update)
        if outside:
            yield _RecordUnit(section, section.breadcrumb, section.title, outside)


def _usable_headline(page: DocPage, section: DocSection, title: str, shown_key: str) -> bool:
    """האם הפתיח שמיש ככותרת וכיעד לקפיצה. ``shown_key`` — הטקסט שהעמוד מציג, כבר אחרי :func:`_match_key`."""
    size = len(title.encode("utf-8"))
    crumb_size = len(BREADCRUMB_SEPARATOR.join(section.breadcrumb + (title,)).encode("utf-8"))
    if size > MAX_TITLE_BYTES or crumb_size > MAX_BREADCRUMB_BYTES:
        logger.warning(
            "docs index: an update headline in %s#%s is %d bytes (breadcrumb %d), over MAX_TITLE_BYTES or "
            "MAX_BREADCRUMB_BYTES; the update is indexed under its day",
            page.path, section.anchor, size, crumb_size,
        )
        return False
    return shown_key.count(_match_key(title)) == 1


def _match_key(text: str) -> str:
    """הטקסט כמו שהדפדפן משווה אותו כשהוא מחפש את הקפיצה: בלי הבדל בין אותיות גדולות לקטנות, ובלי סימנים
    (ניקוד, טעמים, אקסנטים).

    לפי התקן: "The string search must be performed using a base character comparison, or the primary level,
    as defined in UTS10" (https://wicg.github.io/scroll-to-text-fragment/, "find a range from a node list").
    כאן זה קירוב: פירוק ב-NFKD, השמטת תווי צירוף (קטגוריה ``M``), ו-``casefold``. נמדד ב-Chromium 131
    וב-141 (11.10.2026): ``fix: the parser`` קופץ ל-``Fix: The Parser``, ‏``cafe`` ל-``Café`` ו-``שלום`` ל-``שָׁלוֹם``.
    ולכן פתיח נחשב ייחודי רק אם גם בהשוואה הזו הוא מופיע בעמוד פעם אחת. אחרת הקפיצה הייתה מגיעה להופעה
    הראשונה שלו, ולא לעדכון.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.category(char).startswith("M")).casefold()


#: ``\r\n`` ו-``\r`` בודד ← ``\n``: מה ש-markdown-it עושה לקלט לפני הפרסור (``NEWLINES_RE`` ב-
#: ``markdown_it/rules_core/normalize.py``, 4.2.0). כאן הוא נעשה לפני, כדי שמספרי השורות שהפרסר
#: מחזיר יצביעו על אותן שורות שנחתכות מהטקסט.
_NEWLINES_RE = re.compile(r"\r\n?")

#: שורה ריקה בין שני בלוקים.
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")

#: הסימן בתחילת פריט ברשימה, כמו ש-CommonMark מגדיר אותו: עד שלושה רווחים, ``-``/``*``/``+`` או מספר עם
#: ``.``/``)``, ואחריו רווח או סוף השורה. לא ``_LIST_MARKER_RE`` של :func:`is_links_only`, שבודק שורה שאולי
#: אינה פריט, ומצפה לרווח אחרי הסימן.
_ITEM_MARKER_RE = re.compile(r" {0,3}(?:[-*+]|\d{1,9}[.)])(?=[ \t]|$)[ \t]*")


def _split_updates(markdown: str) -> Tuple[List[str], str]:
    """העדכונים בסעיף של יומן עדכונים, ומה שבסעיף מחוץ להם.

    עדכון הוא פריט ברשימה ברמה העליונה של הסעיף, בלי סימן הרשימה ובלי ההזחה של השורות שמתחתיו. מה
    שמחוץ לרשימות (פסקה, בלוק קוד) חוזר כטקסט אחד, הבלוקים לפי הסדר.

    הגבולות נקבעים בפרסר של markdown-it-py, אותה ספרייה של ``services/md_parser.py``, ולא בכלל על
    שורות: כלל כמו "שורה שמתחילה ב-``-   ``" נשען על הצורה שכפתור ההעתקה כותב (``bulletListMarker``
    ב-``docs/_static/copy-page.js``), ובלוק קוד שאינו בתוך עדכון, עם שורה שמתחילה במקף, היה נחתך
    באמצע. לפי המקור של markdown-it-py 4.2.0: ``map`` של ``list_item_open`` הוא השורה הראשונה של
    הפריט והשורה שאחריו (``rules_block/list.py``), ו-``level`` של בלוק ברמה העליונה הוא 0, וכך גם של
    הסוגר שלו (``StateBlock.push``).
    """
    text = _NEWLINES_RE.sub("\n", markdown)
    lines = text.split("\n")
    tokens = MarkdownIt("commonmark").parse(text)
    updates: List[str] = []
    outside: List[str] = []
    index = 0
    while index < len(tokens):
        opening = tokens[index]
        closing = index
        if opening.nesting == 1:
            closing = next(
                (at for at in range(index + 1, len(tokens)) if tokens[at].level == 0 and tokens[at].nesting == -1),
                -1,
            )
            if closing == -1:
                raise RuntimeError(f"markdown-it never closed the block {opening.type!r}")
        if opening.type in ("bullet_list_open", "ordered_list_open"):
            for token in tokens[index:closing]:
                if token.type == "list_item_open" and token.level == 1 and token.map:
                    update = _item_text(lines[token.map[0]:token.map[1]])
                    if update:
                        updates.append(update)
        elif opening.map:
            block = "\n".join(lines[opening.map[0]:opening.map[1]]).strip("\n")
            if block.strip():
                outside.append(block)
        index = closing + 1
    return updates, "\n\n".join(outside)


def _item_text(lines: Sequence[str]) -> str:
    """פריט ברשימה בלי הסימן שלו, ובלי ההזחה של השורות שמתחתיו (עד רוחב הסימן)."""
    marker = _ITEM_MARKER_RE.match(lines[0]) if lines else None
    width = marker.end() if marker else 0
    body = [lines[0][width:]] if lines else []
    for line in lines[1:]:
        indent = len(line) - len(line.lstrip(" "))
        body.append(line[min(indent, width):])
    return "\n".join(body).strip("\n").rstrip()


#: חלק של פתיח, כמו ש-Turndown כותב אותו: הדגשה (``**...**``; בתוכה אין ``*`` חשוף, כי Turndown מוסיף
#: escape לכל כוכבית בטקסט), או קטע קוד בגרש אחד.
_STRONG = r"\*\*(?:\\.|[^\\*])+\*\*"
_CODE_SPAN = r"`[^`\n]+`"
_HEADLINE_PART_RE = re.compile(rf"{_STRONG}|{_CODE_SPAN}")

#: פתיח: הדגשה בתחילת העדכון, ואחריה עוד הדגשות וקטעי קוד, עם רווח ביניהם או בלעדיו — כך גם פתיח
#: שה-rst מפצל סביב קוד (rst לא מקנן סימון, ולכן ``**...ב-**\ ``x``\ **.**``) נשאר שלם.
_HEADLINE_RE = re.compile(rf"{_STRONG}(?:[ \t]*(?:{_STRONG}|{_CODE_SPAN}))*")


def _headline(update: str) -> Tuple[Optional[str], str]:
    """הפתיח של עדכון, כטקסט שהעמוד מציג (:func:`_shown_text`), ושאר העדכון בלעדיו. בלי פתיח —
    ``(None, update)``.

    הפתיח הוא :data:`_HEADLINE_RE` בתחילת השורה הראשונה, עד ההדגשה האחרונה שבו: קטע קוד אחרי ההדגשה
    האחרונה כבר שייך לגוף (``**fix:** `x` נכשל`` — הפתיח הוא ``fix:``).
    """
    first, newline, tail = update.partition("\n")
    match = _HEADLINE_RE.match(first)
    if match is None:
        return None, update
    end = max(
        part.end() for part in _HEADLINE_PART_RE.finditer(match.group(0)) if part.group(0).startswith("**")
    )
    title = _shown_text(first[:end])
    if not title:
        return None, update
    return title, (first[end:].lstrip(" \t") + newline + tail).strip("\n")


#: מה שבא אחרי ``]`` של קישור ש-Turndown 7.2.2 כותב: ``(`` כתובת ``)``, ואם לקישור יש ``title`` — גם הוא,
#: ``(כתובת "title")``. בכתובת Turndown מוסיף escape לסוגריים, וב-``title`` ל-``"`` (``rules.inlineLink`` ב-
#: ``docs/_static/vendor/turndown.umd.js``). Sphinx נותן ``title`` למשל להפניה ל-``:py:mod:``. כתובת בלי
#: רווחים, כמו ב-``_MD_LINK``.
_LINK_TARGET_RE = re.compile(r'\((?:\\.|[^\\()\s])+(?: "(?:\\.|[^"\\])*")?\)')


def _shown_text(markdown: str) -> str:
    """הטקסט שהעמוד מציג במקום המארקדאון ש-Turndown כתב, ברווחים מכווצים: escape ← התו עצמו, קטע קוד ←
    התוכן שלו כמו שהוא, ``**`` ו-``*`` (הדגשה והטה) ← כלום, וקישור ← הטקסט שלו.

    זה ההפך של ``escape`` ב-Turndown 7.2.2 (``docs/_static/vendor/turndown.umd.js``): Turndown מוסיף לוכסן
    לפני תווים מרשימה סגורה, ולוכסן שבטקסט עצמו הוא כותב כ-``\\\\`` — ולכן כל לוכסן מחוץ לקוד הוא escape
    של התו שאחריו. בתוך קטע קוד אין escape. ישות כמו ``&lt;`` נשארת כמו שהיא: Turndown לא מוסיף escape
    ל-``&``, ובעמוד היא מוצגת כך. הקורא מעביר בלוק אחד בכל פעם: לפי CommonMark קטע קוד לא חוצה גבול של
    בלוק, וגרש שלא נסגר בתוך הבלוק הוא תו רגיל — אחרת הוא היה "בולע" טקסט עד בלוק אחר.

    קישור מזוהה באותה סריקה, ולכן רק מחוץ לקטע קוד ורק בסוגר מרובע בלי escape: Turndown מוסיף escape
    ל-``[`` ול-``]`` שבטקסט, כך שסוגר מרובע אחר הוא תמיד חלק מקישור. ``[טקסט](כתובת)`` בתוך קוד, או
    ``\\[טקסט\\](כתובת)`` בטקסט, מוצגים בעמוד כמו שהם. ``!`` לפני קישור הוא תו בטקסט ולא תמונה: סקריפט
    הייצוא מחליף כל תמונה בקישור "תמונה: …" לפני ההמרה (``scripts/docs_export_sections.py``).
    """
    out: List[str] = []
    #: המקום בפלט של כל ``[`` שעוד לא נסגר. ``[`` שלא נסגר בקישור נשאר בטקסט כמו שהוא.
    opened: List[int] = []
    index, size = 0, len(markdown)
    while index < size:
        char = markdown[index]
        if char == "\\" and index + 1 < size:
            out.append(markdown[index + 1])
            index += 2
        elif char == "`":
            fence_end = index
            while fence_end < size and markdown[fence_end] == "`":
                fence_end += 1
            fence = markdown[index:fence_end]
            closing = _closing_fence(markdown, fence, fence_end)
            if closing == -1:
                out.append(fence)
                index = fence_end
            else:
                out.append(markdown[fence_end:closing])
                index = closing + len(fence)
        elif char == "*":
            # סימן של הדגשה (``**``) או של הטה (``*``, ``emDelimiter`` ב-``docs/_static/copy-page.js``): Turndown
            # מוסיף escape לכל ``*`` שבטקסט, ולכן ``*`` בלי escape מחוץ לקוד אינו טקסט בעמוד.
            index += 1
        elif char == "[":
            opened.append(len(out))
            out.append(char)
            index += 1
        elif char == "]" and opened and (target := _LINK_TARGET_RE.match(markdown, index + 1)) is not None:
            # סוף קישור: הטקסט שלו כבר בפלט, ונשאר רק להוריד את ה-``[`` שפתח אותו.
            del out[opened.pop()]
            index = target.end()
        else:
            out.append(char)
            index += 1
    return " ".join("".join(out).split())


def _closing_fence(text: str, fence: str, start: int) -> int:
    """המקום של רצף גרשים באורך ``fence`` בדיוק, מ-``start`` והלאה, או ``-1``."""
    at = text.find(fence, start)
    while at != -1:
        after = at + len(fence)
        if (after >= len(text) or text[after] != "`") and (at == 0 or text[at - 1] != "`"):
            return at
        while after < len(text) and text[after] == "`":
            after += 1
        at = text.find(fence, after)
    return -1


def _chunk_texts(breadcrumb: Sequence[str], body: str) -> List[str]:
    prefix = BREADCRUMB_SEPARATOR.join(breadcrumb) + "\n\n"
    whole = prefix + body
    if len(whole.encode("utf-8")) <= CHUNK_MAX_BYTES:
        return [whole]
    room = CHUNK_MAX_BYTES - len(prefix.encode("utf-8"))
    if room <= 0:
        raise ValueError(
            f"CHUNK_MAX_BYTES={CHUNK_MAX_BYTES} leaves no room for a body after a breadcrumb of "
            f"{len(prefix.encode('utf-8'))} bytes"
        )
    # רק הבתים קובעים: תקרת השורות של המפצל היא מספר השורות כולו, כפי שהוא סופר אותן
    # (``splitlines``), ולכן היא לעולם לא בולמת. החפיפה היא ברירת המחדל של המפצל — אותה
    # חלוקה שעליה נמדדה איכות החיפוש בשלב 0.
    parts = split_code_to_chunks(body, chunk_size=len(body.splitlines()) or 1, max_bytes=room)
    texts = [prefix + part.content for part in parts]
    oversized = [size for size in (len(text.encode("utf-8")) for text in texts) if size > CHUNK_MAX_BYTES]
    if oversized:
        raise ValueError(f"a chunk came out larger than CHUNK_MAX_BYTES={CHUNK_MAX_BYTES}: {oversized}")
    return texts


# ---------------------------------------------------------------------------
# התוכנית
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexPlan:
    """מה מעבר יעשה: מה להטמיע, מה לעדכן ומה למחוק — וטביעת אצבע שמזהה את כל זה."""

    source_commit: str
    built_at: datetime
    model_key: str
    #: כל הסעיפים, הנתחים והעמודים הרצויים — מה שהאימות בסוף המעבר משווה אליו.
    sections: Tuple[SectionRecord, ...]
    chunks: Tuple[ChunkRecord, ...]
    pages: Tuple[PageRecord, ...]
    chunks_to_embed: Tuple[ChunkRecord, ...]
    sections_to_upsert: Tuple[SectionRecord, ...]
    pages_to_upsert: Tuple[PageRecord, ...]
    chunk_ids_to_delete: Tuple[str, ...]
    section_ids_to_delete: Tuple[str, ...]
    page_ids_to_delete: Tuple[str, ...]
    #: כמה מחיקות נחסכו כי הקובץ לא מכיר אף רשומה קיימת (בדיקת החפיפה).
    deletions_spared: int
    existing_with_model: int
    fingerprint: str

    @property
    def has_changes(self) -> bool:
        return bool(
            self.chunks_to_embed
            or self.sections_to_upsert
            or self.pages_to_upsert
            or self.chunk_ids_to_delete
            or self.section_ids_to_delete
            or self.page_ids_to_delete
        )

    @property
    def approval_reason(self) -> Optional[str]:
        """למה מעבר אוטומטי לא ירוץ בלי אישור, או ``None``."""
        if not self.chunks_to_embed:
            return None
        if self.existing_with_model == 0:
            return APPROVAL_FIRST_FILL
        if len(self.chunks_to_embed) > APPROVAL_THRESHOLD_CHUNKS:
            return APPROVAL_OVER_THRESHOLD
        return None

    def summary(self) -> Dict[str, Any]:
        """המספרים שעמוד האדמין מציג ושנשמרים במסמך המצב."""
        return {
            "source_commit": self.source_commit,
            "built_at": self.built_at,
            "model_key": self.model_key,
            "chunks_to_embed": len(self.chunks_to_embed),
            "embed_requests": math.ceil(len(self.chunks_to_embed) / GEMINI_MAX_BATCH_REQUESTS),
            "embed_bytes": sum(len(chunk.text.encode("utf-8")) for chunk in self.chunks_to_embed),
            "sections_to_upsert": len(self.sections_to_upsert),
            "pages_to_upsert": len(self.pages_to_upsert),
            "chunks_to_delete": len(self.chunk_ids_to_delete),
            "sections_to_delete": len(self.section_ids_to_delete),
            "pages_to_delete": len(self.page_ids_to_delete),
            "deletions_spared": self.deletions_spared,
            "desired_chunks": len(self.chunks),
            "desired_sections": len(self.sections),
            "desired_pages": len(self.pages),
            "approval_reason": self.approval_reason,
            "fingerprint": self.fingerprint,
        }


def compute_plan(db: Any, document: ExportDocument, *, model_key: str) -> IndexPlan:
    """משווה את הרצוי מהקובץ לקיים במסד. קורא בלבד — מה-primary, ובלי הווקטורים והטקסטים.

    כשל קריאה עולה (``PyMongoError``): הוא אינו "אין רשומות", ותוכנית שנבנתה עליו הייתה מוחקת.
    """
    sections, chunks = build_records(document)
    pages = build_pages(document)
    existing_chunks = _existing(db, contract.CHUNKS_COLLECTION, {"content_sha": 1, contract.MODEL_KEY_FIELD: 1})
    existing_sections = _existing(db, contract.SECTIONS_COLLECTION, {"record_sha": 1})
    existing_pages = _existing(db, contract.PAGES_COLLECTION, {"record_sha": 1})

    chunks_to_embed = tuple(
        chunk
        for chunk in chunks
        if existing_chunks.get(chunk.id) is None
        or existing_chunks[chunk.id].get("content_sha") != chunk.content_sha
        or existing_chunks[chunk.id].get(contract.MODEL_KEY_FIELD) != model_key
    )
    sections_to_upsert = tuple(
        section
        for section in sections
        if existing_sections.get(section.id) is None
        or existing_sections[section.id].get("record_sha") != section.record_sha
    )
    pages_to_upsert = tuple(
        page
        for page in pages
        if existing_pages.get(page.id) is None or existing_pages[page.id].get("record_sha") != page.record_sha
    )
    desired_chunk_ids = {chunk.id for chunk in chunks}
    desired_section_ids = {section.id for section in sections}
    desired_page_ids = {page.id for page in pages}
    stale_chunks = sorted(set(existing_chunks) - desired_chunk_ids)
    stale_sections = sorted(set(existing_sections) - desired_section_ids)
    stale_pages = sorted(set(existing_pages) - desired_page_ids)

    # בדיקת החפיפה: קובץ שלא מכיר אף רשומה קיימת אינו ראיה שכל הקיים התיישן. מוחקים רק כשהוא
    # מכיר לפחות סעיף, נתח או עמוד אחד מהמסד; אחרת לא מוחקים כלום, ונרשם כמה מחיקות נחסכו. בדיקה אחת
    # לשלושת האוספים, כי הם עותק אחד של אותו קובץ.
    known = (
        bool(desired_section_ids & set(existing_sections))
        or bool(desired_chunk_ids & set(existing_chunks))
        or bool(desired_page_ids & set(existing_pages))
    )
    spared = 0
    if (existing_chunks or existing_sections or existing_pages) and not known:
        spared = len(stale_chunks) + len(stale_sections) + len(stale_pages)
        stale_chunks, stale_sections, stale_pages = [], [], []

    existing_with_model = sum(
        1 for row in existing_chunks.values() if row.get(contract.MODEL_KEY_FIELD) == model_key
    )
    fingerprint = _fingerprint(
        commit=document.source_commit,
        model_key=model_key,
        embed=[[chunk.id, chunk.content_sha] for chunk in chunks_to_embed],
        upsert=[[section.id, section.record_sha] for section in sections_to_upsert],
        upsert_pages=[[page.id, page.record_sha] for page in pages_to_upsert],
        delete_chunks=stale_chunks,
        delete_sections=stale_sections,
        delete_pages=stale_pages,
    )
    return IndexPlan(
        source_commit=document.source_commit,
        built_at=document.built_at,
        model_key=model_key,
        sections=tuple(sections),
        chunks=tuple(chunks),
        pages=tuple(pages),
        chunks_to_embed=chunks_to_embed,
        sections_to_upsert=sections_to_upsert,
        pages_to_upsert=pages_to_upsert,
        chunk_ids_to_delete=tuple(stale_chunks),
        section_ids_to_delete=tuple(stale_sections),
        page_ids_to_delete=tuple(stale_pages),
        deletions_spared=spared,
        existing_with_model=existing_with_model,
        fingerprint=fingerprint,
    )


def _fingerprint(**content: Any) -> str:
    normalized = {key: sorted(value) if isinstance(value, list) else value for key, value in content.items()}
    return hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()


def _primary(db: Any, name: str) -> Any:
    return db[name].with_options(read_preference=ReadPreference.PRIMARY)


def _existing(db: Any, name: str, projection: Dict[str, int]) -> Dict[str, Dict[str, Any]]:
    """כל המסמכים באוסף, ``_id`` ← השדות שבהיטלה. הפונקציה היחידה שמונה את העותק."""
    return {row["_id"]: row for row in _primary(db, name).find({}, projection)}


# ---------------------------------------------------------------------------
# מסמך המצב וה-lease
# ---------------------------------------------------------------------------

#: ``lease_expires_at`` של lease פנוי. כל רגע ממשי מאוחר ממנו, ולכן "פנוי" הוא תנאי אחד —
#: ``lease_expires_at < עכשיו`` — שמכסה גם lease ששוחרר וגם lease של מעבר שמת באמצע.
_LEASE_FREE = datetime(2000, 1, 1, tzinfo=timezone.utc)


class _LeaseLost(Exception):
    """ה-lease עבר למישהו אחר. אסור לכתוב יותר כלום, גם לא את מסמך המצב."""


def _state(db: Any) -> Any:
    return db[contract.STATE_COLLECTION]


def _stamped(fields: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """כל כתיבה למסמך המצב עוברת כאן, ולכן ``updated_at`` נקבע במקום אחד."""
    return {**fields, "updated_at": now or _now()}


def read_state(db: Any) -> Optional[Dict[str, Any]]:
    """מסמך המצב, מה-primary, או ``None`` אם עוד לא נוצר."""
    return _primary(db, contract.STATE_COLLECTION).find_one({"_id": STATE_ID})


def is_index_complete(state: Dict[str, Any], model_key: str) -> bool:
    """האם האינדקס נכון לקובץ האחרון שנקרא, במודל ``model_key`` ובכללים של הקוד שרץ.

    ארבעה תנאים: קריאה חוזרת אימתה את הכתיבות של המעבר האחרון (``indexed_source_commit`` נקבע רק
    אחריה), הקומיט שאומת הוא של הקובץ האחרון שנקרא, המפתח של המודל הוא זה שהתבקש, והרשומות נבנו
    בכללים של :data:`RECORDS_VERSION`. המעבר שואל לפני שהוא קורא את הקובץ, והחיפוש שואל כדי לומר אם
    התוצאות מהמצב העדכני.
    """
    indexed = state.get("indexed_source_commit")
    return (
        indexed is not None
        and indexed == state.get("export_commit")
        and state.get("indexed_model_key") == model_key
        and state.get("indexed_records_version") == RECORDS_VERSION
    )


def _put_pending(db: Any, request: Dict[str, Any]) -> None:
    """שומר את הבקשה ב-``pending`` (האחרונה גוברת), ויוצר את מסמך המצב אם הוא חסר."""
    now = _now()
    result = _state(db).update_one(
        {"_id": STATE_ID},
        {
            "$set": _stamped({"pending": request}, now),
            "$setOnInsert": {
                "lease_holder": None,
                "lease_expires_at": _LEASE_FREE,
                "stop_requested": False,
                "created_at": now,
            },
        },
        upsert=True,
    )
    if result.matched_count != 1 and result.upserted_id is None:
        raise RuntimeError("docs index: the request was not stored in the state document")


def _take_lease(db: Any, holder: str) -> bool:
    """לוקח את ה-lease אם הוא פנוי. לא נוגע ב-``pending`` — את הבקשה לוקח המריץ עצמו."""
    now = _now()
    taken = _state(db).find_one_and_update(
        {"_id": STATE_ID, "lease_expires_at": {"$lt": now}},
        {"$set": _stamped(
            {"lease_holder": holder, "lease_expires_at": now + timedelta(seconds=LEASE_SECONDS)}, now
        )},
        projection={"_id": 1},
    )
    return taken is not None


def _claim_next(db: Any, holder: str) -> Optional[Dict[str, Any]]:
    """לוקח את הבקשה הממתינה ומחדש את ה-lease, בעדכון אחד. ``None`` — אין בקשה.

    באותו עדכון מתאפס גם ``stop_requested``: עצירה שהתבקשה אחרי שהבקשה נלקחה חלה עליה, ועצירה
    שהתבקשה לפני כן כבר מחקה את הבקשה (:func:`request_stop`). זורק :class:`_LeaseLost` כשה-lease
    כבר לא שלנו.
    """
    now = _now()
    before = _state(db).find_one_and_update(
        {"_id": STATE_ID, "lease_holder": holder},
        {"$set": _stamped(
            {
                "pending": None,
                "stop_requested": False,
                "lease_expires_at": now + timedelta(seconds=LEASE_SECONDS),
            },
            now,
        )},
        projection={"pending": 1},
        return_document=ReturnDocument.BEFORE,
    )
    if before is None:
        raise _LeaseLost()
    pending = before.get("pending")
    return pending if isinstance(pending, dict) else None


def _release(db: Any, holder: str) -> bool:
    """משחרר את ה-lease — רק אם אין בקשה ממתינה, באותו עדכון.

    בקשה שנכנסה רגע לפני השחרור אינה הולכת לאיבוד: השחרור נכשל, והמריץ לוקח אותה. בקשה שנכנסה
    רגע אחריו מוצאת lease פנוי, ומי ששלח אותה מריץ אותה בעצמו.
    """
    result = _state(db).update_one(
        {"_id": STATE_ID, "lease_holder": holder, "pending": None},
        {"$set": _stamped({"lease_holder": None, "lease_expires_at": _LEASE_FREE})},
    )
    return result.matched_count == 1


def _free_lease(db: Any, holder: str) -> None:
    """משחרר את ה-lease בלי לגעת ב-``pending``, כשהמריץ לא עלה — הבקשה נשארת לטריגר הבא."""
    _state(db).update_one(
        {"_id": STATE_ID, "lease_holder": holder},
        {"$set": _stamped({"lease_holder": None, "lease_expires_at": _LEASE_FREE})},
    )


def _update_state(db: Any, holder: str, fields: Dict[str, Any]) -> bool:
    """כותב למסמך המצב רק כשה-lease עדיין שלנו. ``False`` — מישהו אחר מחזיק בו עכשיו."""
    result = _state(db).update_one(
        {"_id": STATE_ID, "lease_holder": holder}, {"$set": _stamped(fields)}
    )
    return result.matched_count == 1


def _record_state(db: Any, holder: str, fields: Dict[str, Any]) -> None:
    if not _update_state(db, holder, fields):
        raise _LeaseLost()


def _stop_requested(db: Any) -> bool:
    state = read_state(db) or {}
    return state.get("stop_requested") is True


def request_stop(db: Any) -> bool:
    """עוצר את המעבר שרץ לפני האצווה הבאה, ומוחק את הבקשה שממתינה אחריו. ``False`` — אין מעבר חי.

    מחיקת הבקשה הממתינה היא חלק מהעצירה: בלעדיה, מעבר שהמתין (webhook, רשת הביטחון) היה מתחיל
    מיד אחרי העצירה, וממשיך להטמיע. טריגר שמגיע אחרי העצירה מתחיל מעבר חדש כרגיל.
    """
    now = _now()
    result = _state(db).update_one(
        {"_id": STATE_ID, "lease_expires_at": {"$gt": now}},
        {"$set": _stamped({"stop_requested": True, "pending": None}, now)},
    )
    return result.matched_count == 1


# ---------------------------------------------------------------------------
# הפעלה
# ---------------------------------------------------------------------------

#: מה ש-:func:`request_pass` מחזיר.
REQUEST_STARTED = "started"   # ה-lease נלקח כאן, והמעבר רץ ב-thread ברקע
REQUEST_QUEUED = "queued"     # מעבר אחר רץ; הבקשה נשמרה וירוץ אחריו


def _start_thread(target: Callable[[], None]) -> None:
    # daemon: עלייה של התהליך מחדש לא מחכה למעבר. מעבר שנקטע משאיר lease שפג מעצמו.
    threading.Thread(target=target, name="docs-index-pass", daemon=True).start()


#: מה שמריץ את המעבר. טסטים מחליפים אותו (``monkeypatch``) כדי להריץ באותו thread.
_runner_factory: Callable[[Callable[[], None]], None] = _start_thread


def request_pass(
    db: Any,
    *,
    trigger: str,
    commit: Optional[str] = None,
    approved_fingerprint: Optional[str] = None,
    requested_by: Optional[int] = None,
) -> str:
    """מבקש מעבר. מחזיר :data:`REQUEST_STARTED` או :data:`REQUEST_QUEUED`.

    הבקשה נשמרת ב-``pending`` (האחרונה גוברת: מעבר שירוץ ממילא יקרא את הקובץ העדכני), ואז נעשה
    ניסיון לקחת את ה-lease. מי שלוקח אותו מריץ ב-thread ברקע את כל הבקשות עד שאין עוד; מי שלא —
    משאיר את הבקשה למחזיק הנוכחי, שבודק את ``pending`` לפני שהוא משחרר.

    ערך לא חוקי הוא באג של הקורא ונדחה ב-``ValueError`` — הראוטים בודקים את הקלט לפני כן.
    """
    if not isinstance(trigger, str) or trigger not in TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}")
    if commit is not None and not contract.is_commit_sha(commit):
        raise ValueError(f"expected a 40-character commit sha, got {commit!r}")
    if (trigger == TRIGGER_APPROVED) != (approved_fingerprint is not None):
        raise ValueError("a fingerprint goes with an approved pass, and only with it")
    if approved_fingerprint is not None and not is_fingerprint(approved_fingerprint):
        raise ValueError(f"not a plan fingerprint: {approved_fingerprint!r}")
    if requested_by is not None and type(requested_by) is not int:
        raise ValueError(f"requested_by is a user id, got {requested_by!r}")
    _put_pending(
        db,
        {
            "trigger": trigger,
            "commit": commit,
            "approved_fingerprint": approved_fingerprint,
            "requested_by": requested_by,
            "requested_at": _now(),
        },
    )
    holder = uuid.uuid4().hex
    if not _take_lease(db, holder):
        return REQUEST_QUEUED
    try:
        _runner_factory(lambda: _run_until_idle(db, holder))
    except BaseException:
        _free_lease(db, holder)
        raise
    return REQUEST_STARTED


def _run_until_idle(db: Any, holder: str) -> None:
    """מריץ את הבקשה הממתינה, ואחריה כל בקשה שהגיעה בינתיים, עד שאין יותר — ואז משחרר.

    גבול ה-thread. כשל בלקיחה או בשחרור (המסד לא זמין) נרשם עם traceback, וה-lease פג מעצמו אחרי
    :data:`LEASE_SECONDS`; הבקשה שנשארה ב-``pending`` רצה בטריגר הבא.
    """
    try:
        while True:
            request = _claim_next(db, holder)
            if request is not None:
                _run_guarded(db, holder, request)
            elif _release(db, holder):
                return
    except _LeaseLost:
        logger.warning("docs index: the lease moved to another runner; this one stops")
    except Exception:  # noqa: BLE001 — גבול של thread ברקע; נרשם, וה-lease פג מעצמו
        logger.exception("docs index runner stopped; its lease expires in %ss", LEASE_SECONDS)


def _run_guarded(db: Any, holder: str, request: Dict[str, Any]) -> None:
    """גבול המעבר: כל חריגה נרשמת עם traceback ומובילה למצב משלה, ``unexpected_error``.

    לתוך מסמך המצב והאירוע נכנס רק שם המחלקה של החריגה. ההודעה שלה עלולה לשאת ערכים מהבקשה
    (K13), והיא נשארת בלוג, עם ה-traceback.
    """
    try:
        run_pass(db, holder=holder, request=request)
    except _LeaseLost:
        raise
    except Exception as exc:  # noqa: BLE001 — גבול של המעבר; מוביל למצב נפרד ורועש
        logger.exception("docs index pass crashed")
        detail = type(exc).__name__
        emit_event("docs_index_failed", severity="error", code=CODE_UNEXPECTED, detail=detail)
        try:
            recorded = _update_state(
                db,
                holder,
                {"run.status": STATUS_FAILED, "run.code": CODE_UNEXPECTED, "run.detail": detail,
                 "run.finished_at": _now()},
            )
        except PyMongoError:
            logger.exception("docs index: could not record the crash")
            return
        if not recorded:
            raise _LeaseLost()


# ---------------------------------------------------------------------------
# המעבר
# ---------------------------------------------------------------------------


class _PassAborted(Exception):
    """עצירה מבוקרת באמצע מעבר, עם הסטטוס והקוד שנכתבים למסמך המצב."""

    def __init__(self, status: str, code: Optional[str], detail: str = "") -> None:
        super().__init__(f"{status}: {code}: {detail}")
        self.status = status
        self.code = code
        self.detail = detail[:300]


@dataclass
class PassContext:
    """התלויות של מעבר, כדי שטסט יוכל להחליף את הרשת ואת השעון.

    ``clock`` הוא השעון של הדדליין, ו-``SyncEmbeddingClient`` משווה אליו עם ``time.monotonic``.
    """

    http_client_factory: Callable[[], Any] = new_export_http_client
    embed_client_factory: Callable[[], Any] = SyncEmbeddingClient
    clock: Callable[[], float] = time.monotonic


_default_context = PassContext()


def _outcome(status: str, code: Optional[str], detail: str = "") -> Dict[str, Any]:
    return {"status": status, "code": code, "detail": detail[:300]}


def run_pass(
    db: Any,
    *,
    holder: str,
    request: Dict[str, Any],
    context: Optional[PassContext] = None,
) -> Dict[str, Any]:
    """מעבר אחד, תחת ה-lease של ``holder``. מחזיר את ה-``run`` שנכתב למסמך המצב.

    כשה-lease אבד באמצע, לא נכתב יותר כלום: המעבר נרשם בלוג ובאירוע, וזורק :class:`_LeaseLost`
    כדי שהמריץ ייעצר.
    """
    ctx = context or _default_context
    run: Dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "trigger": request.get("trigger"),
        "requested_commit": request.get("commit"),
        "requested_by": request.get("requested_by"),
        "started_at": _now(),
        "status": STATUS_RUNNING,
        "code": None,
        "detail": "",
        "progress": {"embedded": 0, "to_embed": 0},
    }
    deadline = ctx.clock() + PASS_DEADLINE_SECONDS
    try:
        _record_state(db, holder, {"run": run})
        outcome = _run_steps(db, holder, request, run, ctx, deadline)
    except _LeaseLost:
        logger.warning("docs index pass %s lost its lease; nothing more is written", run["id"])
        emit_event("docs_index_failed", severity="warning", code=CODE_LEASE_LOST, run_id=run["id"])
        raise
    except _PassAborted as aborted:
        outcome = _outcome(aborted.status, aborted.code, aborted.detail)
    except ExportFetchError as failure:
        outcome = _outcome(STATUS_FAILED, failure.code, failure.detail)
    except PyMongoError as exc:
        logger.exception("docs index pass %s: database error", run["id"])
        outcome = _outcome(STATUS_FAILED, CODE_DATABASE_ERROR, type(exc).__name__)

    run.update(outcome)
    run["finished_at"] = _now()
    totals = _totals(db)
    _emit_outcome(run, totals)
    try:
        recorded = _update_state(db, holder, {"run": run, **totals})
    except PyMongoError:
        logger.exception("docs index pass %s: could not record its outcome", run["id"])
        return run
    if not recorded:
        # מי שלקח את ה-lease כותב את המצב מעכשיו; המריץ הזה ייעצר בלקיחה הבאה (``_claim_next``).
        logger.warning("docs index pass %s lost its lease before recording its outcome", run["id"])
    return run


def _run_steps(
    db: Any,
    holder: str,
    request: Dict[str, Any],
    run: Dict[str, Any],
    ctx: PassContext,
    deadline: float,
) -> Dict[str, Any]:
    trigger = request.get("trigger")
    commit = request.get("commit")
    approved = request.get("approved_fingerprint")
    if (
        not isinstance(trigger, str)
        or trigger not in TRIGGERS
        or (commit is not None and not contract.is_commit_sha(commit))
        or (trigger == TRIGGER_APPROVED and not is_fingerprint(approved))
    ):
        # הבקשה נכתבת רק ב-:func:`request_pass`, שבודק אותה; כאן היא נקראת חזרה מהמסד.
        return _outcome(STATUS_FAILED, CODE_INVALID_REQUEST, f"trigger {trigger!r}")

    try:
        settings = get_embedding_settings(db)
    except PyMongoError as exc:
        raise _PassAborted(STATUS_FAILED, CODE_SETTINGS_UNAVAILABLE, type(exc).__name__) from exc
    dimensions = int(settings.dimensions)
    model_key = make_embedding_key(
        api_version=settings.api_version, model=settings.model, dimensions=dimensions
    )
    state = read_state(db) or {}
    complete = is_index_complete(state, model_key)

    # מאיפה הקובץ:
    # * פריסה — הקובץ של הקומיט שלה (מטמון האתר מתעלם מ-query, ראו ``export_path_for_commit``).
    # * מעבר מאושר — אותו מקור שממנו התוכנית שאושרה חושבה: הקובץ של הקומיט אם היא חושבה ממנו
    #   (מעבר של פריסה), ואחרת הקובץ הראשי — גם לתוכנית "יבשה" מעמוד האדמין, שאינה במסמך המצב.
    #   עותק לפי קומיט קיים רק בפריסה שכתבה אותו ונעלם בפריסה הבאה, ולכן תוכנית שחושבה מהקובץ
    #   הראשי לא עוברת אליו. בכל מקרה התוכנית מחושבת מחדש ומושווית לטביעה.
    # * אוטומטי בלי קומיט — הקובץ הראשי, עם ה-ETag של הפעם הקודמת, רק כשהאינדקס שלם עבורו.
    etag = None
    if trigger == TRIGGER_APPROVED:
        approval = state.get("approval")
        if (
            isinstance(approval, dict)
            and approval.get("fingerprint") == approved
            and approval.get("by_commit") is True
        ):
            stored = approval.get("source_commit")
            commit = stored if contract.is_commit_sha(stored) else None
    elif commit is None and complete:
        stored_etag = state.get("export_etag")
        etag = stored_etag if isinstance(stored_etag, str) else None
    with ctx.http_client_factory() as http:
        fetched = fetch_export(http, commit=commit, etag=etag)
    if fetched.not_modified:
        return _outcome(STATUS_UNCHANGED, None, "the export did not change since the last pass")
    document = _document_of(fetched)
    run["export"] = {
        "url": fetched.url,
        "source_commit": document.source_commit,
        "built_at": document.built_at,
        "bytes": fetched.byte_count,
    }

    applied = _as_utc(state.get("applied_built_at"))
    if applied is not None and document.built_at < applied:
        return _outcome(
            STATUS_UNCHANGED,
            CODE_OLDER_EXPORT,
            f"the export was built at {document.built_at.isoformat()}, "
            f"before the one the index reflects ({applied.isoformat()})",
        )
    _checkpoint(
        db, holder, ctx, deadline, run,
        {
            "export_commit": document.source_commit,
            "export_built_at": document.built_at,
            # ה-ETag שייך לקובץ שממנו הוא הגיע; רק של הקובץ הראשי נשלח בפעם הבאה.
            "export_etag": fetched.etag if commit is None else None,
        },
    )

    plan = compute_plan(db, document, model_key=model_key)
    run["plan"] = plan.summary()
    if trigger == TRIGGER_APPROVED and approved != plan.fingerprint:
        if plan.approval_reason is not None:
            _await_approval(db, holder, plan, CODE_APPROVAL_MISMATCH, by_commit=commit is not None)
            return _outcome(
                STATUS_AWAITING_APPROVAL, CODE_APPROVAL_MISMATCH, "the plan changed since it was approved"
            )
        # התוכנית השתנתה, והחדשה בגבולות מה שמעבר אוטומטי מריץ בלי אישור — אז היא רצה.
    elif trigger != TRIGGER_APPROVED and plan.approval_reason is not None:
        _await_approval(db, holder, plan, plan.approval_reason, by_commit=commit is not None)
        return _outcome(STATUS_AWAITING_APPROVAL, plan.approval_reason)

    if plan.has_changes:

        def checkpoint() -> None:
            # לפני כל אצווה שכותבת — הטמעה, כתיבת סעיפים או מחיקה. עצירה היא גם בלם: מעבר שמוחק
            # מה שלא היה צריך להימחק נעצר באצווה הבאה, ולא רק מעבר שמוציא כסף על הטמעות.
            _checkpoint(db, holder, ctx, deadline, run)

        embedder_scope = (
            ctx.embed_client_factory() if plan.chunks_to_embed else contextlib.nullcontext(None)
        )
        with embedder_scope as embedder:
            # מפתח חסר נבדק לפני הכתיבה הראשונה, כדי שלא יישאר אינדקס חלקי בגלל תצורה.
            if embedder is not None and not embedder.is_available():
                raise _PassAborted(STATUS_FAILED, CODE_MISSING_API_KEY, "GEMINI_API_KEY is not set")
            # מכאן המסד משתנה, ועד האימות הוא אינו תואם לשום קובץ: האינדקס "חלקי".
            _record_state(
                db, holder,
                {"indexed_source_commit": None, "applied_built_at": plan.built_at, "approval": None},
            )
            _write_records(db, contract.SECTIONS_COLLECTION, plan.sections_to_upsert, "sections", checkpoint)
            _write_records(db, contract.PAGES_COLLECTION, plan.pages_to_upsert, "pages", checkpoint)
            if embedder is not None:
                run["progress"] = {"embedded": 0, "to_embed": len(plan.chunks_to_embed)}
                _embed_all(db, checkpoint, deadline, run, plan, settings, dimensions, embedder)
        # הספירה מתעדכנת אחרי כל אצווה, כך שמעבר שנעצר באמצע מדווח כמה כבר נמחק.
        deleted = run["deleted"] = {"chunks": 0, "sections": 0, "pages": 0}
        for key, name, ids in (
            ("chunks", contract.CHUNKS_COLLECTION, plan.chunk_ids_to_delete),
            ("sections", contract.SECTIONS_COLLECTION, plan.section_ids_to_delete),
            ("pages", contract.PAGES_COLLECTION, plan.page_ids_to_delete),
        ):
            for count in _delete_ids(db, name, ids, checkpoint):
                deleted[key] += count
        # הכתיבות הסתיימו: ההתקדמות האחרונה נרשמת, וה-lease מתחדש לקריאה החוזרת שאחריהן.
        _heartbeat(db, holder, run)

    verified = _verify(db, plan)
    run["verified"] = verified
    if not verified["complete"]:
        _record_state(db, holder, {"indexed_source_commit": None})
        return _outcome(
            STATUS_FAILED,
            CODE_VERIFY_MISMATCH,
            f"{verified['chunks_matching']} of {verified['chunks_desired']} chunks, "
            f"{verified['sections_matching']} of {verified['sections_desired']} sections and "
            f"{verified['pages_matching']} of {verified['pages_desired']} pages match the export",
        )
    _record_state(
        db,
        holder,
        {
            "indexed_source_commit": plan.source_commit,
            "indexed_model_key": plan.model_key,
            "indexed_records_version": RECORDS_VERSION,
            "indexed_built_at": plan.built_at,
            "indexed_at": _now(),
            "applied_built_at": plan.built_at,
            "approval": None,
        },
    )
    if not plan.has_changes and complete:
        return _outcome(STATUS_UNCHANGED, None, "nothing to change")
    return _outcome(STATUS_COMPLETE, None)


def _document_of(fetched: ExportFetch) -> ExportDocument:
    """המסמך של הורדה שאינה 304. ``fetch_export`` מחזיר מסמך בכל תשובה אחרת."""
    if fetched.document is None:
        raise RuntimeError(f"fetch_export returned no document for {fetched.url}")
    return fetched.document


def _checkpoint(
    db: Any, holder: str, ctx: PassContext, deadline: float, run: Dict[str, Any],
    fields: Optional[Dict[str, Any]] = None,
) -> None:
    """לפני כל אצווה: הדדליין ובקשת עצירה, ואז :func:`_heartbeat`."""
    if ctx.clock() > deadline:
        raise _PassAborted(STATUS_FAILED, CODE_DEADLINE_EXCEEDED, f"stopped after {PASS_DEADLINE_SECONDS}s")
    if _stop_requested(db):
        raise _PassAborted(STATUS_STOPPED, None, "stopped from the admin page")
    _heartbeat(db, holder, run, fields)


def _heartbeat(
    db: Any, holder: str, run: Dict[str, Any], fields: Optional[Dict[str, Any]] = None
) -> None:
    """מחדש את ה-lease ורושם את ההתקדמות, בכתיבה אחת. זורק :class:`_LeaseLost` כשהוא כבר לא שלנו."""
    _record_state(
        db,
        holder,
        {
            "lease_expires_at": _now() + timedelta(seconds=LEASE_SECONDS),
            "run.progress": run.get("progress"),
            **(fields or {}),
        },
    )


def _await_approval(db: Any, holder: str, plan: IndexPlan, reason: str, *, by_commit: bool) -> None:
    """רושם את התוכנית שמחכה לאישור, ומתריע כשהאינדקס *נכנס* עכשיו להמתנה (:func:`_alert_approval_needed`).
    ``by_commit`` — האם התוכנית חושבה מהעותק לפי הקומיט, ואז המעבר המאושר קורא שוב את העותק הזה; אחרת
    הוא קורא שוב את הקובץ הראשי.

    "נכנס" — במסמך המצב לא הייתה ``approval`` לפני הכתיבה הזו. ההחלטה נגזרת מהמסמך שהכתיבה עצמה מחזירה
    (``ReturnDocument.BEFORE``), ולא מ-``state`` שנקרא בתחילת המעבר. ``approval`` מתאפס כשמעבר מתחיל
    לכתוב (וכשהוא מסתיים), ולכן מעבר שעוצר שוב על אותו פער מצטבר אינו מתריע, ואחרי מעבר שהצליח הכניסה
    הבאה מתריעה.
    """
    before = _state(db).find_one_and_update(
        {"_id": STATE_ID, "lease_holder": holder},
        {"$set": _stamped(
            {
                "approval": {
                    "source_commit": plan.source_commit,
                    "by_commit": by_commit,
                    "fingerprint": plan.fingerprint,
                    "plan": plan.summary(),
                    "reason": reason,
                    "created_at": _now(),
                }
            }
        )},
        projection={"approval": 1, "indexed_source_commit": 1},
        return_document=ReturnDocument.BEFORE,
    )
    if before is None:
        raise _LeaseLost()
    if not isinstance(before.get("approval"), dict):
        _alert_approval_needed(plan, reason, before.get("indexed_source_commit"))


def _alert_approval_needed(plan: IndexPlan, reason: str, indexed_commit: Any) -> None:
    """התראה לבוט (:data:`ALERT_APPROVAL_NEEDED`): כמה נתחים להטמעה מול :data:`APPROVAL_THRESHOLD_CHUNKS`, והקומיט
    שנבדק מול הקומיט שהאינדקס נכון אליו. ``emit_internal_alert`` אינו זורק, ולכן אין סביבו ``try``.

    ``alert_type`` הוא אותו שם, וה-runbook שלו ב-``config/observability_runbooks.yml`` נותן את שורת ה-Quick Fix
    (``quick_fix_line_for_bot_alert`` ב-``services/observability_dashboard.py``).
    """
    to_embed = len(plan.chunks_to_embed)
    if reason == APPROVAL_FIRST_FILL:
        why = f"מילוי ראשון או החלפת מודל, {to_embed} נתחים להטמעה"
    elif reason == APPROVAL_OVER_THRESHOLD:
        why = f"{to_embed} נתחים להטמעה, מעל התקרה ({APPROVAL_THRESHOLD_CHUNKS})"
    else:
        why = f"התוכנית השתנתה מאז שאושרה, {to_embed} נתחים להטמעה (התקרה {APPROVAL_THRESHOLD_CHUNKS})"
    details: Dict[str, Any] = {
        "alert_type": ALERT_APPROVAL_NEEDED,
        "reason": reason,
        "chunks_to_embed": to_embed,
        "approval_threshold": APPROVAL_THRESHOLD_CHUNKS,
        "source_commit": plan.source_commit,
    }
    # ``indexed_source_commit`` ריק כשהאינדקס חלקי (מעבר נעצר באמצע) או עוד לא מולא.
    indexed = indexed_commit if contract.is_commit_sha(indexed_commit) else None
    if indexed:
        details["indexed_commit"] = indexed
    emit_internal_alert(
        ALERT_APPROVAL_NEEDED,
        severity="warn",
        summary=(
            f"אינדקס התיעוד עצר ומחכה לאישור: {why}. "
            f"נבדק {plan.source_commit[:7]} · באינדקס {indexed[:7] if indexed else 'אין (חלקי או ריק)'}"
        ),
        details=details,
    )


def _write_records(
    db: Any,
    name: str,
    records: Sequence[Any],
    what: str,
    checkpoint: Callable[[], None],
) -> None:
    """כותב רשומות שלמות — סעיפים או עמודים, כל אחת עם ``id`` ו-``document()`` — באצוות."""
    now = _now()
    for batch in _batches(records, DB_BATCH_SIZE):
        checkpoint()
        operations = [
            ReplaceOne({"_id": record.id}, dict(record.document(), updated_at=now), upsert=True)
            for record in batch
        ]
        result = db[name].bulk_write(operations, ordered=False)
        _check_written(result, len(operations), what)


def _embed_all(
    db: Any,
    checkpoint: Callable[[], None],
    deadline: float,
    run: Dict[str, Any],
    plan: IndexPlan,
    settings: Any,
    dimensions: int,
    embedder: Any,
) -> None:
    """מטמיע את :attr:`IndexPlan.chunks_to_embed` באצוות, וכותב כל אצווה מיד אחרי שהיא חוזרת."""
    for batch in _batches(plan.chunks_to_embed, GEMINI_MAX_BATCH_REQUESTS):
        checkpoint()
        vectors, status, detail = embedder.embed_batch(
            [chunk.text for chunk in batch],
            model=settings.model,
            api_version=settings.api_version,
            dimensions=dimensions,
            deadline=deadline,
        )
        if vectors is None:
            raise _embedding_failure(status, detail)
        now = _now()
        operations = [
            ReplaceOne(
                {"_id": chunk.id},
                {
                    "_id": chunk.id,
                    "section_id": chunk.section_id,
                    "part": chunk.part,
                    "text": chunk.text,
                    "content_sha": chunk.content_sha,
                    contract.VECTOR_FIELD: vector,
                    # המפתח של המודל שבאמת נשלח בבקשה הזאת (write-from-cached-read).
                    contract.MODEL_KEY_FIELD: plan.model_key,
                    "embeddingModel": settings.model,
                    "embeddingApiVersion": settings.api_version,
                    "embeddingDim": len(vector),
                    "updated_at": now,
                },
                upsert=True,
            )
            for chunk, vector in zip(batch, vectors)
        ]
        result = db[contract.CHUNKS_COLLECTION].bulk_write(operations, ordered=False)
        _check_written(result, len(operations), "chunks")
        run["progress"] = {
            "embedded": run["progress"]["embedded"] + len(batch),
            "to_embed": len(plan.chunks_to_embed),
        }


def _embedding_failure(status: int, detail: str) -> _PassAborted:
    """מתרגם כשל של אצווה לסטטוס של המעבר. כל סוג נוקב בשמו, וגם "לא ידוע" עוצר."""
    if detail == EMBEDDING_DETAIL_DEADLINE_EXCEEDED:
        return _PassAborted(STATUS_FAILED, CODE_DEADLINE_EXCEEDED, detail)
    if detail == EMBEDDING_DETAIL_MISSING_API_KEY:
        return _PassAborted(STATUS_FAILED, CODE_MISSING_API_KEY, detail)
    if is_dimension_mismatch(status, detail):
        return _PassAborted(STATUS_FAILED, CODE_EMBEDDING_DIMENSION_MISMATCH, detail)
    failure = classify_embedding_status(int(status))
    if failure == FAILURE_QUOTA:
        return _PassAborted(STATUS_PAUSED_QUOTA, CODE_EMBEDDING_QUOTA, detail)
    if failure == FAILURE_PERMANENT:
        return _PassAborted(STATUS_FAILED, CODE_EMBEDDING_REJECTED, detail)
    if failure == FAILURE_MODEL_MISSING:
        return _PassAborted(STATUS_FAILED, CODE_EMBEDDING_MODEL_MISSING, detail)
    if failure == FAILURE_TRANSIENT:
        return _PassAborted(STATUS_FAILED, CODE_EMBEDDING_UNAVAILABLE, detail)
    return _PassAborted(STATUS_FAILED, CODE_EMBEDDING_UNKNOWN_STATUS, f"status {status}: {detail}")


def _check_written(result: Any, expected: int, what: str) -> None:
    """כתיבה שלא נגעה בכל המסמכים שנשלחו היא כשל, ולא הצלחה חלקית שקטה (K11)."""
    touched = int(result.matched_count) + int(result.upserted_count)
    if touched != expected:
        raise _PassAborted(STATUS_FAILED, CODE_WRITE_MISMATCH, f"{what}: wrote {touched} of {expected}")


def _delete_ids(db: Any, name: str, ids: Sequence[str], checkpoint: Callable[[], None]) -> Iterator[int]:
    """מוחק לפי ``_id`` באצוות, ומחזיר אחרי כל אצווה כמה ממנה נמחק — רק מה שקריאה חוזרת לא מוצאת
    עוד (K11)."""
    for batch in _batches(ids, DB_BATCH_SIZE):
        checkpoint()
        db[name].delete_many({"_id": {"$in": list(batch)}})
        yield len(batch) - _primary(db, name).count_documents({"_id": {"$in": list(batch)}})


def _verify(db: Any, plan: IndexPlan) -> Dict[str, Any]:
    """קריאה חוזרת: כמה מהנתחים והסעיפים הרצויים קיימים, עם ה-sha (והמודל) של התוכנית."""
    chunk_shas = {chunk.id: chunk.content_sha for chunk in plan.chunks}
    chunks_matching = _count_matching(
        db,
        contract.CHUNKS_COLLECTION,
        chunk_shas,
        {"content_sha": 1, contract.MODEL_KEY_FIELD: 1},
        lambda row: row.get("content_sha") == chunk_shas.get(row["_id"])
        and row.get(contract.MODEL_KEY_FIELD) == plan.model_key,
    )
    section_shas = {section.id: section.record_sha for section in plan.sections}
    sections_matching = _count_matching(
        db,
        contract.SECTIONS_COLLECTION,
        section_shas,
        {"record_sha": 1},
        lambda row: row.get("record_sha") == section_shas.get(row["_id"]),
    )
    page_shas = {page.id: page.record_sha for page in plan.pages}
    pages_matching = _count_matching(
        db,
        contract.PAGES_COLLECTION,
        page_shas,
        {"record_sha": 1},
        lambda row: row.get("record_sha") == page_shas.get(row["_id"]),
    )
    return {
        "chunks_desired": len(chunk_shas),
        "chunks_matching": chunks_matching,
        "sections_desired": len(section_shas),
        "sections_matching": sections_matching,
        "pages_desired": len(page_shas),
        "pages_matching": pages_matching,
        "complete": (
            chunks_matching == len(chunk_shas)
            and sections_matching == len(section_shas)
            and pages_matching == len(page_shas)
        ),
    }


def _count_matching(
    db: Any,
    name: str,
    expected: Dict[str, str],
    projection: Dict[str, int],
    matches: Callable[[Dict[str, Any]], bool],
) -> int:
    count = 0
    ids = list(expected)
    for batch in _batches(ids, DB_BATCH_SIZE):
        for row in _primary(db, name).find({"_id": {"$in": list(batch)}}, projection):
            if matches(row):
                count += 1
    return count


def _totals(db: Any) -> Dict[str, Any]:
    """הספירות שבעמוד האדמין — מהמסד, ולא ממה שהמעבר חשב שכתב."""
    try:
        return {
            "chunk_count": _primary(db, contract.CHUNKS_COLLECTION).count_documents({}),
            "section_count": _primary(db, contract.SECTIONS_COLLECTION).count_documents({}),
            "page_count": _primary(db, contract.PAGES_COLLECTION).count_documents({}),
        }
    except PyMongoError:
        # הספירה היא תצוגה בלבד; המצב נכתב בלעדיה, והעמוד מציג "לא ידוע".
        logger.exception("docs index: could not count the collections")
        return {"chunk_count": None, "section_count": None, "page_count": None}


def _emit_outcome(run: Dict[str, Any], totals: Dict[str, Any]) -> None:
    """אירוע לכל מעבר (``docs_index_pass``), ועוד אחד לכל סיום שמבקש תשומת לב. המספרים הם של
    המעבר הזה בלבד — לא מצטברים."""
    status = run.get("status")
    fields: Dict[str, Any] = {
        "run_id": run.get("id"),
        "trigger": run.get("trigger"),
        "status": status,
        "code": run.get("code"),
        "source_commit": (run.get("export") or {}).get("source_commit"),
        "embedded": (run.get("progress") or {}).get("embedded"),
        "deleted_chunks": (run.get("deleted") or {}).get("chunks"),
        "deleted_sections": (run.get("deleted") or {}).get("sections"),
        "deleted_pages": (run.get("deleted") or {}).get("pages"),
        "deletions_spared": (run.get("plan") or {}).get("deletions_spared"),
        "chunk_count": totals.get("chunk_count"),
    }
    if run.get("requested_by") is not None:
        fields["user_id"] = run.get("requested_by")
    if fields["deletions_spared"]:
        logger.warning(
            "docs index: the export knows none of the indexed records; spared %s deletions",
            fields["deletions_spared"],
        )
    if status == STATUS_AWAITING_APPROVAL:
        emit_event("docs_index_awaiting_approval", severity="info", **fields)
    elif status == STATUS_PAUSED_QUOTA:
        emit_event("docs_index_quota_paused", severity="warning", detail=run.get("detail"), **fields)
    elif status == STATUS_FAILED:
        emit_event("docs_index_failed", severity="error", detail=run.get("detail"), **fields)
    emit_event("docs_index_pass", severity="info", **fields)


def _batches(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def plan_for_admin(db: Any, *, context: Optional[PassContext] = None) -> Dict[str, Any]:
    """תוכנית "יבשה" לעמוד האדמין: מוריד את הקובץ הראשי ומשווה, בלי Gemini ובלי כתיבה.

    זורק ``ExportFetchError`` ו-``PyMongoError`` כמו שהם; הראוט מתרגם אותם לתשובה עם קוד.
    """
    ctx = context or _default_context
    settings = get_embedding_settings(db)
    model_key = make_embedding_key(
        api_version=settings.api_version, model=settings.model, dimensions=int(settings.dimensions)
    )
    with ctx.http_client_factory() as http:
        fetched = fetch_export(http)
    return compute_plan(db, _document_of(fetched), model_key=model_key).summary()


# ---------------------------------------------------------------------------
# עמוד האדמין
# ---------------------------------------------------------------------------

#: הקוד ש-``$listSearchIndexes`` מחזיר בשרת שאינו Atlas: ``OperationFailure`` עם ``SearchNotEnabled``.
#: נמדד 7.10.2026 מול MongoDB 8.0.32 עם pymongo 4.15.3. לפני 7.1 אותה פקודה החזירה רשימה ריקה
#: (https://www.mongodb.com/docs/manual/reference/operator/aggregation/listSearchIndexes/), ושם
#: "חסר" ו"לא Atlas" נראים אותו דבר.
SEARCH_NOT_ENABLED_CODE = 31082

#: ``NamespaceNotFound`` — אם Atlas עונה בו על אוסף שעוד לא נוצר. לא אומת מול Atlas; בכל מקרה
#: אוסף שלא קיים הוא אינדקס שחסר.
_NAMESPACE_NOT_FOUND_CODE = 26


def vector_index_status(db: Any, dimensions: int) -> Dict[str, Any]:
    """מצב האינדקס הווקטורי ב-Atlas, וה-JSON ליצירה שלו לפי המימד הפעיל.

    ``status`` הוא אחד: ``missing`` (אין אינדקס בשם הזה), ``unknown`` (השרת אינו Atlas), ``error``
    (השרת סירב — למשל הרשאה חסרה; ``detail`` נושא את הקוד), או הסטטוס של Atlas עצמו (``READY``,
    ``BUILDING``, ``PENDING`` ועוד). סירוב אינו "חסר", אבל גם אינו מפיל את שאר עמוד המצב.
    ``dimensions_match`` אומר אם האינדקס שקיים נבנה למימד של ההגדרות — אחרי החלפת מודל צריך ליצור
    אותו מחדש. תקלת רשת או מסד אחרת (``PyMongoError`` שאינו ``OperationFailure``) עולה.
    """
    report: Dict[str, Any] = {
        "name": contract.VECTOR_INDEX_NAME,
        "collection": contract.CHUNKS_COLLECTION,
        "definition": contract.vector_index_definition(dimensions),
        "status": "missing",
        "queryable": None,
        "dimensions": None,
        "dimensions_match": None,
    }
    try:
        found = list(db[contract.CHUNKS_COLLECTION].list_search_indexes(name=contract.VECTOR_INDEX_NAME))
    except OperationFailure as exc:
        if exc.code == SEARCH_NOT_ENABLED_CODE:
            return dict(report, status="unknown")
        if exc.code == _NAMESPACE_NOT_FOUND_CODE:
            return report
        logger.warning("docs index: list_search_indexes was refused (code %s)", exc.code)
        return dict(report, status="error", detail=f"OperationFailure code {exc.code}")
    if not found:
        return report
    index = found[0] if isinstance(found[0], dict) else {}
    status = index.get("status")
    report["status"] = status if isinstance(status, str) and status else "unknown"
    report["queryable"] = index.get("queryable") is True
    report["dimensions"] = _vector_dimensions(index.get("latestDefinition"))
    if report["dimensions"] is not None:
        report["dimensions_match"] = report["dimensions"] == dimensions
    return report


def _vector_dimensions(definition: Any) -> Optional[int]:
    """``numDimensions`` של שדה הווקטור בהגדרה ש-Atlas מחזיר, אם הוא שם בצורה הצפויה."""
    fields = definition.get("fields") if isinstance(definition, dict) else None
    if not isinstance(fields, list):
        return None
    for field in fields:
        if (
            isinstance(field, dict)
            and field.get("type") == "vector"
            and field.get("path") == contract.VECTOR_FIELD
            and type(field.get("numDimensions")) is int
        ):
            return int(field["numDimensions"])
    return None


def status_for_admin(db: Any) -> Dict[str, Any]:
    """מה שעמוד האדמין מציג: המעבר האחרון, האינדקס, שלושת הקומיטים, וה-Atlas — מקריאות בלבד."""
    state = read_state(db) or {}
    settings = get_embedding_settings(db)
    dimensions = int(settings.dimensions)
    now = _now()
    lease_expires_at = _as_utc(state.get("lease_expires_at"))
    pending = state.get("pending") if isinstance(state.get("pending"), dict) else None
    mirror = _primary(db, "repo_metadata").find_one(
        {"repo_name": contract.SOURCE_REPO_NAME}, {"_id": 0, "last_synced_sha": 1, "last_sync_time": 1}
    ) or {}
    return {
        "now": now,
        "pass_alive": bool(state.get("lease_holder")) and lease_expires_at is not None and lease_expires_at > now,
        "lease_expires_at": lease_expires_at,
        "stop_requested": state.get("stop_requested") is True,
        "pending": (
            {"trigger": pending.get("trigger"), "requested_at": pending.get("requested_at")} if pending else None
        ),
        "run": state.get("run"),
        "approval": state.get("approval"),
        "indexed": {
            "source_commit": state.get("indexed_source_commit"),
            "model_key": state.get("indexed_model_key"),
            "built_at": state.get("indexed_built_at"),
            "at": state.get("indexed_at"),
        },
        "export": {"source_commit": state.get("export_commit"), "built_at": state.get("export_built_at")},
        "counts": {
            "chunks": state.get("chunk_count"),
            "sections": state.get("section_count"),
            "pages": state.get("page_count"),
        },
        "settings": {
            "model_key": make_embedding_key(
                api_version=settings.api_version, model=settings.model, dimensions=dimensions
            ),
            "dimensions": dimensions,
        },
        "mirror": {
            "repo": contract.SOURCE_REPO_NAME,
            "head": mirror.get("last_synced_sha"),
            "synced_at": mirror.get("last_sync_time"),
        },
        "vector_index": vector_index_status(db, dimensions),
        "approval_threshold": APPROVAL_THRESHOLD_CHUNKS,
    }


def jsonable(value: Any) -> Any:
    """ערך שאפשר להחזיר ב-JSON: חותמות זמן כ-ISO עם אזור זמן (``+00:00``), ולא כתאריך HTTP —
    ``jsonify`` של Flask כותב ``datetime`` בפורמט של כותרות HTTP. חותמת נאיבית מהמסד נקראת כ-UTC."""
    if isinstance(value, datetime):
        aware = _as_utc(value)
        return aware.isoformat() if aware is not None else None
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value
