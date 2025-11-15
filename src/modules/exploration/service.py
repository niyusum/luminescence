from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import secrets

from src.database.models.core.player import Player
from database.models.core.maiden_base import MaidenBase
from src.database.models.progression.sector_progress import SectorProgress
from src.core.config import ConfigManager
from src.modules.resource.service import ResourceService
from src.core.infra.transaction_logger import TransactionLogger
from src.core.exceptions import InsufficientResourcesError, InvalidOperationError
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class ExplorationService:
    """
    Sector exploration system with percentage-based progression.
    
    Manages sector/sublevel progression, maiden purification encounters,
    matron battles, and exploration rewards. Integrates with ResourceService
    for energy consumption and reward distribution.

    Features:
        - 7 sectors with 9 sublevels each
        - Dynamic progress rates (fast early, slow late)
        - Random maiden encounters with capture mechanics
        - Matron gates at 100% progress
        - Branching sector unlocks
    
    Usage:
        >>> result = await ExplorationService.explore_sublevel(session, player, sector_id=1, sublevel=1)
        >>> if result["maiden_encounter"]:
        >>>     success = await ExplorationService.attempt_purification(session, player, maiden_data, use_gems=False)
    """
    
    @staticmethod
    async def get_or_create_progress(
        session: AsyncSession,
        player_id: int,
        sector_id: int,
        sublevel: int
    ) -> SectorProgress:
        """
        Get existing progress or create new record for sector/sublevel.
        
        Args:
            session: Database session
            player_id: Discord ID
            sector_id: Sector number (1-7)
            sublevel: Sublevel number (1-9)
        
        Returns:
            SectorProgress record
        """
        result = await session.execute(
            select(SectorProgress).where(
                SectorProgress.player_id == player_id,
                SectorProgress.sector_id == sector_id,
                SectorProgress.sublevel == sublevel
            )
        )
        progress = result.scalar_one_or_none()
        
        if not progress:
            progress = SectorProgress(
                player_id=player_id,
                sector_id=sector_id,
                sublevel=sublevel
            )
            session.add(progress)
            await session.flush()
            logger.info(f"Created sector progress for player {player_id}: sector {sector_id}, sublevel {sublevel}")
        
        return progress
    
    @staticmethod
    async def get_unlocked_sectors(session: AsyncSession, player_id: int) -> List[int]:
        """
        Get list of sectors player has unlocked.
        
        Sector 1 always unlocked. Higher sectors require previous sector 100% completion.
        
        Returns:
            List of unlocked sector IDs
        """
        result = await session.execute(
            select(SectorProgress).where(
                SectorProgress.player_id == player_id
            )
        )
        all_progress = result.scalars().all()
        
        unlocked = [1]  # Sector 1 always available
        
        # Check each sector for completion
        for sector_id in range(2, 8):  # Check sectors 2-7
            previous_sector = sector_id - 1
            
            # Get all sublevels for previous sector
            prev_sector_progress = [
                p for p in all_progress 
                if p.sector_id == previous_sector
            ]
            
            # Need all 9 sublevels completed
            if len(prev_sector_progress) == 9:
                all_complete = all(p.is_complete() for p in prev_sector_progress)
                if all_complete:
                    unlocked.append(sector_id)
                else:
                    break  # Stop checking higher sectors
            else:
                break  # Stop checking higher sectors
        
        return unlocked
    
    @staticmethod
    def calculate_energy_cost(sector_id: int, sublevel: int) -> int:
        """
        Calculate energy cost for exploring specific sublevel.
        
        Cost increases per sector and per sublevel within sector.
        Boss sublevels (9) cost more.
        
        Returns:
            Energy cost
        """
        # LUMEN LAW I.6 - YAML is source of truth
        base_cost = ConfigManager.get(f"exploration_system.energy_costs.sector_{sector_id}_base")
        increment = ConfigManager.get("exploration_system.energy_costs.sublevel_increment")
        boss_mult = ConfigManager.get("exploration_system.energy_costs.boss_multiplier")
        
        cost = base_cost + (increment * (sublevel - 1))
        
        if sublevel == 9:
            cost = int(cost * boss_mult)
        
        return cost
    
    @staticmethod
    def calculate_progress_gain(sector_id: int, sublevel: int) -> float:
        """
        Calculate progress percentage gained per exploration.

        Early sectors progress faster. Matron sublevels progress slower.
        
        Returns:
            Progress percentage (0.0 - 100.0)
        """
        # LUMEN LAW I.6 - YAML is source of truth
        base_rate = ConfigManager.get(f"exploration_system.progress_rates.sector_{sector_id}")
        miniboss_mult = ConfigManager.get("exploration_system.miniboss_progress_multiplier")
        
        if sublevel == 9:
            return base_rate * miniboss_mult
        
        return base_rate
    
    @staticmethod
    def calculate_rewards(sector_id: int, sublevel: int) -> Dict[str, int]:
        """
        Calculate lumees and XP rewards for exploration.

        Scales with sector difficulty.

        Returns:
            Dictionary with 'lumees' and 'xp' keys
        """
        # Lumees rewards
        # LUMEN LAW I.6 - YAML is source of truth
        lumees_min = ConfigManager.get("exploration_system.lumees_rewards.sector_1_min")
        lumees_max = ConfigManager.get("exploration_system.lumees_rewards.sector_1_max")
        lumees_scaling = ConfigManager.get("exploration_system.lumees_rewards.sector_scaling")

        scaled_lumees_min = int(lumees_min * (lumees_scaling ** (sector_id - 1)))
        scaled_lumees_max = int(lumees_max * (lumees_scaling ** (sector_id - 1)))
        lumees = secrets.SystemRandom().randint(scaled_lumees_min, scaled_lumees_max)

        # XP rewards
        # LUMEN LAW I.6 - YAML is source of truth
        xp_min = ConfigManager.get("exploration_system.xp_rewards.sector_1_min")
        xp_max = ConfigManager.get("exploration_system.xp_rewards.sector_1_max")
        xp_scaling = ConfigManager.get("exploration_system.xp_rewards.sector_scaling")

        scaled_xp_min = int(xp_min * (xp_scaling ** (sector_id - 1)))
        scaled_xp_max = int(xp_max * (xp_scaling ** (sector_id - 1)))
        xp = secrets.SystemRandom().randint(scaled_xp_min, scaled_xp_max)

        return {"lumees": lumees, "xp": xp}
    
    @staticmethod
    def roll_maiden_encounter(sector_id: int) -> bool:
        """
        Roll for random maiden encounter during exploration.
        
        Higher sectors have higher encounter rates.
        
        Returns:
            True if maiden encountered
        """
        # LUMEN LAW I.6 - YAML is source of truth
        encounter_rate = ConfigManager.get(f"exploration_system.encounter_rates.sector_{sector_id}")
        roll = secrets.SystemRandom().random() * 100
        return roll < encounter_rate
    
    @staticmethod
    async def generate_encounter_maiden(
        session: AsyncSession,
        sector_id: int,
        player_level: int
    ) -> Dict[str, Any]:
        """
        Generate maiden data for purification encounter.

        Uses actual MaidenBase data with sector-appropriate tier ranges.
        Maidens are selected from database using weighted random selection
        based on rarity_weight, filtered by sector-appropriate tiers.

        Args:
            session: Database session for MaidenBase queries
            sector_id: Current sector (1-7), determines tier range
            player_level: Player level, influences tier selection

        Returns:
            Dictionary with maiden info for encounter UI:
                - maiden_base_id: Database ID of MaidenBase
                - name: Maiden name
                - element: Element type
                - tier: Encounter tier
                - rarity: Rarity category
                - sector_id: Origin sector

        LUMEN LAW Compliance:
            - Article III: Pure business logic, no UI dependencies
            - Article IV: Tier ranges from ConfigManager
            - Article VII: Reuses gacha weight system
        """
        # LUMEN LAW I.6 - YAML is source of truth
        # Get tier range from config (T1-T12 from maiden/constants.py)
        tier_range = ConfigManager.get(f"exploration_system.sector_tier_ranges.sector_{sector_id}")
        min_tier, max_tier = tier_range[0], tier_range[1]

        # Adjust tier based on player level (higher level = can encounter higher tiers)
        level_bonus = player_level // 10
        max_tier = min(max_tier + level_bonus, 12)  # Updated to T12

        # Query MaidenBase for appropriate tier range
        stmt = select(MaidenBase).where(
            MaidenBase.base_tier >= min_tier,
            MaidenBase.base_tier <= max_tier
        )
        maiden_bases = (await session.exec(stmt)).all()

        if not maiden_bases:
            logger.warning(
                f"No maiden bases found for sector {sector_id} tier range {min_tier}-{max_tier}, "
                "falling back to T1"
            )
            stmt = select(MaidenBase).where(MaidenBase.base_tier == 1)
            maiden_bases = (await session.exec(stmt)).all()

            if not maiden_bases:
                raise ValueError("No maiden bases exist in database - seed data required")

        # Weighted random selection based on rarity_weight
        # Lower weight = rarer = less likely to appear
        weights = [mb.rarity_weight for mb in maiden_bases]
        selected_maiden_base = secrets.SystemRandom().choices(maiden_bases, weights=weights, k=1)[0]

        # Map tier to rarity name (from maiden/constants.py Tier names)
        # T1=Common, T2=Uncommon, T3=Rare, T4=Epic, T5=Mythic, T6=Divine,
        # T7=Legendary, T8=Ethereal, T9=Genesis, T10=Empyrean, T11=Void, T12=Singularity
        tier_to_rarity = {
            1: "common",
            2: "uncommon",
            3: "rare",
            4: "epic",
            5: "mythic",
            6: "divine",
            7: "legendary",
            8: "ethereal",
            9: "genesis",
            10: "empyrean",
            11: "void",
            12: "singularity",
        }

        rarity = tier_to_rarity.get(selected_maiden_base.base_tier, "common")

        logger.debug(
            f"Generated encounter maiden: {selected_maiden_base.name} "
            f"T{selected_maiden_base.base_tier} ({rarity}) in sector {sector_id}"
        )

        return {
            "maiden_base_id": selected_maiden_base.id,
            "name": selected_maiden_base.name,
            "element": selected_maiden_base.element,
            "tier": selected_maiden_base.base_tier,
            "rarity": rarity,
            "sector_id": sector_id,
        }
    
    @staticmethod
    def calculate_capture_rate(maiden_rarity: str, player_level: int, sector_id: int) -> float:
        """
        Calculate purification success rate.

        Formula: base_rate - sector_penalty + level_bonus
        - Higher sectors = harder to capture (penalty)
        - Higher player level = easier to capture (bonus)

        Returns:
            Capture rate percentage (0.0 - 100.0)
        """
        # LUMEN LAW I.6 - YAML is source of truth
        base_rate = ConfigManager.get(f"exploration_system.capture_rates.{maiden_rarity}")
        sector_penalty = ConfigManager.get(f"exploration_system.sector_capture_penalty.sector_{sector_id}")
        level_modifier_per_level = ConfigManager.get("exploration_system.capture_level_modifier")

        # Player level advantage (based on sector recommended level)
        sector_recommended_level = sector_id * 10  # Rough estimate
        level_diff = player_level - sector_recommended_level
        level_bonus = level_diff * level_modifier_per_level

        # Final calculation: base - sector_penalty + level_bonus
        final_rate = base_rate - sector_penalty + level_bonus
        return max(5.0, min(95.0, final_rate))  # Clamp 5-95%
    
    @staticmethod
    def get_guaranteed_purification_cost(maiden_rarity: str) -> int:
        """
        Get gem cost for guaranteed maiden purification.
        
        Returns:
            Gem cost
        """
        # LUMEN LAW I.6 - YAML is source of truth
        return ConfigManager.get(f"exploration_system.guaranteed_purification_costs.{maiden_rarity}")
    
    @staticmethod
    async def explore_sublevel(
        session: AsyncSession,
        player: Player,
        sector_id: int,
        sublevel: int
    ) -> Dict[str, Any]:
        """
        Process single exploration attempt in sector sublevel.

        Consumes energy, grants rewards, adds progress, rolls for encounters.
        Automatically spawns matron when progress reaches 100%.

        Args:
            session: Database session
            player: Player object (with_for_update=True)
            sector_id: Target sector
            sublevel: Target sublevel

        Returns:
            Dictionary with:
                - energy_cost: Energy consumed
                - lumees_gained: Lumees rewarded
                - xp_gained: XP rewarded
                - progress_gained: Progress % added
                - current_progress: New progress %
                - maiden_encounter: Maiden data dict if encountered, else None
                - matron_spawn: Matron data dict if progress hit 100%, else None

        Raises:
            InsufficientResourcesError: Not enough energy
            InvalidOperationError: Sector/sublevel not unlocked or already complete
        """
        # Validate unlock status
        unlocked_sectors = await ExplorationService.get_unlocked_sectors(session, player.discord_id)
        if sector_id not in unlocked_sectors:
            raise InvalidOperationError(f"Sector {sector_id} is not unlocked")
        
        # Get progress
        progress = await ExplorationService.get_or_create_progress(
            session, player.discord_id, sector_id, sublevel
        )
        
        # Check if already complete
        if progress.is_complete():
            raise InvalidOperationError(f"Sector {sector_id}, Sublevel {sublevel} is already complete")
        
        # Calculate costs and rewards
        energy_cost = ExplorationService.calculate_energy_cost(sector_id, sublevel)
        
        # Validate energy
        if player.energy < energy_cost:
            raise InsufficientResourcesError(
                resource="energy",
                required=energy_cost,
                current=player.energy
            )
        
        # Consume energy
        player.energy -= energy_cost
        
        # Calculate rewards
        rewards = ExplorationService.calculate_rewards(sector_id, sublevel)
        
        # Grant rewards via ResourceService
        await ResourceService.grant_resources(
            session=session,
            player=player,
            lumees=rewards["lumees"],
            context="exploration",
            details={"sector": sector_id, "sublevel": sublevel}
        )
        
        # Add progress
        progress_gain = ExplorationService.calculate_progress_gain(sector_id, sublevel)
        progress.progress = min(100.0, progress.progress + progress_gain)
        progress.times_explored += 1
        progress.total_lumees_earned += rewards["lumees"]
        progress.total_xp_earned += rewards["xp"]
        progress.last_explored = datetime.utcnow()
        
        # Roll for maiden encounter (only if not at 100% yet)
        maiden_encounter = None
        if progress.progress < 100.0:
            if ExplorationService.roll_maiden_encounter(sector_id):
                maiden_encounter = await ExplorationService.generate_encounter_maiden(session, sector_id, player.level)
        
        # Update daily quest
        from src.modules.daily.service import DailyService
        await DailyService.update_quest_progress(
            session, player.discord_id, "spend_energy", energy_cost
        )
        
        # Log transaction
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player.discord_id,
            transaction_type="exploration",
            details={
                "sector": sector_id,
                "sublevel": sublevel,
                "energy_cost": energy_cost,
                "lumees": rewards["lumees"],
                "xp": rewards["xp"],
                "progress_gain": progress_gain,
                "new_progress": progress.progress,
                "maiden_encountered": maiden_encounter is not None
            },
            context="explore_command"
        )
        
        # Check if matron should spawn (progress hit 100%)
        matron_spawn = None
        if progress.progress >= 100.0 and not progress.miniboss_defeated:
            from src.modules.exploration.matron_logic import MatronService
            matron_spawn = MatronService.generate_matron(sector_id, sublevel)
            logger.info(
                f"Player {player.discord_id} completed sector {sector_id} sublevel {sublevel}: "
                f"Matron {matron_spawn['name']} spawned!"
            )

        logger.info(
            f"Player {player.discord_id} explored sector {sector_id} sublevel {sublevel}: "
            f"+{progress_gain:.1f}% progress (now {progress.progress:.1f}%), "
            f"+{rewards['lumees']} lumees, encounter={maiden_encounter is not None}"
        )

        await session.flush()

        return {
            "energy_cost": energy_cost,
            "lumees_gained": rewards["lumees"],
            "xp_gained": rewards["xp"],
            "progress_gained": progress_gain,
            "current_progress": progress.progress,
            "maiden_encounter": maiden_encounter,
            "matron_spawn": matron_spawn
        }
    
    @staticmethod
    async def attempt_purification(
        session: AsyncSession,
        player: Player,
        maiden_data: Dict[str, Any],
        use_gems: bool = False
    ) -> Dict[str, Any]:
        """
        Attempt to purify encountered maiden.
        
        Either RNG-based capture or guaranteed with gems.
        
        Args:
            session: Database session
            player: Player object (with_for_update=True)
            maiden_data: Maiden info from encounter
            use_gems: If True, use gems for guaranteed capture
        
        Returns:
            Dictionary with:
                - success: Whether purification succeeded
                - capture_rate: Roll percentage (if RNG)
                - gem_cost: Gems spent (if guaranteed)
                - maiden_data: Full maiden info
        
        Raises:
            InsufficientResourcesError: Not enough gems for guaranteed
        """
        rarity = maiden_data["rarity"]
        
        if use_gems:
            # Guaranteed purification
            gem_cost = ExplorationService.get_guaranteed_purification_cost(rarity)
            
            if player.lumenite < gem_cost:
                raise InsufficientResourcesError(
                    resource="lumenite",
                    required=gem_cost,
                    current=player.lumenite
                )
            
            player.lumenite -= gem_cost
            success = True
            
            await TransactionLogger.log_transaction(
                session=session,
                player_id=player.discord_id,
                transaction_type="purification_guaranteed",
                details={
                    "maiden": maiden_data,
                    "gem_cost": gem_cost
                },
                context="purify_command"
            )
            
            logger.info(f"Player {player.discord_id} used {gem_cost} gems for guaranteed purification ({rarity})")
            
            return {
                "success": True,
                "capture_rate": 100.0,
                "gem_cost": gem_cost,
                "maiden_data": maiden_data
            }
        
        else:
            # RNG-based purification
            capture_rate = ExplorationService.calculate_capture_rate(
                rarity, player.level, maiden_data["sector_id"]
            )
            
            roll = secrets.SystemRandom().random() * 100
            success = roll < capture_rate
            
            await TransactionLogger.log_transaction(
                session=session,
                player_id=player.discord_id,
                transaction_type="purification_attempt",
                details={
                    "maiden": maiden_data,
                    "capture_rate": capture_rate,
                    "roll": roll,
                    "success": success
                },
                context="purify_command"
            )
            
            logger.info(
                f"Player {player.discord_id} purification attempt: "
                f"{capture_rate:.1f}% rate, roll {roll:.1f}, success={success}"
            )
            
            return {
                "success": success,
                "capture_rate": capture_rate,
                "gem_cost": 0,
                "maiden_data": maiden_data
            }