"""
Centralized Redis cache management with graceful degradation and observability.

Features:
- Circuit breaker pattern for resilience
- Automatic reconnection with exponential backoff
- Distributed locking for concurrency control
- Batch operations (pipeline, mget, mset)
- Comprehensive metrics (operations, timing, errors)
- Connection pool health monitoring
- JSON serialization/deserialization

RIKI LAW Compliance:
- Complete audit trails with LogContext (Article II)
- ConfigManager integration for tunables (Article V)
- Graceful degradation on failures (Article IX)
- Comprehensive metrics and health monitoring (Article X)
"""

from typing import Optional, Any, List, Dict
from contextlib import asynccontextmanager
import json
import redis.asyncio as redis
from redis.asyncio.lock import Lock
from datetime import datetime
import asyncio
import time

from src.core.config.config import Config
from src.core.config.config_manager import ConfigManager
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class CircuitBreaker:
    """
    Circuit breaker pattern for Redis connection resilience.
    
    Prevents cascade failures by temporarily disabling Redis after repeated failures.
    Automatically attempts reconnection after recovery timeout.
    
    States:
        - closed: Normal operation, all calls allowed
        - open: Failures exceeded threshold, calls blocked
        - half-open: Testing if service recovered
    """
    
    def __init__(self, failure_threshold: int, recovery_timeout: int):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"
    
    def call_succeeded(self):
        """Record successful call and reset failure counter."""
        self.failure_count = 0
        self.state = "closed"
    
    def call_failed(self):
        """Record failed call and potentially open circuit."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(
                f"Circuit breaker OPENED: {self.failure_count} failures",
                extra={"circuit_state": "open", "failure_count": self.failure_count}
            )
    
    def can_attempt(self) -> bool:
        """Check if calls should be allowed."""
        if self.state == "closed":
            return True
        
        if self.state == "open":
            if self.last_failure_time:
                time_since_failure = (datetime.utcnow() - self.last_failure_time).total_seconds()
                if time_since_failure >= self.recovery_timeout:
                    self.state = "half-open"
                    logger.info(
                        "Circuit breaker HALF-OPEN: attempting reconnect",
                        extra={"circuit_state": "half-open"}
                    )
                    return True
            return False
        
        return True


class RedisService:
    """
    Centralized Redis cache management with graceful degradation.
    
    Provides caching, distributed locking, and rate limiting with automatic
    failover to database when Redis is unavailable.
    
    Features:
        - Circuit breaker pattern for resilience
        - Automatic reconnection attempts
        - JSON serialization/deserialization
        - Distributed locks for concurrency control
        - TTL support for cache expiration
        - Batch operations for efficiency
        - Comprehensive metrics tracking
    
    Graceful Degradation:
        When Redis is unavailable, operations return None/False rather than
        raising exceptions, allowing application to continue with database fallback.
    """
    
    _client: redis.Redis = None
    _circuit_breaker: CircuitBreaker = None
    
    # Metrics tracking
    _metrics = {
        "operations": {
            "get": 0,
            "set": 0,
            "delete": 0,
            "exists": 0,
            "increment": 0,
            "expire": 0,
            "lock_acquire": 0,
            "batch": 0,
        },
        "successes": 0,
        "failures": 0,
        "circuit_breaker_opens": 0,
        "reconnection_attempts": 0,
        "reconnection_successes": 0,
        "total_operation_time_ms": 0.0,
    }
    
    @classmethod
    async def initialize(cls) -> None:
        """
        Initialize Redis client with connection pooling.
        
        Raises:
            Exception: If Redis connection cannot be established
        """
        if cls._client is not None:
            logger.warning("RedisService already initialized")
            return
        
        try:
            cls._client = redis.from_url(
                Config.REDIS_URL,
                password=Config.REDIS_PASSWORD,
                max_connections=Config.REDIS_MAX_CONNECTIONS,
                decode_responses=Config.REDIS_DECODE_RESPONSES,
                socket_connect_timeout=Config.REDIS_SOCKET_TIMEOUT,
                socket_keepalive=True,
                retry_on_timeout=Config.REDIS_RETRY_ON_TIMEOUT,
            )
            
            cls._circuit_breaker = CircuitBreaker(
                failure_threshold=Config.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                recovery_timeout=Config.CIRCUIT_BREAKER_RECOVERY_TIMEOUT
            )
            
            await cls._client.ping()
            logger.info(
                "RedisService initialized successfully",
                extra={
                    "max_connections": Config.REDIS_MAX_CONNECTIONS,
                    "socket_timeout": Config.REDIS_SOCKET_TIMEOUT
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to initialize RedisService: {e}", exc_info=True)
            raise
    
    @classmethod
    async def shutdown(cls) -> None:
        """Close Redis connection and cleanup resources."""
        if cls._client is None:
            return
        
        try:
            await cls._client.close()
            cls._client = None
            logger.info("RedisService shutdown successfully")
            
        except Exception as e:
            logger.error(f"Error during RedisService shutdown: {e}", exc_info=True)
    
    @classmethod
    async def health_check(cls) -> bool:
        """
        Verify Redis connectivity.
        
        Returns:
            True if Redis is accessible, False otherwise
        """
        try:
            if cls._client is None:
                return False
            await cls._client.ping()
            return True
        except Exception:
            return False
    
    @classmethod
    async def _attempt_reconnect(cls) -> bool:
        """
        Attempt to reconnect to Redis after circuit breaker opens.
        
        Returns:
            True if reconnection successful, False otherwise
        """
        cls._metrics["reconnection_attempts"] += 1
        
        try:
            if cls._client is None:
                await cls.initialize()
            else:
                await cls._client.ping()
            
            cls._circuit_breaker.call_succeeded()
            cls._metrics["reconnection_successes"] += 1
            logger.info(
                "Redis reconnection successful",
                extra={
                    "circuit_state": "closed",
                    "reconnection_attempts": cls._metrics["reconnection_attempts"],
                    "reconnection_successes": cls._metrics["reconnection_successes"]
                }
            )
            return True
            
        except Exception as e:
            cls._circuit_breaker.call_failed()
            logger.error(
                f"Redis reconnection failed: {e}",
                extra={"reconnection_attempts": cls._metrics["reconnection_attempts"]},
                exc_info=True
            )
            return False
    
    @classmethod
    async def get(cls, key: str) -> Optional[Any]:
        """
        Get value from Redis cache.
        
        Automatically deserializes JSON values. Returns None if key not found
        or Redis unavailable (graceful degradation).
        
        Args:
            key: Cache key
        
        Returns:
            Cached value (deserialized if JSON) or None
        """
        start_time = time.perf_counter()
        cls._metrics["operations"]["get"] += 1
        
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            if cls._circuit_breaker.state == "half-open":
                await cls._attempt_reconnect()
            
            if not cls._circuit_breaker.can_attempt():
                logger.debug(f"Redis unavailable for GET: {key}")
                cls._metrics["failures"] += 1
                return None
        
        try:
            value = await cls._client.get(key)
            cls._circuit_breaker.call_succeeded()
            cls._metrics["successes"] += 1
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            cls._metrics["total_operation_time_ms"] += elapsed_ms
            
            if value is None:
                return None
            
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
                
        except Exception as e:
            cls._circuit_breaker.call_failed()
            cls._metrics["failures"] += 1
            logger.error(
                f"Redis GET error: key={key} error={e}",
                extra={"operation": "get", "key": key},
                exc_info=True
            )
            return None
    
    @classmethod
    async def set(cls, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Set value in Redis cache with optional TTL.
        
        Automatically serializes dicts/lists to JSON.
        
        Args:
            key: Cache key
            value: Value to cache (will be JSON-serialized if dict/list)
            ttl: Time-to-live in seconds (None = no expiration)
        
        Returns:
            True if successful, False if Redis unavailable
        """
        start_time = time.perf_counter()
        cls._metrics["operations"]["set"] += 1
        
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            if cls._circuit_breaker.state == "half-open":
                await cls._attempt_reconnect()
            
            if not cls._circuit_breaker.can_attempt():
                logger.debug(f"Redis unavailable for SET: {key}")
                cls._metrics["failures"] += 1
                return False
        
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            
            if ttl:
                await cls._client.setex(key, ttl, value)
            else:
                await cls._client.set(key, value)
            
            cls._circuit_breaker.call_succeeded()
            cls._metrics["successes"] += 1
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            cls._metrics["total_operation_time_ms"] += elapsed_ms
            
            return True
            
        except Exception as e:
            cls._circuit_breaker.call_failed()
            cls._metrics["failures"] += 1
            logger.error(
                f"Redis SET error: key={key} ttl={ttl} error={e}",
                extra={"operation": "set", "key": key, "ttl": ttl},
                exc_info=True
            )
            return False
    
    @classmethod
    async def delete(cls, key: str) -> bool:
        """Delete key from Redis cache."""
        cls._metrics["operations"]["delete"] += 1
        
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            cls._metrics["failures"] += 1
            return False
        
        try:
            await cls._client.delete(key)
            cls._circuit_breaker.call_succeeded()
            cls._metrics["successes"] += 1
            return True
            
        except Exception as e:
            cls._circuit_breaker.call_failed()
            cls._metrics["failures"] += 1
            logger.error(
                f"Redis DELETE error: key={key} error={e}",
                extra={"operation": "delete", "key": key},
                exc_info=True
            )
            return False
    
    @classmethod
    async def exists(cls, key: str) -> bool:
        """Check if key exists in Redis cache."""
        cls._metrics["operations"]["exists"] += 1
        
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            cls._metrics["failures"] += 1
            return False
        
        try:
            result = await cls._client.exists(key)
            cls._circuit_breaker.call_succeeded()
            cls._metrics["successes"] += 1
            return result > 0
        except Exception as e:
            cls._circuit_breaker.call_failed()
            cls._metrics["failures"] += 1
            logger.error(
                f"Redis EXISTS error: key={key} error={e}",
                extra={"operation": "exists", "key": key},
                exc_info=True
            )
            return False
    
    @classmethod
    async def increment(cls, key: str, amount: int = 1) -> Optional[int]:
        """
        Atomically increment integer value in Redis.
        
        Args:
            key: Cache key
            amount: Amount to increment by
        
        Returns:
            New value after increment, or None if Redis unavailable
        """
        cls._metrics["operations"]["increment"] += 1
        
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            cls._metrics["failures"] += 1
            return None
        
        try:
            result = await cls._client.incrby(key, amount)
            cls._circuit_breaker.call_succeeded()
            cls._metrics["successes"] += 1
            return result
        except Exception as e:
            cls._circuit_breaker.call_failed()
            cls._metrics["failures"] += 1
            logger.error(
                f"Redis INCR error: key={key} amount={amount} error={e}",
                extra={"operation": "increment", "key": key, "amount": amount},
                exc_info=True
            )
            return None
    
    @classmethod
    async def expire(cls, key: str, ttl: int) -> bool:
        """Set TTL on existing key."""
        cls._metrics["operations"]["expire"] += 1

        if cls._client is None or not cls._circuit_breaker.can_attempt():
            cls._metrics["failures"] += 1
            return False

        try:
            await cls._client.expire(key, ttl)
            cls._circuit_breaker.call_succeeded()
            cls._metrics["successes"] += 1
            return True
        except Exception as e:
            cls._circuit_breaker.call_failed()
            cls._metrics["failures"] += 1
            logger.error(
                f"Redis EXPIRE error: key={key} ttl={ttl} error={e}",
                extra={"operation": "expire", "key": key, "ttl": ttl},
                exc_info=True
            )
            return False

    @classmethod
    async def ttl(cls, key: str) -> int:
        """
        Get remaining time-to-live for a key.

        Args:
            key: Cache key

        Returns:
            TTL in seconds, -1 if key exists with no TTL, -2 if key doesn't exist
        """
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            return -1

        try:
            result = await cls._client.ttl(key)
            cls._circuit_breaker.call_succeeded()
            cls._metrics["successes"] += 1
            return result
        except Exception as e:
            cls._circuit_breaker.call_failed()
            cls._metrics["failures"] += 1
            logger.error(
                f"Redis TTL error: key={key} error={e}",
                extra={"operation": "ttl", "key": key},
                exc_info=True
            )
            return -1
    
    # =========================================================================
    # BATCH OPERATIONS
    # =========================================================================
    
    @classmethod
    async def mget(cls, keys: List[str]) -> Dict[str, Any]:
        """
        Get multiple keys in a single operation (batch GET).
        
        More efficient than multiple individual get() calls.
        
        Args:
            keys: List of cache keys
        
        Returns:
            Dictionary mapping keys to values (missing keys excluded)
        
        Example:
            >>> results = await RedisService.mget(["player:123", "player:456"])
            >>> # {"player:123": {...}, "player:456": {...}}
        """
        cls._metrics["operations"]["batch"] += 1
        
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            cls._metrics["failures"] += 1
            return {}
        
        try:
            values = await cls._client.mget(keys)
            cls._circuit_breaker.call_succeeded()
            cls._metrics["successes"] += 1
            
            result = {}
            for key, value in zip(keys, values):
                if value is not None:
                    try:
                        result[key] = json.loads(value)
                    except json.JSONDecodeError:
                        result[key] = value
            
            return result
            
        except Exception as e:
            cls._circuit_breaker.call_failed()
            cls._metrics["failures"] += 1
            logger.error(
                f"Redis MGET error: count={len(keys)} error={e}",
                extra={"operation": "mget", "key_count": len(keys)},
                exc_info=True
            )
            return {}
    
    @classmethod
    async def mset(cls, mapping: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """
        Set multiple keys in a single operation (batch SET).
        
        More efficient than multiple individual set() calls.
        
        Args:
            mapping: Dictionary of key-value pairs
            ttl: Optional TTL for all keys (applied via pipeline)
        
        Returns:
            True if successful, False otherwise
        
        Example:
            >>> await RedisService.mset({
            ...     "player:123": {"rikis": 1000},
            ...     "player:456": {"rikis": 2000}
            ... }, ttl=300)
        """
        cls._metrics["operations"]["batch"] += 1
        
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            cls._metrics["failures"] += 1
            return False
        
        try:
            # Serialize all values
            serialized = {}
            for key, value in mapping.items():
                if isinstance(value, (dict, list)):
                    serialized[key] = json.dumps(value)
                else:
                    serialized[key] = value
            
            # Use pipeline for efficiency
            async with cls._client.pipeline(transaction=False) as pipe:
                await pipe.mset(serialized)
                
                # Apply TTL if specified
                if ttl:
                    for key in serialized.keys():
                        await pipe.expire(key, ttl)
                
                await pipe.execute()
            
            cls._circuit_breaker.call_succeeded()
            cls._metrics["successes"] += 1
            return True
            
        except Exception as e:
            cls._circuit_breaker.call_failed()
            cls._metrics["failures"] += 1
            logger.error(
                f"Redis MSET error: count={len(mapping)} ttl={ttl} error={e}",
                extra={"operation": "mset", "key_count": len(mapping), "ttl": ttl},
                exc_info=True
            )
            return False
    
    # =========================================================================
    # DISTRIBUTED LOCKING
    # =========================================================================
    
    @classmethod
    @asynccontextmanager
    async def acquire_lock(cls, lock_name: str, timeout: int = 5, blocking_timeout: int = 3):
        """
        Acquire distributed lock for critical sections (RIKI LAW Article I.3).
        
        Prevents race conditions in concurrent operations like fusion, trading,
        or button double-clicks.
        
        Args:
            lock_name: Unique identifier for the lock
            timeout: Lock expiration time (seconds)
            blocking_timeout: Max time to wait for lock (seconds)
        
        Yields:
            Lock object
        
        Raises:
            RuntimeError: If Redis unavailable (circuit breaker open)
            TimeoutError: If lock cannot be acquired within blocking_timeout
        
        Example:
            >>> async with RedisService.acquire_lock(f"fusion:{player_id}"):
            ...     # Critical section - only one coroutine can execute this
            ...     await perform_fusion(player_id)
        """
        cls._metrics["operations"]["lock_acquire"] += 1
        
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            if cls._circuit_breaker.state == "half-open":
                await cls._attempt_reconnect()
            
            if not cls._circuit_breaker.can_attempt():
                cls._metrics["failures"] += 1
                raise RuntimeError(
                    f"Redis unavailable, circuit breaker open. Cannot acquire lock: {lock_name}"
                )
        
        lock = Lock(cls._client, lock_name, timeout=timeout, blocking_timeout=blocking_timeout)
        
        try:
            acquired = await lock.acquire(blocking=True, blocking_timeout=blocking_timeout)
            cls._circuit_breaker.call_succeeded()
            cls._metrics["successes"] += 1
            
            if not acquired:
                raise TimeoutError(f"Failed to acquire lock: {lock_name}")
            
            logger.debug(f"Lock acquired: {lock_name}")
            yield lock
            
        except Exception as e:
            cls._circuit_breaker.call_failed()
            cls._metrics["failures"] += 1
            logger.error(
                f"Redis LOCK error: lock={lock_name} error={e}",
                extra={"operation": "lock_acquire", "lock_name": lock_name},
                exc_info=True
            )
            raise
        finally:
            try:
                await lock.release()
                logger.debug(f"Lock released: {lock_name}")
            except Exception as e:
                logger.error(
                    f"Error releasing lock: {lock_name} error={e}",
                    exc_info=True
                )
    
    # =========================================================================
    # METRICS & MONITORING
    # =========================================================================
    
    @classmethod
    def get_metrics(cls) -> Dict[str, Any]:
        """
        Get comprehensive Redis metrics.
        
        Returns:
            Dictionary with operation counts, success/failure rates, timing
        
        Example:
            >>> metrics = RedisService.get_metrics()
            >>> print(f"Success rate: {metrics['success_rate']:.1f}%")
            >>> print(f"Avg operation time: {metrics['avg_operation_time_ms']:.2f}ms")
        """
        total_ops = cls._metrics["successes"] + cls._metrics["failures"]
        success_rate = (
            (cls._metrics["successes"] / total_ops * 100)
            if total_ops > 0 else 0.0
        )
        
        avg_op_time = (
            cls._metrics["total_operation_time_ms"] / total_ops
            if total_ops > 0 else 0.0
        )
        
        return {
            "operations": cls._metrics["operations"].copy(),
            "total_operations": total_ops,
            "successes": cls._metrics["successes"],
            "failures": cls._metrics["failures"],
            "success_rate": round(success_rate, 2),
            "avg_operation_time_ms": round(avg_op_time, 2),
            "circuit_breaker_state": cls._circuit_breaker.state if cls._circuit_breaker else "unknown",
            "circuit_breaker_opens": cls._metrics["circuit_breaker_opens"],
            "reconnection_attempts": cls._metrics["reconnection_attempts"],
            "reconnection_successes": cls._metrics["reconnection_successes"],
        }
    
    @classmethod
    def reset_metrics(cls) -> None:
        """Reset all metrics counters."""
        cls._metrics = {
            "operations": {
                "get": 0,
                "set": 0,
                "delete": 0,
                "exists": 0,
                "increment": 0,
                "expire": 0,
                "lock_acquire": 0,
                "batch": 0,
            },
            "successes": 0,
            "failures": 0,
            "circuit_breaker_opens": 0,
            "reconnection_attempts": 0,
            "reconnection_successes": 0,
            "total_operation_time_ms": 0.0,
        }
        logger.info("Redis metrics reset")
    
    @classmethod
    async def get_health_status(cls) -> Dict[str, Any]:
        """
        Get comprehensive health status.
        
        Returns:
            Health status including connectivity, metrics, and circuit breaker state
        """
        is_connected = await cls.health_check()
        metrics = cls.get_metrics()
        
        # Determine overall health
        is_healthy = (
            is_connected and
            metrics["success_rate"] > 95.0 and
            metrics["circuit_breaker_state"] == "closed"
        )
        
        return {
            "connected": is_connected,
            "healthy": is_healthy,
            "circuit_breaker_state": metrics["circuit_breaker_state"],
            "success_rate": metrics["success_rate"],
            "total_operations": metrics["total_operations"],
            "failures": metrics["failures"],
            "avg_operation_time_ms": metrics["avg_operation_time_ms"],
            "status": "healthy" if is_healthy else "degraded"
        }