"""טוקן ה-GitHub לא נשמר במראה ולא עובר בשורת הפקודה (#3480), וזיהוי הענף הראשי (#3479).

**git אמיתי, שרת אמיתי.** הטסטים כאן לא מחליפים את ``subprocess.run``: עד #3480
הטסטים של ``init_mirror`` החליפו אותו, ולכן לא ראו לא את ה-config של המראה ולא
את רשימת הפקודות המותרות ב-``_run_git_command`` — שני המקומות שבהם הבאגים ישבו.
כאן ``init_mirror``/``fetch_updates`` האמיתיים מדברים עם שרת HTTP מקומי שעוטף את
``git http-backend`` ודורש Basic auth לבעלים "פרטיים". ``GITHUB_HTTPS_ORIGIN``
מוחלף בכתובת השרת — אותו קבוע שממנו נגזרים הבדיקה של הכתובת ומפתח הכותרת.

הטוקנים בדויים.
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from services import mirror_credentials as creds
from services.git_mirror_service import GitCommandResult, GitMirrorService

MAP_TOKEN = "ghp_TESTMAP0123456789abcdefghijABCDEFGH"
GLOBAL_TOKEN = "ghp_TESTGLOBAL0123456789abcdefghijABCD"
PRIVATE_OWNERS = {"mapped", "unmapped"}


class _GitServer:
    """``git http-backend`` מאחורי Basic auth, עם רישום של כל בקשה."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.requests: List[Dict[str, Any]] = []
        self.delay = 0.0
        self._lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # שקט בפלט של pytest
                return

            def _handle(self) -> None:
                path, _, query = self.path.partition("?")
                owner = path.strip("/").split("/", 1)[0]
                auth = self.headers.get("Authorization")
                password: Optional[str] = None
                user: Optional[str] = None
                if auth and auth.startswith("Basic "):
                    user, _, password = base64.b64decode(auth[6:]).decode().partition(":")
                with server._lock:
                    server.requests.append({"owner": owner, "user": user, "password": password})
                if owner in PRIVATE_OWNERS and password not in (MAP_TOKEN, GLOBAL_TOKEN):
                    body = b"auth required\n"
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="test"')
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if server.delay:
                    time.sleep(server.delay)
                length = int(self.headers.get("Content-Length") or 0)
                data = self.rfile.read(length) if length else b""
                env = {
                    "PATH": os.environ["PATH"],
                    "GIT_PROJECT_ROOT": str(server.root),
                    "GIT_HTTP_EXPORT_ALL": "1",
                    "PATH_INFO": path,
                    "QUERY_STRING": query,
                    "REQUEST_METHOD": self.command,
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": str(len(data)),
                    "REMOTE_ADDR": "127.0.0.1",
                }
                if self.headers.get("Git-Protocol"):
                    env["GIT_PROTOCOL"] = self.headers["Git-Protocol"]
                if self.headers.get("Content-Encoding"):
                    env["HTTP_CONTENT_ENCODING"] = self.headers["Content-Encoding"]
                out = subprocess.run(["git", "http-backend"], input=data, env=env, capture_output=True).stdout
                sep, seplen = out.find(b"\r\n\r\n"), 4
                if sep == -1:
                    sep, seplen = out.find(b"\n\n"), 2
                head, payload = out[:sep], out[sep + seplen:]
                code, headers = 200, []
                for line in head.decode("latin-1").splitlines():
                    key, _, value = line.partition(":")
                    if key.lower() == "status":
                        code = int(value.strip().split()[0])
                    elif key.strip():
                        headers.append((key.strip(), value.strip()))
                self.send_response(code)
                for key, value in headers:
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _handle
            do_POST = _handle

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def take(self) -> List[Dict[str, Any]]:
        with self._lock:
            out, self.requests = self.requests, []
        return out


class _World:
    def __init__(self, tmp_path: Path, server: _GitServer, env: Dict[str, str]) -> None:
        self.tmp = tmp_path
        self.server = server
        self.env = env
        self.mirrors = tmp_path / "mirrors"
        self.svc = GitMirrorService(base_path=str(self.mirrors))

    def git(self, *args: str, cwd: Optional[Path] = None) -> str:
        done = subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True, text=True)
        return done.stdout.strip()

    def make_origin(self, owner: str, repo: str, branch: str = "main") -> str:
        bare = self.server.root / owner / f"{repo}.git"
        bare.parent.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "--bare", "-b", branch, str(bare))
        work = self.tmp / f"work-{owner}-{repo}"
        self.git("init", "-q", "-b", branch, str(work))
        (work / "app.py").write_text("print('v1')\n", encoding="utf-8")
        self.git("add", ".", cwd=work)
        self.git("commit", "-q", "-m", "v1", cwd=work)
        self.git("push", "-q", str(bare), branch, cwd=work)
        return f"{self.server.origin}/{owner}/{repo}.git"

    def push_change(self, owner: str, repo: str, text: str, branch: str = "main") -> None:
        work = self.tmp / f"work-{owner}-{repo}"
        (work / "app.py").write_text(text, encoding="utf-8")
        self.git("commit", "-q", "-am", text.strip(), cwd=work)
        self.git("push", "-q", str(self.server.root / owner / f"{repo}.git"), branch, cwd=work)

    def legacy_mirror(self, owner: str, repo: str, token: str) -> Path:
        """מראה כמו שהקוד יצר עד #3480: clone מ-URL שהטוקן בתוכו."""
        clean = f"{self.server.origin}/{owner}/{repo}.git"
        with_token = clean.replace("http://", f"http://oauth2:{token}@")
        target = self.mirrors / f"{repo}.git"
        self.git("clone", "-q", "--mirror", "--", with_token, str(target))
        assert token in (target / "config").read_text(), "הכנת הטסט: המראה הישנה אמורה לשאת את הטוקן"
        return target


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    for key in list(os.environ):
        if key.lower() in ("http_proxy", "https_proxy", "all_proxy") or key.startswith("GIT_CONFIG"):
            monkeypatch.delenv(key, raising=False)
    for key in ("GITHUB_TOKEN", "GITHUB_TOKENS"):
        monkeypatch.delenv(key, raising=False)
    settings = {
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "NO_PROXY": "127.0.0.1",
        "no_proxy": "127.0.0.1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    server = _GitServer(tmp_path / "srv")
    monkeypatch.setattr(creds, "GITHUB_HTTPS_ORIGIN", server.origin)
    try:
        yield _World(tmp_path, server, dict(os.environ))
    finally:
        server.httpd.shutdown()
        server.httpd.server_close()


def _files_with(root: Path, *needles: str) -> List[str]:
    hits = []
    for f in sorted(root.rglob("*")):
        if f.is_file():
            data = f.read_bytes()
            if any(n.encode() in data for n in needles):
                hits.append(str(f.relative_to(root)))
    return hits


def _basic(token: str) -> str:
    return base64.b64encode(f"oauth2:{token}".encode()).decode()


# ---------------------------------------------------------------------------
# #3480: הטוקן לא נשמר בדיסק
# ---------------------------------------------------------------------------


def test_init_mirror_leaves_the_token_in_no_file(world, monkeypatch):
    """אחרי ``init_mirror`` של ריפו פרטי, אף קובץ במראה לא מכיל את הטוקן — לא בטקסט ולא ב-base64."""
    monkeypatch.setenv("GITHUB_TOKENS", f"mapped={MAP_TOKEN}")
    url = world.make_origin("mapped", "secret-app")

    res = world.svc.init_mirror(url, "secret-app")

    assert res["success"] is True, res
    assert res["auth_used"] == "map"
    mirror = world.mirrors / "secret-app.git"
    assert _files_with(mirror, MAP_TOKEN, _basic(MAP_TOKEN)) == []
    assert world.git("config", "--get", "remote.origin.url", cwd=mirror) == url
    # והשרת אכן קיבל את ה-credential — כלומר האימות עבר, לא דולג
    assert any(r["password"] == MAP_TOKEN and r["user"] == "oauth2" for r in world.server.take())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="סריקת /proc/<pid>/cmdline קיימת רק בלינוקס")
def test_no_git_process_carries_the_token_on_its_command_line(world, monkeypatch):
    """בזמן clone ו-fetch, הטוקן (גם ב-base64) לא מופיע בשורת הפקודה של אף תהליך.

    עד #3480 הוא הופיע ב-``git clone`` וב-``git-remote-http`` — git מעביר את ה-URL
    המלא כארגומנט לתהליך העזר (``transport-helper.c``, git 2.43).
    """
    monkeypatch.setenv("GITHUB_TOKENS", f"mapped={MAP_TOKEN}")
    url = world.make_origin("mapped", "slow-app")
    world.server.delay = 0.3  # מחזיק את התהליכים חיים מספיק זמן לסריקה
    needles = (MAP_TOKEN.encode(), _basic(MAP_TOKEN).encode())
    seen: List[str] = []
    stop = threading.Event()

    def scan() -> None:
        me = os.getpid()
        while not stop.is_set():
            for pid in os.listdir("/proc"):
                if not pid.isdigit() or int(pid) == me:
                    continue
                try:
                    cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
                except OSError:
                    continue
                if any(n in cmdline for n in needles):
                    seen.append(cmdline.split(b"\0")[0].decode(errors="replace"))
            time.sleep(0.002)

    scanner = threading.Thread(target=scan, daemon=True)
    scanner.start()
    try:
        assert world.svc.init_mirror(url, "slow-app")["success"] is True
        world.push_change("mapped", "slow-app", "print('v2')\n")
        assert world.svc.fetch_updates("slow-app")["success"] is True
    finally:
        stop.set()
        scanner.join()
    assert seen == []
    # ולוודא שהסורק באמת ראה תהליכים מאומתים: השרת קיבל את הטוקן
    assert any(r["password"] == MAP_TOKEN for r in world.server.take())


def test_fetch_cleans_a_legacy_mirror_and_still_authenticates(world, monkeypatch):
    """מראה מלפני #3480: ``fetch_updates`` מנקה את ה-URL, ה-fetch עובד, ואין טוקן באף קובץ."""
    monkeypatch.setenv("GITHUB_TOKENS", f"mapped={MAP_TOKEN}")
    url = world.make_origin("mapped", "old-app")
    mirror = world.legacy_mirror("mapped", "old-app", MAP_TOKEN)
    world.server.take()
    world.push_change("mapped", "old-app", "print('v2')\n")

    res = world.svc.fetch_updates("old-app")

    assert res["success"] is True, res
    assert res["auth_used"] == "map"
    assert world.git("config", "--get", "remote.origin.url", cwd=mirror) == url
    assert _files_with(mirror, MAP_TOKEN, _basic(MAP_TOKEN)) == []
    # המצב, לא רק קוד היציאה: ה-commit החדש באמת הגיע
    head = world.git("rev-parse", "refs/heads/main", cwd=mirror)
    origin_head = world.git("rev-parse", "main", cwd=world.tmp / "work-mapped-old-app")
    assert head == origin_head


def test_public_repo_never_receives_a_token(world, monkeypatch):
    """ריפו ציבורי: גם כשמוגדרים טוקן במפה וטוקן גלובלי, אף בקשה לא נושאת ``Authorization``."""
    monkeypatch.setenv("GITHUB_TOKENS", f"openorg={MAP_TOKEN}")
    monkeypatch.setenv("GITHUB_TOKEN", GLOBAL_TOKEN)
    url = world.make_origin("openorg", "public-app")

    created = world.svc.init_mirror(url, "public-app")
    world.push_change("openorg", "public-app", "print('v2')\n")
    fetched = world.svc.fetch_updates("public-app")

    assert created["success"] and fetched["success"]
    assert created["auth_used"] == fetched["auth_used"] == "none"
    requests = world.server.take()
    assert requests, "השרת אמור לקבל בקשות"
    assert all(r["password"] is None for r in requests)


def test_owner_not_in_map_uses_the_global_token(world, monkeypatch, caplog):
    """בעלים במפה ← הטוקן שלו; בעלים שאינו במפה ← ``GITHUB_TOKEN``. ושורות הלוג אומרות מה נשלח."""
    monkeypatch.setenv("GITHUB_TOKENS", f"mapped={MAP_TOKEN}")
    monkeypatch.setenv("GITHUB_TOKEN", GLOBAL_TOKEN)
    mapped = world.make_origin("mapped", "a")
    unmapped = world.make_origin("unmapped", "b")

    with caplog.at_level(logging.INFO, logger="services.git_mirror_service"):
        assert world.svc.init_mirror(mapped, "a")["auth_used"] == "map"
        assert world.svc.init_mirror(unmapped, "b")["auth_used"] == "global"

    used = {(r["owner"], r["password"]) for r in world.server.take() if r["password"]}
    assert used == {("mapped", MAP_TOKEN), ("unmapped", GLOBAL_TOKEN)}
    assert "auth_used=global" in caplog.text
    assert MAP_TOKEN not in caplog.text and GLOBAL_TOKEN not in caplog.text


def test_fetch_is_refused_when_the_url_cannot_be_cleaned(world, monkeypatch):
    """כשהניקוי נכשל, ``fetch_updates`` לא מושך בכלל — אף בקשה לא מגיעה לשרת, והמראה לא משתנה."""
    monkeypatch.setenv("GITHUB_TOKENS", f"mapped={MAP_TOKEN}")
    world.make_origin("mapped", "stuck")
    mirror = world.legacy_mirror("mapped", "stuck", MAP_TOKEN)
    world.server.take()
    real = world.svc._run_git_command

    def set_url_fails(cmd, *args, **kwargs):
        if cmd[1:3] == ["remote", "set-url"]:
            return GitCommandResult(success=False, stdout="", stderr="injected", return_code=1)
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(world.svc, "_run_git_command", set_url_fails)

    res = world.svc.fetch_updates("stuck")

    assert res["success"] is False
    assert res["error_type"] == "mirror_url_not_clean"
    assert world.server.take() == []
    # ולא דווח "נוקה" על משהו שלא נוקה: הטוקן עדיין שם, וזה מה שהניקוי הבא יתפוס
    assert MAP_TOKEN in (mirror / "config").read_text()


def test_set_url_that_reports_success_without_cleaning_is_not_counted_as_cleaned(world, monkeypatch):
    """קוד יציאה 0 מ-``set-url`` אינו ראיה. רק הקריאה החוזרת קובעת — ו-fetch לא רץ."""
    monkeypatch.setenv("GITHUB_TOKENS", f"mapped={MAP_TOKEN}")
    world.make_origin("mapped", "liar")
    mirror = world.legacy_mirror("mapped", "liar", MAP_TOKEN)
    world.server.take()
    real = world.svc._run_git_command

    def set_url_lies(cmd, *args, **kwargs):
        if cmd[1:3] == ["remote", "set-url"]:
            return GitCommandResult(success=True, stdout="", stderr="", return_code=0)
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(world.svc, "_run_git_command", set_url_lies)

    assert creds.ensure_clean_remote(world.svc, "liar")["status"] == "failed"
    assert world.svc.fetch_updates("liar")["error_type"] == "mirror_url_not_clean"
    assert world.server.take() == []
    assert MAP_TOKEN in (mirror / "config").read_text()


def test_guard_stops_a_mirror_that_still_carries_credentials(world, monkeypatch):
    """``transfer.credentialsInUrl=die``: פקודת רשת על מראה עם טוקן ב-URL נכשלת לפני בקשה, והטוקן לא בהודעה."""
    monkeypatch.setenv("GITHUB_TOKENS", f"mapped={MAP_TOKEN}")
    url = world.make_origin("mapped", "guarded")
    mirror = world.legacy_mirror("mapped", "guarded", MAP_TOKEN)
    world.server.take()

    result, _ = world.svc._run_network_git(["git", "fetch", "--all", "--prune"], url, cwd=mirror)

    assert result.success is False
    assert "plaintext credentials" in result.stderr
    assert MAP_TOKEN not in result.stderr
    assert world.server.take() == []


def test_sweep_cleans_every_mirror_and_logs_counts_and_sources(world, monkeypatch, caplog):
    """הניקוי בעלייה: כל ``*.git`` נבדקת, ספירה אחת בלוג, מקור הטוקן לכל מראה — בלי הטוקן עצמו."""
    monkeypatch.setenv("GITHUB_TOKENS", f"mapped={MAP_TOKEN}")
    monkeypatch.setenv("GITHUB_TOKEN", GLOBAL_TOKEN)
    world.make_origin("mapped", "legacy")
    world.make_origin("unmapped", "fresh")
    world.legacy_mirror("mapped", "legacy", MAP_TOKEN)
    assert world.svc.init_mirror(f"{world.server.origin}/unmapped/fresh.git", "fresh")["success"]
    (world.mirrors / "junk.git").mkdir()

    with caplog.at_level(logging.INFO, logger="services.mirror_credentials"):
        stats = creds.scrub_stored_credentials(world.svc)

    assert {k: stats[k] for k in ("checked", "had_credentials", "cleaned", "failed")} == {
        "checked": 3,
        "had_credentials": 1,
        "cleaned": 1,
        "failed": 1,
    }
    assert stats["sources"] == {"fresh": "global", "junk": "unknown", "legacy": "map"}
    assert _files_with(world.mirrors, MAP_TOKEN, GLOBAL_TOKEN) == []
    assert "mirror credential sweep: checked=3 had_credentials=1 cleaned=1 failed=1" in caplog.text
    assert MAP_TOKEN not in caplog.text and GLOBAL_TOKEN not in caplog.text


def test_sweep_never_touches_a_repository_above_the_mirrors_dir(world):
    """תיקייה שאינה ריפו בתוך ריפו אחר: git היה מטפס למעלה ו-``set-url`` היה כותב ל-config שלו."""
    parent = world.tmp / "parent"
    world.git("init", "-q", str(parent))
    # URL שעובר את ``_validate_repo_url`` — אחרת הטסט היה עובר גם בלי ההצמדה,
    # כי ניקוי של URL לא תקין נדחה ממילא (נתפס בהרצת מוטציה)
    secret_url = world.server.origin.replace("http://", f"http://oauth2:{MAP_TOKEN}@") + "/x/parent.git"
    world.git("remote", "add", "origin", secret_url, cwd=parent)
    nested = GitMirrorService(base_path=str(parent / "mirrors"))
    (parent / "mirrors" / "junk.git").mkdir()

    stats = creds.scrub_stored_credentials(nested)

    assert stats["failed"] == 1 and stats["cleaned"] == 0
    assert world.git("config", "--get", "remote.origin.url", cwd=parent) == secret_url


def test_module_sweep_does_not_create_a_missing_mirror_dir(tmp_path, monkeypatch):
    missing = tmp_path / "no-mirrors-here"
    monkeypatch.setenv("REPO_MIRROR_PATH", str(missing))
    assert creds.sweep_stored_credentials() is None
    assert not missing.exists()


def test_sweep_of_an_unreadable_mirror_dir_raises_and_logs_no_clean_line(tmp_path, monkeypatch, caplog):
    """``checked=0 failed=0`` על תיקייה שלא נקראה היה נראה כמו "הכול נקי".

    ``Path.glob`` בלע את ``PermissionError`` והחזיר רשימה ריקה. ההרשאה נכשלת כאן
    רק לתיקיית המראות, כי טסט שרץ כ-root לא יכול לחסום אותה ב-``chmod``.
    """
    mirrors = tmp_path / "mirrors"
    svc = GitMirrorService(base_path=str(mirrors))
    real_scandir = os.scandir

    def scandir(path="."):
        if os.fspath(path) == str(mirrors):
            raise PermissionError(13, "Permission denied", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)

    with caplog.at_level(logging.INFO, logger="services.mirror_credentials"):
        with pytest.raises(PermissionError):
            creds.scrub_stored_credentials(svc)
    assert "mirror credential sweep: checked=" not in caplog.text


# ---------------------------------------------------------------------------
# רשימת הפקודות המותרות: רק שתי צורות של ``git remote``
# ---------------------------------------------------------------------------


def test_only_the_two_remote_shapes_are_allowed(world):
    url = world.make_origin("openorg", "shapes")
    assert world.svc.init_mirror(url, "shapes")["success"]
    mirror = world.mirrors / "shapes.git"
    run = world.svc._run_git_command

    assert run(["git", "remote", "get-url", "origin"], cwd=mirror).stdout.strip() == url
    assert run(["git", "remote", "set-url", "origin", url], cwd=mirror).success
    refused = [
        ["git", "remote", "add", "evil", url],
        ["git", "remote", "set-url", "--push", "origin", url],
        ["git", "remote", "set-url", "origin", url.replace("http://", f"http://oauth2:{MAP_TOKEN}@")],
        ["git", "remote", "set-url", "origin", "https://example.com/o/r.git"],
        ["git", "remote", "get-url", "origin", "--all"],
        ["git", "-c", "http.extraHeader=x", "fetch", "--all"],
        ["git", "config", "--get", "remote.origin.url"],
    ]
    for cmd in refused:
        res = run(cmd, cwd=mirror)
        assert (res.success, res.stderr) == (False, "Unsupported git subcommand"), cmd
    assert world.git("config", "--get", "remote.origin.url", cwd=mirror) == url


# ---------------------------------------------------------------------------
# #3479: הענף הראשי מזוהה מ-HEAD של המראה, ובלי נפילה ל-main
# ---------------------------------------------------------------------------


def test_detect_default_branch_on_a_master_only_mirror(world):
    url = world.make_origin("openorg", "legacy-master", branch="master")
    assert world.svc.init_mirror(url, "legacy-master")["success"]
    mirror = world.mirrors / "legacy-master.git"
    assert world.git("for-each-ref", "--format=%(refname)", "refs/heads", cwd=mirror) == "refs/heads/master"

    assert world.svc.detect_default_branch("legacy-master") == {"branch": "master", "reason": None}

    # HEAD שמצביע על ענף שאינו קיים: rev-parse מדפיס "HEAD" עם קוד 0 — חייב להיות כשל עם שם
    world.git("symbolic-ref", "HEAD", "refs/heads/gone", cwd=mirror)
    detected = world.svc.detect_default_branch("legacy-master")
    assert detected["branch"] is None and detected["reason"]


def test_initial_import_of_a_master_only_repo(world, monkeypatch):
    """``initial_import`` מקצה לקצה, עם המראה האמיתית: ``default_branch`` נשמר כ-``master``."""
    from services import repo_sync_service as rss

    class _Metadata:
        saved: Dict[str, Any] = {}

        def update_one(self, filt, update, upsert=False):
            _Metadata.saved = update["$set"]

    class _Files:
        def distinct(self, field, filt=None):
            return []

        def count_documents(self, filt):
            return 1

    class _Db:
        repo_metadata = _Metadata()
        repo_files = _Files()

    class _Indexer:
        def __init__(self, db=None):
            pass

        def should_index(self, path):
            return True

        def index_file(self, repo_name, path, content, sha="HEAD"):
            return True

        def remove_files(self, repo_name, paths):
            return 0

    url = world.make_origin("openorg", "old-style", branch="master")
    monkeypatch.setattr(rss, "get_mirror_service", lambda: world.svc)
    monkeypatch.setattr(rss, "CodeIndexer", _Indexer)

    out = rss.initial_import(url, "old-style", _Db())

    assert out.get("status") == "completed", out
    assert _Metadata.saved["default_branch"] == "master"


# ---------------------------------------------------------------------------
# מקרי קצה שהריוויו של PR #3519 העלה — כל אחד נמדד לפני התיקון
# ---------------------------------------------------------------------------


def test_sweep_survives_an_unparseable_url_and_cleans_the_rest(world, monkeypatch):
    """``urlsplit`` זורק ``ValueError`` על ``https://[::1/x.git`` — זה לא עוצר את המעבר."""
    monkeypatch.setenv("GITHUB_TOKENS", f"mapped={MAP_TOKEN}")
    world.make_origin("mapped", "good")
    world.legacy_mirror("mapped", "good", MAP_TOKEN)
    broken = world.mirrors / "broken.git"
    world.git("init", "-q", "--bare", str(broken))
    world.git("remote", "add", "origin", "https://[::1/x.git", cwd=broken)

    stats = creds.scrub_stored_credentials(world.svc)

    assert (stats["checked"], stats["cleaned"], stats["failed"]) == (2, 1, 1)
    assert creds.ensure_clean_remote(world.svc, "broken")["reason"] == "unparseable_url"


def test_cleaning_works_with_a_relative_mirrors_path(world, monkeypatch):
    """``base_path`` יחסי: ``GIT_DIR`` יחסי היה נפתר מתוך המראה עצמה ונכשל."""
    monkeypatch.setenv("GITHUB_TOKENS", f"mapped={MAP_TOKEN}")
    world.make_origin("mapped", "rel")
    mirror = world.legacy_mirror("mapped", "rel", MAP_TOKEN)
    monkeypatch.chdir(world.tmp)
    relative = GitMirrorService(base_path="mirrors")

    assert creds.ensure_clean_remote(relative, "rel")["status"] == "cleaned"
    assert MAP_TOKEN not in (mirror / "config").read_text()


def test_detect_default_branch_accepts_names_git_accepts(world):
    """``_main`` הוא שם ענף תקין ב-git; הבדיקה היא על ``refs/heads/_main``, כמו אצל הצרכנים."""
    url = world.make_origin("openorg", "underscore", branch="_main")
    assert world.svc.init_mirror(url, "underscore")["success"]
    assert world.svc.detect_default_branch("underscore") == {"branch": "_main", "reason": None}


_SWEEP_PROBE = """
import asyncio, sys, time, types
sys.path.insert(0, {tests!r})
sys.path.insert(0, {repo!r})
from _fake_mongo import FakeDB

fake_database = types.ModuleType("database")
fake_database.db = types.SimpleNamespace(db=FakeDB())
sys.modules["database"] = fake_database

config = {config!r}

def token_left():
    with open(config, encoding="utf-8") as fh:
        return {token!r} in fh.read()

import mcp_server.app as app_module
time.sleep(1.0)
print("AFTER-IMPORT=" + str(token_left()), flush=True)

async def serve():
    async with app_module.app.router.lifespan_context(app_module.app):
        deadline = time.monotonic() + 20
        while token_left() and time.monotonic() < deadline:
            await asyncio.sleep(0.1)

asyncio.run(serve())
print("AFTER-LIFESPAN=" + str(token_left()), flush=True)
"""


def test_importing_the_mcp_app_does_not_sweep_but_serving_it_does(world, tmp_path):
    """ייבוא של ``mcp_server.app`` (טסטים, כלים, REPL) לא נוגע במראות; עליית השרת כן.

    בתהליך נקי, כמו ש-uvicorn מייבא: ``create_app`` רץ בייבוא, ולכן ניקוי
    שמופעל ממנו ישירות היה כותב ל-config של כל מראה גם בייבוא סתמי.
    """
    pytest.importorskip("mcp")
    import pathlib

    repo = str(pathlib.Path(__file__).resolve().parents[1])
    tests_dir = str(pathlib.Path(__file__).resolve().parent)
    mirrors = tmp_path / "probe-mirrors"
    mirrors.mkdir()
    origin = world.make_origin("openorg", "served")
    target = mirrors / "served.git"
    # כמו מראה מלפני #3480, עם כתובת GitHub אמיתית — הניקוי מקומי ואינו פונה לרשת
    world.git("clone", "-q", "--mirror", "--", origin, str(target))
    world.git("remote", "set-url", "origin", f"https://oauth2:{MAP_TOKEN}@github.com/openorg/served.git", cwd=target)

    env = dict(world.env)
    env.update({"REPO_MIRROR_PATH": str(mirrors), "MCP_REPO_AUTOSYNC": "0"})
    for key in ("MCP_SERVER_URL", "WEBAPP_URL"):
        env.pop(key, None)
    probe = _SWEEP_PROBE.format(repo=repo, tests=tests_dir, config=str(target / "config"), token=MAP_TOKEN)
    proc = subprocess.run(
        [sys.executable, "-B", "-c", probe], capture_output=True, text=True, timeout=120, cwd=repo, env=env
    )

    assert "AFTER-IMPORT=True" in proc.stdout, proc.stdout + proc.stderr
    assert "AFTER-LIFESPAN=False" in proc.stdout, proc.stdout + proc.stderr
