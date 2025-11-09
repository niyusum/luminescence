"""
Quest mastery system for sector completion rewards.

Each sector has 3 mastery ranks granting permanent stat boost relics.

RIKI LAW Compliance:
- Article III: Pure business logic service
- Article II: Comprehensive transaction logging
- Article VII: Domain exceptions only
"""

from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from src.database.models.core.player import Player
from src.database.models.progression.exploration_mastery import ExplorationMastery
from src.modules.exploration.mastery_relic import MasteryRelic
from src.modules.exploration.constants import RELIC_TYPES
from src.core.config.config_manager import ConfigManager
from src.core.infra.transaction_logger import TransactionLogger
from src.core.exceptions import InvalidOperationError
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class MasteryService:
    """Quest mastery system for sector completion rewards."""
    
    # ========================================================================
    # RANK COMPLETION
    # ========================================================================
    
    @staticmethod
    async def complete_sector_rank(
        session: AsyncSession,
        player: Player,
        sector_id: int,
        rank: int
    ) -> Dict[str, Any]:
        """
        Mark sector rank as complete and grant relic reward.
        
        Args:
            session: Database session
            player: Player object (with_for_update=True)
            sector_id: Sector number (1-6)
            rank: Rank completed (1, 2, or 3)
        
        Returns:
            {
                "rank_completed": int,
                "relic_granted": {
                    "name": str,
                    "type": str,
                    "bonus": float,
                    "description": str,
                    "icon": str
                },
                "all_ranks_complete": bool
            }
        
        Raises:
            InvalidOperationError: Rank already complete or invalid
        """
        if rank not in [1, 2, 3]:
            raise InvalidOperationError(f"Invalid rank: {rank}. Must be 1, 2, or 3")
        
        if sector_id < 1 or sector_id > 6:
            raise InvalidOperationError(f"Invalid sector: {sector_id}. Must be 1-6")
        
        # Get or create mastery record
        result = await session.execute(
            select(ExplorationMastery).where(
                ExplorationMastery.player_id == player.discord_id,
                ExplorationMastery.sector_id == sector_id
            ).with_for_update()
        )
        mastery = result.scalar_one_or_none()
        
        if not mastery:
            mastery = ExplorationMastery(
                player_id=player.discord_id,
                sector_id=sector_id
            )
            session.add(mastery)
            await session.flush()
        
        # Check if rank already complete
        if rank == 1 and mastery.rank_1_complete:
            raise InvalidOperationError("Rank 1 already complete for this sector")
        elif rank == 2 and mastery.rank_2_complete:
            raise InvalidOperationError("Rank 2 already complete for this sector")
        elif rank == 3 and mastery.rank_3_complete:
            raise InvalidOperationError("Rank 3 already complete for this sector")
        
        # Check prerequisites (must complete ranks in order)
        if rank == 2 and not mastery.rank_1_complete:
            raise InvalidOperationError("Must complete Rank 1 before Rank 2")
        elif rank == 3 and not mastery.rank_2_complete:
            raise InvalidOperationError("Must complete Rank 2 before Rank 3")
        
        # Mark rank complete
        if rank == 1:
            mastery.rank_1_complete = True
            mastery.rank_1_completed_at = datetime.utcnow()
        elif rank == 2:
            mastery.rank_2_complete = True
            mastery.rank_2_completed_at = datetime.utcnow()
        elif rank == 3:
            mastery.rank_3_complete = True
            mastery.rank_3_completed_at = datetime.utcnow()
        
        # Get relic reward from config
        reward_config = ConfigManager.get(
            f"exploration.mastery_rewards.sector_{sector_id}.rank_{rank}"
        )
        
        if not reward_config:
            raise InvalidOperationError(
                f"No reward config for sector {sector_id} rank {rank}. "
                f"Check config/exploration/mastery_rewards.yaml"
            )
        
        # Grant mastery relic
        mastery_relic = MasteryRelic(
            player_id=player.discord_id,
            relic_name=reward_config["description"],
            relic_type=reward_config["relic_type"],  # ← CORRECTED from item_type
            bonus_value=reward_config["bonus_value"],
            acquired_from=f"sector_{sector_id}_rank_{rank}"
        )
        session.add(mastery_relic)
        
        # Get relic type info for response
        relic_type_info = RELIC_TYPES.get(mastery_relic.relic_type, {})
        
        # Log transaction
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player.discord_id,
            transaction_type="mastery_rank_complete",
            details={
                "sector": sector_id,
                "rank": rank,
                "relic": {
                    "name": mastery_relic.relic_name,
                    "type": mastery_relic.relic_type,
                    "bonus": mastery_relic.bonus_value
                }
            },
            context="sector_completion"
        )
        
        logger.info(
            f"Player {player.discord_id} completed sector {sector_id} rank {rank}: "
            f"granted {mastery_relic.relic_name} ({mastery_relic.relic_type} +{mastery_relic.bonus_value})"
        )
        
        await session.flush()
        
        return {
            "rank_completed": rank,
            "relic_granted": {
                "name": mastery_relic.relic_name,
                "type": mastery_relic.relic_type,
                "bonus": mastery_relic.bonus_value,
                "description": relic_type_info.get("description", ""),
                "icon": relic_type_info.get("icon", "🏆")
            },
            "all_ranks_complete": mastery.is_fully_mastered()
        }
    
    # ========================================================================
    # QUERY
    # ========================================================================
    
    @staticmethod
    async def get_active_bonuses(
        session: AsyncSession,
        player_id: int
    ) -> Dict[str, float]:
        """
        Calculate all active mastery relic bonuses.
        
        Returns:
            {
                "shrine_income": 22.0,  # +22% total
                "combine_rate": 6.0,    # +6% total
                "attack_boost": 9.0,    # +9% total
                "defense_boost": 8.0,   # +8% total
                "energy_regen": 15.0,   # +15 per hour total
                "stamina_regen": 3.0,   # +3 per hour total
                "hp_boost": 700.0,      # +700 HP total
                "xp_gain": 5.0,         # +5% total
            }
        """
        result = await session.execute(
            select(MasteryRelic).where(
                MasteryRelic.player_id == player_id,
                MasteryRelic.is_active == True
            )
        )
        relics = result.scalars().all()
        
        bonuses = {}
        for relic in relics:
            if relic.relic_type not in bonuses:
                bonuses[relic.relic_type] = 0.0
            bonuses[relic.relic_type] += relic.bonus_value
        
        return bonuses
    
    @staticmethod
    async def get_player_relics(
        session: AsyncSession,
        player_id: int
    ) -> list:
        """
        Get all mastery relics for player.
        
        Returns:
            List of MasteryRelic objects
        """
        result = await session.execute(
            select(MasteryRelic).where(
                MasteryRelic.player_id == player_id,
                MasteryRelic.is_active == True
            ).order_by(MasteryRelic.acquired_at.desc())
        )
        return result.scalars().all()
    
    @staticmethod
    async def get_sector_mastery_status(
        session: AsyncSession,
        player_id: int,
        sector_id: int
    ) -> Dict[str, Any]:
        """
        Get mastery status for specific sector.
        
        Returns:
            {
                "sector_id": int,
                "current_rank": int (0-3),
                "next_rank": Optional[int],
                "fully_mastered": bool,
                "ranks": {
                    "rank_1": {"complete": bool, "completed_at": Optional[datetime]},
                    "rank_2": {"complete": bool, "completed_at": Optional[datetime]},
                    "rank_3": {"complete": bool, "completed_at": Optional[datetime]}
                }
            }
        """
        result = await session.execute(
            select(ExplorationMastery).where(
                ExplorationMastery.player_id == player_id,
                ExplorationMastery.sector_id == sector_id
            )
        )
        mastery = result.scalar_one_or_none()
        
        if not mastery:
            return {
                "sector_id": sector_id,
                "current_rank": 0,
                "next_rank": 1,
                "fully_mastered": False,
                "ranks": {
                    "rank_1": {"complete": False, "completed_at": None},
                    "rank_2": {"complete": False, "completed_at": None},
                    "rank_3": {"complete": False, "completed_at": None}
                }
            }
        
        return {
            "sector_id": sector_id,
            "current_rank": mastery.get_current_rank(),
            "next_rank": mastery.get_next_rank(),
            "fully_mastered": mastery.is_fully_mastered(),
            "ranks": {
                "rank_1": {
                    "complete": mastery.rank_1_complete,
                    "completed_at": mastery.rank_1_completed_at
                },
                "rank_2": {
                    "complete": mastery.rank_2_complete,
                    "completed_at": mastery.rank_2_completed_at
                },
                "rank_3": {
                    "complete": mastery.rank_3_complete,
                    "completed_at": mastery.rank_3_completed_at
                }
            }
        }
    
    @staticmethod
    async def get_all_sector_mastery(
        session: AsyncSession,
        player_id: int
    ) -> Dict[int, Dict[str, Any]]:
        """
        Get mastery status for all sectors.
        
        Returns:
            {
                1: {"current_rank": 3, "fully_mastered": True, ...},
                2: {"current_rank": 2, "fully_mastered": False, ...},
                ...
            }
        """
        result = await session.execute(
            select(ExplorationMastery).where(
                ExplorationMastery.player_id == player_id
            ).order_by(ExplorationMastery.sector_id)
        )
        all_mastery = result.scalars().all()
        
        mastery_dict = {}
        for sector_id in range(1, 7):  # Sectors 1-6
            mastery = next((m for m in all_mastery if m.sector_id == sector_id), None)
            
            if mastery:
                mastery_dict[sector_id] = {
                    "current_rank": mastery.get_current_rank(),
                    "next_rank": mastery.get_next_rank(),
                    "fully_mastered": mastery.is_fully_mastered(),
                    "ranks": {
                        "rank_1": {
                            "complete": mastery.rank_1_complete,
                            "completed_at": mastery.rank_1_completed_at
                        },
                        "rank_2": {
                            "complete": mastery.rank_2_complete,
                            "completed_at": mastery.rank_2_completed_at
                        },
                        "rank_3": {
                            "complete": mastery.rank_3_complete,
                            "completed_at": mastery.rank_3_completed_at
                        }
                    }
                }
            else:
                mastery_dict[sector_id] = {
                    "current_rank": 0,
                    "next_rank": 1,
                    "fully_mastered": False,
                    "ranks": {
                        "rank_1": {"complete": False, "completed_at": None},
                        "rank_2": {"complete": False, "completed_at": None},
                        "rank_3": {"complete": False, "completed_at": None}
                    }
                }
        
        return mastery_dict