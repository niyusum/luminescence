"""
Aggregate Power Combat Engine - LES 2025 Compliant
===================================================

Purpose
-------
Total power combat for exploration, world bosses, raids, and dungeon guardians.
Uses player's total_attack and total_defense against massive HP pools.

Domain
------
- Aggregate power calculation (all maidens contribute)
- Boss HP scaling (can reach billions)
- Multi-hit attacks (configurable hits per turn)
- Configurable retaliation (bosses can counter-attack)
- Leader skill application to aggregate stats

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord, no DB
✓ Config-driven - hits per attack, scaling from config
✓ Deterministic - same inputs = same outputs
✓ Observable - structured logging for all events
✓ Dependency injection - all services passed in
✓ Type-safe - complete type hints

Design Decisions
----------------
- Uses player's total_attack/total_defense (all maidens)
- Boss HP can be arbitrarily large (world boss, raids)
- Multi-hit support (hits_per_attack config)
- Optional boss retaliation (exploration: yes, world boss: optional)
- Victory: Boss HP reaches 0
- Defeat: Player HP reaches 0 (if retaliation enabled)

Dependencies
------------
- PowerCalculationService: For total power
- LeaderSkillService: For leader bonuses
- ElementResolver: For element advantages (optional)
- CombatFormulas: For damage calculation
- HPScalingCalculator: For player HP damage
- ConfigManager: For PvE rules
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Tuple

from src.core.logging.logger import get_logger
from src.core.validation.input_validator import InputValidator
from src.modules.combat.shared.encounter import Encounter, EncounterType, EnemyStats

if TYPE_CHECKING:
    from src.core.config.manager import ConfigManager
    from src.modules.combat.shared.elements import ElementResolver
    from src.modules.combat.shared.formulas import CombatFormulas
    from src.modules.combat.shared.hp_scaling import HPScalingCalculator
    from src.modules.maiden.leader_skill_service import LeaderSkillService
    from src.modules.maiden.power_service import PowerCalculationService

logger = get_logger(__name__)


# ============================================================================
# AggregateEngine
# ============================================================================


class AggregateEngine:
    """
    Aggregate power combat engine for PvE content.
    
    Handles exploration monsters, world bosses, raid bosses, dungeon guardians.
    Uses total_attack/total_defense against large HP pools.
    
    Public Methods
    --------------
    - build_encounter(player_id, enemy_stats, enable_retaliation) -> Create encounter
    - calculate_player_stats(player_id) -> Get total power with leader bonus
    - calculate_player_damage(total_atk, boss_def, boss_elem) -> Damage to boss
    - calculate_boss_retaliation(boss_atk, total_def) -> Damage to player
    - simulate_turn(encounter) -> Execute one combat turn
    - simulate_full_combat(encounter) -> Run combat to completion
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        power_service: PowerCalculationService,
        leader_service: LeaderSkillService,
        element_resolver: ElementResolver,
        combat_formulas: CombatFormulas,
        hp_scaling: HPScalingCalculator,
    ) -> None:
        """
        Initialize aggregate power engine.
        
        Args:
            config_manager: Application configuration
            power_service: Power calculation service
            leader_service: Leader skill service
            element_resolver: Element advantage resolver
            combat_formulas: Damage calculation formulas
            hp_scaling: HP scaling calculator
        """
        self._config = config_manager
        self._power = power_service
        self._leader = leader_service
        self._elements = element_resolver
        self._formulas = combat_formulas
        self._hp_scaling = hp_scaling
        self._logger = logger

        # Load PvE config
        self._hits_per_attack = int(
            self._config.get("combat.pve.hits_per_attack", default=1)
        )
        self._defense_effectiveness = float(
            self._config.get("combat.pve.defense_effectiveness", default=0.7)
        )
        self._player_base_hp = int(
            self._config.get("combat.pve.exploration.player_base_hp", default=1000)
        )
        self._player_hp_per_level = int(
            self._config.get("combat.pve.exploration.scaling_per_level", default=15)
        )

        self._logger.info(
            "AggregateEngine initialized",
            extra={
                "hits_per_attack": self._hits_per_attack,
                "defense_effectiveness": self._defense_effectiveness,
            },
        )

    # ========================================================================
    # PUBLIC API - Encounter Creation
    # ========================================================================

    async def build_encounter(
        self,
        player_id: int,
        enemy_stats: EnemyStats,
        enable_retaliation: bool = True,
        player_level: int = 1,
    ) -> Encounter:
        """
        Create PvE encounter with aggregate power.
        
        Args:
            player_id: Discord ID
            enemy_stats: Boss/monster stats
            enable_retaliation: Whether boss counter-attacks
            player_level: Player level for HP calculation
        
        Returns:
            Encounter ready for simulation
        """
        from uuid import uuid4

        player_id = InputValidator.validate_discord_id(player_id)

        # Calculate player HP
        player_max_hp = self._player_base_hp + (player_level * self._player_hp_per_level)

        # Get player's total power
        total_atk, total_def, total_power = await self._power.get_player_total_power(
            player_id
        )

        # Apply leader modifiers
        leader_mods = await self._leader.get_leader_modifiers(player_id)
        modified_atk = int(total_atk * leader_mods.atk_multiplier)
        modified_def = int(total_def * leader_mods.def_multiplier)

        # Create encounter
        encounter = Encounter(
            encounter_id=uuid4(),
            type=EncounterType.PVE,
            player_id=player_id,
            turn=0,
            player_hp=player_max_hp,
            player_max_hp=player_max_hp,
            enemy_hp=enemy_stats.max_hp,
            enemy_max_hp=enemy_stats.max_hp,
            player_team=[],  # No individual maidens tracked
            enemy_team=[enemy_stats],
        )

        self._logger.info(
            "PvE encounter created",
            extra={
                "encounter_id": str(encounter.encounter_id),
                "player_id": player_id,
                "enemy_id": enemy_stats.enemy_id,
                "player_atk": modified_atk,
                "player_def": modified_def,
                "enemy_hp": enemy_stats.max_hp,
                "retaliation": enable_retaliation,
            },
        )

        return encounter

    # ========================================================================
    # PUBLIC API - Combat Calculations
    # ========================================================================

    async def calculate_player_stats(self, player_id: int) -> Tuple[int, int]:
        """
        Calculate total ATK/DEF with leader bonuses.
        
        Args:
            player_id: Discord ID
        
        Returns:
            Tuple of (total_atk, total_def) with leader bonuses
        """
        total_atk, total_def, _ = await self._power.get_player_total_power(player_id)

        leader_mods = await self._leader.get_leader_modifiers(player_id)
        modified_atk = int(total_atk * leader_mods.atk_multiplier)
        modified_def = int(total_def * leader_mods.def_multiplier)

        return modified_atk, modified_def

    def calculate_player_damage(
        self, total_atk: int, boss_def: int, boss_elem: str = "neutral"
    ) -> int:
        """
        Calculate damage player deals to boss.
        
        Args:
            total_atk: Player's total attack (with leader bonus)
            boss_def: Boss defense
            boss_elem: Boss element (for future element advantage)
        
        Returns:
            Total damage (includes multi-hit multiplier)
        """
        # Apply defense effectiveness
        effective_def = int(boss_def * self._defense_effectiveness)
        raw_damage = max(total_atk - effective_def, 1)

        # Apply multi-hit
        total_damage = raw_damage * self._hits_per_attack

        self._logger.debug(
            "Player damage calculated",
            extra={
                "total_atk": total_atk,
                "boss_def": boss_def,
                "effective_def": effective_def,
                "raw_damage": raw_damage,
                "hits": self._hits_per_attack,
                "total_damage": total_damage,
            },
        )

        return total_damage

    def calculate_boss_retaliation(self, boss_atk: int, total_def: int) -> int:
        """
        Calculate damage boss deals to player HP.
        
        Args:
            boss_atk: Boss attack
            total_def: Player's total defense (with leader bonus)
        
        Returns:
            Damage to player HP pool
        """
        # Calculate unit damage
        effective_def = int(total_def * self._defense_effectiveness)
        raw_unit_damage = max(boss_atk - effective_def, 1)

        # Scale to player HP
        player_damage = self._hp_scaling.convert_unit_damage_to_player_hp(
            raw_unit_damage, combat_type="pve"
        )

        self._logger.debug(
            "Boss retaliation calculated",
            extra={
                "boss_atk": boss_atk,
                "total_def": total_def,
                "raw_unit_damage": raw_unit_damage,
                "player_damage": player_damage,
            },
        )

        return player_damage

    # ========================================================================
    # PUBLIC API - Combat Simulation
    # ========================================================================

    async def simulate_turn(
        self, encounter: Encounter, enable_retaliation: bool = True
    ) -> Encounter:
        """
        Simulate one combat turn (player attacks, optional boss retaliation).
        
        Args:
            encounter: Current encounter state
            enable_retaliation: Whether boss counter-attacks
        
        Returns:
            Updated encounter after turn
        """
        if encounter.is_over:
            return encounter

        # Get boss stats
        if not encounter.enemy_team or len(encounter.enemy_team) == 0:
            self._logger.error(
                "No enemy in encounter",
                extra={"encounter_id": str(encounter.encounter_id)},
            )
            return encounter

        boss = encounter.enemy_team[0]
        if not isinstance(boss, EnemyStats):
            self._logger.error(
                "Enemy is not EnemyStats",
                extra={"encounter_id": str(encounter.encounter_id)},
            )
            return encounter

        # Calculate player stats
        total_atk, total_def = await self.calculate_player_stats(encounter.player_id)

        # Player attacks boss
        player_damage = self.calculate_player_damage(
            total_atk, boss.defense, boss.element
        )
        encounter.enemy_hp = max(encounter.enemy_hp - player_damage, 0)

        encounter.add_log(
            event_type="player_attack",
            actor="player",
            target="boss",
            damage=player_damage,
            hp_remaining=encounter.enemy_hp,
            metadata={
                "total_atk": total_atk,
                "boss_def": boss.defense,
                "hits": self._hits_per_attack,
            },
        )

        self._logger.info(
            "Player attacked boss",
            extra={
                "turn": encounter.turn,
                "damage": player_damage,
                "boss_hp": encounter.enemy_hp,
            },
        )

        # Check if boss defeated
        if encounter.enemy_hp <= 0:
            encounter.add_log(
                event_type="victory",
                actor="player",
                target="boss",
                damage=0,
                hp_remaining=0,
                metadata={"reason": "boss_defeated"},
            )
            self._logger.info("Boss defeated", extra={"turn": encounter.turn})
            encounter.turn += 1
            return encounter

        # Boss retaliation (if enabled)
        if enable_retaliation:
            boss_damage = self.calculate_boss_retaliation(boss.attack, total_def)
            encounter.player_hp = max(encounter.player_hp - boss_damage, 0)

            encounter.add_log(
                event_type="boss_attack",
                actor="boss",
                target="player",
                damage=boss_damage,
                hp_remaining=encounter.player_hp,
                metadata={"boss_atk": boss.attack, "total_def": total_def},
            )

            self._logger.info(
                "Boss retaliated",
                extra={
                    "turn": encounter.turn,
                    "damage": boss_damage,
                    "player_hp": encounter.player_hp,
                },
            )

            # Check if player defeated
            if encounter.player_hp <= 0:
                encounter.add_log(
                    event_type="defeat",
                    actor="boss",
                    target="player",
                    damage=0,
                    hp_remaining=0,
                    metadata={"reason": "player_defeated"},
                )
                self._logger.info("Player defeated", extra={"turn": encounter.turn})

        # Increment turn
        encounter.turn += 1

        return encounter

    async def simulate_full_combat(
        self,
        encounter: Encounter,
        enable_retaliation: bool = True,
        max_turns: int = 1000,
    ) -> Encounter:
        """
        Simulate PvE combat to completion.
        
        Args:
            encounter: Starting encounter state
            enable_retaliation: Whether boss counter-attacks
            max_turns: Maximum turns before forced end
        
        Returns:
            Final encounter state
        """
        self._logger.info(
            "Starting PvE combat simulation",
            extra={
                "encounter_id": str(encounter.encounter_id),
                "player_id": encounter.player_id,
                "retaliation": enable_retaliation,
            },
        )

        while not encounter.is_over and encounter.turn < max_turns:
            encounter = await self.simulate_turn(encounter, enable_retaliation)

        if encounter.turn >= max_turns:
            self._logger.warning(
                "PvE combat reached max turns",
                extra={"encounter_id": str(encounter.encounter_id)},
            )

        self._logger.info(
            "PvE combat complete",
            extra={
                "encounter_id": str(encounter.encounter_id),
                "winner": encounter.winner,
                "turns": encounter.turn,
            },
        )

        return encounter