"""
Ascension system constants.

Single source of truth for:
- Token tier definitions (maiden redemption)
- Attack cost definitions
- Token drop weights by floor

RIKI LAW Compliance:
- Article IV: Pure data only, tunable values in ConfigManager
- Article VII: No business logic in constants

Note: Boss generation, HP scaling, and rewards are handled via ConfigManager
in the service layer for maximum flexibility.
"""

from typing import Dict, Optional, Tuple
import random


# ============================================================================
# TOKEN TIERS (Display & Reference Data)
# ============================================================================

TOKEN_TIERS: Dict[str, Dict] = {
    "bronze": {
        "name": "Bronze Token",
        "tier_range": (1, 3),
        "emoji": "🥉",
        "color": 0xCD7F32,
        "description": "Redeems for Tier 1-3 Maiden",
        "order": 1
    },
    "silver": {
        "name": "Silver Token",
        "tier_range": (3, 5),
        "emoji": "🥈",
        "color": 0xC0C0C0,
        "description": "Redeems for Tier 3-5 Maiden",
        "order": 2
    },
    "gold": {
        "name": "Gold Token",
        "tier_range": (5, 7),
        "emoji": "🥇",
        "color": 0xFFD700,
        "description": "Redeems for Tier 5-7 Maiden",
        "order": 3
    },
    "platinum": {
        "name": "Platinum Token",
        "tier_range": (7, 9),
        "emoji": "💎",
        "color": 0xE5E4E2,
        "description": "Redeems for Tier 7-9 Maiden",
        "order": 4
    },
    "diamond": {
        "name": "Diamond Token",
        "tier_range": (9, 11),
        "emoji": "💠",
        "color": 0xB9F2FF,
        "description": "Redeems for Tier 9-11 Maiden",
        "order": 5
    }
}

FLOOR_COLOR_TIERS = {
    "GRAY": (1, 25, 0x808080),
    "GREEN": (26, 50, 0x00FF00),
    "BLUE": (51, 100, 0x0099FF),
    "PURPLE": (101, 150, 0x9932CC),
    "ORANGE_RED": (151, 9999, 0xFF4500),
}

# ============================================================================
# TOKEN HELPER FUNCTIONS
# ============================================================================

def get_token_tier(token_type: str) -> Optional[Dict]:
    """
    Get token tier data by type.
    
    Args:
        token_type: Token type key (bronze, silver, etc.)
    
    Returns:
        Token tier data dict or None if invalid
    """
    return TOKEN_TIERS.get(token_type.lower())


def get_all_token_types() -> list:
    """Get list of all valid token types in display order."""
    return sorted(TOKEN_TIERS.keys(), key=lambda k: TOKEN_TIERS[k]["order"])


def validate_token_type(token_type: str) -> bool:
    """Check if token type is valid."""
    return token_type.lower() in TOKEN_TIERS


def get_token_display_name(token_type: str) -> str:
    """Get display name for token type."""
    tier_data = get_token_tier(token_type)
    return tier_data["name"] if tier_data else "Unknown Token"


def get_token_emoji(token_type: str) -> str:
    """Get emoji for token type."""
    tier_data = get_token_tier(token_type)
    return tier_data["emoji"] if tier_data else "🎫"


def get_token_tier_range(token_type: str) -> Optional[Tuple[int, int]]:
    """Get maiden tier range for token type."""
    tier_data = get_token_tier(token_type)
    return tier_data["tier_range"] if tier_data else None


def get_token_color(token_type: str) -> int:
    """Get Discord embed color for token type."""
    tier_data = get_token_tier(token_type)
    return tier_data["color"] if tier_data else 0x2C2D31


# ============================================================================
# ATTACK COSTS (Used by service.get_attack_cost)
# ============================================================================

ATTACK_COSTS: Dict[str, Dict[str, int]] = {
    "x1": {"stamina": 1, "gems": 0},
    "x3": {"stamina": 3, "gems": 0},
    "x10": {"stamina": 10, "gems": 10}
}


def get_attack_cost(attack_type: str) -> Dict[str, int]:
    """
    Get resource costs for attack type.
    
    Args:
        attack_type: "x1", "x3", or "x10"
    
    Returns:
        {"stamina": int, "gems": int}
    """
    return ATTACK_COSTS.get(attack_type, {"stamina": 1, "gems": 0})