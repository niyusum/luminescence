# src/ui/embeds.py
"""
Enhanced embed factory for Discord embeds across Lumen systems.

Extends EmbedBuilder with additional specialized builders for:
- Combat encounters
- Leaderboards
- Collection displays
- Transaction history

Features:
- Consistent branding and colors
- Type-safe embed creation
- Automatic Discord limits enforcement
- Specialized builders for common patterns
- Element/tier-aware coloring
- Integration with ColorTheme and BrandingTheme

Usage:
    >>> from src.ui.embeds import EmbedFactory
    >>> embed = EmbedFactory.success("Victory!", "You won the battle!")
    >>> embed = EmbedFactory.combat_encounter("Boss Fight", enemy, player, mechanics, rewards)
"""

import discord
from datetime import datetime
from typing import Optional, List, Dict, Any

from src.modules.maiden.constants import EmbedColor, UIConstants
from src.ui.emojis import Emojis
from src.ui.colors import ColorTheme
from src.ui.themes import BrandingTheme, FieldTemplates


class EmbedFactory:
    """
    Enhanced factory for standardized Discord embeds across Lumen systems.

    Ensures consistent branding, tone, and hierarchy.
    All embeds automatically include timestamps and enforce Discord limits.
    """

    @staticmethod
    def _base_embed(
        title: str,
        description: str,
        color: int,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """
        Create base embed with automatic limit enforcement.

        Args:
            title: Embed title (max 256 chars)
            description: Embed description (max 4096 chars)
            color: Discord color integer
            footer: Optional footer text (max 2048 chars)

        Returns:
            Discord Embed object
        """
        # Enforce Discord limits
        title = UIConstants.truncate_text(title, UIConstants.EMBED_TITLE_LIMIT)
        description = UIConstants.truncate_text(description, UIConstants.EMBED_DESCRIPTION_LIMIT)

        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )

        if footer:
            footer = UIConstants.truncate_text(footer, UIConstants.EMBED_FOOTER_LIMIT)
            embed.set_footer(text=footer)

        return embed

    # =========================================================================
    # CORE TYPES
    # =========================================================================

    @staticmethod
    def primary(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Default embed for neutral/system messages."""
        return EmbedFactory._base_embed(
            title, description, EmbedColor.DEFAULT, footer or BrandingTheme.DEFAULT_FOOTER
        )

    @staticmethod
    def success(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Positive actions (rewards, victories, confirmations)."""
        return EmbedFactory._base_embed(
            title, description, EmbedColor.SUCCESS, footer or BrandingTheme.DEFAULT_FOOTER
        )

    @staticmethod
    def error(
        title: str,
        description: str,
        help_text: Optional[str] = None
    ) -> discord.Embed:
        """
        Error embeds with optional help text.

        Args:
            title: Error title
            description: Error description
            help_text: Optional helpful suggestion for user
        """
        desc = description
        if help_text:
            desc += f"\n\n{Emojis.TIP} **Help:** {help_text}"
        return EmbedFactory._base_embed(title, desc, EmbedColor.ERROR)

    @staticmethod
    def warning(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """For recoverable issues or alerts."""
        return EmbedFactory._base_embed(
            title, description, EmbedColor.WARNING, footer or BrandingTheme.DEFAULT_FOOTER
        )

    @staticmethod
    def info(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Informational messages."""
        return EmbedFactory._base_embed(
            title, description, EmbedColor.INFO, footer or BrandingTheme.DEFAULT_FOOTER
        )

    # =========================================================================
    # GAME-SPECIFIC TYPES
    # =========================================================================

    @staticmethod
    def fusion_success(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Successful fusion embeds."""
        return EmbedFactory._base_embed(
            title, description, EmbedColor.FUSION_SUCCESS, footer or BrandingTheme.get_footer("fusion")
        )

    @staticmethod
    def fusion_fail(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Failed fusion embeds."""
        return EmbedFactory._base_embed(
            title, description, EmbedColor.FUSION_FAIL, footer or BrandingTheme.get_footer("fusion")
        )

    @staticmethod
    def summon(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Summon/gacha embeds."""
        return EmbedFactory._base_embed(
            title, description, EmbedColor.SUMMON, footer or BrandingTheme.get_footer("summon")
        )

    @staticmethod
    def level_up(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Level up celebration embeds."""
        return EmbedFactory._base_embed(
            title, description, EmbedColor.LEVEL_UP, footer or BrandingTheme.get_footer("progression")
        )

    @staticmethod
    def drop(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """DROP system embeds."""
        return EmbedFactory._base_embed(
            title, description, EmbedColor.DROP, footer or BrandingTheme.get_footer("drop")
        )

    @staticmethod
    def ascension(
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Ascension tower embeds."""
        return EmbedFactory._base_embed(
            title, description, EmbedColor.ASCENSION, footer or BrandingTheme.get_footer("ascension")
        )

    # =========================================================================
    # CONTEXT-AWARE EMBEDS
    # =========================================================================

    @staticmethod
    def for_element(
        element: str,
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Create embed with element-specific color."""
        color = EmbedColor.get_element_color(element)
        return EmbedFactory._base_embed(title, description, color, footer or BrandingTheme.DEFAULT_FOOTER)

    @staticmethod
    def for_tier(
        tier: int,
        title: str,
        description: str,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """Create embed with tier-specific color."""
        color = EmbedColor.get_tier_color(tier)
        return EmbedFactory._base_embed(title, description, color, footer or BrandingTheme.DEFAULT_FOOTER)

    # =========================================================================
    # SPECIALIZED BUILDERS
    # =========================================================================

    @staticmethod
    def player_stats(player, title: str = "Player Profile") -> discord.Embed:
        """
        Detailed player profile display.

        Args:
            player: Player model instance
            title: Optional custom title

        Returns:
            Formatted player stats embed
        """
        player_class = getattr(player, "player_class", None) or "Adventurer"

        embed = discord.Embed(
            title=title,
            description=f"**Level {player.level} {player_class}**",
            color=EmbedColor.DEFAULT,
            timestamp=datetime.utcnow()
        )

        # Use FieldTemplates for consistent field structure
        embed.add_field(**FieldTemplates.resources_field(player, inline=True))
        embed.add_field(**FieldTemplates.energy_stamina_field(player, inline=True))
        embed.add_field(**FieldTemplates.drop_status_field(player, inline=True))
        embed.add_field(**FieldTemplates.progression_field(player, inline=False))
        embed.add_field(**FieldTemplates.collection_field(player, inline=True))

        embed.set_footer(text=BrandingTheme.DEFAULT_FOOTER)
        return embed

    @staticmethod
    def resource_display(
        title: str,
        resources: Dict[str, int],
        description: Optional[str] = None,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """
        Display resource amounts (rewards, costs, etc).

        Args:
            title: Embed title
            resources: Dict of resource names to amounts
            description: Optional description
            footer: Optional footer

        Returns:
            Formatted resource embed
        """
        embed = EmbedFactory.primary(
            title=title,
            description=description or "",
            footer=footer or BrandingTheme.DEFAULT_FOOTER
        )

        # Format resources
        resource_emojis = {
            "lumees": Emojis.LUMEES,
            "auric_coin": Emojis.AURIC_COIN,
            "lumenite": Emojis.LUMENITE,
            "energy": Emojis.ENERGY,
            "stamina": Emojis.STAMINA,
            "DROP_CHARGES": Emojis.DROP_CHARGES,
            "experience": Emojis.EXPERIENCE
        }

        resource_lines = []
        for resource, amount in resources.items():
            emoji = resource_emojis.get(resource, "•")
            resource_name = resource.replace("_", " ").title()
            formatted_amount = UIConstants.format_number(amount)
            resource_lines.append(f"{emoji} **{resource_name}:** {formatted_amount}")

        if resource_lines:
            embed.add_field(
                name="Resources",
                value="\n".join(resource_lines),
                inline=False
            )

        return embed

    @staticmethod
    def paginated_list(
        title: str,
        items: List[str],
        page: int,
        total_pages: int,
        description: Optional[str] = None,
        context: Optional[str] = None
    ) -> discord.Embed:
        """
        Create paginated list embed.

        Args:
            title: Embed title
            items: List of item strings to display
            page: Current page number (1-indexed)
            total_pages: Total number of pages
            description: Optional description
            context: Optional context for footer

        Returns:
            Paginated embed
        """
        page_footer = BrandingTheme.get_page_footer(page, total_pages, context)

        # Combine items into description
        items_text = "\n".join(items) if items else "No items to display"
        full_description = f"{description}\n\n{items_text}" if description else items_text

        return EmbedFactory.primary(
            title=title,
            description=full_description,
            footer=page_footer
        )

    @staticmethod
    def battle_result(
        victory: bool,
        title: str,
        description: str,
        stats: Optional[Dict[str, Any]] = None,
        footer: Optional[str] = None
    ) -> discord.Embed:
        """
        Create battle result embed.

        Args:
            victory: Whether battle was won
            title: Embed title
            description: Battle description
            stats: Optional battle stats dict
            footer: Optional footer

        Returns:
            Victory or defeat embed
        """
        color = EmbedColor.SUCCESS if victory else EmbedColor.ERROR
        embed = EmbedFactory._base_embed(
            title,
            description,
            color,
            footer or BrandingTheme.get_footer("combat")
        )

        if stats:
            for stat_name, stat_value in stats.items():
                embed.add_field(
                    name=stat_name.replace("_", " ").title(),
                    value=str(stat_value),
                    inline=True
                )

        return embed

    # =========================================================================
    # NEW SPECIALIZED BUILDERS
    # =========================================================================

    @staticmethod
    def combat_encounter(
        title: str,
        enemy_name: str,
        enemy_hp: int,
        enemy_max_hp: int,
        player_hp: Optional[int] = None,
        player_max_hp: Optional[int] = None,
        mechanics: Optional[str] = None,
        rewards: Optional[str] = None
    ) -> discord.Embed:
        """
        Create combat encounter embed.

        Args:
            title: Combat encounter title
            enemy_name: Enemy name
            enemy_hp: Current enemy HP
            enemy_max_hp: Maximum enemy HP
            player_hp: Optional player HP
            player_max_hp: Optional player max HP
            mechanics: Optional special mechanics description
            rewards: Optional reward preview

        Returns:
            Combat encounter embed
        """
        from src.ui.utils.combat_utils import CombatUtils

        color = ColorTheme.get_color("combat")
        embed = discord.Embed(
            title=title,
            description=f"{Emojis.ATTACK} **{enemy_name}**",
            color=color,
            timestamp=datetime.utcnow()
        )

        # Enemy HP
        hp_bar = CombatUtils.render_hp_bar(enemy_hp, enemy_max_hp, width=20)
        hp_percent = CombatUtils.render_hp_percentage(enemy_hp, enemy_max_hp)
        embed.add_field(
            name=f"{Emojis.ERROR} Enemy HP",
            value=f"{hp_bar} {hp_percent}\n{enemy_hp:,} / {enemy_max_hp:,}",
            inline=False
        )

        # Player HP (if provided)
        if player_hp is not None and player_max_hp is not None:
            player_hp_bar = CombatUtils.render_hp_bar(player_hp, player_max_hp, width=20)
            player_hp_percent = CombatUtils.render_hp_percentage(player_hp, player_max_hp)
            embed.add_field(
                name=f"{Emojis.SUCCESS} Your HP",
                value=f"{player_hp_bar} {player_hp_percent}\n{player_hp:,} / {player_max_hp:,}",
                inline=False
            )

        # Special mechanics
        if mechanics:
            embed.add_field(
                name=f"{Emojis.TIP} Special Mechanics",
                value=mechanics,
                inline=False
            )

        # Rewards preview
        if rewards:
            embed.add_field(
                name=f"{Emojis.RADIANT} Potential Rewards",
                value=rewards,
                inline=False
            )

        embed.set_footer(text=BrandingTheme.get_footer("combat"))
        return embed

    @staticmethod
    def leaderboard(
        category: str,
        rankings: List[Dict[str, Any]],
        player_rank: Optional[Dict[str, Any]] = None,
        page: int = 1,
        total_pages: int = 1
    ) -> discord.Embed:
        """
        Create leaderboard embed.

        Args:
            category: Leaderboard category name
            rankings: List of ranking dicts (rank, username, value, etc.)
            player_rank: Optional player's ranking info
            page: Current page number
            total_pages: Total number of pages

        Returns:
            Leaderboard embed
        """
        from src.database.models.progression.leaderboard import LeaderboardSnapshot

        color = ColorTheme.get_color("progression")
        embed = discord.Embed(
            title=f"{Emojis.LEADERBOARD} {category} Leaderboard",
            description=f"Top players ranked by {category.lower()}",
            color=color,
            timestamp=datetime.utcnow()
        )

        # Rankings
        if rankings:
            ranking_lines = []
            for entry in rankings:
                rank = entry.get("rank", 0)
                username = entry.get("username", "Unknown")
                value = entry.get("value", 0)

                # Get rank display (medals for top 3)
                if rank == 1:
                    rank_display = f"{Emojis.FIRST_PLACE} #1"
                elif rank == 2:
                    rank_display = f"{Emojis.SECOND_PLACE} #2"
                elif rank == 3:
                    rank_display = f"{Emojis.THIRD_PLACE} #3"
                else:
                    rank_display = f"#{rank}"

                ranking_lines.append(f"{rank_display} **{username}** - {value:,}")

            embed.add_field(
                name="Rankings",
                value="\n".join(ranking_lines),
                inline=False
            )
        else:
            embed.add_field(
                name="Rankings",
                value="No rankings available yet",
                inline=False
            )

        # Player's rank
        if player_rank:
            rank = player_rank.get("rank", "Unranked")
            value = player_rank.get("value", 0)
            embed.add_field(
                name=f"{Emojis.EXPERIENCE} Your Rank",
                value=f"**#{rank}** - {value:,}",
                inline=False
            )

        embed.set_footer(text=BrandingTheme.get_page_footer(page, total_pages, "leaderboard"))
        return embed

    @staticmethod
    def collection_display(
        items: List[str],
        page: int,
        total_pages: int,
        collection_type: str = "Collection",
        stats: Optional[str] = None
    ) -> discord.Embed:
        """
        Create collection display embed.

        Args:
            items: List of formatted item strings
            page: Current page number
            total_pages: Total number of pages
            collection_type: Type of collection (e.g., "Maidens", "Items")
            stats: Optional stats summary

        Returns:
            Collection embed
        """
        color = ColorTheme.get_color("default")
        embed = discord.Embed(
            title=f"{Emojis.MAIDEN} {collection_type}",
            description=stats or f"Viewing {collection_type.lower()}",
            color=color,
            timestamp=datetime.utcnow()
        )

        # Items
        if items:
            items_text = "\n".join(items)
            embed.add_field(
                name=f"Page {page}/{total_pages}",
                value=items_text,
                inline=False
            )
        else:
            embed.add_field(
                name="Empty Collection",
                value="No items found in this collection",
                inline=False
            )

        embed.set_footer(text=BrandingTheme.get_page_footer(page, total_pages))
        return embed

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def add_fields_safe(
        embed: discord.Embed,
        fields: List[Dict[str, Any]],
        max_fields: int = 25
    ) -> int:
        """
        Safely add fields to embed with limit checking.

        Args:
            embed: Discord embed to add fields to
            fields: List of dicts with 'name', 'value', 'inline' keys
            max_fields: Maximum fields to add (Discord limit is 25)

        Returns:
            Number of fields actually added
        """
        added = 0
        for field in fields:
            if len(embed.fields) >= max_fields:
                break

            name = UIConstants.truncate_text(
                field.get("name", "Field"),
                UIConstants.EMBED_FIELD_LIMIT
            )
            value = UIConstants.truncate_text(
                field.get("value", "No value"),
                UIConstants.EMBED_FIELD_LIMIT
            )
            inline = field.get("inline", False)

            embed.add_field(name=name, value=value, inline=inline)
            added += 1

        return added


# Backward compatibility alias
EmbedBuilder = EmbedFactory
