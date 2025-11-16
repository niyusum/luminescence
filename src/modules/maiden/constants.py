"""
Unified maiden system constants for Lumen RPG.

Single source of truth for:
- Element definitions (names, emojis, colors)
- Tier definitions (names, colors, roman numerals, stat ranges)
- UI constants (pagination, progress bars)
- Embed colors for all contexts
- Cache key templates

LUMEN LAW Compliance:
- Pure data only - NO business logic (Article VII)
- Business logic stays in services (MaidenService, LeaderService, FusionService)
- Tunable game values stay in ConfigManager (Article IV)
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from src.ui.emojis import Emojis


# ============================================================================
# ELEMENTS
# ============================================================================

class Element(Enum):
    """
    Maiden element enumeration.

    Each element has display name, emoji, and Discord embed color.
    Business logic (bonuses, scaling) lives in LeaderService.
    """
    INFERNAL = ("infernal", "Infernal", Emojis.INFERNAL, 0xEE4B2B)
    UMBRAL = ("umbral", "Umbral", Emojis.UMBRAL, 0x36454F)
    EARTH = ("earth", "Earth", Emojis.EARTH, 0x355E3B)
    TEMPEST = ("tempest", "Tempest", Emojis.ENERGY, 0x818589)
    RADFIANT = ("radiant", "Radiant", Emojis.RADIANT, 0xFFF8DC)
    ABYSSAL = ("abyssal", "Abyssal", Emojis.ABYSSAL, 0x191970)

    def __init__(self, key: str, display_name: str, emoji: str, color: int):
        self.key = key
        self.display_name = display_name
        self.emoji = emoji
        self.color = color

    @classmethod
    def from_string(cls, value: str) -> Optional['Element']:
        """Get element from string (case-insensitive key or display name)."""
        value_lower = value.lower()
        for element in cls:
            if element.key == value_lower or element.display_name.lower() == value_lower:
                return element
        return None

    @classmethod
    def get_all_keys(cls) -> List[str]:
        """Get all element keys."""
        return [e.key for e in cls]

    @classmethod
    def get_all_names(cls) -> List[str]:
        """Get all element display names."""
        return [e.display_name for e in cls]

    def __str__(self) -> str:
        return f"{self.emoji} {self.display_name}"


# ============================================================================
# TIERS
# ============================================================================

@dataclass
class TierData:
    """
    Complete tier information with stat ranges for variety.

    stat_range: (min_total, max_total) - Range of total stats for this tier
                Used during seeding to create variety within tier
    base_attack: Representative/average attack for this tier
                 Used for balance calculations and reference

    Example: Tier 1 with stat_range (31, 62) and base_attack 45
    - Blazeblob could have 41 ATK, 6 DEF, 16 HP (total: 63)
    - Droozle could have 19 ATK, 15 DEF, 28 HP (total: 62)
    - Both valid Tier 1, different stat distributions
    """
    tier: int
    name: str
    roman: str
    stat_range: Tuple[int, int]  # (min_total, max_total) stats for variety
    base_attack: int             # Representative attack for scaling
    color: int

    @property
    def display_name(self) -> str:
        """Get full display name (e.g., 'Tier VII - Legendary')."""
        return f"Tier {self.roman} - {self.name}"

    @property
    def short_display(self) -> str:
        """Get short display name (e.g., 'T7 Legendary')."""
        return f"T{self.tier} {self.name}"

    @property
    def stat_range_display(self) -> str:
        """Get formatted stat range."""
        return f"{self.stat_range[0]:,}-{self.stat_range[1]:,} total stats"


class Tier:
    """
    Tier management system with exponentially rewarding progression.

    Provides tier metadata including stat ranges for seeding variety.
    Stat calculations and game balance live in services.
    """

    _TIER_DATA = {
        # Early Game - Linear Learning Phase (2.4-3.3x jumps)
        1: TierData(1, "Common", "I", (31, 62), 45, 0x808080),              # Gray
        2: TierData(2, "Uncommon", "II", (77, 154), 110, 0x40E0D0),        # Turquoise
        3: TierData(3, "Rare", "III", (210, 420), 300, 0x00FF00),          # Green
        4: TierData(4, "Epic", "IV", (630, 1260), 900, 0x0099FF),          # Blue

        # Mid Game - Accelerating Growth (3.3-3.7x jumps)
        5: TierData(5, "Mythic", "V", (2100, 4200), 3000, 0x9932CC),       # Purple
        6: TierData(6, "Divine", "VI", (7700, 15400), 11000, 0xFFD700),    # Gold
        7: TierData(7, "Legendary", "VII", (26250, 52500), 37500, 0xFF4500), # Orange Red
        8: TierData(8, "Ethereal", "VIII", (91000, 182000), 130000, 0x9370DB), # Medium Purple

        # End Game - Exponential Fantasy (3.4-3.7x jumps)
        9: TierData(9, "Genesis", "IX", (332500, 665000), 475000, 0x00CED1),   # Dark Turquoise
        10: TierData(10, "Empyrean", "X", (1120000, 2240000), 1600000, 0xFF1493), # Deep Pink
        11: TierData(11, "Void", "XI", (3850000, 7700000), 5500000, 0x1C1C1C),    # Almost Black
        12: TierData(12, "Singularity", "XII", (13650000, 27300000), 19500000, 0xFFFFFF) # Pure White
    }

    @classmethod
    def get(cls, tier: int) -> Optional[TierData]:
        """Get tier data by number."""
        return cls._TIER_DATA.get(tier)

    @classmethod
    def get_all(cls) -> Dict[int, TierData]:
        """Get all tier data."""
        return cls._TIER_DATA.copy()

    @classmethod
    def is_valid(cls, tier: int) -> bool:
        """Check if tier is valid."""
        return tier in cls._TIER_DATA

    @classmethod
    def get_max_tier(cls) -> int:
        """Get maximum tier number."""
        return max(cls._TIER_DATA.keys())


# ============================================================================
# EMBED COLORS
# ============================================================================

class EmbedColor:
    """
    Discord embed color system.

    Provides consistent colors across all bot responses.
    Can pull colors from Element or Tier enums for context-aware embeds.
    """

    # Base colors
    DEFAULT = 0x2c2d31  # Default dark theme

    # Status colors
    SUCCESS = 0x00ff00  # Bright green for victories/success
    ERROR = 0xff0000    # Red for defeats/errors
    WARNING = 0xffa500  # Orange for warnings
    INFO = 0x3498db     # Blue for information

    # Action-specific colors
    FUSION_SUCCESS = 0x00ff00   # Green for successful fusion
    FUSION_FAIL = 0xff6b6b      # Softer red for failed fusion
    SUMMON = 0x9b59b6           # Purple for summons
    LEVEL_UP = 0x00ffff         # Cyan for level ups
    DROP = 0xFFD700           # Gold for drop
    ASCENSION = 0xFF4500        # Orange for ascension

    @classmethod
    def get_element_color(cls, element: str) -> int:
        """Get color for specific element."""
        elem = Element.from_string(element)
        return elem.color if elem else cls.DEFAULT

    @classmethod
    def get_tier_color(cls, tier: int) -> int:
        """Get color based on tier."""
        tier_data = Tier.get(tier)
        return tier_data.color if tier_data else cls.DEFAULT

    @classmethod
    def get_context_color(cls, context: str, **kwargs) -> int:
        """
        Get appropriate color based on context.

        Args:
            context: Context type (success, error, element, tier, etc.)
            **kwargs: Additional context (element=, tier=)

        Returns:
            Discord color integer

        Example:
            >>> EmbedColor.get_context_color("element", element="infernal")
            0xEE4B2B
            >>> EmbedColor.get_context_color("tier", tier=7)
            0xFF4500
        """
        context_map = {
            "default": cls.DEFAULT,
            "success": cls.SUCCESS,
            "error": cls.ERROR,
            "warning": cls.WARNING,
            "info": cls.INFO,
            "fusion_success": cls.FUSION_SUCCESS,
            "fusion_fail": cls.FUSION_FAIL,
            "summon": cls.SUMMON,
            "level_up": cls.LEVEL_UP,
            "drop": cls.DROP,
            "ascension": cls.ASCENSION,
            "victory": cls.SUCCESS,
            "defeat": cls.ERROR,
        }

        # Handle special cases with kwargs
        if context == "element" and "element" in kwargs:
            return cls.get_element_color(kwargs["element"])
        elif context == "tier" and "tier" in kwargs:
            return cls.get_tier_color(kwargs["tier"])

        return context_map.get(context, cls.DEFAULT)


# ============================================================================
# UI CONSTANTS
# ============================================================================

class UIConstants:
    """Constants for Discord UI components."""

    # Pagination
    ITEMS_PER_PAGE = 10
    MAX_SELECT_OPTIONS = 25

    # Progress bars
    PROGRESS_BAR_LENGTH = 10
    PROGRESS_FILLED = "█"
    PROGRESS_EMPTY = "░"

    # Discord embed limits
    EMBED_DESCRIPTION_LIMIT = 4096
    EMBED_FIELD_LIMIT = 1024
    EMBED_TITLE_LIMIT = 256
    EMBED_FOOTER_LIMIT = 2048
    EMBED_AUTHOR_LIMIT = 256
    EMBED_MAX_FIELDS = 25

    # Button/Select limits
    MAX_BUTTONS_PER_ROW = 5
    MAX_ROWS = 5
    MAX_SELECT_VALUES = 25

    @classmethod
    def create_progress_bar(cls, current: int, maximum: int, length: Optional[int] = None) -> str:
        """
        Create a progress bar string.

        Args:
            current: Current value
            maximum: Maximum value
            length: Bar length (defaults to PROGRESS_BAR_LENGTH)

        Returns:
            Progress bar string (e.g., "████░░░░░░")
        """
        if length is None:
            length = cls.PROGRESS_BAR_LENGTH

        if maximum == 0:
            return cls.PROGRESS_EMPTY * length

        filled = min(int((current / maximum) * length), length)
        return cls.PROGRESS_FILLED * filled + cls.PROGRESS_EMPTY * (length - filled)

    @classmethod
    def truncate_text(cls, text: str, limit: int, suffix: str = "...") -> str:
        """
        Truncate text to fit within Discord limits.

        Args:
            text: Text to truncate
            limit: Character limit
            suffix: Suffix to add if truncated

        Returns:
            Truncated text
        """
        if len(text) <= limit:
            return text
        return text[:limit - len(suffix)] + suffix

    @classmethod
    def format_number(cls, num: int) -> str:
        """Format large numbers with commas (e.g., 1000000 → 1,000,000)."""
        return f"{num:,}"

    @classmethod
    def format_percentage(cls, value: float, decimals: int = 1) -> str:
        """Format percentage (e.g., 0.125 → 12.5%)."""
        return f"{value * 100:.{decimals}f}%"


# ============================================================================
# CACHE KEYS
# ============================================================================

class CacheKey:
    """
    Redis cache key templates.

    Use .format() to substitute values:
        >>> CacheKey.PLAYER_POWER.format(player_id=123)
        'player_power:123'
    """

    # Player-specific
    PLAYER_POWER = "player_power:{player_id}"
    PLAYER_MAIDENS = "player_maidens:{player_id}"
    PLAYER_COLLECTION = "player_collection:{player_id}"
    PLAYER_LEADER = "player_leader:{player_id}"

    # Maiden-specific
    MAIDEN_STATS = "maiden_stats:{maiden_id}"
    MAIDEN_BASE = "maiden_base:{maiden_base_id}"

    # Game data
    FUSION_RATES = "fusion_rates:tier_{tier}"
    SUMMON_POOL = "summon_pool:{tier}"
    LEADERBOARD = "leaderboard:{board_type}"

    # TTLs (seconds)
    TTL_PLAYER_POWER = 300       # 5 minutes
    TTL_PLAYER_MAIDENS = 600     # 10 minutes
    TTL_PLAYER_COLLECTION = 900  # 15 minutes
    TTL_MAIDEN_STATS = 1800      # 30 minutes
    TTL_FUSION_RATES = 3600      # 1 hour
    TTL_SUMMON_POOL = 3600       # 1 hour
    TTL_LEADERBOARD = 300        # 5 minutes


# ============================================================================
# FUSION ELEMENTS CHART
# ============================================================================

# Fusion element combinations (pure data mapping)
FUSION_ELEMENT_CHART = {
    # Same element fusions
    ("infernal", "infernal"): "infernal",
    ("umbral", "umbral"): "umbral",
    ("earth", "earth"): "earth",
    ("tempest", "tempest"): "tempest",
    ("radiant", "radiant"): "radiant",
    ("abyssal", "abyssal"): "abyssal",

    # Cross-element fusions (alphabetically sorted keys)
    ("abyssal", "infernal"): "tempest",
    ("earth", "infernal"): ["infernal", "earth"],
    ("infernal", "tempest"): ["infernal", "tempest"],
    ("infernal", "umbral"): ["infernal", "umbral"],
    ("infernal", "radiant"): "earth",

    ("abyssal", "earth"): ["abyssal", "earth"],
    ("abyssal", "tempest"): ["abyssal", "tempest"],
    ("abyssal", "umbral"): "earth",
    ("abyssal", "radiant"): "tempest",

    ("earth", "tempest"): "abyssal",
    ("earth", "umbral"): "infernal",
    ("earth", "radiant"): ["earth", "radiant"],

    ("tempest", "umbral"): "abyssal",
    ("radiant", "tempest"): ["tempest", "radiant"],

    ("radiant", "umbral"): "random"
}


def get_fusion_element(element1: str, element2: str):
    """
    Get fusion result element(s) for two input elements.

    Args:
        element1: First element key
        element2: Second element key

    Returns:
        - Single element key (str) if deterministic
        - List of element keys if random between options
        - "random" if completely random

    Example:
        >>> get_fusion_element("infernal", "abyssal")
        'tempest'
        >>> get_fusion_element("earth", "infernal")
        ['infernal', 'earth']
    """
    # Sort alphabetically for consistent lookup
    e1, e2 = sorted([element1.lower(), element2.lower()])
    sorted_elements: tuple[str, str] = (e1, e2)
    return FUSION_ELEMENT_CHART.get(sorted_elements, "random")


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "Element",
    "Tier",
    "TierData",
    "EmbedColor",
    "UIConstants",
    "CacheKey",
    "FUSION_ELEMENT_CHART",
    "get_fusion_element",
]
