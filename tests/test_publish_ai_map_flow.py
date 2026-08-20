"""בדיקת קבלה לזרימת פרסום AI-MAP.md — מקצה לקצה, על הפקודות האמיתיות.

הבאג שהוליד את הקובץ הזה: שלב "Regenerate" ב-workflow כתב את המפה
הטרייה ל-workspace, ואז סקריפט הפרסום ייצר אותה שוב ל-temp והשווה מול
אותו קובץ — שני הצדדים מאותו מקור, ההשוואה תמיד זהה, וכל ה-workflow
היה no-op שמדווח "המפה עדכנית" לנצח. ירוק שקרי מושלם: אף בדיקה קיימת
לא הריצה את הזרימה כולה.

לכן הבדיקות כאן לא בודקות את הסקריפט בבידוד אלא את **מה שה-workflow
באמת מריץ**: פקודות ה-run נשלפות מה-yaml עצמו ורצות בסדרן, בארגז חול
זמני (עותק של docs/, המחולל, הסקריפט וה-AI-MAP.md המקומט, עם git init)
ועם gh מזויף שרושם כל קריאה. שינוי עתידי ב-workflow נבדק אוטומטית.

האימות הוא קריאה חוזרת של המצב, לא ערך החזרה: "הצליח" נמדד בשאלה האם
קריאת PUT ל-Contents API אכן נשלחה עם התוכן והנעילה הנכונים.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ai-map.yml"

FAKE_GH = r'''#!/usr/bin/env bash
# gh מזויף: רושם כל קריאה לשורה אחת ב-GH_LOG ומדמה את Contents API.
printf '%s\n' "$*" >> "${GH_LOG}"
mode="${FAKE_GH_MODE:-ok}"
if [[ "$*" == *"-X PUT"* ]]; then
  if [[ "${mode}" == "put_fail" ]]; then
    echo "gh: Validation Failed (HTTP 422)" >&2
    exit 1
  fi
  echo "fakecommitsha"
  exit 0
fi
# כל קריאה אחרת (למשל GET שהעיצוב החדש אסר) — נכשלת ברעש כדי שתתגלה
echo "gh: unexpected call in test: $*" >&2
exit 1
'''


@pytest.fixture
def sandbox(tmp_path):
    """עותק מבודד של כל מה שהזרימה נוגעת בו, כריפו git עם קומיט אחד."""
    for rel in ("docs", "scripts", ".github"):
        src = ROOT / rel
        shutil.copytree(
            src, tmp_path / rel,
            ignore=shutil.ignore_patterns("_build", "__pycache__"),
        )
    shutil.copy(ROOT / "AI-MAP.md", tmp_path / "AI-MAP.md")

    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)

    def _git(*args):
        subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
        )

    _git("init", "-q")
    _git("add", "-A")
    _git("commit", "-qm", "מצב מקומט")
    return tmp_path


def _workflow_run_commands():
    """שולף את פקודות ה-run מה-yaml — הבדיקה רצה על מה שה-CI באמת מריץ."""
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["refresh-map"]["steps"]
    return [(s.get("name", "?"), s["run"]) for s in steps if "run" in s]


def _run_flow(sandbox, mode="ok"):
    log = sandbox / "gh_calls.log"
    log.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{sandbox / 'fake-bin'}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "fake-token",
        "GITHUB_REPOSITORY": "amirbiron/CodeBot",
        "GH_LOG": str(log),
        "FAKE_GH_MODE": mode,
    }
    results = []
    for name, cmd in _workflow_run_commands():
        proc = subprocess.run(
            ["bash", "-c", cmd], cwd=sandbox, env=env,
            capture_output=True, text=True, timeout=300,
        )
        results.append((name, proc))
    calls = log.read_text(encoding="utf-8").splitlines()
    return results, calls


def _touch_docs(sandbox):
    """שינוי תוכן אמיתי: עריכת הפסקה הראשונה של עמוד קיים משנה את המפה."""
    page = sandbox / "docs" / "architecture.rst"
    text = page.read_text(encoding="utf-8")
    page.write_text(
        text.replace(
            "המערכת מורכבת", "המערכת (עודכן בבדיקת קבלה) מורכבת", 1
        ),
        encoding="utf-8",
    )


def _committed_map_blob(sandbox):
    out = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD:AI-MAP.md"],
        cwd=sandbox, check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def test_docs_change_actually_publishes(sandbox):
    """בדיקת הקבלה: שינוי בתיעוד חייב להסתיים בקריאת PUT אמיתית.

    זו הבדיקה שנופלת על הקוד שלפני התיקון — שם שלב ה-Regenerate רומס
    את בסיס ההשוואה והזרימה מדווחת "עדכני" בלי לפרסם דבר.
    """
    _touch_docs(sandbox)
    results, calls = _run_flow(sandbox)

    for name, proc in results:
        assert proc.returncode == 0, f"שלב '{name}' נכשל:\n{proc.stderr}"
    puts = [c for c in calls if "-X PUT" in c]
    assert puts, (
        "שום PUT לא נשלח אחרי שינוי תיעוד — הזרימה דיווחה הצלחה בלי "
        f"לפרסם. קריאות gh שנרשמו: {calls or 'אין'}"
    )
    assert len(calls) == len(puts), (
        f"נרשמו קריאות gh שאינן PUT — העיצוב אוסר GET: {calls}"
    )


def test_publish_carries_the_committed_blob_as_optimistic_lock(sandbox):
    """ה-PUT נושא את ה-sha של הקובץ כפי שהוא בקומיט של ה-checkout.

    זו הנעילה האופטימית: אם מישהו עדכן את הקובץ ב-main אחרי הקומיט
    שעליו רצים, ה-API יחזיר קונפליקט במקום לדרוס. ה-sha חייב להגיע
    מ-git המקומי — לא מ-GET, שכשל רשת שלו התחזה בעבר ל"קובץ לא קיים".
    """
    _touch_docs(sandbox)
    expected = _committed_map_blob(sandbox)
    _, calls = _run_flow(sandbox)
    puts = [c for c in calls if "-X PUT" in c]
    assert puts and f"sha={expected}" in puts[0], (
        f"ה-PUT לא נושא את ה-blob של הקומיט ({expected[:12]}…): "
        f"{puts[0][:200] if puts else 'אין PUT'}"
    )


def test_no_docs_change_publishes_nothing(sandbox):
    """בלי שינוי — אף קריאת רשת, יציאה נקייה. המפה המקומטת היא הבסיס."""
    results, calls = _run_flow(sandbox)
    for name, proc in results:
        assert proc.returncode == 0, f"שלב '{name}' נכשל:\n{proc.stderr}"
    assert not calls, f"נשלחו קריאות gh בלי שום שינוי בתיעוד: {calls}"


def test_put_failure_fails_the_run_loudly(sandbox):
    """כשל פרסום אמיתי (422/500) מפיל את הריצה — לא ירוק שקרי."""
    _touch_docs(sandbox)
    results, _ = _run_flow(sandbox, mode="put_fail")
    last_name, last = results[-1]
    assert last.returncode != 0, (
        f"שלב '{last_name}' דיווח הצלחה למרות שה-PUT נכשל"
    )


def test_first_publish_sends_put_without_sha(sandbox):
    """כשהמפה עוד לא קיימת בקומיט — PUT יצירה, בלי sha.

    מקור (docs.github.com, Contents API): "sha — Required if you are
    updating a file" — כלומר ביצירה הוא מושמט.
    """
    (sandbox / "AI-MAP.md").unlink()
    subprocess.run(["git", "rm", "-q", "--cached", "AI-MAP.md"], cwd=sandbox,
                   check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "בלי מפה"], cwd=sandbox,
                   check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t",
                        "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})
    results, calls = _run_flow(sandbox)
    for name, proc in results:
        assert proc.returncode == 0, f"שלב '{name}' נכשל:\n{proc.stderr}"
    puts = [c for c in calls if "-X PUT" in c]
    assert puts, "יצירה ראשונה חייבת לשלוח PUT"
    assert "sha=" not in puts[0], f"PUT יצירה נושא sha שלא קיים: {puts[0][:200]}"
