"""
Exploration system constants.

Single source of truth for:
- Sector definitions (requirements, rewards, difficulty)
- Mastery rank system (requirements, rewards)
- Relic types (bonuses from mastery completion)
- Energy costs and scaling

RIKI LAW Compliance:
- Article V: Centralized constants for exploration domain
- Article IV: Tunable values via ConfigManager
"""

from typing import Dict, Any
from dataclasses import dataclass


# ============================================================================
# MASTERY RANKS
# ============================================================================

MASTERY_RANKS_PER_SECTOR = 3

MASTERY_RANK_NAMES = {
    1: "Bronze",
    2: "Silver", 
    3: "Gold"
}

MASTERY_RANK_EMOJIS = {
    0: "⭐",  # No mastery
    1: "🥉",  # Bronze
    2: "🥈",  # Silver
    3: "🥇",  # Gold
}


# ============================================================================
# RELIC TYPES (from mastery completion)
# ============================================================================

RELIC_TYPES = {
    "shrine_income": {
        "name": "Shrine Income Boost",
        "description": "Increases passive rikis earned from shrines",
        "icon": "🏛️",
        "bonus_type": "percentage",
        "category": "economy"
    },
    "combine_rate": {
        "name": "Fusion Success Boost",
        "description": "Increases success rate for maiden fusion",
        "icon": "🔮",
        "bonus_type": "percentage",
        "category": "progression"
    },
    "attack_boost": {
        "name": "Attack Power Boost",
        "description": "Increases ATK stat for all maidens",
        "icon": "⚔️",
        "bonus_type": "percentage",
        "category": "combat"
    },
    "defense_boost": {
        "name": "Defense Power Boost",
        "description": "Increases DEF stat for all maidens",
        "icon": "🛡️",
        "bonus_type": "percentage",
        "category": "combat"
    },
    "hp_boost": {
        "name": "HP Boost",
        "description": "Increases max HP for ascension tower",
        "icon": "❤️",
        "bonus_type": "flat",
        "category": "survival"
    },
    "energy_regen": {
        "name": "Energy Regeneration",
        "description": "Increases energy regeneration per hour",
        "icon": "⚡",
        "bonus_type": "flat",
        "category": "resources"
    },
    "stamina_regen": {
        "name": "Stamina Regeneration",
        "description": "Increases stamina regeneration per hour",
        "icon": "💪",
        "bonus_type": "flat",
        "category": "resources"
    },
    "xp_gain": {
        "name": "Experience Boost",
        "description": "Increases XP gained from all sources",
        "icon": "📈",
        "bonus_type": "percentage",
        "category": "progression"
    }
}

RELIC_CATEGORIES = {
    "economy": {"name": "Economy", "icon": "💰", "types": ["shrine_income"]},
    "combat": {"name": "Combat", "icon": "⚔️", "types": ["attack_boost", "defense_boost"]},
    "progression": {"name": "Progression", "icon": "📊", "types": ["combine_rate", "xp_gain"]},
    "resources": {"name": "Resources", "icon": "⚡", "types": ["energy_regen", "stamina_regen"]},
    "survival": {"name": "Survival", "icon": "❤️", "types": ["hp_boost"]}
}


# ============================================================================
# MASTERY RANK REWARDS
# ============================================================================

@dataclass
class RankReward:
    """Reward for completing a mastery rank."""
    relic_type: str
    bonus_value: float
    description: str


# Rewards scale by sector tier
MASTERY_RANK_REWARDS: Dict[int, Dict[int, RankReward]] = {
    1: {  # Sector 1
        1: RankReward("energy_regen", 5.0, "Basic Energy Regeneration"),
        2: RankReward("stamina_regen", 3.0, "Basic Stamina Regeneration"),
        3: RankReward("xp_gain", 5.0, "Experience Boost"),
    },
    # Add more sectors as you design them
}


# ============================================================================
# SECTOR DEFINITIONS
# ============================================================================

@dataclass
class SectorData:
    """Complete sector information."""
    sector_id: int
    name: str
    min_level: int
    energy_cost: int
    description: str
    rank_requirements: Dict[int, int]  # rank -> completions_needed


SECTOR_DEFINITIONS: Dict[int, SectorData] = {
    1: SectorData(
        sector_id=1,
        name="Whispering Woods",
        min_level=1,
        energy_cost=10,
        description="A peaceful forest perfect for beginners",
        rank_requirements={1: 5, 2: 15, 3: 30}
    ),
    # Add more sectors
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_relic_info(relic_type: str) -> dict:
    """Get relic metadata by type."""
    if relic_type not in RELIC_TYPES:
        raise ValueError(f"Unknown relic type: {relic_type}")
    return RELIC_TYPES[relic_type]


def is_valid_relic_type(relic_type: str) -> bool:
    """Check if relic type is valid."""
    return relic_type in RELIC_TYPES


def get_relics_by_category(category: str) -> list:
    """Get all relic types in a category."""
    if category not in RELIC_CATEGORIES:
        raise ValueError(f"Unknown category: {category}")
    return RELIC_CATEGORIES[category]["types"]


def get_sector_info(sector_id: int) -> SectorData:
    """Get sector data by ID."""
    if sector_id not in SECTOR_DEFINITIONS:
        raise ValueError(f"Unknown sector: {sector_id}")
    return SECTOR_DEFINITIONS[sector_id]


def get_rank_reward(sector_id: int, rank: int) -> RankReward:
    """Get reward for completing sector rank."""
    if sector_id not in MASTERY_RANK_REWARDS:
        raise ValueError(f"No rewards defined for sector {sector_id}")
    if rank not in MASTERY_RANK_REWARDS[sector_id]:
        raise ValueError(f"No reward defined for sector {sector_id} rank {rank}")
    return MASTERY_RANK_REWARDS[sector_id][rank]