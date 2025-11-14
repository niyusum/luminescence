"""
Base view classes with common patterns.

Provides reusable base classes for Discord views with:
- User validation
- Timeout handling
- Message tracking
- Logging integration

All custom views should inherit from BaseView or BaseModalView.

Usage:
    >>> class MyView(BaseView):
    ...     def __init__(self, user_id: int):
    ...         super().__init__(user_id, timeout=180)
    ...
    ...     @discord.ui.button(label="Click Me")
    ...     async def my_button(self, interaction, button):
    ...         if not await self.check_user(interaction):
    ...             return
    ...         await interaction.response.send_message("Clicked!")
"""

import discord
from discord.ui import View
from typing import Optional, Callable
from src.core.logging.logger import get_logger


class BaseView(View):
    """
    Base view class with common functionality.

    Provides:
    - User validation
    - Timeout handling
    - Message tracking
    - Optional logging

    All view interactions should check user authorization via check_user().
    """

    def __init__(
        self,
        user_id: int,
        timeout: float = 180,
        logger_name: Optional[str] = None
    ):
        """
        Initialize base view.

        Args:
            user_id: Discord user ID who can interact with this view
            timeout: Timeout in seconds (default 3 minutes)
            logger_name: Optional logger name for logging interactions
        """
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.message: Optional[discord.Message] = None
        self.logger = get_logger(logger_name or __name__)

    async def check_user(self, interaction: discord.Interaction) -> bool:
        """
        Check if interaction user is authorized.

        Sends ephemeral error message if unauthorized.

        Args:
            interaction: Discord interaction

        Returns:
            True if authorized, False otherwise
        """
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This interaction is not for you!",
                ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        """
        Handle view timeout.

        Disables all buttons and removes view from message.
        Override this method for custom timeout behavior.
        """
        if self.message:
            try:
                # Disable all buttons
                for child in self.children:
                    if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                        child.disabled = True

                await self.message.edit(view=self)
                self.logger.debug(f"View timed out for user {self.user_id}")
            except discord.HTTPException as e:
                self.logger.warning(f"Failed to edit message on timeout: {e}")

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item
    ) -> None:
        """
        Handle view errors.

        Logs error and sends user-friendly error message.

        Args:
            interaction: Discord interaction
            error: Exception that occurred
            item: UI item that caused error
        """
        self.logger.error(
            f"Error in view for user {self.user_id}: {error}",
            exc_info=error
        )

        # Try to send error message to user
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "An error occurred while processing your interaction.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "An error occurred while processing your interaction.",
                    ephemeral=True
                )
        except discord.HTTPException:
            pass  # Failed to send error message

    def set_message(self, message: discord.Message) -> None:
        """
        Set the message this view is attached to.

        Args:
            message: Discord message
        """
        self.message = message


class BaseModalView(BaseView):
    """
    Base view class for views that show modals.

    Extends BaseView with modal management functionality.
    """

    def __init__(
        self,
        user_id: int,
        timeout: float = 180,
        logger_name: Optional[str] = None
    ):
        """
        Initialize base modal view.

        Args:
            user_id: Discord user ID who can interact with this view
            timeout: Timeout in seconds (default 3 minutes)
            logger_name: Optional logger name for logging interactions
        """
        super().__init__(user_id, timeout, logger_name)
        self.current_modal: Optional[discord.ui.Modal] = None

    async def show_modal(
        self,
        interaction: discord.Interaction,
        modal: discord.ui.Modal
    ) -> None:
        """
        Show modal to user.

        Args:
            interaction: Discord interaction
            modal: Modal to show
        """
        self.current_modal = modal
        await interaction.response.send_modal(modal)
        self.logger.debug(f"Showed modal to user {self.user_id}")
