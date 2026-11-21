"""
Connection Pool Health Monitor
מוניטור בריאות ל-Connection Pools
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Import pool managers
try:
    from database.enhanced_pool import enhanced_mongo_pool
except ImportError:
    enhanced_mongo_pool = None

try:
    from cache.enhanced_redis_pool import enhanced_redis_pool
except ImportError:
    enhanced_redis_pool = None

# Prometheus metrics
try:
    from prometheus_client import Gauge, Counter, Histogram, Summary
    
    pool_health_status = Gauge(
        'connection_pool_health_status',
        'Pool health status (1=healthy, 0=unhealthy)',
        ['service']
    )
    pool_latency = Histogram(
        'connection_pool_latency_ms',
        'Pool latency in milliseconds',
        ['service'],
        buckets=[5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000]
    )
    pool_health_checks = Counter(
        'connection_pool_health_checks_total',
        'Total health checks performed',
        ['service', 'status']
    )
except ImportError:
    # Dummy implementations
    class DummyMetric:
        def set(self, value): pass
        def inc(self, amount=1): pass
        def observe(self, value): pass
        def labels(self, **kwargs): return self
    
    pool_health_status = DummyMetric()
    pool_latency = DummyMetric()
    pool_health_checks = DummyMetric()


class PoolHealthMonitor:
    """
    מוניטור בריאות מרכזי לכל ה-Connection Pools
    """
    
    def __init__(self):
        self.monitoring_interval = 30  # seconds
        self.alert_threshold = 3  # consecutive failures before alert
        self.failure_counts: Dict[str, int] = {}
        self.last_check_results: Dict[str, Dict[str, Any]] = {}
        self.monitoring_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start_monitoring(self):
        """
        Start continuous health monitoring
        """
        if self._running:
            logger.warning("Pool health monitoring already running")
            return
        
        self._running = True
        logger.info("Starting connection pool health monitoring")
        
        self.monitoring_task = asyncio.create_task(self._monitor_loop())
    
    async def stop_monitoring(self):
        """
        Stop health monitoring
        """
        self._running = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Pool health monitoring stopped")
    
    async def _monitor_loop(self):
        """
        Main monitoring loop
        """
        while self._running:
            try:
                # Check all pools
                results = await self.check_all_pools()
                
                # Update metrics and check for alerts
                self._process_results(results)
                
                # Wait for next check
                await asyncio.sleep(self.monitoring_interval)
                
            except Exception as e:
                logger.error(f"Error in health monitoring loop: {e}")
                await asyncio.sleep(self.monitoring_interval)
    
    async def check_all_pools(self) -> Dict[str, Dict[str, Any]]:
        """
        Check health of all connection pools
        """
        results = {}
        
        # Check MongoDB pool
        if enhanced_mongo_pool:
            results['mongodb'] = await self._check_mongodb_health()
        
        # Check Redis pool
        if enhanced_redis_pool:
            results['redis'] = await self._check_redis_health()
        
        # Check HTTP pools (if needed)
        results['http'] = await self._check_http_health()
        
        self.last_check_results = results
        return results
    
    async def _check_mongodb_health(self) -> Dict[str, Any]:
        """
        Check MongoDB pool health
        """
        try:
            start = time.time()
            is_healthy, details = enhanced_mongo_pool.health_check()
            check_duration = (time.time() - start) * 1000
            
            result = {
                'healthy': is_healthy,
                'check_duration_ms': check_duration,
                'timestamp': datetime.now().isoformat(),
                **details
            }
            
            # Update metrics
            pool_health_status.labels(service='mongodb').set(1 if is_healthy else 0)
            pool_latency.labels(service='mongodb').observe(details.get('ping_latency_ms', 0))
            pool_health_checks.labels(service='mongodb', status='success' if is_healthy else 'failure').inc()
            
            return result
            
        except Exception as e:
            logger.error(f"MongoDB health check failed: {e}")
            pool_health_status.labels(service='mongodb').set(0)
            pool_health_checks.labels(service='mongodb', status='error').inc()
            
            return {
                'healthy': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    async def _check_redis_health(self) -> Dict[str, Any]:
        """
        Check Redis pool health
        """
        try:
            start = time.time()
            is_healthy, details = enhanced_redis_pool.health_check()
            check_duration = (time.time() - start) * 1000
            
            result = {
                'healthy': is_healthy,
                'check_duration_ms': check_duration,
                'timestamp': datetime.now().isoformat(),
                **details
            }
            
            # Update metrics
            pool_health_status.labels(service='redis').set(1 if is_healthy else 0)
            pool_latency.labels(service='redis').observe(details.get('ping_latency_ms', 0))
            pool_health_checks.labels(service='redis', status='success' if is_healthy else 'failure').inc()
            
            return result
            
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            pool_health_status.labels(service='redis').set(0)
            pool_health_checks.labels(service='redis', status='error').inc()
            
            return {
                'healthy': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    async def _check_http_health(self) -> Dict[str, Any]:
        """
        Check HTTP connection pools health
        """
        # Placeholder for HTTP pool health checks
        # This would check aiohttp connector pools
        return {
            'healthy': True,
            'timestamp': datetime.now().isoformat(),
            'note': 'HTTP pool monitoring not yet implemented'
        }
    
    def _process_results(self, results: Dict[str, Dict[str, Any]]):
        """
        Process health check results and trigger alerts if needed
        """
        for service, result in results.items():
            if not result.get('healthy', False):
                # Increment failure count
                self.failure_counts[service] = self.failure_counts.get(service, 0) + 1
                
                # Check if we should alert
                if self.failure_counts[service] >= self.alert_threshold:
                    self._trigger_alert(service, result)
            else:
                # Reset failure count on success
                self.failure_counts[service] = 0
    
    def _trigger_alert(self, service: str, result: Dict[str, Any]):
        """
        Trigger an alert for unhealthy pool
        """
        logger.error(f"ALERT: {service} pool unhealthy for {self.failure_counts[service]} consecutive checks")
        
        # Here you would integrate with your alerting system
        # For example: send to Telegram, PagerDuty, etc.
        
        # Try to auto-recover
        asyncio.create_task(self._attempt_recovery(service))
    
    async def _attempt_recovery(self, service: str):
        """
        Attempt to recover an unhealthy pool
        """
        logger.info(f"Attempting to recover {service} pool...")
        
        try:
            if service == 'mongodb' and enhanced_mongo_pool:
                # Force reconnection
                enhanced_mongo_pool.graceful_shutdown()
                enhanced_mongo_pool.connect()
                logger.info("MongoDB pool recovery attempted")
                
            elif service == 'redis' and enhanced_redis_pool:
                # Force reconnection
                enhanced_redis_pool.graceful_shutdown()
                enhanced_redis_pool.connect()
                logger.info("Redis pool recovery attempted")
                
        except Exception as e:
            logger.error(f"Failed to recover {service} pool: {e}")
    
    def get_status_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all pool statuses
        """
        summary = {
            'timestamp': datetime.now().isoformat(),
            'pools': {}
        }
        
        for service, result in self.last_check_results.items():
            summary['pools'][service] = {
                'healthy': result.get('healthy', False),
                'last_check': result.get('timestamp', 'Never'),
                'consecutive_failures': self.failure_counts.get(service, 0)
            }
            
            # Add specific details based on service
            if service == 'mongodb' and 'connections' in result:
                summary['pools'][service]['connections'] = result['connections']
            elif service == 'redis' and 'connections_active' in result:
                summary['pools'][service]['connections_active'] = result['connections_active']
        
        return summary
    
    async def perform_load_test(self, service: str, iterations: int = 100) -> Dict[str, Any]:
        """
        Perform a load test on a specific pool
        """
        logger.info(f"Starting load test for {service} with {iterations} iterations")
        
        if service == 'mongodb' and enhanced_mongo_pool:
            return await self._load_test_mongodb(iterations)
        elif service == 'redis' and enhanced_redis_pool:
            return await self._load_test_redis(iterations)
        else:
            return {'error': f'Unknown service: {service}'}
    
    async def _load_test_mongodb(self, iterations: int) -> Dict[str, Any]:
        """
        Load test MongoDB pool
        """
        latencies = []
        errors = 0
        
        async def single_operation():
            try:
                start = time.time()
                with enhanced_mongo_pool.get_database() as db:
                    # Simple ping operation
                    db.client.admin.command('ping')
                latencies.append((time.time() - start) * 1000)
                return True
            except Exception as e:
                logger.debug(f"MongoDB load test operation failed: {e}")
                return False
        
        # Run operations concurrently
        tasks = [single_operation() for _ in range(iterations)]
        results = await asyncio.gather(*tasks)
        
        errors = sum(1 for r in results if not r)
        
        if latencies:
            import statistics
            return {
                'service': 'mongodb',
                'iterations': iterations,
                'successful': len(latencies),
                'errors': errors,
                'latency_stats': {
                    'mean_ms': statistics.mean(latencies),
                    'median_ms': statistics.median(latencies),
                    'min_ms': min(latencies),
                    'max_ms': max(latencies),
                    'stdev_ms': statistics.stdev(latencies) if len(latencies) > 1 else 0
                }
            }
        else:
            return {
                'service': 'mongodb',
                'iterations': iterations,
                'errors': errors,
                'error': 'All operations failed'
            }
    
    async def _load_test_redis(self, iterations: int) -> Dict[str, Any]:
        """
        Load test Redis pool
        """
        latencies = []
        errors = 0
        
        async def single_operation():
            try:
                start = time.time()
                with enhanced_redis_pool.get_client() as client:
                    # Simple ping operation
                    client.ping()
                latencies.append((time.time() - start) * 1000)
                return True
            except Exception as e:
                logger.debug(f"Redis load test operation failed: {e}")
                return False
        
        # Run operations concurrently
        tasks = [single_operation() for _ in range(iterations)]
        results = await asyncio.gather(*tasks)
        
        errors = sum(1 for r in results if not r)
        
        if latencies:
            import statistics
            return {
                'service': 'redis',
                'iterations': iterations,
                'successful': len(latencies),
                'errors': errors,
                'latency_stats': {
                    'mean_ms': statistics.mean(latencies),
                    'median_ms': statistics.median(latencies),
                    'min_ms': min(latencies),
                    'max_ms': max(latencies),
                    'stdev_ms': statistics.stdev(latencies) if len(latencies) > 1 else 0
                }
            }
        else:
            return {
                'service': 'redis',
                'iterations': iterations,
                'errors': errors,
                'error': 'All operations failed'
            }


# Singleton instance
pool_health_monitor = PoolHealthMonitor()


# Convenience functions
async def start_monitoring():
    """Start pool health monitoring"""
    await pool_health_monitor.start_monitoring()


async def stop_monitoring():
    """Stop pool health monitoring"""
    await pool_health_monitor.stop_monitoring()


def get_pool_status():
    """Get current status of all pools"""
    return pool_health_monitor.get_status_summary()


async def run_load_test(service: str, iterations: int = 100):
    """Run a load test on a specific pool"""
    return await pool_health_monitor.perform_load_test(service, iterations)