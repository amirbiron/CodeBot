"""חיפוש בתיעוד — ``services/docs_search_service.py`` ו-``POST /api/search/docs``.

האינדקס נבנה במעבר אמיתי (``fill`` של ``_docs_index_harness``), ואוסף הנתחים הוא ``_Atlas``: דמה
שמריצה את הצינור של החיפוש — רק בצורה שהשירות שולח, כך ששינוי בצינור מפיל את הטסט במקום לעבור
בשקט. הווקטורים של הנתחים מוחלפים אחרי המילוי בווקטור יחידה לכל סעיף, כדי שהדירוג יהיה ידוע מראש.
"""

from __future__ import annotations

import math

import pytest
from pymongo.errors import ExecutionTimeout, OperationFailure, ServerSelectionTimeoutError

# ‏``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _docs_index_harness import DIMENSIONS, MODEL, MODEL_KEY, SHA_A, admin_app_for, fill, make_world, page, section
from _fake_mongo import FakeCollection, FakeDB

from services import docs_index_service as svc
from services import docs_search_contract as contract
from services import docs_search_service as search
from services.embedding_service import EMBEDDING_DETAIL_DEADLINE_EXCEEDED, EMBEDDING_DETAIL_MISSING_API_KEY


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class _Atlas(FakeCollection):
    """``docs_chunks`` ב-Atlas: מצב האינדקס הווקטורי נקבע בטסט, ו-``aggregate`` מריץ את הצינור של החיפוש."""

    def __init__(self):
        super().__init__()
        self.indexes = [
            {"name": contract.VECTOR_INDEX_NAME, "status": "READY", "queryable": True,
             "latestDefinition": contract.vector_index_definition(DIMENSIONS)}
        ]
        self.list_error = None
        self.aggregate_error = None
        self.pipelines = []

    def list_search_indexes(self, name=None, session=None, comment=None, **kwargs):
        if self.list_error is not None:
            raise self.list_error
        return [dict(index) for index in self.indexes if name in (None, index["name"])]

    def aggregate(self, pipeline, *args, **kwargs):
        self.pipelines.append(pipeline)
        if self.aggregate_error is not None:
            raise self.aggregate_error
        assert [next(iter(stage)) for stage in pipeline] == ["$vectorSearch", "$project", "$group", "$sort", "$limit"]
        stage = pipeline[0]["$vectorSearch"]
        assert (stage["index"], stage["path"]) == (contract.VECTOR_INDEX_NAME, contract.VECTOR_FIELD)
        assert stage["numCandidates"] >= 20 * stage["limit"]
        assert pipeline[1]["$project"] == {"_id": 0, "section_id": 1, "score": {"$meta": "vectorSearchScore"}}
        assert pipeline[2]["$group"] == {"_id": "$section_id", "score": {"$max": "$score"}}
        assert pipeline[3]["$sort"] == {"score": -1, "_id": 1}
        # ציון של Atlas ל-cosine הוא (1 + cos) / 2, בטווח 0 עד 1.
        scored = sorted(
            ((1 + _cosine(stage["queryVector"], doc[contract.VECTOR_FIELD])) / 2, doc["section_id"])
            for doc in self.find(stage["filter"])
        )[::-1][: stage["limit"]]
        best = {}
        for score, section_id in scored:
            best[section_id] = max(score, best.get(section_id, 0.0))
        rows = sorted(({"_id": key, "score": value} for key, value in best.items()),
                      key=lambda row: (-row["score"], row["_id"]))
        return iter(rows[: pipeline[4]["$limit"]])


class _QueryEmbedder:
    """``SyncEmbeddingClient`` לשאלה: מחזיר את הווקטור שהטסט קבע, או כשל בחוזה של ``embed_batch``."""

    def __init__(self, world):
        self.world = world

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def embed_batch(self, texts, *, model, api_version, dimensions, deadline):
        self.world.query_calls.append({"texts": list(texts), "model": model, "api_version": api_version,
                                       "dimensions": dimensions})
        if self.world.query_failure is not None:
            return (None,) + self.world.query_failure
        return [list(self.world.query_vector)], 200, ""


def _unit(index):
    return [1.0 if position == index else 0.0 for position in range(DIMENSIONS)]


def _pages():
    """ארבעה סעיפים, ואחד מהם ארוך — נתח אחד לא מספיק לו."""
    long_body = "\n".join(f"שורה {n} בהסבר הארוך על חיפוש בתיעוד, עם מספיק מילים כדי למלא נתח." for n in range(80))
    return [
        page("webapp/search.html", "docs/webapp/search.rst",
             section("search-basics", "חיפוש", "יסודות"),
             section("search-long", "חיפוש", "הסבר ארוך", markdown=long_body)),
        page("webapp/themes.html", "docs/webapp/themes.rst",
             section("themes-dark", "ערכות", "כהה"), section("themes-light", "ערכות", "בהירה")),
    ]


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    db.c[contract.CHUNKS_COLLECTION] = _Atlas()
    world = make_world(monkeypatch, db)
    world.atlas = db[contract.CHUNKS_COLLECTION]
    world.query_calls = []
    world.query_failure = None
    world.query_vector = _unit(0)
    world.search = lambda query="איך מחפשים בתיעוד", **kwargs: search.search_docs(
        db, query, embed_client_factory=lambda: _QueryEmbedder(world), **kwargs
    )
    return world


def _filled(world):
    """מילוי, ואחריו וקטור יחידה לכל סעיף — לפי הסדר של המזהים — ומפה מעוגן לאינדקס שלו."""
    fill(world, pages=_pages())
    sections = sorted(world.db[contract.SECTIONS_COLLECTION].find({}), key=lambda doc: doc["_id"])
    position = {doc["_id"]: index for index, doc in enumerate(sections)}
    for chunk in list(world.atlas.find({})):
        world.atlas.update_one(
            {"_id": chunk["_id"]}, {"$set": {contract.VECTOR_FIELD: _unit(position[chunk["section_id"]])}}
        )
    return {doc["anchor"]: position[doc["_id"]] for doc in sections}


# ---------------------------------------------------------------------------
# התוצאות
# ---------------------------------------------------------------------------


def test_the_closest_sections_come_back_first_with_their_markdown_and_link(world):
    anchors = _filled(world)
    world.query_vector = [0.0] * DIMENSIONS
    world.query_vector[anchors["themes-dark"]] = 1.0
    world.query_vector[anchors["search-basics"]] = 0.5

    found = world.search(limit=2)

    assert [result["anchor"] for result in found["results"]] == ["themes-dark", "search-basics"]
    first = found["results"][0]
    assert first["url"] == contract.SITE_URL + "webapp/themes.html#themes-dark"
    assert (first["title"], first["breadcrumb"], first["page_title"]) == ("כהה", ["ערכות", "כהה"], "ערכות")
    assert first["markdown"] == "טקסט של הסעיף."
    assert 0 < found["results"][1]["score"] < first["score"] <= 1
    assert (found["source_commit"], found["index_complete"]) == (SHA_A, True)


def test_the_chunks_of_one_section_come_back_as_one_result(world):
    anchors = _filled(world)
    long_id = world.db[contract.SECTIONS_COLLECTION].find_one({"anchor": "search-long"})["_id"]
    assert len(list(world.atlas.find({"section_id": long_id}))) >= 2
    world.query_vector = _unit(anchors["search-long"])

    found = world.search(limit=3)

    anchors_found = [result["anchor"] for result in found["results"]]
    assert anchors_found[0] == "search-long"
    assert len(anchors_found) == len(set(anchors_found)) == 3


def test_the_query_is_embedded_with_the_model_of_the_index_and_not_the_active_settings(world):
    _filled(world)
    world.db["system_config"].update_one(
        {"_id": "semantic_embedding"}, {"$set": {"model": "text-embedding-005", "dimensions": 8}}
    )

    found = world.search()

    assert world.query_calls == [{"texts": ["איך מחפשים בתיעוד"], "model": MODEL, "api_version": "v1beta",
                                  "dimensions": DIMENSIONS}]
    assert world.atlas.pipelines[0][0]["$vectorSearch"]["filter"] == {contract.MODEL_KEY_FIELD: MODEL_KEY}
    assert found["index_complete"] is False


def test_a_section_deleted_between_the_two_reads_is_left_out(world):
    anchors = _filled(world)
    world.query_vector = _unit(anchors["themes-light"])
    gone = world.db[contract.SECTIONS_COLLECTION].find_one({"anchor": "themes-light"})["_id"]
    world.db[contract.SECTIONS_COLLECTION].delete_many({"_id": {"$in": [gone]}})

    found = world.search(limit=4)

    assert "themes-light" not in [result["anchor"] for result in found["results"]]
    assert len(found["results"]) == 3


def test_a_section_that_would_build_a_bad_link_is_left_out_and_logged(world, caplog):
    anchors = _filled(world)
    world.query_vector = _unit(anchors["themes-dark"])
    world.db[contract.SECTIONS_COLLECTION].update_one(
        {"anchor": "themes-dark"}, {"$set": {"page_path": "javascript:alert(1)//x.html"}}
    )

    found = world.search(limit=4)

    assert "themes-dark" not in [result["anchor"] for result in found["results"]]
    assert "no valid page path or anchor" in caplog.text


# ---------------------------------------------------------------------------
# השאלה
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,code",
    [(None, "invalid_query"), (7, "invalid_query"), (["חיפוש"], "invalid_query"), ("   ", "empty_query"),
     ("", "empty_query"), ("\ud800", "invalid_query"), ("א" * 1001, "query_too_long")],
)
def test_a_query_that_is_not_a_question_is_refused_before_any_work(world, query, code):
    with pytest.raises(search.DocsSearchError) as caught:
        world.search(query)

    assert (caught.value.code, caught.value.http_status) == (code, 400)
    assert world.query_calls == [] and world.atlas.pipelines == []


def test_the_query_limit_is_counted_in_bytes_not_characters(world):
    _filled(world)

    world.search("א" * (search.QUERY_MAX_BYTES // 2))

    assert len(world.query_calls) == 1


@pytest.mark.parametrize("limit", [0, search.MAX_LIMIT + 1, "5", 2.0, True, None])
def test_a_limit_outside_the_range_is_refused(world, limit):
    with pytest.raises(search.DocsSearchError) as caught:
        world.search(limit=limit)

    assert caught.value.code == "invalid_limit"


# ---------------------------------------------------------------------------
# אין אינדקס שאפשר לחפש בו — סיבה, ולא "אפס תוצאות"
# ---------------------------------------------------------------------------


def _unavailable(world):
    with pytest.raises(search.DocsSearchError) as caught:
        world.search()
    assert (caught.value.code, caught.value.http_status) == ("index_unavailable", 503)
    assert world.query_calls == [] and world.atlas.pipelines == []
    return caught.value.reason


def test_before_the_first_fill_there_is_no_index(world):
    assert _unavailable(world) == "not_indexed"


def test_a_state_that_names_a_model_no_chunk_has_is_not_an_index(world):
    _filled(world)
    world.db[contract.STATE_COLLECTION].update_one({"_id": svc.STATE_ID},
                                                   {"$set": {"indexed_model_key": "other-model/4"}})

    assert _unavailable(world) == "not_indexed"


@pytest.mark.parametrize(
    "setup,reason",
    [
        (lambda atlas: setattr(atlas, "list_error", OperationFailure("not atlas", code=svc.SEARCH_NOT_ENABLED_CODE)),
         "vector_search_unavailable"),
        (lambda atlas: setattr(atlas, "indexes", []), "vector_index_missing"),
        (lambda atlas: setattr(atlas, "list_error", OperationFailure("denied", code=13)), "vector_index_error"),
        (lambda atlas: atlas.indexes[0].update(status="BUILDING", queryable=False), "vector_index_not_queryable"),
        (lambda atlas: atlas.indexes[0].update(latestDefinition=contract.vector_index_definition(8)),
         "vector_index_dimensions_mismatch"),
    ],
)
def test_an_atlas_index_that_cannot_answer_is_named_before_any_embedding(world, setup, reason):
    _filled(world)
    setup(world.atlas)

    assert _unavailable(world) == reason


# ---------------------------------------------------------------------------
# כשלים בדרך
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure,code,status",
    [
        ((0, EMBEDDING_DETAIL_MISSING_API_KEY), "embedding_unavailable", 503),
        ((0, EMBEDDING_DETAIL_DEADLINE_EXCEEDED), "embedding_timeout", 504),
        ((429, "RESOURCE_EXHAUSTED"), "embedding_quota", 429),
        ((500, "internal"), "embedding_failed", 502),
    ],
)
def test_an_embedding_failure_has_its_own_code_and_no_search_runs(world, failure, code, status):
    _filled(world)
    world.query_failure = failure

    with pytest.raises(search.DocsSearchError) as caught:
        world.search()

    assert (caught.value.code, caught.value.http_status) == (code, status)
    assert world.atlas.pipelines == []


@pytest.mark.parametrize(
    "error,code,status",
    [
        (ExecutionTimeout("operation exceeded time limit", code=50), "search_timeout", 504),
        (OperationFailure("not atlas", code=svc.SEARCH_NOT_ENABLED_CODE), "index_unavailable", 503),
        (OperationFailure("bad vector", code=2), "search_failed", 502),
    ],
)
def test_a_failing_vector_search_has_its_own_code(world, error, code, status):
    _filled(world)
    world.atlas.aggregate_error = error

    with pytest.raises(search.DocsSearchError) as caught:
        world.search()

    assert (caught.value.code, caught.value.http_status) == (code, status)


def test_a_database_that_cannot_be_reached_is_not_reported_as_a_slow_search(world):
    _filled(world)
    world.atlas.aggregate_error = ServerSelectionTimeoutError("no primary available")

    with pytest.raises(ServerSelectionTimeoutError):
        world.search()


# ---------------------------------------------------------------------------
# הראוט
# ---------------------------------------------------------------------------


@pytest.fixture
def app(monkeypatch, world):
    monkeypatch.setattr(search, "SyncEmbeddingClient", lambda: _QueryEmbedder(world))
    return admin_app_for(monkeypatch, world.db, world)


def test_the_route_returns_the_results_as_json(app):
    anchors = _filled(app.world)
    app.world.query_vector = _unit(anchors["search-basics"])
    app.login(1)

    response = app.client.post("/api/search/docs", json={"query": "חיפוש", "limit": 1})

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert [result["anchor"] for result in body["results"]] == ["search-basics"]
    assert (body["source_commit"], body["index_complete"]) == (SHA_A, True)


@pytest.mark.parametrize(
    "request_kwargs,status,error",
    [
        ({"data": "query=x", "content_type": "application/x-www-form-urlencoded"}, 415, "json_required"),
        ({"data": "[1]", "content_type": "application/json"}, 400, "invalid_json"),
        ({"json": {"query": ""}}, 400, "empty_query"),
        ({"json": {}}, 400, "invalid_query"),
    ],
)
def test_the_route_refuses_bad_input_with_json(app, request_kwargs, status, error):
    app.login(1)

    response = app.client.post("/api/search/docs", **request_kwargs)

    assert (response.status_code, response.get_json()["error"]) == (status, error)


def test_the_route_names_the_reason_when_there_is_no_index(app):
    app.login(1)

    response = app.client.post("/api/search/docs", json={"query": "חיפוש"})

    assert response.status_code == 503
    assert response.get_json() == {"ok": False, "error": "index_unavailable", "reason": "not_indexed"}


def test_the_route_answers_json_when_the_database_fails(app):
    _filled(app.world)
    app.world.atlas.aggregate_error = ServerSelectionTimeoutError("no primary available")
    app.login(1)

    response = app.client.post("/api/search/docs", json={"query": "חיפוש"})

    assert (response.status_code, response.get_json()["error"]) == (503, "database_unavailable")


def test_the_route_answers_503_without_a_database(app, monkeypatch):
    monkeypatch.setattr(app.wa, "get_db", lambda: None)
    app.login(1)

    response = app.client.post("/api/search/docs", json={"query": "חיפוש"})

    assert (response.status_code, response.get_json()["error"]) == (503, "database_unavailable")
