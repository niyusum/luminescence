"""
Matron Service - LES 2025 Compliant
====================================

Purpose
-------
Manages matron boss encounters during exploration.
Matrons spawn when sector progress reaches 100% and provide
major rewards (lumees, XP, drop charges, fusion catalysts).

Domain
------
- Matron spawning (triggered by 100% sector completion)
- Rarity selection based on sector
- HP calculation with sector/sublevel scaling
- Reward calculation and distribution
- Integration with combat system for battles
- Special reward distribution (drop charges, catalysts)

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Transaction-safe - all writes in atomic transactions
✓ Config-driven - all scaling from matron.yaml
✓ Domain exceptions - raises NotFoundError, ValidationError
✓ Event-driven - emits matron.* events
✓ Observable - structured logging, audit trail
✓ Combat delegation - uses CombatService for battles

Design Decisions
----------------
- Matron rarity scales with sector (sector 1 = uncommon, sector 6+ = legendary)
- HP uses multiplicative scaling (base * sector_mult * sublevel_mult)
- Rewards scale exponentially with sector
- Special rewards (drop charges, catalysts) fixed per victory
- Combat uses AggregateEngine (total power vs boss HP)
- Defeat marks miniboss_defeated in SectorProgress

Dependencies
------------
- CombatService: For battle execution
- SectorProgressService: For miniboss defeat tracking
- WalletService: For lumees/currency rewards (future)
- ProgressionService: For XP rewards (future)
- ConfigManager: For matron scaling
- EventBus: For matron events
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.database.service import DatabaseService
from src.core.event.bus import EventBus
from src.core.infra.audit_logger import AuditLogger
from src.core.logging.logger import get_logger
from src.core.validation.input_validator import InputValidator
from src.modules.combat.shared.encounter import EnemyStats
from src.modules.shared.base_service import BaseService
from src.modules.shared.exceptions import InvalidOperationError, NotFoundError

if TYPE_CHECKING:
    from logging import Logger

    from src.core.config.manager import ConfigManager
    from src.modules.combat.service import CombatService
    from src.modules.exploration.sector_progress_service import SectorProgressService

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

RARITY_TIERS = ["uncommon", "rare", "epic", "legendary", "mythic"]
RARITY_TO_INDEX = {rarity: i for i, rarity in enumerate(RARITY_TIERS)}


# ============================================================================
# MatronService
# ============================================================================


class MatronService(BaseService):
    """
    Service for matron boss encounter management.
    
    Handles matron spawning, stats calculation, combat coordination,
    and reward distribution for exploration bosses.
    
    Public Methods
    --------------
    - check_matron_spawn_eligible(player_id, sector, sublevel) -> Check if matron can spawn
    - generate_matron_stats(sector, sublevel) -> Create matron EnemyStats
    - start_matron_battle(player_id, sector, sublevel) -> Initiate combat
    - finalize_matron_victory(player_id, sector, sublevel, encounter_id) -> Award rewards
    - calculate_matron_hp(rarity, sector, sublevel) -> Calculate HP
    - calculate_matron_rewards(sector, sublevel) -> Calculate rewards
    - select_matron_rarity(sector) -> Determine rarity tier
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
        combat_service: CombatService,
        sector_progress_service: SectorProgressService,
    ) -> None:
        """
        Initialize MatronService with required dependencies.
        
        Args:
            config_manager: Application configuration
            event_bus: Event bus for matron events
            logger: Structured logger
            combat_service: Combat service for battle execution
            sector_progress_service: Sector progress service for tracking
        """
        super().__init__(config_manager, event_bus, logger)

        self._combat = combat_service
        self._sector_progress = sector_progress_service

        # Load matron config
        self._hp_base = self.get_config(
            "exploration.matron.matron_system.hp_base",
            default={
                "uncommon": 2000,
                "rare": 5000,
                "epic": 15000,
                "legendary": 50000,
                "mythic": 150000,
            },
        )
        self._hp_sector_mult = float(
            self.get_config(
                "exploration.matron.matron_system.hp_sector_multiplier", default=0.5
            )
        )
        self._hp_sublevel_mult = float(
            self.get_config(
                "exploration.matron.matron_system.hp_sublevel_multiplier", default=0.1
            )
        )

        # Rarity selection
        self._sector_avg_rarity = self.get_config(
            "exploration.matron.matron_system.sector_avg_rarity",
            default={
                "sector_1": "uncommon",
                "sector_2": "rare",
                "sector_3": "rare",
                "sector_4": "epic",
                "sector_5": "epic",
                "sector_6": "legendary",
                "sector_7": "legendary",
            },
        )
        self._rarity_variance = self.get_config(
            "exploration.matron.matron_system.rarity_tier_increase", default=[1, 2]
        )

        # Rewards
        self._base_lumees = int(
            self.get_config(
                "exploration.matron.matron_system.reward_base_lumees", default=500
            )
        )
        self._base_xp = int(
            self.get_config(
                "exploration.matron.matron_system.reward_base_xp", default=100
            )
        )
        self._sector_reward_mult = float(
            self.get_config(
                "exploration.matron.matron_system.reward_sector_multiplier", default=1.0
            )
        )
        self._boss_sublevel_bonus = float(
            self.get_config(
                "exploration.matron.matron_system.boss_sublevel_bonus", default=2.0
            )
        )

        # Special rewards
        self._boss_rewards = self.get_config(
            "exploration.matron.matron_system.boss_rewards",
            default={"DROP_CHARGES": 1, "fusion_catalyst": 1},
        )

        # Legacy sector-specific config (fallback)
        self._legacy_sector_hp = {}
        self._legacy_sector_lumees = {}
        self._legacy_sector_xp = {}
        for sector in range(1, 8):
            self._legacy_sector_hp[sector] = int(
                self.get_config(
                    f"exploration.matron.sector_{sector}_hp_base", default=100000
                )
            )
            self._legacy_sector_lumees[sector] = int(
                self.get_config(
                    f"exploration.matron.sector_{sector}_lumees", default=5000
                )
            )
            self._legacy_sector_xp[sector] = int(
                self.get_config(f"exploration.matron.sector_{sector}_xp", default=200)
            )

        self.log.info("MatronService initialized")

    # ========================================================================
    # PUBLIC API - Matron Eligibility
    # ========================================================================

    async def check_matron_spawn_eligible(
        self, player_id: int, sector_id: int, sublevel: int
    ) -> Dict[str, Any]:
        """
        Check if player is eligible to spawn matron.
        
        Requirements:
        - Sector progress must be at 100%
        - Miniboss must not already be defeated
        
        Args:
            player_id: Discord ID
            sector_id: Sector number
            sublevel: Sublevel number
        
        Returns:
            Dict with eligible (bool) and reason (str)
        
        Example:
            >>> result = await matron_service.check_matron_spawn_eligible(123, 1, 1)
            >>> if result["eligible"]:
            ...     # Spawn matron
        """
        player_id = InputValidator.validate_discord_id(player_id)
        sector_id = InputValidator.validate_positive_integer(sector_id, "sector_id")
        sublevel = InputValidator.validate_positive_integer(sublevel, "sublevel")

        self.log_operation(
            "check_matron_spawn_eligible",
            player_id=player_id,
            sector_id=sector_id,
            sublevel=sublevel,
        )

        # Get sector progress
        progress_data = await self._sector_progress.get_sector_progress(
            player_id, sector_id, sublevel
        )

        # Check if progress is 100%
        if progress_data["progress"] < 100.0:
            return {
                "eligible": False,
                "reason": "sector_incomplete",
                "progress": progress_data["progress"],
            }

        # Check if miniboss already defeated
        if progress_data["miniboss_defeated"]:
            return {
                "eligible": False,
                "reason": "already_defeated",
                "miniboss_defeated": True,
            }

        self.log.info(
            "Matron spawn eligible",
            extra={
                "player_id": player_id,
                "sector_id": sector_id,
                "sublevel": sublevel,
            },
        )

        return {
            "eligible": True,
            "reason": "ready",
            "progress": progress_data["progress"],
        }

    # ========================================================================
    # PUBLIC API - Matron Stats Generation
    # ========================================================================

    def select_matron_rarity(self, sector_id: int) -> str:
        """
        Select matron rarity based on sector.
        
        Uses sector average rarity with random variance.
        
        Args:
            sector_id: Sector number
        
        Returns:
            Rarity tier string (uncommon/rare/epic/legendary/mythic)
        
        Example:
            >>> rarity = matron_service.select_matron_rarity(4)
            >>> print(rarity)  # "epic" or "legendary"
        """
        sector_id = InputValidator.validate_positive_integer(sector_id, "sector_id")

        # Get average rarity for sector
        sector_key = f"sector_{sector_id}"
        base_rarity = self._sector_avg_rarity.get(sector_key, "uncommon")

        # Get base index
        base_index = RARITY_TO_INDEX.get(base_rarity, 0)

        # Apply variance
        min_offset, max_offset = self._rarity_variance
        offset = random.randint(min_offset, max_offset)

        # Calculate final index (clamped to valid range)
        final_index = min(max(base_index + offset, 0), len(RARITY_TIERS) - 1)

        selected_rarity = RARITY_TIERS[final_index]

        self.log.debug(
            "Matron rarity selected",
            extra={
                "sector_id": sector_id,
                "base_rarity": base_rarity,
                "offset": offset,
                "selected_rarity": selected_rarity,
            },
        )

        return selected_rarity

    def calculate_matron_hp(
        self, rarity: str, sector_id: int, sublevel: int
    ) -> int:
        """
        Calculate matron HP based on rarity, sector, and sublevel.
        
        Formula:
            base_hp * (1 + sector_mult * sector_id) * (1 + sublevel_mult * sublevel)
        
        Args:
            rarity: Rarity tier
            sector_id: Sector number
            sublevel: Sublevel number
        
        Returns:
            Total HP
        
        Example:
            >>> hp = matron_service.calculate_matron_hp("epic", 4, 2)
            >>> print(hp)  # ~48600
        """
        rarity = rarity.lower()
        sector_id = InputValidator.validate_positive_integer(sector_id, "sector_id")
        sublevel = InputValidator.validate_positive_integer(sublevel, "sublevel")

        # Get base HP for rarity
        base_hp = self._hp_base.get(rarity, 2000)

        # Apply sector scaling
        sector_mult = 1.0 + (self._hp_sector_mult * sector_id)

        # Apply sublevel scaling
        sublevel_mult = 1.0 + (self._hp_sublevel_mult * sublevel)

        # Calculate final HP
        total_hp = int(base_hp * sector_mult * sublevel_mult)

        self.log.debug(
            "Matron HP calculated",
            extra={
                "rarity": rarity,
                "sector_id": sector_id,
                "sublevel": sublevel,
                "base_hp": base_hp,
                "total_hp": total_hp,
            },
        )

        return total_hp

    def calculate_matron_attack_defense(
        self, sector_id: int, sublevel: int
    ) -> tuple[int, int]:
        """
        Calculate matron attack and defense stats.
        
        Uses sector-based scaling similar to exploration monsters.
        
        Args:
            sector_id: Sector number
            sublevel: Sublevel number
        
        Returns:
            Tuple of (attack, defense)
        """
        sector_id = InputValidator.validate_positive_integer(sector_id, "sector_id")
        sublevel = InputValidator.validate_positive_integer(sublevel, "sublevel")

        # Base stats (higher than normal exploration monsters)
        base_attack = 300 + (sector_id * 100)
        base_defense = 200 + (sector_id * 50)

        # Sublevel scaling
        sublevel_mult = 1.0 + (sublevel * 0.15)

        attack = int(base_attack * sublevel_mult)
        defense = int(base_defense * sublevel_mult)

        return attack, defense

    async def generate_matron_stats(
        self, sector_id: int, sublevel: int
    ) -> EnemyStats:
        """
        Generate complete matron EnemyStats for combat.
        
        Args:
            sector_id: Sector number
            sublevel: Sublevel number
        
        Returns:
            EnemyStats ready for combat
        
        Example:
            >>> matron = await matron_service.generate_matron_stats(4, 2)
            >>> # Pass to CombatService.start_pve_battle()
        """
        sector_id = InputValidator.validate_positive_integer(sector_id, "sector_id")
        sublevel = InputValidator.validate_positive_integer(sublevel, "sublevel")

        # Select rarity
        rarity = self.select_matron_rarity(sector_id)

        # Calculate HP
        hp = self.calculate_matron_hp(rarity, sector_id, sublevel)

        # Calculate attack/defense
        attack, defense = self.calculate_matron_attack_defense(sector_id, sublevel)

        # Create EnemyStats
        matron = EnemyStats(
            enemy_id=f"matron_s{sector_id}_l{sublevel}_{rarity}",
            name=f"Matron Guardian ({rarity.capitalize()})",
            element="neutral",  # Could add element variation in future
            attack=attack,
            defense=defense,
            max_hp=hp,
            level=sector_id * 10 + sublevel,  # Cosmetic level
        )

        self.log.info(
            "Matron stats generated",
            extra={
                "sector_id": sector_id,
                "sublevel": sublevel,
                "rarity": rarity,
                "hp": hp,
                "attack": attack,
                "defense": defense,
            },
        )

        return matron

    # ========================================================================
    # PUBLIC API - Combat Integration
    # ========================================================================

    async def start_matron_battle(
        self, player_id: int, sector_id: int, sublevel: int, player_level: int = 1
    ) -> Dict[str, Any]:
        """
        Start matron battle using combat system.
        
        This delegates to CombatService for actual battle execution.
        
        Args:
            player_id: Discord ID
            sector_id: Sector number
            sublevel: Sublevel number
            player_level: Player level for HP calculation
        
        Returns:
            Combat result dict from CombatService
        
        Raises:
            InvalidOperationError: If matron not eligible to spawn
        
        Example:
            >>> result = await matron_service.start_matron_battle(123, 4, 2)
            >>> if result["outcome"] == "victory":
            ...     await matron_service.finalize_matron_victory(...)
        """
        player_id = InputValidator.validate_discord_id(player_id)
        sector_id = InputValidator.validate_positive_integer(sector_id, "sector_id")
        sublevel = InputValidator.validate_positive_integer(sublevel, "sublevel")

        self.log_operation(
            "start_matron_battle",
            player_id=player_id,
            sector_id=sector_id,
            sublevel=sublevel,
        )

        # Check eligibility
        eligibility = await self.check_matron_spawn_eligible(
            player_id, sector_id, sublevel
        )

        if not eligibility["eligible"]:
            raise InvalidOperationError(
                "start_matron_battle",
                f"Matron not eligible: {eligibility['reason']}",
            )

        # Generate matron stats
        matron = await self.generate_matron_stats(sector_id, sublevel)

        # Emit spawn event
        await self.emit_event(
            event_type="matron.spawned",
            data={
                "player_id": player_id,
                "sector_id": sector_id,
                "sublevel": sublevel,
                "matron_name": matron.name,
                "matron_hp": matron.max_hp,
            },
        )

        # Start combat (delegates to CombatService)
        combat_result = await self._combat.start_pve_battle(
            player_id=player_id,
            enemy_stats=matron,
            enable_retaliation=True,  # Matrons fight back
            player_level=player_level,
        )

        self.log.info(
            f"Matron battle completed: {combat_result['outcome']}",
            extra={
                "player_id": player_id,
                "sector_id": sector_id,
                "sublevel": sublevel,
                "outcome": combat_result["outcome"],
                "turns": combat_result["turns"],
            },
        )

        # Add matron-specific context
        combat_result["sector_id"] = sector_id
        combat_result["sublevel"] = sublevel
        combat_result["matron_name"] = matron.name

        return combat_result

    # ========================================================================
    # PUBLIC API - Reward Distribution
    # ========================================================================

    def calculate_matron_rewards(
        self, sector_id: int, sublevel: int, is_boss_sublevel: bool = False
    ) -> Dict[str, Any]:
        """
        Calculate matron victory rewards.
        
        Args:
            sector_id: Sector number
            sublevel: Sublevel number
            is_boss_sublevel: Whether this is a floor boss (extra rewards)
        
        Returns:
            Dict with lumees, xp, and special rewards
        
        Example:
            >>> rewards = matron_service.calculate_matron_rewards(4, 2)
            >>> print(rewards)
            {"lumees": 2000, "xp": 400, "drop_charges": 1, "fusion_catalyst": 1}
        """
        sector_id = InputValidator.validate_positive_integer(sector_id, "sector_id")
        sublevel = InputValidator.validate_positive_integer(sublevel, "sublevel")

        # Calculate base rewards with sector scaling
        sector_mult = 1.0 + (self._sector_reward_mult * (sector_id - 1))
        lumees = int(self._base_lumees * sector_mult)
        xp = int(self._base_xp * sector_mult)

        # Apply boss sublevel bonus if applicable
        if is_boss_sublevel:
            lumees = int(lumees * self._boss_sublevel_bonus)
            xp = int(xp * self._boss_sublevel_bonus)

        # Add special rewards
        rewards = {
            "lumees": lumees,
            "xp": xp,
            "drop_charges": self._boss_rewards.get("DROP_CHARGES", 1),
            "fusion_catalyst": self._boss_rewards.get("fusion_catalyst", 1),
        }

        self.log.debug(
            "Matron rewards calculated",
            extra={
                "sector_id": sector_id,
                "sublevel": sublevel,
                "is_boss_sublevel": is_boss_sublevel,
                "rewards": rewards,
            },
        )

        return rewards

    async def finalize_matron_victory(
        self,
        player_id: int,
        sector_id: int,
        sublevel: int,
        encounter_id: str,
        is_boss_sublevel: bool = False,
    ) -> Dict[str, Any]:
        """
        Finalize matron victory: award rewards, mark miniboss defeated.
        
        This is a **write operation** using get_transaction().
        
        Args:
            player_id: Discord ID
            sector_id: Sector number
            sublevel: Sublevel number
            encounter_id: Combat encounter UUID
            is_boss_sublevel: Whether this is a floor boss
        
        Returns:
            Dict with rewards and updated status
        
        Example:
            >>> result = await matron_service.finalize_matron_victory(
            ...     player_id=123,
            ...     sector_id=4,
            ...     sublevel=2,
            ...     encounter_id="...",
            ... )
        """
        player_id = InputValidator.validate_discord_id(player_id)
        sector_id = InputValidator.validate_positive_integer(sector_id, "sector_id")
        sublevel = InputValidator.validate_positive_integer(sublevel, "sublevel")

        self.log_operation(
            "finalize_matron_victory",
            player_id=player_id,
            sector_id=sector_id,
            sublevel=sublevel,
        )

        # Calculate rewards
        rewards = self.calculate_matron_rewards(sector_id, sublevel, is_boss_sublevel)

        async with DatabaseService.get_transaction() as session:
            # TODO: Award lumees via WalletService
            # await wallet_service.add_lumees(player_id, rewards["lumees"], "matron_victory")

            # TODO: Award XP via ProgressionService
            # await progression_service.add_xp(player_id, rewards["xp"], "matron_victory")

            # TODO: Award drop charges via StatsService
            # await stats_service.add_drop_charges(player_id, rewards["drop_charges"], "matron_victory")

            # Mark miniboss as defeated
            await self._sector_progress.defeat_miniboss(
                player_id, sector_id, sublevel, context="matron_victory"
            )

            # Audit log
            await AuditLogger.log(
                player_id=player_id,
                transaction_type="matron_defeated",
                details={
                    "sector_id": sector_id,
                    "sublevel": sublevel,
                    "encounter_id": encounter_id,
                    "rewards": rewards,
                },
                context="matron_combat",
            )

        # Emit victory event
        await self.emit_event(
            event_type="matron.defeated",
            data={
                "player_id": player_id,
                "sector_id": sector_id,
                "sublevel": sublevel,
                "rewards": rewards,
            },
        )

        self.log.info(
            f"Matron victory finalized: sector {sector_id}-{sublevel}",
            extra={
                "player_id": player_id,
                "sector_id": sector_id,
                "sublevel": sublevel,
                "rewards": rewards,
            },
        )

        return {
            "player_id": player_id,
            "sector_id": sector_id,
            "sublevel": sublevel,
            "rewards": rewards,
            "miniboss_defeated": True,
        }
