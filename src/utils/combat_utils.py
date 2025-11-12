from typing import Dict, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.database.models.core.maiden import Maiden
from src.database.models.core.maiden_base import MaidenBase
from src.core.logging.logger import get_logger

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
        
        Args:
            current_hp: Current HP value
            max_hp: Maximum HP value
            width: Bar width in characters
        
        Returns:
            Formatted HP bar string
        
        Example:
            >>> CombatUtils.render_hp_bar(7500, 10000, 20)
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
        Format damage number for display.
        
        Args:
            damage: Damage value
            is_crit: Whether this is a critical hit
        
        Returns:
            Formatted damage string with emojis
        """
        formatted = f"{damage:,}"
        
        if is_crit:
            return f"💥 **{formatted}** ✨ CRITICAL!"
        else:
            return f"⚔️ {formatted}"
    
    @staticmethod
    def get_element_emoji(element: str) -> str:
        """
        Get emoji for element type.
        
        Returns:
            Element emoji
        """
        emojis = {
            "infernal": "🔥",
            "abyssal": "💧",
            "tempest": "🌪️",
            "earth": "🌿",
            "Radiant": "✨",
            "umbral": "🌑",
        }
        return emojis.get(element, "⚪")
    
    @staticmethod
    def get_rarity_emoji(rarity: str) -> str:
        """
        Get emoji for rarity tier.
        
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
        return emojis.get(rarity, "⚪")
    
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
        
        Returns:
            Formatted combat log line
        """
        damage_display = CombatUtils.format_damage_display(damage, is_crit)
        hp_bar = CombatUtils.render_hp_bar(current_hp, max_hp, width=20)
        hp_percent = CombatUtils.render_hp_percentage(current_hp, max_hp)
        
        return f"{damage_display}\n{hp_bar} {hp_percent}\nHP: {current_hp:,} / {max_hp:,}"


class ProgressUtils:
    """
    Utility functions for progression tracking and display.
    
    Provides progress bar rendering, unlock checks, and stat formatting.
    """
    
    @staticmethod
    def render_progress_bar(progress: float, width: int = 20) -> str:
        """
        Render progress bar for sector exploration.
        
        Args:
            progress: Progress percentage (0.0 - 100.0)
            width: Bar width in characters
        
        Returns:
            Formatted progress bar
        """
        filled_width = int((progress / 100.0) * width)
        filled_width = max(0, min(width, filled_width))
        empty_width = width - filled_width
        
        return "━" * filled_width + "░" * empty_width
    
    @staticmethod
    def format_progress_display(progress: float) -> str:
        """
        Format progress as percentage with color coding.
        
        Returns:
            Formatted string
        """
        if progress < 25:
            emoji = "🔴"
        elif progress < 50:
            emoji = "🟠"
        elif progress < 75:
            emoji = "🟡"
        elif progress < 100:
            emoji = "🟢"
        else:
            emoji = "✅"
        
        return f"{emoji} {progress:.1f}%"
    
    @staticmethod
    def format_resource_cost(resource: str, amount: int) -> str:
        """
        Format resource cost display.
        
        Args:
            resource: Resource type (energy, stamina, gems)
            amount: Cost amount
        
        Returns:
            Formatted string with emoji
        """
        emojis = {
            "energy": "🪙",
            "stamina": "💪",
            "lumenite": "💎",
            "lumees": "💰",
            "auric_coin": "💎",
        }
        
        emoji = emojis.get(resource, "•")
        return f"{emoji} {amount}"
    
    @staticmethod
    def format_reward_display(reward_type: str, amount: int) -> str:
        """
        Format reward display with appropriate emoji.
        
        Returns:
            Formatted reward string
        """
        emojis = {
            "lumees": "💰",
            "xp": "⭐",
            "lumenite": "💎",
            "auric_coin": "💎",
            "DROP_CHARGES": "💎",
            "fusion_catalyst": "🔮",
        }
        
        emoji = emojis.get(reward_type, "✨")
        return f"{emoji} +{amount:,}"