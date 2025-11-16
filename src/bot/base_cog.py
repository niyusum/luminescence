"""
Base Discord Cog for Lumen (2025)

Purpose
-------
Provide foundational infrastructure for all feature cogs in the Lumen RPG bot.
Enforces architectural patterns, standardized error handling, and consistent
user feedback while maintaining LUMEN LAW compliance across the Discord layer.

Responsibilities
----------------
- Provide database session convenience (service-managed transactions)
- Standardize user feedback (success/error/info embeds)
- Handle domain exceptions with user-friendly messages
- Provide structured logging with Discord context
- Support Discord View error handling helpers
- Provide user validation helpers for interactive components

Non-Responsibilities
--------------------
- Business logic (delegated to service layer)
- Database mutation rules, locking, or transactions (delegated to services)
- Bot lifecycle or feature loading (handled elsewhere)
- Event bus emissions

Lumen 2025 Compliance
---------------------
- Cogs are Discord-only UI surfaces (no business logic)
- All errors converted into structured embeds
- Logging uses LogContext with Discord IDs where available
- No direct database writes; only uses DatabaseService transaction contexts

Architecture Notes
------------------
- Prefix-only architecture (slash commands removed)
- Error boundaries: domain exceptions → user-friendly embeds
- Layered: Cog → Service → Infra
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

import discord
from discord.ext import commands

from src.core.database.service import DatabaseService
from src.core.logging.logger import LogContext, get_logger
from src.modules.shared.exceptions import (
    CooldownActiveError,
    InsufficientResourcesError,
    InvalidOperationError,
    NotFoundError,
    RateLimitError,
)
from src.ui.utils.embed_builder import EmbedBuilder

# Legacy alias for backward compatibility
CooldownError = CooldownActiveError


class BaseCog(commands.Cog):
    """
    Base class for all feature cogs (prefix-only).

    Provides common utilities for:
    - safe database transaction contexts
    - standardized feedback embeds
    - domain-aware error handling
    - Discord View helper utilities
    """

    def __init__(self, bot: commands.Bot, cog_name: str) -> None:
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

    def get_session(self):
        """
        Return an async database transaction context manager.

        Usage:
            async with self.get_session() as session:
                ...

        Transaction semantics (enforced by DatabaseService):
        - Atomic transaction per context
        - Pessimistic locking for writes
        - No manual commits in the cog layer
        """
        return DatabaseService.get_transaction()

    # ========================================================================
    # USER FEEDBACK UTILITIES
    # ========================================================================

    async def defer(self, ctx: commands.Context) -> None:
        """
        Indicate to the user that a long operation is in progress.

        Uses ctx.typing() for prefix commands.
        """
        try:
            await ctx.typing()
        except Exception as exc:  # Best-effort UX hint
            self.logger.warning(
                "Failed to start typing indicator",
                extra={"error": str(exc), "error_type": type(exc).__name__},
            )

    async def send_error(
        self,
        ctx: commands.Context,
        title: str,
        description: str,
        help_text: Optional[str] = None,
    ) -> None:
        """Send standardized error feedback."""
        embed = EmbedBuilder.error(title=title, description=description, help_text=help_text)
        await self._safe_send(ctx, embed)

    async def send_success(
        self,
        ctx: commands.Context,
        title: str,
        description: str,
        footer: Optional[str] = None,
    ) -> None:
        """Send standardized success feedback."""
        embed = EmbedBuilder.success(title=title, description=description, footer=footer)
        await self._safe_send(ctx, embed)

    async def send_info(
        self,
        ctx: commands.Context,
        title: str,
        description: str,
        footer: Optional[str] = None,
    ) -> None:
        """Send standardized informational feedback."""
        embed = EmbedBuilder.info(title=title, description=description, footer=footer)
        await self._safe_send(ctx, embed)

    async def _safe_send(self, ctx: commands.Context, embed: discord.Embed) -> None:
        """
        Safely send an embed to the invoking context.

        Uses reply when possible, falls back to send.
        """
        try:
            if ctx.message:
                await ctx.reply(embed=embed, mention_author=False)
            else:
                await ctx.send(embed=embed)
        except Exception as exc:
            self.logger.error(
                "Failed to send embed from BaseCog",
                extra={
                    "cog_name": self.cog_name,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )

    # ========================================================================
    # STANDARDIZED ERROR HANDLING (COMMAND CONTEXT)
    # ========================================================================

    async def handle_standard_errors(self, ctx: commands.Context, error: Exception) -> bool:
        """
        Handle known domain exceptions with user-friendly responses.

        Returns:
            True if the error was handled and a response was sent, False otherwise.
        """
        if isinstance(error, InsufficientResourcesError):
            await self.send_error(
                ctx,
                "Insufficient Resources",
                str(error),
                "Check your inventory and try again.",
            )
            return True

        if isinstance(error, InvalidOperationError):
            await self.send_error(ctx, "Invalid Operation", str(error))
            return True

        if isinstance(error, CooldownError):
            await self.send_error(
                ctx,
                "Cooldown Active",
                str(error),
                "Please wait before retrying.",
            )
            return True

        if isinstance(error, RateLimitError):
            await self.send_error(
                ctx,
                "Rate Limit Exceeded",
                str(error),
                "You're using this command too frequently. Please slow down.",
            )
            return True

        if isinstance(error, NotFoundError):
            await self.send_error(ctx, "Not Found", str(error))
            return True

        return False

    # ========================================================================
    # LOGGING UTILITIES
    # ========================================================================

    def log_command_use(
        self,
        command_name: str,
        user_id: int,
        guild_id: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """
        Log command usage for observability and analytics.

        Uses LogContext to attach player/guild information in a structured way.
        """
        context = LogContext(
            service=self.cog_name,
            operation=command_name,
            player_id=user_id,
            guild_id=guild_id,
            **kwargs,
        )
        self.logger.info(
            "Command used",
            extra={"context": context},
        )

    def log_cog_error(
        self,
        operation: str,
        error: Exception,
        user_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """
        Log cog-level operational errors with context.

        Args:
            operation: Logical operation name (e.g., "fusion_execute")
            error: Exception that occurred
            user_id: Discord user ID if available
            guild_id: Discord guild ID if available
        """
        context = LogContext(
            service=self.cog_name,
            operation=operation,
            player_id=user_id,
            guild_id=guild_id,
            **kwargs,
        )
        self.logger.error(
            f"{self.cog_name}.{operation} failed: {error}",
            exc_info=error,
            extra={"context": context},
        )

    # ========================================================================
    # DISCORD VIEW UTILITIES
    # ========================================================================

    def create_user_validation_check(
        self,
        user_id: int,
    ) -> Callable[[discord.Interaction], Awaitable[bool]]:
        """
        Create a reusable user validation function for Discord Views.

        Returns an async function that validates the interaction user and sends
        an ephemeral error message if the user is not authorized.

        Args:
            user_id: Discord user ID who is authorized to use the view
        """

        async def check(interaction: discord.Interaction) -> bool:
            if interaction.user.id != user_id:
                try:
                    await interaction.response.send_message(
                        "This button is not for you!",
                        ephemeral=True,
                    )
                except discord.InteractionResponded:
                    # Already responded; try followup as best-effort
                    try:
                        await interaction.followup.send(
                            "This button is not for you!",
                            ephemeral=True,
                        )
                    except Exception as exc:
                        self.logger.warning(
                            "Failed to send unauthorized interaction message",
                            extra={"error": str(exc), "error_type": type(exc).__name__},
                        )
                return False
            return True

        return check

    async def handle_view_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        operation_name: str,
        **context: object,
    ) -> None:
        """
        Standardized error handling for Discord View interactions.

        Converts domain exceptions to user-friendly embeds and logs errors
        with full context. Handles both response and followup scenarios.

        Args:
            interaction: Discord interaction from button/modal/select callback
            operation_name: Name of the operation for logging (e.g., "fusion_confirm")
            error: Exception that occurred
            **context: Additional context for logging (e.g., guild_id, floor, etc.)
        """
        self.log_cog_error(
            operation_name,
            error,
            user_id=interaction.user.id,
            guild_id=interaction.guild.id if interaction.guild else None,
            **context,
        )

        # Build appropriate error embed
        if isinstance(error, InsufficientResourcesError):
            embed = EmbedBuilder.error(
                title="Insufficient Resources",
                description=str(error),
                help_text="Check your inventory and try again.",
            )
        elif isinstance(error, InvalidOperationError):
            embed = EmbedBuilder.error(
                title="Invalid Operation",
                description=str(error),
            )
        elif isinstance(error, CooldownError):
            embed = EmbedBuilder.warning(
                title="Cooldown Active",
                description=str(error),
            )
        elif isinstance(error, RateLimitError):
            embed = EmbedBuilder.warning(
                title="Rate Limit Exceeded",
                description=str(error),
            )
        elif isinstance(error, NotFoundError):
            embed = EmbedBuilder.error(
                title="Not Found",
                description=str(error),
            )
        else:
            embed = EmbedBuilder.error(
                title="Something Went Wrong",
                description="An unexpected error occurred while handling your action.",
                help_text="The issue has been logged.",
            )

        # Send error embed (ephemeral where possible)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as send_error:
            self.logger.warning(
                "Failed to send view error message",
                extra={
                    "error": str(send_error),
                    "error_type": type(send_error).__name__,
                },
            )
