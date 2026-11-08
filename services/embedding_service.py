"""
Embedding service using the Gemini API (async).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

logger = logging.getLogger(__name__)
# חשוב: httpx יכול להדפיס URL מלא (כולל API key בפרמטרים).
# כדי למנוע דליפת סודות בלוגים, נוריד את הלוגר שלו ל-WARNING כברירת מחדל.
try:
    logging.getLogger("httpx").setLevel(logging.WARNING)
except Exception:
    pass

# Self-heal throttling (avoid thundering herd on 404)
# None means "never ran" (avoid blocking first attempt).
_LAST_SELF_HEAL_TS: Optional[float] = None
_SELF_HEAL_COOLDOWN_SECONDS = float(os.getenv("EMBEDDING_SELF_HEAL_COOLDOWN_SECONDS", "60") or 60)

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "text-embedding-004")  # fallback only
GEMINI_API_VERSION = os.getenv("GEMINI_API_VERSION", "v1beta")  # fallback only
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))  # fallback only

# ``autoTruncate`` הוא שדה ב-``EmbedContentConfig`` של Gemini, ותיאורו:
# "Whether to silently truncate the input content if it's longer than the maximum
# sequence length" (https://ai.google.dev/api/embeddings). כלומר ברירת המחדל של
# הספק היא בדיוק החיתוך השקט שגרם לבעיה — וקטור שמתאר רק את תחילת הקלט.
#
# **נמדד מול ה-API החי, ואינו עובד.** ``scripts/probe_embedding_limits.py``
# מריץ את המדידה; מה שהיא הראתה:
#
# 1. השדה **תקף**. מפתח מומצא בתוך ``embedContentConfig`` מוחזר עם
#    ``400 Unknown name "..." at 'embed_content_config'``, ואילו
#    ``autoTruncate`` עובר. כלומר ה-API מכיר אותו ואינו דוחה אותו.
# 2. השדה **לא משנה דבר**. שני טקסטים בני 28,000 תווים עם תחילית זהה של
#    14,400 תווים וזנבות שונים לחלוטין החזירו וקטורים עם קוסינוס
#    **1.000000** — עם הדגל כבוי. אותם זנבות לבדם נותנים 0.68, כלומר הם
#    באמת שונים. ובקרה נוספת: הווקטור של הטקסט הארוך זהה לחלוטין לווקטור
#    של התחילית שלו בלבד.
#
# המסקנה: החיתוך השקט מתרחש בכל מקרה, ו-``EMBEDDING_AUTO_TRUNCATE=false``
# **אינו רשת ביטחון**. ההגנה היחידה היא תקציב הבייטים ב-
# ``services/chunking_service.py``. הדגל נשאר ברירת מחדל ``true`` (בלי שינוי
# התנהגות) כי השדה תקף וייתכן שגוגל תממש אותו בעתיד — אבל אין להסתמך עליו.
#
# 3. **והבלוק כולו לא נאכף, לא רק ``autoTruncate``.** התיעוד מסמן את
#    ``outputDimensionality`` ברמה העליונה כ-deprecated לטובת
#    ``EmbedContentConfig``, אבל ב-API החי ``outputDimensionality`` בתוך
#    ``embedContentConfig`` נבלע: בקשה ל-768 מימדים חוזרת עם 3,072, כמו
#    בקשה בלי השדה בכלל; ברמה העליונה היא חוזרת עם 768. נמדד ב-7.10.2026 על
#    ``gemini-embedding-001`` (``scripts/probe_embedding_limits.py``, החלק של
#    ``batchEmbedContents``). לכן ``outputDimensionality`` נשאר ברמה העליונה
#    (:func:`build_embed_content_request`), ו"תיקון" שמזיז אותו לפי התיעוד היה
#    משנה בשקט את גודל הווקטור ושובר את האינדקס.
EMBEDDING_AUTO_TRUNCATE = str(
    os.getenv("EMBEDDING_AUTO_TRUNCATE", "true") or "true"
).strip().lower() in {"1", "true", "yes", "on"}

# תקרת בטיחות על הטקסט שנשלח. ה-chunker אחראי לגודל, ולכן טקסט שחורג כאן
# הוא באג במעלה הזרם — ומדווח ככשל **קבוע**, לא נחתך בשקט.
EMBEDDING_MAX_INPUT_BYTES = int(os.getenv("EMBEDDING_MAX_INPUT_BYTES", "30000") or 30000)

# קוד סטטוס פנימי לקלט ארוך מדי. אינו קוד HTTP — הוא נבדל מ-400 של הספק
# כדי שהקורא יוכל להבחין בין "אנחנו שלחנו יותר מדי" ל"הספק דחה".
EMBEDDING_STATUS_INPUT_TOO_LONG = 413


def oversized_input_detail(text: str, *, index: Optional[int] = None) -> Optional[str]:
    """``None`` כשהטקסט נכנס ב-``EMBEDDING_MAX_INPUT_BYTES``, ואחרת התיאור של הכשל (``input_too_long``).

    הבדיקה היחידה של הגודל לפני שליחה: בבקשה בודדת, באצווה של שני הלקוחות, וב-worker של
    הסניפטים לפני שהוא מרכיב אצווה — כדי שטקסט כזה לא יפיל אצווה שלמה. ``index`` הוא המקום
    של הטקסט באצווה, ונכנס לתיאור.
    """
    text_bytes = len(text.encode("utf-8"))
    if text_bytes <= EMBEDDING_MAX_INPUT_BYTES:
        return None
    where = f"index={index} " if index is not None else ""
    return f"input_too_long {where}bytes={text_bytes} max={EMBEDDING_MAX_INPUT_BYTES}"


# Best-effort dynamic config (DB-backed). Fail-open.
try:
    from services.semantic_embedding_settings import get_embedding_settings_cached, normalize_model_name  # type: ignore
except Exception:  # pragma: no cover
    def get_embedding_settings_cached(*, allow_db: bool = True):  # type: ignore
        return None

    def normalize_model_name(model: str) -> str:  # type: ignore
        m = str(model or "").strip()
        return m[len("models/") :].strip() if m.startswith("models/") else m

# Rate limiting
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2.0
REQUEST_TIMEOUT = 30.0


def _retry_backoff_seconds(attempt: int) -> float:
    """כמה לחכות אחרי ניסיון מספר ``attempt`` (מאפס) שנכשל, לפני הניסיון הבא.

    ``RETRY_DELAY_SECONDS``, ומוכפל בכל ניסיון. משותף ל-429 ול-5xx בכל הקריאות של
    :class:`EmbeddingService` (:meth:`EmbeddingService._post_with_retries`), כדי שלכולן תהיה
    אותה הסלמה.
    """
    return RETRY_DELAY_SECONDS * (2 ** attempt)


# שער הקצב של קריאות ההטמעה: מרווח מינימלי בין בקשות, ואחרי 429 הוא נדחף קדימה כך שכל
# הקוראים נסוגים יחד. **השער הוא של התהליך, ולא של המערכת:** הבוט (ה-worker של הסניפטים)
# והוובאפ (מעבר התיעוד) הם שני תהליכים, וכל אחד מהם סופר לעצמו ולא יודע על השני.
#
# בקשה תופסת בשער ``weight`` מרווחים. ``1`` לכל בקשה רגילה; :meth:`EmbeddingService.embed_batch`
# תופס מרווח לכל טקסט באצווה, כך שאצווה של N טקסטים מרחיקה את הבקשה הבאה בדיוק כמו N בקשות
# בודדות. הסיבה: התיעוד של Gemini אינו אומר אם אצווה נספרת במכסה כבקשה אחת או כ-N, ולא מה
# נספר מהטוקנים שלה (נבדק ב-8.11.2026 ב-https://ai.google.dev/gemini-api/docs/rate-limits, שמפנה
# היום ל-aistudio.google.com/docs/rate-limits, ובעמוד ה-API של ``batchEmbedContents``; גם בכותרות
# התשובה החיה אין שום מידע על מכסה). מרווח לכל טקסט שומר על הקצב הממוצע של טקסטים — ולכן גם של טוקנים —
# שה-worker שלח כשכל צ'אנק היה בקשה, בלי תלות בתשובה. :class:`SyncEmbeddingClient` (מעבר
# התיעוד) תופס מרווח אחד לבקשה, כמו קודם.
EMBEDDING_MIN_INTERVAL_SECONDS = float(
    os.getenv("EMBEDDING_MIN_INTERVAL_SECONDS", "1.2") or 1.2
)
EMBEDDING_RATE_LIMIT_COOLDOWN_SECONDS = float(
    os.getenv("EMBEDDING_RATE_LIMIT_COOLDOWN_SECONDS", "30") or 30
)
# ``threading.Lock`` ולא ``asyncio.Lock``: אותו שער משמש גם את
# :class:`SyncEmbeddingClient`, שרץ בוובאפ מ-thread או מ-greenlet ולא מלולאה.
# ``asyncio.Lock`` נקשר ללולאה שהמתינה עליו ראשונה, ושחרור מ-thread אחר אינו מעיר
# את מי שממתין לו (נקרא במקור של ``asyncio/locks.py`` ב-CPython 3.11). בקטע הקריטי
# אין ``await`` ואין I/O — רק חישוב של החריץ הבא — ולכן נעילה רגילה אינה חוסמת את
# הלולאה בפועל, והשינה עצמה נשארת מחוץ לנעילה.
_throttle_lock = threading.Lock()
_next_allowed_ts: float = 0.0


def _reserve_throttle_slot(max_wait: float = math.inf, *, weight: int = 1) -> Optional[float]:
    """שומר את החריץ הבא בשער המשותף, ומחזיר כמה שניות לחכות לו (אפס = עכשיו).

    החריץ תופס ``weight`` מרווחים: הקורא הבא יחכה ``weight * EMBEDDING_MIN_INTERVAL_SECONDS``
    אחרי החריץ הזה (ההסבר בהערה מעל ``EMBEDDING_MIN_INTERVAL_SECONDS``).

    עם ``max_wait`` השמירה מותנית: כשההמתנה לחריץ אינה קצרה ממנו, השער לא משתנה והתשובה היא
    ``None``. קורא ששומר חריץ ורק אחר כך מוותר עליו — כי הדדליין שלו לא מכיל את ההמתנה — דוחה
    את כל שאר הקוראים בתהליך במרווח שלם, בלי שנשלחה שום בקשה. לכן הבדיקה והשמירה קורות באותה
    נעילה. בלי ``max_wait`` החריץ נשמר תמיד.
    """
    global _next_allowed_ts
    with _throttle_lock:
        now = time.monotonic()
        slot = _next_allowed_ts if _next_allowed_ts > now else now
        wait = slot - now
        if wait >= max_wait:
            return None
        _next_allowed_ts = slot + weight * EMBEDDING_MIN_INTERVAL_SECONDS
        return wait


def _push_cooldown_after_429() -> None:
    """Push the global gate forward so all callers back off after a 429."""
    global _next_allowed_ts
    with _throttle_lock:
        target = time.monotonic() + EMBEDDING_RATE_LIMIT_COOLDOWN_SECONDS
        if target > _next_allowed_ts:
            _next_allowed_ts = target


async def _acquire_throttle_slot(weight: int = 1) -> None:
    """Reserve the next slot under the lock, then sleep outside it.

    Holding the lock across ``asyncio.sleep`` would block every other caller
    (e.g. user-facing search query embeddings) and also prevent
    ``_extend_cooldown_after_429`` from updating the gate promptly.
    """
    wait = _reserve_throttle_slot(weight=weight)
    if wait:
        await asyncio.sleep(wait)


#: כמה זמן של השער אצווה אחת יכולה לתפוס: :func:`paced_batch_size`.
PACED_BATCH_WINDOW_SECONDS = 30.0


def paced_batch_size() -> int:
    """כמה טקסטים נכנסים לקריאה אחת של מי שתופס מרווח לכל טקסט (:meth:`EmbeddingService.embed_batch`).

    המרווח לכל טקסט שומר על הקצב **הממוצע**; התקרה כאן מגבילה את **הפרץ**. השער מרחיק את הבקשה
    הבאה רק אחרי שהאצווה נשלחה, ולכן בכל חלון של דקה עוברים לכל היותר ``60 / EMBEDDING_MIN_INTERVAL_SECONDS``
    טקסטים ועוד אצווה אחת. אצווה של חצי דקה (``PACED_BATCH_WINDOW_SECONDS``) מגבילה את החלון
    לפי 1.5 מהממוצע, במקום עד פי 3 באצווה של :data:`GEMINI_MAX_BATCH_REQUESTS`. הגודל נגזר מהמרווח,
    כדי שהגדלה של ``EMBEDDING_MIN_INTERVAL_SECONDS`` להרגעת 429 תקטין גם אותו. בלי מרווח (``0``
    ומטה) — התקרה של ה-API.

    ב-8.11.2026 נמדד מול ``gemini-embedding-001`` (``_probe_batch_semantics`` ב-
    ``scripts/probe_embedding_limits.py``) שאצווה של 25 טקסטים בגודל המקסימלי שה-worker שולח
    (כ-2,500 בתים ו-500–700 טוקנים כל אחד) חוזרת בפחות משנייה — 0.44 ו-0.68 בשתי הרצות — ובהרצה
    ידנית גם אצווה של 90 ב-1.21: רחוק מ-:data:`REQUEST_TIMEOUT`.
    """
    interval = EMBEDDING_MIN_INTERVAL_SECONDS
    if interval <= 0:
        return GEMINI_MAX_BATCH_REQUESTS
    return max(1, min(GEMINI_MAX_BATCH_REQUESTS, int(PACED_BATCH_WINDOW_SECONDS / interval)))


async def wait_for_throttle_gate() -> None:
    """מחכה עד שהשער פתוח, **בלי** לשמור חריץ.

    ל-worker של הסניפטים: הוא מחכה כאן לפני שהוא בודק שהקובץ הוא עדיין הגרסה האחרונה, כך
    שההמתנה לשער — אחרי אצווה גדולה היא יכולה להיות עשרות שניות — לא נופלת בין הבדיקה הזו
    לבקשה. החריץ עצמו נשמר רק בבקשה, ולכן קורא אחר שתפס אותו בינתיים פשוט נשלח קודם.
    """
    with _throttle_lock:
        wait = _next_allowed_ts - time.monotonic()
    if wait > 0:
        await asyncio.sleep(wait)


async def _extend_cooldown_after_429() -> None:
    """Push the global gate forward so all callers back off after a 429."""
    _push_cooldown_after_429()


# ---------------------------------------------------------------------------
# סיווג הכשל של קריאת הטמעה — נקודת המיפוי היחידה בריפו
# ---------------------------------------------------------------------------

FAILURE_TRANSIENT = "transient"   # timeout / רשת / 5xx — כדאי לנסות שוב
FAILURE_PERMANENT = "permanent"   # 400 / קלט ארוך מדי — ניסיון חוזר לא יעזור
FAILURE_QUOTA = "quota"           # 429
FAILURE_MODEL_MISSING = "model_missing"   # 404 — המודל נעלם, צריך self-heal
FAILURE_UNKNOWN = "unknown"       # סטטוס שאין לו משמעות מוגדרת כאן — כל צרכן מחליט במפורש

#: הסטטוסים שהם זמניים בלי תלות בצרכן, מלבד כל ``5xx``. ‏``0`` = הבקשה לא קיבלה
#: תשובת HTTP (timeout או רשת). ‏``401``/``403`` הם קונפיג שאפשר לתקן בלי לשנות את הקלט.
_TRANSIENT_STATUSES = frozenset({0, 401, 403, 408})


def classify_embedding_status(status: int) -> str:
    """ממפה סטטוס של קריאת הטמעה לסוג כשל.

    * ``404`` — המודל שבקונפיג לא קיים. לא כשל של הקלט אלא של ההגדרה.
    * ``400`` — הבקשה עצמה פסולה; ``413`` — הקלט חרג מהתקרה שלנו
      (``EMBEDDING_STATUS_INPUT_TOO_LONG``). ניסיון חוזר יחזיר אותה תשובה.
    * ``429`` — מכסה.
    * ``0`` (timeout/רשת), ``401``/``403``/``408`` וכל ``5xx`` — זמניים.
    * **כל השאר — ``FAILURE_UNKNOWN``**, ולא "זמני" כברירת מחדל. ענף ברירת מחדל שמחזיר
      את הסוג ה"בטוח" נותן לבאג (תשובה לא צפויה, סטטוס פנימי חדש) את התווית של תקלה
      חולפת; כאן הצרכן מחליט מה לעשות בו, ובמפורש. ה-worker של הסניפטים מחזיר אותו
      לתור כמו זמני (``_classify_status`` ב-``services/embedding_worker.py``), ומעבר
      התיעוד עוצר עליו.

    עד 7.10.2026 הפונקציה חיה ב-``embedding_worker.py``, שמייבא את ``database`` ברמת
    המודול; היא עברה לכאן כדי שגם מעבר התיעוד ישתמש באותו מיפוי בלי לייבא את ה-worker.
    """
    if status == 404:
        return FAILURE_MODEL_MISSING
    if status == 429:
        return FAILURE_QUOTA
    if status in (400, 413):
        return FAILURE_PERMANENT
    if status in _TRANSIENT_STATUSES or 500 <= status <= 599:
        return FAILURE_TRANSIENT
    return FAILURE_UNKNOWN


# התיאורים הפנימיים בחוזה ``(הטמעה | None, סטטוס, תיאור)`` — כשאין תשובת HTTP שמסבירה את
# הכשל, התיאור הוא שמזהה אותו. קבועים, כדי שצרכן ישווה אליהם ולא יחזיק עותק של המחרוזת.

#: אין מפתח API. מגיע עם הסטטוס ``0``.
EMBEDDING_DETAIL_MISSING_API_KEY = "missing_api_key"

#: הדדליין של הקורא עבר לפני שהתקבלה תשובה. מגיע עם הסטטוס ``0``, מ-:class:`SyncEmbeddingClient`.
EMBEDDING_DETAIL_DEADLINE_EXCEEDED = "deadline_exceeded"

#: הוקטור שחזר במימד שונה מהמבוקש. מגיע עם הסטטוס הפנימי ``422``, ואחריו ``expected=`` ו-``actual=``.
EMBEDDING_DETAIL_DIMENSION_MISMATCH = "dimension_mismatch"


def is_dimension_mismatch(status: int, body: object) -> bool:
    """האם הכשל הוא מימד שונה מהמבוקש: הסטטוס הפנימי ``422``, עם התיאור שלו.

    ‏``422`` לבדו אינו מספיק, כי גם הספק יכול להחזיר אותו, ובמשמעות אחרת. הבדיקה הזאת
    חזרה עד 7.10.2026 כמחרוזת בכל צרכן (ה-self-heal כאן, ‏``services/embedding_worker.py``).
    """
    return int(status or 0) == 422 and EMBEDDING_DETAIL_DIMENSION_MISMATCH in str(body or "")


#: ה-host היחיד שהלקוחות כאן פונים אליו. המפתח יושב על הלקוח ככותרת ברירת מחדל, ולכן
#: יעד נוסף ללקוח היה שולח אליו את המפתח — יעד אחר מקבל לקוח משלו.
GEMINI_API_HOST = "https://generativelanguage.googleapis.com"

#: כמה בקשות נכנסות לקריאה אחת ל-``batchEmbedContents``. התיעוד אינו נוקב בתקרה; ה-API
#: החי מקבל 100 ודוחה 101 ב-``400 INVALID_ARGUMENT`` עם ההודעה "at most 100 requests
#: can be in one batch". נמדד ב-7.10.2026 (``scripts/probe_embedding_limits.py``).
GEMINI_MAX_BATCH_REQUESTS = 100


def gemini_models_base_url(api_version: str) -> str:
    """הכתובת של ``/models`` בגרסת ה-API המבוקשת; גרסה לא מוכרת נופלת ל-``v1beta``."""
    av = str(api_version or "").strip().lstrip("/") or "v1beta"
    if av not in {"v1", "v1beta"}:
        av = "v1beta"
    return f"{GEMINI_API_HOST}/{av}/models"


def build_embed_content_request(text: str, *, model: str, dimensions: int) -> Dict[str, Any]:
    """בקשת הטמעה אחת: הגוף של ``embedContent``, וגם פריט אחד ב-``requests`` של ``batchEmbedContents``.

    ``outputDimensionality`` ברמה העליונה ולא בתוך ``embedContentConfig`` — ראו את ההערה
    ליד :data:`EMBEDDING_AUTO_TRUNCATE`: שם הוא נבלע. ``dimensions`` שאינו חיובי משמיט
    את השדה, ואז הספק מחזיר את המימד שלו כברירת מחדל.
    """
    model_n = normalize_model_name(model)
    payload: Dict[str, Any] = {
        "model": f"models/{model_n}",
        "content": {"parts": [{"text": text}]},
    }
    if int(dimensions or 0) > 0:
        payload["outputDimensionality"] = int(dimensions)
    if not EMBEDDING_AUTO_TRUNCATE:
        # מקור: https://ai.google.dev/api/embeddings — ``EmbedContentConfig`` מכיל
        # ``autoTruncate`` (boolean). נמדד שהוא לא משנה דבר (ההערה ליד
        # :data:`EMBEDDING_AUTO_TRUNCATE`), ונשלח רק כשמכבים אותו במפורש.
        payload["embedContentConfig"] = {"autoTruncate": False}
    return payload


# ---------------------------------------------------------------------------
# אצווה של ``batchEmbedContents`` — החלקים המשותפים לשני הלקוחות
# ---------------------------------------------------------------------------
#
# :meth:`EmbeddingService.embed_batch` (אסינכרוני, ה-worker של הסניפטים) ו-
# :meth:`SyncEmbeddingClient.embed_batch` (סינכרוני, מעבר התיעוד) שונים רק בתעבורה, במדיניות
# הניסיונות ובמשקל בשער. בדיקת הקלט, הבקשה, הפענוח של התשובה ותיאור השגיאה — כאן, פעם אחת.


def _check_batch_size(items: Sequence[Any]) -> None:
    """אצווה ריקה, או גדולה מ-:data:`GEMINI_MAX_BATCH_REQUESTS`, היא שימוש שגוי: ``ValueError``."""
    if not items or len(items) > GEMINI_MAX_BATCH_REQUESTS:
        raise ValueError(
            f"embed_batch takes 1..{GEMINI_MAX_BATCH_REQUESTS} texts, got {len(items)}"
        )


def _check_batch_texts(items: Sequence[Any]) -> Optional[Tuple[None, int, str]]:
    """טקסט ריק הוא שימוש שגוי (``ValueError``). טקסט ארוך מדי מחזיר את הכשל ``413`` של האצווה
    כולה, עם המקום שלו בה (:func:`oversized_input_detail`), בלי שנשלחת בקשה. אחרת — ``None``.
    """
    for index, text in enumerate(items):
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"text {index} is empty")
        oversized = oversized_input_detail(text, index=index)
        if oversized:
            return None, EMBEDDING_STATUS_INPUT_TOO_LONG, oversized
    return None


def _batch_request(
    items: Sequence[str], *, base_url: str, model: str, dimensions: int
) -> Tuple[str, Dict[str, Any], int]:
    """הכתובת, הגוף והמימד המבוקש של קריאה ל-``batchEmbedContents``: פריט לכל טקסט, באותו סדר.

    ``base_url`` הוא הכתובת של ``/models`` (:func:`gemini_models_base_url`), שכל לקוח מעביר
    בעצמו — :class:`EmbeddingService` דרך :meth:`EmbeddingService._base_url`, כמו כל קריאה שלו.
    """
    model_n = normalize_model_name(model)
    dim = int(dimensions or 0)
    url = f"{base_url}/{model_n}:batchEmbedContents"
    body = {
        "requests": [
            build_embed_content_request(text, model=model_n, dimensions=dim) for text in items
        ]
    }
    return url, body, dim


def _parse_batch_response(
    response: httpx.Response, *, count: int, dim: int
) -> Tuple[Optional[List[List[float]]], int, str]:
    """בודק את צורת התשובה לפני שמשהו ממנה נשמר: רשימה באורך הבקשה, ומספרים סופיים.

    הווקטור ה-i שייך לטקסט ה-i. ב-8.11.2026 נבדק מול ה-API החי (``_probe_batch_semantics`` ב-
    ``scripts/probe_embedding_limits.py``) ש-``batchEmbedContents`` שומר על הסדר: כל וקטור באצווה
    של שישה טקסטים היה זהה (קוסינוס 1.000000) לווקטור של אותו טקסט שנשלח לבד ב-``embedContent``,
    ומול הטקסטים האחרים הדמיון לא עלה על 0.68.
    """
    try:
        data = response.json()
    except ValueError:
        return None, 200, "malformed_response: not json"
    embeddings = data.get("embeddings") if isinstance(data, dict) else None
    if not isinstance(embeddings, list) or len(embeddings) != count:
        return None, 200, f"malformed_response: expected {count} embeddings"
    vectors: List[List[float]] = []
    for index, item in enumerate(embeddings):
        values = item.get("values") if isinstance(item, dict) else None
        if (
            not isinstance(values, list)
            or not values
            # ``type`` ולא ``isinstance``: ‏``True`` הוא ``int`` בפייתון.
            or not all(type(v) in (int, float) and math.isfinite(v) for v in values)
        ):
            return None, 200, f"malformed_response: embedding {index}"
        if dim > 0 and len(values) != dim:
            return (
                None,
                422,
                f"{EMBEDDING_DETAIL_DIMENSION_MISMATCH} expected={dim} actual={len(values)}",
            )
        vectors.append([float(v) for v in values])
    return vectors, 200, ""


#: אורך מרבי לכל שדה בתיאור של תשובת שגיאה (הסטטוס של Google וההודעה שלו). התיאור נכנס
#: ללוג ולמסמך המצב, ולכן יש לו תקרה; זו קטיעה של טקסט אבחוני, לא של נתונים.
_ERROR_FIELD_MAX_CHARS = 300


def _error_summary(response: httpx.Response) -> str:
    """תיאור קצר של תשובת שגיאה מ-Gemini: הקוד, ושדות ``error.status`` ו-``error.message``.

    לא גוף התשובה כמו שהוא ולא הכותרות של הבקשה: מה שחוזר מכאן נרשם בלוג ובמסמך המצב.
    """
    parts = [f"http {response.status_code}"]
    try:
        data = response.json()
    except ValueError:
        return parts[0]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        for field in ("status", "message"):
            value = error.get(field)
            if isinstance(value, str) and value:
                parts.append(value[:_ERROR_FIELD_MAX_CHARS])
    return ": ".join(parts)


class EmbeddingError(Exception):
    """Embedding generation error."""


class EmbeddingService:
    """Async embedding generation service."""

    def __init__(self, api_key: Optional[str] = None):
        # ``None`` = "לא סופק, קח מהסביבה". מחרוזת ריקה = "אין מפתח", והיא
        # **לא** נופלת חזרה לקבוע.
        #
        # קודם זה היה ``api_key or GEMINI_API_KEY``, ואז ``api_key=""`` היה
        # מקבל בשקט את מפתח הסביבה — כלומר אי אפשר היה בכלל לבטא "בלי מפתח".
        # המחיר היה שקט אבל אמיתי: ``test_no_api_key_returns_none`` עבר רק
        # כל עוד לא היה מפתח בסביבה, וברגע שהיה — הוא יצא לקריאת רשת אמיתית
        # מול Gemini במקום לבדוק את מסלול ה"אין מפתח".
        # ``test_gemini_key_not_in_url.py`` כבר עקף את זה ב-``monkeypatch``
        # על הקבוע; זה השורש שהעקיפה הזו כיסתה.
        self.api_key = GEMINI_API_KEY if api_key is None else api_key
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not configured - semantic search disabled")
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy initialization of the AsyncClient.

        **המפתח יושב על הלקוח, ולא על אתר הקריאה.** קודם הוא הועבר בכל
        קריאה כ-``params={"key": ...}``, כלומר נכנס ל-URL — ומשם דלף:
        אינטגרציית httpx של Sentry נדלקת מעצמה (היא ב-
        ``_AUTO_ENABLING_INTEGRATIONS``), קוראת ל-``parse_url`` עם
        ``sanitize=False`` ורושמת את שורת השאילתה כשדה נפרד ב-span. הסוד
        יצא בכל בקשה מוצלחת, לא רק בכשל, ובלי ששורת קוד אחת רשמה אותו.

        ``x-goog-api-key`` הוא ההזדהות שגוגל מתעדת מול אותו host בדיוק:
        https://ai.google.dev/gemini-api/docs/api-key

        **ולמה על הלקוח ולא בכל קריאה:** שלושת אתרי הקריאה כאן היו זהים,
        ותיקון משוכפל הוא בדיוק מה שמשאיר מסלול אחד מאחור. כאן אי אפשר
        לשכוח — כל בקשה דרך הלקוח הזה נושאת את הכותרת, וגם אתר קריאה
        רביעי בעתיד יקבל אותה בלי לדעת עליה.

        **האינווריאנט שמאפשר את זה: הלקוח הזה פונה ל-Google בלבד.** הוא
        פרטי למופע, וכל הקריאות עוברות דרך :meth:`_base_url` שה-host
        בו קבוע בקוד. כותרת ברירת-מחדל נשלחת בכל בקשה, ולכן הוספת יעד
        שאינו של Google ללקוח הזה תשלח את המפתח לצד שלישי — כלומר תחליף
        דליפה לערוץ תצפית בדליפה חמורה יותר. יעד נוסף ⇒ לקוח נפרד.
        """
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            # בלי מפתח לא שולחים כותרת ריקה; ``is_available`` חוסם ממילא
            if self.api_key:
                headers["x-goog-api-key"] = self.api_key
            self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=headers)
        return self._client

    def is_available(self) -> bool:
        """Check if the service is available."""
        return bool(self.api_key)

    def _base_url(self, api_version: str) -> str:
        return gemini_models_base_url(api_version)

    async def generate_embedding_with_status(
        self,
        text: str,
        *,
        model: str,
        api_version: str,
        dimensions: int,
    ) -> Tuple[Optional[List[float]], int, str]:
        """
        Embed text with an explicit (model, api_version, dimensions) and return (embedding, status, body).
        Intended for health-check / upgrade logic.

        **ניסיון חוזר** — :meth:`_post_with_retries`, אותה מדיניות כמו ב-:meth:`embed_batch`.
        בלי תשובת HTTP הסטטוס הוא ``0``, וכך גם כל חריגה אחרת בדרך (ההערה ליד ה-``except``).
        """
        if not self.is_available():
            return None, 0, EMBEDDING_DETAIL_MISSING_API_KEY

        if not text or not text.strip():
            return None, 0, "empty_text"

        # אין חיתוך שקט. עד כה השורה כאן הייתה ``text = text[:30000]``, כלומר
        # הקוד עשה בדיוק את מה שהאישו מתלונן עליו — רק במקום אחר. מעכשיו
        # ה-chunker אחראי לגודל, וחריגה היא כשל גלוי.
        oversized = oversized_input_detail(text)
        if oversized:
            logger.error("Embedding input too long: %s model=%s", oversized, model)
            return None, EMBEDDING_STATUS_INPUT_TOO_LONG, oversized

        model_n = normalize_model_name(model)
        try:
            dim = int(dimensions)
        except Exception:
            dim = EMBEDDING_DIMENSIONS

        base_url = self._base_url(api_version)
        url = f"{base_url}/{model_n}:embedContent"
        # outputDimensionality optional. If <=0, omit and accept provider default dimension.
        payload = build_embed_content_request(text, model=model_n, dimensions=dim)

        # ה-``except`` הרחב נשאר מהלולאה שהייתה כאן עד 8.11.2026 (כל חריגה ← סטטוס ``0``), כדי
        # שהחוזה מול הקוראים הקיימים לא ישתנה; ב-:meth:`embed_batch` הוא צר.
        try:
            response, detail = await self._post_with_retries(url, payload)
            if response is None:
                return None, 0, detail
            try:
                last_body = response.text
            except Exception:
                last_body = ""

            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception:
                    return None, 200, last_body
                embedding = data.get("embedding", {}).get("values", [])
                if embedding and isinstance(embedding, list):
                    # Ensure expected dim (fail-safe)
                    try:
                        if int(dim or 0) > 0 and len(embedding) != int(dim):
                            logger.warning(
                                "Embedding dimensions mismatch: expected=%s actual=%s model=%s api=%s",
                                int(dim),
                                int(len(embedding)),
                                model_n,
                                str(api_version),
                            )
                            # Use internal status code to allow upgrade logic to react.
                            return (
                                None,
                                422,
                                f"{EMBEDDING_DETAIL_DIMENSION_MISMATCH} expected={int(dim)} "
                                f"actual={int(len(embedding))}",
                            )
                    except Exception:
                        pass
                    return embedding, 200, last_body
                logger.error("Empty embedding in response: %s", data)
                return None, 200, last_body

            # 429 ו-``5xx`` מגיעים לכאן רק אחרי שהניסיונות נגמרו. 404 is handled by callers
            # (upgrade logic).
            logger.error("Gemini API error %s: %s", response.status_code, last_body)
            return None, int(response.status_code), last_body

        except Exception as exc:
            logger.error("Embedding generation failed: %s", exc)
            return None, 0, str(exc)

    async def _post_with_retries(
        self, url: str, payload: Dict[str, Any], *, weight: int = 1
    ) -> Tuple[Optional[httpx.Response], str]:
        """שולח בקשה לפי מדיניות הניסיונות של הלקוח הזה, ומחזיר ``(תשובה, "")`` או ``(None, תיאור)``.

        המדיניות של כל הקריאות של :class:`EmbeddingService`, בלולאה אחת: עד :data:`MAX_RETRIES`
        ניסיונות. אחרי 429 ו-``5xx`` ההמתנה היא :func:`_retry_backoff_seconds`, והיא גדלה מניסיון
        לניסיון; 429 גם דוחף את השער המשותף קדימה, כי המכסה משותפת לכל הקוראים בתהליך, ו-``5xx`` לא
        (תקלה בצד של הספק, למשל 503 של עומס). אחרי timeout ההמתנה היא :data:`RETRY_DELAY_SECONDS`
        קבוע. כל תשובה אחרת חוזרת מיד, ובסוף הניסיונות חוזרת התשובה האחרונה — 429 או ה-``5xx``
        עצמו — כדי שהקורא יסווג אותה כמו שהיא (:func:`classify_embedding_status`).

        ``(None, תיאור)`` כשלא התקבלה תשובת HTTP: ``"timeout"`` אחרי שהניסיונות נגמרו, או
        ``"transport_error: <סוג>"`` על שגיאת רשת אחרת, בלי ניסיון חוזר. רק תת-העץ של
        ``httpx.TransportError`` נתפס כאן; כל חריגה אחרת היא באג, ועולה לקורא.

        כל ניסיון תופס בשער ``weight`` מרווחים (:func:`_reserve_throttle_slot`).

        עד 8.11.2026 הלולאה ישבה בתוך :meth:`generate_embedding_with_status`, ו-``5xx`` נוסף לה
        באותו יום (#3657): לפני כן 503 רגעי חזר מיד, וה-worker של הסניפטים החזיר את הקובץ לתור.
        """
        for attempt in range(MAX_RETRIES):
            try:
                await _acquire_throttle_slot(weight)
                response = await self.client.post(url, json=payload)
            except httpx.TimeoutException:
                logger.warning("Timeout on attempt %s", attempt + 1)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    continue
                return None, "timeout"
            except httpx.TransportError as exc:
                detail = f"transport_error: {type(exc).__name__}"
                logger.warning("Embedding request failed: %s", detail)
                return None, detail

            status = int(response.status_code)
            retryable = status == 429 or 500 <= status <= 599
            if not retryable:
                return response, ""
            if status == 429:
                await _extend_cooldown_after_429()
            if attempt >= MAX_RETRIES - 1:
                # מיצינו את הניסיונות. עד 7.10.2026 נפלנו מכאן לשורת ``return None, 0``, ומכסה
                # יומית שנגמרה נראתה בדיוק כמו timeout — ולכן ה-worker המשיך לקובץ הבא ושרף
                # עליו עוד שלוש קריאות.
                return response, ""
            wait_time = _retry_backoff_seconds(attempt)
            if status == 429:
                logger.warning("Rate limited, waiting %ss...", wait_time)
            else:
                logger.warning(
                    "Gemini API error %s on attempt %s, retrying in %ss",
                    status,
                    attempt + 1,
                    wait_time,
                )
            await asyncio.sleep(wait_time)
        raise AssertionError("unreachable: the last attempt always returns")

    async def embed_batch(
        self,
        texts: Sequence[str],
        *,
        model: str,
        api_version: str,
        dimensions: int,
    ) -> Tuple[Optional[List[List[float]]], int, str]:
        """מטמיע עד :data:`GEMINI_MAX_BATCH_REQUESTS` טקסטים בקריאה אחת ל-``batchEmbedContents``.

        החוזה של :meth:`SyncEmbeddingClient.embed_batch`, והחלקים המשותפים שלו: ``(וקטורים, 200,
        "")`` בהצלחה, וקטור לכל טקסט באותו סדר; ``(None, סטטוס, תיאור)`` בכשל, עם ``413`` לטקסט
        ארוך מדי בלי שנשלחת בקשה, ``422`` למימד שונה מהמבוקש ו-``200`` לתשובה שאינה בצורה הצפויה.
        אצווה ריקה, גדולה מהתקרה, או עם טקסט ריק — ``ValueError``.

        ההבדלים מהלקוח הסינכרוני: אין דדליין, והניסיונות הם של :meth:`_post_with_retries` — כלומר
        גם 429 מקבל ניסיון חוזר, ומיצוי שלו חוזר כ-429. הבקשה תופסת בשער מרווח לכל טקסט (ההסבר
        בהערה מעל ``EMBEDDING_MIN_INTERVAL_SECONDS``).

        כשהספק דוחה פריט אחד, הוא דוחה את האצווה כולה: ב-8.11.2026 אצווה של שלושה טקסטים שאחד
        מהם ריק חזרה ``400 INVALID_ARGUMENT`` בלי שום וקטור, וההודעה לא אמרה איזה פריט
        (``_probe_batch_semantics`` ב-``scripts/probe_embedding_limits.py``). הבידוד
        של הפריט הוא של הקורא (``_embed_items`` ב-``services/embedding_worker.py``).
        """
        items = list(texts)
        _check_batch_size(items)
        if not self.is_available():
            return None, 0, EMBEDDING_DETAIL_MISSING_API_KEY
        invalid = _check_batch_texts(items)
        if invalid is not None:
            return invalid
        url, body, dim = _batch_request(
            items, base_url=self._base_url(api_version), model=model, dimensions=dimensions
        )
        response, detail = await self._post_with_retries(url, body, weight=len(items))
        if response is None:
            return None, 0, detail
        if response.status_code == 200:
            return _parse_batch_response(response, count=len(items), dim=dim)
        summary = _error_summary(response)
        logger.warning("Embedding batch of %s failed: %s", len(items), summary)
        return None, int(response.status_code), summary

    async def list_models(self, *, api_version: str) -> List[str]:
        """
        Best-effort list of available models via REST (similar to genai.list_models()).
        Returns model names without the "models/" prefix.
        """
        if not self.is_available():
            return []
        base_url = self._base_url(api_version)
        try:
            resp = await self.client.get(base_url)
        except Exception:
            return []
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []
        models = data.get("models")
        if not isinstance(models, list):
            return []
        out: List[str] = []
        for m in models:
            if not isinstance(m, dict):
                continue
            name = str(m.get("name") or "").strip()
            if not name:
                continue
            # name is usually "models/xyz"
            if name.startswith("models/"):
                name = name[len("models/") :]
            out.append(name)
        # Dedup (stable)
        seen = set()
        deduped: List[str] = []
        for x in out:
            if x in seen:
                continue
            seen.add(x)
            deduped.append(x)
        return deduped

    async def list_models_detailed(self, *, api_version: str) -> List[Dict[str, Any]]:
        """
        Best-effort list of available models with metadata (e.g. supportedGenerationMethods).
        Returns raw dicts with normalized name (no "models/" prefix) when possible.
        """
        if not self.is_available():
            return []
        base_url = self._base_url(api_version)
        try:
            resp = await self.client.get(base_url)
        except Exception:
            return []
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []
        models = data.get("models")
        if not isinstance(models, list):
            return []
        out: List[Dict[str, Any]] = []
        for m in models:
            if not isinstance(m, dict):
                continue
            try:
                name = str(m.get("name") or "").strip()
            except Exception:
                name = ""
            if name.startswith("models/"):
                name = name[len("models/") :]
            if not name:
                continue
            item = dict(m)
            item["name"] = name
            out.append(item)
        return out

    def _model_supports_embed_content(self, model_doc: Dict[str, Any]) -> bool:
        try:
            methods = model_doc.get("supportedGenerationMethods")
        except Exception:
            methods = None
        if not isinstance(methods, list):
            return False
        try:
            return any(str(m).strip() == "embedContent" for m in methods)
        except Exception:
            return False

    async def _self_heal_on_404(
        self,
        *,
        text: str,
        preferred_dimensions: int,
        preferred_allowlist: Optional[List[str]] = None,
        existing_legacy_key: Optional[str] = None,
        existing_active_key: Optional[str] = None,
    ) -> Optional[List[float]]:
        """
        If current model is 404, attempt to auto-select a working embedding model from ListModels
        and use it immediately. Best-effort persist to DB.
        """
        global _LAST_SELF_HEAL_TS
        try:
            now = float(time.monotonic())
        except Exception:
            now = 0.0
        try:
            if (
                _LAST_SELF_HEAL_TS is not None
                and now
                and (now - float(_LAST_SELF_HEAL_TS)) < float(_SELF_HEAL_COOLDOWN_SECONDS)
            ):
                logger.info("Self-heal skipped (cooldown: %.1fs remaining)",
                            float(_SELF_HEAL_COOLDOWN_SECONDS) - (now - float(_LAST_SELF_HEAL_TS)))
                return None
        except Exception:
            pass

        # Set cooldown immediately so exceptions/early-exits don't cause hammering.
        _LAST_SELF_HEAL_TS = now if now else _LAST_SELF_HEAL_TS
        logger.warning("Self-heal triggered: attempting to find a working embedding model")

        allow = [normalize_model_name(x) for x in (preferred_allowlist or []) if str(x).strip()]
        legacy_to_keep = (str(existing_legacy_key or "").strip()) or (str(existing_active_key or "").strip())
        # list models (try v1beta then v1)
        for api_version in ["v1beta", "v1"]:
            models = await self.list_models_detailed(api_version=api_version)
            if not models:
                logger.info("Self-heal: list_models returned empty for api_version=%s", api_version)
                continue
            # candidates: embedContent-capable + contains "embedding"
            embed_models: List[str] = []
            for m in models:
                if not isinstance(m, dict):
                    continue
                if not self._model_supports_embed_content(m):
                    continue
                name = normalize_model_name(str(m.get("name") or ""))
                if not name:
                    continue
                if "embedding" not in name.lower():
                    continue
                embed_models.append(name)

            logger.info("Self-heal: found %d embedding-capable models on %s: %s",
                        len(embed_models), api_version, embed_models[:10])

            # order: allowlist intersection first, else provider order
            if allow:
                ordered = [m for m in allow if m in set(embed_models)]
            else:
                ordered = []
            if not ordered:
                ordered = embed_models

            logger.info("Self-heal: probing %d candidates (api=%s): %s",
                        len(ordered[:20]), api_version, ordered[:20])

            # probe using the real text (already trimmed in generate_embedding_with_status)
            for candidate in ordered[:20]:
                emb, status, body = await self.generate_embedding_with_status(
                    text,
                    model=candidate,
                    api_version=api_version,
                    dimensions=int(preferred_dimensions or 0),
                )
                # If candidate exists but dimensionality differs, retry without requesting a fixed dimension.
                if (not emb) and is_dimension_mismatch(status, body):
                    logger.info("Self-heal: dimension mismatch for %s/%s, retrying without fixed dim",
                                candidate, api_version)
                    emb2, status_b, body_b = await self.generate_embedding_with_status(
                        text,
                        model=candidate,
                        api_version=api_version,
                        dimensions=0,
                    )
                    _ = status_b
                    _ = body_b
                    if emb2:
                        emb = emb2
                if emb:
                    actual_dim = len(emb)
                    logger.warning(
                        "Self-heal SUCCESS: switched to model=%s api=%s dim=%d",
                        candidate, api_version, actual_dim,
                    )
                    # Persist best-effort so future calls don't need self-heal
                    try:
                        from services.semantic_embedding_settings import upsert_embedding_settings  # type: ignore

                        persisted = upsert_embedding_settings(
                            api_version=api_version,
                            model=candidate,
                            # Prefer the actual returned dimension (safe) over the old preferred dimension.
                            dimensions=int(actual_dim or 0),
                            allowlist=allow or None,
                            # חשוב: לא לדרוס legacy_key - נשמור את הערך הקיים כדי לא לאבד מעקב על embeddings ישנים.
                            legacy_key=legacy_to_keep or None,
                            active_key=None,
                            reason="self_heal_404",
                            extra={"lastSelfHealAt": datetime.now(timezone.utc)},
                        )
                        if not persisted:
                            logger.warning("Self-heal: embedding found but failed to persist config to DB")
                    except Exception as exc:
                        logger.warning("Self-heal: failed to persist config: %s", exc)
                    return emb
                logger.info("Self-heal: candidate %s/%s failed (status=%s)", candidate, api_version, status)

        logger.error("Self-heal FAILED: no working embedding model found after probing all candidates")
        return None

    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate an embedding for a single text (async).

        Args:
            text: input text

        Returns:
            embedding vector or None on failure
        """
        # Pull dynamic settings (DB-backed) if available; fallback to ENV constants.
        settings = None
        try:
            settings = get_embedding_settings_cached(allow_db=True)
        except Exception:
            settings = None

        if settings is not None:
            model = getattr(settings, "model", "") or GEMINI_EMBEDDING_MODEL
            api_version = getattr(settings, "api_version", "") or GEMINI_API_VERSION
            dimensions = int(getattr(settings, "dimensions", 0) or EMBEDDING_DIMENSIONS)
            allowlist = list(getattr(settings, "allowlist", []) or [])
        else:
            model = GEMINI_EMBEDDING_MODEL
            api_version = GEMINI_API_VERSION
            dimensions = EMBEDDING_DIMENSIONS
            allowlist = []

        embedding, status1, _body1 = await self.generate_embedding_with_status(
            text,
            model=str(model),
            api_version=str(api_version),
            dimensions=int(dimensions),
        )
        # Fail-open fallback: אם הוגדר v1beta אבל המודל לא קיים שם (404),
        # נסה פעם אחת v1 (גם אם עדכון קונפיג ב-DB נכשל).
        status2 = None
        try:
            if embedding is None and int(status1 or 0) == 404 and str(api_version or "").strip() != "v1":
                logger.info("Model %s returned 404 on %s, trying v1 fallback", model, api_version)
                embedding2, status2, _body2 = await self.generate_embedding_with_status(
                    text,
                    model=str(model),
                    api_version="v1",
                    dimensions=int(dimensions),
                )
                if embedding2:
                    logger.info("v1 fallback succeeded for model %s", model)
                    return embedding2
                logger.info("v1 fallback also failed for model %s (status=%s)", model, status2)
        except Exception as exc:
            logger.warning("v1 fallback raised exception: %s", exc)
        # Self-heal: if current model is 404 (and v1 fallback didn't return an embedding),
        # try to pick a working model from ListModels automatically.
        try:
            if embedding is None and int(status1 or 0) == 404:
                logger.warning("Model %s is 404 on all API versions, initiating self-heal", model)
                healed = await self._self_heal_on_404(
                    text=text,
                    preferred_dimensions=int(dimensions),
                    preferred_allowlist=allowlist,
                    existing_legacy_key=str(getattr(settings, "legacy_key", "") or "") if settings is not None else "",
                    existing_active_key=str(getattr(settings, "active_key", "") or "") if settings is not None else "",
                )
                if healed:
                    return healed
                logger.warning("Self-heal returned no embedding for model %s", model)
        except Exception as exc:
            logger.error("Self-heal raised unexpected exception: %s", exc, exc_info=True)
        # Keep old behavior: just return embedding or None.
        # Special case: if model is missing (404), callers may run startup health check to auto-upgrade.
        _ = status1
        return embedding

    async def close(self) -> None:
        """Close the client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


# Singleton instance
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get a singleton instance of the embedding service."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def compute_content_hash(content: str) -> str:
    """Compute a hash of content for change tracking."""
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()


# ---------------------------------------------------------------------------
# לקוח סינכרוני — לקוד שרץ בוובאפ תחת WSGI
# ---------------------------------------------------------------------------


class SyncEmbeddingClient:
    """לקוח הטמעות סינכרוני, באצוות של ``batchEmbedContents``, לקוד שרץ בוובאפ.

    **למה לא :meth:`EmbeddingService.embed_batch`.** הוא אסינכרוני, ובוובאפ (gunicorn עם
    worker של gevent) אי אפשר להריץ לולאת asyncio בבטחה מקוד סינכרוני — ראו
    ``docs/observability/asyncio-loop-safety.rst``. מה שמשותף לשניהם יושב ברמת המודול: בדיקת
    הקלט (``_check_batch_size``, ``_check_batch_texts``), הבקשה (``_batch_request``), הפענוח של
    התשובה (``_parse_batch_response``), תיאור השגיאה (``_error_summary``), השער לקצב ול-cooldown
    אחרי 429, והסיווג (:func:`classify_embedding_status`). שונים: התעבורה, הדדליין, מדיניות
    הניסיונות שלמטה, והמשקל בשער — כאן מרווח אחד לבקשה (ההסבר בהערה מעל
    ``EMBEDDING_MIN_INTERVAL_SECONDS``).

    **המפתח** בכותרת ``x-goog-api-key`` שעל הלקוח, והלקוח פונה ל-:data:`GEMINI_API_HOST`
    בלבד — אותו אינווריאנט כמו ב-:attr:`EmbeddingService.client`.

    **ההמתנה מוגבלת.** הקורא מעביר ``deadline`` (ערך של ``time.monotonic``) בכל קריאה. הוא
    נבדק לפני כל ניסיון ולפני השינה בשער, וה-timeout של כל בקשה הוא הקטן מבין
    :data:`REQUEST_TIMEOUT` ומה שנשאר עד הדדליין; בתוך בקשה אחת httpx מחיל אותו על כל שלב
    (חיבור, כתיבה, קריאה) בנפרד.

    **החוזה** של :meth:`embed_batch` הוא החוזה של :meth:`EmbeddingService.embed_batch`:
    ``(וקטורים | None, סטטוס, תיאור)``. כאן 429 חוזר מיד, בלי ניסיון חוזר — הקורא מחליט — ודוחף
    את השער המשותף קדימה.

    מופע אחד לכל מעבר, ונסגר בסופו (``with``); אין מופע משותף ברמת המודול.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        # ``None`` = "קח מהסביבה", מחרוזת ריקה = "אין מפתח" — כמו ב-:class:`EmbeddingService`.
        self.api_key = GEMINI_API_KEY if api_key is None else api_key
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-goog-api-key"] = self.api_key
        # ``follow_redirects`` נשאר כבוי (ברירת המחדל של httpx). בהפניה ל-origin אחר httpx
        # מסיר רק את ``Authorization`` ומשאיר כותרות אחרות (``_redirect_headers`` ב-
        # ``httpx/_client.py``, ‏0.28.1), כלומר בקשה שהייתה עוקבת אחרי הפניה הייתה לוקחת
        # את כותרת המפתח ליעד אחר.
        self._client = httpx.Client(timeout=REQUEST_TIMEOUT, headers=headers, transport=transport)

    def is_available(self) -> bool:
        return bool(self.api_key)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SyncEmbeddingClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def embed_batch(
        self,
        texts: Sequence[str],
        *,
        model: str,
        api_version: str,
        dimensions: int,
        deadline: float,
    ) -> Tuple[Optional[List[List[float]]], int, str]:
        """מטמיע עד :data:`GEMINI_MAX_BATCH_REQUESTS` טקסטים בקריאה אחת.

        מחזיר ``(וקטורים, 200, "")`` בהצלחה — וקטור לכל טקסט, באותו סדר. בכשל:
        ``(None, סטטוס, תיאור)``, כשהסטטוס הוא קוד ה-HTTP, או אחד הפנימיים: ``0`` (אין
        מפתח, הדדליין עבר, או שהבקשה לא קיבלה תשובה), ``413``
        (:data:`EMBEDDING_STATUS_INPUT_TOO_LONG`), ``422`` (מימד שונה מהמבוקש), ו-``200``
        בלי וקטורים (תשובה שאינה בצורה הצפויה).

        ``texts`` ריק, או ארוך מהתקרה, הוא שימוש שגוי ונדחה ב-``ValueError``.
        """
        items = list(texts)
        _check_batch_size(items)
        if not self.is_available():
            return None, 0, EMBEDDING_DETAIL_MISSING_API_KEY
        invalid = _check_batch_texts(items)
        if invalid is not None:
            return invalid
        url, body, dim = _batch_request(
            items,
            base_url=gemini_models_base_url(api_version),
            model=model,
            dimensions=dimensions,
        )

        last = ""
        for attempt in range(MAX_RETRIES):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, 0, EMBEDDING_DETAIL_DEADLINE_EXCEEDED
            wait = _reserve_throttle_slot(max_wait=remaining)
            if wait is None:
                return None, 0, EMBEDDING_DETAIL_DEADLINE_EXCEEDED
            if wait > 0:
                time.sleep(wait)
            timeout = min(REQUEST_TIMEOUT, deadline - time.monotonic())
            if timeout <= 0:
                return None, 0, EMBEDDING_DETAIL_DEADLINE_EXCEEDED
            try:
                response = self._client.post(url, json=body, timeout=timeout)
            except httpx.TransportError as exc:
                # רשת או timeout: אין תשובת HTTP. רק תת-העץ של התעבורה — חריגה אחרת היא
                # באג, ועולה הלאה.
                last = f"transport_error: {type(exc).__name__}"
                logger.warning("Embedding batch attempt %s failed: %s", attempt + 1, last)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(max(0.0, min(RETRY_DELAY_SECONDS, deadline - time.monotonic())))
                    continue
                return None, 0, last

            if response.status_code == 200:
                return _parse_batch_response(response, count=len(items), dim=dim)

            summary = _error_summary(response)
            if response.status_code == 429:
                _push_cooldown_after_429()
                return None, 429, summary
            if (
                classify_embedding_status(response.status_code) == FAILURE_TRANSIENT
                and attempt < MAX_RETRIES - 1
            ):
                last = summary
                logger.warning("Embedding batch attempt %s failed: %s", attempt + 1, summary)
                time.sleep(max(0.0, min(RETRY_DELAY_SECONDS, deadline - time.monotonic())))
                continue
            return None, int(response.status_code), summary

        return None, 0, last
