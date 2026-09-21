import pytest

from services.git_mirror_service import GitMirrorService


@pytest.fixture
def service(tmp_path):
    return GitMirrorService(base_path=str(tmp_path))


def test_init_mirror(service, monkeypatch):
    class _Res:
        def __init__(self):
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

    def _fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        # Basic sanity that we run the expected command shape
        assert cmd[0:3] == ["git", "clone", "--mirror"]
        return _Res()

    monkeypatch.setattr("services.git_mirror_service.subprocess.run", _fake_run)

    result = service.init_mirror("https://github.com/octocat/Hello-World.git", "test-repo")
    assert result["success"] is True


def test_should_classify_errors(service):
    assert service._classify_git_error("Could not resolve host") == "network_error"
    assert service._classify_git_error("Authentication failed") == "auth_error"


def test_init_mirror_existing_invalid_mirror_is_cleaned_and_recloned(service, tmp_path, monkeypatch):
    # Create a "corrupt" mirror directory (exists but not a real git repo)
    repo_dir = tmp_path / "test-repo.git"
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "junk.txt").write_text("not a git repo", encoding="utf-8")

    calls = {"rev_parse": 0, "clone": 0}

    class _Res:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        if cmd[:3] == ["git", "rev-parse", "--is-bare-repository"]:
            calls["rev_parse"] += 1
            return _Res(returncode=1, stdout="", stderr="fatal: not a git repository")
        if cmd[:3] == ["git", "clone", "--mirror"]:
            calls["clone"] += 1
            return _Res(returncode=0, stdout="", stderr="")
        raise AssertionError(f"Unexpected git command: {cmd}")

    monkeypatch.setattr("services.git_mirror_service.subprocess.run", _fake_run)

    result = service.init_mirror("https://github.com/octocat/Hello-World.git", "test-repo")
    assert result["success"] is True
    assert result.get("already_existed") is False
    assert calls["rev_parse"] >= 1
    assert calls["clone"] == 1


def test_sanitize_output_masks_https_credentials(service):
    raw = "fatal: unable to access 'https://oauth2:SECRET_TOKEN@github.com/org/repo.git/': 403\n"
    sanitized = service._sanitize_output(raw)
    assert "SECRET_TOKEN" not in sanitized
    assert "https://oauth2:***@github.com/org/repo.git" in sanitized


def test_get_file_content_strips_ref_and_path(service, monkeypatch):
    class _Res:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    seen = {"cmd": None}

    def _fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        seen["cmd"] = cmd
        return _Res(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("services.git_mirror_service.subprocess.run", _fake_run)

    out = service.get_file_content("test-repo", " src/file.py ", ref=" origin/main ")
    assert out == "ok"
    assert seen["cmd"] == ["git", "show", "origin/main:src/file.py"]


def test_a_leading_byte_order_mark_does_not_reach_the_decoded_text(service):
    """BOM הוא מטא-דאטה של קידוד, ולכן אינו נשאר כתו בטקסט.

    הסדר ברשימת הקודקים הוא מה שקובע כאן: קובץ עם BOM נפרס בהצלחה גם
    כ-``utf-8``, ואז ה-BOM נשאר כ-U+FEFF ונוסע לכל צרכן. הנזק נמדד
    בשני מסלולים — ``ast.parse`` נכשל על קובץ פייתון כזה ב"invalid
    non-printable character U+FEFF" והאאוטליין חוזר ריק, ובקובץ CSS
    ה-BOM נכנס לשם הסימבול הראשון. Chromium 141 מראה שגיליון חיצוני
    עם BOM נותן ``selectorText`` של ``.hero`` בלבד, כלומר הפרשנות
    הנכונה היא שה-BOM אינו תוכן.
    """
    with_bom = service._try_decode_content("\ufeff.hero { color: red }\n".encode("utf-8"))

    assert with_bom["is_binary"] is False
    assert not with_bom["content"].startswith("\ufeff"), (
        f"ה-BOM נשאר בטקסט: {with_bom['content'][:3]!r}"
    )
    assert with_bom["content"] == ".hero { color: red }\n"
    assert with_bom["encoding"] == "utf-8-sig"


def test_text_without_a_byte_order_mark_decodes_exactly_as_before(service):
    """הבקרה: קובץ בלי BOM אינו משתנה, **וגם התווית שלו אינה משתנה.**

    התוכן — נמדד על 60,000 קלטים אקראיים ששני הקודקים מחזירים פלט זהה,
    פרט לקלט שמתחיל ב-BOM. הטסט מקבע את הקצוות של אותה מדידה: עברית,
    אמוג'י, ו-BOM שיושב **באמצע** ולא בהתחלה (שם הוא כן תו).

    **והתווית היא החצי שקל לפספס.** גרסה קודמת פשוט הקדימה את
    ``utf-8-sig`` ברשימת הקודקים, וזה אכן הוריד את ה-BOM — אבל אז כל
    קובץ UTF-8 דיווח ``utf-8-sig``, גם קובץ בלי BOM, כלומר כמעט כל
    קובץ בכל ריפו. ``utf-8-sig`` פירושו "UTF-8 עם חתימה", והתווית
    נוסעת ל-``file_meta`` בתשובת הכלי. הזיהוי הוא ענף על הבייטים, ולכן
    התווית אומרת את מה שקרה.
    """
    for probe in (".hero { color: red }\n", "שלום\nעולם", "x \U0001F600 y", "abc\ufeffdef"):
        result = service._try_decode_content(probe.encode("utf-8"))

        assert result["content"] == probe, f"נבדל על {probe!r}"
        assert result["encoding"] == "utf-8", f"תווית שגויה על {probe!r}"


def test_a_byte_order_mark_over_an_undecodable_body_still_returns_something(service):
    """חתימה תקינה וגוף פגום אינם מחזירים שגיאה.

    ``utf-8-sig`` נכשל שם, ולכן הענף על ה-BOM **נופל חזרה** לרשימה —
    ושם ``latin-1`` תופס כל רצף בייטים. עדיף להציג קובץ מקולקל מלהחזיר
    כלום, וזו גם ההתנהגות שהייתה לפני שהענף נכנס.
    """
    result = service._try_decode_content(b"\xef\xbb\xbf\xff\xfe rest")

    assert result["is_binary"] is False
    assert result["content"]


def test_parse_grep_output_strips_sha_prefix(service):
    output = "abc123def456:src/app.py\n10:hello\n"
    results = service._parse_grep_output(output, max_results=10)
    assert results == [{"path": "src/app.py", "line": 10, "content": "hello"}]


def test_get_mirror_info_ignores_deleted_files_during_size_calc(service, monkeypatch):
    class _St:
        def __init__(self, size: int):
            self.st_size = size

    class _FakeFile:
        def __init__(self, *, size: int | None):
            self._size = size

        def is_file(self) -> bool:
            return True

        def stat(self):
            if self._size is None:
                raise FileNotFoundError("deleted during traversal")
            return _St(self._size)

    class _FakeRepoPath:
        def exists(self) -> bool:
            return True

        def rglob(self, pattern: str):
            assert pattern == "*"
            return [_FakeFile(size=10), _FakeFile(size=None), _FakeFile(size=5)]

        def __str__(self) -> str:
            return "/tmp/fake-repo.git"

    monkeypatch.setattr(service, "_get_repo_path", lambda repo_name: _FakeRepoPath())
    monkeypatch.setattr(service, "get_current_sha", lambda repo_name: "deadbeef")

    info = service.get_mirror_info("test-repo")
    assert info is not None
    assert info["size_bytes"] == 15



# ============================================
# ריבוי טוקנים לפי ארגון (GITHUB_TOKENS)
# ============================================

def test_extract_owner_https_and_ssh(service):
    assert service._extract_owner("https://github.com/Campaign-AI4U/campaign-ai.git") == "Campaign-AI4U"
    assert service._extract_owner("https://github.com/octocat/Hello-World") == "octocat"
    assert service._extract_owner("git@github.com:MyOrg/repo.git") == "MyOrg"
    assert service._extract_owner("not-a-url") == ""


def test_token_map_simple_format_selects_per_owner(service, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKENS", "Campaign-AI4U=ghp_AAA,OtherOrg=github_pat_BBB")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_GLOBAL")

    # ארגון ממופה → הטוקן שלו
    assert service._token_for_url("https://github.com/Campaign-AI4U/campaign-ai.git") == "ghp_AAA"
    # התאמת בעלים היא case-insensitive
    assert service._token_for_url("https://github.com/otherorg/foo.git") == "github_pat_BBB"
    # ארגון לא ממופה → נפילה ל-GITHUB_TOKEN הגלובלי
    assert service._token_for_url("https://github.com/ThirdOrg/bar.git") == "ghp_GLOBAL"


def test_token_map_json_format(service, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKENS", '{"Campaign-AI4U": "ghp_JSON_A", "OtherOrg": "ghp_JSON_B"}')
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert service._token_for_url("https://github.com/Campaign-AI4U/campaign-ai.git") == "ghp_JSON_A"
    assert service._token_for_url("https://github.com/OtherOrg/x.git") == "ghp_JSON_B"
    # ארגון לא ממופה ואין GITHUB_TOKEN → None (לא מזריקים טוקן)
    assert service._token_for_url("https://github.com/Nobody/y.git") is None


def test_token_fallback_to_global_when_no_map(service, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKENS", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_GLOBAL")
    assert service._token_for_url("https://github.com/anyone/x.git") == "ghp_GLOBAL"


def test_invalid_json_token_map_is_ignored(service, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKENS", "{not valid json")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_GLOBAL")
    # JSON שבור → מתעלמים מהמפה ונופלים ל-GITHUB_TOKEN
    assert service._token_for_url("https://github.com/Campaign-AI4U/campaign-ai.git") == "ghp_GLOBAL"


def test_authenticated_url_injects_per_owner_token(service, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKENS", "Campaign-AI4U=ghp_AAA")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_GLOBAL")
    url = service._get_authenticated_url("https://github.com/Campaign-AI4U/campaign-ai.git")
    assert url == "https://oauth2:ghp_AAA@github.com/Campaign-AI4U/campaign-ai.git"
    # ארגון לא ממופה → הטוקן הגלובלי
    url2 = service._get_authenticated_url("https://github.com/Zzz/repo.git")
    assert url2 == "https://oauth2:ghp_GLOBAL@github.com/Zzz/repo.git"


def test_constructor_token_overrides_map(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKENS", "Campaign-AI4U=ghp_AAA")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_GLOBAL")
    svc = GitMirrorService(base_path=str(tmp_path), github_token="ghp_EXPLICIT")
    # טוקן שהוזרק במפורש ל-constructor גובר על הכל
    assert svc._token_for_url("https://github.com/Campaign-AI4U/campaign-ai.git") == "ghp_EXPLICIT"


# ---------------------------------------------------------------------------
# get_file_at_commit: התקרה נבדקת מול מאגר האובייקטים לפני git show (#3433, פריט 9)
# ---------------------------------------------------------------------------
#
# עד #3433 ``git show`` נטען כולו לזיכרון ורק אז ``max_size`` נבדק — קובץ של
# 12MB שנדחה עלה 20MiB שיא. הטסטים כאן רצים על מראה git אמיתית שנבנית
# ב-``tmp_path`` (bare clone, כמו בייצור), ומרגלים על ``subprocess.run`` כדי
# לראות **אילו** פקודות git רצו — כי התכונה הנבדקת היא מה לא נקרא, ואת זה
# רואים רק ברשימת הפקודות.

import subprocess  # noqa: E402

from services import git_mirror_service as _gms  # noqa: E402


def _bare_mirror(tmp_path, files):
    """מראה bare בשם ``probe`` תחת ``tmp_path``, עם הקבצים הנתונים בקומיט אחד; מחזיר את השירות ואת ה-sha."""
    src = tmp_path / "src"
    src.mkdir()
    for name, data in files.items():
        target = src / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]}
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=src, check=True, env=env, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, check=True, env=env,
                         capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(tmp_path / "probe.git")],
                   check=True, env=env, capture_output=True)
    return GitMirrorService(base_path=str(tmp_path)), sha


def _spy_on_git(monkeypatch, override=None):
    """מרגל שמעביר כל קריאה ל-``subprocess.run`` האמיתי ורושם את ה-argv; ``override(argv)`` יכול להחזיר תוצאה מזויפת."""
    calls = []
    real = subprocess.run

    def spy(cmd, *args, **kwargs):
        calls.append(list(cmd))
        if override is not None:
            faked = override(list(cmd))
            if faked is not None:
                return faked
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(_gms.subprocess, "run", spy)
    return calls


def _subcommands(calls):
    return [cmd[cmd.index("-C") + 2] if "-C" in cmd else cmd[1] for cmd in calls]


def test_a_file_over_the_cap_is_refused_before_git_show_reads_it(tmp_path, monkeypatch):
    """הסירוב מגיע מ-``git cat-file -s``, ו-``git show`` אינו רץ כלל — אפס בתים נקראים."""
    svc, _ = _bare_mirror(tmp_path, {"big.bin": b"x" * 3000})
    calls = _spy_on_git(monkeypatch)

    out = svc.get_file_at_commit("probe", "big.bin", "HEAD", max_size=1000)

    assert out["error"] == "file_too_large" and out["size"] == 3000 and out["max_size"] == 1000
    assert "cat-file" in _subcommands(calls)
    assert "show" not in _subcommands(calls), f"git show רץ על קובץ שמעל התקרה: {calls}"


def test_a_file_under_the_cap_is_read_exactly_as_before(tmp_path, monkeypatch):
    """הבקרה: מתחת לתקרה התשובה זהה לזו של קודם — תוכן, קידוד, גודל, שורות, sha."""
    svc, sha = _bare_mirror(tmp_path, {"a.txt": "שלום\nעולם\n".encode("utf-8")})
    calls = _spy_on_git(monkeypatch)

    out = svc.get_file_at_commit("probe", "a.txt", "HEAD", max_size=1000)

    assert out["success"] and out["content"] == "שלום\nעולם\n" and out["is_binary"] is False
    assert out["encoding"] == "utf-8" and out["size"] == len("שלום\nעולם\n".encode("utf-8"))
    assert out["lines"] == 3 and out["resolved_commit"] == sha
    assert "show" in _subcommands(calls), "מתחת לתקרה הקובץ כן נקרא"


def test_a_missing_path_is_still_file_not_in_commit_through_the_probe(tmp_path):
    """git מדפיס את אותה הודעה ל-``cat-file -s`` ול-``show`` על נתיב חסר, והמפה אחת לשתיהן."""
    svc, _ = _bare_mirror(tmp_path, {"a.txt": b"x"})
    out = svc.get_file_at_commit("probe", "nope.txt", "HEAD")
    assert out == {"error": "file_not_in_commit", "message": "הקובץ לא קיים ב-commit זה"}


def test_both_commands_name_the_same_resolved_commit(tmp_path, monkeypatch):
    """בלי חלון בין הבדיקה לקריאה: שתי הפקודות פונות ל-``<sha>:<path>`` שנפתר פעם אחת, לא ל-``HEAD``."""
    svc, sha = _bare_mirror(tmp_path, {"a.txt": b"x"})
    calls = _spy_on_git(monkeypatch)

    svc.get_file_at_commit("probe", "a.txt", "HEAD")

    # ``rev-parse`` של אימות ה-ref רץ גם הוא עם ``-C``; כאן מעניינות רק שתי פקודות האובייקט.
    targets = {sub: cmd[-1] for cmd in calls if "-C" in cmd
               for sub in [cmd[cmd.index("-C") + 2]] if sub in ("cat-file", "show")}
    assert targets == {"cat-file": f"{sha}:a.txt", "show": f"{sha}:a.txt"}
    assert [s for s in _subcommands(calls) if s in ("cat-file", "show")] == ["cat-file", "show"], (
        "הבדיקה קודמת לקריאה — זה הסדר שהופך את max_size לחסם על מה שנקרא")


def test_a_failed_size_probe_never_falls_back_to_an_unbounded_read(tmp_path, monkeypatch):
    """כשל בבדיקת הגודל הוא סירוב, לא קריאה בלי תקרה — ``silent-fallback-to-worse-path``."""
    svc, _ = _bare_mirror(tmp_path, {"a.txt": b"x" * 3000})

    def fail_the_probe(cmd):
        if "cat-file" in cmd:
            return subprocess.CompletedProcess(cmd, 128, stdout=b"", stderr=b"fatal: object store unreadable")
        return None

    calls = _spy_on_git(monkeypatch, override=fail_the_probe)
    out = svc.get_file_at_commit("probe", "a.txt", "HEAD", max_size=10)

    assert out["error"] == "git_error" and "unreadable" in out["message"]
    assert "show" not in _subcommands(calls)


def test_a_non_numeric_size_is_a_failure_and_not_a_small_file(tmp_path, monkeypatch):
    """הפלט של git הוא קלט חיצוני (U3): "lots" אינו אפס, והוא אינו עובר את התקרה בשקט."""
    svc, _ = _bare_mirror(tmp_path, {"a.txt": b"x" * 3000})

    def garble_the_probe(cmd):
        if "cat-file" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"lots\n", stderr=b"")
        return None

    calls = _spy_on_git(monkeypatch, override=garble_the_probe)
    out = svc.get_file_at_commit("probe", "a.txt", "HEAD", max_size=10)

    assert out["error"] == "git_error"
    assert "show" not in _subcommands(calls)


def test_what_comes_back_never_exceeds_the_cap_whatever_the_probe_said(tmp_path, monkeypatch):
    """החסם השני, על מה שמוחזר: גם אם המאגר דיווח גודל קטן, מה ש-``git show`` הדפיס נבדק שוב.

    פין של תכונה שהייתה קיימת — הבדיקה בדיעבד — ונשארת בכוונה, כי לנתיב
    של תיקייה ``cat-file -s`` מודד את אובייקט העץ ואילו ``git show`` מדפיס
    רשימה מעוצבת. הדרך היחידה לבודד אותה היא מאגר שמשקר.
    """
    svc, _ = _bare_mirror(tmp_path, {"a.txt": b"x" * 3000})

    def understate_the_probe(cmd):
        if "cat-file" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"10\n", stderr=b"")
        return None

    _spy_on_git(monkeypatch, override=understate_the_probe)
    out = svc.get_file_at_commit("probe", "a.txt", "HEAD", max_size=1000)

    assert out["error"] == "file_too_large" and out["size"] == 3000
