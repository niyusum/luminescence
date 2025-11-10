# src/database/models/__init__.py
"""
Unified model aggregator for all RIKI RPG domains.

RIKI LAW Compliance:
    - Centralized model registry for consistency and schema visibility
    - Domain-subfolder segregation for clarity and import hygiene
"""

# --- Core ---
from ..database.models.core.player import Player
from ..database.models.core.maiden import Maiden
from ..database.models.core.maiden_base import MaidenBase
from ..database.models.core.game_config import GameConfig

# --- Progression ---
from ..database.models.progression.ascension_progress import AscensionProgress
from ..database.models.progression.sector_progress import SectorProgress
from ..database.models.progression.daily_quest import DailyQuest
from ..database.models.progression.tutorial import TutorialProgress
from ..database.models.progression.leaderboard import LeaderboardSnapshot
from ..database.models.progression.exploration_mastery import ExplorationMastery

# --- Economy ---
from ..database.models.economy.transaction_log import TransactionLog
from ..database.models.economy.shrine import PlayerShrine
from ..database.models.economy.guild_shrine import GuildShrine
from ..database.models.economy.token import Token

# --- Combat ---
# Future: PvPMatch, WorldBoss, Enemy

# --- Social ---
from ..database.models.social.guild import Guild
from ..database.models.social.guild_member import GuildMember
from ..database.models.social.guild_invite import GuildInvite
from ..database.models.social.guild_audit import GuildAudit
from ..database.models.social.guild_role import GuildRole

__all__ = [
    # Core
    "Player", "Maiden", "MaidenBase", "GameConfig",
    # Progression
    "AscensionProgress", "SectorProgress", "DailyQuest",
    "TutorialProgress", "LeaderboardSnapshot", "ExplorationMastery",
    # Economy
    "TransactionLog", "PlayerShrine", "GuildShrine", "Token",
    # Combat
    # Future: "PvPMatch", "WorldBoss", "Enemy",
    # Social
    "Guild", "GuildMember", "GuildInvite", "GuildAudit", "GuildRole",
]
