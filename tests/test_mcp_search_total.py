"""‏``total`` ב-``codekeeper_search_repo`` — המספר שהיה שווה תמיד ל-``count``.

**הבאג שהקובץ הזה שומר עליו.** השדה ``total`` הוחזר כ-``len(results)``
אחרי החיתוך, ולכן ``max_results=3`` נתן ``count: 3, total: 3`` בין אם יש
בריפו שלוש התאמות ובין אם אלפיים. זו אינה רק אי-נוחות: באותו שרת,
``query=`` של ``codekeeper_get_file`` מחזיר בשדה בעל אותו שם את הסך
האמיתי — כלומר סוכן שלמד את המשמעות בכלי אחד מייחס אותה לשני, ומסיק
שמצא את כל המופעים.

**החוזה שנבדק כאן:** אם ``total`` קיים — הוא מדויק. כשהספירה נקטעת אין
``total`` כלל, ובמקומו ``total_at_least`` ו-``truncation_reason``.

**ולמה הבדיקות עוברות דרך הכלי ולא דרך המנוע.** הפער חי בין השכבות:
המנוע עצר מוקדם בכוונה, ``repo_backend`` חישב ``total`` ממה שקיבל, ושתי
ההחלטות נכונות כל אחת לחוד. רק הקריאה המלאה — שרת MCP אמיתי מעל
``RepoBackend`` אמיתי מעל מראת git אמיתית — מראה את התוצאה.

הריפו, המראה וכל קלט/פלט יושבים תחת ``tmp_path`` בלבד.
"""

import json
import shutil
import subprocess

import pytest

pytest.importorskip("mcp")

from services.git_mirror_service import SEARCH_COUNT_CEILING  # noqa: E402

_GIT = shutil.which("git")
requires_git = pytest.mark.skipif(_GIT is None, reason="git is not installed")

_USER = 1

# מחרוזת שלא תופיע בטעות בשום מקום אחר בקורפוס.
_N = "ZQNEEDLE"


def _run(*args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True)


def _lines(needle_count: int, *, filler: str = "plain line") -> str:
    """קובץ עם מספר מופעים ידוע, ושורות רגילות ביניהם.

    השורות שביניהן חשובות: הן מה שהופך ``context_lines`` לבדיקה אמיתית,
    שאם ההקשר היה נספר כהתאמה — המספר היה משתנה.
    """
    out = []
    for i in range(needle_count):
        out.append(f"{filler} {i}a")
        out.append(f"{_N} hit {i}")
        out.append(f"{filler} {i}b")
    return "\n".join(out) + "\n"


def _build(tmp_path, files: dict, monkeypatch):
    """שרת MCP אמיתי מעל ``RepoBackend`` אמיתי מעל מראה אמיתית.

    אותה צורת בנייה כמו ב-``tests/test_mcp_additive_params.py``: ריפו
    עובד תחת ``tmp_path``, ומשם ``clone --mirror`` — זה המבנה שהשירות
    מצפה לו (``<base>/<repo>.git``).
    """
    import mcp_server.auth as auth
    import mcp_server.server as srv
    import services.repo_search_service as rss
    from mcp_server.repo_backend import RepoBackend
    from services.git_mirror_service import GitMirrorService

    work = tmp_path / "work"
    work.mkdir()
    for name, body in files.items():
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    _run(_GIT, "init", "-q", "-b", "main", ".", cwd=work)
    _run(_GIT, "add", "-A", cwd=work)
    _run(
        _GIT, "-c", "user.email=t@t", "-c", "user.name=t",
        "commit", "-qm", "init", cwd=work,
    )
    _run(_GIT, "clone", "-q", "--mirror", str(work), str(tmp_path / "repo.git"), cwd=tmp_path)

    # **המראה מוזרקת דרך המפעל, ולא מוצבת אחרי הבנייה.**
    # ‏``RepoSearchService.__init__`` קורא ל-``get_mirror_service()``, וזה
    # בונה ``GitMirrorService()`` בברירת המחדל — ‏``REPO_MIRROR_PATH`` או
    # ‏``/var/data/repos`` — ועושה לו ``mkdir`` כבר בבנאי. הצבה של
    # ‏``git_service`` אחרי הבנייה מאחרת את המועד: התיקייה כבר נוצרה, וב-CI
    # שרץ בלי הרשאת כתיבה ל-``/var/data`` הבנאי פשוט זורק ``PermissionError``.
    # קיבוע המפעל הוא מה שמונע את הבנייה הזו מלכתחילה.
    mirror = GitMirrorService(base_path=str(tmp_path))
    monkeypatch.setattr(rss, "get_mirror_service", lambda: mirror)
    # חגורה שנייה, לפי כלל ה-IO של הריפו: גם אם מסלול כלשהו כן יבנה מראה
    # בברירת מחדל, היא תיפול תחת ``tmp_path`` ולא על דיסק אמיתי.
    monkeypatch.setenv("REPO_MIRROR_PATH", str(tmp_path / "unused-default"))
    search = rss.RepoSearchService(db=None)

    monkeypatch.setenv("ENVIRONMENT", "production")
    # הזהות מגיעה מהטוקן, והאדמיניות מ-``config.ADMIN_USER_IDS``. הקיבוע
    # הוא על **המקור** ולא על השער, כדי שהשער עצמו ייבדק כמו שהוא — והוא
    # נקרא בכל קריאה ולא נשמר, ולכן זה עובד אחרי שהקונפיג כבר נטען.
    from config import config as _cfg

    monkeypatch.setattr(auth, "current_user_id", lambda ctx=None: _USER)
    monkeypatch.setattr(_cfg, "ADMIN_USER_IDS", [_USER], raising=False)

    mcp = srv.build_mcp(
        object(),
        repo_backend=RepoBackend(db=None, mirror=mirror, search_service=search),
    )
    mcp._request_is_admin = lambda: True
    return mcp


def _payload(result):
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


async def _search(mcp, **arguments):
    arguments.setdefault("repo", "repo")
    arguments.setdefault("query", _N)
    return _payload(await mcp.call_tool("codekeeper_search_repo", arguments))


# ===========================================================================
# 1. ‏``total`` אומר כמה יש, לא כמה הוחזרו
# ===========================================================================


@requires_git
async def test_total_counts_every_match_and_not_the_returned_rows(tmp_path, monkeypatch):
    """הבדיקה המרכזית. שבעה מופעים בקובץ אחד, מבקשים שניים.

    **שבעה באותו קובץ בכוונה.** ``git grep -m`` מגביל את ההתאמות לכל
    קובץ לפי ``max_results``, ולכן בבקשה של שניים הוא מדפיס שתיים בלבד —
    ומי שיסתמך על הזרם הזה לספירה יקבל 2. רק מעבר ספירה בלי המגבלה
    מחזיר 7.
    """
    mcp = _build(tmp_path, {"src/a.py": _lines(7)}, monkeypatch)

    out = await _search(mcp, max_results=2)

    assert out["ok"] is True
    assert out["count"] == 2
    assert out["total"] == 7
    assert out["truncated"] is True
    assert out["truncation_reason"] == "max_results"
    assert "total_at_least" not in out


@requires_git
async def test_total_spans_files(tmp_path, monkeypatch):
    mcp = _build(
        tmp_path,
        {"src/a.py": _lines(3), "src/b.py": _lines(4), "docs/c.md": _lines(5)},
        monkeypatch,
    )

    out = await _search(mcp, max_results=2)

    assert out["count"] == 2
    assert out["total"] == 12


@requires_git
async def test_nothing_truncated_means_an_exact_total_and_no_extra_keys(tmp_path, monkeypatch):
    """תוספתיות: חיפוש צר מחזיר בדיוק את מה שהחזיר קודם.

    ‏``total == count`` כאן אינו הבאג — הוא פשוט האמת, כי כל המופעים
    הוחזרו. מה שנבדק הוא שלא נוספו שדות לתשובה שלמה.
    """
    mcp = _build(tmp_path, {"src/a.py": _lines(3)}, monkeypatch)

    out = await _search(mcp, max_results=50)

    assert out["count"] == 3
    assert out["total"] == 3
    assert out["truncated"] is False
    assert "total_at_least" not in out
    assert "truncation_reason" not in out


@requires_git
async def test_zero_matches_is_a_success_with_total_zero(tmp_path, monkeypatch):
    mcp = _build(tmp_path, {"src/a.py": _lines(3)}, monkeypatch)

    out = await _search(mcp, query="NOTHINGHERE")

    assert out["ok"] is True
    assert out["count"] == 0
    assert out["total"] == 0
    assert out["truncated"] is False


# ===========================================================================
# 2. כשהספירה נקטעת — אין ``total``
# ===========================================================================


@requires_git
async def test_above_the_ceiling_there_is_no_total_only_a_lower_bound(tmp_path, monkeypatch):
    """יותר מופעים מהתקרה: ``total_at_least`` בדיוק בגובה התקרה.

    הקובץ נבנה עם מופע אחד יותר מהתקרה, כדי שהתשובה לא תוכל להיות
    נכונה במקרה.
    """
    mcp = _build(
        tmp_path,
        {"big.txt": "".join(f"{_N} {i}\n" for i in range(SEARCH_COUNT_CEILING + 1))},
        monkeypatch,
    )

    out = await _search(mcp, max_results=2)

    assert "total" not in out
    assert out["total_at_least"] == SEARCH_COUNT_CEILING
    assert out["truncated"] is True
    assert out["truncation_reason"] == "count_ceiling"


@requires_git
async def test_timeout_reports_a_lower_bound_and_says_so(tmp_path, monkeypatch):
    """timeout אמיתי במסלול אמיתי, בלי להמתין באמת.

    תקציב הזמן הוא של **שני** המעברים יחד, ולכן אפס שניות עוצר את
    החיפוש לפני הכול — וזה בדיוק הקצה שנבדק: אין ``total``, ויש סיבה.
    """
    import services.repo_search_service as rss

    mcp = _build(tmp_path, {"src/a.py": _lines(7)}, monkeypatch)
    monkeypatch.setattr(rss, "CONTENT_SEARCH_TIMEOUT_SECONDS", 0)

    out = await _search(mcp, max_results=2)

    assert "total" not in out
    assert out["total_at_least"] >= 0
    assert out["truncated"] is True
    assert out["truncation_reason"] == "timeout"


@requires_git
async def test_a_cut_count_never_reports_less_than_what_it_returned(tmp_path, monkeypatch):
    """‏``total_at_least`` הוא חסם תחתון — ולכן לעולם לא קטן מ-``count``."""
    import services.git_mirror_service as gms

    mcp = _build(tmp_path, {"src/a.py": _lines(7)}, monkeypatch)
    # מעבר הספירה נקטע מיד, לפני שספר ולו קובץ אחד.
    monkeypatch.setattr(gms, "GREP_COUNT_MAX_FILES", 0)

    out = await _search(mcp, max_results=2)

    assert "total" not in out
    assert out["total_at_least"] == out["count"] == 2
    assert out["truncation_reason"] == "count_output_limit"


@requires_git
async def test_a_sync_between_the_two_passes_does_not_move_the_ground(tmp_path, monkeypatch):
    """שני המעברים על אותו קומיט, גם כשהענף זז באמצע.

    ה-autosync מושך עדכונים בזמן שקריאות רצות, ובלי נעילה — כלומר הענף
    באמת יכול לזוז בין מעבר התוצאות למעבר הספירה. הבדיקה מכריחה בדיוק
    את זה: קומיט חדש עם עוד מופעים נמשך למראה **בין** שני המעברים.

    ‏``total`` חייב לתאר את העץ שהתוצאות הגיעו ממנו, ולכן 7 ולא 12.
    הכתיבה כולה על העותק שתחת ``tmp_path``.
    """
    from services.git_mirror_service import GitMirrorService

    mcp = _build(tmp_path, {"src/a.py": _lines(7)}, monkeypatch)
    original = GitMirrorService._count_matches_with_git_grep

    def _sync_then_count(self, **kwargs):
        work = tmp_path / "work"
        (work / "src" / "b.py").write_text(_lines(5), encoding="utf-8")
        _run(_GIT, "add", "-A", cwd=work)
        _run(
            _GIT, "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-qm", "more", cwd=work,
        )
        _run(_GIT, "fetch", "-q", cwd=tmp_path / "repo.git")
        return original(self, **kwargs)

    monkeypatch.setattr(GitMirrorService, "_count_matches_with_git_grep", _sync_then_count)

    out = await _search(mcp, max_results=2)

    assert out["total"] == 7


@requires_git
async def test_the_count_timeout_is_enforced_on_the_wait_itself(tmp_path, monkeypatch):
    """תהליך שלא מדפיס כלום — והספירה עדיין חוזרת בזמן.

    ``readline`` חוסם עד שיש פלט, ולכן בדיקת שעון **אחרי** הקריאה אינה
    שווה דבר בדיוק במקרה שבשבילו היא קיימת: סריקה ארוכה שאינה מדפיסה
    שורה. הבדיקה מחליפה את התהליך בכזה שרק ישן, ומוודאת שהחזרה היא לפי
    תקציב הזמן ולא לפי סיום התהליך.

    **זו בדיקה של המנגנון ולא של החוזה**, ולכן היא היחידה כאן שקוראת
    למתודה ישירות: אין דרך לגרום ל-``git`` להשתתק לפי דרישה דרך הכלי.
    """
    import subprocess as sp
    import sys
    import time

    import services.git_mirror_service as gms

    svc = gms.GitMirrorService(base_path=str(tmp_path))
    real_popen = sp.Popen

    def _silent_popen(cmd, **kwargs):
        return real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)

    monkeypatch.setattr(gms.subprocess, "Popen", _silent_popen)

    started = time.monotonic()
    out = svc._count_matches_with_git_grep(
        repo_path=tmp_path,
        query=_N,
        ref="HEAD",
        case_sensitive=True,
        regex=False,
        pathspec=[],
        timeout=1,
    )
    elapsed = time.monotonic() - started

    assert out["complete"] is False
    assert out["truncation_reason"] == "timeout"
    # התהליך היה ישן 30 שניות. חסם של 5 הוא רחב דיו כדי לא להבהב על מכונת
    # CI עמוסה, וצר דיו כדי ליפול אם ההמתנה אינה מוגבלת בכלל.
    assert elapsed < 5


def test_the_argv_guard_refuses_anything_that_is_not_git():
    """השומר שמאמת את ה-argv לפני ההרצה.

    הוא אינו מחטא ערכים — ניקוי תווים היה שובר שאילתות לגיטימיות כמו
    ``dict[`` — אלא מאמת שהתוכנית היא ``git`` ליטרלי ושכל ארגומנט הוא
    מחרוזת בלי ``NUL``. בלי בדיקה כזאת שומר הוא הצהרה, לא התנהגות.
    """
    from services.git_mirror_service import _require_git_argv

    assert _require_git_argv(["git", "grep", "-c", "needle"]) is None
    assert _require_git_argv([]) is not None
    assert _require_git_argv(["rm", "-rf", "/"]) is not None
    assert _require_git_argv(["git", 5]) is not None
    assert _require_git_argv(["git", "a\0b"]) is not None


@requires_git
async def test_an_exhausted_budget_never_starts_a_search(tmp_path, monkeypatch):
    """תקציב הזמן אחד לשלושת השלבים, ולא אחד לכל שלב.

    קיבוע ה-ref הוא תת-תהליך בפני עצמו, וקודם הוא רץ עם timeout משלו
    **מחוץ** לתקציב — כלומר קריאה שהובטח לה חסם של עשר שניות יכלה
    להחזיק חוט עשרים. היום השעון מתחיל לפניו, וכשלא נשאר זמן לא נפתח
    שום תת-תהליך: לא קיבוע, לא איסוף ולא ספירה.

    **מוטציה שמפילה:** להחזיר את ``started`` אל מתחת לקיבוע.
    """
    import services.git_mirror_service as gms
    import services.repo_search_service as rss

    mcp = _build(tmp_path, {"src/a.py": _lines(7)}, monkeypatch)
    monkeypatch.setattr(rss, "CONTENT_SEARCH_TIMEOUT_SECONDS", 0)

    started_a_process = []

    def _forbidden(*a, **k):
        started_a_process.append(a)
        raise AssertionError("תת-תהליך נפתח למרות שהתקציב נגמר")

    monkeypatch.setattr(gms.GitMirrorService, "_validate_ref_with_git", _forbidden)
    monkeypatch.setattr(gms.GitMirrorService, "_run_grep_with_streaming", _forbidden)
    monkeypatch.setattr(gms.GitMirrorService, "_count_matches_with_git_grep", _forbidden)

    out = await _search(mcp, max_results=2)

    assert started_a_process == []
    assert out["ok"] is True
    assert "total" not in out
    assert out["total_at_least"] == 0
    assert out["truncated"] is True
    assert out["truncation_reason"] == "timeout"


# ===========================================================================
# 3. מה שהספירה לא סופרת
# ===========================================================================


@requires_git
async def test_context_lines_do_not_change_the_count(tmp_path, monkeypatch):
    """שורת הקשר אינה התאמה — והמספר חייב להיות זהה עם וּבלי הקשר."""
    files = {"src/a.py": _lines(7)}
    mcp = _build(tmp_path, files, monkeypatch)

    plain = await _search(mcp, max_results=2)
    with_ctx = await _search(mcp, max_results=2, context_lines=3)

    assert plain["total"] == with_ctx["total"] == 7
    assert with_ctx["results"][0]["context_before"]


@requires_git
async def test_denied_paths_are_neither_returned_nor_counted(tmp_path, monkeypatch):
    """מדיניות הסודות חלה על הספירה, לא רק על התוצאות.

    שלושה מסלולים באותה בדיקה: קובץ חסום מקונן (``config/.env``), שם
    באותיות גדולות (``SECRETS.YAML``), ותבנית שהגיעה מ-
    ``MCP_REPO_DENYLIST_EXTRA``. אף אחד מהם אינו נספר.
    """
    monkeypatch.setenv("MCP_REPO_DENYLIST_EXTRA", "*.private")
    mcp = _build(
        tmp_path,
        {
            "src/a.py": _lines(3),
            "config/.env": _lines(5),
            "SECRETS.YAML": _lines(4),
            "vault/keys.private": _lines(6),
        },
        monkeypatch,
    )

    out = await _search(mcp, max_results=50)

    assert out["total"] == 3
    assert {r["path"] for r in out["results"]} == {"src/a.py"}


@requires_git
async def test_vendored_code_is_out_of_both_the_results_and_the_count(tmp_path, monkeypatch):
    mcp = _build(
        tmp_path,
        {
            "src/a.py": _lines(3),
            "node_modules/pkg/index.js": _lines(5),
            "web/node_modules/deep/x.js": _lines(6),
        },
        monkeypatch,
    )

    out = await _search(mcp, max_results=50)

    assert out["total"] == 3
    assert {r["path"] for r in out["results"]} == {"src/a.py"}


@requires_git
async def test_include_vendored_brings_it_back_to_both(tmp_path, monkeypatch):
    mcp = _build(
        tmp_path,
        {
            "src/a.py": _lines(3),
            "node_modules/pkg/index.js": _lines(5),
            "web/node_modules/deep/x.js": _lines(6),
        },
        monkeypatch,
    )

    out = await _search(mcp, max_results=50, include_vendored=True)

    assert out["total"] == 14
    assert {r["path"] for r in out["results"]} == {
        "src/a.py",
        "node_modules/pkg/index.js",
        "web/node_modules/deep/x.js",
    }


@requires_git
async def test_include_vendored_does_not_unlock_a_secret(tmp_path, monkeypatch):
    """שתי הרשימות נפרדות, וזו הבדיקה שמחזיקה את ההפרדה.

    ``include_vendored`` נוגע בקוד חיצוני בלבד. קובץ סוד נשאר חסום גם
    כשהוא דלוק — אחרת דגל נוחות היה הופך לדגל הרשאה.
    """
    mcp = _build(
        tmp_path,
        {
            "src/a.py": _lines(3),
            "node_modules/pkg/index.js": _lines(5),
            "config/.env": _lines(9),
        },
        monkeypatch,
    )

    out = await _search(mcp, max_results=50, include_vendored=True)

    assert out["total"] == 8
    assert all(r["path"] != "config/.env" for r in out["results"])


@requires_git
async def test_the_per_file_cap_is_reported_and_counted(tmp_path, monkeypatch):
    """הקצה השקט: ``max_results`` לא נגמר, ובכל זאת חסרות התאמות.

    ‏``git grep -m`` מגביל ל-20 התאמות לקובץ (``min(max_results, 20)``),
    ולכן קובץ עם 25 מופעים מחזיר 20 גם כשביקשו 50 — הסריקה מסתיימת
    מעצמה, ושום תקרה שהקורא מכיר לא נגמרה. בלי זיהוי המכסה התשובה הייתה
    ``count: 20, total: 20, truncated: false``, כלומר שקר שלם ושקט.

    **הבדיקה הזאת נוספה אחרי בדיקת מוטציה:** כיבוי ``per_file_cap_hit``
    לא הפיל אף טסט, כי כל שאר המקרים נקטעים ממילא ב-``max_results``.
    """
    mcp = _build(tmp_path, {"src/a.py": _lines(25)}, monkeypatch)

    out = await _search(mcp, max_results=50)

    assert out["count"] == 20
    assert out["total"] == 25
    assert out["truncated"] is True
    assert out["truncation_reason"] == "matches_per_file"


# ===========================================================================
# 3ב. רישיות — מה שהחיפוש הזה לא ידע להבדיל
# ===========================================================================

# ``Config`` ו-``config`` באותו ריפו, ובכוונה גם ``CONFIG`` — שלושה מופעים
# שהתאמה חסרת-רישיות מאחדת לאחד.
_CASE_FILES = {
    "src/upper.py": "class Config:\nCONFIG = 1\n",
    "src/lower.py": "config = {}\nfrom config import x\n",
}


@requires_git
async def test_case_is_ignored_by_default_in_results_and_in_the_count(tmp_path, monkeypatch):
    """ברירת המחדל לא זזה: ``Config`` תופס גם את ``config``.

    זו הבדיקה ששומרת על התאימות — הפרמטר החדש הוא תוספת, ומי שלא מעביר
    אותו מקבל בדיוק את מה שקיבל קודם.
    """
    mcp = _build(tmp_path, _CASE_FILES, monkeypatch)

    out = await _search(mcp, query="Config", max_results=50)

    assert out["total"] == 4
    assert {r["path"] for r in out["results"]} == {"src/upper.py", "src/lower.py"}


@requires_git
async def test_case_sensitive_narrows_both_the_results_and_the_count(tmp_path, monkeypatch):
    """הבדיקה המרכזית של הפרמטר.

    **הספירה חייבת לכבד אותו.** מופע שהדגל מוציא מהתוצאות ועדיין נספר
    היה מייצר בדיוק את הפער ש-``total`` אמור לסגור: מספר שאינו מתאר את
    מה שאפשר לקבל.

    **מוטציה שמפילה:** להסיר את ``case_sensitive`` מהקריאה ב-
    ``repo_backend.search`` — ואז ``git grep`` רץ עם ``-i`` ושתי
    הבדיקות האלה מקבלות את אותו מספר.
    """
    mcp = _build(tmp_path, _CASE_FILES, monkeypatch)

    exact = await _search(mcp, query="Config", max_results=50, case_sensitive=True)

    assert exact["total"] == 1
    assert [r["path"] for r in exact["results"]] == ["src/upper.py"]
    assert exact["results"][0]["snippet"] == "class Config:"

    # והצד השני של אותו מטבע, כדי שהבדיקה לא תעבור על "פחות זה תמיד טוב".
    lower = await _search(mcp, query="config", max_results=50, case_sensitive=True)
    assert lower["total"] == 2
    assert {r["path"] for r in lower["results"]} == {"src/lower.py"}


@requires_git
async def test_case_sensitive_applies_with_regex_too(tmp_path, monkeypatch):
    """הדגל אינו נעצר ב-``-F``.

    ‏``-i`` ו-``-E`` הם שני מתגים נפרדים ב-``git grep``, ולכן אין שום
    ערובה מראש שמי שהעביר את האחד העביר גם את השני — נבדק ולא מונח.
    """
    mcp = _build(tmp_path, _CASE_FILES, monkeypatch)

    loose = await _search(mcp, query="Config|CONFIG", max_results=50, regex=True)
    strict = await _search(
        mcp, query="Config|CONFIG", max_results=50, regex=True, case_sensitive=True
    )

    assert loose["total"] == 4
    assert strict["total"] == 2
    assert {r["path"] for r in strict["results"]} == {"src/upper.py"}


@requires_git
async def test_case_sensitive_does_not_reopen_a_denied_or_vendored_path(tmp_path, monkeypatch):
    """דגל נוחות אינו דגל הרשאה — אותה בדיקה שכבר קיימת ל-``include_vendored``."""
    mcp = _build(
        tmp_path,
        {
            "src/upper.py": "class Config:\n",
            "config/.env": "Config=secret\n",
            "node_modules/pkg/i.js": "Config = 1\n",
        },
        monkeypatch,
    )

    out = await _search(mcp, query="Config", max_results=50, case_sensitive=True)

    assert out["total"] == 1
    assert [r["path"] for r in out["results"]] == ["src/upper.py"]


# ===========================================================================
# 4. הספירה אינה נגזרת ממה שביקשו להחזיר
# ===========================================================================


@requires_git
async def test_a_small_max_results_does_not_shrink_the_count(tmp_path, monkeypatch):
    """‏``max_results=1`` על קורפוס גדול — הספירה אינה נעצרת איתו.

    מגבלת הפלט של מעבר התוצאות נגזרת מ-``max_results`` (``*50``), ולכן
    ``max_results=1`` היה עוצר את הקריאה אחרי 50 שורות. הספירה אינה
    קוראת את הזרם ההוא בכלל, ולכן היא אינה כפופה למגבלה — וזה מה שנבדק
    כאן: אותו ``total`` בדיוק לכל ערך של ``max_results``.
    """
    mcp = _build(tmp_path, {f"src/f{i}.py": _lines(30) for i in range(10)}, monkeypatch)

    tiny = await _search(mcp, max_results=1)
    wide = await _search(mcp, max_results=100)

    assert tiny["count"] == 1
    assert wide["count"] == 100
    assert tiny["total"] == wide["total"] == 300
