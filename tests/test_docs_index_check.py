"""הבדיקה שאחרי פריסת אתר התיעוד — ``scripts/docs_index_check.py`` והג'וב שמריץ אותה ב-``documentation.yml``.

החלק המרכזי רץ מקצה לקצה: שרת HTTP אמיתי (``werkzeug``) עם ה-blueprint של ה-webhooks, מעבר אמיתי מול האתר
המדומה של ``_docs_index_harness``, והסקריפט שולח אליו בקשות חתומות דרך ``urllib`` — אותו מסלול שה-CI עובר.
מה שמוזרק הוא רק השעון וההמתנה, כדי ששלושים דקות של בדיקה ירוצו בשנייה.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ‏``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _docs_index_harness import SHA_A, SHA_B, fill, make_world, site_pages  # noqa: E402
from _fake_mongo import FakeDB  # noqa: E402

from scripts import docs_index_check as check  # noqa: E402  (אחרי sys.path.insert, כמו בשאר טסטי הריפו)
from services import docs_index_service as svc  # noqa: E402
from services import docs_search_contract as contract  # noqa: E402
from services.docs_export_client import EXPORT_NOT_FOUND  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "documentation.yml"
SECRET = "test-webhook-secret"


# ---------------------------------------------------------------------------
# העולם: הוובאפ מאחורי שרת HTTP אמיתי
# ---------------------------------------------------------------------------


@pytest.fixture
def webapp(monkeypatch):
    """ה-blueprint של ה-webhooks מאחורי ``werkzeug`` על פורט פנוי, מול ``FakeDB`` ומעבר שרץ באותו thread."""
    import importlib

    from flask import Flask
    from werkzeug.serving import make_server

    from webapp.routes.webhooks import webhooks_bp

    db = FakeDB()
    world = make_world(monkeypatch, db)
    db_manager = importlib.import_module("database.db_manager")
    monkeypatch.setattr(db_manager, "get_db", lambda: db)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    app = Flask(__name__)
    app.register_blueprint(webhooks_bp)
    server = make_server("127.0.0.1", 0, app, threaded=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    world.base_url = f"http://127.0.0.1:{server.server_port}"
    world.app = app
    try:
        yield world
    finally:
        server.shutdown()
        thread.join(timeout=10)


class Clock:
    """שעון שמתקדם רק כשהסקריפט ממתין. ``on_sleep`` רץ בכל המתנה — כאן נכנס מה שקורה "בינתיים" בעולם."""

    def __init__(self, on_sleep=None):
        self.now = 0.0
        self.on_sleep = on_sleep
        self.sleeps = 0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.sleeps += 1
        if self.on_sleep is not None:
            self.on_sleep(self)


def _run(world, commit, *, secret=SECRET, base_url=None, clock=None):
    clock = clock or Clock()
    lines = []
    outcome = check.run_check(
        commit, base_url or world.base_url, secret, clock=clock, sleep=clock.sleep, log=lines.append
    )
    return outcome, lines


# ---------------------------------------------------------------------------
# מקצה לקצה
# ---------------------------------------------------------------------------


def test_a_webhook_that_already_brought_the_pass_needs_nothing(webapp):
    fill(webapp, commit=SHA_A)
    calls = []
    real_post = check.post_signed

    def counting_post(url, payload, secret):
        calls.append(url)
        return real_post(url, payload, secret)

    clock = Clock()
    outcome = check.run_check(SHA_A, webapp.base_url, SECRET, post=counting_post, clock=clock, sleep=clock.sleep,
                              log=lambda line: None)

    assert outcome.ok and outcome.resends == 0
    assert calls == [webapp.base_url + check.STATUS_PATH]


def test_a_lost_deployment_webhook_is_healed_by_sending_the_pass_again(webapp):
    """13.11.2026: הפריסה נפרסה וה-webhook שלה לא הגיע. הבדיקה רואה שאין מעבר, ושולחת אותו בעצמה."""
    fill(webapp, commit=SHA_A)
    pages = site_pages()
    pages[0]["sections"][0]["markdown"] = "טקסט שהשתנה בפריסה החדשה."
    webapp.site.publish(SHA_B, pages)  # האתר נפרס; ה-webhook לא נשלח

    outcome, lines = _run(webapp, SHA_B)

    assert outcome.ok, outcome.message
    assert outcome.resends == 1
    state = svc.read_state(webapp.db)
    assert state["indexed_source_commit"] == SHA_B
    assert (state["run"]["trigger"], state["run"]["requested_commit"]) == (svc.TRIGGER_DEPLOY, SHA_B)
    # לא נשלח שוב לפני שה-webhook של GitHub הספיק להגיע.
    assert outcome.elapsed >= check.RESEND_GRACE_SECONDS
    assert any("sent again (1/" in line for line in lines)


def test_a_pass_that_stops_for_approval_alerts_at_once(webapp):
    """מילוי ראשון: המעבר עוצר לאישור, ורק האדמין יכול להמשיך — אין טעם להמתין עד הדדליין."""
    webapp.site.publish(SHA_A, site_pages())

    outcome, _ = _run(webapp, SHA_A)

    assert not outcome.ok
    assert "מחכה לאישור" in outcome.message and SHA_A[:7] in outcome.message
    assert check.APPROVAL_REASONS[svc.APPROVAL_FIRST_FILL] in outcome.message
    assert outcome.elapsed < check.DEADLINE_SECONDS


def test_a_pass_that_keeps_failing_alerts_after_the_last_resend_with_its_code(webapp):
    fill(webapp, commit=SHA_A)
    # הקובץ הראשי עודכן, אבל העותק לפי הקומיט לא נכתב — כל מעבר של הפריסה נכשל ב-404.
    webapp.site.publish(SHA_B, site_pages(), commit_copy=False)

    outcome, _ = _run(webapp, SHA_B)

    assert not outcome.ok
    assert outcome.resends == check.MAX_RESENDS
    assert "לא התעדכן" in outcome.message
    assert svc.STATUS_FAILED in outcome.message and EXPORT_NOT_FOUND in outcome.message
    assert f"באינדקס עכשיו: {SHA_A[:7]}" in outcome.message
    assert outcome.elapsed < check.DEADLINE_SECONDS


def test_a_wrong_secret_stops_at_once_and_names_the_two_settings(webapp):
    webapp.site.publish(SHA_A, site_pages())

    outcome, _ = _run(webapp, SHA_A, secret="not-the-secret")

    assert not outcome.ok and outcome.resends == 0
    assert "401" in outcome.message and check.SECRET_ENV in outcome.message
    assert "GITHUB_WEBHOOK_SECRET" in outcome.message
    assert svc.read_state(webapp.db) is None


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_a_webapp_that_never_answers_alerts_at_the_deadline(webapp):
    outcome, _ = _run(webapp, SHA_A, base_url=f"http://127.0.0.1:{_closed_port()}")

    assert not outcome.ok
    assert outcome.elapsed >= check.DEADLINE_SECONDS
    assert f"תוך {check.DEADLINE_SECONDS // 60} דקות" in outcome.message
    assert "אין תשובה" in outcome.message and "לא התקבל מהוובאפ אף מצב" in outcome.message


def test_a_webapp_that_restarts_in_the_middle_is_waited_for(webapp):
    """הוובאפ עולה מחדש: בינתיים הנתיב עונה 503 (או לא עונה בכלל), ואחר כך המעבר מגיע."""
    fill(webapp, commit=SHA_A)
    pages = site_pages()
    pages[0]["sections"][0]["markdown"] = "טקסט חדש."
    webapp.site.publish(SHA_B, pages)
    real_post = check.post_signed
    answers = iter([check.Reply(503, {"error": "database_unavailable"})] * 4)

    def restarting(url, payload, secret):
        reply = next(answers, None)
        return reply if reply is not None else real_post(url, payload, secret)

    clock = Clock()
    outcome = check.run_check(SHA_B, webapp.base_url, SECRET, post=restarting, clock=clock, sleep=clock.sleep,
                              log=lambda line: None)

    assert outcome.ok, outcome.message
    assert outcome.resends == 1


def test_a_pass_that_holds_the_lease_is_waited_for_without_resending(webapp):
    """מעבר חי: שליחה חוזרת הייתה רק נכנסת לתור אחריו. כשהוא מסיים, הבדיקה מצליחה בלי לשלוח כלום."""
    fill(webapp, commit=SHA_A)
    pages = site_pages()
    pages[0]["sections"][0]["markdown"] = "עוד טקסט."
    webapp.site.publish(SHA_B, pages)
    from datetime import datetime, timedelta, timezone

    state = webapp.db[contract.STATE_COLLECTION]
    state.update_one({"_id": svc.STATE_ID}, {"$set": {
        "lease_holder": "github-webhook-runner",
        "lease_expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
    }})

    def webhook_pass_finishes(clock):
        if clock.sleeps == 10:  # ~200 שניות: אחרי ה-grace, ובלי שום שליחה חוזרת בינתיים
            state.update_one(
                {"_id": svc.STATE_ID}, {"$set": {"lease_holder": None, "lease_expires_at": svc._LEASE_FREE}}
            )
            assert svc.request_pass(webapp.db, trigger=svc.TRIGGER_DEPLOY, commit=SHA_B) == svc.REQUEST_STARTED

    outcome, _ = _run(webapp, SHA_B, clock=Clock(on_sleep=webhook_pass_finishes))

    assert outcome.ok, outcome.message
    assert outcome.resends == 0


# ---------------------------------------------------------------------------
# ההחלטה והצורה של התשובה
# ---------------------------------------------------------------------------


def _status(**overrides):
    fields = dict(indexed=False, indexed_commit=SHA_A, pass_alive=False, run_status=None, run_code=None,
                  run_trigger=None, run_source_commit=None, approval_commit=None, approval_reason=None,
                  approval_chunks=None)
    fields.update(overrides)
    return check.IndexStatus(**fields)


@pytest.mark.parametrize(
    "status,elapsed,resends,last,expected",
    [
        (_status(indexed=True), 0, 0, None, check.DONE),
        (_status(indexed=True, pass_alive=True, approval_commit=SHA_B), 0, 3, 0, check.DONE),
        (_status(pass_alive=True, approval_commit=SHA_B), 500, 0, None, check.WAIT),
        (_status(approval_commit=SHA_B, approval_reason=svc.APPROVAL_OVER_THRESHOLD), 0, 0, None,
         check.ALERT_APPROVAL),
        (_status(approval_commit=SHA_A), 500, 0, None, check.RESEND),  # אישור לקומיט אחר אינו של הפריסה הזו
        (_status(), 0, 0, None, check.WAIT),
        (_status(), check.RESEND_GRACE_SECONDS, 0, None, check.RESEND),
        (_status(), 200, 1, 100, check.WAIT),
        (_status(), 100 + check.RESEND_INTERVAL_SECONDS, 1, 100, check.RESEND),
        (_status(), 900, check.MAX_RESENDS, 700, check.ALERT_GAVE_UP),
        (_status(pass_alive=True), 900, check.MAX_RESENDS, 700, check.WAIT),
    ],
)
def test_the_decision_for_each_state(status, elapsed, resends, last, expected):
    assert check.decide(status, commit=SHA_B, elapsed=elapsed, resends=resends, last_resend_at=last) == expected


def _answer(**overrides):
    answer = {"commit": SHA_B, "indexed": False, "indexed_source_commit": SHA_A, "pass_alive": False,
              "pending": False, "run": None, "approval": None}
    answer.update(overrides)
    return answer


@pytest.mark.parametrize(
    "answer",
    [
        None,
        [],
        "ok",
        _answer(commit=SHA_A),
        _answer(indexed="false"),
        _answer(pass_alive=1),
        _answer(indexed_source_commit="abc"),
        _answer(run=[]),
        _answer(run={"status": 7}),
        _answer(run={"code": "x" * (check.MAX_FIELD_CHARS + 1)}),
        _answer(run={"source_commit": SHA_A.upper()}),
        _answer(approval="yes"),
        _answer(approval={"chunks_to_embed": True}),
        _answer(approval={"chunks_to_embed": -1}),
        _answer(approval={"chunks_to_embed": 1.5}),
        _answer(approval={"source_commit": 5}),
    ],
)
def test_an_answer_in_any_other_shape_is_refused(answer):
    with pytest.raises(check.InvalidAnswer):
        check.parse_status(answer, SHA_B)


def test_the_answer_the_webapp_gives_is_the_shape_the_script_reads(webapp):
    """הוובאפ האמיתי עונה, והסקריפט קורא — בלי טקסט ביניים שנכתב ביד."""
    fill(webapp, commit=SHA_A)

    reply = check.post_signed(webapp.base_url + check.STATUS_PATH, {"commit": SHA_A}, SECRET)
    status = check.parse_status(reply.body, SHA_A)

    assert reply.status == 200
    assert status.indexed and status.indexed_commit == SHA_A and not status.pass_alive
    assert status.run_status == svc.STATUS_COMPLETE and status.run_source_commit == SHA_A


def test_the_script_paths_are_the_routes_the_blueprint_declares(webapp):
    paths = {rule.endpoint: rule.rule for rule in webapp.app.url_map.iter_rules()}

    assert paths["webhooks.docs_index_check_status"] == check.STATUS_PATH
    assert paths["webhooks.docs_index_check_pass"] == check.PASS_PATH


def test_a_redirect_is_returned_as_a_status_and_not_followed():
    """הפניה מהוובאפ אינה צפויה; הגוף החתום לא נשלח לכתובת אחרת."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = []

    class Redirecting(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 — השם שהמחלקה דורשת
            seen.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):  # noqa: N802
            seen.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            return None

    server = HTTPServer(("127.0.0.1", 0), Redirecting)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        reply = check.post_signed(f"http://127.0.0.1:{server.server_port}/status", {"commit": SHA_A}, SECRET)
    finally:
        server.shutdown()
        thread.join(timeout=10)

    assert reply.status == 302
    assert seen == ["/status"]


# ---------------------------------------------------------------------------
# העותקים שכתובים בסקריפט, מול הבעלים שלהם
# ---------------------------------------------------------------------------


def test_the_deadline_covers_a_dead_lease_and_a_full_pass_after_it():
    """המקרה הגרוע: מעבר שמת מחזיק ב-lease עד שהוא פג, ואחריו המעבר שנשלח שוב רץ עד התקרה שלו."""
    assert check.DEADLINE_SECONDS >= svc.LEASE_SECONDS + svc.PASS_DEADLINE_SECONDS + 2 * check.POLL_SECONDS


def test_the_job_timeout_covers_the_deadline():
    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["check-docs-index"]

    # חמש דקות להכנת הג'וב (checkout, ‏setup-python) ולבקשה האחרונה.
    assert job["timeout-minutes"] * 60 >= check.DEADLINE_SECONDS + 5 * 60


def test_the_approval_reasons_and_request_answers_are_the_service_codes():
    assert set(check.APPROVAL_REASONS) == {
        svc.APPROVAL_FIRST_FILL, svc.APPROVAL_OVER_THRESHOLD, svc.CODE_APPROVAL_MISMATCH
    }
    assert check.ACCEPTED_REQUESTS == {svc.REQUEST_STARTED, svc.REQUEST_QUEUED}


# ---------------------------------------------------------------------------
# הג'וב ב-workflow
# ---------------------------------------------------------------------------


def _jobs():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def test_the_check_runs_after_a_deployment_that_has_an_export():
    jobs = _jobs()
    job = jobs["check-docs-index"]

    assert set(job["needs"]) == {"build-docs", "deploy-docs"}
    assert job["if"] == "${{ needs.build-docs.outputs.sections_export == 'success' }}"
    assert jobs["build-docs"]["outputs"]["sections_export"] == "${{ steps.export_sections.outcome }}"
    export_steps = [step for step in jobs["build-docs"]["steps"] if step.get("id") == "export_sections"]
    assert len(export_steps) == 1 and export_steps[0].get("continue-on-error") is True


def test_the_check_step_gives_the_script_what_it_reads():
    steps = {step.get("id"): step for step in _jobs()["check-docs-index"]["steps"]}
    env = steps["check"]["env"]

    assert env["WEBAPP_URL"] == "${{ vars.WEBAPP_URL }}"
    assert env[check.SECRET_ENV] == f"${{{{ secrets.{check.SECRET_ENV} }}}}"
    assert not check.SECRET_ENV.startswith("GITHUB_")  # GitHub אינו מתיר סוד בשם שמתחיל כך
    assert env["SOURCE_COMMIT"] == "${{ github.sha }}"
    assert steps["check"]["run"] == 'python scripts/docs_index_check.py --commit "${SOURCE_COMMIT}"'


def test_every_failure_of_the_check_job_reaches_telegram():
    steps = _jobs()["check-docs-index"]["steps"]
    alerts = [step for step in steps if step.get("uses") == "./.github/actions/telegram-message"]

    conditions = sorted(step["if"] for step in alerts)
    assert conditions == [
        "${{ failure() && steps.check.outcome != 'failure' }}",
        "${{ failure() && steps.check.outcome == 'failure' }}",
    ]
    message_step = next(step for step in alerts if "== 'failure'" in step["if"])
    assert "${{ steps.check.outputs.message }}" in message_step["with"]["text"]
    assert all(step.get("continue-on-error") is True for step in alerts)
    assert steps.index(message_step) > [step.get("id") for step in steps].index("check")


# ---------------------------------------------------------------------------
# הכניסה: תצורה חסרה, הפלט ל-GitHub, וריצה בלי חבילות
# ---------------------------------------------------------------------------


def _read_output(path: Path) -> dict:
    """קורא את ``$GITHUB_OUTPUT`` בתחביר ``name<<delimiter`` — כמו ש-GitHub קורא אותו."""
    values, lines = {}, path.read_text(encoding="utf-8").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        if "<<" in line:
            name, delimiter = line.split("<<", 1)
            end = lines.index(delimiter, index + 1)
            values[name] = "\n".join(lines[index + 1:end])
            index = end + 1
        else:
            index += 1
    return values


@pytest.fixture
def github_files(tmp_path, monkeypatch):
    output, summary = tmp_path / "output", tmp_path / "summary"
    output.touch()
    summary.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("WEBAPP_URL", "https://webapp.example.test")
    monkeypatch.setenv(check.SECRET_ENV, SECRET)
    return output, summary


@pytest.mark.parametrize(
    "unset,value,expected",
    [
        ("WEBAPP_URL", None, "WEBAPP_URL לא הוגדר"),
        ("WEBAPP_URL", "http://webapp.example.test", "WEBAPP_URL ב-GitHub פגום"),
        (check.SECRET_ENV, None, f"הסוד {check.SECRET_ENV} לא הוגדר"),
    ],
)
def test_a_missing_setting_is_an_alert_that_names_it(github_files, monkeypatch, unset, value, expected):
    output, _ = github_files
    if value is None:
        monkeypatch.delenv(unset, raising=False)
    else:
        monkeypatch.setenv(unset, value)

    assert check.main(["--commit", SHA_A]) == 1
    assert expected in _read_output(output)["message"]


def test_a_commit_that_is_not_a_sha_is_an_alert(github_files):
    output, _ = github_files

    assert check.main(["--commit", "HEAD"]) == 1
    assert "אינו sha מלא" in _read_output(output)["message"]


def test_the_alert_message_survives_the_trip_through_github_output(github_files, monkeypatch):
    output, summary = github_files
    message = "שורה ראשונה\nEOF\nשורה שלישית"
    monkeypatch.setattr(check, "run_check", lambda *a, **k: check.Outcome(False, message, 2, 1800.0))

    assert check.main(["--commit", SHA_A]) == 1
    assert _read_output(output)["message"] == message
    assert "שורה שלישית" in summary.read_text(encoding="utf-8")


def test_a_bug_in_the_check_is_an_alert_of_its_own(github_files, monkeypatch, capsys):
    output, _ = github_files

    def broken(*args, **kwargs):
        raise KeyError("a bug")

    monkeypatch.setattr(check, "run_check", broken)

    assert check.main(["--commit", SHA_A]) == 1
    assert "קרסה" in _read_output(output)["message"]
    assert "KeyError" in capsys.readouterr().err


def test_a_success_writes_no_alert_and_says_when_it_had_to_resend(github_files, monkeypatch):
    output, summary = github_files
    monkeypatch.setattr(check, "run_check", lambda *a, **k: check.Outcome(True, None, 1, 95.0))

    assert check.main(["--commit", SHA_A]) == 0
    assert _read_output(output) == {}
    assert "שליחות חוזרות" in summary.read_text(encoding="utf-8")


def test_the_admin_link_comes_from_webapp_url(webapp, monkeypatch):
    monkeypatch.setenv("WEBAPP_URL", "https://webapp.example.test")
    webapp.site.publish(SHA_A, site_pages())

    outcome, _ = _run(webapp, SHA_A)

    assert "https://webapp.example.test/admin/docs-index" in outcome.message


def test_the_script_runs_without_any_installed_package(tmp_path):
    """הג'וב ב-CI לא מתקין כלום. ``-S`` מוריד את site-packages, ולכן ייבוא של חבילה חיצונית היה נכשל כאן."""
    finished = subprocess.run(
        [sys.executable, "-B", "-S", "-I", str(ROOT / "scripts" / "docs_index_check.py"), "--commit", "HEAD"],
        capture_output=True, text=True, timeout=60, cwd=tmp_path,
        env={"GITHUB_OUTPUT": str(tmp_path / "out"), "PATH": "/usr/bin:/bin"},
    )

    assert finished.returncode == 1, finished.stderr
    assert "אינו sha מלא" in finished.stderr
    assert "ModuleNotFoundError" not in finished.stderr
