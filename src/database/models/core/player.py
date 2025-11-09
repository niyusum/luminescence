"""
Core Player model with comprehensive progression tracking and stat allocation system.

RIKI LAW Compliance:
- Article I: Core domain model with proper indexing
- Article II: Complete audit trail (created_at, last_active, last_level_up)
- Article IV: Tunable values via ConfigManager integration
- Article V: Immutable base constants for stat calculations

Features:
- Multi-resource management (energy, stamina, hp, grace, rikis, prayer charges)
- Stat allocation system (5 points per level, allocate to energy/stamina/hp)
- Player class system (destroyer, adapter, invoker)
- Tutorial progression tracking
- Gacha system integration (pity counter, summon tracking)
- Fusion system tracking (shards, success rates)
- Combat power aggregation (attack, defense, total_power)
- Comprehensive statistics tracking
- Performance-optimized indexes for leaderboards and queries

Player Classes (Choose ONE - Permanent):
- DESTROYER: +25% stamina regeneration (faster combat recovery)
- ADAPTER: +25% energy regeneration (faster exploration recovery)
- INVOKER: +25% rewards from shrines (more rikis/items from shrine visits)

Stat Allocation Mechanics:
- Players gain 5 allocation points per level
- Points can be allocated to Energy, Stamina, or HP
- Energy: +10 per point (exploration, questing)
- Stamina: +5 per point (combat, raids)
- HP: +100 per point (ascension survival)
- Full resource refresh on level up
"""

from typing import Optional, Dict
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger, Index
from sqlalchemy.dialects.postgresql import JSON
from datetime import datetime


class Player(SQLModel, table=True):
    """
    Core player data model representing a Discord user in RIKI RPG.
    
    Stores player progression, resources, stats, metadata, and stat allocations.
    All resource regeneration and activity tracking handled through this model.
    
    Attributes:
        discord_id: Unique Discord user ID (primary key)
        level: Current player level (1-∞)
        grace: Prayer currency for summoning maidens
        rikis: Primary currency for fusion and upgrades
        riki_gems: Premium currency for shop purchases
        energy: Resource for questing and exploration
        stamina: Resource for battles and raids
        hp: Resource for ascension tower (survival stat)
        prayer_charges: Charges for prayer system (0-1, regenerates every 5 minutes)
        fusion_shards: Dictionary of shards per tier for guaranteed fusions
        total_power: Calculated combat power from all maidens
        stat_points_available: Unspent allocation points
        stat_points_spent: Point distribution across energy/stamina/hp
    
    Stat Allocation System:
        - Gain 5 points per level up
        - Allocate to energy (+10 max), stamina (+5 max), or hp (+100 max)
        - Full resource refresh on level up
        - Reset available via service (with cost)
    
    Indexes:
        - discord_id (unique)
        - level
        - total_power
        - last_active
        - player_class + level composite
        - Various composite indexes for leaderboards and queries
    """
    
    # ========================================================================
    # STAT ALLOCATION CONSTANTS (IMMUTABLE)
    # ========================================================================
    
    BASE_ENERGY = 100
    BASE_STAMINA = 50
    BASE_HP = 500
    
    ENERGY_PER_POINT = 10
    STAMINA_PER_POINT = 5
    HP_PER_POINT = 100
    POINTS_PER_LEVEL = 5

    # ========================================================================
    # PLAYER CLASS SYSTEM
    # ========================================================================

    DESTROYER = "destroyer"  # Combat specialist - +25% stamina regeneration
    ADAPTER = "adapter"      # Exploration specialist - +25% energy regeneration
    INVOKER = "invoker"      # Shrine specialist - +25% shrine rewards

    VALID_CLASSES = [DESTROYER, ADAPTER, INVOKER]

    # ========================================================================
    # TABLE CONFIGURATION
    # ========================================================================
    
    __tablename__ = "players"
    __table_args__ = (
        Index("ix_players_discord_id", "discord_id", unique=True),
        Index("ix_players_level", "level"),
        Index("ix_players_total_power", "total_power"),
        Index("ix_players_last_active", "last_active"),
        Index("ix_players_last_level_up", "last_level_up"),
        Index("ix_players_class_level", "player_class", "level"),
        Index("ix_players_highest_sector", "highest_sector_reached"),
        Index("ix_players_highest_floor", "highest_floor_ascended"),
        Index("ix_players_class_power", "player_class", "total_power"),  # Class-based leaderboards
        Index("ix_players_active_level", "last_active", "level"),  # Comeback bonus eligibility
    )
    
    # ========================================================================
    # PRIMARY KEY & IDENTITY
    # ========================================================================
    
    id: Optional[int] = Field(default=None, primary_key=True)
    discord_id: int = Field(
        sa_column=Column(BigInteger, unique=True, nullable=False, index=True)
    )
    username: str = Field(default="Unknown", max_length=100)
    
    # ========================================================================
    # TIMESTAMPS
    # ========================================================================
    
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    last_active: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    last_level_up: Optional[datetime] = Field(default=None, index=True)
    
    # ========================================================================
    # PROGRESSION
    # ========================================================================
    
    level: int = Field(default=1, ge=1, index=True)
    experience: int = Field(default=0, ge=0, sa_column=Column(BigInteger))
    
    # ========================================================================
    # CURRENCIES
    # ========================================================================
    
    grace: int = Field(default=5, ge=0)
    rikis: int = Field(default=1000, ge=0, sa_column=Column(BigInteger))
    riki_gems: int = Field(default=0, ge=0)  # Premium currency
    
    # ========================================================================
    # RESOURCES (CURRENT VALUES)
    # ========================================================================
    
    energy: int = Field(default=100, ge=0)
    max_energy: int = Field(default=100, ge=0)
    
    stamina: int = Field(default=50, ge=0)
    max_stamina: int = Field(default=50, ge=0)
    
    hp: int = Field(default=500, ge=0)  # NEW: Ascension survival stat
    max_hp: int = Field(default=500, ge=0)  # NEW: Scales with stat allocation
    
    prayer_charges: int = Field(default=0, ge=0, le=1)
    max_prayer_charges: int = Field(default=1, ge=0)  # DEPRECATED: Always 1 (single charge system)
    last_prayer_regen: Optional[datetime] = Field(default=None)
    
    # ========================================================================
    # STAT ALLOCATION SYSTEM (NEW)
    # ========================================================================
    
    stat_points_available: int = Field(default=0, ge=0)
    stat_points_spent: Dict[str, int] = Field(
        default_factory=lambda: {
            "energy": 0,
            "stamina": 0,
            "hp": 0
        },
        sa_column=Column(JSON)
    )
    
    # ========================================================================
    # FUSION SYSTEM
    # ========================================================================
    
    fusion_shards: Dict[str, int] = Field(
        default_factory=lambda: {
            "tier_1": 0, "tier_2": 0, "tier_3": 0, "tier_4": 0,
            "tier_5": 0, "tier_6": 0, "tier_7": 0, "tier_8": 0,
            "tier_9": 0, "tier_10": 0, "tier_11": 0
        },
        sa_column=Column(JSON)
    )
    
    total_fusions: int = Field(default=0, ge=0)
    successful_fusions: int = Field(default=0, ge=0)
    failed_fusions: int = Field(default=0, ge=0)
    highest_tier_achieved: int = Field(default=1, ge=1)
    
    # ========================================================================
    # COMBAT POWER
    # ========================================================================
    
    total_attack: int = Field(default=0, ge=0, sa_column=Column(BigInteger))
    total_defense: int = Field(default=0, ge=0, sa_column=Column(BigInteger))
    total_power: int = Field(default=0, ge=0, sa_column=Column(BigInteger), index=True)
    
    # ========================================================================
    # MAIDEN COLLECTION
    # ========================================================================
    
    leader_maiden_id: Optional[int] = Field(default=None, foreign_key="maidens.id")
    total_maidens_owned: int = Field(default=0, ge=0)
    unique_maidens: int = Field(default=0, ge=0)
    
    # ========================================================================
    # GACHA SYSTEM
    # ========================================================================
    
    total_summons: int = Field(default=0, ge=0)
    pity_counter: int = Field(default=0, ge=0)
    
    # ========================================================================
    # PLAYER CLASS SYSTEM
    # ========================================================================
    
    player_class: Optional[str] = Field(default=None, max_length=20, index=True)
    # Classes: "destroyer" (+25% stamina regen)
    #          "adapter" (+25% energy regen)
    #          "invoker" (+25% shrine rewards)
    
    # ========================================================================
    # TUTORIAL SYSTEM
    # ========================================================================
    
    tutorial_completed: bool = Field(default=False)
    tutorial_step: int = Field(default=0, ge=0)
    
    # ========================================================================
    # COMPREHENSIVE STATISTICS
    # ========================================================================
    
    stats: Dict[str, int] = Field(
        default_factory=lambda: {
            "battles_fought": 0,
            "battles_won": 0,
            "total_rikis_earned": 0,
            "total_rikis_spent": 0,
            "prayers_performed": 0,
            "shards_earned": 0,
            "shards_spent": 0,
            "level_ups": 0,
            "overflow_energy_gained": 0,
            "overflow_stamina_gained": 0,
            "total_explorations": 0,
            "total_miniboss_defeats": 0,
            "total_maidens_purified": 0,
            "total_floor_attempts": 0,
            "total_floor_victories": 0,
        },
        sa_column=Column(JSON)
    )
    
    # ========================================================================
    # PROGRESSION MILESTONES
    # ========================================================================
    
    highest_sector_reached: int = Field(default=0, ge=0)
    highest_floor_ascended: int = Field(default=0, ge=0)
    
    # ========================================================================
    # ORIGINAL METHODS (PRESERVED)
    # ========================================================================
    
    def get_fusion_shards(self, tier: int) -> int:
        """Get number of fusion shards for specific tier."""
        return self.fusion_shards.get(f"tier_{tier}", 0)
    
    def get_class_bonus_description(self) -> str:
        """Get human-readable description of current class bonuses."""
        bonuses = {
            "destroyer": "+25% stamina regeneration",
            "adapter": "+25% energy regeneration",
            "invoker": "+25% rewards from shrines"
        }
        return bonuses.get(self.player_class, "No class selected")
    
    def get_power_display(self) -> str:
        """Format total power with K/M abbreviations."""
        if self.total_power >= 1_000_000:
            return f"{self.total_power / 1_000_000:.1f}M"
        elif self.total_power >= 1_000:
            return f"{self.total_power / 1_000:.1f}K"
        return str(self.total_power)
    
    def get_prayer_regen_time_remaining(self) -> int:
        """
        Calculate seconds until next prayer charge regenerates.
        
        Returns:
            Seconds remaining (0 if at max charges or ready to regen)
        """
        if self.prayer_charges >= self.max_prayer_charges:
            return 0
        
        if self.last_prayer_regen is None:
            return 0
        
        from src.core.config.config_manager import ConfigManager
        regen_interval = ConfigManager.get("prayer_system.regen_minutes", 5) * 60
        time_since = (datetime.utcnow() - self.last_prayer_regen).total_seconds()
        return max(0, int(regen_interval - time_since))
    
    def get_prayer_regen_display(self) -> str:
        """Format prayer regeneration time as 'Xm Ys' or 'Ready!'."""
        remaining = self.get_prayer_regen_time_remaining()
        if remaining == 0:
            return "Ready!"
        
        minutes = remaining // 60
        seconds = remaining % 60
        return f"{minutes}m {seconds}s"
    
    def update_activity(self) -> None:
        """Update last_active timestamp to current time."""
        self.last_active = datetime.utcnow()
    
    def calculate_fusion_success_rate(self) -> float:
        """Calculate player's historical fusion success rate as percentage."""
        if self.total_fusions == 0:
            return 0.0
        return (self.successful_fusions / self.total_fusions) * 100
    
    def calculate_win_rate(self) -> float:
        """Calculate player's battle win rate as percentage."""
        battles = self.stats.get("battles_fought", 0)
        if battles == 0:
            return 0.0
        wins = self.stats.get("battles_won", 0)
        return (wins / battles) * 100
    
    # ========================================================================
    # NEW METHODS (STAT ALLOCATION SYSTEM)
    # ========================================================================
    
    def calculate_max_stats(self) -> Dict[str, int]:
        """
        Calculate max resource values based on stat allocation.
        
        Formula:
            max_energy = BASE_ENERGY + (points_spent * ENERGY_PER_POINT)
            max_stamina = BASE_STAMINA + (points_spent * STAMINA_PER_POINT)
            max_hp = BASE_HP + (points_spent * HP_PER_POINT)
        
        Returns:
            Dictionary with max_energy, max_stamina, max_hp
            
        Example:
            >>> player.stat_points_spent = {"energy": 5, "stamina": 10, "hp": 2}
            >>> player.calculate_max_stats()
            {"max_energy": 150, "max_stamina": 100, "max_hp": 700}
        """
        spent = self.stat_points_spent
        
        return {
            "max_energy": self.BASE_ENERGY + (spent.get("energy", 0) * self.ENERGY_PER_POINT),
            "max_stamina": self.BASE_STAMINA + (spent.get("stamina", 0) * self.STAMINA_PER_POINT),
            "max_hp": self.BASE_HP + (spent.get("hp", 0) * self.HP_PER_POINT)
        }
    
    def refresh_on_level_up(self) -> None:
        """
        Full resource refresh on level up + grant allocation points.
        
        Called by PlayerService.level_up() after level increase.
        
        Actions:
            1. Calculate new max stats from allocations
            2. Refresh all resources to max (energy, stamina, hp, prayer)
            3. Update max values in database
            4. Grant POINTS_PER_LEVEL allocation points
            5. Update last_level_up timestamp
            6. Increment stats.level_ups counter
        
        RIKI LAW Compliance:
            - Called within transaction context
            - Audit trail via last_level_up timestamp
            - Stats tracking for analytics
        """
        # Calculate max stats based on current allocations
        max_stats = self.calculate_max_stats()
        
        # Full resource refresh
        self.energy = max_stats["max_energy"]
        self.stamina = max_stats["max_stamina"]
        self.hp = max_stats["max_hp"]
        self.prayer_charges = 1  # Always 1 in new system
        
        # Update max values (in case allocations changed)
        self.max_energy = max_stats["max_energy"]
        self.max_stamina = max_stats["max_stamina"]
        self.max_hp = max_stats["max_hp"]
        
        # Grant allocation points
        self.stat_points_available += self.POINTS_PER_LEVEL
        
        # Update audit trail
        self.last_level_up = datetime.utcnow()
        
        # Increment level up counter
        if "level_ups" in self.stats:
            self.stats["level_ups"] += 1
    
    def get_total_stat_points_spent(self) -> int:
        """
        Get total stat points allocated across all stats.
        
        Returns:
            Sum of energy + stamina + hp allocations
            
        Example:
            >>> player.stat_points_spent = {"energy": 5, "stamina": 10, "hp": 2}
            >>> player.get_total_stat_points_spent()
            17
        """
        spent = self.stat_points_spent
        return spent.get("energy", 0) + spent.get("stamina", 0) + spent.get("hp", 0)
    
    def get_stat_allocation_display(self) -> str:
        """
        Format stat allocations for display in embeds.
        
        Returns:
            Formatted string showing allocations and available points
            
        Example:
            >>> player.get_stat_allocation_display()
            "Energy: 5 (+50 max) | Stamina: 10 (+50 max) | HP: 2 (+200 max)\\nAvailable: 3 points"
        """
        spent = self.stat_points_spent
        energy_bonus = spent.get("energy", 0) * self.ENERGY_PER_POINT
        stamina_bonus = spent.get("stamina", 0) * self.STAMINA_PER_POINT
        hp_bonus = spent.get("hp", 0) * self.HP_PER_POINT
        
        return (
            f"Energy: {spent.get('energy', 0)} (+{energy_bonus} max) | "
            f"Stamina: {spent.get('stamina', 0)} (+{stamina_bonus} max) | "
            f"HP: {spent.get('hp', 0)} (+{hp_bonus} max)\n"
            f"Available: {self.stat_points_available} points"
        )
    
    # ========================================================================
    # RESOURCE CAP ENFORCEMENT
    # ========================================================================

    def set_grace_safe(self, amount: int) -> int:
        """
        Safely set grace with cap enforcement.

        IMPORTANT: All grace modifications should go through ResourceService.
        This method is a fallback for cases where direct assignment is unavoidable.

        Args:
            amount: Grace amount to set

        Returns:
            Actual grace value after cap enforcement

        Example:
            >>> actual_grace = player.set_grace_safe(1000000)
            >>> # actual_grace will be 999999 if that's the cap
        """
        from src.core.config.config_manager import ConfigManager
        grace_cap = ConfigManager.get("resource_system.grace_max_cap", 999999)
        self.grace = min(max(0, amount), grace_cap)
        return self.grace

    # ========================================================================
    # REPR
    # ========================================================================

    def __repr__(self) -> str:
        return (
            f"<Player(discord_id={self.discord_id}, "
            f"level={self.level}, power={self.total_power})>"
        )