"""ההחלטות של ``notify-post-merge-issue.yml``: מתי אישו של כשל אחרי מיזוג נסגר, ואיפה נשמר הקומיט שנכשל.

הטסט מריץ את הסקריפטים עצמם, כמו שהם כתובים ב-YAML, ולא עותק שלהם. הוא שולף את ה-``script`` של
שני צעדי ``actions/github-script`` (הפתיחה והסגירה) ואת ה-``env`` של ה-workflow, ומריץ אותם ב-``node``
באותה צורה שבה github-script מריץ: ``new AsyncFunction(...Object.keys(args), source)`` עם ``github``,
``context`` ו-``core`` (``src/async-function.ts`` ב-actions/github-script@v7). ``github`` מדומה: הוא רושם
כל קריאה, ובהשוואת קומיטים מחזיר את ה-merge base שהטסט קבע.

למה הסגירה בודקת היסטוריה: ל-``deploy.yml`` אין ``concurrency``, ולכן ריצות של קומיטים סמוכים רצות
במקביל, וריצה שנכשלת מסתיימת לפני ריצה מוצלחת. בלי הבדיקה, הצלחה של קומיט ישן שמגיעה אחרי הכשל
הייתה סוגרת את האישו של קומיט חדש יותר שעדיין שבור. ראו ``docs/ci-cd.rst``, "אישו על כשל אחרי מיזוג".

למה הסגירה עוברת על כל האישיוז: לכל קומיט שנכשל נפתח אישו משלו, ושני כשלים ברצף על ``main`` הם שני
אישיוז שאותה ריצה מוצלחת מכסה. עד 27.11.2026 הסגירה בדקה רק את האישו החדש ביותר, ולכן #3740 נשאר פתוח
אחרי ש-#3741 נסגר.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "notify-post-merge-issue.yml"

WORKFLOW_NAME = "🚀 Code Keeper Bot CI/CD"
FAILED_SHA = "1" * 40
SUCCESS_SHA = "2" * 40
OLDER_SHA = "3" * 40

# הרצה של סקריפט github-script מול github מדומה. הקלט מגיע בקובץ JSON, והפלט הוא רשימת הקריאות.
_HARNESS = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const AsyncFunction = Object.getPrototypeOf(async () => null).constructor;
const calls = [];
const logs = [];
// שגיאה בצורה של RequestError מ-@octokit/request-error, שדרכו github-script@v7 קורא ל-API: status מספרי.
const httpError = (failure) => {
  const err = new Error(failure.message);
  err.name = 'HttpError';
  err.status = failure.status;
  return err;
};
const github = {
  paginate: async () => input.openIssues,
  rest: {
    issues: {
      listForRepo: function listForRepo() {},
      createComment: async (p) => { calls.push(['createComment', p]); return { data: {} }; },
      update: async (p) => {
        const failure = input.updateErrors[String(p.issue_number)];
        calls.push([failure ? 'updateFailed' : 'update', p]);
        if (failure) throw httpError(failure);
        return { data: {} };
      },
      create: async (p) => { calls.push(['create', p]); return { data: { number: 101 } }; },
      createLabel: async () => ({}),
      addLabels: async () => ({}),
      addAssignees: async () => ({}),
    },
    repos: {
      getCommit: async () => ({ data: { commit: { message: 'subject' } } }),
      compareCommitsWithBasehead: async (p) => {
        calls.push(['compare', p]);
        const failure = input.compareErrors[p.basehead];
        if (failure) throw httpError(failure);
        return { data: { status: 'mock', merge_base_commit: { sha: input.mergeBases[p.basehead] } } };
      },
    },
  },
};
const core = {
  info: (m) => logs.push(['info', String(m)]),
  warning: (m) => logs.push(['warning', String(m)]),
  error: (m) => logs.push(['error', String(m)]),
  setFailed: (m) => logs.push(['setFailed', String(m)]),
};
const context = { payload: { workflow_run: input.workflowRun }, repo: { owner: 'o', repo: 'r' } };
new AsyncFunction('github', 'context', 'core', input.script)(github, context, core)
  .then(() => console.log(JSON.stringify({ ok: true, calls, logs })))
  .catch((err) => console.log(JSON.stringify({ ok: false, error: String(err && err.message), calls, logs })));
"""


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _script(job: str, step_name_prefix: str) -> str:
    for step in _workflow()["jobs"][job]["steps"]:
        if str(step.get("uses", "")).startswith("actions/github-script") and step.get("name", "").startswith(
            step_name_prefix
        ):
            return step["with"]["script"]
    raise AssertionError(f"לא נמצא צעד github-script שמתחיל ב-{step_name_prefix!r} בג'וב {job}")


def _node() -> str:
    node = shutil.which("node")
    if not node:
        # מקומית מותר לדלג. ב-CI היעדר node אומר שההחלטות של ההתראה לא נבדקות בכלל,
        # ודילוג שקט שם מסוכן יותר מכישלון רועש (כמו ב-tests/test_lang_icons.py).
        if os.environ.get("CI"):
            pytest.fail("node אינו זמין ב-CI, ולכן הסקריפטים של notify-post-merge-issue.yml לא נבדקו.")
        pytest.skip("node אינו זמין בסביבה המקומית")
    return node


def _run(
    tmp_path, script, *, step_env, workflow_run, open_issues=(), merge_bases=None, compare_errors=None, update_errors=None
):
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS, encoding="utf-8")
    payload = tmp_path / "input.json"
    payload.write_text(
        json.dumps(
            {
                "script": script,
                "workflowRun": workflow_run,
                "openIssues": list(open_issues),
                "mergeBases": merge_bases or {},
                # basehead -> {"status", "message"}: ההשוואה הזו נכשלת בשגיאת HTTP.
                "compareErrors": compare_errors or {},
                # מספר אישו (כמחרוזת) -> {"status", "message"}: הסגירה שלו נכשלת בשגיאת HTTP.
                "updateErrors": {str(k): v for k, v in (update_errors or {}).items()},
            }
        ),
        encoding="utf-8",
    )
    env = {**os.environ, **{k: str(v) for k, v in _workflow()["env"].items()}, **step_env}
    result = subprocess.run(
        [_node(), str(harness), str(payload)], capture_output=True, text=True, timeout=60, env=env, cwd=tmp_path
    )
    assert result.returncode == 0, f"node נכשל:\n{result.stderr}"
    return json.loads(result.stdout)


def _calls(outcome, name):
    return [args for call, args in outcome["calls"] if call == name]


def _workflow_run(sha):
    return {"name": WORKFLOW_NAME, "head_sha": sha, "head_branch": "main", "html_url": "https://example.invalid/run"}


def _issue(sha, body, number=7, created_at="2026-11-09T00:00:00Z"):
    return {
        "number": number,
        "title": f"Post-merge failure: {WORKFLOW_NAME} on main @ {sha[:7]}",
        "created_at": created_at,
        "body": body,
    }


def _marker(sha):
    return f"<!-- {_workflow()['env']['POST_MERGE_SHA_MARKER']}: {sha} -->"


def _open(tmp_path, sha, open_issues=()):
    return _run(
        tmp_path,
        _script("open-issue-on-failure", "Create/Update"),
        step_env={
            "HAS_FAILURES": "1",
            # שם ג'וב לדוגמה. לא שם של סטטוס אמיתי, כדי שלא ייראה כמו עותק של רשימת הבדיקות החובה
            # (tests/test_required_checks_are_listed.py מחפש עותקים כאלה בכל הריפו).
            "FAILED_JOBS_TEXT": "- example-job: https://example.invalid/job",
            "TESTS_FAILED_TOTAL": "0",
        },
        workflow_run=_workflow_run(sha),
        open_issues=open_issues,
    )


def _close(tmp_path, success_sha, issues, merge_bases=None, compare_errors=None, update_errors=None):
    return _run(
        tmp_path,
        _script("close-issue-on-success", "Close matching"),
        step_env={"HAS_FAILURES": "0"},
        workflow_run=_workflow_run(success_sha),
        open_issues=issues,
        merge_bases=merge_bases,
        compare_errors=compare_errors,
        update_errors=update_errors,
    )


def _closed(outcome):
    return any(args.get("state") == "closed" for args in _calls(outcome, "update"))


def _closed_numbers(outcome):
    return sorted(args["issue_number"] for args in _calls(outcome, "update") if args.get("state") == "closed")


def _commented_numbers(outcome):
    return sorted(args["issue_number"] for args in _calls(outcome, "createComment"))


def _logs(outcome, level):
    return [message for lvl, message in outcome["logs"] if lvl == level]


# ── הפתיחה: הקומיט שנכשל נשמר בגוף האישו ─────────────────────────────────────────


def test_a_new_issue_carries_the_full_failing_sha_in_its_body(tmp_path):
    outcome = _open(tmp_path, FAILED_SHA)
    assert outcome["ok"], outcome
    [created] = _calls(outcome, "create")
    assert _marker(FAILED_SHA) in created["body"]


def test_an_existing_issue_without_the_marker_gets_it_in_its_body(tmp_path):
    """אישו קיים עם אותה כותרת מקבל תגובה, והסגירה לא קוראת תגובות. לכן הסימון נכנס לגוף."""
    outcome = _open(tmp_path, FAILED_SHA, open_issues=[_issue(FAILED_SHA, "opened before the marker existed")])
    assert outcome["ok"], outcome
    assert len(_calls(outcome, "createComment")) == 1
    [update] = _calls(outcome, "update")
    assert update["issue_number"] == 7
    assert update["body"].startswith("opened before the marker existed")
    assert _marker(FAILED_SHA) in update["body"]


def test_an_existing_issue_that_has_the_marker_is_not_rewritten(tmp_path):
    outcome = _open(tmp_path, FAILED_SHA, open_issues=[_issue(FAILED_SHA, "body\n\n" + _marker(FAILED_SHA))])
    assert outcome["ok"], outcome
    assert _calls(outcome, "update") == []


# ── הסגירה: רק כשהקומיט שהצליח מכיל את הקומיט שנכשל ─────────────────────────────────


def test_closes_when_the_successful_commit_contains_the_failing_one(tmp_path):
    outcome = _close(
        tmp_path,
        SUCCESS_SHA,
        [_issue(FAILED_SHA, "x\n\n" + _marker(FAILED_SHA))],
        merge_bases={f"{FAILED_SHA}...{SUCCESS_SHA}": FAILED_SHA},
    )
    assert outcome["ok"], outcome
    assert _calls(outcome, "compare") == [{"owner": "o", "repo": "r", "basehead": f"{FAILED_SHA}...{SUCCESS_SHA}"}]
    assert _closed(outcome)


def test_closes_when_the_same_commit_passes_on_a_rerun(tmp_path):
    outcome = _close(
        tmp_path,
        FAILED_SHA,
        [_issue(FAILED_SHA, _marker(FAILED_SHA))],
        merge_bases={f"{FAILED_SHA}...{FAILED_SHA}": FAILED_SHA},
    )
    assert outcome["ok"], outcome
    assert _closed(outcome)


def test_a_late_success_of_an_older_commit_leaves_the_issue_open(tmp_path):
    """הקומיט הישן לא מכיל את הקומיט שנכשל: ה-merge base שלהם הוא הישן עצמו."""
    outcome = _close(
        tmp_path,
        OLDER_SHA,
        [_issue(FAILED_SHA, _marker(FAILED_SHA))],
        merge_bases={f"{FAILED_SHA}...{OLDER_SHA}": OLDER_SHA},
    )
    assert outcome["ok"], outcome
    assert _calls(outcome, "update") == []
    assert _calls(outcome, "createComment") == []


def test_an_issue_without_the_marker_is_left_open_without_comparing(tmp_path):
    outcome = _close(tmp_path, SUCCESS_SHA, [_issue(FAILED_SHA, "opened before the marker existed")])
    assert outcome["ok"], outcome
    assert _calls(outcome, "compare") == []
    assert _calls(outcome, "update") == []


def test_a_run_without_a_valid_head_sha_compares_and_closes_nothing(tmp_path):
    outcome = _close(tmp_path, "not-a-sha", [_issue(FAILED_SHA, _marker(FAILED_SHA))])
    assert outcome["ok"], outcome
    assert _calls(outcome, "compare") == []
    assert _calls(outcome, "update") == []


def test_a_404_comparison_leaves_the_issue_open_without_failing_the_step(tmp_path):
    """404 הוא המצב שהוצהר: GitHub לא מוצא את הקומיט שנכשל (למשל אחרי force push). אזהרה, והאישו נשאר פתוח."""
    outcome = _close(
        tmp_path,
        SUCCESS_SHA,
        [_issue(FAILED_SHA, _marker(FAILED_SHA))],
        compare_errors={f"{FAILED_SHA}...{SUCCESS_SHA}": {"status": 404, "message": "Not Found"}},
    )
    assert outcome["ok"], outcome
    assert _calls(outcome, "update") == []
    assert _calls(outcome, "createComment") == []
    [warning] = _logs(outcome, "warning")
    assert "#7" in warning and "404" in warning


# ── כמה אישיוז פתוחים: כל אחד נבדק לבד ───────────────────────────────────────────
# שני כשלים ברצף על main פותחים שני אישיוז, אחד לכל קומיט. ‏listForRepo מחזיר אותם מהחדש לישן,
# ולכן ברשימות שבטסטים החדש ראשון: כך הוא היה candidates[0] בקוד שבדק רק את הראשון.

NEXT_FAILED_SHA = "4" * 40  # כשל שני, בקומיט שאחרי FAILED_SHA


def _older_and_newer(newer_sha=NEXT_FAILED_SHA, newer_body=None):
    older = _issue(FAILED_SHA, _marker(FAILED_SHA), number=3740, created_at="2026-11-27T02:36:59Z")
    newer = _issue(
        newer_sha,
        _marker(newer_sha) if newer_body is None else newer_body,
        number=3741,
        created_at="2026-11-27T03:46:33Z",
    )
    return [newer, older]


def test_closes_every_issue_whose_failing_commit_the_successful_commit_contains(tmp_path):
    """המקרה של #3740 ו-#3741: שני קומיטים רצופים שנכשלו, ותיקון אחרי שניהם. שני האישיוז נסגרים."""
    outcome = _close(
        tmp_path,
        SUCCESS_SHA,
        _older_and_newer(),
        merge_bases={
            f"{FAILED_SHA}...{SUCCESS_SHA}": FAILED_SHA,
            f"{NEXT_FAILED_SHA}...{SUCCESS_SHA}": NEXT_FAILED_SHA,
        },
    )
    assert outcome["ok"], outcome
    assert _closed_numbers(outcome) == [3740, 3741]
    assert _commented_numbers(outcome) == [3740, 3741]
    by_issue = {args["issue_number"]: args["body"] for args in _calls(outcome, "createComment")}
    assert FAILED_SHA[:7] in by_issue[3740] and NEXT_FAILED_SHA[:7] in by_issue[3741]
    assert all(SUCCESS_SHA[:7] in body and "https://example.invalid/run" in body for body in by_issue.values())


def test_an_issue_the_success_does_not_contain_stays_open_and_the_older_one_is_still_closed(tmp_path):
    """FAILED_SHA ← SUCCESS_SHA (התיקון) ← NEXT_FAILED_SHA (שבר חדש). ההצלחה מכילה רק את הראשון."""
    outcome = _close(
        tmp_path,
        SUCCESS_SHA,
        _older_and_newer(),
        merge_bases={
            f"{FAILED_SHA}...{SUCCESS_SHA}": FAILED_SHA,
            f"{NEXT_FAILED_SHA}...{SUCCESS_SHA}": SUCCESS_SHA,
        },
    )
    assert outcome["ok"], outcome
    assert _closed_numbers(outcome) == [3740]
    assert _commented_numbers(outcome) == [3740]


def test_an_issue_without_the_marker_does_not_stop_the_others(tmp_path):
    outcome = _close(
        tmp_path,
        SUCCESS_SHA,
        _older_and_newer(newer_body="opened before the marker existed"),
        merge_bases={f"{FAILED_SHA}...{SUCCESS_SHA}": FAILED_SHA},
    )
    assert outcome["ok"], outcome
    assert [c["basehead"] for c in _calls(outcome, "compare")] == [f"{FAILED_SHA}...{SUCCESS_SHA}"]
    assert _closed_numbers(outcome) == [3740]


def test_a_missing_commit_404_leaves_its_issue_open_and_the_others_are_closed(tmp_path):
    outcome = _close(
        tmp_path,
        SUCCESS_SHA,
        _older_and_newer(),
        merge_bases={f"{FAILED_SHA}...{SUCCESS_SHA}": FAILED_SHA},
        compare_errors={f"{NEXT_FAILED_SHA}...{SUCCESS_SHA}": {"status": 404, "message": "Not Found"}},
    )
    assert outcome["ok"], outcome
    assert _closed_numbers(outcome) == [3740]
    [warning] = _logs(outcome, "warning")
    assert "#3741" in warning


@pytest.mark.parametrize(
    "failure",
    [
        {"status": 500, "message": "Server Error"},
        {"status": 403, "message": "API rate limit exceeded"},
        # שגיאת רשת: לא תשובה מ-GitHub, ולכן בלי status
        {"status": None, "message": "socket hang up"},
    ],
    ids=["server-error", "rate-limit", "network"],
)
def test_an_unexpected_comparison_error_fails_the_step_after_the_others_are_closed(tmp_path, failure):
    """רק 404 הוא המצב שהוצהר. כל שגיאה אחרת מכשילה את הצעד, אבל רק אחרי ששאר האישיוז נבדקו ונסגרו."""
    outcome = _close(
        tmp_path,
        SUCCESS_SHA,
        _older_and_newer(),
        merge_bases={f"{FAILED_SHA}...{SUCCESS_SHA}": FAILED_SHA},
        compare_errors={f"{NEXT_FAILED_SHA}...{SUCCESS_SHA}": failure},
    )
    assert not outcome["ok"], outcome
    assert "#3741" in outcome["error"] and failure["message"] in outcome["error"]
    assert _closed_numbers(outcome) == [3740]
    assert _logs(outcome, "warning") == []
    [error] = _logs(outcome, "error")
    assert "#3741" in error


def test_a_failure_while_closing_one_issue_does_not_stop_the_others(tmp_path):
    outcome = _close(
        tmp_path,
        SUCCESS_SHA,
        _older_and_newer(),
        merge_bases={
            f"{FAILED_SHA}...{SUCCESS_SHA}": FAILED_SHA,
            f"{NEXT_FAILED_SHA}...{SUCCESS_SHA}": NEXT_FAILED_SHA,
        },
        update_errors={3741: {"status": 502, "message": "Bad Gateway"}},
    )
    assert not outcome["ok"], outcome
    assert "#3741" in outcome["error"]
    assert _closed_numbers(outcome) == [3740]


def test_the_marker_written_by_the_open_step_is_the_one_the_close_step_reads(tmp_path):
    """הפתיחה כותבת את הסימון והסגירה קוראת אותו, בשני סקריפטים נפרדים. הטסט מחבר ביניהם."""
    opened = _open(tmp_path, FAILED_SHA)
    [created] = _calls(opened, "create")
    outcome = _close(
        tmp_path,
        SUCCESS_SHA,
        [_issue(FAILED_SHA, created["body"])],
        merge_bases={f"{FAILED_SHA}...{SUCCESS_SHA}": FAILED_SHA},
    )
    assert outcome["ok"], outcome
    assert _closed(outcome)
