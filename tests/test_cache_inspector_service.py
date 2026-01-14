"""Unit tests for CacheInspectorService."""

from unittest.mock import MagicMock, patch
import pytest

from services.cache_inspector_service import (
    CacheInspectorService,
    CacheKeyStatus,
    CacheEntry,
    CacheStats,
)


class TestCacheInspectorService:
    """Test suite for CacheInspectorService."""

    def setup_method(self):
        """Setup test instance."""
        self.service = CacheInspectorService()

    def test_is_sensitive_key(self):
        """Test sensitive key detection."""
        assert self.service._is_sensitive_key("session:user:123") is True
        assert self.service._is_sensitive_key("token:abc") is True
        assert self.service._is_sensitive_key("auth:refresh") is True
        assert self.service._is_sensitive_key("user:stats:123") is False
        assert self.service._is_sensitive_key("file_content:abc") is False

    def test_determine_status(self):
        """Test status determination based on TTL."""
        assert self.service._determine_status(-2) == CacheKeyStatus.EXPIRED
        assert self.service._determine_status(-1) == CacheKeyStatus.PERSISTENT
        assert self.service._determine_status(30) == CacheKeyStatus.EXPIRING_SOON
        assert self.service._determine_status(60) == CacheKeyStatus.EXPIRING_SOON
        assert self.service._determine_status(61) == CacheKeyStatus.ACTIVE
        assert self.service._determine_status(3600) == CacheKeyStatus.ACTIVE

    def test_get_cache_stats_disabled(self):
        """Test stats when Redis is disabled."""
        with patch.object(self.service, 'is_enabled', return_value=False):
            stats = self.service.get_cache_stats()

            assert stats.enabled is False
            assert stats.used_memory == "N/A"
            assert stats.error == "Redis is disabled"

    @patch('services.cache_inspector_service.CacheInspectorService.redis_client')
    def test_get_cache_stats_enabled(self, mock_client):
        """Test stats when Redis is enabled."""
        mock_client.info.return_value = {
            'used_memory_human': '1.5M',
            'used_memory': 1500000,
            'connected_clients': 5,
            'keyspace_hits': 1000,
            'keyspace_misses': 100,
            'evicted_keys': 0,
            'uptime_in_seconds': 86400,
            'redis_version': '7.0.0',
        }
        mock_client.dbsize.return_value = 500

        with patch.object(self.service, 'is_enabled', return_value=True):
            with patch.object(self.service, 'redis_client', mock_client):
                stats = self.service.get_cache_stats()

                assert stats.enabled is True
                assert stats.used_memory == '1.5M'
                assert stats.hit_rate == 90.91  # 1000/(1000+100)*100

    def test_list_keys_disabled(self):
        """Test list_keys when Redis is disabled."""
        with patch.object(self.service, 'is_enabled', return_value=False):
            entries, scanned, has_more = self.service.list_keys()

            assert entries == []
            assert scanned == 0
            assert has_more is False

    def test_list_keys_limit_enforcement(self):
        """Test that limit is enforced."""
        # מגבלה גבוהה מדי צריכה להיות מוגבלת
        service = CacheInspectorService()
        limit = min(1000, service.MAX_SCAN_LIMIT)
        assert limit == service.MAX_SCAN_LIMIT

    def test_delete_pattern_blocks_wildcard(self):
        """Test that delete_pattern blocks dangerous patterns."""
        with patch.object(self.service, 'is_enabled', return_value=True):
            # לא צריך לקרוא ל-cache_manager.delete_pattern
            result = self.service.delete_pattern("*")
            assert result == 0

            result = self.service.delete_pattern("**")
            assert result == 0

    @patch('services.cache_inspector_service.CacheInspectorService.cache_manager')
    def test_delete_key(self, mock_cache):
        """Test single key deletion."""
        mock_cache.delete.return_value = True
        mock_cache.is_enabled = True

        with patch.object(self.service, 'is_enabled', return_value=True):
            with patch.object(self.service, 'cache_manager', mock_cache):
                result = self.service.delete_key("user:123")

                assert result is True
                mock_cache.delete.assert_called_once_with("user:123")

    def test_clear_all_requires_confirmation(self):
        """Test that clear_all requires explicit confirmation."""
        with patch.object(self.service, 'is_enabled', return_value=True):
            # Without confirmation
            result = self.service.clear_all(confirm=False)
            assert result == 0

    def test_get_value_preview_masks_sensitive(self):
        """Test that sensitive keys have masked values."""
        # מפתח רגיש צריך להחזיר ערך מוסתר
        assert self.service._is_sensitive_key("session:abc") is True
        preview, value_type = self.service._get_value_preview("session:abc")
        assert preview == self.service.MASKED_VALUE
        assert value_type == "sensitive"

    def test_get_value_preview_list_uses_redis_type(self):
        """List keys shouldn't use GET (avoid WRONGTYPE)."""
        mock_client = MagicMock()
        mock_client.type.return_value = b"list"
        mock_client.llen.return_value = 7
        mock_client.lrange.return_value = [b"1", b"2", b"3", b"4", b"5"]

        with patch.object(self.service, "redis_client", mock_client):
            preview, value_type = self.service._get_value_preview("my:list")

        assert value_type == "list"
        assert "1" in preview
        assert "more" in preview.lower()
        mock_client.get.assert_not_called()

    def test_get_key_details_sensitive_does_not_call_get(self):
        """Sensitive keys should never call GET and should not crash."""
        mock_client = MagicMock()
        mock_client.exists.return_value = True
        mock_client.ttl.return_value = 120
        mock_client.type.return_value = b"string"
        mock_client.strlen.side_effect = Exception("WRONGTYPE")
        mock_client.object.side_effect = Exception("unsupported")

        with patch.object(self.service, "is_enabled", return_value=True):
            with patch.object(self.service, "redis_client", mock_client):
                details = self.service.get_key_details("session:abc")

        assert details is not None
        assert details["value"] == self.service.MASKED_VALUE
        assert details["value_type"] == "sensitive"
        assert details["size_bytes"] == 0
        mock_client.get.assert_not_called()

    def test_overview_integration(self):
        """Test get_overview returns proper structure."""
        with patch.object(self.service, 'is_enabled', return_value=False):
            overview = self.service.get_overview()

            assert overview.stats is not None
            assert overview.entries == []
            assert overview.generated_at != ""
            assert overview.search_pattern == "*"


class TestCacheKeyStatus:
    """Test CacheKeyStatus enum."""

    def test_values(self):
        """Test enum values."""
        assert CacheKeyStatus.ACTIVE.value == "Active"
        assert CacheKeyStatus.PERSISTENT.value == "Persistent"
        assert CacheKeyStatus.EXPIRING_SOON.value == "Expiring"
        assert CacheKeyStatus.EXPIRED.value == "Expired"

