"""הורדה ובדיקה של קובץ הייצוא של אתר התיעוד (``services/docs_export_client.py``).

הקובץ מגיע מחוץ לתהליך, ולכן כל צורה פגומה חייבת להיגמר ב-``ExportFetchError`` עם קוד סיבה —
לפני שמשהו נכתב. ההורדה נבדקת דרך ``httpx.MockTransport``: הבקשה כפי ש-httpx בנה אותה, והתשובה
כפי שהלקוח קורא אותה, כולל זרם בחתיכות לבדיקות התקרה והדדליין.
"""

from __future__ import annotations

import copy
import gzip
import json
import logging

import httpx
import pytest

from services import docs_export_client as client
from services import docs_search_contract as contract

SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "f" * 40


def _document(**overrides) -> dict:
    document = {
        "schema_version": contract.SCHEMA_VERSION,
        "source_commit": SHA,
        "built_at": "2026-10-07T13:43:42+00:00",
        "site_url": contract.SITE_URL,
        "page_count": 1,
        "section_count": 2,
        "pages": [
            {
                "path": "webapp/global-search.html",
                "source_path": "docs/webapp/global-search.rst",
                "title": "חיפוש גלובלי",
                "sections": [
                    {
                        "anchor": "webapp-global-search",
                        "title": "חיפוש גלובלי",
                        "breadcrumb": ["חיפוש גלובלי"],
                        "level": 1,
                        "markdown": "",
                    },
                    {
                        "anchor": "global-search-types",
                        "title": "סוגי החיפוש",
                        "breadcrumb": ["חיפוש גלובלי", "סוגי החיפוש"],
                        "level": 2,
                        "markdown": "| תווית | ערך |\n| --- | --- |",
                    },
                ],
            }
        ],
    }
    document.update(overrides)
    return document


def _bytes(document) -> bytes:
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def _section(document, index=1) -> dict:
    return document["pages"][0]["sections"][index]


# ---------------------------------------------------------------------------
# הבדיקה
# ---------------------------------------------------------------------------


def test_a_valid_file_becomes_a_document():
    parsed = client.parse_export(_bytes(_document()))

    assert parsed.source_commit == SHA
    assert parsed.section_count == 2
    [page] = parsed.pages
    assert (page.path, page.source_path, page.title) == (
        "webapp/global-search.html", "docs/webapp/global-search.rst", "חיפוש גלובלי",
    )
    assert page.sections[1].breadcrumb == ("חיפוש גלובלי", "סוגי החיפוש")
    assert page.sections[0].markdown == ""


def _broken(mutate):
    document = _document()
    mutate(document)
    return document


BROKEN = {
    "not an object": [],
    "schema is text": _broken(lambda d: d.update(schema_version="1")),
    "schema is a bool": _broken(lambda d: d.update(schema_version=True)),
    "commit is short": _broken(lambda d: d.update(source_commit="abc")),
    "commit is upper case": _broken(lambda d: d.update(source_commit=SHA.upper())),
    "built_at has no zone": _broken(lambda d: d.update(built_at="2026-10-07T13:43:42")),
    "built_at is not a time": _broken(lambda d: d.update(built_at="yesterday")),
    "site_url is not text": _broken(lambda d: d.update(site_url=["x"])),
    "no pages": _broken(lambda d: d.update(pages=[], page_count=0, section_count=0)),
    "page_count is wrong": _broken(lambda d: d.update(page_count=2)),
    "page_count is a bool": _broken(lambda d: d.update(page_count=True)),
    "section_count is wrong": _broken(lambda d: d.update(section_count=3)),
    "page is a list": _broken(lambda d: d["pages"].__setitem__(0, [])),
    "path climbs up": _broken(lambda d: d["pages"][0].update(path="../index.html")),
    "path is absolute": _broken(lambda d: d["pages"][0].update(path="/index.html")),
    "path is a url": _broken(lambda d: d["pages"][0].update(path="https://evil.example/x.html")),
    "path is too long": _broken(lambda d: d["pages"][0].update(path="a" * client.MAX_PATH_BYTES + ".html")),
    "source is not rst": _broken(lambda d: d["pages"][0].update(source_path="docs/x.html")),
    "page title is empty": _broken(lambda d: d["pages"][0].update(title="  ")),
    "no sections": _broken(lambda d: d["pages"][0].update(sections=[])),
    "anchor twice": _broken(lambda d: _section(d).update(anchor="webapp-global-search")),
    "anchor with a space": _broken(lambda d: _section(d).update(anchor="a b")),
    "anchor in Hebrew": _broken(lambda d: _section(d).update(anchor="סוגים")),
    "anchor is too long": _broken(lambda d: _section(d).update(anchor="a" * (client.MAX_ANCHOR_BYTES + 1))),
    "title is not text": _broken(lambda d: _section(d).update(title=7)),
    "title is too long": _broken(
        lambda d: _section(d).update(
            title="ש" * client.MAX_TITLE_BYTES,
            breadcrumb=["חיפוש גלובלי", "ש" * client.MAX_TITLE_BYTES],
        )
    ),
    "breadcrumb is text": _broken(lambda d: _section(d).update(breadcrumb="חיפוש גלובלי")),
    "breadcrumb ends elsewhere": _broken(lambda d: _section(d).update(breadcrumb=["חיפוש גלובלי", "אחר"])),
    "breadcrumb has an empty title": _broken(lambda d: _section(d).update(breadcrumb=["", "סוגי החיפוש"])),
    "breadcrumb is too long": _broken(
        lambda d: _section(d).update(
            breadcrumb=["א" * (client.MAX_TITLE_BYTES // 2)] * 6 + ["סוגי החיפוש"], level=7
        )
    ),
    "level is a bool": _broken(lambda d: _section(d, 0).update(level=True)),
    "level does not match": _broken(lambda d: _section(d).update(level=3)),
    "markdown is missing": _broken(lambda d: _section(d).pop("markdown")),
}


@pytest.mark.parametrize("name", sorted(BROKEN))
def test_a_malformed_file_is_refused_with_a_reason(name):
    with pytest.raises(client.ExportFetchError) as raised:
        client.parse_export(_bytes(BROKEN[name]))
    assert raised.value.code == client.EXPORT_INVALID


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: _section(d).update(markdown="תוכן \ud800 נוסף"),
        lambda d: _section(d).update(title="\ud800", breadcrumb=["חיפוש גלובלי", "\ud800"]),
        lambda d: d["pages"][0].update(title="\udfff"),
    ],
    ids=["markdown", "section title", "page title"],
)
def test_a_lone_surrogate_is_an_invalid_file_and_not_a_crash(mutate):
    """``\\ud800`` ב-JSON הוא UTF-8 תקין ומפוענח ל-surrogate בודד, ו-``encode`` עליו זורק
    ``UnicodeEncodeError`` — בבדיקת הגודל, או אחר כך בבניית הנתחים."""
    data = json.dumps(_broken(mutate), ensure_ascii=True).encode("ascii")
    with pytest.raises(client.ExportFetchError) as raised:
        client.parse_export(data)
    assert raised.value.code == client.EXPORT_INVALID


@pytest.mark.parametrize("data", [b"not json", b"\xff\xfe\x00", b""])
def test_bytes_that_are_not_json_are_refused(data):
    with pytest.raises(client.ExportFetchError) as raised:
        client.parse_export(data)
    assert raised.value.code == client.EXPORT_INVALID


def test_a_newer_schema_is_refused_by_name():
    with pytest.raises(client.ExportFetchError) as raised:
        client.parse_export(_bytes(_document(schema_version=contract.SCHEMA_VERSION + 1)))
    assert raised.value.code == client.EXPORT_UNSUPPORTED_SCHEMA


def test_a_failure_detail_is_bounded():
    huge = "x" * 5000
    with pytest.raises(client.ExportFetchError) as raised:
        client.parse_export(_bytes(_broken(lambda d: d["pages"][0].update(path=huge + ".html"))))
    assert len(raised.value.detail) <= 300


def test_the_limits_are_far_above_the_measured_file():
    """התקרות נגזרות מהמדידה (7.10.2026, ``scripts/measure_docs_export.py``), עם שוליים."""
    assert client.EXPORT_MAX_BYTES == 2 * 2_462_043
    assert client.MAX_BREADCRUMB_BYTES < 2000 - len("\n\n"), "no room left for a body in a chunk"


# ---------------------------------------------------------------------------
# ההורדה
# ---------------------------------------------------------------------------


def _fetch(handler, **kwargs):
    with client.new_export_http_client(transport=httpx.MockTransport(handler)) as http:
        return client.fetch_export(http, **kwargs)


def test_a_commit_is_fetched_from_its_own_file_without_a_validator():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=_bytes(_document()), headers={"ETag": '"abc-1"'})

    result = _fetch(handler, commit=SHA, etag='"old"')

    [request] = seen
    assert str(request.url) == f"{contract.SITE_URL}_export/sections-{SHA}.json"
    assert "if-none-match" not in request.headers
    assert result.document.source_commit == SHA
    assert result.etag == '"abc-1"'
    assert result.not_modified is False


def test_the_main_file_is_asked_with_the_previous_etag_and_304_means_no_change():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(304)

    result = _fetch(handler, etag='"abc-1"')

    assert str(seen[0].url) == contract.SITE_URL + contract.EXPORT_PATH
    assert seen[0].headers["if-none-match"] == '"abc-1"'
    assert (result.not_modified, result.document, result.etag) == (True, None, '"abc-1"')


def test_a_304_that_was_not_asked_for_is_an_error():
    with pytest.raises(client.ExportFetchError) as raised:
        _fetch(lambda request: httpx.Response(304))
    assert raised.value.code == client.EXPORT_HTTP_ERROR


@pytest.mark.parametrize(
    "status,code",
    [(404, client.EXPORT_NOT_FOUND), (500, client.EXPORT_HTTP_ERROR), (301, client.EXPORT_HTTP_ERROR)],
)
def test_an_http_failure_is_named(status, code):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, headers={"Location": "https://evil.example/x.json"})

    with pytest.raises(client.ExportFetchError) as raised:
        _fetch(handler, commit=SHA)
    assert raised.value.code == code
    assert len(seen) == 1, "a redirect was followed"


def test_a_missing_commit_file_does_not_fall_back_to_the_main_file():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path.endswith(f"sections-{SHA}.json"):
            return httpx.Response(404)
        return httpx.Response(200, content=_bytes(_document()))

    with pytest.raises(client.ExportFetchError) as raised:
        _fetch(handler, commit=SHA)
    assert raised.value.code == client.EXPORT_NOT_FOUND
    assert seen == [f"{contract.SITE_URL}_export/sections-{SHA}.json"]


def test_a_network_failure_is_unreachable():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(client.ExportFetchError) as raised:
        _fetch(handler)
    assert raised.value.code == client.EXPORT_UNREACHABLE


def test_an_exception_outside_the_transport_is_not_swallowed():
    def handler(request):
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError, match="bug"):
        _fetch(handler)


def test_a_corrupt_compressed_body_is_invalid():
    def handler(request):
        return httpx.Response(200, content=b"not gzip at all", headers={"Content-Encoding": "gzip"})

    with pytest.raises(client.ExportFetchError) as raised:
        _fetch(handler)
    assert raised.value.code == client.EXPORT_INVALID


def test_a_compressed_body_is_counted_after_decoding(monkeypatch):
    """תקרת הבתים חלה על מה שנפתח, ולא על מה שעבר ברשת — אחרת קובץ דחוס היה עוקף אותה."""
    payload = _bytes(_document())
    monkeypatch.setattr(client, "EXPORT_MAX_BYTES", len(payload) - 1)

    def handler(request):
        return httpx.Response(200, content=gzip.compress(payload), headers={"Content-Encoding": "gzip"})

    with pytest.raises(client.ExportFetchError) as raised:
        _fetch(handler)
    assert raised.value.code == client.EXPORT_TOO_LARGE


def test_a_declared_size_above_the_limit_is_refused_before_reading(monkeypatch):
    monkeypatch.setattr(client, "EXPORT_MAX_BYTES", 10)
    pulled = []

    def body():
        pulled.append(1)
        yield b"{}"

    def handler(request):
        return httpx.Response(200, content=body(), headers={"Content-Length": "11"})

    with pytest.raises(client.ExportFetchError) as raised:
        _fetch(handler)
    assert raised.value.code == client.EXPORT_TOO_LARGE
    assert pulled == []


def test_a_download_that_runs_past_the_deadline_stops():
    ticks = iter(range(0, 10_000, 30))

    def clock():
        return float(next(ticks))

    def body():
        while True:
            yield b" " * 10

    def handler(request):
        return httpx.Response(200, content=body())

    with pytest.raises(client.ExportFetchError) as raised:
        _fetch(handler, clock=clock)
    assert raised.value.code == client.EXPORT_TIMEOUT


def test_a_file_for_another_site_is_refused():
    def handler(request):
        return httpx.Response(200, content=_bytes(_document(site_url="https://docs.example.test/")))

    with pytest.raises(client.ExportFetchError) as raised:
        _fetch(handler)
    assert raised.value.code == client.EXPORT_SITE_MISMATCH


def test_a_file_from_another_commit_is_stale():
    def handler(request):
        return httpx.Response(200, content=_bytes(_document(source_commit=OTHER_SHA)))

    with pytest.raises(client.ExportFetchError) as raised:
        _fetch(handler, commit=SHA)
    assert raised.value.code == client.EXPORT_STALE


def test_an_etag_outside_the_grammar_is_not_kept(caplog):
    def handler(request):
        return httpx.Response(200, content=_bytes(_document()), headers={"ETag": "no-quotes"})

    with caplog.at_level(logging.WARNING, logger=client.__name__):
        result = _fetch(handler)
    assert result.etag is None
    assert "ETag" in caplog.text


def test_a_weak_etag_is_kept():
    def handler(request):
        return httpx.Response(200, content=_bytes(_document()), headers={"ETag": 'W/"6ac64cb8-25915b"'})

    assert _fetch(handler).etag == 'W/"6ac64cb8-25915b"'


def test_a_caller_passing_a_non_sha_is_a_bug():
    with pytest.raises(ValueError):
        _fetch(lambda request: httpx.Response(200), commit="abc")


def test_the_document_is_not_shared_with_the_raw_input():
    """מה שחוזר בנוי מהערכים שנבדקו, ולא מצביע לרשימות של הקלט."""
    raw = _document()
    parsed = client.parse_export(_bytes(copy.deepcopy(raw)))
    assert isinstance(parsed.pages, tuple)
    assert isinstance(parsed.pages[0].sections, tuple)
    assert isinstance(parsed.pages[0].sections[1].breadcrumb, tuple)
