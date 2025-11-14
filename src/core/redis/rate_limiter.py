"""
Redis Rate Limiter for Lumen (2025)

Purpose
-------
Token bucket rate limiting implementation using Redis for distributed
rate limiting across multiple bot instances.

Algorithms:
- Token bucket (smooth rate limiting)
- Fixed window (simple counting)
- Sliding window log (precise but memory-intensive)

Responsibilities
----------------
- Enforce rate limits using Redis as shared state
- Support multiple rate limiting algorithms
- Provide clear limit exceeded feedback
- Track rate limit metrics
- Handle Redis failures gracefully

Non-Responsibilities
--------------------
- No business logic
- No retry logic (handled by retry_policy.py)
- No circuit breaking (handled by circuit_breaker.py)

Lumen 2025 Compliance
---------------------
- Strict layering: pure infrastructure utility
- Config-driven: rate limits and algorithm selection
- Observability: structured logging for limit events
- Graceful degradation: allows operations if Redis unavailable

Configuration Keys
------------------
- core.redis.rate_limiter.algorithm        : str (default "token_bucket")
- core.redis.rate_limiter.default_rate     : int (default 10)
- core.redis.rate_limiter.default_period_sec: int (default 60)
- core.redis.rate_limiter.fallback_mode    : str (default "allow")

Architecture Notes
------------------
- Uses Redis for distributed rate limiting across instances
- Token bucket algorithm provides smooth rate limiting
- Atomic operations via Lua scripts for consistency
- Falls back to permissive mode if Redis unavailable (configurable)
- All limit exceeded events are logged
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from src.core.logging.logger import get_logger
from src.core.config import ConfigManager

if TYPE_CHECKING:
    from src.core.redis.service import RedisService

logger = get_logger(__name__)


class RateLimitExceededError(Exception):
    """Raised when rate limit is exceeded."""
    pass


class RedisRateLimiter:
    """
    Distributed rate limiter using Redis.
    
    Implements token bucket algorithm for smooth, distributed
    rate limiting across multiple bot instances.
    """
    
    # Lua script for atomic token bucket operation
    _LUA_TOKEN_BUCKET = """
    local key = KEYS[1]
    local max_tokens = tonumber(ARGV[1])
    local refill_rate = tonumber(ARGV[2])
    local requested = tonumber(ARGV[3])
    local now = tonumber(ARGV[4])
    
    local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
    local tokens = tonumber(bucket[1])
    local last_refill = tonumber(bucket[2])
    
    if tokens == nil then
        tokens = max_tokens
        last_refill = now
    end
    
    -- Refill tokens based on time passed
    local time_passed = now - last_refill
    local new_tokens = math.min(max_tokens, tokens + (time_passed * refill_rate))
    
    -- Check if we have enough tokens
    if new_tokens >= requested then
        new_tokens = new_tokens - requested
        redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
        redis.call('EXPIRE', key, 3600)  -- Expire after 1 hour
        return 1  -- Allowed
    else
        redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
        redis.call('EXPIRE', key, 3600)
        return 0  -- Denied
    end
    """
    
    def __init__(self, redis_service: RedisService) -> None:
        """
        Initialize rate limiter.
        
        Parameters
        ----------
        redis_service : RedisService
            The Redis service to use for state storage
        """
        self._redis_service = redis_service
        
        # Configuration
        self._algorithm = self._get_config_str("core.redis.rate_limiter.algorithm", "token_bucket")
        self._default_rate = self._get_config_int("core.redis.rate_limiter.default_rate", 10)
        self._default_period = self._get_config_int("core.redis.rate_limiter.default_period_sec", 60)
        self._fallback_mode = self._get_config_str("core.redis.rate_limiter.fallback_mode", "allow")
        
        logger.debug(
            "RedisRateLimiter initialized",
            extra={
                "algorithm": self._algorithm,
                "default_rate": self._default_rate,
                "default_period_seconds": self._default_period,
                "fallback_mode": self._fallback_mode,
            },
        )
    
    # ═══════════════════════════════════════════════════════════════════════
    # RATE LIMITING
    # ═══════════════════════════════════════════════════════════════════════
    
    async def check_limit(
        self,
        key: str,
        rate: Optional[int] = None,
        period_seconds: Optional[int] = None,
        tokens: int = 1,
    ) -> bool:
        """
        Check if operation is within rate limit.
        
        Parameters
        ----------
        key : str
            Rate limit key (e.g., "user:123:commands", "guild:456:summons")
        rate : Optional[int]
            Maximum number of operations allowed in period (default from config)
        period_seconds : Optional[int]
            Time window in seconds (default from config)
        tokens : int
            Number of tokens to consume (default 1)
            
        Returns
        -------
        bool
            True if operation is allowed, False if rate limit exceeded
        """
        rate = rate if rate is not None else self._default_rate
        period_seconds = period_seconds if period_seconds is not None else self._default_period
        
        try:
            if self._algorithm == "token_bucket":
                return await self._check_token_bucket(key, rate, period_seconds, tokens)
            elif self._algorithm == "fixed_window":
                return await self._check_fixed_window(key, rate, period_seconds, tokens)
            else:
                logger.warning(
                    "Unknown rate limit algorithm, falling back to token bucket",
                    extra={"algorithm": self._algorithm},
                )
                return await self._check_token_bucket(key, rate, period_seconds, tokens)
                
        except Exception as exc:
            logger.error(
                "Rate limit check failed",
                extra={
                    "key": key,
                    "rate": rate,
                    "period_seconds": period_seconds,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            
            # Fallback based on config
            if self._fallback_mode == "allow":
                logger.warning("Rate limiter failure, allowing operation (fallback mode: allow)")
                return True
            else:
                logger.warning("Rate limiter failure, denying operation (fallback mode: deny)")
                return False
    
    # ═══════════════════════════════════════════════════════════════════════
    # TOKEN BUCKET ALGORITHM
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _check_token_bucket(
        self,
        key: str,
        rate: int,
        period_seconds: int,
        tokens: int,
    ) -> bool:
        """Token bucket algorithm using Lua script."""
        client = self._redis_service.client()
        
        # Calculate refill rate (tokens per second)
        refill_rate = rate / period_seconds
        now = time.time()
        
        try:
            result = await client.eval(
                self._LUA_TOKEN_BUCKET,
                1,
                f"ratelimit:tb:{key}",
                rate,          # max_tokens
                refill_rate,   # refill_rate
                tokens,        # requested
                now,           # now
            )
            
            allowed = bool(result)
            
            if not allowed:
                logger.info(
                    "Rate limit exceeded",
                    extra={
                        "key": key,
                        "algorithm": "token_bucket",
                        "rate": rate,
                        "period_seconds": period_seconds,
                        "tokens_requested": tokens,
                    },
                )
            
            return allowed
            
        except Exception as exc:
            logger.error(
                "Token bucket rate limit check failed",
                extra={
                    "key": key,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    # ═══════════════════════════════════════════════════════════════════════
    # FIXED WINDOW ALGORITHM
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _check_fixed_window(
        self,
        key: str,
        rate: int,
        period_seconds: int,
        tokens: int,
    ) -> bool:
        """Fixed window algorithm (simple counter)."""
        client = self._redis_service.client()
        
        # Create time-based key
        window = int(time.time() / period_seconds)
        window_key = f"ratelimit:fw:{key}:{window}"
        
        try:
            # Increment counter
            count = await client.incr(window_key)
            
            # Set expiry on first increment
            if count == tokens:
                await client.expire(window_key, period_seconds * 2)
            
            allowed = count <= rate
            
            if not allowed:
                logger.info(
                    "Rate limit exceeded",
                    extra={
                        "key": key,
                        "algorithm": "fixed_window",
                        "rate": rate,
                        "period_seconds": period_seconds,
                        "current_count": count,
                    },
                )
            
            return allowed
            
        except Exception as exc:
            logger.error(
                "Fixed window rate limit check failed",
                extra={
                    "key": key,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    # ═══════════════════════════════════════════════════════════════════════
    # UTILITY METHODS
    # ═══════════════════════════════════════════════════════════════════════
    
    async def reset_limit(self, key: str) -> None:
        """
        Reset rate limit for a key.
        
        Parameters
        ----------
        key : str
            Rate limit key to reset
        """
        client = self._redis_service.client()
        
        try:
            # Delete all variants
            await client.delete(f"ratelimit:tb:{key}")
            
            # Delete fixed window keys (search pattern)
            pattern = f"ratelimit:fw:{key}:*"
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor, match=pattern, count=100)
                if keys:
                    await client.delete(*keys)
                if cursor == 0:
                    break
            
            logger.info(
                "Rate limit reset",
                extra={"key": key},
            )
            
        except Exception as exc:
            logger.error(
                "Failed to reset rate limit",
                extra={
                    "key": key,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
    
    async def get_remaining(self, key: str, rate: Optional[int] = None) -> Optional[int]:
        """
        Get remaining rate limit tokens.
        
        Parameters
        ----------
        key : str
            Rate limit key
        rate : Optional[int]
            Maximum rate (default from config)
            
        Returns
        -------
        Optional[int]
            Number of remaining tokens, or None if cannot determine
        """
        rate = rate if rate is not None else self._default_rate
        client = self._redis_service.client()
        
        try:
            if self._algorithm == "token_bucket":
                bucket = await client.hmget(f"ratelimit:tb:{key}", "tokens", "last_refill")
                if bucket[0] is not None:
                    return max(0, int(float(bucket[0])))
                return rate
            
            elif self._algorithm == "fixed_window":
                period_seconds = self._default_period
                window = int(time.time() / period_seconds)
                window_key = f"ratelimit:fw:{key}:{window}"
                count = await client.get(window_key)
                if count is not None:
                    return max(0, rate - int(count))
                return rate
            
            return None
            
        except Exception as exc:
            logger.warning(
                "Failed to get remaining rate limit",
                extra={
                    "key": key,
                    "error": str(exc),
                },
            )
            return None
    
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
        return default