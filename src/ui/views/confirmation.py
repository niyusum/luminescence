"""
Reusable confirmation dialog views for Discord.

Provides yes/no confirmation dialogs and agreement views.
Supports custom labels, callbacks, and danger warnings.

Usage:
    >>> # Simple confirmation
    >>> async def on_confirm(interaction):
    ...     await handle_confirmation(interaction)
    >>>
    >>> view = ConfirmationView(
    ...     user_id,
    ...     on_confirm=on_confirm,
    ...     on_cancel=on_cancel
    ... )
    >>>
    >>> # Agreement (TOS, etc.)
    >>> view = AgreementView(user_id, on_agree=on_agree)
"""

import discord
from discord.ui import Button
from typing import Optional, Callable, Awaitable, cast

from src.ui.views.base import BaseView
from src.ui.emojis import Emojis


class ConfirmationView(BaseView):
    """
    Yes/No confirmation dialog view.

    Provides customizable confirm/cancel buttons with callbacks.
    """

    def __init__(
        self,
        user_id: int,
        on_confirm: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        on_cancel: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
        confirm_style: discord.ButtonStyle = discord.ButtonStyle.success,
        danger_mode: bool = False,
        timeout: float = 60
    ):
        """
        Initialize confirmation view.

        Args:
            user_id: Discord user ID
            on_confirm: Callback for confirm action
            on_cancel: Callback for cancel action
            confirm_label: Label for confirm button
            cancel_label: Label for cancel button
            confirm_style: Style for confirm button
            danger_mode: If True, confirm button is red (for destructive actions)
            timeout: Timeout in seconds (default 1 minute)
        """
        super().__init__(user_id, timeout)
        self.on_confirm_callback = on_confirm
        self.on_cancel_callback = on_cancel

        # Override confirm style if danger mode
        if danger_mode:
            confirm_style = discord.ButtonStyle.danger

        # Add buttons
        self._setup_buttons(confirm_label, cancel_label, confirm_style)

    def _setup_buttons(
        self,
        confirm_label: str,
        cancel_label: str,
        confirm_style: discord.ButtonStyle
    ) -> None:
        """Setup confirmation buttons."""
        # Confirm button
        confirm_button = Button(
            label=confirm_label,
            emoji=Emojis.SUCCESS,
            style=confirm_style
        )
        confirm_button.callback = self._confirm
        self.add_item(confirm_button)

        # Cancel button
        cancel_button = Button(
            label=cancel_label,
            emoji=Emojis.ERROR,
            style=discord.ButtonStyle.secondary
        )
        cancel_button.callback = self._cancel
        self.add_item(cancel_button)

    async def _confirm(self, interaction: discord.Interaction) -> None:
        """Handle confirm action."""
        if not await self.check_user(interaction):
            return

        # Disable buttons
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                button = cast(discord.ui.Button, child)
                button.disabled = True

        if self.on_confirm_callback:
            await self.on_confirm_callback(interaction)
        else:
            # Default: acknowledge and close
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("Confirmed!", ephemeral=True)

    async def _cancel(self, interaction: discord.Interaction) -> None:
        """Handle cancel action."""
        if not await self.check_user(interaction):
            return

        # Disable buttons
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                button = cast(discord.ui.Button, child)
                button.disabled = True

        if self.on_cancel_callback:
            await self.on_cancel_callback(interaction)
        else:
            # Default: acknowledge and close
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("Cancelled.", ephemeral=True)


class AgreementView(BaseView):
    """
    Agreement view for TOS, rules, etc.

    Provides agree button with optional support link.
    """

    def __init__(
        self,
        user_id: int,
        on_agree: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        agree_label: str = "I Agree",
        support_link: Optional[str] = None,
        timeout: float = 300  # 5 minutes for reading
    ):
        """
        Initialize agreement view.

        Args:
            user_id: Discord user ID
            on_agree: Callback for agree action
            agree_label: Label for agree button
            support_link: Optional support/help URL
            timeout: Timeout in seconds (default 5 minutes)
        """
        super().__init__(user_id, timeout)
        self.on_agree_callback = on_agree

        # Add buttons
        self._setup_buttons(agree_label, support_link)

    def _setup_buttons(self, agree_label: str, support_link: Optional[str]) -> None:
        """Setup agreement buttons."""
        # Agree button
        agree_button = Button(
            label=agree_label,
            emoji=Emojis.SUCCESS,
            style=discord.ButtonStyle.success
        )
        agree_button.callback = self._agree
        self.add_item(agree_button)

        # Support link (if provided)
        if support_link:
            support_button = Button(
                label="Need Help?",
                emoji=Emojis.TIP,
                style=discord.ButtonStyle.link,
                url=support_link
            )
            self.add_item(support_button)

    async def _agree(self, interaction: discord.Interaction) -> None:
        """Handle agree action."""
        if not await self.check_user(interaction):
            return

        # Disable agree button
        if isinstance(self.children[0], discord.ui.Button):
            button = cast(discord.ui.Button, self.children[0])
            button.disabled = True

        if self.on_agree_callback:
            await self.on_agree_callback(interaction)
        else:
            # Default: acknowledge
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("Thank you for agreeing!", ephemeral=True)


class DeletionConfirmationView(ConfirmationView):
    """
    Special confirmation view for destructive deletion actions.

    Pre-configured with danger styling and warning message.
    """

    def __init__(
        self,
        user_id: int,
        item_name: str,
        on_confirm: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        on_cancel: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        timeout: float = 60
    ):
        """
        Initialize deletion confirmation view.

        Args:
            user_id: Discord user ID
            item_name: Name of item being deleted (for confirmation message)
            on_confirm: Callback for confirm deletion
            on_cancel: Callback for cancel
            timeout: Timeout in seconds
        """
        super().__init__(
            user_id=user_id,
            on_confirm=on_confirm,
            on_cancel=on_cancel,
            confirm_label=f"Delete {item_name}",
            cancel_label="Keep It",
            danger_mode=True,
            timeout=timeout
        )
        self.item_name = item_name
