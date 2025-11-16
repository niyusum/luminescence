"""
Reusable menu views for Discord.

Provides dropdown menus and button menus with custom options.
Supports dynamic menu generation from config.

Usage:
    >>> # Dropdown menu
    >>> async def on_select(interaction, value):
    ...     await handle_selection(interaction, value)
    >>>
    >>> view = DropdownMenuView(
    ...     user_id,
    ...     options=[("Option 1", "opt1"), ("Option 2", "opt2")],
    ...     callback=on_select
    ... )
    >>>
    >>> # Button menu
    >>> buttons = {
    ...     "button1": {"label": "Option 1", "style": "primary"},
    ...     "button2": {"label": "Option 2", "style": "secondary"}
    ... }
    >>> view = ButtonMenuView(user_id, buttons, on_button_press)
"""

import discord
from discord.ui import Select, Button, select
from typing import List, Tuple, Callable, Awaitable, Dict, Any, Optional

from src.ui.views.base import BaseView
from src.ui.emojis import Emojis


class DropdownMenuView(BaseView):
    """
    Generic dropdown menu view.

    Provides single-select dropdown with custom options and callback.
    """

    def __init__(
        self,
        user_id: int,
        options: List[Tuple[str, str]],
        callback: Callable[[discord.Interaction, str], Awaitable[None]],
        placeholder: str = "Select an option...",
        min_values: int = 1,
        max_values: int = 1,
        timeout: float = 180
    ):
        """
        Initialize dropdown menu view.

        Args:
            user_id: Discord user ID
            options: List of (label, value) tuples
            callback: Async callback function(interaction, selected_value)
            placeholder: Placeholder text
            min_values: Minimum selections required
            max_values: Maximum selections allowed
            timeout: Timeout in seconds
        """
        super().__init__(user_id, timeout)
        self.select_callback = callback

        # Create select menu
        select_menu = Select(
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values
        )

        # Add options
        for label, value in options:
            select_menu.add_option(label=label, value=value)

        select_menu.callback = self._on_select
        self.add_item(select_menu)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        """Handle select menu interaction."""
        if not await self.check_user(interaction):
            return

        # Get selected value
        if interaction.data:
            values = interaction.data.get("values", [])
            select_menu = values[0] if values else None
        else:
            select_menu = None

        if select_menu and self.select_callback:
            await self.select_callback(interaction, select_menu)


class ButtonMenuView(BaseView):
    """
    Dynamic button menu view.

    Creates buttons from config dict with custom callbacks.
    """

    def __init__(
        self,
        user_id: int,
        buttons: Dict[str, Dict[str, Any]],
        callback: Callable[[discord.Interaction, str], Awaitable[None]],
        timeout: float = 180
    ):
        """
        Initialize button menu view.

        Args:
            user_id: Discord user ID
            buttons: Dict of button_id -> {label, style, emoji (optional), row (optional)}
            callback: Async callback function(interaction, button_id)
            timeout: Timeout in seconds

        Example buttons dict:
            {
                "option1": {"label": "Option 1", "style": "primary", "emoji": "🔥"},
                "option2": {"label": "Option 2", "style": "secondary", "row": 1}
            }
        """
        super().__init__(user_id, timeout)
        self.button_callback = callback
        self.button_ids: Dict[str, str] = {}  # Maps custom_id to button_id

        # Create buttons
        for button_id, config in buttons.items():
            self._add_button(button_id, config)

    def _add_button(self, button_id: str, config: Dict[str, Any]) -> None:
        """Add button to view."""
        # Parse style
        style_map = {
            "primary": discord.ButtonStyle.primary,
            "secondary": discord.ButtonStyle.secondary,
            "success": discord.ButtonStyle.success,
            "danger": discord.ButtonStyle.danger,
            "link": discord.ButtonStyle.link,
        }
        style = style_map.get(config.get("style", "secondary"), discord.ButtonStyle.secondary)

        # Create button
        button = Button(
            label=config.get("label", "Button"),
            style=style,
            emoji=config.get("emoji"),
            row=config.get("row", 0),
            disabled=config.get("disabled", False)
        )

        # Store button ID mapping
        if button.custom_id:
            custom_id_str: str = button.custom_id
            self.button_ids[custom_id_str] = button_id

        # Set callback
        button.callback = self._on_button_press
        self.add_item(button)

    async def _on_button_press(self, interaction: discord.Interaction) -> None:
        """Handle button press."""
        if not await self.check_user(interaction):
            return

        # Get button ID from custom_id
        if interaction.data:
            data = interaction.data
            custom_id = data.get("custom_id")
            if isinstance(custom_id, str):
                button_id = self.button_ids.get(custom_id)
                if button_id and self.button_callback:
                    await self.button_callback(interaction, button_id)
