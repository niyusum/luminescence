from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import math

from src.database.models.core.player import Player
from src.core.config.config_manager import ConfigManager
from src.core.infra.transaction_logger import TransactionLogger
from src.core.config.config import Config
from src.core.exceptions import InsufficientResourcesError
from src.core.logging.logger import get_logger
from src.features.resource.service import ResourceService

logger = get_logger(__name__)


class PlayerService:
    """
    Core service for player operations and resource management.

    Handles player lifecycle, resource regeneration, experience/leveling,
    prayer system, and activity tracking. All player state changes must
    go through this service (RIKI LAW Article I.7).

    Key Responsibilities:
        - Resource regeneration (energy, stamina, prayer charges)
        - Experience and leveling with milestone rewards
        - Prayer system with class bonuses
        - Activity tracking and scoring
    """

    # =========================================================================
    # PLAYER RETRIEVAL AND REGENERATION
    # =========================================================================
    @staticmethod
    async def get_player_with_regen(
        session: AsyncSession,
        discord_id: int,
        lock: bool = True
    ) -> Optional[Player]:
        """
        Get player and regenerate all resources automatically.

        Regenerates energy, stamina, and prayer charges based on time elapsed
        since last activity. Updates last_active timestamp.
        """
        if lock:
            player = await session.get(Player, discord_id, with_for_update=True)
        else:
            result = await session.execute(
                select(Player).where(Player.discord_id == discord_id)
            )
            player = result.scalar_one_or_none()

        if not player:
            return None

        PlayerService.regenerate_all_resources(player)
        player.update_activity()
        return player

    # =========================================================================
    # RESOURCE REGENERATION
    # =========================================================================
    @staticmethod
    def regenerate_all_resources(player: Player) -> Dict[str, Any]:
        """Regenerate energy, stamina, and prayer charges based on elapsed time."""
        prayer_regen = PlayerService.regenerate_prayer_charges(player)
        energy_regen = PlayerService.regenerate_energy(player)
        stamina_regen = PlayerService.regenerate_stamina(player)

        return {
            "prayer_charges_gained": prayer_regen,
            "energy_gained": energy_regen,
            "stamina_gained": stamina_regen,
            "total_regenerated": prayer_regen + energy_regen + stamina_regen,
        }

    @staticmethod
    def regenerate_prayer_charges(player: Player) -> int:
        """
        Regenerate prayer charges based on time since last regen.

        UPDATED SYSTEM (NO ACCUMULATION):
        - If 5 minutes passed since last prayer → set charges to 1
        - Does NOT accumulate multiple charges
        - Always 1 charge available every 5 minutes (no storage)
        """
        if player.prayer_charges >= 1:
            return 0

        if player.last_prayer_regen is None:
            player.last_prayer_regen = datetime.utcnow()
            return 0

        regen_interval = ConfigManager.get("prayer_system.regen_minutes", 5) * 60
        time_since = (datetime.utcnow() - player.last_prayer_regen).total_seconds()

        # If 5 minutes passed, grant 1 charge (no accumulation)
        if time_since >= regen_interval:
            player.prayer_charges = 1
            player.last_prayer_regen = datetime.utcnow()
            return 1

        return 0

    @staticmethod
    def regenerate_energy(player: Player) -> int:
        """Regenerate energy based on time since last activity."""
        if player.energy >= player.max_energy:
            return 0

        regen_minutes = ConfigManager.get("energy_system.regen_minutes", 5)
        if player.player_class == "adapter":
            regen_minutes *= 0.75

        regen_interval = regen_minutes * 60
        time_since = (datetime.utcnow() - player.last_active).total_seconds()
        energy_to_regen = int(time_since // regen_interval)

        if energy_to_regen > 0:
            energy_regenerated = min(energy_to_regen, player.max_energy - player.energy)
            player.energy += energy_regenerated
            return energy_regenerated

        return 0

    @staticmethod
    def regenerate_stamina(player: Player) -> int:
        """Regenerate stamina based on time since last activity."""
        if player.stamina >= player.max_stamina:
            return 0

        regen_minutes = ConfigManager.get("stamina_system.regen_minutes", 10)
        if player.player_class == "destroyer":
            regen_minutes *= 0.75

        regen_interval = regen_minutes * 60
        time_since = (datetime.utcnow() - player.last_active).total_seconds()
        stamina_to_regen = int(time_since // regen_interval)

        if stamina_to_regen > 0:
            stamina_regenerated = min(stamina_to_regen, player.max_stamina - player.stamina)
            player.stamina += stamina_regenerated
            return stamina_regenerated

        return 0

    # =========================================================================
    # PRAYER SYSTEM (DEPRECATED - Use PrayerService)
    # =========================================================================
    # NOTE: Prayer logic has been moved to src.features.prayer.service.PrayerService
    # This method is kept for backwards compatibility only and will be removed in future versions.

    # =========================================================================
    # EXPERIENCE AND LEVELING
    # =========================================================================
    @staticmethod
    def get_xp_for_next_level(level: int) -> int:
        """Calculate XP required to reach the next level."""
        curve_cfg = ConfigManager.get("xp_curve", {})
        curve_type = curve_cfg.get("type", "polynomial")
        base = curve_cfg.get("base", 50)
        exponent = curve_cfg.get("exponent", 2.2)

        if curve_type == "exponential":
            return int(base * (1.5 ** (level - 1)))
        elif curve_type == "polynomial":
            return int(base * (level ** exponent))
        elif curve_type == "logarithmic":
            return int(500 * level * math.log(level + 1))
        else:
            return int(base * (1.5 ** (level - 1)))

    @staticmethod
    async def add_xp_and_level_up(
        player: Player,
        xp_amount: int,
        allow_overcap: bool = True
    ) -> Dict[str, Any]:
        """
        Award experience and handle automatic level-ups.

        Grants XP and automatically levels up player if threshold exceeded.
        Handles milestone rewards (every 5/10 levels) and resource refresh.
        Can grant bonus energy/stamina if near-full (overcap system).
        """
        player.experience += xp_amount
        leveled_up = False
        levels_gained = 0
        overcap_energy = 0
        overcap_stamina = 0
        milestone_rewards = {}

        loop_safety = 0
        max_loops = Config.MAX_LEVEL_UPS_PER_TRANSACTION

        milestones_cfg = ConfigManager.get("level_milestones", {})
        minor_interval = milestones_cfg.get("minor_interval", 5)
        major_interval = milestones_cfg.get("major_interval", 10)
        minor_rewards_cfg = milestones_cfg.get("minor_rewards", {})
        major_rewards_cfg = milestones_cfg.get("major_rewards", {})

        while player.experience >= PlayerService.get_xp_for_next_level(player.level):
            loop_safety += 1
            if loop_safety > max_loops:
                logger.error(
                    f"XP loop safety cap hit for player {player.discord_id} "
                    f"at level {player.level}. Check XP curve configuration."
                )
                break

            xp_needed = PlayerService.get_xp_for_next_level(player.level)
            player.experience -= xp_needed
            player.level += 1
            levels_gained += 1
            leveled_up = True

            player.last_level_up = datetime.utcnow()
            player.stats["level_ups"] = player.stats.get("level_ups", 0) + 1

            # Handle overcap bonuses
            if allow_overcap:
                old_energy = player.energy
                old_stamina = player.stamina

                player.energy = player.max_energy
                player.stamina = player.max_stamina

                # Get overcap configuration values
                overcap_threshold = ConfigManager.get("energy_system.overcap_threshold", 0.9)
                overflow_bonus = ConfigManager.get("energy_system.overcap_bonus", 0.10)

                if old_energy >= player.max_energy * overcap_threshold:
                    overcap_energy = int(player.max_energy * overflow_bonus)
                    player.energy += overcap_energy
                    player.stats["overflow_energy_gained"] = \
                        player.stats.get("overflow_energy_gained", 0) + overcap_energy

                if old_stamina >= player.max_stamina * overcap_threshold:
                    overcap_stamina = int(player.max_stamina * overflow_bonus)
                    player.stamina += overcap_stamina
                    player.stats["overflow_stamina_gained"] = \
                        player.stats.get("overflow_stamina_gained", 0) + overcap_stamina
            else:
                player.energy = player.max_energy
                player.stamina = player.max_stamina

            # Minor milestone
            if player.level % minor_interval == 0:
                rikis_mult = minor_rewards_cfg.get("rikis_multiplier", 100)
                grace_amt = minor_rewards_cfg.get("grace", 5)
                gems_div = minor_rewards_cfg.get("gems_divisor", 10)

                milestone_rewards[f"level_{player.level}"] = {
                    "rikis": player.level * rikis_mult,
                    "grace": grace_amt,
                    "riki_gems": player.level // gems_div
                }

            # Major milestone
            if player.level % major_interval == 0:
                rikis_mult = major_rewards_cfg.get("rikis_multiplier", 500)
                grace_amt = major_rewards_cfg.get("grace", 10)
                gems_amt = major_rewards_cfg.get("gems", 5)
                energy_inc = major_rewards_cfg.get("max_energy_increase", 10)
                stamina_inc = major_rewards_cfg.get("max_stamina_increase", 5)

                milestone_rewards[f"level_{player.level}_major"] = {
                    "rikis": player.level * rikis_mult,
                    "grace": grace_amt,
                    "riki_gems": gems_amt,
                    "max_energy_increase": energy_inc,
                    "max_stamina_increase": stamina_inc
                }

        return {
            "leveled_up": leveled_up,
            "levels_gained": levels_gained,
            "new_level": player.level,
            "refreshed_resources": leveled_up,
            "overcap_energy": overcap_energy,
            "overcap_stamina": overcap_stamina,
            "milestone_rewards": milestone_rewards,
            "safety_cap_hit": loop_safety > max_loops
        }

    # =========================================================================
    # UTILITY / METRICS
    # =========================================================================
    @staticmethod
    def can_redeem_shards(player: Player, tier: int) -> bool:
        """Check if player has enough shards for guaranteed fusion at tier."""
        shards_needed = ConfigManager.get("shard_system.shards_for_redemption", 10)
        return player.get_fusion_shards(tier) >= shards_needed

    @staticmethod
    def calculate_activity_score(player: Player) -> float:
        """Calculate player activity score (0–100) based on engagement."""
        score = 0
        time_since_active = datetime.utcnow() - player.last_active

        if time_since_active < timedelta(hours=1):
            score += 40
        elif time_since_active < timedelta(days=1):
            score += 30
        elif time_since_active < timedelta(days=3):
            score += 20
        elif time_since_active < timedelta(days=7):
            score += 10

        score += min(20, player.level)

        if player.total_fusions > 100:
            score += 20
        elif player.total_fusions > 50:
            score += 15
        elif player.total_fusions > 10:
            score += 10
        elif player.total_fusions > 0:
            score += 5

        score += min(20, player.unique_maidens)
        return min(100, score)

    @staticmethod
    def calculate_days_since_level_up(player: Player) -> Optional[int]:
        """Return number of days since player's last level-up."""
        if player.last_level_up is None:
            return None
        delta = datetime.utcnow() - player.last_level_up
        return delta.days
