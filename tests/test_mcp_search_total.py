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
    from mcp_server.repo_backend import RepoBackend
    from services.git_mirror_service import GitMirrorService
    from services.repo_search_service import RepoSearchService

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

    mirror = GitMirrorService(base_path=str(tmp_path))
    search = RepoSearchService(db=None)
    # ‏``RepoSearchService`` מושך את ה-singleton הגלובלי של המראה, שמצביע
    # על דיסק הייצור. ההזרקה כאן היא מה שמחזיק את הכלל "הכול תחת tmp_path".
    search.git_service = mirror

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
