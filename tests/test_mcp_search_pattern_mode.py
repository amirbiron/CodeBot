"""חיפוש בריפו: כשל מפסיק להתחזות לאפס תוצאות.

**הבאג שהקובץ הזה שומר עליו.** ‏``codekeeper_search_repo`` החזיר
``{"ok": true, "count": 0}`` לשאילתה ``dict[`` — בזמן שהמחרוזת קיימת
ב-``mcp_server/repo_backend.py`` שש-עשרה פעמים. הסוכן שמקבל תשובה כזאת
מסיק שהמחרוזת אינה בקוד, וממשיך על סמך מסקנה שגויה.

**השרשרת.** ‏``git grep`` נכשל על דפוס פסול ויוצא בקוד 128, אבל
``_run_grep_with_streaming`` בדק ``process.returncode`` בלי שאיש מילא
אותו: הוא מתמלא רק אחרי ``poll()``/``wait()``, ובלולאת הקריאה ``poll()``
נקרא רק בענף ``not ready``. במסלול הרגיל — git יוצא, ‏``readline()``
מחזיר ``''`` והלולאה נשברת — הוא נשאר ``None``, הבדיקה דולגה, והכשל חזר
כרשימה ריקה בלי מפתח ``error``.

**ולמה לא די בלבדוק את קוד היציאה תמיד.** ללולאה שבעה מסלולים שהורגים
את התהליך **בכוונה** (timeout, ‏output_limit, וחמישה מסלולי תקרה). שם
קוד היציאה יכול להיות ``-9``, אבל גם ``0``/``1``/``128`` אם git הספיק
לצאת מעצמו רגע לפני ה-kill — ולכן הוא נבדק רק כשלא הרגנו, ולא "נבדק
ומסונן". הטסטים כאן מכסים את שני הצדדים: כשל שחייב להידלק, ועצירה
יזומה שחייבת להישאר שקטה.
"""

import shutil
import subprocess

import pytest

from services.git_mirror_service import _classify_grep_failure

_GIT = shutil.which("git")
requires_git = pytest.mark.skipif(_GIT is None, reason="git is not installed")

# כל שורה נושאת תו מיוחד אחד לפחות, כדי שכל שאילתה בטסטים תהיה מחרוזת
# שקיימת בקובץ באמת — ואפס תוצאות עליה יהיה בהכרח באג ולא תשובה נכונה.
_SAMPLE = "\n".join(
    [
        "def a(x: dict[str, int]) -> None:",
        "b: dict[str, str] = {}",
        "bold **here** and more",
        "c = foo(self)",
        "plain line without anything special",
        "    indented_return = 1",
        "fooXbar = 2",
    ]
) + "\n"


def _run(*args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True)


def _build_mirror(tmp_path, files: dict[str, str]):
    """בונה ריפו אמיתי ומשכפל אותו ל-mirror, ומחזיר ``GitMirrorService``.

    אותה צורה כמו ב-``tests/test_mcp_additive_params.py`` — כל הכתיבה
    מתחת ל-``tmp_path`` בלבד, לפי כלל ה-IO של הריפו.
    """
    from services.git_mirror_service import GitMirrorService

    work = tmp_path / "work"
    work.mkdir()
    for name, body in files.items():
        (work / name).write_text(body, encoding="utf-8")
    _run(_GIT, "init", "-q", "-b", "main", ".", cwd=work)
    _run(_GIT, "add", "-A", cwd=work)
    _run(_GIT, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init", cwd=work)
    _run(_GIT, "clone", "-q", "--mirror", str(work), str(tmp_path / "repo.git"), cwd=tmp_path)
    return GitMirrorService(base_path=str(tmp_path))


def _search(svc, query: str, **kw):
    kw.setdefault("max_results", 50)
    kw.setdefault("timeout", 10)
    kw.setdefault("ref", "refs/heads/main")
    return svc.search_with_git_grep(repo_name="repo", query=query, **kw)


# --------------------------------------------------------------------------
# המסווג — יחידה טהורה
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stderr, expected",
    [
        ("fatal: command line, 'dict[': Invalid regular expression", "invalid_pattern"),
        ("fatal: command line, '**': Invalid preceding regular expression", "invalid_pattern"),
        ("fatal: command line, '(self': Unmatched ( or \\(", "invalid_pattern"),
        ("fatal: bad revision 'refs/heads/nope'", "search_failed"),
        ("fatal: unable to read tree object", "search_failed"),
        ("", "search_failed"),
    ],
)
def test_the_classifier_blames_the_pattern_only_when_git_did(stderr, expected):
    """‏128 משותף לדפוס פסול ול-ref שבור, ורק ה-stderr מבדיל ביניהם.

    שלוש ההודעות הראשונות הן פלט אמיתי של git 2.43, הועתק מהרצה.

    **מוטציה שמפילה:** להחזיר ``invalid_pattern`` כברירת מחדל במקום
    ``search_failed`` — ואז ריפו פגום שולח את הקורא לתקן את הדפוס שלו,
    שהוא הדבר היחיד שאינו שבור אצלו.
    """
    assert _classify_grep_failure(stderr) == expected


# --------------------------------------------------------------------------
# כשל שחייב להידלק
# --------------------------------------------------------------------------


@requires_git
@pytest.mark.parametrize("query", ["dict[", "**", "(self"])
def test_a_pattern_git_rejects_returns_an_error_and_not_zero_results(tmp_path, query):
    """הבאג המדווח עצמו: דפוס שגיט דוחה חזר כרשימה ריקה.

    כל שלוש השאילתות קיימות בקורפוס כמחרוזת מילולית, ולכן "אפס תוצאות"
    עליהן אינו יכול להיות תשובה נכונה בשום מצב.

    **מוטציה שמפילה:** להחזיר את ``returncode = process.returncode``
    במקום ה-``wait()`` — ואז ``returncode`` הוא ``None``, הבדיקה מדולגת,
    ושלושתן חוזרות ל-``results: []`` בלי ``error``. הורץ על הקוד שלפני
    התיקון וכל השלוש נפלו בדיוק כך.
    """
    svc = _build_mirror(tmp_path, {"sample.py": _SAMPLE})

    res = _search(svc, query)

    assert res.get("error") == "invalid_pattern", f"נבלע: {res!r}"
    assert res.get("exit_code") == 128
    assert query in res.get("message", ""), "ההודעה חייבת לנקוב בדפוס שנדחה"
    assert res.get("query") == query


@requires_git
def test_an_engine_failure_is_not_blamed_on_the_pattern(tmp_path):
    """‏ref שאינו קיים יוצא גם הוא ב-128, והוא אינו באשמת הדפוס.

    **מוטציה שמפילה:** לסווג כל קוד יציאה גדול מ-1 כ-``invalid_pattern``.
    """
    svc = _build_mirror(tmp_path, {"sample.py": _SAMPLE})

    res = _search(svc, "dict", ref="refs/heads/no-such-branch")

    assert res.get("error") == "search_failed"
    assert res.get("error") != "invalid_pattern"


# --------------------------------------------------------------------------
# מה שחייב להישאר שקט
# --------------------------------------------------------------------------


@requires_git
def test_no_matches_is_still_a_success(tmp_path):
    """‏git grep מחזיר 1 כשאין התאמות, וזו תשובה תקינה ולא שגיאה.

    **מוטציה שמפילה:** להחליף את הפרדיקט ל-``returncode > 0``.
    """
    svc = _build_mirror(tmp_path, {"sample.py": _SAMPLE})

    res = _search(svc, "zzz_nothing_here_zzz")

    assert "error" not in res
    assert res["results"] == []


@requires_git
def test_a_deliberate_stop_is_not_reported_as_an_engine_error(tmp_path):
    """עצירה בתקרה היא החלטה שלנו, ולא כשל של git.

    **מוטציה שמפילה:** להחליף את ``len(results) >= max_results``
    ב-``>`` — הטסט הזה שומר על צורת התשובה במסלול התקרה: בדיוק תוצאה
    אחת, ‏``truncated`` דלוק, והסיבה הנכונה.

    **ומה הוא *אינו* מוכיח, כדי שלא ייקרא כיותר ממה שהוא:** הוא אינו
    מפיל לא את הסרת הדגל ``killed_by_us`` ולא את הסרת ענף ``< 0``.
    מול git אמיתי ההריגה שלנו נותנת ``-9``, וכל אחד משני המנגנונים
    בולע אותו לבדו. שניהם נבדקים בשני הטסטים שמתחת, עם דמה — כי git
    מאמת את הארגומנטים שלו לפני שהוא פולט, ולכן לעולם אינו גם פולט
    התאמות וגם נכשל, ואת הצירוף הזה אי אפשר לשחזר מולו.
    """
    svc = _build_mirror(tmp_path, {"sample.py": _SAMPLE})

    res = _search(svc, "dict", max_results=1)

    assert "error" not in res, f"עצירה יזומה דווחה ככשל: {res!r}"
    assert len(res["results"]) == 1
    assert res["truncated"] is True
    assert res["truncation_reason"] == "max_results"


class _FakeStdout:
    """זרם שמחזיר שורות מוכנות, ואין לו fd אמיתי.

    ‏``fileno`` זורק ``ValueError`` בכוונה: ``_run_grep_with_streaming``
    תופס אותו ונופל למסלול ``ready = [process.stdout]``, שהוא מסלול קיים
    בקוד ולא עוקף שנפתח בשביל הטסט.
    """

    def __init__(self, lines):
        self._lines = list(lines)

    def fileno(self):
        raise ValueError("no real fd")

    def readline(self):
        return self._lines.pop(0) if self._lines else ""

    def close(self):
        pass


class _FakeStderr:
    def __init__(self, text):
        self._text = text

    def read(self, n=-1):
        return self._text if n is None or n < 0 else self._text[:n]

    def close(self):
        pass


class _RacingProcess:
    """git שפלט שורות ואז יצא **מעצמו** בקוד כשל, רגע לפני ה-kill שלנו.

    זה החלון שהדגל ``killed_by_us`` קיים בשבילו, והוא אינו ניתן לשחזור
    מול git אמיתי: ‏``git grep`` מאמת את הארגומנטים שלו לפני שהוא פולט,
    ולכן לעולם לא גם פולט התאמות וגם נכשל. הדמה מייצרת בדיוק את הצירוף
    הזה, ובלעדיה הדגל היה קוד שאי אפשר להוכיח.
    """

    def __init__(self, lines, stderr_text, exit_code):
        self.stdout = _FakeStdout(lines)
        self.stderr = _FakeStderr(stderr_text)
        self._exit_code = exit_code
        self.returncode = None
        self.kill_calls = 0

    def kill(self):
        self.kill_calls += 1

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = self._exit_code
        return self._exit_code


def test_the_exit_code_is_ignored_once_we_stopped_the_child_ourselves(monkeypatch, tmp_path):
    """עצרנו בתקרה, וגיט במקרה יצא בכשל — התוצאות עדיין תקפות.

    מרגע שהרגנו את התהליך, קוד היציאה מתאר מרוץ ולא את החיפוש. כאן git
    פלט התאמה, אנחנו עצרנו בתקרה, ובאותו רגע הוא יצא ב-128 עם הודעת
    דפוס. בלי הדגל, חיפוש שהצליח לחלוטין היה מדווח כ-``invalid_pattern``
    — כלומר בדיוק ההאשמה השגויה שה-PR הזה בא למנוע.

    **מוטציה שמפילה:** להחליף את ``if not killed_by_us`` ב-``if True``.
    """
    from services import git_mirror_service as gms

    proc = _RacingProcess(
        lines=["sample.py\n", "1:alpha\n", "2:beta\n"],
        stderr_text="fatal: command line, 'x[': Invalid regular expression",
        exit_code=128,
    )
    monkeypatch.setattr(gms.subprocess, "Popen", lambda *a, **k: proc)

    svc = gms.GitMirrorService(base_path=str(tmp_path))
    res = svc._run_grep_with_streaming(
        ["git", "grep", "-n", "x"], tmp_path, max_results=1, timeout=10
    )

    assert proc.kill_calls >= 1, "הטסט לא הגיע בכלל למסלול העצירה היזומה"
    assert "error" not in res, f"עצירה יזומה הואשמה ככשל דפוס: {res!r}"
    assert res["results"] == [{"path": "sample.py", "line": 1, "content": "alpha"}]
    assert res["truncated"] is True
    assert res["truncation_reason"] == "max_results"


def test_a_child_killed_from_outside_is_reported_as_truncated_and_not_as_success(
    monkeypatch, tmp_path
):
    """‏git שנהרג מבחוץ — OOM למשל — החזיר עד היום "אפס תוצאות" שקט.

    זה המקרה השלישי של אותו באג, והוא אינו היפותטי: השירות רץ ב-Render
    עם תקרת זיכרון, וה-OOM killer שולח SIGKILL. התוצאות במקרה כזה הן
    חלקיות, והתשובה חייבת לומר זאת ולא להציג אותן כסריקה שהושלמה.

    כאן אין קריאה ל-``kill`` שלנו: הזרם נגמר מעצמו, ולכן ``killed_by_us``
    כבוי וקוד היציאה **כן** נבדק — ויוצא ``-9``.

    **מוטציה שמפילה:** להסיר את ענף ``returncode < 0`` — ואז ``-9``
    אינו גדול מ-1, שום ענף לא נדלק, והתשובה חוזרת ``truncated: False``
    כאילו הסריקה נגמרה כרגיל.
    """
    from services import git_mirror_service as gms

    proc = _RacingProcess(
        lines=["sample.py\n", "1:alpha\n"],
        stderr_text="",
        exit_code=-9,
    )
    monkeypatch.setattr(gms.subprocess, "Popen", lambda *a, **k: proc)

    svc = gms.GitMirrorService(base_path=str(tmp_path))
    res = svc._run_grep_with_streaming(
        ["git", "grep", "-n", "x"], tmp_path, max_results=50, timeout=10
    )

    assert proc.kill_calls == 0, "הטסט נועד למסלול שבו *לא* אנחנו עצרנו"
    assert "error" not in res, "הריגה חיצונית אינה שגיאת דפוס ואינה כשל מנוע"
    assert res["truncated"] is True, f"תוצאות חלקיות הוצגו כסריקה שלמה: {res!r}"
    assert res["truncation_reason"] == "process_killed"
    assert res["results"] == [{"path": "sample.py", "line": 1, "content": "alpha"}]
