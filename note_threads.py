"""שרשורי תגובות על פתקים — המודל והכללים, פעם אחת, לשני השירותים.

על פתק אפשר לפתוח שרשורי תגובות: המשתמש מגיב מהוובאפ, וכל סוכן מגיב דרך ה-MCP
(``codekeeper_comment_note``). כל שרשור הוא מסמך אחד באוסף :data:`NOTE_THREADS_COLLECTION`,
והתגובות יושבות בתוכו. מקור הדרישות: האפיון "שרשורי תגובות על פתקים" ב-Ck, וההחלטות
שבפתק שעליו (הפיצ'ר פתוח לכל המשתמשים; תשובה על שרשור שנפתר פותחת אותו כברירת מחדל,
ואפשר גם לענות בלי לפתוח).

**למה מודול משותף בשורש.** לאוסף יש שני כותבים: שירות ה-MCP, והוובאפ (ה-PR שאחרי זה).
כלל שכתוב פעמיים מתפצל — שדה נגזר שאחד הכותבים שוכח לעדכן הוא בדיוק
``derived-field-added-to-one-writer``. לכן **כל** בניית מסמך וכל שינוי של ``note_threads``
עוברים דרך הפונקציות כאן, ו-``tests/test_note_threads_single_writer.py`` סורק את הריפו
ונופל על כתיבה לאוסף מכל מקום אחר.

**טהור**, כמו ``sticky_notes_target`` ו-``mcp_uploads``: בלי Flask ובלי pymongo בזמן הייבוא,
ובלי שום תופעת לוואי בייבוא. פעולות על המסד מקבלות את האוסף בהזרקה, ו-``bson`` /
``pymongo`` נטענים בתוך הפונקציות שצריכות אותם.

**אטומיות.** כל שינוי של שרשור קיים הוא ``find_one_and_update`` אחד: התגובה נדחפת
(``$push``), ובאותה פעולה מתעדכנים ``last_author_kind``, ``last_at``, הסטטוס והמונים.
אין מצב ביניים שבו התגובה נכתבה והסטטוס עוד לא (``state-record-without-state-change``).
התנאים — התקרות, והסטטוס שהפעולה דורשת — יושבים **בפילטר** (CAS), ולכן שתי כתיבות
מקבילות אינן יכולות לעבור תקרה יחד (``race-toctou``). כשהפילטר לא תפס, קריאה חוזרת
מסווגת למה, וזו התשובה.

**התחום הוא תמיד המשתמש, ובפעולה על פתק אחד — גם הפתק.** כל שאילתה כאן מסננת ``user_id``,
וכל מסמך שנכתב נושא אותו. כל מה שפועל על השרשורים של פתק אחד תחום ל-``user_id`` ול-``note_id``
יחד (:func:`thread_scope`): :func:`create_thread` והקריאה החוזרת אחריה, :func:`add_comment`,
:func:`resolve_thread` ו-:func:`reopen_thread` (כולל הקריאה שמסווגת למה העדכון לא תפס),
:func:`list_threads`, :func:`load_comments` ו-:func:`delete_note_threads`. זה נכון גם כשיש
``_id`` של שרשור: מזהה שרשור של משתמש אחר, או של פתק אחר של אותו משתמש, הוא "לא נמצא".
**ארבע קריאות עוברות על כמה פתקים, ולכן אינן תחומות לפתק אחד — בכוונה:**
:func:`open_thread_counts` סופרת בשאילתה אחת את השרשורים הפתוחים בפתקים שהקורא העביר
(``note_id`` מתוך הרשימה שלו), :func:`list_threads_for_notes` מחזירה בשאילתה אחת את תקצירי
השרשורים של הפתקים שהקורא העביר (הבועות ברשימת הפתקים בוובאפ), :func:`comments_by_ref`
שולפת תגובות לפי מזהה בשביל שולח הפוש, ו-:func:`pending_for_agent` עוברת על כל הפתקים של
המשתמש, בשביל שורת הפריימר.

**ההרשאה עצמה אינה כאן**, אלא אצל הקורא. בפעולה על פתק אחד היא נבדקת **לפני** הקריאה
לפונקציה כאן: הפתק שייך לקורא, ופתק ריפו פתוח רק לאדמין — ב-MCP זה השער המשותף של
``codekeeper_get_note`` ו-``codekeeper_comment_note`` (``mcp_server/handlers.py``). בשורת
הפריימר היא חלה על התוצאה: ``pending_note_threads`` (``mcp_server/backend.py``) משאירה מתוך
:func:`pending_for_agent` רק פתקים ש-``codekeeper_get_note`` היה מחזיר לקורא. ``user_id``
מגיע תמיד מהזהות המאומתת של הקורא (ב-MCP — הטוקן), ולעולם לא מארגומנט שהלקוח שלח.

**מחיקת פתק.** מחיקת פתק בוובאפ היא מחיקה קשה (``delete_one``), ואין לפתקים סל מחזור,
ולכן שרשורים אינם "חוזרים" עם פתק משוחזר — גיבוי משחזר פתק עם ``_id`` חדש.
:func:`delete_note_threads` מוחקת את שרשורי הפתק, וראוט המחיקה בוובאפ
(``webapp/sticky_notes_api.py:delete_note``) קורא לה **רק אחרי** שמחיקת הפתק עצמו הצליחה
(``deleted_count == 1``) — בסדר ההפוך, מחיקה שנכשלה הייתה מוחקת שרשורים של פתק שנשאר.
שרשור יתום עדיין אפשרי: כשמחיקת השרשורים נכשלת אחרי שהפתק נמחק, או כשסוכן מגיב בדיוק
ברגע שהפתק נמחק (הבדיקה שהפתק קיים קודמת לכתיבה). כל הקוראים כאן עמידים לו: הם מגיעים
לשרשורים דרך פתק קיים.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from file_dates import as_utc
from sticky_notes_target import canonical_title_text

__all__ = [
    "AGENT_CLIENT_LABELS",
    "AUTHOR_AGENT",
    "AUTHOR_USER",
    "MAX_CLIENT_NAME_CHARS",
    "MAX_COMMENTS_PER_THREAD",
    "MAX_COMMENT_CHARS",
    "MAX_THREAD_BODY_BYTES",
    "MAX_WORKING_ON_CHARS",
    "NOTE_COMMENT_PUSH_KIND",
    "NOTE_THREADS_BY_NOTE_INDEX",
    "NOTE_THREADS_COLLECTION",
    "NOTE_THREADS_PENDING_INDEX",
    "STATUS_OPEN",
    "STATUS_RESOLVED",
    "THREAD_SUMMARY_FIELDS",
    "UNKNOWN_AGENT_LABEL",
    "add_comment",
    "agent_author",
    "author_label",
    "awaits_user",
    "body_wire_bytes",
    "comment_body_error",
    "comments_by_ref",
    "create_thread",
    "delete_note_threads",
    "display_order",
    "is_canonical_note_id",
    "list_threads",
    "list_threads_for_notes",
    "load_comments",
    "normalize_client_name",
    "note_comment_push_event",
    "note_threads_indexes",
    "open_thread_counts",
    "parse_thread_id",
    "pending_for_agent",
    "reopen_thread",
    "resolve_thread",
    "stored_comment",
    "thread_scope",
    "user_author",
    "working_on_or_error",
]

logger = logging.getLogger(__name__)

NOTE_THREADS_COLLECTION = "note_threads"

#: תקרת אורך לתגובה, בתווים (נקודות קוד). המספר מהעיצוב — המונה "0 / 4,000" — ומההחלטה
#: שבפתק על האפיון, שהחליפה את ההצעה של אלפיים.
MAX_COMMENT_CHARS = 4_000

#: כמה תגובות שרשור אחד מחזיק. בלם ללולאה של סוכנים שעונים זה לזה: בלי תקרה, "שרשורים
#: קצרים" היא הבטחה ולא חוזה.
MAX_COMMENTS_PER_THREAD = 50

#: תקרת אורך ל-``working_on`` — "על מה הסוכן עבד", שורה אחת ליד שם הסוכן.
MAX_WORKING_ON_CHARS = 60

#: תקרת אורך לשם הלקוח שנשמר ליד תגובת סוכן — מה שהלקוח הצהיר בחיבור; השמות שנצפו
#: בייצור קצרים בהרבה (``claude-code``, ``Anthropic/ClaudeAI``, ``Gemini``). התקרה חוסמת
#: את גודל המטא-דאטה של תגובה, ש-:data:`MAX_THREAD_BODY_BYTES` נשען עליו. זו תווית ולא
#: תוכן, ולכן היא מקוצרת ולא נדחית — כמו ``anchor_text`` של פתק.
MAX_CLIENT_NAME_CHARS = 64

#: תקרה על **סך הגדלים** של גופי התגובות בשרשור, בבתים כפי שהם נשלחים ב-JSON
#: (:func:`body_wire_bytes`). נאכפת אטומית בפילטר מול המונה ``body_bytes`` שבמסמך.
#:
#: **למה תקרה שלישית, שאינה באפיון:** בלעדיה שרשור מלא — 50 תגובות של 4,000 תווים בעברית —
#: שוקל כ-400KB, יותר מתקציב תשובה של שרת ה-MCP (``OUTPUT_BYTE_BUDGET``), ושום קריאה לא
#: הייתה מחזירה אותו שלם: התגובות הראשונות היו נעלמות מכל סוכן. עם התקרה, שרשור אחד תמיד
#: נכנס בתשובה אחת, וזה מעוגן בטסט שבונה את השרשור הגרוע ביותר ומודד אותו כפי שהוא נשלח.
#: שרשור שהגיע לתקרה עונה ``thread_too_long``, וממשיכים בשרשור חדש על אותו פתק.
MAX_THREAD_BODY_BYTES = 160_000

STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"
_STATUSES = (STATUS_OPEN, STATUS_RESOLVED)

AUTHOR_USER = "user"
AUTHOR_AGENT = "agent"
_AUTHOR_KINDS = (AUTHOR_USER, AUTHOR_AGENT)

#: שם הלקוח (מה שהלקוח מצהיר בחיבור — ``$mcp_client_name`` בלוח האנליטיקס) ← השם שמוצג.
#: הטבלה "מי כתב" שבאפיון. לקוח שאינו כאן מוצג בשמו כמו שהוא.
AGENT_CLIENT_LABELS: dict[str, str] = {
    "claude-code": "CC",
    "Anthropic/ClaudeAI": "Claude",
    "Gemini": "Gemini",
}

#: מה שמוצג לסוכן שהלקוח שלו לא נודע (החיבור לא נשא שם).
UNKNOWN_AGENT_LABEL = "סוכן"

#: ``kind`` של אירוע התראה על תגובת סוכן באוסף ``push_events``.
NOTE_COMMENT_PUSH_KIND = "note_comment"

NOTE_THREADS_BY_NOTE_INDEX = "note_threads_user_note_idx"
NOTE_THREADS_PENDING_INDEX = "note_threads_user_status_last_author_idx"

#: כמה פעמים פעולת CAS נשלחת שוב כשהקריאה החוזרת מראה שהמצב זז בין השתיים (סטטוס
#: שהתהפך באמצע). אחרי זה — ``conflict``.
_CAS_ATTEMPTS = 3

_HEX_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")

#: המפתחות של ``author`` (וגם של ``resolved_by``), בסדר שבו הם נשמרים.
_AUTHOR_FIELDS = ("kind", "client", "working_on")

#: שדות היעד של פתק שאירוע ההתראה נושא — ``note_target_ref`` של ``sticky_notes_target``.
_PUSH_TARGET_FIELDS = ("target", "file_name", "file_id", "board_id", "repo_name", "repo_path")

#: השדות של **תקציר** שרשור — מה שהבועות שמעל הפתק צריכות: המספר שבבועה (``comment_count``),
#: הסטטוס, "מחכה לך" (``last_author_kind``), והסדר (``created_at``). בלי התגובות, ובלי
#: ``body_bytes`` / ``resolved_by`` שרק חלונית פתוחה צריכה. היטלת **הכללה** ולא החרגה: שדה
#: שיתווסף למסמך בעתיד לא ייגרר מעצמו לכל טעינת לוח (``work-disproportionate-to-answer`` §5).
THREAD_SUMMARY_FIELDS = ("note_id", "status", "comment_count", "last_author_kind", "created_at")


# -- גדלים, מזהים וקלט ------------------------------------------------------


def _utf8_encodable(text: str) -> bool:
    """האם המחרוזת ניתנת לקידוד UTF-8 — ``False`` על surrogate בודד, ש-BSON ו-JSON לא יישאו."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def body_wire_bytes(body: str) -> int:
    """כמה בתים הגוף תופס בתשובת JSON — כולל המירכאות וה-escape-ים.

    ``json.dumps(..., ensure_ascii=False)`` בקידוד UTF-8 כותב מחרוזת בדיוק כמו
    ``pydantic_core.to_json`` שבו שרת ה-MCP מודד תשובה (``mcp_server.answer_size.wire_json``):
    אותם escape-ים לתווי בקרה, ל-``"`` ול-``\\``, ותווים שאינם ASCII כמו שהם. השוויון נמדד
    על כל נקודות הקוד שאינן surrogate, ומעוגן ב-``tests/test_note_threads.py``. המודול אינו
    מייבא את ``answer_size`` עצמו כי הוא חלק מ-``mcp_server``, והוובאפ אינו מייבא את החבילה הזו.
    """
    return len(json.dumps(body, ensure_ascii=False).encode("utf-8"))


def _hex_id(value: Any) -> str | None:
    """מזהה בצורת ``str(ObjectId)`` — 24 תווי hex באותיות קטנות — או ``None``."""
    text = value.strip() if isinstance(value, str) else ""
    if not _HEX_ID_RE.match(text):
        return None
    return text.lower()


def parse_thread_id(value: Any) -> str | None:
    """מזהה שרשור בצורתו הקנונית (24 תווי hex באותיות קטנות) — או ``None``.

    הערך מגיע מהלקוח, ולכן נבדק לפני כל המרה (``external-input-isinstance``). קטנות
    ולא גדולות: ``str(ObjectId)`` היא תמיד קטנה, וזו הצורה שכל קורא אחר יחפש.
    """
    return _hex_id(value)


def is_canonical_note_id(value: Any) -> bool:
    """האם ``value`` הוא ``note_id`` בצורה שבה הוא נשמר כאן: 24 תווי hex באותיות קטנות."""
    return isinstance(value, str) and bool(_HEX_ID_RE.match(value)) and value == value.lower()


def _canonical_note_id(note_id: Any) -> str:
    """``note_id`` כפי שהוא נשמר — ``ValueError`` על כל צורה אחרת.

    המזהה נשמר כמחרוזת hex קטנה, כמו ``sticky_note_versions.note_id`` ואירועי ההתראה.
    מזהה באותיות גדולות היה כותב שרשור שאף קריאה לא תמצא — ולכן כאן זו שגיאת תכנות
    שעולה, ולא תיקון שקט: הקוראים מעבירים את מה ש-``_clean_note_id`` החזיר.
    """
    if not is_canonical_note_id(note_id):
        raise ValueError("note_id must be the canonical lowercase 24-hex id")
    return note_id


def comment_body_error(body: Any) -> dict[str, Any] | None:
    """הסירוב לגוף תגובה — או ``None``, ואז הגוף נשמר **בדיוק כפי שנשלח**.

    אותו כלל של גוף פתק (``mcp_server/handlers._note_content_error``): בלי ניקוי; ריקנות
    נשפטת על עותק בלי רווחים בקצוות, והמקור הוא מה שנשמר; האורך נמדד על מה שנשמר.
    **סירוב ולא חיתוך** (``silent-truncation-at-sink``): סוכן אינו רואה את מה שנשמר, וחיתוך
    שקט הוא אובדן שהוא לעולם לא ילמד עליו.

    ``invalid_body`` גם למחרוזת שאי אפשר לקודד ב-UTF-8 (surrogate בודד): BSON לא יקבל אותה,
    ותשובת JSON לא תוכל לשאת אותה.
    """
    if not isinstance(body, str):
        return {"ok": False, "error": "invalid_body"}
    if not body.strip():
        return {"ok": False, "error": "empty_body"}
    if len(body) > MAX_COMMENT_CHARS:
        return {"ok": False, "error": "body_too_long", "max": MAX_COMMENT_CHARS}
    if not _utf8_encodable(body):
        return {"ok": False, "error": "invalid_body"}
    return None


def working_on_or_error(value: Any) -> str | dict[str, Any]:
    """``working_on`` מנורמל לשורה אחת — או **מילון שגיאה** (הקורא מזהה ב-``isinstance``).

    "על מה הסוכן עבד" מגיע מהסוכן, ולכן נבדק כאן: חובה, ועד :data:`MAX_WORKING_ON_CHARS`
    תווים. הנרמול הוא של שם פתק (``canonical_title_text``): רווחים בקצוות יורדים ושורות
    מתכווצות לשורה אחת, כי זו תווית שיושבת בשורה אחת ליד שם הסוכן. האורך נמדד **אחרי**
    הנרמול, כי זה מה שנשמר ומוצג; ומעבר לתקרה — סירוב, לא חיתוך.
    """
    if value is None:
        return {"ok": False, "error": "working_on_required", "max": MAX_WORKING_ON_CHARS}
    if not isinstance(value, str) or not _utf8_encodable(value):
        return {"ok": False, "error": "invalid_working_on"}
    text = canonical_title_text(value)
    if not text:
        return {"ok": False, "error": "working_on_required", "max": MAX_WORKING_ON_CHARS}
    if len(text) > MAX_WORKING_ON_CHARS:
        return {"ok": False, "error": "working_on_too_long", "max": MAX_WORKING_ON_CHARS}
    return text


def normalize_client_name(value: Any) -> str | None:
    """שם הלקוח לשמירה ליד תגובת סוכן — שורה אחת, עד :data:`MAX_CLIENT_NAME_CHARS` תווים.

    ``None`` כשאין שם שמיש (לא מחרוזת, ריק, או לא ניתן לקידוד) — ואז התגובה מוצגת
    כ-:data:`UNKNOWN_AGENT_LABEL`. הקיצוץ הוא של תווית ולא של תוכן.
    """
    if not isinstance(value, str) or not _utf8_encodable(value):
        return None
    text = canonical_title_text(value)
    return text[:MAX_CLIENT_NAME_CHARS] or None


# -- מי כתב ------------------------------------------------------------------


def agent_author(*, client: Any, working_on: str) -> dict[str, Any]:
    """הכותב של תגובת סוכן. ``client`` הוא שם הלקוח **מהחיבור** — לעולם לא מפרמטר של הכלי.

    ``working_on`` הוא הערך ש-:func:`working_on_or_error` החזיר.
    """
    return {"kind": AUTHOR_AGENT, "client": normalize_client_name(client), "working_on": working_on}


def user_author() -> dict[str, Any]:
    """הכותב של תגובה מהוובאפ — המשתמש עצמו."""
    return {"kind": AUTHOR_USER, "client": None, "working_on": None}


def _checked_author(author: Any) -> dict[str, Any]:
    """הכותב כפי שיישמר — ``ValueError`` על צורה שאינה של :func:`agent_author` / :func:`user_author`.

    הכותב נבנה תמיד בקוד שלנו, ולכן צורה שגויה היא באג אצל הקורא ועולה, ולא קלט לסרב לו.
    """
    if not isinstance(author, Mapping) or author.get("kind") not in _AUTHOR_KINDS:
        raise ValueError("author must come from agent_author() or user_author()")
    clean = {key: author.get(key) for key in _AUTHOR_FIELDS}
    if clean["kind"] == AUTHOR_USER:
        if clean["client"] is not None or clean["working_on"] is not None:
            raise ValueError("a user author carries no client and no working_on")
        return clean
    working_on = clean["working_on"]
    if not isinstance(working_on, str) or working_on != working_on_or_error(working_on):
        raise ValueError("an agent author needs working_on from working_on_or_error()")
    if clean["client"] is not None and clean["client"] != normalize_client_name(clean["client"]):
        raise ValueError("an agent author's client must come from normalize_client_name()")
    return clean


def author_label(author: Any, *, user_name: str) -> str:
    """השם שמוצג ליד תגובה — הטבלה "מי כתב" שבאפיון, במקום אחד.

    משתמש ← ``user_name`` (מה שהוובאפ יודע עליו). סוכן ← השם המקוצר ללקוח מוכר
    (:data:`AGENT_CLIENT_LABELS`), שם הלקוח כמו שהוא לכל לקוח אחר, ו-
    :data:`UNKNOWN_AGENT_LABEL` כשהלקוח לא נודע. ``working_on`` אינו חלק מהשם: הוא מוצג לידו.
    """
    author = author if isinstance(author, Mapping) else {}
    if author.get("kind") == AUTHOR_USER:
        return user_name
    client = author.get("client")
    if not isinstance(client, str) or not client:
        return UNKNOWN_AGENT_LABEL
    return AGENT_CLIENT_LABELS.get(client, client)


# -- המסמך ---------------------------------------------------------------------


def thread_scope(user_id: int, note_id: str) -> dict[str, Any]:
    """המסנן של כל השרשורים של פתק אחד של משתמש אחד — הבסיס של כל פעולה על פתק אחד כאן.

    שתי הקריאות שעוברות על כמה פתקים, :func:`open_thread_counts` ו-:func:`pending_for_agent`,
    אינן בנויות עליו: הן תחומות למשתמש, ולא לפתק אחד (ראו בראש המודול).
    """
    return {"user_id": int(user_id), "note_id": _canonical_note_id(note_id)}


def _now(now: datetime | None) -> datetime:
    """הרגע של הכתיבה, ב-UTC עם אזור זמן (R7). ``now`` שהועבר חייב לשאת אזור זמן."""
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(timezone.utc)


def _new_comment(author: dict[str, Any], body: str, now: datetime) -> dict[str, Any]:
    from bson import ObjectId  # נטען כאן: המודול טהור בזמן הייבוא

    return {"id": str(ObjectId()), "author": dict(author), "body": body, "created_at": now}


def _thread_oid(thread_id: Any) -> Any:
    """``ObjectId`` של שרשור מהקלט — או ``None`` כשאינו בצורת מזהה."""
    canonical = parse_thread_id(thread_id)
    if canonical is None:
        return None
    from bson import ObjectId

    return ObjectId(canonical)


def _primary(coll: Any) -> Any:
    """``coll`` לקריאה מה-primary — לקריאה החוזרת אחרי ``insert_one``.

    ``ReadPreference.PRIMARY`` דרך ``Collection.with_options`` (pymongo 4.15.3) — אותה קריאה
    של ``ProductionBackend._primary_reader`` ב-``mcp_server/backend.py``, שאינו נגיש מכאן
    (הוובאפ אינו מייבא את ``mcp_server``). נקשר **לפני** ה-insert, מאותו נימוק שכתוב שם:
    אוסף בלי ``with_options`` נופל לפני שנכתב דבר, ולא אחרי.
    """
    from pymongo import ReadPreference

    return coll.with_options(read_preference=ReadPreference.PRIMARY)


# -- כתיבה ---------------------------------------------------------------------


def create_thread(
    coll: Any, *, user_id: int, note_id: str, author: Any, body: Any, now: datetime | None = None
) -> dict[str, Any]:
    """שרשור חדש על פתק, עם התגובה הראשונה שלו — פתוח, והכותב שלו הוא האחרון.

    **התשובה נבנית מקריאה חוזרת** לפי ה-``_id`` שה-insert החזיר, מה-primary: ``insert_one``
    מחזיר מזהה ולא מסמך, והכלל הוא לקרוא את המצב ולא להדהד את הבקשה. כשהקריאה החוזרת
    נכשלת בשגיאת מסד, או לא מוצאת את השרשור, הכתיבה עדיין קרתה — ולכן ``ok: true`` עם
    ``thread: None``, ושורת ``WARNING``. כך עושה גם ``_created_note_answer`` בפתקים: סוכן
    שהיה מקבל ``ok: false`` היה פותח שרשור שני.

    :returns: ``{"ok": True, "action": "created", "thread": <מסמך או None>, "thread_id",
        "comment_id"}``, או מילון שגיאה של :func:`comment_body_error`.
    """
    from pymongo.errors import PyMongoError

    refused = comment_body_error(body)
    if refused:
        return refused
    scope = thread_scope(user_id, note_id)
    author = _checked_author(author)
    when = _now(now)
    comment = _new_comment(author, body, when)
    doc = {
        **scope,
        "status": STATUS_OPEN,
        "resolved_by": None,
        "resolved_at": None,
        "last_author_kind": author["kind"],
        "last_at": when,
        "comment_count": 1,
        "body_bytes": body_wire_bytes(body),
        "comments": [comment],
        "created_at": when,
    }
    read_back = _primary(coll)
    inserted_id = coll.insert_one(doc).inserted_id
    try:
        stored = read_back.find_one({**scope, "_id": inserted_id})
    except PyMongoError:
        # "לא הצלחתי לקרוא" — בדיוק מה ש-``thread: None`` מתאר. המזהים בלבד, בלי גוף (K13).
        logger.warning("note_threads: could not read back the created thread (_id=%s)",
                       inserted_id, exc_info=True)
        stored = None
    else:
        if stored is None:
            logger.warning("note_threads: the created thread was not found on read-back (_id=%s)",
                           inserted_id)
    return {
        "ok": True,
        "action": "created",
        "thread": stored,
        "thread_id": str(inserted_id),
        "comment_id": comment["id"],
    }


def add_comment(
    coll: Any,
    *,
    user_id: int,
    note_id: str,
    thread_id: Any,
    author: Any,
    body: Any,
    reopen: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """תשובה בשרשור קיים — פעולה אטומית אחת.

    ``reopen=True`` (ברירת המחדל, לפי ההחלטה שבפתק על האפיון) פותח שרשור שנפתר: הסטטוס
    חוזר ל-``open`` ו-``resolved_by`` / ``resolved_at`` מתאפסים — באותו עדכון שדוחף את
    התגובה. על שרשור פתוח אלה אותם ערכים, ולכן הפילטר אינו תלוי בסטטוס ואין כאן מרוץ על
    הסטטוס. ``reopen=False`` עונה בלי לגעת בסטטוס, ו-``last_author_kind`` / ``last_at``
    מתעדכנים בכל מקרה: הם מתארים את התגובה האחרונה, לא את הסטטוס.

    הפילטר נושא את שתי התקרות (:data:`MAX_COMMENTS_PER_THREAD`, :data:`MAX_THREAD_BODY_BYTES`),
    ולכן שתי תשובות מקבילות אינן יכולות לעבור אותן יחד.
    """
    refused = comment_body_error(body)
    if refused:
        return refused
    oid = _thread_oid(thread_id)
    if oid is None:
        return {"ok": False, "error": "invalid_thread_id"}
    scope = thread_scope(user_id, note_id)
    author = _checked_author(author)
    when = _now(now)
    comment = _new_comment(author, body, when)
    cost = body_wire_bytes(body)
    fields: dict[str, Any] = {"last_author_kind": author["kind"], "last_at": when}
    if reopen is not False:
        fields.update(status=STATUS_OPEN, resolved_by=None, resolved_at=None)
    update = {
        "$push": {"comments": comment},
        "$inc": {"comment_count": 1, "body_bytes": cost},
        "$set": fields,
    }
    return _apply(coll, scope, oid, update, require_status=None, adds_bytes=cost,
                  comment_id=comment["id"], action="replied")


def resolve_thread(
    coll: Any,
    *,
    user_id: int,
    note_id: str,
    thread_id: Any,
    author: Any,
    body: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """סגירת שרשור פתוח. ``body`` אופציונלי — משפט סיכום, שנשמר כתגובה אחרונה **באותה פעולה**.

    נשמר מי סגר (``resolved_by``: ``kind``, ``client``, ``working_on`` — אותם שדות של כותב)
    ומתי. שרשור שכבר נפתר עונה ``already_resolved`` ושום דבר לא נכתב, גם לא הסיכום.
    בלי ``body`` אין תגובה חדשה, ולכן ``last_author_kind`` / ``last_at`` אינם זזים.
    """
    oid = _thread_oid(thread_id)
    if oid is None:
        return {"ok": False, "error": "invalid_thread_id"}
    if body is not None:
        refused = comment_body_error(body)
        if refused:
            return refused
    scope = thread_scope(user_id, note_id)
    author = _checked_author(author)
    when = _now(now)
    fields: dict[str, Any] = {
        "status": STATUS_RESOLVED,
        "resolved_by": {key: author[key] for key in _AUTHOR_FIELDS},
        "resolved_at": when,
    }
    update: dict[str, Any] = {"$set": fields}
    comment_id: str | None = None
    cost: int | None = None
    if body is not None:
        comment = _new_comment(author, body, when)
        cost = body_wire_bytes(body)
        comment_id = comment["id"]
        fields.update(last_author_kind=author["kind"], last_at=when)
        update["$push"] = {"comments": comment}
        update["$inc"] = {"comment_count": 1, "body_bytes": cost}
    return _apply(coll, scope, oid, update, require_status=STATUS_OPEN, adds_bytes=cost,
                  comment_id=comment_id, action="resolved")


def reopen_thread(coll: Any, *, user_id: int, note_id: str, thread_id: Any) -> dict[str, Any]:
    """פתיחה מחדש של שרשור שנפתר, בלי תגובה — כפתור "פתיחה מחדש" שבעיצוב.

    ``last_author_kind`` אינו זז: הוא מתאר את התגובה האחרונה, ופתיחה אינה תגובה. שרשור
    פתוח עונה ``not_resolved``.
    """
    oid = _thread_oid(thread_id)
    if oid is None:
        return {"ok": False, "error": "invalid_thread_id"}
    scope = thread_scope(user_id, note_id)
    update = {"$set": {"status": STATUS_OPEN, "resolved_by": None, "resolved_at": None}}
    return _apply(coll, scope, oid, update, require_status=STATUS_RESOLVED, adds_bytes=None,
                  comment_id=None, action="reopened")


def _apply(
    coll: Any,
    scope: dict[str, Any],
    oid: Any,
    update: dict[str, Any],
    *,
    require_status: str | None,
    adds_bytes: int | None,
    comment_id: str | None,
    action: str,
) -> dict[str, Any]:
    """עדכון CAS אחד על שרשור, ומה שהמסד השאיר אחריו.

    הפילטר הוא התחום (משתמש, פתק, שרשור), ועוד מה שהפעולה דורשת: הסטטוס, והמקום לתגובה
    כשהיא מוסיפה אחת. ``ReturnDocument.AFTER`` מחזיר את המצב שהכתיבה **הזו** השאירה, וההיטלה
    מחזירה רק את התגובה האחרונה — זו שנדחפה כאן: ``$push`` מוסיף בסוף, והפעולה אטומית.

    ``None`` מהמסד הוא כשל ולא "בסדר" (K11): קוראים את השרשור שוב ומסווגים. כשהסיווג אינו
    מוצא סיבה — המצב זז בין שתי הקריאות — שולחים שוב, עד :data:`_CAS_ATTEMPTS`, ואז ``conflict``.
    """
    from pymongo import ReturnDocument

    base = {**scope, "_id": oid}
    cas = dict(base)
    if require_status is not None:
        cas["status"] = require_status
    if adds_bytes is not None:
        cas["comment_count"] = {"$lt": MAX_COMMENTS_PER_THREAD}
        cas["body_bytes"] = {"$lte": MAX_THREAD_BODY_BYTES - adds_bytes}
    projection = {"comments": {"$slice": -1}} if comment_id is not None else {"comments": 0}
    for _attempt in range(_CAS_ATTEMPTS):
        stored = coll.find_one_and_update(
            cas, update, projection=projection, return_document=ReturnDocument.AFTER
        )
        if stored is not None:
            return {"ok": True, "action": action, "thread": stored, "thread_id": str(oid),
                    "comment_id": comment_id}
        current = coll.find_one(base, {"status": 1, "comment_count": 1, "body_bytes": 1})
        refused = _why_not(current, require_status, adds_bytes)
        if refused is not None:
            return refused
    logger.warning("note_threads: %s kept missing its CAS after %d attempts (_id=%s)",
                   action, _CAS_ATTEMPTS, oid)
    return {"ok": False, "error": "conflict"}


def _why_not(current: Any, require_status: str | None, adds_bytes: int | None) -> dict[str, Any] | None:
    """למה עדכון ה-CAS לא תפס — או ``None`` כשהמצב שנקרא היה מאפשר אותו (הוא זז בינתיים)."""
    if not isinstance(current, Mapping):
        return {"ok": False, "error": "thread_not_found"}
    status = current.get("status")
    if require_status == STATUS_OPEN and status == STATUS_RESOLVED:
        return {"ok": False, "error": "already_resolved"}
    if require_status == STATUS_RESOLVED and status == STATUS_OPEN:
        return {"ok": False, "error": "not_resolved"}
    if adds_bytes is not None:
        count = current.get("comment_count")
        used = current.get("body_bytes")
        if isinstance(count, int) and count >= MAX_COMMENTS_PER_THREAD:
            return {"ok": False, "error": "thread_full", "max": MAX_COMMENTS_PER_THREAD}
        if isinstance(used, int) and used + adds_bytes > MAX_THREAD_BODY_BYTES:
            return {"ok": False, "error": "thread_too_long", "max_bytes": MAX_THREAD_BODY_BYTES}
    return None


def stored_comment(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """התגובה שהפעולה כתבה, **כפי שהמסד החזיר אותה** — או ``None`` כשאינה בתשובה.

    ``result`` הוא מה ש-:func:`create_thread` / :func:`add_comment` / :func:`resolve_thread`
    החזירו. ``None`` כשלא נכתבה תגובה, כשהקריאה החוזרת נכשלה, או כשהתגובה עם המזהה הזה
    אינה בזנב שחזר — את המקרה האחרון אטומיות של פעולה אחת שוללת, ולכן הוא נרשם ברמת
    ERROR: הקורא מדווח "לא ידוע" ולא תגובה של מישהו אחר כאילו היא שלו.
    """
    comment_id = result.get("comment_id")
    thread = result.get("thread")
    if not comment_id or not isinstance(thread, Mapping):
        return None
    for comment in reversed(thread.get("comments") or []):
        if isinstance(comment, Mapping) and comment.get("id") == comment_id:
            return dict(comment)
    logger.error("note_threads: comment %s is not in the stored thread %s", comment_id,
                 result.get("thread_id"))
    return None


def delete_note_threads(coll: Any, *, user_id: int, note_id: str) -> int:
    """מוחק את כל השרשורים של פתק, ומחזיר כמה נמחקו.

    הקורא היחיד הוא ראוט המחיקה בוובאפ, **אחרי** שמחיקת הפתק עצמו הצליחה — ראו בראש המודול.
    כשל של המסד עולה לקורא.
    """
    return int(coll.delete_many(thread_scope(user_id, note_id)).deleted_count)


# -- קריאה ---------------------------------------------------------------------


def _numbered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """מוסיף לכל שורה ``number`` — "שרשור N" שבעיצוב: המקום ברשימה ועוד אחד.

    השורות מגיעות ממוינות ``(created_at, _id)`` מהמסד; ``_id`` שובר שוויון באותה אלפית שנייה,
    כך שהסדר קבוע בין קריאות (``unsorted-representative``). המספר אינו נשמר — הוא נגזר בכל
    קריאה מאותו סדר, ולכן יש לו מקום אחד: כאן, לשני הקוראים (:func:`list_threads` ו-
    :func:`list_threads_for_notes`).
    """
    for number, row in enumerate(rows, start=1):
        row["number"] = number
    return rows


def list_threads(coll: Any, *, user_id: int, note_id: str) -> list[dict[str, Any]]:
    """כל השרשורים של פתק, **בלי התגובות**, ממוספרים לפי סדר היצירה (:func:`_numbered`)."""
    return _numbered(list(
        coll.find(thread_scope(user_id, note_id), {"comments": 0}).sort([("created_at", 1), ("_id", 1)])
    ))


def list_threads_for_notes(
    coll: Any, *, user_id: int, note_ids: Iterable[str]
) -> dict[str, list[dict[str, Any]]]:
    """תקצירי השרשורים של כמה פתקים, ממוספרים — **שאילתה אחת** לכל הרשימה, לא קריאה לכל פתק.

    בשביל רשימת הפתקים בוובאפ (לוח, קובץ, ריפו): כל פתק מגיע עם הבועות שלו. המספור זהה לזה
    של :func:`list_threads` — אותו מיון ``(created_at, _id)`` בתוך כל פתק, ואותו :func:`_numbered`.
    כל שורה נושאת רק את :data:`THREAD_SUMMARY_FIELDS` ואת ``_id``.

    תחומה למשתמש ולפתקים שהקורא העביר (``note_id`` מתוך רשימה שהוא קרא בשאילתה שתחומה
    למשתמש). פתק בלי שרשורים אינו במילון. כשל של המסד עולה לקורא, שמחליט מה "לא ידוע" אצלו.
    """
    ids = sorted({_canonical_note_id(nid) for nid in note_ids})
    if not ids:
        return {}
    rows = coll.find(
        {"user_id": int(user_id), "note_id": {"$in": ids}},
        {field: 1 for field in THREAD_SUMMARY_FIELDS},
    ).sort([("note_id", 1), ("created_at", 1), ("_id", 1)])
    by_note: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_note.setdefault(row["note_id"], []).append(row)
    for group in by_note.values():
        _numbered(group)
    return by_note


def awaits_user(row: Mapping[str, Any]) -> bool:
    """"מחכה לך" — הנקודה האדומה בעיצוב: שרשור פתוח שהתגובה האחרונה בו של סוכן.

    הצד השני של :func:`pending_for_agent`, שם — פתוח והאחרונה של המשתמש.
    """
    return row.get("status") == STATUS_OPEN and row.get("last_author_kind") == AUTHOR_AGENT


def comments_by_ref(
    coll: Any, *, user_id: int, refs: Iterable[tuple[Any, Any]]
) -> dict[tuple[str, str], dict[str, Any]]:
    """התגובות שמבוקשות לפי ``(thread_id, comment_id)`` — **שאילתה אחת** לכל הרשימה.

    בשביל שולח הפוש: אירוע ``note_comment`` נושא מזהים בלבד, והגוף נקרא טרי בזמן השליחה.
    הסינון של התגובות קורה **במסד** — ``$filter`` ב-``$project`` שצמוד ל-``$match`` — ולכן רק
    התגובות שנשאלו יוצאות ממנו, ולא השרשור כולו (עד :data:`MAX_THREAD_BODY_BYTES`). כל תגובה
    חוזרת עם ``note_id`` של השרשור שלה, כדי שהקורא יוודא שהיא שייכת לפתק שהאירוע מתאר.

    תחומה למשתמש. זוג עם מזהה פגום מדולג, וזוג שלא נמצא (שרשור שנמחק, משתמש אחר) אינו
    במילון. כשל של המסד עולה לקורא.

    **מזהה תגובה נבדק לצורתו לפני שהוא נכנס לביטוי**, כמו מזהה שרשור: הוא יושב במערך ליטרלי
    בתוך ``$in`` של אגרגציה, ושם מחרוזת שמתחילה ב-``$`` היא נתיב שדה ולא ערך. מזהה תגובה הוא
    ``str(ObjectId())`` (:func:`_new_comment`), ולכן הצורה ידועה.
    """
    wanted: set[tuple[str, str]] = set()
    oids: dict[str, Any] = {}
    for thread_id, comment_id in refs:
        oid = _thread_oid(thread_id)
        clean_comment_id = _hex_id(comment_id)
        if oid is None or clean_comment_id is None:
            continue
        oids[str(oid)] = oid
        wanted.add((str(oid), clean_comment_id))
    if not wanted:
        return {}
    comment_ids = sorted({comment_id for _tid, comment_id in wanted})
    rows = coll.aggregate([
        {"$match": {"user_id": int(user_id), "_id": {"$in": list(oids.values())}}},
        {"$project": {
            "note_id": 1,
            "comments": {"$filter": {
                "input": "$comments", "as": "c", "cond": {"$in": ["$$c.id", comment_ids]},
            }},
        }},
    ])
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        thread_id = str(row["_id"])
        for comment in row.get("comments") or []:
            comment_id = comment.get("id") if isinstance(comment, Mapping) else None
            if not isinstance(comment_id, str):
                continue
            key = (thread_id, comment_id)
            if key in wanted:
                found[key] = {**comment, "note_id": row.get("note_id")}
    return found


def load_comments(
    coll: Any, *, user_id: int, note_id: str, thread_ids: Iterable[Any], tail: int | None = None
) -> dict[str, list[dict[str, Any]]]:
    """התגובות של השרשורים המבוקשים, לפי מזהה — כולן (``tail=None``), או ``tail`` האחרונות.

    ``tail`` נחתך **במסד** (``$slice``) ולא בפייתון: השרשורים שלא מוצגים במלואם אינם יוצאים
    מהמסד במלואם. ההיטלה כוללת שדה אחד נוסף, ולכן היא היטלת הכללה ואין שדות אחרים שנגררים
    (נמדד מול mongod 8.0: ``$slice`` לבדו מחזיר את כל שאר השדות).
    """
    if tail is not None and (isinstance(tail, bool) or not isinstance(tail, int) or tail < 1):
        raise ValueError("tail must be a positive int or None")
    oids = [oid for oid in (_thread_oid(tid) for tid in thread_ids) if oid is not None]
    if not oids:
        return {}
    comments: Any = {"$slice": -tail} if tail is not None else 1
    rows = coll.find({**thread_scope(user_id, note_id), "_id": {"$in": oids}},
                     {"comments": comments, "comment_count": 1})
    return {str(row["_id"]): list(row.get("comments") or []) for row in rows}


def display_order(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """הסדר שבו שרשורים מוצגים: הפתוחים קודם, ובכל קבוצה — הפעילות האחרונה קודם.

    "הפתוחים למעלה, אלה שנפתרו מקופלים למטה" (האפיון). שוויון ב-``last_at`` נשבר לפי
    ``number`` יורד, כך שהסדר קבוע.
    """
    def key(row: Mapping[str, Any]) -> tuple:
        last_at = row.get("last_at")
        # שרשור בלי ``last_at`` שמיש (לא נכתב כאן) יורד לסוף הקבוצה שלו.
        when = as_utc(last_at).timestamp() if isinstance(last_at, datetime) else float("-inf")
        number = row.get("number")
        return (row.get("status") != STATUS_OPEN, -when, -(number if isinstance(number, int) else 0))

    return sorted(rows, key=key)


def open_thread_counts(coll: Any, *, user_id: int, note_ids: Iterable[str]) -> dict[str, int]:
    """כמה שרשורים פתוחים יש על כל פתק — **שאילתה אחת** לכל הרשימה, לא קריאה לכל פתק.

    פתק בלי שרשור פתוח אינו במילון (הקורא מפרש היעדר כאפס). כשל של המסד עולה לקורא, שמחליט
    מה "לא ידוע" אצלו.
    """
    ids = sorted({_canonical_note_id(nid) for nid in note_ids})
    if not ids:
        return {}
    rows = coll.aggregate([
        {"$match": {"user_id": int(user_id), "status": STATUS_OPEN, "note_id": {"$in": ids}}},
        {"$group": {"_id": "$note_id", "n": {"$sum": 1}}},
    ])
    return {str(row["_id"]): int(row.get("n") or 0) for row in rows}


def pending_for_agent(coll: Any, *, user_id: int) -> list[dict[str, Any]]:
    """השרשורים שממתינים לסוכן: פתוחים, והתגובה האחרונה בהם של המשתמש — החדש ביותר קודם.

    זה מכסה גם תשובה של המשתמש לסוכן וגם שרשור חדש שהמשתמש פתח. שרשור שסוכן ענה בו
    אחרון אינו כאן, אחרת שורת הפריימר הייתה ממשיכה להציק אחרי שטיפלו בו. השאילתה נשענת
    על :data:`NOTE_THREADS_PENDING_INDEX`, וההיטלה מחזירה רק את הפתק והזמן.
    """
    rows = coll.find(
        {"user_id": int(user_id), "status": STATUS_OPEN, "last_author_kind": AUTHOR_USER},
        {"note_id": 1, "last_at": 1},
    ).sort([("last_at", -1), ("_id", -1)])
    return [{"note_id": row.get("note_id"), "last_at": row.get("last_at")} for row in rows]


# -- התראה ---------------------------------------------------------------------


def note_comment_push_event(
    *,
    user_id: int,
    note_id: str,
    thread_id: str,
    comment_id: str,
    author: Mapping[str, Any],
    target_ref: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """בקשת התראה על תגובת סוכן, לאוסף ``push_events`` — **רק אחרי כתיבה שהצליחה**.

    השליחה נעשית בוובאפ (שולח יחיד תחת ``flock``, עם מפתחות ה-VAPID); כאן נבנית הבקשה בלבד.
    האירוע נושא מזהים: הפתק, השרשור, התגובה, היעד של הפתק (``note_target_ref``) והכותב.
    כותרת הפתק ושם הלוח נקראים טריים בזמן השליחה, ולא מועתקים לכאן.

    תגובה של המשתמש אינה שולחת לו התראה — הקורא שולח אירוע רק על תגובת סוכן, וזה נאכף כאן.
    """
    clean_author = {key: author.get(key) for key in _AUTHOR_FIELDS}
    if clean_author["kind"] != AUTHOR_AGENT:
        raise ValueError("only an agent's comment notifies the user")
    event: dict[str, Any] = {
        "user_id": int(user_id),
        "kind": NOTE_COMMENT_PUSH_KIND,
        "note_id": _canonical_note_id(note_id),
        "thread_id": str(thread_id),
        "comment_id": str(comment_id),
    }
    for key in _PUSH_TARGET_FIELDS:
        value = target_ref.get(key)
        if isinstance(value, str) and value:
            event[key] = value
    event.update(author=clean_author, created_at=_now(now), needs_push=True)
    return event


# -- אינדקסים -------------------------------------------------------------------


def note_threads_indexes() -> list[dict[str, Any]]:
    """הגדרות האינדקסים, בצורה ש-``safe_create_index`` מקבלת.

    ``DatabaseManager._create_indexes`` מצהיר עליהם בכל עלייה, בשני השירותים — שניהם כותבים
    לאוסף. אינדקסי ביצועים בלבד: בלי ``unique``, בלי TTL ובלי פילטר חלקי, ולכן כשל ביצירה
    הוא איטיות ולא שינוי התנהגות.
    """
    return [
        {
            # קריאת השרשורים של פתק (get_note), הספירה לרשימה הרזה, והמחיקה עם הפתק.
            "keys": [("user_id", 1), ("note_id", 1)],
            "name": NOTE_THREADS_BY_NOTE_INDEX,
        },
        {
            # שורת הפריימר: פתוחים שהתגובה האחרונה בהם של המשתמש.
            "keys": [("user_id", 1), ("status", 1), ("last_author_kind", 1)],
            "name": NOTE_THREADS_PENDING_INDEX,
        },
    ]
