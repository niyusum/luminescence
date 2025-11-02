
"""
Ascension system constants - minimal and data-driven.

Contains ONLY the data that's currently hardcoded in the service:
- Boss name generation logic (no sprites assumed)
- HP/reward scaling formulas
- Milestone floor definitions
- Resource costs

Future: When sprites/assets are ready, expand boss definitions.
For now: Keep it simple and functional.
"""

from typing import Dict, Any
from dataclasses import dataclass


# ============================================================================
# HP SCALING
# ============================================================================

BASE_HP = 1000
HP_GROWTH_RATE = 1.10
MAX_HP = 999_999_999_999  # Prevent overflow at extreme floors


# ============================================================================
# REWARD SCALING
# ============================================================================

BASE_RIKIS_REWARD = 50
BASE_XP_REWARD = 20
REWARD_GROWTH_RATE = 1.12

# Reward intervals
EGG_INTERVAL = 5           # Maiden egg every 5 floors
PRAYER_INTERVAL = 10       # Prayer charge every 10 floors
CATALYST_INTERVAL = 25     # Fusion catalyst every 25 floors


# ============================================================================
# STAMINA COSTS
# ============================================================================

BASE_STAMINA_COST = 5
STAMINA_INCREASE_PER_10_LEVELS = 1
MAX_STAMINA_COST = 50


# ============================================================================
# ATTACK CONSTANTS
# ============================================================================

ATTACK_MULTIPLIERS = {
    "x1": 1,
    "x5": 5,
    "x20": 20
}

GEM_ATTACK_COST = 10
X20_CRIT_CHANCE = 0.20
X20_CRIT_MULTIPLIER = 1.5


# ============================================================================
# BOSS NAME GENERATION (Current System)
# ============================================================================

# Generic boss name components (no sprites assumed)
BOSS_PREFIXES_BY_TIER = {
    (1, 10): ["Lesser", "Minor", "Weak"],
    (11, 50): ["Guardian", "Sentinel", "Watcher"],
    (51, 100): ["Elite", "Champion", "Veteran"],
    (101, 200): ["Ascended", "Exalted", "Divine"],
    (201, 999999): ["Transcendent", "Eternal", "Absolute"],
}

BOSS_TYPES = ["Warrior", "Mage", "Beast", "Construct", "Wraith"]


# ============================================================================
# MILESTONE BOSSES (Special Named Bosses)
# ============================================================================

@dataclass(frozen=True)
class MilestoneBoss:
    """Special boss for milestone floors."""
    name: str
    description: str  # Short flavor text for now
    hp_multiplier: float = 1.5


# Milestone bosses - can expand these as you add lore/sprites
MILESTONE_BOSSES: Dict[int, MilestoneBoss] = {
    50: MilestoneBoss(
        name="Floor 50 Guardian",
        description="A powerful guardian marking your progress",
        hp_multiplier=1.5
    ),
    100: MilestoneBoss(
        name="Floor 100 Champion",
        description="The champion of the 100th floor",
        hp_multiplier=2.0
    ),
    200: MilestoneBoss(
        name="Floor 200 Ascendant",
        description="An ascended being of immense power",
        hp_multiplier=3.0
    ),
    # Add more as you develop lore/assets
}


# ============================================================================
# MILESTONE REWARDS
# ============================================================================

MILESTONE_REWARDS: Dict[int, Dict[str, Any]] = {
    50: {
        "title": "Tower Climber",
        "rikis": 10000,
        "gems": 5
    },
    100: {
        "title": "Sky Piercer",
        "rikis": 50000,
        "gems": 10,
        "prayer_charges": 1
    },
    200: {
        "title": "Celestial Ascendant",
        "rikis": 500000,
        "gems": 25,
        "prayer_charges": 2,
        "fusion_catalyst": 1
    },
    # Add more as you design progression
}


# ============================================================================
# EGG RARITY BY FLOOR RANGE
# ============================================================================

def get_egg_rarity_for_floor(floor: int) -> str:
    """
    Determine maiden egg rarity based on floor number.
    
    Simple escalating rarity based on floor ranges.
    """
    if floor < 20:
        return "common"
    elif floor < 50:
        return "rare"
    elif floor < 100:
        return "epic"
    elif floor < 200:
        return "legendary"
    else:
        return "mythic"


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_boss_prefix_for_floor(floor: int) -> str:
    """
    Get appropriate boss prefix for floor number.
    
    Uses tier ranges to select from prefix pools.
    """
    import random
    
    for (min_floor, max_floor), prefixes in BOSS_PREFIXES_BY_TIER.items():
        if min_floor <= floor <= max_floor:
            return random.choice(prefixes)
    
    # Fallback to highest tier
    return random.choice(BOSS_PREFIXES_BY_TIER[(201, 999999)])


def is_milestone_floor(floor: int) -> bool:
    """Check if floor is a special milestone floor."""
    return floor in MILESTONE_BOSSES