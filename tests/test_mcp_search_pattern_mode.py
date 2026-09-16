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

**והשורש שמעליו: המצב נגזר מהנתונים.** ההיוריסטיקה ``_is_regex`` בדקה
אם השאילתה מכילה אחד מ-``.*+?[]{}()^$|\\`` והעבירה אותה ל-``-E`` בלי
שאיש ביקש — כלומר **תוכן** השאילתה החליף את הסמנטיקה שלה. ‏``dict[``
הפך ל-ERE פסול, ו-``a|b`` הפך לחלופה שמחזירה שורות בלי קו אנכי בכלל.
‏escape לא יכול לתקן את זה: אחריו אי אפשר לחפש רג'קס, ולפניו אי אפשר
לחפש מילולית. לכן המצב הוא היום פרמטר ``regex``, מילולי כברירת מחדל,
והטסטים כאן בודקים את שני הכיוונים — שאחד מהם לבדו אינו מבדיל בין
"תוקן" ל"נחסם".
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


# כל תו מיוחד יושב בשורה משלו עם מזהה ייחודי. הצורה ``a<תו>b`` נבחרה כדי
# שהיא תפריד בין שני המצבים: מילולית היא מתאימה לשורה **אחת**, ואילו
# כ-ERE הצורה ``a.b`` מתאימה לכולן — ולכן טסט שסופר שורה אחת מבדיל בין
# ``-F`` ל-``-E`` ולא רק בודק "נמצא משהו".
_METACHARS = [".", "*", "+", "?", "[", "]", "{", "}", "(", ")", "^", "$", "|", "\\"]
_META_CORPUS = "\n".join(
    f"mark{i:02d} a{ch}b" for i, ch in enumerate(_METACHARS, start=1)
) + "\n"


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

    **‏``regex=True`` מפורש כאן, וזה מה שהשתנה.** קודם שלוש השאילתות
    האלה הגיעו ל-``-E`` מעצמן, כי ההיוריסטיקה ראתה בהן תווים מיוחדים —
    וזה היה הבאג. היום הן מילוליות כברירת מחדל ופשוט עובדות, ולכן דפוס
    פסול מגיע רק ממי שביקש רג'קס במפורש. בלי ההצהרה הזאת הטסט היה
    מודד את הצד המילולי, שכבר נבדק ב-
    ``test_the_same_query_that_is_an_invalid_pattern_works_literally``.

    **מוטציה שמפילה:** להחזיר את ``returncode = process.returncode``
    במקום ה-``wait()`` — ואז ``returncode`` הוא ``None``, הבדיקה מדולגת,
    ושלושתן חוזרות ל-``results: []`` בלי ``error``. הורץ על הקוד שלפני
    התיקון וכל השלוש נפלו בדיוק כך.
    """
    svc = _build_mirror(tmp_path, {"sample.py": _SAMPLE})

    res = _search(svc, query, regex=True)

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

    res = _search(svc, "dict", ref="refs/heads/no-such-branch", regex=True)

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


# --------------------------------------------------------------------------
# מילולי כברירת מחדל, ורג'קס רק כשמבקשים
# --------------------------------------------------------------------------


@requires_git
@pytest.mark.parametrize("ch", _METACHARS, ids=lambda c: f"char={c!r}")
def test_a_special_character_in_the_query_is_just_a_character(tmp_path, ch):
    """כל תו מיוחד נמצא כמחרוזת, ומוצא בדיוק את השורה שמכילה אותו.

    הצורה ``a<תו>b`` מבדילה בין שני המצבים ולא רק מוודאת "נמצא משהו":
    מילולית היא מתאימה לשורה אחת, ואילו כ-ERE ``a.b`` מתאימה לכל
    ארבע-עשרה השורות ו-``a[b`` היא דפוס פסול שגיט דוחה.

    **מוטציה שמפילה:** להחזיר את ``-E`` כברירת מחדל — חמישה תווים
    (``[``, ``(``, ``)``, ``*``, ``+``, ``?``) מפילים את הטסט כשגיאת
    דפוס, והשאר מחזירים יותר משורה אחת.
    """
    svc = _build_mirror(tmp_path, {"meta.txt": _META_CORPUS})
    expected = f"mark{_METACHARS.index(ch) + 1:02d}"

    res = _search(svc, f"a{ch}b")

    assert "error" not in res, f"תו מילולי נדחה כדפוס: {res!r}"
    got = [r["content"] for r in res["results"]]
    assert len(got) == 1, f"התאמה מילולית חייבת להיות יחידה, קיבלנו {got!r}"
    assert got[0].startswith(expected)
    assert f"a{ch}b" in got[0]


@requires_git
def test_regex_true_still_reads_the_query_as_a_pattern(tmp_path):
    """היכולת לא נמחקה, רק הפסיקה להידלק מעצמה.

    בלי הטסט הזה, הטסט שמעליו היה עובר גם אם ``-E`` הוסר לגמרי — כלומר
    "תוקן" היה נראה זהה ל"נחסם".

    **מוטציה שמפילה:** להתעלם מ-``regex`` ולשלוח תמיד ``-F``.
    """
    svc = _build_mirror(tmp_path, {"sample.py": _SAMPLE})

    literal = _search(svc, "foo.*bar", regex=False)
    as_regex = _search(svc, "foo.*bar", regex=True)

    assert literal["results"] == [], "מילולית אין בקורפוס את המחרוזת הזאת"
    assert [r["content"] for r in as_regex["results"]] == ["fooXbar = 2"]


@requires_git
@pytest.mark.parametrize("query", ["dict[", "**", "(self"])
def test_the_same_query_that_is_an_invalid_pattern_works_literally(tmp_path, query):
    """שני הצדדים של אותו מטבע, ובלי שניהם אי אפשר לדעת מה קרה.

    ב-``regex=True`` גיט דוחה את הדפוס והתשובה היא ``invalid_pattern``;
    ב-``regex=False`` — ברירת המחדל — אותה שאילתה בדיוק מוצאת את השורות.
    טסט אחד לבדו לא היה מבדיל בין "תוקן" לבין "נחסם".

    **מוטציה שמפילה:** להחזיר את ההיוריסטיקה ``_is_regex``, שהייתה
    מעבירה את שלוש השאילתות האלה ל-``-E`` בלי שאיש ביקש.
    """
    svc = _build_mirror(tmp_path, {"sample.py": _SAMPLE})

    as_regex = _search(svc, query, regex=True)
    literal = _search(svc, query, regex=False)

    assert as_regex.get("error") == "invalid_pattern"
    assert "error" not in literal, f"מילולית זה חייב לעבוד: {literal!r}"
    assert literal["results"], f"{query!r} קיים בקורפוס ולא נמצא"
    assert all(query in r["content"] for r in literal["results"])


@requires_git
def test_leading_whitespace_in_the_query_is_not_trimmed_away(tmp_path):
    """חיפוש הזחה הוא שימוש אמיתי, ולכן השאילתה אינה מקוצצת.

    **שתי השורות נושאות את אותו טוקן בכוונה**, אחת מוזחת ואחת בשוליים.
    אילו הטוקן היה שונה ביניהן, הקיצוץ לא היה משנה את התוצאה והטסט היה
    עובר גם על קוד שמקצץ — נמדד, וזו בדיוק הגרסה הראשונה שלו.

    **מוטציה שמפילה:** להחזיר את ``query.strip()`` ב-
    ``search_with_git_grep`` — ואז החיפוש הופך ל-``return_x`` ושתי
    השורות חוזרות.
    """
    corpus = "    return_x = 1\nreturn_x = 2\n"
    svc = _build_mirror(tmp_path, {"s.py": corpus})

    res = _search(svc, "    return_x")

    assert "error" not in res
    assert [r["line"] for r in res["results"]] == [1], f"ההזחה קוצצה: {res!r}"


# --------------------------------------------------------------------------
# דרך ממשק ה-MCP עצמו
# --------------------------------------------------------------------------


class _StubRepoBackend:
    """דמה לשכבת ה-backend, כדי לבדוק את החיווט של הכלי ולא את git."""

    def __init__(self):
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "repo": kwargs["repo"], "query": kwargs["query"],
                "count": 0, "total": 0, "results": [], "truncated": False}


async def test_the_tool_passes_the_query_and_the_mode_through_untouched(monkeypatch):
    """מקצה לקצה דרך ``mcp.call_tool`` — מסלול שלא היה לו טסט כלל.

    בודק את שני הדברים שהשתנו בשכבה הזאת: ``regex`` מגיע עד הסוף,
    והשאילתה מגיעה **עם הרווחים שלה**.

    **מוטציה שמפילה:** להחזיר את ``q = (query or "").strip()``
    ב-``repo_handlers.search_repo``, או להשמיט את ``regex=regex``
    מהקריאה ב-``server.py``.
    """
    pytest.importorskip("mcp")
    import mcp_server.server as srv

    monkeypatch.setenv("ENVIRONMENT", "production")
    # ``require_admin`` מיובא לתוך ``server`` ונקרא כגלובל של המודול, ולכן
    # זו נקודת העקיפה. הכלי מוגדר ``[Admin]``, ו-``mcp._request_is_admin``
    # לבדו אינו מספיק כי ``require_admin`` דורש הקשר בקשה אמיתי.
    monkeypatch.setattr(srv, "require_admin", lambda ctx=None: 7)
    backend = _StubRepoBackend()
    mcp = srv.build_mcp(object(), repo_backend=backend)
    mcp._request_is_admin = lambda: True

    await mcp.call_tool(
        "codekeeper_search_repo",
        {"repo": "r", "query": "    return", "regex": True},
    )

    assert backend.calls, "הכלי לא הגיע ל-backend בכלל"
    call = backend.calls[0]
    assert call["query"] == "    return", "הרווחים קוצצו בדרך"
    assert call["regex"] is True


async def test_the_tool_defaults_to_literal_matching(monkeypatch):
    """בלי ``regex``, הכלי מבקש התאמה מילולית.

    **מוטציה שמפילה:** להחליף את ברירת המחדל של הפרמטר ל-``True``.
    """
    pytest.importorskip("mcp")
    import mcp_server.server as srv

    monkeypatch.setenv("ENVIRONMENT", "production")
    # ``require_admin`` מיובא לתוך ``server`` ונקרא כגלובל של המודול, ולכן
    # זו נקודת העקיפה. הכלי מוגדר ``[Admin]``, ו-``mcp._request_is_admin``
    # לבדו אינו מספיק כי ``require_admin`` דורש הקשר בקשה אמיתי.
    monkeypatch.setattr(srv, "require_admin", lambda ctx=None: 7)
    backend = _StubRepoBackend()
    mcp = srv.build_mcp(object(), repo_backend=backend)
    mcp._request_is_admin = lambda: True

    await mcp.call_tool("codekeeper_search_repo", {"repo": "r", "query": "dict["})

    assert backend.calls[0]["regex"] is False
