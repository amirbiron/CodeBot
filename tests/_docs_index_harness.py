"""העולם של מעבר האינדוקס של התיעוד בטסטים: אתר מדומה, מטמיע מדומה, וקובץ ייצוא שנבנה לפי החוזה.

פונקציות ולא fixtures (T3), כמו ``_metrics_writer_harness.py``. משמש את
``test_docs_index_service.py`` (מול דמה) ואת ``test_docs_index_mongo.py`` (מול מונגו אמיתי),
כדי שהאתר והמטמיע ייכתבו פעם אחת.

**האתר מגיש בתים, והמעבר קורא אותם דרך ``fetch_export`` ו-``parse_export`` האמיתיים** — בלי קיצור
דרך שבונה ``ExportDocument`` ביד. כך כל טסט עובר באותו מסלול שהמעבר עובר בייצור: הכתובת לפי
קומיט, ‏ETag ו-304, הבדיקה של הקובץ. מה שמדומה הוא רק מה שמחוץ לתהליך: ה-CDN של האתר, ו-Gemini.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import httpx

from services import docs_index_service as svc
from services import docs_search_contract as contract
from services.docs_export_client import new_export_http_client

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40

MODEL = "gemini-embedding-001"
DIMENSIONS = 4
MODEL_KEY = f"{MODEL}/{DIMENSIONS}"

EARLY = "2026-10-07T10:00:00+00:00"
LATE = "2026-10-07T12:00:00+00:00"
LATER = "2026-10-07T13:00:00+00:00"


# ---------------------------------------------------------------------------
# קובץ הייצוא
# ---------------------------------------------------------------------------


def section(anchor: str, *breadcrumb: str, markdown: str = "טקסט של הסעיף.") -> Dict[str, Any]:
    """סעיף בצורה שסקריפט הייצוא כותב: הכותרת היא סוף השביל, והרמה היא אורכו."""
    return {
        "anchor": anchor,
        "title": breadcrumb[-1],
        "breadcrumb": list(breadcrumb),
        "level": len(breadcrumb),
        "markdown": markdown,
    }


def page(path: str, source_path: str, *sections: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "path": path,
        "source_path": source_path,
        "title": sections[0]["breadcrumb"][0],
        "sections": list(sections),
    }


def site_pages() -> List[Dict[str, Any]]:
    """שני עמודים, חמישה סעיפים. ארבעה נכנסים לאינדקס; "ראו גם" הוא קישורים בלבד ומדולג."""
    return [
        page(
            "webapp/global-search.html",
            "docs/webapp/global-search.rst",
            section("webapp-global-search", "חיפוש גלובלי", markdown="החיפוש בעמוד הקבצים."),
            section(
                "global-search-types", "חיפוש גלובלי", "סוגי החיפוש",
                markdown="| סוג | מה |\n| --- | --- |\n| תוכן | טקסט |",
            ),
            section(
                "see-also", "חיפוש גלובלי", "ראו גם",
                markdown="- [אינדקסים](https://amirbiron.github.io/CodeBot/database/indexing.html)",
            ),
        ),
        page(
            "observability/events_catalog.html",
            "docs/observability/events_catalog.rst",
            section("events-catalog", "קטלוג אירועים", markdown="כל האירועים במערכת."),
            section("id3", "קטלוג אירועים", "אינדקס התיעוד", markdown="``docs_index_pass`` — מעבר הסתיים."),
        ),
    ]


def export_bytes(commit: str, pages: List[Dict[str, Any]], built_at: str = LATE) -> bytes:
    """הקובץ כפי שהוא מוגש מהאתר — אותם שדות ש-``build_document`` בסקריפט הייצוא כותב."""
    document = {
        "schema_version": contract.SCHEMA_VERSION,
        "source_commit": commit,
        "built_at": built_at,
        "site_url": contract.SITE_URL,
        "page_count": len(pages),
        "section_count": sum(len(item["sections"]) for item in pages),
        "pages": pages,
    }
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------------------
# האתר והמטמיע
# ---------------------------------------------------------------------------


class FakeSite:
    """האתר: הקובץ הראשי והעותקים לפי קומיט, עם ETag ו-304 כמו GitHub Pages."""

    def __init__(self) -> None:
        self.files: Dict[str, bytes] = {}
        self.requests: List[httpx.Request] = []

    def publish(self, commit: str, pages: List[Dict[str, Any]], *, built_at: str = LATE,
                main: bool = True, commit_copy: bool = True) -> None:
        """פריסה: העותק לפי הקומיט והקובץ הראשי. ``commit_copy=False`` — אתר שנבנה לפני שהייצוא
        כתב עותק לפי קומיט, או עותק של פריסה קודמת שכבר נעלם."""
        data = export_bytes(commit, pages, built_at)
        if commit_copy:
            self.files[contract.export_path_for_commit(commit)] = data
        if main:
            self.files[contract.EXPORT_PATH] = data

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/CodeBot/")
        data = self.files.get(path)
        if data is None:
            return httpx.Response(404)
        etag = '"' + hashlib.sha256(data).hexdigest()[:16] + '"'
        if request.headers.get("If-None-Match") == etag:
            return httpx.Response(304, headers={"ETag": etag})
        return httpx.Response(200, content=data, headers={"ETag": etag})

    def client(self) -> httpx.Client:
        return new_export_http_client(transport=httpx.MockTransport(self._handle))

    def paths(self) -> List[str]:
        return [request.url.path.removeprefix("/CodeBot/") for request in self.requests]


class FakeEmbedder:
    """מה שהמעבר משתמש בו מ-``SyncEmbeddingClient``. ההתנהגות נקבעת ב-``world``:

    * ``world.api_key`` — מה ש-``is_available`` מחזיר.
    * ``world.embed_failures`` — מספר קריאה ← ``(סטטוס, תיאור)``, בחוזה של ``embed_batch``.
    * ``world.on_embed`` — מספר קריאה ← פונקציה שרצה בתוך הקריאה (עצירה, גניבת lease, שעון).
    """

    def __init__(self, world: Any) -> None:
        self.world = world

    def __enter__(self) -> "FakeEmbedder":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None

    def is_available(self) -> bool:
        return bool(self.world.api_key)

    def embed_batch(self, texts, *, model, api_version, dimensions, deadline):
        index = len(self.world.embed_calls)
        self.world.embed_calls.append(
            {"texts": list(texts), "model": model, "api_version": api_version, "dimensions": dimensions}
        )
        hook = self.world.on_embed.get(index)
        if hook is not None:
            hook()
        failure = self.world.embed_failures.get(index)
        if failure is not None:
            return None, failure[0], failure[1]
        return [[float(position + 1)] * dimensions for position in range(len(texts))], 200, ""


def make_world(monkeypatch, db: Any) -> SimpleNamespace:
    """מסד עם הגדרות ההטמעה, אתר, מטמיע ואירועים — ומעבר שרץ באותו thread.

    ``_runner_factory`` מריץ את המעבר מיד, כך ש-``request_pass`` חוזר אחרי שהוא הסתיים. טסט
    שבודק את התור מחליף אותו שוב.
    """
    db["system_config"].insert_one(
        {"_id": "semantic_embedding", "model": MODEL, "api_version": "v1beta", "dimensions": DIMENSIONS}
    )
    world = SimpleNamespace(
        db=db,
        site=FakeSite(),
        api_key=True,
        embed_calls=[],
        embed_failures={},
        on_embed={},
        clock=[0.0],
        events=[],
    )
    world.context = svc.PassContext(
        http_client_factory=world.site.client,
        embed_client_factory=lambda: FakeEmbedder(world),
        clock=lambda: world.clock[0],
    )
    monkeypatch.setattr(svc, "_default_context", world.context)
    monkeypatch.setattr(svc, "_runner_factory", lambda target: target())
    monkeypatch.setattr(
        svc, "emit_event", lambda name, severity="info", **fields: world.events.append((name, severity, fields))
    )
    return world


def admin_app_for(monkeypatch, db: Any, world: SimpleNamespace) -> SimpleNamespace:
    """הוובאפ האמיתי מול ``db``: לקוח בדיקה, ``login(user_id)`` (1 הוא האדמין) והאירועים שנשלחו.

    ``webapp.app`` מיובא כאן ולא בראש הקובץ, כדי שטסטים של השירות לבד לא יטענו את הוובאפ.
    """
    import webapp.app as wa

    audits: List[Any] = []
    monkeypatch.setattr(wa, "get_db", lambda: db)
    monkeypatch.setattr(wa, "emit_event", lambda name, severity="info", **fields: audits.append((name, fields)))
    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    monkeypatch.setitem(wa.app.config, "SECRET_KEY", "docs-index-tests")
    client = wa.app.test_client()

    def login(user_id: int) -> None:
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_data"] = {"id": user_id, "is_admin": user_id == 1, "is_premium": False}

    return SimpleNamespace(wa=wa, db=db, world=world, client=client, login=login, audits=audits)


def run_request(world: SimpleNamespace, trigger: str = svc.TRIGGER_MANUAL_CHECK, **kwargs: Any) -> Dict[str, Any]:
    """מבקש מעבר, מריץ אותו עד הסוף, ומחזיר את ה-``run`` שנרשם. ה-lease חייב להשתחרר בסוף."""
    assert svc.request_pass(world.db, trigger=trigger, **kwargs) == svc.REQUEST_STARTED
    state = svc.read_state(world.db)
    assert state["lease_holder"] is None, state
    return state["run"]


def fill(world: SimpleNamespace, *, pages: Optional[List[Dict[str, Any]]] = None, commit: str = SHA_A,
         built_at: str = LATE, requested_by: Optional[int] = None) -> Dict[str, Any]:
    """מילוי ראשון: מעבר הפריסה עוצר לאישור, והאישור מריץ אותו עד הסוף."""
    world.site.publish(commit, pages if pages is not None else site_pages(), built_at=built_at)
    waiting = run_request(world, svc.TRIGGER_DEPLOY, commit=commit)
    assert waiting["status"] == svc.STATUS_AWAITING_APPROVAL, waiting
    fingerprint = svc.read_state(world.db)["approval"]["fingerprint"]
    done = run_request(world, svc.TRIGGER_APPROVED, approved_fingerprint=fingerprint, requested_by=requested_by)
    assert done["status"] == svc.STATUS_COMPLETE, done
    return done
