"""
Combat and progression utilities.

Contains business logic for:
- Power calculations (database queries)
- Power breakdown analysis
- Combat utilities with display helpers

Display formatting methods are being migrated to src.ui.formatters
and maintained here as backward-compatible wrappers.
"""

from typing import Dict, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.database.models.core.maiden import Maiden
from database.models.core.maiden_base import MaidenBase
from src.core.logging.logger import get_logger
from src.ui.emojis import Emojis
from src.ui.formatters import CombatFormatters, ProgressFormatters

logger = get_logger(__name__)


class CombatUtils:
    """
    Shared utility functions for combat and power calculations.
    
    Provides centralized power calculation from maiden collection,
    HP bar rendering, and combat display formatting.
    
    Usage:
        >>> power = await CombatUtils.calculate_total_power(session, player_id)
        >>> hp_bar = CombatUtils.render_hp_bar(5000, 10000, width=20)
    """
    
    @staticmethod
    async def calculate_total_power(session: AsyncSession, player_id: int) -> int:
        """
        Calculate player's total power from ALL owned maidens.
        
        Power = sum of all maiden ATK stats.
        No squad limits, no benching - every maiden contributes.
        
        Args:
            session: Database session
            player_id: Discord ID
        
        Returns:
            Total ATK value
        """
        result = await session.execute(
            select(func.sum(MaidenBase.base_atk * Maiden.quantity * (1 + (Maiden.tier - 1) * 0.5)))
            .join(MaidenBase, Maiden.maiden_base_id == MaidenBase.id)
            .where(Maiden.player_id == player_id)
        )
        total_power = result.scalar_one_or_none()
        
        return total_power if total_power else 0
    
    @staticmethod
    async def get_power_breakdown(session: AsyncSession, player_id: int, limit: int = 10) -> Dict:
        """
        Get detailed breakdown of player power contribution.

        Shows top contributing maidens and collection stats.

        Args:
            session: Database session
            player_id: Discord ID
            limit: Number of top maidens to return

        Returns:
            Dictionary with:
                - total_power: Total ATK
                - maiden_count: Total maidens owned
                - top_maidens: List of top contributors
                - average_atk: Average ATK per maiden
        """
        # ✅ Fixed: Use correct column name and join with MaidenBase
        result = await session.execute(
            select(Maiden, MaidenBase)
            .join(MaidenBase, Maiden.maiden_base_id == MaidenBase.id)
            .where(Maiden.player_id == player_id)  # ✅ Fixed: player_id instead of owner_id
        )
        maiden_pairs = result.all()

        if not maiden_pairs:
            return {
                "total_power": 0,
                "maiden_count": 0,
                "top_maidens": [],
                "average_atk": 0
            }

        # Calculate power for each maiden (base_atk * quantity * tier multiplier)
        maiden_powers = []
        for maiden, maiden_base in maiden_pairs:
            power = maiden_base.base_atk * maiden.quantity * (1 + (maiden.tier - 1) * 0.5)
            maiden_powers.append({
                "maiden": maiden,
                "maiden_base": maiden_base,
                "power": int(power)
            })

        # Sort by power descending
        maiden_powers.sort(key=lambda x: x["power"], reverse=True)

        total_power = sum(mp["power"] for mp in maiden_powers)
        total_maidens = sum(mp["maiden"].quantity for mp in maiden_powers)
        average_atk = total_power / total_maidens if total_maidens > 0 else 0

        top_maidens = [
            {
                "id": mp["maiden"].id,
                "name": mp["maiden_base"].name,
                "atk": mp["power"],
                "tier": mp["maiden"].tier,
                "element": mp["maiden"].element,
                "quantity": mp["maiden"].quantity,
                "contribution_percent": (mp["power"] / total_power) * 100 if total_power > 0 else 0
            }
            for mp in maiden_powers[:limit]
        ]

        return {
            "total_power": total_power,
            "maiden_count": total_maidens,
            "top_maidens": top_maidens,
            "average_atk": int(average_atk)
        }
    
    @staticmethod
    def render_hp_bar(current_hp: int, max_hp: int, width: int = 20) -> str:
        """
        Render ASCII HP bar using Unicode blocks.

        ⚠️ DEPRECATED: Use src.ui.formatters.CombatFormatters.render_hp_bar instead
        This wrapper maintained for backward compatibility.

        Args:
            current_hp: Current HP value
            max_hp: Maximum HP value
            width: Bar width in characters

        Returns:
            Formatted HP bar string
        """
        return CombatFormatters.render_hp_bar(current_hp, max_hp, width)
    
    @staticmethod
    def render_hp_percentage(current_hp: int, max_hp: int) -> str:
        """
        Render HP as percentage string.

        ⚠️ DEPRECATED: Use src.ui.formatters.CombatFormatters.render_hp_percentage instead
        This wrapper maintained for backward compatibility.

        Returns:
            Formatted percentage (e.g., "75%")
        """
        return CombatFormatters.render_hp_percentage(current_hp, max_hp)
    
    @staticmethod
    def format_damage_display(damage: int, is_crit: bool = False) -> str:
        """
        Format damage number for display.

        ⚠️ DEPRECATED: Use src.ui.formatters.CombatFormatters.format_damage_display instead
        This wrapper maintained for backward compatibility.

        Args:
            damage: Damage value
            is_crit: Whether this is a critical hit

        Returns:
            Formatted damage string with emojis
        """
        return CombatFormatters.format_damage_display(damage, is_crit)

    @staticmethod
    def get_element_emoji(element: str) -> str:
        """
        Get emoji for element type.

        ⚠️ DEPRECATED: Use src.ui.formatters.CombatFormatters.get_element_emoji instead
        This wrapper maintained for backward compatibility.

        Returns:
            Element emoji
        """
        return CombatFormatters.get_element_emoji(element)

    @staticmethod
    def get_rarity_emoji(rarity: str) -> str:
        """
        Get emoji for rarity tier.

        ⚠️ DEPRECATED: Use src.ui.formatters.CombatFormatters.get_rarity_emoji instead
        This wrapper maintained for backward compatibility.

        Returns:
            Rarity emoji
        """
        return CombatFormatters.get_rarity_emoji(rarity)

    @staticmethod
    def format_combat_log_entry(
        attacker: str,
        damage: int,
        current_hp: int,
        max_hp: int,
        is_crit: bool = False
    ) -> str:
        """
        Format single combat log entry.

        ⚠️ DEPRECATED: Use src.ui.formatters.CombatFormatters.format_combat_log_entry instead
        This wrapper maintained for backward compatibility.

        Returns:
            Formatted combat log line
        """
        return CombatFormatters.format_combat_log_entry(attacker, damage, current_hp, max_hp, is_crit)


class ProgressUtils:
    """
    Utility functions for progression tracking and display.
    
    Provides progress bar rendering, unlock checks, and stat formatting.
    """
    
    @staticmethod
    def render_progress_bar(progress: float, width: int = 20) -> str:
        """
        Render progress bar for sector exploration.

        ⚠️ DEPRECATED: Use src.ui.formatters.ProgressFormatters.render_progress_bar instead
        This wrapper maintained for backward compatibility.

        Args:
            progress: Progress percentage (0.0 - 100.0)
            width: Bar width in characters

        Returns:
            Formatted progress bar
        """
        return ProgressFormatters.render_progress_bar(progress, width)

    @staticmethod
    def format_progress_display(progress: float) -> str:
        """
        Format progress as percentage with color coding.

        ⚠️ DEPRECATED: Use src.ui.formatters.ProgressFormatters.format_progress_display instead
        This wrapper maintained for backward compatibility.

        Returns:
            Formatted string
        """
        return ProgressFormatters.format_progress_display(progress)

    @staticmethod
    def format_resource_cost(resource: str, amount: int) -> str:
        """
        Format resource cost display.

        ⚠️ DEPRECATED: Use src.ui.formatters.ProgressFormatters.format_resource_cost instead
        This wrapper maintained for backward compatibility.

        Args:
            resource: Resource type (energy, stamina, gems)
            amount: Cost amount

        Returns:
            Formatted string with emoji
        """
        return ProgressFormatters.format_resource_cost(resource, amount)

    @staticmethod
    def format_reward_display(reward_type: str, amount: int) -> str:
        """
        Format reward display with appropriate emoji.

        ⚠️ DEPRECATED: Use src.ui.formatters.ProgressFormatters.format_reward_display instead
        This wrapper maintained for backward compatibility.

        Returns:
            Formatted reward string
        """
        return ProgressFormatters.format_reward_display(reward_type, amount)