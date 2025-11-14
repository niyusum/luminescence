"""
RedisService: Production-grade async Redis infrastructure for Lumen (2025)

Purpose
-------
Provide a robust, observable, connection-pooled Redis abstraction with:
- Singleton async client with automatic reconnection
- Health monitoring with degradation detection
- Distributed locking with token-based safety and ownership tracking
- KV operations with built-in observability
- Graceful failure handling and circuit breaking integration

Responsibilities
----------------
- Initialize and manage singleton Redis connection pool
- Provide atomic distributed locking via SET NX + Lua unlock
- Track lock ownership for debugging (lock holders, durations, metadata)
- Expose simple KV operations (get/set/delete/expire/incr)
- JSON serialization helpers
- Health check integration
- Structured logging for all operations

Non-Responsibilities
--------------------
- Rate limiting (see rate_limiter.py)
- Circuit breaking (see circuit_breaker.py)
- Retry policies (see retry_policy.py)
- Batch operations (see batch.py)
- Metrics collection (see metrics.py)
- Business logic of any kind

Lumen 2025 Compliance
---------------------
- Strict layering: pure infrastructure only
- Config-driven: all tunables via ConfigManager
- Observability: structured logs + operation context
- Concurrency safety: distributed locks for mutations
- Graceful degradation: health checks + clear failure modes
- Transaction discipline: N/A (Redis is not transactional in SQL sense)
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
- Health check returns detailed status for monitoring systems
- Initialization is idempotent and thread-safe via asyncio.Lock
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError

from src.core.logging.logger import get_logger
from src.core.config.config import Config
from src.core.config import ConfigManager

logger = get_logger(__name__)


class RedisService:
    """
    Production-grade async Redis infrastructure service.
    
    Provides connection pooling, distributed locking, health monitoring,
    and observable KV operations for the Lumen system.
    """

    _client: Optional[Redis] = None
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
        Initialize the singleton Redis client with connection pooling.
        
        Idempotent and thread-safe. Safe to call multiple times.
        
        Raises
        ------
        RuntimeError
            If Redis connection cannot be established
        """
        if cls._client is not None:
            logger.debug("RedisService already initialized, skipping")
            return

        async with cls._init_lock:
            if cls._client is not None:
                return

            url = cls._get_config_str("core.redis.url", "redis://localhost:6379/0")
            socket_timeout = cls._get_config_int("core.redis.socket_timeout_seconds", 5)
            encoding = cls._get_config_str("core.redis.encoding", "utf-8")
            decode_responses = cls._get_config_bool("core.redis.decode_responses", True)
            max_connections = cls._get_config_int("core.redis.max_connections", 50)

            start_time = time.monotonic()

            try:
                cls._client = Redis.from_url(
                    url,
                    socket_timeout=socket_timeout,
                    encoding=encoding,
                    decode_responses=decode_responses,
                    max_connections=max_connections,
                    retry_on_timeout=False,  # Handled by retry_policy.py
                    health_check_interval=30,  # Background health checks
                )

                # Verify connection
                await cls._client.ping()
                cls._is_healthy = True

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
                cls._client = None
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
        Gracefully shutdown the Redis client and close all connections.
        
        Safe to call even if not initialized.
        """
        if cls._client is None:
            logger.debug("RedisService not initialized, nothing to shutdown")
            return

        client = cls._client
        cls._client = None
        cls._is_healthy = False

        try:
            await client.aclose()
            logger.info("RedisService shutdown complete")

        except Exception as exc:
            logger.error(
                "Error during RedisService shutdown",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
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
            True if Redis is reachable and responsive, False otherwise
        """
        if cls._client is None:
            logger.warning("Health check failed: RedisService not initialized")
            cls._is_healthy = False
            return False

        try:
            start_time = time.monotonic()
            pong = await cls._client.ping()
            latency_ms = (time.monotonic() - start_time) * 1000

            if pong:
                cls._is_healthy = True
                logger.debug(
                    "Redis health check passed",
                    extra={"latency_ms": round(latency_ms, 2)},
                )
                return True
            else:
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

    # ═══════════════════════════════════════════════════════════════════════
    # CLIENT ACCESS
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def client(cls) -> Redis:
        """
        Return the singleton Redis client.
        
        Returns
        -------
        Redis
            The active Redis client instance
            
        Raises
        ------
        RuntimeError
            If RedisService has not been initialized
        """
        if cls._client is None:
            raise RuntimeError(
                "RedisService not initialized. Call `await RedisService.initialize()` first."
            )
        return cls._client

    # ═══════════════════════════════════════════════════════════════════════
    # KEY-VALUE OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    async def get(cls, key: str) -> Optional[str]:
        """
        Get a string value from Redis.
        
        Parameters
        ----------
        key : str
            The Redis key to retrieve
            
        Returns
        -------
        Optional[str]
            The value if it exists, None otherwise
        """
        try:
            start_time = time.monotonic()
            value = await cls.client().get(key)
            latency_ms = (time.monotonic() - start_time) * 1000

            logger.debug(
                "Redis GET operation",
                extra={
                    "key": key,
                    "found": value is not None,
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return value

        except Exception as exc:
            logger.error(
                "Redis GET operation failed",
                extra={
                    "key": key,
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
            The Redis key to set
        value : Any
            The value to store (will be converted to string)
        ttl_seconds : Optional[int]
            Time-to-live in seconds. If None, uses default from config.
            
        Returns
        -------
        bool
            True if successful, False otherwise
        """
        if ttl_seconds is None:
            ttl_seconds = cls._get_config_int("core.redis.default_ttl_seconds", 300)

        try:
            start_time = time.monotonic()
            result = await cls.client().set(key, value, ex=ttl_seconds)
            latency_ms = (time.monotonic() - start_time) * 1000

            logger.debug(
                "Redis SET operation",
                extra={
                    "key": key,
                    "ttl_seconds": ttl_seconds,
                    "success": bool(result),
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return bool(result)

        except Exception as exc:
            logger.error(
                "Redis SET operation failed",
                extra={
                    "key": key,
                    "ttl_seconds": ttl_seconds,
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
            The Redis key to delete
            
        Returns
        -------
        int
            Number of keys deleted (0 or 1)
        """
        try:
            start_time = time.monotonic()
            count = await cls.client().delete(key)
            latency_ms = (time.monotonic() - start_time) * 1000

            logger.debug(
                "Redis DELETE operation",
                extra={
                    "key": key,
                    "deleted_count": count,
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return int(count)

        except Exception as exc:
            logger.error(
                "Redis DELETE operation failed",
                extra={
                    "key": key,
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
            The Redis key to increment
        amount : int
            The amount to increment by (default 1)
            
        Returns
        -------
        int
            The new value after incrementing
        """
        try:
            start_time = time.monotonic()
            new_value = await cls.client().incrby(key, amount)
            latency_ms = (time.monotonic() - start_time) * 1000

            logger.debug(
                "Redis INCR operation",
                extra={
                    "key": key,
                    "amount": amount,
                    "new_value": new_value,
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return int(new_value)

        except Exception as exc:
            logger.error(
                "Redis INCR operation failed",
                extra={
                    "key": key,
                    "amount": amount,
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
            The Redis key to set expiration on
        ttl_seconds : int
            Time-to-live in seconds
            
        Returns
        -------
        bool
            True if expiration was set, False if key doesn't exist
        """
        try:
            start_time = time.monotonic()
            result = await cls.client().expire(key, ttl_seconds)
            latency_ms = (time.monotonic() - start_time) * 1000

            logger.debug(
                "Redis EXPIRE operation",
                extra={
                    "key": key,
                    "ttl_seconds": ttl_seconds,
                    "success": bool(result),
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return bool(result)

        except Exception as exc:
            logger.error(
                "Redis EXPIRE operation failed",
                extra={
                    "key": key,
                    "ttl_seconds": ttl_seconds,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

    # ═══════════════════════════════════════════════════════════════════════
    # JSON OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    async def get_json(cls, key: str) -> Optional[Any]:
        """
        Get and deserialize a JSON value from Redis.
        
        Parameters
        ----------
        key : str
            The Redis key to retrieve
            
        Returns
        -------
        Optional[Any]
            The deserialized JSON value, or None if key doesn't exist
            or JSON is invalid
        """
        raw = await cls.get(key)
        if raw is None:
            return None

        try:
            return json.loads(raw)
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

    @classmethod
    async def set_json(
        cls,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Serialize and store a JSON value in Redis.
        
        Parameters
        ----------
        key : str
            The Redis key to set
        value : Any
            The value to serialize as JSON
        ttl_seconds : Optional[int]
            Time-to-live in seconds
            
        Returns
        -------
        bool
            True if successful, False otherwise
        """
        try:
            payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
            return await cls.set(key, payload, ttl_seconds=ttl_seconds)

        except (TypeError, ValueError) as exc:
            logger.error(
                "Failed to serialize value as JSON",
                extra={
                    "key": key,
                    "value_type": type(value).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise

    # ═══════════════════════════════════════════════════════════════════════
    # DISTRIBUTED LOCKING
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
            The lock key
        token : str
            Unique lock token (UUID)
        timeout : int
            Lock timeout in seconds
        operation : Optional[str]
            Optional operation name (e.g., "fusion", "summon")
        owner_id : Optional[str]
            Optional owner identifier (e.g., player_id, user_id)
        """
        client = cls.client()
        tracking_key = f"lock:tracking:{lock_key}"

        try:
            now = time.time()
            expires_at = now + timeout

            tracking_data = {
                "token": token,
                "acquired_at": str(now),
                "expires_at": str(expires_at),
                "timeout": str(timeout),
            }

            if operation:
                tracking_data["operation"] = operation

            if owner_id:
                tracking_data["owner_id"] = owner_id

            # Store tracking data with same expiration as lock + buffer
            await client.hset(tracking_key, mapping=tracking_data)
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
            The lock key to check

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
            data = await client.hgetall(tracking_key)

            if not data:
                return None

            # Calculate held duration
            acquired_at = float(data.get("acquired_at", 0))
            held_duration = time.time() - acquired_at if acquired_at else 0

            result = {
                "token": data.get("token"),
                "acquired_at": acquired_at,
                "expires_at": float(data.get("expires_at", 0)),
                "timeout": int(data.get("timeout", 0)),
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
            tracking_keys = []
            async for key in client.scan_iter(match="lock:tracking:*"):
                tracking_keys.append(key)

            # Retrieve ownership info for each
            locks = []
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
            Lock identifier (e.g., "fusion:{player_id}", "ui:{user_id}")
        timeout : Optional[int]
            Lock expiration in seconds (default from config)
        wait_timeout : Optional[int]
            Maximum time to wait for lock acquisition (default from config)
        retry_interval : Optional[float]
            Sleep duration between acquisition attempts (default from config)
        operation : Optional[str]
            Optional operation name for debugging (e.g., "fusion", "summon")
        owner_id : Optional[str]
            Optional owner identifier for debugging (e.g., player_id, user_id)

        Yields
        ------
        None
            Control is yielded when lock is acquired

        Raises
        ------
        TimeoutError
            If lock cannot be acquired within wait_timeout

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
            timeout = cls._get_config_int("core.redis.lock.default_timeout_sec", 5)
        if wait_timeout is None:
            wait_timeout = cls._get_config_int("core.redis.lock.wait_timeout_sec", 5)
        if retry_interval is None:
            retry_interval = cls._get_config_float("core.redis.lock.retry_interval_sec", 0.1)

        token = str(uuid.uuid4())
        deadline = time.monotonic() + max(0, wait_timeout)
        acquired = False

        lock_start_time = time.monotonic()

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
                        acquisition_time_ms = (time.monotonic() - lock_start_time) * 1000

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
                                "acquisition_time_ms": round(acquisition_time_ms, 2),
                                "operation": operation,
                                "owner_id": owner_id,
                            },
                        )
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
                    total_wait_time = time.monotonic() - lock_start_time
                    logger.warning(
                        "Failed to acquire Redis lock within timeout",
                        extra={
                            "lock_key": key,
                            "wait_timeout_seconds": wait_timeout,
                            "actual_wait_seconds": round(total_wait_time, 2),
                        },
                    )
                    raise TimeoutError(
                        f"Failed to acquire Redis lock '{key}' within {wait_timeout}s"
                    )

                await asyncio.sleep(retry_interval)

            # Critical section
            yield

        finally:
            # Safe release via Lua script (only if we hold the lock)
            if acquired:
                try:
                    release_start_time = time.monotonic()
                    released = await client.eval(
                        cls._LUA_UNLOCK_SCRIPT,
                        1,
                        key,
                        token,
                    )
                    release_time_ms = (time.monotonic() - release_start_time) * 1000

                    if released:
                        # Remove lock ownership tracking
                        await cls._remove_lock_tracking(key)

                        logger.debug(
                            "Redis lock released",
                            extra={
                                "lock_key": key,
                                "release_time_ms": round(release_time_ms, 2),
                            },
                        )
                    else:
                        # Lock expired or stolen, but still remove tracking
                        await cls._remove_lock_tracking(key)

                        logger.warning(
                            "Redis lock already expired or stolen",
                            extra={"lock_key": key},
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