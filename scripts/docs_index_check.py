"""הבדיקה שאחרי פריסת אתר התיעוד: האם אינדקס החיפוש בתיעוד הגיע לקומיט שנפרס — ואם לא, בקשת המעבר נשלחת שוב.

**למה.** האינדקס מתעדכן כשה-webhook של ``deployment_status`` מגיע לוובאפ (``handle_deployment_status_event`` ב-
``webapp/routes/webhooks.py``). GitHub שולח אותו פעם אחת. מיזוג ל-``main`` פורס גם את האתר וגם את הוובאפ, בהפרש
של דקות, וכשה-webhook מגיע בזמן שהוובאפ עולה מחדש הוא הולך לאיבוד בלי שום עקבה: ב-13.11.2026 הפריסה של
``87fa366`` לא הגיעה לוובאפ, והאינדקס נשאר מאחור שעתיים, עד ש"בדוק עכשיו" ידני. שום התראה לא נשלחה, כי כל
ההתראות של האינדקס נשלחות מתוך מעבר — ומעבר שלא רץ לא מדווח. לכן הבדיקה רצה מבחוץ, ב-CI, אחרי הפריסה.

**מה היא עושה.** כל :data:`POLL_SECONDS` היא שואלת את הוובאפ מה מצב האינדקס לקומיט (``/api/webhooks/docs-index/status``,
שמחזיר את ``status_for_deploy_check`` ב-``services/docs_index_service.py``), ומחליטה (:func:`decide`):

* האינדקס בקומיט ← הצלחה.
* מעבר מחזיק ב-lease ← ממתינים לו.
* האינדקס מחכה לאישור על התוכנית של הקומיט ← התראה מיד: רק האדמין יכול להמשיך.
* אין מעבר חי ← אחרי :data:`RESEND_GRACE_SECONDS`, שבהן ה-webhook של GitHub עוד יכול להגיע, היא שולחת שוב את
  בקשת המעבר (``/api/webhooks/docs-index/pass``) — עד :data:`MAX_RESENDS` פעמים, ולפחות
  :data:`RESEND_INTERVAL_SECONDS` בין שתיים. כשאין עוד ניסיונות והמעבר האחרון נגמר בלי להגיע לקומיט ← התראה.
* :data:`DEADLINE_SECONDS` עברו ← התראה, עם המצב האחרון שנקרא.

**הסיום.** 0 — האינדקס הגיע לקומיט. 1 — לא הגיע, או שהבדיקה לא יכלה לרוץ; ההודעה נכתבת ל-``$GITHUB_OUTPUT``
בשם ``message``, והצעד שאחריו ב-workflow שולח אותה לטלגרם, דרך הסודות של ה-CI ולא דרך הוובאפ.

**סודות.** ``CODEBOT_WEBHOOK_SECRET`` — אותו ערך כמו ``GITHUB_WEBHOOK_SECRET`` בוובאפ — משמש רק לחתימת הגוף, בצורה
של GitHub (``verify_github_signature``), ואינו מודפס ואינו נכנס לשום הודעה. כל מה שהסקריפט מדפיס הולך ליומן של
ריצה בריפו ציבורי, ולכן הוא קומיטים, סטטוסים וקודים בלבד — ובשביל זה הוובאפ לא מחזיר את ``detail`` של המעבר.

**הרצה מקומית:** עם ``WEBAPP_URL`` ו-``CODEBOT_WEBHOOK_SECRET`` בסביבה —
``python scripts/docs_index_check.py --commit <sha>``.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
# הסקריפט רץ לבדו (``python scripts/docs_index_check.py``), ואז ``sys.path[0]`` הוא ``scripts/`` ולא שורש הריפו.
# שני המודולים שמיובאים מהריפו טהורים — בלי תלויות מחוץ לספרייה הסטנדרטית — ולכן הג'וב ב-CI לא מתקין כלום.
sys.path.insert(0, str(ROOT))

import webapp_url  # noqa: E402
from services import docs_search_contract as contract  # noqa: E402

# ---------------------------------------------------------------------------
# מספרים
# ---------------------------------------------------------------------------

#: כל כמה שניות שואלים את הוובאפ.
POLL_SECONDS = 20

#: תקרה לכל בקשה בודדת לוובאפ — חיבור וקריאה (``urlopen(timeout=...)``).
REQUEST_TIMEOUT_SECONDS = 15

#: כמה זמן מתחילת הבדיקה לא שולחים שוב, כדי שהמעבר של ה-webhook של GitHub יספיק להתחיל ולתפוס את ה-lease.
RESEND_GRACE_SECONDS = 60

#: הזמן המינימלי בין שתי שליחות חוזרות שהתקבלו — שתקלה חולפת בוובאפ לא תשרוף את כל הניסיונות בדקה אחת.
RESEND_INTERVAL_SECONDS = 120

#: כמה פעמים לכל היותר שולחים שוב את בקשת המעבר.
MAX_RESENDS = 3

#: כמה זמן לכל היותר ממתינים לאינדקס. במקרה הגרוע ה-webhook הביא מעבר שמת ולא שחרר את ה-lease, ה-lease פג
#: (``LEASE_SECONDS``), והמעבר ששולחים אחריו רץ עד התקרה שלו (``PASS_DEADLINE_SECONDS``).
#: ``tests/test_docs_index_check.py`` בודק שהמספר הזה מכסה את שניהם, ושה-``timeout-minutes`` של הג'וב
#: ב-``documentation.yml`` מכסה אותו.
DEADLINE_SECONDS = 30 * 60

#: התקרה של גוף תשובה מהוובאפ. התשובות הן מסמך JSON קטן; יותר מזה אינו תשובה של הנתיבים האלה.
MAX_ANSWER_BYTES = 64 * 1024

#: התקרה של מחרוזת בתשובה (סטטוס, קוד, טריגר). הן קודים קצרים; ארוכה מזה היא תשובה פגומה, ולא נכנסת להודעה.
MAX_FIELD_CHARS = 100

#: הסיבות שמעבר עוצר בגללן לאישור, כמו שהן נכתבות ל-``approval.reason`` (``APPROVAL_FIRST_FILL``,
#: ``APPROVAL_OVER_THRESHOLD`` ו-``CODE_APPROVAL_MISMATCH`` ב-``services/docs_index_service.py``). המודול ההוא
#: מושך את לקוח ההטמעות ואת מונגו, ולכן הקודים כתובים כאן שוב; ``tests/test_docs_index_check.py`` משווה ביניהם.
APPROVAL_REASONS: Dict[str, str] = {
    "first_fill_or_model_change": "מילוי ראשון או החלפת מודל",
    "over_threshold": "יותר נתחים להטמעה מהתקרה",
    "plan_changed": "התוכנית השתנתה מאז שאושרה",
}

#: מה ש-``request_pass`` מחזיר כשהבקשה התקבלה (``REQUEST_STARTED`` ו-``REQUEST_QUEUED``); גם כאן ההשוואה בטסט.
ACCEPTED_REQUESTS = frozenset({"started", "queued"})

SECRET_ENV = "CODEBOT_WEBHOOK_SECRET"
STATUS_PATH = "/api/webhooks/docs-index/status"
PASS_PATH = "/api/webhooks/docs-index/pass"
ADMIN_PATH = "/admin/docs-index"


# ---------------------------------------------------------------------------
# התשובה של הוובאפ
# ---------------------------------------------------------------------------


class InvalidAnswer(ValueError):
    """תשובה של הוובאפ שאינה בצורה של ``status_for_deploy_check``."""


@dataclass(frozen=True)
class IndexStatus:
    """המצב שנקרא מהוובאפ, אחרי בדיקת הצורה."""

    indexed: bool
    indexed_commit: Optional[str]
    pass_alive: bool
    run_status: Optional[str]
    run_code: Optional[str]
    run_trigger: Optional[str]
    run_source_commit: Optional[str]
    approval_commit: Optional[str]
    approval_reason: Optional[str]
    approval_chunks: Optional[int]


def _optional_text(value: Any, where: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_FIELD_CHARS:
        raise InvalidAnswer(f"{where} is not a short string")
    return value


def _optional_sha(value: Any, where: str) -> Optional[str]:
    if value is None:
        return None
    if not contract.is_commit_sha(value):
        raise InvalidAnswer(f"{where} is not a commit sha")
    return value


def parse_status(answer: Any, commit: str) -> IndexStatus:
    """התשובה של ``/status``, אחרי בדיקה של כל שדה שהסקריפט קורא. כל סטייה היא :class:`InvalidAnswer`."""
    if not isinstance(answer, dict):
        raise InvalidAnswer("the answer is not an object")
    if answer.get("commit") != commit:
        raise InvalidAnswer("the answer is about another commit")
    indexed, alive = answer.get("indexed"), answer.get("pass_alive")
    if not isinstance(indexed, bool) or not isinstance(alive, bool):
        raise InvalidAnswer("indexed and pass_alive must be booleans")
    run = answer.get("run")
    if run is not None and not isinstance(run, dict):
        raise InvalidAnswer("run is not an object")
    approval = answer.get("approval")
    if approval is not None and not isinstance(approval, dict):
        raise InvalidAnswer("approval is not an object")
    chunks = approval.get("chunks_to_embed") if approval else None
    # ``bool`` הוא תת-מחלקה של ``int``, ולכן הוא נבדק לחוד.
    if chunks is not None and (isinstance(chunks, bool) or not isinstance(chunks, int) or chunks < 0):
        raise InvalidAnswer("approval.chunks_to_embed is not a count")
    run = run or {}
    return IndexStatus(
        indexed=indexed,
        indexed_commit=_optional_sha(answer.get("indexed_source_commit"), "indexed_source_commit"),
        pass_alive=alive,
        run_status=_optional_text(run.get("status"), "run.status"),
        run_code=_optional_text(run.get("code"), "run.code"),
        run_trigger=_optional_text(run.get("trigger"), "run.trigger"),
        run_source_commit=_optional_sha(run.get("source_commit"), "run.source_commit"),
        approval_commit=_optional_sha(approval.get("source_commit"), "approval.source_commit") if approval else None,
        approval_reason=_optional_text(approval.get("reason"), "approval.reason") if approval else None,
        approval_chunks=chunks,
    )


# ---------------------------------------------------------------------------
# הרשת
# ---------------------------------------------------------------------------


class Unreachable(Exception):
    """הבקשה לא קיבלה תשובת HTTP: חיבור, DNS, timeout, או חיבור שנסגר באמצע."""


@dataclass(frozen=True)
class Reply:
    """תשובת HTTP: הסטטוס, והגוף כ-JSON — או ``None`` כשהוא אינו JSON."""

    status: int
    body: Any


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """הפניה אינה צפויה מהנתיבים האלה, ולכן היא מוחזרת כסטטוס ולא נעקבת. ``redirect_request`` שזורק
    ``HTTPError`` הוא הדרך שהמחלקה עצמה מתעדת ל"לא להמשיך" (``urllib/request.py``)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect())


def sign(body: bytes, secret: str) -> str:
    """החתימה בצורה ש-``verify_github_signature`` בודק: ``sha256=`` ואחריו HMAC-SHA256 של הגוף, ב-hex."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def post_signed(url: str, payload: Dict[str, Any], secret: str) -> Reply:
    """``POST`` של JSON חתום. זורק :class:`Unreachable` כשאין תשובת HTTP; כל סטטוס אחר חוזר ב-:class:`Reply`."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sign(body, secret)},
    )
    try:
        with _OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status, raw = response.status, response.read(MAX_ANSWER_BYTES + 1)
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read(MAX_ANSWER_BYTES + 1)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
        # תת-העץ של "אין תשובה": ``URLError`` (DNS, סירוב חיבור), ``OSError`` (timeout של socket, חיבור שאופס)
        # ו-``HTTPException`` (``IncompleteRead`` ו-``RemoteDisconnected`` של ``http.client``). רק שם המחלקה נכנס
        # להודעה — הכתובת אינה סוד, אבל אין בה צורך.
        raise Unreachable(type(error).__name__) from error
    if len(raw) > MAX_ANSWER_BYTES:
        return Reply(status, None)
    try:
        return Reply(status, json.loads(raw.decode("utf-8")))
    except ValueError:  # JSONDecodeError ו-UnicodeDecodeError הם תת-מחלקות שלו
        return Reply(status, None)


# ---------------------------------------------------------------------------
# ההחלטה
# ---------------------------------------------------------------------------

DONE = "done"
WAIT = "wait"
RESEND = "resend"
ALERT_APPROVAL = "alert_approval"
ALERT_GAVE_UP = "alert_gave_up"


def decide(status: IndexStatus, *, commit: str, elapsed: float, resends: int,
           last_resend_at: Optional[float]) -> str:
    """מה עושים אחרי שנקרא מצב. ``elapsed`` — שניות מתחילת הבדיקה; ``last_resend_at`` — מתי התקבלה השליחה
    החוזרת האחרונה, באותן שניות. הדדליין אינו כאן: הוא חל גם כשלא נקרא מצב בכלל (:func:`run_check`)."""
    if status.indexed:
        return DONE
    # מעבר חי קודם לאישור: מעבר מאושר שרץ עוד לא ניקה את ``approval`` (הוא מתאפס כשהמעבר מתחיל לכתוב).
    if status.pass_alive:
        return WAIT
    if status.approval_commit == commit:
        return ALERT_APPROVAL
    if resends >= MAX_RESENDS:
        return ALERT_GAVE_UP
    if elapsed < RESEND_GRACE_SECONDS:
        return WAIT
    if last_resend_at is not None and elapsed - last_resend_at < RESEND_INTERVAL_SECONDS:
        return WAIT
    return RESEND


# ---------------------------------------------------------------------------
# ההודעות
# ---------------------------------------------------------------------------


def _short(sha: Optional[str]) -> str:
    return sha[:7] if sha else "אין (האינדקס חלקי או ריק)"


def _last_run(status: IndexStatus) -> str:
    if status.run_status is None:
        return "אין מעבר רשום"
    parts = [status.run_status]
    if status.run_code:
        parts.append(status.run_code)
    described = " / ".join(parts)
    details = []
    if status.run_trigger:
        details.append(f"טריגר {status.run_trigger}")
    if status.run_source_commit:
        details.append(f"קרא את {status.run_source_commit[:7]}")
    return f"{described} ({', '.join(details)})" if details else described


def _admin_line() -> str:
    link = webapp_url.webapp_link(ADMIN_PATH)
    return f"עמוד האדמין: {link}" if link else ""


def _join(*lines: str) -> str:
    return "\n".join(line for line in lines if line)


def approval_message(commit: str, status: IndexStatus) -> str:
    reason = APPROVAL_REASONS.get(status.approval_reason or "", status.approval_reason or "סיבה לא ידועה")
    chunks = f", {status.approval_chunks} נתחים להטמעה" if status.approval_chunks is not None else ""
    return _join(
        f"⏸️ אינדקס החיפוש בתיעוד מחכה לאישור אחרי הפריסה של {commit[:7]}: {reason}{chunks}.",
        f"באינדקס עכשיו: {_short(status.indexed_commit)}.",
        _admin_line(),
    )


def gave_up_message(commit: str, status: IndexStatus, resends: int) -> str:
    return _join(
        f"⚠️ אינדקס החיפוש בתיעוד לא התעדכן לפריסה של {commit[:7]}.",
        f"באינדקס עכשיו: {_short(status.indexed_commit)}. המעבר האחרון: {_last_run(status)}.",
        f"בקשת המעבר נשלחה שוב {resends} פעמים, והמעבר האחרון נגמר בלי להגיע לקומיט.",
        _admin_line(),
    )


def timeout_message(commit: str, last_status: Optional[IndexStatus], last_problem: Optional[str],
                    resends: int) -> str:
    minutes = DEADLINE_SECONDS // 60
    if last_status is not None:
        state = f"באינדקס: {_short(last_status.indexed_commit)}. המעבר האחרון: {_last_run(last_status)}."
    else:
        state = "לא התקבל מהוובאפ אף מצב."
    return _join(
        f"⚠️ אינדקס החיפוש בתיעוד לא הגיע לפריסה של {commit[:7]} תוך {minutes} דקות.",
        state,
        f"הבעיה האחרונה בפנייה לוובאפ: {last_problem}." if last_problem else "",
        f"בקשת המעבר נשלחה שוב {resends} פעמים." if resends else "",
        _admin_line(),
    )


def unauthorized_message() -> str:
    return (
        "⚠️ בדיקת אינדקס התיעוד לא רצה: הוובאפ דחה את החתימה (401). "
        f"הסוד {SECRET_ENV} ב-GitHub אינו אותו ערך כמו GITHUB_WEBHOOK_SECRET בוובאפ, או שבוובאפ הוא לא מוגדר."
    )


def refused_message(path: str, status: int) -> str:
    return f"⚠️ בדיקת אינדקס התיעוד לא רצה: הוובאפ דחה את הבקשה ל-{path} ({status}). זה באג בבדיקה או בנתיב."


# ---------------------------------------------------------------------------
# הלולאה
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """התוצאה: ``ok`` — האינדקס הגיע לקומיט; אחרת ``message`` להתראה."""

    ok: bool
    message: Optional[str]
    resends: int
    elapsed: float


Post = Callable[[str, Dict[str, Any], str], Reply]


def run_check(
    commit: str,
    base_url: str,
    secret: str,
    *,
    post: Post = post_signed,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> Outcome:
    """הלולאה כולה, עד הצלחה, התראה או :data:`DEADLINE_SECONDS`. הרשת, השעון וההמתנה מוזרקים, לטסטים."""
    started = clock()
    payload = {"commit": commit}
    resends = 0
    last_resend_at: Optional[float] = None
    last_status: Optional[IndexStatus] = None
    last_problem: Optional[str] = None

    def finish(ok: bool, message: Optional[str] = None) -> Outcome:
        return Outcome(ok=ok, message=message, resends=resends, elapsed=clock() - started)

    while True:
        elapsed = clock() - started
        status: Optional[IndexStatus] = None
        try:
            reply = post(base_url + STATUS_PATH, payload, secret)
        except Unreachable as error:
            last_problem = f"אין תשובה ({error})"
        else:
            if reply.status == 401:
                return finish(False, unauthorized_message())
            if reply.status == 400:
                return finish(False, refused_message(STATUS_PATH, reply.status))
            if reply.status == 200:
                try:
                    status = parse_status(reply.body, commit)
                except InvalidAnswer as error:
                    last_problem = f"תשובה לא תקינה ({error})"
            else:
                # 404 — הוובאפ שרץ עוד לא כולל את הנתיב (הפריסה שלו מאחרת); 5xx — הוא עולה מחדש או שהמסד לא זמין.
                last_problem = f"HTTP {reply.status}"

        if status is not None:
            last_status = status
            log(
                f"[{elapsed:5.0f}s] indexed={status.indexed} index_at={_short(status.indexed_commit)} "
                f"pass_alive={status.pass_alive} last_run={_last_run(status)} resends={resends}"
            )
            action = decide(status, commit=commit, elapsed=elapsed, resends=resends, last_resend_at=last_resend_at)
            if action == DONE:
                return finish(True)
            if action == ALERT_APPROVAL:
                return finish(False, approval_message(commit, status))
            if action == ALERT_GAVE_UP:
                return finish(False, gave_up_message(commit, status, resends))
            if action == RESEND:
                try:
                    reply = post(base_url + PASS_PATH, payload, secret)
                except Unreachable as error:
                    last_problem = f"השליחה החוזרת לא קיבלה תשובה ({error})"
                else:
                    answer = reply.body.get("status") if isinstance(reply.body, dict) else None
                    if reply.status == 401:
                        return finish(False, unauthorized_message())
                    if reply.status == 400:
                        return finish(False, refused_message(PASS_PATH, reply.status))
                    if reply.status == 202 and answer in ACCEPTED_REQUESTS:
                        resends += 1
                        last_resend_at = elapsed
                        log(f"[{elapsed:5.0f}s] the pass request was sent again ({resends}/{MAX_RESENDS}): {answer}")
                    else:
                        last_problem = f"השליחה החוזרת נענתה ב-HTTP {reply.status}"
        else:
            log(f"[{elapsed:5.0f}s] no status: {last_problem}")

        if clock() - started >= DEADLINE_SECONDS:
            return finish(False, timeout_message(commit, last_status, last_problem, resends))
        sleep(POLL_SECONDS)


# ---------------------------------------------------------------------------
# הכניסה
# ---------------------------------------------------------------------------


def write_output(message: str) -> None:
    """``message`` ל-``$GITHUB_OUTPUT``, בתחביר של ערך רב-שורתי (``name<<delimiter``). המפריד אקראי, כדי שאף
    שורה בהודעה לא תהיה זהה לו — זו האזהרה בתיעוד של GitHub (workflow-commands, "Multiline strings")."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    delimiter = f"EOF_{uuid.uuid4().hex}"
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(f"message<<{delimiter}\n{message}\n{delimiter}\n")


def write_summary(line: str) -> None:
    """שורה בסיכום של הריצה ב-GitHub (``$GITHUB_STEP_SUMMARY``), כשהוא קיים."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def _configuration_problem(commit: str) -> Optional[str]:
    """מה חסר כדי שהבדיקה תוכל לרוץ, או ``None``."""
    if not contract.is_commit_sha(commit):
        return "⚠️ בדיקת אינדקס התיעוד לא רצה: הקומיט שהועבר לה אינו sha מלא. זה באג ב-documentation.yml."
    url = webapp_url.webapp_url_status()
    if url.state == webapp_url.STATE_MISSING:
        return (
            "⚠️ בדיקת אינדקס התיעוד לא רצה: המשתנה WEBAPP_URL לא הוגדר ב-GitHub "
            "(Settings ← Secrets and variables ← Actions ← Variables)."
        )
    if url.state != webapp_url.STATE_CONFIGURED:
        return f"⚠️ בדיקת אינדקס התיעוד לא רצה: המשתנה WEBAPP_URL ב-GitHub פגום ({url.problem})."
    if not os.environ.get(SECRET_ENV):
        return (
            f"⚠️ בדיקת אינדקס התיעוד לא רצה: הסוד {SECRET_ENV} לא הוגדר ב-GitHub "
            "(Settings ← Secrets and variables ← Actions ← Secrets). הערך שלו הוא GITHUB_WEBHOOK_SECRET של הוובאפ."
        )
    return None


def main(argv: Optional[list] = None) -> int:
    """נקודת הכניסה. ``argv`` כרשימה, כדי שאפשר יהיה להריץ אותה מטסט."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", required=True, help="ה-sha של הקומיט שהאתר נפרס ממנו (github.sha).")
    args = parser.parse_args(argv)

    problem = _configuration_problem(args.commit)
    if problem is not None:
        print(problem, file=sys.stderr)
        write_output(problem)
        return 1
    try:
        outcome = run_check(args.commit, webapp_url.webapp_base_url(), os.environ[SECRET_ENV])
    except Exception:  # noqa: BLE001 — גבול התוכנית: traceback מלא ביומן, והתראה משלו ולא "האינדקס לא התעדכן"
        traceback.print_exc()
        message = "⚠️ בדיקת אינדקס התיעוד קרסה לפני שהספיקה להחליט. זה באג בבדיקה; הפרטים ביומן של הריצה."
        write_output(message)
        return 1
    if outcome.ok:
        healed = (
            f" אחרי {outcome.resends} שליחות חוזרות של בקשת המעבר — ה-webhook של הפריסה כנראה לא הביא מעבר"
            if outcome.resends else ""
        )
        line = f"✅ אינדקס החיפוש בתיעוד הגיע ל-{args.commit[:7]} תוך {outcome.elapsed:.0f} שניות{healed}."
        print(line)
        write_summary(line)
        return 0
    print(outcome.message, file=sys.stderr)
    write_summary(outcome.message or "")
    write_output(outcome.message or "")
    return 1


if __name__ == "__main__":
    sys.exit(main())
