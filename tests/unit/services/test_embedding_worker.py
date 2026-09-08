"""ה-worker חייב להבחין בין כשל זמני לכשל קבוע.

הרקע (אישו #3332): עד כה ``should_retry = len(chunk_docs) < len(chunks)``,
כלומר **כל** כשל בצ'אנק אחד סימן את הקובץ כולו ב-``needs_embedding=True``.
הקובץ נשלף שוב כל 300 שניות וכל הצ'אנקים שלו נשלחו מחדש — לנצח. כל עוד
Gemini חתך בשקט זה כמעט לא קרה; ברגע שמפסיקים את החיתוך השקט, זה הופך
למסלול הראשי.

הסטאבים כאן הם דמויות מקרטון: מחלקות קטנות שכתובות ביד ומחזירות תשובות
מתוכננות, כמו שמקובל בריפו (בלי mongomock).
"""

import pytest

import services.embedding_worker as worker_mod
from services.chunking_service import CHUNKER_VERSION


class _FakeEmbeddingService:
    """מחזיר תשובות לפי תור מתוכנן, ומונה כמה קריאות יצאו."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.heal_calls = 0

    def is_available(self):
        return True

    async def generate_embedding_with_status(self, text, *, model, api_version, dimensions):
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return ([0.1] * 768, 200, "")

    async def generate_embedding(self, text):
        self.heal_calls += 1
        return [0.1] * 768


class _Settings:
    model = "gemini-embedding-001"
    api_version = "v1beta"
    dimensions = 768
    active_key = "gemini-embedding-001/768"
    legacy_key = "gemini-embedding-001/768"


@pytest.fixture()
def harness(monkeypatch):
    """מחליף את שכבת ה-DB במקליטים, ומחזיר אותם לבדיקה."""
    saved_chunks = []
    status_updates = []

    async def _save_snippet_chunks(*, user_id, snippet_id, chunks):
        saved_chunks.append({"user_id": user_id, "snippet_id": snippet_id, "chunks": chunks})
        return len(chunks)

    async def _update_status(**kwargs):
        status_updates.append(kwargs)
        return True

    async def _is_latest(user_id, file_name, snippet_id):
        return True

    monkeypatch.setattr(worker_mod, "save_snippet_chunks", _save_snippet_chunks)
    monkeypatch.setattr(worker_mod, "update_snippet_embedding_status", _update_status)
    monkeypatch.setattr(worker_mod, "is_latest_active_snippet", _is_latest)
    monkeypatch.setattr(
        worker_mod, "get_embedding_settings_cached", lambda **_kw: _Settings()
    )
    return saved_chunks, status_updates


def _snippet(code="print(1)\n" * 5, **extra):
    doc = {
        "_id": "snippet-1",
        "user_id": 42,
        "file_name": "a.py",
        "code": code,
        "programming_language": "python",
        "tags": [],
        "needs_embedding": True,
        "needs_chunking": True,
    }
    doc.update(extra)
    return doc


def _make_worker(monkeypatch, responses):
    service = _FakeEmbeddingService(responses)
    monkeypatch.setattr(worker_mod, "get_embedding_service", lambda: service)
    w = worker_mod.EmbeddingWorker()
    return w, service


class TestFailureClassification:
    @pytest.mark.asyncio
    async def test_permanent_failure_does_not_requeue_the_file(self, harness, monkeypatch):
        """400 על צ'אנק אחד לא מחזיר את הקובץ לתור.

        לפני התיקון זה סימן ``needs_embedding=True`` והקובץ חזר כל 300 שניות
        לנצח, כי ניסיון חוזר מחזיר בדיוק את אותה תשובה.
        """
        _saved, updates = harness
        w, _svc = _make_worker(monkeypatch, [(None, 400, "bad request")])

        await w._process_snippet(_snippet())

        assert updates, "no status update was written"
        assert updates[-1]["needs_embedding"] is False
        assert updates[-1]["chunker_version"] == CHUNKER_VERSION

    @pytest.mark.asyncio
    async def test_transient_failure_does_requeue_the_file(self, harness, monkeypatch):
        """timeout הוא כשל שכדאי לנסות שוב — הקובץ חייב לחזור לתור."""
        _saved, updates = harness
        w, _svc = _make_worker(monkeypatch, [(None, 0, "timeout")])

        await w._process_snippet(_snippet())

        assert updates[-1]["needs_embedding"] is True

    @pytest.mark.asyncio
    async def test_quota_stops_the_batch_without_touching_stored_chunks(self, harness, monkeypatch):
        """429 שמוצו עליו ה-retries עוצר את הבאץ' ולא נוגע בצ'אנקים הקיימים.

        ``save_snippet_chunks`` מוחק את הצ'אנקים הישנים לפני שהוא כותב חדשים.
        אם היינו קוראים לו כאן, הקובץ היה נשאר בלי צ'אנקים בכלל עד שהמכסה
        תתחדש — כלומר נעלם מהחיפוש הסמנטי בגלל rate limiting.
        """
        saved, updates = harness
        w, _svc = _make_worker(monkeypatch, [(None, 429, "quota")])

        with pytest.raises(worker_mod.EmbeddingQuotaExhausted):
            await w._process_snippet(_snippet())

        assert saved == [], "existing chunks were deleted while the quota was exhausted"
        assert updates == [], "snippet was marked as handled despite doing no work"

    @pytest.mark.asyncio
    async def test_batch_stops_on_quota(self, harness, monkeypatch):
        """שאר הבאץ' ייתקל באותה תשובה בדיוק — אין טעם לשרוף עליו קריאות."""
        _saved, _updates = harness
        w, svc = _make_worker(monkeypatch, [(None, 429, "quota")])

        async def _fetch(limit):
            return [_snippet(_id=f"s{i}") for i in range(5)]

        monkeypatch.setattr(worker_mod, "get_snippets_needing_processing", _fetch)

        processed = await w._process_batch()

        assert processed == 0
        assert w._quota_hit is True
        assert svc.calls == 1, f"kept calling Gemini after the quota ran out ({svc.calls} calls)"


class TestChunkerVersion:
    @pytest.mark.asyncio
    async def test_written_on_success(self, harness, monkeypatch):
        _saved, updates = harness
        w, _svc = _make_worker(monkeypatch, [])

        await w._process_snippet(_snippet())

        assert updates[-1]["chunker_version"] == CHUNKER_VERSION

    @pytest.mark.asyncio
    async def test_written_for_empty_content(self, harness, monkeypatch):
        """מסמך ריק הוא מסמך מטופל.

        בלי ``chunkerVersion`` הוא היה נשלף שוב בכל סבב ותופס אחד מחמשת
        המקומות בבאץ' — כלומר עבודה אמיתית לא הייתה מתוזמנת לעולם.
        """
        _saved, updates = harness
        w, svc = _make_worker(monkeypatch, [])

        await w._process_snippet(_snippet(code=""))

        assert updates[-1]["chunker_version"] == CHUNKER_VERSION
        assert svc.calls == 0

    @pytest.mark.asyncio
    async def test_written_for_unchanged_content(self, harness, monkeypatch):
        from services.embedding_service import compute_content_hash

        _saved, updates = harness
        w, svc = _make_worker(monkeypatch, [])
        code = "print(1)\n" * 5
        snippet = _snippet(
            code=code,
            needs_embedding=False,
            needs_chunking=False,
            contentHash=compute_content_hash(code),
            chunkerVersion=CHUNKER_VERSION,
            chunkCount=3,
        )

        await w._process_snippet(snippet)

        assert svc.calls == 0, "re-embedded a file that did not change"
        assert updates[-1]["chunker_version"] == CHUNKER_VERSION

    @pytest.mark.asyncio
    async def test_stale_chunker_version_forces_reprocessing(self, harness, monkeypatch):
        """זה מה שמחליף פקודת re-index ידנית: הקובץ לא השתנה, אבל הכלל כן."""
        from services.embedding_service import compute_content_hash

        _saved, updates = harness
        w, svc = _make_worker(monkeypatch, [])
        code = "print(1)\n" * 5
        snippet = _snippet(
            code=code,
            needs_embedding=False,
            needs_chunking=False,
            contentHash=compute_content_hash(code),
            chunkerVersion=CHUNKER_VERSION - 1,
        )

        await w._process_snippet(snippet)

        assert svc.calls > 0, "an old chunker version did not trigger re-chunking"


class TestSupersededVersions:
    @pytest.mark.asyncio
    async def test_non_latest_version_is_cleared_without_calling_gemini(self, harness, monkeypatch):
        """גרסה ישנה לא תופיע בתוצאות בשום מקרה — הצינור מסנן אותה.

        אין טעם לשלם עליה קריאות, ואת הצ'אנקים שלה יש לנקות.
        """
        saved, updates = harness
        w, svc = _make_worker(monkeypatch, [])

        async def _not_latest(user_id, file_name, snippet_id):
            return False

        monkeypatch.setattr(worker_mod, "is_latest_active_snippet", _not_latest)

        await w._process_snippet(_snippet())

        assert svc.calls == 0, "embedded a superseded version"
        assert saved and saved[-1]["chunks"] == []
        assert updates[-1]["chunker_version"] == CHUNKER_VERSION


class TestLowInformationChunks:
    @pytest.mark.asyncio
    async def test_dump_chunks_are_skipped_without_requeueing(self, harness, monkeypatch):
        """dump של מספרים מדולג — וזה לא כשל.

        אילו הסינון היה בתוך הלולאה, ``len(chunk_docs) < len(chunks)`` היה
        מסמן ``needs_embedding=True`` וכל קובץ dump היה חוזר לתור לנצח.
        """
        saved, updates = harness
        w, svc = _make_worker(monkeypatch, [])
        dump = "\n".join("0.0123456789, " * 20 for _ in range(40))

        await w._process_snippet(_snippet(code=dump))

        assert svc.calls == 0, "a pure number dump was still sent for embedding"
        assert saved and saved[-1]["chunks"] == []
        assert updates[-1]["needs_embedding"] is not True
        assert updates[-1]["chunker_version"] == CHUNKER_VERSION


class TestMetadataEmbedding:
    @pytest.mark.asyncio
    async def test_empty_metadata_is_not_a_failure(self, harness, monkeypatch):
        """קובץ בלי שם/תיאור/תגיות/שפה — אין מה להטמיע, וזה לא כשל."""
        _saved, updates = harness
        w, _svc = _make_worker(monkeypatch, [])
        snippet = _snippet()
        snippet["file_name"] = ""
        snippet["programming_language"] = ""
        snippet["tags"] = []

        await w._process_snippet(snippet)

        assert updates[-1]["needs_embedding"] is False


class TestDimensionFallbackClassification:
    """הנתיב שנשבר: ניסיון חוזר בלי מימד קבוע אחרי 422.

    הקוד הקודם קרא לניסיון השני וזרק את הסטטוס שלו (``_st2``). כל כשל שם —
    429, timeout, 500 — סווג כ**קבוע**, והצ'אנק נדחה לצמיתות ונעלם מהחיפוש.
    זה בדיוק המנגנון התלת-מצבי שנבנה בסעיף 4ג, שנשבר על מסלול אחד.
    """

    DIM_MISMATCH = (None, 422, '{"error":{"message":"dimension_mismatch"}}')

    @pytest.mark.asyncio
    async def test_quota_on_the_retry_stops_the_batch(self, harness, monkeypatch):
        """429 בניסיון השני = מכסה שנגמרה, לא צ'אנק פגום."""
        _saved, _updates = harness
        w, _svc = _make_worker(monkeypatch, [self.DIM_MISMATCH, (None, 429, "rate limit")])

        with pytest.raises(worker_mod.EmbeddingQuotaExhausted):
            await w._process_snippet(_snippet())

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [0, 500, 503])
    async def test_transient_failure_on_the_retry_requeues_the_file(
        self, harness, monkeypatch, status
    ):
        """timeout או 5xx בניסיון השני מחזירים את הקובץ לתור.

        הקוד הקודם היה מוחק את הצ'אנק מהחיפוש בגלל תקלת רשת חולפת.
        """
        _saved, updates = harness
        w, _svc = _make_worker(monkeypatch, [self.DIM_MISMATCH, (None, status, "boom")])

        await w._process_snippet(_snippet())

        assert updates, "the worker never reported a status"
        assert updates[-1]["needs_embedding"] is True

    @pytest.mark.asyncio
    async def test_a_genuinely_bad_request_on_the_retry_stays_permanent(
        self, harness, monkeypatch
    ):
        """400 בניסיון השני באמת קבוע — התיקון לא הפך הכול לזמני."""
        _saved, updates = harness
        w, _svc = _make_worker(monkeypatch, [self.DIM_MISMATCH, (None, 400, "bad request")])

        await w._process_snippet(_snippet())

        assert updates[-1]["needs_embedding"] is False

    @pytest.mark.asyncio
    async def test_a_successful_retry_still_yields_a_chunk(self, harness, monkeypatch):
        """ההצלחה במסלול הזה נשמרה כמו שהייתה."""
        saved, updates = harness
        w, _svc = _make_worker(monkeypatch, [self.DIM_MISMATCH, ([0.2] * 768, 200, "")])

        await w._process_snippet(_snippet())

        assert saved and saved[-1]["chunks"]
        assert updates[-1]["needs_embedding"] is False

    def test_classification_is_one_function_for_both_call_sites(self):
        """שני אתרי הקריאה חולקים מיפוי אחד, אחרת הם נסחפים שוב."""
        assert worker_mod._classify_status(429) == worker_mod.FAILURE_QUOTA
        assert worker_mod._classify_status(400) == worker_mod.FAILURE_PERMANENT
        assert worker_mod._classify_status(413) == worker_mod.FAILURE_PERMANENT
        for status in (0, 401, 403, 500, 502, 503):
            assert worker_mod._classify_status(status) == worker_mod.FAILURE_TRANSIENT


class TestSupersededWhileEmbedding:
    """המירוץ שהריוויו תפס ב-``webapp/app.py``.

    ההטמעה של קובץ אורכת דקות (1.2 שניות לצ'אנק בשער הגלובלי). בזמן הזה
    המשתמש יכול לשמור גרסה חדשה; הניקוי שלה רץ מיד ומוחק את הצ'אנקים של
    הישנה. בלי בדיקה חוזרת ממש לפני הכתיבה, ה-worker היה כותב אותם בחזרה
    שנייה אחרי — וגרסה שהוחלפה הייתה חוזרת לתוצאות החיפוש.
    """

    @pytest.mark.asyncio
    async def test_chunks_are_discarded_when_a_newer_version_arrives_mid_run(
        self, harness, monkeypatch
    ):
        saved, updates = harness

        calls = {"n": 0}

        async def _is_latest(user_id, file_name, snippet_id):
            calls["n"] += 1
            return calls["n"] == 1  # אמת בכניסה, שקר רגע לפני הכתיבה

        monkeypatch.setattr(worker_mod, "is_latest_active_snippet", _is_latest)
        w, _svc = _make_worker(monkeypatch, [])

        await w._process_snippet(_snippet(code="print(1)\n" * 40))

        assert calls["n"] == 2, "the worker checked only once"
        assert saved, "nothing was written at all"
        assert saved[-1]["chunks"] == [], "stale chunks were written back to the index"
        assert updates[-1]["chunk_count"] == 0

    @pytest.mark.asyncio
    async def test_the_normal_path_still_writes_its_chunks(self, harness, monkeypatch):
        """הבדיקה הכפולה לא שוברת את המסלול הרגיל."""
        saved, _updates = harness
        w, _svc = _make_worker(monkeypatch, [])

        await w._process_snippet(_snippet(code="print(1)\n" * 40))

        assert saved[-1]["chunks"], "the happy path stopped writing chunks"


class TestModelMissingIsOneMapping:
    """404 = "המודל שבקונפיג לא קיים", ולכן self-heal ולא retry.

    הרקע: אותו נתיב (ניסיון חוזר בלי מימד קבוע, אחרי 422) נשבר **פעמיים
    ברצף** בשתי דרכים שונות — קודם הסטטוס השני נזרק לגמרי, ואז הוא נשמר
    אבל 404 בו סווג ככשל זמני. שתי התקלות אפשריות רק כשמיפוי הסטטוס חי
    בשני מקומות. הטסטים כאן נועלים את המיפוי לנקודה אחת.
    """

    DIM_MISMATCH = (None, 422, '{"error":{"message":"dimension_mismatch"}}')
    GONE = (None, 404, '{"error":{"message":"model not found"}}')

    def test_the_mapping_knows_about_404(self):
        assert worker_mod._classify_status(404) == worker_mod.FAILURE_MODEL_MISSING

    @pytest.mark.parametrize(
        "status,expected",
        [
            (404, "FAILURE_MODEL_MISSING"),
            (429, "FAILURE_QUOTA"),
            (400, "FAILURE_PERMANENT"),
            (413, "FAILURE_PERMANENT"),
            (0, "FAILURE_TRANSIENT"),
            (500, "FAILURE_TRANSIENT"),
        ],
    )
    def test_every_status_has_exactly_one_meaning(self, status, expected):
        assert worker_mod._classify_status(status) == getattr(worker_mod, expected)

    @pytest.mark.asyncio
    async def test_404_on_the_first_attempt_triggers_self_heal(self, harness, monkeypatch):
        """התנהגות קיימת — הגנה מפני רגרסיה בזמן האיחוד."""
        _saved, _updates = harness
        w, svc = _make_worker(monkeypatch, [self.GONE])

        await w._process_snippet(_snippet())

        assert svc.heal_calls == 1, "a missing model must self-heal, not retry"

    @pytest.mark.asyncio
    async def test_404_on_the_dimension_retry_also_triggers_self_heal(
        self, harness, monkeypatch
    ):
        """זה הבאג: המודל נעלם **בין** שתי הקריאות.

        קודם 422 (אי-התאמת מימדים), ואז הניסיון בלי מימד קבוע מקבל 404. עד
        התיקון זה סווג ככשל זמני — הקובץ חזר לתור כל 300 שניות לנצח, בזמן
        שהתיקון האמיתי (רענון ההגדרה) לא הופעל אף פעם.
        """
        _saved, _updates = harness
        w, svc = _make_worker(monkeypatch, [self.DIM_MISMATCH, self.GONE])

        await w._process_snippet(_snippet())

        assert svc.heal_calls == 1, (
            "404 on the second call was swallowed as transient; self-heal never ran"
        )

    @pytest.mark.asyncio
    async def test_the_snippet_completes_after_the_model_comes_back(
        self, harness, monkeypatch
    ):
        """מסלול ההחלמה המלא: 422 ← 404 ← restart ← הצלחה."""
        saved, updates = harness
        w, svc = _make_worker(monkeypatch, [self.DIM_MISMATCH, self.GONE])

        await w._process_snippet(_snippet())

        assert svc.heal_calls == 1
        assert saved and saved[-1]["chunks"], "the retry never produced chunks"
        assert updates[-1]["needs_embedding"] is False
