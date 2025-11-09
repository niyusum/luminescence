"""
Production-grade rate limiting decorators for Discord commands.

RIKI LAW Compliance: Article IV (Rate Limiting & Degradation)
- Distributed rate limiting via Redis
- Graceful degradation on Redis failure
- Comprehensive metrics and audit trails
- Per-user and per-guild rate limiting support

Features:
- Redis-backed distributed rate limiting
- Automatic fallback to command execution on Redis failure
- Metrics tracking (hits, blocks, fallback events)
- LogContext integration for audit trails
- Type-safe decorator patterns
- Per-user or per-guild rate limiting modes
"""

from typing import Callable, Literal, Optional, TypeVar, cast
from functools import wraps
import discord
from discord.ext import commands

from src.core.infra.redis_service import RedisService
from src.core.exceptions import RateLimitError
from src.core.logging.logger import get_logger, LogContext

logger = get_logger(__name__)

# Type variable for decorated function
F = TypeVar('F', bound=Callable)

# Metrics tracking
_ratelimit_metrics = {
    "checks": 0,
    "blocks": 0,
    "fallbacks": 0,
    "redis_errors": 0
}


def ratelimit(
    uses: int,
    per_seconds: int,
    command_name: Optional[str] = None,
    scope: Literal["user", "guild"] = "user"
) -> Callable[[F], F]:
    """
    Rate limit decorator for Discord commands (RIKI LAW Article IV).

    Prevents command spam by limiting uses within time window using Redis.
    Falls back to allowing command if Redis is unavailable (graceful degradation).
    Integrates with LogContext for audit trails.

    Works with both prefix commands (commands.Context) and slash commands (discord.Interaction).

    Args:
        uses: Number of uses allowed per time window
        per_seconds: Time window in seconds
        command_name: Name of the command (for logging), auto-detected if None
        scope: Rate limit scope - "user" (per-user) or "guild" (per-guild)

    Returns:
        Decorator function that enforces rate limiting

    Raises:
        RateLimitError: If user/guild exceeds rate limit

    Example:
        >>> # Prefix command
        >>> @commands.command(name="profile")
        >>> @ratelimit(uses=5, per_seconds=60)
        >>> async def profile(self, ctx: commands.Context):
        ...     # Can only be used 5 times per minute per user

        >>> # Slash command
        >>> @commands.slash_command(name="fuse")
        >>> @ratelimit(uses=5, per_seconds=60, command_name="fuse")
        >>> async def fuse(self, inter: discord.Interaction):
        ...     # Can only be used 5 times per minute per user

        >>> # Guild-scoped rate limit
        >>> @commands.command(name="announce")
        >>> @ratelimit(uses=3, per_seconds=3600, scope="guild")
        >>> async def announce(self, ctx: commands.Context):
        ...     # Can only be used 3 times per hour per guild
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(self, ctx_or_inter, *args, **kwargs):
            # Detect command type (prefix vs slash)
            is_prefix = isinstance(ctx_or_inter, commands.Context)
            is_slash = isinstance(ctx_or_inter, discord.Interaction)

            if not (is_prefix or is_slash):
                # Unknown type, skip rate limiting
                return await func(self, ctx_or_inter, *args, **kwargs)

            # Extract user, guild, and command name
            if is_prefix:
                ctx = ctx_or_inter
                user = ctx.author
                guild = ctx.guild
                cmd_name = command_name or ctx.command.name if ctx.command else "unknown"
            else:
                inter = ctx_or_inter
                user = inter.user
                guild = inter.guild
                cmd_name = command_name or "unknown"
            # Generate rate limit key based on scope
            if scope == "guild":
                if not guild:
                    # DM commands don't have guild scope, skip rate limiting
                    return await func(self, ctx_or_inter, *args, **kwargs)
                scope_id = guild.id
                scope_name = f"guild:{guild.name}"
            else:
                scope_id = user.id
                scope_name = f"user:{user.name}"

            key = f"ratelimit:{cmd_name}:{scope}:{scope_id}"

            # Increment metrics
            _ratelimit_metrics["checks"] += 1

            # Setup LogContext for audit trail
            context_kwargs = {
                "user_id": user.id,
                "command": f"/{cmd_name}" if is_slash else f"r{cmd_name}",
            }
            if guild:
                context_kwargs["guild_id"] = guild.id
            
            async with LogContext(**context_kwargs):
                try:
                    # Check current usage
                    current = await RedisService.get(key)
                    
                    if current and int(current) >= uses:
                        # Rate limit exceeded
                        ttl = await RedisService.ttl(key)
                        retry_after = float(ttl) if ttl > 0 else per_seconds
                        
                        _ratelimit_metrics["blocks"] += 1
                        
                        logger.warning(
                            f"Rate limit exceeded for {cmd_name} "
                            f"({scope_name}, {int(current)}/{uses} uses, "
                            f"retry in {retry_after:.0f}s)"
                        )

                        raise RateLimitError(
                            command=cmd_name,
                            retry_after=retry_after
                        )

                    # Increment usage counter
                    if current:
                        new_count = await RedisService.increment(key)
                        logger.debug(
                            f"Rate limit check passed for {cmd_name} "
                            f"({scope_name}, {new_count}/{uses} uses)"
                        )
                    else:
                        # First use, set with TTL
                        await RedisService.set(key, 1, ttl=per_seconds)
                        logger.debug(
                            f"Rate limit initialized for {cmd_name} "
                            f"({scope_name}, 1/{uses} uses, {per_seconds}s window)"
                        )

                    # Execute command
                    return await func(self, ctx_or_inter, *args, **kwargs)
                    
                except RateLimitError:
                    # Re-raise rate limit errors (don't fall through)
                    raise
                    
                except Exception as e:
                    # Redis failure or other error - graceful degradation
                    _ratelimit_metrics["redis_errors"] += 1
                    _ratelimit_metrics["fallbacks"] += 1

                    logger.error(
                        f"Rate limit check failed for {cmd_name} "
                        f"({scope_name}): {e}. Allowing command (graceful degradation)"
                    )

                    # Allow command to proceed despite Redis failure
                    return await func(self, ctx_or_inter, *args, **kwargs)
        
        return cast(F, wrapper)
    return decorator


def get_ratelimit_metrics() -> dict:
    """
    Get current rate limiting metrics.
    
    Returns:
        Dictionary with metrics:
        - checks: Total rate limit checks performed
        - blocks: Number of commands blocked by rate limit
        - fallbacks: Number of times rate limit fell back due to Redis error
        - redis_errors: Number of Redis errors encountered
        - block_rate: Percentage of checks that resulted in blocks
        - error_rate: Percentage of checks that encountered errors
    """
    checks = _ratelimit_metrics["checks"]
    blocks = _ratelimit_metrics["blocks"]
    errors = _ratelimit_metrics["redis_errors"]
    
    return {
        **_ratelimit_metrics,
        "block_rate": (blocks / checks * 100) if checks > 0 else 0.0,
        "error_rate": (errors / checks * 100) if checks > 0 else 0.0
    }


def reset_ratelimit_metrics() -> None:
    """Reset rate limiting metrics (useful for testing)."""
    _ratelimit_metrics["checks"] = 0
    _ratelimit_metrics["blocks"] = 0
    _ratelimit_metrics["fallbacks"] = 0
    _ratelimit_metrics["redis_errors"] = 0


async def clear_ratelimit(
    command_name: str,
    scope_id: int,
    scope: Literal["user", "guild"] = "user"
) -> bool:
    """
    Manually clear rate limit for a specific user/guild and command.
    
    Useful for admin commands to reset rate limits.
    
    Args:
        command_name: Name of the command
        scope_id: User ID or Guild ID
        scope: Rate limit scope - "user" or "guild"
    
    Returns:
        True if rate limit was cleared, False if key didn't exist
    
    Example:
        >>> # Admin command to clear user's rate limit
        >>> await clear_ratelimit("fuse", user_id, scope="user")
    """
    key = f"ratelimit:{command_name}:{scope}:{scope_id}"
    
    try:
        result = await RedisService.delete(key)
        
        if result:
            logger.info(
                f"Rate limit cleared for {command_name} "
                f"({scope}:{scope_id})"
            )
        
        return result
        
    except Exception as e:
        logger.error(
            f"Failed to clear rate limit for {command_name} "
            f"({scope}:{scope_id}): {e}"
        )
        return False


async def get_ratelimit_status(
    command_name: str,
    scope_id: int,
    scope: Literal["user", "guild"] = "user"
) -> Optional[dict]:
    """
    Get current rate limit status for a specific user/guild and command.
    
    Args:
        command_name: Name of the command
        scope_id: User ID or Guild ID
        scope: Rate limit scope - "user" or "guild"
    
    Returns:
        Dictionary with current status or None if no rate limit active:
        - current_uses: Current number of uses
        - time_remaining: Seconds until rate limit resets
        
    Example:
        >>> status = await get_ratelimit_status("fuse", user_id)
        >>> if status:
        ...     print(f"Used {status['current_uses']} times, "
        ...           f"resets in {status['time_remaining']}s")
    """
    key = f"ratelimit:{command_name}:{scope}:{scope_id}"
    
    try:
        current = await RedisService.get(key)
        
        if not current:
            return None
        
        ttl = await RedisService.ttl(key)
        
        return {
            "current_uses": int(current),
            "time_remaining": ttl if ttl > 0 else 0
        }
        
    except Exception as e:
        logger.error(
            f"Failed to get rate limit status for {command_name} "
            f"({scope}:{scope_id}): {e}"
        )
        return None






