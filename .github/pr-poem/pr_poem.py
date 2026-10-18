"""כותב פואמה קצרה בעברית על PR ומפרסם אותה כתגובה אחת על ה-PR.

רץ מ-``.github/workflows/pr-poem.yml``, ואפשר להריץ אותו גם מקומית::

    python .github/pr-poem/pr_poem.py --pr 3583 --repo amirbiron/CodeBot --dry-run

הזרימה, לפי הסדר:

1. ``ANTHROPIC_API_KEY`` חסר ← אזהרה גלויה ב-Actions ויציאה בהצלחה. זה מצב תצורה, לא כשל של ה-PR.
2. ה-PR מגיע מ-fork, או שכבר יש עליו תגובה עם ``MARKER`` ← יציאה בלי לעשות כלום. רק הסימון שלנו
   נבדק: הפואמה של CodeRabbit אינה נחשבת, ושתיהן יכולות להופיע על אותו PR.
3. הקלט: כותרת, תיאור נקי (``clean_description``) ושמות הקבצים שהשתנו, עד ``MAX_FILES``.
4. קריאה אחת ל-Messages API של Anthropic. ה-system הוא ``prompt.md`` ואחריו ``examples.md``.
5. סידור הפלט (``tidy_poem``) ופרסום תגובה אחת (``format_comment``).

כל כשל אחר — ברשת, ב-API, בפלט או בפרסום — מכשיל את ההרצה עם הודעה. אף הודעה אינה מכילה את המפתח
או את הטוקן: הם נשלחים רק בכותרות, ותוכן שחוזר מהשרת עובר ``_redact`` לפני שהוא מודפס.

``--dry-run`` מדפיס את הבקשה שהייתה נשלחת, בלי המפתח, ולא קורא ל-Anthropic ולא מפרסם. הבדיקות
שהיו עוצרות הרצה אמיתית (fork, פואמה קיימת) מודפסות כהערה, וההדפסה ממשיכה, כדי שאפשר יהיה לבדוק
את הבקשה גם על PR שכבר יש עליו פואמה.

ספרייה סטנדרטית בלבד, כדי שה-workflow לא יצטרך ``pip install``.
"""

from __future__ import annotations

import argparse
import html
import http.client
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
PROMPT_PATH = HERE / "prompt.md"
EXAMPLES_PATH = HERE / "examples.md"

#: הסימון הנסתר שמזהה תגובה של הסוכן הזה. הוא גם מה שמונע פואמה שנייה על אותו PR.
MARKER = "<!-- pr-poem -->"

#: מקור: https://platform.claude.com/docs/en/api/messages ו-https://platform.claude.com/docs/en/api/versioning
#: (``2023-06-01`` היא הגרסה היחידה שמופיעה שם מאז 2023-01-01).
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
#: מזהה ה-Claude API של Claude Sonnet 5.5, מהטבלה ב-https://platform.claude.com/docs/en/about-claude/models/overview.
#: ``POEM_MODEL`` דורס אותו.
DEFAULT_MODEL = "claude-sonnet-5-5"
#: ל-Claude Sonnet 5.5 ההמלצה היא להתחיל ב-``high`` כשהעבודה אינה agentic ואינה רגישה לזמן תגובה
#: (https://platform.claude.com/docs/en/build-with-claude/effort, "Recommended effort levels for Claude Sonnet 5.5").
#: זו גם ברירת המחדל של ה-API, והיא כתובה כאן כדי שהבחירה תהיה גלויה.
EFFORT = "high"
#: תקרה על כל הפלט, כולל החשיבה: ב-Sonnet 5.5 החשיבה נספרת ב-``max_tokens`` גם כשהתוכן שלה לא מוחזר
#: (אותו עמוד). הפואמה עצמה היא כמה מאות טוקנים, והשאר הוא מקום לחשיבה. לא נמדד — ``main`` מדפיס את
#: ``usage`` בכל הרצה, וממנו אפשר לכוונן.
MAX_TOKENS = 8000
#: שניות לכל פעולת רשת חוסמת (התחברות, קריאה) — זה מה ש-``timeout`` של ``urlopen`` מגביל, ולא את
#: הבקשה כולה. התקרה על ההרצה כולה היא ``timeout-minutes`` של הג'וב ב-``pr-poem.yml``.
ANTHROPIC_TIMEOUT = 180

GITHUB_API = "https://api.github.com"
#: הגרסה החדשה ביותר ב-https://docs.github.com/en/rest/about-the-rest-api/api-versions. ברשימת השינויים
#: השוברים שלה אין שינוי בשדות שהסקריפט קורא.
GITHUB_API_VERSION = "2026-03-10"
GITHUB_TIMEOUT = 30
#: ``per_page`` המקסימלי ברשימת התגובות (https://docs.github.com/en/rest/issues/comments).
COMMENTS_PER_PAGE = 100

#: כמה שמות קבצים נשלחים למודל. מעבר לזה נשלחת שורה שאומרת כמה נשארו בחוץ.
MAX_FILES = 40
#: כמה תווים מהתיאור הנקי נשלחים למודל. החיתוך נעשה בסוף שורה (``_cut_at_line_end``).
MAX_DESCRIPTION_CHARS = 12_000
#: פלט ארוך מזה הוא תשובה שהשתבשה, ולא פואמה.
MAX_POEM_LINES = 10

#: נאמר למודל בסוף תיאור שנחתך, כדי שלא יכתוב כאילו קרא את כולו.
DESCRIPTION_CUT_NOTE = "(התיאור ארוך יותר, ונחתך כאן)"

#: בלוק שבוט מוסיף לתיאור בין שתי הערות HTML. cubic פותח ב-
#: ``<!-- This is an auto-generated description by cubic. -->`` וסוגר ב-
#: ``<!-- End of auto-generated description by cubic. -->``. הבלוק מוסר לפני שאר ההערות, כי אחריהן לא
#: נשארים הגבולות שלו, והתוכן שביניהן (כפתורי ``<a>``) היה נשאר.
_BOT_BLOCK_RE = re.compile(
    r"<!--\s*This is an auto-generated\b.*?-->.*?<!--\s*End of auto-generated\b.*?-->",
    re.IGNORECASE | re.DOTALL,
)
#: הערת HTML. בלי ``-->`` היא מסתירה ב-GitHub את כל מה שאחריה, ולכן גם כאן היא נמשכת עד הסוף.
_HTML_COMMENT_RE = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
#: הסיכום ש-Sourcery מוסיף לתיאור. כל מה שממנו והלאה יורד.
_SOURCERY_RE = re.compile(r"^##[ \t]+Summary by Sourcery\b", re.MULTILINE)
#: גדר קוד שפותחת או סוגרת בלוק (``` או ```text).
_FENCE_RE = re.compile(r"`{3,}[\w-]*")
_REPO_RE = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")
#: מחלקות ה-bidi של אות מימין לשמאל (עברית, ערבית) לפי ``unicodedata.bidirectional``. אות משמאל לימין היא ``L``.
_RTL_BIDI_CLASSES = frozenset({"R", "AL"})


class PoemError(Exception):
    """כשל שמכשיל את ההרצה. ההודעה מודפסת כ-``::error::`` ואינה מכילה סודות."""


# --------------------------------------------------------------------------
# הקלט
# --------------------------------------------------------------------------


def _cut_at_line_end(text: str, limit: int) -> Tuple[str, bool]:
    """עד ``limit`` תווים, בסוף השורה האחרונה שנכנסת במלואה. מחזיר גם האם נחתך.

    שורה שמסתיימת בדיוק בגבול נכנסת, כי ה-``\\n`` שלה יושב במקום ``limit``. שורה אחת שארוכה
    לבדה מהגבול נחתכת בגבול עצמו — אחרת לא היה נשאר כלום.
    """
    if len(text) <= limit:
        return text, False
    end = text.rfind("\n", 0, limit + 1)
    if end <= 0:
        end = limit
    return text[:end].rstrip(), True


def clean_description(body: Any) -> str:
    """התיאור בלי הבלוקים שהבוטים מוסיפים, ועד ``MAX_DESCRIPTION_CHARS`` תווים.

    יורדים: בלוקים שבוט תוחם בהערות (``_BOT_BLOCK_RE``), כל הערת HTML, וכל מה שמ-
    ``## Summary by Sourcery`` והלאה. ברגע ה-``opened`` הבלוקים האלה לרוב עוד לא שם, אבל
    בהרצה ידנית או ב-``ready_for_review`` הם כבר יהיו. תיאור שנחתך מסתיים ב-``DESCRIPTION_CUT_NOTE``.
    """
    if not isinstance(body, str):
        return ""
    text = _BOT_BLOCK_RE.sub("", body)
    text = _HTML_COMMENT_RE.sub("", text)
    sourcery = _SOURCERY_RE.search(text)
    if sourcery:
        text = text[: sourcery.start()]
    text = text.strip()
    text, was_cut = _cut_at_line_end(text, MAX_DESCRIPTION_CHARS)
    if was_cut:
        text = f"{text}\n{DESCRIPTION_CUT_NOTE}"
    return text


def build_user_message(title: str, description: str, files: List[str], total_files: int) -> str:
    """ההודעה למודל: כותרת, תיאור וקבצים, כל אחד בתוך תגית משלו."""
    listed = "\n".join(f"- {name}" for name in files) or "(אין קבצים ברשימה)"
    left_out = total_files - len(files)
    if left_out > 0:
        listed += f"\n(ועוד {left_out} קבצים שלא נכללו ברשימה)"
    return (
        "כתוב פואמה על ה-PR הבא.\n\n"
        f"<pr_title>\n{title}\n</pr_title>\n\n"
        f"<pr_description>\n{description or '(אין תיאור)'}\n</pr_description>\n\n"
        f"<changed_files>\n{listed}\n</changed_files>"
    )


def build_request(model: str, prompt: str, examples: str, user_message: str) -> Dict[str, Any]:
    """גוף הבקשה ל-Messages API. ה-system הוא ההנחיה ואחריה הדוגמאות, כשני בלוקים של טקסט."""
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": [
            {"type": "text", "text": prompt},
            {"type": "text", "text": examples},
        ],
        "output_config": {"effort": EFFORT},
        "messages": [{"role": "user", "content": user_message}],
    }


# --------------------------------------------------------------------------
# הפלט
# --------------------------------------------------------------------------


def extract_text(response: Any) -> str:
    """הטקסט שהמודל כתב. תשובה שלא הסתיימה כרגיל היא כשל, גם אם יש בה טקסט.

    ``stop_reason`` נבדק לפני התוכן: בסירוב (``refusal``) התוכן ריק או חלקי
    (https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback), וב-``max_tokens``
    הפואמה נקטעה באמצע. בלוקים שאינם ``text`` (למשל ``thinking``) אינם חלק מהפואמה.
    """
    if not isinstance(response, dict):
        raise PoemError(f"התשובה מ-Anthropic אינה אובייקט JSON ({type(response).__name__})")
    stop_reason = response.get("stop_reason")
    if stop_reason == "refusal":
        details = response.get("stop_details")
        category = details.get("category") if isinstance(details, dict) else None
        explanation = details.get("explanation") if isinstance(details, dict) else None
        raise PoemError(f"המודל סירב לבקשה (category={category!r}, explanation={explanation!r})")
    if stop_reason != "end_turn":
        raise PoemError(f"התשובה לא הסתיימה כרגיל (stop_reason={stop_reason!r})")
    content = response.get("content")
    if not isinstance(content, list):
        raise PoemError("בתשובה אין רשימת content")
    return "".join(
        block["text"]
        for block in content
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    )


def tidy_poem(text: str) -> List[str]:
    """שורות הפואמה, בלי code fences ובלי שורות ריקות.

    שורה ריקה יורדת גם מאמצע הפואמה, ולא רק מהקצוות: בתוך ``<div>`` היא סוגרת את בלוק ה-HTML
    ב-GitHub, וכל מה שאחריה מתפרש כ-Markdown. פלט ריק, או ארוך מ-``MAX_POEM_LINES`` שורות, הוא
    תשובה שהשתבשה ולא מתפרסם.
    """
    lines = [line.strip() for line in text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if len(lines) >= 2 and _FENCE_RE.fullmatch(lines[0]) and _FENCE_RE.fullmatch(lines[-1]):
        lines = lines[1:-1]
    lines = [line for line in lines if line]
    if not lines:
        raise PoemError("המודל לא החזיר טקסט")
    if len(lines) > MAX_POEM_LINES:
        raise PoemError(f"המודל החזיר {len(lines)} שורות, יותר מ-{MAX_POEM_LINES}; זו לא פואמה")
    return lines


def _reads_left_to_right(line: str) -> bool:
    """שורה שיש בה אות משמאל לימין ואין בה אף אות מימין לשמאל, כמו ``CodeKeeper forever 💫``.

    בתוך ``<div dir="rtl">`` תו ניטרלי בקצה שורה כזו — אימוג'י או סימן פיסוק — מקבל את הכיוון של
    הבלוק, ולכן ה-💫 של החתימה מוצג משמאל לטקסט ולא אחריו. שורה שיש בה עברית נשארת בכיוון של
    הבלוק, גם כשהיא מתחילה באנגלית (``Claude Code מקבל הוראות חיבור משלו.``).
    """
    classes = {unicodedata.bidirectional(char) for char in line}
    return "L" in classes and not classes & _RTL_BIDI_CLASSES


def _line_html(line: str) -> str:
    """שורה אחת של הפואמה, כ-HTML. שורה משמאל לימין נעטפת ב-``<span dir="ltr">``.

    ``span`` ולא ``<bdi>``: ``<bdi>`` אינו ברשימת התגיות ש-sanitizer של GitHub משאיר (``html-pipeline``,
    ``sanitization_filter.rb``), ו-``span`` ותכונת ``dir`` כן. ``dir`` עושה את ה-``span`` ל-isolate
    (תקן HTML, "Rendering" ← "Bidirectional text": ``[dir=ltr i] { unicode-bidi: isolate; }``), ולכן
    האימוג'י נשאר בכיוון של השורה. ולא תו שליטה בלתי נראה כמו LRM, שהיה נכנס לטקסט של התגובה
    (``H1`` ב-amir-bug-patterns).
    """
    escaped = html.escape(line, quote=False)
    return f'<span dir="ltr">{escaped}</span>' if _reads_left_to_right(line) else escaped


def format_comment(lines: List[str]) -> str:
    """גוף התגובה: הסימון, ובלוק ``<div dir="rtl">`` שבו כל שורה נשברת ב-``<br>``.

    ב-Markdown של GitHub מעבר שורה רגיל אינו שובר שורה, ובלי ``dir="rtl"`` שורה שמתחילה באנגלית
    מוצגת משמאל לימין. הטקסט עובר ``html.escape``, כי בתוך בלוק HTML הוא מוצג כמו שהוא נכתב, ו-``<``
    מהמודל היה נקרא כתגית. שורה בלי עברית בכלל מקבלת כיוון משלה (``_line_html``).
    """
    body = "<br>\n".join(_line_html(line) for line in lines)
    return f'{MARKER}\n<div dir="rtl">\n{body}\n</div>\n'


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def _redact(text: str, secrets: Tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def _error_body(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read()
    except (OSError, http.client.HTTPException) as read_exc:
        # קוד הסטטוס כבר בהודעה שנבנית מהחריגה, ולכן כשל בקריאת הגוף רק מקצר אותה.
        return f"(גוף התשובה לא נקרא: {type(read_exc).__name__})"
    return raw[:1000].decode("utf-8", "replace")


def http_json(
    method: str,
    url: str,
    headers: Dict[str, str],
    payload: Optional[Dict[str, Any]],
    timeout: float,
    secrets: Tuple[str, ...],
) -> Any:
    """בקשה אחת ותשובת JSON שלה. כל כשל הופך ל-``PoemError`` עם הודעה שאין בה סוד.

    כל קריאת רשת בסקריפט עוברת כאן, ולכן הטסטים מחליפים את הפונקציה הזו בלבד.
    """
    label = f"{method} {urllib.parse.urlsplit(url).path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        # B310 של bandit מזהיר מסכמה שאינה http(s). כאן הכתובת נבנית רק מ-ANTHROPIC_URL ומ-GITHUB_API.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = _redact(_error_body(exc), secrets)
        raise PoemError(f"{label}: HTTP {exc.code}: {detail}") from None
    except (OSError, http.client.HTTPException) as exc:
        # ``URLError`` ו-``TimeoutError`` הם ``OSError``; ``IncompleteRead`` הוא ``HTTPException``.
        raise PoemError(f"{label}: כשל רשת: {_redact(str(exc), secrets)}") from None
    try:
        return json.loads(raw)
    except ValueError:
        raise PoemError(f"{label}: התשובה אינה JSON") from None


class GitHub:
    """הקריאות ל-REST API של GitHub שהסקריפט צריך, על ריפו אחד."""

    def __init__(self, repo: str, token: str) -> None:
        self.repo = repo
        self.token = token
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": "codebot-pr-poem",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _call(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{GITHUB_API}/repos/{self.repo}{path}"
        if payload is not None:
            headers = {**self.headers, "Content-Type": "application/json"}
        else:
            headers = self.headers
        return http_json(method, url, headers, payload, GITHUB_TIMEOUT, (self.token,))

    def get_pull(self, number: int) -> Dict[str, Any]:
        pull = self._call("GET", f"/pulls/{number}")
        if not isinstance(pull, dict):
            raise PoemError(f"ה-PR #{number}: התשובה אינה אובייקט")
        return pull

    def list_file_names(self, number: int, limit: int) -> List[str]:
        files = self._call("GET", f"/pulls/{number}/files?per_page={limit}")
        if not isinstance(files, list):
            raise PoemError(f"ה-PR #{number}: רשימת הקבצים אינה רשימה")
        names = [item.get("filename") for item in files if isinstance(item, dict)]
        return [name for name in names if isinstance(name, str)][:limit]

    def has_poem(self, number: int) -> bool:
        """האם יש על ה-PR תגובה עם ``MARKER``. עובר על כל העמודים, לא רק על הראשון."""
        page = 1
        while True:
            comments = self._call("GET", f"/issues/{number}/comments?per_page={COMMENTS_PER_PAGE}&page={page}")
            if not isinstance(comments, list):
                raise PoemError(f"ה-PR #{number}: רשימת התגובות אינה רשימה")
            for comment in comments:
                body = comment.get("body") if isinstance(comment, dict) else None
                if isinstance(body, str) and MARKER in body:
                    return True
            if len(comments) < COMMENTS_PER_PAGE:
                return False
            page += 1

    def post_comment(self, number: int, body: str) -> str:
        """מפרסם תגובה ומחזיר את הכתובת שלה. ההצלחה נקבעת לפי מה שחזר, לא לפי מה שנשלח."""
        created = self._call("POST", f"/issues/{number}/comments", {"body": body})
        if not isinstance(created, dict) or not isinstance(created.get("body"), str) or MARKER not in created["body"]:
            raise PoemError("GitHub לא החזיר את התגובה שפורסמה; בדקו את ה-PR לפני הרצה חוזרת")
        url = created.get("html_url")
        return url if isinstance(url, str) else "(בלי כתובת)"


def anthropic_headers(api_key: str) -> Dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


def call_anthropic(api_key: str, request: Dict[str, Any]) -> Any:
    return http_json("POST", ANTHROPIC_URL, anthropic_headers(api_key), request, ANTHROPIC_TIMEOUT, (api_key,))


# --------------------------------------------------------------------------
# ההרצה
# --------------------------------------------------------------------------


def _annotate(level: str, message: str) -> None:
    """שורת workflow command של Actions (``::warning::`` וכו').

    ה-escaping הוא של ``escapeData`` ב-actions/toolkit (``packages/core/src/command.ts``), כדי
    שהודעה עם שורות או עם ``%`` תוצג שלמה.
    """
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{level}::{escaped}", flush=True)


def _pr_number(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"מספר PR לא תקין: {value!r}") from None
    if number <= 0:
        raise argparse.ArgumentTypeError(f"מספר PR לא תקין: {value!r}")
    return number


def _is_fork(pull: Dict[str, Any]) -> bool:
    """האם ה-head יושב בריפו אחר מה-base. ``head.repo`` חסר נחשב fork — אין ממה לקבוע שאינו."""
    head = pull.get("head")
    base = pull.get("base")
    head_repo = head.get("repo") if isinstance(head, dict) else None
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_name = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    base_name = base_repo.get("full_name") if isinstance(base_repo, dict) else None
    return not isinstance(head_name, str) or head_name != base_name


def run(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="פואמה קצרה על PR, כתגובה על ה-PR.")
    parser.add_argument("--pr", type=_pr_number, required=True, help="מספר ה-PR")
    parser.add_argument("--repo", default=None, help="owner/name; ברירת המחדל היא GITHUB_REPOSITORY")
    parser.add_argument("--dry-run", action="store_true", help="מדפיס את הבקשה בלי לקרוא ל-API ובלי לפרסם")
    args = parser.parse_args(argv)

    repo = (args.repo or os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if not _REPO_RE.fullmatch(repo):
        raise PoemError(f"ריפו לא תקין: {repo!r} (צריך owner/name, ב---repo או ב-GITHUB_REPOSITORY)")
    # ``vars.POEM_MODEL`` שלא הוגדר מגיע ל-env כמחרוזת ריקה, ולכן ריק ולא רק חסר נופל לברירת המחדל.
    model = (os.environ.get("POEM_MODEL") or "").strip() or DEFAULT_MODEL
    api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()

    if not args.dry_run:
        if not api_key:
            # ב-PR של Dependabot ה-secret לא מועבר גם כשהוא מוגדר, ולכן ההודעה נוקבת בשתי האפשרויות.
            _annotate(
                "warning",
                "ANTHROPIC_API_KEY לא הגיע להרצה (לא מוגדר ב-secrets של הריפו, או PR של Dependabot), "
                "ולכן לא נכתבה פואמה.",
            )
            return 0
        if not token:
            raise PoemError("GITHUB_TOKEN חסר, ובלעדיו אי אפשר לפרסם תגובה")

    def stop(reason: str) -> bool:
        """הרצה אמיתית נעצרת כאן; ב-dry-run זו רק הערה, וההדפסה ממשיכה."""
        if args.dry_run:
            print(f"[dry-run] הרצה אמיתית הייתה נעצרת כאן: {reason}", file=sys.stderr)
            return False
        _annotate("notice", reason)
        return True

    github = GitHub(repo, token)
    pull = github.get_pull(args.pr)
    if _is_fork(pull) and stop(f"ה-PR #{args.pr} מגיע מ-fork, ולכן אין פואמה."):
        return 0
    if github.has_poem(args.pr) and stop(f"על ה-PR #{args.pr} כבר יש פואמה ({MARKER})."):
        return 0

    raw_title = pull.get("title")
    title = raw_title if isinstance(raw_title, str) else ""
    changed = pull.get("changed_files")
    files = github.list_file_names(args.pr, MAX_FILES)
    # ``bool`` הוא ``int`` בפייתון, וספירה שאינה מספר שלם נופלת לאורך הרשימה.
    total_files = changed if isinstance(changed, int) and not isinstance(changed, bool) else len(files)
    request = build_request(
        model,
        PROMPT_PATH.read_text(encoding="utf-8"),
        EXAMPLES_PATH.read_text(encoding="utf-8"),
        build_user_message(title, clean_description(pull.get("body")), files, total_files),
    )

    if args.dry_run:
        shown_headers = {k: v for k, v in anthropic_headers(api_key).items() if k != "x-api-key"}
        print(f"POST {ANTHROPIC_URL}")
        print(json.dumps(shown_headers, ensure_ascii=False, indent=2))
        print(json.dumps(request, ensure_ascii=False, indent=2))
        return 0

    response = call_anthropic(api_key, request)
    lines = tidy_poem(extract_text(response))
    usage = response.get("usage") if isinstance(response, dict) else None
    print(f"model={response.get('model')!r} usage={json.dumps(usage) if isinstance(usage, dict) else None}")
    url = github.post_comment(args.pr, format_comment(lines))
    print(f"הפואמה פורסמה: {url}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    try:
        return run(argv)
    except PoemError as exc:
        _annotate("error", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
