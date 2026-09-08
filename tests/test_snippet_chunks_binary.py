"""וקטורי embedding נשמרים כ-BSON BinData ולא כמערך doubles.

הרקע (אישו #3332): מערך BSON שומר כל מספר כ-double (8 בייט), ובנוסף שם
מפתח ("0", "1", ... "767") ובייט טיפוס לכל איבר — כ-9.9KB לווקטור של 768
מימדים, שהם ~33MB מתוך 63MB הקולקציה. אותו וקטור כ-BinData float32 הוא
768×4 + 2 בייט תקורה = 3,074 בייט.

אומת מול הקלאסטר האמיתי לפני המימוש: מסמך עם BinData נכנס ל-``vector_index``
הקיים, ``$vectorSearch`` עם ``queryVector`` כמערך החזיר אותו בציון 1.0
מדויק, ובאותה שאילתה חזרו גם מסמכים עם וקטורי מערך — כלומר שתי הצורות
חיות יחד תחת אותו ``path`` בזמן ה-re-index.
"""

import asyncio

import pytest
from bson.binary import Binary, BinaryVectorDtype, VECTOR_SUBTYPE

import database.manager as manager_mod


class _FakeChunks:
    def __init__(self):
        self.docs = []

    def delete_many(self, query):
        class _R:
            deleted_count = 0
        return _R()

    def insert_many(self, documents):
        self.docs.extend(documents)

        class _R:
            inserted_ids = [i for i, _ in enumerate(documents)]
        return _R()


class _FakeFiles:
    def __init__(self):
        self.updates = []

    def update_one(self, query, update):
        self.updates.append((query, update))

        class _R:
            modified_count = 1
        return _R()


class _FakeDB:
    def __init__(self):
        self.snippet_chunks = _FakeChunks()
        self.code_snippets = _FakeFiles()


@pytest.fixture()
def fake_db(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(manager_mod, "_get_raw_db", lambda: db)
    return db


def test_to_binary_vector_matches_pymongo_encoding():
    """הפורמט חייב להיות בדיוק זה ש-Atlas אינדקס בבדיקה מול הקלאסטר."""
    values = [0.5, -0.25, 0.125]
    encoded = manager_mod._to_binary_vector(values)

    assert isinstance(encoded, Binary)
    assert encoded.subtype == VECTOR_SUBTYPE == 9
    assert bytes(encoded) == bytes(Binary.from_vector(values, BinaryVectorDtype.FLOAT32))

    decoded = encoded.as_vector()
    assert decoded.dtype is BinaryVectorDtype.FLOAT32
    assert list(decoded.data) == pytest.approx(values)


def test_binary_vector_is_far_smaller_than_the_array_form():
    """זו כל הנקודה — והגודל נמדד, לא מוערך.

    מערך BSON שומר לכל איבר גם שם מפתח ("0" ... "767") וגם בייט טיפוס,
    ולכן הוא יקר בהרבה מ-8 בייט לערך.
    """
    import bson

    values = [0.001 * i for i in range(768)]
    encoded = manager_mod._to_binary_vector(values)
    assert len(encoded) == 768 * 4 + 2  # dtype byte + padding byte

    as_array = len(bson.encode({"v": values}))
    as_binary = len(bson.encode({"v": encoded}))
    assert as_binary * 3 < as_array, (
        f"binary={as_binary}B array={as_array}B - expected roughly a 3x saving"
    )


def test_already_binary_is_passed_through():
    encoded = manager_mod._to_binary_vector([0.5, 0.5])
    assert manager_mod._to_binary_vector(encoded) is encoded


def test_none_stays_none():
    assert manager_mod._to_binary_vector(None) is None


def test_save_snippet_chunks_stores_binary(fake_db):
    chunks = [{
        "chunkIndex": 0,
        "codeChunk": "print(1)",
        "startLine": 1,
        "endLine": 1,
        "language": "python",
        "chunkEmbedding": [0.25] * 768,
    }]

    saved = asyncio.run(
        manager_mod.save_snippet_chunks(user_id=1, snippet_id="s1", chunks=chunks)
    )

    assert saved == 1
    stored = fake_db.snippet_chunks.docs[0]["chunkEmbedding"]
    assert isinstance(stored, Binary) and stored.subtype == 9
    assert list(stored.as_vector().data) == pytest.approx([0.25] * 768)


def test_update_snippet_embedding_status_stores_binary(fake_db):
    ok = asyncio.run(
        manager_mod.update_snippet_embedding_status(
            snippet_id="s1",
            content_hash="h",
            chunk_count=1,
            snippet_embedding=[0.75] * 768,
            chunker_version=2,
        )
    )

    assert ok is True
    update = fake_db.code_snippets.updates[-1][1]["$set"]
    assert isinstance(update["snippetEmbedding"], Binary)
    assert update["snippetEmbedding"].subtype == 9
    assert update["chunkerVersion"] == 2


def test_chunker_version_is_written_only_when_given(fake_db):
    """זה מה שמונע רשומה שמתארת חיתוך שלא קרה."""
    asyncio.run(
        manager_mod.update_snippet_embedding_status(
            snippet_id="s1", content_hash="h", chunk_count=0
        )
    )
    assert "chunkerVersion" not in fake_db.code_snippets.updates[-1][1]["$set"]


def test_snippet_embedding_is_excluded_from_list_projections():
    """הוא ``Binary``, ולכן ``jsonify`` על מסמך גולמי יזרוק ``TypeError``.

    כמערך הוא היה עובר בשקט ורק מנפח את התשובה ב-~3KB למסמך.
    """
    from database.repository import HEAVY_FIELDS_EXCLUDE_PROJECTION

    assert HEAVY_FIELDS_EXCLUDE_PROJECTION.get("snippetEmbedding") == 0
