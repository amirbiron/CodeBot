"""ייצוא הסעיפים של אתר התיעוד — החלקים שאינם דורשים דפדפן.

``scripts/docs_export_sections.py`` רץ בבניית האתר ב-``.github/workflows/documentation.yml``.
הבדיקות כאן מכסות את מה שקורה מסביב לדפדפן: אילו עמודים נכנסים, מאיפה נגזר קובץ המקור,
מה נדחה ממה שהעמוד מחזיר, איך ה-CLI מסרב לערכים שגויים, ושהצעדים ב-workflow בנויים
כך שכשל בייצוא לא מפיל את בניית האתר. ההמרה עצמה, בדפדפן, נבדקת
ב-``tests/test_docs_export_sections_browser.py``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import docs_export_sections as export  # noqa: E402  (אחרי sys.path.insert, כמו בשאר טסטי הריפו)

WORKFLOW = ROOT / ".github" / "workflows" / "documentation.yml"
TELEGRAM_ACTION = ROOT / ".github" / "actions" / "telegram-message" / "action.yml"
BASE_REQUIREMENTS = ROOT / "requirements" / "base.txt"

SITE_URL = "https://docs.example.test/CodeBot/"
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_docs_steps() -> dict[str, dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return {step["id"]: step for step in workflow["jobs"]["build-docs"]["steps"] if "id" in step}


def _build_docs_step_named(prefix: str) -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    matches = [
        step for step in workflow["jobs"]["build-docs"]["steps"]
        if str(step.get("name", "")).startswith(prefix)
    ]
    assert len(matches) == 1, f"expected one step named {prefix!r}, found {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# אילו עמודים נכנסים, ומאיפה המקור
# ---------------------------------------------------------------------------


def test_content_pages_skip_sphinx_folders_api_and_generated_pages(tmp_path):
    for page in (
        "index.html",
        "guide/intro.html",
        "guide/deep/more.html",
        "api/module.html",
        "_modules/pkg/mod.html",
        "_static/fragment.html",
        ".doctrees/cached.html",
        "genindex.html",
        "search.html",
        "py-modindex.html",
        "guide/search.html",
    ):
        _touch(tmp_path / page)

    assert export.content_pages(tmp_path) == [
        "guide/deep/more.html",
        "guide/intro.html",
        # ``search.html`` מוחרג רק בשורש: עמוד בשם הזה בתוך תיקייה הוא עמוד תוכן.
        "guide/search.html",
        "index.html",
    ]


def test_source_path_comes_from_the_copy_sphinx_keeps_under_sources(tmp_path):
    _touch(tmp_path / "_sources" / "guide" / "intro.rst.txt")
    _touch(tmp_path / "_sources" / "notes.md.txt")

    root = PurePosixPath("docs")
    assert export.source_path(tmp_path, "guide/intro.html", root) == "docs/guide/intro.rst"
    assert export.source_path(tmp_path, "notes.html", root) == "docs/notes.md"


def test_a_page_without_exactly_one_source_fails(tmp_path):
    _touch(tmp_path / "_sources" / "both.rst.txt")
    _touch(tmp_path / "_sources" / "both.md.txt")

    with pytest.raises(export.ExportError, match="missing.html"):
        export.source_path(tmp_path, "missing.html", PurePosixPath("docs"))
    with pytest.raises(export.ExportError, match="both.html"):
        export.source_path(tmp_path, "both.html", PurePosixPath("docs"))


# ---------------------------------------------------------------------------
# מה נדחה ממה שהעמוד מחזיר
# ---------------------------------------------------------------------------


def _section(**overrides):
    section = {
        "anchor": "id3",
        "title": "סעיף",
        "breadcrumb": ["עמוד", "סעיף"],
        "level": 2,
        "markdown": "תוכן\n",
    }
    section.update(overrides)
    return section


def test_valid_sections_pass_through_unchanged():
    top = _section(anchor="top", title="עמוד", breadcrumb=["עמוד"], level=1)
    raw = {"sections": [top, _section()]}

    assert export._validated_sections(raw, "page.html") == raw["sections"]


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {"sections": "not a list"},
        {"sections": []},
        {"sections": ["not an object"]},
        {"sections": [_section(anchor="")]},
        {"sections": [_section(), _section()]},
        {"sections": [_section(title="")]},
        {"sections": [_section(breadcrumb="עמוד › סעיף")]},
        {"sections": [_section(breadcrumb=["עמוד", "אחר"])]},
        {"sections": [_section(breadcrumb=["", "סעיף"])]},
        {"sections": [_section(level=3)]},
        {"sections": [_section(level=True, breadcrumb=["סעיף"])]},
        {"sections": [_section(level="2")]},
        {"sections": [_section(markdown=None)]},
    ],
    ids=[
        "not-an-object",
        "a-list",
        "sections-not-a-list",
        "no-sections",
        "section-not-an-object",
        "empty-anchor",
        "duplicate-anchor",
        "empty-title",
        "breadcrumb-not-a-list",
        "breadcrumb-does-not-end-with-title",
        "empty-crumb",
        "level-is-not-the-depth",
        "level-is-a-bool",
        "level-is-text",
        "markdown-is-not-text",
    ],
)
def test_a_malformed_page_answer_fails_the_page(raw):
    with pytest.raises(export.ExportError, match="page.html"):
        export._validated_sections(raw, "page.html")


# ---------------------------------------------------------------------------
# ה-CLI
# ---------------------------------------------------------------------------


def _args(html_dir: Path, **overrides: str) -> list[str]:
    options = {"--site-url": SITE_URL, "--source-commit": COMMIT, "--source-root": "docs"}
    options.update(overrides)
    argv = [str(html_dir)]
    for name, value in options.items():
        argv += [name, value]
    return argv


@pytest.mark.parametrize(
    "option, value",
    [
        ("--site-url", "http://docs.example.test/CodeBot/"),
        ("--site-url", "https://docs.example.test/CodeBot"),
        ("--site-url", "https://docs.example.test/CodeBot/?v=1"),
        ("--site-url", "https://docs.example.test/CodeBot/#top"),
        ("--site-url", "https://user:secret@docs.example.test/CodeBot/"),
        ("--site-url", "https:///CodeBot/"),
        ("--source-commit", "0123456"),
        ("--source-commit", COMMIT.upper()),
        ("--source-root", ""),
        ("--source-root", "/home/runner/docs"),
        ("--source-root", "../docs"),
        ("--source-root", "."),
    ],
)
def test_the_cli_refuses_bad_values_before_doing_anything(tmp_path, option, value):
    with pytest.raises(SystemExit) as raised:
        export.main(_args(tmp_path, **{option: value}))
    assert raised.value.code == 2


def test_a_missing_site_folder_is_a_usage_error(tmp_path, capsys):
    assert export.main(_args(tmp_path / "missing")) == 2
    assert "missing" in capsys.readouterr().err


def test_a_failed_export_removes_the_files_of_a_previous_run(tmp_path, capsys):
    """ייצוא שנכשל לא משאיר קובץ ישן שנראה עדכני — גם כשהכשל קורה לפני הדפדפן.

    נמחקים הקובץ הראשי וכל עותק לפי קומיט, ורק הם: קובץ אחר באותה תיקייה, ושם שרק דומה
    לעותק, נשארים.
    """
    export_dir = tmp_path / "_export"
    stale = tmp_path / export.EXPORT_PATH
    _touch(stale, '{"schema_version": 1}')
    for sha in (COMMIT, "f" * 40):
        _touch(export_dir / f"sections-{sha}.json", '{"schema_version": 1}')
    for unrelated in ("notes.txt", "sections-abc.json", f"sections-{'A' * 40}.json"):
        _touch(export_dir / unrelated)

    assert export.main(_args(tmp_path)) == 1

    assert not stale.exists()
    assert sorted(path.name for path in export_dir.iterdir()) == sorted(
        ["notes.txt", "sections-abc.json", f"sections-{'A' * 40}.json"]
    )
    assert "no content pages" in capsys.readouterr().err


def test_the_commit_copy_is_named_after_the_commit():
    assert export.export_path_for_commit(COMMIT) == PurePosixPath(f"_export/sections-{COMMIT}.json")
    assert export.export_path_for_commit(COMMIT).parent == export.EXPORT_PATH.parent


@pytest.mark.parametrize(
    "value",
    ["", "0123456", COMMIT.upper(), COMMIT + "0", "../" + COMMIT[3:], None, 1234],
)
def test_the_commit_copy_refuses_anything_but_a_full_sha(value):
    """ה-sha נכנס לשם קובץ ולכתובת באתר, ולכן כל ערך אחר נדחה."""
    with pytest.raises(ValueError):
        export.export_path_for_commit(value)


def test_importing_the_script_does_not_import_playwright():
    """את פונקציות העזר אפשר לייבא גם בלי Playwright: הייבוא שלו קורה רק בייצוא עצמו."""
    probe = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import scripts.docs_export_sections\n"
        "print(sorted(name for name in sys.modules if name.split('.')[0] == 'playwright'))\n"
    )
    finished = subprocess.run(
        [sys.executable, "-B", "-c", probe], capture_output=True, text=True, timeout=60, check=True
    )
    assert finished.stdout.strip() == "[]"


# ---------------------------------------------------------------------------
# ה-workflow והפעולה לטלגרם
# ---------------------------------------------------------------------------


def _run_install_step(cwd: Path, tmp_path: Path) -> tuple[subprocess.CompletedProcess, list[str]]:
    """מריץ את הסקריפט של צעד ההתקנה כמו ש-GitHub Actions מריץ אותו, עם ``python`` מדומה.

    ``python`` המדומה רק רושם את הארגומנטים שלו, כך ששום דבר לא מותקן באמת.
    """
    script = _build_docs_steps()["export_setup"]["run"]
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "calls.txt"
    _touch(bin_dir / "python", f'#!/bin/sh\necho "$*" >> "{calls}"\n')
    (bin_dir / "python").chmod(0o755)
    environment = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    # הדגלים של ``shell: bash`` ב-GitHub Actions: ``bash --noprofile --norc -eo pipefail {0}``.
    finished = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        cwd=cwd, env=environment, capture_output=True, text=True, timeout=60,
    )
    recorded = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return finished, recorded


def test_the_workflow_installs_the_playwright_that_base_txt_pins(tmp_path):
    """הגרסה נקראת מ-``requirements/base.txt`` ואינה מוקלדת ב-workflow, ולכן אין שני עותקים."""
    pinned = [
        line.strip() for line in BASE_REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.startswith("playwright==")
    ]
    assert len(pinned) == 1, pinned
    assert not re.search(r"playwright==\d", WORKFLOW.read_text(encoding="utf-8"))

    finished, calls = _run_install_step(ROOT, tmp_path)

    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert calls == [
        f"-m pip install {pinned[0]}",
        "-m playwright install --with-deps --only-shell chromium",
    ]


def test_the_install_step_fails_loudly_without_an_exact_pin(tmp_path):
    checkout = tmp_path / "checkout"
    _touch(checkout / "requirements" / "base.txt", "playwright==1.49.0  # pinned\n")

    finished, calls = _run_install_step(checkout, tmp_path)

    assert finished.returncode != 0
    assert calls == []
    assert "::error::" in finished.stdout


def test_a_failed_export_never_fails_the_docs_build():
    """ההחלטה: שום דבר בייצוא לא מפיל את בניית האתר. כשל נשאר גלוי באזהרה ובטלגרם."""
    steps = _build_docs_steps()
    alert = _build_docs_step_named("📨 Alert Telegram about a failed sections export")
    report = _build_docs_step_named("⚠️ Report a failed sections export")

    for step in (steps["export_setup"], steps["export_sections"], report, alert):
        assert step.get("continue-on-error") is True, step["name"]
    for step in (steps["export_setup"], steps["export_sections"]):
        assert isinstance(step.get("timeout-minutes"), int), step["name"]

    assert alert["uses"] == "./.github/actions/telegram-message"
    assert "steps.sphinx_main.outcome == 'success'" in alert["if"]
    assert "steps.export_sections.outcome != 'success'" in alert["if"]


def test_the_export_reads_sources_from_the_folder_sphinx_builds():
    """``--source-root`` הוא התיקייה שבה Sphinx רץ (``cd docs``), אחרת נתיבי המקור בקובץ שגויים."""
    steps = _build_docs_steps()
    run = steps["export_sections"]["run"]
    source_root = re.search(r"--source-root (\S+)", run).group(1)

    for build in (steps["sphinx_pr"], steps["sphinx_main"]):
        assert f"cd {source_root}\n" in build["run"]
    assert (ROOT / source_root / "conf.py").is_file()
    assert '"${SPHINX_BUILD_DIR}"' in run


def test_the_telegram_action_passes_inputs_only_through_env():
    """תוכן ההודעה לא נכתב לתוך הסקריפט, ולכן לא יכול להתפרש כפקודה."""
    action = yaml.safe_load(TELEGRAM_ACTION.read_text(encoding="utf-8"))
    (step,) = action["runs"]["steps"]

    assert action["runs"]["using"] == "composite"
    assert "${{" not in step["run"]
    assert set(step["env"]) == {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_TEXT"}
    assert all(spec["required"] is True for spec in action["inputs"].values())
