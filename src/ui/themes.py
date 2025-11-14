"""
Branding and theming elements for Discord embeds.

Centralized branding, footer templates, and common field structures.
Ensures consistent tone, voice, and visual identity across all embeds.

LUMEN LAW Compliance:
- Article V: Single source of truth for branding
- Consistent messaging and tone across all player interactions

Features:
- Brand identity (name, tagline, footer templates)
- Context-aware footer generation
- Common field templates (resources, stats, progression)
- Reusable embed structures

Usage:
    >>> from src.ui.themes import BrandingTheme, FieldTemplates
    >>> footer = BrandingTheme.get_footer("Combat")
    >>> resource_field = FieldTemplates.resources_field(player)
"""

from typing import Optional, Dict, Any
from src.ui.emojis import Emojis


class BrandingTheme:
    """
    Lumen RPG branding and identity.

    Provides consistent branding elements across all Discord embeds.
    """

    # =========================================================================
    # BRAND IDENTITY
    # =========================================================================

    BOT_NAME = "Lumen RPG"
    TAGLINE = "Light favors the vigilant"
    DEFAULT_FOOTER = f"{BOT_NAME} • {TAGLINE}"

    # =========================================================================
    # CONTEXTUAL TAGLINES
    # =========================================================================

    TAGLINES = {
        "combat": "Victory through strength",
        "exploration": "Adventure awaits the bold",
        "fusion": "Power through unity",
        "summon": "Fortune favors the brave",
        "ascension": "Rise to new heights",
        "economy": "Prosperity through wisdom",
        "guild": "Together we shine brighter",
        "tutorial": "Every master was once a beginner",
        "leaderboard": "Glory to the strongest",
        "daily": "Consistency breeds excellence",
    }

    # =========================================================================
    # FOOTER TEMPLATES
    # =========================================================================

    @classmethod
    def get_footer(cls, context: Optional[str] = None, custom: Optional[str] = None) -> str:
        """
        Get appropriate footer for context.

        Args:
            context: Context type (e.g., "combat", "fusion")
            custom: Custom footer text (overrides context)

        Returns:
            Formatted footer string

        Examples:
            >>> BrandingTheme.get_footer()
            'Lumen RPG • Light favors the vigilant'
            >>> BrandingTheme.get_footer("combat")
            'Victory through strength • Lumen RPG'
            >>> BrandingTheme.get_footer(custom="Special Event")
            'Special Event'
        """
        if custom:
            return custom

        if context and context in cls.TAGLINES:
            return f"{cls.TAGLINES[context]} • {cls.BOT_NAME}"

        return cls.DEFAULT_FOOTER

    @classmethod
    def get_tutorial_footer(cls, step: int, total_steps: int) -> str:
        """
        Get footer for tutorial steps.

        Args:
            step: Current step number
            total_steps: Total number of steps

        Returns:
            Formatted tutorial footer
        """
        return f"Tutorial Step {step}/{total_steps} • {cls.TAGLINES['tutorial']}"

    @classmethod
    def get_page_footer(cls, page: int, total_pages: int, context: Optional[str] = None) -> str:
        """
        Get footer with page information.

        Args:
            page: Current page number
            total_pages: Total number of pages
            context: Optional context for tagline

        Returns:
            Formatted page footer
        """
        base_footer = cls.get_footer(context)
        return f"Page {page}/{total_pages} • {base_footer}"


class FieldTemplates:
    """
    Common field structures for Discord embeds.

    Provides reusable field templates for consistent embed layouts.
    """

    @staticmethod
    def resources_field(player, inline: bool = True) -> Dict[str, Any]:
        """
        Create resources field for player embeds.

        Args:
            player: Player model instance
            inline: Whether field should be inline

        Returns:
            Field dict with name, value, inline
        """
        return {
            "name": f"{Emojis.LUMEES} Resources",
            "value": (
                f"Lumees: **{player.lumees:,}**\n"
                f"AuricCoin: **{player.auric_coin:,}**\n"
                f"Lumenite: **{player.lumenite:,}**"
            ),
            "inline": inline
        }

    @staticmethod
    def energy_stamina_field(player, inline: bool = True) -> Dict[str, Any]:
        """
        Create energy & stamina field for player embeds.

        Args:
            player: Player model instance
            inline: Whether field should be inline

        Returns:
            Field dict
        """
        return {
            "name": f"{Emojis.ENERGY} Energy & Stamina",
            "value": (
                f"Energy: **{player.energy}/{player.max_energy}**\n"
                f"Stamina: **{player.stamina}/{player.max_stamina}**"
            ),
            "inline": inline
        }

    @staticmethod
    def progression_field(player, inline: bool = False) -> Dict[str, Any]:
        """
        Create progression field for player embeds.

        Args:
            player: Player model instance
            inline: Whether field should be inline

        Returns:
            Field dict
        """
        xp = getattr(player, "experience", 0)
        total_power = getattr(player, "total_power", 0)

        return {
            "name": f"{Emojis.EXPERIENCE} Progression",
            "value": (
                f"XP: **{xp:,}**\n"
                f"Total Power: **{total_power:,}**"
            ),
            "inline": inline
        }

    @staticmethod
    def collection_field(player, inline: bool = True) -> Dict[str, Any]:
        """
        Create collection stats field for player embeds.

        Args:
            player: Player model instance
            inline: Whether field should be inline

        Returns:
            Field dict
        """
        total_maidens = getattr(player, "total_maidens_owned", 0)
        unique_maidens = getattr(player, "unique_maidens", 0)

        return {
            "name": f"{Emojis.MAIDEN} Collection",
            "value": (
                f"Total Maidens: **{total_maidens}**\n"
                f"Unique: **{unique_maidens}**"
            ),
            "inline": inline
        }

    @staticmethod
    def drop_status_field(player, inline: bool = True) -> Dict[str, Any]:
        """
        Create DROP status field for player embeds.

        Args:
            player: Player model instance
            inline: Whether field should be inline

        Returns:
            Field dict
        """
        next_regen = getattr(player, "get_drop_regen_display", lambda: "N/A")
        next_regen_str = next_regen() if callable(next_regen) else "N/A"

        drop_status = f"{Emojis.SUCCESS} Ready!" if player.DROP_CHARGES >= 1 else f"{Emojis.REGENERATING} Regenerating"

        return {
            "name": f"{Emojis.DROP_CHARGES} DROP",
            "value": (
                f"**{drop_status}**\n"
                f"Next: {next_regen_str}"
            ),
            "inline": inline
        }
