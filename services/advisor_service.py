"""מצב היועץ — השכבה שמדברת עם מודל השפה: הגדרות, הפרומפט, הקריאה ופענוח התשובה.

עבר מ-``llm.py`` ומ-``config.py`` בריפו ``codekeeper_advisor_bot``. הפרומפט ומסמך
הידע עברו כמו שהם. מה שהשתנה במעבר:

- **לקוח אסינכרוני** (``openai.AsyncOpenAI``) במקום לקוח סינכרוני בתוך
  ``asyncio.to_thread``. קריאה למודל נמשכת שניות ארוכות, וב-thread היא הייתה
  מחזיקה עובד של ה-executor המשותף של הבוט לכל הזמן הזה.
- **תקרת זמן אחת לקריאה כולה** (``ANSWER_DEADLINE_SECONDS``), כולל הניסיון
  החוזר של ה-SDK: מי שממתין לתשובה מחזיק את המנעול של הגולש.
- **משתני סביבה עם קידומת משלהם** — ``ADVISOR_API_KEY``, ``ADVISOR_BASE_URL``,
  ``ADVISOR_MODEL``, ``ADVISOR_CONTACT_URL``, ``ADVISOR_CONTEXT_EXCHANGES`` — והמפתח
  והכתובת מועברים ללקוח במפורש. בלי ``base_url`` מפורש ה-SDK קורא בעצמו את
  ``OPENAI_BASE_URL`` מהסביבה (openai 3.36.1, ``openai/_client.py``, ``AsyncOpenAI.__init__``).
- **אורך הזיכרון נספר בזוגות** (``ADVISOR_CONTEXT_EXCHANGES``) ולא בהודעות כמו
  ``CONTEXT_WINDOW_SIZE`` בבוט הנפרד: כל מסמך בזיכרון השיחה הוא זוג שאלה-תשובה.
- טמפרטורה ו-``reasoning_effort`` אינם ניתנים להגדרה, ושאלות ההמשך פועלות תמיד:
  בבוט הנפרד שני הראשונים נשארו ריקים, כלומר ברירת המחדל של המודל.
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

import openai

logger = logging.getLogger(__name__)

# ─── הגדרות ──────────────────────────────────────────────────────────────────

#: מסמך הידע — נכנס כולו לפרומפט בכל שאלה, בלי RAG.
KNOWLEDGE_FILE = Path(__file__).resolve().parent / "advisor_knowledge" / "codekeeper.md"

#: תקרה לניסיון אחד מול הספק. ברירת המחדל של ה-SDK היא 600 שניות
#: (openai 3.36.1, ``openai/_constants.py``, ``DEFAULT_TIMEOUT``).
LLM_TIMEOUT_SECONDS = 45.0

#: ניסיון חוזר אחד על תקלה חולפת. התקרה הכוללת היא ``ANSWER_DEADLINE_SECONDS``,
#: ולכן ניסיון שני שמתחיל מאוחר נקטע.
LLM_MAX_RETRIES = 1

#: תקרת הזמן לקריאה כולה, כולל הניסיון החוזר.
ANSWER_DEADLINE_SECONDS = 60.0

LLM_MAX_COMPLETION_TOKENS = 1500

#: ברירת המחדל של ``ADVISOR_CONTEXT_EXCHANGES``: כמה זוגות שאלה-תשובה אחרונים נכנסים לפרומפט.
#: אותו זיכרון כמו בבוט הנפרד, שם ``CONTEXT_WINDOW_SIZE=10`` ספר הודעות, כלומר 5 זוגות.
DEFAULT_CONTEXT_EXCHANGES = 5

#: התקרה של ``ADVISOR_CONTEXT_EXCHANGES``. כל זוג בזיכרון נשלח שוב בכל שאלה שאחריו, ותשובה
#: יכולה להגיע עד ``LLM_MAX_COMPLETION_TOKENS``, כך שהזיכרון מייקר כל קריאה. התקרה היא
#: החלטה ולא מדידה: היא חוסמת ערך שהוקלד בטעות (למשל 500), לא כיוונון.
MAX_CONTEXT_EXCHANGES = 20


@dataclass(frozen=True)
class AdvisorSettings:
    api_key: str
    base_url: str
    model: str
    contact_url: str  # ריק = בלי כפתור יצירת קשר
    context_exchanges: int = DEFAULT_CONTEXT_EXCHANGES


def load_settings(environ: Mapping[str, str] = os.environ) -> Tuple[Optional[AdvisorSettings], List[str]]:
    """קריאת ההגדרות מהסביבה.

    ``(הגדרות, [])`` — תקין. ``(None, [])`` — היועץ לא הוגדר כלל. ``(None, שגיאות)``
    — הוגדר חלקית או בערכים פגומים. ``ADVISOR_CONTACT_URL`` ו-``ADVISOR_CONTEXT_EXCHANGES``
    אינם חובה.
    """
    api_key = environ.get("ADVISOR_API_KEY", "").strip()
    base_url = environ.get("ADVISOR_BASE_URL", "").strip()
    model = environ.get("ADVISOR_MODEL", "").strip()
    contact_url = environ.get("ADVISOR_CONTACT_URL", "").strip()
    raw_exchanges = environ.get("ADVISOR_CONTEXT_EXCHANGES", "").strip()

    if not (api_key or base_url or model):
        return None, []

    errors: List[str] = []
    if not api_key:
        errors.append("ADVISOR_API_KEY לא מוגדר")
    # המפתח נשלח בכותרת Authorization, וכותרת HTTP היא ASCII. תו נסתר שנכנס
    # בהעתקה מדפדפן היה מפיל כל קריאה בצד הלקוח, ולא בעלייה.
    elif not api_key.isascii() or any(ch.isspace() for ch in api_key):
        errors.append("ADVISOR_API_KEY חייב להיות ASCII בלי רווחים")
    base_parts = urlsplit(base_url)
    if base_parts.scheme not in ("https", "http") or not base_parts.netloc:
        errors.append("ADVISOR_BASE_URL חייב להיות כתובת מלאה שמתחילה ב-https://")
    if not model:
        errors.append("ADVISOR_MODEL לא מוגדר")
    context_exchanges = DEFAULT_CONTEXT_EXCHANGES
    if raw_exchanges:
        # ספרות ASCII בלבד ובאורך חסום, לפני int(): ערך כמו "5.0", "²" או מחרוזת ארוכה
        # הוא שגיאת הגדרה שנאמרת בלוג, ולא חריגה של int() שמפילה את הרישום
        if re.fullmatch(r"[0-9]{1,3}", raw_exchanges) and 1 <= int(raw_exchanges) <= MAX_CONTEXT_EXCHANGES:
            context_exchanges = int(raw_exchanges)
        else:
            errors.append(f"ADVISOR_CONTEXT_EXCHANGES חייב להיות מספר שלם בין 1 ל-{MAX_CONTEXT_EXCHANGES}")
    # Bot API מקבל בכפתור url רק "HTTP or tg:// URL" — כתובת אחרת הייתה נכשלת
    # בכל תשובה שמציגה את הכפתור, לא בעלייה.
    if contact_url:
        contact_parts = urlsplit(contact_url)
        if contact_parts.scheme not in ("https", "http", "tg") or not contact_parts.netloc:
            errors.append("ADVISOR_CONTACT_URL חייב להתחיל ב-https:// או ב-tg://")
    if errors:
        return None, errors
    return AdvisorSettings(
        api_key=api_key,
        base_url=base_url,
        model=model,
        contact_url=contact_url,
        context_exchanges=context_exchanges,
    ), []


# טוקן שהמודל שם בתחילת התשובה כשאין לו תשובה במסמך או כשהגולש מבקש לדבר
# עם המפתח. זה אותו מנגנון כמו HANDOFF_MARKER בפרויקט המקור: זיהוי
# דטרמיניסטי של startswith, בלי חיפוש ניסוחים ("אין לי מידע" וכו') שמייצר
# זיהויים שגויים.
CONTACT_MARKER = "[CONTACT]"

FALLBACK_ERROR = "מצטער, הייתה תקלה זמנית. נסו לשלוח את השאלה שוב בעוד רגע 🙏"
# כשהמודל שלח רק את הטוקן בלי טקסט
CONTACT_DEFAULT_TEXT = "על זה כדאי לשאול ישירות את המפתח 👇"


# ─── הפרומפט ─────────────────────────────────────────────────────────────────

_FORMATTING_RULES = (
    "חוק ברזל: השתמש אך ורק בתגי HTML של טלגרם. אסור בהחלט להשתמש בתחביר Markdown "
    "(כוכביות, קווים תחתונים, סולמיות).\n"
    "תגים מותרים:\n"
    "- תג b (פתיחה וסגירה) — לכותרות ולשמות של פיצ'רים\n"
    "- תג i (פתיחה וסגירה) — להערות משניות, הבהרות ותנאים\n"
    "- תג code (פתיחה וסגירה) — לשמות של פקודות, קבצים וכלים\n"
    "- רשימות עם תבליטים (•) כשיש כמה פריטים\n"
    "- רווח ברור בין פסקאות ונושאים שונים\n"
    "דוגמה נכונה: <b>שמירת קבצים</b> — <i>כולל היסטוריית גרסאות</i>\n"
    "דוגמה שגויה: **שמירת קבצים** — *כולל היסטוריית גרסאות*\n"
    "אם תשתמש בכוכביות (*) או בקווים תחתונים (_) להדגשה — התשובה תיחשב שגויה."
)

_FOLLOW_UP_RULE = (
    "\n── שאלות המשך ──\n"
    "בסוף כל תשובה (חוץ מתשובה שנפתחת ב-" + CONTACT_MARKER + "), הוסף בשורה נפרדת "
    "2-3 שאלות המשך קצרות (עד 6 מילים) שהגולש עשוי לרצות לשאול, בפורמט הזה בדיוק:\n"
    "[שאלות_המשך: שאלה ראשונה | שאלה שנייה | שאלה שלישית]\n"
    "הצע רק שאלות שהתשובה עליהן מופיעה במסמך הידע, ואל תציע שאלה שכבר נענתה בשיחה.\n"
)


def build_system_prompt(knowledge: str) -> str:
    """הפרומפט כולו סטטי — הוראות ואז מסמך הידע.

    חשוב לעלות: OpenAI שומרת במטמון את תחילת הפרומפט ומחייבת עליה מחיר מוזל,
    אבל רק כשהתחילית זהה לחלוטין בין קריאות. לכן אסור להכניס לכאן שום דבר
    שמשתנה (שעה, שם הגולש) — כל דבר דינמי בא אחרי, בהודעות השיחה.
    """
    return f"""אתה היועץ הדיגיטלי של CodeKeeper (בקיצור Ck), ואתה משוחח עם גולשים בטלגרם.

── מי פונה אליך ולמה ──
הפונים אליך הם מפתחים ואנשים שעובדים עם קוד ועם סוכני AI, ששמעו על CodeKeeper ושוקלים אם להשתמש בו. רובם עוד לא יודעים בדיוק מה המוצר עושה, ואין להם סבלנות לקרוא תיעוד ארוך. הם באים עם שאלה אחת: "האם זה יעזור לי, בדרך שבה אני עובד?".

── התפקיד שלך ──
אתה יועץ טכני שמייצג את CodeKeeper. המטרה שלך היא לעזור למפתחים להבין בכנות אם השיטה של "תיעוד חי לפי נושא" מתאימה לזרימת העבודה שלהם עם סוכני AI, או שהם יכולים להסתפק בפתרון פשוט יותר. אתה יועץ אובייקטיבי וישיר — לא איש מכירות. אם הפתרון לא מתאים, תגיד את זה מיד.
העובדות על CodeKeeper — יכולות, מחירים, מגבלות — מגיעות רק ממסמך הידע שבסוף ההודעה הזו. אל תשלים אותן מהידע הכללי שלך על מוצרים דומים, גם כשזה נראה סביר.

── איך לנהל את השיחה (כללים לסוכן) ──

- **שיחה, לא הרצאה:** אל תשפוך על המשתמש את כל המסמך בהודעה הראשונה. תתחיל מלהבין במשפט או שניים איך הוא עובד היום עם סוכני קוד ומה כואב לו.
- **התאם את הדוגמה למשתמש:** אם הוא מתלונן שהסוכן חוזר על אותן טעויות עיצוב או קוד — תן לו בקצרה את דוגמת דריסת הצבע. אם הוא בונה מערכת מורכבת לאורך זמן — תן לו את דוגמת מסמך ה-MCP או האנלוגיה של התיק הרפואי.
- **תן תשובה כנה וחותכת:** ברגע שהבנת את אופי העבודה שלו, תגיד לו בבירור אחד משלושה דברים:
  1. **"זה תפור עליך"** — והסבר בדיוק איזה כאב זה יפתור לו ואיך להתחיל ממסמך אחד בסוף הסשן הבא שלו.
  2. **"תיקיית `docs/` בריפו תספיק לך כרגע"** — אם הוא עובד לבד בריפו אחד רק מול Claude Code ולא צריך גישה מצ'אט, קריאה לפי סעיפים או היסטוריית גרסאות נפרדת.
  3. **"אתה לא צריך מסמכי נושא כבדים, אבל יכול להיעזר בפתקים ושמירת קבצים"** — אם הפרויקטים שלו קטנים יחסית, אבל הוא מחפש דרך נוחה להעביר משימות, פתקים וקטעי קוד בין Claude.ai (למשל מהנייד) לבין Claude Code.

── כשאין תשובה במסמך, או כשהגולש רוצה לדבר עם המפתח ──
אם התשובה לא נמצאת במסמך, או שהגולש מבקש לדבר עם אדם או עם המפתח, פתח את התשובה בדיוק במחרוזת {CONTACT_MARKER} (כולל הסוגריים המרובעים, בשורה משלה). אחריה כתוב משפט או שניים: מה כן ידוע מהמסמך אם יש משהו רלוונטי, ושאפשר לפנות ישירות למפתח. אל תכתוב קישור או שם משתמש — כפתור יצירת קשר מצורף להודעה אוטומטית. אל תכתוב את {CONTACT_MARKER} בשום מצב אחר.

── עיצוב טקסט (חובה!) ──
{_FORMATTING_RULES}
{_FOLLOW_UP_RULE}
── סגנון ──
- דבר תמיד על עצמך בלשון זכר ("אני יכול", "אשמח לעזור"), לעולם לא בלשון נקבה.
- ענה באותה שפה שבה הגולש כותב.
- שאלות שאינן קשורות ל-CodeKeeper או לאופן העבודה של הגולש — הפנה בעדינות חזרה לנושא.

── מסמך הידע ──
{knowledge}
── סוף מסמך הידע ──"""


def build_messages(system_prompt: str, history: list[dict], user_text: str) -> list[dict]:
    """הסדר קבוע: הוראות + מסמך (סטטי, נשמר במטמון) ← היסטוריה ← השאלה."""
    # role=developer ולא system: לפי ה-SDK, "With o1 models and newer, `developer`
    # messages replace the previous `system` messages".
    # מקור: openai/types/chat/chat_completion_developer_message_param.py
    messages = [{"role": "developer", "content": system_prompt}]
    messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    messages.append({"role": "user", "content": user_text})
    return messages


# ─── אתחול ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Runtime:
    settings: AdvisorSettings
    system_prompt: str
    client: openai.AsyncOpenAI


_runtime: Optional[_Runtime] = None


def init_advisor(settings: AdvisorSettings) -> None:
    """טעינת מסמך הידע, בניית הפרומפט והלקוח — פעם אחת, בעליית הבוט.

    הכול נבנה במשתנים מקומיים ומתפרסם בהצבה אחת, כך שאין מצב ביניים שבו יש
    פרומפט בלי לקוח. בניית הלקוח אינה פונה לרשת. קובץ ידע חסר או ריק זורק:
    יועץ בלי מסמך ידע לא יכול לענות על כלום.
    """
    global _runtime
    knowledge = KNOWLEDGE_FILE.read_text(encoding="utf-8").strip()
    if not knowledge:
        raise RuntimeError(f"קובץ הידע ריק: {KNOWLEDGE_FILE}")
    client = openai.AsyncOpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
    )
    _runtime = _Runtime(settings=settings, system_prompt=build_system_prompt(knowledge), client=client)
    logger.info(
        "Advisor ready: model=%s knowledge_chars=%d context_exchanges=%d",
        settings.model, len(knowledge), settings.context_exchanges,
    )


def current_settings() -> Optional[AdvisorSettings]:
    """ההגדרות שהיועץ אותחל איתן, או ``None`` כשהוא כבוי."""
    runtime = _runtime
    return runtime.settings if runtime is not None else None


def context_exchanges() -> int:
    """כמה זוגות אחרונים מזיכרון השיחה נכנסים לפרומפט, לפי ההגדרות שהיועץ אותחל איתן."""
    runtime = _runtime
    if runtime is None:
        raise RuntimeError("init_advisor() was not called")
    return runtime.settings.context_exchanges


# ─── פענוח התשובה ────────────────────────────────────────────────────────────

# תבנית ראשית: [שאלות_המשך: שאלה1 | שאלה2 | שאלה3]
# תבנית חלופית: אותו דבר בלי סוגריים מרובעים (מודלים לפעמים משמיטים אותם)
_FOLLOW_UP_PATTERN = re.compile(r"\[שאלות[_ ]המשך:\s*(.+?)\]")
_FOLLOW_UP_PATTERN_ALT = re.compile(r"שאלות[_ ]המשך:\s*(.+?)(?:\n|$)")


def extract_follow_up_questions(text: str) -> list[str]:
    """חילוץ עד 3 שאלות המשך מתשובת המודל. אין התאמה = רשימה ריקה."""
    match = _FOLLOW_UP_PATTERN.search(text) or _FOLLOW_UP_PATTERN_ALT.search(text)
    if not match:
        return []
    questions = [q.strip() for q in match.group(1).split("|") if q.strip()]
    return questions[:3]


def strip_follow_up_questions(text: str) -> str:
    """הסרת בלוק שאלות ההמשך (כולל שורות ריקות לפניו) לפני שליחה לגולש."""
    text = re.sub(r"\n*\[שאלות[_ ]המשך:\s*.*?\]", "", text)
    text = re.sub(r"\n*שאלות[_ ]המשך:\s*.+?(?:\n|$)", "\n", text)
    return text.strip()


def split_contact_marker(text: str) -> tuple[bool, str]:
    """(האם המודל ביקש כפתור יצירת קשר, הטקסט בלי הטוקן).

    הזיהוי — רק בתחילת התשובה. ההסרה — מכל מקום, כי הטוקן הוא אות פנימי
    בין המודל לקוד ואסור שיגיע לגולש גם כשהמודל שם אותו במקום הלא נכון.
    """
    needs_contact = text.lstrip().startswith(CONTACT_MARKER)
    return needs_contact, text.replace(CONTACT_MARKER, "").strip()


def trim_to_last_sentence(text: str) -> str:
    """חיתוך תשובה שנעצרה בתקרת הטוקנים לגבול בטוח (שורה או משפט שלמים).

    מקור: llm._trim_to_last_sentence — תיקון לבאג חוזר שבו רשימה נקטעה באמצע
    מילה. שורה אחרונה שלא מסתיימת בסימן פיסוק נחתכת; בשורה בודדת חותכים
    לסוף המשפט האחרון.
    """
    text = (text or "").rstrip()
    if not text:
        return ""
    lines = text.split("\n")
    if len(lines) > 1:
        last = lines[-1].rstrip()
        if last and last[-1] not in ".!?:;":
            return "\n".join(lines[:-1]).rstrip() + "\n…"
        return text + "\n…"
    for ch in (".", "!", "?"):
        idx = text.rfind(ch)
        if idx >= len(text) // 3:  # לפחות שליש מהטקסט נשאר
            return text[: idx + 1] + " …"
    return text + "…"


# ─── הפקת תשובה ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Answer:
    text: str                      # HTML של טלגרם, לפני סניטציה
    ok: bool                       # False = תקלה; text הוא הודעת התקלה ולא נשמר בהיסטוריה
    needs_contact: bool = False    # להציג כפתור יצירת קשר
    follow_up_questions: list[str] = field(default_factory=list)


async def generate_answer(history: List[dict], user_text: str) -> Answer:
    """קריאה אחת למודל, עם תקרת זמן אחת לכולה (``ANSWER_DEADLINE_SECONDS``)."""
    runtime = _runtime
    if runtime is None:
        raise RuntimeError("init_advisor() was not called")

    try:
        async with asyncio.timeout(ANSWER_DEADLINE_SECONDS):
            # max_completion_tokens ולא max_tokens: ב-SDK מסומן max_tokens כ-"now
            # deprecated in favor of max_completion_tokens".
            # מקור: openai/resources/chat/completions/completions.py, create()
            response = await runtime.client.chat.completions.create(
                model=runtime.settings.model,
                messages=build_messages(runtime.system_prompt, history, user_text),
                max_completion_tokens=LLM_MAX_COMPLETION_TOKENS,
            )
    except TimeoutError:
        logger.error("Advisor LLM call exceeded %.0f seconds", ANSWER_DEADLINE_SECONDS)
        return Answer(text=FALLBACK_ERROR, ok=False)
    except openai.OpenAIError as e:
        # מחלקת הבסיס של כל שגיאות ה-SDK (APIError, timeout, חיבור, אימות) — והמצב
        # "התשובה נכשלה" הוצהר לכל אחת מהן. בלוג רק הסוג והקודים: גוף השגיאה הוא
        # טקסט של הספק, ואין ערובה שהוא לא מצטט את מה שהגולש כתב.
        logger.error(
            "Advisor LLM call failed: %s status=%s code=%s request_id=%s",
            type(e).__name__,
            getattr(e, "status_code", None),
            getattr(e, "code", None),
            getattr(e, "request_id", None),
        )
        return Answer(text=FALLBACK_ERROR, ok=False)

    # ולידציה של התשובה — content יכול להיות None (למשל refusal)
    choice = response.choices[0] if response.choices else None
    content = choice.message.content if choice is not None else None
    finish_reason = choice.finish_reason if choice is not None else None
    if not isinstance(content, str) or not content.strip():
        logger.error("Advisor LLM returned no text (finish_reason=%s)", finish_reason)
        return Answer(text=FALLBACK_ERROR, ok=False)

    # לוג אבחון — מספרים בלבד. בלי תוכן התשובה: היא יכולה לצטט את הגולש.
    usage = response.usage
    details = usage.prompt_tokens_details if usage is not None else None
    cached_tokens = details.cached_tokens if details is not None and details.cached_tokens is not None else 0
    logger.info(
        "Advisor LLM diag: model=%s finish_reason=%s prompt_tokens=%s cached_tokens=%s "
        "completion_tokens=%s chars=%d",
        response.model, finish_reason,
        usage.prompt_tokens if usage is not None else -1, cached_tokens,
        usage.completion_tokens if usage is not None else -1, len(content),
    )

    text = content.strip()
    if finish_reason == "length":
        logger.warning("Advisor answer hit max_completion_tokens=%d — trimming", LLM_MAX_COMPLETION_TOKENS)
        text = trim_to_last_sentence(text)

    follow_ups = extract_follow_up_questions(text)
    text = strip_follow_up_questions(text)

    needs_contact, text = split_contact_marker(text)
    if needs_contact:
        # אין טעם להציע שאלות המשך כשאין למודל מידע לענות
        follow_ups = []
        text = text or CONTACT_DEFAULT_TEXT
    if not text:
        return Answer(text=FALLBACK_ERROR, ok=False)
    return Answer(text=text, ok=True, needs_contact=needs_contact, follow_up_questions=follow_ups)
