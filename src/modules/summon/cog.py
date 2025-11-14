from src.core.bot.base_cog import BaseCog
import discord
from discord.ext import commands
from typing import List, Dict, Any, Optional
import time

from src.core.infra.database_service import DatabaseService
from src.modules.player.service import PlayerService
from src.modules.summon.service import SummonService
from src.core.infra.redis_service import RedisService
from src.core.infra.transaction_logger import TransactionLogger
from src.core.config import ConfigManager
from core.event.bus.event_bus import EventBus
from src.core.exceptions import InsufficientResourcesError, ValidationError
from src.core.logging.logger import get_logger
from src.utils.decorators import ratelimit
from src.ui import EmbedFactory, BaseView
from src.ui.emojis import Emojis

logger = get_logger(__name__)


class SummonCog(BaseCog):
    """
    Maiden summoning system with batch support.
    Players spend auric coin to summon maidens. Batch summons (x5/x10) use
    an interactive sequence to reveal results before the final summary.

    LUMEN LAW Compliance:
        - SELECT FOR UPDATE on summons (Article I.1)
        - Transaction logging (Article I.2)
        - Redis locks for summon sessions (Article I.3)
        - ConfigManager for all rates/costs (Article I.4)
        - Specific exception handling (Article I.5)
        - Single commit per transaction (Article I.6)
        - All logic through SummonService (Article I.7)
        - Event publishing for achievements (Article I.8)
    """

    def __init__(self, bot: commands.Bot):
        super().__init__(bot, self.__class__.__name__)
        self.bot = bot
        self.active_summon_sessions: Dict[int, List[Dict[str, Any]]] = {}

    @commands.command(
        name="summon",
        aliases=[],
        description="Summon powerful maidens using auric coin"
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.summon.single.uses", 20),
        per_seconds=ConfigManager.get("rate_limits.summon.single.period", 60),
        command_name="summon"
    )
    async def summon(self, ctx: commands.Context, count: int = 1):
        """
        Summon maidens using auric coin.

        Single summons show results immediately. Batch summons (x5/x10)
        use an interactive flow to reveal each result before a summary.
        """
        start_time = time.perf_counter()
        await ctx.defer()  # public by default

        try:
            if count not in (1, 5, 10):
                raise ValidationError("count", f"Must be 1, 5, or 10. You entered {count}.")

            async with RedisService.acquire_lock(f"summon:{ctx.author.id}", timeout=60):
                async with DatabaseService.get_transaction() as session:
                    player = await self.require_player(ctx, session, ctx.author.id, lock=True)
                    if not player:
                        return

                    auric_coin_cost = ConfigManager.get("summon.auric_coin_cost", 1) * count
                    if player.auric_coin < auric_coin_cost:
                        raise InsufficientResourcesError(
                            resource="auric_coin", required=auric_coin_cost, current=player.auric_coin
                        )

                    results = await SummonService.perform_summons(session, player, count=count)

                    await TransactionLogger.log_transaction(
                        session=session,
                        player_id=ctx.author.id,
                        transaction_type="summons_performed",
                        details={
                            "count": count,
                            "auric_coin_spent": auric_coin_cost,
                            "maidens": [
                                {"id": r["maiden_id"], "tier": r["tier"], "element": r["element"]}
                                for r in results
                            ],
                            "pity_triggered": any(r.get("pity_triggered", False) for r in results)
                        },
                        context=f"summon_command"
                    )

                    await EventBus.publish("summons_completed", {
                        "player_id": ctx.author.id,
                        "count": count,
                        "results": results,
                        "channel_id": ctx.channel.id,
                        "__topic__": "drop_completed",
                        "timestamp": discord.utils.utcnow()
                    })

                remaining = player.auric_coin - auric_coin_cost

                if count == 1:
                    await self._display_single(ctx, results[0], remaining)
                else:
                    self.active_summon_sessions[ctx.author.id] = results
                    view = BatchSummonView(ctx.author.id, results, self.active_summon_sessions)
                    first = self._build_result_embed(results[0], 1, count, remaining)
                    message = await ctx.send(embed=first, view=view)
                    view.message = message

            # Log successful execution
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "summon",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
                count=count
            )

        except Exception as e:
            # Standardized error handling
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error(
                "summon",
                e,
                user_id=ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
                count=count
            )

            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "Summon Failed",
                    "An unexpected error occurred while summoning.",
                    help_text="Please try again shortly."
                )

    async def _display_single(self, ctx: commands.Context, result: Dict[str, Any], remaining: int):
        """Display a single summon result."""
        embed = self._build_result_embed(result, 1, 1, remaining)
        view = SingleSummonView(ctx.author.id, remaining)
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    def _build_result_embed(
        self,
        result: Dict[str, Any],
        index: int,
        total: int,
        remaining: int
    ) -> discord.Embed:
        """Create embed for an individual summon result."""
        name = result.get("maiden_name", "Unknown Maiden")
        tier = result.get("tier", 1)
        element = result.get("element", "Unknown")
        emoji = result.get("element_emoji", Emojis.HELP)
        is_new = result.get("is_new", False)
        pity = result.get("pity_triggered", False)

        title = f"{f'{Emojis.PITY} PITY! ' if pity else f'{Emojis.SUMMON} '}{name} Summoned!"
        desc = f"{emoji} **{element.title()}** Element • **Tier {tier}**\n"
        desc += f"{Emojis.NEW} New to your collection!" if is_new else f"{Emojis.INFO} Added to your collection."

        flavor = {
            1: "Common maiden - fusion material",
            2: "Uncommon maiden - steady ally",
            3: "Rare maiden - solid find",
            4: "Epic maiden - excellent pull!",
            5: "Legendary maiden - incredible luck!",
            6: "Mythic maiden - extremely rare!",
            7: "Divine maiden - blessed by fate!",
            8: "Transcendent maiden - one in a million!",
            9: "Celestial maiden - beyond mortal power!",
            10: "Primordial maiden - ancient force reborn!",
            11: "Eternal maiden - timeless perfection!",
            12: "Absolute maiden - ultimate existence!"
        }
        desc += f"\n\n*{flavor.get(tier, 'Mysterious maiden...')}*"

        embed = EmbedFactory.success(
            title=title,
            description=desc,
            footer=f"Summon {index}/{total} • {remaining} auric coin remaining"
        )

        atk = result.get("attack", 0)
        dfs = result.get("defense", 0)
        embed.add_field(
            name=f"{Emojis.ATTACK} Stats",
            value=f"ATK: {atk:,} • DEF: {dfs:,}\nPower: {atk + dfs:,}",
            inline=True
        )

        return embed


class BatchSummonView(discord.ui.View):
    """Interactive viewer for batch summons."""

    def __init__(self, user_id: int, results: List[Dict[str, Any]], session: Dict[int, List[Dict[str, Any]]]):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.results = results
        self.session = session
        self.index = 0
        self.message: Optional[discord.Message] = None

    @discord.ui.button(label=f"Next {Emojis.NEXT}", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This summon is not for you!", ephemeral=True)
            return

        self.index += 1
        if self.index >= len(self.results):
            await self._show_summary(interaction)
            return

        embed = SummonCog._build_result_embed(self=SummonCog, result=self.results[self.index],
                                              index=self.index + 1, total=len(self.results),
                                              remaining=0)
        if self.index == len(self.results) - 1:
            button.label = "Finish ✓"
            button.style = discord.ButtonStyle.success

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label=f"{Emojis.SKIP} Skip to Summary", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This summon is not for you!", ephemeral=True)
            return
        await self._show_summary(interaction)

    async def _show_summary(self, interaction: discord.Interaction):
        for i in self.children:
            i.disabled = True

        total = len(self.results)
        tiers, new_count, high = {}, 0, 0
        for r in self.results:
            t = r["tier"]
            tiers[t] = tiers.get(t, 0) + 1
            new_count += 1 if r.get("is_new") else 0
            high = max(high, t)

        text = f"You summoned **{total}** maidens!\n"
        if new_count:
            text += f"{Emojis.NEW} **{new_count}** new to your collection!\n\n"
        text += "**Tier Breakdown:**\n"
        for t in sorted(tiers.keys(), reverse=True):
            text += f"• Tier {t}: **{tiers[t]}**\n"

        embed = EmbedFactory.success(
            title=f"{Emojis.VICTORY} Summon Summary ({total} Summons)",
            description=text,
            footer=f"Highest Tier: {high} • New Maidens: {new_count}/{total}"
        )
        embed.add_field(
            name="Next Steps",
            value="`/collection` to view maidens\n`/fusion` to upgrade\n`/stats` for progress",
            inline=False
        )

        if self.user_id in self.session:
            del self.session[self.user_id]

        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        """Disable all buttons visually when the view expires."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        try:
            if self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass

        if self.user_id in self.session:
            del self.session[self.user_id]


class SingleSummonView(discord.ui.View):
    """Actions available after a single summon."""

    def __init__(self, user_id: int, remaining: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.remaining = remaining
        self.message: Optional[discord.Message] = None
        if remaining < 1:
            self.summon_again.disabled = True

    @discord.ui.button(label=f"{Emojis.SUMMON} Summon Again", style=discord.ButtonStyle.primary)
    async def summon_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button isn't for you!", ephemeral=True)
            return
        await interaction.response.send_message(f"Use `/summon` again! ({self.remaining} auric coin left)", ephemeral=True)

    @discord.ui.button(label=f"{Emojis.MAIDEN} View Collection", style=discord.ButtonStyle.secondary)
    async def view_collection(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button isn't for you!", ephemeral=True)
            return
        await interaction.response.send_message("Use `/collection` to see your maidens!", ephemeral=True)

    async def on_timeout(self):
        """Disable all buttons visually when the view expires."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        try:
            if self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    """Required for Discord cog loading."""
    await bot.add_cog(SummonCog(bot))
