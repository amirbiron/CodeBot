"""
ChatOps – שליחת משימות קוד ל‑Claude Code דרך GitHub Actions.

המודול הזה מכיל את הלוגיקה ה"טהורה" של הפקודות: סניטציה, ולידציה ובניית
טקסטים לתצוגה. אין כאן I/O ואין תלות ב‑telegram — ככה אפשר לבדוק הכל בלי stubs.

הזרימה: הבוט מקבל ‎/claude <משימה>‎, מנקה את הטקסט, מציג preview לאישור,
ואחרי אישור פותח Issue ב‑GitHub עם מנשן ‎@claude‎ שמפעיל את ה‑workflow.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── מגבלות ─────────────────────────────────────────────────────────────────
# הפרומפט נכנס לגוף Issue ציבורי ולפרומפט של Claude, לכן שומרים אותו קצר.
MIN_PROMPT_LEN = 10
_DEFAULT_MAX_PROMPT_LEN = 1500


def get_max_prompt_len() -> int:
    """אורך מקסימלי לפרומפט (ניתן לכוונון דרך ENV)."""
    try:
        value = int(os.getenv("CLAUDE_MAX_PROMPT_LEN", str(_DEFAULT_MAX_PROMPT_LEN)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_PROMPT_LEN
    # גבולות שפיות: לא פחות מהמינימום ולא יותר ממה ש-GitHub נושא בנוחות
    return max(MIN_PROMPT_LEN, min(value, 20000))


def get_max_tasks_per_day() -> int:
    """מכסת משימות יומית למשתמש (הגנת עלות מול Anthropic API)."""
    try:
        value = int(os.getenv("CLAUDE_MAX_TASKS_PER_DAY", "10"))
    except (TypeError, ValueError):
        return 10
    return max(0, value)


# ── זיהוי סודות ────────────────────────────────────────────────────────────
# שלוש התבניות הראשונות זהות ל-SensitiveDataFilter ב-utils.py כדי לשמור עקביות.
SECRET_PATTERNS: Sequence[Tuple[str, str]] = (
    (r"ghp_[A-Za-z0-9]{20,}", "GitHub token"),
    (r"github_pat_[A-Za-z0-9_]{20,}", "GitHub fine-grained PAT"),
    (r"gh[opsu]_[A-Za-z0-9]{20,}", "GitHub token"),
    (r"sk-ant-[A-Za-z0-9_\-]{20,}", "Anthropic API key"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    (r"xox[baprs]-[A-Za-z0-9\-]{10,}", "Slack token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY", "Private key"),
    (r"\d{6,}:AA[A-Za-z0-9_\-]{30,}", "Telegram bot token"),
    (r"mongodb(?:\+srv)?://[^\s:]+:[^\s@]+@", "MongoDB URI עם סיסמה"),
    (r"Bearer\s+[A-Za-z0-9\-_.=:/+]{20,}", "Bearer token"),
)

_COMPILED_SECRETS = [(re.compile(pattern), label) for pattern, label in SECRET_PATTERNS]

# תווי בקרה שאין להם מה לחפש בגוף Issue (משאירים \n ו-\t)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# תווים בלתי נראים שעלולים לשמש להסתרת טקסט מהעין אבל לא מהמודל
_ZERO_WIDTH_RE = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]"
)
# zero-width space שמוזרק אחרי @ כדי לנטרל מנשן
_ZWSP = "\u200b"
# מנשן GitHub: ‎@user‎ / ‎@org/team‎
_MENTION_RE = re.compile(r"@(?=[A-Za-z0-9])")

# התג שתוחם את הטקסט של המשתמש בתוך גוף ה-Issue
TASK_OPEN_TAG = "<task-from-telegram>"
TASK_CLOSE_TAG = "</task-from-telegram>"


def detect_secrets(text: str) -> List[str]:
    """מחזיר רשימת סוגי סודות שזוהו בטקסט (בלי הערך עצמו)."""
    if not text:
        return []
    found: List[str] = []
    for regex, label in _COMPILED_SECRETS:
        if regex.search(text) and label not in found:
            found.append(label)
    return found


def _neutralize_structure(text: str) -> str:
    """מנטרל תווים שיכולים לשבור את מבנה גוף ה‑Issue.

    הכי קריטי: HTML comments. בגוף ה-Issue יש בלוק meta מוסתר בתוך <!-- ... -->,
    ו-"-->" בטקסט של המשתמש היה סוגר אותו מוקדם או מזריק meta מזויף.
    """
    text = text.replace("<!--", "‹!--").replace("-->", "--›")
    # התג התוחם — כדי שלא ניתן יהיה "לצאת" מהבלוק ולהוסיף הוראות
    text = text.replace(TASK_CLOSE_TAG, "‹/task-from-telegram›")
    text = text.replace(TASK_OPEN_TAG, "‹task-from-telegram›")
    return text


def _neutralize_mentions(text: str) -> str:
    """מוסיף zero-width space אחרי ‎@‎ כדי שלא ייווצרו מנשנים ב‑GitHub.

    שתי סיבות: לא לתייג אנשים אקראיים, ולא ליצור ‎@claude‎ שני שיבלבל
    את תנאי ההפעלה של ה‑workflow.
    """
    return _MENTION_RE.sub("@" + _ZWSP, text)


def sanitize_prompt(raw: str) -> Tuple[str, Optional[str]]:
    """מנקה ומאמת את הטקסט שהמשתמש שלח.

    Returns:
        (טקסט נקי, שגיאה בעברית או None). כשיש שגיאה — הטקסט הנקי ריק.

    חשוב: הודעת השגיאה לעולם לא מכילה את הטקסט המקורי, כדי שסוד שזוהה
    לא יחזור לצ'אט.
    """
    text = str(raw or "")

    # נרמול שורות ותווים בלתי נראים לפני כל בדיקה
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS_RE.sub("", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = text.strip()

    if not text:
        return "", "לא נשלח טקסט. שימוש: <code>/claude תיאור המשימה</code>"

    if len(text) < MIN_PROMPT_LEN:
        return "", f"המשימה קצרה מדי (מינימום {MIN_PROMPT_LEN} תווים). תכתוב קצת יותר פירוט."

    max_len = get_max_prompt_len()
    if len(text) > max_len:
        return "", (
            f"המשימה ארוכה מדי ({len(text)} תווים, המקסימום הוא {max_len}). "
            "תקצר אותה או תפצל לכמה משימות."
        )

    secrets_found = detect_secrets(text)
    if secrets_found:
        kinds = ", ".join(secrets_found)
        return "", (
            f"🚨 ההודעה מכילה מה שנראה כמו סוד ({kinds}) — לא נשלח.\n"
            "Issue ב‑GitHub נשמר לצמיתות גם אחרי מחיקה, אז עדיף לא לקחת סיכון."
        )

    text = _neutralize_structure(text)
    text = _neutralize_mentions(text)
    return text, None


# ── בניית טקסטים לתצוגה ────────────────────────────────────────────────────

def _shorten(text: str, limit: int) -> str:
    s = str(text or "").strip()
    if len(s) > limit:
        return s[: max(0, limit - 1)] + "…"
    return s


def _escape_html(text: str) -> str:
    """escape מינימלי ל‑parse_mode=HTML של טלגרם."""
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_preview_text(prompt: str, repo: str) -> str:
    """טקסט ה‑preview שמוצג לפני שליחה בפועל."""
    return (
        "🤖 <b>שליחת משימה ל‑Claude Code</b>\n\n"
        f"<b>ריפו:</b> <code>{_escape_html(repo)}</code>\n\n"
        "<b>המשימה:</b>\n"
        f"<blockquote>{_escape_html(_shorten(prompt, 900))}</blockquote>\n\n"
        "יפתח Issue בריפו ו‑Claude יתחיל לעבוד. זה עולה טוקנים — לאשר?"
    )


def build_preview_keyboard(request_id: str) -> Dict[str, Any]:
    """מקלדת אישור/ביטול. ה‑callback_data קצר בהרבה מ‑64 בתים."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ שלח ל‑Claude", "callback_data": f"claude_ok:{request_id}"},
                {"text": "❌ בטל", "callback_data": f"claude_no:{request_id}"},
            ]
        ]
    }


def format_dispatch_result(result: Dict[str, Any]) -> str:
    """הודעת ה‑ack שנשלחת מיד אחרי פתיחת ה‑Issue."""
    if not result.get("success"):
        error = _shorten(result.get("error") or "שגיאה לא ידועה", 300)
        return f"❌ לא הצלחתי לפתוח את ה‑Issue.\n<code>{_escape_html(error)}</code>"

    number = result.get("issue_number")
    url = result.get("issue_url") or ""
    return (
        f"📤 <b>נשלח ל‑Claude Code</b> — Issue #{number}\n"
        f"{_escape_html(url)}\n\n"
        "⏳ ה‑workflow אמור להתחיל בתוך כדקה. אעדכן כשיהיה מה לספר."
    )


_STATUS_LABELS = {
    "pending_confirm": "⏸️ ממתין לאישור",
    "dispatched": "📤 נשלח",
    "running": "🔄 רץ",
    "completed": "✅ הסתיים",
    "failed": "❌ נכשל",
    "cancelled": "🚫 בוטל",
    "timeout": "⌛ לא זוהתה ריצה",
}


def status_label(status: str) -> str:
    return _STATUS_LABELS.get(str(status or ""), f"❓ {status}")


def format_task_details(task: Optional[Dict[str, Any]]) -> str:
    """פירוט מלא של משימה אחת (‎/claude_status‎)."""
    if not task:
        return "לא נמצאה משימה. שלח <code>/claude &lt;משימה&gt;</code> כדי להתחיל."

    lines = [
        f"<b>משימה {task.get('request_id')}</b> — {status_label(task.get('status', ''))}",
        "",
        f"<blockquote>{_escape_html(_shorten(task.get('prompt') or '', 400))}</blockquote>",
    ]
    if task.get("issue_url"):
        lines.append(f"📋 Issue #{task.get('issue_number')}: {_escape_html(task['issue_url'])}")
    if task.get("run_url"):
        lines.append(f"⚙️ ריצה: {_escape_html(task['run_url'])}")
    if task.get("pr_url"):
        lines.append(f"🔀 PR: {_escape_html(task['pr_url'])}")
    if task.get("error"):
        lines.append(f"⚠️ {_escape_html(_shorten(task['error'], 300))}")
    return "\n".join(lines)


def format_tasks_list(tasks: Sequence[Dict[str, Any]]) -> str:
    """רשימת המשימות האחרונות (‎/claude_tasks‎)."""
    if not tasks:
        return "אין עדיין משימות. שלח <code>/claude &lt;משימה&gt;</code> כדי להתחיל."

    lines = ["🤖 <b>המשימות האחרונות</b>", ""]
    for task in tasks:
        number = task.get("issue_number")
        head = f"#{number}" if number else str(task.get("request_id") or "—")
        lines.append(
            f"{status_label(task.get('status', ''))} <b>{head}</b> — "
            f"{_escape_html(_shorten(task.get('prompt') or '', 80))}"
        )
    lines.append("")
    lines.append("לפרטים: <code>/claude_status &lt;מספר&gt;</code>")
    return "\n".join(lines)


def parse_task_selector(args: str) -> Tuple[Optional[int], bool]:
    """מפרש ארגומנט של ‎/claude_status‎ / ‎/claude_cancel‎.

    Returns:
        (issue_number או None, האם התבקשה המשימה האחרונה)
    """
    raw = str(args or "").strip().lstrip("#")
    if not raw or raw.lower() == "last":
        return None, True
    try:
        return int(raw), False
    except ValueError:
        return None, True
