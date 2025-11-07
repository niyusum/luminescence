"""
Base Discord Cog for RIKI LAW–compliant prefix-only command modules.

Enforces architectural patterns for all feature cogs
in the RIKI RPG Bot (post-slash-removal architecture).

RIKI LAW Compliance:
- Article VI: Cogs handle Discord layer only (UI and context)
- Article VII: Standardized error handling and user feedback
- Article II: Enforces transaction logging and audit integrity
"""

import discord
from discord.ext import commands
from typing import Optional
from datetime import datetime

from src.core.infra.database_service import DatabaseService
from src.core.infra.transaction_logger import TransactionLogger
from src.core.logging.logger import get_logger, LogContext
from src.core.exceptions import (
    InsufficientResourcesError,
    InvalidOperationError,
    CooldownError,
    NotFoundError
)
from utils.embed_builder import EmbedBuilder


class BaseCog(commands.Cog):
    """
    Base class for all feature cogs (prefix-only).
    
    Provides common utilities for error handling, database access,
    and consistent feedback while enforcing RIKI LAW.
    """

    def __init__(self, bot: commands.Bot, cog_name: str):
        """
        Initialize BaseCog.

        Args:
            bot: Discord bot instance
            cog_name: Name of the cog (e.g., "AscensionCog")
        """
        self.bot = bot
        self.cog_name = cog_name
        self.logger = get_logger(cog_name)

    # ========================================================================
    # DATABASE UTILITIES
    # ========================================================================

    async def get_session(self):
        """Return an async database transaction context."""
        return DatabaseService.get_transaction()

    # ========================================================================
    # USER FEEDBACK UTILITIES
    # ========================================================================

    async def defer(self, ctx: commands.Context):
        """
        Indicate to the user that a long operation is in progress.

        Uses ctx.typing() instead of Discord interaction defer.
        """
        try:
            await ctx.typing()
        except Exception as e:
            self.logger.warning(f"Failed to start typing indicator: {e}")

    async def send_error(
        self,
        ctx: commands.Context,
        title: str,
        description: str,
        help_text: Optional[str] = None
    ):
        """Send standardized error feedback."""
        embed = EmbedBuilder.error(title=title, description=description, help_text=help_text)
        await self._safe_send(ctx, embed)

    async def send_success(
        self,
        ctx: commands.Context,
        title: str,
        description: str,
        footer: Optional[str] = None
    ):
        """Send standardized success feedback."""
        embed = EmbedBuilder.success(title=title, description=description, footer=footer)
        await self._safe_send(ctx, embed)

    async def send_info(
        self,
        ctx: commands.Context,
        title: str,
        description: str,
        footer: Optional[str] = None
    ):
        """Send standardized informational feedback."""
        embed = EmbedBuilder.info(title=title, description=description, footer=footer)
        await self._safe_send(ctx, embed)

    async def _safe_send(self, ctx: commands.Context, embed: discord.Embed):
        """Send embed safely to the invoking context."""
        try:
            await ctx.reply(embed=embed)
        except Exception as e:
            self.logger.error(f"Failed to send embed in {self.cog_name}: {e}")

    # ========================================================================
    # STANDARDIZED ERROR HANDLING
    # ========================================================================

    async def handle_standard_errors(self, ctx: commands.Context, error: Exception) -> bool:
        """
        Handle known RIKI LAW exceptions with user-friendly responses.

        Returns:
            bool: True if handled, False otherwise.
        """
        if isinstance(error, InsufficientResourcesError):
            await self.send_error(ctx, "Insufficient Resources", str(error),
                                  "Check your inventory and try again.")
            return True

        if isinstance(error, InvalidOperationError):
            await self.send_error(ctx, "Invalid Operation", str(error))
            return True

        if isinstance(error, CooldownError):
            await self.send_error(ctx, "Cooldown Active", str(error),
                                  "Please wait before retrying.")
            return True

        if isinstance(error, NotFoundError):
            await self.send_error(ctx, "Not Found", str(error))
            return True

        return False

    # ========================================================================
    # PLAYER VALIDATION UTILITIES
    # ========================================================================

    async def require_player(self, ctx: commands.Context, session, player_id: int, lock: bool = False):
        """
        Retrieve a player or inform them to register if missing.
        """
        from src.features.player.service import PlayerService

        player = await PlayerService.get_player_with_regen(session, player_id, lock=lock)
        if not player:
            await self.send_error(
                ctx,
                "Not Registered",
                "You need to register first!",
                help_text="Use `rregister` to create your account."
            )
            return None
        return player

    # ========================================================================
    # LOGGING UTILITIES
    # ========================================================================

    def log_command_use(
        self,
        command_name: str,
        user_id: int,
        guild_id: Optional[int] = None,
        **kwargs
    ):
        """
        Log command usage for observability and analytics.
        """
        context = LogContext(
            service=self.cog_name,
            operation=command_name,
            player_id=user_id,
            guild_id=guild_id,
            **kwargs
        )
        self.logger.info(f"Command used: r{command_name}", extra={"context": context})

    def log_cog_error(
        self,
        operation: str,
        error: Exception,
        user_id: Optional[int] = None,
        **kwargs
    ):
        """
        Log cog-level operational errors.
        """
        context = LogContext(
            service=self.cog_name,
            operation=operation,
            player_id=user_id,
            **kwargs
        )
        self.logger.error(
            f"{self.cog_name}.{operation} failed: {error}",
            exc_info=error,
            extra={"context": context}
        )
