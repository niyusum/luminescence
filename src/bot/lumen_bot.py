"""
Lumen RPG Discord Bot - Main Bot Class (2025)

Purpose
-------
Provide the production-grade Discord bot implementation for Lumen, responsible for:
- Discord integration (events, commands, presence)
- Delegating lifecycle to BotLifecycle
- Delegating feature loading to FeatureLoader
- Global error handling for prefix commands

LUMEN LAW Compliance
--------------------
- Business logic confined to services (no business rules here)
- Event-driven architecture via event bus
- Transaction-safe operations delegated to services
- Dynamic cog discovery via FeatureLoader
- Graceful degradation on service failures
- Structured audit logging with Discord context

Architecture
------------
- LumenBot is the only concrete discord.ext.commands.Bot implementation.
- Lifecycle (startup, health monitoring, shutdown) is delegated to BotLifecycle.
- Cog loading is delegated to FeatureLoader / load_all_features.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, cast

import discord
from discord.ext import commands

from src.bot.lifecycle import BotLifecycle, StartupMetrics
from src.bot.loader import load_all_features
from src.core.config import ConfigManager
from src.core.config.config import Config
from src.core.database.service import DatabaseService
from src.core.exceptions import (
    InsufficientResourcesError,
    LumenException,
    RateLimitError,
)
from src.core.logging.logger import LogContext, get_logger
from src.core.redis.service import RedisService
from src.core.event import event_bus, initialize_event_system, shutdown_event_system
from src.utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class LumenBot(commands.Bot):
    """
    Lumen RPG Discord Bot - Production-Grade Implementation.

    Handles:
    - Discord integration, events, and prefix commands
    - Cog loading and presence
    - Global error handling for prefix commands

    Delegates:
    - Startup validation, service init, and health monitoring to BotLifecycle
    - Cog discovery and loading to FeatureLoader
    """

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        super().__init__(
            command_prefix=self._get_prefix,
            intents=intents,
            help_command=None,
            case_insensitive=True,
            strip_after_prefix=True,
            description=Config.BOT_DESCRIPTION,
        )

        self.lifecycle = BotLifecycle(self)

        self.startup_metrics: Optional[StartupMetrics] = None
        self.bot_ready: bool = False
        self.degraded_mode: bool = False
        self.errors_by_type: Dict[str, int] = {}

    # --------------------------------------------------------------- #
    # Prefix Handling
    # --------------------------------------------------------------- #

    def _get_prefix(self, bot: commands.Bot, message: discord.Message) -> List[str]:
        """
        Smart dynamic prefix with flexible whitespace.

        - ;, ; , ;  , ;   (semi-colon prefixes)
        - lumen, lumen , lumen  , lumen   (word prefixes)
        """
        return commands.when_mentioned_or(
            ";",
            "; ",
            ";  ",
            ";   ",
            "lumen",
            "lumen ",
            "lumen  ",
            "lumen   ",
        )(bot, message)

    # --------------------------------------------------------------- #
    # Startup and Initialization (Delegates to BotLifecycle)
    # --------------------------------------------------------------- #

    async def setup_hook(self) -> None:
        """
        Initialize all core systems and load all features.

        Delegates lifecycle management to BotLifecycle:
        - Startup validation
        - Service initialization with timing
        - Health monitoring
        - Startup metrics collection

        Handles Discord-specific concerns:
        - Cog loading
        - Publishing bot setup event
        """
        startup_start = time.perf_counter()
        logger.info("=" * 60)
        logger.info("LUMEN RPG BOT STARTUP")
        logger.info("=" * 60)

        try:
            await self.lifecycle.validate_startup()

            db_time = await self.lifecycle.initialize_service(
                "Database", DatabaseService.initialize()
            )
            redis_time = await self.lifecycle.initialize_service(
                "Redis", RedisService.initialize(), required=False
            )
            config_time = await self.lifecycle.initialize_service(
                "ConfigManager", ConfigManager.initialize()
            )

            if (
                self.lifecycle.metrics.services_unhealthy > 0
                or self.lifecycle.metrics.services_degraded > 0
            ):
                self.degraded_mode = True

            cogs_start = time.perf_counter()
            cog_stats = await load_all_features(self)
            cogs_time = (time.perf_counter() - cogs_start) * 1000

            # Initialize event system (listeners and consumers)
            await initialize_event_system()

            await event_bus.publish("bot.setup_complete", {"bot": self})
            logger.info("Bot setup complete event published")

            sync_time_ms = 0.0  # Slash commands removed; prefix-only

            total_time_ms = (time.perf_counter() - startup_start) * 1000
            self.startup_metrics = StartupMetrics(
                total_time_ms=total_time_ms,
                database_time_ms=db_time,
                redis_time_ms=redis_time,
                config_time_ms=config_time,
                cogs_time_ms=cogs_time,
                sync_time_ms=sync_time_ms,
                cogs_loaded=cast(int, cog_stats.get("loaded", 0)),
                cogs_failed=cast(int, cog_stats.get("failed", 0)),
            )

            self.lifecycle.log_startup_summary(self.startup_metrics)
            self.lifecycle.start_health_monitoring()

        except Exception as exc:
            logger.critical(
                "FATAL: Bot setup failed",
                extra={"error": str(exc), "error_type": type(exc).__name__},
                exc_info=True,
            )
            raise

    # --------------------------------------------------------------- #
    # Events
    # --------------------------------------------------------------- #

    async def on_ready(self) -> None:
        """Bot is connected and ready to receive events."""
        self.bot_ready = True

        total_users = sum(getattr(g, "member_count", 0) for g in self.guilds)
        logger.info("=" * 60)
        logger.info("Bot is ONLINE as %s", self.user)
        logger.info("Guilds: %d • Users: %d", len(self.guilds), total_users)
        logger.info("Bot ID: %s", getattr(self.user, "id", "unknown"))
        logger.info("=" * 60)

        await self._update_presence()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Send welcome embed when joining a new guild."""
        logger.info(
            "Joined guild",
            extra={
                "guild_name": guild.name,
                "guild_id": guild.id,
                "member_count": getattr(guild, "member_count", 0),
            },
        )

        await self._update_presence()

        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            embed = EmbedBuilder.success(
                title="Thanks for adding Lumen RPG!",
                description="Use `;register` to begin your maiden journey.",
                footer="Use ;help for full command list.",
            )
            try:
                await guild.system_channel.send(embed=embed)
            except Exception as exc:
                logger.warning(
                    "Failed to send welcome message",
                    extra={"error": str(exc), "error_type": type(exc).__name__},
                )

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Log when removed from a guild."""
        logger.info(
            "Removed from guild",
            extra={"guild_name": guild.name, "guild_id": guild.id},
        )
        await self._update_presence()

    async def _update_presence(self) -> None:
        """Update the bot presence with current guild count."""
        try:
            await self.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.playing,
                    name=f";help | {len(self.guilds)} servers",
                )
            )
        except Exception as exc:
            logger.warning(
                "Failed to update presence",
                extra={"error": str(exc), "error_type": type(exc).__name__},
            )

    # --------------------------------------------------------------- #
    # Error Handling - Prefix Commands
    # --------------------------------------------------------------- #

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        """
        Global error handler for prefix commands.

        - Uses LogContext for Discord audit trail
        - Converts domain exceptions to user-friendly embeds
        - Tracks metrics for monitoring
        """
        async with LogContext(
            user_id=ctx.author.id,
            guild_id=ctx.guild.id if ctx.guild else None,
            command=f"prefix:{ctx.command}" if ctx.command else "unknown",
        ):
            self.lifecycle.metrics.commands_failed += 1

            if isinstance(error, commands.CommandNotFound):
                return

            original = getattr(error, "original", error)
            error_type = type(original).__name__
            self.lifecycle.metrics.errors_handled += 1
            self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1

            # Domain-level exceptions
            if isinstance(original, RateLimitError):
                embed = EmbedBuilder.warning(
                    title="Rate Limited",
                    description=f"Wait **{original.retry_after:.1f}s** before using this command again.",
                )
                await ctx.send(embed=embed)
                return

            if isinstance(original, InsufficientResourcesError):
                embed = EmbedBuilder.error(
                    title="Insufficient Resources",
                    description=(
                        f"You need **{original.required:,}** {original.resource}, "
                        f"but only have **{original.current:,}**."
                    ),
                )
                await ctx.send(embed=embed)
                return

            if isinstance(original, LumenException):
                embed = EmbedBuilder.error(
                    title="Error",
                    description=original.message,
                    help_text="If this persists, contact support.",
                )
                logger.warning(
                    "Domain exception in command handler",
                    extra=original.to_dict(),
                )
                await ctx.send(embed=embed)
                return

            # Framework-level command errors
            if isinstance(error, commands.MissingRequiredArgument):
                embed = EmbedBuilder.error(
                    title="Missing Argument",
                    description=f"Missing required argument: `{error.param.name}`",
                )
                await ctx.send(embed=embed)
                return

            if isinstance(error, commands.CommandOnCooldown):
                embed = EmbedBuilder.warning(
                    title="Cooldown Active",
                    description=f"Please wait **{error.retry_after:.1f}s**.",
                )
                await ctx.send(embed=embed)
                return

            if isinstance(error, commands.CheckFailure):
                embed = EmbedBuilder.error(
                    title="Permission Denied",
                    description="You lack permission to use this command.",
                )
                await ctx.send(embed=embed)
                return

            # Fallback - unexpected error
            logger.error(
                "Unhandled command error",
                extra={
                    "command": str(ctx.command),
                    "error": str(error),
                    "error_type": error_type,
                },
                exc_info=True,
            )
            embed = EmbedBuilder.error(
                title="Unexpected Error",
                description="Something went wrong while processing your command.",
                help_text="The issue has been logged.",
            )
            await ctx.send(embed=embed)

    # --------------------------------------------------------------- #
    # Command Execution Tracking
    # --------------------------------------------------------------- #

    async def on_command_completion(self, ctx: commands.Context) -> None:
        """Track successful command execution."""
        self.lifecycle.metrics.commands_executed += 1

    # --------------------------------------------------------------- #
    # Graceful Shutdown (Delegates to BotLifecycle)
    # --------------------------------------------------------------- #

    async def close(self) -> None:
        """
        Gracefully close services before bot shutdown.

        Delegates service cleanup to BotLifecycle:
        - Health monitoring shutdown
        - Service closure with error handling
        - Metrics logging
        """
        logger.info("=" * 60)
        logger.info("LUMEN RPG BOT SHUTDOWN")
        logger.info("=" * 60)

        metrics = self.lifecycle.get_metrics_snapshot()
        total_commands = metrics["commands_executed"] + metrics["commands_failed"]
        if total_commands > 0:
            success_rate = (metrics["commands_executed"] / total_commands) * 100
            logger.info("Final command stats:")
            logger.info("  Commands Executed: %d", metrics["commands_executed"])
            logger.info("  Commands Failed:   %d", metrics["commands_failed"])
            logger.info("  Success Rate:      %.1f%%", success_rate)
            logger.info("  Errors Handled:    %d", metrics["errors_handled"])

        # Shutdown event system first (flush consumers, stop tasks)
        await shutdown_event_system()

        await self.lifecycle.shutdown()
        await super().close()

        logger.info("=" * 60)
        logger.info("Lumen RPG shutdown complete")
        logger.info("=" * 60)







