"""
Combat calculation and resolution service.

LUMEN LAW Compliance: Article III (Service Layer), Article II (Audit Trails)
- Pure business logic with no Discord dependencies
- Comprehensive transaction logging for all combat events
- Pessimistic locking for combat state modifications
- Dual power calculation: Strategic (best 6) and Total (all maidens)

Features:
- Strategic power calculation (best 6 maidens, one per element)
- Total power calculation (all maidens)
- Element-based general bonuses
- Damage calculations with modifiers, crits, and scaling
- Turn-based combat resolution with HP management
- Boss counter-attack damage calculation

Combat Modes:
1. Strategic (Ascension): Best 6 maidens, boss fights back, HP at risk
2. Total (Exploration): All maidens, speed-based, no retaliation
"""

from typing import Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from dataclasses import dataclass
import secrets

from src.database.models.core.player import Player
from src.database.models.core.maiden import Maiden
from database.models.core.maiden_base import MaidenBase
from src.core.config import ConfigManager
from src.core.infra.transaction_logger import TransactionLogger
from src.core.exceptions import CombatError
from src.core.logging.logger import get_logger, LogContext

logger = get_logger(__name__)


# ============================================================================
# COMBAT DATA STRUCTURES
# ============================================================================

@dataclass(frozen=True)
class StrategicPower:
    """
    Strategic power breakdown from best 6 maidens.
    
    Attributes:
        total_power: Total ATK from 6 generals
        total_defense: Total DEF from 6 generals
        generals: Dict of element -> general data
        element_bonuses: List of active element bonuses
    """
    total_power: int
    total_defense: int
    generals: Dict[str, Dict]
    element_bonuses: List[Dict[str, str]]


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
class CombatTurn:
    """
    Complete combat turn result.
    
    Attributes:
        player_damage: Damage dealt by player
        boss_damage: Damage dealt by boss (to player HP)
        player_hp: Player HP after turn
        boss_hp: Boss HP after turn
        critical: Whether player crit
        momentum: Current momentum level (0-100)
        victory: True if boss defeated
        defeat: True if player defeated
        combat_log: Turn description
    """
    player_damage: int
    boss_damage: int
    player_hp: int
    boss_hp: int
    critical: bool
    momentum: int
    victory: bool
    defeat: bool
    combat_log: List[str]


# ============================================================================
# ELEMENT BONUS DEFINITIONS
# ============================================================================
# NOTE: Element bonuses now configured via ConfigManager.get("combat_element_bonuses.{element}")
# This allows live balance tuning without code changes (LUMEN LAW Article IV)


# ============================================================================
# COMBAT SERVICE
# ============================================================================

class CombatService:
    """
    Core combat mechanics service (LUMEN LAW Article III).
    
    Provides dual power calculation modes and combat resolution.
    """
    
    # ========================================================================
    # STRATEGIC POWER CALCULATION (ASCENSION)
    # ========================================================================
    
    @staticmethod
    async def calculate_strategic_power(
        session: AsyncSession,
        player_id: int,
        include_leader_bonus: bool = True
    ) -> StrategicPower:
        """
        Calculate power from best 6 maidens (one per element).
        
        This is MUCH lower than total power, designed for challenging combat.
        Used for Ascension tower climbing.
        
        Formula:
            - Select highest ATK maiden in each element
            - Sum their (base_atk × quantity)
            - Apply leader bonus if requested
            - Apply element bonuses
        
        Args:
            session: Database session
            player_id: Discord ID
            include_leader_bonus: Whether to apply leader multiplier
        
        Returns:
            StrategicPower dataclass with full breakdown
        
        Example:
            >>> strategic = await CombatService.calculate_strategic_power(session, player_id)
            >>> print(f"Strategic Power: {strategic.total_power:,}")
            >>> print(f"Generals: {len(strategic.generals)}/6")
        """
        elements = ["infernal", "abyssal", "tempest", "earth", "radiant", "umbral"]
        generals = {}
        total_power = 0
        total_defense = 0
        
        for element in elements:
            # Get strongest maiden in this element
            result = await session.execute(
                select(Maiden, MaidenBase)
                .join(MaidenBase, Maiden.maiden_base_id == MaidenBase.id)
                .where(
                    Maiden.player_id == player_id,
                    MaidenBase.element == element
                )
                .order_by((MaidenBase.base_atk * Maiden.quantity).desc())
                .limit(1)
            )
            maiden_pair = result.first()
            
            if maiden_pair:
                maiden, maiden_base = maiden_pair
                maiden_power = maiden_base.base_atk * maiden.quantity
                maiden_defense = maiden_base.base_def * maiden.quantity
                
                generals[element] = {
                    "maiden_id": maiden.id,
                    "name": maiden_base.name,
                    "atk": maiden_power,
                    "def": maiden_defense,
                    "tier": maiden.tier,
                    "quantity": maiden.quantity,
                    "element": element
                }
                
                total_power += maiden_power
                total_defense += maiden_defense
        
        # Apply element bonuses (LUMEN LAW I.6 - YAML is source of truth)
        if "infernal" in generals:
            multiplier = ConfigManager.get("combat_element_bonuses.infernal.multiplier")
            total_power = int(total_power * multiplier)

        if "abyssal" in generals:
            multiplier = ConfigManager.get("combat_element_bonuses.abyssal.multiplier")
            total_defense = int(total_defense * multiplier)
        
        # Apply leader bonus
        if include_leader_bonus:
            player = await session.get(Player, player_id)
            if player and player.leader_maiden_id:
                from src.modules.maiden.leader_service import LeaderService
                modifiers = await LeaderService.get_active_modifiers(player)
                
                atk_multiplier = modifiers.get("income_boost", 1.0)
                total_power = int(total_power * atk_multiplier)
        
        # Get element bonuses list
        element_bonuses = CombatService._format_element_bonuses(generals)
        
        logger.info(
            f"Strategic power calculated: player={player_id}, power={total_power:,}, "
            f"def={total_defense:,}, generals={len(generals)}/6"
        )
        
        return StrategicPower(
            total_power=total_power,
            total_defense=total_defense,
            generals=generals,
            element_bonuses=element_bonuses
        )
    
    @staticmethod
    def _format_element_bonuses(generals: Dict[str, Dict]) -> List[Dict[str, str]]:
        """
        Format active element bonuses for display.

        Returns list of active bonuses with emoji and description.
        """
        bonuses = []

        for element, general in generals.items():
            bonus_data = ConfigManager.get(f"combat_element_bonuses.{element}")
            if bonus_data:
                bonuses.append({
                    "element": element,
                    "emoji": bonus_data.get("emoji", "❓"),
                    "name": bonus_data.get("name", element.capitalize()),
                    "bonus": bonus_data.get("bonus_text", "Unknown")
                })

        return bonuses
    
    # ========================================================================
    # TOTAL POWER CALCULATION (EXPLORATION)
    # ========================================================================
    
    @staticmethod
    async def calculate_total_power(
        session: AsyncSession,
        player_id: int,
        include_leader_bonus: bool = True
    ) -> int:
        """
        Calculate player's total power from ALL maidens.
        
        Used for Exploration (Matrons) where full collection matters.
        
        Formula:
            Power = Σ(base_atk × quantity) × leader_bonus
        
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
        # Calculate base power from all maidens
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
                from src.modules.maiden.leader_service import LeaderService
                modifiers = await LeaderService.get_active_modifiers(player)
                atk_multiplier = modifiers.get("income_boost", 1.0)
                total_power = int(total_power * atk_multiplier)
        
        logger.debug(f"Total power calculated: player={player_id}, power={total_power:,}")
        
        return total_power
    
    # ========================================================================
    # DAMAGE CALCULATION
    # ========================================================================
    
    @staticmethod
    def calculate_damage(
        player_power: int,
        attack_count: int = 1,
        crit_chance: float = 0.0,
        crit_multiplier: float = 1.5,
        momentum_level: int = 0,
        modifiers: Optional[Dict[str, float]] = None
    ) -> DamageCalculation:
        """
        Calculate damage dealt based on power and modifiers.
        
        Formula:
            base_damage = player_power × attack_count
            momentum_bonus = 1.0 + (momentum_level dependent)
            final_damage = base_damage × momentum_bonus × modifiers × crit_bonus
        
        Args:
            player_power: Total ATK from maiden collection
            attack_count: Number of attacks (1, 3, 10)
            crit_chance: Critical hit chance (0.0-1.0)
            crit_multiplier: Critical hit damage multiplier (default 1.5x)
            momentum_level: Current momentum (0-100)
            modifiers: Optional dict of modifier names to multipliers
        
        Returns:
            DamageCalculation with full breakdown
        """
        import random

        # Base damage
        base_damage = player_power * attack_count

        # Momentum bonus (LUMEN LAW I.6 - YAML is source of truth)
        momentum_config = ConfigManager.get("combat_mechanics.momentum.thresholds")
        momentum_mult = 1.0

        # Evaluate thresholds in descending order
        if momentum_config:
            threshold_levels = ["high", "medium", "low", "none"]
            for level in threshold_levels:
                level_config = momentum_config.get(level, {})
                threshold = level_config.get("threshold", 0)
                if momentum_level >= threshold:
                    momentum_mult = level_config.get("multiplier", 1.0)
                    break
        
        # Roll for critical hit using cryptographically secure RNG
        was_critical = secrets.SystemRandom().random() < crit_chance
        
        # Apply modifiers
        applied_modifiers = modifiers or {}
        total_multiplier = momentum_mult
        
        for modifier_name, multiplier in applied_modifiers.items():
            total_multiplier *= multiplier
        
        # Apply crit multiplier
        if was_critical:
            total_multiplier *= crit_multiplier
            applied_modifiers["critical_hit"] = crit_multiplier
        
        if momentum_level > 0:
            applied_modifiers["momentum"] = momentum_mult
        
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
    
    # ========================================================================
    # BOSS DAMAGE CALCULATION
    # ========================================================================
    
    @staticmethod
    def calculate_boss_damage_to_player(
        boss_atk: int,
        generals_total_def: int,
        umbral_general_present: bool = False
    ) -> int:
        """
        Calculate damage boss deals to player HP.
        
        Formula:
            1. Apply Umbral reduction if present: boss_atk × 0.95
            2. Subtract generals' total DEF
            3. Minimum 1 damage
        
        Args:
            boss_atk: Boss attack stat
            generals_total_def: Sum of 6 generals' defense
            umbral_general_present: Whether umbral general active
        
        Returns:
            Damage dealt to player (minimum 1)
        """
        # Apply umbral reduction (LUMEN LAW I.6 - YAML is source of truth)
        effective_boss_atk = boss_atk
        if umbral_general_present:
            multiplier = ConfigManager.get("combat_element_bonuses.umbral.multiplier")
            effective_boss_atk = int(boss_atk * multiplier)
        
        # Calculate damage
        raw_damage = effective_boss_atk - generals_total_def
        final_damage = max(1, raw_damage)
        
        logger.debug(
            f"Boss damage calc: boss_atk={boss_atk}, "
            f"umbral_reduction={umbral_general_present}, "
            f"effective_atk={effective_boss_atk}, "
            f"generals_def={generals_total_def}, "
            f"raw={raw_damage}, final={final_damage}"
        )
        
        return final_damage
    
    # ========================================================================
    # UTILITY
    # ========================================================================
    
    @staticmethod
    def calculate_attacks_needed(player_power: int, enemy_hp: int) -> int:
        """
        Estimate attacks needed to defeat enemy.
        
        Args:
            player_power: Total ATK
            enemy_hp: Enemy HP
        
        Returns:
            Number of attacks needed (minimum 1, max 999 if no power)
        """
        if player_power == 0:
            return 999
        
        import math
        return max(1, math.ceil(enemy_hp / player_power))
    
    @staticmethod
    def render_hp_bar(current_hp: int, max_hp: int, width: int = 10) -> str:
        """
        Render ASCII HP bar using Unicode blocks.
        
        Args:
            current_hp: Current HP value
            max_hp: Maximum HP value
            width: Bar width in characters (default 10)
        
        Returns:
            Formatted HP bar string
        """
        if max_hp == 0:
            return "░" * width
        
        filled_width = int((current_hp / max_hp) * width)
        filled_width = max(0, min(width, filled_width))
        empty_width = width - filled_width
        
        return "█" * filled_width + "░" * empty_width
    
    @staticmethod
    def get_element_emoji(element: str) -> str:
        """Get emoji for element type."""
        bonus_data = ConfigManager.get(f"combat_element_bonuses.{element}")
        if bonus_data:
            return bonus_data.get("emoji", "⚪")
        return "⚪"