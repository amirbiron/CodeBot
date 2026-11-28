"""חילוץ בחיפוש בתיעוד: מודל שפה קורא את הסעיפים שהחיפוש מצא, ומחזיר את הקטע שעונה על השאלה.

הקורא הוא ``POST /api/search/docs/extract`` ב-``webapp/app.py`` (לאדמין), כשלוחצים "חלץ" מעל התוצאות של
החיפוש בתיעוד. החיפוש עצמו (``services/docs_search_service.py``) לא משתנה: הוא מחזיר את הסעיפים הקרובים
לפי וקטורים, וכאן מודל שפה בוחר מתוכם את החלק המתאים לפי התוכן וההקשר. אין קריאה למודל בלי לחיצה.

**הסעיפים נקראים מהמסד לפי המזהים שלהם**, ולא נשלחים מהדפדפן: הדפדפן שולח רק את השאלה ואת המזהים של
הסעיפים שמוצגים. הסעיף, הכותרת והקישור לאתר נבנים ב-``section_result`` של החיפוש, ולכן הם זהים לכרטיס.

**ההגדרות משלו** — ``DOCS_EXTRACT_API_KEY``, ``DOCS_EXTRACT_BASE_URL``, ``DOCS_EXTRACT_MODEL`` — באותם כללים
כמו של היועץ (``services/llm_endpoint_settings.py``), אבל נפרדות ממנו: החלפת מודל ביועץ לא משנה את החילוץ,
והצריכה של כל אחד נספרת לחוד. הלקוח סינכרוני (``openai.OpenAI``), כי הוובאפ רץ ב-Flask עם worker של gevent
ואין בו לולאת asyncio (``docs/observability/asyncio-loop-safety.rst``). לקוח חדש נבנה לכל לחיצה.

**תקרת הזמן היא** ``gevent.Timeout`` **על הקריאה כולה** (:data:`EXTRACT_DEADLINE_SECONDS`). התקרה של ה-SDK
חלה על כל פעולה מול הרשת בנפרד (httpcore2 קובע ``settimeout`` לכל ``recv``), ולכן תשובה שמגיעה טיפה אחרי
טיפה עוברת אותה בלי סוף, וה-worker של gevent אינו מגביל את אורך הבקשה (``wait-without-own-deadline``).
``gevent.Timeout`` נקטע גם באמצע קריאה מהרשת — אבל רק בתהליך שעבר ``monkey.patch_all()``, כמו ה-worker של
gunicorn (``gunicorn/workers/ggevent.py``, ``GeventWorker.patch``); בתהליך אחר הוא חסר אונים (gevent 24.11.1,
``gevent/timeout.py``). לכן בתהליך כזה החילוץ מסרב (``extract_needs_gevent``) במקום לרוץ בלי תקרה.
``tests/test_docs_extract_deadline_under_gevent.py`` מודד, מול שרת שמטפטף תשובה, שהתקרה של ה-SDK לבדה לא עוצרת את
הקריאה ו-``gevent.Timeout`` כן. שבלי ``patch_all`` הוא לא עוצר אותה — נמדד מול אותו שרת ב-28.11.2026, בניסוי נפרד.

**השאלה ותשובת המודל אינן נרשמות** — לא בלוג ולא באירוע ``docs_extract``, כמו שהחיפוש לא רושם את השאלה.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import gevent
import pymongo
from pymongo.errors import ConnectionFailure, PyMongoError

from observability import emit_event
from services import docs_search_contract as contract
from services import docs_search_service as docs_search
from services.docs_search_service import DocsSearchError
from services.llm_endpoint_settings import LlmEndpoint, load_endpoint

logger = logging.getLogger(__name__)

#: הקידומת של משתני הסביבה של החילוץ: ``DOCS_EXTRACT_API_KEY``, ``DOCS_EXTRACT_BASE_URL``, ``DOCS_EXTRACT_MODEL``.
ENV_PREFIX = "DOCS_EXTRACT_"

#: תקרת הזמן לקריאה למודל, מהחיבור ועד סוף התשובה. קריאת הסעיפים מהמסד שלפניה מוגבלת לחוד, ב-
#: ``SEARCH_DB_TIMEOUT_SECONDS`` של החיפוש. ההמתנה של הדפדפן (``DOCS_EXTRACT_DEADLINE_MS`` ב-
#: ``global_search.js``) ארוכה מסכום השתיים, ו-``tests/test_docs_search_files_page.py`` משווה ביניהן.
EXTRACT_DEADLINE_SECONDS = 60.0

#: התקרה על סכום המארקדאון (בבתים של UTF-8) של הסעיפים שנשלחים למודל. נגזרה ממדידה של קובץ הייצוא של האתר
#: בקומיט ``6b52435`` (28.11.2026): הסעיף הגדול ביותר היה 50,730 בתים, ועשרת הגדולים יחד — כמו
#: ``MAX_LIMIT`` של החיפוש — 291,577 בתים. התקרה היא פי שניים מזה. מעליה החילוץ מסרב (``sections_too_large``),
#: בלי חיתוך שקט.
MAX_SECTIONS_BYTES = 2 * 291_577

#: האירוע שנשלח בסוף כל חילוץ, והתוצאות שלו (``docs/observability/events_catalog.rst``).
EVENT = "docs_extract"
OUTCOME_FOUND = "found"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_FAILED = "failed"

#: ההנחיה למודל. סטטית, בלי שום דבר שמשתנה בין לחיצות, ולכן היא גם תחילית זהה שספקים שומרים במטמון.
SYSTEM_PROMPT = """אתה קורא תיעוד טכני של פרויקט תוכנה בשם CodeBot, ובוחר מתוכו את הקטע שעונה על שאלה.

── מי שואל ולמה ──
השואל הוא המפתח של הפרויקט. הוא חיפש בתיעוד בחיפוש וקטורי, שמחזיר את הסעיפים שהניסוח שלהם דומה לניסוח של השאלה. דמיון בניסוח אינו תשובה: סעיף יכול להשתמש באותן מילים ולדבר על משהו אחר, וסעיף שעונה בדיוק יכול להשתמש במילים אחרות לגמרי. לכן הוא מבקש ממך לקרוא את הסעיפים שהחיפוש מצא, להבין מה כתוב בהם, ולמצוא את החלק שעונה על מה שהוא שאל — לפי התוכן וההקשר, ולא לפי מילים משותפות.

── מה לעשות ──
1. קרא את השאלה, ואז את כל הסעיפים. כל סעיף מסומן במספר, ובראשו שביל הכותרות שלו באתר התיעוד.
2. מצא את הקטע הקצר ביותר שעדיין עונה על השאלה במלואה: משפט, פסקה, פריט ברשימה, שורה בטבלה או בלוק קוד. כשהתשובה פרושה על כמה פסקאות רצופות, הקטע כולל את כולן.
3. העתק את הקטע מילה במילה, כמו שהוא כתוב בסעיף, כולל סימני המארקדאון (הדגשות, קוד, קישורים). אל תנסח מחדש, אל תסכם ואל תוסיף הסבר משלך: השואל יקרא את הקטע כציטוט מהתיעוד, ולידו יופיע קישור לסעיף.
4. כשאף סעיף לא עונה על השאלה באמת, התשובה היא "לא נמצא". זו תשובה לגיטימית ורצויה, ולא כישלון. אל תבחר את הסעיף "הכי פחות גרוע", ואל תבחר קטע שרק מזכיר את הנושא בלי לענות עליו: קטע כזה גרוע מ"לא נמצא", כי השואל יסמוך עליו.

── צורת התשובה ──
ענה ב-JSON בלבד, בלי טקסט לפניו או אחריו ובלי גדר קוד, באחת משתי הצורות:
{"found": true, "section": <מספר הסעיף>, "quote": "<הקטע, מילה במילה>"}
{"found": false}"""


def load_settings(environ: Mapping[str, str] = os.environ) -> Tuple[Optional[LlmEndpoint], List[str]]:
    """ההגדרות של החילוץ, בחוזה של ``load_endpoint``: ``(None, [])`` — לא הוגדרו כלל; ``(None, שגיאות)`` — חלקיות."""
    return load_endpoint(ENV_PREFIX, environ)


def is_offered(environ: Mapping[str, str] = os.environ) -> bool:
    """האם להציג את הכפתור: כן כשההגדרות תקינות, וגם כשהן חלקיות או פגומות — אז הלחיצה אומרת מה חסר.
    כשאף אחת מהן לא מוגדרת, לא."""
    endpoint, errors = load_settings(environ)
    return endpoint is not None or bool(errors)


def deadline_enforceable() -> bool:
    """האם ``gevent.Timeout`` יכול לקטוע קריאה מהרשת בתהליך הזה: רק כש-``socket`` ו-``ssl`` הוחלפו בגרסאות
    השיתופיות של gevent (``gevent.monkey.is_module_patched``, ``gevent/monkey/_state.py``)."""
    from gevent.monkey import is_module_patched

    return is_module_patched("socket") and is_module_patched("ssl")


def validated_section_ids(value: object) -> List[str]:
    """המזהים של הסעיפים: רשימה של 1 עד ``MAX_LIMIT`` מזהים, כל אחד ``_id`` של סעיף, בלי כפילויות."""
    if not isinstance(value, list) or not 1 <= len(value) <= docs_search.MAX_LIMIT:
        raise DocsSearchError("invalid_section_ids", 400, detail=f"a list of 1..{docs_search.MAX_LIMIT} ids")
    if not all(contract.is_section_id(item) for item in value):
        raise DocsSearchError("invalid_section_ids", 400, detail="an id is 64 lowercase hex characters")
    if len(set(value)) != len(value):
        raise DocsSearchError("invalid_section_ids", 400, detail="duplicate ids")
    return list(value)


def _read_sections(db: Any, section_ids: List[str]) -> List[Dict[str, Any]]:
    """הסעיפים לפי הסדר שהדפדפן שלח, כמו הכרטיסים. סעיף שכבר אינו באינדקס (מעבר שרץ מאז החיפוש) חסר."""
    try:
        with pymongo.timeout(docs_search.SEARCH_DB_TIMEOUT_SECONDS):
            found = docs_search.read_sections(db, section_ids)
    except PyMongoError as exc:
        if docs_search._ran_out_of_time(exc):
            raise DocsSearchError("database_timeout", 504) from exc
        if isinstance(exc, ConnectionFailure):
            logger.warning("docs extract: the database is unreachable (%s)", type(exc).__name__)
            raise DocsSearchError("database_unavailable", 503) from exc
        raise
    sections: List[Dict[str, Any]] = []
    for section_id in section_ids:
        doc = found.get(section_id)
        result = docs_search.section_result(section_id, doc) if doc is not None else None
        if result is not None:
            sections.append(result)
    if not sections:
        raise DocsSearchError("sections_gone", 409)
    return sections


def _section_block(number: int, section: Dict[str, Any]) -> str:
    trail = " ← ".join(section["breadcrumb"]) or section["title"]
    return f'<section number="{number}">\nשביל: {trail}\n\n{section["markdown"]}\n</section>'


def build_messages(query: str, sections: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """ההנחיה בתפקיד ``system`` — כמו בדוגמאות של עמוד התאימות ל-OpenAI של Gemini
    (https://aistudio.google.com/docs/openai, נקרא 28.11.2026) — ואחריה השאלה והסעיפים, ממוספרים מ-1."""
    blocks = "\n\n".join(_section_block(number, section) for number, section in enumerate(sections, start=1))
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"<question>\n{query}\n</question>\n\n{blocks}"},
    ]


def _openai_client(endpoint: LlmEndpoint) -> Any:
    """לקוח ל-``endpoint``. ``timeout`` הוא תקרה לכל פעולה מול הרשת, כדי שלא תהיה ארוכה מהקריאה כולה (ברירת
    המחדל של ה-SDK היא 600 שניות, ``openai/_constants.py``, ``DEFAULT_TIMEOUT``). בלי ניסיון חוזר: התקרה
    היא אחת ללחיצה, וניסיון שני היה מתחיל מאוחר ונקטע בה — האדמין לוחץ שוב."""
    import openai  # ייבוא של כ-0.4 שניות, ולכן רק כשבאמת קוראים למודל ולא ברינדור של עמוד הקבצים

    return openai.OpenAI(
        api_key=endpoint.api_key, base_url=endpoint.base_url, timeout=EXTRACT_DEADLINE_SECONDS, max_retries=0
    )


def _log_provider_failure(exc: Exception) -> None:
    """בלוג רק הסוג והקודים: גוף השגיאה הוא טקסט של הספק, ואין ערובה שהוא לא מצטט את מה שנשלח אליו."""
    import openai

    status = exc.status_code if isinstance(exc, openai.APIStatusError) else None
    request_id = exc.request_id if isinstance(exc, openai.APIStatusError) else None
    code = exc.code if isinstance(exc, openai.APIError) else None
    logger.warning(
        "docs extract: the model call failed: %s status=%s code=%s request_id=%s",
        type(exc).__name__, status, code, request_id,
    )


def _call_model(endpoint: LlmEndpoint, messages: List[Dict[str, str]],
                client_factory: Callable[[LlmEndpoint], Any]) -> object:
    """תוכן התשובה של המודל, או ``DocsSearchError``. חריגה שאינה של ה-SDK — באג — עולה כמו שהיא.

    הפרמטרים הם ``model`` ו-``messages`` בלבד: רק הם מופיעים בכל הדוגמאות של ``chat.completions.create`` בעמוד
    התאימות של Gemini. ``max_completion_tokens`` ו-``response_format`` לא מופיעים שם, ואורך התשובה מוגבל ממילא
    על ידי התקרה.
    """
    import openai

    timer = gevent.Timeout(EXTRACT_DEADLINE_SECONDS)
    timer.start()
    try:
        with client_factory(endpoint) as client:
            response = client.chat.completions.create(model=endpoint.model, messages=messages)
    except gevent.Timeout as fired:
        # ``Timeout`` הוא ``BaseException``, ולכן ה-SDK לא תופס אותו בדרך (``request`` ב-``openai/_base_client.py``
        # תופס רק את החריגות של הרשת ושל ה-SDK). ייתכן שזו תקרה של מי שקרא לנו, ואז היא לא שלנו להשתיק.
        if fired is not timer:
            raise
        logger.warning("docs extract: the model did not answer within %.0f seconds", EXTRACT_DEADLINE_SECONDS)
        raise DocsSearchError("extract_timeout", 504) from None
    # המחלקות הספציפיות לפני מחלקות הבסיס שלהן.
    except openai.RateLimitError as exc:
        _log_provider_failure(exc)
        raise DocsSearchError("extract_quota", 429) from exc
    except openai.APITimeoutError as exc:
        _log_provider_failure(exc)
        raise DocsSearchError("extract_timeout", 504) from exc
    except openai.APIStatusError as exc:
        _log_provider_failure(exc)
        raise DocsSearchError("extract_failed", 502, detail=f"status {exc.status_code}") from exc
    except openai.OpenAIError as exc:
        # מחלקת הבסיס של כל שגיאות ה-SDK (חיבור, תשובה שלא בצורה, אימות) — והמצב "הקריאה למודל נכשלה" הוצהר
        # לכל אחת מהן.
        _log_provider_failure(exc)
        raise DocsSearchError("extract_failed", 502, detail=type(exc).__name__) from exc
    finally:
        timer.close()
    choice = response.choices[0] if response.choices else None
    if choice is None:
        logger.warning("docs extract: the model returned no choices")
        return None
    if choice.finish_reason != "stop":
        logger.warning("docs extract: the model stopped with finish_reason=%s", choice.finish_reason)
    return choice.message.content


def _bad_answer(reason: str) -> DocsSearchError:
    logger.warning("docs extract: the model's answer is not in the asked form (%s)", reason)
    return DocsSearchError("extract_bad_answer", 502, detail=reason)


def parse_answer(content: object, count: int, max_quote_bytes: int) -> Tuple[Optional[int], str]:
    """``(מספר הסעיף, הקטע)`` כשנמצא, ``(None, "")`` כשלא נמצא, או ``extract_bad_answer``.

    הקטע מוצג כמו שהמודל החזיר אותו, עם הקישור לסעיף, ואינו מושווה לטקסט של הסעיף: שינוי קטן בניסוח לא
    פוסל תשובה (החלטה מ-28.11.2026). ה-JSON נקרא מה-``{`` הראשון ב-``raw_decode``, כך שגדר קוד סביבו לא
    מפריעה. קטע ארוך מכל מה שנשלח למודל (``max_quote_bytes``) אינו קטע מתוכו, ונפסל.
    """
    if not isinstance(content, str) or not content.strip():
        raise _bad_answer("empty")
    start = content.find("{")
    if start < 0:
        raise _bad_answer("not_json")
    try:
        data, _end = json.JSONDecoder().raw_decode(content, start)
    except json.JSONDecodeError:
        raise _bad_answer("not_json") from None
    if not isinstance(data, dict):
        raise _bad_answer("not_an_object")
    found = data.get("found")
    if found is False:
        return None, ""
    if found is not True:
        raise _bad_answer("found_is_not_boolean")
    number = data.get("section")
    if type(number) is not int or not 1 <= number <= count:
        raise _bad_answer("no_such_section")
    quote = data.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        raise _bad_answer("no_quote")
    quote = quote.strip()
    if len(quote.encode("utf-8", "surrogatepass")) > max_quote_bytes:
        raise _bad_answer("quote_longer_than_the_sections")
    return number, quote


def _emit(outcome: str, code: Optional[str], model: Optional[str], started: float,
          clock: Callable[[], float]) -> None:
    emit_event(
        EVENT,
        severity="warning" if outcome == OUTCOME_FAILED else "info",
        outcome=outcome,
        code=code,
        model=model,
        duration_ms=int(round((clock() - started) * 1000)),
    )


def extract(
    db: Any,
    query: object,
    section_ids: object,
    *,
    environ: Optional[Mapping[str, str]] = None,
    client_factory: Optional[Callable[[LlmEndpoint], Any]] = None,
    can_enforce_deadline: Optional[Callable[[], bool]] = None,
    clock: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """הקטע שעונה על ``query`` מתוך הסעיפים ``section_ids``.

    ``{"found": True, "quote": ..., "section": {...}}`` — הסעיף בצורה של כרטיס, בלי המארקדאון; או
    ``{"found": False}``. ``DocsSearchError`` לכל כשל צפוי, עם קוד יציב. כל קריאה שמסתיימת באחד מהם שולחת את
    האירוע :data:`EVENT`. מה שלא נמסר נלקח מהמודול בזמן הקריאה: ``os.environ``, ``_openai_client`` ו-
    :func:`deadline_enforceable`.
    """
    if environ is None:
        environ = os.environ
    if client_factory is None:
        client_factory = _openai_client
    if can_enforce_deadline is None:
        can_enforce_deadline = deadline_enforceable
    started = clock()
    model: Optional[str] = None
    try:
        text = docs_search.validated_query(query)
        ids = validated_section_ids(section_ids)
        endpoint, errors = load_settings(environ)
        if endpoint is None:
            if errors:
                raise DocsSearchError("extract_misconfigured", 503, detail="; ".join(errors))
            raise DocsSearchError("extract_not_configured", 503)
        model = endpoint.model
        if not can_enforce_deadline():
            raise DocsSearchError("extract_needs_gevent", 503)
        sections = _read_sections(db, ids)
        size = sum(len(section["markdown"].encode("utf-8", "surrogatepass")) for section in sections)
        if size > MAX_SECTIONS_BYTES:
            raise DocsSearchError("sections_too_large", 422, detail=f"max {MAX_SECTIONS_BYTES} bytes")
        messages = build_messages(text, sections)
        content = _call_model(endpoint, messages, client_factory)
        sent_bytes = sum(len(message["content"].encode("utf-8", "surrogatepass")) for message in messages[1:])
        number, quote = parse_answer(content, len(sections), sent_bytes)
    except DocsSearchError as exc:
        _emit(OUTCOME_FAILED, exc.code, model, started, clock)
        raise
    if number is None:
        _emit(OUTCOME_NOT_FOUND, None, model, started, clock)
        return {"found": False}
    _emit(OUTCOME_FOUND, None, model, started, clock)
    section = {key: value for key, value in sections[number - 1].items() if key != "markdown"}
    return {"found": True, "quote": quote, "section": section}
