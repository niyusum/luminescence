"""
Lumen RPG Discord Bot - Production-Grade Main Bot Class

LUMEN LAW Compliance:
- Business logic confined to services (Article VII)
- Event-driven architecture (Article VIII)
- Transaction-safe operations (Article I)
- Dynamic cog discovery (Article II)
- Graceful degradation (Article IX)
- Audit logging with Discord context (Article II)

Production Features:
- Startup timing metrics (delegated to BotLifecycle)
- Health monitoring (delegated to BotLifecycle)
- Context injection for all errors
- Slash command error handling
- Startup validation (delegated to BotLifecycle)
- Graceful degradation
- Metrics tracking
- Reconnection handling

Architecture:
- Discord integration and command handling in LumenBot
- Lifecycle management delegated to BotLifecycle module
- Clear separation: Discord vs Infrastructure concerns
"""

import time
from typing import List

import discord
from discord.ext import commands

from src.core.bot.lifecycle import BotLifecycle, StartupMetrics
from src.core.bot.loader import load_all_features
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
from src.modules.tutorial.listener import register_tutorial_listeners
from src.utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class LumenBot(commands.Bot):
    """
    Lumen RPG Discord Bot - Production-Grade Implementation

    Handles Discord integration, cog loading, command execution, and error management.
    Delegates lifecycle management (startup, health monitoring, shutdown) to BotLifecycle.

    LUMEN LAW Compliance:
        - Business logic confined to services
        - Event-driven + transaction-safe
        - Concurrent initialization with graceful degradation
        - Dynamic cog discovery
        - Graceful shutdown
        - Full audit trails with Discord context
    """

    def __init__(self):
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

        # Lifecycle management (delegated)
        self.lifecycle = BotLifecycle(self)

        # Discord-specific state
        self.startup_metrics: StartupMetrics | None = None
        self.is_ready = False
        self.degraded_mode = False
        self.errors_by_type: dict[str, int] = {}

    # --------------------------------------------------------------- #
    # Prefix Handling
    # --------------------------------------------------------------- #
    def _get_prefix(self, bot: commands.Bot, message: discord.Message) -> List[str]:
        """Smart dynamic prefix with flexible whitespace (0-3 spaces)."""
        return commands.when_mentioned_or(
            ";", "; ", ";  ", ";   ",
            "lumen", "lumen ", "lumen  ", "lumen   "
        )(bot, message)

    # --------------------------------------------------------------- #
    # Startup and Initialization (Delegates to BotLifecycle)
    # --------------------------------------------------------------- #
    async def setup_hook(self):
        """
        Initialize all core systems and load all features.

        Delegates lifecycle management to BotLifecycle module:
        - Startup validation
        - Service initialization with timing
        - Health monitoring
        - Startup metrics collection

        This method handles Discord-specific concerns:
        - Cog loading
        - Event listener registration
        """
        startup_start = time.perf_counter()
        logger.info("=" * 60)
        logger.info("🚀 LUMEN RPG BOT STARTUP")
        logger.info("=" * 60)

        try:
            # Validate configuration (delegated to lifecycle)
            await self.lifecycle.validate_startup()

            # Initialize core services with individual timing (delegated to lifecycle)
            db_time = await self.lifecycle.initialize_service(
                "Database", DatabaseService.initialize()
            )
            redis_time = await self.lifecycle.initialize_service(
                "Redis", RedisService.initialize(), required=False
            )
            config_time = await self.lifecycle.initialize_service(
                "ConfigManager", ConfigManager.initialize()
            )

            # Track degraded mode from lifecycle
            if (
                self.lifecycle.metrics.services_unhealthy > 0
                or self.lifecycle.metrics.services_degraded > 0
            ):
                self.degraded_mode = True

            # Load feature cogs (Discord-specific)
            cogs_start = time.perf_counter()
            cog_stats = await load_all_features(self)
            cogs_time = (time.perf_counter() - cogs_start) * 1000

            # Register event listeners (Discord-specific)
            await register_tutorial_listeners(self)
            logger.info("✅ Tutorial listeners registered")

            # Slash commands removed - prefix-only architecture
            sync_time = 0

            # Store startup metrics
            total_time = (time.perf_counter() - startup_start) * 1000
            self.startup_metrics = StartupMetrics(
                total_time_ms=total_time,
                database_time_ms=db_time,
                redis_time_ms=redis_time,
                config_time_ms=config_time,
                cogs_time_ms=cogs_time,
                sync_time_ms=sync_time,
                cogs_loaded=cog_stats.get("loaded", 0),
                cogs_failed=cog_stats.get("failed", 0),
            )

            # Log startup summary (delegated to lifecycle)
            self.lifecycle.log_startup_summary(self.startup_metrics)

            # Start background health monitoring (delegated to lifecycle)
            self.lifecycle.start_health_monitoring()

        except Exception as e:
            logger.critical(f"❌ FATAL: Setup failed: {e}", exc_info=True)
            raise

    # --------------------------------------------------------------- #
    # Health Monitoring (Delegated to BotLifecycle)
    # --------------------------------------------------------------- #
    # Health monitoring is fully delegated to BotLifecycle.
    # Access health status via self.lifecycle.get_metrics_snapshot()

    # --------------------------------------------------------------- #
    # Events
    # --------------------------------------------------------------- #
    async def on_ready(self):
        """Bot is connected and ready to receive events."""
        self.is_ready = True

        total_users = sum(g.member_count for g in self.guilds)
        logger.info("=" * 60)
        logger.info(f"✅ {self.user} is ONLINE")
        logger.info(f"👥 {len(self.guilds)} guilds • {total_users:,} total users")
        logger.info(f"🆔 Bot ID: {self.user.id}")
        logger.info("=" * 60)

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name=f"/help | ;help | {len(self.guilds)} servers",
            )
        )

    async def on_guild_join(self, guild: discord.Guild):
        """Send welcome embed when joining a new guild."""
        logger.info(f"➕ Joined guild: {guild.name} ({guild.id}) • {guild.member_count} members")
        
        # Update presence
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name=f"/help | ;help | {len(self.guilds)} servers",
            )
        )

        # Send welcome message
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            embed = EmbedBuilder.success(
                title="Thanks for adding Lumen RPG!",
                description="Use `/register` to begin your maiden purification journey.",
                footer="Use /help for full command list",
            )
            try:
                await guild.system_channel.send(embed=embed)
            except Exception as e:
                logger.warning(f"Failed to send welcome message: {e}")

    async def on_guild_remove(self, guild: discord.Guild):
        """Log when removed from a guild."""
        logger.info(f"➖ Removed from guild: {guild.name} ({guild.id})")
        
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name=f"/help | ;help | {len(self.guilds)} servers",
            )
        )

    # --------------------------------------------------------------- #
    # Error Handling - Prefix Commands
    # --------------------------------------------------------------- #
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        """
        Global error handler for prefix commands.

        LUMEN LAW Compliance:
        - Uses LogContext for Discord audit trail (Article II)
        - Converts domain exceptions to user-friendly embeds
        - Tracks metrics for monitoring
        """
        # Set logging context - LUMEN LAW Article II
        async with LogContext(
            user_id=ctx.author.id,
            guild_id=ctx.guild.id if ctx.guild else None,
            command=f"prefix:{ctx.command}" if ctx.command else "unknown",
        ):
            # Track metrics in lifecycle
            self.lifecycle.metrics.commands_failed += 1

            # Ignore command not found
            if isinstance(error, commands.CommandNotFound):
                return

            original = getattr(error, "original", error)
            error_type = type(original).__name__
            self.lifecycle.metrics.errors_handled += 1
            self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1

            # Handle domain exceptions
            if isinstance(original, RateLimitError):
                embed = EmbedBuilder.warning(
                    title="Rate Limited",
                    description=f"Wait **{original.retry_after:.1f}s** before using this command again.",
                )
                return await ctx.send(embed=embed, ephemeral=True)

            if isinstance(original, InsufficientResourcesError):
                embed = EmbedBuilder.error(
                    title="Insufficient Resources",
                    description=(
                        f"You need **{original.required:,}** {original.resource}, "
                        f"but only have **{original.current:,}**."
                    ),
                )
                return await ctx.send(embed=embed, ephemeral=True)

            if isinstance(original, LumenException):
                embed = EmbedBuilder.error(
                    title="Error",
                    description=original.message,
                    help_text="If this persists, contact support.",
                )
                logger.warning(f"Domain exception: {original}", extra=original.to_dict())
                return await ctx.send(embed=embed, ephemeral=True)

            # Framework-level errors
            if isinstance(error, commands.MissingRequiredArgument):
                embed = EmbedBuilder.error(
                    title="Missing Argument",
                    description=f"Missing required argument: `{error.param.name}`",
                )
                return await ctx.send(embed=embed, ephemeral=True)

            if isinstance(error, commands.CommandOnCooldown):
                embed = EmbedBuilder.warning(
                    title="Cooldown Active",
                    description=f"Please wait **{error.retry_after:.1f}s**.",
                )
                return await ctx.send(embed=embed, ephemeral=True)

            if isinstance(error, commands.CheckFailure):
                embed = EmbedBuilder.error(
                    title="Permission Denied",
                    description="You lack permission to use this command.",
                )
                return await ctx.send(embed=embed, ephemeral=True)

            # Fallback - unexpected error
            logger.error(
                f"Unhandled error in {ctx.command}: {error}",
                exc_info=True,
                extra={"error_type": error_type}
            )
            embed = EmbedBuilder.error(
                title="Unexpected Error",
                description="Something went wrong while processing your command.",
                help_text="The issue has been logged.",
            )
            await ctx.send(embed=embed, ephemeral=True)

    # --------------------------------------------------------------- #
    # Command Execution Tracking
    # --------------------------------------------------------------- #
    async def on_command_completion(self, ctx: commands.Context):
        """Track successful command execution."""
        self.lifecycle.metrics.commands_executed += 1

    # --------------------------------------------------------------- #
    # Graceful Shutdown (Delegates to BotLifecycle)
    # --------------------------------------------------------------- #
    async def close(self):
        """
        Gracefully close services before bot shutdown.

        Delegates service cleanup to BotLifecycle:
        - Health monitoring shutdown
        - Service closure with error handling
        - Comprehensive logging
        """
        logger.info("=" * 60)
        logger.info("🛑 LUMEN RPG BOT SHUTDOWN")
        logger.info("=" * 60)

        # Log final metrics
        metrics = self.lifecycle.get_metrics_snapshot()
        total_commands = metrics["commands_executed"] + metrics["commands_failed"]
        if total_commands > 0:
            success_rate = (metrics["commands_executed"] / total_commands) * 100
            logger.info(f"Final Stats:")
            logger.info(f"  Commands Executed: {metrics['commands_executed']}")
            logger.info(f"  Commands Failed:   {metrics['commands_failed']}")
            logger.info(f"  Success Rate:      {success_rate:.1f}%")
            logger.info(f"  Errors Handled:    {metrics['errors_handled']}")

        # Delegate shutdown to lifecycle
        await self.lifecycle.shutdown()

        await super().close()
        logger.info("=" * 60)
        logger.info("👋 Lumen RPG shutdown complete")
        logger.info("=" * 60)







