"""
Maiden inventory and collection management service.

Handles querying, adding, updating, and removing maidens from player inventories.
Provides filtering, sorting, and collection utilities.

Features:
- Inventory queries with filtering and sorting
- Maiden addition/removal with validation
- Power calculation (DEFERS TO CombatService)
- Fusable maiden identification
- Collection statistics
- Performance metrics and monitoring

RIKI LAW Compliance:
- Session-first parameter pattern (Article I.6)
- Delegates power calculations to CombatService (Article VII)
- Transaction logging for audit trails (Article II)
- Domain exceptions only (Article VII)
- No Discord imports (Article VII)
- Performance metrics (Article X)

Note: Power calculations now defer to CombatService as the authoritative source.
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import time

from src.database.models.core.maiden import Maiden
from src.database.models.core.maiden_base import MaidenBase
from src.database.models.core.player import Player
from src.core.exceptions import MaidenNotFoundError
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class MaidenService:
    """
    Maiden inventory and collection management service.
    
    Provides:
    - Collection management
    - Inventory operations
    - Power calculations (via CombatService)
    """
    
    # Metrics tracking
    _metrics = {
        "queries": 0,
        "additions": 0,
        "removals": 0,
        "power_calculations": 0,
        "collection_stat_queries": 0,
        "total_maidens_added": 0,
        "total_maidens_removed": 0,
        "errors": 0,
        "total_query_time_ms": 0.0,
        "total_power_calc_time_ms": 0.0,
    }
    
    @staticmethod
    async def get_player_maidens(
        session: AsyncSession,
        player_id: int,
        tier_filter: Optional[int] = None,
        element_filter: Optional[str] = None,
        sort_by: str = "tier_desc",
        lock: bool = False
    ) -> List[Maiden]:
        """
        Get all maidens for player with optional filtering and sorting.
        
        Args:
            session: Database session
            player_id: Player's Discord ID
            tier_filter: Optional tier to filter by
            element_filter: Optional element to filter by
            sort_by: Sort method - "tier_desc", "tier_asc", "name", "quantity"
            lock: Whether to use SELECT FOR UPDATE
        
        Returns:
            List of Maiden objects with maiden_base relationship loaded
        """
        start_time = time.perf_counter()
        MaidenService._metrics["queries"] += 1
        
        try:
            query = (
                select(Maiden)
                .join(MaidenBase)
                .where(Maiden.player_id == player_id)
            )
            
            if tier_filter is not None:
                query = query.where(Maiden.tier == tier_filter)
            
            if element_filter:
                query = query.where(MaidenBase.element == element_filter)
            
            if sort_by == "tier_desc":
                query = query.order_by(Maiden.tier.desc())
            elif sort_by == "tier_asc":
                query = query.order_by(Maiden.tier.asc())
            elif sort_by == "name":
                query = query.order_by(MaidenBase.name)
            elif sort_by == "quantity":
                query = query.order_by(Maiden.quantity.desc())
            
            if lock:
                query = query.with_for_update()
            
            result = await session.execute(query)
            maidens = list(result.scalars().all())
            
            # Batch load relationships
            for maiden in maidens:
                await session.refresh(maiden, ["maiden_base"])
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            MaidenService._metrics["total_query_time_ms"] += elapsed_ms
            
            logger.debug(
                f"Fetched maidens: player={player_id} count={len(maidens)} filters=[tier={tier_filter}, element={element_filter}]",
                extra={
                    "player_id": player_id,
                    "maiden_count": len(maidens),
                    "tier_filter": tier_filter,
                    "element_filter": element_filter,
                    "query_time_ms": round(elapsed_ms, 2)
                }
            )
            
            return maidens
            
        except Exception as e:
            MaidenService._metrics["errors"] += 1
            logger.error(
                f"Failed to fetch maidens: player={player_id} error={e}",
                extra={"player_id": player_id},
                exc_info=True
            )
            raise
    
    @staticmethod
    async def get_maiden_by_id(
        session: AsyncSession,
        maiden_id: int,
        player_id: Optional[int] = None,
        lock: bool = False
    ) -> Optional[Maiden]:
        """
        Get specific maiden by ID with optional ownership validation.
        
        Args:
            session: Database session
            maiden_id: Maiden instance ID
            player_id: Optional player ID to validate ownership
            lock: Whether to use SELECT FOR UPDATE
        
        Returns:
            Maiden object or None if not found
        
        Raises:
            MaidenNotFoundError: If player_id provided and ownership doesn't match
        """
        try:
            query = select(Maiden).where(Maiden.id == maiden_id)
            
            if lock:
                query = query.with_for_update()
            
            result = await session.execute(query)
            maiden = result.scalar_one_or_none()
            
            if not maiden:
                return None
            
            if player_id is not None and maiden.player_id != player_id:
                raise MaidenNotFoundError(f"Maiden {maiden_id} not owned by player {player_id}")
            
            await session.refresh(maiden, ["maiden_base"])
            
            return maiden
            
        except MaidenNotFoundError:
            raise
        except Exception as e:
            MaidenService._metrics["errors"] += 1
            logger.error(
                f"Failed to fetch maiden: maiden_id={maiden_id} error={e}",
                extra={"maiden_id": maiden_id, "player_id": player_id},
                exc_info=True
            )
            raise
    
    @staticmethod
    async def get_fusable_maidens(
        session: AsyncSession,
        player_id: int,
        tier: Optional[int] = None
    ) -> List[Maiden]:
        """
        Get maidens that can be fused (quantity >= 2 and tier < 12).
        
        Args:
            session: Database session
            player_id: Player's Discord ID
            tier: Optional specific tier to filter
        
        Returns:
            List of Maiden objects that meet fusion requirements
        """
        start_time = time.perf_counter()
        
        try:
            query = (
                select(Maiden)
                .join(MaidenBase)
                .where(
                    Maiden.player_id == player_id,
                    Maiden.quantity >= 2,
                    Maiden.tier < 12
                )
            )
            
            if tier is not None:
                query = query.where(Maiden.tier == tier)
            
            query = query.order_by(Maiden.tier.desc())
            
            result = await session.execute(query)
            maidens = list(result.scalars().all())
            
            # Batch load relationships
            for maiden in maidens:
                await session.refresh(maiden, ["maiden_base"])
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            logger.debug(
                f"Fetched fusable maidens: player={player_id} count={len(maidens)} tier_filter={tier}",
                extra={
                    "player_id": player_id,
                    "fusable_count": len(maidens),
                    "tier_filter": tier,
                    "query_time_ms": round(elapsed_ms, 2)
                }
            )
            
            return maidens
            
        except Exception as e:
            MaidenService._metrics["errors"] += 1
            logger.error(
                f"Failed to fetch fusable maidens: player={player_id} error={e}",
                extra={"player_id": player_id},
                exc_info=True
            )
            raise
    
    @staticmethod
    async def add_maiden_to_inventory(
        session: AsyncSession,
        player_id: int,
        maiden_base_id: int,
        tier: int,
        quantity: int = 1,
        acquired_from: str = "summon"
    ) -> Maiden:
        """
        Add maiden to player inventory or increment quantity if exists.

        Args:
            session: Database session
            player_id: Player's Discord ID
            maiden_base_id: MaidenBase template ID
            tier: Maiden tier
            quantity: Number to add (default 1)
            acquired_from: Source of acquisition (default "summon")

        Returns:
            Maiden object (existing or newly created)
        """
        MaidenService._metrics["additions"] += 1
        MaidenService._metrics["total_maidens_added"] += quantity
        
        try:
            existing_result = await session.execute(
                select(Maiden).where(
                    Maiden.player_id == player_id,
                    Maiden.maiden_base_id == maiden_base_id,
                    Maiden.tier == tier
                ).with_for_update()
            )
            existing_maiden = existing_result.scalar_one_or_none()

            if existing_maiden:
                existing_maiden.quantity += quantity
                await session.refresh(existing_maiden, ["maiden_base"])
                
                logger.info(
                    f"Incremented maiden: player={player_id} maiden_id={existing_maiden.id} quantity_added={quantity}",
                    extra={
                        "player_id": player_id,
                        "maiden_id": existing_maiden.id,
                        "quantity_added": quantity,
                        "new_quantity": existing_maiden.quantity
                    }
                )
                
                return existing_maiden
            else:
                # Fetch maiden_base to get element field
                maiden_base = await session.get(MaidenBase, maiden_base_id)
                if not maiden_base:
                    raise ValueError(f"MaidenBase {maiden_base_id} not found")

                new_maiden = Maiden(
                    player_id=player_id,
                    maiden_base_id=maiden_base_id,
                    tier=tier,
                    element=maiden_base.element,
                    quantity=quantity,
                    acquired_from=acquired_from
                )
                session.add(new_maiden)
                await session.flush()
                await session.refresh(new_maiden, ["maiden_base"])

                # Update player unique count
                player = await session.get(Player, player_id)
                if player:
                    player.unique_maidens += 1
                
                logger.info(
                    f"Added new maiden: player={player_id} maiden_id={new_maiden.id} base_id={maiden_base_id} tier={tier} quantity={quantity}",
                    extra={
                        "player_id": player_id,
                        "maiden_id": new_maiden.id,
                        "maiden_base_id": maiden_base_id,
                        "tier": tier,
                        "quantity": quantity,
                        "acquired_from": acquired_from
                    }
                )

                return new_maiden
                
        except ValueError:
            raise
        except Exception as e:
            MaidenService._metrics["errors"] += 1
            logger.error(
                f"Failed to add maiden: player={player_id} base_id={maiden_base_id} error={e}",
                extra={"player_id": player_id, "maiden_base_id": maiden_base_id},
                exc_info=True
            )
            raise
    
    @staticmethod
    async def update_maiden_quantity(
        session: AsyncSession,
        maiden_id: int,
        quantity_change: int
    ) -> Optional[Maiden]:
        """
        Modify maiden quantity and delete if quantity reaches 0.
        
        Args:
            session: Database session
            maiden_id: Maiden instance ID
            quantity_change: Amount to add (positive) or remove (negative)
        
        Returns:
            Updated Maiden object, or None if deleted
        """
        if quantity_change < 0:
            MaidenService._metrics["removals"] += 1
            MaidenService._metrics["total_maidens_removed"] += abs(quantity_change)
        
        try:
            maiden = await session.get(Maiden, maiden_id, with_for_update=True)
            
            if not maiden:
                raise MaidenNotFoundError(f"Maiden {maiden_id} not found")
            
            old_quantity = maiden.quantity
            maiden.quantity += quantity_change
            
            if maiden.quantity <= 0:
                player = await session.get(Player, maiden.player_id)
                if player:
                    player.unique_maidens -= 1
                
                await session.delete(maiden)
                
                logger.info(
                    f"Deleted maiden: maiden_id={maiden_id} player={maiden.player_id} old_quantity={old_quantity}",
                    extra={
                        "maiden_id": maiden_id,
                        "player_id": maiden.player_id,
                        "old_quantity": old_quantity
                    }
                )
                
                return None
            
            logger.info(
                f"Updated maiden quantity: maiden_id={maiden_id} change={quantity_change} new_quantity={maiden.quantity}",
                extra={
                    "maiden_id": maiden_id,
                    "quantity_change": quantity_change,
                    "old_quantity": old_quantity,
                    "new_quantity": maiden.quantity
                }
            )
            
            return maiden
            
        except MaidenNotFoundError:
            raise
        except Exception as e:
            MaidenService._metrics["errors"] += 1
            logger.error(
                f"Failed to update maiden quantity: maiden_id={maiden_id} error={e}",
                extra={"maiden_id": maiden_id},
                exc_info=True
            )
            raise
    
    @staticmethod
    async def get_maiden_base_by_id(
        session: AsyncSession,
        maiden_base_id: int
    ) -> Optional[MaidenBase]:
        """
        Get MaidenBase template by ID.
        
        Args:
            session: Database session
            maiden_base_id: MaidenBase ID
        
        Returns:
            MaidenBase object or None if not found
        """
        try:
            return await session.get(MaidenBase, maiden_base_id)
        except Exception as e:
            MaidenService._metrics["errors"] += 1
            logger.error(
                f"Failed to fetch maiden base: base_id={maiden_base_id} error={e}",
                exc_info=True
            )
            raise
    
    @staticmethod
    async def calculate_player_total_power(
        session: AsyncSession,
        player_id: int
    ) -> int:
        """
        Calculate player's total power from all maidens.
        
        DEFERS TO CombatService as the authoritative source.
        Includes leader bonus by default.
        
        Formula (from CombatService):
            Power = Σ(base_atk × quantity) × leader_bonus
        
        Args:
            session: Database session
            player_id: Player's Discord ID
        
        Returns:
            Total power value
        """
        start_time = time.perf_counter()
        MaidenService._metrics["power_calculations"] += 1
        
        try:
            # Defer to CombatService as authoritative source
            from src.modules.combat.service import CombatService
            
            total_power = await CombatService.calculate_total_power(
                session,
                player_id,
                include_leader_bonus=True
            )
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            MaidenService._metrics["total_power_calc_time_ms"] += elapsed_ms
            
            logger.debug(
                f"Calculated power: player={player_id} power={total_power}",
                extra={
                    "player_id": player_id,
                    "total_power": total_power,
                    "calc_time_ms": round(elapsed_ms, 2)
                }
            )
            
            return total_power
            
        except Exception as e:
            MaidenService._metrics["errors"] += 1
            logger.error(
                f"Failed to calculate power: player={player_id} error={e}",
                extra={"player_id": player_id},
                exc_info=True
            )
            raise
    
    @staticmethod
    async def get_collection_stats(
        session: AsyncSession,
        player_id: int
    ) -> Dict[str, Any]:
        """
        Get player's collection statistics.
        
        Returns:
            Dictionary with:
                - total_maidens (int): Sum of all quantities
                - unique_maidens (int): Count of unique maidens
                - tier_distribution (dict): Count per tier
                - element_distribution (dict): Count per element
                - highest_tier (int): Highest tier owned
                - total_power (int): Calculated power
        """
        start_time = time.perf_counter()
        MaidenService._metrics["collection_stat_queries"] += 1
        
        try:
            maidens = await MaidenService.get_player_maidens(session, player_id)
            
            total_maidens = sum(maiden.quantity for maiden in maidens)
            unique_maidens = len(maidens)
            
            tier_distribution = {}
            element_distribution = {}
            highest_tier = 0
            
            for maiden in maidens:
                tier = maiden.tier
                tier_distribution[tier] = tier_distribution.get(tier, 0) + maiden.quantity
                highest_tier = max(highest_tier, tier)
                
                if maiden.maiden_base:
                    element = maiden.maiden_base.element
                    element_distribution[element] = element_distribution.get(element, 0) + maiden.quantity
            
            total_power = await MaidenService.calculate_player_total_power(session, player_id)
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            logger.debug(
                f"Collection stats: player={player_id} unique={unique_maidens} total={total_maidens}",
                extra={
                    "player_id": player_id,
                    "unique_maidens": unique_maidens,
                    "total_maidens": total_maidens,
                    "stats_time_ms": round(elapsed_ms, 2)
                }
            )
            
            return {
                "total_maidens": total_maidens,
                "unique_maidens": unique_maidens,
                "tier_distribution": tier_distribution,
                "element_distribution": element_distribution,
                "highest_tier": highest_tier,
                "total_power": total_power
            }
            
        except Exception as e:
            MaidenService._metrics["errors"] += 1
            logger.error(
                f"Failed to get collection stats: player={player_id} error={e}",
                extra={"player_id": player_id},
                exc_info=True
            )
            raise
    
    # =========================================================================
    # METRICS & MONITORING
    # =========================================================================
    
    @staticmethod
    def get_metrics() -> Dict[str, Any]:
        """
        Get MaidenService performance metrics.
        
        Returns:
            Dictionary with operation counts, totals, timing
        """
        total_ops = (
            MaidenService._metrics["queries"] +
            MaidenService._metrics["additions"] +
            MaidenService._metrics["removals"] +
            MaidenService._metrics["power_calculations"] +
            MaidenService._metrics["collection_stat_queries"]
        )
        
        avg_query_time = (
            MaidenService._metrics["total_query_time_ms"] / MaidenService._metrics["queries"]
            if MaidenService._metrics["queries"] > 0 else 0.0
        )
        
        avg_power_calc_time = (
            MaidenService._metrics["total_power_calc_time_ms"] / MaidenService._metrics["power_calculations"]
            if MaidenService._metrics["power_calculations"] > 0 else 0.0
        )
        
        return {
            "queries": MaidenService._metrics["queries"],
            "additions": MaidenService._metrics["additions"],
            "removals": MaidenService._metrics["removals"],
            "power_calculations": MaidenService._metrics["power_calculations"],
            "collection_stat_queries": MaidenService._metrics["collection_stat_queries"],
            "total_operations": total_ops,
            "total_maidens_added": MaidenService._metrics["total_maidens_added"],
            "total_maidens_removed": MaidenService._metrics["total_maidens_removed"],
            "errors": MaidenService._metrics["errors"],
            "avg_query_time_ms": round(avg_query_time, 2),
            "avg_power_calc_time_ms": round(avg_power_calc_time, 2),
        }
    
    @staticmethod
    def reset_metrics() -> None:
        """Reset all metrics counters."""
        MaidenService._metrics = {
            "queries": 0,
            "additions": 0,
            "removals": 0,
            "power_calculations": 0,
            "collection_stat_queries": 0,
            "total_maidens_added": 0,
            "total_maidens_removed": 0,
            "errors": 0,
            "total_query_time_ms": 0.0,
            "total_power_calc_time_ms": 0.0,
        }
        logger.info("MaidenService metrics reset")