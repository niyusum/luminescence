"""
Combat calculation and resolution service.

RIKI LAW Compliance: Article III (Service Layer), Article II (Audit Trails)
- Pure business logic with no Discord dependencies
- Comprehensive transaction logging for all combat events
- Pessimistic locking for combat state modifications
- Power calculations from maiden collections with leader bonuses
- Damage calculations with modifiers, crits, and scaling

Features:
- Player power calculation from maiden inventory
- Damage calculation with attack multipliers and critical hits
- Combat resolution (attacker vs defender, PvP/PvE)
- HP management and stat calculations
- Combat display formatting (HP bars, damage text, element emojis)
- Comprehensive metrics and logging

Attack damage originates from maiden base_atk stats:
    Power = sum(base_atk × quantity) for all maidens
    Damage = Power × attack_count × modifiers × crit_bonus
    
Note: Tier scaling handled via MaidenBase.base_atk values from seed data.
      Higher tier maidens have exponentially higher base_atk naturally.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.database.models.core.player import Player
from src.database.models.core.maiden import Maiden
from src.database.models.core.maiden_base import MaidenBase
from src.core.config_manager import ConfigManager
from src.core.transaction_logger import TransactionLogger
from src.core.exceptions import CombatError
from src.core.logger import get_logger, LogContext

logger = get_logger(__name__)


# ============================================================================
# COMBAT DATA STRUCTURES
# ============================================================================

@dataclass(frozen=True)
class PowerBreakdown:
    """
    Detailed breakdown of player power from maiden collection.
    
    Attributes:
        total_power: Total ATK value from all maidens
        maiden_count: Total number of unique maidens owned
        top_contributors: List of top power-contributing maidens
        average_power: Average power per maiden
        leader_bonus_applied: Whether leader bonus was included
    """
    total_power: int
    maiden_count: int
    top_contributors: List[Dict]
    average_power: int
    leader_bonus_applied: bool


@dataclass(frozen=True)
class DamageCalculation:
    """
    Result of damage calculation with full breakdown.
    
    Attributes:
        base_damage: Raw damage before modifiers
        final_damage: Actual damage dealt after all modifiers
        was_critical: Whether this was a critical hit
        modifiers_applied: Dict of modifier names to multipliers
        attack_count: Number of attacks in this calculation
    """
    base_damage: int
    final_damage: int
    was_critical: bool
    modifiers_applied: Dict[str, float]
    attack_count: int


@dataclass(frozen=True)
class CombatResult:
    """
    Complete combat resolution result.
    
    Attributes:
        attacker_victory: True if attacker won
        damage_dealt: Total damage dealt by attacker
        damage_taken: Total damage taken by attacker (PvP only)
        attacker_remaining_hp: Attacker's HP after combat
        defender_remaining_hp: Defender's HP after combat
        turns_elapsed: Number of combat turns
        combat_log: List of combat events for display
    """
    attacker_victory: bool
    damage_dealt: int
    damage_taken: int
    attacker_remaining_hp: int
    defender_remaining_hp: int
    turns_elapsed: int
    combat_log: List[str]


# ============================================================================
# COMBAT SERVICE
# ============================================================================

class CombatService:
    """
    Core combat mechanics and power calculation service (RIKI LAW Article III).
    
    Provides centralized combat calculations including:
    - Player power from maiden collection with tier scaling
    - Damage calculations with crits, modifiers, and scaling
    - Combat resolution for PvE and PvP encounters
    - HP management and stat calculations
    - Combat display formatting utilities
    
    All combat state modifications use pessimistic locking (RIKI LAW Article III).
    All combat events are logged for audit trails (RIKI LAW Article II).
    
    Usage:
        >>> # Calculate player power
        >>> power = await CombatService.calculate_total_power(session, player_id)
        >>> breakdown = await CombatService.get_power_breakdown(session, player_id)
        
        >>> # Calculate damage
        >>> damage_calc = CombatService.calculate_damage(
        ...     player_power=5000,
        ...     attack_count=5,
        ...     crit_chance=0.15,
        ...     modifiers={"leader_bonus": 1.10}
        ... )
        
        >>> # Resolve combat
        >>> result = await CombatService.resolve_combat(
        ...     session=session,
        ...     attacker_id=user_id,
        ...     defender_id=enemy_id,
        ...     combat_type="pvp"
        ... )
    """
    
    # ========================================================================
    # POWER CALCULATION
    # ========================================================================
    
    @staticmethod
    async def calculate_total_power(
        session: AsyncSession,
        player_id: int,
        include_leader_bonus: bool = False
    ) -> int:
        """
        Calculate player's total power from ALL owned maidens.
        
        Power = sum(base_atk × quantity) for all maidens
        
        No tier multipliers - tier scaling handled via MaidenBase.base_atk values.
        Higher tier maidens naturally have exponentially higher base_atk from seed data.
        No squad limits, no benching - every maiden contributes.
        Optionally includes leader bonus multiplier.
        
        Args:
            session: Database session
            player_id: Discord ID
            include_leader_bonus: Whether to apply leader ATK bonus
        
        Returns:
            Total ATK value (integer)
        
        Example:
            >>> power = await CombatService.calculate_total_power(session, player_id)
            >>> print(f"Total Power: {power:,}")
        """
        # Calculate base power from all maidens (pure sum, no tier multipliers)
        result = await session.execute(
            select(func.sum(
                MaidenBase.base_atk * Maiden.quantity
            ))
            .join(MaidenBase, Maiden.maiden_base_id == MaidenBase.id)
            .where(Maiden.player_id == player_id)
        )
        base_power = result.scalar_one_or_none()
        total_power = int(base_power) if base_power else 0
        
        # Apply leader bonus if requested
        if include_leader_bonus:
            player = await session.get(Player, player_id)
            if player and player.leader_maiden_id:
                # Get leader bonus from LeaderService
                from src.features.leader.service import LeaderService
                modifiers = await LeaderService.get_active_modifiers(player)
                
                # Check if leader provides ATK bonus (income_boost often scales ATK)
                atk_multiplier = modifiers.get("income_boost", 1.0)
                total_power = int(total_power * atk_multiplier)
                
                logger.debug(
                    f"Applied leader bonus to power calculation "
                    f"(player={player_id}, multiplier={atk_multiplier:.2f}, "
                    f"final_power={total_power:,})"
                )
        
        return total_power
    
    @staticmethod
    async def get_power_breakdown(
        session: AsyncSession,
        player_id: int,
        top_n: int = 10,
        include_leader_bonus: bool = False
    ) -> PowerBreakdown:
        """
        Get detailed breakdown of player power contribution.
        
        Shows top contributing maidens, collection stats, and leader bonus.
        Useful for player stats displays and debugging power calculations.
        
        Args:
            session: Database session
            player_id: Discord ID
            top_n: Number of top contributors to include
            include_leader_bonus: Whether to calculate leader bonus
        
        Returns:
            PowerBreakdown with detailed stats
        
        Example:
            >>> breakdown = await CombatService.get_power_breakdown(session, player_id, top_n=5)
            >>> print(f"Total Power: {breakdown.total_power:,}")
            >>> for maiden in breakdown.top_contributors:
            ...     print(f"{maiden['name']}: {maiden['power']:,} ATK")
        """
        # Fetch all maidens with their bases
        result = await session.execute(
            select(Maiden, MaidenBase)
            .join(MaidenBase, Maiden.maiden_base_id == MaidenBase.id)
            .where(Maiden.player_id == player_id)
        )
        maiden_pairs = result.all()
        
        if not maiden_pairs:
            return PowerBreakdown(
                total_power=0,
                maiden_count=0,
                top_contributors=[],
                average_power=0,
                leader_bonus_applied=False
            )
        
        # Calculate power for each maiden (no tier multipliers)
        maiden_powers = []
        for maiden, maiden_base in maiden_pairs:
            power = int(maiden_base.base_atk * maiden.quantity)
            
            maiden_powers.append({
                "maiden_id": maiden.id,
                "name": maiden_base.name,
                "power": power,
                "tier": maiden.tier,
                "element": maiden.element,
                "quantity": maiden.quantity,
                "base_atk": maiden_base.base_atk
            })
        
        # Sort by power descending
        maiden_powers.sort(key=lambda x: x["power"], reverse=True)
        
        total_power = sum(mp["power"] for mp in maiden_powers)
        total_maidens = sum(mp["quantity"] for mp in maiden_powers)
        average_power = total_power // total_maidens if total_maidens > 0 else 0
        
        # Calculate contribution percentages for top contributors
        top_contributors = []
        for mp in maiden_powers[:top_n]:
            contribution_pct = (mp["power"] / total_power * 100) if total_power > 0 else 0
            top_contributors.append({
                **mp,
                "contribution_percent": round(contribution_pct, 2)
            })
        
        # Apply leader bonus if requested
        leader_bonus_applied = False
        if include_leader_bonus:
            player = await session.get(Player, player_id)
            if player and player.leader_maiden_id:
                from src.features.leader.service import LeaderService
                modifiers = await LeaderService.get_active_modifiers(player)
                atk_multiplier = modifiers.get("income_boost", 1.0)
                
                if atk_multiplier > 1.0:
                    total_power = int(total_power * atk_multiplier)
                    leader_bonus_applied = True
        
        return PowerBreakdown(
            total_power=total_power,
            maiden_count=total_maidens,
            top_contributors=top_contributors,
            average_power=average_power,
            leader_bonus_applied=leader_bonus_applied
        )
    
    # ========================================================================
    # DAMAGE CALCULATION
    # ========================================================================
    
    @staticmethod
    def calculate_damage(
        player_power: int,
        attack_count: int = 1,
        crit_chance: float = 0.0,
        crit_multiplier: float = 1.5,
        modifiers: Optional[Dict[str, float]] = None
    ) -> DamageCalculation:
        """
        Calculate damage dealt based on power and modifiers.
        
        Formula:
            base_damage = player_power × attack_count
            final_damage = base_damage × modifiers × crit_bonus
        
        Args:
            player_power: Total ATK from maiden collection
            attack_count: Number of attacks (1, 5, 20 for ascension)
            crit_chance: Critical hit chance (0.0-1.0)
            crit_multiplier: Critical hit damage multiplier (default 1.5x)
            modifiers: Optional dict of modifier names to multipliers
        
        Returns:
            DamageCalculation with full breakdown
        
        Example:
            >>> damage = CombatService.calculate_damage(
            ...     player_power=5000,
            ...     attack_count=5,
            ...     crit_chance=0.15,
            ...     modifiers={"leader_bonus": 1.10, "event_bonus": 1.20}
            ... )
            >>> print(f"Damage: {damage.final_damage:,} {'CRIT!' if damage.was_critical else ''}")
        """
        import random
        
        # Base damage
        base_damage = player_power * attack_count
        
        # Roll for critical hit
        was_critical = random.random() < crit_chance
        
        # Apply modifiers
        applied_modifiers = modifiers or {}
        total_multiplier = 1.0
        
        for modifier_name, multiplier in applied_modifiers.items():
            total_multiplier *= multiplier
        
        # Apply crit multiplier
        if was_critical:
            total_multiplier *= crit_multiplier
            applied_modifiers["critical_hit"] = crit_multiplier
        
        # Calculate final damage
        final_damage = int(base_damage * total_multiplier)
        
        logger.debug(
            f"Damage calculation: base={base_damage:,}, modifiers={applied_modifiers}, "
            f"final={final_damage:,}, crit={was_critical}"
        )
        
        return DamageCalculation(
            base_damage=base_damage,
            final_damage=final_damage,
            was_critical=was_critical,
            modifiers_applied=applied_modifiers,
            attack_count=attack_count
        )
    
    @staticmethod
    def calculate_attacks_needed(player_power: int, enemy_hp: int) -> int:
        """
        Estimate attacks needed to defeat enemy.
        
        Useful for UI displays showing estimated combat length.
        
        Args:
            player_power: Total ATK from maidens
            enemy_hp: Enemy total HP
        
        Returns:
            Number of attacks needed (minimum 1, max 999 if no power)
        
        Example:
            >>> attacks = CombatService.calculate_attacks_needed(5000, 25000)
            >>> print(f"Estimated attacks to win: {attacks}")
        """
        if player_power == 0:
            return 999
        
        import math
        return max(1, math.ceil(enemy_hp / player_power))
    
    # ========================================================================
    # COMBAT RESOLUTION
    # ========================================================================
    
    @staticmethod
    async def resolve_combat(
        session: AsyncSession,
        attacker_id: int,
        defender_id: int,
        combat_type: str = "pve",
        attacker_attacks: int = 1
    ) -> CombatResult:
        """
        Resolve complete combat encounter between attacker and defender.
        
        Handles both PvE (player vs enemy) and PvP (player vs player) combat.
        Uses pessimistic locking for combat state (RIKI LAW Article III).
        Logs complete combat transaction for audit trail (RIKI LAW Article II).
        
        Args:
            session: Database session (must be in transaction)
            attacker_id: Attacker's player ID
            defender_id: Defender's player ID or enemy ID
            combat_type: "pve" or "pvp"
            attacker_attacks: Number of attacks attacker performs
        
        Returns:
            CombatResult with full combat resolution
        
        Raises:
            CombatError: If combat cannot be resolved
        
        Example:
            >>> async with DatabaseService.get_transaction() as session:
            ...     result = await CombatService.resolve_combat(
            ...         session=session,
            ...         attacker_id=user_id,
            ...         defender_id=enemy_id,
            ...         combat_type="pve",
            ...         attacker_attacks=5
            ...     )
            ...     if result.attacker_victory:
            ...         print(f"Victory! Dealt {result.damage_dealt:,} damage")
        """
        async with LogContext(user_id=attacker_id, combat_type=combat_type):
            # Fetch attacker with lock
            attacker = await session.get(Player, attacker_id, with_for_update=True)
            if not attacker:
                raise CombatError(f"Attacker player {attacker_id} not found")
            
            # Calculate attacker power
            attacker_power = await CombatService.calculate_total_power(
                session=session,
                player_id=attacker_id,
                include_leader_bonus=True
            )
            
            # Get combat configuration
            crit_chance = ConfigManager.get("combat.crit_chance", 0.1)
            crit_multiplier = ConfigManager.get("combat.crit_multiplier", 1.5)
            
            # Calculate damage
            damage_calc = CombatService.calculate_damage(
                player_power=attacker_power,
                attack_count=attacker_attacks,
                crit_chance=crit_chance,
                crit_multiplier=crit_multiplier
            )
            
            combat_log = []
            combat_log.append(
                f"⚔️ Attacker power: {attacker_power:,} ATK × {attacker_attacks} attacks"
            )
            combat_log.append(
                CombatService.format_damage_display(
                    damage=damage_calc.final_damage,
                    is_crit=damage_calc.was_critical
                )
            )
            
            # Log combat transaction
            await TransactionLogger.log_transaction(
                session=session,
                player_id=attacker_id,
                transaction_type=f"combat_{combat_type}",
                details={
                    "defender_id": defender_id,
                    "attacker_power": attacker_power,
                    "damage_dealt": damage_calc.final_damage,
                    "was_critical": damage_calc.was_critical,
                    "attack_count": attacker_attacks,
                    "modifiers": damage_calc.modifiers_applied
                },
                context=f"combat_resolution:{combat_type}"
            )
            
            logger.info(
                f"Combat resolved: attacker={attacker_id}, defender={defender_id}, "
                f"type={combat_type}, damage={damage_calc.final_damage:,}, "
                f"crit={damage_calc.was_critical}"
            )
            
            # For now, return simplified result (expand for full combat system)
            return CombatResult(
                attacker_victory=True,  # Will be calculated based on HP
                damage_dealt=damage_calc.final_damage,
                damage_taken=0,  # PvP only
                attacker_remaining_hp=100,  # Placeholder
                defender_remaining_hp=0,  # Placeholder
                turns_elapsed=1,
                combat_log=combat_log
            )
    
    # ========================================================================
    # DISPLAY UTILITIES
    # ========================================================================
    
    @staticmethod
    def render_hp_bar(current_hp: int, max_hp: int, width: int = 20) -> str:
        """
        Render ASCII HP bar using Unicode blocks.
        
        Args:
            current_hp: Current HP value
            max_hp: Maximum HP value
            width: Bar width in characters (default 20)
        
        Returns:
            Formatted HP bar string
        
        Example:
            >>> bar = CombatService.render_hp_bar(7500, 10000, 20)
            >>> print(bar)
            '███████████████░░░░░'
        """
        if max_hp == 0:
            return "░" * width
        
        filled_width = int((current_hp / max_hp) * width)
        filled_width = max(0, min(width, filled_width))
        empty_width = width - filled_width
        
        return "█" * filled_width + "░" * empty_width
    
    @staticmethod
    def render_hp_percentage(current_hp: int, max_hp: int) -> str:
        """
        Render HP as percentage string.
        
        Returns:
            Formatted percentage (e.g., "75%")
        """
        if max_hp == 0:
            return "0%"
        
        percent = int((current_hp / max_hp) * 100)
        return f"{percent}%"
    
    @staticmethod
    def format_damage_display(damage: int, is_crit: bool = False) -> str:
        """
        Format damage number for display with appropriate styling.
        
        Args:
            damage: Damage value
            is_crit: Whether this is a critical hit
        
        Returns:
            Formatted damage string with emojis
        
        Example:
            >>> print(CombatService.format_damage_display(5000, is_crit=False))
            '⚔️ 5,000'
            >>> print(CombatService.format_damage_display(7500, is_crit=True))
            '💥 **7,500** ✨ CRITICAL!'
        """
        formatted = f"{damage:,}"
        
        if is_crit:
            return f"💥 **{formatted}** ✨ CRITICAL!"
        else:
            return f"⚔️ {formatted}"
    
    @staticmethod
    def format_combat_log_entry(
        attacker_name: str,
        damage: int,
        current_hp: int,
        max_hp: int,
        is_crit: bool = False
    ) -> str:
        """
        Format single combat log entry with HP bar.
        
        Args:
            attacker_name: Name of attacker
            damage: Damage dealt
            current_hp: Defender's current HP
            max_hp: Defender's max HP
            is_crit: Whether this was a critical hit
        
        Returns:
            Formatted combat log entry
        
        Example:
            >>> entry = CombatService.format_combat_log_entry(
            ...     "Ember", 5000, 15000, 20000, is_crit=True
            ... )
            >>> print(entry)
            '💥 Ember dealt **5,000** damage! ✨ CRITICAL!\n███████████████░░░░░ 15,000 / 20,000 HP'
        """
        damage_text = CombatService.format_damage_display(damage, is_crit)
        hp_bar = CombatService.render_hp_bar(current_hp, max_hp, width=20)
        hp_text = f"{current_hp:,} / {max_hp:,} HP"
        
        return f"{attacker_name} dealt {damage_text}\n{hp_bar} {hp_text}"
    
    @staticmethod
    def get_element_emoji(element: str) -> str:
        """
        Get emoji for element type.
        
        Args:
            element: Element name (infernal, abyssal, etc.)
        
        Returns:
            Element emoji
        """
        emojis = {
            "infernal": "🔥",
            "abyssal": "💧",
            "tempest": "🌪️",
            "earth": "🌿",
            "radiant": "✨",
            "umbral": "🌑",
        }
        return emojis.get(element.lower(), "⚪")
    
    @staticmethod
    def get_rarity_emoji(rarity: str) -> str:
        """
        Get emoji for rarity tier.
        
        Args:
            rarity: Rarity name (common, rare, epic, etc.)
        
        Returns:
            Rarity emoji
        """
        emojis = {
            "common": "⚪",
            "uncommon": "🟢",
            "rare": "🔵",
            "epic": "🟣",
            "legendary": "🟠",
            "mythic": "🔴",
        }
        return emojis.get(rarity.lower(), "⚪")