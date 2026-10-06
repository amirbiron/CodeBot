"""כל ג'וב תחת ``.github/workflows`` רץ על אותה תווית runner, והתווית נוקבת בגרסה.

שני כללים נאכפים:

1. **כל תווית היא תווית אובונטו שנוקבת בגרסה** (``PINNED_LABEL``). ``ubuntu-latest`` אינו
   גרסה אלא מצביע ש-GitHub מזיזים בלוח הזמנים שלהם, והמעבר שלו הדרגתי — במשך כמה שבועות חלק
   מהג'ובים רצים על הגרסה הישנה וחלק על החדשה.
2. **כל הג'ובים, בכל הקבצים, רצים על אותה תווית.** כך שדרוג הוא החלפה אחת, ולא מצב ביניים
   שבו ה-CI של PR בודק גרסה אחת והפריסה רצה על אחרת.

**הכלל הראשון בודק את הצורה שחייבת להתקיים, ולא רשימה של צורות אסורות** — רשימה כזו לעולם
אינה שלמה. בגרסה הראשונה שלו הוא בדק רק שהתווית אינה מסתיימת ב-``-latest``, ולכן עברו אותו
שלוש תוויות שזזות לבד באותה מידה: ``Ubuntu-LATEST`` (GitHub משווים תוויות בלי הבדל בין
אותיות גדולות לקטנות — ראו ``PINNED_LABEL``), ``ubuntu-slim`` (תווית רשמית של GitHub בלי
גרסה, בטבלת התמונות ב-README של ``actions/runner-images``), ו-``self-hosted``.

הנימוק המלא, ואיך משדרגים: ``docs/ci-cd.rst``, הסעיף "תווית ה-runner".

הסריקה מבינה רק ``runs-on`` שהוא מחרוזת פשוטה, כי זה כל מה שיש היום בריפו. ``runs-on``
יכול להיות גם משתנה, מערך, או מיפוי של ``group``/``labels`` (תיעוד GitHub, "Choosing the
runner for a job"), וצורה כזו **נכשלת** כאן בהודעה שאומרת מה לעשות — דילוג היה משאיר את
שני הכללים ירוקים בלי שהג'וב נבדק. ג'וב שקורא ל-workflow לשימוש חוזר (``uses:``) אינו
מגדיר ``runs-on`` בעצמו, ולכן אינו נבדק כאן; workflow מקומי כזה הוא קובץ באותה תיקייה,
והג'ובים שלו נסרקים שם.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

#: תווית שנוקבת בגרסת אובונטו, כמו בעמודת "YAML Label" ב-README של ``actions/runner-images``.
#: נבדקת ב-``fullmatch`` ובאותיות קטנות בלבד. GitHub משווים תוויות בלי הבדל בין אותיות גדולות
#: לקטנות (תיעוד GitHub, "Using labels with self-hosted runners": "Labels are
#: case-insensitive"; ‏actionlint 1.7.12 מקטין את התווית ב-``strings.ToLower`` לפני שהוא מחפש
#: אותה ברשימת התוויות של GitHub), כך ש-``Ubuntu-LATEST`` הוא ``ubuntu-latest``. כתיב אחד
#: לכל תווית גם שומר על הכלל השני מדויק, כי הוא משווה מחרוזות בין ג'ובים.
#: מעבר מכוון לתווית מסוג אחר (``self-hosted``, ‏``-arm``) הוא שינוי מדיניות: משנים כאן, וגם
#: את ``docs/ci-cd.rst``.
PINNED_LABEL = re.compile(r"ubuntu-\d{2}\.\d{2}")


def _runner_labels(workflows: Path) -> dict[str, str]:
    """ה-``runs-on`` של כל ג'וב, לפי ``<קובץ>:<ג'וב>``.

    GitHub קוראים workflow גם מ-``.yml`` וגם מ-``.yaml`` (תיעוד GitHub, "Workflow syntax for
    GitHub Actions"), ולכן שתי הסיומות נסרקות.
    """
    files = sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")])
    assert files, f"לא נמצאו קבצי workflow ב-{workflows}"
    labels = {}
    for path in files:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        jobs = workflow.get("jobs") if isinstance(workflow, dict) else None
        assert isinstance(jobs, dict) and jobs, f"{path.name}: אין בקובץ מיפוי jobs עם ג'ובים"
        for job_id, job in jobs.items():
            where = f"{path.name}:{job_id}"
            assert isinstance(job, dict), f"{where}: הג'וב אינו מיפוי"
            if "uses" in job:
                continue
            runs_on = job.get("runs-on")
            assert isinstance(runs_on, str) and "${{" not in runs_on, (
                f"{where}: runs-on הוא {runs_on!r}, והבדיקה הזו מבינה רק תווית אחת כתובה כמחרוזת. "
                "אם הצורה הזו נחוצה, הרחיבו את _runner_labels כך שתחלץ ממנה את התוויות — "
                "אל תדלגו על הג'וב, כי אז אף כלל לא היה נבדק עליו."
            )
            labels[where] = runs_on
    return labels


def _unpinned(labels: dict[str, str]) -> dict[str, str]:
    """הג'ובים שהתווית שלהם אינה בצורה של ``PINNED_LABEL``."""
    return {where: label for where, label in labels.items() if not PINNED_LABEL.fullmatch(label)}


def test_every_job_runs_on_a_label_that_names_an_ubuntu_version():
    """כל ג'וב רץ על תווית אובונטו עם גרסה (``PINNED_LABEL``), ולא על תווית שזזה לבד."""
    unpinned = _unpinned(_runner_labels(WORKFLOWS))
    assert not unpinned, (
        "ג'ובים שהתווית שלהם אינה נוקבת בגרסת אובונטו, ולכן יכולה לזוז בלי שאף שורה בריפו "
        "תשתנה. כתבו את התווית שכל שאר הג'ובים רצים עליה, באותיות קטנות (ראו docs/ci-cd.rst, "
        "'תווית ה-runner'; ואם תווית מסוג אחר מכוונת — PINNED_LABEL):\n"
        + "\n".join(f"{where}: {label}" for where, label in sorted(unpinned.items()))
    )


@pytest.mark.parametrize(
    "label, pinned",
    [
        ("ubuntu-24.04", True),
        ("ubuntu-26.04", True),
        ("ubuntu-latest", False),
        # אותה תווית כמו ubuntu-latest, כי GitHub משווים בלי הבדל בין אותיות גדולות לקטנות.
        ("Ubuntu-LATEST", False),
        # תווית רשמית של GitHub בלי גרסה, וגם בלי -latest.
        ("ubuntu-slim", False),
        # runner של הבעלים: אין בתווית גרסה, ומה שמותקן עליו נקבע מחוץ לריפו.
        ("self-hosted", False),
        # גרסה נכונה בכתיב אחר: GitHub היו מקבלים אותה, אבל הכלל השני משווה מחרוזות.
        ("UBUNTU-24.04", False),
        # שגיאת הקלדה, ולא תווית שקיימת.
        ("ubuntu-24.4", False),
    ],
)
def test_the_version_rule_accepts_only_a_lowercase_ubuntu_label_with_a_version(label, pinned):
    """הכלל הראשון מקבל רק את הכתיב של ``PINNED_LABEL``.

    .. note::

       **הטסט הזה אינו נופל על ה-workflows של היום, וזה מכוון.** הוא שומר על ``_unpinned``:
       בגרסה הראשונה, שבדקה רק סיומת ``-latest``, ``Ubuntu-LATEST``, ‏``ubuntu-slim``,
       ‏``self-hosted``, ‏``UBUNTU-24.04`` ו-``ubuntu-24.4`` עברו כולן, והטסט על ה-workflows
       היה נשאר ירוק עליהן.
    """
    assert (_unpinned({"w.yml:job": label}) == {}) is pinned


def test_every_job_runs_on_the_same_label():
    """כל הג'ובים רצים על תווית אחת, כך ששדרוג הוא החלפה אחת בכל הקבצים."""
    labels = _runner_labels(WORKFLOWS)
    by_label: dict[str, list[str]] = {}
    for where, label in labels.items():
        by_label.setdefault(label, []).append(where)
    assert len(by_label) == 1, (
        "הג'ובים רצים על תוויות שונות — כנראה שדרוג שנעצר באמצע. החליפו את התווית בכל הקבצים "
        "באותו PR (ראו docs/ci-cd.rst, 'תווית ה-runner'):\n"
        + "\n".join(
            f"{label}: {', '.join(sorted(jobs))}" for label, jobs in sorted(by_label.items())
        )
    )


def test_the_scan_reports_every_job_and_refuses_shapes_it_cannot_read(tmp_path):
    """הסריקה מחזירה כל ג'וב שמגדיר ``runs-on``, ונכשלת על צורה שאינה מחרוזת פשוטה.

    .. note::

       **הטסט הזה אינו נופל על ה-workflows שלפני הנעיצה, וזה מכוון.** הוא שומר על
       ``_runner_labels``: סריקה שמחזירה פחות ג'ובים ממה שיש, או שמדלגת על צורה שאינה
       מבינה, הייתה משאירה את שני הטסטים שלמעלה ירוקים על כל workflow שהוא.
    """
    (tmp_path / "a.yml").write_text(
        "on: push\n"
        "jobs:\n"
        "  pinned:\n"
        "    runs-on: ubuntu-24.04\n"
        "    steps: [{run: 'true'}]\n"
        "  moving:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps: [{run: 'true'}]\n"
        "  reusable:\n"
        "    uses: ./.github/workflows/b.yaml\n",
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(
        "on: workflow_call\n"
        "jobs:\n"
        "  called:\n"
        "    runs-on: ubuntu-26.04\n"
        "    steps: [{run: 'true'}]\n",
        encoding="utf-8",
    )
    assert _runner_labels(tmp_path) == {
        "a.yml:pinned": "ubuntu-24.04",
        "a.yml:moving": "ubuntu-latest",
        "b.yaml:called": "ubuntu-26.04",
    }

    for shape in (
        "[self-hosted, linux]",
        "{group: ubuntu-runners}",
        '"${{ vars.RUNNER }}"',
        "",
    ):
        (tmp_path / "c.yml").write_text(
            f"on: push\njobs:\n  odd:\n    runs-on: {shape}\n    steps: [{{run: 'true'}}]\n",
            encoding="utf-8",
        )
        with pytest.raises(AssertionError, match="c.yml:odd: runs-on"):
            _runner_labels(tmp_path)
