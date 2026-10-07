"""התיעוד של אינדקס התיעוד מול הקוד: שמות שהוא נוקב בהם קיימים, והאירועים שהוא מונה הם אלה שנשלחים.

העמודים נוקבים בשמות של קבועים ופונקציות במקום להעתיק את הערכים שלהם (``prose-restates-code-fact``
ב-amir-bug-patterns). שם שהשתנה בקוד היה משאיר את הפרוזה מפנה למשהו שלא קיים, והטסטים כאן הם מה
שהופך את זה לכשל.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GLOBAL_SEARCH = ROOT / "docs" / "webapp" / "global-search.rst"
EVENTS_CATALOG = ROOT / "docs" / "observability" / "events_catalog.rst"
EMITTERS = (ROOT / "services" / "docs_index_service.py", ROOT / "webapp" / "app.py")


def _section(path: Path, label: str) -> str:
    """הטקסט מהתווית ועד התווית הבאה בעמוד."""
    text = path.read_text(encoding="utf-8")
    start = text.index(f".. _{label}:")
    following = re.search(r"^\.\. _[\w-]+:$", text[start + 1:], re.M)
    return text[start:start + 1 + following.start()] if following else text[start:]


@pytest.mark.parametrize(
    "module,name",
    [
        ("services.docs_index_service", "run_pass"),
        ("webapp.routes.webhooks", "handle_push_event"),
        ("services.docs_index_service", "is_links_only"),
        ("services.docs_index_service", "APPROVAL_THRESHOLD_CHUNKS"),
        ("services.docs_index_service", "PASS_DEADLINE_SECONDS"),
        ("services.docs_index_service", "TRIGGERS"),
        ("services.docs_search_contract", "vector_index_definition"),
        ("services.chunking_service", "CHUNK_MAX_BYTES"),
        ("services.chunking_service", "split_code_to_chunks"),
        ("webapp.routes.webhooks", "handle_deployment_status_event"),
        ("webapp.app", "admin_api_required"),
    ],
)
def test_a_name_the_docs_cite_exists_in_the_code(module, name):
    import importlib

    assert hasattr(importlib.import_module(module), name), f"{module}.{name}"
    pages = GLOBAL_SEARCH.read_text(encoding="utf-8") + EVENTS_CATALOG.read_text(encoding="utf-8")
    assert f"``{name}``" in pages, f"{name} אינו מוזכר עוד בתיעוד — הסירו אותו מהרשימה"


def test_the_values_the_docs_spell_out_are_the_codes_in_the_code():
    from services import docs_index_service as svc

    section = _section(GLOBAL_SEARCH, "docs-index")
    assert f"``{svc.CODE_OLDER_EXPORT}``" in section
    assert f"``{svc.STATUS_PAUSED_QUOTA}``" in section


def test_the_catalog_lists_exactly_the_events_that_are_emitted():
    emitted = set()
    for path in EMITTERS:
        emitted |= set(re.findall(r"emit_event\(\s*[\"'](docs_index_\w+)[\"']", path.read_text(encoding="utf-8")))
    listed = set(re.findall(r"^- ``(docs_index_\w+)``", _section(EVENTS_CATALOG, "docs-index-events"), re.M))

    assert emitted, "לא נמצא אף אירוע בקוד — הביטוי לא תופס יותר את הקריאות"
    assert listed == emitted
