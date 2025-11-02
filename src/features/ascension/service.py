"""
Infinite tower climbing progression system.

RIKI LAW Compliance: Article III (Service Layer), Article II (Audit Trails)
- Pure business logic with no Discord dependencies
- Uses CombatService for all power/damage calculations
- Comprehensive transaction logging for all floor attempts
- Pessimistic locking for player state modifications

Features:
- Infinite tower climbing with exponential difficulty scaling
- Dynamic stamina costs based on player level
- Multiple attack options (x1, x5, x20 with gems)
- Progressive rewards with milestone bonuses
- Leaderboard tracking and statistics
- Complete audit trails for all battles

Attack damage originates from CombatService.calculate_damage()
Power calculation from CombatService.calculate_total_power()
"""

from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import random
import math

from src.database.models.core.player import Player
from src.database.models.progression.ascension_progress import AscensionProgress
from src.core.config_manager import ConfigManager
from src.features.resource.service import ResourceService
from src.features.combat.service import CombatService
from src.core.transaction_logger import TransactionLogger
from src.core.exceptions import InsufficientResourcesError, InvalidOperationError
from src.core.logger import get_logger, LogContext

logger = get_logger(__name__)


class AscensionService:
    """
    Infinite tower climbing system with exponentially scaling difficulty (RIKI LAW Article III).
    
    Players use collective maiden power to climb floors, earning rewards
    at each level. Stamina cost increases with player level. Checkpoints
    at each completed floor.
    
    Key Features:
        - Exponential HP scaling (never trivial)
        - Dynamic stamina costs (scales with player level)
        - Multiple attack options (x1/x5/x20 with gem cost)
        - Milestone rewards every 50 floors
        - Leaderboard tracking
        - Complete audit trails (RIKI LAW Article II)
    
    Design Principles:
        - Uses CombatService for all power/damage calculations (no duplication)
        - Pure business logic (zero Discord dependencies)
        - Pessimistic locking for all player modifications
        - Transaction logging for all floor attempts
    
    Usage:
        >>> # Get player progress
        >>> progress = await AscensionService.get_or_create_progress(session, player_id)
        
        >>> # Attempt floor
        >>> async with DatabaseService.get_transaction() as session:
        ...     player = await session.get(Player, player_id, with_for_update=True)
        ...     power = await CombatService.calculate_total_power(session, player_id, include_leader_bonus=True)
        ...     result = await AscensionService.attempt_floor(session, player, power)
        
        >>> # Execute attacks
        >>> damage = CombatService.calculate_damage(power, attack_count=5, crit_chance=0.0)
        >>> result = await AscensionService.resolve_combat(
        ...     session, player, floor, damage.final_damage, attacks_used=1
        ... )
    """
    
    # ========================================================================
    # PROGRESS TRACKING
    # ========================================================================
    
    @staticmethod
    async def get_or_create_progress(session: AsyncSession, player_id: int) -> AscensionProgress:
        """
        Get existing ascension progress or create new record.
        
        Args:
            session: Database session
            player_id: Discord ID
        
        Returns:
            AscensionProgress record
        
        Example:
            >>> progress = await AscensionService.get_or_create_progress(session, player_id)
            >>> print(f"Current floor: {progress.current_floor}")
        """
        result = await session.execute(
            select(AscensionProgress).where(AscensionProgress.player_id == player_id)
        )
        progress = result.scalar_one_or_none()
        
        if not progress:
            progress = AscensionProgress(player_id=player_id)
            session.add(progress)
            await session.flush()
            logger.info(f"Created ascension progress for player {player_id}")
        
        return progress
    
    # ========================================================================
    # RESOURCE CALCULATIONS
    # ========================================================================
    
    @staticmethod
    def calculate_stamina_cost(player_level: int) -> int:
        """
        Calculate stamina cost for floor attempt.
        
        Formula: base_cost + (level // 10) × increase_per_10
        
        Args:
            player_level: Player's current level
        
        Returns:
            Stamina cost (integer)
        
        Example:
            >>> cost = AscensionService.calculate_stamina_cost(level=25)
            >>> print(f"Stamina cost: {cost}")  # 5 + (25 // 10) * 1 = 7
        """
        base_cost = ConfigManager.get("ascension_system.base_stamina_cost", 5)
        increase_per_10 = ConfigManager.get("ascension_system.stamina_increase_per_10_levels", 1)
        
        additional_cost = (player_level // 10) * increase_per_10
        return base_cost + additional_cost
    
    @staticmethod
    def get_gem_attack_cost() -> int:
        """
        Get gem cost for x20 attack.
        
        Returns:
            Gem cost for x20 attack
        
        Example:
            >>> cost = AscensionService.get_gem_attack_cost()
            >>> print(f"x20 attack costs {cost} gems")
        """
        return ConfigManager.get("ascension_system.x20_attack_gem_cost", 10)
    
    # ========================================================================
    # ENEMY GENERATION
    # ========================================================================
    
    @staticmethod
    def generate_floor_enemy(floor: int) -> Dict[str, Any]:
        """
        Generate enemy stats for specific floor.
        
        HP scales exponentially to always remain challenging.
        Formula: base_hp × (growth_rate ^ floor)
        
        Args:
            floor: Floor number (1+)
        
        Returns:
            Dictionary with:
                - name: Enemy name (thematic based on floor tier)
                - hp: Total HP
                - floor: Floor number
                - rewards: Reward breakdown
        
        Example:
            >>> enemy = AscensionService.generate_floor_enemy(floor=50)
            >>> print(f"{enemy['name']}: {enemy['hp']:,} HP")
        """
        base_hp = ConfigManager.get("ascension_system.enemy_hp_base", 1000)
        growth_rate = ConfigManager.get("ascension_system.enemy_hp_growth_rate", 1.10)
        
        hp = int(base_hp * (growth_rate ** floor))
        
        # Generate thematic name
        name = AscensionService._generate_enemy_name(floor)
        
        # Calculate rewards
        rewards = AscensionService._calculate_floor_rewards(floor)
        
        return {
            "name": name,
            "hp": hp,
            "floor": floor,
            "rewards": rewards,
        }
    
    @staticmethod
    def _generate_enemy_name(floor: int) -> str:
        """
        Generate thematic enemy name based on floor tier.
        
        Args:
            floor: Floor number
        
        Returns:
            Enemy name string
        """
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
        
        prefix = random.choice(prefixes)
        enemy_type = random.choice(types)
        
        # Special naming for milestone floors
        if floor % 50 == 0:
            return f"Floor {floor} Guardian"
        
        return f"{prefix} {enemy_type}"
    
    @staticmethod
    def _calculate_floor_rewards(floor: int) -> Dict[str, Any]:
        """
        Calculate rewards for clearing specific floor.
        
        Base rewards scale exponentially. Bonus rewards at intervals.
        
        Args:
            floor: Floor number
        
        Returns:
            Dictionary with reward types and amounts
        """
        base_rikis = ConfigManager.get("ascension_system.reward_base_rikis", 50)
        base_xp = ConfigManager.get("ascension_system.reward_base_xp", 20)
        growth_rate = ConfigManager.get("ascension_system.reward_growth_rate", 1.12)
        
        rikis = int(base_rikis * (growth_rate ** floor))
        xp = int(base_xp * (growth_rate ** floor))
        
        rewards = {
            "rikis": rikis,
            "xp": xp,
        }
        
        # Bonus rewards at intervals
        bonus_intervals = ConfigManager.get("ascension_system.bonus_intervals", {})
        
        egg_interval = bonus_intervals.get("egg_every_n_floors", 5)
        if floor % egg_interval == 0:
            rewards["maiden_egg"] = {
                "rarity": AscensionService._get_egg_rarity_for_floor(floor),
                "element": "random"
            }
        
        prayer_interval = bonus_intervals.get("prayer_charge_every_n_floors", 10)
        if floor % prayer_interval == 0:
            rewards["prayer_charges"] = 1
        
        catalyst_interval = bonus_intervals.get("fusion_catalyst_every_n_floors", 25)
        if floor % catalyst_interval == 0:
            rewards["fusion_catalyst"] = 1
        
        # Milestone rewards
        milestones = ConfigManager.get("ascension_system.milestones", {})
        if floor in milestones:
            milestone_rewards = milestones[floor]
            rewards["milestone"] = milestone_rewards
        
        return rewards
    
    @staticmethod
    def _get_egg_rarity_for_floor(floor: int) -> str:
        """
        Determine maiden egg rarity based on floor number.
        
        Higher floors grant better eggs.
        
        Args:
            floor: Floor number
        
        Returns:
            Rarity string (common, rare, epic, legendary, mythic)
        """
        # Example floor ranges (should be in config)
        if floor < 20:
            return "common"
        elif floor < 50:
            return "rare"
        elif floor < 100:
            return "epic"
        elif floor < 200:
            return "legendary"
        else:
            return "mythic"
    
    # ========================================================================
    # FLOOR ATTEMPT
    # ========================================================================
    
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
        
        Uses pessimistic locking (player must be fetched with with_for_update=True).
        
        Args:
            session: Database session (must be in transaction)
            player: Player object (with_for_update=True)
            player_power: Total ATK from maiden collection
        
        Returns:
            Dictionary with:
                - floor: Floor number
                - enemy: Enemy data (name, hp, rewards)
                - stamina_cost: Stamina consumed
                - estimated_attacks: Attacks needed estimate
        
        Raises:
            InsufficientResourcesError: Not enough stamina
        
        Example:
            >>> async with DatabaseService.get_transaction() as session:
            ...     player = await session.get(Player, player_id, with_for_update=True)
            ...     power = await CombatService.calculate_total_power(session, player_id, include_leader_bonus=True)
            ...     result = await AscensionService.attempt_floor(session, player, power)
        """
        async with LogContext(user_id=player.discord_id, command="/ascension attempt"):
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
            
            # Generate enemy
            enemy = AscensionService.generate_floor_enemy(floor)
            
            # Update progress stats
            progress.total_attempts += 1
            progress.last_attempt = datetime.utcnow()
            
            # Estimate attacks needed using CombatService
            estimated_attacks = CombatService.calculate_attacks_needed(player_power, enemy["hp"])
            
            # Update daily quest
            from src.features.daily.service import DailyService
            await DailyService.update_quest_progress(
                session, player.discord_id, "spend_stamina", stamina_cost
            )
            
            # Transaction logging
            await TransactionLogger.log_transaction(
                session=session,
                player_id=player.discord_id,
                transaction_type="ascension_attempt",
                details={
                    "floor": floor,
                    "enemy": enemy["name"],
                    "enemy_hp": enemy["hp"],
                    "stamina_cost": stamina_cost,
                    "player_power": player_power,
                    "estimated_attacks": estimated_attacks
                },
                context="ascension_floor_attempt"
            )
            
            await session.flush()
            
            logger.info(
                f"Player {player.discord_id} attempting floor {floor}: "
                f"enemy HP {enemy['hp']:,}, power {player_power:,}, est. attacks {estimated_attacks}"
            )
            
            return {
                "floor": floor,
                "enemy": enemy,
                "stamina_cost": stamina_cost,
                "estimated_attacks": estimated_attacks,
            }
    
    # ========================================================================
    # COMBAT RESOLUTION
    # ========================================================================
    
    @staticmethod
    async def resolve_combat(
        session: AsyncSession,
        player: Player,
        floor: int,
        damage_dealt: int,
        attacks_used: int,
        gems_spent: int = 0
    ) -> Dict[str, Any]:
        """
        Resolve floor combat after player attacks complete.
        
        Updates progress, grants rewards on victory.
        Uses pessimistic locking (player must be fetched with with_for_update=True).
        
        Args:
            session: Database session (must be in transaction)
            player: Player object (with_for_update=True)
            floor: Floor number attempted
            damage_dealt: Total damage player dealt
            attacks_used: Number of attacks made (for stats)
            gems_spent: Gems consumed for x20 attacks
        
        Returns:
            Dictionary with:
                - victory: True if floor cleared
                - rewards: Rewards granted (if victory)
                - new_floor: Next floor number (if victory)
                - remaining_hp: Enemy HP left (if defeat)
                - is_record: True if new highest floor
        
        Example:
            >>> # After calculating damage from attacks
            >>> result = await AscensionService.resolve_combat(
            ...     session, player, floor=10, damage_dealt=15000, attacks_used=1
            ... )
            >>> if result["victory"]:
            ...     print(f"Victory! Rewards: {result['rewards']}")
        """
        async with LogContext(user_id=player.discord_id, command="/ascension attack"):
            progress = await AscensionService.get_or_create_progress(session, player.discord_id)
            
            # Generate enemy for validation
            enemy = AscensionService.generate_floor_enemy(floor)
            enemy_hp = enemy["hp"]
            
            victory = damage_dealt >= enemy_hp
            
            if victory:
                # Update progress
                progress.current_floor = floor
                progress.total_floors_cleared += 1
                progress.total_victories += 1
                progress.last_victory = datetime.utcnow()
                
                is_record = False
                if floor > progress.highest_floor:
                    progress.highest_floor = floor
                    is_record = True
                    
                    # Update player global stat
                    if floor > player.highest_floor_ascended:
                        player.highest_floor_ascended = floor
                
                # Grant rewards
                rewards = enemy["rewards"]
                
                # Rikis and XP via ResourceService
                await ResourceService.add_rikis(session, player, rewards["rikis"], "ascension_victory")
                await ResourceService.add_xp(session, player, rewards["xp"])
                
                # Bonus rewards
                if "prayer_charges" in rewards:
                    player.prayer_charges += rewards["prayer_charges"]
                
                if "fusion_catalyst" in rewards:
                    # Add fusion catalyst to inventory (future feature)
                    pass
                
                if "maiden_egg" in rewards:
                    # Add maiden egg to inventory (future feature)
                    pass
                
                # Transaction logging
                await TransactionLogger.log_transaction(
                    session=session,
                    player_id=player.discord_id,
                    transaction_type="ascension_victory",
                    details={
                        "floor": floor,
                        "enemy": enemy["name"],
                        "damage_dealt": damage_dealt,
                        "attacks_used": attacks_used,
                        "gems_spent": gems_spent,
                        "rewards": rewards,
                        "is_record": is_record
                    },
                    context="ascension_battle"
                )
                
                logger.info(
                    f"Player {player.discord_id} cleared floor {floor}: "
                    f"dealt {damage_dealt:,} damage in {attacks_used} attacks "
                    f"(record: {is_record})"
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
                progress.total_defeats += 1
                remaining_hp = enemy_hp - damage_dealt
                
                await TransactionLogger.log_transaction(
                    session=session,
                    player_id=player.discord_id,
                    transaction_type="ascension_defeat",
                    details={
                        "floor": floor,
                        "enemy": enemy["name"],
                        "damage_dealt": damage_dealt,
                        "attacks_used": attacks_used,
                        "gems_spent": gems_spent,
                        "remaining_hp": remaining_hp
                    },
                    context="ascension_battle"
                )
                
                logger.info(
                    f"Player {player.discord_id} failed floor {floor}: "
                    f"{remaining_hp:,}/{enemy_hp:,} HP remaining after {attacks_used} attacks"
                )
                
                await session.flush()
                
                return {
                    "victory": False,
                    "rewards": None,
                    "new_floor": None,
                    "remaining_hp": remaining_hp,
                    "is_record": False
                }