"""
Centralized resource transaction and modifier application system.

Handles ALL resource modifications (lumees, auric coin, gems, energy, stamina, DROP_CHARGES)
with validation, global modifier application, transaction logging, and cap enforcement.

Features:
- Resource granting with modifier application (leader + class bonuses)
- Resource consumption with validation
- Resource checking without modification
- Modifier calculation from multiple sources
- AuricCoin cap enforcement (configurable)
- Comprehensive audit trails
- Performance metrics and monitoring

LUMEN LAW Compliance:
- Session-first parameter pattern (Article I.6)
- ConfigManager for all tunables (Article IV)
- Transaction logging for audit trails (Article II)
- Domain exceptions only (Article VII)
- No Discord imports (Article VII)
- Performance metrics (Article X)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
import time

from src.database.models.core.player import Player
from src.core.config import ConfigManager
from src.core.infra.transaction_logger import TransactionLogger
from src.modules.maiden.leader_service import LeaderService
from src.core.exceptions import InsufficientResourcesError
from src.core.logging.logger import get_logger
from src.core.constants import drop_CHARGES_MAX

logger = get_logger(__name__)


class ResourceService:
    """
    Centralized resource transaction and modifier application system.
    
    Modifier System:
        - Multiplicative stacking: final = base * leader_mult * class_mult
        - Applies to: lumees, auric coin, lumenite, XP gains
        - Sources: Leader effects (income_boost, xp_boost), class bonuses
    """
    
    # Metrics tracking
    _metrics = {
        "grants": 0,
        "consumes": 0,
        "checks": 0,
        "total_lumees_granted": 0,
        "total_auric_coin_granted": 0,
        "total_lumenite_granted": 0,
        "total_lumees_consumed": 0,
        "total_auric_coin_consumed": 0,
        "auric_coin_caps_hit": 0,
        "insufficient_resource_errors": 0,
        "errors": 0,
        "total_grant_time_ms": 0.0,
        "total_consume_time_ms": 0.0,
    }
    
    @staticmethod
    async def grant_resources(
        session: AsyncSession,
        player: Player,
        resources: Dict[str, int],
        source: str,
        apply_modifiers: bool = True,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Grant resources to player with optional modifier application.
        
        Applies leader bonuses and class bonuses multiplicatively:
        - income_boost applies to: lumees, auric coin, lumenite
        - xp_boost applies to: experience
        
        Enforces auric coin cap (configurable). No cap for lumees/lumenite.
        Logs all changes via TransactionLogger.
        
        Args:
            session: Database session (transaction managed by caller)
            player: Player object (must be locked with SELECT FOR UPDATE)
            resources: Dict of resource amounts {"lumees": 1000, "auric_coin": 5, "experience": 100}
            source: Reason for grant ("daily_reward", "fusion_refund", "drop_completion")
            apply_modifiers: Whether to apply leader/class bonuses (False for tutorial)
            context: Additional context for transaction log
        
        Returns:
            Dictionary with:
                - granted (dict): Actual amounts granted after modifiers
                - modifiers_applied (dict): Multipliers used
                - caps_hit (list): Resources that hit caps
                - old_values (dict): Values before grant
                - new_values (dict): Values after grant
        """
        start_time = time.perf_counter()
        ResourceService._metrics["grants"] += 1
        
        try:
            granted = {}
            modifiers_applied = {}
            caps_hit = []
            old_values = {}
            new_values = {}
            
            # Calculate modifiers if requested
            if apply_modifiers:
                resource_types = list(resources.keys())
                modifiers = await ResourceService.calculate_modifiers(player, resource_types)
                modifiers_applied = modifiers
            else:
                modifiers_applied = {}
            
            # Process each resource
            for resource, base_amount in resources.items():
                if base_amount <= 0:
                    continue
                
                old_values[resource] = getattr(player, resource, 0)
                
                # Apply modifiers
                final_amount = base_amount
                if apply_modifiers:
                    if resource in ["lumees", "auric_coin", "lumenite"]:
                        income_mult = modifiers_applied.get("income_boost", 1.0)
                        final_amount = int(base_amount * income_mult)
                    elif resource == "experience":
                        xp_mult = modifiers_applied.get("xp_boost", 1.0)
                        final_amount = int(base_amount * xp_mult)
                
                # Apply with caps
                if resource == "auric_coin":
                    auric_coin_cap = ConfigManager.get("resource_system.auric_coin_max_cap", 999999)
                    new_value = old_values[resource] + final_amount
                    if new_value > auric_coin_cap:
                        final_amount = auric_coin_cap - old_values[resource]
                        caps_hit.append("auric_coin")
                        new_value = auric_coin_cap
                        ResourceService._metrics["auric_coin_caps_hit"] += 1
                    player.auric_coin = new_value
                    ResourceService._metrics["total_auric_coin_granted"] += final_amount
                    
                elif resource == "lumees":
                    player.lumees += final_amount
                    ResourceService._metrics["total_lumees_granted"] += final_amount
                    
                elif resource == "lumenite":
                    player.lumenite += final_amount
                    ResourceService._metrics["total_gems_granted"] += final_amount
                    
                elif resource == "experience":
                    player.experience += final_amount
                    
                elif resource == "energy":
                    new_val = min(player.energy + final_amount, player.max_energy)
                    final_amount = new_val - player.energy
                    player.energy = new_val
                    
                elif resource == "stamina":
                    new_val = min(player.stamina + final_amount, player.max_stamina)
                    final_amount = new_val - player.stamina
                    player.stamina = new_val
                    
                elif resource == "DROP_CHARGES":
                    # Single charge system: cap at drop_CHARGES_MAX
                    new_val = min(player.DROP_CHARGES + final_amount, drop_CHARGES_MAX)
                    final_amount = new_val - player.DROP_CHARGES
                    player.DROP_CHARGES = new_val
                    
                else:
                    logger.warning(
                        f"Unknown resource type: {resource}",
                        extra={"resource": resource, "player_id": player.discord_id}
                    )
                    continue
                
                granted[resource] = final_amount
                new_values[resource] = getattr(player, resource, 0)
            
            # Log transaction
            await TransactionLogger.log_transaction(
                session=session,
                player_id=player.discord_id,
                transaction_type=f"resource_grant_{source}",
                details={
                    "resources_granted": granted,
                    "base_amounts": resources,
                    "modifiers": modifiers_applied,
                    "caps_hit": caps_hit,
                    "old_values": old_values,
                    "new_values": new_values,
                    "source": source,
                    "context": context or {}
                },
                context=f"grant:{source}"
            )
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            ResourceService._metrics["total_grant_time_ms"] += elapsed_ms
            
            logger.info(
                f"Granted resources: player={player.discord_id} resources={granted} source={source}",
                extra={
                    "player_id": player.discord_id,
                    "granted": granted,
                    "modifiers": modifiers_applied,
                    "source": source,
                    "grant_time_ms": round(elapsed_ms, 2)
                }
            )
            
            return {
                "granted": granted,
                "modifiers_applied": modifiers_applied,
                "caps_hit": caps_hit,
                "old_values": old_values,
                "new_values": new_values
            }
            
        except Exception as e:
            ResourceService._metrics["errors"] += 1
            logger.error(
                f"Grant resources failed: player={player.discord_id} error={e}",
                extra={"player_id": player.discord_id, "source": source},
                exc_info=True
            )
            raise
    
    @staticmethod
    async def consume_resources(
        session: AsyncSession,
        player: Player,
        resources: Dict[str, int],
        source: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Consume resources from player with validation.
        
        Validates player has sufficient resources before consuming.
        Logs all changes via TransactionLogger.
        
        Args:
            session: Database session (transaction managed by caller)
            player: Player object (must be locked with SELECT FOR UPDATE)
            resources: Dict of resource amounts to consume {"lumees": 5000, "auric_coin": 5}
            source: Reason for consumption ("fusion_cost", "summon_cost", "upgrade_cost")
            context: Additional context for transaction log
        
        Returns:
            Dictionary with:
                - consumed (dict): Amounts consumed
                - old_values (dict): Values before consumption
                - new_values (dict): Values after consumption
        
        Raises:
            InsufficientResourcesError: If player lacks required resources
        """
        start_time = time.perf_counter()
        ResourceService._metrics["consumes"] += 1
        
        try:
            old_values = {}
            new_values = {}
            consumed = {}
            
            # Validate all resources first
            for resource, amount in resources.items():
                if amount <= 0:
                    continue
                
                current = getattr(player, resource, 0)
                old_values[resource] = current
                
                if current < amount:
                    ResourceService._metrics["insufficient_resource_errors"] += 1
                    raise InsufficientResourcesError(
                        resource=resource,
                        required=amount,
                        current=current
                    )
            
            # Consume all resources
            for resource, amount in resources.items():
                if amount <= 0:
                    continue
                
                if resource == "auric_coin":
                    player.auric_coin -= amount
                    ResourceService._metrics["total_auric_coin_consumed"] += amount
                elif resource == "lumees":
                    player.lumees -= amount
                    ResourceService._metrics["total_lumees_consumed"] += amount
                elif resource == "lumenite":
                    player.lumenite -= amount
                elif resource == "energy":
                    player.energy -= amount
                elif resource == "stamina":
                    player.stamina -= amount
                elif resource == "DROP_CHARGES":
                    player.DROP_CHARGES -= amount
                else:
                    logger.warning(
                        f"Unknown resource type for consumption: {resource}",
                        extra={"resource": resource, "player_id": player.discord_id}
                    )
                    continue
                
                consumed[resource] = amount
                new_values[resource] = getattr(player, resource, 0)
            
            # Log transaction
            await TransactionLogger.log_transaction(
                session=session,
                player_id=player.discord_id,
                transaction_type=f"resource_consume_{source}",
                details={
                    "resources_consumed": consumed,
                    "old_values": old_values,
                    "new_values": new_values,
                    "source": source,
                    "context": context or {}
                },
                context=f"consume:{source}"
            )
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            ResourceService._metrics["total_consume_time_ms"] += elapsed_ms
            
            logger.info(
                f"Consumed resources: player={player.discord_id} resources={consumed} source={source}",
                extra={
                    "player_id": player.discord_id,
                    "consumed": consumed,
                    "source": source,
                    "consume_time_ms": round(elapsed_ms, 2)
                }
            )
            
            return {
                "consumed": consumed,
                "old_values": old_values,
                "new_values": new_values
            }
            
        except InsufficientResourcesError:
            raise
        except Exception as e:
            ResourceService._metrics["errors"] += 1
            logger.error(
                f"Consume resources failed: player={player.discord_id} error={e}",
                extra={"player_id": player.discord_id, "source": source},
                exc_info=True
            )
            raise
    
    @staticmethod
    def check_resources(player: Player, resources: Dict[str, int]) -> bool:
        """
        Check if player has sufficient resources without consuming.
        
        Args:
            player: Player object
            resources: Dict of resource requirements {"lumees": 5000, "auric_coin": 5}
        
        Returns:
            True if player has all required resources, False otherwise
        """
        ResourceService._metrics["checks"] += 1
        
        for resource, amount in resources.items():
            if amount <= 0:
                continue
            
            current = getattr(player, resource, 0)
            if current < amount:
                return False
        
        return True
    
    @staticmethod
    async def calculate_modifiers(player: Player, resource_types: List[str]) -> Dict[str, float]:
        """
        Calculate active modifiers from leader and class effects.

        Multiplicative stacking: final = base * leader_mult * class_mult

        Args:
            player: Player object
            resource_types: List of resource types to calculate modifiers for

        Returns:
            Dictionary of multipliers:
                - income_boost: Multiplier for lumees, auric coin, gems (1.0 = no bonus)
                - xp_boost: Multiplier for experience (1.0 = no bonus)

        Performance:
            Results are not cached because leader can change mid-transaction.
            However, we optimize by only querying leader service when needed.
        """
        modifiers = {
            "income_boost": 1.0,
            "xp_boost": 1.0
        }

        needs_income = any(r in resource_types for r in ["lumees", "auric_coin", "lumenite"])
        needs_xp = "experience" in resource_types

        # Early exit if no modifiers needed
        if not needs_income and not needs_xp:
            return modifiers

        if not player.leader_maiden_id:
            return modifiers  # Early exit if no leader set

        try:
            leader_modifiers = await LeaderService.get_active_modifiers(player)
            if needs_income and "income_boost" in leader_modifiers:
                modifiers["income_boost"] *= leader_modifiers["income_boost"]
            if needs_xp and "xp_boost" in leader_modifiers:
                modifiers["xp_boost"] *= leader_modifiers["xp_boost"]
        except Exception as e:
            logger.warning(
                f"Failed to get leader modifiers: player={player.discord_id} error={e}",
                extra={"player_id": player.discord_id}
            )

        return modifiers
    
    @staticmethod
    def apply_regeneration(player: Player, regen_amounts: Dict[str, int]) -> Dict[str, int]:
        """
        Apply calculated regeneration amounts with cap enforcement.
        
        Called by PlayerService after calculating regen. This method applies
        the amounts and respects caps. Does NOT calculate regen itself.
        
        Args:
            player: Player object
            regen_amounts: Dict of regen amounts {"energy": 10, "stamina": 5, "DROP_CHARGES": 1}
        
        Returns:
            Dictionary of actual amounts regenerated (after caps)
        """
        actual_regen = {}
        
        if "energy" in regen_amounts and regen_amounts["energy"] > 0:
            old_energy = player.energy
            player.energy = min(player.energy + regen_amounts["energy"], player.max_energy)
            actual_regen["energy"] = player.energy - old_energy
        
        if "stamina" in regen_amounts and regen_amounts["stamina"] > 0:
            old_stamina = player.stamina
            player.stamina = min(player.stamina + regen_amounts["stamina"], player.max_stamina)
            actual_regen["stamina"] = player.stamina - old_stamina
        
        if "DROP_CHARGES" in regen_amounts and regen_amounts["DROP_CHARGES"] > 0:
            old_charges = player.DROP_CHARGES
            # Single charge system: cap at drop_CHARGES_MAX
            player.DROP_CHARGES = min(
                player.DROP_CHARGES + regen_amounts["DROP_CHARGES"],
                drop_CHARGES_MAX
            )
            actual_regen["DROP_CHARGES"] = player.DROP_CHARGES - old_charges
        
        return actual_regen
    
    @staticmethod
    async def get_resource_summary(player: Player) -> Dict[str, Any]:
        """
        Get formatted resource display for player profile.

        Args:
            player: Player object

        Returns:
            Dictionary with formatted resource information:
                - currencies: lumees, auric coin, gems
                - consumables: energy, stamina, DROP_CHARGES with max values
                - modifiers: active bonuses from leader/class
        """
        modifiers = await ResourceService.calculate_modifiers(
            player,
            ["lumees", "auric_coin", "lumenite", "experience"]
        )
        
        return {
            "currencies": {
                "lumees": player.lumees,
                "auric_coin": player.auric_coin,
                "lumenite": player.lumenite
            },
            "consumables": {
                "energy": {
                    "current": player.energy,
                    "max": player.max_energy,
                    "percentage": int((player.energy / player.max_energy) * 100) if player.max_energy > 0 else 0
                },
                "stamina": {
                    "current": player.stamina,
                    "max": player.max_stamina,
                    "percentage": int((player.stamina / player.max_stamina) * 100) if player.max_stamina > 0 else 0
                },
                "DROP_CHARGES": {
                    "current": player.DROP_CHARGES,
                    "max": drop_CHARGES_MAX,  # Single charge system
                    "has_charge": player.DROP_CHARGES >= drop_CHARGES_MAX,
                    "next_regen": player.get_drop_regen_display() if hasattr(player, 'get_drop_regen_display') else "N/A"
                }
            },
            "modifiers": {
                "income_boost": f"{(modifiers['income_boost'] - 1.0) * 100:.0f}%" if modifiers['income_boost'] > 1.0 else "None",
                "xp_boost": f"{(modifiers['xp_boost'] - 1.0) * 100:.0f}%" if modifiers['xp_boost'] > 1.0 else "None"
            }
        }
    
    # =========================================================================
    # METRICS & MONITORING
    # =========================================================================
    
    @staticmethod
    def get_metrics() -> Dict[str, Any]:
        """
        Get ResourceService performance metrics.
        
        Returns:
            Dictionary with operation counts, totals, timing
        """
        total_ops = (
            ResourceService._metrics["grants"] +
            ResourceService._metrics["consumes"] +
            ResourceService._metrics["checks"]
        )
        
        avg_grant_time = (
            ResourceService._metrics["total_grant_time_ms"] / ResourceService._metrics["grants"]
            if ResourceService._metrics["grants"] > 0 else 0.0
        )
        
        avg_consume_time = (
            ResourceService._metrics["total_consume_time_ms"] / ResourceService._metrics["consumes"]
            if ResourceService._metrics["consumes"] > 0 else 0.0
        )
        
        return {
            "grants": ResourceService._metrics["grants"],
            "consumes": ResourceService._metrics["consumes"],
            "checks": ResourceService._metrics["checks"],
            "total_operations": total_ops,
            "total_lumees_granted": ResourceService._metrics["total_lumees_granted"],
            "total_auric_coin_granted": ResourceService._metrics["total_auric_coin_granted"],
            "total_gems_granted": ResourceService._metrics["total_gems_granted"],
            "total_lumees_consumed": ResourceService._metrics["total_lumees_consumed"],
            "total_auric_coin_consumed": ResourceService._metrics["total_auric_coin_consumed"],
            "auric_coin_caps_hit": ResourceService._metrics["auric_coin_caps_hit"],
            "insufficient_resource_errors": ResourceService._metrics["insufficient_resource_errors"],
            "errors": ResourceService._metrics["errors"],
            "avg_grant_time_ms": round(avg_grant_time, 2),
            "avg_consume_time_ms": round(avg_consume_time, 2),
        }
    
    @staticmethod
    def reset_metrics() -> None:
        """Reset all metrics counters."""
        ResourceService._metrics = {
            "grants": 0,
            "consumes": 0,
            "checks": 0,
            "total_lumees_granted": 0,
            "total_auric_coin_granted": 0,
            "total_gems_granted": 0,
            "total_lumees_consumed": 0,
            "total_auric_coin_consumed": 0,
            "auric_coin_caps_hit": 0,
            "insufficient_resource_errors": 0,
            "errors": 0,
            "total_grant_time_ms": 0.0,
            "total_consume_time_ms": 0.0,
        }
        logger.info("ResourceService metrics reset")