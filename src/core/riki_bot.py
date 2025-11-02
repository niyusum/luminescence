"""
RIKI RPG Discord Bot - Production-Grade Main Bot Class

RIKI LAW Compliance:
- Business logic confined to services (Article VII)
- Event-driven architecture (Article VIII)
- Transaction-safe operations (Article I)
- Dynamic cog discovery (Article II)
- Graceful degradation (Article IX)
- Audit logging with Discord context (Article II)

Production Features:
- Startup timing metrics
- Health monitoring
- Context injection for all errors
- Slash command error handling
- Startup validation
- Graceful degradation
- Metrics tracking
- Reconnection handling
"""

import asyncio
import time
from dataclasses import dataclass
from typing import List, Optional

import discord
from discord.ext import commands

from src.core.config import Config
from src.core.config_manager import ConfigManager
from src.core.database_service import DatabaseService
from src.core.exceptions import (
    ConfigurationError,
    InsufficientResourcesError,
    RateLimitError,
    RIKIException,
)
from src.core.loader import load_all_features
from src.core.logger import LogContext, get_logger, set_log_context
from src.core.redis_service import RedisService
from src.features.tutorial.listener import register_tutorial_listeners
from src.utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


@dataclass
class ServiceHealth:
    """Health status for a service."""
    name: str
    healthy: bool
    degraded: bool
    error: Optional[str] = None
    latency_ms: Optional[float] = None


@dataclass
class StartupMetrics:
    """Metrics collected during bot startup."""
    total_time_ms: float
    database_time_ms: float
    redis_time_ms: float
    config_time_ms: float
    cogs_time_ms: float
    sync_time_ms: float
    cogs_loaded: int
    cogs_failed: int


class BotMetrics:
    """In-memory metrics for monitoring."""
    
    def __init__(self):
        self.commands_executed = 0
        self.commands_failed = 0
        self.slash_commands_executed = 0
        self.slash_commands_failed = 0
        self.errors_by_type = {}
        self.startup_time = None
        self.last_health_check = None
        self.service_health = {}
    
    def increment_command(self, success: bool = True, is_slash: bool = False):
        """Increment command counter."""
        if is_slash:
            if success:
                self.slash_commands_executed += 1
            else:
                self.slash_commands_failed += 1
        else:
            if success:
                self.commands_executed += 1
            else:
                self.commands_failed += 1
    
    def increment_error(self, error_type: str):
        """Track error by type."""
        self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1
    
    def get_stats(self) -> dict:
        """Get current metrics as dictionary."""
        total_commands = (
            self.commands_executed + 
            self.commands_failed + 
            self.slash_commands_executed + 
            self.slash_commands_failed
        )
        total_failed = self.commands_failed + self.slash_commands_failed
        
        return {
            "total_commands": total_commands,
            "commands_succeeded": self.commands_executed + self.slash_commands_executed,
            "commands_failed": total_failed,
            "success_rate": (
                ((total_commands - total_failed) / total_commands * 100)
                if total_commands > 0 else 100.0
            ),
            "prefix_commands": self.commands_executed,
            "slash_commands": self.slash_commands_executed,
            "errors_by_type": self.errors_by_type,
            "uptime_seconds": (
                (time.time() - self.startup_time) if self.startup_time else 0
            ),
        }


class RIKIBot(commands.Bot):
    """
    RIKI RPG Discord Bot - Production-Grade Implementation

    Handles startup, service orchestration, cog loading, error management,
    health monitoring, and comprehensive observability.

    RIKI LAW Compliance:
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
        
        # Metrics and health tracking
        self.metrics = BotMetrics()
        self.startup_metrics: Optional[StartupMetrics] = None
        self.is_ready = False
        self.degraded_mode = False

    # --------------------------------------------------------------- #
    # Prefix Handling
    # --------------------------------------------------------------- #
    def _get_prefix(self, bot: commands.Bot, message: discord.Message) -> List[str]:
        """Dynamic prefix getter (mention, r, riki)."""
        return commands.when_mentioned_or("r", "r ", "riki", "riki ")(bot, message)

    # --------------------------------------------------------------- #
    # Startup and Initialization
    # --------------------------------------------------------------- #
    async def setup_hook(self):
        """
        Initialize all core systems and load all features.
        
        Production features:
        - Timing metrics for each stage
        - Startup validation
        - Graceful degradation if services fail
        - Comprehensive logging
        """
        startup_start = time.perf_counter()
        logger.info("=" * 60)
        logger.info("🚀 RIKI RPG BOT STARTUP")
        logger.info("=" * 60)

        try:
            # Validate configuration before proceeding
            await self._validate_startup()
            
            # Initialize core services with individual timing
            db_time = await self._init_service("Database", DatabaseService.initialize)
            redis_time = await self._init_service("Redis", RedisService.initialize, required=False)
            config_time = await self._init_service("ConfigManager", ConfigManager.initialize)
            
            # Load feature cogs
            cogs_start = time.perf_counter()
            cog_stats = await load_all_features(self)
            cogs_time = (time.perf_counter() - cogs_start) * 1000
            
            # Register event listeners
            await register_tutorial_listeners(self)
            logger.info("✅ Tutorial listeners registered")

            # Sync slash commands
            sync_start = time.perf_counter()
            await self._sync_commands()
            sync_time = (time.perf_counter() - sync_start) * 1000

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
            
            self._log_startup_summary()
            
            # Start background health monitoring
            self.loop.create_task(self._health_monitor_loop())
            
        except Exception as e:
            logger.critical(f"❌ FATAL: Setup failed: {e}", exc_info=True)
            raise

    async def _validate_startup(self):
        """
        Validate configuration and environment before startup.
        
        Fails fast if critical configuration is missing or invalid.
        """
        logger.info("🔍 Validating startup configuration...")
        
        validations = []
        
        # Check required environment variables
        if not Config.DISCORD_TOKEN:
            validations.append("DISCORD_TOKEN not set")
        
        if not Config.DATABASE_URL:
            validations.append("DATABASE_URL not set")
        
        # Check optional but recommended configs
        if not Config.REDIS_URL:
            logger.warning("⚠️  REDIS_URL not set - caching disabled")
        
        if Config.is_development() and not Config.DISCORD_GUILD_ID:
            logger.warning("⚠️  DISCORD_GUILD_ID not set - commands will sync globally")
        
        # Fail if critical validation errors
        if validations:
            error_msg = f"Configuration validation failed: {', '.join(validations)}"
            logger.critical(f"❌ {error_msg}")
            raise ConfigurationError("startup", error_msg)
        
        logger.info("✅ Configuration valid")

    async def _init_service(
        self, 
        name: str, 
        init_coro, 
        required: bool = True
    ) -> float:
        """
        Initialize a service with timing and error handling.
        
        Args:
            name: Service name for logging
            init_coro: Coroutine to initialize service
            required: Whether service is required (non-required services enable degraded mode)
            
        Returns:
            Initialization time in milliseconds
            
        Raises:
            Exception if required service fails
        """
        start_time = time.perf_counter()
        
        try:
            await init_coro()
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(f"✅ {name} initialized ({duration_ms:.0f}ms)")
            return duration_ms
            
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            
            if required:
                logger.critical(
                    f"❌ {name} initialization failed ({duration_ms:.0f}ms): {e}",
                    exc_info=True
                )
                raise
            else:
                logger.warning(
                    f"⚠️  {name} initialization failed ({duration_ms:.0f}ms): {e}. "
                    f"Continuing in degraded mode.",
                    exc_info=True
                )
                self.degraded_mode = True
                return duration_ms

    async def _sync_commands(self):
        """
        Sync commands globally or to dev guild with error handling.
        """
        try:
            if Config.is_development() and Config.DISCORD_GUILD_ID:
                guild = discord.Object(id=Config.DISCORD_GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info(f"✅ Commands synced to dev guild {Config.DISCORD_GUILD_ID}")
            elif Config.is_production():
                await self.tree.sync()
                logger.info("✅ Commands synced globally")
        except Exception as e:
            logger.error(f"⚠️  Command sync failed: {e}. Commands may not update.", exc_info=True)
            # Don't fail startup - commands can be synced manually

    def _log_startup_summary(self):
        """Log comprehensive startup summary with metrics."""
        m = self.startup_metrics
        
        logger.info("=" * 60)
        logger.info("🎯 STARTUP COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Total Time:      {m.total_time_ms:.0f}ms")
        logger.info(f"Database:        {m.database_time_ms:.0f}ms")
        logger.info(f"Redis:           {m.redis_time_ms:.0f}ms")
        logger.info(f"ConfigManager:   {m.config_time_ms:.0f}ms")
        logger.info(f"Cogs:            {m.cogs_time_ms:.0f}ms ({m.cogs_loaded} loaded, {m.cogs_failed} failed)")
        logger.info(f"Command Sync:    {m.sync_time_ms:.0f}ms")
        logger.info(f"Mode:            {'🟡 DEGRADED' if self.degraded_mode else '🟢 NORMAL'}")
        logger.info("=" * 60)

    # --------------------------------------------------------------- #
    # Health Monitoring
    # --------------------------------------------------------------- #
    async def _health_monitor_loop(self):
        """
        Background task to monitor service health.
        
        Runs every 60 seconds, checking connectivity to critical services.
        Updates metrics for observability.
        """
        await self.wait_until_ready()
        
        while not self.is_closed():
            try:
                await self._check_service_health()
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Health monitor error: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _check_service_health(self):
        """Check health of all services and update metrics."""
        health_checks = {
            "database": self._check_database_health(),
            "redis": self._check_redis_health(),
        }
        
        results = await asyncio.gather(*health_checks.values(), return_exceptions=True)
        
        for (name, _), result in zip(health_checks.items(), results):
            if isinstance(result, Exception):
                self.metrics.service_health[name] = ServiceHealth(
                    name=name,
                    healthy=False,
                    degraded=False,
                    error=str(result)
                )
            else:
                self.metrics.service_health[name] = result
        
        self.metrics.last_health_check = time.time()
        
        # Log if any services are unhealthy
        unhealthy = [h for h in self.metrics.service_health.values() if not h.healthy]
        if unhealthy:
            logger.warning(
                f"⚠️  Unhealthy services: {', '.join(h.name for h in unhealthy)}"
            )

    async def _check_database_health(self) -> ServiceHealth:
        """Check database connectivity and latency."""
        start = time.perf_counter()
        
        try:
            # Simple health check query
            async with DatabaseService.get_session() as session:
                await session.execute("SELECT 1")
            
            latency_ms = (time.perf_counter() - start) * 1000
            
            return ServiceHealth(
                name="database",
                healthy=True,
                degraded=latency_ms > 100,  # Degraded if >100ms
                latency_ms=latency_ms
            )
        except Exception as e:
            return ServiceHealth(
                name="database",
                healthy=False,
                degraded=False,
                error=str(e)
            )

    async def _check_redis_health(self) -> ServiceHealth:
        """Check Redis connectivity and latency."""
        start = time.perf_counter()
        
        try:
            await RedisService.ping()
            latency_ms = (time.perf_counter() - start) * 1000
            
            return ServiceHealth(
                name="redis",
                healthy=True,
                degraded=latency_ms > 50,  # Degraded if >50ms
                latency_ms=latency_ms
            )
        except Exception as e:
            # Redis is optional - degraded mode, not unhealthy
            return ServiceHealth(
                name="redis",
                healthy=False,
                degraded=True,
                error=str(e)
            )

    # --------------------------------------------------------------- #
    # Events
    # --------------------------------------------------------------- #
    async def on_ready(self):
        """Bot is connected and ready to receive events."""
        self.is_ready = True
        self.metrics.startup_time = time.time()
        
        total_users = sum(g.member_count for g in self.guilds)
        logger.info("=" * 60)
        logger.info(f"✅ {self.user} is ONLINE")
        logger.info(f"👥 {len(self.guilds)} guilds • {total_users:,} total users")
        logger.info(f"🆔 Bot ID: {self.user.id}")
        logger.info("=" * 60)

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name=f"/help | r help | {len(self.guilds)} servers",
            )
        )

    async def on_guild_join(self, guild: discord.Guild):
        """Send welcome embed when joining a new guild."""
        logger.info(f"➕ Joined guild: {guild.name} ({guild.id}) • {guild.member_count} members")
        
        # Update presence
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name=f"/help | r help | {len(self.guilds)} servers",
            )
        )
        
        # Send welcome message
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            embed = EmbedBuilder.success(
                title="Thanks for adding RIKI RPG!",
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
                name=f"/help | r help | {len(self.guilds)} servers",
            )
        )

    # --------------------------------------------------------------- #
    # Error Handling - Prefix Commands
    # --------------------------------------------------------------- #
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        """
        Global error handler for prefix commands.
        
        RIKI LAW Compliance:
        - Uses LogContext for Discord audit trail (Article II)
        - Converts domain exceptions to user-friendly embeds
        - Tracks metrics for monitoring
        """
        # Set logging context - RIKI LAW Article II
        async with LogContext(
            user_id=ctx.author.id,
            guild_id=ctx.guild.id if ctx.guild else None,
            command=f"prefix:{ctx.command}" if ctx.command else "unknown"
        ):
            # Track metrics
            self.metrics.increment_command(success=False, is_slash=False)
            
            # Ignore command not found
            if isinstance(error, commands.CommandNotFound):
                return

            original = getattr(error, "original", error)
            error_type = type(original).__name__
            self.metrics.increment_error(error_type)

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

            if isinstance(original, RIKIException):
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
    # Error Handling - Slash Commands (Application Commands)
    # --------------------------------------------------------------- #
    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError
    ):
        """
        Global error handler for slash commands.
        
        RIKI LAW Compliance:
        - Uses LogContext for Discord audit trail (Article II)
        - Converts domain exceptions to user-friendly embeds
        - Tracks metrics for monitoring
        """
        # Set logging context - RIKI LAW Article II
        async with LogContext(
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            command=f"/{interaction.command.name}" if interaction.command else "unknown"
        ):
            # Track metrics
            self.metrics.increment_command(success=False, is_slash=True)
            
            original = getattr(error, "original", error)
            error_type = type(original).__name__
            self.metrics.increment_error(error_type)

            # Handle domain exceptions
            if isinstance(original, RateLimitError):
                embed = EmbedBuilder.warning(
                    title="Rate Limited",
                    description=f"Wait **{original.retry_after:.1f}s** before using this command again.",
                )
                return await self._send_error_response(interaction, embed)

            if isinstance(original, InsufficientResourcesError):
                embed = EmbedBuilder.error(
                    title="Insufficient Resources",
                    description=(
                        f"You need **{original.required:,}** {original.resource}, "
                        f"but only have **{original.current:,}**."
                    ),
                )
                return await self._send_error_response(interaction, embed)

            if isinstance(original, RIKIException):
                embed = EmbedBuilder.error(
                    title="Error",
                    description=original.message,
                    help_text="If this persists, contact support.",
                )
                logger.warning(f"Domain exception: {original}", extra=original.to_dict())
                return await self._send_error_response(interaction, embed)

            # Framework-level errors
            if isinstance(error, discord.app_commands.CommandOnCooldown):
                embed = EmbedBuilder.warning(
                    title="Cooldown Active",
                    description=f"Please wait **{error.retry_after:.1f}s**.",
                )
                return await self._send_error_response(interaction, embed)

            if isinstance(error, discord.app_commands.CheckFailure):
                embed = EmbedBuilder.error(
                    title="Permission Denied",
                    description="You lack permission to use this command.",
                )
                return await self._send_error_response(interaction, embed)

            # Fallback - unexpected error
            logger.error(
                f"Unhandled slash command error: {error}",
                exc_info=True,
                extra={"error_type": error_type}
            )
            embed = EmbedBuilder.error(
                title="Unexpected Error",
                description="Something went wrong while processing your command.",
                help_text="The issue has been logged.",
            )
            await self._send_error_response(interaction, embed)

    async def _send_error_response(
        self, 
        interaction: discord.Interaction, 
        embed: discord.Embed
    ):
        """
        Send error response, handling both responded and unresponded interactions.
        
        Args:
            interaction: Discord interaction
            embed: Error embed to send
        """
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to send error response: {e}", exc_info=True)

    # --------------------------------------------------------------- #
    # Command Execution Tracking
    # --------------------------------------------------------------- #
    async def on_command_completion(self, ctx: commands.Context):
        """Track successful command execution."""
        self.metrics.increment_command(success=True, is_slash=False)

    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: discord.app_commands.Command
    ):
        """Track successful slash command execution."""
        self.metrics.increment_command(success=True, is_slash=True)

    # --------------------------------------------------------------- #
    # Graceful Shutdown
    # --------------------------------------------------------------- #
    async def close(self):
        """
        Gracefully close services before bot shutdown.
        
        Features:
        - Individual service closure with error handling
        - Metrics logging before shutdown
        - Comprehensive shutdown logging
        """
        logger.info("=" * 60)
        logger.info("🛑 RIKI RPG BOT SHUTDOWN")
        logger.info("=" * 60)
        
        # Log final metrics
        if self.metrics.startup_time:
            stats = self.metrics.get_stats()
            logger.info(f"Final Stats:")
            logger.info(f"  Uptime:          {stats['uptime_seconds']:.0f}s")
            logger.info(f"  Commands:        {stats['total_commands']}")
            logger.info(f"  Success Rate:    {stats['success_rate']:.1f}%")
            logger.info(f"  Slash Commands:  {stats['slash_commands']}")
            logger.info(f"  Prefix Commands: {stats['prefix_commands']}")

        async def safe_close(name: str, coro):
            """Close a service safely with error handling."""
            try:
                await coro()
                logger.info(f"✅ {name} closed")
            except Exception as e:
                logger.error(f"⚠️  Error closing {name}: {e}", exc_info=True)

        # Close all services
        await asyncio.gather(
            safe_close("Database", DatabaseService.close),
            safe_close("Redis", RedisService.close),
        )

        await super().close()
        logger.info("=" * 60)
        logger.info("👋 RIKI RPG shutdown complete")
        logger.info("=" * 60)







