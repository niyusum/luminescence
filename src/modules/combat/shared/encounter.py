"""
Combat Encounter Model - LES 2025 Compliant
============================================

Purpose
-------
Unified combat state container for all combat types (Ascension, PvP, PvE).
Tracks turn-by-turn progression, HP, teams, and battle logs.

Domain
------
- Combat state management (HP, turn counter, teams)
- Combat log tracking (turn-by-turn events)
- Victory/defeat detection
- Serialization for state persistence

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure data structure - no business logic
✓ Immutable after creation (frozen dataclasses where possible)
✓ Type-safe - complete type hints
✓ Serializable - to_dict() for DB storage
✓ Observable - structured combat log

Design Decisions
----------------
- encounter_id as UUID for distributed systems
- Polymorphic enemy support (MaidenStats or generic EnemyStats)
- Log as append-only list for deterministic replay
- Winner computed from HP, not stored as state
- Supports mid-battle serialization/deserialization

Dependencies
------------
None - pure data structure
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Sequence
from uuid import UUID, uuid4


# ============================================================================
# Enums
# ============================================================================


class EncounterType(str, Enum):
    """Combat encounter types."""

    ASCENSION = "ascension"
    PVP = "pvp"
    PVE = "pve"
    WORLD_BOSS = "world_boss"
    EXPLORATION = "exploration"
    RAID = "raid"


class CombatOutcome(str, Enum):
    """Combat resolution outcomes."""

    VICTORY = "victory"
    DEFEAT = "defeat"
    RETREAT = "retreat"
    ONGOING = "ongoing"


# ============================================================================
# Supporting Data Classes
# ============================================================================


@dataclass(frozen=True)
class MaidenStats:
    """
    Maiden combat stats snapshot.
    
    Immutable snapshot of maiden stats at combat start.
    Used for team composition in elemental/PvP engines.
    """

    maiden_id: int
    maiden_base_id: int
    element: str
    attack: int
    defense: int
    power: int
    tier: int
    quantity: int


@dataclass(frozen=True)
class EnemyStats:
    """
    Generic enemy stats for PvE encounters.
    
    Used for exploration monsters, world bosses, raid bosses.
    """

    enemy_id: str  # "floor_5_boss", "world_boss_1", etc.
    name: str
    element: str
    attack: int
    defense: int
    max_hp: int
    level: Optional[int] = None


@dataclass
class CombatLogEntry:
    """
    Single combat event log entry.
    
    Mutable to allow appending during combat simulation.
    """

    turn: int
    event_type: str  # "player_attack", "enemy_attack", "victory", "defeat"
    actor: str  # "player", "enemy", "monster"
    target: str
    damage: int
    hp_remaining: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# Main Encounter Class
# ============================================================================


@dataclass
class Encounter:
    """
    Unified combat encounter state.
    
    Represents a single combat instance across all combat types.
    Tracks HP, teams, turn progression, and event log.
    
    Attributes:
        encounter_id: Unique identifier
        type: Combat type (ascension/pvp/pve/etc.)
        player_id: Discord ID of primary player
        enemy_id: Optional opponent player ID or enemy identifier
        floor: Optional floor number (for Ascension)
        turn: Current turn number (0-indexed)
        player_hp: Current player HP
        player_max_hp: Maximum player HP
        enemy_hp: Current enemy/monster HP
        enemy_max_hp: Maximum enemy/monster HP
        player_team: List of maiden stats for player
        enemy_team: Optional list of enemy maiden stats (PvP) or None (PvE)
        log: Turn-by-turn combat log
        created_at: Encounter creation timestamp
        resolved_at: Encounter resolution timestamp (None if ongoing)
    """

    encounter_id: UUID
    type: EncounterType
    player_id: int
    
    # Combat state
    turn: int
    player_hp: int
    player_max_hp: int
    enemy_hp: int
    enemy_max_hp: int
    
    # Teams
    player_team: Sequence[MaidenStats]
    enemy_team: Optional[Sequence[MaidenStats | EnemyStats]]
    
    # Optional context
    enemy_id: Optional[int] = None  # For PvP
    floor: Optional[int] = None  # For Ascension
    node_id: Optional[str] = None  # For Exploration
    
    # Log
    log: List[CombatLogEntry] = field(default_factory=list)
    
    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None

    # ========================================================================
    # Properties
    # ========================================================================

    @property
    def is_over(self) -> bool:
        """Check if combat has concluded."""
        return self.player_hp <= 0 or self.enemy_hp <= 0

    @property
    def winner(self) -> Optional[Literal["player", "enemy"]]:
        """
        Determine winner based on HP.
        
        Returns:
            "player" if player won
            "enemy" if enemy won
            None if combat ongoing
        """
        if not self.is_over:
            return None
        
        if self.player_hp <= 0 and self.enemy_hp <= 0:
            # Both died somehow - player loses
            return "enemy"
        
        if self.player_hp > 0:
            return "player"
        
        return "enemy"

    @property
    def outcome(self) -> CombatOutcome:
        """Get combat outcome enum."""
        if not self.is_over:
            return CombatOutcome.ONGOING
        
        if self.winner == "player":
            return CombatOutcome.VICTORY
        
        return CombatOutcome.DEFEAT

    # ========================================================================
    # Methods
    # ========================================================================

    def add_log(
        self,
        event_type: str,
        actor: str,
        target: str,
        damage: int,
        hp_remaining: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Add entry to combat log.
        
        Args:
            event_type: Type of event (attack, ability, status, etc.)
            actor: Who performed the action
            target: Who received the action
            damage: Damage dealt (0 for non-damaging events)
            hp_remaining: Target's HP after event
            metadata: Additional context data
        """
        entry = CombatLogEntry(
            turn=self.turn,
            event_type=event_type,
            actor=actor,
            target=target,
            damage=damage,
            hp_remaining=hp_remaining,
            metadata=metadata or {},
        )
        self.log.append(entry)

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize encounter to dictionary for DB storage.
        
        Returns:
            Dictionary with all encounter data
        """
        return {
            "encounter_id": str(self.encounter_id),
            "type": self.type.value,
            "player_id": self.player_id,
            "enemy_id": self.enemy_id,
            "floor": self.floor,
            "node_id": self.node_id,
            "turn": self.turn,
            "player_hp": self.player_hp,
            "player_max_hp": self.player_max_hp,
            "enemy_hp": self.enemy_hp,
            "enemy_max_hp": self.enemy_max_hp,
            "player_team": [
                {
                    "maiden_id": m.maiden_id,
                    "maiden_base_id": m.maiden_base_id,
                    "element": m.element,
                    "attack": m.attack,
                    "defense": m.defense,
                    "power": m.power,
                    "tier": m.tier,
                    "quantity": m.quantity,
                }
                for m in self.player_team
            ],
            "enemy_team": (
                [
                    {
                        "maiden_id": e.maiden_id if isinstance(e, MaidenStats) else None,
                        "enemy_id": e.enemy_id if isinstance(e, EnemyStats) else None,
                        "element": e.element,
                        "attack": e.attack,
                        "defense": e.defense,
                        "name": e.name if isinstance(e, EnemyStats) else None,
                    }
                    for e in self.enemy_team
                ]
                if self.enemy_team
                else None
            ),
            "log": [
                {
                    "turn": entry.turn,
                    "event_type": entry.event_type,
                    "actor": entry.actor,
                    "target": entry.target,
                    "damage": entry.damage,
                    "hp_remaining": entry.hp_remaining,
                    "metadata": entry.metadata,
                    "timestamp": entry.timestamp.isoformat(),
                }
                for entry in self.log
            ],
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Encounter:
        """
        Deserialize encounter from dictionary.
        
        Args:
            data: Dictionary with encounter data
        
        Returns:
            Reconstructed Encounter instance
        """
        # Reconstruct player team
        player_team = [
            MaidenStats(
                maiden_id=m["maiden_id"],
                maiden_base_id=m["maiden_base_id"],
                element=m["element"],
                attack=m["attack"],
                defense=m["defense"],
                power=m["power"],
                tier=m["tier"],
                quantity=m["quantity"],
            )
            for m in data["player_team"]
        ]

        # Reconstruct enemy team (polymorphic)
        enemy_team = None
        if data.get("enemy_team"):
            enemy_team = []
            for e in data["enemy_team"]:
                if e.get("maiden_id"):
                    # It's a MaidenStats
                    enemy_team.append(
                        MaidenStats(
                            maiden_id=e["maiden_id"],
                            maiden_base_id=e.get("maiden_base_id", 0),
                            element=e["element"],
                            attack=e["attack"],
                            defense=e["defense"],
                            power=e.get("power", e["attack"] + e["defense"]),
                            tier=e.get("tier", 1),
                            quantity=e.get("quantity", 1),
                        )
                    )
                else:
                    # It's an EnemyStats
                    enemy_team.append(
                        EnemyStats(
                            enemy_id=e.get("enemy_id", "unknown"),
                            name=e.get("name", "Unknown Enemy"),
                            element=e["element"],
                            attack=e["attack"],
                            defense=e["defense"],
                            max_hp=e.get("max_hp", 1000),
                            level=e.get("level"),
                        )
                    )

        # Reconstruct log
        log = [
            CombatLogEntry(
                turn=entry["turn"],
                event_type=entry["event_type"],
                actor=entry["actor"],
                target=entry["target"],
                damage=entry["damage"],
                hp_remaining=entry["hp_remaining"],
                metadata=entry.get("metadata", {}),
                timestamp=datetime.fromisoformat(entry["timestamp"]),
            )
            for entry in data.get("log", [])
        ]

        return cls(
            encounter_id=UUID(data["encounter_id"]),
            type=EncounterType(data["type"]),
            player_id=data["player_id"],
            enemy_id=data.get("enemy_id"),
            floor=data.get("floor"),
            node_id=data.get("node_id"),
            turn=data["turn"],
            player_hp=data["player_hp"],
            player_max_hp=data["player_max_hp"],
            enemy_hp=data["enemy_hp"],
            enemy_max_hp=data["enemy_max_hp"],
            player_team=player_team,
            enemy_team=enemy_team,
            log=log,
            created_at=datetime.fromisoformat(data["created_at"]),
            resolved_at=(
                datetime.fromisoformat(data["resolved_at"])
                if data.get("resolved_at")
                else None
            ),
        )