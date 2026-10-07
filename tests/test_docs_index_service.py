"""מעבר האינדוקס של התיעוד (``services/docs_index_service.py``): רשומות, תוכנית, מעבר, ו-lease.

מול דמה של מונגו (``_fake_mongo.FakeDB``), אתר מדומה ומטמיע מדומה (``_docs_index_harness``).
הקובץ עובר דרך ``fetch_export`` ו-``parse_export`` האמיתיים. ה-lease נבדק כאן גם עם threads (הדמה
מחזיקה מנעול על כל עדכון, כמו האטומיות של מסמך אחד במונגו), ושוב מול מונגו אמיתי ב-
``test_docs_index_mongo.py``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import threading
from datetime import datetime, timedelta, timezone

import pytest
from pymongo.errors import ServerSelectionTimeoutError

# ‏``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _docs_index_harness import (
    DIMENSIONS,
    EARLY,
    LATE,
    LATER,
    MODEL,
    MODEL_KEY,
    SHA_A,
    SHA_B,
    SHA_C,
    export_bytes,
    fill,
    make_world,
    page,
    run_request,
    section,
    site_pages,
)
from _fake_mongo import FakeCollection, FakeDB

from services import docs_index_service as svc
from services import docs_search_contract as contract
from services.chunking_service import CHUNK_MAX_BYTES
from services.docs_export_client import EXPORT_NOT_FOUND, EXPORT_STALE, parse_export


@pytest.fixture
def world(monkeypatch):
    return make_world(monkeypatch, FakeDB())


def _chunks(world):
    return list(world.db[contract.CHUNKS_COLLECTION].find({}))


def _sections(world):
    return list(world.db[contract.SECTIONS_COLLECTION].find({}))


def _state(world):
    return svc.read_state(world.db)


def _event_names(world):
    return [name for name, _severity, _fields in world.events]


def _request(trigger=svc.TRIGGER_MANUAL_CHECK, commit=None, fingerprint=None):
    return {
        "trigger": trigger,
        "commit": commit,
        "approved_fingerprint": fingerprint,
        "requested_by": None,
        "requested_at": datetime.now(timezone.utc),
    }


def _records(pages, commit=SHA_A):
    return svc.build_records(parse_export(export_bytes(commit, pages)))


# ---------------------------------------------------------------------------
# סעיפים ונתחים
# ---------------------------------------------------------------------------


def test_a_section_that_fits_is_one_chunk_led_by_its_breadcrumb():
    sections, chunks = _records(site_pages())

    assert [s.title for s in sections] == ["חיפוש גלובלי", "סוגי החיפוש", "קטלוג אירועים", "אינדקס התיעוד"]
    types = sections[1]
    [chunk] = [c for c in chunks if c.section_id == types.id]
    assert chunk.text == "חיפוש גלובלי › סוגי החיפוש\n\n| סוג | מה |\n| --- | --- |\n| תוכן | טקסט |"
    assert chunk.part == 0
    assert chunk.content_sha == hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
    assert (types.page_path, types.source_path, types.page_title, types.anchor) == (
        "webapp/global-search.html", "docs/webapp/global-search.rst", "חיפוש גלובלי", "global-search-types",
    )


def test_a_long_section_is_split_within_the_byte_budget_breadcrumb_included():
    body = "\n".join(f"שורה {n}: " + "מילה " * 30 for n in range(200))
    sections, chunks = _records([page("a.html", "docs/a.rst", section("a", "עמוד", "סעיף ארוך", markdown=body))])

    prefix = "עמוד › סעיף ארוך\n\n"
    assert len(sections) == 1 and len(chunks) > 1
    assert all(c.text.startswith(prefix) for c in chunks)
    assert max(len(c.text.encode("utf-8")) for c in chunks) <= CHUNK_MAX_BYTES
    assert [c.part for c in chunks] == list(range(len(chunks)))
    covered = "\n".join(c.text[len(prefix):] for c in chunks)
    assert all(f"שורה {n}:" in covered for n in range(200))


def test_a_budget_smaller_than_the_breadcrumb_is_a_configuration_error(monkeypatch):
    monkeypatch.setattr(svc, "CHUNK_MAX_BYTES", 10)
    with pytest.raises(ValueError, match="no room for a body"):
        _records([page("a.html", "docs/a.rst", section("a", "עמוד", "סעיף", markdown="טקסט " * 10))])


@pytest.mark.parametrize(
    "markdown",
    [
        "- [אינדקסים](https://amirbiron.github.io/CodeBot/database/indexing.html)",
        "* [א](https://x.example/a) — הסבר קצר\n* [ב](https://x.example/b)",
        "1. [א](a.html)\n2. [ב](b.html).",
        "https://github.com/amirbiron/CodeBot",
        "::: seealso\n- [א](a.html)\n:::",
    ],
)
def test_a_list_of_links_is_links_only(markdown):
    assert svc.is_links_only(markdown) is True


@pytest.mark.parametrize(
    "markdown",
    ["", "טקסט רגיל.", "- [א](a.html) ועוד מילים", "ראו [א](a.html) בהמשך", "::: note\n:::", "- [א](a.html)\nטקסט"],
)
def test_text_is_not_links_only(markdown):
    assert svc.is_links_only(markdown) is False


@pytest.mark.parametrize("markdown", ["", "\n\n", "::: note\n:::", "- [א](a.html)"])
def test_an_empty_or_links_only_section_is_not_indexed(markdown):
    sections, chunks = _records(
        [page("a.html", "docs/a.rst", section("a", "עמוד"), section("b", "עמוד", "ריק", markdown=markdown))]
    )
    assert [s.title for s in sections] == ["עמוד"]
    assert len(chunks) == 1


def test_a_repeated_breadcrumb_gets_its_own_key():
    sections, chunks = _records(
        [
            page("a.html", "docs/a.rst", section("a", "עמוד"), section("id1", "עמוד", "דוגמה"),
                 section("id2", "עמוד", "דוגמה", markdown="דוגמה שנייה.")),
            page("b.html", "docs/b.rst", section("b", "עמוד"), section("id1", "עמוד", "דוגמה")),
        ]
    )
    assert len({s.id for s in sections}) == len(sections) == 5
    assert len({c.id for c in chunks}) == len(chunks) == 5


def test_the_keys_do_not_depend_on_the_anchor():
    moved = site_pages()
    moved[1]["sections"][1]["anchor"] = "id7"
    before_sections, before_chunks = _records(site_pages())
    after_sections, after_chunks = _records(moved)

    assert [s.id for s in after_sections] == [s.id for s in before_sections]
    assert [(c.id, c.content_sha) for c in after_chunks] == [(c.id, c.content_sha) for c in before_chunks]
    changed = [a for a, b in zip(after_sections, before_sections) if a.record_sha != b.record_sha]
    assert [s.anchor for s in changed] == ["id7"]


def test_the_section_sha_covers_every_field_the_card_shows():
    """שדה שנוסף ל-``content`` ולא נכנס ל-sha היה משאיר במסד ערך ישן בלי שאיש יעדכן אותו."""
    [record, *_] = _records(site_pages())[0]
    for field in record.content():
        value = getattr(record, field)
        if isinstance(value, tuple):
            changed = value + ("x",)
        elif isinstance(value, int):
            changed = value + 1
        else:
            changed = value + "x"
        assert dataclasses.replace(record, **{field: changed}).record_sha != record.record_sha, field
    assert set(record.document()) == {"_id", "record_sha", *record.content()}


# ---------------------------------------------------------------------------
# מילוי ראשון ואישור
# ---------------------------------------------------------------------------


def test_a_first_fill_waits_for_approval_and_changes_nothing(world):
    world.site.publish(SHA_A, site_pages())
    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)

    assert (run["status"], run["code"]) == (svc.STATUS_AWAITING_APPROVAL, svc.APPROVAL_FIRST_FILL)
    approval = _state(world)["approval"]
    assert approval["source_commit"] == SHA_A
    assert svc.is_fingerprint(approval["fingerprint"])
    assert (approval["plan"]["chunks_to_embed"], approval["plan"]["embed_requests"]) == (4, 1)
    assert world.embed_calls == [] and _chunks(world) == [] and _sections(world) == []
    assert _state(world).get("indexed_source_commit") is None
    assert _event_names(world) == ["docs_index_awaiting_approval", "docs_index_pass"]
    assert world.site.paths() == [contract.export_path_for_commit(SHA_A)]


def test_an_approved_first_fill_indexes_everything_and_records_the_commit(world):
    fill(world, requested_by=7)

    state = _state(world)
    assert (state["indexed_source_commit"], state["indexed_model_key"]) == (SHA_A, MODEL_KEY)
    assert state["approval"] is None and state["pending"] is None
    chunks = _chunks(world)
    assert len(chunks) == 4
    assert {c[contract.MODEL_KEY_FIELD] for c in chunks} == {MODEL_KEY}
    assert {(c["embeddingModel"], c["embeddingApiVersion"], c["embeddingDim"]) for c in chunks} == {
        (MODEL, "v1beta", DIMENSIONS)
    }
    assert all(len(c[contract.VECTOR_FIELD]) == DIMENSIONS for c in chunks)
    assert len(_sections(world)) == 4
    assert (state["chunk_count"], state["section_count"]) == (4, 4)
    assert state["run"]["verified"]["complete"] is True
    assert [len(call["texts"]) for call in world.embed_calls] == [4]
    # המעבר המאושר קרא את הקובץ של התוכנית שאושרה, ולא את הקובץ הראשי.
    assert world.site.paths()[-1] == contract.export_path_for_commit(SHA_A)
    [complete] = [fields for name, _s, fields in world.events if name == "docs_index_pass"][-1:]
    assert (complete["status"], complete["embedded"], complete["chunk_count"], complete["user_id"]) == (
        svc.STATUS_COMPLETE, 4, 4, 7
    )


def test_the_state_timestamps_carry_a_timezone(world):
    fill(world)
    state = _state(world)
    for field in ("updated_at", "indexed_at", "indexed_built_at", "applied_built_at", "created_at"):
        assert state[field].utcoffset() is not None, field


def test_a_second_pass_on_the_same_export_sends_nothing(world):
    fill(world)
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)

    assert (run["status"], run["code"]) == (svc.STATUS_UNCHANGED, None)
    assert world.embed_calls == []


def test_the_main_file_is_not_downloaded_again_when_it_did_not_change(world):
    fill(world)
    # ה-ETag הוא של הכתובת שממנה הגיע: אחרי מעבר לפי קומיט אין עדיין ETag של הקובץ הראשי.
    assert _state(world)["export_etag"] is None
    first = run_request(world, svc.TRIGGER_PUSH)
    assert first["status"] == svc.STATUS_UNCHANGED
    assert _state(world)["export_etag"]

    second = run_request(world, svc.TRIGGER_PUSH)

    assert (second["status"], second["detail"]) == (
        svc.STATUS_UNCHANGED, "the export did not change since the last pass"
    )
    assert world.site.requests[-1].headers.get("If-None-Match")
    assert "export" not in second


def test_the_dry_run_plan_writes_nothing_and_can_be_approved(world):
    world.site.publish(SHA_A, site_pages())

    summary = svc.plan_for_admin(world.db)

    assert (summary["chunks_to_embed"], summary["approval_reason"]) == (4, svc.APPROVAL_FIRST_FILL)
    assert svc.read_state(world.db) is None and _chunks(world) == [] and world.embed_calls == []
    run = run_request(world, svc.TRIGGER_APPROVED, approved_fingerprint=summary["fingerprint"])
    assert run["status"] == svc.STATUS_COMPLETE
    assert _state(world)["indexed_source_commit"] == SHA_A


def test_an_approved_deployment_plan_reads_its_commit_file_again(world):
    """הקובץ הראשי זז מאז, אבל התוכנית שאושרה חושבה מהעותק של הקומיט — והוא מה שנקרא שוב."""
    world.site.publish(SHA_A, site_pages())
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)
    fingerprint = _state(world)["approval"]["fingerprint"]
    moved_on = site_pages()
    moved_on[0]["sections"][0]["markdown"] = "גרסה חדשה יותר."
    world.site.publish(SHA_B, moved_on)

    run = run_request(world, svc.TRIGGER_APPROVED, approved_fingerprint=fingerprint)

    assert run["status"] == svc.STATUS_COMPLETE
    assert world.site.paths()[-1] == contract.export_path_for_commit(SHA_A)
    assert _state(world)["indexed_source_commit"] == SHA_A


def test_an_approved_main_file_plan_reads_the_main_file_again(world):
    """תוכנית של "בדוק עכשיו" או של רשת הביטחון חושבה מהקובץ הראשי, ואין בהכרח עותק לפי קומיט:
    הוא קיים רק בפריסה שכתבה אותו. נמצא באימות מול האתר החי (7.10.2026): לפני התיקון, המעבר המאושר
    ביקש את העותק לפי הקומיט ונכשל ב-``export_not_found``."""
    world.site.publish(SHA_A, site_pages(), commit_copy=False)
    run_request(world, svc.TRIGGER_MANUAL_CHECK)
    approval = _state(world)["approval"]
    assert approval["by_commit"] is False

    run = run_request(world, svc.TRIGGER_APPROVED, approved_fingerprint=approval["fingerprint"])

    assert run["status"] == svc.STATUS_COMPLETE, run
    assert world.site.paths()[-1] == contract.EXPORT_PATH
    assert _state(world)["indexed_source_commit"] == SHA_A


def test_an_approval_of_a_plan_that_changed_waits_again(world):
    world.site.publish(SHA_A, site_pages())
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)
    outdated = _state(world)["approval"]["fingerprint"]
    newer = site_pages()
    newer[0]["sections"][0]["markdown"] = "טקסט חדש."
    world.site.publish(SHA_B, newer)
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    run = run_request(world, svc.TRIGGER_APPROVED, approved_fingerprint=outdated)

    assert (run["status"], run["code"]) == (svc.STATUS_AWAITING_APPROVAL, svc.CODE_APPROVAL_MISMATCH)
    assert world.embed_calls == [] and _chunks(world) == []
    assert _state(world)["approval"]["fingerprint"] == run["plan"]["fingerprint"] != outdated


def test_an_approved_plan_that_changed_into_a_small_one_runs(world, monkeypatch):
    fill(world)
    monkeypatch.setattr(svc, "APPROVAL_THRESHOLD_CHUNKS", 1)
    big = site_pages()
    big[0]["sections"][0]["markdown"] = "שינוי ראשון."
    big[1]["sections"][0]["markdown"] = "שינוי שני."
    world.site.publish(SHA_B, big)
    dry = svc.plan_for_admin(world.db)
    assert dry["approval_reason"] == svc.APPROVAL_OVER_THRESHOLD
    small = site_pages()
    small[0]["sections"][0]["markdown"] = "שינוי ראשון."
    world.site.publish(SHA_C, small)

    run = run_request(world, svc.TRIGGER_APPROVED, approved_fingerprint=dry["fingerprint"])

    assert run["status"] == svc.STATUS_COMPLETE
    assert _state(world)["indexed_source_commit"] == SHA_C


def test_over_the_threshold_an_automatic_pass_waits(world, monkeypatch):
    fill(world)
    monkeypatch.setattr(svc, "APPROVAL_THRESHOLD_CHUNKS", 1)
    pages = site_pages()
    pages[0]["sections"][0]["markdown"] = "שינוי ראשון."
    pages[1]["sections"][0]["markdown"] = "שינוי שני."
    world.site.publish(SHA_B, pages)
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_AWAITING_APPROVAL, svc.APPROVAL_OVER_THRESHOLD)
    assert world.embed_calls == []
    assert _state(world)["indexed_source_commit"] == SHA_A
    assert _state(world)["approval"]["plan"]["chunks_to_embed"] == 2


def test_a_model_change_waits_for_approval_and_then_reembeds_everything(world):
    fill(world)
    world.db["system_config"].update_one({"_id": "semantic_embedding"}, {"$set": {"dimensions": 8}})
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)

    assert (run["status"], run["code"]) == (svc.STATUS_AWAITING_APPROVAL, svc.APPROVAL_FIRST_FILL)
    assert (run["plan"]["model_key"], run["plan"]["chunks_to_embed"]) == (f"{MODEL}/8", 4)
    assert world.embed_calls == []
    done = run_request(
        world, svc.TRIGGER_APPROVED, approved_fingerprint=_state(world)["approval"]["fingerprint"]
    )
    assert done["status"] == svc.STATUS_COMPLETE
    assert {len(c[contract.VECTOR_FIELD]) for c in _chunks(world)} == {8}
    assert {c[contract.MODEL_KEY_FIELD] for c in _chunks(world)} == {f"{MODEL}/8"}
    assert _state(world)["indexed_model_key"] == f"{MODEL}/8"


# ---------------------------------------------------------------------------
# מה שהשתנה
# ---------------------------------------------------------------------------


def test_only_what_changed_is_embedded_and_what_was_removed_is_deleted(world):
    fill(world)
    before = {c["_id"]: c for c in _chunks(world)}
    pages = site_pages()
    pages[0]["sections"][1]["markdown"] = "| סוג | מה |\n| --- | --- |\n| שם | שם הקובץ |"
    removed_title = pages[1]["sections"].pop(1)["title"]
    pages[1]["sections"].append(section("id9", "קטלוג אירועים", "אירוע חדש", markdown="``docs_index_failed``."))
    world.site.publish(SHA_B, pages)
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert run["status"] == svc.STATUS_COMPLETE, run
    [call] = world.embed_calls
    assert sorted(text.split("\n\n")[0] for text in call["texts"]) == [
        "חיפוש גלובלי › סוגי החיפוש", "קטלוג אירועים › אירוע חדש"
    ]
    assert run["deleted"] == {"chunks": 1, "sections": 1}
    after = {c["_id"]: c for c in _chunks(world)}
    assert len(after) == 4 and len(set(before) & set(after)) == 3
    assert removed_title not in {s["title"] for s in _sections(world)}
    assert _state(world)["indexed_source_commit"] == SHA_B


def _long_section_pages(lines: int):
    body = "\n".join(f"שורה {n}: " + "מילה " * 30 for n in range(lines))
    return [page("a.html", "docs/a.rst", section("a", "עמוד", "סעיף ארוך", markdown=body))]


def _stored_chunks(world):
    """מסמכי הנתחים בלי מה שמשתנה בכל כתיבה: הווקטור (המטמיע המדומה תלוי במקום באצווה) והחותמת."""
    volatile = {contract.VECTOR_FIELD, "updated_at"}
    return {c["_id"]: {k: v for k, v in c.items() if k not in volatile} for c in _chunks(world)}


def test_a_section_that_grows_leaves_the_chunks_a_fresh_fill_would_store(world, monkeypatch):
    """מעבר שמאריך סעיף לא כותב מחדש את הנתחים שלא השתנו, ולכן אסור שיישמר בהם שדה שתלוי בסעיף
    כולו (כמו כמה חלקים יש לו). ההשוואה היא למה שמילוי מאפס של אותו קובץ כותב."""
    fill(world, pages=_long_section_pages(40))
    world.site.publish(SHA_B, _long_section_pages(60))

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert run["status"] == svc.STATUS_COMPLETE, run
    assert 0 < run["plan"]["chunks_to_embed"] < len(_chunks(world)), "some chunks must stay as they were"
    incremental = _stored_chunks(world)

    fresh = make_world(monkeypatch, FakeDB())
    fill(fresh, pages=_long_section_pages(60), commit=SHA_B)
    assert incremental == _stored_chunks(fresh)


def test_an_anchor_change_updates_the_card_without_embedding(world):
    fill(world)
    pages = site_pages()
    pages[1]["sections"][1]["anchor"] = "id7"
    world.site.publish(SHA_B, pages)
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert run["status"] == svc.STATUS_COMPLETE
    assert world.embed_calls == []
    assert (run["plan"]["sections_to_upsert"], run["plan"]["chunks_to_embed"]) == (1, 0)
    assert {s["anchor"] for s in _sections(world)} >= {"id7"}
    assert "id3" not in {s["anchor"] for s in _sections(world)}


def test_an_export_that_knows_nothing_indexed_deletes_nothing_and_warns(world, caplog):
    fill(world)
    caplog.set_level(logging.WARNING, logger=svc.logger.name)
    others = [page("other/page.html", "docs/other/page.rst", section("other", "עמוד אחר", markdown="תוכן אחר."))]
    world.site.publish(SHA_B, others)

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert run["plan"]["deletions_spared"] == 8
    assert run["deleted"] == {"chunks": 0, "sections": 0}
    assert len(_chunks(world)) == 5 and len(_sections(world)) == 5
    assert "spared 8 deletions" in caplog.text


def test_an_older_export_does_not_roll_the_index_back(world):
    fill(world, built_at=LATE)
    older = site_pages()
    older[0]["sections"][0]["markdown"] = "גרסה ישנה."
    world.site.publish(SHA_B, older, built_at=EARLY)
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_UNCHANGED, svc.CODE_OLDER_EXPORT)
    assert world.embed_calls == []
    assert (_state(world)["indexed_source_commit"], _state(world)["export_commit"]) == (SHA_A, SHA_A)
    world.site.publish(SHA_C, older, built_at=LATER)
    assert run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_C)["status"] == svc.STATUS_COMPLETE
    assert _state(world)["indexed_source_commit"] == SHA_C


def test_a_timestamp_stored_without_a_timezone_is_read_as_utc(world):
    """לקוח מונגו שלא הוגדר ``tz_aware`` מחזיר חותמת נאיבית; ההשוואה לא נופלת עליה."""
    fill(world, built_at=LATE)
    naive = datetime.fromisoformat(LATE).replace(tzinfo=None)
    world.db[contract.STATE_COLLECTION].update_one({"_id": svc.STATE_ID}, {"$set": {"applied_built_at": naive}})
    world.site.publish(SHA_B, site_pages(), built_at=EARLY)

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_UNCHANGED, svc.CODE_OLDER_EXPORT)


# ---------------------------------------------------------------------------
# כשלים — כל אחד בשמו, ואינדקס חלקי אינו נרשם כשלם
# ---------------------------------------------------------------------------


def _approved_pass(world):
    """מעבר מאושר של מילוי ראשון, אחרי שמעבר הפריסה עצר לאישור."""
    world.site.publish(SHA_A, site_pages())
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)
    world.events.clear()
    return run_request(
        world, svc.TRIGGER_APPROVED, approved_fingerprint=_state(world)["approval"]["fingerprint"]
    )


def test_quota_pauses_the_pass_and_a_later_pass_finishes_it(world, monkeypatch):
    monkeypatch.setattr(svc, "GEMINI_MAX_BATCH_REQUESTS", 2)
    world.embed_failures[1] = (429, "http 429: RESOURCE_EXHAUSTED: quota")

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_PAUSED_QUOTA, svc.CODE_EMBEDDING_QUOTA)
    assert run["progress"] == {"embedded": 2, "to_embed": 4}
    assert len(_chunks(world)) == 2
    assert _state(world)["indexed_source_commit"] is None
    assert _event_names(world) == ["docs_index_quota_paused", "docs_index_pass"]

    world.embed_failures.clear()
    world.embed_calls.clear()
    done = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)
    assert done["status"] == svc.STATUS_COMPLETE
    assert sum(len(call["texts"]) for call in world.embed_calls) == 2
    assert _state(world)["indexed_source_commit"] == SHA_A


@pytest.mark.parametrize(
    "status,detail,code",
    [
        (400, "http 400: INVALID_ARGUMENT: bad request", svc.CODE_EMBEDDING_REJECTED),
        (413, "input_too_long index=0 bytes=40000 max=30000", svc.CODE_EMBEDDING_REJECTED),
        (404, "http 404: NOT_FOUND: no such model", svc.CODE_EMBEDDING_MODEL_MISSING),
        (422, "dimension_mismatch expected=4 actual=768", svc.CODE_EMBEDDING_DIMENSION_MISMATCH),
        (0, "deadline_exceeded", svc.CODE_DEADLINE_EXCEEDED),
        (0, "missing_api_key", svc.CODE_MISSING_API_KEY),
        (0, "transport_error: ConnectError", svc.CODE_EMBEDDING_UNAVAILABLE),
        (503, "http 503: UNAVAILABLE: overloaded", svc.CODE_EMBEDDING_UNAVAILABLE),
        (403, "http 403: PERMISSION_DENIED: key", svc.CODE_EMBEDDING_UNAVAILABLE),
        (200, "malformed_response: expected 4 embeddings", svc.CODE_EMBEDDING_UNKNOWN_STATUS),
        (422, "http 422: something else", svc.CODE_EMBEDDING_UNKNOWN_STATUS),
        (418, "http 418: teapot", svc.CODE_EMBEDDING_UNKNOWN_STATUS),
    ],
)
def test_an_embedding_failure_stops_the_pass_by_name(world, status, detail, code):
    world.embed_failures[0] = (status, detail)

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, code)
    assert detail in run["detail"]
    assert _chunks(world) == []
    assert _state(world)["indexed_source_commit"] is None
    assert _event_names(world) == ["docs_index_failed", "docs_index_pass"]


def test_a_missing_api_key_stops_before_anything_is_written(world):
    world.api_key = False

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_MISSING_API_KEY)
    assert world.embed_calls == [] and _chunks(world) == [] and _sections(world) == []
    assert "applied_built_at" not in _state(world)


def test_a_stop_request_stops_the_pass_before_the_next_batch(world, monkeypatch):
    monkeypatch.setattr(svc, "GEMINI_MAX_BATCH_REQUESTS", 2)
    world.on_embed[0] = lambda: svc.request_stop(world.db)

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_STOPPED, None)
    assert len(world.embed_calls) == 1 and len(_chunks(world)) == 2
    assert _state(world)["indexed_source_commit"] is None
    # העצירה חלה על המעבר ההוא בלבד: המעבר הבא רץ עד הסוף.
    assert run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)["status"] == svc.STATUS_COMPLETE


def test_the_deadline_stops_the_pass_between_batches(world, monkeypatch):
    monkeypatch.setattr(svc, "GEMINI_MAX_BATCH_REQUESTS", 2)
    world.on_embed[0] = lambda: world.clock.__setitem__(0, svc.PASS_DEADLINE_SECONDS + 1.0)

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_DEADLINE_EXCEEDED)
    assert len(world.embed_calls) == 1 and len(_chunks(world)) == 2
    assert _state(world)["indexed_source_commit"] is None


def _after_the_first_call(monkeypatch, collection, method, action):
    """עוטף מתודה של אוסף בדמה: אחרי הקריאה הראשונה רץ ``action`` (עצירה, שעון). מחזיר את מספר הקריאות."""
    original = getattr(collection, method)
    calls = []

    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(method)
        if len(calls) == 1:
            action()
        return result

    monkeypatch.setattr(collection, method, wrapper)
    return calls


def _every_anchor_moved():
    pages = site_pages()
    for item in pages:
        for entry in item["sections"]:
            entry["anchor"] += "-moved"
    return pages


def test_a_stop_between_section_writes_stops_a_pass_with_nothing_to_embed(world, monkeypatch):
    """עצירה היא גם בלם, ולא רק חיסכון בהטמעות: מעבר שכולו כתיבות למסד נעצר לפני האצווה הבאה."""
    fill(world)
    monkeypatch.setattr(svc, "DB_BATCH_SIZE", 1)
    world.site.publish(SHA_B, _every_anchor_moved())
    world.embed_calls.clear()
    sections = world.db[contract.SECTIONS_COLLECTION]
    calls = _after_the_first_call(monkeypatch, sections, "bulk_write", lambda: svc.request_stop(world.db))

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_STOPPED, None)
    assert (run["plan"]["chunks_to_embed"], run["plan"]["sections_to_upsert"]) == (0, 4)
    assert len(calls) == 1 and world.embed_calls == []
    assert sum(s["anchor"].endswith("-moved") for s in _sections(world)) == 1
    assert _state(world)["indexed_source_commit"] is None


def test_a_stop_between_deletions_stops_them_and_reports_what_was_deleted(world, monkeypatch):
    fill(world)
    monkeypatch.setattr(svc, "DB_BATCH_SIZE", 1)
    world.site.publish(SHA_B, site_pages()[:1])
    chunks = world.db[contract.CHUNKS_COLLECTION]
    _after_the_first_call(monkeypatch, chunks, "delete_many", lambda: svc.request_stop(world.db))

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_STOPPED, None)
    assert (run["plan"]["chunks_to_delete"], run["plan"]["sections_to_delete"]) == (2, 2)
    assert run["deleted"] == {"chunks": 1, "sections": 0}
    assert (len(_chunks(world)), len(_sections(world))) == (3, 4)
    assert _state(world)["indexed_source_commit"] is None


def test_the_deadline_is_checked_between_database_batches_too(world, monkeypatch):
    fill(world)
    monkeypatch.setattr(svc, "DB_BATCH_SIZE", 1)
    world.site.publish(SHA_B, _every_anchor_moved())
    sections = world.db[contract.SECTIONS_COLLECTION]
    _after_the_first_call(
        monkeypatch, sections, "bulk_write",
        lambda: world.clock.__setitem__(0, svc.PASS_DEADLINE_SECONDS + 1.0),
    )

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_DEADLINE_EXCEEDED)
    assert sum(s["anchor"].endswith("-moved") for s in _sections(world)) == 1


def test_a_pass_that_lost_its_lease_writes_nothing_more(world, monkeypatch):
    monkeypatch.setattr(svc, "GEMINI_MAX_BATCH_REQUESTS", 2)
    world.site.publish(SHA_A, site_pages())
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)
    fingerprint = _state(world)["approval"]["fingerprint"]
    world.on_embed[0] = lambda: world.db[contract.STATE_COLLECTION].update_one(
        {"_id": svc.STATE_ID}, {"$set": {"lease_holder": "another-runner"}}
    )
    world.events.clear()

    assert svc.request_pass(
        world.db, trigger=svc.TRIGGER_APPROVED, approved_fingerprint=fingerprint
    ) == svc.REQUEST_STARTED

    state = _state(world)
    assert state["lease_holder"] == "another-runner"
    assert state["run"]["status"] == svc.STATUS_RUNNING
    assert len(_chunks(world)) == 2
    assert [(name, fields.get("code")) for name, _s, fields in world.events] == [
        ("docs_index_failed", svc.CODE_LEASE_LOST)
    ]


class _DropsTheLastWrite(FakeCollection):
    def bulk_write(self, requests, ordered=True, **kwargs):
        return super().bulk_write(list(requests)[:-1], ordered=ordered)


class _LosesADocumentAfterWriting(FakeCollection):
    def bulk_write(self, requests, ordered=True, **kwargs):
        result = super().bulk_write(requests, ordered=ordered)
        self.docs.pop()
        return result


def test_a_pass_that_stops_half_way_leaves_the_index_marked_partial(world, monkeypatch):
    """מרגע הכתיבה הראשונה המסד אינו תואם לקומיט הקודם, ולכן הוא לא נשאר רשום כשלם."""
    fill(world)
    monkeypatch.setattr(svc, "GEMINI_MAX_BATCH_REQUESTS", 1)
    pages = site_pages()
    pages[0]["sections"][0]["markdown"] = "שינוי ראשון."
    pages[1]["sections"][0]["markdown"] = "שינוי שני."
    world.site.publish(SHA_B, pages)
    world.embed_failures[len(world.embed_calls) + 1] = (429, "http 429: RESOURCE_EXHAUSTED: quota")

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert run["status"] == svc.STATUS_PAUSED_QUOTA
    state = _state(world)
    assert state["indexed_source_commit"] is None
    assert state["applied_built_at"] == datetime.fromisoformat(LATE)


def test_the_lease_is_renewed_before_every_batch(world, monkeypatch):
    """גם lease שכבר פג — המעבר איטי, אבל איש לא לקח אותו — מתחדש אצל מי שמחזיק בו."""
    monkeypatch.setattr(svc, "GEMINI_MAX_BATCH_REQUESTS", 2)
    seen = []

    def expire_the_lease():
        world.db[contract.STATE_COLLECTION].update_one(
            {"_id": svc.STATE_ID}, {"$set": {"lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}}
        )

    world.on_embed[0] = expire_the_lease
    world.on_embed[1] = lambda: seen.append(_state(world)["lease_expires_at"])

    run = _approved_pass(world)

    assert run["status"] == svc.STATUS_COMPLETE
    assert seen and seen[0] > datetime.now(timezone.utc) + timedelta(seconds=svc.LEASE_SECONDS - 60)


def test_a_write_that_touches_fewer_documents_fails_the_pass(world):
    world.db.c[contract.CHUNKS_COLLECTION] = _DropsTheLastWrite()

    run = _approved_pass(world)

    assert (run["status"], run["code"], run["detail"]) == (
        svc.STATUS_FAILED, svc.CODE_WRITE_MISMATCH, "chunks: wrote 3 of 4"
    )
    assert _state(world)["indexed_source_commit"] is None


def test_a_verification_that_reads_back_less_fails_the_pass(world):
    world.db.c[contract.CHUNKS_COLLECTION] = _LosesADocumentAfterWriting()

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_VERIFY_MISMATCH)
    assert run["detail"] == "3 of 4 chunks and 4 of 4 sections match the export"
    assert _state(world)["indexed_source_commit"] is None


def test_a_section_missing_on_read_back_fails_the_pass_too(world):
    """הכרטיס בחיפוש נבנה מהסעיף: נתח בלי הסעיף שלו הוא תוצאה שבורה, ולכן גם הסעיפים מאומתים."""
    world.db.c[contract.SECTIONS_COLLECTION] = _LosesADocumentAfterWriting()

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_VERIFY_MISMATCH)
    assert run["detail"] == "4 of 4 chunks and 3 of 4 sections match the export"


class _Unreachable(FakeCollection):
    def find(self, *args, **kwargs):
        raise ServerSelectionTimeoutError("no primary available")

    def find_one(self, *args, **kwargs):
        raise ServerSelectionTimeoutError("no primary available")


def test_a_database_error_while_planning_is_named_and_deletes_nothing(world):
    world.db.c[contract.CHUNKS_COLLECTION] = _Unreachable()
    world.site.publish(SHA_A, site_pages())

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)

    assert (run["status"], run["code"], run["detail"]) == (
        svc.STATUS_FAILED, svc.CODE_DATABASE_ERROR, "ServerSelectionTimeoutError"
    )


def test_unreadable_settings_fail_the_pass_before_any_download(world):
    world.db.c["system_config"] = _Unreachable()

    run = run_request(world, svc.TRIGGER_PUSH)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_SETTINGS_UNAVAILABLE)
    assert world.site.requests == []


def test_a_missing_commit_file_fails_without_reading_the_main_file(world):
    fill(world)
    world.site.publish(SHA_B, site_pages(), main=True)
    del world.site.files[contract.export_path_for_commit(SHA_B)]

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, EXPORT_NOT_FOUND)
    assert world.site.paths()[-1] == contract.export_path_for_commit(SHA_B)
    assert _state(world)["indexed_source_commit"] == SHA_A


def test_a_commit_file_from_another_commit_is_stale_and_changes_nothing(world):
    fill(world)
    world.site.files[contract.export_path_for_commit(SHA_B)] = export_bytes(SHA_C, site_pages())

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, EXPORT_STALE)
    assert _state(world)["indexed_source_commit"] == SHA_A


def test_a_request_read_back_in_a_shape_it_was_never_written_in_is_refused(world):
    svc._put_pending(world.db, _request())
    assert svc._take_lease(world.db, "runner")

    run = svc.run_pass(world.db, holder="runner", request={"trigger": "nightly"})

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_INVALID_REQUEST)
    assert world.site.requests == []


def test_a_crash_inside_the_pass_is_recorded_without_its_message(world, caplog):
    def crash():
        raise RuntimeError("detail-that-stays-in-the-log")

    world.on_embed[0] = crash

    run = _approved_pass(world)

    assert (run["status"], run["code"], run["detail"]) == (svc.STATUS_FAILED, svc.CODE_UNEXPECTED, "RuntimeError")
    assert _state(world)["lease_holder"] is None
    assert [(name, fields.get("detail")) for name, _s, fields in world.events] == [
        ("docs_index_failed", "RuntimeError")
    ]
    assert "docs index pass crashed" in caplog.text


# ---------------------------------------------------------------------------
# ה-lease והתור
# ---------------------------------------------------------------------------


def test_a_request_while_a_pass_runs_waits_and_runs_after_it(world, monkeypatch):
    started = []
    monkeypatch.setattr(svc, "_runner_factory", started.append)
    world.site.publish(SHA_A, site_pages())

    assert svc.request_pass(world.db, trigger=svc.TRIGGER_PUSH) == svc.REQUEST_STARTED
    assert svc.request_pass(world.db, trigger=svc.TRIGGER_DEPLOY, commit=SHA_A) == svc.REQUEST_QUEUED
    assert len(started) == 1
    started[0]()

    state = _state(world)
    assert state["run"]["trigger"] == svc.TRIGGER_DEPLOY
    assert (state["pending"], state["lease_holder"]) == (None, None)


def test_a_request_that_arrives_just_before_the_release_is_not_lost(world, monkeypatch):
    real_release = svc._release
    raced = []

    def release_with_a_request_racing_in(db, holder):
        if not raced:
            raced.append(True)
            svc._put_pending(db, _request(svc.TRIGGER_DEPLOY, commit=SHA_A))
        return real_release(db, holder)

    monkeypatch.setattr(svc, "_release", release_with_a_request_racing_in)
    world.site.publish(SHA_A, site_pages())

    run = run_request(world, svc.TRIGGER_PUSH)

    assert run["trigger"] == svc.TRIGGER_DEPLOY
    assert _state(world)["pending"] is None


def test_one_of_many_concurrent_requests_takes_the_lease(world, monkeypatch):
    started = []
    lock = threading.Lock()

    def record(target):
        with lock:
            started.append(target)

    monkeypatch.setattr(svc, "_runner_factory", record)
    barrier = threading.Barrier(8)
    results = []

    def ask():
        barrier.wait()
        results.append(svc.request_pass(world.db, trigger=svc.TRIGGER_PUSH))

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(results) == [svc.REQUEST_QUEUED] * 7 + [svc.REQUEST_STARTED]
    assert len(started) == 1


def test_an_expired_lease_is_taken_over_and_a_live_one_is_not(world, monkeypatch):
    started = []
    monkeypatch.setattr(svc, "_runner_factory", started.append)
    now = datetime.now(timezone.utc)
    world.db[contract.STATE_COLLECTION].insert_one(
        {"_id": svc.STATE_ID, "lease_holder": "dead-runner", "lease_expires_at": now - timedelta(seconds=1),
         "pending": None, "stop_requested": False}
    )

    assert svc.request_pass(world.db, trigger=svc.TRIGGER_PUSH) == svc.REQUEST_STARTED
    assert _state(world)["lease_holder"] not in (None, "dead-runner")
    assert svc.request_pass(world.db, trigger=svc.TRIGGER_PUSH) == svc.REQUEST_QUEUED
    assert len(started) == 1


def test_a_runner_that_cannot_start_gives_the_lease_back_and_keeps_the_request(world, monkeypatch):
    def cannot_start(target):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(svc, "_runner_factory", cannot_start)

    with pytest.raises(RuntimeError):
        svc.request_pass(world.db, trigger=svc.TRIGGER_PUSH)

    state = _state(world)
    assert state["lease_holder"] is None
    assert state["lease_expires_at"] < datetime.now(timezone.utc)
    assert state["pending"]["trigger"] == svc.TRIGGER_PUSH


def test_a_runner_whose_lease_was_taken_over_stops_without_running(world):
    svc._put_pending(world.db, _request())
    assert svc._take_lease(world.db, "runner-a")
    world.db[contract.STATE_COLLECTION].update_one({"_id": svc.STATE_ID}, {"$set": {"lease_holder": "runner-b"}})

    svc._run_until_idle(world.db, "runner-a")

    state = _state(world)
    assert state["lease_holder"] == "runner-b"
    assert state["pending"]["trigger"] == svc.TRIGGER_MANUAL_CHECK
    assert "run" not in state


def test_a_stop_also_drops_the_request_waiting_behind_the_pass(world):
    svc._put_pending(world.db, _request())
    assert svc._take_lease(world.db, "runner")
    svc._put_pending(world.db, _request(svc.TRIGGER_DEPLOY, commit=SHA_A))

    assert svc.request_stop(world.db) is True

    state = _state(world)
    assert (state["stop_requested"], state["pending"]) == (True, None)
    assert svc._claim_next(world.db, "runner") is None
    assert svc._release(world.db, "runner") is True


def test_a_stop_without_a_live_pass_is_refused(world):
    assert svc.request_stop(world.db) is False
    fill(world)
    assert svc.request_stop(world.db) is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trigger": "nightly"},
        {"trigger": ["deploy"]},
        {"trigger": svc.TRIGGER_DEPLOY, "commit": "abc"},
        {"trigger": svc.TRIGGER_DEPLOY, "commit": SHA_A.upper()},
        {"trigger": svc.TRIGGER_APPROVED},
        {"trigger": svc.TRIGGER_MANUAL_CHECK, "approved_fingerprint": "a" * 64},
        {"trigger": svc.TRIGGER_APPROVED, "approved_fingerprint": "xyz"},
        {"trigger": svc.TRIGGER_APPROVED, "approved_fingerprint": "A" * 64},
        {"trigger": svc.TRIGGER_MANUAL_CHECK, "requested_by": True},
        {"trigger": svc.TRIGGER_MANUAL_CHECK, "requested_by": "7"},
    ],
)
def test_a_request_with_a_value_that_cannot_be_stored_is_refused(world, kwargs):
    with pytest.raises(ValueError):
        svc.request_pass(world.db, **kwargs)
    assert svc.read_state(world.db) is None


@pytest.mark.parametrize("value", ["a" * 64, "0123456789abcdef" * 4])
def test_fingerprints_in_the_grammar(value):
    assert svc.is_fingerprint(value) is True


@pytest.mark.parametrize("value", ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, None, 7, ["a" * 64]])
def test_fingerprints_outside_the_grammar(value):
    assert svc.is_fingerprint(value) is False
