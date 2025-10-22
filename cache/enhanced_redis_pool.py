"""
Enhanced Redis Connection Pool Manager
מנהל Connection Pool משופר ל-Redis
"""

import os
import logging
import time
from typing import Optional, Dict, Any, Union
import ssl
from contextlib import contextmanager

try:
    import redis
    from redis.connection import ConnectionPool
    from redis.retry import Retry
    from redis.backoff import ExponentialBackoff
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None
    ConnectionPool = None

from config import config

logger = logging.getLogger(__name__)

# Prometheus metrics
try:
    from prometheus_client import Counter, Gauge, Histogram
    
    redis_pool_connections_created = Gauge(
        'redis_pool_connections_created',
        'Total Redis connections created'
    )
    redis_pool_connections_active = Gauge(
        'redis_pool_connections_active',
        'Active Redis connections'
    )
    redis_pool_connections_idle = Gauge(
        'redis_pool_connections_idle',
        'Idle Redis connections'
    )
    redis_command_duration = Histogram(
        'redis_command_duration_seconds',
        'Redis command execution time',
        ['command']
    )
    redis_pool_errors = Counter(
        'redis_pool_errors_total',
        'Redis pool errors',
        ['error_type']
    )
except ImportError:
    # Dummy implementations
    class DummyMetric:
        def set(self, value): pass
        def inc(self, amount=1): pass
        def observe(self, value): pass
        def labels(self, **kwargs): return self
    
    redis_pool_connections_created = DummyMetric()
    redis_pool_connections_active = DummyMetric()
    redis_pool_connections_idle = DummyMetric()
    redis_command_duration = DummyMetric()
    redis_pool_errors = DummyMetric()


class EnhancedRedisPool:
    """
    מנהל Connection Pool משופר ל-Redis עם:
    - Connection pooling אופטימלי
    - Retry logic מתקדם
    - Health checks אוטומטיים
    - מוניטורינג מפורט
    - Circuit breaker pattern
    """
    
    def __init__(self):
        self.pool: Optional[ConnectionPool] = None
        self.client: Optional[redis.Redis] = None
        self._initialized = False
        self._circuit_breaker_open = False
        self._last_error_time = 0
        self._error_count = 0
        self._max_errors = 5
        self._circuit_reset_time = 60  # seconds
    
    def _parse_redis_url(self) -> Dict[str, Any]:
        """
        Parse Redis URL to connection parameters
        """
        if not config.REDIS_URL:
            return {}
        
        from urllib.parse import urlparse
        parsed = urlparse(config.REDIS_URL)
        
        params = {
            'host': parsed.hostname or 'localhost',
            'port': parsed.port or 6379,
            'db': 0,
        }
        
        if parsed.password:
            params['password'] = parsed.password
        
        if parsed.username:
            params['username'] = parsed.username
        
        # Parse query parameters
        if parsed.query:
            import urllib.parse
            query_params = urllib.parse.parse_qs(parsed.query)
            if 'db' in query_params:
                params['db'] = int(query_params['db'][0])
        
        return params
    
    def get_pool_settings(self) -> Dict[str, Any]:
        """
        Get optimized pool settings based on environment
        """
        env = os.getenv('ENVIRONMENT', 'development').lower()
        
        # Base settings
        settings = {
            'max_connections': config.REDIS_MAX_CONNECTIONS or 50,
            'socket_keepalive': True,
            'socket_keepalive_options': {
                # TCP keepalive settings
                1: 1,  # TCP_KEEPIDLE (seconds before sending keepalive probes)
                2: 1,  # TCP_KEEPINTVL (interval between keepalive probes)
                3: 5,  # TCP_KEEPCNT (failed keepalive probes before declaring dead)
            },
            'socket_connect_timeout': config.REDIS_CONNECT_TIMEOUT or 5.0,
            'socket_timeout': config.REDIS_SOCKET_TIMEOUT or 5.0,
            'retry_on_timeout': True,
            'retry_on_error': [ConnectionError, TimeoutError],
            'health_check_interval': 30,
            'encoding': 'utf-8',
            'decode_responses': True,
        }
        
        # Environment-specific adjustments
        if env == 'production':
            settings.update({
                'max_connections': 100,
                'socket_connect_timeout': 10.0,
                'socket_timeout': 10.0,
                'health_check_interval': 15,
            })
        elif env == 'staging':
            settings.update({
                'max_connections': 75,
                'health_check_interval': 20,
            })
        elif env == 'development':
            settings.update({
                'max_connections': 20,
                'health_check_interval': 60,
            })
        
        # SSL/TLS settings if needed
        if config.REDIS_URL and ('rediss://' in config.REDIS_URL or 'ssl=true' in config.REDIS_URL):
            settings.update({
                'connection_class': redis.SSLConnection if redis else None,
                'ssl_cert_reqs': ssl.CERT_REQUIRED,
                'ssl_ca_certs': '/etc/ssl/certs/ca-certificates.crt',
                'ssl_check_hostname': env != 'development',
            })
        
        return settings
    
    def create_pool(self) -> Optional[ConnectionPool]:
        """
        Create optimized Redis connection pool
        """
        if not REDIS_AVAILABLE:
            logger.warning("Redis module not available, skipping pool creation")
            return None
        
        if not config.REDIS_URL:
            logger.info("Redis URL not configured, skipping pool creation")
            return None
        
        try:
            # Parse connection parameters
            conn_params = self._parse_redis_url()
            pool_settings = self.get_pool_settings()
            
            # Merge parameters
            pool_kwargs = {**conn_params, **pool_settings}
            
            logger.info(f"Creating Redis pool with max_connections={pool_kwargs.get('max_connections')}")
            
            # Create the pool
            pool = ConnectionPool(**pool_kwargs)
            
            logger.info("Redis connection pool created successfully")
            return pool
            
        except Exception as e:
            logger.error(f"Failed to create Redis pool: {e}")
            redis_pool_errors.labels(error_type='pool_creation').inc()
            return None
    
    def connect(self) -> Optional[redis.Redis]:
        """
        Get or create Redis client with connection pool
        """
        # Circuit breaker check
        if self._circuit_breaker_open:
            if time.time() - self._last_error_time < self._circuit_reset_time:
                logger.warning("Circuit breaker is open, skipping Redis connection")
                return None
            else:
                # Try to reset circuit breaker
                logger.info("Attempting to close circuit breaker")
                self._circuit_breaker_open = False
                self._error_count = 0
        
        if self._initialized and self.client:
            return self.client
        
        if not REDIS_AVAILABLE:
            return None
        
        try:
            # Create pool if needed
            if not self.pool:
                self.pool = self.create_pool()
                if not self.pool:
                    return None
            
            # Create client with retry logic
            self.client = redis.Redis(
                connection_pool=self.pool,
                retry_on_timeout=True,
                retry=Retry(
                    backoff=ExponentialBackoff(base=0.1, cap=5.0),
                    retries=3,
                ),
            )
            
            # Test connection
            self.client.ping()
            
            self._initialized = True
            self._error_count = 0
            
            logger.info("Redis client connected successfully")
            return self.client
            
        except Exception as e:
            self._error_count += 1
            self._last_error_time = time.time()
            
            if self._error_count >= self._max_errors:
                logger.error(f"Opening circuit breaker after {self._error_count} errors")
                self._circuit_breaker_open = True
            
            logger.error(f"Failed to connect to Redis: {e}")
            redis_pool_errors.labels(error_type='connection').inc()
            return None
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """
        Get detailed pool statistics
        """
        if not self.pool:
            return {'status': 'disconnected'}
        
        try:
            stats = {
                'status': 'connected',
                'created_connections': self.pool.created_connections,
                'available_connections': len(self.pool._available_connections),
                'in_use_connections': len(self.pool._in_use_connections),
                'max_connections': self.pool.max_connections,
                'circuit_breaker_open': self._circuit_breaker_open,
                'error_count': self._error_count,
            }
            
            # Update Prometheus metrics
            redis_pool_connections_created.set(stats['created_connections'])
            redis_pool_connections_active.set(stats['in_use_connections'])
            redis_pool_connections_idle.set(stats['available_connections'])
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get pool stats: {e}")
            return {'status': 'error', 'error': str(e)}
    
    @contextmanager
    def get_client(self):
        """
        Context manager for Redis client with automatic error handling
        """
        client = self.connect()
        if not client:
            # Return a dummy client that does nothing
            class DummyRedis:
                def __getattr__(self, name):
                    return lambda *args, **kwargs: None
            yield DummyRedis()
            return
        
        start_time = time.time()
        try:
            yield client
        except redis.ConnectionError as e:
            logger.error(f"Redis connection error: {e}")
            redis_pool_errors.labels(error_type='ConnectionError').inc()
            self._handle_connection_error()
        except redis.TimeoutError as e:
            logger.error(f"Redis timeout error: {e}")
            redis_pool_errors.labels(error_type='TimeoutError').inc()
        except Exception as e:
            logger.error(f"Redis operation failed: {e}")
            redis_pool_errors.labels(error_type=type(e).__name__).inc()
        finally:
            # Record command duration
            duration = time.time() - start_time
            redis_command_duration.labels(command='operation').observe(duration)
    
    def _handle_connection_error(self):
        """
        Handle connection errors and potentially reset the pool
        """
        try:
            if self.pool:
                # Try to reset the pool
                logger.info("Attempting to reset Redis connection pool")
                self.pool.reset()
                self._initialized = False
                self.client = None
        except Exception as e:
            logger.error(f"Failed to reset Redis pool: {e}")
    
    def health_check(self) -> tuple[bool, Dict[str, Any]]:
        """
        Perform comprehensive health check
        """
        try:
            if not self.client:
                self.connect()
            
            if not self.client:
                return False, {'healthy': False, 'error': 'No connection available'}
            
            start = time.time()
            self.client.ping()
            ping_latency = (time.time() - start) * 1000
            
            # Get pool stats
            stats = self.get_pool_stats()
            
            # Get Redis info
            info = self.client.info()
            
            health_status = {
                'healthy': True,
                'ping_latency_ms': ping_latency,
                'connections_active': stats.get('in_use_connections', 0),
                'connections_idle': stats.get('available_connections', 0),
                'used_memory_mb': info.get('used_memory', 0) / (1024 * 1024),
                'connected_clients': info.get('connected_clients', 0),
                'instantaneous_ops_per_sec': info.get('instantaneous_ops_per_sec', 0),
            }
            
            # Warning conditions
            if ping_latency > 50:
                health_status['warning'] = 'High latency detected'
            
            if stats.get('available_connections', 0) < 5:
                health_status['warning'] = 'Low available connections'
            
            return True, health_status
            
        except Exception as e:
            return False, {'healthy': False, 'error': str(e)}
    
    def warm_connections(self, num_connections: int = 5):
        """
        Pre-warm Redis connections
        """
        try:
            logger.info(f"Warming up {num_connections} Redis connections...")
            
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_connections) as executor:
                futures = [
                    executor.submit(lambda: self.client.ping() if self.client else None)
                    for _ in range(num_connections)
                ]
                concurrent.futures.wait(futures, timeout=5)
            
            logger.info("Redis connection warming completed")
        except Exception as e:
            logger.warning(f"Redis connection warming failed: {e}")
    
    def graceful_shutdown(self):
        """
        Gracefully close all connections
        """
        try:
            if self.client:
                logger.info("Performing graceful shutdown of Redis pool...")
                
                # Log final stats
                final_stats = self.get_pool_stats()
                logger.info(f"Final Redis pool stats: {final_stats}")
                
                # Close the pool
                if self.pool:
                    self.pool.disconnect()
                
                self.client = None
                self.pool = None
                self._initialized = False
                
                logger.info("Redis pool closed successfully")
                
        except Exception as e:
            logger.error(f"Error during Redis graceful shutdown: {e}")


# Singleton instance
enhanced_redis_pool = EnhancedRedisPool()


# Convenience functions
def get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client with enhanced pooling"""
    return enhanced_redis_pool.connect()


def get_redis_pool() -> EnhancedRedisPool:
    """Get the enhanced Redis pool instance"""
    return enhanced_redis_pool