"""התצוגה המרונדרת של עמוד rst בדפדפן הריפו: מתי היא מוצעת, מה היא מחזירה, ומתי היא ישנה מהקובץ.

הטסטים עוברים בממשק שהצרכן משתמש בו — ``/repo/api/file/<path>`` ו-``/repo/api/docs-page/<path>``,
שמהם ``repo-browser.js`` טוען — ובשרשרת האמיתית: האינדקס נבנה במעבר האמיתי (``_docs_index_harness``,
מול דמה של מונגו), והמראה היא מראה git אמיתית תחת ``tmp_path``. הקומיט של "בניית האתר" הוא קומיט
אמיתי במראה, ולכן השוואת התוכן (``get_blob_ids``, ‏``git ls-tree``) רצה כמו בייצור.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from flask import Flask
from pymongo.errors import ServerSelectionTimeoutError

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _docs_index_harness import fill, make_world, page, section
from _fake_mongo import FakeDB
from _git_mirror_harness import GIT, RepoWithMirror

from services import docs_index_service as svc
from services import docs_page_view
from services import docs_search_contract as contract
from services.git_mirror_service import GitMirrorService
from webapp.routes import repo_browser
from webapp.routes.repo_browser import repo_bp

pytestmark = pytest.mark.skipif(GIT is None, reason="git is not installed")

_ADMIN_ID = 999
REPO = contract.SOURCE_REPO_NAME
RST = "docs/webapp/code-browser.rst"
API_RST = "docs/api/handlers.rst"
#: קוד שהעמוד מציג מקובץ אחר (``literalinclude``) — קובץ שהעמוד נבנה ממנו.
INCLUDED = "handlers/save_flow.py"


def _site_pages():
    return [
        page(
            "webapp/code-browser.html", RST,
            section("code-browser", "דפדפן קוד", markdown=""),
            section("import", "דפדפן קוד", "ייבוא ריפו חדש", title_markdown="ייבוא `ריפו` חדש",
                    markdown="להריץ את הפקודה."),
            dependencies=[INCLUDED],
        ),
    ]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """אינדקס שנבנה מבנייה של הקומיט ``built``, ודפדפן הריפו מול המראה ומול אותו מסד."""
    repo = RepoWithMirror(tmp_path, REPO)
    built = repo.commit({
        RST: "דפדפן קוד\n=========\n", API_RST: "api\n===\n", "README.md": "# קרא אותי\n",
        INCLUDED: "def save():\n    pass\n",
    })
    world = make_world(monkeypatch, FakeDB())
    fill(world, pages=_site_pages(), commit=built)
    for path in (RST, API_RST, "README.md", INCLUDED):
        world.db.repo_files.insert_one({"repo_name": REPO, "path": path, "commit_sha": built, "language": "text"})
    world.db.repo_metadata.insert_one({"repo_name": REPO, "default_branch": "main", "last_synced_sha": built})

    mirror_service = GitMirrorService(base_path=str(repo.mirrors))
    monkeypatch.setattr(repo_browser, "get_mirror_service", lambda: mirror_service)
    monkeypatch.setattr(repo_browser, "get_db", lambda: world.db)
    # דפדפן הקוד חסום לאדמינים — אותו ``webapp.app`` מדומה כמו ב-``tests/test_repo_browser_content_as_is.py``.
    stub = ModuleType("webapp.app")
    stub.is_admin = lambda uid: int(uid) == _ADMIN_ID
    stub.is_impersonating_safe = lambda: False
    monkeypatch.setitem(sys.modules, "webapp.app", stub)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    app.register_blueprint(repo_bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = _ADMIN_ID
    world.client, world.repo, world.built = client, repo, built
    return world


def _file(world, path, repo=REPO):
    response = world.client.get(f"/repo/api/file/{path}?repo={repo}")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _docs_page(world, path=RST, **params):
    query = "&".join(f"{key}={value}" for key, value in {"repo": REPO, **params}.items())
    return world.client.get(f"/repo/api/docs-page/{path}?{query}")


def _sync(world, sha, *changed, removed=()):
    """סנכרון של המראה ל-``sha``, כמו ``_sync_repo_logic`` ב-``services/repo_sync_service.py``: ``last_synced_sha``
    מתקדם, אבל ``commit_sha`` ב-``repo_files`` מתעדכן רק לקבצים שהשתנו, וקובץ שנמחק יוצא מהאינדקס. קובץ שלא
    השתנה נשאר על הקומיט הקודם שלו — וזה בדיוק מה שהדפדפן מציג ממנו."""
    world.db.repo_metadata.update_one({"repo_name": REPO}, {"$set": {"last_synced_sha": sha}})
    for path in changed:
        world.db.repo_files.update_one({"repo_name": REPO, "path": path}, {"$set": {"commit_sha": sha}})
    for path in removed:
        world.db.repo_files.delete_one({"repo_name": REPO, "path": path})


def _file_commit(world, path=RST):
    return world.db.repo_files.find_one({"repo_name": REPO, "path": path})["commit_sha"]


# ---------------------------------------------------------------------------
# מתי התצוגה מוצעת
# ---------------------------------------------------------------------------


def test_an_rst_file_with_a_page_in_the_index_offers_the_rendered_view(world):
    assert _file(world, RST)["has_docs_page"] is True


def test_an_rst_file_that_the_export_skips_is_code_only(world):
    """עמודי ``docs/api/`` אינם בייצוא, ולכן אין להם עמוד באינדקס."""
    assert _file(world, API_RST)["has_docs_page"] is False
    assert _docs_page(world, API_RST).status_code == 404


def test_a_markdown_file_is_not_offered_a_docs_page(world):
    """קובץ md מוצג בתצוגת ה-Markdown הקיימת, מהמקור שלו."""
    assert _file(world, "README.md")["has_docs_page"] is False
    assert _docs_page(world, "README.md").status_code == 404


def test_the_same_path_in_another_repo_has_no_docs_page(world, tmp_path):
    """האתר נבנה מריפו אחד. קובץ באותו נתיב בריפו אחר אינו העמוד הזה."""
    other = RepoWithMirror(tmp_path, "probe")
    sha = other.commit({RST: "אחר\n===\n"})
    world.db.repo_files.insert_one({"repo_name": "probe", "path": RST, "commit_sha": sha, "language": "text"})

    assert _file(world, RST, repo="probe")["has_docs_page"] is False
    assert world.client.get(f"/repo/api/docs-page/{RST}?repo=probe").status_code == 404


def test_a_database_error_while_looking_up_the_page_still_shows_the_file(world, monkeypatch, caplog):
    def unreachable(db, path):
        raise ServerSelectionTimeoutError("no primary")

    monkeypatch.setattr(docs_page_view, "has_docs_page", unreachable)

    body = _file(world, RST)

    assert body["content"] == "דפדפן קוד\n=========\n"
    assert body["has_docs_page"] is False
    assert "could not look up the docs page" in caplog.text


def test_an_error_that_is_not_the_database_is_not_taken_for_no_page(world, monkeypatch):
    """רק כשל מסד הוא "אין עמוד"; באג (``TypeError`` של חתימה שהשתנתה) עולה ולא מוסתר כקוד בלבד."""
    def broken(db, path):
        raise TypeError("has_docs_page() takes 1 positional argument")

    monkeypatch.setattr(docs_page_view, "has_docs_page", broken)

    with pytest.raises(TypeError):
        world.client.get(f"/repo/api/file/{RST}?repo={REPO}")


# ---------------------------------------------------------------------------
# העמוד, ומתי הוא ישן מהקובץ
# ---------------------------------------------------------------------------


def test_the_page_is_the_assembled_page_built_from_the_file_shown(world):
    response = _docs_page(world)

    assert response.status_code == 200
    assert response.get_json() == {
        "path": RST,
        "markdown": "# דפדפן קוד\n\n## ייבוא `ריפו` חדש\n\nלהריץ את הפקודה.\n",
        "page_path": "webapp/code-browser.html",
        "freshness": docs_page_view.FRESHNESS_CURRENT,
        "changed_dependencies": [],
    }


def test_a_commit_that_did_not_touch_the_file_is_not_a_change(world):
    later = world.repo.commit({"README.md": "# קרא אותי, בגרסה חדשה\n"})
    _sync(world, later, "README.md")

    assert _docs_page(world).get_json()["freshness"] == docs_page_view.FRESHNESS_CURRENT


def test_a_file_that_changed_after_the_build_is_marked_changed(world):
    later = world.repo.commit({RST: "דפדפן קוד\n=========\n\nפסקה חדשה.\n"})
    _sync(world, later, RST)

    body = _docs_page(world).get_json()

    assert body["freshness"] == docs_page_view.FRESHNESS_CHANGED
    # העמוד עצמו הוא עדיין זה של הבנייה האחרונה.
    assert body["markdown"].startswith("# דפדפן קוד\n")


def test_a_version_from_the_history_is_compared_by_its_own_commit(world):
    later = world.repo.commit({RST: "דפדפן קוד\n=========\n\nפסקה חדשה.\n"})
    _sync(world, later, RST)

    assert _docs_page(world, ref=world.built).get_json()["freshness"] == docs_page_view.FRESHNESS_CURRENT
    assert _docs_page(world, ref=later).get_json()["freshness"] == docs_page_view.FRESHNESS_CHANGED


def test_a_change_in_code_the_page_includes_is_named(world):
    """הקובץ לא השתנה, אבל הקוד שהעמוד מציג ממנו כן — העמוד ישן מהקוד, וההודעה אומרת איזה קובץ. הקובץ נשאר
    ב-``repo_files`` על הקומיט הישן שלו, כמו אחרי סנכרון אמיתי, ולכן ההשוואה היא מול הקומיט האחרון שסונכרן
    ולא מול הקומיט של הקובץ — שם הקוד עוד לא השתנה."""
    later = world.repo.commit({INCLUDED: "def save():\n    return 1\n"})
    _sync(world, later, INCLUDED)
    assert _file_commit(world) == world.built

    body = _docs_page(world).get_json()

    assert (body["freshness"], body["changed_dependencies"]) == (docs_page_view.FRESHNESS_DEPENDENCY_CHANGED, [INCLUDED])


def test_code_the_page_includes_that_was_deleted_is_a_change(world):
    later = world.repo.commit({INCLUDED: None})
    _sync(world, later, removed=[INCLUDED])

    body = _docs_page(world).get_json()

    assert (body["freshness"], body["changed_dependencies"]) == (docs_page_view.FRESHNESS_DEPENDENCY_CHANGED, [INCLUDED])


def test_a_change_in_the_file_itself_is_named_first(world):
    """כשגם הקובץ השתנה, ההודעה היא על הקובץ שמוצג — זה מה שהמשתמש קורא."""
    later = world.repo.commit({RST: "דפדפן קוד\n=========\n\nפסקה חדשה.\n", INCLUDED: "def save():\n    return 1\n"})
    _sync(world, later, RST, INCLUDED)

    body = _docs_page(world).get_json()

    assert (body["freshness"], body["changed_dependencies"]) == (docs_page_view.FRESHNESS_CHANGED, [])


def test_a_version_from_the_history_compares_the_included_code_of_that_version(world):
    later = world.repo.commit({INCLUDED: "def save():\n    return 1\n"})
    _sync(world, later, INCLUDED)

    assert _docs_page(world, ref=world.built).get_json()["freshness"] == docs_page_view.FRESHNESS_CURRENT
    assert _docs_page(world, ref=later).get_json()["freshness"] == docs_page_view.FRESHNESS_DEPENDENCY_CHANGED


def test_a_page_rebuilt_after_the_included_code_changed_is_current(world):
    """אחרי שהאתר נבנה מחדש מהקומיט החדש, העמוד עדכני — גם כשהקובץ עצמו עדיין על הקומיט הישן שלו ב-
    ``repo_files``. השוואה לקומיט של הקובץ הייתה מוצאת את הקוד הישן שם, ומסמנת את העמוד כישן עד שהקובץ
    עצמו ישתנה."""
    later = world.repo.commit({INCLUDED: "def save():\n    return 1\n"})
    _sync(world, later, INCLUDED)
    _set_state(world, indexed_source_commit=later)
    assert _file_commit(world) == world.built

    assert _docs_page(world).get_json()["freshness"] == docs_page_view.FRESHNESS_CURRENT


@pytest.mark.parametrize("synced", [None, "main", "origin/main"], ids=["missing", "branch name", "remote branch"])
def test_without_a_synced_commit_the_page_cannot_be_compared(world, synced):
    """בלי הקומיט האחרון שסונכרן אין "עכשיו" להשוות אליו. ``origin/<branch>`` לא נפתר במראה שנבנתה ב-
    ``git clone --mirror`` (שם הענפים תחת ``refs/heads``), ולכן גם הוא אינו תחליף."""
    world.db.repo_metadata.update_one({"repo_name": REPO}, {"$set": {"last_synced_sha": synced}})

    assert _docs_page(world).get_json()["freshness"] == docs_page_view.FRESHNESS_UNKNOWN


def _set_page(world, **fields):
    world.db[contract.PAGES_COLLECTION].update_one({"_id": RST}, {"$set": fields})


def test_an_included_file_missing_from_the_build_commit_cannot_be_compared(world):
    """הבנייה רשמה קובץ שאינו בקומיט שלה — הנתונים לא עקביים, וזה "אי אפשר לבדוק" ולא "עדכני"."""
    _set_page(world, dependencies=[INCLUDED, "handlers/missing.py"])

    assert _docs_page(world).get_json()["freshness"] == docs_page_view.FRESHNESS_UNKNOWN


@pytest.mark.parametrize("stored", [None, "handlers/save_flow.py", [7]], ids=["missing", "text", "number"])
def test_a_page_without_a_list_of_files_cannot_be_compared(world, stored):
    """בלי הרשימה אין דרך לדעת שהעמוד מציג קוד מקובץ אחר, ולכן גם לא שהוא עדכני."""
    _set_page(world, dependencies=stored)

    assert _docs_page(world).get_json()["freshness"] == docs_page_view.FRESHNESS_UNKNOWN


def _set_state(world, **fields):
    world.db[contract.STATE_COLLECTION].update_one({"_id": svc.STATE_ID}, {"$set": fields})


def test_an_index_in_the_middle_of_a_pass_cannot_be_compared(world):
    _set_state(world, indexed_source_commit=None)

    assert _docs_page(world).get_json()["freshness"] == docs_page_view.FRESHNESS_UNKNOWN


def test_an_index_built_by_rules_without_pages_cannot_be_compared(world):
    """הקומיט במסמך המצב נכון לרשומות של אותם כללים; כללים שלא כתבו עמודים לא אומרים כלום על העמוד."""
    _set_state(world, indexed_records_version=svc.RECORDS_VERSION - 1)

    assert _docs_page(world).get_json()["freshness"] == docs_page_view.FRESHNESS_UNKNOWN


def test_a_build_commit_that_the_mirror_does_not_have_cannot_be_compared(world):
    """המראה מפגרת אחרי הבנייה: אין עם מה להשוות, וזה לא "השתנה"."""
    _set_state(world, indexed_source_commit="d" * 40)

    assert _docs_page(world).get_json()["freshness"] == docs_page_view.FRESHNESS_UNKNOWN


def test_a_pass_that_ran_between_reading_the_state_and_the_page_cannot_be_compared(world, monkeypatch):
    """מעבר שהסתיים בין שתי הקריאות היה יכול לכתוב עמוד מבנייה אחרת מזו שבמסמך המצב שנקרא קודם."""
    states = iter([{"indexed_source_commit": world.built, "indexed_records_version": svc.RECORDS_VERSION},
                   {"indexed_source_commit": "e" * 40, "indexed_records_version": svc.RECORDS_VERSION}])
    monkeypatch.setattr(svc, "read_state", lambda db: next(states))

    assert docs_page_view.read_docs_page(world.db, RST)["indexed_commit"] is None


def test_a_database_error_while_reading_the_page_is_named(world, monkeypatch):
    def unreachable(db, path):
        raise ServerSelectionTimeoutError("no primary")

    monkeypatch.setattr(docs_page_view, "read_docs_page", unreachable)

    response = _docs_page(world)

    assert (response.status_code, response.get_json()) == (503, {"error": "docs_page_unavailable"})


# ---------------------------------------------------------------------------
# ``get_blob_ids`` — ההשוואה במראה
# ---------------------------------------------------------------------------


def _mirror(world) -> GitMirrorService:
    return GitMirrorService(base_path=str(world.repo.mirrors))


def test_blob_ids_come_in_one_answer_for_every_file_asked(world):
    """קובץ שאינו בקומיט חסר בתשובה, ותיקייה אינה קובץ — רק blobs בנתיב שהתבקש בדיוק."""
    blobs = _mirror(world).get_blob_ids(REPO, world.built, [RST, INCLUDED, "handlers/missing.py", "handlers"])

    assert sorted(blobs) == [RST, INCLUDED]
    assert all(len(sha) == 40 for sha in blobs.values())


def test_blob_ids_of_a_file_that_did_not_change_are_the_same(world):
    later = world.repo.commit({"README.md": "# אחר\n"})
    mirror = _mirror(world)

    assert mirror.get_blob_ids(REPO, world.built, [INCLUDED]) == mirror.get_blob_ids(REPO, later, [INCLUDED])


@pytest.mark.parametrize(
    "repo,ref,paths",
    [
        ("../" + REPO, None, [RST]),
        (REPO + "/..", None, [RST]),
        (REPO, "--output=x", [RST]),
        (REPO, None, ["../outside.py"]),
        (REPO, None, [RST, "-x"]),
    ],
    ids=["repo climbs up", "repo ends up", "ref is a flag", "path climbs up", "path is a flag"],
)
def test_a_rejected_name_runs_no_git_command(world, monkeypatch, repo, ref, paths):
    """שם הריפו בונה את התיקייה שבה git רץ (``_get_repo_path``), ולכן הוא נבדק כמו הנתיב וה-ref."""
    mirror = _mirror(world)
    monkeypatch.setattr(mirror, "_run_git_command", lambda *a, **k: pytest.fail("git ran on a rejected name"))

    assert mirror.get_blob_ids(repo, ref or world.built, paths) is None


def test_a_commit_the_mirror_does_not_have_has_no_answer(world):
    assert _mirror(world).get_blob_ids(REPO, "d" * 40, [RST]) is None


# ---------------------------------------------------------------------------
# דפדפן הריפו אינו תלוי במעבר האינדוקס בזמן שהוא נטען
# ---------------------------------------------------------------------------


def test_the_repo_browser_loads_even_when_the_index_cannot_be_imported():
    """``webapp/app.py`` מדלג בשקט על blueprint שהייבוא שלו נכשל, ולכן כשל במעבר (כאן: ערך ENV ש-
    ``services/embedding_service.py`` מפרסר בזמן ייבוא) לא יכול להעלים את דפדפן הריפו כולו. נמדד על
    הקוד שלפני ההפרדה: ``ValueError`` בייבוא של ``webapp.routes.repo_browser``."""
    root = Path(__file__).resolve().parent.parent
    probe = (
        "import sys\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        "import webapp.routes.repo_browser\n"
        "print('index imported:', 'services.docs_index_service' in sys.modules)\n"
    )
    env = {**os.environ, "EMBEDDING_MAX_INPUT_BYTES": "not-a-number"}
    finished = subprocess.run(
        [sys.executable, "-B", "-I", "-c", probe], capture_output=True, text=True, timeout=120, env=env, cwd=root
    )
    assert finished.returncode == 0, finished.stderr[-2000:]
    # הייבוא כותב שורות לוג ל-stdout; התשובה היא השורה עם התחילית.
    assert "index imported: False" in finished.stdout.splitlines()
