"""
Core Database Models for Lumen (2025)

Purpose
-------
Core game entities that form the foundation of the Lumen RPG system.
These models represent the primary domain objects that all game features depend on.

Models
------
**Primary Entities:**
- Player: Player accounts and core stats
- Maiden: Collectible maiden entities
- MaidenBase: Base maiden templates/archetypes
- GameConfig: System-wide configuration storage

Responsibilities
----------------
- Define core entity schemas (ORM models)
- Establish relationships between core entities
- Enforce database-level constraints
- Provide type-safe data structures

Non-Responsibilities
--------------------
- Business logic (belongs in services)
- Queries (belongs in repositories)
- Validation (belongs in services/validators)
- Transactions (belongs in services)

Lumen 2025 Compliance
---------------------
- Models are PURE DATA DEFINITIONS
- No business logic methods
- Type-safe with Mapped[] annotations
- Use declarative ORM patterns
- Relationships defined with back_populates

Usage
-----
>>> from src.database.models.core import Player, Maiden
>>> # Models are used by services via DatabaseService transactions
"""

from src.database.models.core.game_config import GameConfig
from src.database.models.core.maiden import Maiden
from src.database.models.core.maiden_base import MaidenBase
from src.database.models.core.player import Player

__all__ = [
    # Primary entities
    "Player",
    "Maiden",
    "MaidenBase",
    # System
    "GameConfig",
]
