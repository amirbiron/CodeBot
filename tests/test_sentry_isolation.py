"""בידוד Sentry בין בדיקות (``tests/_sentry_isolation.py``), נבדק כמו שהוא רץ — בתוך ריצת pytest.

**למה יש קובץ שלם על זה.** טסט הטפטוף של ``PUT /api/agent/upload`` נפל רק
בריצה הסדרתית של ``deploy.yml``, רק אחרי שתי בדיקות אחרות, ובמקום שלא היה
קשור לשום דבר מהן: בדיקה אחת השאירה ``SENTRY_DSN`` בסביבה, בדיקה אחרת טענה
מחדש את ``main`` ומשם נדלק Sentry אמיתי, ואינטגרציית ה-Starlette שלו תקעה את
טסט הטפטוף. הקובץ הזה מקבע שבדיקה כזו נכשלת **בשמה**, ושהבאה אחריה מתחילה
נקייה.

**למה תת-תהליך.** מה שנבדק קורה *בין* בדיקות, ואת זה אי אפשר לשאול מתוך אותה
ריצה. כל בדיקה כאן מריצה סשן pytest פנימי ב-``tmp_path``, עם ``pytest.ini`` ריק
משלו — כך ש-``addopts`` וה-conftest של הריפו אינם נטענים — והפלאגין נטען
במפורש ב-``-p``, בדיוק כמו שהוא נרשם בריצה האמיתית.

**והמוטציה היא חלק מהקובץ ולא הערה בצד.** לכל תרחיש יש גם ריצה בלי הפלאגין,
שמוודאת שהדליפה *כן* עוברת לבדיקה הבאה. בלעדיה אין ראיה שהתרחיש בכלל משחזר את
הבעיה, והבדיקה עם הפלאגין הייתה עוברת גם על קוד שאינו עושה כלום.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import _sentry_isolation

_TESTS_DIR = Path(__file__).resolve().parent

#: תקציב לתת-התהליך. סשן פנימי של שתי בדיקות נגמר בשנייה; התקרה קיימת כדי
#: שסשן תקוע ייכשל כאן בשמו ולא יתקע את הסוויטה.
_OUTER_BUDGET = 120

#: כתובת שלא תיפתר לעולם: ``.invalid`` שמור לכך (RFC 6761), כך ששום אירוע לא
#: יוצא החוצה גם אם משהו כן ינסה לשלוח.
_FAKE_DSN = "https://public@example.invalid/1"

_NEXT_STARTS_CLEAN = f"""

def test_next_one_starts_clean():
    assert {_sentry_isolation.DSN_ENV!r} not in os.environ
"""

#: שתי הצורות של הדליפה, כפי שהופיעו בריפו: השמה ישירה (``test_chatops_stage7.py``),
#: והשמה ישירה ש"מנוקה" ב-``monkeypatch.delenv`` — שזוכר את הערך שמצא ומחזיר
#: אותו בסוף הבדיקה (``test_db_sentry_checks.py``).
_LEAKS = {
    "direct_write": f"""
import os


def test_leaks_the_dsn():
    os.environ[{_sentry_isolation.DSN_ENV!r}] = {_FAKE_DSN!r}
""",
    "delenv_after_a_direct_write": f"""
import os


def test_leaks_the_dsn(monkeypatch):
    os.environ[{_sentry_isolation.DSN_ENV!r}] = {_FAKE_DSN!r}
    monkeypatch.delenv({_sentry_isolation.DSN_ENV!r})
""",
}

_LIVE_CLIENT = """
import sentry_sdk
from sentry_sdk.transport import Transport


class _Drop(Transport):
    def capture_envelope(self, envelope):
        pass


def test_leaves_a_live_client():
    sentry_sdk.init(
        dsn=%r,
        transport=_Drop(),
        default_integrations=False,
        auto_enabling_integrations=False,
    )
    assert sentry_sdk.get_client().is_active()


def test_next_one_starts_without_a_client():
    assert not sentry_sdk.get_client().is_active()
""" % (_FAKE_DSN,)


#: שני לקוחות אמיתיים, כל אחד ב-scope אחר. ``Scope.get_client`` מחזיר רק את
#: הראשון מביניהם (current קודם ל-global), ולכן שומר שסוגר את "הלקוח" היה
#: משאיר את השני פתוח, עם החוטים שלו.
_TWO_CLIENTS = """
import sentry_sdk
from sentry_sdk.transport import Transport

_CLIENTS = []


class _Drop(Transport):
    def capture_envelope(self, envelope):
        pass


def _client():
    return sentry_sdk.Client(
        dsn=%r,
        transport=_Drop(),
        default_integrations=False,
        auto_enabling_integrations=False,
    )


def test_leaves_two_clients_in_two_scopes():
    current, global_ = _client(), _client()
    _CLIENTS.extend([current, global_])
    sentry_sdk.get_current_scope().set_client(current)
    sentry_sdk.get_global_scope().set_client(global_)


def test_next_one_finds_both_closed():
    assert len(_CLIENTS) == 2
    assert [c.transport for c in _CLIENTS] == [None, None]
    assert not sentry_sdk.get_client().is_active()
""" % (_FAKE_DSN,)

#: הניקוי שהתיעוד ממליץ עליו, מול ``close()`` לבדו. לקוח סגור שעדיין רשום
#: ב-scope ממשיך להיחשב פעיל, ולכן רק הראשון עובר.
_CLEANUP_WAYS = """
import sentry_sdk
from sentry_sdk.transport import Transport

import _sentry_isolation


class _Drop(Transport):
    def capture_envelope(self, envelope):
        pass


def _init():
    sentry_sdk.init(
        dsn=%r,
        transport=_Drop(),
        default_integrations=False,
        auto_enabling_integrations=False,
    )


def test_cleans_up_with_shut_down_sentry():
    _init()
    _sentry_isolation.shut_down_sentry()


def test_only_closes():
    _init()
    sentry_sdk.get_client().close()


def test_next_one_starts_without_a_client():
    assert not sentry_sdk.get_client().is_active()
""" % (_FAKE_DSN,)


def _inner_env(env_extra: dict[str, str] | None = None) -> dict[str, str]:
    """הסביבה לריצה הפנימית: בלי משתני ``PYTEST_*`` של הריצה החיצונית, ובלי כתובת.

    ``PYTEST_ADDOPTS`` היה משנה את הדגלים, ו-``PYTEST_XDIST_WORKER`` ודומיו היו
    מציגים לריצה הפנימית תהליך xdist שאינו קיים. כתובת נכנסת רק דרך ``env_extra``.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env.pop(_sentry_isolation.DSN_ENV, None)
    env.update(env_extra or {})
    return env


def _run_inner(workdir: Path, body: str, *, with_guard: bool, env_extra: dict[str, str] | None = None) -> str:
    """מריץ את ``body`` כקובץ בדיקות בסשן pytest נפרד, ומחזיר את כל הפלט.

    ``-B`` כדי שהפייתון הפנימי לא יכתוב ``__pycache__`` לתוך ``tests/`` כשהוא
    מייבא משם את הפלאגין.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (workdir / "test_inner.py").write_text(body, encoding="utf-8")

    env = _inner_env(env_extra)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(_TESTS_DIR), env.get("PYTHONPATH", "")) if p)

    args = [sys.executable, "-B", "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider"]
    if with_guard:
        args += ["-p", "_sentry_isolation"]
    args.append("test_inner.py")

    finished = subprocess.run(
        args, cwd=workdir, env=env, capture_output=True, text=True, timeout=_OUTER_BUDGET
    )
    return finished.stdout + finished.stderr


@pytest.mark.parametrize("leak", sorted(_LEAKS))
def test_a_test_that_leaves_the_dsn_errors_in_its_own_name_and_the_next_starts_clean(tmp_path, leak):
    output = _run_inner(tmp_path, _LEAKS[leak] + _NEXT_STARTS_CLEAN, with_guard=True)

    assert "ERROR test_inner.py::test_leaks_the_dsn" in output, (
        f"הבדיקה שהשאירה את הכתובת לא נכשלה בשמה:\n{output}"
    )
    assert _sentry_isolation.REPORT_PREFIX in output and "monkeypatch.setenv" in output, (
        f"הכישלון אינו אומר מה לעשות במקום:\n{output}"
    )
    assert "PASSED test_inner.py::test_next_one_starts_clean" in output, (
        f"הבדיקה הבאה ירשה את הכתובת:\n{output}"
    )


@pytest.mark.parametrize("leak", sorted(_LEAKS))
def test_without_the_guard_the_dsn_does_reach_the_next_test(tmp_path, leak):
    """המוטציה: אותו סשן בלי הפלאגין. כך נראה ה-main לפני התיקון."""
    output = _run_inner(tmp_path, _LEAKS[leak] + _NEXT_STARTS_CLEAN, with_guard=False)

    assert "FAILED test_inner.py::test_next_one_starts_clean" in output, (
        f"בלי הפלאגין הכתובת לא הגיעה לבדיקה הבאה — התרחיש אינו משחזר את הדליפה:\n{output}"
    )


def test_a_test_that_uses_monkeypatch_setenv_is_not_flagged(tmp_path):
    """הצד השני של אותה בדיקה: הפלאגין בודק *אחרי* ש-``monkeypatch`` שחזר את הסביבה.

    אילו הבדיקה רצה לפני פירוק הפיקסצ'רים, כל בדיקה שעושה את הדבר הנכון הייתה
    נכשלת כאן.
    """
    body = f"""
import os


def test_sets_the_dsn_the_right_way(monkeypatch):
    monkeypatch.setenv({_sentry_isolation.DSN_ENV!r}, {_FAKE_DSN!r})
""" + _NEXT_STARTS_CLEAN
    output = _run_inner(tmp_path, body, with_guard=True)

    assert "ERROR test_inner.py::" not in output and "2 passed" in output, (
        f"בדיקה שהשתמשה ב-monkeypatch.setenv נתפסה כדולפת:\n{output}"
    )


def test_a_test_that_leaves_a_live_client_errors_and_the_next_starts_without_one(tmp_path):
    output = _run_inner(tmp_path, _LIVE_CLIENT, with_guard=True)

    assert "ERROR test_inner.py::test_leaves_a_live_client" in output, (
        f"הבדיקה שהשאירה לקוח חי לא נכשלה בשמה:\n{output}"
    )
    assert "PASSED test_inner.py::test_next_one_starts_without_a_client" in output, (
        f"הבדיקה הבאה ירשה לקוח חי:\n{output}"
    )


def test_without_the_guard_a_live_client_does_reach_the_next_test(tmp_path):
    output = _run_inner(tmp_path, _LIVE_CLIENT, with_guard=False)

    assert "FAILED test_inner.py::test_next_one_starts_without_a_client" in output, (
        f"בלי הפלאגין הלקוח לא נשאר חי — התרחיש אינו משחזר את הדליפה:\n{output}"
    )


def test_two_clients_in_two_scopes_are_both_closed(tmp_path):
    """כל לקוח ששייך לאחד משלושת ה-scopes נסגר, ולא רק זה ש-``get_client`` מחזיר."""
    output = _run_inner(tmp_path, _TWO_CLIENTS, with_guard=True)

    assert "ERROR test_inner.py::test_leaves_two_clients_in_two_scopes" in output, (
        f"הבדיקה שהשאירה שני לקוחות לא נכשלה בשמה:\n{output}"
    )
    assert "PASSED test_inner.py::test_next_one_finds_both_closed" in output, (
        f"אחד הלקוחות נותק ולא נסגר, או נשאר פעיל:\n{output}"
    )


def test_the_recommended_cleanup_passes_and_close_alone_does_not(tmp_path):
    """הניקוי שבתיעוד ובהודעת הכישלון — ``shut_down_sentry`` — באמת מספיק, ו-``close()`` לבדו לא.

    ``_Client.is_active`` מחזיר ``True`` תמיד (sentry-sdk 2.42.1), ולכן לקוח
    סגור שעדיין רשום ב-scope נשאר "פעיל" בעיני ``get_client``. הבדיקה מקבעת את
    ההנחיה עצמה: אילו היא הייתה שגויה, מי שהולך לפיה היה נכשל בשומר.
    """
    output = _run_inner(tmp_path, _CLEANUP_WAYS, with_guard=True)

    assert "PASSED test_inner.py::test_cleans_up_with_shut_down_sentry" in output, (
        f"הניקוי המומלץ לא עבר:\n{output}"
    )
    assert "ERROR test_inner.py::test_cleans_up_with_shut_down_sentry" not in output, (
        f"השומר תפס בדיקה שניקתה בדרך המומלצת:\n{output}"
    )
    assert "ERROR test_inner.py::test_only_closes" in output, (
        f"close() לבדו עבר — כלומר ההבדל שהתיעוד מסביר אינו קיים:\n{output}"
    )
    assert "PASSED test_inner.py::test_next_one_starts_without_a_client" in output, (
        f"הבדיקה הבאה ירשה לקוח חי:\n{output}"
    )


def test_a_dsn_from_the_outer_environment_never_reaches_the_tests(tmp_path):
    """כתובת אמיתית מהמעטפת של מי שמריץ — או מסוד ב-CI — אינה מגיעה לאף בדיקה."""
    body = "import os\n" + _NEXT_STARTS_CLEAN
    env_extra = {_sentry_isolation.DSN_ENV: _FAKE_DSN}

    with_guard = _run_inner(tmp_path / "with", body, with_guard=True, env_extra=env_extra)
    without_guard = _run_inner(tmp_path / "without", body, with_guard=False, env_extra=env_extra)

    assert "PASSED test_inner.py::test_next_one_starts_clean" in with_guard, (
        f"הכתובת מהסביבה החיצונית הגיעה לבדיקה:\n{with_guard}"
    )
    assert "FAILED test_inner.py::test_next_one_starts_clean" in without_guard, (
        f"בלי הפלאגין הכתובת לא הגיעה — התרחיש אינו משחזר את המצב:\n{without_guard}"
    )


def test_no_dsn_is_in_the_environment_while_tests_run():
    """בריצה רגילה זה נכון מאליו, כי אין כתובת. המשמעות היא כשמריצים את הבדיקה
    הזו עם ``SENTRY_DSN`` בסביבה — וזה בדיוק מה שהבדיקה הבאה עושה."""
    assert _sentry_isolation.DSN_ENV not in os.environ


def test_through_the_real_conftest_a_dsn_from_the_outer_environment_is_removed(tmp_path):
    """ההסרה בתחילת הריצה עובדת גם במסלול שבו הפלאגין נרשם בפועל — מתוך ``tests/conftest.py``.

    הבדיקה שמעליה טוענת את הפלאגין ב-``-p``, כלומר לפני ``pytest_configure``.
    בריצה האמיתית הוא נרשם **בתוך** ``pytest_configure`` של ה-conftest, והטענה
    שה-``pytest_configure`` שלו רץ גם אז נשענת על כך ש-pluggy מריץ hook
    היסטורי על פלאגין שנרשם אחרי הקריאה (``HookCaller.call_historic`` ו-
    ``_maybe_apply_history``, pluggy 1.6.0). כאן זה נמדד ולא מונח: pytest רץ
    מתוך שורש הריפו, עם ה-conftest-ים האמיתיים וכתובת בסביבה.

    ``-B`` ו-``cache_dir`` ב-``tmp_path`` כדי שהריצה לא תכתוב לתוך הריפו, ו-
    ``addopts`` ריק כדי שלא תמדוד כיסוי.
    """
    target = "tests/test_sentry_isolation.py::test_no_dsn_is_in_the_environment_while_tests_run"
    finished = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "-rA", "-o", "addopts=",
         "-o", f"cache_dir={tmp_path / 'pytest_cache'}", target],
        cwd=_TESTS_DIR.parent,
        env=_inner_env({_sentry_isolation.DSN_ENV: _FAKE_DSN}),
        capture_output=True,
        text=True,
        timeout=_OUTER_BUDGET,
    )
    output = finished.stdout + finished.stderr

    assert f"PASSED {target}" in output, f"הכתובת מהסביבה החיצונית הגיעה לבדיקה בריצה האמיתית:\n{output}"


def test_when_the_teardown_itself_fails_the_finding_rides_on_its_error(tmp_path):
    """‏teardown שנכשל בעצמו: השגיאה שלו עולה, הבידוד משוחזר, ומה שנמצא מוצמד אליה.

    אילו מה שנמצא היה נזרק כאן, הוא היה מסתיר את השגיאה המקורית; אילו נבלע,
    הדליפה הייתה נעלמת. ההערה (PEP 678) מציגה את שניהם.
    """
    body = f"""
import os

import pytest


@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("the fixture's own teardown failed")


def test_leaks_and_its_teardown_fails(broken_teardown):
    os.environ[{_sentry_isolation.DSN_ENV!r}] = {_FAKE_DSN!r}
""" + _NEXT_STARTS_CLEAN
    output = _run_inner(tmp_path, body, with_guard=True)

    assert "the fixture's own teardown failed" in output, (
        f"השגיאה המקורית של ה-teardown לא הגיעה לדיווח:\n{output}"
    )
    assert f"{_sentry_isolation.REPORT_PREFIX} {_sentry_isolation.DSN_ENV}" in output, (
        f"הדליפה לא הוצמדה לשגיאה של ה-teardown:\n{output}"
    )
    assert "PASSED test_inner.py::test_next_one_starts_clean" in output, (
        f"הבידוד לא שוחזר אחרי teardown שנכשל:\n{output}"
    )


def test_the_guard_covers_tests_outside_the_tests_directory(request):
    """הפלאגין רשום לכל הריצה, כולל בדיקות בשורש הריפו (``testpaths`` כולל את ``.``).

    **למה פלאגין ולא hook ב-``tests/conftest.py``.** hook שמוגדר שם חל רק על
    בדיקות שמתחת ל-``tests/``: ``Session.gethookproxy`` מסנן אותו לכל נתיב אחר.
    הבדיקה שואלת את pytest עצמו אילו מימושים ירוצו לנתיב השורש, ומראה את שני
    הצדדים — הפלאגין שם, וה-hook של ``tests/conftest.py`` לא.
    """
    at_root = request.session.gethookproxy(request.config.rootpath)

    teardown_plugins = [impl.plugin for impl in at_root.pytest_runtest_teardown.get_hookimpls()]
    assert _sentry_isolation in teardown_plugins, (
        "הפלאגין אינו רץ לבדיקות בשורש הריפו — הוא נרשם כ-hook של conftest ולא כפלאגין"
    )

    our_conftest = str(_TESTS_DIR / "conftest.py")
    configure_files = {
        getattr(impl.plugin, "__file__", None) for impl in at_root.pytest_configure.get_hookimpls()
    }
    assert our_conftest not in configure_files, (
        "hook של tests/conftest.py חל גם בשורש — ההנחה שהבדיקה הזו נשענת עליה השתנתה"
    )
