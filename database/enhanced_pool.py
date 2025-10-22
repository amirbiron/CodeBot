"""
Enhanced Connection Pool Manager for MongoDB
מנהל Connection Pool משופר ל-MongoDB
"""

import os
import logging
from typing import Optional, Dict, Any, Tuple
from contextlib import contextmanager
import time

from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure, AutoReconnect
from config import config

try:
    from observability import emit_event
except Exception:
    def emit_event(event: str, severity: str = "info", **fields):
        return None

logger = logging.getLogger(__name__)

# Prometheus metrics (optional)
try:
    from prometheus_client import Counter, Gauge, Histogram
    
    pool_connections_active = Gauge(
        'mongodb_pool_connections_active',
        'Active MongoDB connections'
    )
    pool_connections_available = Gauge(
        'mongodb_pool_connections_available', 
        'Available MongoDB connections'
    )
    pool_wait_time = Histogram(
        'mongodb_pool_wait_seconds',
        'Time waiting for MongoDB connection'
    )
    pool_errors = Counter(
        'mongodb_pool_errors_total',
        'MongoDB pool errors',
        ['error_type']
    )
except ImportError:
    # Dummy implementations if prometheus_client not available
    class DummyMetric:
        def set(self, value): pass
        def inc(self, amount=1): pass
        def observe(self, value): pass
        def labels(self, **kwargs): return self
    
    pool_connections_active = DummyMetric()
    pool_connections_available = DummyMetric()
    pool_wait_time = DummyMetric()
    pool_errors = DummyMetric()


class EnhancedMongoPool:
    """
    מנהל Connection Pool משופר ל-MongoDB עם:
    - הגדרות pool דינמיות לפי סביבה
    - retry logic מובנה
    - מוניטורינג מפורט
    - connection warming
    - graceful shutdown
    """
    
    def __init__(self):
        self.client: Optional[MongoClient] = None
        self.db = None
        self._initialized = False
        self._retry_count = 0
        self._last_error_time = 0
        
    def get_optimal_pool_settings(self) -> Dict[str, Any]:
        """
        חישוב הגדרות Pool אופטימליות לפי סביבה וקונפיגורציה
        """
        env = os.getenv('ENVIRONMENT', 'development').lower()
        
        # Base settings
        settings = {
            'maxPoolSize': 50,
            'minPoolSize': 5,
            'maxIdleTimeMS': 60000,  # 1 minute
            'waitQueueTimeoutMS': 10000,  # 10 seconds
            'waitQueueMultiple': 5,
            'serverSelectionTimeoutMS': 5000,
            'connectTimeoutMS': 10000,
            'socketTimeoutMS': 30000,
            'retryWrites': True,
            'retryReads': True,
            'heartbeatFrequencyMS': 10000,
            'minHeartbeatFrequencyMS': 500,
            'appname': f'CodeBot-{env}',
            'compressors': ['zstd', 'snappy', 'zlib'],
            'zlibCompressionLevel': 6,
        }
        
        # Environment-specific adjustments
        if env == 'production':
            settings.update({
                'maxPoolSize': getattr(config, 'MONGODB_MAX_POOL_SIZE', 100),
                'minPoolSize': getattr(config, 'MONGODB_MIN_POOL_SIZE', 10),
                'maxIdleTimeMS': 120000,  # 2 minutes
                'waitQueueTimeoutMS': 15000,  # 15 seconds
            })
        elif env == 'staging':
            settings.update({
                'maxPoolSize': 75,
                'minPoolSize': 7,
                'maxIdleTimeMS': 90000,  # 1.5 minutes
            })
        elif env == 'development':
            settings.update({
                'maxPoolSize': 20,
                'minPoolSize': 2,
                'maxIdleTimeMS': 30000,  # 30 seconds
            })
        
        # TLS/SSL settings if needed
        if any(x in config.MONGODB_URL for x in ['mongodb+srv://', 'ssl=true', 'tls=true']):
            settings.update({
                'tls': True,
                'tlsAllowInvalidCertificates': env == 'development',
            })
        
        return settings
    
    def connect(self, warm_connections: bool = True) -> MongoClient:
        """
        יצירת חיבור עם retry logic ו-connection warming
        """
        if self._initialized and self.client:
            return self.client
        
        settings = self.get_optimal_pool_settings()
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Creating MongoDB connection pool (attempt {attempt + 1}/{max_retries})")
                
                self.client = MongoClient(config.MONGODB_URL, **settings)
                
                # Test connection
                self.client.admin.command('ping')
                
                # Set database
                self.db = self.client[config.DATABASE_NAME]
                
                # Connection warming - create initial connections
                if warm_connections:
                    self._warm_connections(settings['minPoolSize'])
                
                self._initialized = True
                
                emit_event(
                    "mongodb_pool_created",
                    severity="info",
                    max_pool=settings['maxPoolSize'],
                    min_pool=settings['minPoolSize'],
                    environment=os.getenv('ENVIRONMENT', 'unknown')
                )
                
                logger.info(f"MongoDB pool created successfully: max={settings['maxPoolSize']}, min={settings['minPoolSize']}")
                
                return self.client
                
            except (ServerSelectionTimeoutError, ConnectionFailure) as e:
                self._retry_count += 1
                pool_errors.labels(error_type=type(e).__name__).inc()
                
                if attempt < max_retries - 1:
                    logger.warning(f"MongoDB connection attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Failed to create MongoDB pool after {max_retries} attempts")
                    emit_event(
                        "mongodb_pool_creation_failed",
                        severity="error",
                        error=str(e),
                        attempts=max_retries
                    )
                    raise
    
    def _warm_connections(self, num_connections: int):
        """
        Pre-warm connections by executing lightweight queries
        """
        try:
            logger.info(f"Warming up {num_connections} MongoDB connections...")
            
            # Execute parallel pings to create connections
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_connections) as executor:
                futures = [
                    executor.submit(lambda: self.client.admin.command('ping'))
                    for _ in range(num_connections)
                ]
                concurrent.futures.wait(futures, timeout=5)
            
            logger.info("Connection warming completed")
        except Exception as e:
            logger.warning(f"Connection warming failed: {e}")
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """
        קבלת סטטיסטיקות מפורטות על ה-Pool
        """
        if not self.client:
            return {'status': 'disconnected'}
        
        try:
            # Get server status
            server_status = self.client.admin.command('serverStatus')
            connections = server_status.get('connections', {})
            
            # Get topology description
            topology = self.client.topology_description
            
            stats = {
                'status': 'connected',
                'connections': {
                    'current': connections.get('current', 0),
                    'available': connections.get('available', 0),
                    'total_created': connections.get('totalCreated', 0),
                },
                'topology': {
                    'type': str(topology.topology_type),
                    'servers': len(topology.server_descriptions()),
                    'has_primary': topology.has_readable_server(),
                    'has_secondary': topology.has_writable_server(),
                },
                'retry_count': self._retry_count,
            }
            
            # Update Prometheus metrics
            pool_connections_active.set(connections.get('current', 0))
            pool_connections_available.set(connections.get('available', 0))
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get pool stats: {e}")
            return {'status': 'error', 'error': str(e)}
    
    @contextmanager
    def get_database(self):
        """
        Context manager לקבלת database עם error handling
        """
        if not self.client:
            self.connect()
        
        start_time = time.time()
        try:
            pool_wait_time.observe(time.time() - start_time)
            yield self.db
        except AutoReconnect as e:
            logger.warning(f"MongoDB auto-reconnect triggered: {e}")
            pool_errors.labels(error_type='AutoReconnect').inc()
            # Let PyMongo handle the reconnection
            raise
        except Exception as e:
            logger.error(f"Database operation failed: {e}")
            pool_errors.labels(error_type=type(e).__name__).inc()
            raise
    
    def health_check(self) -> Tuple[bool, Dict[str, Any]]:
        """
        בדיקת תקינות מקיפה של ה-Pool
        """
        try:
            start = time.time()
            
            # Basic ping
            self.client.admin.command('ping')
            ping_latency = (time.time() - start) * 1000
            
            # Get pool stats
            stats = self.get_pool_stats()
            
            # Check if we have enough connections
            current_connections = stats['connections']['current']
            available_connections = stats['connections']['available']
            
            health_status = {
                'healthy': True,
                'ping_latency_ms': ping_latency,
                'connections_current': current_connections,
                'connections_available': available_connections,
                'topology_type': stats['topology']['type'],
            }
            
            # Warning conditions
            if ping_latency > 100:
                health_status['warning'] = 'High latency detected'
            
            if available_connections < 10:
                health_status['warning'] = 'Low available connections'
            
            return True, health_status
            
        except Exception as e:
            return False, {'healthy': False, 'error': str(e)}
    
    def graceful_shutdown(self):
        """
        סגירה נקייה של כל החיבורים
        """
        if self.client:
            try:
                logger.info("Performing graceful shutdown of MongoDB pool...")
                
                # Log final stats
                final_stats = self.get_pool_stats()
                logger.info(f"Final pool stats: {final_stats}")
                
                # Close the client
                self.client.close()
                
                emit_event(
                    "mongodb_pool_closed",
                    severity="info",
                    final_stats=final_stats
                )
                
                self.client = None
                self.db = None
                self._initialized = False
                
                logger.info("MongoDB pool closed successfully")
                
            except Exception as e:
                logger.error(f"Error during graceful shutdown: {e}")
    
    def __enter__(self):
        """Support for context manager"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up on context exit"""
        self.graceful_shutdown()


# Singleton instance
enhanced_mongo_pool = EnhancedMongoPool()


# Convenience functions for backward compatibility
def get_enhanced_pool() -> EnhancedMongoPool:
    """Get the enhanced MongoDB pool instance"""
    return enhanced_mongo_pool


def get_database():
    """Get MongoDB database with enhanced pooling"""
    if not enhanced_mongo_pool.client:
        enhanced_mongo_pool.connect()
    return enhanced_mongo_pool.db