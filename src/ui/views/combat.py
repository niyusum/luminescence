"""
Reusable combat views for Discord.

Provides combat action views and post-battle views.
Supports customizable callbacks for attack, special, defend, and retreat.

Usage:
    >>> async def on_attack(interaction):
    ...     await handle_attack(interaction)
    >>>
    >>> view = CombatActionView(
    ...     user_id,
    ...     on_attack=on_attack,
    ...     on_retreat=on_retreat
    ... )
"""

import discord
from discord.ui import Button
from typing import Optional, Callable, Awaitable

from src.ui.views.base import BaseView
from src.ui.emojis import Emojis


class CombatActionView(BaseView):
    """
    Combat action view with attack/special/defend/retreat buttons.

    Provides customizable callbacks for each action.
    """

    def __init__(
        self,
        user_id: int,
        on_attack: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        on_special: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        on_defend: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        on_retreat: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        show_special: bool = True,
        show_defend: bool = True,
        timeout: float = 180
    ):
        """
        Initialize combat action view.

        Args:
            user_id: Discord user ID
            on_attack: Callback for attack action
            on_special: Callback for special action
            on_defend: Callback for defend action
            on_retreat: Callback for retreat action
            show_special: Whether to show special button
            show_defend: Whether to show defend button
            timeout: Timeout in seconds
        """
        super().__init__(user_id, timeout)
        self.on_attack_callback = on_attack
        self.on_special_callback = on_special
        self.on_defend_callback = on_defend
        self.on_retreat_callback = on_retreat

        # Add action buttons
        self._setup_buttons(show_special, show_defend)

    def _setup_buttons(self, show_special: bool, show_defend: bool) -> None:
        """Setup combat action buttons."""
        # Attack button (always shown)
        attack_button = Button(
            label="Attack",
            emoji=Emojis.ATTACK,
            style=discord.ButtonStyle.danger,
            row=0
        )
        attack_button.callback = self._attack
        self.add_item(attack_button)

        # Special button (optional)
        if show_special:
            special_button = Button(
                label="Special",
                emoji=Emojis.CRITICAL,
                style=discord.ButtonStyle.primary,
                row=0
            )
            special_button.callback = self._special
            self.add_item(special_button)

        # Defend button (optional)
        if show_defend:
            defend_button = Button(
                label="Defend",
                emoji=Emojis.DEFENSE_BOOST,
                style=discord.ButtonStyle.secondary,
                row=0
            )
            defend_button.callback = self._defend
            self.add_item(defend_button)

        # Retreat button (always shown)
        retreat_button = Button(
            label="Retreat",
            emoji=Emojis.ERROR,
            style=discord.ButtonStyle.secondary,
            row=1
        )
        retreat_button.callback = self._retreat
        self.add_item(retreat_button)

    async def _attack(self, interaction: discord.Interaction) -> None:
        """Handle attack action."""
        if not await self.check_user(interaction):
            return

        if self.on_attack_callback:
            await self.on_attack_callback(interaction)
        else:
            await interaction.response.send_message(
                "Attack action not configured!",
                ephemeral=True
            )

    async def _special(self, interaction: discord.Interaction) -> None:
        """Handle special action."""
        if not await self.check_user(interaction):
            return

        if self.on_special_callback:
            await self.on_special_callback(interaction)
        else:
            await interaction.response.send_message(
                "Special action not configured!",
                ephemeral=True
            )

    async def _defend(self, interaction: discord.Interaction) -> None:
        """Handle defend action."""
        if not await self.check_user(interaction):
            return

        if self.on_defend_callback:
            await self.on_defend_callback(interaction)
        else:
            await interaction.response.send_message(
                "Defend action not configured!",
                ephemeral=True
            )

    async def _retreat(self, interaction: discord.Interaction) -> None:
        """Handle retreat action."""
        if not await self.check_user(interaction):
            return

        if self.on_retreat_callback:
            await self.on_retreat_callback(interaction)
        else:
            await interaction.response.send_message(
                "Retreat action not configured!",
                ephemeral=True
            )


class CombatVictoryView(BaseView):
    """
    Post-battle view with continue/profile actions.

    Shown after combat victory.
    """

    def __init__(
        self,
        user_id: int,
        on_continue: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        on_view_profile: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        timeout: float = 180
    ):
        """
        Initialize combat victory view.

        Args:
            user_id: Discord user ID
            on_continue: Callback for continue action
            on_view_profile: Callback for view profile action
            timeout: Timeout in seconds
        """
        super().__init__(user_id, timeout)
        self.on_continue_callback = on_continue
        self.on_view_profile_callback = on_view_profile

        # Add action buttons
        self._setup_buttons()

    def _setup_buttons(self) -> None:
        """Setup post-battle action buttons."""
        # Continue button
        continue_button = Button(
            label="Continue",
            emoji=Emojis.SUCCESS,
            style=discord.ButtonStyle.success
        )
        continue_button.callback = self._continue
        self.add_item(continue_button)

        # View Profile button
        profile_button = Button(
            label="View Profile",
            emoji=Emojis.INFO,
            style=discord.ButtonStyle.secondary
        )
        profile_button.callback = self._view_profile
        self.add_item(profile_button)

    async def _continue(self, interaction: discord.Interaction) -> None:
        """Handle continue action."""
        if not await self.check_user(interaction):
            return

        if self.on_continue_callback:
            await self.on_continue_callback(interaction)
        else:
            # Default: close view
            await interaction.response.edit_message(view=None)

    async def _view_profile(self, interaction: discord.Interaction) -> None:
        """Handle view profile action."""
        if not await self.check_user(interaction):
            return

        if self.on_view_profile_callback:
            await self.on_view_profile_callback(interaction)
        else:
            await interaction.response.send_message(
                "View profile action not configured!",
                ephemeral=True
            )
