"""
בדיקות לשירות Embeddings.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_openai_response():
    """Mock response from OpenAI API."""
    return {
        "data": [
            {
                "embedding": [0.1] * 1536,
                "index": 0,
            }
        ],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 10, "total_tokens": 10},
    }


class TestEmbeddingService:
    """בדיקות לשירות Embeddings."""

    @pytest.mark.asyncio
    async def test_generate_embedding_success(self, mock_openai_response):
        """בדיקת יצירת embedding בהצלחה."""
        with patch("services.embedding_service._get_api_key", return_value="test-key"):
            with patch("httpx.AsyncClient") as mock_client:
                mock_response = MagicMock()
                mock_response.json.return_value = mock_openai_response
                mock_response.raise_for_status = MagicMock()

                mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                    return_value=mock_response
                )

                from services.embedding_service import generate_embedding

                result = await generate_embedding("test text")

                assert isinstance(result, list)
                assert len(result) == 1536
                assert all(isinstance(x, float) for x in result)

    @pytest.mark.asyncio
    async def test_generate_embedding_empty_text(self):
        """בדיקת שגיאה על טקסט ריק."""
        with patch("services.embedding_service._get_api_key", return_value="test-key"):
            from services.embedding_service import EmbeddingError, generate_embedding

            with pytest.raises(EmbeddingError, match="empty_text"):
                await generate_embedding("")

    @pytest.mark.asyncio
    async def test_generate_embedding_no_api_key(self):
        """בדיקת שגיאה כשאין API key."""
        with patch("services.embedding_service._get_api_key", return_value=""):
            from services.embedding_service import EmbeddingError, generate_embedding

            with pytest.raises(EmbeddingError, match="openai_api_key_missing"):
                await generate_embedding("test")

    def test_prepare_text_truncation(self):
        """בדיקת קיצור טקסט ארוך."""
        from services.embedding_service import _truncate_text

        long_text = "x" * 5000
        result = _truncate_text(long_text, 2000)

        assert len(result) <= 2000

    def test_prepare_text_for_embedding(self):
        """בדיקת הכנת טקסט עם מטא-דאטה."""
        from services.embedding_service import _prepare_text_for_embedding

        result = _prepare_text_for_embedding(
            code="print('hello')",
            file_name="test.py",
            description="A test file",
            tags=["python", "test"],
            programming_language="python",
        )

        assert "File: test.py" in result
        assert "Language: python" in result
        assert "Description: A test file" in result
        assert "print('hello')" in result

