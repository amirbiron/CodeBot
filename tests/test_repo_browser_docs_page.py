"""התצוגה המרונדרת של עמוד rst בדפדפן הריפו: מתי היא מוצעת, מה היא מחזירה, ומתי היא ישנה מהקובץ.

הטסטים עוברים בממשק שהצרכן משתמש בו — ``/repo/api/file/<path>`` ו-``/repo/api/docs-page/<path>``,
שמהם ``repo-browser.js`` טוען — ובשרשרת האמיתית: האינדקס נבנה במעבר האמיתי (``_docs_index_harness``,
מול דמה של מונגו), והמראה היא מראה git אמיתית תחת ``tmp_path``. הקומיט של "בניית האתר" הוא קומיט
אמיתי במראה, ולכן השוואת התוכן (``git rev-parse``) רצה כמו בייצור.
"""

from __future__ import annotations

import sys
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


def _site_pages():
    return [
        page(
            "webapp/code-browser.html", RST,
            section("code-browser", "דפדפן קוד", markdown=""),
            section("import", "דפדפן קוד", "ייבוא ריפו חדש", title_markdown="ייבוא `ריפו` חדש",
                    markdown="להריץ את הפקודה."),
        ),
    ]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """אינדקס שנבנה מבנייה של הקומיט ``built``, ודפדפן הריפו מול המראה ומול אותו מסד."""
    repo = RepoWithMirror(tmp_path, REPO)
    built = repo.commit({RST: "דפדפן קוד\n=========\n", API_RST: "api\n===\n", "README.md": "# קרא אותי\n"})
    world = make_world(monkeypatch, FakeDB())
    fill(world, pages=_site_pages(), commit=built)
    for path in (RST, API_RST, "README.md"):
        world.db.repo_files.insert_one({"repo_name": REPO, "path": path, "commit_sha": built, "language": "text"})
    world.db.repo_metadata.insert_one({"repo_name": REPO, "default_branch": "main"})

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


def _show(world, sha, path=RST):
    """הדפדפן מציג את הקובץ מהקומיט שבו הוא אונדקס אחרון — כמו שהסנכרון של המראה כותב אותו."""
    world.db.repo_files.update_one({"repo_name": REPO, "path": path}, {"$set": {"commit_sha": sha}})


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
    }


def test_a_commit_that_did_not_touch_the_file_is_not_a_change(world):
    later = world.repo.commit({"README.md": "# קרא אותי, בגרסה חדשה\n"})
    _show(world, later)

    assert _docs_page(world).get_json()["freshness"] == docs_page_view.FRESHNESS_CURRENT


def test_a_file_that_changed_after_the_build_is_marked_changed(world):
    later = world.repo.commit({RST: "דפדפן קוד\n=========\n\nפסקה חדשה.\n"})
    _show(world, later)

    body = _docs_page(world).get_json()

    assert body["freshness"] == docs_page_view.FRESHNESS_CHANGED
    # העמוד עצמו הוא עדיין זה של הבנייה האחרונה.
    assert body["markdown"].startswith("# דפדפן קוד\n")


def test_a_version_from_the_history_is_compared_by_its_own_commit(world):
    later = world.repo.commit({RST: "דפדפן קוד\n=========\n\nפסקה חדשה.\n"})
    _show(world, later)

    assert _docs_page(world, ref=world.built).get_json()["freshness"] == docs_page_view.FRESHNESS_CURRENT
    assert _docs_page(world, ref=later).get_json()["freshness"] == docs_page_view.FRESHNESS_CHANGED


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
    monkeypatch.setattr(docs_page_view, "read_state", lambda db: next(states))

    assert docs_page_view.read_docs_page(world.db, RST)["indexed_commit"] is None


def test_a_database_error_while_reading_the_page_is_named(world, monkeypatch):
    def unreachable(db, path):
        raise ServerSelectionTimeoutError("no primary")

    monkeypatch.setattr(docs_page_view, "read_docs_page", unreachable)

    response = _docs_page(world)

    assert (response.status_code, response.get_json()) == (503, {"error": "docs_page_unavailable"})
