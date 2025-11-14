"""
Reusable button factory for Discord views.

Provides factory methods for common button patterns.
Reduces code duplication across cog files.

Usage:
    >>> from src.ui.components.buttons import CommonButtons
    >>>
    >>> # Create a view with common buttons
    >>> view = View()
    >>> view.add_item(CommonButtons.view_profile())
    >>> view.add_item(CommonButtons.next_page())
"""

import discord
from discord.ui import Button
from typing import Optional

from src.ui.emojis import Emojis


class CommonButtons:
    """
    Factory for common Discord UI buttons.

    Provides pre-configured buttons for frequent patterns.
    All buttons need their callback set after creation.
    """

    @staticmethod
    def view_profile(
        label: str = "View Profile",
        row: int = 0,
        disabled: bool = False
    ) -> Button:
        """
        Create 'View Profile' button.

        Args:
            label: Button label
            row: Button row (0-4)
            disabled: Whether button is disabled

        Returns:
            Button instance (callback must be set)
        """
        return Button(
            label=label,
            emoji=Emojis.INFO,
            style=discord.ButtonStyle.secondary,
            row=row,
            disabled=disabled
        )

    @staticmethod
    def view_collection(
        label: str = "View Collection",
        row: int = 0,
        disabled: bool = False
    ) -> Button:
        """
        Create 'View Collection' button.

        Args:
            label: Button label
            row: Button row (0-4)
            disabled: Whether button is disabled

        Returns:
            Button instance (callback must be set)
        """
        return Button(
            label=label,
            emoji=Emojis.MAIDEN,
            style=discord.ButtonStyle.secondary,
            row=row,
            disabled=disabled
        )

    @staticmethod
    def summon_again(
        label: str = "Summon Again",
        row: int = 0,
        disabled: bool = False
    ) -> Button:
        """
        Create 'Summon Again' button.

        Args:
            label: Button label
            row: Button row (0-4)
            disabled: Whether button is disabled

        Returns:
            Button instance (callback must be set)
        """
        return Button(
            label=label,
            emoji=Emojis.RADIANT,
            style=discord.ButtonStyle.primary,
            row=row,
            disabled=disabled
        )

    @staticmethod
    def next_page(
        label: str = "Next",
        row: int = 0,
        disabled: bool = False
    ) -> Button:
        """
        Create 'Next Page' button.

        Args:
            label: Button label
            row: Button row (0-4)
            disabled: Whether button is disabled

        Returns:
            Button instance (callback must be set)
        """
        return Button(
            label=label,
            emoji=Emojis.NEXT,
            style=discord.ButtonStyle.secondary,
            row=row,
            disabled=disabled
        )

    @staticmethod
    def previous_page(
        label: str = "Previous",
        row: int = 0,
        disabled: bool = False
    ) -> Button:
        """
        Create 'Previous Page' button.

        Args:
            label: Button label
            row: Button row (0-4)
            disabled: Whether button is disabled

        Returns:
            Button instance (callback must be set)
        """
        return Button(
            label=label,
            emoji=Emojis.BACK,
            style=discord.ButtonStyle.secondary,
            row=row,
            disabled=disabled
        )

    @staticmethod
    def attack(
        label: str = "Attack",
        row: int = 0,
        disabled: bool = False
    ) -> Button:
        """
        Create 'Attack' button.

        Args:
            label: Button label
            row: Button row (0-4)
            disabled: Whether button is disabled

        Returns:
            Button instance (callback must be set)
        """
        return Button(
            label=label,
            emoji=Emojis.ATTACK,
            style=discord.ButtonStyle.danger,
            row=row,
            disabled=disabled
        )

    @staticmethod
    def retreat(
        label: str = "Retreat",
        row: int = 0,
        disabled: bool = False
    ) -> Button:
        """
        Create 'Retreat' button.

        Args:
            label: Button label
            row: Button row (0-4)
            disabled: Whether button is disabled

        Returns:
            Button instance (callback must be set)
        """
        return Button(
            label=label,
            emoji=Emojis.ERROR,
            style=discord.ButtonStyle.secondary,
            row=row,
            disabled=disabled
        )

    @staticmethod
    def upgrade(
        label: str = "Upgrade",
        row: int = 0,
        disabled: bool = False
    ) -> Button:
        """
        Create 'Upgrade' button.

        Args:
            label: Button label
            row: Button row (0-4)
            disabled: Whether button is disabled

        Returns:
            Button instance (callback must be set)
        """
        return Button(
            label=label,
            emoji=Emojis.EXPERIENCE,
            style=discord.ButtonStyle.success,
            row=row,
            disabled=disabled
        )

    @staticmethod
    def collect_all(
        label: str = "Collect All",
        row: int = 0,
        disabled: bool = False
    ) -> Button:
        """
        Create 'Collect All' button.

        Args:
            label: Button label
            row: Button row (0-4)
            disabled: Whether button is disabled

        Returns:
            Button instance (callback must be set)
        """
        return Button(
            label=label,
            emoji=Emojis.LUMEES,
            style=discord.ButtonStyle.success,
            row=row,
            disabled=disabled
        )

    @staticmethod
    def confirm(
        label: str = "Confirm",
        row: int = 0,
        disabled: bool = False,
        danger: bool = False
    ) -> Button:
        """
        Create 'Confirm' button.

        Args:
            label: Button label
            row: Button row (0-4)
            disabled: Whether button is disabled
            danger: If True, uses danger style (red)

        Returns:
            Button instance (callback must be set)
        """
        style = discord.ButtonStyle.danger if danger else discord.ButtonStyle.success
        return Button(
            label=label,
            emoji=Emojis.SUCCESS,
            style=style,
            row=row,
            disabled=disabled
        )

    @staticmethod
    def cancel(
        label: str = "Cancel",
        row: int = 0,
        disabled: bool = False
    ) -> Button:
        """
        Create 'Cancel' button.

        Args:
            label: Button label
            row: Button row (0-4)
            disabled: Whether button is disabled

        Returns:
            Button instance (callback must be set)
        """
        return Button(
            label=label,
            emoji=Emojis.ERROR,
            style=discord.ButtonStyle.secondary,
            row=row,
            disabled=disabled
        )

    @staticmethod
    def refresh(
        label: str = "Refresh",
        row: int = 0,
        disabled: bool = False
    ) -> Button:
        """
        Create 'Refresh' button.

        Args:
            label: Button label
            row: Button row (0-4)
            disabled: Whether button is disabled

        Returns:
            Button instance (callback must be set)
        """
        return Button(
            label=label,
            emoji=Emojis.REGENERATING,
            style=discord.ButtonStyle.secondary,
            row=row,
            disabled=disabled
        )

    @staticmethod
    def custom(
        label: str,
        emoji: Optional[str] = None,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        row: int = 0,
        disabled: bool = False,
        url: Optional[str] = None
    ) -> Button:
        """
        Create custom button.

        Args:
            label: Button label
            emoji: Optional emoji
            style: Button style
            row: Button row (0-4)
            disabled: Whether button is disabled
            url: Optional URL (creates link button)

        Returns:
            Button instance (callback must be set if not link button)
        """
        return Button(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            disabled=disabled,
            url=url
        )
