"""מה שמפעיל את אינדקס התיעוד ומה שמציג אותו: ה-webhook של הפריסה, רשת הביטחון ב-webhook של push,
ההחרגה מהמגבלה הגורפת, וה-API והעמוד של האדמין.

ה-webhooks נבדקים דרך הנתיב האמיתי, עם payload בצורה של ``deployment_status`` ושל ``push`` וחתימת HMAC תקפה. ה-API
נבדק דרך ``webapp.app`` עצמו — עם ``admin_api_required`` האמיתי — מול ``_fake_mongo`` והאתר המדומה
של ``_docs_index_harness``, כך ש"בדוק עכשיו" ו"אשר והתחל" מריצים מעבר שלם בתוך הבקשה.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import re
from types import SimpleNamespace

import pytest
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

# ‏``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _docs_index_harness import SHA_A, make_world, site_pages
from _fake_mongo import FakeCollection, FakeDB

from services import docs_index_service as svc
from services import docs_search_contract as contract

SECRET = "test-webhook-secret"


# ---------------------------------------------------------------------------
# ה-webhook של הפריסה
# ---------------------------------------------------------------------------


def _deployment_status(state="success", environment="github-pages", full_name="amirbiron/CodeBot", sha=SHA_A):
    """הצורה של ``deployment_status`` (https://docs.github.com/en/webhooks/webhook-events-and-payloads)."""
    return {
        "action": "created",
        "deployment_status": {"state": state, "environment": environment},
        "deployment": {"sha": sha, "ref": "main", "task": "deploy", "environment": environment},
        "repository": {"name": full_name.split("/")[-1], "full_name": full_name},
    }


@pytest.fixture
def hook(monkeypatch):
    from flask import Flask

    from webapp.routes.webhooks import webhooks_bp

    # המודול ולא ``from database import db_manager``: לחבילה יש תכונה בשם הזה.
    db_manager = importlib.import_module("database.db_manager")
    db = FakeDB()
    started = []
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(db_manager, "get_db", lambda: db)
    monkeypatch.setattr(svc, "_runner_factory", started.append)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(webhooks_bp)
    client = app.test_client()

    def deliver(payload, *, event="deployment_status", secret=SECRET):
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return client.post(
            "/api/webhooks/github",
            data=body,
            content_type="application/json",
            headers={"X-Hub-Signature-256": signature, "X-GitHub-Event": event, "X-GitHub-Delivery": "d-1"},
        )

    return SimpleNamespace(db=db, started=started, deliver=deliver, db_manager=db_manager)


def test_a_successful_pages_deployment_requests_a_pass_for_its_commit(hook):
    response = hook.deliver(_deployment_status())

    assert response.status_code == 202
    assert response.get_json()["status"] == svc.REQUEST_STARTED
    pending = svc.read_state(hook.db)["pending"]
    assert (pending["trigger"], pending["commit"]) == (svc.TRIGGER_DEPLOY, SHA_A)
    assert len(hook.started) == 1
    assert hook.deliver(_deployment_status()).get_json()["status"] == svc.REQUEST_QUEUED


@pytest.mark.parametrize(
    "payload,reason",
    [
        (_deployment_status(full_name="someone/CodeBot"), "other_repository"),
        (_deployment_status(environment="preview"), "other_environment"),
        *[(_deployment_status(state=state), "not_success")
          for state in ("waiting", "queued", "in_progress", "pending", "failure", "error", "inactive")],
    ],
)
def test_a_deployment_that_is_not_a_finished_pages_deployment_is_ignored(hook, payload, reason):
    response = hook.deliver(payload)

    assert response.status_code == 200
    assert response.get_json()["reason"] == reason
    assert svc.read_state(hook.db) is None and hook.started == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(deployment=[p["deployment"]]),
        lambda p: p.pop("deployment_status"),
        lambda p: p.update(repository=None),
        lambda p: p["deployment"].update(sha="abc"),
        lambda p: p["deployment"].update(sha=SHA_A.upper()),
        lambda p: p["deployment"].update(sha=None),
        lambda p: p["deployment"].update(sha=7),
    ],
)
def test_a_malformed_deployment_status_requests_nothing(hook, mutate):
    payload = _deployment_status()
    mutate(payload)

    response = hook.deliver(payload)

    assert response.status_code == 400
    assert svc.read_state(hook.db) is None and hook.started == []


def test_a_deployment_status_with_a_bad_signature_is_refused(hook):
    response = hook.deliver(_deployment_status(), secret="not-the-secret")

    assert response.status_code == 401
    assert svc.read_state(hook.db) is None


def test_a_deployment_status_without_a_database_is_503(hook, monkeypatch):
    monkeypatch.setattr(hook.db_manager, "get_db", lambda: None)

    assert hook.deliver(_deployment_status()).status_code == 503


class _StateUnreachable(FakeCollection):
    def update_one(self, *args, **kwargs):
        raise ServerSelectionTimeoutError("no primary available")


def test_a_database_failure_while_requesting_is_503(hook):
    hook.db.c[contract.STATE_COLLECTION] = _StateUnreachable()

    assert hook.deliver(_deployment_status()).status_code == 503
    assert hook.started == []


def test_the_github_webhook_is_exempt_from_the_global_rate_limit():
    """המגבלה הגורפת היא לפי IP, ו-GitHub שולח מכמה כתובות קבועות — push וסטטוסי פריסה נספרים יחד.

    ``exemption_scope`` הוא מה שהמגביל עצמו שואל על כל בקשה (``flask_limiter/_extension.py``,
    4.0.0), ולכן הבדיקה לא תלויה באחסון של המגביל — ב-CI הוא Redis שאינו נגיש, והמגבלה שם
    נבלעת (``swallow_errors``).
    """
    from flask_limiter import ExemptionScope

    import webapp.app as wa

    assert wa.limiter is not None
    manager = wa.limiter.limit_manager
    assert manager.exemption_scope(wa.app, "webhooks.handle_github_webhook", "webhooks") & ExemptionScope.DEFAULT
    assert not manager.exemption_scope(wa.app, "api_docs_index_status", None) & ExemptionScope.DEFAULT


# ---------------------------------------------------------------------------
# רשת הביטחון: push לענף הראשי של ריפו המקור
# ---------------------------------------------------------------------------


def _push(full_name=contract.SOURCE_REPO_FULL_NAME, ref="refs/heads/main", after="a" * 40):
    """הצורה של ``push``: ``repository`` הוא אובייקט הריפו, ו-``full_name`` ו-``default_branch`` שדות חובה בו
    (``payload-schemas/api.github.com/push/event.schema.json`` ו-``common/repository.schema.json`` ב-octokit/webhooks).
    """
    return {
        "ref": ref,
        "before": "b" * 40,
        "after": after,
        "repository": {"name": full_name.split("/")[-1], "full_name": full_name, "default_branch": "main"},
    }


@pytest.fixture
def queued(monkeypatch):
    """הסנכרון של המראה, בלי git: מה שה-webhook העביר ל-``trigger_sync``."""
    from services import repo_sync_service

    calls = []
    monkeypatch.setattr(repo_sync_service, "trigger_sync", lambda **kwargs: calls.append(kwargs) or "job-1")
    return calls


def test_a_push_to_the_source_repo_queues_the_sync_and_asks_for_a_docs_check(hook, queued):
    response = hook.deliver(_push(), event="push")

    assert response.status_code == 202
    body = response.get_json()
    assert (body["status"], body["docs_index"]) == ("queued", svc.REQUEST_STARTED)
    assert [call["repo_name"] for call in queued] == [contract.SOURCE_REPO_NAME]
    pending = svc.read_state(hook.db)["pending"]
    assert (pending["trigger"], pending["commit"]) == (svc.TRIGGER_PUSH, None)
    assert len(hook.started) == 1
    assert hook.deliver(_push(), event="push").get_json()["docs_index"] == svc.REQUEST_QUEUED


@pytest.mark.parametrize(
    "payload,status,synced",
    [
        # אותו שם ריפו, בעלים אחר: מסתנכרן כרגיל, אבל אינו המקור של האתר
        (_push(full_name="someone/CodeBot"), 202, True),
        (_push(ref="refs/heads/feature"), 200, False),
        (_push(after="0" * 40), 200, False),  # מחיקה של הענף
    ],
)
def test_a_push_that_is_not_a_new_commit_on_the_source_main_branch_asks_for_no_docs_check(
    hook, queued, payload, status, synced
):
    response = hook.deliver(payload, event="push")

    assert response.status_code == status
    assert "docs_index" not in response.get_json()
    assert bool(queued) is synced
    assert svc.read_state(hook.db) is None and hook.started == []


def test_a_push_without_a_database_still_answers_with_the_queued_sync(hook, queued, monkeypatch):
    monkeypatch.setattr(hook.db_manager, "get_db", lambda: None)

    response = hook.deliver(_push(), event="push")

    assert response.status_code == 202
    assert response.get_json()["docs_index"] == "database_unavailable"
    assert len(queued) == 1


def test_a_database_failure_while_asking_for_the_docs_check_does_not_fail_the_push(hook, queued, caplog):
    hook.db.c[contract.STATE_COLLECTION] = _StateUnreachable()

    response = hook.deliver(_push(), event="push")

    assert response.status_code == 202
    assert response.get_json()["docs_index"] == "database_unavailable"
    assert len(queued) == 1 and hook.started == []
    assert "the push safety net could not request a pass" in caplog.text


def test_a_bug_in_the_docs_check_is_not_disguised_as_a_database_failure(hook, queued, monkeypatch):
    def broken(db, **kwargs):
        raise ValueError("unknown trigger 'push'")

    monkeypatch.setattr(svc, "request_pass", broken)

    response = hook.deliver(_push(), event="push")

    assert response.status_code == 500


# ---------------------------------------------------------------------------
# ה-API והעמוד
# ---------------------------------------------------------------------------


class _SearchNotEnabled(FakeCollection):
    """אוסף בשרת שאינו Atlas: מה ש-MongoDB 8.0.32 עונה (נמדד 7.10.2026)."""

    def list_search_indexes(self, name=None, session=None, comment=None, **kwargs):
        raise OperationFailure("Using Atlas Search Database Commands ... requires additional configuration",
                               code=svc.SEARCH_NOT_ENABLED_CODE)


@pytest.fixture
def admin_app(monkeypatch):
    import webapp.app as wa

    db = FakeDB()
    db.c[contract.CHUNKS_COLLECTION] = _SearchNotEnabled()
    world = make_world(monkeypatch, db)
    audits = []
    monkeypatch.setattr(wa, "get_db", lambda: db)
    monkeypatch.setattr(wa, "emit_event", lambda name, severity="info", **fields: audits.append((name, fields)))
    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    monkeypatch.setitem(wa.app.config, "SECRET_KEY", "docs-index-tests")
    client = wa.app.test_client()

    def login(user_id):
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_data"] = {"id": user_id, "is_admin": user_id == 1, "is_premium": False}

    return SimpleNamespace(wa=wa, db=db, world=world, client=client, login=login, audits=audits)


_API = [
    ("GET", "/api/docs-index"),
    ("GET", "/api/docs-index/plan"),
    ("POST", "/api/docs-index/start"),
    ("POST", "/api/docs-index/check"),
    ("POST", "/api/docs-index/stop"),
]


def _call(client, method, path, body=None):
    if method == "GET":
        return client.get(path)
    return client.post(path, json=body if body is not None else {})


@pytest.mark.parametrize("method,path", _API)
def test_the_api_refuses_without_a_session_and_without_an_admin(admin_app, method, path):
    response = _call(admin_app.client, method, path)
    assert (response.status_code, response.get_json()["error"]) == (401, "login_required")

    admin_app.login(2)
    response = _call(admin_app.client, method, path)
    assert (response.status_code, response.get_json()["error"]) == (403, "admin_only")
    assert svc.read_state(admin_app.db) is None


@pytest.mark.parametrize("method,path", _API)
def test_the_api_refuses_an_admin_who_is_viewing_as_a_user(admin_app, method, path):
    admin_app.login(1)
    assert admin_app.client.post("/admin/impersonate/start").status_code == 200

    response = _call(admin_app.client, method, path)

    assert (response.status_code, response.get_json()["error"]) == (403, "impersonation_active")
    assert svc.read_state(admin_app.db) is None


def test_force_admin_lets_an_impersonating_admin_through_like_the_pages(admin_app):
    admin_app.login(1)
    admin_app.client.post("/admin/impersonate/start")

    assert admin_app.client.get("/api/docs-index?force_admin=1").status_code == 200


def test_check_then_start_runs_the_plan_the_admin_saw(admin_app):
    admin_app.world.site.publish(SHA_A, site_pages())
    admin_app.login(1)

    checked = admin_app.client.post("/api/docs-index/check", json={})
    assert (checked.status_code, checked.get_json()["status"]) == (202, svc.REQUEST_STARTED)
    status = admin_app.client.get("/api/docs-index").get_json()
    assert status["run"]["status"] == svc.STATUS_AWAITING_APPROVAL
    fingerprint = status["approval"]["fingerprint"]

    started = admin_app.client.post("/api/docs-index/start", json={"fingerprint": fingerprint})

    assert started.status_code == 202
    after = admin_app.client.get("/api/docs-index").get_json()
    assert after["indexed"]["source_commit"] == SHA_A
    assert after["counts"] == {"chunks": 4, "sections": 4}
    # ``emit_event`` של האפליקציה רושם גם אירועי בקשה (``access_logs`` ועוד); כאן רק אירועי הביקורת.
    actions = [fields for name, fields in admin_app.audits if name == "docs_index_admin_action"]
    assert [(fields["action"], fields["result"], fields["user_id"]) for fields in actions] == [
        ("check", svc.REQUEST_STARTED, 1),
        ("start", svc.REQUEST_STARTED, 1),
    ]


def test_the_status_carries_times_with_their_zone_and_an_unknown_vector_index(admin_app):
    admin_app.world.site.publish(SHA_A, site_pages())
    admin_app.login(1)
    admin_app.client.post("/api/docs-index/check", json={})

    status = admin_app.client.get("/api/docs-index").get_json()

    for value in (status["now"], status["run"]["started_at"], status["approval"]["created_at"]):
        assert re.search(r"T\d\d:\d\d:\d\d(\.\d+)?\+00:00$", value), value
    assert status["vector_index"]["status"] == "unknown"
    assert status["vector_index"]["definition"] == contract.vector_index_definition(4)
    assert (status["mirror"]["repo"], status["pass_alive"]) == (contract.SOURCE_REPO_NAME, False)


@pytest.mark.parametrize("body", [{"fingerprint": 7}, {"fingerprint": "abc"}, {"fingerprint": "A" * 64}, {}])
def test_start_refuses_anything_that_is_not_a_fingerprint(admin_app, body):
    admin_app.login(1)

    response = admin_app.client.post("/api/docs-index/start", json=body)

    assert (response.status_code, response.get_json()["error"]) == (400, "fingerprint_invalid")
    assert svc.read_state(admin_app.db) is None


def test_a_post_that_is_not_json_is_refused(admin_app):
    admin_app.login(1)

    form = admin_app.client.post("/api/docs-index/start", data={"fingerprint": "a" * 64})
    assert (form.status_code, form.get_json()["error"]) == (415, "json_required")
    listed = admin_app.client.post("/api/docs-index/check", data="[1]", content_type="application/json")
    assert (listed.status_code, listed.get_json()["error"]) == (400, "invalid_json")
    assert svc.read_state(admin_app.db) is None


def test_stop_without_a_live_pass_is_a_conflict(admin_app):
    admin_app.login(1)

    response = admin_app.client.post("/api/docs-index/stop", json={})

    assert (response.status_code, response.get_json()["error"]) == (409, "no_live_pass")


def test_stop_with_a_live_pass_asks_it_to_stop(admin_app):
    svc._put_pending(admin_app.db, {"trigger": svc.TRIGGER_MANUAL_CHECK})
    assert svc._take_lease(admin_app.db, "runner")
    admin_app.login(1)

    response = admin_app.client.post("/api/docs-index/stop", json={})

    assert response.status_code == 202
    assert svc.read_state(admin_app.db)["stop_requested"] is True
    assert admin_app.client.get("/api/docs-index").get_json()["pass_alive"] is True


def test_the_plan_is_computed_from_the_main_file(admin_app):
    admin_app.world.site.publish(SHA_A, site_pages())
    admin_app.login(1)

    response = admin_app.client.get("/api/docs-index/plan")

    plan = response.get_json()["plan"]
    assert (plan["chunks_to_embed"], plan["approval_reason"]) == (4, svc.APPROVAL_FIRST_FILL)
    assert plan["built_at"].endswith("+00:00")
    assert svc.read_state(admin_app.db) is None


def test_a_plan_without_an_export_names_the_failure(admin_app):
    admin_app.login(1)

    response = admin_app.client.get("/api/docs-index/plan")

    assert (response.status_code, response.get_json()["error"]) == (502, "export_not_found")


def test_the_api_without_a_database_is_503(admin_app, monkeypatch):
    monkeypatch.setattr(admin_app.wa, "get_db", lambda: None)
    admin_app.login(1)

    response = admin_app.client.get("/api/docs-index")

    assert (response.status_code, response.get_json()["error"]) == (503, "database_unavailable")


def test_the_page_calls_exactly_the_registered_api_routes(admin_app):
    """הכתובות שה-JS של העמוד קורא נגזרות מה-HTML שיצא, ומושוות לראוטים הרשומים ולמתודות שלהם."""
    admin_app.login(1)

    page = admin_app.client.get("/admin/docs-index")

    assert page.status_code == 200
    block = re.search(r"const API = \{(.*?)\};", page.get_data(as_text=True), re.S).group(1)
    urls = dict(re.findall(r"(\w+): \"([^\"]+)\"", block))
    adapter = admin_app.wa.app.url_map.bind("localhost")
    expected = {
        "status": ("GET", "api_docs_index_status"),
        "plan": ("GET", "api_docs_index_plan"),
        "start": ("POST", "api_docs_index_start"),
        "check": ("POST", "api_docs_index_check"),
        "stop": ("POST", "api_docs_index_stop"),
    }
    assert set(urls) == set(expected)
    for key, (method, endpoint) in expected.items():
        assert adapter.match(urls[key], method=method)[0] == endpoint, key


def test_the_page_is_for_admins_only(admin_app):
    admin_app.login(2)
    assert admin_app.client.get("/admin/docs-index").status_code == 403


# ---------------------------------------------------------------------------
# מצב האינדקס הווקטורי
# ---------------------------------------------------------------------------


class _Indexes(FakeCollection):
    def __init__(self, answer):
        super().__init__()
        self.answer = answer

    def list_search_indexes(self, name=None, session=None, comment=None, **kwargs):
        if isinstance(self.answer, Exception):
            raise self.answer
        return iter(self.answer)


def _vector_status(answer, dimensions=768):
    db = FakeDB()
    db.c[contract.CHUNKS_COLLECTION] = _Indexes(answer)
    return svc.vector_index_status(db, dimensions)


def _atlas_index(status="READY", dimensions=768):
    return {
        "id": "1", "name": contract.VECTOR_INDEX_NAME, "status": status, "queryable": status == "READY",
        "latestDefinition": {"fields": [
            {"type": "vector", "path": contract.VECTOR_FIELD, "numDimensions": dimensions, "similarity": "cosine"},
            {"type": "filter", "path": contract.MODEL_KEY_FIELD},
        ]},
    }


def test_a_ready_index_built_for_the_active_dimensions():
    report = _vector_status([_atlas_index()])
    assert (report["status"], report["queryable"], report["dimensions_match"]) == ("READY", True, True)


def test_an_index_built_for_other_dimensions_is_reported():
    report = _vector_status([_atlas_index(dimensions=3072)])
    assert (report["dimensions"], report["dimensions_match"]) == (3072, False)


@pytest.mark.parametrize(
    "answer,status",
    [
        ([], "missing"),
        (OperationFailure("ns not found", code=26), "missing"),
        (OperationFailure("search is not enabled", code=svc.SEARCH_NOT_ENABLED_CODE), "unknown"),
        ([{"status": 5, "latestDefinition": "x"}], "unknown"),
    ],
)
def test_the_vector_index_status_names_each_answer(answer, status):
    report = _vector_status(answer)
    assert report["status"] == status
    assert report["definition"] == contract.vector_index_definition(768)


def test_a_refusal_is_an_error_and_not_missing():
    """למשל משתמש מסד בלי הרשאה ל-``$listSearchIndexes``: העמוד אומר שהשרת סירב, ולא שאין אינדקס —
    ושאר עמוד המצב ממשיך לעבוד."""
    report = _vector_status(OperationFailure("not authorized", code=13))
    assert (report["status"], report["detail"]) == ("error", "OperationFailure code 13")


def test_a_database_that_cannot_be_reached_is_not_a_vector_status():
    with pytest.raises(ServerSelectionTimeoutError):
        _vector_status(ServerSelectionTimeoutError("no primary available"))
