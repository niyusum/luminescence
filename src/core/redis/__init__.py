"""
Redis Infrastructure for Lumen (2025)

Purpose
-------
Provides production-grade Redis infrastructure with:
- Connection pooling and lifecycle management
- Distributed locking with ownership tracking
- Circuit breaking and automatic retry
- Health monitoring with degradation detection
- Comprehensive metrics collection
- Rate limiting for distributed systems
- Efficient batch operations

This module consolidates all Redis functionality into a cohesive,
observable, and resilient infrastructure layer that enforces
Lumen Engineering Standard 2025 compliance.

Exports
-------
Core Service:
    RedisService - Main Redis service with pooling, locking, and KV operations

Resilience (Unified Circuit Breaker + Retry):
    RedisResilience - Unified resilience layer
    CircuitState - Circuit breaker state enum
    CircuitBreakerOpenError - Exception when circuit is open

Health Monitoring:
    RedisHealthMonitor - Background health monitoring
    HealthState - Health state enum (HEALTHY, DEGRADED, UNHEALTHY)

Metrics:
    RedisMetrics - Centralized metrics collection

Rate Limiting:
    RedisRateLimiter - Distributed rate limiting
    RateLimitExceededError - Exception when rate limit exceeded

Batch Operations:
    RedisBatchOperations - Efficient batch operations (MGET, MSET, pipelines)

Architecture Notes
------------------
- RedisService is the primary entry point for all Redis operations
- All operations automatically use RedisResilience for circuit breaking and retry
- Health monitoring runs as background task when started
- Metrics are collected automatically for all operations
- Rate limiting and batch operations are available as utilities

Example Usage
-------------
>>> # Initialize Redis
>>> await RedisService.initialize()
>>>
>>> # Basic operations
>>> await RedisService.set("key", "value", ttl=60)
>>> value = await RedisService.get("key")
>>>
>>> # Distributed locking
>>> async with RedisService.acquire_lock(f"fusion:{player_id}", timeout=5):
>>>     await perform_critical_operation()
>>>
>>> # Health check
>>> is_healthy = await RedisService.health_check()
>>>
>>> # Get metrics
>>> metrics = RedisMetrics.get_summary()
>>>
>>> # Graceful shutdown
>>> await RedisService.shutdown()

Lumen 2025 Compliance
---------------------
- Strict layering: pure infrastructure only
- Config-driven: all behavior via ConfigManager
- Observability: comprehensive structured logging
- Concurrency safety: distributed locks for mutations
- Graceful degradation: health checks + circuit breaking
- Domain exceptions: typed errors with clear semantics
- Zero business logic
"""

from __future__ import annotations

from src.core.redis.batch import RedisBatchOperations
from src.core.redis.health_monitor import HealthState, RedisHealthMonitor
from src.core.redis.metrics import RedisMetrics
from src.core.redis.rate_limiter import RateLimitExceededError, RedisRateLimiter
from src.core.redis.resilience import (
    CircuitBreakerOpenError,
    CircuitState,
    RedisResilience,
)
from src.core.redis.service import RedisService

__all__ = [
    # Main service
    "RedisService",
    # Resilience (unified circuit breaker + retry)
    "RedisResilience",
    "CircuitState",
    "CircuitBreakerOpenError",
    # Health monitoring
    "RedisHealthMonitor",
    "HealthState",
    # Metrics
    "RedisMetrics",
    # Rate limiting
    "RedisRateLimiter",
    "RateLimitExceededError",
    # Batch operations
    "RedisBatchOperations",
]