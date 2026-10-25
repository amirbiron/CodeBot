"""``GET /api/agent/primer`` — פריימר טקסטואלי שנקרא בפתיחת סשן של סוכן AI.

הגוף הוא ``text/plain``, לא JSON: מה שיוצא מכאן נכנס להקשר של המודל **כפי שהוא**.
הוא מורכב משני חלקים — הוראות חופשיות שהמשתמש עורך בדפדפן (עיקר התוכן), ואחריהן
שורת מצב קצרה שנבנית בזמן אמת.

ארבעה אילוצים מעצבים את הקוד כאן:

* **אימות.** הראוט קורא ל-``authenticate_bearer`` בגוף שלו. הוא *לא* מסתמך על כך
  שהאפליקציה מוגנת: במצב OAuth (הפרודקשן) ה-``PATAuthMiddleware`` לא מותקן בכלל,
  וה-SDK עוטף רק את ה-mount של ``/mcp`` — ראוט שנרשם ידנית יוצא ציבורי. ראו את
  ה-docstring של ``mcp_server.auth``.
* **תקרת 24KB.** חורגים ⇒ חותכים ומוסיפים שורה שאומרת שנחתך. לעולם לא שגיאה:
  פריימר חתוך עדיף על פריימר חסר.
* **60 שניות cache.** נקרא בפתיחת כל סשן, ולכן אסור לו לגעת בשאילתה כבדה.
* **סינון סודות.** הפריימר עובר דרך המודל, ולכן הוא מסונן בכל מקרה — גם אם
  המשתמש הדביק מפתח לשדה ההוראות בטעות. ערכי משתני סביבה של השרת לא נכנסים
  לגוף כלל: אין כאן שום קריאה ל-``os.environ``.

התקרה וה-TTL הם **קבועים בקוד** ולא משתני סביבה, במכוון. התקרה אינה כוונון
תפעולי אלא תקציב מול חלון ההקשר של המודל, שמתחלק עם כל השאר בסשן; אילו היה
משתנה סביבה, מצב הכשל של העלאתו היה בלתי-נראה (הקשר נאכל בשקט, בלי שאף אחד
מתריע). שינוי דורש PR — וזה החיכוך הנכון.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

import anyio
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from .auth import authenticate_bearer, is_admin_user, unauthorized

# מיוצא מחדש בשם המקורי כדי ש-``from mcp_server.primer import redact_secrets``
# ימשיך לעבוד: זה מה שהטסטים ושאר הקוד קוראים לו.
from .redaction import redact_secrets  # noqa: F401  — חלק מה-API של המודול הזה

logger = logging.getLogger(__name__)

PRIMER_PATH = "/api/agent/primer"

#: תקרת גודל הגוף בבייטים. קבוע במכוון — ראו את ה-docstring של המודול.
MAX_BYTES = 24 * 1024

#: משך ה-cache בשניות.
CACHE_TTL_SECONDS = 60

#: כותרת ה-cache. ``private`` — פריימר הוא תוכן אישי, אסור לפרוקסי משותף לשמור אותו.
_CACHE_CONTROL = f"private, max-age={CACHE_TTL_SECONDS}"

#: כמה קבצים אחרונים מופיעים בשורת המצב.
RECENT_FILES_COUNT = 3

#: תקרת ערכים ב-cache התהליכי (מונע דליפת זיכרון בשירות ארוך-חיים).
MAX_CACHE_ENTRIES = 512

#: תקרת גודל לשורת המצב. שמות הקבצים הם קלט משתמש, ובלי תקרה שלושה שמות ארוכים
#: היו יכולים לדחוף את הגוף כולו מעל ``MAX_BYTES``.
MAX_STATUS_BYTES = 512

#: כמה פתקים שממתינה בהם תגובה לסוכן מופיעים בשורת התגובות; השאר — "ועוד N".
PENDING_THREADS_COUNT = 3

#: תקרת גודל לשורת התגובות — **תקציב משלה**, באותה שיטה של שורת הקבצים ולא מתוך
#: :data:`MAX_STATUS_BYTES`: כותרות פתקים ושמות לוחות הם קלט משתמש, ושלושה ארוכים היו
#: דוחפים את שורת הקבצים החוצה.
MAX_PENDING_STATUS_BYTES = 512

#: אורך מקסימלי, בתווים, לכל שם בשורת התגובות — כותרת הפתק (או תחילת הגוף כשאין כותרת),
#: שם הלוח או הקובץ. מקוצר עם "…": זו תווית לזיהוי, ולא התוכן — ה-``note_id`` שלידה הוא
#: מה שהסוכן ממשיך איתו. גם התקרה הזו היא מה שמבטיח שפריט אחד תמיד נכנס בתקציב השורה.
PENDING_LABEL_CHARS = 40

#: סף האזהרה שה-UI בוובאפ מציג. חי כאן כי ``MAX_BYTES`` הוא מקור האמת שלו —
#: ``webapp.routes.settings_routes`` משכפל את שניהם (שני שירותים נפרדים, בלי
#: ייבוא ביניהם) ו-``test_mcp_primer`` מוודא שהערכים לא התפצלו.
WARN_BYTES = 21 * 1024

_TRUNCATION_NOTICE = (
    f"\n[הפריימר נחתך כאן: ההוראות חורגות מתקרת {MAX_BYTES // 1024}KB. "
    "קצרו אותן בהגדרות CodeKeeper — ההמשך לא נשלח לסוכן.]"
)

_SEPARATOR = "\n\n---\n"


# --------------------------------------------------------------------------
# סינון סודות
# --------------------------------------------------------------------------
# הרשימה עצמה חיה ב-``mcp_server.redaction`` ולא כאן, מרגע ששער הפרטיות של
# האנליטיקס נזקק לה גם הוא (``analytics.py``). ``primer`` הוא ראוט HTTP
# ומייבא ``starlette`` ואת ``auth``; ``analytics`` אינו צריך אף אחד מהם,
# ולכן הוא לא צריך לייבא ראוט רק כדי להגיע לרג'קס. שתי רשימות נפרדות כבר
# נכשלו בפרויקט הזה: דפוס נוסף לאחת ולא לשנייה.
#
# ``redact_secrets`` מיובא בראש הקובץ ומיוצא מחדש מכאן.


# --------------------------------------------------------------------------
# הרכבת הגוף
# --------------------------------------------------------------------------
def _truncate_to_bytes(text: str, max_bytes: int) -> tuple[str, bool]:
    """חותך ל-``max_bytes`` בגבול תו UTF-8 שלם.

    מחזיר ``(טקסט, נחתך?)``. חיתוך נאיבי של ``encode()[:n]`` היה יכול לחצות תו
    עברי באמצע ולהוציא בייטים לא-תקינים — ולכן ``errors="ignore"`` בפענוח החוזר,
    שמפיל בדיוק את התו החלקי האחרון.
    """
    if max_bytes <= 0:
        return "", bool(text)
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text, False
    return raw[:max_bytes].decode("utf-8", errors="ignore"), True


def _relative_time(when: datetime, *, now: datetime) -> str:
    """מתי נשמר, בשפה טבעית — בלי לדרוש מהסוכן לדעת מה השעה עכשיו."""
    delta = now - when
    seconds = int(delta.total_seconds())
    if seconds < 0:  # שעון שלא מסונכרן — לא ממציאים עתיד
        return "לפני רגע"
    minutes, hours, days = seconds // 60, seconds // 3600, seconds // 86400
    if seconds < 90:
        return "לפני רגע"
    if minutes < 60:
        return "לפני דקה" if minutes == 1 else f"לפני {minutes} דקות"
    if hours < 24:
        return "לפני שעה" if hours == 1 else f"לפני {hours} שעות"
    if days < 30:
        return "אתמול" if days == 1 else f"לפני {days} ימים"
    return when.strftime("%Y-%m-%d")


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def build_status_line(files: list[dict[str, Any]], *, now: datetime | None = None) -> str:
    """שורת המצב: שמות הקבצים האחרונים שנשמרו ומתי. ותו לא.

    מחזיר מחרוזת ריקה כשאין קבצים — שורת מצב ריקה עדיפה על שורה שמדווחת על כלום.
    """
    now = now or datetime.now(UTC)
    parts: list[str] = []
    for item in files or []:
        name = str((item or {}).get("file_name") or "").strip()
        if not name:
            continue
        when = _as_utc((item or {}).get("saved_at"))
        parts.append(f"{name} ({_relative_time(when, now=now)})" if when else name)
    if not parts:
        return ""
    return "קבצים אחרונים שנשמרו ב-CodeKeeper: " + ", ".join(parts)


_PENDING_PREFIX = "תגובות שממתינות לסוכן: "


def _label(text: Any) -> str:
    """שם לשורת התגובות: שורה אחת, מסונן מסודות, עד :data:`PENDING_LABEL_CHARS` תווים.

    **הסינון לפני הקיצוץ, ולא אחריו.** קיצוץ קודם היה יכול לחתוך טוקן באמצעו — ``ghp_``
    ועוד ארבעה-עשר תווים כבר אינו מזוהה כסוד, ותחילתו של טוקן אמיתי הייתה יוצאת לפריימר.
    הקיצוץ בתווים (נקודות קוד) ולא בבתים, כך שתו עברי אינו נחתך באמצע (H6).
    """
    from sticky_notes_target import canonical_title_text

    one_line = redact_secrets(canonical_title_text(text))
    if len(one_line) > PENDING_LABEL_CHARS:
        one_line = one_line[: PENDING_LABEL_CHARS - 1].rstrip() + "…"
    return one_line


def _pending_item(item: dict[str, Any]) -> str:
    """פריט אחד: ``"כותרת" <איפה הפתק> (note_id …)`` — הצורה שבאפיון."""
    title = _label(item.get("title")) or _label(item.get("preview")) or "פתק"
    target = item.get("target")
    if target == "board":
        where = " בלוח " + (_label(item.get("board_name")) or "")
    elif target == "file":
        where = " בקובץ " + (_label(item.get("file_name")) or "")
    elif target == "repo":
        where = f" בקובץ {_label(item.get('repo_path'))} בריפו {_label(item.get('repo_name'))}"
    elif target == "archive":
        # ההעברה לארכיון סוגרת את השרשורים הפתוחים, ולכן פתק ארכיון מגיע לכאן רק אחרי
        # שהמשתמש ענה בו שוב — וזה בדיוק המקרה שבו הסוכן צריך לדעת איפה לחפש.
        where = " בארכיון"
    else:
        where = ""
    return f'"{title}"{where.rstrip()} (note_id {item.get("note_id")})'


def build_pending_threads_line(pending: dict[str, Any] | None, *, max_bytes: int) -> str:
    """שורת המצב השנייה: הפתקים שמחכה בהם תגובה לסוכן — בתוך ``max_bytes`` בתים.

    ``pending`` הוא מה ש-``ProductionBackend.pending_note_threads`` החזיר: ``total`` (כמה
    פתקים בסך הכול) ו-``items`` (הראשונים, החדש ביותר קודם). השורה נבנית **פריט אחרי
    פריט**: כל פריט שלם נכנס, או לא נכנס — כך ש-``note_id`` לעולם אינו נחתך באמצע, ו"ועוד N"
    סופר בדיוק את מה שלא הוצג. כל שם עובר :func:`_label`, והשורה כולה עוברת
    ``redact_secrets`` לפני שהיא נמדדת.

    מחרוזת ריקה כשאין מה לדווח — או כשהשורה לא נכנסת אפילו כספירה בלבד.
    """
    if not isinstance(pending, dict):
        return ""
    items = [i for i in (pending.get("items") or []) if isinstance(i, dict) and i.get("note_id")]
    total = pending.get("total")
    total = total if isinstance(total, int) and total >= len(items) else len(items)
    if total <= 0:
        return ""

    def compose(shown: list[str]) -> str:
        rest = total - len(shown)
        if not shown:
            return f"{_PENDING_PREFIX}{total} פתקים"
        return _PENDING_PREFIX + ", ".join(shown) + (f", ועוד {rest}" if rest > 0 else "")

    def fits(line: str) -> bool:
        return len(line.encode("utf-8")) <= max_bytes

    shown: list[str] = []
    line = redact_secrets(compose(shown))
    for item in items:
        candidate = redact_secrets(compose(shown + [_pending_item(item)]))
        if not fits(candidate):
            break
        shown.append(_pending_item(item))
        line = candidate
    return line if fits(line) else ""


def build_primer(
    instructions: str,
    files: list[dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
    max_bytes: int = MAX_BYTES,
    pending: dict[str, Any] | None = None,
) -> str:
    """מרכיב את גוף הפריימר המלא, מסונן וחתוך לפי הצורך.

    מחזיר מחרוזת ריקה כשאין הוראות — הקורא הופך את זה ל-204. הפריימר קיים כדי
    לשאת את ההוראות; שמות קבצים בלי מסגור הם רעש, לא פריימר — וכך גם שורת התגובות:
    בלי הוראות אין פריימר, ולכן גם אין שורת תגובות.

    ``pending`` הם הפתקים שמחכה בהם תגובה לסוכן (:func:`build_pending_threads_line`): שורת
    מצב שנייה, אחרי שורת הקבצים, עם **תקציב משלה** (:data:`MAX_PENDING_STATUS_BYTES`) ובאותה
    שיטה — מקום שמור לפני ההוראות.
    """
    # מסננים לפני המדידה: הצנזור משנה אורך, ומדידה על טקסט לא-מסונן הייתה
    # מוציאה גוף שחורג מהתקרה אחרי הסינון.
    body = redact_secrets((instructions or "").strip())
    if not body:
        return ""

    # שורת המצב עוברת את אותו סינון. שמות הקבצים מגיעים מ-``code_snippets``
    # ולכן הם נשלטים ע"י המשתמש: קובץ ששמור בשם בצורת מפתח היה יוצא כאן כמו
    # שהוא — בדיוק הנתיב שהסינון "על כל הגוף" נועד לחסום.
    status = redact_secrets(build_status_line(files or [], now=now))
    # ותקרה משלה, כדי ששמות קבצים ארוכים (גם הם קלט משתמש) לא ידחפו את הגוף
    # מעל ``max_bytes``. חלוקה יחסית ולא קבוע, כדי שגם ``max_bytes`` קטן בטסטים
    # ישאיר את רוב המקום להוראות.
    status_budget = min(MAX_STATUS_BYTES, max(max_bytes // 4, 0))
    status, _ = _truncate_to_bytes(status, status_budget)
    # שורת התגובות — תקציב משלה באותה שיטה, ובנייה פריט-פריט שאינה חותכת note_id.
    pending_line = build_pending_threads_line(
        pending, max_bytes=min(MAX_PENDING_STATUS_BYTES, max(max_bytes // 4, 0))
    )
    lines = [line for line in (status, pending_line) if line]
    suffix = f"{_SEPARATOR}" + "\n".join(lines) + "\n" if lines else "\n"

    # שורת המצב מקבלת מקום שמור: היא נבנית ראשונה ונחסרת מהתקציב, כדי שהוראות
    # ארוכות לא ידחפו אותה החוצה מהגוף.
    suffix_bytes = len(suffix.encode("utf-8"))
    notice_bytes = len(_TRUNCATION_NOTICE.encode("utf-8"))

    budget = max_bytes - suffix_bytes
    kept, truncated = _truncate_to_bytes(body, budget)
    if truncated:
        # מפנים מקום גם להודעת החיתוך עצמה — אחרת התוספת שלה תחזיר אותנו מעל התקרה.
        kept, _ = _truncate_to_bytes(body, max(budget - notice_bytes, 0))
        kept = kept.rstrip() + _TRUNCATION_NOTICE

    result = kept + suffix
    # רשת ביטחון אחרונה: החוזה של המודול הוא שהגוף לעולם לא חורג מהתקרה, ולכן
    # הוא נאכף על התוצאה עצמה ולא נגזר מנכונות החישובים שמעל.
    final, over = _truncate_to_bytes(result, max_bytes)
    return final if over else result


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------
class PrimerCache:
    """Cache תהליכי לפי ``user_id``, עם TTL ותקרת ערכים.

    לפי משתמש ולא גלובלי — פריימר של משתמש אחד לעולם לא יוגש לאחר. הזמן נמדד
    ב-``monotonic`` כדי שקפיצת שעון מערכת לא תאריך או תקצר TTL.
    """

    def __init__(
        self, ttl_seconds: float = CACHE_TTL_SECONDS, max_entries: int = MAX_CACHE_ENTRIES
    ):
        self._ttl = float(ttl_seconds)
        self._max = int(max_entries)
        self._lock = threading.Lock()
        self._data: dict[int, tuple[float, str]] = {}

    def get(self, user_id: int) -> str | None:
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(int(user_id))
            if entry is None:
                return None
            expires_at, body = entry
            if expires_at <= now:
                self._data.pop(int(user_id), None)
                return None
            return body

    def put(self, user_id: int, body: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._data) >= self._max:
                # קודם ניקוי פגים; אם עדיין צפוף — מפנים את הישן ביותר.
                for key in [k for k, (exp, _) in self._data.items() if exp <= now]:
                    self._data.pop(key, None)
                while len(self._data) >= self._max:
                    oldest = min(self._data, key=lambda k: self._data[k][0])
                    self._data.pop(oldest, None)
            self._data[int(user_id)] = (now + self._ttl, body)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


#: ה-cache של השירות. מיוצא כדי שהוובאפ־צד־הבוט לא יצטרך להכיר את המבנה, ושטסטים
#: יוכלו לאפס אותו בין מקרים.
primer_cache = PrimerCache()


# --------------------------------------------------------------------------
# הראוט
# --------------------------------------------------------------------------
def _load_primer_sync(backend: Any, user_id: int) -> str:
    """שליפה + הרכבה. סינכרוני במכוון — הקורא מריץ אותו ב-thread נפרד."""
    try:
        instructions = backend.get_agent_instructions(int(user_id)) or ""
    except Exception:
        logger.warning("primer: failed to read agent instructions", exc_info=True)
        instructions = ""
    if not instructions.strip():
        # אין הוראות ⇒ 204. לא נוגעים במסד בשביל שורת מצב שלא תוגש.
        return ""
    try:
        files = backend.recent_files(int(user_id), limit=RECENT_FILES_COUNT) or []
    except Exception:
        # שורת המצב היא תוספת. אם היא נכשלה — עדיין מגישים את ההוראות.
        logger.warning("primer: failed to read recent files", exc_info=True)
        files = []
    # שורת התגובות היא תוספת, כמו שורת הקבצים: כשל בה אינו מפיל את ההוראות. שני סוגי
    # הכשל נפרדים בכוונה (R10). שגיאת מסד נתפסת בתוך ``pending_note_threads`` ונרשמת שם
    # ב-WARNING: בקריאה העיקרית (השרשורים והפתקים) הוא מחזיר ``None`` ("לא ידוע") והשורה
    # אינה מוצגת, ובקישוטים (שמות לוחות וקבצים) השורה מוצגת בלעדיהם — ולכן ה-``except`` כאן
    # אינו רואה אותה. כל חריגה אחרת היא באג במסלול החדש, ולכן היא נרשמת כאן ב-ERROR עם
    # traceback מלא — לא בתווית של כשל המסד — וההוראות מוגשות בלי השורה. בלי זה הראוט היה
    # מחזיר 500, וההוראות היו הולכות לאיבוד לכל משתמש. פתקי ריפו נספרים רק לאדמין: אותו
    # שער של ``codekeeper_get_note``, כדי שהשורה לא תפנה לפתק שהסוכן לא יוכל לקרוא.
    try:
        pending = backend.pending_note_threads(
            int(user_id),
            limit=PENDING_THREADS_COUNT,
            include_repo_notes=is_admin_user(int(user_id)),
            preview_chars=PENDING_LABEL_CHARS,
        )
    except Exception:
        logger.exception(
            "primer: reading the notes that wait for an agent failed unexpectedly; "
            "serving the instructions without the pending-comments line"
        )
        pending = None
    return build_primer(instructions, files, pending=pending)


def agent_primer_route(
    backend: Any,
    *,
    token_store: Any = None,
    auth_provider: Any = None,
    cache: PrimerCache | None = None,
) -> Route:
    """בונה את ה-``Route`` של ``GET /api/agent/primer``.

    ``token_store``/``auth_provider`` הם אותם מאמתים שבהם משתמש טרנספורט ה-MCP —
    הראוט לא בונה מנגנון אימות משלו, רק קורא לאותו נתיב ולידציה.
    """
    active_cache = cache if cache is not None else primer_cache

    async def endpoint(request):
        principal = await authenticate_bearer(
            request, token_store=token_store, auth_provider=auth_provider
        )
        if not principal:
            return unauthorized("invalid_token")

        user_id = int(principal["user_id"])
        body = active_cache.get(user_id)
        if body is None:
            # קריאות pymongo חוסמות — מחוץ ל-event loop.
            body = await anyio.to_thread.run_sync(_load_primer_sync, backend, user_id)
            active_cache.put(user_id, body)

        if not body:
            # אין הוראות ⇒ אין פריימר. 204 ולא 200 עם גוף ריק.
            return Response(status_code=204, headers={"Cache-Control": _CACHE_CONTROL})

        return PlainTextResponse(
            body,
            media_type="text/plain; charset=utf-8",
            headers={"Cache-Control": _CACHE_CONTROL},
        )

    return Route(PRIMER_PATH, endpoint, methods=["GET"])
