"""
Elemental Team Combat Engine - LES 2025 Compliant
==================================================

Purpose
-------
Ascension tower combat using best-of-each-element 6-maiden teams.
Selects strongest maiden per element, applies leader bonuses, simulates
turn-based combat against floor monsters.

Domain
------
- Element-based team composition (Fire/Water/Earth/Air/Light/Dark)
- Leader skill application to team stats
- Turn-based combat simulation
- Monster scaling per floor
- Player HP pool management

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord, no DB
✓ Config-driven - monster stats, scaling from config
✓ Deterministic - same inputs = same outputs
✓ Observable - structured logging for all events
✓ Dependency injection - all services passed in
✓ Type-safe - complete type hints

Design Decisions
----------------
- Team size: Up to 6 maidens (one per element)
- Selection: Strongest maiden of each element by power
- Leader bonus: Applied to entire team ATK/DEF
- Turn order: Player attacks first, then monster
- Victory: Monster HP reaches 0
- Defeat: Player HP reaches 0

Dependencies
------------
- PowerCalculationService: For maiden stats
- LeaderSkillService: For leader bonuses
- ElementResolver: For element advantages
- CombatFormulas: For damage calculation
- HPScalingCalculator: For player HP damage
- ConfigManager: For monster stats and scaling
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Tuple

from src.core.logging.logger import get_logger
from src.core.validation.input_validator import InputValidator
from src.modules.combat.shared.encounter import (
    Encounter,
    EncounterType,
    EnemyStats,
    MaidenStats,
)

if TYPE_CHECKING:
    from src.core.config.manager import ConfigManager
    from src.modules.combat.shared.elements import ElementResolver
    from src.modules.combat.shared.formulas import CombatFormulas, DamageInput
    from src.modules.combat.shared.hp_scaling import HPScalingCalculator
    from src.modules.maiden.leader_skill_service import LeaderSkillService
    from src.modules.maiden.power_service import PowerCalculationService

logger = get_logger(__name__)


# ============================================================================
# ElementalTeamEngine
# ============================================================================


class ElementalTeamEngine:
    """
    Ascension tower combat engine using elemental teams.
    
    Builds 6-maiden teams (best per element), applies leader bonuses,
    simulates turn-based combat against scaled floor monsters.
    
    Public Methods
    --------------
    - build_player_team(player_id) -> Build elemental team
    - build_encounter(player_id, floor) -> Create encounter state
    - calculate_team_stats(team, leader_mods) -> Aggregate stats
    - calculate_player_damage(team_atk, monster_def, monster_elem) -> Damage to monster
    - calculate_monster_damage(monster_atk, team_def) -> Damage to player
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
        Initialize elemental team engine.
        
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

        # Load config
        self._player_hp_base = int(
            self._config.get("combat.ascension.player_hp_base", default=1000)
        )
        self._player_hp_per_level = int(
            self._config.get("combat.ascension.player_hp_per_level", default=25)
        )
        self._defense_effectiveness = float(
            self._config.get("combat.ascension.defense_effectiveness", default=0.7)
        )

        # Monster scaling
        self._monster_base_atk = int(
            self._config.get("combat.ascension.monster.base_attack", default=250)
        )
        self._monster_atk_scaling = float(
            self._config.get("combat.ascension.monster.scaling_per_floor", default=1.18)
        )
        self._monster_base_def = int(
            self._config.get("combat.ascension.monster.base_defense", default=100)
        )
        self._monster_def_scaling = float(
            self._config.get("combat.ascension.monster.defense_scaling", default=1.12)
        )
        self._monster_base_hp = int(
            self._config.get("combat.ascension.monster.base_hp", default=1000)
        )
        self._monster_hp_scaling = float(
            self._config.get("combat.ascension.monster.hp_scaling", default=1.20)
        )

        self._logger.info(
            "ElementalTeamEngine initialized",
            extra={
                "player_hp_base": self._player_hp_base,
                "monster_base_atk": self._monster_base_atk,
                "monster_atk_scaling": self._monster_atk_scaling,
            },
        )

    # ========================================================================
    # PUBLIC API - Team Building
    # ========================================================================

    async def build_player_team(self, player_id: int) -> List[MaidenStats]:
        """
        Build elemental team: best maiden per element (up to 6).
        
        Selects strongest maiden of each element by power.
        Elements considered: fire, water, earth, air, light, dark.
        
        Args:
            player_id: Discord ID
        
        Returns:
            List of MaidenStats (up to 6 maidens)
        
        Example:
            >>> team = await engine.build_player_team(123)
            >>> print([m.element for m in team])
            ['fire', 'water', 'earth', 'light', 'dark']
        """
        player_id = InputValidator.validate_discord_id(player_id)

        self._logger.debug(
            "Building elemental team",
            extra={"player_id": player_id, "operation": "build_player_team"},
        )

        # Get full power breakdown
        breakdown = await self._power.get_power_breakdown(player_id, top_n=100)

        # Group by element and select strongest per element
        element_best: Dict[str, MaidenStats] = {}
        target_elements = {"fire", "water", "earth", "air", "light", "dark"}

        for maiden_data in breakdown.top_contributors:
            element = maiden_data["element"].lower()

            if element not in target_elements:
                continue

            if element in element_best:
                # Already have a maiden for this element
                continue

            # Create MaidenStats
            maiden_stats = MaidenStats(
                maiden_id=maiden_data["maiden_id"],
                maiden_base_id=maiden_data["maiden_base_id"],
                element=element,
                attack=maiden_data["attack"],
                defense=maiden_data["defense"],
                power=maiden_data["power"],
                tier=maiden_data["tier"],
                quantity=maiden_data["quantity"],
            )

            element_best[element] = maiden_stats

        team = list(element_best.values())

        self._logger.info(
            "Elemental team built",
            extra={
                "player_id": player_id,
                "team_size": len(team),
                "elements": [m.element for m in team],
                "total_power": sum(m.power for m in team),
            },
        )

        return team

    # ========================================================================
    # PUBLIC API - Encounter Creation
    # ========================================================================

    async def build_encounter(self, player_id: int, floor: int) -> Encounter:
        """
        Create Ascension encounter with team and monster.
        
        Args:
            player_id: Discord ID
            floor: Ascension floor number
        
        Returns:
            Encounter ready for simulation
        """
        from uuid import uuid4

        player_id = InputValidator.validate_discord_id(player_id)
        floor = InputValidator.validate_positive_integer(floor, "floor")

        # Build player team
        team = await self.build_player_team(player_id)

        # Calculate player HP (TODO: get from player level)
        player_level = 1  # Placeholder - should come from PlayerCore
        player_max_hp = self._player_hp_base + (player_level * self._player_hp_per_level)

        # Calculate monster stats
        monster_atk = int(self._monster_base_atk * (self._monster_atk_scaling ** (floor - 1)))
        monster_def = int(self._monster_base_def * (self._monster_def_scaling ** (floor - 1)))
        monster_hp = int(self._monster_base_hp * (self._monster_hp_scaling ** (floor - 1)))

        # Create monster enemy
        monster = EnemyStats(
            enemy_id=f"ascension_floor_{floor}",
            name=f"Floor {floor} Guardian",
            element="neutral",  # TODO: Could have element per floor
            attack=monster_atk,
            defense=monster_def,
            max_hp=monster_hp,
            level=floor,
        )

        encounter = Encounter(
            encounter_id=uuid4(),
            type=EncounterType.ASCENSION,
            player_id=player_id,
            floor=floor,
            turn=0,
            player_hp=player_max_hp,
            player_max_hp=player_max_hp,
            enemy_hp=monster_hp,
            enemy_max_hp=monster_hp,
            player_team=team,
            enemy_team=[monster],
        )

        self._logger.info(
            "Ascension encounter created",
            extra={
                "encounter_id": str(encounter.encounter_id),
                "player_id": player_id,
                "floor": floor,
                "team_size": len(team),
                "monster_hp": monster_hp,
                "monster_atk": monster_atk,
            },
        )

        return encounter

    # ========================================================================
    # PUBLIC API - Combat Calculations
    # ========================================================================

    async def calculate_team_stats(
        self, team: List[MaidenStats], player_id: int
    ) -> Tuple[int, int]:
        """
        Calculate aggregate team ATK/DEF with leader bonuses.
        
        Args:
            team: List of maiden stats
            player_id: For fetching leader modifiers
        
        Returns:
            Tuple of (total_atk, total_def) with leader bonuses applied
        """
        # Base stats
        base_atk = sum(m.attack for m in team)
        base_def = sum(m.defense for m in team)

        # Apply leader modifiers
        leader_mods = await self._leader.get_leader_modifiers(player_id)
        total_atk = int(base_atk * leader_mods.atk_multiplier)
        total_def = int(base_def * leader_mods.def_multiplier)

        self._logger.debug(
            "Team stats calculated",
            extra={
                "base_atk": base_atk,
                "base_def": base_def,
                "leader_atk_mult": leader_mods.atk_multiplier,
                "leader_def_mult": leader_mods.def_multiplier,
                "total_atk": total_atk,
                "total_def": total_def,
            },
        )

        return total_atk, total_def

    def calculate_player_damage(
        self, team_atk: int, monster_def: int, monster_elem: str = "neutral"
    ) -> int:
        """
        Calculate damage player team deals to monster.
        
        Uses aggregate ATK vs monster DEF, no element advantage
        (team has mixed elements).
        
        Args:
            team_atk: Total team attack
            monster_def: Monster defense
            monster_elem: Monster element (for future element logic)
        
        Returns:
            Damage dealt to monster
        """
        # Apply defense effectiveness
        effective_def = int(monster_def * self._defense_effectiveness)
        raw_damage = max(team_atk - effective_def, 1)

        # Could apply element logic here if needed
        # For now, no element advantage (mixed team)

        self._logger.debug(
            "Player damage calculated",
            extra={
                "team_atk": team_atk,
                "monster_def": monster_def,
                "effective_def": effective_def,
                "damage": raw_damage,
            },
        )

        return raw_damage

    def calculate_monster_damage(self, monster_atk: int, team_def: int) -> int:
        """
        Calculate damage monster deals to player HP.
        
        Converts unit damage to player HP damage using scaling.
        
        Args:
            monster_atk: Monster attack
            team_def: Total team defense
        
        Returns:
            Damage to player HP pool
        """
        # Calculate unit damage
        effective_def = int(team_def * self._defense_effectiveness)
        raw_unit_damage = max(monster_atk - effective_def, 1)

        # Scale to player HP
        player_damage = self._hp_scaling.convert_unit_damage_to_player_hp(
            raw_unit_damage, combat_type="ascension"
        )

        self._logger.debug(
            "Monster damage calculated",
            extra={
                "monster_atk": monster_atk,
                "team_def": team_def,
                "raw_unit_damage": raw_unit_damage,
                "player_damage": player_damage,
            },
        )

        return player_damage

    # ========================================================================
    # PUBLIC API - Combat Simulation
    # ========================================================================

    async def simulate_turn(self, encounter: Encounter) -> Encounter:
        """
        Simulate one combat turn (player attacks, then monster).
        
        Modifies encounter in-place and returns it.
        
        Args:
            encounter: Current encounter state
        
        Returns:
            Updated encounter after turn
        """
        if encounter.is_over:
            return encounter

        # Get monster from enemy_team
        if not encounter.enemy_team or len(encounter.enemy_team) == 0:
            self._logger.error("No enemy in encounter", extra={"encounter_id": str(encounter.encounter_id)})
            return encounter

        monster = encounter.enemy_team[0]
        if not isinstance(monster, EnemyStats):
            self._logger.error("Enemy is not EnemyStats", extra={"encounter_id": str(encounter.encounter_id)})
            return encounter

        # Calculate team stats
        team_atk, team_def = await self.calculate_team_stats(
            encounter.player_team, encounter.player_id
        )

        # Player attacks monster
        player_damage = self.calculate_player_damage(
            team_atk, monster.defense, monster.element
        )
        encounter.enemy_hp = max(encounter.enemy_hp - player_damage, 0)

        encounter.add_log(
            event_type="player_attack",
            actor="player",
            target="monster",
            damage=player_damage,
            hp_remaining=encounter.enemy_hp,
            metadata={"team_atk": team_atk, "monster_def": monster.defense},
        )

        self._logger.info(
            "Player attacked monster",
            extra={
                "turn": encounter.turn,
                "damage": player_damage,
                "monster_hp": encounter.enemy_hp,
            },
        )

        # Check if monster died
        if encounter.enemy_hp <= 0:
            encounter.add_log(
                event_type="victory",
                actor="player",
                target="monster",
                damage=0,
                hp_remaining=0,
                metadata={"reason": "monster_defeated"},
            )
            self._logger.info("Monster defeated", extra={"turn": encounter.turn})
            return encounter

        # Monster attacks player
        monster_damage = self.calculate_monster_damage(monster.attack, team_def)
        encounter.player_hp = max(encounter.player_hp - monster_damage, 0)

        encounter.add_log(
            event_type="monster_attack",
            actor="monster",
            target="player",
            damage=monster_damage,
            hp_remaining=encounter.player_hp,
            metadata={"monster_atk": monster.attack, "team_def": team_def},
        )

        self._logger.info(
            "Monster attacked player",
            extra={
                "turn": encounter.turn,
                "damage": monster_damage,
                "player_hp": encounter.player_hp,
            },
        )

        # Check if player died
        if encounter.player_hp <= 0:
            encounter.add_log(
                event_type="defeat",
                actor="monster",
                target="player",
                damage=0,
                hp_remaining=0,
                metadata={"reason": "player_defeated"},
            )
            self._logger.info("Player defeated", extra={"turn": encounter.turn})

        # Increment turn
        encounter.turn += 1

        return encounter

    async def simulate_full_combat(self, encounter: Encounter, max_turns: int = 100) -> Encounter:
        """
        Simulate combat to completion.
        
        Args:
            encounter: Starting encounter state
            max_turns: Maximum turns before forced draw (safety)
        
        Returns:
            Final encounter state
        """
        self._logger.info(
            "Starting full combat simulation",
            extra={
                "encounter_id": str(encounter.encounter_id),
                "player_hp": encounter.player_hp,
                "enemy_hp": encounter.enemy_hp,
            },
        )

        while not encounter.is_over and encounter.turn < max_turns:
            encounter = await self.simulate_turn(encounter)

        if encounter.turn >= max_turns:
            self._logger.warning(
                "Combat reached max turns",
                extra={"encounter_id": str(encounter.encounter_id), "max_turns": max_turns},
            )

        self._logger.info(
            "Combat simulation complete",
            extra={
                "encounter_id": str(encounter.encounter_id),
                "winner": encounter.winner,
                "turns": encounter.turn,
                "final_player_hp": encounter.player_hp,
                "final_enemy_hp": encounter.enemy_hp,
            },
        )

        return encounter