"""אימות מול GitHub בלי לשמור את הטוקן בדיסק, וניקוי מראות שנוצרו לפני #3480.

עד #3480 הטוקן הוזרק ל-URL (``https://oauth2:<token>@github.com/...``), ו-git שומר
את ה-URL שה-clone נעשה ממנו ב-``remote.origin.url`` בקובץ ``config`` של המראה — בטקסט
גלוי, על הדיסק של הוובאפ ושל שירות ה-MCP ובצילומי הדיסק של Render. git גם מעביר את
ה-URL המלא כארגומנט ל-``git-remote-https``, כך שהוא גלוי ברשימת התהליכים בכל clone
ו-fetch. מאז, ה-URL שנשמר נקי, והטוקן עובר לכל פקודת רשת בנפרד כ**כותרת**, דרך משתני
הסביבה ``GIT_CONFIG_COUNT`` / ``GIT_CONFIG_KEY_<n>`` / ``GIT_CONFIG_VALUE_<n>`` (git
2.31 ומעלה, ``Documentation/git-config.txt``) — לא דרך ``git -c``, שמציב את הערך
בשורת הפקודה. התיעוד של git עצמו מצביע על ``http.extraHeader`` כמקרה שבו העברה דרך
הסביבה עדיפה (``Documentation/git.txt``, ``--config-env``).

**מה כאן ומה ב-``git_mirror_service``.** כאן: הקבועים, בניית הסביבה של פקודת רשת,
זיהוי "השרת דרש הזדהות", הניקוי של מראה אחת (``ensure_clean_remote``) והמעבר על
כל המראות. ב-``GitMirrorService`` נשארים רק בחירת הטוקן לפי בעלים
(``_token_and_source_for_url``) והרצת clone/fetch (``_run_network_git``), כי הם חלק
מהרצת הפקודות שהשירות כבר מחזיק. כל מה שכאן מריץ git דרך
``GitMirrorService._run_git_command`` — אותה רשימת פקודות מותרות ואותו ניקוי פלט.

**מתי המעבר על כל המראות רץ.** בעליית כל שירות, מנקודת הכניסה שלו ולא בייבוא:
בשירות ה-MCP מה-lifespan של האפליקציה (``attach_credential_sweep`` ב-
``mcp_server/repo_autosync.py``), ובוובאפ מ-``scripts/start_webapp.sh`` דרך
``scripts/sweep_mirror_credentials.py``.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:  # pragma: no cover - type-only, אין ייבוא מעגלי בזמן ריצה
    from services.git_mirror_service import GitMirrorService

logger = logging.getLogger(__name__)

# **המקור (origin) של GitHub.** ממנו נגזרים גם הבדיקה של כתובת ריפו
# (``GitMirrorService._validate_repo_url``), גם חילוץ הבעלים, וגם המפתח שאליו
# הכותרת ממוקדת — git משווה את המפתח לכתובת לפי scheme, host ו-port
# (``Documentation/config/http.txt``, ``http.<url>.*``), ולכן הכותרת לא נשלחת לשום
# מארח אחר. נקרא בזמן קריאה ולא מועתק, כך שהטסטים מחליפים אותו כאן כדי להריץ את
# ``init_mirror``/``fetch_updates`` האמיתיים מול שרת מקומי.
GITHUB_HTTPS_ORIGIN = "https://github.com"

# שם המשתמש שנשלח עם הטוקן. אותו credential בדיוק שה-URL נשא עד #3480.
GIT_AUTH_USERNAME = "oauth2"

# ``transfer.credentialsInUrl=die`` (git 2.37 ומעלה): מראה ששוב נושאת
# credentials ב-URL נכשלת **לפני** בקשת רשת, וההודעה של git כבר מסתירה את
# הסיסמה (``<redacted>``). זה השומר שהופך "מראה שלא נוקתה" לשגיאה עם שם,
# במקום fetch שקט עם הטוקן השמור.
CREDENTIALS_IN_URL_GUARD: Tuple[str, str] = ("transfer.credentialsInUrl", "die")

# הודעות git כשהשרת דורש הזדהות ואין מה לתת לו. נאכפות באנגלית דרך
# ``LC_ALL=C`` בסביבת פקודות הרשת. ``could not read Username`` נבדק מול
# github.com עצמו, על ריפו פרטי/לא קיים בלי טוקן (git 2.43, אוקטובר 2026).
AUTH_REQUIRED_MARKERS = (
    "could not read username",
    "terminal prompts disabled",
    "authentication failed",
)

# ``git remote`` מותר ב-``_run_git_command`` **רק** בשתי הצורות האלה, ובדיוק
# במבנה הזה. כל השאר (``add``, ``remove``, ``set-url --push``...) נדחה.
REMOTE_GET_URL: Tuple[str, str, str] = ("remote", "get-url", "origin")
REMOTE_SET_URL: Tuple[str, str, str] = ("remote", "set-url", "origin")


def network_env(token: Optional[str]) -> Dict[str, str]:
    """הסביבה של פקודת רשת (clone/fetch): בלי הנחיות מסוף, עם השומר, ועם הכותרת אם יש טוקן.

    הכותרת היא אותו credential בדיוק שה-URL נשא עד #3480 (``oauth2:<token>``
    ב-Basic), ממוקדת ל-``GITHUB_HTTPS_ORIGIN`` בלבד. base64 גם מנטרל כל תו
    בטוקן שהיה שובר את הדקדוק של כותרת HTTP.
    """
    pairs: List[Tuple[str, str]] = [CREDENTIALS_IN_URL_GUARD]
    if token:
        basic = base64.b64encode(f"{GIT_AUTH_USERNAME}:{token}".encode("utf-8")).decode("ascii")
        pairs.append((f"http.{GITHUB_HTTPS_ORIGIN.rstrip('/')}/.extraHeader", f"Authorization: Basic {basic}"))
    env: Dict[str, str] = {
        "GIT_TERMINAL_PROMPT": "0",
        # הודעות git באנגלית: ``needs_auth`` ו-``_classify_git_error`` מזהים אותן לפי הטקסט
        "LC_ALL": "C",
        "GIT_CONFIG_COUNT": str(len(pairs)),
    }
    for i, (key, value) in enumerate(pairs):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    return env


def needs_auth(stderr: str) -> bool:
    """האם git נכשל כי השרת דרש הזדהות (ריפו פרטי, או טוקן שלא התקבל)."""
    text = (stderr or "").lower()
    return any(marker in text for marker in AUTH_REQUIRED_MARKERS)


def strip_userinfo(url: str) -> Tuple[Optional[str], bool]:
    """(ה-URL בלי ``user:pass@``, האם היה שם userinfo). URL של SSH מוחזר כמות שהוא.

    URL ש-``urlsplit`` אינו מצליח לפרק (למשל ``https://[::1/x`` — "Invalid IPv6
    URL", נמדד) מחזיר ``None`` במקום להפיל את הקורא: מראה עם URL כזה נספרת ככשל
    עם סיבה, והמעבר ממשיך לשאר המראות. ``had`` במקרה הזה הוא ההערכה השמרנית —
    יש ``@`` במחרוזת.
    """
    u = (url or "").strip()
    if "://" not in u:
        return u, False
    try:
        parts = urlsplit(u)
    except ValueError:
        return None, "@" in u
    if "@" not in parts.netloc:
        return u, False
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment)), True


def _failed(reason: str, had_credentials: bool) -> Dict[str, Any]:
    return {"status": "failed", "url": None, "had_credentials": had_credentials, "reason": reason}


def ensure_clean_remote(service: "GitMirrorService", repo_name: str) -> Dict[str, Any]:
    """מוודא ש-``remote.origin.url`` של המראה אינו נושא credentials, ומנקה אם כן.

    מחזיר ``{"status", "url", "had_credentials", "reason"}``:

    - ``clean`` — ה-URL כבר נקי.
    - ``cleaned`` — היה בו userinfo, ``set-url`` רץ, **והקריאה החוזרת** מראה URL
      נקי וזהה למה שנכתב. קוד היציאה של ``set-url`` לבדו אינו ראיה.
    - ``failed`` — אחד השלבים לא אומת; ``reason`` אומר איזה. ``url`` הוא ``None``.

    ה-URL נקרא דרך ``_run_git_command``, שמעביר את הפלט ב-``_sanitize_output``,
    ולכן הטוקן אינו מגיע לשום דבר שהפונקציה מחזירה או רושמת.
    """
    repo_name = str(repo_name or "").strip()
    if not service._validate_repo_name(repo_name):
        return _failed("invalid_repo_name", False)
    repo_path = service._get_repo_path(repo_name)

    # ``GIT_DIR`` מצמיד את הפקודה לתיקיית המראה. בלעדיו, תיקייה שאינה ריפו
    # גורמת ל-git לטפס לתיקיות שמעליה — ו-``set-url`` היה כותב ל-config של
    # ריפו אחר לגמרי (נמדד: "not a git repository (or any of the parent
    # directories)"). **נתיב מוחלט:** ``GIT_DIR`` יחסי נפתר מה-cwd של git, שהוא
    # המראה עצמה — ``base_path`` יחסי היה מצביע על ``<מראה>/<base>/<מראה>``
    # ונכשל (נמדד: "not a git repository: 'mirrors/a.git'").
    pinned = {"GIT_DIR": str(repo_path.resolve())}

    def run(cmd: List[str]):
        return service._run_git_command(cmd, cwd=repo_path, timeout=10, extra_env=pinned)

    read = run(["git", *REMOTE_GET_URL])
    if not read.success:
        return _failed("get_url_failed", False)
    clean_url, had_credentials = strip_userinfo(read.stdout)
    if clean_url is None:
        return _failed("unparseable_url", had_credentials)
    if not service._validate_repo_url(clean_url):
        return _failed("unexpected_url", had_credentials)
    if not had_credentials:
        return {"status": "clean", "url": clean_url, "had_credentials": False, "reason": None}

    if not run(["git", *REMOTE_SET_URL, clean_url]).success:
        return _failed("set_url_failed", True)
    reread = run(["git", *REMOTE_GET_URL])
    if not reread.success:
        return _failed("reread_failed", True)
    now_url, still_has = strip_userinfo(reread.stdout)
    if still_has or now_url != clean_url:
        return _failed("still_not_clean", True)
    return {"status": "cleaned", "url": clean_url, "had_credentials": True, "reason": None}


def scrub_stored_credentials(service: "GitMirrorService") -> Dict[str, Any]:
    """מעבר על **כל** המראות של השירות: מנקה credentials מ-``remote.origin.url``, ושורת לוג אחת.

    רץ בעליית כל שירות, כי מראה שאינה נמשכת לעולם לא מגיעה לניקוי שב-
    ``fetch_updates``, וצילום דיסק משוחזר מחזיר config ישן. כל תיקייה ``*.git``
    נבדקת, גם כזו שאינה מראה תקינה — היא תיספר כ-``failed`` עם הסיבה, לא תדולג
    בשקט. **השורה מאמתת שהמראות נקיות רק כש-``failed=0``**: מראה שנכשלה עדיין
    עלולה להחזיק את הטוקן, וה-fetch שלה נחסם עד שהניקוי יצליח.

    ``sources``: לכל מראה, מאיפה יגיע הטוקן שלה אם הריפו ידרוש הזדהות —
    ``map``/``global``/``explicit``/``none``, או ``unknown`` כשה-URL לא ידוע.
    """
    stats = {"checked": 0, "had_credentials": 0, "cleaned": 0, "failed": 0}
    sources: Dict[str, str] = {}
    for path in sorted(service.base_path.glob("*.git")):
        if not path.is_dir():
            continue
        name = path.name[: -len(".git")]
        stats["checked"] += 1
        res = ensure_clean_remote(service, name)
        if res["had_credentials"]:
            stats["had_credentials"] += 1
        if res["status"] == "cleaned":
            stats["cleaned"] += 1
        elif res["status"] == "failed":
            stats["failed"] += 1
            logger.warning("mirror credential sweep: %s failed (%s)", name, res["reason"])
        sources[name] = service._token_and_source_for_url(res["url"])[1] if res["url"] else "unknown"
    logger.info(
        "mirror credential sweep: checked=%d had_credentials=%d cleaned=%d failed=%d sources=%s",
        stats["checked"],
        stats["had_credentials"],
        stats["cleaned"],
        stats["failed"],
        json.dumps(sources, sort_keys=True),
    )
    return {**stats, "sources": sources}


def sweep_stored_credentials() -> Optional[Dict[str, Any]]:
    """ניקוי credentials מכל המראות בדיסק של השירות הזה. ``None`` אם אין תיקיית מראות.

    **לא יוצר את התיקייה.** ``GitMirrorService()`` עושה ``mkdir``, וכאן אין סיבה:
    כשאין תיקיית מראות בדיסק, אין מה לנקות.
    """
    from services.git_mirror_service import _default_mirror_base_path, get_mirror_service

    base = _default_mirror_base_path()
    if not base.is_dir():
        logger.info("mirror credential sweep: no mirror directory at %s, nothing to check", base)
        return None
    return scrub_stored_credentials(get_mirror_service())


def start_credential_sweep() -> threading.Thread:
    """מריץ את ``sweep_stored_credentials`` פעם אחת ברקע. נקרא מעליית השירות, לא מייבוא."""

    def _run() -> None:
        try:
            sweep_stored_credentials()
        except Exception:
            # thread רקע: חריגה כאן לא מגיעה לאף קורא, ולכן נרשמת עם traceback
            logger.warning("mirror credential sweep failed", exc_info=True)

    thread = threading.Thread(target=_run, daemon=True, name="mirror-credential-sweep")
    thread.start()
    return thread
