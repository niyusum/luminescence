"""
Infinite tower climbing system with exponentially scaling difficulty.

Features:
- Exponential HP scaling (never trivial)
- Dynamic stamina costs based on player level
- x1/x5/x20 attack options with gem boost
- Milestone rewards every 50 floors
- Comprehensive statistics tracking
- Performance metrics and monitoring

RIKI LAW Compliance:
- Session-first parameter pattern (Article I.6)
- ConfigManager for all tunables (Article IV)
- Transaction logging for audit trails (Article II)
- Domain exceptions only (Article VII)
- No Discord imports (Article VII)
"""

from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime
import random
import math
import time

from src.database.models.core.player import Player
from src.database.models.progression.ascension_progress import AscensionProgress
from src.core.config_manager import ConfigManager
from src.features.resource.service import ResourceService
from src.core.transaction_logger import TransactionLogger
from src.core.exceptions import InsufficientResourcesError, InvalidOperationError
from src.core.logger import get_logger

logger = get_logger(__name__)


class AscensionService:
    """
    Infinite tower climbing system with exponentially scaling difficulty.
    
    Players use collective maiden power to climb floors, earning rewards
    at each level. Stamina cost increases with player level. Checkpoints
    at each completed floor.
    """
    
    # Metrics tracking
    _metrics = {
        "attempts": 0,
        "victories": 0,
        "defeats": 0,
        "total_damage_dealt": 0,
        "total_stamina_spent": 0,
        "total_gems_spent": 0,
        "floors_cleared": 0,
        "errors": 0,
        "total_attempt_time_ms": 0.0,
        "total_resolve_time_ms": 0.0,
    }
    
    @staticmethod
    async def get_or_create_progress(
        session: AsyncSession,
        player_id: int
    ) -> AscensionProgress:
        """Get existing ascension progress or create new record."""
        try:
            result = await session.execute(
                select(AscensionProgress).where(AscensionProgress.player_id == player_id)
            )
            progress = result.scalar_one_or_none()
            
            if not progress:
                progress = AscensionProgress(player_id=player_id)
                session.add(progress)
                await session.flush()
                logger.info(
                    f"Created ascension progress: player={player_id}",
                    extra={"player_id": player_id}
                )
            
            return progress
            
        except Exception as e:
            AscensionService._metrics["errors"] += 1
            logger.error(
                f"Failed to get/create progress: player={player_id} error={e}",
                extra={"player_id": player_id},
                exc_info=True
            )
            raise
    
    @staticmethod
    def calculate_stamina_cost(player_level: int) -> int:
        """Calculate stamina cost for floor attempt (base + 1 per 10 levels)."""
        base_cost = ConfigManager.get("ascension_system.base_stamina_cost", 5)
        increase_per_10 = ConfigManager.get("ascension_system.stamina_increase_per_10_levels", 1)
        
        additional_cost = (player_level // 10) * increase_per_10
        return base_cost + additional_cost
    
    @staticmethod
    def generate_floor_enemy(floor: int) -> Dict[str, Any]:
        """Generate enemy stats for specific floor with exponential HP scaling."""
        base_hp = ConfigManager.get("ascension_system.enemy_hp_base", 1000)
        growth_rate = ConfigManager.get("ascension_system.enemy_hp_growth_rate", 1.12)
        
        hp = int(base_hp * (growth_rate ** floor))
        name = AscensionService._generate_enemy_name(floor)
        rewards = AscensionService._calculate_floor_rewards(floor)
        
        return {
            "name": name,
            "hp": hp,
            "floor": floor,
            "rewards": rewards,
        }
    
    @staticmethod
    def _generate_enemy_name(floor: int) -> str:
        """Generate thematic enemy name based on floor tier."""
        if floor <= 10:
            prefixes = ["Lesser", "Minor", "Weak"]
        elif floor <= 50:
            prefixes = ["Guardian", "Sentinel", "Watcher"]
        elif floor <= 100:
            prefixes = ["Elite", "Champion", "Veteran"]
        elif floor <= 200:
            prefixes = ["Ascended", "Exalted", "Divine"]
        else:
            prefixes = ["Transcendent", "Eternal", "Absolute"]
        
        types = ["Warrior", "Mage", "Beast", "Construct", "Wraith"]
        
        if floor % 50 == 0:
            return f"Floor {floor} Guardian"
        
        return f"{random.choice(prefixes)} {random.choice(types)}"
    
    @staticmethod
    def _calculate_floor_rewards(floor: int) -> Dict[str, Any]:
        """Calculate rewards with exponential scaling and bonus items at intervals."""
        base_rikis = ConfigManager.get("ascension_system.reward_base_rikis", 50)
        base_xp = ConfigManager.get("ascension_system.reward_base_xp", 20)
        growth_rate = ConfigManager.get("ascension_system.reward_growth_rate", 1.1)
        
        rewards = {
            "rikis": int(base_rikis * (growth_rate ** floor)),
            "xp": int(base_xp * (growth_rate ** floor)),
        }
        
        # Bonus rewards at intervals
        bonus_intervals = ConfigManager.get("ascension_system.bonus_intervals", {})
        
        if floor % bonus_intervals.get("egg_every_n_floors", 5) == 0:
            rewards["maiden_egg"] = {
                "rarity": AscensionService._get_egg_rarity_for_floor(floor),
                "element": "random"
            }
        
        if floor % bonus_intervals.get("prayer_charge_every_n_floors", 10) == 0:
            rewards["prayer_charges"] = 1
        
        if floor % bonus_intervals.get("fusion_catalyst_every_n_floors", 25) == 0:
            rewards["fusion_catalyst"] = 1
        
        # Milestone rewards
        milestones = ConfigManager.get("ascension_system.milestones", {})
        if floor in milestones:
            rewards["milestone"] = milestones[floor]
        
        return rewards
    
    @staticmethod
    def _get_egg_rarity_for_floor(floor: int) -> str:
        """Determine maiden egg rarity based on floor number."""
        egg_rarity_floors = ConfigManager.get("ascension_system.egg_rarity_floors", {})
        
        for rarity, (min_floor, max_floor) in egg_rarity_floors.items():
            if min_floor <= floor <= max_floor:
                return rarity
        
        return "epic"
    
    @staticmethod
    def calculate_damage(
        player_power: int,
        attack_count: int,
        is_gem_attack: bool = False
    ) -> int:
        """Calculate damage with optional crit bonus for gem attacks."""
        base_damage = player_power * attack_count
        
        if is_gem_attack:
            crit_bonus = ConfigManager.get("ascension_system.x20_attack_crit_bonus", 0.2)
            base_damage = int(base_damage * (1 + crit_bonus))
        
        return base_damage
    
    @staticmethod
    def get_gem_attack_cost() -> int:
        """Get gem cost for x20 attack."""
        return ConfigManager.get("ascension_system.x20_attack_gem_cost", 10)
    
    @staticmethod
    async def attempt_floor(
        session: AsyncSession,
        player: Player,
        player_power: int
    ) -> Dict[str, Any]:
        """
        Initiate floor attempt, consuming stamina.
        
        Returns floor enemy data and validates stamina cost.
        Does NOT resolve combat - that's done via attack actions.
        """
        start_time = time.perf_counter()
        AscensionService._metrics["attempts"] += 1
        
        try:
            progress = await AscensionService.get_or_create_progress(session, player.discord_id)
            
            floor = progress.get_next_floor()
            stamina_cost = AscensionService.calculate_stamina_cost(player.level)
            
            # Validate stamina
            if player.stamina < stamina_cost:
                raise InsufficientResourcesError(
                    resource="stamina",
                    required=stamina_cost,
                    current=player.stamina
                )
            
            # Consume stamina
            player.stamina -= stamina_cost
            AscensionService._metrics["total_stamina_spent"] += stamina_cost
            
            # Generate enemy
            enemy = AscensionService.generate_floor_enemy(floor)
            
            # Update progress stats
            progress.total_attempts += 1
            progress.last_attempt = datetime.utcnow()
            
            # Estimate attacks needed
            estimated_attacks = (
                math.ceil(enemy["hp"] / player_power)
                if player_power > 0 else 999
            )
            
            # Update daily quest
            from src.features.daily.service import DailyService
            await DailyService.update_quest_progress(
                session, player.discord_id, "spend_stamina", stamina_cost
            )
            
            await session.flush()
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            AscensionService._metrics["total_attempt_time_ms"] += elapsed_ms
            
            logger.info(
                f"Floor attempt: player={player.discord_id} floor={floor} "
                f"hp={enemy['hp']} power={player_power}",
                extra={
                    "player_id": player.discord_id,
                    "floor": floor,
                    "enemy_hp": enemy["hp"],
                    "player_power": player_power,
                    "attempt_time_ms": round(elapsed_ms, 2)
                }
            )
            
            return {
                "floor": floor,
                "enemy": enemy,
                "stamina_cost": stamina_cost,
                "estimated_attacks": estimated_attacks,
            }
            
        except InsufficientResourcesError:
            raise
        except Exception as e:
            AscensionService._metrics["errors"] += 1
            logger.error(
                f"Floor attempt failed: player={player.discord_id} error={e}",
                extra={"player_id": player.discord_id},
                exc_info=True
            )
            raise
    
    @staticmethod
    async def resolve_combat(
        session: AsyncSession,
        player: Player,
        floor: int,
        damage_dealt: int,
        attacks_used: int,
        gems_spent: int = 0
    ) -> Dict[str, Any]:
        """Resolve floor combat after player attacks complete."""
        start_time = time.perf_counter()
        
        try:
            progress = await AscensionService.get_or_create_progress(session, player.discord_id)
            
            enemy = AscensionService.generate_floor_enemy(floor)
            enemy_hp = enemy["hp"]
            victory = damage_dealt >= enemy_hp
            
            # Track metrics
            AscensionService._metrics["total_damage_dealt"] += damage_dealt
            AscensionService._metrics["total_gems_spent"] += gems_spent
            
            if victory:
                AscensionService._metrics["victories"] += 1
                AscensionService._metrics["floors_cleared"] += 1
                
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
                
                # Grant rewards
                rewards = enemy["rewards"]
                
                await ResourceService.grant_resources(
                    session=session,
                    player=player,
                    rikis=rewards["rikis"],
                    context="ascension_victory",
                    details={
                        "floor": floor,
                        "enemy": enemy["name"],
                        "attacks_used": attacks_used
                    }
                )
                
                progress.total_rikis_earned += rewards["rikis"]
                progress.total_xp_earned += rewards["xp"]
                
                await TransactionLogger.log_transaction(
                    session=session,
                    player_id=player.discord_id,
                    transaction_type="ascension_victory",
                    details={
                        "floor": floor,
                        "enemy": enemy,
                        "damage_dealt": damage_dealt,
                        "attacks_used": attacks_used,
                        "gems_spent": gems_spent,
                        "rewards": rewards,
                        "is_record": is_record
                    },
                    context="ascension_battle"
                )
                
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                AscensionService._metrics["total_resolve_time_ms"] += elapsed_ms
                
                logger.info(
                    f"Floor cleared: player={player.discord_id} floor={floor} "
                    f"attacks={attacks_used} record={is_record}",
                    extra={
                        "player_id": player.discord_id,
                        "floor": floor,
                        "is_record": is_record,
                        "resolve_time_ms": round(elapsed_ms, 2)
                    }
                )
                
                await session.flush()
                
                return {
                    "victory": True,
                    "rewards": rewards,
                    "new_floor": progress.get_next_floor(),
                    "remaining_hp": 0,
                    "is_record": is_record
                }
            
            else:
                # Defeat
                AscensionService._metrics["defeats"] += 1
                progress.total_defeats += 1
                remaining_hp = enemy_hp - damage_dealt
                
                await TransactionLogger.log_transaction(
                    session=session,
                    player_id=player.discord_id,
                    transaction_type="ascension_defeat",
                    details={
                        "floor": floor,
                        "enemy": enemy,
                        "damage_dealt": damage_dealt,
                        "remaining_hp": remaining_hp
                    },
                    context="ascension_battle"
                )
                
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                AscensionService._metrics["total_resolve_time_ms"] += elapsed_ms
                
                logger.info(
                    f"Floor failed: player={player.discord_id} floor={floor} "
                    f"remaining={remaining_hp}/{enemy_hp}",
                    extra={
                        "player_id": player.discord_id,
                        "floor": floor,
                        "remaining_hp": remaining_hp,
                        "resolve_time_ms": round(elapsed_ms, 2)
                    }
                )
                
                await session.flush()
                
                return {
                    "victory": False,
                    "rewards": None,
                    "new_floor": None,
                    "remaining_hp": remaining_hp,
                    "is_record": False
                }
                
        except Exception as e:
            AscensionService._metrics["errors"] += 1
            logger.error(
                f"Combat resolution failed: player={player.discord_id} floor={floor} error={e}",
                extra={"player_id": player.discord_id, "floor": floor},
                exc_info=True
            )
            raise
    
    @staticmethod
    def calculate_attacks_needed(player_power: int, enemy_hp: int) -> int:
        """Estimate attacks needed to defeat enemy."""
        return 999 if player_power == 0 else math.ceil(enemy_hp / player_power)
    
    # =========================================================================
    # LEADERBOARD & STATISTICS
    # =========================================================================
    
    @staticmethod
    async def get_leaderboard(
        session: AsyncSession,
        limit: int = 10,
        offset: int = 0
    ) -> list[AscensionProgress]:
        """Get top players by highest floor reached."""
        try:
            stmt = (
                select(AscensionProgress)
                .order_by(AscensionProgress.highest_floor.desc())
                .limit(limit)
                .offset(offset)
            )
            
            result = await session.execute(stmt)
            return list(result.scalars().all())
            
        except Exception as e:
            logger.error(f"Failed to get leaderboard: {e}", exc_info=True)
            return []
    
    @staticmethod
    async def get_player_rank(
        session: AsyncSession,
        player_id: int
    ) -> Optional[int]:
        """Get player's rank on leaderboard (1-indexed)."""
        try:
            progress = await AscensionService.get_or_create_progress(session, player_id)
            
            stmt = select(func.count()).select_from(AscensionProgress).where(
                AscensionProgress.highest_floor > progress.highest_floor
            )
            result = await session.execute(stmt)
            higher_count = result.scalar()
            
            return higher_count + 1
            
        except Exception as e:
            logger.error(
                f"Failed to get rank: player={player_id} error={e}",
                exc_info=True
            )
            return None
    
    # =========================================================================
    # METRICS & MONITORING
    # =========================================================================
    
    @staticmethod
    def get_metrics() -> Dict[str, Any]:
        """Get ascension service metrics."""
        total = AscensionService._metrics["attempts"]
        wins = AscensionService._metrics["victories"]
        losses = AscensionService._metrics["defeats"]
        
        win_rate = (wins / total * 100) if total > 0 else 0.0
        avg_attempt_ms = (
            AscensionService._metrics["total_attempt_time_ms"] / total
            if total > 0 else 0.0
        )
        avg_resolve_ms = (
            AscensionService._metrics["total_resolve_time_ms"] / (wins + losses)
            if (wins + losses) > 0 else 0.0
        )
        
        return {
            "attempts": total,
            "victories": wins,
            "defeats": losses,
            "win_rate": round(win_rate, 2),
            "floors_cleared": AscensionService._metrics["floors_cleared"],
            "total_damage_dealt": AscensionService._metrics["total_damage_dealt"],
            "total_stamina_spent": AscensionService._metrics["total_stamina_spent"],
            "total_gems_spent": AscensionService._metrics["total_gems_spent"],
            "errors": AscensionService._metrics["errors"],
            "avg_attempt_time_ms": round(avg_attempt_ms, 2),
            "avg_resolve_time_ms": round(avg_resolve_ms, 2),
        }
    
    @staticmethod
    def reset_metrics() -> None:
        """Reset all metrics counters."""
        AscensionService._metrics = {
            "attempts": 0,
            "victories": 0,
            "defeats": 0,
            "total_damage_dealt": 0,
            "total_stamina_spent": 0,
            "total_gems_spent": 0,
            "floors_cleared": 0,
            "errors": 0,
            "total_attempt_time_ms": 0.0,
            "total_resolve_time_ms": 0.0,
        }
        logger.info("AscensionService metrics reset")