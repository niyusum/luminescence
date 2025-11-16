"""
Reusable modal dialogs for Discord.

Provides common modal patterns with built-in validation.
Supports numeric input, text input, and custom forms.

Usage:
    >>> # Numeric input modal
    >>> async def on_submit(interaction, value):
    ...     await handle_numeric_input(interaction, value)
    >>>
    >>> modal = NumericInputModal(
    ...     title="Enter Amount",
    ...     label="Quantity",
    ...     callback=on_submit,
    ...     min_value=1,
    ...     max_value=100
    ... )
    >>> await interaction.response.send_modal(modal)
"""

import discord
from discord.ui import Modal, TextInput
from typing import Optional, Callable, Awaitable

from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class NumericInputModal(Modal):
    """
    Numeric input modal with validation.

    Validates input is a valid number within min/max range.
    """

    def __init__(
        self,
        title: str,
        label: str,
        callback: Callable[[discord.Interaction, int], Awaitable[None]],
        placeholder: Optional[str] = None,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
        default: Optional[str] = None,
        required: bool = True
    ):
        """
        Initialize numeric input modal.

        Args:
            title: Modal title
            label: Input field label
            callback: Async callback function(interaction, value)
            placeholder: Placeholder text
            min_value: Minimum allowed value
            max_value: Maximum allowed value
            default: Default value
            required: Whether input is required
        """
        super().__init__(title=title)
        self.submit_callback = callback
        self.min_value = min_value
        self.max_value = max_value

        # Create input field
        self.numeric_input = TextInput(
            label=label,
            placeholder=placeholder or f"Enter a number{f' ({min_value}-{max_value})' if min_value and max_value else ''}",
            default=default,
            required=required,
            max_length=20
        )
        self.add_item(self.numeric_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        input_value = self.numeric_input.value

        # Validate numeric
        try:
            value = int(input_value)
        except ValueError:
            await interaction.response.send_message(
                f"Invalid input! '{input_value}' is not a valid number.",
                ephemeral=True
            )
            return

        # Validate min value
        if self.min_value is not None and value < self.min_value:
            await interaction.response.send_message(
                f"Value too low! Minimum is {self.min_value}.",
                ephemeral=True
            )
            return

        # Validate max value
        if self.max_value is not None and value > self.max_value:
            await interaction.response.send_message(
                f"Value too high! Maximum is {self.max_value}.",
                ephemeral=True
            )
            return

        # Call callback with validated value
        await self.submit_callback(interaction, value)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception
    ) -> None:
        """Handle modal errors."""
        logger.error(f"Error in NumericInputModal: {error}", exc_info=error)
        await interaction.response.send_message(
            "An error occurred while processing your input.",
            ephemeral=True
        )


class TextInputModal(Modal):
    """
    Simple text input modal.

    Provides basic text input with optional validation.
    """

    def __init__(
        self,
        title: str,
        label: str,
        callback: Callable[[discord.Interaction, str], Awaitable[None]],
        placeholder: Optional[str] = None,
        default: Optional[str] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        required: bool = True,
        style: discord.TextStyle = discord.TextStyle.short
    ):
        """
        Initialize text input modal.

        Args:
            title: Modal title
            label: Input field label
            callback: Async callback function(interaction, text)
            placeholder: Placeholder text
            default: Default value
            min_length: Minimum text length
            max_length: Maximum text length
            required: Whether input is required
            style: Text input style (short or paragraph)
        """
        super().__init__(title=title)
        self.submit_callback = callback

        # Create input field
        self.text_input = TextInput(
            label=label,
            placeholder=placeholder,
            default=default,
            required=required,
            min_length=min_length,
            max_length=max_length or 4000,
            style=style
        )
        self.add_item(self.text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        text = self.text_input.value

        # Call callback with text
        await self.submit_callback(interaction, text)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception
    ) -> None:
        """Handle modal errors."""
        logger.error(f"Error in TextInputModal: {error}", exc_info=error)
        await interaction.response.send_message(
            "An error occurred while processing your input.",
            ephemeral=True
        )


class MultiFieldModal(Modal):
    """
    Multi-field input modal.

    Supports up to 5 text input fields with custom validation.
    """

    def __init__(
        self,
        title: str,
        fields: list[dict],
        callback: Callable[[discord.Interaction, dict], Awaitable[None]]
    ):
        """
        Initialize multi-field modal.

        Args:
            title: Modal title
            fields: List of field configs (max 5)
                Each field dict should contain:
                    - key: Field identifier
                    - label: Field label
                    - placeholder: Optional placeholder
                    - default: Optional default value
                    - required: Whether required (default True)
                    - min_length: Optional min length
                    - max_length: Optional max length
                    - style: TextStyle (default short)
            callback: Async callback function(interaction, values_dict)

        Example:
            fields = [
                {"key": "name", "label": "Name", "required": True},
                {"key": "description", "label": "Description", "style": discord.TextStyle.paragraph}
            ]
        """
        super().__init__(title=title)
        self.submit_callback = callback
        self.field_keys = []

        # Add fields (max 5)
        for field_config in fields[:5]:
            key = field_config.get("key")
            self.field_keys.append(key)

            text_input = TextInput(
                label=field_config.get("label", "Field"),
                placeholder=field_config.get("placeholder"),
                default=field_config.get("default"),
                required=field_config.get("required", True),
                min_length=field_config.get("min_length"),
                max_length=field_config.get("max_length", 4000),
                style=field_config.get("style", discord.TextStyle.short)
            )
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        # Build values dict
        values = {}
        for i, key in enumerate(self.field_keys):
            child = self.children[i]
            if isinstance(child, discord.ui.TextInput):
                values[key] = child.value

        # Call callback with values dict
        await self.submit_callback(interaction, values)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception
    ) -> None:
        """Handle modal errors."""
        logger.error(f"Error in MultiFieldModal: {error}", exc_info=error)
        await interaction.response.send_message(
            "An error occurred while processing your input.",
            ephemeral=True
        )
