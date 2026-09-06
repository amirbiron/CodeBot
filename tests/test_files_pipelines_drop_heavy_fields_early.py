"""השדות הכבדים יורדים לפני המיון והקיבוץ, ולא אחריהם.

**מה הבעיה, במשל.** נניח שאתה מבקש מהמחסן רשימה של שמות תיקיות. במקום
לפתוח כל תיקייה, לרשום את השם ולהחזיר אותה למקום — המחסנאי סוחב את כל
התיקיות עם כל הניירת לשולחן, ממיין שם את הערימה, מקבץ, **ורק בסוף** זורק
את הניירת ומגיש לך שמות. השולחן קטן, ולכן הוא קורס באמצע.

זה מה שקרה בפרודקשן: ``$project`` שמסיר את ``code`` ישב **אחרי**
ה-``$sort`` וה-``$group``, מונגו החזיר שגיאה 292
(``QueryExceededMemoryLimitNoDiskUseAllowed``), והקוד נפל למסלול חלופי
איטי — 3.1 עד 3.4 שניות לטעינת ``/files``. ``allowDiskUse`` לא הציל, כי
Atlas מתעלם ממנו בקלאסטרים חינמיים ו-Flex.

**מה נבדק כאן, ולמה דווקא ככה.** הטסט לא בודק את הפלט של פונקציית הבנייה
— פונקציה כזו אפשר לכתוב נכון ועדיין לשכוח לחבר אליה אתר קריאה, והטסט
היה ירוק. במקום זה הוא **מקליט את הצינורות שאתרי הקריאה שולחים בפועל**
ל-``aggregate``, ומאמת עליהם את התכונה. זו אותה דלת שהמשתמש עובר בה.

**התכונה:** אם צינור מכיל ``$sort``, או ``$group`` שצובר מסמכים שלמים
(``$$ROOT``), אז ``code`` חייב לרדת ממנו **לפני** אותו שלב. שני השלבים
האלה הם שמחזיקים מסמכים בזיכרון — ``$sort`` מאגר את מה שהוא ממיין,
ו-``$group`` צובר את מה שהוא שומר.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from webapp import app as webapp_app

HEAVY_FIELD = "code"

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)

DOC = {
    "_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
    "user_id": 123,
    "is_active": True,
    "file_name": "demo.py",
    "programming_language": "python",
    "description": "demo",
    "tags": ["repo:amirbiron/CodeBot"],
    "file_size": 10,
    "lines_count": 1,
    "version": 1,
    "created_at": NOW - timedelta(days=1),
    "updated_at": NOW - timedelta(days=1),
}


# ---------------------------------------------------------------- הכלים


def _stage_name(stage: Any) -> Optional[str]:
    if isinstance(stage, dict) and len(stage) == 1:
        return next(iter(stage))
    return None


def _removes_heavy_field(stage: Any) -> bool:
    """האם השלב הזה מוציא את ``code`` מהמסמך.

    שתי הצורות נחשבות: החרגה (``{'code': 0}``) והכללה שאינה מזכירה את
    ``code`` — בהיטלת הכללה כל מה שלא נרשם נופל ממילא. ``$unset`` נתמך גם
    הוא, כי הוא הדרך השנייה של מונגו לומר את אותו דבר.
    """
    name = _stage_name(stage)
    if name == "$unset":
        value = stage["$unset"]
        fields = [value] if isinstance(value, str) else list(value or [])
        return HEAVY_FIELD in fields
    if name != "$project":
        return False

    spec = stage["$project"] or {}
    if not isinstance(spec, dict):
        return False
    if HEAVY_FIELD in spec:
        return not spec[HEAVY_FIELD]

    # היטלה מעורבת אינה חוקית במונגו (למעט ``_id``), ולכן די לבדוק שדה אחד
    # שאינו ``_id`` כדי לדעת אם זו הכללה או החרגה.
    for field, value in spec.items():
        if field == "_id":
            continue
        return bool(value)  # הכללה ← ``code`` שלא נרשם יורד ממילא
    return False


def _buffers_documents(stage: Any) -> bool:
    """שלב שמחזיק מסמכים בזיכרון: ``$sort``, או ``$group`` שצובר ``$$ROOT``."""
    name = _stage_name(stage)
    if name == "$sort":
        return True
    if name != "$group":
        return False
    return "$$ROOT" in repr(stage["$group"])


def assert_heavy_field_drops_early(pipeline: List[Dict[str, Any]], label: str) -> None:
    stages = list(pipeline or [])
    buffering = [i for i, st in enumerate(stages) if _buffers_documents(st)]
    if not buffering:
        return

    drops = [i for i, st in enumerate(stages) if _removes_heavy_field(st)]
    first_buffer = buffering[0]
    shape = " ← ".join(_stage_name(st) or "?" for st in stages)

    assert drops, (
        f"[{label}] הצינור ממיין או צובר מסמכים שלמים ואף פעם לא מוריד "
        f"את `{HEAVY_FIELD}`.\n   {shape}"
    )
    assert drops[0] < first_buffer, (
        f"[{label}] `{HEAVY_FIELD}` יורד בשלב {drops[0]}, אחרי שלב שמחזיק "
        f"מסמכים בזיכרון בשלב {first_buffer}. גוף הקובץ נגרר לתוך "
        f"{_stage_name(stages[first_buffer])}.\n   {shape}"
    )


# ------------------------------------------------------- הסטאב שמקליט


class _RecordingCodeSnippets:
    """אוסף מזויף שרושם כל צינור שנשלח אליו, ומחזיר מסמך אחד."""

    def __init__(self):
        self.pipelines: List[List[Dict[str, Any]]] = []

    def aggregate(self, pipeline, allowDiskUse=False):
        stages = list(pipeline or [])
        self.pipelines.append(stages)
        for st in stages:
            if _stage_name(st) == "$count":
                return [{next(iter(st["$count"]) if isinstance(st["$count"], dict) else [st["$count"]]): 1}]
        return [dict(DOC)]

    def distinct(self, _field, _query=None):
        return ["python"]

    def count_documents(self, _query, **_kwargs):
        return 1

    def find(self, _query, _projection=None):
        return _Cursor([dict(DOC)])


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_a, **_k):
        return self

    def skip(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def __iter__(self):
        return iter(self._docs)


class _StubDB:
    def __init__(self, code_snippets):
        self.code_snippets = code_snippets

    def __getattr__(self, name):
        # אוספים אחרים שהעמוד נוגע בהם (large_files, users…) — ריקים ולא מפריעים.
        return _RecordingCodeSnippets()


class _CacheDisabled:
    is_enabled = False


@pytest.fixture
def recorder(monkeypatch):
    collection = _RecordingCodeSnippets()
    monkeypatch.setattr(webapp_app, "get_db", lambda: _StubDB(collection), raising=True)
    monkeypatch.setattr(webapp_app, "cache", _CacheDisabled(), raising=True)
    return collection


def _client():
    client = webapp_app.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 123
        sess["user_data"] = {"id": 123, "first_name": "Test"}
    return client


# ------------------------------------------------------------ הטסטים


@pytest.mark.parametrize(
    "url, label",
    [
        ("/files", "ברירת מחדל (עימוד לפי cursor על created_at)"),
        ("/files?category=recent", "קטגוריית recent"),
        ("/files?category=repo", "רשימת הריפואים (repo_pipeline)"),
        ("/files?sort=name", "מיון לפי שם — מסלול ללא cursor"),
        ("/files?category=other", "קטגוריית other"),
    ],
)
def test_files_page_never_sorts_or_groups_full_documents(recorder, url, label):
    response = _client().get(url)
    assert response.status_code == 200, f"{url} החזיר {response.status_code}"
    assert recorder.pipelines, f"{url} לא הריץ שום aggregate — הטסט לא בדק כלום"

    for index, pipeline in enumerate(recorder.pipelines):
        assert_heavy_field_drops_early(pipeline, f"{label} · צינור {index}")


def test_files_need_attention_never_sorts_or_groups_full_documents(recorder):
    """הווידג'ט בדשבורד, דרך הפונקציה שהראוט קורא לה."""
    webapp_app._build_files_need_attention(
        _StubDB(recorder), 123, max_items=10, stale_days=60, dismissed_ids=[]
    )

    assert recorder.pipelines, "לא הורץ שום aggregate — הטסט לא בדק כלום"
    for index, pipeline in enumerate(recorder.pipelines):
        assert_heavy_field_drops_early(pipeline, f"files_need_attention · צינור {index}")


# ------------------------------------------ אפס אינו "לא ידוע"


class _CountFailsCodeSnippets(_RecordingCodeSnippets):
    """כמו הסטאב הרגיל, אבל ספירה נכשלת — בדיוק כמו 292 בפרודקשן."""

    def aggregate(self, pipeline, allowDiskUse=False):
        from pymongo.errors import OperationFailure

        stages = list(pipeline or [])
        for st in stages:
            if _stage_name(st) == "$count":
                raise OperationFailure("ExceededMemoryLimit", code=292)
        return super().aggregate(stages, allowDiskUse=allowDiskUse)


def test_a_failed_count_is_unknown_and_not_zero(monkeypatch):
    """ספירה שנכשלה מחזירה ``None``, לא ``0``.

    ``0`` הוא תשובה שנראית לגיטימית: המשתמש קורא "אין קבצים שדורשים
    טיפול" ומאמין לזה. אחרי כשל אנחנו לא יודעים כמה יש, וזה מה שצריך
    להיאמר.
    """
    collection = _CountFailsCodeSnippets()
    monkeypatch.setattr(webapp_app, "cache", _CacheDisabled(), raising=True)

    result = webapp_app._build_files_need_attention(
        _StubDB(collection), 123, max_items=10, stale_days=60, dismissed_ids=[]
    )

    assert result["total_missing"] is None, "ספירה שנכשלה הוצגה כאפס"
    assert result["total_stale"] is None, "ספירה שנכשלה הוצגה כאפס"


def test_the_dashboard_renders_a_dash_instead_of_a_wrong_number():
    """התבנית האמיתית לא נופלת על ``None``, ולא ממציאה מספר.

    **נבדק על ``dashboard.html`` עצמו ולא על ביטוי שנכתב כאן.** טסט שמרנדר
    מחרוזת שהטסט עצמו כתב מאמת את מה שהמחבר חשב, לא את מה שהמשתמש מקבל —
    והוא יישאר ירוק גם אם התבנית תשתנה. לכן הבלוק נחתך מהקובץ ומורץ כמו
    שהוא.

    ב-Jinja החישוב הוא Python, ולכן ``None + None`` זורק ``TypeError``.
    """
    import re
    from pathlib import Path

    from jinja2 import Environment

    source = Path("webapp/templates/dashboard.html").read_text(encoding="utf-8")
    start = source.index('<span class="badge badge-warning" data-attention-total-badge>')
    # הבלוק מכיל ``<span>`` פנימי, ולכן נחתכים לפי ``{% endif %}`` ואז
    # ה-``</span>`` שאחריו — ולא לפי ה-``</span>`` הראשון שנתקלים בו.
    end = source.index("</span>", source.index("{% endif %}", start)) + len("</span>")
    block = source[start:end]
    assert "total_missing" in block, "נחתך הבלוק הלא נכון מהתבנית"

    template = Environment().from_string(block)

    class _Unknown:
        total_missing = None
        total_stale = 3

    rendered = template.render(files_need_attention=_Unknown())
    assert "—" in rendered, f"ספירה לא ידועה לא הוצגה כמקף: {rendered!r}"
    assert "0" not in re.sub(r"<[^>]*>", "", rendered), "הוצג מספר במקום 'לא ידוע'"

    class _Known:
        total_missing = 2
        total_stale = 3

    rendered = template.render(files_need_attention=_Known())
    assert "5" in rendered, f"סכום תקין לא רונדר: {rendered!r}"
