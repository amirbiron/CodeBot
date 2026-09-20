"""Unit tests for the repo secrets-path policy (mandatory, fail-closed)."""

from pathlib import Path

import pytest

from mcp_server import repo_policy
from mcp_server.repo_policy import is_denied

_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "config/.env",  # nested
        "a/b/.env.production",
        ".ENV",  # case variant
        "certs/server.pem",
        "keys/private.key",
        "id_rsa",
        ".ssh/id_rsa.pub",
        "deploy/id_ed25519",
        "secrets.yaml",
        "conf/secrets.json",
        "credentials.json",
        "gcp/credentials_prod.yaml",
        "store.p12",
        "win/cert.pfx",
        ".netrc",
        ".npmrc",
        "android/release.keystore",
    ],
)
def test_denied_paths(path):
    assert is_denied(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "main.py",
        "src/app/utils.py",
        "envelope.py",  # starts with 'env' but no leading dot
        "environment.md",
        "key_utils.py",  # 'key' not as extension
        "docs/keys.md",
        "secrets_test.py",  # 'secrets_' != 'secrets.'
        "tests/test_secrets_handling.py",
        "README.md",
        "config/settings.yaml",
    ],
)
def test_allowed_paths(path):
    assert is_denied(path) is False


def test_empty_and_traversal_denied():
    assert is_denied("") is True
    assert is_denied(None) is True
    assert is_denied("..") is True


def test_windows_separators_normalized():
    assert is_denied("config\\.env") is True


def test_extra_patterns_from_env(monkeypatch):
    monkeypatch.setenv("MCP_REPO_DENYLIST_EXTRA", "*.sqlite, private/*")
    assert is_denied("data/app.sqlite") is True
    assert is_denied("private/notes.md") is True
    monkeypatch.delenv("MCP_REPO_DENYLIST_EXTRA")
    assert is_denied("data/app.sqlite") is False


def test_fail_closed_on_internal_error(monkeypatch):
    # If pattern evaluation blows up, the path must be treated as denied.
    def _boom(*a, **k):
        raise RuntimeError("policy unavailable")

    monkeypatch.setattr(repo_policy.fnmatch, "fnmatchcase", _boom)
    assert is_denied("main.py") is True


# ===========================================================================
# שם רגיש שהוא **תיקייה** ולא קובץ
# ===========================================================================


@pytest.mark.parametrize(
    "path",
    [
        "config/.env/README.md",        # תיקיית .env בעומק אחד
        "deep/a/b/credentials/notes.md",  # ובעומק שלושה
        "a/secrets.d/x.md",
        "keys/id_rsa/readme.md",
        "certs/server.pem/notes.md",    # תבנית-סיומת כשם תיקייה
        "x/.NETRC/y.md",                # וריאציית רישיות על תיקייה
        "CONFIG/.ENV/readme.MD",
    ],
)
def test_a_sensitive_directory_is_denied_at_any_depth(path):
    """קובץ בתוך תיקייה ששמה רגיש נחסם — התיקייה היא שם, לא רק הקובץ.

    **הכיסוי הקודם היה מקרי ולא חלקי, וזו הנקודה.** ההתאמה הייתה מול
    ה-basename ומול הנתיב המלא בלבד, ו-``fnmatch`` מרשה ל-``*`` לחצות
    ``/`` — ולכן ``credentials*`` תפס את ``credentials/notes.md`` רק מפני
    שהתיקייה ישבה ב**רכיב הראשון**. אותה תיקייה בדיוק, רכיב אחד פנימה,
    עברה. כל שבעת הנתיבים כאן הוחזרו ``False`` לפני התיקון.
    """
    assert is_denied(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "envelope/notes.md",       # 'env' בלי הנקודה המובילה
        "environment/readme.md",
        "keys/notes.md",           # 'keys' אינו 'key'
        "src/secrets_helpers/x.py",  # 'secrets_' אינו 'secrets.'
        "docs/credential-rotation.md",  # 'credential-' אינו 'credentials'
    ],
)
def test_a_directory_that_merely_resembles_a_secret_is_still_served(path):
    """ריצת הבקרה להרחבה: שם שנראה דומה ואינו תואם — נשאר מותר.

    בלי השורות האלה "ההרחבה לא חוסמת יותר מדי" הוא משפט בלי ראיה.
    """
    assert is_denied(path) is False


def test_a_pattern_with_a_slash_still_matches_the_whole_path(monkeypatch):
    """תבנית מ-``MCP_REPO_DENYLIST_EXTRA`` שמכילה ``/`` ממשיכה לעבוד.

    זה מה שמוכיח שבדיקת הנתיב המלא אינה כפילות של סריקת הרכיבים: אף רכיב
    בודד אינו ``internal/*``, ולכן רק ההשוואה לנתיב השלם תופסת אותה.
    """
    monkeypatch.setenv(repo_policy._EXTRA_ENV, "internal/*")
    assert is_denied("internal/roadmap.md") is True
    assert is_denied("public/roadmap.md") is False


def test_the_policy_blocks_exactly_the_known_files_in_this_repository():
    """על כל הריפו, המדיניות חוסמת בדיוק שני קבצים — ולא יותר.

    **זה השומר מול חסימת-יתר, והוא אבסולוטי ולא יחסי.** מימוש-ייחוס של
    הכלל הישן בתוך הטסט היה עותק שני שלו, ולכן הטענה היא על הרשימה עצמה:
    ``.env`` ו-``.env.example``, ששניהם באמת אמורים להיחסם. מי שיוסיף
    לריפו קובץ שנחסם — או ירחיב תבנית כך שתתפוס תיעוד — יראה את הרשימה
    גדלה, ויחליט במודע.

    ``git ls-files`` ולא ``rglob``, כי זה בדיוק מה שהמראה מגישה.
    """
    import subprocess

    proc = subprocess.run(["git", "ls-files"], cwd=str(_ROOT),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip("אין git או שזו אינה עבודה מגיט")
    paths = proc.stdout.split()
    assert len(paths) > 1000, "רשימת הקבצים קצרה מדי — הבדיקה איבדה את הקורפוס שלה"

    assert sorted(p for p in paths if is_denied(p)) == [".env", ".env.example"]


# ===========================================================================
# שתי מחציות של אותה מדיניות — ושתיהן נבדקות על אותו עץ
# ===========================================================================


def _seeded_mirror(tmp_path):
    """מראה אמיתית עם שם רגיש כתיקייה, בכל אחת מהצורות.

    ``clone --mirror`` ולא ריפו עובד — זה המבנה שהשירות מצפה לו
    (``<base>/<repo>.git``), אותה צורה כמו ב-``tests/test_mcp_search_total.py``.
    """
    import subprocess

    work = tmp_path / "work"
    seeded = {
        "config/.env/README.md": "SEEDTOKEN\n",
        "deep/a/b/credentials/notes.md": "SEEDTOKEN\n",
        "certs/server.pem/notes.md": "SEEDTOKEN\n",
        "a/secrets.d/x.md": "SEEDTOKEN\n",
        "keys/id_rsa/readme.md": "SEEDTOKEN\n",
        ".env": "SEEDTOKEN\n",
        "docs/ok.md": "SEEDTOKEN\n",
    }
    for name, body in seeded.items():
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    def _git(*args, cwd):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                       cwd=str(cwd), check=True, capture_output=True)

    _git("init", "-q", "-b", "main", ".", cwd=work)
    _git("add", "-A", cwd=work)
    _git("commit", "-qm", "init", cwd=work)
    subprocess.run(["git", "clone", "-q", "--mirror", str(work),
                    str(tmp_path / "demo.git")], check=True, capture_output=True)
    return seeded


def test_the_search_side_skips_every_path_the_read_side_denies(tmp_path):
    """שתי מחציות המדיניות מסכימות — נמדד מול git אמיתי, לא נגזר מקריאת קוד.

    **וזו הייתה הסיבה שהמדידה נדרשה.** ``is_denied`` חוסם קריאה, והמנוע
    מחריג את אותן תבניות מ-``git grep``; שתיהן נבנות מאותה רשימה, אבל
    **סמנטיקת ההתאמה שלהן נפרדה**. נמדד על git 2.43.0 לפני התיקון: מתוך
    שבעה קבצים שנזרעו, החיפוש החזיר גם את ``certs/server.pem/notes.md`` —
    תיקייה ששמה תואם תבנית-סיומת, ש-``*.pem`` ו-``*/*.pem`` שניהם מפספסים
    כי הם דורשים שהנתיב **יסתיים** ב-``.pem``.

    הטענה כאן היא על ההסכמה עצמה ולא על רשימה מוקלדת: כל נתיב שהקריאה
    חוסמת חייב להיעדר מתוצאות החיפוש, וההפך.
    """
    pytest.importorskip("services.git_mirror_service")
    from services.git_mirror_service import GitMirrorService

    seeded = _seeded_mirror(tmp_path)
    mirror = GitMirrorService(base_path=str(tmp_path))
    out = mirror.search_with_git_grep(
        "demo", "SEEDTOKEN", exclude_paths=list(repo_policy.denylist_patterns()))

    returned = {r["path"] for r in out.get("results", [])}
    denied = {p for p in seeded if is_denied(p)}
    allowed = set(seeded) - denied

    assert denied, "אף נתיב שנזרע אינו נחסם — הזריעה איבדה את הנושא שלה"
    assert returned & denied == set(), (
        f"החיפוש החזיר נתיבים שהקריאה חוסמת: {sorted(returned & denied)}")
    assert returned == allowed, (
        f"החיפוש ותשובת הקריאה אינם מסכימים: חיפוש={sorted(returned)}, "
        f"מותר={sorted(allowed)}")
