"""
Player stat allocation system.

Manages allocation points, validation, and stat calculation.
Level ups grant 5 points that can be allocated to Energy, Stamina, or HP.

RIKI LAW Compliance:
- Article III: Pure business logic service
- Article I.6: Session-first parameter pattern
- Article IV: ConfigManager for ratios
- Article II: Transaction logging
- Article VII: Domain exceptions only
"""

from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.core.player import Player
from src.core.transaction_logger import TransactionLogger
from src.core.exceptions import InvalidOperationError
from src.core.logger import get_logger

logger = get_logger(__name__)


class AllocationService:
    """Stat allocation system for player customization."""
    
    @staticmethod
    async def allocate_points(
        session: AsyncSession,
        player: Player,
        energy: int = 0,
        stamina: int = 0,
        hp: int = 0
    ) -> Dict[str, Any]:
        """
        Allocate stat points to energy, stamina, or hp.
        
        Validates points available and applies allocation.
        Refreshes current values to new max (generous).
        
        Args:
            session: Database session
            player: Player object (must be with_for_update=True)
            energy: Points to allocate to energy
            stamina: Points to allocate to stamina
            hp: Points to allocate to hp
        
        Returns:
            {
                "allocated": {"energy": 2, "stamina": 1, "hp": 2},
                "new_max_stats": {"max_energy": 120, "max_stamina": 55, "max_hp": 700},
                "points_remaining": 0
            }
        
        Raises:
            InvalidOperationError: Insufficient points or invalid values
        """
        total_points = energy + stamina + hp
        
        # Validation
        if total_points == 0:
            raise InvalidOperationError("Must allocate at least 1 point")
        
        if any(v < 0 for v in [energy, stamina, hp]):
            raise InvalidOperationError("Cannot allocate negative points")
        
        if total_points > player.stat_points_available:
            raise InvalidOperationError(
                f"Insufficient points. Have {player.stat_points_available}, "
                f"trying to spend {total_points}"
            )
        
        # Update spent tracking
        player.stat_points_spent["energy"] += energy
        player.stat_points_spent["stamina"] += stamina
        player.stat_points_spent["hp"] += hp
        
        # Deduct available points
        player.stat_points_available -= total_points
        
        # Recalculate max stats
        max_stats = player.calculate_max_stats()
        player.max_energy = max_stats["max_energy"]
        player.max_stamina = max_stats["max_stamina"]
        player.max_hp = max_stats["max_hp"]
        
        # Refresh current values to new max (generous)
        player.energy = player.max_energy
        player.stamina = player.max_stamina
        player.hp = player.max_hp
        
        # Log transaction
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player.discord_id,
            transaction_type="stat_allocation",
            details={
                "allocated": {"energy": energy, "stamina": stamina, "hp": hp},
                "new_totals": player.stat_points_spent.copy(),
                "new_max_stats": max_stats,
                "points_remaining": player.stat_points_available
            },
            context="allocation_command"
        )
        
        logger.info(
            f"Player {player.discord_id} allocated stats: "
            f"energy={energy}, stamina={stamina}, hp={hp}, "
            f"remaining={player.stat_points_available}"
        )
        
        await session.flush()
        
        return {
            "allocated": {"energy": energy, "stamina": stamina, "hp": hp},
            "new_max_stats": max_stats,
            "points_remaining": player.stat_points_available
        }
    
    @staticmethod
    def get_allocation_preview(
        player: Player,
        energy: int = 0,
        stamina: int = 0,
        hp: int = 0
    ) -> Dict[str, Any]:
        """
        Preview stat changes without committing.
        
        Args:
            player: Player object
            energy: Points to preview
            stamina: Points to preview
            hp: Points to preview
        
        Returns:
            {
                "current_max": {"energy": 100, "stamina": 50, "hp": 500},
                "new_max": {"energy": 120, "stamina": 55, "hp": 700},
                "delta": {"energy": +20, "stamina": +5, "hp": +200},
                "cost": 5,
                "affordable": True
            }
        """
        total_cost = energy + stamina + hp
        
        current_max = {
            "energy": player.max_energy,
            "stamina": player.max_stamina,
            "hp": player.max_hp
        }
        
        new_max = {
            "energy": current_max["energy"] + (energy * Player.ENERGY_PER_POINT),
            "stamina": current_max["stamina"] + (stamina * Player.STAMINA_PER_POINT),
            "hp": current_max["hp"] + (hp * Player.HP_PER_POINT)
        }
        
        delta = {
            "energy": new_max["energy"] - current_max["energy"],
            "stamina": new_max["stamina"] - current_max["stamina"],
            "hp": new_max["hp"] - current_max["hp"]
        }
        
        return {
            "current_max": current_max,
            "new_max": new_max,
            "delta": delta,
            "cost": total_cost,
            "affordable": total_cost <= player.stat_points_available
        }
    
    @staticmethod
    def get_recommended_builds(level: int) -> Dict[str, Dict[str, Any]]:
        """
        Get recommended stat allocation builds for different playstyles.
        
        Args:
            level: Player level
        
        Returns:
            Dictionary of build name -> allocation breakdown
        """
        total_points = level * Player.POINTS_PER_LEVEL
        
        return {
            "explorer": {
                "description": "Maximize exploration (energy farming)",
                "energy": int(total_points * 0.70),
                "stamina": int(total_points * 0.20),
                "hp": int(total_points * 0.10),
                "pros": "More exploration attempts, faster progression",
                "cons": "Weak in ascension, lower survivability"
            },
            "ascender": {
                "description": "Maximize ascension (tower climbing)",
                "energy": int(total_points * 0.20),
                "stamina": int(total_points * 0.50),
                "hp": int(total_points * 0.30),
                "pros": "More tower attempts, decent survivability",
                "cons": "Limited exploration capacity"
            },
            "balanced": {
                "description": "Balanced across all modes",
                "energy": int(total_points * 0.40),
                "stamina": int(total_points * 0.30),
                "hp": int(total_points * 0.30),
                "pros": "Versatile, no major weaknesses",
                "cons": "Not optimized for any specific mode"
            },
            "tank": {
                "description": "Maximum survivability",
                "energy": int(total_points * 0.20),
                "stamina": int(total_points * 0.20),
                "hp": int(total_points * 0.60),
                "pros": "Survives high-floor bosses, hard to defeat",
                "cons": "Fewer attempts overall"
            }
        }