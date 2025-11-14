"""
Centralized color palette for Discord embeds.

Single source of truth for all embed colors across Lumen systems.
Provides context-aware color resolution for elements, tiers, features, and status.

LUMEN LAW Compliance:
- Article V: Single source of truth for UI colors
- Article IV: ConfigManager integration for runtime tuning

Features:
- Base status colors (success, error, warning, info)
- Feature-specific colors (fusion, summon, combat, etc.)
- Element-aware color resolution
- Tier-aware color resolution
- ConfigManager fallback support

Usage:
    >>> from src.ui.colors import ColorTheme
    >>> color = ColorTheme.get_color("success")  # Green
    >>> color = ColorTheme.get_color("element", element="infernal")  # Red
    >>> color = ColorTheme.get_color("tier", tier=5)  # Gold
"""

from typing import Optional
from src.core.config import ConfigManager


class ColorPalette:
    """
    Base color palette for Discord embeds.

    All colors are Discord-compatible integers (0xRRGGBB format).
    """

    # =========================================================================
    # CORE STATUS COLORS
    # =========================================================================

    DEFAULT = 0x5865F2  # Discord Blurple
    SUCCESS = 0x57F287  # Green
    ERROR = 0xED4245    # Red
    WARNING = 0xFEE75C  # Yellow
    INFO = 0x5865F2     # Blue

    # =========================================================================
    # GAME FEATURE COLORS
    # =========================================================================

    FUSION_SUCCESS = 0x57F287  # Green (successful fusion)
    FUSION_FAIL = 0xED4245     # Red (failed fusion)
    SUMMON = 0xEB459E          # Pink (gacha/summon)
    LEVEL_UP = 0xFEE75C        # Gold (level up celebration)
    DROP = 0x5865F2            # Blue (DROP system)
    ASCENSION = 0x9B59B6       # Purple (ascension tower)
    COMBAT = 0xE67E22          # Orange (combat encounters)
    ECONOMY = 0xF1C40F         # Yellow (economy/transactions)
    PROGRESSION = 0x3498DB     # Light Blue (progression tracking)
    SOCIAL = 0x1ABC9C          # Teal (guild/social)

    # =========================================================================
    # ELEMENT COLORS
    # =========================================================================

    INFERNAL = 0xEE4B2B   # Red (fire)
    ABYSSAL = 0x191970    # Midnight Blue (water/abyss)
    TEMPEST = 0x818589    # Gray (wind/storm)
    EARTH = 0x355E3B      # Hunter Green (earth/nature)
    RADIANT = 0xFFF8DC    # Cornsilk (light/holy)
    UMBRAL = 0x36454F     # Charcoal (dark/shadow)

    # =========================================================================
    # TIER/RARITY COLORS
    # =========================================================================

    TIER_1 = 0x95A5A6  # Gray (Common)
    TIER_2 = 0x27AE60  # Green (Uncommon)
    TIER_3 = 0x3498DB  # Blue (Rare)
    TIER_4 = 0x9B59B6  # Purple (Epic)
    TIER_5 = 0xF39C12  # Gold (Legendary)
    TIER_6 = 0xE74C3C  # Red (Mythic)


class ElementColors:
    """
    Element-specific color resolution.

    Maps element strings to their corresponding colors.
    """

    @classmethod
    def get(cls, element: str) -> int:
        """
        Get color for element.

        Args:
            element: Element name (case-insensitive)

        Returns:
            Color integer
        """
        element_map = {
            "infernal": ColorPalette.INFERNAL,
            "abyssal": ColorPalette.ABYSSAL,
            "tempest": ColorPalette.TEMPEST,
            "earth": ColorPalette.EARTH,
            "radiant": ColorPalette.RADIANT,
            "umbral": ColorPalette.UMBRAL,
        }

        return element_map.get(element.lower(), ColorPalette.DEFAULT)


class TierColors:
    """
    Tier/rarity-specific color resolution.

    Maps tier numbers to their corresponding colors.
    """

    @classmethod
    def get(cls, tier: int) -> int:
        """
        Get color for tier.

        Args:
            tier: Tier number (1-6)

        Returns:
            Color integer
        """
        tier_map = {
            1: ColorPalette.TIER_1,  # Common
            2: ColorPalette.TIER_2,  # Uncommon
            3: ColorPalette.TIER_3,  # Rare
            4: ColorPalette.TIER_4,  # Epic
            5: ColorPalette.TIER_5,  # Legendary
            6: ColorPalette.TIER_6,  # Mythic
        }

        return tier_map.get(tier, ColorPalette.DEFAULT)


class ColorTheme:
    """
    Context-aware color resolution with ConfigManager integration.

    Provides intelligent color selection based on context (element, tier, feature, status).
    Falls back to ConfigManager for runtime-tunable colors.

    Usage:
        >>> ColorTheme.get_color("success")  # Status color
        >>> ColorTheme.get_color("element", element="infernal")  # Element color
        >>> ColorTheme.get_color("tier", tier=5)  # Tier color
        >>> ColorTheme.get_color("fusion")  # Feature color
    """

    @classmethod
    def get_color(cls, context: str, **kwargs) -> int:
        """
        Get appropriate color for context.

        Args:
            context: Context type (e.g., "success", "element", "tier", "fusion")
            **kwargs: Additional context (e.g., element="infernal", tier=5)

        Returns:
            Color integer

        Examples:
            >>> ColorTheme.get_color("success")
            0x57F287
            >>> ColorTheme.get_color("element", element="infernal")
            0xEE4B2B
            >>> ColorTheme.get_color("tier", tier=5)
            0xF39C12
        """
        # Try ConfigManager first (allows runtime tuning)
        config_key = f"embed_colors.{context}"
        try:
            if config_color := ConfigManager.get(config_key):
                return config_color
        except Exception:
            pass  # Fall back to defaults

        # Element context
        if context == "element" and "element" in kwargs:
            return ElementColors.get(kwargs["element"])

        # Tier context
        if context == "tier" and "tier" in kwargs:
            return TierColors.get(kwargs["tier"])

        # Feature/status mapping
        color_map = {
            # Status
            "default": ColorPalette.DEFAULT,
            "success": ColorPalette.SUCCESS,
            "error": ColorPalette.ERROR,
            "warning": ColorPalette.WARNING,
            "info": ColorPalette.INFO,

            # Features
            "fusion_success": ColorPalette.FUSION_SUCCESS,
            "fusion_fail": ColorPalette.FUSION_FAIL,
            "summon": ColorPalette.SUMMON,
            "level_up": ColorPalette.LEVEL_UP,
            "drop": ColorPalette.DROP,
            "ascension": ColorPalette.ASCENSION,
            "combat": ColorPalette.COMBAT,
            "economy": ColorPalette.ECONOMY,
            "progression": ColorPalette.PROGRESSION,
            "social": ColorPalette.SOCIAL,
        }

        return color_map.get(context, ColorPalette.DEFAULT)
