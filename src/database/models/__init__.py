# src/database/models/__init__.py
"""
Unified model aggregator for all RIKI RPG domains.

RIKI LAW Compliance:
    - Centralized model registry for consistency and schema visibility
    - Domain-subfolder segregation for clarity and import hygiene
"""

# --- Core ---
from .core.player import Player
from .core.maiden import Maiden
from .core.maiden_base import MaidenBase
from .core.game_config import GameConfig

# --- Progression ---
from .progression.ascension_progress import AscensionProgress
from .progression.sector_progress import SectorProgress
from .progression.daily_quest import DailyQuest
from .progression.tutorial import TutorialProgress
from .progression.leaderboard import LeaderboardSnapshot
from .progression.exploration_mastery import ExplorationMastery

# --- Economy ---
from .economy.transaction_log import TransactionLog
from .economy.shrine import PlayerShrine
from .economy.guild_shrine import GuildShrine
from .economy.token import Token

# --- Combat ---
# Future: PvPMatch, WorldBoss, Enemy

# --- Social ---
from .social.guild import Guild
from .social.guild_member import GuildMember
from .social.guild_invite import GuildInvite
from .social.guild_audit import GuildAudit
from .social.guild_role import GuildRole

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
