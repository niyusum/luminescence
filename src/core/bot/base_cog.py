"""
Base Discord Cog for Lumen (2025)

Purpose
-------
Provide foundational infrastructure for all feature cogs in the Lumen RPG bot.
Enforces architectural patterns, standardized error handling, and consistent
user feedback while maintaining LUMEN LAW compliance across the Discord layer.

This base class serves as the parent for all feature cogs (Fusion, Ascension,
Collection, etc.), providing common utilities and enforcing separation between
Discord UI concerns and business logic.

Responsibilities
----------------
- Provide database session management utilities
- Standardize user feedback (success/error/info embeds)
- Handle domain exceptions with user-friendly messages
- Enforce player validation and registration checks
- Provide structured logging with Discord context
- Support Discord View error handling
- Create user validation checks for interactive components

Non-Responsibilities
--------------------
- Business logic (delegated to service layer)
- Database operations (delegated to service layer)
- Event handling (handled by dedicated listeners)
- Bot lifecycle management (handled by BotLifecycle)

LUMEN LAW Compliance
--------------------
- Article VI: Cogs handle Discord layer only (UI and context)
- Article VII: Standardized error handling and user feedback
- Article II: Transaction logging and audit integrity
- Article I: Transaction-safe operations via DatabaseService
- Article IX: Graceful error handling with fallbacks
- Article X: Structured logging for observability

Architecture Notes
------------------
- **Prefix-only architecture**: Post-slash-command removal, all commands use prefix
- **Error boundaries**: Converts domain exceptions to Discord embeds
- **Context injection**: All operations include Discord context for audit trails
- **Layered design**: Cog → Service → Repository → Database
- **Reusable utilities**: Common patterns extracted for DRY compliance

Key Features
------------
**Database Access**:
- `get_session()`: Returns async transaction context from DatabaseService

**User Feedback**:
- `send_success()`: Standardized success embed
- `send_error()`: Standardized error embed
- `send_info()`: Standardized informational embed
- `defer()`: Typing indicator for long operations

**Error Handling**:
- `handle_standard_errors()`: Converts domain exceptions to user-friendly messages
- `handle_view_error()`: Error handling for Discord View interactions

**Validation**:
- `require_player()`: Player existence check with registration prompt
- `create_user_validation_check()`: User authorization for interactive components

**Logging**:
- `log_command_use()`: Command execution logging with context
- `log_cog_error()`: Cog-level error logging with context

Usage Example
-------------
Creating a feature cog:

>>> from src.core.bot.base_cog import BaseCog
>>> from discord.ext import commands
>>>
>>> class FusionCog(BaseCog):
>>>     def __init__(self, bot: commands.Bot):
>>>         super().__init__(bot, "FusionCog")
>>>
>>>     @commands.command(name="fuse")
>>>     async def fuse(self, ctx: commands.Context, tier: int):
>>>         '''Fuse two maidens to create a higher tier maiden.'''
>>>         await self.defer(ctx)  # Show typing indicator
>>>
>>>         async with self.get_session() as session:
>>>             # Validate player exists
>>>             player = await self.require_player(ctx, session, ctx.author.id, lock=True)
>>>             if not player:
>>>                 return
>>>
>>>             try:
>>>                 # Business logic in service layer
>>>                 result = await FusionService.fuse_maidens(session, player.id, tier)
>>>
>>>                 # Success feedback
>>>                 await self.send_success(
>>>                     ctx,
>>>                     "Fusion Complete!",
>>>                     f"Created a Tier {result.tier} maiden!"
>>>                 )
>>>
>>>             except InsufficientResourcesError as e:
>>>                 await self.send_error(ctx, "Insufficient Resources", str(e))

Discord View Integration Example
---------------------------------
Using BaseCog utilities in Discord Views:

>>> class FusionView(discord.ui.View):
>>>     def __init__(self, user_id: int, cog: BaseCog):
>>>         super().__init__(timeout=120)
>>>         self.user_id = user_id
>>>         self.cog = cog
>>>         self.validate_user = cog.create_user_validation_check(user_id)
>>>
>>>     @discord.ui.button(label="Confirm Fusion")
>>>     async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
>>>         # Validate user authorization
>>>         if not await self.validate_user(interaction):
>>>             return
>>>
>>>         try:
>>>             await interaction.response.defer()
>>>             # Execute fusion logic...
>>>             await self.cog.send_success(interaction, "Success!", "Fusion complete!")
>>>         except Exception as e:
>>>             await self.cog.handle_view_error(interaction, e, "fusion_confirm")
"""

import discord
from discord.ext import commands
from typing import Optional
from datetime import datetime

from src.core.database.service import DatabaseService
from src.core.infra.transaction_logger import TransactionLogger
from src.core.logging.logger import get_logger, LogContext
from src.core.exceptions import (
    InsufficientResourcesError,
    InvalidOperationError,
    CooldownError,
    NotFoundError,
    RateLimitError
)
from src.utils.embed_builder import EmbedBuilder


class BaseCog(commands.Cog):
    """
    Base class for all feature cogs (prefix-only).
    
    Provides common utilities for error handling, database access,
    and consistent feedback while enforcing LUMEN LAW.
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
        Handle known LUMEN LAW exceptions with user-friendly responses.

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

        if isinstance(error, RateLimitError):
            await self.send_error(ctx, "Rate Limit Exceeded", str(error),
                                  "You're using this command too frequently. Please slow down.")
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
        from src.modules.player.service import PlayerService

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

    # ========================================================================
    # DISCORD VIEW UTILITIES
    # ========================================================================

    def create_user_validation_check(self, user_id: int):
        """
        Create a reusable user validation function for Discord Views.

        Returns an async function that validates interaction user and sends
        an ephemeral error message if the user is not authorized.

        Args:
            user_id: Discord user ID who is authorized to use the view

        Returns:
            Async function that returns True if user is valid, False otherwise

        Usage in View:
            class MyView(discord.ui.View):
                def __init__(self, user_id: int, cog: BaseCog):
                    super().__init__(timeout=120)
                    self.user_id = user_id
                    self.validate_user = cog.create_user_validation_check(user_id)

                @discord.ui.button(label="Click")
                async def button(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if not await self.validate_user(interaction):
                        return  # User validation failed, error sent

                    # Continue with button logic...
        """
        async def check(interaction: discord.Interaction) -> bool:
            if interaction.user.id != user_id:
                await interaction.response.send_message(
                    "This button is not for you!",
                    ephemeral=True
                )
                return False
            return True

        return check

    async def handle_view_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        operation_name: str,
        **context
    ):
        """
        Standardized error handling for Discord View interactions.

        Converts domain exceptions to user-friendly embeds and logs errors
        with full context. Handles both response and followup scenarios.

        Args:
            interaction: Discord interaction from button/modal/select callback
            operation_name: Name of the operation for logging (e.g., "fusion_execute")
            error: Exception that occurred
            **context: Additional context for logging (e.g., guild_id, floor, etc.)

        Usage in View:
            try:
                # Execute view logic...
                await SomeService.do_something(...)
            except Exception as e:
                await self.cog.handle_view_error(
                    interaction, e, "view_action",
                    guild_id=interaction.guild_id
                )
                # Optionally disable view
                await interaction.edit_original_response(view=None)

        LUMEN LAW Compliance:
            - Converts domain exceptions to Discord embeds (Article I.5)
            - Logs with full context (Article II)
            - Provides user-friendly error messages
        """
        # Log the error with context
        self.log_cog_error(
            operation_name,
            error,
            user_id=interaction.user.id,
            guild_id=interaction.guild.id if interaction.guild else None,
            **context
        )

        # Build appropriate error embed based on exception type
        if isinstance(error, InsufficientResourcesError):
            embed = EmbedBuilder.error(
                title="Insufficient Resources",
                description=str(error),
                help_text="Check your inventory and try again."
            )
        elif isinstance(error, InvalidOperationError):
            embed = EmbedBuilder.error(
                title="Invalid Operation",
                description=str(error)
            )
        elif isinstance(error, CooldownError):
            embed = EmbedBuilder.warning(
                title="Cooldown Active",
                description=str(error)
            )
        elif isinstance(error, RateLimitError):
            embed = EmbedBuilder.warning(
                title="Rate Limit Exceeded",
                description=str(error),
                help_text="You're using this command too frequently. Please slow down."
            )
        elif isinstance(error, NotFoundError):
            embed = EmbedBuilder.error(
                title="Not Found",
                description=str(error)
            )
        else:
            # Generic error for unexpected exceptions
            embed = EmbedBuilder.error(
                title="Something Went Wrong",
                description="An unexpected error occurred.",
                help_text="The issue has been logged."
            )

        # Send error embed (ephemeral)
        try:
            # Try followup first (if response was already deferred)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.InteractionResponded:
            # If already responded, try editing
            try:
                await interaction.edit_original_response(embed=embed)
            except Exception as edit_error:
                self.logger.warning(f"Failed to edit interaction response: {edit_error}")
        except Exception as send_error:
            self.logger.warning(f"Failed to send error message to user: {send_error}")
