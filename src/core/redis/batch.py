"""
Redis Batch Operations for Lumen (2025)

Purpose
-------
Provide efficient batch operations for Redis to reduce network roundtrips
and improve performance for bulk operations.

Supports:
- Batch GET (MGET)
- Batch SET (MSET)
- Batch DELETE (DEL)
- Pipeline operations for complex workflows
- Atomic batch operations via transactions

Responsibilities
----------------
- Execute multiple Redis commands in single roundtrip
- Provide convenient batch operation APIs
- Handle partial failures gracefully
- Log batch operation metrics
- Optimize network usage for bulk operations

Non-Responsibilities
--------------------
- No business logic
- No retry logic (use retry_policy.py)
- No metrics collection (handled by metrics.py)

Lumen 2025 Compliance
---------------------
- Strict layering: pure infrastructure utility
- Config-driven: batch size limits
- Observability: structured logging for batch operations
- Performance: optimized network usage

Configuration Keys
------------------
- core.redis.batch.max_keys_per_operation: int (default 1000)
- core.redis.batch.pipeline_buffer_size  : int (default 100)

Architecture Notes
------------------
- Uses Redis MGET/MSET for efficient bulk operations
- Pipelines for complex multi-command workflows
- Automatic chunking for operations exceeding size limits
- Preserves operation order and atomicity where possible
- All batch operations are observable via structured logs
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from redis.asyncio import Redis
from redis.asyncio.client import Pipeline

from src.core.logging.logger import get_logger
from src.core.config.config_manager import ConfigManager

logger = get_logger(__name__)


class RedisBatchOperations:
    """
    Efficient batch operations for Redis.
    
    Provides high-performance bulk operations using MGET, MSET,
    pipelines, and chunking for large batches.
    """
    
    def __init__(self, client: Redis) -> None:
        """
        Initialize batch operations handler.
        
        Parameters
        ----------
        client : Redis
            The Redis client to use for operations
        """
        self._client = client
        self._max_keys = self._get_config_int("core.redis.batch.max_keys_per_operation", 1000)
        self._pipeline_buffer = self._get_config_int("core.redis.batch.pipeline_buffer_size", 100)
        
        logger.debug(
            "RedisBatchOperations initialized",
            extra={
                "max_keys_per_operation": self._max_keys,
                "pipeline_buffer_size": self._pipeline_buffer,
            },
        )
    
    # ═══════════════════════════════════════════════════════════════════════
    # BATCH GET
    # ═══════════════════════════════════════════════════════════════════════
    
    async def mget(self, keys: Sequence[str]) -> Dict[str, Optional[str]]:
        """
        Get multiple keys in a single roundtrip.
        
        Parameters
        ----------
        keys : Sequence[str]
            List of keys to retrieve
            
        Returns
        -------
        Dict[str, Optional[str]]
            Dictionary mapping keys to values (None if key doesn't exist)
        """
        if not keys:
            return {}
        
        start_time = time.monotonic()
        
        try:
            # Chunk if necessary
            if len(keys) > self._max_keys:
                logger.warning(
                    "Batch GET exceeds max keys, chunking operation",
                    extra={
                        "total_keys": len(keys),
                        "max_keys": self._max_keys,
                        "chunks": (len(keys) + self._max_keys - 1) // self._max_keys,
                    },
                )
                
                result = {}
                for i in range(0, len(keys), self._max_keys):
                    chunk = keys[i:i + self._max_keys]
                    chunk_result = await self._mget_chunk(chunk)
                    result.update(chunk_result)
                
                return result
            
            # Single operation
            values = await self._client.mget(keys)
            latency_ms = (time.monotonic() - start_time) * 1000
            
            logger.debug(
                "Batch GET completed",
                extra={
                    "key_count": len(keys),
                    "found_count": sum(1 for v in values if v is not None),
                    "latency_ms": round(latency_ms, 2),
                },
            )
            
            return dict(zip(keys, values))
            
        except Exception as exc:
            logger.error(
                "Batch GET failed",
                extra={
                    "key_count": len(keys),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    async def _mget_chunk(self, keys: Sequence[str]) -> Dict[str, Optional[str]]:
        """Get a chunk of keys."""
        values = await self._client.mget(keys)
        return dict(zip(keys, values))
    
    # ═══════════════════════════════════════════════════════════════════════
    # BATCH SET
    # ═══════════════════════════════════════════════════════════════════════
    
    async def mset(
        self,
        mapping: Dict[str, Any],
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Set multiple key-value pairs in a single roundtrip.
        
        Parameters
        ----------
        mapping : Dict[str, Any]
            Dictionary of key-value pairs to set
        ttl_seconds : Optional[int]
            Optional TTL for all keys
            
        Returns
        -------
        bool
            True if all keys were set successfully
        """
        if not mapping:
            return True
        
        start_time = time.monotonic()
        
        try:
            # If TTL is specified, use pipeline for MSET + EXPIRE
            if ttl_seconds is not None:
                async with self._client.pipeline() as pipe:
                    await pipe.mset(mapping)
                    for key in mapping.keys():
                        await pipe.expire(key, ttl_seconds)
                    await pipe.execute()
            else:
                # Simple MSET without TTL
                await self._client.mset(mapping)
            
            latency_ms = (time.monotonic() - start_time) * 1000
            
            logger.debug(
                "Batch SET completed",
                extra={
                    "key_count": len(mapping),
                    "ttl_seconds": ttl_seconds,
                    "latency_ms": round(latency_ms, 2),
                },
            )
            
            return True
            
        except Exception as exc:
            logger.error(
                "Batch SET failed",
                extra={
                    "key_count": len(mapping),
                    "ttl_seconds": ttl_seconds,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    # ═══════════════════════════════════════════════════════════════════════
    # BATCH DELETE
    # ═══════════════════════════════════════════════════════════════════════
    
    async def delete_many(self, keys: Sequence[str]) -> int:
        """
        Delete multiple keys in a single roundtrip.
        
        Parameters
        ----------
        keys : Sequence[str]
            List of keys to delete
            
        Returns
        -------
        int
            Number of keys deleted
        """
        if not keys:
            return 0
        
        start_time = time.monotonic()
        
        try:
            # Chunk if necessary
            if len(keys) > self._max_keys:
                logger.warning(
                    "Batch DELETE exceeds max keys, chunking operation",
                    extra={
                        "total_keys": len(keys),
                        "max_keys": self._max_keys,
                    },
                )
                
                total_deleted = 0
                for i in range(0, len(keys), self._max_keys):
                    chunk = keys[i:i + self._max_keys]
                    deleted = await self._client.delete(*chunk)
                    total_deleted += deleted
                
                return total_deleted
            
            # Single operation
            deleted = await self._client.delete(*keys)
            latency_ms = (time.monotonic() - start_time) * 1000
            
            logger.debug(
                "Batch DELETE completed",
                extra={
                    "key_count": len(keys),
                    "deleted_count": deleted,
                    "latency_ms": round(latency_ms, 2),
                },
            )
            
            return int(deleted)
            
        except Exception as exc:
            logger.error(
                "Batch DELETE failed",
                extra={
                    "key_count": len(keys),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    # ═══════════════════════════════════════════════════════════════════════
    # PIPELINE
    # ═══════════════════════════════════════════════════════════════════════
    
    def pipeline(self, transaction: bool = True) -> Pipeline:
        """
        Create a Redis pipeline for batching multiple commands.
        
        Parameters
        ----------
        transaction : bool
            If True, pipeline will be wrapped in MULTI/EXEC
            
        Returns
        -------
        Pipeline
            Redis pipeline context manager
            
        Example
        -------
        >>> async with batch_ops.pipeline() as pipe:
        >>>     pipe.set("key1", "value1")
        >>>     pipe.incr("counter")
        >>>     pipe.get("key2")
        >>>     results = await pipe.execute()
        """
        return self._client.pipeline(transaction=transaction)
    
    # ═══════════════════════════════════════════════════════════════════════
    # BATCH INCREMENT
    # ═══════════════════════════════════════════════════════════════════════
    
    async def incr_many(self, keys: Sequence[str], amounts: Optional[List[int]] = None) -> Dict[str, int]:
        """
        Increment multiple keys atomically.
        
        Parameters
        ----------
        keys : Sequence[str]
            List of keys to increment
        amounts : Optional[List[int]]
            List of amounts to increment by (default 1 for each)
            
        Returns
        -------
        Dict[str, int]
            Dictionary mapping keys to new values
        """
        if not keys:
            return {}
        
        if amounts is None:
            amounts = [1] * len(keys)
        elif len(amounts) != len(keys):
            raise ValueError("Length of amounts must match length of keys")
        
        start_time = time.monotonic()
        
        try:
            async with self._client.pipeline() as pipe:
                for key, amount in zip(keys, amounts):
                    pipe.incrby(key, amount)
                results = await pipe.execute()
            
            latency_ms = (time.monotonic() - start_time) * 1000
            
            logger.debug(
                "Batch INCR completed",
                extra={
                    "key_count": len(keys),
                    "latency_ms": round(latency_ms, 2),
                },
            )
            
            return dict(zip(keys, results))
            
        except Exception as exc:
            logger.error(
                "Batch INCR failed",
                extra={
                    "key_count": len(keys),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    # ═══════════════════════════════════════════════════════════════════════
    # CONFIGURATION HELPERS
    # ═══════════════════════════════════════════════════════════════════════
    
    @staticmethod
    def _get_config_int(key: str, default: int) -> int:
        """Get integer config value with fallback."""
        try:
            val = ConfigManager.get(key)
            if isinstance(val, int):
                return val
        except Exception:
            pass
        return default