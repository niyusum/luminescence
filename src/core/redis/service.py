"""
RedisService: Production-grade async Redis infrastructure for Lumen (2025)

Purpose
-------
Provide a robust, observable, resilience-aware Redis abstraction with:
- Singleton async client with automatic reconnection
- Unified resilience layer wrapping all Redis I/O
- Health monitoring with degradation detection
- Distributed locking with token-based safety and ownership tracking
- KV and JSON operations with built-in metrics and observability
- Integration points for batch operations and rate limiting
- Graceful failure handling and status reporting

Responsibilities
----------------
- Initialize and manage a singleton Redis connection pool
- Provide atomic distributed locking via SET NX + Lua unlock
- Track lock ownership for debugging (lock holders, durations, metadata)
- Expose simple KV and JSON operations (get/set/delete/expire/incr/decr/exists/ttl)
- Route all KV / JSON operations through RedisResilience
- Emit metrics for operations and locks via RedisMetrics
- Expose health, status, batch operations, rate limiter, and resilience utilities

Non-Responsibilities
--------------------
- Business logic of any kind
- Database transactions
- Discord/UI concerns

Lumen 2025 Compliance
---------------------
- Strict layering: pure infrastructure only
- Config-driven: all tunables via ConfigManager
- Observability: structured logs + metrics + operation context
- Concurrency safety: distributed locks for mutations
- Resilience: unified execution layer for all Redis I/O
- Graceful degradation: health checks + clear failure modes
- Domain separation: zero business logic

Configuration Keys
------------------
- core.redis.url                       : str (e.g., "redis://localhost:6379/0")
- core.redis.socket_timeout_seconds    : int (default 5)
- core.redis.encoding                  : str (default "utf-8")
- core.redis.decode_responses          : bool (default True)
- core.redis.default_ttl_seconds       : int (default 300)
- core.redis.lock.default_timeout_sec  : int (default 5)
- core.redis.lock.wait_timeout_sec     : int (default 5)
- core.redis.lock.retry_interval_sec   : float (default 0.1)
- core.redis.max_connections           : int (default 50)

Architecture Notes
------------------
- Uses redis-py 4+ asyncio client with connection pooling
- Lock safety guaranteed via unique UUID tokens + Lua compare-and-delete
- All operations log start/completion/failure with structured context
- Health monitor maintains rolling status for monitoring systems
- Initialization is idempotent and thread-safe via asyncio.Lock
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional, Awaitable, Callable

from redis.asyncio.client import Redis as AsyncRedis  # type: ignore[misc]

from redis.exceptions import RedisError, ConnectionError as RedisConnectionError

from src.core.config import ConfigManager
from src.core.config.config import Config
from src.core.logging.logger import get_logger
from src.core.redis.batch import RedisBatchOperations
from src.core.redis.health_monitor import RedisHealthMonitor
from src.core.redis.metrics import RedisMetrics
from src.core.redis.rate_limiter import RedisRateLimiter
from src.core.redis.resilience import RedisResilience

logger = get_logger(__name__)


class RedisService:
    """
    Production-grade async Redis infrastructure service.

    Provides connection pooling, resilience, distributed locking, health
    monitoring, metrics, and observable KV/JSON operations for the Lumen system.
    """

    _client: Optional[AsyncRedis] = None
    _resilience: Optional[RedisResilience] = None
    _health_monitor: Optional[RedisHealthMonitor] = None
    _batch_ops: Optional[RedisBatchOperations] = None
    _rate_limiter: Optional[RedisRateLimiter] = None
    _init_lock: asyncio.Lock = asyncio.Lock()
    _is_healthy: bool = False

    # Lua script for atomic lock release (compare token + delete)
    _LUA_UNLOCK_SCRIPT = """
    if redis.call("GET", KEYS[1]) == ARGV[1] then
        return redis.call("DEL", KEYS[1])
    else
        return 0
    end
    """

    # ═══════════════════════════════════════════════════════════════════════
    # LIFECYCLE MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    async def initialize(cls) -> None:
        """
        Initialize the singleton Redis client and all Redis subsystem components.

        Idempotent and thread-safe. Safe to call multiple times.

        Raises
        ------
        RuntimeError
            If Redis connection or subsystem initialization fails.
        """
        if cls._client is not None:
            logger.debug("RedisService already initialized, skipping")
            return

        async with cls._init_lock:
            if cls._client is not None:
                return

            url = cls._get_config_str(
                "core.redis.url",
                "redis://localhost:6379/0",
            )
            socket_timeout = cls._get_config_int(
                "core.redis.socket_timeout_seconds",
                5,
            )
            encoding = cls._get_config_str(
                "core.redis.encoding",
                "utf-8",
            )
            decode_responses = cls._get_config_bool(
                "core.redis.decode_responses",
                True,
            )
            max_connections = cls._get_config_int(
                "core.redis.max_connections",
                50,
            )

            start_time = time.monotonic()

            try:
                client: AsyncRedis = AsyncRedis.from_url(
                    url,
                    socket_timeout=socket_timeout,
                    encoding=encoding,
                    decode_responses=decode_responses,
                    max_connections=max_connections,
                    retry_on_timeout=False,  # Higher-level resilience handles retries
                    health_check_interval=30,  # Background health checks
                )

                # Verify connection
                await client.ping()  # type: ignore[misc]

                # Initialize core state
                cls._client = client
                cls._is_healthy = True

                # Initialize resilience and utilities
                cls._resilience = RedisResilience()
                cls._batch_ops = RedisBatchOperations(cls._client)
                cls._rate_limiter = RedisRateLimiter(cls)

                # Initialize and start health monitor
                cls._health_monitor = RedisHealthMonitor(cls)
                await cls._health_monitor.start()

                initialization_time_ms = (time.monotonic() - start_time) * 1000

                logger.info(
                    "RedisService initialized successfully",
                    extra={
                        "url_scheme": url.split("://")[0] if "://" in url else "unknown",
                        "socket_timeout_seconds": socket_timeout,
                        "encoding": encoding,
                        "decode_responses": decode_responses,
                        "max_connections": max_connections,
                        "initialization_time_ms": round(initialization_time_ms, 2),
                    },
                )

            except Exception as exc:
                # Best-effort cleanup
                if cls._health_monitor is not None:
                    try:
                        await cls._health_monitor.stop()
                    except Exception:
                        # Swallow to avoid masking root cause
                        pass

                if cls._client is not None:
                    try:
                        await cls._client.aclose()
                    except Exception:
                        pass

                cls._client = None
                cls._resilience = None
                cls._health_monitor = None
                cls._batch_ops = None
                cls._rate_limiter = None
                cls._is_healthy = False

                logger.critical(
                    "Failed to initialize RedisService",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "url_scheme": url.split("://")[0] if "://" in url else "unknown",
                    },
                    exc_info=True,
                )
                raise RuntimeError(f"Failed to initialize RedisService: {exc}") from exc

    @classmethod
    async def shutdown(cls) -> None:
        """
        Gracefully shutdown the Redis client and all Redis subsystem components.

        Safe to call even if not initialized.
        """
        if cls._client is None and cls._health_monitor is None:
            logger.debug("RedisService not initialized, nothing to shutdown")
            return

        client = cls._client
        health_monitor = cls._health_monitor

        cls._client = None
        cls._resilience = None
        cls._batch_ops = None
        cls._rate_limiter = None
        cls._health_monitor = None
        cls._is_healthy = False

        # Stop health monitor first so it doesn't race shutdown
        if health_monitor is not None:
            try:
                await health_monitor.stop()
                logger.info("RedisHealthMonitor stopped")
            except Exception as exc:
                logger.error(
                    "Error during RedisHealthMonitor shutdown",
                    extra={"error": str(exc), "error_type": type(exc).__name__},
                    exc_info=True,
                )

        if client is not None:
            try:
                await client.aclose()
                logger.info("RedisService shutdown complete")
            except Exception as exc:
                logger.error(
                    "Error during RedisService shutdown",
                    extra={"error": str(exc), "error_type": type(exc).__name__},
                    exc_info=True,
                )

    # ═══════════════════════════════════════════════════════════════════════
    # HEALTH & STATUS
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    async def health_check(cls) -> bool:
        """
        Verify Redis connectivity via PING command.

        Returns
        -------
        bool
            True if Redis is reachable and responsive, False otherwise.
        """
        if cls._client is None:
            logger.warning("Health check failed: RedisService not initialized")
            cls._is_healthy = False
            return False

        try:
            start_time = time.monotonic()
            pong = await cls._client.ping()  # type: ignore[misc]
            latency_ms = (time.monotonic() - start_time) * 1000

            if pong:
                cls._is_healthy = True
                logger.debug(
                    "Redis health check passed",
                    extra={"latency_ms": round(latency_ms, 2)},
                )
                return True

            cls._is_healthy = False
            logger.warning("Redis health check failed: PING returned False")
            return False

        except (RedisConnectionError, RedisError) as exc:
            cls._is_healthy = False
            logger.error(
                "Redis health check failed",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            return False

        except Exception as exc:
            cls._is_healthy = False
            logger.error(
                "Unexpected error during Redis health check",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            return False

    @classmethod
    def is_healthy(cls) -> bool:
        """Return cached health status without performing I/O."""
        return cls._is_healthy

    @classmethod
    def get_status(cls) -> dict[str, Any]:
        """
        Get comprehensive Redis subsystem status snapshot.

        Returns
        -------
        dict[str, Any]
            Status including initialization, health, resilience, health monitor,
            and metrics summary.
        """
        resilience_status: Optional[dict[str, Any]] = None
        health_monitor_status: Optional[dict[str, Any]] = None
        metrics_summary: Optional[dict[str, Any]] = None

        if cls._resilience is not None:
            try:
                resilience_status = cls._resilience.get_status()
            except Exception as exc:
                logger.warning(
                    "Failed to collect RedisResilience status (non-critical)",
                    extra={"error": str(exc), "error_type": type(exc).__name__},
                )

        if cls._health_monitor is not None:
            try:
                health_monitor_status = cls._health_monitor.get_status()
            except Exception as exc:
                logger.warning(
                    "Failed to collect RedisHealthMonitor status (non-critical)",
                    extra={"error": str(exc), "error_type": type(exc).__name__},
                )

        try:
            metrics_summary = RedisMetrics.get_summary()
        except Exception as exc:
            logger.warning(
                "Failed to collect RedisMetrics summary (non-critical)",
                extra={"error": str(exc), "error_type": type(exc).__name__},
            )

        return {
            "initialized": cls._client is not None,
            "healthy": cls._is_healthy,
            "resilience": resilience_status,
            "health_monitor": health_monitor_status,
            "metrics": metrics_summary,
        }

    # ═══════════════════════════════════════════════════════════════════════
    # CLIENT & UTILITIES ACCESS
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def client(cls) -> AsyncRedis:
        """
        Return the singleton Redis client.

        Returns
        -------
        Redis
            The active Redis client instance.

        Raises
        ------
        RuntimeError
            If RedisService has not been initialized.
        """
        if cls._client is None:
            raise RuntimeError(
                "RedisService not initialized. "
                "Call `await RedisService.initialize()` first."
            )
        return cls._client

    @classmethod
    def get_resilience(cls) -> RedisResilience:
        """Get the Redis resilience layer instance."""
        if cls._resilience is None:
            raise RuntimeError("RedisService resilience layer not initialized")
        return cls._resilience

    @classmethod
    def get_batch_operations(cls) -> RedisBatchOperations:
        """Get Redis batch operations utility."""
        if cls._batch_ops is None:
            raise RuntimeError("RedisService batch operations not initialized")
        return cls._batch_ops

    @classmethod
    def get_rate_limiter(cls) -> RedisRateLimiter:
        """Get Redis-based rate limiter utility."""
        if cls._rate_limiter is None:
            raise RuntimeError("RedisService rate limiter not initialized")
        return cls._rate_limiter

    @classmethod
    def get_health_monitor(cls) -> RedisHealthMonitor:
        """Get Redis health monitor instance."""
        if cls._health_monitor is None:
            raise RuntimeError("RedisService health monitor not initialized")
        return cls._health_monitor

    # ═══════════════════════════════════════════════════════════════════════
    # METRICS HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _record_operation_metric(
        operation: str,
        start_time: float,
        success: bool,
    ) -> float:
        """
        Record metrics for a Redis operation.

        Parameters
        ----------
        operation : str
            Logical operation name (e.g., "GET", "SET", "TTL").
        start_time : float
            Monotonic timestamp from which to compute latency.
        success : bool
            Whether the operation succeeded.

        Returns
        -------
        float
            Measured latency in milliseconds.
        """
        latency_ms = (time.monotonic() - start_time) * 1000
        try:
            RedisMetrics.record_operation(operation, latency_ms, success=success)
        except Exception as exc:
            # Metrics failures must never affect mainline behavior
            logger.warning(
                "Failed to record Redis operation metric (non-critical)",
                extra={
                    "operation": operation,
                    "success": success,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
        return latency_ms

    @staticmethod
    def _record_lock_acquisition_metric(
        lock_key: str,
        start_time: float,
        success: bool,
    ) -> float:
        """
        Record metrics for lock acquisition.

        Returns the measured wait time in milliseconds.
        """
        wait_ms = (time.monotonic() - start_time) * 1000
        try:
            RedisMetrics.record_lock_acquisition(lock_key, wait_ms, success=success)
        except Exception as exc:
            logger.warning(
                "Failed to record Redis lock acquisition metric (non-critical)",
                extra={
                    "lock_key": lock_key,
                    "success": success,
                    "wait_ms": round(wait_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
        return wait_ms

    @staticmethod
    def _record_lock_hold_metric(
        lock_key: str,
        hold_start_time: float,
    ) -> float:
        """
        Record metrics for lock hold duration.

        Returns the measured hold time in milliseconds.
        """
        hold_ms = (time.monotonic() - hold_start_time) * 1000
        try:
            RedisMetrics.record_lock_hold(lock_key, hold_ms)
        except Exception as exc:
            logger.warning(
                "Failed to record Redis lock hold metric (non-critical)",
                extra={
                    "lock_key": lock_key,
                    "hold_ms": round(hold_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
        return hold_ms

    # ═══════════════════════════════════════════════════════════════════════
    # KEY-VALUE OPERATIONS (RESILIENCE + METRICS)
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    async def get(cls, key: str) -> Optional[str]:
        """
        Get a string value from Redis.

        Parameters
        ----------
        key : str
            The Redis key to retrieve.

        Returns
        -------
        Optional[str]
            The value if it exists, None otherwise.
        """
        start_time = time.monotonic()
        try:
            result = await cls.get_resilience().execute( 
                operation=(lambda: cls.client().get(key)), # type: Callable[[], Awaitable[Any]]
                operation_name=f"GET:{key}",
            )
            latency_ms = cls._record_operation_metric("GET", start_time, success=True)
            logger.debug(
                "Redis GET operation",
                extra={
                    "key": key,
                    "found": result is not None,
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return result
        except Exception as exc:
            latency_ms = cls._record_operation_metric("GET", start_time, success=False)
            logger.error(
                "Redis GET operation failed",
                extra={
                    "key": key,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

    @classmethod
    async def set(
        cls,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Set a string value in Redis with optional TTL.

        Parameters
        ----------
        key : str
            The Redis key to set.
        value : Any
            The value to store (will be converted to string).
        ttl_seconds : Optional[int]
            Time-to-live in seconds. If None, uses default from config.

        Returns
        -------
        bool
            True if successful, False otherwise.
        """
        if ttl_seconds is None:
            ttl_seconds = cls._get_config_int(
                "core.redis.default_ttl_seconds",
                300,
            )

        start_time = time.monotonic()
        try:
            result = await cls.get_resilience().execute(
                operation=(lambda: cls.client().set(key, value, ex=ttl_seconds)),  # type: Callable[[], Awaitable[Any]]
                operation_name=f"SET:{key}",
            )
            latency_ms = cls._record_operation_metric("SET", start_time, success=True)
            success = bool(result)
            logger.debug(
                "Redis SET operation",
                extra={
                    "key": key,
                    "ttl_seconds": ttl_seconds,
                    "success": success,
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return success
        except Exception as exc:
            latency_ms = cls._record_operation_metric("SET", start_time, success=False)
            logger.error(
                "Redis SET operation failed",
                extra={
                    "key": key,
                    "ttl_seconds": ttl_seconds,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

    @classmethod
    async def delete(cls, key: str) -> int:
        """
        Delete a key from Redis.

        Parameters
        ----------
        key : str
            The Redis key to delete.

        Returns
        -------
        int
            Number of keys deleted (0 or 1).
        """
        start_time = time.monotonic()
        try:
            count = await cls.get_resilience().execute(
                operation=(lambda: cls.client().delete(key)),  # type: Callable[[], Awaitable[Any]]
                operation_name=f"DEL:{key}",
            )
            latency_ms = cls._record_operation_metric(
                "DELETE",
                start_time,
                success=True,
            )
            deleted = int(count)
            logger.debug(
                "Redis DELETE operation",
                extra={
                    "key": key,
                    "deleted_count": deleted,
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return deleted
        except Exception as exc:
            latency_ms = cls._record_operation_metric(
                "DELETE",
                start_time,
                success=False,
            )
            logger.error(
                "Redis DELETE operation failed",
                extra={
                    "key": key,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

    @classmethod
    async def incr(cls, key: str, amount: int = 1) -> int:
        """
        Increment a key's integer value atomically.

        Parameters
        ----------
        key : str
            The Redis key to increment.
        amount : int
            The amount to increment by (default 1).

        Returns
        -------
        int
            The new value after incrementing.
        """
        start_time = time.monotonic()
        try:
            new_value = await cls.get_resilience().execute(
                operation=lambda: cls.client().incrby(key, amount),
                operation_name=f"INCR:{key}",
            )
            latency_ms = cls._record_operation_metric(
                "INCR",
                start_time,
                success=True,
            )
            logger.debug(
                "Redis INCR operation",
                extra={
                    "key": key,
                    "amount": amount,
                    "new_value": int(new_value),
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return int(new_value)
        except Exception as exc:
            latency_ms = cls._record_operation_metric(
                "INCR",
                start_time,
                success=False,
            )
            logger.error(
                "Redis INCR operation failed",
                extra={
                    "key": key,
                    "amount": amount,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

    @classmethod
    async def decr(cls, key: str, amount: int = 1) -> int:
        """
        Decrement a key's integer value atomically.

        Parameters
        ----------
        key : str
            The Redis key to decrement.
        amount : int
            The amount to decrement by (default 1).

        Returns
        -------
        int
            The new value after decrementing.
        """
        start_time = time.monotonic()
        try:
            new_value = await cls.get_resilience().execute(
                operation=lambda: cls.client().decrby(key, amount),
                operation_name=f"DECR:{key}",
            )
            latency_ms = cls._record_operation_metric(
                "DECR",
                start_time,
                success=True,
            )
            logger.debug(
                "Redis DECR operation",
                extra={
                    "key": key,
                    "amount": amount,
                    "new_value": int(new_value),
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return int(new_value)
        except Exception as exc:
            latency_ms = cls._record_operation_metric(
                "DECR",
                start_time,
                success=False,
            )
            logger.error(
                "Redis DECR operation failed",
                extra={
                    "key": key,
                    "amount": amount,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

    @classmethod
    async def expire(cls, key: str, ttl_seconds: int) -> bool:
        """
        Set expiration time on an existing key.

        Parameters
        ----------
        key : str
            The Redis key to set expiration on.
        ttl_seconds : int
            Time-to-live in seconds.

        Returns
        -------
        bool
            True if expiration was set, False if key doesn't exist.
        """
        start_time = time.monotonic()
        try:
            result = await cls.get_resilience().execute(
                operation=lambda: cls.client().expire(key, ttl_seconds),
                operation_name=f"EXPIRE:{key}",
            )
            latency_ms = cls._record_operation_metric(
                "EXPIRE",
                start_time,
                success=True,
            )
            success = bool(result)
            logger.debug(
                "Redis EXPIRE operation",
                extra={
                    "key": key,
                    "ttl_seconds": ttl_seconds,
                    "success": success,
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return success
        except Exception as exc:
            latency_ms = cls._record_operation_metric(
                "EXPIRE",
                start_time,
                success=False,
            )
            logger.error(
                "Redis EXPIRE operation failed",
                extra={
                    "key": key,
                    "ttl_seconds": ttl_seconds,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

    @classmethod
    async def exists(cls, key: str) -> bool:
        """
        Check whether a key exists in Redis.

        Parameters
        ----------
        key : str
            The Redis key to check.

        Returns
        -------
        bool
            True if key exists, False otherwise.
        """
        start_time = time.monotonic()
        try:
            count = await cls.get_resilience().execute(
                operation=(lambda: cls.client().exists(key)), # type: Callable[[], Awaitable[Any]]
                operation_name=f"EXISTS:{key}",
            )
            latency_ms = cls._record_operation_metric(
                "EXISTS",
                start_time,
                success=True,
            )
            exists_flag = bool(count)
            logger.debug(
                "Redis EXISTS operation",
                extra={
                    "key": key,
                    "exists": exists_flag,
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return exists_flag
        except Exception as exc:
            latency_ms = cls._record_operation_metric(
                "EXISTS",
                start_time,
                success=False,
            )
            logger.error(
                "Redis EXISTS operation failed",
                extra={
                    "key": key,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

    @classmethod
    async def ttl(cls, key: str) -> int:
        """
        Get the remaining time-to-live of a key.

        Parameters
        ----------
        key : str
            The Redis key to inspect.

        Returns
        -------
        int
            Remaining TTL in seconds. Returns:
            -1 if key exists but has no associated expire.
            -2 if key does not exist.
        """
        start_time = time.monotonic()
        try:
            ttl_value = await cls.get_resilience().execute(
                operation=(lambda: cls.client().ttl(key)), # type: Callable[[], Awaitable[Any]]
                operation_name=f"TTL:{key}",
            )
            latency_ms = cls._record_operation_metric(
                "TTL",
                start_time,
                success=True,
            )
            logger.debug(
                "Redis TTL operation",
                extra={
                    "key": key,
                    "ttl": int(ttl_value),
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return int(ttl_value)
        except Exception as exc:
            latency_ms = cls._record_operation_metric(
                "TTL",
                start_time,
                success=False,
            )
            logger.error(
                "Redis TTL operation failed",
                extra={
                    "key": key,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

    # ═══════════════════════════════════════════════════════════════════════
    # JSON OPERATIONS (WITH OPTIONAL PATH SUPPORT)
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _normalize_json_path(path: str) -> list[str]:
        """
        Normalize a JSON path into a list of path segments.

        Supports simple dotted paths with optional leading "$." or "$".
        """
        if not path or path in {"$", "."}:
            return []
        # Strip leading "$" and "." characters, then split on "."
        normalized = path.lstrip("$.")
        if not normalized:
            return []
        return normalized.split(".")

    @classmethod
    async def json_get(cls, key: str, path: str = "$") -> Optional[Any]:
        """
        Get and optionally project a JSON value from Redis.

        Parameters
        ----------
        key : str
            The Redis key to retrieve.
        path : str
            Optional dotted JSON path. Defaults to root ("$").

        Returns
        -------
        Optional[Any]
            The deserialized JSON value, or None if key doesn't exist or
            path cannot be resolved.
        """
        raw = await cls.get(key)
        if raw is None:
            return None

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Failed to deserialize JSON from Redis",
                extra={
                    "key": key,
                    "error": str(exc),
                    "raw_value_length": len(raw),
                },
            )
            return None

        segments = cls._normalize_json_path(path)
        if not segments:
            return data

        node: Any = data
        try:
            for segment in segments:
                if isinstance(node, dict):
                    node = node[segment]
                elif isinstance(node, list):
                    index = int(segment)
                    node = node[index]
                else:
                    # Unsupported structure for further traversal
                    logger.debug(
                        "JSON path traversal failed: non-container node",
                        extra={
                            "key": key,
                            "path": path,
                            "segment": segment,
                        },
                    )
                    return None
            return node
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            logger.debug(
                "JSON path traversal failed",
                extra={"key": key, "path": path, "error": str(exc)},
            )
            return None

    @classmethod
    async def json_set(
        cls,
        key: str,
        path: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Set a JSON value at the given path, creating intermediate containers
        as needed.

        This is implemented client-side on top of simple string storage to
        avoid requiring RedisJSON, so it is not atomic across concurrent
        writers to the same key.

        Parameters
        ----------
        key : str
            The Redis key to modify.
        path : str
            Dotted JSON path (e.g., "$.stats.hp" or "stats.hp").
            Use "$" or "." for root replacement.
        value : Any
            Value to set at the target path.
        ttl_seconds : Optional[int]
            Optional TTL to apply to the key. If None, the default Redis TTL
            config is used.

        Returns
        -------
        bool
            True if the value was written successfully.
        """
        segments = cls._normalize_json_path(path)

        if not segments:
            # Root replacement
            return await cls.set_json(key, value, ttl_seconds=ttl_seconds)

        # Load existing document or start a new one
        current = await cls.json_get(key, "$")
        if current is None or not isinstance(current, (dict, list)):
            current = {}

        node: Any = current
        for i, segment in enumerate(segments):
            is_last = i == len(segments) - 1
            if isinstance(node, dict):
                if is_last:
                    node[segment] = value
                else:
                    next_node = node.get(segment)
                    if not isinstance(next_node, (dict, list)):
                        next_node = {}
                        node[segment] = next_node
                    node = next_node
            elif isinstance(node, list):
                index = int(segment)
                # Grow list if needed
                while len(node) <= index:
                    node.append({})
                if is_last:
                    node[index] = value
                else:
                    next_node = node[index]
                    if not isinstance(next_node, (dict, list)):
                        next_node = {}
                        node[index] = next_node
                    node = next_node
            else:
                # Replace invalid structure with a dict for continued traversal
                current = {}
                node = current

        return await cls.set_json(key, current, ttl_seconds=ttl_seconds)

    @classmethod
    async def json_delete(cls, key: str, path: str) -> bool:
        """
        Delete a JSON value at the given path.

        Implemented client-side on top of simple string storage.

        Parameters
        ----------
        key : str
            The Redis key to modify.
        path : str
            Dotted JSON path to delete. "$" or "." deletes the entire key.

        Returns
        -------
        bool
            True if something was deleted, False otherwise.
        """
        segments = cls._normalize_json_path(path)
        if not segments:
            # Delete entire key
            deleted = await cls.delete(key)
            return deleted > 0

        current = await cls.json_get(key, "$")
        if current is None:
            return False

        # Traverse to parent node
        node: Any = current
        try:
            for segment in segments[:-1]:
                if isinstance(node, dict):
                    node = node[segment]
                elif isinstance(node, list):
                    index = int(segment)
                    node = node[index]
                else:
                    return False

            last = segments[-1]
            changed = False
            if isinstance(node, dict):
                if last in node:
                    del node[last]
                    changed = True
            elif isinstance(node, list):
                index = int(last)
                if 0 <= index < len(node):
                    del node[index]
                    changed = True

            if not changed:
                return False

            await cls.set_json(key, current)
            return True

        except (KeyError, IndexError, ValueError, TypeError):
            return False

    # Backwards-compatible helpers that operate on whole-document JSON
    @classmethod
    async def get_json(cls, key: str) -> Optional[Any]:
        """
        Get and deserialize a JSON value from Redis (entire document variant).

        This is a backwards-compatible wrapper around json_get with root path.
        """
        return await cls.json_get(key, path="$")

    @classmethod
    async def set_json(
        cls,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Serialize and store a JSON value in Redis (entire document variant).

        This is a backwards-compatible wrapper that serializes the full object
        and stores it at the given key.
        """
        try:
            payload = json.dumps(
                value,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            logger.error(
                "Failed to serialize value as JSON",
                extra={
                    "key": key,
                    "value_type": type(value).__name__,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

        return await cls.set(key, payload, ttl_seconds=ttl_seconds)

    # ═══════════════════════════════════════════════════════════════════════
    # DISTRIBUTED LOCKING (WITH METRICS)
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    async def _track_lock_ownership(
        cls,
        lock_key: str,
        token: str,
        timeout: int,
        operation: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> None:
        """
        Record lock ownership metadata for debugging.

        Stores lock metadata in Redis hash for monitoring and debugging:
        - lock:tracking:{lock_key} hash with token, acquired_at, expires_at, etc.

        Parameters
        ----------
        lock_key : str
            The lock key.
        token : str
            Unique lock token (UUID).
        timeout : int
            Lock timeout in seconds.
        operation : Optional[str]
            Optional operation name (e.g., "fusion", "summon").
        owner_id : Optional[str]
            Optional owner identifier (e.g., player_id, user_id).
        """
        client = cls.client()
        tracking_key = f"lock:tracking:{lock_key}"

        try:
            now = time.time()
            expires_at = now + timeout

            tracking_data: dict[str, str] = {
                "token": token,
                "acquired_at": str(now),
                "expires_at": str(expires_at),
                "timeout": str(timeout),
            }

            if operation:
                tracking_data["operation"] = operation

            if owner_id:
                tracking_data["owner_id"] = owner_id

            # Store tracking data with same expiration as lock + small buffer
            await client.hset(tracking_key, mapping=tracking_data)  # type: ignore[misc]
            await client.expire(tracking_key, timeout + 10)

        except Exception as exc:
            # Don't fail lock acquisition if tracking fails
            logger.warning(
                "Failed to track lock ownership (non-critical)",
                extra={
                    "lock_key": lock_key,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

    @classmethod
    async def _remove_lock_tracking(cls, lock_key: str) -> None:
        """Remove lock ownership tracking data."""
        client = cls.client()
        tracking_key = f"lock:tracking:{lock_key}"

        try:
            await client.delete(tracking_key)
        except Exception as exc:
            logger.warning(
                "Failed to remove lock tracking (non-critical)",
                extra={
                    "lock_key": lock_key,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

    @classmethod
    async def get_lock_owner(cls, lock_key: str) -> Optional[dict[str, Any]]:
        """
        Get current lock owner information for debugging.

        Parameters
        ----------
        lock_key : str
            The lock key to check.

        Returns
        -------
        Optional[dict[str, Any]]
            Lock ownership data if lock is held:
            - token: Lock token
            - acquired_at: Timestamp when acquired
            - expires_at: Timestamp when expires
            - timeout: Lock timeout in seconds
            - operation: Optional operation name
            - owner_id: Optional owner identifier
            - held_duration: Current duration lock has been held (seconds)

            Returns None if lock not held or tracking data not available.
        """
        client = cls.client()
        tracking_key = f"lock:tracking:{lock_key}"

        try:
            data = await client.hgetall(tracking_key)  # type: ignore[misc]
            if not data:
                return None

            # Calculate held duration
            acquired_at = float(data.get("acquired_at", 0)) if data.get("acquired_at") else 0.0
            held_duration = time.time() - acquired_at if acquired_at else 0.0

            result: dict[str, Any] = {
                "token": data.get("token"),
                "acquired_at": acquired_at,
                "expires_at": float(data.get("expires_at", 0)) if data.get("expires_at") else 0.0,
                "timeout": int(data.get("timeout", 0)) if data.get("timeout") else 0,
                "held_duration": round(held_duration, 2),
            }

            if "operation" in data:
                result["operation"] = data["operation"]

            if "owner_id" in data:
                result["owner_id"] = data["owner_id"]

            return result

        except Exception as exc:
            logger.error(
                "Failed to retrieve lock owner info",
                extra={
                    "lock_key": lock_key,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            return None

    @classmethod
    async def get_all_active_locks(cls) -> list[dict[str, Any]]:
        """
        Get all currently held locks for debugging.

        Returns
        -------
        list[dict[str, Any]]
            List of active lock information dictionaries.
            Each dict contains: lock_key, token, acquired_at, expires_at,
            held_duration, and optional operation/owner_id fields.
        """
        client = cls.client()

        try:
            # Scan for all lock tracking keys
            tracking_keys: list[str] = []
            async for key in client.scan_iter(match="lock:tracking:*"):
                tracking_keys.append(key)

            # Retrieve ownership info for each
            locks: list[dict[str, Any]] = []
            for tracking_key in tracking_keys:
                # Extract original lock key
                lock_key = tracking_key.replace("lock:tracking:", "")

                owner_info = await cls.get_lock_owner(lock_key)
                if owner_info:
                    owner_info["lock_key"] = lock_key
                    locks.append(owner_info)

            return locks

        except Exception as exc:
            logger.error(
                "Failed to retrieve active locks",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            return []

    @classmethod
    @asynccontextmanager
    async def acquire_lock(
        cls,
        key: str,
        timeout: Optional[int] = None,
        wait_timeout: Optional[int] = None,
        retry_interval: Optional[float] = None,
        operation: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> AsyncGenerator[None, None]:
        """
        Acquire a distributed lock using Redis SET NX with unique token.

        Uses a UUID token and Lua script for safe release. The lock will
        automatically expire if not released (e.g., due to crash).

        Lock ownership is tracked in Redis for debugging purposes, allowing
        inspection of which locks are held, by whom, and for how long.

        Parameters
        ----------
        key : str
            Lock identifier (e.g., "fusion:{player_id}", "ui:{user_id}").
        timeout : Optional[int]
            Lock expiration in seconds (default from config).
        wait_timeout : Optional[int]
            Maximum time to wait for lock acquisition (default from config).
        retry_interval : Optional[float]
            Sleep duration between acquisition attempts (default from config).
        operation : Optional[str]
            Optional operation name for debugging (e.g., "fusion", "summon").
        owner_id : Optional[str]
            Optional owner identifier for debugging (e.g., player_id, user_id).

        Yields
        ------
        None
            Control is yielded when lock is acquired.

        Raises
        ------
        TimeoutError
            If lock cannot be acquired within wait_timeout.

        Example
        -------
        Basic usage:
        >>> async with RedisService.acquire_lock(f"fusion:{player_id}", timeout=5):
        >>>     # perform atomic operation
        >>>     await fusion_service.perform_fusion(player_id, material_ids)

        With ownership tracking:
        >>> async with RedisService.acquire_lock(
        >>>     f"fusion:{player_id}",
        >>>     timeout=5,
        >>>     operation="fusion",
        >>>     owner_id=str(player_id)
        >>> ):
        >>>     await fusion_service.perform_fusion(player_id, material_ids)
        """
        client = cls.client()

        # Load config with fallbacks
        if timeout is None:
            timeout = cls._get_config_int(
                "core.redis.lock.default_timeout_sec",
                5,
            )
        if wait_timeout is None:
            wait_timeout = cls._get_config_int(
                "core.redis.lock.wait_timeout_sec",
                5,
            )
        if retry_interval is None:
            retry_interval = cls._get_config_float(
                "core.redis.lock.retry_interval_sec",
                0.1,
            )

        token = str(uuid.uuid4())
        deadline = time.monotonic() + max(0, wait_timeout)
        acquired = False

        lock_start_time = time.monotonic()
        hold_start_time: Optional[float] = None

        try:
            # Acquisition loop with timeout
            while True:
                try:
                    acquired = await client.set(
                        name=key,
                        value=token,
                        nx=True,
                        ex=timeout,
                    )

                    if acquired:
                        # Record acquisition metrics
                        wait_ms = cls._record_lock_acquisition_metric(
                            key,
                            lock_start_time,
                            success=True,
                        )

                        # Track lock ownership for debugging
                        await cls._track_lock_ownership(
                            lock_key=key,
                            token=token,
                            timeout=timeout,
                            operation=operation,
                            owner_id=owner_id,
                        )

                        logger.debug(
                            "Redis lock acquired",
                            extra={
                                "lock_key": key,
                                "timeout_seconds": timeout,
                                "wait_ms": round(wait_ms, 2),
                                "operation": operation,
                                "owner_id": owner_id,
                            },
                        )

                        # Start hold-time measurement from this point
                        hold_start_time = time.monotonic()
                        break

                except (RedisConnectionError, RedisError) as exc:
                    logger.error(
                        "Redis lock acquisition error",
                        extra={
                            "lock_key": key,
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                        },
                        exc_info=True,
                    )
                    # Continue trying unless deadline reached

                # Check timeout
                if time.monotonic() >= deadline:
                    wait_ms = cls._record_lock_acquisition_metric(
                        key,
                        lock_start_time,
                        success=False,
                    )
                    logger.warning(
                        "Failed to acquire Redis lock within timeout",
                        extra={
                            "lock_key": key,
                            "wait_timeout_seconds": wait_timeout,
                            "actual_wait_ms": round(wait_ms, 2),
                        },
                    )
                    raise TimeoutError(
                        f"Failed to acquire Redis lock '{key}' "
                        f"within {wait_timeout}s"
                    )

                await asyncio.sleep(retry_interval)

            # Critical section
            yield

        finally:
            # Safe release via Lua script (only if we hold the lock)
            if acquired:
                try:
                    release_start_time = time.monotonic()
                    released = await client.eval(  # type: ignore[misc]
                        cls._LUA_UNLOCK_SCRIPT,
                        1,
                        key,
                        token,
                    )
                    release_time_ms = (time.monotonic() - release_start_time) * 1000

                    # Record hold metrics if we know when the lock was acquired
                    if hold_start_time is not None:
                        hold_ms = cls._record_lock_hold_metric(key, hold_start_time)
                    else:
                        hold_ms = None  # pragma: no cover - defensive

                    if released:
                        # Remove lock ownership tracking
                        await cls._remove_lock_tracking(key)

                        logger.debug(
                            "Redis lock released",
                            extra={
                                "lock_key": key,
                                "release_time_ms": round(release_time_ms, 2),
                                "hold_ms": round(hold_ms, 2) if hold_ms is not None else None,
                            },
                        )
                    else:
                        # Lock expired or stolen, but still remove tracking
                        await cls._remove_lock_tracking(key)

                        logger.warning(
                            "Redis lock already expired or stolen",
                            extra={
                                "lock_key": key,
                                "release_time_ms": round(release_time_ms, 2),
                                "hold_ms": round(hold_ms, 2) if hold_ms is not None else None,
                            },
                        )

                except Exception as exc:
                    logger.warning(
                        "Failed to release Redis lock (will expire automatically)",
                        extra={
                            "lock_key": key,
                            "timeout_seconds": timeout,
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                        },
                        exc_info=True,
                    )

    # ═══════════════════════════════════════════════════════════════════════
    # CONFIGURATION HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _get_config_str(key: str, default: str) -> str:
        """Get string config value with fallback."""
        try:
            val = ConfigManager.get(key)
            if isinstance(val, str):
                return val
        except Exception:
            pass

        # Fallback to Config class attribute
        attr_name = key.replace("core.redis.", "REDIS_").replace(".", "_").upper()
        val = getattr(Config, attr_name, None)
        if isinstance(val, str):
            return val

        return default

    @staticmethod
    def _get_config_int(key: str, default: int) -> int:
        """Get integer config value with fallback."""
        try:
            val = ConfigManager.get(key)
            if isinstance(val, int):
                return val
        except Exception:
            pass

        # Fallback to Config class attribute
        attr_name = key.replace("core.redis.", "REDIS_").replace(".", "_").upper()
        val = getattr(Config, attr_name, None)
        if isinstance(val, int):
            return val

        return default

    @staticmethod
    def _get_config_float(key: str, default: float) -> float:
        """Get float config value with fallback."""
        try:
            val = ConfigManager.get(key)
            if isinstance(val, (int, float)):
                return float(val)
        except Exception:
            pass

        # Fallback to Config class attribute
        attr_name = key.replace("core.redis.", "REDIS_").replace(".", "_").upper()
        val = getattr(Config, attr_name, None)
        if isinstance(val, (int, float)):
            return float(val)

        return default

    @staticmethod
    def _get_config_bool(key: str, default: bool) -> bool:
        """Get boolean config value with fallback."""
        try:
            val = ConfigManager.get(key)
            if isinstance(val, bool):
                return val
        except Exception:
            pass

        # Fallback to Config class attribute
        attr_name = key.replace("core.redis.", "REDIS_").replace(".", "_").upper()
        val = getattr(Config, attr_name, None)
        if isinstance(val, bool):
            return val

        return default
