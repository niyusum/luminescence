"""
Mastery relic - permanent stat boost from exploration mastery.

Relics are earned by completing exploration sector mastery ranks.
They provide stackable, persistent bonuses that can be toggled active/inactive.

RIKI LAW Compliance:
- Article I: Economy domain model with proper indexing
- Article II: Complete audit trail (acquired_at timestamp)
- Article IV: Tunable relic values via ConfigManager
- Article VII: Business logic in RelicService, not model

Features:
- Stackable bonus system (multiple relics of same type add together)
- Active/inactive toggle for strategic builds
- Multiple relic types (shrine income, fusion rate, combat stats, resources, XP)
- Acquisition tracking (which sector/rank awarded the relic)
- Player-level aggregation methods
- Performance indexes for queries

Relic Types:
- shrine_income: Passive rikis boost from shrines
- combine_rate: Fusion success rate increase
- attack_boost: ATK multiplier for all maidens
- defense_boost: DEF multiplier for all maidens
- hp_boost: Flat max HP increase
- energy_regen: Energy regeneration per hour
- stamina_regen: Stamina regeneration per hour
- xp_gain: Experience multiplier from all sources
"""

from typing import Optional, Dict, List
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger, Index, Float, String, Boolean, DateTime
from datetime import datetime


class MasteryRelic(SQLModel, table=True):
    """
    Mastery relic - permanent stat boost from exploration mastery.
    
    Relics are stackable - players can have multiple relics of the same type,
    and bonus values add together. Relics can be toggled active/inactive
    for strategic customization without losing the relic.
    
    Attributes:
        id: Primary key
        player_id: Foreign key to players.discord_id
        relic_name: Display name of the relic
        relic_type: Type identifier (shrine_income, attack_boost, etc.)
        bonus_value: Numeric bonus (percentage or flat value depending on type)
        acquired_from: Source description (e.g., "Sector 5 Rank 2")
        acquired_at: Timestamp when relic was awarded
        is_active: Whether relic bonus is currently applied
    
    Indexes:
        - player_id (for player inventory queries)
        - relic_type (for type-specific aggregations)
        - is_active (for active bonus calculations)
        - Composite (player_id, relic_type) for efficient lookups
    
    Example Usage:
        >>> relic = MasteryRelic(
        ...     player_id=123456789,
        ...     relic_name="Shrine Income Boost",
        ...     relic_type="shrine_income",
        ...     bonus_value=5.0,
        ...     acquired_from="Sector 3 Rank 1"
        ... )
        >>> relic.get_display_value()
        "+5.0%"
        >>> relic.is_active = False
        >>> relic.get_status_display()
        "⚪ Inactive"
    """
    
    # ========================================================================
    # TABLE CONFIGURATION
    # ========================================================================
    
    __tablename__ = "mastery_relics"
    __table_args__ = (
        Index("ix_mastery_relics_player", "player_id"),
        Index("ix_mastery_relics_type", "relic_type"),
        Index("ix_mastery_relics_active", "is_active"),
        Index("ix_mastery_relics_player_type", "player_id", "relic_type"),
        Index("ix_mastery_relics_player_active", "player_id", "is_active"),
    )
    
    # ========================================================================
    # PRIMARY KEY & FOREIGN KEYS
    # ========================================================================
    
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        foreign_key="players.discord_id"
    )
    
    # ========================================================================
    # RELIC DETAILS
    # ========================================================================
    
    relic_name: str = Field(max_length=100, nullable=False)
    relic_type: str = Field(
        max_length=50,
        nullable=False,
        index=True,
        description="Type identifier from RELIC_TYPES"
    )
    bonus_value: float = Field(
        nullable=False,
        description="Bonus value - interpretation depends on relic_type"
    )
    
    # ========================================================================
    # METADATA & AUDIT TRAIL
    # ========================================================================
    
    acquired_from: str = Field(
        max_length=100,
        nullable=False,
        description="Source description (e.g., 'Sector 5 Rank 2')"
    )
    acquired_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    
    # ========================================================================
    # ACTIVE STATE
    # ========================================================================
    
    is_active: bool = Field(
        default=True,
        nullable=False,
        index=True,
        description="Whether relic bonus is currently applied to player stats"
    )
    
    # ========================================================================
    # RELIC TYPE CHECKING METHODS
    # ========================================================================
    
    def is_percentage_bonus(self) -> bool:
        """Check if relic uses percentage-based bonus."""
        percentage_types = {
            "shrine_income",
            "combine_rate",
            "attack_boost",
            "defense_boost",
            "xp_gain"
        }
        return self.relic_type in percentage_types
    
    def is_regen_bonus(self) -> bool:
        """Check if relic provides resource regeneration."""
        return self.relic_type in ("energy_regen", "stamina_regen")
    
    def is_combat_bonus(self) -> bool:
        """Check if relic provides combat stat bonus."""
        return self.relic_type in ("attack_boost", "defense_boost")
    
    # ========================================================================
    # DISPLAY METHODS (FOR DISCORD EMBEDS)
    # ========================================================================
    
    def get_display_value(self) -> str:
        """Format bonus value for display."""
        if self.is_percentage_bonus():
            return f"+{self.bonus_value:.1f}%"
        else:
            return f"+{int(self.bonus_value)}"
    
    def get_status_display(self) -> str:
        """Format active status for display."""
        return "🟢 Active" if self.is_active else "⚪ Inactive"
    
    def get_icon(self) -> str:
        """Get emoji icon for relic type."""
        from src.modules.exploration.constants import RELIC_TYPES
        
        relic_info = RELIC_TYPES.get(self.relic_type, {})
        return relic_info.get("icon", "📦")
    
    def get_full_description(self) -> str:
        """Get full relic description with bonus value."""
        return f"{self.relic_name}: {self.get_display_value()}"
    
    def get_embed_field(self) -> tuple:
        """Get (name, value) tuple for Discord embed field."""
        status = "🟢" if self.is_active else "⚪"
        name = f"{self.get_icon()} {self.relic_name}"
        value = f"{self.get_display_value()} {status}\n*From: {self.acquired_from}*"
        return (name, value)
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def toggle_active(self) -> bool:
        """Toggle relic active state."""
        self.is_active = not self.is_active
        return self.is_active
    
    def get_effective_bonus(self) -> float:
        """Get bonus value if active, 0 if inactive."""
        return self.bonus_value if self.is_active else 0.0
    
    # ========================================================================
    # STATIC AGGREGATION METHODS
    # ========================================================================
    
    @staticmethod
    def calculate_total_bonus(relics: List["MasteryRelic"], relic_type: str) -> float:
        """Calculate total bonus for specific relic type from list."""
        return sum(
            relic.bonus_value
            for relic in relics
            if relic.relic_type == relic_type and relic.is_active
        )
    
    @staticmethod
    def get_all_bonuses(relics: List["MasteryRelic"]) -> Dict[str, float]:
        """Calculate total bonuses for all relic types."""
        bonuses: Dict[str, float] = {}
        
        for relic in relics:
            if not relic.is_active:
                continue
            
            if relic.relic_type not in bonuses:
                bonuses[relic.relic_type] = 0.0
            
            bonuses[relic.relic_type] += relic.bonus_value
        
        return bonuses
    
    @staticmethod
    def count_by_type(relics: List["MasteryRelic"], relic_type: str) -> tuple:
        """Count active and total relics of specific type."""
        type_relics = [relic for relic in relics if relic.relic_type == relic_type]
        active_count = sum(1 for relic in type_relics if relic.is_active)
        total_count = len(type_relics)
        
        return (active_count, total_count)
    
    # ========================================================================
    # REPR
    # ========================================================================
    
    def __repr__(self) -> str:
        status = "active" if self.is_active else "inactive"
        return (
            f"<MasteryRelic(id={self.id}, type={self.relic_type}, "
            f"bonus={self.bonus_value}, {status})>"
        )