"""החוזה של חיפוש התיעוד — ושני הצדדים שלו מסכימים עליו.

קובץ הייצוא נכתב בבניית האתר (``scripts/docs_export_sections.py``, ב-``documentation.yml``)
ונקרא בוובאפ (``services/docs_export_client.py``). שני הצדדים רצים ביחידות פריסה שונות, ולכן
כמה שמות כתובים בשניהם (ההסבר ב-docstring של ``services/docs_search_contract.py``). הטסטים כאן
הם מה שהופך עותק כזה מתקווה לכשל CI: הם משווים את העותקים, ומעבירים מסמך שהיצרן בונה דרך
הקורא של הוובאפ.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import docs_export_sections as producer  # noqa: E402  (אחרי sys.path.insert)
from scripts import measure_docs_export as measure  # noqa: E402
from services import docs_export_client as client  # noqa: E402
from services import docs_search_contract as contract  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "documentation.yml"
SHA = "0123456789abcdef0123456789abcdef01234567"


# ---------------------------------------------------------------------------
# העותקים מול המקור
# ---------------------------------------------------------------------------


def test_the_schema_version_is_the_one_the_export_writes():
    assert contract.SCHEMA_VERSION == producer.SCHEMA_VERSION


def test_the_file_paths_are_the_ones_the_export_writes():
    assert contract.EXPORT_PATH == str(producer.EXPORT_PATH)
    assert contract.export_path_for_commit(SHA) == str(producer.export_path_for_commit(SHA))


@pytest.mark.parametrize("value", ["", "abc", SHA.upper(), SHA + "0", None, 7])
def test_both_sides_refuse_the_same_non_sha_values(value):
    with pytest.raises(ValueError):
        contract.export_path_for_commit(value)
    with pytest.raises(ValueError):
        producer.export_path_for_commit(value)
    assert contract.is_commit_sha(value) is False


def test_the_site_url_is_the_one_the_workflow_builds_links_with():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = {step.get("id"): step for step in workflow["jobs"]["build-docs"]["steps"]}
    assert steps["export_sections"]["env"]["DOCS_SITE_URL"] == contract.SITE_URL


def test_the_measuring_script_joins_the_breadcrumb_like_the_webapp():
    assert measure.BREADCRUMB_SEPARATOR == client.BREADCRUMB_SEPARATOR


# ---------------------------------------------------------------------------
# מסמך שהיצרן בונה עובר בקורא של הוובאפ
# ---------------------------------------------------------------------------


def _producer_section(anchor: str, breadcrumb: list[str], markdown: str = "תוכן") -> dict:
    return {
        "anchor": anchor,
        "title": breadcrumb[-1],
        "breadcrumb": breadcrumb,
        "level": len(breadcrumb),
        "markdown": markdown,
    }


def test_a_document_built_by_the_export_reads_back_in_the_webapp():
    raw_sections = [
        _producer_section("guide", ["מדריך"], ""),
        _producer_section("id1", ["מדריך", "סעיף ראשון"], "::: warning\nזהירות\n:::"),
        _producer_section("deep", ["מדריך", "סעיף ראשון", "עמוק"]),
    ]
    # אותה בדיקה שהיצרן מריץ על מה שהדפדפן החזיר, ואז אותו מסמך שהוא כותב לקובץ.
    sections = producer._validated_sections({"sections": raw_sections}, "index.html")
    exported = [
        {"path": "index.html", "source_path": "docs/index.rst", "sections": sections},
        {
            "path": "webapp/global-search.html",
            "source_path": "docs/webapp/global-search.rst",
            "sections": producer._validated_sections(
                {"sections": [_producer_section("webapp-global-search", ["חיפוש גלובלי"])]},
                "webapp/global-search.html",
            ),
        },
    ]
    document = producer.build_document(exported, site_url=contract.SITE_URL, source_commit=SHA)
    data = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    parsed = client.parse_export(data)

    assert parsed.source_commit == SHA
    assert parsed.site_url == contract.SITE_URL
    assert parsed.built_at.utcoffset() is not None
    assert [page.path for page in parsed.pages] == ["index.html", "webapp/global-search.html"]
    assert parsed.pages[0].title == "מדריך"
    assert parsed.section_count == 4
    deep = parsed.pages[0].sections[2]
    assert (deep.anchor, deep.level, deep.breadcrumb) == ("deep", 3, ("מדריך", "סעיף ראשון", "עמוק"))


# ---------------------------------------------------------------------------
# הדקדוק של מה שנכנס לכתובת, והאינדקס הווקטורי
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anchor", ["guide", "id12", "webapp-global-search", "mod.func", "a_b:c"])
def test_anchors_in_the_grammar(anchor):
    assert contract.ANCHOR_RE.fullmatch(anchor)


@pytest.mark.parametrize("anchor", ["", "1abc", "-x", "a b", "a#b", "a/b", "שלום", "a%20b"])
def test_anchors_outside_the_grammar(anchor):
    assert not contract.ANCHOR_RE.fullmatch(anchor)


@pytest.mark.parametrize(
    "path",
    ["index.html", "webapp/global-search.html", "observability/events_catalog.html", "dev/A_B-c.html"],
)
def test_page_paths_in_the_grammar(path):
    assert contract.PAGE_PATH_RE.fullmatch(path)


@pytest.mark.parametrize(
    "path",
    ["", "/index.html", "../index.html", "a/../b.html", ".hidden/x.html", "a/./b.html", "x.htm",
     "https://evil.example/x.html", "a//b.html", "a b.html", "a\\b.html"],
)
def test_page_paths_outside_the_grammar(path):
    assert not contract.PAGE_PATH_RE.fullmatch(path)


@pytest.mark.parametrize("path", ["docs/index.rst", "docs/user/sticky_notes.rst", "docs/monitoring.md"])
def test_source_paths_in_the_grammar(path):
    assert contract.SOURCE_PATH_RE.fullmatch(path)


@pytest.mark.parametrize("path", ["docs/index.html", "/docs/x.rst", "../x.rst", "docs/x.txt"])
def test_source_paths_outside_the_grammar(path):
    assert not contract.SOURCE_PATH_RE.fullmatch(path)


def test_the_vector_index_definition_follows_the_active_dimensions():
    assert contract.vector_index_definition(768) == {
        "fields": [
            {"type": "vector", "path": "chunkEmbedding", "numDimensions": 768, "similarity": "cosine"},
            {"type": "filter", "path": "embeddingModelKey"},
        ]
    }


@pytest.mark.parametrize("dimensions", [0, -1, contract.ATLAS_MAX_DIMENSIONS + 1, True, "768", 768.0])
def test_the_vector_index_definition_refuses_impossible_dimensions(dimensions):
    with pytest.raises(ValueError):
        contract.vector_index_definition(dimensions)
