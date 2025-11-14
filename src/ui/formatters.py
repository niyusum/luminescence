"""
Pure UI formatters for display strings.

Contains zero business logic - only formatting functions for:
- HP bars and percentages
- Damage displays
- Progress bars
- Resource costs
- Combat log entries

All functions are pure (no side effects, no database access).

LUMEN LAW Compliance:
- Article V: UI formatters separated from business logic
- Pure functions for testability
- Zero dependencies on database or services

Usage:
    >>> from src.ui.formatters import CombatFormatters, ProgressFormatters
    >>> hp_bar = CombatFormatters.render_hp_bar(5000, 10000)
    >>> damage = CombatFormatters.format_damage_display(500, is_crit=True)
"""

from src.ui.emojis import Emojis


class CombatFormatters:
    """
    Pure formatters for combat displays.

    All methods are static and pure - no side effects, no database access.
    """

    @staticmethod
    def render_hp_bar(current_hp: int, max_hp: int, width: int = 20) -> str:
        """
        Render ASCII HP bar using Unicode blocks.

        Args:
            current_hp: Current HP value
            max_hp: Maximum HP value
            width: Bar width in characters

        Returns:
            Formatted HP bar string

        Example:
            >>> CombatFormatters.render_hp_bar(7500, 10000, 20)
            '███████████████░░░░░'
        """
        if max_hp == 0:
            return "░" * width

        filled_width = int((current_hp / max_hp) * width)
        filled_width = max(0, min(width, filled_width))
        empty_width = width - filled_width

        return "█" * filled_width + "░" * empty_width

    @staticmethod
    def render_hp_percentage(current_hp: int, max_hp: int) -> str:
        """
        Render HP as percentage string.

        Returns:
            Formatted percentage (e.g., "75%")
        """
        if max_hp == 0:
            return "0%"

        percent = int((current_hp / max_hp) * 100)
        return f"{percent}%"

    @staticmethod
    def format_damage_display(damage: int, is_crit: bool = False) -> str:
        """
        Format damage number for display.

        Args:
            damage: Damage value
            is_crit: Whether this is a critical hit

        Returns:
            Formatted damage string with emojis
        """
        formatted = f"{damage:,}"

        if is_crit:
            return f"{Emojis.CRITICAL} **{formatted}** {Emojis.RADIANT} CRITICAL!"
        else:
            return f"{Emojis.ATTACK} {formatted}"

    @staticmethod
    def get_element_emoji(element: str) -> str:
        """
        Get emoji for element type.

        Returns:
            Element emoji
        """
        emojis = {
            "infernal": Emojis.INFERNAL,
            "abyssal": Emojis.ABYSSAL,
            "tempest": Emojis.TEMPEST,
            "earth": Emojis.EARTH,
            "radiant": Emojis.RADIANT,
            "umbral": Emojis.UMBRAL,
        }
        return emojis.get(element.lower(), Emojis.COMMON)

    @staticmethod
    def get_rarity_emoji(rarity: str) -> str:
        """
        Get emoji for rarity tier.

        Returns:
            Rarity emoji
        """
        emojis = {
            "common": Emojis.COMMON,
            "uncommon": Emojis.UNCOMMON,
            "rare": Emojis.RARE,
            "epic": Emojis.EPIC,
            "legendary": Emojis.LEGENDARY,
            "mythic": Emojis.MYTHIC,
        }
        return emojis.get(rarity, Emojis.COMMON)

    @staticmethod
    def format_combat_log_entry(
        attacker: str,
        damage: int,
        current_hp: int,
        max_hp: int,
        is_crit: bool = False
    ) -> str:
        """
        Format single combat log entry.

        Returns:
            Formatted combat log line
        """
        damage_display = CombatFormatters.format_damage_display(damage, is_crit)
        hp_bar = CombatFormatters.render_hp_bar(current_hp, max_hp, width=20)
        hp_percent = CombatFormatters.render_hp_percentage(current_hp, max_hp)

        return f"{damage_display}\n{hp_bar} {hp_percent}\nHP: {current_hp:,} / {max_hp:,}"


class ProgressFormatters:
    """
    Pure formatters for progression displays.

    All methods are static and pure - no side effects, no database access.
    """

    @staticmethod
    def render_progress_bar(progress: float, width: int = 20) -> str:
        """
        Render progress bar for sector exploration.

        Args:
            progress: Progress percentage (0.0 - 100.0)
            width: Bar width in characters

        Returns:
            Formatted progress bar
        """
        filled_width = int((progress / 100.0) * width)
        filled_width = max(0, min(width, filled_width))
        empty_width = width - filled_width

        return "━" * filled_width + "░" * empty_width

    @staticmethod
    def format_progress_display(progress: float) -> str:
        """
        Format progress as percentage with color coding.

        Returns:
            Formatted string
        """
        if progress < 25:
            emoji = Emojis.PROGRESS_EMPTY
        elif progress < 50:
            emoji = Emojis.PROGRESS_LOW
        elif progress < 75:
            emoji = Emojis.PROGRESS_MEDIUM
        elif progress < 100:
            emoji = Emojis.PROGRESS_HIGH
        else:
            emoji = Emojis.PROGRESS_COMPLETE

        return f"{emoji} {progress:.1f}%"

    @staticmethod
    def format_resource_cost(resource: str, amount: int) -> str:
        """
        Format resource cost display.

        Args:
            resource: Resource type (energy, stamina, gems)
            amount: Cost amount

        Returns:
            Formatted string with emoji
        """
        emojis = {
            "energy": Emojis.ENERGY,
            "stamina": Emojis.STAMINA,
            "lumenite": Emojis.LUMENITE,
            "lumees": Emojis.LUMEES,
            "auric_coin": Emojis.AURIC_COIN,
        }

        emoji = emojis.get(resource, "•")
        return f"{emoji} {amount}"

    @staticmethod
    def format_reward_display(reward_type: str, amount: int) -> str:
        """
        Format reward display with appropriate emoji.

        Returns:
            Formatted reward string
        """
        emojis = {
            "lumees": Emojis.LUMEES,
            "xp": Emojis.NO_MASTERY,
            "lumenite": Emojis.LUMENITE,
            "auric_coin": Emojis.AURIC_COIN,
            "DROP_CHARGES": Emojis.DROP_CHARGES,
            "fusion_catalyst": Emojis.FUSION_SUCCESS_BOOST,
        }

        emoji = emojis.get(reward_type, Emojis.RADIANT)
        return f"{emoji} +{amount:,}"
