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
- Accept dependencies via constructor injection (ServiceContainer, ErrorResponseService)

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
- Constructor injection for all dependencies (P0.5, P0.6)
- No service locator pattern (deprecated: bot.service_container)

Architecture Notes
------------------
- Prefix-only architecture (slash commands removed)
- Error boundaries: domain exceptions → user-friendly embeds
- Layered: Cog → Service → Infra
- Dependency injection: ServiceContainer passed in constructor

Usage Example
-------------
>>> # Recommended: explicit dependency injection
>>> class FusionCog(BaseCog):
...     def __init__(self, bot, service_container, error_response_service):
...         super().__init__(
...             bot=bot,
...             cog_name="FusionCog",
...             service_container=service_container,
...             error_response_service=error_response_service,
...         )
...         # Access services via self.service_container
...         self.fusion_service = service_container.fusion_service
...
...     @commands.command()
...     async def fuse(self, ctx, maiden1_id: int, maiden2_id: int):
...         result = await self.fusion_service.execute_fusion(...)
...         await self.send_success(ctx, "Fusion Complete", result.message)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

import discord
from discord.ext import commands

from src.core.database.service import DatabaseService
from src.core.logging.logger import LogContext, get_logger
from src.core.services.error_response_service import ErrorResponseService
from src.modules.shared.exceptions import CooldownActiveError, ErrorSeverity
from src.ui.utils.embed_builder import EmbedBuilder

if TYPE_CHECKING:
    from src.core.services.container import ServiceContainer

# Legacy alias for backward compatibility
CooldownError = CooldownActiveError


class BaseCog(commands.Cog):
    """
    Base class for all feature cogs (prefix-only).

    Provides common utilities for:
    - safe database transaction contexts
    - standardized feedback embeds
    - domain-aware error handling via ErrorResponseService
    - Discord View helper utilities
    - dependency injection for ServiceContainer

    LUMEN LAW / LES 2025 Compliance
    -------------------------------
    - Uses ErrorResponseService for exception formatting (P0.1, P0.2)
    - No hardcoded error messages in presentation layer
    - Constructor injection for dependencies (P0.5, P0.6)
    - ServiceContainer passed as parameter, not accessed via bot.service_container
    - Explicit dependency graph enables testing and maintainability

    Attributes
    ----------
    bot : commands.Bot
        Discord bot instance
    cog_name : str
        Name of the cog for logging
    logger : Logger
        Structured logger for this cog
    service_container : Optional[ServiceContainer]
        Domain service container for accessing business services
    error_response_service : ErrorResponseService
        Service for formatting error responses
    """

    def __init__(
        self,
        bot: commands.Bot,
        cog_name: str,
        service_container: Optional[ServiceContainer] = None,
        error_response_service: Optional[ErrorResponseService] = None,
    ) -> None:
        """
        Initialize BaseCog with dependency injection.

        Args:
            bot: Discord bot instance
            cog_name: Name of the cog (e.g., "AscensionCog")
            service_container: Domain service container for accessing business services.
                If None, falls back to bot.service_container (for backward compatibility).
            error_response_service: Service for formatting error responses.
                If None, creates a new instance (for backward compatibility).

        LES 2025 Compliance:
            - Constructor injection for all dependencies (P0.5, P0.6)
            - No service locator pattern (bot.service_container deprecated)
            - Explicit dependency graph
        """
        self.bot = bot
        self.cog_name = cog_name
        self.logger = get_logger(cog_name)

        # Service container (constructor injection preferred)
        self.service_container = service_container or getattr(bot, 'service_container', None)

        # Error response service
        self.error_response_service = error_response_service or ErrorResponseService()

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

        Uses ErrorResponseService to format exceptions following LES 2025 standards.

        Returns:
            True if the error was handled and a response was sent, False otherwise.
        """
        # Format error using ErrorResponseService
        response = await self.error_response_service.format_error(error)

        # Check if this is a known error type (has a template)
        from src.domain.exceptions.registry import get_exception_template
        template = get_exception_template(error)

        if template is None:
            # Unknown error type, not handled here
            return False

        # Send formatted error response
        await self.send_error(
            ctx,
            title=response["title"],
            description=response["description"],
            help_text=response.get("help_text"),
        )
        return True

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

        Converts domain exceptions to user-friendly embeds using ErrorResponseService
        and logs errors with full context. Handles both response and followup scenarios.

        Uses ErrorResponseService for formatting following LES 2025 standards.

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

        # Format error using ErrorResponseService
        response = await self.error_response_service.format_error(error)

        # Build embed based on severity
        severity = response["severity"]
        if severity in (ErrorSeverity.DEBUG, ErrorSeverity.INFO):
            embed = EmbedBuilder.warning(
                title=response["title"],
                description=response["description"],
            )
        else:
            embed = EmbedBuilder.error(
                title=response["title"],
                description=response["description"],
                help_text=response.get("help_text"),
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
