"""
Base Discord cog for RIKI LAW compliant command modules.

Provides common utilities and enforces architectural patterns
for all feature cogs in the RIKI RPG Bot.

RIKI LAW Compliance:
- Article VI: Enforces Discord layer only (no business logic in cogs)
- Article VII: Standardizes error handling and user feedback
- Article II: Ensures transaction logging compliance

Usage:
    Cogs should inherit BaseCog and use provided utilities:

    >>> class MyCog(BaseCog):
    ...     def __init__(self, bot: commands.Bot):
    ...         super().__init__(bot, cog_name="MyCog")
    ...
    ...     @commands.hybrid_command(name="mycommand")
    ...     async def my_command(self, ctx: commands.Context):
    ...         await self.safe_defer(ctx)
    ...         try:
    ...             # ... your logic ...
    ...         except InsufficientResourcesError as e:
    ...             await self.send_error(ctx, "Insufficient Resources", str(e))

Design Philosophy:
    - Cogs handle Discord interactions only
    - All business logic delegated to service layer
    - Standardized error handling and user feedback
    - Common patterns extracted to reduce boilerplate
"""

import discord
from discord.ext import commands
from typing import Optional, Union
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
    Base class for all feature cogs.

    Provides common utilities for error handling, database access,
    and user feedback while enforcing RIKI LAW principles.
    """

    def __init__(self, bot: commands.Bot, cog_name: str):
        """
        Initialize base cog.

        Args:
            bot: Discord bot instance
            cog_name: Name of the cog for logging (e.g., "AscensionCog")
        """
        self.bot = bot
        self.cog_name = cog_name
        self.logger = get_logger(cog_name)

    # ========================================================================
    # DATABASE UTILITIES
    # ========================================================================

    async def get_session(self):
        """
        Get database session for transactions.

        Returns:
            AsyncSession context manager

        Example:
            >>> async with self.get_session() as session:
            ...     player = await PlayerService.get_player(session, user_id)
        """
        return DatabaseService.get_transaction()

    # ========================================================================
    # USER INTERACTION UTILITIES
    # ========================================================================

    async def safe_defer(
        self,
        ctx_or_interaction: Union[commands.Context, discord.Interaction],
        ephemeral: bool = False
    ) -> None:
        """
        Safely defer response (handles both Context and Interaction).

        Args:
            ctx_or_interaction: Context or Interaction object
            ephemeral: Whether response should be ephemeral

        Example:
            >>> await self.safe_defer(ctx)
            >>> # Long operation
            >>> await ctx.send(embed=embed)
        """
        try:
            if isinstance(ctx_or_interaction, discord.Interaction):
                if not ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.response.defer(ephemeral=ephemeral)
            else:
                await ctx_or_interaction.defer(ephemeral=ephemeral)
        except Exception as e:
            self.logger.warning(f"Failed to defer: {e}")

    async def send_error(
        self,
        ctx_or_interaction: Union[commands.Context, discord.Interaction],
        title: str,
        description: str,
        help_text: Optional[str] = None,
        ephemeral: bool = True
    ) -> None:
        """
        Send error embed to user.

        Args:
            ctx_or_interaction: Context or Interaction object
            title: Error title
            description: Error description
            help_text: Optional help text
            ephemeral: Whether message should be ephemeral

        Example:
            >>> await self.send_error(
            ...     ctx,
            ...     "Insufficient Resources",
            ...     "You need 1000 rikis to perform this fusion."
            ... )
        """
        embed = EmbedBuilder.error(
            title=title,
            description=description,
            help_text=help_text
        )
        await self._send_embed(ctx_or_interaction, embed, ephemeral)

    async def send_success(
        self,
        ctx_or_interaction: Union[commands.Context, discord.Interaction],
        title: str,
        description: str,
        footer: Optional[str] = None,
        ephemeral: bool = False
    ) -> None:
        """
        Send success embed to user.

        Args:
            ctx_or_interaction: Context or Interaction object
            title: Success title
            description: Success description
            footer: Optional footer text
            ephemeral: Whether message should be ephemeral

        Example:
            >>> await self.send_success(
            ...     ctx,
            ...     "Fusion Complete!",
            ...     "Your maiden has been upgraded to Tier 6."
            ... )
        """
        embed = EmbedBuilder.success(
            title=title,
            description=description,
            footer=footer
        )
        await self._send_embed(ctx_or_interaction, embed, ephemeral)

    async def send_info(
        self,
        ctx_or_interaction: Union[commands.Context, discord.Interaction],
        title: str,
        description: str,
        footer: Optional[str] = None,
        ephemeral: bool = False
    ) -> None:
        """
        Send info embed to user.

        Args:
            ctx_or_interaction: Context or Interaction object
            title: Info title
            description: Info description
            footer: Optional footer text
            ephemeral: Whether message should be ephemeral

        Example:
            >>> await self.send_info(
            ...     ctx,
            ...     "Current Progress",
            ...     f"You are on floor {floor} of the ascension tower."
            ... )
        """
        embed = EmbedBuilder.info(
            title=title,
            description=description,
            footer=footer
        )
        await self._send_embed(ctx_or_interaction, embed, ephemeral)

    async def _send_embed(
        self,
        ctx_or_interaction: Union[commands.Context, discord.Interaction],
        embed: discord.Embed,
        ephemeral: bool = False
    ) -> None:
        """Send embed handling both Context and Interaction."""
        try:
            if isinstance(ctx_or_interaction, discord.Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(embed=embed, ephemeral=ephemeral)
                else:
                    await ctx_or_interaction.response.send_message(embed=embed, ephemeral=ephemeral)
            else:
                await ctx_or_interaction.send(embed=embed, ephemeral=ephemeral)
        except Exception as e:
            self.logger.error(f"Failed to send embed: {e}")

    # ========================================================================
    # ERROR HANDLING UTILITIES
    # ========================================================================

    async def handle_standard_errors(
        self,
        ctx_or_interaction: Union[commands.Context, discord.Interaction],
        error: Exception
    ) -> bool:
        """
        Handle standard RIKI exceptions with user-friendly messages.

        Args:
            ctx_or_interaction: Context or Interaction object
            error: Exception that occurred

        Returns:
            True if error was handled, False if unhandled

        Example:
            >>> try:
            ...     # some operation
            ... except Exception as e:
            ...     if not await self.handle_standard_errors(ctx, e):
            ...         raise  # Re-raise if not handled
        """
        if isinstance(error, InsufficientResourcesError):
            await self.send_error(
                ctx_or_interaction,
                "Insufficient Resources",
                str(error),
                help_text="Check your inventory and try again."
            )
            return True

        elif isinstance(error, InvalidOperationError):
            await self.send_error(
                ctx_or_interaction,
                "Invalid Operation",
                str(error)
            )
            return True

        elif isinstance(error, CooldownError):
            await self.send_error(
                ctx_or_interaction,
                "Cooldown Active",
                str(error),
                help_text="Please wait before trying again."
            )
            return True

        elif isinstance(error, NotFoundError):
            await self.send_error(
                ctx_or_interaction,
                "Not Found",
                str(error)
            )
            return True

        return False

    # ========================================================================
    # PLAYER VALIDATION UTILITIES
    # ========================================================================

    async def require_player(
        self,
        ctx_or_interaction: Union[commands.Context, discord.Interaction],
        session,
        player_id: int,
        lock: bool = False
    ):
        """
        Get player or send registration error if not found.

        Args:
            ctx_or_interaction: Context or Interaction object
            session: Database session
            player_id: Player's Discord ID
            lock: Whether to lock row for update

        Returns:
            Player object or None if not registered

        Example:
            >>> async with self.get_session() as session:
            ...     player = await self.require_player(ctx, session, ctx.author.id, lock=True)
            ...     if not player:
            ...         return  # Error already sent
            ...     # Continue with player
        """
        from src.features.player.service import PlayerService

        player = await PlayerService.get_player_with_regen(
            session, player_id, lock=lock
        )

        if not player:
            await self.send_error(
                ctx_or_interaction,
                "Not Registered",
                "You need to register first!",
                help_text="Use `/register` to create your account."
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
    ) -> None:
        """
        Log command usage for analytics.

        Args:
            command_name: Name of command
            user_id: User's Discord ID
            guild_id: Optional guild ID
            **kwargs: Additional context

        Example:
            >>> self.log_command_use(
            ...     "fusion",
            ...     user_id=ctx.author.id,
            ...     guild_id=ctx.guild.id if ctx.guild else None,
            ...     tier=5
            ... )
        """
        context = LogContext(
            service=self.cog_name,
            operation=command_name,
            player_id=user_id,
            guild_id=guild_id,
            **kwargs
        )
        self.logger.info(
            f"Command used: /{command_name}",
            extra={"context": context}
        )

    def log_cog_error(
        self,
        operation: str,
        error: Exception,
        user_id: Optional[int] = None,
        **kwargs
    ) -> None:
        """
        Log cog-level errors.

        Args:
            operation: Operation that failed
            error: Exception that occurred
            user_id: Optional user ID
            **kwargs: Additional context

        Example:
            >>> try:
            ...     # some operation
            ... except Exception as e:
            ...     self.log_cog_error("process_fusion", e, user_id=ctx.author.id)
            ...     raise
        """
        context = LogContext(
            service=self.cog_name,
            operation=operation,
            player_id=user_id,
            **kwargs
        )
        self.logger.error(
            f"{self.cog_name}.{operation} failed: {str(error)}",
            exc_info=error,
            extra={"context": context}
        )
