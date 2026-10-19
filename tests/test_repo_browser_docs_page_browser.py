"""התצוגה המרונדרת של עמוד rst בדפדפן הריפו — בכרומיום אמיתי, מול הוובאפ האמיתי.

**מה נבדק כאן ולא בבדיקות השרת.** ``tests/test_repo_browser_docs_page.py`` מוכיח מה השרת מחזיר, ו-
``tests/repo-browser-docs-page.test.js`` מה הסקריפט עושה עם זה ב-DOM מדומה. מה שרק דפדפן מראה: שהעמוד
באמת מרונדר, מימין לשמאל ועם קוד משמאל לימין (עיצוב ``markdown-preview.css`` על הרינדור של
``MarkdownLiveRenderer``), שההודעה מוצגת כשהקובץ השתנה, ושקובץ בלי עמוד נשאר קוד — בלי שגיאות JS.

השרת, המסד, המראה והעמוד — ``_repo_browser_harness.py``. הדפדפן מורם כאן, בפיקסצ'ר ``browser``.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``), וכשאין git.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll
from _docs_index_harness import page, section
from _git_mirror_harness import GIT
from _repo_browser_harness import REPO, mirror_world, open_file, repo_page

from services import docs_search_contract as contract

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

pytestmark = pytest.mark.skipif(GIT is None, reason="git is not installed")

RST = "docs/webapp/code-browser.rst"
API_RST = "docs/api/handlers.rst"


def _pages():
    """עמוד שיש בו כל מה שהכיוון נוגע בו: פסקה בעברית, קוד בשורה, בלוק קוד עם שפה, טבלה והערה."""
    return [
        page(
            "webapp/code-browser.html", RST,
            section("code-browser", "דפדפן קוד", markdown="ייבוא ריפו לדפדפן הקוד, עם `initial_import`."),
            section(
                "import", "דפדפן קוד", "ייבוא ריפו חדש", title_markdown="ייבוא ריפו חדש",
                markdown=(
                    "יש להריץ את הפקודה:\n\n```python\nres = initial_import(\"url\", \"שם\", get_db())\n```\n\n"
                    "| שדה | ערך |\n| --- | --- |\n| Secret | הסוד |\n\n::: warning\nודאו שהסוד תואם.\n:::"
                ),
            ),
        ),
    ]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """אינדקס שנבנה מהבנייה של הקומיט ``built``, והוובאפ האמיתי מול אותו מסד ומול המראה."""
    return mirror_world(
        tmp_path, monkeypatch, {RST: "דפדפן קוד\n=========\n", API_RST: "api\n===\n"}, _pages()
    )


@pytest.fixture(scope="module")
def browser(chromium_executable):
    """הדפדפן של הקובץ — **המקום היחיד שמרים דפדפן כאן**. ההרמה נשארת בקובצי ``*_browser.py``
    (``tests/test_browser_suite_is_gated_once.py``), ו-``repo_page`` מקימה בו context לכל בדיקה."""
    with sync_playwright() as pw:
        try:
            launched = pw.chromium.launch(executable_path=chromium_executable)
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            yield launched
        finally:
            launched.close()


def _sync_rst(world, sha) -> None:
    """סנכרון של המראה לקומיט ששינה את קובץ ה-rst: ``last_synced_sha`` מתקדם, וגם ``commit_sha`` של הקובץ —
    כמו ``_sync_repo_logic`` ב-``services/repo_sync_service.py`` לקובץ שהשתנה."""
    world.db.repo_metadata.update_one({"repo_name": REPO}, {"$set": {"last_synced_sha": sha}})
    world.db.repo_files.update_one({"repo_name": REPO, "path": RST}, {"$set": {"commit_sha": sha}})


#: הכיוון של כל מה שהעמוד המרונדר מציג: המיכל, הכותרת והפסקה, וכל בלוק קוד.
_DIRECTIONS = """
() => {
  const root = document.getElementById('markdown-preview-content');
  const dir = (el) => el ? getComputedStyle(el).direction : null;
  return {
    container: dir(document.getElementById('markdown-preview-container')),
    heading: dir(root.querySelector('h1')),
    paragraph: dir(root.querySelector('p')),
    table: dir(root.querySelector('table')),
    code: Array.from(root.querySelectorAll('pre')).map((pre) => dir(pre)),
  };
}
"""

_RENDERED = "() => !!document.querySelector('#markdown-preview-content h1')"


def test_an_rst_page_is_rendered_right_to_left_with_its_code_left_to_right(
    world, admin_live_server, browser
):
    with repo_page(browser, admin_live_server) as (tab, errors):
        open_file(tab, admin_live_server, RST)
        poll(tab, _RENDERED, "העמוד מאתר התיעוד רונדר")

        # הרינדור מוסיף לכל כותרת סימן עוגן (``¶``), כמו בתצוגת ה-Markdown של כל קובץ.
        heading = tab.evaluate(
            "() => document.querySelector('#markdown-preview-content h1').textContent.replace('¶', '').trim()"
        )
        assert heading == "דפדפן קוד"
        directions = tab.evaluate(_DIRECTIONS)
        assert directions["container"] == directions["heading"] == directions["paragraph"] == "rtl", directions
        assert directions["code"] and set(directions["code"]) == {"ltr"}, directions
        toggle = tab.evaluate(
            "() => { const b = document.getElementById('markdown-preview-toggle');"
            " return {shown: getComputedStyle(b).display !== 'none', title: b.title}; }"
        )
        assert toggle == {"shown": True, "title": "תצוגה מרונדרת מאתר התיעוד (Ctrl+Shift+M)"}
        assert tab.evaluate("() => document.getElementById('markdown-preview-note').hidden") is True
    assert errors == [], "\n".join(errors)


def test_a_file_that_changed_after_the_build_shows_the_note(world, admin_live_server, browser):
    later = world.repo.commit({RST: "דפדפן קוד\n=========\n\nפסקה חדשה.\n"})
    _sync_rst(world, later)

    with repo_page(browser, admin_live_server) as (tab, errors):
        open_file(tab, admin_live_server, RST)
        poll(tab, _RENDERED, "העמוד מאתר התיעוד רונדר")

        note = tab.evaluate(
            "() => { const n = document.getElementById('markdown-preview-note');"
            " return {hidden: n.hidden, shown: n.getBoundingClientRect().height > 0, text: n.textContent}; }"
        )
    assert note == {
        "hidden": False, "shown": True, "text": "התצוגה מהבנייה האחרונה של אתר התיעוד; הקובץ השתנה מאז",
    }
    assert errors == [], "\n".join(errors)


_NOTE = (
    "() => { const n = document.getElementById('markdown-preview-note');"
    " return {hidden: n.hidden, text: n.textContent}; }"
)


def test_a_version_viewed_from_the_history_is_compared_by_its_own_commit(world, admin_live_server, browser):
    """דרך הממשק: "צפה" על הקומיט שהאתר נבנה ממנו, בפאנל ההיסטוריה. ``viewFileAtCommit`` מעביר את הקומיט
    הלאה, והעמוד מושווה אליו — ולכן ההודעה שהייתה על הגרסה הנוכחית יורדת. נופל כש-``repo-history.js`` לא
    מעביר את הקומיט: העמוד מושווה אז לגרסה הנוכחית, וההודעה נשארת."""
    built = world.db[contract.STATE_COLLECTION].find_one({})["indexed_source_commit"]
    later = world.repo.commit({RST: "דפדפן קוד\n=========\n\nפסקה חדשה.\n"})
    _sync_rst(world, later)

    with repo_page(browser, admin_live_server) as (tab, errors):
        page_requests = []
        tab.on("request", lambda request: page_requests.append(request.url) if "/repo/api/docs-page/" in request.url else None)
        open_file(tab, admin_live_server, RST)
        poll(tab, _RENDERED, "העמוד מאתר התיעוד רונדר")
        assert tab.evaluate(_NOTE)["hidden"] is False

        tab.click(".file-history-btn")
        view = f'.history-commit[data-hash="{built}"] .view-btn'
        poll(tab, f"() => !!document.querySelector('{view}')", "הקומיט של הבנייה בפאנל ההיסטוריה")
        tab.click(view)
        poll(tab, "() => document.getElementById('markdown-preview-note').hidden", "ההודעה ירדה")

        note = tab.evaluate(_NOTE)
    assert parse_qs(urlsplit(page_requests[-1]).query).get("ref") == [built]
    assert note == {"hidden": True, "text": ""}
    assert errors == [], "\n".join(errors)


def test_an_rst_file_without_a_page_stays_code(world, admin_live_server, browser):
    with repo_page(browser, admin_live_server) as (tab, errors):
        open_file(tab, admin_live_server, API_RST)
        poll(tab, "() => document.getElementById('code-header').style.display === 'flex'", "הקובץ נטען")

        shown = tab.evaluate(
            "() => ({toggle: document.getElementById('markdown-preview-toggle').style.display,"
            " preview: document.getElementById('markdown-preview-container').style.display})"
        )
    assert shown == {"toggle": "none", "preview": "none"}
    assert errors == [], "\n".join(errors)
