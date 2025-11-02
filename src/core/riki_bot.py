import discord
from discord.ext import commands
import asyncio
from typing import List

from src.core.config import Config
from src.core.database_service import DatabaseService
from src.core.redis_service import RedisService
from src.core.config_manager import ConfigManager
from src.core.logger import get_logger
from src.core.loader import load_all_features
from src.core.exceptions import RIKIException, RateLimitError, InsufficientResourcesError
from src.features.tutorial.listener import register_tutorial_listeners
from src.utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class RIKIBot(commands.Bot):
    """
    RIKI RPG Discord Bot

    Handles startup, service orchestration, cog loading, and error management.

    RIKI LAW Compliance:
        - Business logic confined to services
        - Event-driven + transaction-safe
        - Concurrent initialization
        - Dynamic cog discovery
        - Graceful shutdown
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
        """Initialize all core systems and load all features."""
        logger.info("🚀 RIKI setup starting...")

        try:
            # Initialize core services concurrently
            await asyncio.gather(
                DatabaseService.initialize(),
                RedisService.initialize(),
                ConfigManager.initialize(),
            )
            logger.info("✓ Core services initialized")

            # Dynamic cog loading
            await load_all_features(self)
            logger.info("✓ Feature cogs loaded")

            # Event listener registration
            await register_tutorial_listeners(self)
            logger.info("✓ Tutorial listeners registered")

            # Slash command sync
            await self._sync_commands()
            logger.info("✓ Slash commands synced")

            logger.info("🎮 RIKI RPG setup complete.")
        except Exception as e:
            logger.critical(f"Setup error: {e}", exc_info=True)
            raise

    async def _sync_commands(self):
        """Sync commands globally or to dev guild."""
        if Config.is_development() and Config.DISCORD_GUILD_ID:
            guild = discord.Object(id=Config.DISCORD_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info(f"✓ Commands synced to dev guild {Config.DISCORD_GUILD_ID}")
        elif Config.is_production():
            await self.tree.sync()
            logger.info("✓ Commands synced globally")

    # --------------------------------------------------------------- #
    # Events
    # --------------------------------------------------------------- #
    async def on_ready(self):
        total_users = sum(g.member_count for g in self.guilds)
        logger.info(f"✅ Logged in as {self.user} ({self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guilds • {total_users:,} total users")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name=f"/help | r help | {len(self.guilds)} servers",
            )
        )
        logger.info("RIKI RPG Bot is online 🎮")

    async def on_guild_join(self, guild: discord.Guild):
        """Send welcome embed when joining a new guild."""
        logger.info(f"Joined new guild: {guild.name} ({guild.id})")
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            embed = EmbedBuilder.success(
                title="Thanks for adding RIKI RPG!",
                description="Use `/register` to begin your maiden purification journey.",
                footer="Use /help for full command list",
            )
            await guild.system_channel.send(embed=embed)

    async def on_guild_remove(self, guild: discord.Guild):
        logger.info(f"Removed from guild: {guild.name} ({guild.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name=f"/help | r help | {len(self.guilds)} servers",
            )
        )

    # --------------------------------------------------------------- #
    # Error Handling
    # --------------------------------------------------------------- #
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.CommandNotFound):
            return

        original = getattr(error, "original", error)

        if isinstance(original, RateLimitError):
            embed = EmbedBuilder.warning(
                title="Rate Limited",
                description=f"Wait **{original.retry_after:.1f}s** before using this command again.",
            )
            return await ctx.send(embed=embed, ephemeral=True)

        if isinstance(original, InsufficientResourcesError):
            embed = EmbedBuilder.error(
                title="Insufficient Resources",
                description=f"You need **{original.required:,}** {original.resource}, "
                            f"but only have **{original.current:,}**.",
            )
            return await ctx.send(embed=embed, ephemeral=True)

        if isinstance(original, RIKIException):
            embed = EmbedBuilder.error(
                title="Error",
                description=original.message,
                help_text="If this persists, contact support.",
            )
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

        # Fallback
        logger.error(f"Unhandled error in {ctx.command}: {error}", exc_info=True)
        embed = EmbedBuilder.error(
            title="Unexpected Error",
            description="Something went wrong while processing your command.",
            help_text="The issue has been logged.",
        )
        await ctx.send(embed=embed, ephemeral=True)

    # --------------------------------------------------------------- #
    # Graceful Shutdown
    # --------------------------------------------------------------- #
    async def close(self):
        """Gracefully close services before bot shutdown."""
        logger.info("🛑 Shutting down RIKI RPG...")

        async def safe_close(name: str, coro):
            try:
                await coro()
                logger.info(f"✓ {name} closed successfully")
            except Exception as e:
                logger.error(f"Error closing {name}: {e}", exc_info=True)

        await asyncio.gather(
            safe_close("Database", DatabaseService.close),
            safe_close("Redis", RedisService.close),
        )

        await super().close()
        logger.info("RIKI RPG shutdown complete 👋")
