"""מסלול ההתראות מבוסס-האירועים (``config/alerts.yml``) — מקצה לקצה.

הרקע: ``_maybe_emit_event_alert`` בנה ``ctx`` שמכיל תמיד ``severity`` ואז
קרא ל-``emit_internal_alert(name=..., severity=..., summary=..., **ctx)``.
‏פייתון זורק ``TypeError: got multiple values for keyword argument
'severity'`` בכל קריאה כזו, וה-``except`` הבולע שמסביב הפך את זה לשקט
מוחלט: אף כלל ב-``config/alerts.yml`` לא ירה מעולם.

הטסטים כאן עוברים דרך הפונקציות **האמיתיות** — ``emit_event``,
‏``_maybe_emit_event_alert``, ``emit_internal_alert`` ו-``forward_critical_alert``
— ומחליפים רק את הגבול החיצוני (``alert_manager._notify_critical_external``),
כי דמה של ``emit_internal_alert`` לא הייתה מריצה את פריסת ה-``details``
שהיא עצמה חלק מהתיקון.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# הפונקציות שמקבלות מטען של שדות מקוראים שרירותיים לצד ארגומנטים משלהן.
ALERT_DISPATCH_FUNCTIONS = {"emit_internal_alert", "forward_critical_alert"}

SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "tmp", "build", "_build"}


@pytest.fixture
def reset_event_alert_cache():
    """מאפס את ה-state המודולרי של כללי ההתראות.

    ‏``_EVENT_ALERTS_CACHE`` מחזיק גם את הכללים לפי ``mtime`` וגם את
    ``last_fired`` לצורך ה-cooldown. בלי איפוס, טסט שני שפולט את אותו
    אירוע נחסם בשקט על ידי ``cooldown_seconds`` של הטסט הראשון ועובר
    מסיבה הלא נכונה.
    """
    import observability

    saved = dict(observability._EVENT_ALERTS_CACHE)
    observability._EVENT_ALERTS_CACHE.clear()
    observability._EVENT_ALERTS_CACHE.update({"mtime": 0.0, "rules": [], "last_fired": {}})
    try:
        yield
    finally:
        observability._EVENT_ALERTS_CACHE.clear()
        observability._EVENT_ALERTS_CACHE.update(saved)


@pytest.fixture
def critical_sink(monkeypatch):
    """תופס את הגבול החיצוני של התראות critical, ומשאיר את כל השרשרת אמיתית."""
    import alert_manager

    captured: List[Dict[str, Any]] = []

    def _spy(name: str, summary: str, details: Dict[str, Any]) -> None:
        captured.append({"name": name, "summary": summary, "details": dict(details or {})})

    monkeypatch.setattr(alert_manager, "_notify_critical_external", _spy)
    return captured


def test_job_stuck_event_reaches_the_sink_with_the_job_name(
    reset_event_alert_cache, critical_sink, monkeypatch
):
    """‏``job_stuck`` חייב להגיע לסינק עם שם הג'וב בתוך ההודעה.

    על הקוד שלפני התיקון הטסט הזה נכשל עם ``len(critical_sink) == 0``:
    ה-``TypeError`` נבלע ושום התראה לא יצאה.
    """
    import observability

    monkeypatch.setenv("ALERTS_CONFIG_PATH", str(REPO_ROOT / "config" / "alerts.yml"))

    observability.emit_event(
        "job_stuck",
        severity="error",
        job_id="predictive_sampler",
        run_id="34d7f1d9-0d5",
        minutes=20,
    )

    assert len(critical_sink) == 1, "ההתראה לא הגיעה לסינק בכלל"
    alert = critical_sink[0]
    assert alert["name"] == "job_stuck_alert"
    # מה שהמשתמש אמור לקרוא בטלגרם — כולל שם הג'וב ומספר הדקות.
    assert "predictive_sampler" in alert["summary"]
    assert "20" in alert["summary"]
    # המטען עצמו נשמר ולא נבלע בדרך.
    assert alert["details"]["job_id"] == "predictive_sampler"
    assert alert["details"]["run_id"] == "34d7f1d9-0d5"


def test_event_fields_do_not_shadow_dispatch_parameters(
    reset_event_alert_cache, critical_sink, monkeypatch, tmp_path
):
    """שדות אירוע ששמם כשם פרמטר של הנמען אינם מפילים את ההתראה.

    ‏``name`` ו-``summary`` הם פרמטרים של ``forward_critical_alert``,
    ו-``severity`` של ``emit_internal_alert``. אירוע רשאי לשאת שדות
    בשמות האלה (``alert_manager`` ו-``remediation_manager`` עושים זאת),
    והמסלול חייב לשרוד אותם.
    """
    import observability

    config = tmp_path / "alerts.yml"
    config.write_text(
        "alerts:\n"
        '  - name: shadowing_probe_alert\n'
        '    event_pattern: "shadowing_probe"\n'
        "    severity: critical\n"
        "    cooldown_seconds: 0\n"
        '    message: "probe {job_id}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ALERTS_CONFIG_PATH", str(config))

    observability.emit_event(
        "shadowing_probe",
        severity="error",
        job_id="zombie_job",
        name="a field called name",
        summary="a field called summary",
    )

    assert len(critical_sink) == 1, "שדה ששמו כשם פרמטר הפיל את ההתראה"
    alert = critical_sink[0]
    # שם ההתראה נקבע בכלל שבקונפיג, לא בשדה של האירוע.
    assert alert["name"] == "shadowing_probe_alert"
    assert alert["summary"] == "probe zombie_job"
    # ושדות האירוע עדיין נמצאים במטען.
    assert alert["details"]["name"] == "a field called name"
    assert alert["details"]["summary"] == "a field called summary"


# --------------------------------------------------------------------------
# טסט מבני: שהכותב הבא לא יחזיר את הדפוס
# --------------------------------------------------------------------------


def _iter_repo_python_files():
    for path in REPO_ROOT.rglob("*.py"):
        # ‏relative_to ולא path.parts: הנתיב המוחלט של הריפו עשוי בעצמו
        # להכיל רכיב בשם "tmp"/"build" (למשל ‏git worktree תחת /tmp),
        # ואז סינון על הנתיב המלא מדלג על כל הקבצים והטסט עובר בלי לסרוק
        # כלום. נמדד: בדיוק זה קרה בריצת הבקרה על הקוד הישן.
        if any(part in SKIP_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        yield path


def _callee_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _own_body_nodes(scope: ast.AST):
    """כל הצמתים של ה-scope, בלי לרדת לתוך פונקציות מקוננות.

    בלי ההפרדה הזו, ``details`` שהוא ליטרל בפונקציה אחת היה מכשיר גם
    ``details`` שהוא פרמטר בפונקציה אחרת באותו קובץ.
    """
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, nested):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _locally_built_dict_names(scope: ast.AST) -> set:
    """שמות שכל השמה אליהם בתוך ה-scope היא בניית מילון מקומית.

    מילון שנבנה כאן — ``{...}`` או dict comprehension — אפשר לקרוא את
    מפתחותיו באותה פונקציה. פרמטר, אטריבוט או ערך מוחזר מקריאה — אי אפשר,
    ולכן הם חייבים לעבור דרך ``details=``.
    """
    assigned: Dict[str, List[Any]] = {}
    for node in _own_body_nodes(scope):
        targets: List[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                assigned.setdefault(target.id, []).append(getattr(node, "value", None))
    return {
        name
        for name, values in assigned.items()
        if values and all(isinstance(v, (ast.Dict, ast.DictComp)) for v in values)
    }


def test_alert_dispatch_calls_never_splat_a_foreign_payload():
    """אסור ``**`` של מטען שלא נבנה באותה פונקציה, לצד ארגומנט מפורש.

    זו הצורה שמפילה את הקריאה ב-``TypeError`` כשמפתח במטען נושא שם של
    פרמטר. כשהמטען נבנה מקומית אפשר לראות את המפתחות בעין; כשהוא מגיע
    מפרמטר, מאטריבוט או מקריאה — אי אפשר, והוא חייב לעבור ב-``details=``.

    ‏מקור לסמנטיקה: ``keyword(identifier? arg, expr value)`` ב-ASDL של
    ``ast`` — ``arg`` הוא ``None`` בדיוק עבור ``**``. אומת מול המפרשנים
    המותקנים 3.11, 3.12 ו-3.13 (מטריצת ה-CI היא 3.11 ו-3.12).
    """
    violations: List[str] = []
    scanned_files = 0
    scanned_dispatch_calls = 0

    for path in _iter_repo_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        scanned_files += 1

        for scope in ast.walk(tree):
            if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                continue
            local_dicts = _locally_built_dict_names(scope)

            # רק הקריאות ששייכות ל-scope הזה עצמו, לא לפונקציות מקוננות בתוכו.
            for node in _own_body_nodes(scope):
                if not isinstance(node, ast.Call):
                    continue
                if _callee_name(node) not in ALERT_DISPATCH_FUNCTIONS:
                    continue
                scanned_dispatch_calls += 1

                explicit = [kw.arg for kw in node.keywords if kw.arg is not None]
                splats = [kw for kw in node.keywords if kw.arg is None]
                if not explicit or not splats:
                    continue

                for kw in splats:
                    value = kw.value
                    if isinstance(value, ast.Name) and value.id in local_dicts:
                        continue
                    if isinstance(value, (ast.Dict, ast.DictComp)):
                        continue
                    rel = path.relative_to(REPO_ROOT)
                    violations.append(
                        f"{rel}:{node.lineno} — {_callee_name(node)}("
                        f"{', '.join(explicit)}, **{ast.unparse(value)})"
                    )

    # שומר מפני המצב שבו הסריקה לא ראתה כלום והטסט "עבר" על אוויר.
    assert scanned_files > 100, f"הסריקה עברה על {scanned_files} קבצים בלבד — משהו בסינון שבור"
    assert scanned_dispatch_calls > 0, "לא נמצאה אף קריאה לפונקציות השיגור — הזיהוי שבור"

    assert not violations, (
        "מטען שלא נבנה באותה פונקציה מועבר ב-** לצד ארגומנט מפורש. "
        "העבירו אותו כ-details={...}:\n  " + "\n  ".join(sorted(set(violations)))
    )


def test_dispatch_functions_still_accept_an_explicit_details_payload():
    """החתימות שהטסטים למעלה נשענים עליהן קיימות באמת.

    בלי זה, שינוי עתידי בחתימה היה הופך את ``details=`` למפתח רגיל
    בתוך ``**kwargs`` — והטסטים היו ממשיכים לעבור על התנהגות אחרת.
    """
    from alert_manager import forward_critical_alert
    from internal_alerts import emit_internal_alert

    forward_params = inspect.signature(forward_critical_alert).parameters
    assert "details" in forward_params
    assert forward_params["details"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD

    # ‏emit_internal_alert קולטת את המטען דרך ``**details`` ופורסת מילון
    # יחיד בשם ``details`` חזרה למטען. אם מישהו יהפוך את ``details``
    # לפרמטר מפורש — הפריסה הזו מתייתרת, והבדיקה הזו היא שתסמן את זה.
    emit_params = inspect.signature(emit_internal_alert).parameters
    assert emit_params["details"].kind is inspect.Parameter.VAR_KEYWORD, (
        "details אינו עוד **kwargs ב-emit_internal_alert — בדקו שפריסת "
        "details={...} עדיין נכונה, ועדכנו את הבדיקה"
    )
