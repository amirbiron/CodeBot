"""הבדיקה שמונעת מקבצי bytecode להיכנס לגיט — נבדקת על שני הקצוות.

**המקרה שהוליד את זה.** ``git checkout origin/main -- .`` בסשן של
PR #3401 החזיר **11 קבצי ``.pyc``** ל-index — בדיוק אלה ש-#3395 הסיר.
ה-``origin/main`` המקומי היה snapshot מלפני אותו תיקון, ו-``checkout``
מ-ref אינו מתייעץ עם ``.gitignore``: הוא משחזר את מה שהיה שם. ה-
``git add -A`` שאחריו קומיט אותם בלי מילה, כי קובץ שכבר ב-index אינו
"חדש" ו-``.gitignore`` אינו נשאל עליו יותר.

**למה בדיקה ולא רק תיקון.** זו הפעם השנייה: #3395 הסיר את אותם קבצים,
והם חזרו פחות משבוע אחרי. תיקון ידני מסיר את המופע; בדיקה מסירה את
המחלקה.

**שני הקצוות, כי אחד לבדו אינו ראיה.** בדיקה שרצה רק על ריפו נקי
מוכיחה שהיא לא צועקת סתם — ולא שהיא מסוגלת לצעוק בכלל. לכן יש כאן גם
ריפו גיט אמיתי שנבנה תחת ``tmp_path`` עם ``.pyc`` אחד, והבדיקה חייבת
ליפול עליו.

כל הכתיבה מתבצעת תחת ``tmp_path``. הריפו של הפרויקט נקרא בלבד
(``git ls-files`` / ``git ls-tree``), ושום בדיקה כאן אינה כותבת או
מוחקת בו.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_no_committed_pyc.py"


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=60
    ).stdout


@pytest.fixture
def repo_with_pyc(tmp_path: Path) -> Path:
    """ריפו גיט אמיתי תחת ``tmp_path``, עם קובץ ``.pyc`` אחד בקומיט.

    **ריפו אמיתי ולא רשימת נתיבים מזויפת.** הבדיקה שואלת את git מה
    במעקב, ולכן דמה שמחזירה מחרוזות הייתה בודקת את עצמה. כאן הקובץ
    באמת עובר את ``.gitignore``, באמת נכנס ל-index, ובאמת מקומט — כלומר
    המסלול שהבדיקה אמורה לתפוס.

    ``-f`` ב-``git add`` מדמה בדיוק את מה שקרה: ``.gitignore`` מכיל
    ``__pycache__/`` ובכל זאת הקובץ נכנס. הצורה האמיתית הייתה
    ``git checkout <ref> -- .``, ושתיהן מגיעות לאותו מצב — קובץ אסור
    ב-index.
    """
    repo = tmp_path / "repo"
    (repo / "__pycache__").mkdir(parents=True)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    (repo / "__pycache__" / "a.cpython-311.pyc").write_bytes(b"\x00\x01bytecode")

    _git("init", "-q", ".", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "test", cwd=repo)
    _git("add", "-A", "-f", cwd=repo)
    _git("commit", "-q", "-m", "עם bytecode", cwd=repo)
    return repo


def test_the_check_fails_on_a_branch_that_carries_a_pyc(repo_with_pyc: Path):
    """הקצה שמוכיח שהבדיקה מסוגלת ליפול.

    שלוש טענות: קוד יציאה, שם הקובץ בפלט, וההסבר על ``.gitignore``.
    השלישית אינה קישוט — מי שרואה "קובץ .pyc בגיט" ומסתכל ב-
    ``.gitignore`` מוצא שם ``__pycache__/`` ומסיק שהבדיקה שבורה. ההסבר
    הוא מה שמפנה אותו למסלול האמיתי במקום למסע סרק.
    """
    result = _run(cwd=repo_with_pyc)

    assert result.returncode == 1, (
        f"הבדיקה עברה על ריפו שמכיל .pyc — היא אינה מסוגלת ליפול.\n"
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "a.cpython-311.pyc" in result.stderr, result.stderr
    assert ".gitignore אינו מונע את זה" in result.stderr, (
        "הכשל אינו מסביר למה .gitignore לא עזר — הקורא ילך למקום הלא נכון.\n"
        "הטענה היא על המשפט ולא על המילה ``.gitignore`` לבדה, שמופיעה "
        f"בהודעה בכמה הקשרים:\n{result.stderr}"
    )
    assert "git rm -r --cached" in result.stderr, "אין הוראת תיקון"


def test_the_check_passes_on_the_projects_main(repo_with_pyc: Path):
    """הקצה השני: ``main`` של הפרויקט נקי, והבדיקה שותקת עליו.

    בלי הטענה הזו, בדיקה שמחזירה 1 תמיד הייתה "עוברת" את הבדיקה שמעל
    ונראית תקינה — ואז מפילה כל PR.

    ``origin/main`` ולא ``main``: בקלון של CI קיים רק ה-remote ref.
    כשאין אף אחד מהם (עומק שיבוט 1, או clone חלקי) הבדיקה מדולגת במקום
    להיכשל, כי מה שנבדק כאן הוא הכלל — לא הזמינות של ה-ref.

    ``repo_with_pyc`` נדרש כאן במכוון אף שאינו בשימוש: הוא מוודא
    שהפיקסצ'ר באמת בנה ריפו במקום אחר, ושהבדיקה הזו אינה נשענת על
    ``cwd`` ששרד מבדיקה קודמת.
    """
    ref = None
    for candidate in ("origin/main", "main"):
        try:
            _git("rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}", cwd=REPO_ROOT)
            ref = candidate
            break
        except subprocess.CalledProcessError:
            continue
    if ref is None:
        pytest.skip("אין ref של main בקלון הזה")

    result = _run("--ref", ref, cwd=REPO_ROOT)

    assert result.returncode == 0, (
        f"main של הפרויקט מכיל קבצי bytecode, והבדיקה תפיל כל PR:\n{result.stderr}"
    )


def test_the_working_tree_is_clean_right_now():
    """העץ שה-CI יבדוק בפועל — כלומר ה-PR הזה עצמו.

    ``main`` יכול להיות נקי בזמן שהענף הנוכחי אינו, וזה בדיוק המצב
    שקרה: הקבצים נכנסו בענף ולא ב-main. הבדיקה שמעל לא הייתה תופסת
    אותו.
    """
    result = _run(cwd=REPO_ROOT)

    assert result.returncode == 0, result.stderr


def test_a_directory_that_merely_contains_the_cache_name_is_not_flagged():
    """``__pycache__`` נבדק כרכיב נתיב שלם, לא כתת-מחרוזת.

    בלי זה, ``tools/my__pycache__helpers/run.py`` היה נדחה — קובץ מקור
    לגיטימי שנפסל על שם תיקייה. זה הצד השני של כל בדיקת איסור: מה
    שהיא **לא** אמורה לתפוס.

    נבדק על הפונקציה הטהורה ולא דרך git, כי השאלה כאן היא על כלל
    ההתאמה ולא על מצב הריפו.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from check_no_committed_pyc import offending_paths
    finally:
        sys.path.pop(0)

    allowed = [
        "tools/my__pycache__helpers/run.py",
        "docs/__pycache__notes.md",
        "a/pycache/b.py",
        "src/recompyced.py",
    ]
    assert offending_paths(allowed) == [], offending_paths(allowed)

    flagged = [
        "__pycache__/a.cpython-311.pyc",
        "deep/nested/__pycache__/b.pyc",
        "stray.pyc",
        "legacy.pyo",
    ]
    assert offending_paths(flagged) == sorted(flagged)


def test_anything_under_the_cache_directory_is_flagged_even_without_a_pyc_suffix():
    """התיקייה נפסלת בזכות עצמה, ולא רק בזכות הסיומת שבתוכה.

    **המוטציה שחשפה את הפער:** הסרת בדיקת ``__pycache__`` לגמרי עברה את
    כל שאר הקובץ, כי כל הקבצים בבדיקות מסתיימים ממילא ב-``.pyc`` —
    הסיומת תפסה אותם והתיקייה מעולם לא נבדקה בפועל. זה כיסוי מדומה:
    שני חצאי הכלל נראו נבדקים, ואחד מהם לא היה.

    נתיב תחת ``__pycache__/`` בלי סיומת bytecode הוא נדיר אבל אמיתי —
    ``.gitkeep`` שמישהו שם שם, קובץ זמני של כלי, פלט של פרופיילר.
    הוא שייך לגיט בדיוק כמו השאר: לא.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from check_no_committed_pyc import offending_paths
    finally:
        sys.path.pop(0)

    without_suffix = [
        "__pycache__/.gitkeep",
        "__pycache__/notes.txt",
        "src/__pycache__/leftover",
    ]
    assert offending_paths(without_suffix) == sorted(without_suffix)


def test_a_failure_to_read_git_is_not_reported_as_clean(tmp_path: Path):
    """כשגיט אינו זמין, הבדיקה **אינה** מחזירה "נקי".

    ``CRITICAL-PATTERNS.md`` K11: הכשל כאן מגיע בערך החזרה ולא בחריגה,
    ובדיקה שבולעת אותו ומחזירה 0 מדווחת הצלחה על משהו שמעולם לא רץ. ה-CI
    היה ירוק, ואיש לא היה יודע שהשער כבוי.

    ``2`` ולא ``1``, כדי שאפשר יהיה להבדיל בין "נמצאו קבצים" לבין "לא
    הצלחתי לבדוק" — שתי תשובות שונות שדורשות שתי פעולות שונות. הטענה
    כאן היא רק שהתשובה **אינה** 0; היא לא כובלת את הערך המדויק מעבר לכך
    שהוא מסמן כשל.
    """
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    (not_a_repo / "a.py").write_text("x = 1\n", encoding="utf-8")

    result = _run(cwd=not_a_repo)

    assert result.returncode != 0, (
        "הבדיקה דיווחה 'נקי' בתיקייה שאינה ריפו גיט — כלומר היא מדווחת "
        f"הצלחה על בדיקה שלא רצה.\nstdout={result.stdout!r}"
    )
    assert "git" in result.stderr.lower(), result.stderr


@pytest.fixture
def repo_with_awkward_pyc_names(tmp_path: Path) -> Path:
    """ריפו עם שני קבצי ``.pyc`` שגיט **מצטט** בפלט הרגיל שלו.

    ``line\\nbreak.pyc`` — שורה חדשה בשם. ``שלום.pyc`` — לא-ASCII, שגיט מצטט
    כברירת מחדל (``core.quotePath``). בשני המקרים ``git ls-files`` בלי ``-z``
    מדפיס ``"..."`` עם escape-ים, והשם המודפס מסתיים במירכאה ולא ב-``.pyc``.
    השני הוא המקרה הריאלי כאן: שמות בעברית נפוצים בריפו הזה.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    (repo / "line\nbreak.pyc").write_bytes(b"\x00\x01")
    (repo / "שלום.pyc").write_bytes(b"\x00\x01")

    _git("init", "-q", ".", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "test", cwd=repo)
    _git("add", "-A", "-f", cwd=repo)
    _git("commit", "-q", "-m", "awkward names", cwd=repo)
    return repo


@pytest.mark.parametrize("extra_args", [[], ["--ref", "HEAD"]], ids=["index", "ref"])
def test_paths_git_would_quote_are_still_caught(repo_with_awkward_pyc_names: Path, extra_args):
    """נתיב עם שורה חדשה או עברית נתפס — בשני מסלולי הקריאה.

    **הבאג שנתפס בסקירה:** בלי ``-z`` גיט מצטט, ``splitlines()`` החזיר
    ``"line\\nbreak.pyc"`` עם המירכאות, ``endswith(".pyc")`` נכשל על ``"``,
    והקובץ עבר. אומת על הגרסה הקודמת של הסקריפט: שני הקבצים האלה עברו
    אותה ב-exit 0, גם ב-index וגם ב-``--ref``. שני המסלולים נבדקים כי הם
    שתי פקודות git שונות (``ls-files`` / ``ls-tree``), וכל אחת צריכה את
    ה-``-z`` שלה.
    """
    result = _run(*extra_args, cwd=repo_with_awkward_pyc_names)

    assert result.returncode == 1, (
        f"קובץ .pyc עם שם שגיט מצטט עבר את הבדיקה: stderr={result.stderr!r}"
    )
    assert "break.pyc" in result.stderr, result.stderr
    assert "שלום.pyc" in result.stderr, result.stderr
