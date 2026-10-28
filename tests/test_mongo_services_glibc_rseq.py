"""כל שירות שמרים את התמונה ``mongo`` משאיר את rseq אצל glibc (``glibc.pthread.rseq=1``).

התמונה הרשמית של מונגו מגדירה ``GLIBC_TUNABLES`` עם ``glibc.pthread.rseq=0``, ו-mongod של 8.0
עוצרת אז את העלייה על קרנל שנראה לה לא תואם — והג'וב נכשל עוד לפני הצעד הראשון שלו, בלי שאף
שורה בריפו השתנתה. ההגדרה בשירות מבטלת את זה. ההסבר המלא, הגרסאות והמקורות: ``docs/testing.rst``,
הסעיף "``GLIBC_TUNABLES`` בשירותי המונגו".

**מה נסרק:** ``services`` של כל ג'וב תחת ``.github/workflows``, ו-``services`` של כל קובץ compose
בשורש הריפו (``COMPOSE_PATTERNS``). שירות נחשב למונגו לפי ``_is_mongo_image``: הקטע האחרון בשם
התמונה, בלי התג ובלי ה-digest, הוא ``mongo``. כך ``mongo:8.0`` ו-``docker.io/library/mongo:8.0``
נבדקים, ו-``mongo-express`` לא. ``image`` שהוא ביטוי ``${{ … }}`` נבדק לפי המחרוזות שבגרשיים
בתוכו, כי כך ``ci.yml`` בוחר אם להרים את השירות במסלול.

**מה אינו נסרק:** ``docker run`` בתוך צעד, ``container:`` של ג'וב, וקובץ compose מחוץ לשורש. אין
היום אף אחד מהם עם מונגו. צורה של ``env``/``environment`` שהסריקה אינה מבינה **נכשלת** בהודעה,
ולא מדלגת — דילוג היה משאיר את הטסט ירוק בלי שהשירות נבדק (כמו ב-``_runner_labels`` שב-
``tests/test_workflow_runner_labels.py``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

#: שמות הקבצים ש-Docker Compose מחפש בתיקייה (תיעוד Docker, ``compose/intro/compose-application-model``:
#: ``compose.yaml`` או ``compose.yml``, ולתאימות לאחור ``docker-compose.yaml`` ו-``docker-compose.yml``).
#: הכוכבית תופסת גם קובץ שמריצים ב-``-f``, כמו ``docker-compose.dev.yml``.
COMPOSE_PATTERNS = ("compose.yml", "compose.yaml", "docker-compose*.yml", "docker-compose*.yaml")

#: מחרוזת בתוך ביטוי של GitHub Actions נכתבת בגרשיים בודדים (תיעוד GitHub, "Evaluate expressions
#: in workflows and actions", "Literals").
_EXPRESSION_STRING = re.compile(r"'([^']*)'")


def _image_candidates(image: str) -> list[str]:
    """התמונות ש-``image`` יכול להרים: המחרוזת עצמה, או המחרוזות שבגרשיים בתוך ביטוי."""
    if "${{" in image:
        return _EXPRESSION_STRING.findall(image)
    return [image]


def _is_mongo_image(image: str) -> bool:
    """האם אחת התמונות ש-``image`` מרים היא ``mongo``, בכל registry ובכל תג."""
    for candidate in _image_candidates(image):
        name = candidate.split("@", 1)[0]
        last = name.rsplit("/", 1)[-1]
        if last.split(":", 1)[0] == "mongo":
            return True
    return False


def _as_env(raw, where: str) -> dict[str, str | None]:
    """``env`` של שירות ב-workflow, או ``environment`` של שירות ב-compose, כמיפוי.

    ב-compose ``environment`` הוא מיפוי או רשימה של ``KEY=VALUE`` (Compose Specification,
    "environment"); ``KEY`` בלי ערך לוקח את הערך מהסביבה של מי שמריץ, ולכן נשמר כאן כ-``None``.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(key): None if value is None else str(value) for key, value in raw.items()}
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        env: dict[str, str | None] = {}
        for item in raw:
            key, sep, value = item.partition("=")
            env[key] = value if sep else None
        return env
    raise AssertionError(
        f"{where}: הסביבה של השירות היא {raw!r}, והבדיקה הזו מבינה רק מיפוי או רשימת KEY=VALUE. "
        "הרחיבו את _as_env — אל תדלגו על השירות, כי אז ההגדרה לא הייתה נבדקת עליו."
    )


def _rseq_tunable(env: dict[str, str | None]) -> str | None:
    """הערך של ``glibc.pthread.rseq`` ב-``GLIBC_TUNABLES``, או ``None`` כשאינו שם.

    ``GLIBC_TUNABLES`` הוא רשימה של ``name=value`` שמופרדים בנקודתיים (GNU C Library manual,
    "Tunables"), ולכן ההגדרה יכולה לשבת שם לצד tunables אחרים.
    """
    tunables = env.get("GLIBC_TUNABLES")
    if not tunables:
        return None
    for pair in tunables.split(":"):
        name, sep, value = pair.partition("=")
        if sep and name == "glibc.pthread.rseq":
            return value
    return None


def _mongo_services(workflows: Path, compose_files: list[Path]) -> dict[str, dict[str, str | None]]:
    """הסביבה של כל שירות מונגו: ``<קובץ>:<ג'וב>:<שירות>`` ב-workflow, ``<קובץ>:<שירות>`` ב-compose."""
    found: dict[str, dict[str, str | None]] = {}
    for path in sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")]):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        jobs = workflow.get("jobs") if isinstance(workflow, dict) else None
        assert isinstance(jobs, dict), f"{path.name}: אין בקובץ מיפוי jobs"
        for job_id, job in jobs.items():
            assert isinstance(job, dict), f"{path.name}:{job_id}: הג'וב אינו מיפוי"
            services = job.get("services")
            if services is None:
                continue
            assert isinstance(services, dict), f"{path.name}:{job_id}: services אינו מיפוי"
            for name, service in services.items():
                where = f"{path.name}:{job_id}:{name}"
                assert isinstance(service, dict), f"{where}: השירות אינו מיפוי"
                if _is_mongo_image(str(service.get("image", ""))):
                    found[where] = _as_env(service.get("env"), where)
    for path in compose_files:
        compose = yaml.safe_load(path.read_text(encoding="utf-8"))
        services = compose.get("services") if isinstance(compose, dict) else None
        assert isinstance(services, dict), f"{path.name}: אין בקובץ מיפוי services"
        for name, service in services.items():
            where = f"{path.name}:{name}"
            assert isinstance(service, dict), f"{where}: השירות אינו מיפוי"
            if _is_mongo_image(str(service.get("image", ""))):
                found[where] = _as_env(service.get("environment"), where)
    return found


def _compose_files(root: Path) -> list[Path]:
    return sorted({path for pattern in COMPOSE_PATTERNS for path in root.glob(pattern)})


def test_every_mongo_service_lets_glibc_keep_rseq():
    """כל שירות ``mongo`` ב-workflows וב-compose מגדיר ``glibc.pthread.rseq=1``."""
    services = _mongo_services(WORKFLOWS, _compose_files(ROOT))
    assert services, (
        "הסריקה לא מצאה אף שירות mongo — כנראה ש-_mongo_services או _is_mongo_image נשברו, כי "
        "היום יש כאלה ב-workflows וב-compose. אם הם באמת הוסרו, הסירו גם את הטסט הזה."
    )
    missing = {where: env for where, env in services.items() if _rseq_tunable(env) != "1"}
    assert not missing, (
        "שירותי mongo בלי GLIBC_TUNABLES=glibc.pthread.rseq=1. בלעדיה mongod של 8.0 מסרבת לעלות "
        "על חלק מהקרנלים (SERVER-121912) — ראו docs/testing.rst, הסעיף "
        "'GLIBC_TUNABLES בשירותי המונגו':\n"
        + "\n".join(f"{where}: GLIBC_TUNABLES={env.get('GLIBC_TUNABLES')!r}" for where, env in sorted(missing.items()))
    )


@pytest.mark.parametrize(
    "image, is_mongo",
    [
        ("mongo:8.0", True),
        ("mongo", True),
        ("docker.io/library/mongo:8.0", True),
        ("mongo@sha256:b9924c330a8bbc5800fe9c69f04a84e221eca7b28fd049a0354147d9908fa142", True),
        # כך ci.yml מרים את השירות רק במסלול main.
        ("${{ matrix.suite == 'main' && 'mongo:8.0' || '' }}", True),
        ("${{ matrix.suite == 'main' && 'redis:7-alpine' || '' }}", False),
        ("mongo-express:latest", False),
        ("redis:7-alpine", False),
        ("", False),
    ],
)
def test_the_image_rule_matches_mongo_in_every_spelling(image, is_mongo):
    """``_is_mongo_image`` מזהה את ``mongo`` בכל צורת כתיבה, ורק אותו.

    .. note::

       **הטסט הזה אינו נופל על הקבצים שלפני ההגדרה, וזה מכוון.** הוא שומר על הזיהוי: זיהוי
       שמפספס את הביטוי של ``ci.yml`` היה משאיר את הטסט על הריפו ירוק בלי לבדוק את ``ci.yml``.
    """
    assert _is_mongo_image(image) is is_mongo


@pytest.mark.parametrize(
    "tunables, value",
    [
        ("glibc.pthread.rseq=1", "1"),
        # מה שהתמונה הרשמית מגדירה ב-ENV.
        ("glibc.pthread.rseq=0", "0"),
        ("glibc.malloc.check=3:glibc.pthread.rseq=1", "1"),
        ("glibc.malloc.check=3", None),
        ("", None),
        (None, None),
    ],
)
def test_the_rseq_rule_reads_the_tunable_among_others(tunables, value):
    """``_rseq_tunable`` מוצא את ``glibc.pthread.rseq`` גם כשיש לידו tunables אחרים.

    .. note::

       **גם הטסט הזה אינו נופל על הקבצים שלפני ההגדרה, וזה מכוון.** הוא שומר על הקריאה של
       ``GLIBC_TUNABLES``: קריאה שמשווה את כל המחרוזת הייתה דוחה הגדרה נכונה עם tunable נוסף.
    """
    env = {} if tunables is None else {"GLIBC_TUNABLES": tunables}
    assert _rseq_tunable(env) == value


def test_the_scan_finds_mongo_in_workflows_and_compose_and_refuses_unknown_shapes(tmp_path):
    """הסריקה מחזירה כל שירות מונגו בשני סוגי הקבצים, ונכשלת על סביבה שאינה מבינה.

    .. note::

       **גם הטסט הזה אינו נופל על הקבצים שלפני ההגדרה, וזה מכוון.** הוא שומר על
       ``_mongo_services``: סריקה שמחזירה פחות שירותים ממה שיש הייתה משאירה את הטסט על הריפו
       ירוק.
    """
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "a.yml").write_text(
        "on: push\n"
        "jobs:\n"
        "  tests:\n"
        "    runs-on: ubuntu-24.04\n"
        "    services:\n"
        "      db:\n"
        "        image: ${{ matrix.suite == 'main' && 'mongo:8.0' || '' }}\n"
        "        env:\n"
        "          GLIBC_TUNABLES: glibc.pthread.rseq=1\n"
        "      cache:\n"
        "        image: redis:7-alpine\n"
        "    steps: [{run: 'true'}]\n"
        "  bare:\n"
        "    runs-on: ubuntu-24.04\n"
        "    services:\n"
        "      mongodb:\n"
        "        image: mongo:8.0\n"
        "    steps: [{run: 'true'}]\n"
        "  reusable:\n"
        "    uses: ./.github/workflows/b.yml\n",
        encoding="utf-8",
    )
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        "  mongodb:\n"
        "    image: mongo:8.0\n"
        "    environment:\n"
        "      - MONGO_INITDB_ROOT_USERNAME=admin\n"
        "      - GLIBC_TUNABLES=glibc.pthread.rseq=1\n"
        "      - FROM_SHELL\n"
        "  admin-ui:\n"
        "    image: mongo-express:latest\n",
        encoding="utf-8",
    )
    assert _mongo_services(workflows, [compose]) == {
        "a.yml:tests:db": {"GLIBC_TUNABLES": "glibc.pthread.rseq=1"},
        "a.yml:bare:mongodb": {},
        "docker-compose.yml:mongodb": {
            "MONGO_INITDB_ROOT_USERNAME": "admin",
            "GLIBC_TUNABLES": "glibc.pthread.rseq=1",
            "FROM_SHELL": None,
        },
    }

    compose.write_text(
        "services:\n  mongodb:\n    image: mongo:8.0\n    environment: GLIBC_TUNABLES=x\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="docker-compose.yml:mongodb: הסביבה של השירות"):
        _mongo_services(workflows, [compose])
