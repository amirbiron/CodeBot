import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.embedding_service import EmbeddingService, compute_content_hash
from services.chunking_service import split_code_to_chunks, create_embedding_text


class TestContentHash:
    def test_consistent_hash(self):
        content = "def hello(): pass"
        hash1 = compute_content_hash(content)
        hash2 = compute_content_hash(content)
        assert hash1 == hash2

    def test_different_content_different_hash(self):
        hash1 = compute_content_hash("def foo(): pass")
        hash2 = compute_content_hash("def bar(): pass")
        assert hash1 != hash2


class TestChunking:
    def test_short_code_single_chunk(self):
        code = "\n".join([f"line {i}" for i in range(50)])
        chunks = split_code_to_chunks(code, chunk_size=100)
        assert len(chunks) == 1

    def test_long_code_multiple_chunks(self):
        code = "\n".join([f"line {i}" for i in range(500)])
        chunks = split_code_to_chunks(code, chunk_size=100, overlap=20)
        assert len(chunks) > 1

    def test_chunk_overlap(self):
        code = "\n".join([f"line {i}" for i in range(300)])
        chunks = split_code_to_chunks(code, chunk_size=100, overlap=20)
        if len(chunks) >= 2:
            chunk1_end = chunks[0].end_line
            chunk2_start = chunks[1].start_line
            assert chunk2_start < chunk1_end

    def test_empty_code(self):
        chunks = split_code_to_chunks("")
        assert len(chunks) == 0


class TestEmbeddingText:
    def test_creates_combined_text(self):
        text = create_embedding_text(
            code_chunk="def hello(): pass",
            title="hello.py",
            description="A greeting function",
            tags=["python", "utils"],
            language="python",
        )

        assert "hello.py" in text
        assert "greeting function" in text
        assert "python" in text
        assert "def hello()" in text


class TestEmbeddingService:
    @pytest.mark.asyncio
    async def test_generate_embedding_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": {"values": [0.1] * 768}}

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False

        with patch(
            "services.embedding_service.httpx.AsyncClient", return_value=mock_client
        ):
            service = EmbeddingService(api_key="test_key")
            embedding = await service.generate_embedding("test text")

        assert embedding is not None
        assert len(embedding) == 768

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self):
        service = EmbeddingService(api_key="")
        embedding = await service.generate_embedding("test")
        assert embedding is None
