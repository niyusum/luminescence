"""
Reusable select menu factory for Discord views.

Provides factory methods for common select menu patterns.
Reduces code duplication across cog files.

Usage:
    >>> from src.ui.components.selects import CommonSelects
    >>>
    >>> # Create a view with common select menus
    >>> view = View()
    >>> select = CommonSelects.category_select()
    >>> # Set callback
    >>> select.callback = my_callback
    >>> view.add_item(select)
"""

import discord
from discord.ui import Select
from typing import List, Optional

from src.ui.emojis import Emojis


class CommonSelects:
    """
    Factory for common Discord UI select menus.

    Provides pre-configured select menus for frequent patterns.
    All select menus need their callback set after creation.
    """

    @staticmethod
    def category_select(
        categories: Optional[List[str]] = None,
        placeholder: str = "Select a category...",
        row: int = 0,
        min_values: int = 1,
        max_values: int = 1
    ) -> Select:
        """
        Create category select menu.

        Args:
            categories: List of category names (default: economy, combat, progression, resources, survival)
            placeholder: Placeholder text
            row: Select row (0-4)
            min_values: Minimum selections
            max_values: Maximum selections

        Returns:
            Select instance (callback must be set)
        """
        if categories is None:
            categories = ["Economy", "Combat", "Progression", "Resources", "Survival"]

        select = Select(
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            row=row
        )

        # Add category options
        category_emojis = {
            "Economy": Emojis.CATEGORY_ECONOMY,
            "Combat": Emojis.CATEGORY_COMBAT,
            "Progression": Emojis.CATEGORY_PROGRESSION,
            "Resources": Emojis.CATEGORY_RESOURCES,
            "Survival": Emojis.CATEGORY_SURVIVAL,
        }

        for category in categories:
            select.add_option(
                label=category,
                value=category.lower(),
                emoji=category_emojis.get(category, Emojis.INFO)
            )

        return select

    @staticmethod
    def tier_select(
        max_tier: int = 6,
        placeholder: str = "Select tier...",
        row: int = 0,
        min_values: int = 1,
        max_values: int = 1
    ) -> Select:
        """
        Create tier select menu.

        Args:
            max_tier: Maximum tier to show (1-6)
            placeholder: Placeholder text
            row: Select row (0-4)
            min_values: Minimum selections
            max_values: Maximum selections

        Returns:
            Select instance (callback must be set)
        """
        select = Select(
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            row=row
        )

        # Add tier options
        tier_config = {
            1: ("Tier 1 - Common", Emojis.COMMON),
            2: ("Tier 2 - Uncommon", Emojis.UNCOMMON),
            3: ("Tier 3 - Rare", Emojis.RARE),
            4: ("Tier 4 - Epic", Emojis.EPIC),
            5: ("Tier 5 - Legendary", Emojis.LEGENDARY),
            6: ("Tier 6 - Mythic", Emojis.MYTHIC),
        }

        for tier in range(1, min(max_tier + 1, 7)):
            label, emoji = tier_config[tier]
            select.add_option(
                label=label,
                value=str(tier),
                emoji=emoji
            )

        return select

    @staticmethod
    def element_select(
        elements: Optional[List[str]] = None,
        placeholder: str = "Select element...",
        row: int = 0,
        min_values: int = 1,
        max_values: int = 1
    ) -> Select:
        """
        Create element select menu.

        Args:
            elements: List of element names (default: all 6 elements)
            placeholder: Placeholder text
            row: Select row (0-4)
            min_values: Minimum selections
            max_values: Maximum selections

        Returns:
            Select instance (callback must be set)
        """
        if elements is None:
            elements = ["Infernal", "Abyssal", "Tempest", "Earth", "Radiant", "Umbral"]

        select = Select(
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            row=row
        )

        # Add element options
        element_config = {
            "Infernal": Emojis.INFERNAL,
            "Abyssal": Emojis.ABYSSAL,
            "Tempest": Emojis.ENERGY,
            "Earth": Emojis.EARTH,
            "Radiant": Emojis.RADIANT,
            "Umbral": Emojis.UMBRAL,
        }

        for element in elements:
            select.add_option(
                label=element,
                value=element.lower(),
                emoji=element_config.get(element, Emojis.INFO)
            )

        return select

    @staticmethod
    def sorting_select(
        sort_options: Optional[List[tuple[str, str]]] = None,
        placeholder: str = "Sort by...",
        row: int = 0
    ) -> Select:
        """
        Create sorting select menu.

        Args:
            sort_options: List of (label, value) tuples (default: common sorts)
            placeholder: Placeholder text
            row: Select row (0-4)

        Returns:
            Select instance (callback must be set)
        """
        if sort_options is None:
            sort_options = [
                ("Power (High to Low)", "power_desc"),
                ("Power (Low to High)", "power_asc"),
                ("Tier (High to Low)", "tier_desc"),
                ("Tier (Low to High)", "tier_asc"),
                ("Name (A-Z)", "name_asc"),
                ("Name (Z-A)", "name_desc"),
            ]

        select = Select(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            row=row
        )

        for label, value in sort_options:
            select.add_option(label=label, value=value)

        return select

    @staticmethod
    def filter_select(
        filter_options: List[tuple[str, str, Optional[str]]],
        placeholder: str = "Filter by...",
        row: int = 0,
        min_values: int = 0,
        max_values: int = 1
    ) -> Select:
        """
        Create filter select menu.

        Args:
            filter_options: List of (label, value, emoji) tuples
            placeholder: Placeholder text
            row: Select row (0-4)
            min_values: Minimum selections (0 allows clearing filter)
            max_values: Maximum selections

        Returns:
            Select instance (callback must be set)
        """
        select = Select(
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            row=row
        )

        for label, value, emoji in filter_options:
            select.add_option(
                label=label,
                value=value,
                emoji=emoji
            )

        return select

    @staticmethod
    def custom(
        options: List[tuple[str, str, Optional[str]]],
        placeholder: str = "Select an option...",
        row: int = 0,
        min_values: int = 1,
        max_values: int = 1,
        disabled: bool = False
    ) -> Select:
        """
        Create custom select menu.

        Args:
            options: List of (label, value, emoji) tuples (max 25)
            placeholder: Placeholder text
            row: Select row (0-4)
            min_values: Minimum selections
            max_values: Maximum selections
            disabled: Whether select is disabled

        Returns:
            Select instance (callback must be set)
        """
        select = Select(
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            row=row,
            disabled=disabled
        )

        # Add options (max 25)
        for label, value, emoji in options[:25]:
            select.add_option(
                label=label,
                value=value,
                emoji=emoji
            )

        return select
