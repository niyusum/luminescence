"""
Infinite tower climbing system with turn-based strategic combat.

LUMEN LAW Compliance: Article III (Service Layer), Article II (Audit Trails)
- Pure business logic with no Discord dependencies
- Uses CombatService for strategic power calculations (best 6 maidens)
- Turn-based combat with boss retaliation and player HP
- Comprehensive transaction logging

Features:
- Strategic squad combat (best 6 maidens, one per element)
- Turn-based with boss counter-attacks
- Player HP management and defeat conditions
- Critical gauge and momentum systems
- Token rewards (bronze/silver/gold/platinum/diamond)
- Milestone bosses with special mechanics

Combat Flow:
1. Player attacks (x1, x3, x10)
2. Boss takes damage
3. If boss alive: boss counter-attacks (player HP reduced)
4. If boss defeated: victory rewards
5. If player HP = 0: defeat (no rewards)
"""

from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import secrets
import math

from src.database.models.core.player import Player
from src.database.models.progression.ascension_progress import AscensionProgress
from src.core.config.config_manager import ConfigManager
from src.modules.resource.service import ResourceService
from src.modules.combat.service import CombatService
from src.core.infra.transaction_logger import TransactionLogger
from src.core.exceptions import InsufficientResourcesError, InvalidOperationError
from src.core.logging.logger import get_logger, LogContext

logger = get_logger(__name__)


class AscensionService:
    """
    Strategic tower climbing system (LUMEN LAW Article III).
    
    Uses best 6 maidens (one per element) for challenging turn-based combat.
    """
    
    # ========================================================================
    # PROGRESS TRACKING
    # ========================================================================
    
    @staticmethod
    async def get_or_create_progress(
        session: AsyncSession,
        player_id: int
    ) -> AscensionProgress:
        """
        Get existing ascension progress or create new record.
        
        Args:
            session: Database session
            player_id: Discord ID
        
        Returns:
            AscensionProgress record
        """
        result = await session.execute(
            select(AscensionProgress).where(
                AscensionProgress.player_id == player_id
            )
        )
        progress = result.scalar_one_or_none()
        
        if not progress:
            progress = AscensionProgress(player_id=player_id)
            session.add(progress)
            await session.flush()
            logger.info(f"Created ascension progress for player {player_id}")
        
        return progress
    
    # ========================================================================
    # FLOOR GENERATION
    # ========================================================================
    
    @staticmethod
    def generate_floor_monster(floor: int) -> Dict[str, Any]:
        """
        Generate monster for specific floor.
        
        Loads monster data from config with scaled stats.
        
        Args:
            floor: Floor number (1+)
        
        Returns:
            {
                "name": "Guardian Sentinel",
                "atk": 1000,
                "def": 30000,  # HP
                "element": "tempest",
                "floor": 10,
                "is_milestone": False
            }
        """
        # Check for milestone boss
        milestone_config = ConfigManager.get(f"ascension_monsters.milestone_bosses.{floor}")
        if milestone_config:
            return {
                "name": milestone_config["name"],
                "atk": milestone_config["atk"],
                "def": milestone_config["def"],
                "hp": milestone_config["def"],  # DEF = HP
                "max_hp": milestone_config["def"],
                "element": milestone_config["element"],
                "floor": floor,
                "is_milestone": True,
                "special_mechanics": milestone_config.get("special_mechanics", [])
            }
        
        # Determine floor range
        if floor <= 10:
            range_key = "1_10"
        elif floor <= 25:
            range_key = "11_25"
        elif floor <= 50:
            range_key = "26_50"
        elif floor <= 100:
            range_key = "51_100"
        else:
            range_key = "101_plus"
        
        # Get monster pool for range
        # LUMEN LAW I.6 - YAML is source of truth
        monster_pool = ConfigManager.get(f"ascension_monsters.floor_ranges.{range_key}.monsters")
        if not monster_pool:
            # Fallback
            return AscensionService._generate_fallback_monster(floor)
        
        # Weighted selection
        total_weight = sum(m.get("weight", 100) for m in monster_pool)
        roll = secrets.SystemRandom().random() * total_weight
        
        cumulative = 0
        selected = monster_pool[0]
        for monster in monster_pool:
            cumulative += monster.get("weight", 100)
            if roll <= cumulative:
                selected = monster
                break
        
        # Get scaling
        # LUMEN LAW I.6 - YAML is source of truth
        scaling = ConfigManager.get(f"ascension_monsters.floor_ranges.{range_key}.scaling")
        atk_per_floor = scaling.get("atk_per_floor", 1.08)
        def_per_floor = scaling.get("def_per_floor", 1.10)
        
        # Calculate floor offset within range
        range_start = int(range_key.split("_")[0])
        floor_offset = floor - range_start
        
        # Scale stats
        scaled_atk = int(selected["atk_base"] * (atk_per_floor ** floor_offset))
        scaled_def = int(selected["def_base"] * (def_per_floor ** floor_offset))
        
        return {
            "name": selected["name"],
            "atk": scaled_atk,
            "def": scaled_def,
            "hp": scaled_def,
            "max_hp": scaled_def,
            "element": selected["element"],
            "floor": floor,
            "is_milestone": False
        }
    
    @staticmethod
    def _generate_fallback_monster(floor: int) -> Dict[str, Any]:
        """Fallback monster generation if config missing."""
        base_atk = 100
        base_def = 2000
        
        scaled_atk = int(base_atk * (1.08 ** floor))
        scaled_def = int(base_def * (1.10 ** floor))
        
        return {
            "name": f"Floor {floor} Guardian",
            "atk": scaled_atk,
            "def": scaled_def,
            "hp": scaled_def,
            "max_hp": scaled_def,
            "element": secrets.choice(["infernal", "abyssal", "tempest", "earth", "radiant", "umbral"]),
            "floor": floor,
            "is_milestone": False
        }
    
    # ========================================================================
    # FLOOR INITIATION
    # ========================================================================
    
    @staticmethod
    async def initiate_floor(
        session: AsyncSession,
        player: Player
    ) -> Dict[str, Any]:
        """
        Start floor combat encounter.
        
        Validates stamina and generates combat state.
        Does NOT consume stamina - that happens on attack.
        
        Args:
            session: Database session
            player: Player object
        
        Returns:
            {
                "floor": 10,
                "monster": {...},
                "player_stats": {...},
                "strategic_power": {...},
                "combat_state": {...}
            }
        """
        progress = await AscensionService.get_or_create_progress(
            session, player.discord_id
        )
        
        floor = progress.get_next_floor()
        
        # Generate monster
        monster = AscensionService.generate_floor_monster(floor)
        
        # Get strategic power (best 6 maidens)
        strategic = await CombatService.calculate_strategic_power(
            session, player.discord_id, include_leader_bonus=True
        )
        
        # Calculate player max HP (with Earth general bonus)
        max_hp = player.max_hp
        if "earth" in strategic.generals:
            max_hp += 100  # Earth general bonus
        
        # Initialize combat state
        combat_state = {
            "floor": floor,
            "monster_hp": monster["hp"],
            "monster_max_hp": monster["max_hp"],
            "player_hp": player.hp,
            "player_max_hp": max_hp,
            "critical_gauge": 0,
            "momentum": 0,
            "turns_taken": 0
        }
        
        logger.info(
            f"Floor {floor} initiated for player {player.discord_id}: "
            f"monster={monster['name']}, player_power={strategic.total_power:,}"
        )
        
        return {
            "floor": floor,
            "monster": monster,
            "player_stats": {
                "hp": player.hp,
                "max_hp": max_hp,
                "power": strategic.total_power,
                "defense": strategic.total_defense
            },
            "strategic_power": {
                "total_power": strategic.total_power,
                "total_defense": strategic.total_defense,
                "generals": strategic.generals,
                "element_bonuses": strategic.element_bonuses
            },
            "combat_state": combat_state
        }
    
    # ========================================================================
    # COMBAT TURN EXECUTION
    # ========================================================================
    
    @staticmethod
    async def execute_attack_turn(
        session: AsyncSession,
        player: Player,
        monster: Dict[str, Any],
        attack_type: str,
        combat_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute full combat turn: player attacks, boss retaliates.
        
        Args:
            session: Database session
            player: Player object (with_for_update=True)
            monster: Monster data
            attack_type: "x1", "x3", or "x10"
            combat_state: Current combat state
        
        Returns:
            {
                "player_damage": int,
                "boss_damage": int,
                "player_hp": int,
                "boss_hp": int,
                "critical": bool,
                "momentum": int,
                "victory": bool,
                "defeat": bool,
                "combat_log": List[str],
                "stamina_cost": int,
                "lumenite_cost": int
            }
        """
        # Validate and consume resources
        costs = AscensionService.get_attack_cost(attack_type)
        stamina_cost = costs["stamina"]
        lumenite_cost = costs["lumenite"]

        if player.stamina < stamina_cost:
            raise InsufficientResourcesError("stamina", stamina_cost, player.stamina)

        if lumenite_cost > 0 and player.lumenite < lumenite_cost:
            raise InsufficientResourcesError("lumenite", lumenite_cost, player.lumenite)

        # Consume resources
        player.stamina -= stamina_cost
        if lumenite_cost > 0:
            player.lumenite -= lumenite_cost
        
        # Get strategic power
        strategic = await CombatService.calculate_strategic_power(
            session, player.discord_id, include_leader_bonus=True
        )
        
        # Calculate player damage
        attack_mult = {"x1": 1, "x3": 3, "x10": 10}[attack_type]
        
        # Get crit chance (base + tempest general bonus)
        base_crit = 0.05
        tempest_bonus = 0.05 if "tempest" in strategic.generals else 0.0
        crit_chance = base_crit + tempest_bonus
        
        # x10 attack fills crit gauge instantly
        if attack_type == "x10":
            combat_state["critical_gauge"] = 100
        
        # Check if crit guaranteed
        guaranteed_crit = combat_state["critical_gauge"] >= 100
        if guaranteed_crit:
            crit_chance = 1.0
            combat_state["critical_gauge"] = 0
        
        # Calculate damage
        damage_calc = CombatService.calculate_damage(
            player_power=strategic.total_power,
            attack_count=attack_mult,
            crit_chance=crit_chance,
            crit_multiplier=1.5,
            momentum_level=combat_state["momentum"]
        )
        
        # Update critical gauge if not reset
        if not guaranteed_crit:
            combat_state["critical_gauge"] += 10 * attack_mult
            combat_state["critical_gauge"] = min(100, combat_state["critical_gauge"])
        
        # Deal damage to boss
        monster["hp"] -= damage_calc.final_damage
        victory = monster["hp"] <= 0
        
        combat_log = [
            f"⚔️ You dealt {damage_calc.final_damage:,} damage! "
            f"{'💥 CRITICAL!' if damage_calc.was_critical else ''}"
        ]
        
        # Boss retaliation (if still alive)
        boss_damage_to_player = 0
        defeat = False
        
        if not victory:
            # Check for Umbral general
            umbral_present = "umbral" in strategic.generals
            
            boss_damage = CombatService.calculate_boss_damage_to_player(
                boss_atk=monster["atk"],
                generals_total_def=strategic.total_defense,
                umbral_general_present=umbral_present
            )
            
            player.hp -= boss_damage
            boss_damage_to_player = boss_damage
            
            defeat = player.hp <= 0
            
            combat_log.append(
                f"🗡️ Boss counter-attacks! You took {boss_damage:,} damage!"
            )
            
            # Check momentum loss (heavy hit)
            if boss_damage > (player.max_hp * 0.3):
                combat_state["momentum"] = max(0, combat_state["momentum"] - 20)
                combat_log.append("⚠️ Heavy damage! Momentum decreased!")
        
        # Update momentum (if not lost)
        if not defeat and boss_damage_to_player < (player.max_hp * 0.3):
            combat_state["momentum"] = min(100, combat_state["momentum"] + 10)
        
        # Update turn count
        combat_state["turns_taken"] += 1
        
        # Apply Radiant general HP regen (if present)
        if "radiant" in strategic.generals and not victory:
            regen = int(player.max_hp * 0.05)
            player.hp = min(player.max_hp, player.hp + regen)
            if regen > 0:
                combat_log.append(f"✨ Radiant General: Restored {regen} HP!")
        
        return {
            "player_damage": damage_calc.final_damage,
            "boss_damage": boss_damage_to_player,
            "player_hp": max(0, player.hp),
            "boss_hp": max(0, monster["hp"]),
            "critical": damage_calc.was_critical,
            "momentum": combat_state["momentum"],
            "victory": victory,
            "defeat": defeat,
            "combat_log": combat_log,
            "stamina_cost": stamina_cost,
            "lumenite_cost": lumenite_cost,
            "critical_gauge": combat_state["critical_gauge"],
            "turns_taken": combat_state["turns_taken"]
        }
    
    # ========================================================================
    # VICTORY RESOLUTION
    # ========================================================================
    
    @staticmethod
    async def resolve_victory(
        session: AsyncSession,
        player: Player,
        floor: int,
        turns_taken: int
    ) -> Dict[str, Any]:
        """
        Process floor victory and grant rewards.
        
        Args:
            session: Database session
            player: Player object (with_for_update=True)
            floor: Floor cleared
            turns_taken: Combat turns
        
        Returns:
            {
                "rewards": {...},
                "new_floor": int,
                "is_record": bool
            }
        """
        progress = await AscensionService.get_or_create_progress(
            session, player.discord_id
        )
        
        # Update progress
        progress.current_floor = floor
        progress.total_floors_cleared += 1
        progress.total_victories += 1
        progress.last_victory = datetime.utcnow()
        
        is_record = False
        if floor > progress.highest_floor:
            progress.highest_floor = floor
            is_record = True
            
            if floor > player.highest_floor_ascended:
                player.highest_floor_ascended = floor
        
        # Calculate rewards
        rewards = await AscensionService._calculate_rewards(session, player, floor)
        
        # Grant rewards
        if rewards["lumees"] > 0:
            await ResourceService.grant_resources(
                session=session,
                player=player,
                resources={"lumees": rewards["lumees"]},
                source="ascension_victory",
                context={"floor": floor, "turns": turns_taken}
            )
        
        if rewards["xp"] > 0:
            from src.modules.player.service import PlayerService
            await PlayerService.add_xp_and_level_up(player, rewards["xp"])
        
        # Grant token (CORRECTED IMPORT PATH)
        if rewards.get("token"):
            from src.modules.ascension.token_logic import TokenService
            await TokenService.grant_token(
                session=session,
                player_id=player.discord_id,
                token_type=rewards["token"]["type"],
                quantity=rewards["token"]["quantity"],
                source=f"ascension_floor_{floor}"
            )
        
        # Log transaction
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player.discord_id,
            transaction_type="ascension_victory",
            details={
                "floor": floor,
                "turns": turns_taken,
                "rewards": rewards,
                "is_record": is_record
            },
            context="ascension_combat"
        )
        
        logger.info(
            f"Player {player.discord_id} cleared floor {floor} "
            f"in {turns_taken} turns (record: {is_record})"
        )
        
        await session.flush()
        
        return {
            "rewards": rewards,
            "new_floor": progress.get_next_floor(),
            "is_record": is_record
        }
    
    @staticmethod
    async def _calculate_rewards(
        session: AsyncSession,
        player: Player,
        floor: int
    ) -> Dict[str, Any]:
        """Calculate rewards for floor victory."""
        # Base rewards
        base_lumees = 100
        base_xp = 20
        growth_rate = 1.08

        lumees = int(base_lumees * (growth_rate ** floor))
        xp = int(base_xp * (growth_rate ** floor))

        # Token reward
        token = AscensionService._determine_token_drop(floor)

        rewards = {
            "lumees": lumees,
            "xp": xp,
            "token": token
        }
        
        # Milestone bonuses
        if floor in [50, 100, 150, 200]:
            # LUMEN LAW I.6 - YAML is source of truth
            milestone_config = ConfigManager.get(
                f"ascension_monsters.milestone_bosses.{floor}.bonus_rewards"
            )
            if milestone_config:
                rewards["milestone_bonus"] = milestone_config
        
        return rewards
    
    @staticmethod
    def _determine_token_drop(floor: int) -> Dict[str, Any]:
        """Determine which token drops from floor."""
        if floor <= 10:
            return {"type": "bronze", "quantity": 1}
        elif floor <= 25:
            # 60% bronze, 40% silver
            return {"type": secrets.choices(["bronze", "silver"], weights=[60, 40])[0], "quantity": 1}
        elif floor <= 50:
            # 70% silver, 30% gold
            return {"type": secrets.choices(["silver", "gold"], weights=[70, 30])[0], "quantity": 1}
        elif floor <= 100:
            # 60% gold, 40% platinum
            return {"type": secrets.choices(["gold", "platinum"], weights=[60, 40])[0], "quantity": 1}
        elif floor <= 150:
            # 70% platinum, 30% diamond
            return {"type": secrets.choices(["platinum", "diamond"], weights=[70, 30])[0], "quantity": 1}
        else:
            # 80% diamond, 20% mythic (future token type)
            return {"type": secrets.choices(["diamond"], weights=[100])[0], "quantity": 1}
    
    # ========================================================================
    # UTILITY
    # ========================================================================
    
    @staticmethod
    def get_attack_cost(attack_type: str) -> Dict[str, int]:
        """
        Get resource costs for attack type (LUMEN LAW I.6 - ConfigManager).

        Returns:
            {"stamina": int, "lumenite": int}
        """
        # LUMEN LAW I.6 - YAML is source of truth
        ATTACK_COSTS = ConfigManager.get("ASCENSION.ATTACK_COSTS")
        return ATTACK_COSTS.get(attack_type, {"stamina": 1, "lumenite": 0})