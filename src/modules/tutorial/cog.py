from src.bot.base_cog import BaseCog
import discord
from discord.ext import commands
from typing import Optional
import time

from src.core.infra.database_service import DatabaseService
from src.core.infra.transaction_logger import TransactionLogger
from src.modules.player.service import PlayerService
from src.modules.tutorial.service import TutorialService, TRIGGER_INDEX, TUTORIAL_STEPS
from src.core.config import ConfigManager
from core.event.bus.event_bus import EventBus
from src.core.logging.logger import get_logger
from src.ui.emojis import Emojis
from src.utils.decorators import ratelimit
from src.ui import EmbedFactory, BaseView

logger = get_logger(__name__)


class TutorialCog(BaseCog):
    """
    Reacts to gameplay events and announces tangible tutorial completions.
    Sends a public embed, followed by a plain text reward line.
    Also provides `/tutorial` command to view progress.
    """

    def __init__(self, bot: commands.Bot):
        super().__init__(bot, self.__class__.__name__)
        self.bot = bot

    async def cog_load(self):
        # Subscribe to all tutorial triggers
        for topic in TRIGGER_INDEX.keys():
            EventBus.subscribe(topic, self._handle_event)

    @commands.command(
        name="tutorial",
        aliases=["t"],
        description="View your tutorial progress and hints"
    )
    @ratelimit(
        uses=ConfigManager.get("rate_limits.tutorial.progress.uses", 10),
        per_seconds=ConfigManager.get("rate_limits.tutorial.progress.period", 60),
        command_name="tutorial"
    )
    async def tutorial(self, ctx: commands.Context):
        """Display tutorial progress with checklist and hints."""
        start_time = time.perf_counter()
        await ctx.defer(ephemeral=True)

        try:
            async with DatabaseService.get_session() as session:
                player = await PlayerService.get_player_with_regen(
                    session, ctx.author.id, lock=False
                )

                if not player:
                    embed = EmbedFactory.error(
                        title="Not Registered",
                        description="You need to register first!",
                        help_text="Use `/register` to create your account."
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return

                # Get tutorial state
                tutorial_state = player.tutorial_state or {}
                completed_steps = tutorial_state.get("completed_steps", [])

                # Build progress embed
                embed = discord.Embed(
                    title=f"{Emojis.TUTORIAL} Tutorial Progress",
                    description="Complete tutorial steps to earn rewards and learn the game!",
                    color=0x3498db,
                    timestamp=discord.utils.utcnow()
                )

                # Count progress
                total_steps = len(TUTORIAL_STEPS)
                completed_count = len(completed_steps)
                progress_pct = (completed_count / total_steps * 100) if total_steps > 0 else 0

                embed.add_field(
                    name=f"{Emojis.INFO} Overall Progress",
                    value=f"{completed_count}/{total_steps} steps completed ({progress_pct:.0f}%)",
                    inline=False
                )

                # Show step checklist
                step_lines = []
                next_step_hint = None

                for i, step in enumerate(TUTORIAL_STEPS, 1):
                    key = step["key"]
                    title = step["title"]
                    reward = step["reward"]

                    # Check if completed
                    if key in completed_steps:
                        status = Emojis.SUCCESS
                    else:
                        status = "⬜"
                        # Mark first incomplete step
                        if not next_step_hint:
                            status = "🔸"  # Highlight next step
                            next_step_hint = step.get("congrats", "Complete this step!")

                    # Build reward text
                    reward_parts = []
                    if reward.get("lumees", 0) > 0:
                        reward_parts.append(f"+{reward['lumees']} lumees")
                    if reward.get("auric_coin", 0) > 0:
                        reward_parts.append(f"+{reward['auric_coin']} auric coin")

                    reward_text = f" ({', '.join(reward_parts)})" if reward_parts else ""

                    step_lines.append(f"{status} **{i}.** {title}{reward_text}")

                # Split into chunks to fit Discord field limits
                chunk_size = 10
                for i in range(0, len(step_lines), chunk_size):
                    chunk = step_lines[i:i+chunk_size]
                    field_name = f"Steps {i+1}-{min(i+chunk_size, len(step_lines))}"
                    embed.add_field(
                        name=field_name,
                        value="\n".join(chunk),
                        inline=False
                    )

                # Add next step hint
                if next_step_hint:
                    embed.add_field(
                        name=f"{Emojis.TIP} Next Step Hint",
                        value=next_step_hint,
                        inline=False
                    )
                else:
                    embed.add_field(
                        name=f"{Emojis.VICTORY} Congratulations!",
                        value="You've completed all tutorial steps!",
                        inline=False
                    )

                embed.set_footer(
                    text=f"Player ID: {player.discord_id} • Keep playing to complete more!"
                )

                await ctx.send(embed=embed, ephemeral=True)

            # Log successful execution
            latency = (time.perf_counter() - start_time) * 1000
            self.log_command_use(
                "tutorial",
                ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2),
                completed_steps=completed_count,
                total_steps=total_steps,
                progress_pct=round(progress_pct, 1)
            )

        except Exception as e:
            # Standardized error handling
            latency = (time.perf_counter() - start_time) * 1000
            self.log_cog_error(
                "tutorial",
                e,
                user_id=ctx.author.id,
                guild_id=ctx.guild.id if ctx.guild else None,
                latency_ms=round(latency, 2)
            )

            if not await self.handle_standard_errors(ctx, e):
                await self.send_error(
                    ctx,
                    "Tutorial Error",
                    "Unable to load tutorial progress.",
                    help_text="Please try again shortly."
                )

    async def _handle_event(self, payload: dict):
        """
        Expected payload:
        {
          "__topic__": str (required),
          "player_id": int,
          "channel_id": Optional[int],
          ...other fields...
        }
        """
        try:
            player_id = payload.get("player_id")
            channel_id = payload.get("channel_id")
            topic = payload.get("__topic__")

            # Validate required fields
            if not topic:
                logger.warning(
                    "Tutorial event missing required __topic__ field",
                    extra={"payload": payload}
                )
                return

            if not player_id:
                logger.warning(
                    "Tutorial event missing player_id",
                    extra={"payload": payload, "topic": topic}
                )
                return

            if not channel_id:
                logger.warning(
                    "Tutorial event missing channel_id",
                    extra={"payload": payload, "topic": topic, "player_id": player_id}
                )
                return

            # Lookup step from topic
            step = TRIGGER_INDEX.get(topic)
            if not step:
                logger.warning(
                    f"Tutorial event topic '{topic}' not found in TRIGGER_INDEX",
                    extra={"payload": payload, "topic": topic, "player_id": player_id}
                )
                return

            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(session, player_id, lock=True)
                if not player:
                    logger.warning(
                        f"Tutorial event player not found",
                        extra={"player_id": player_id, "topic": topic, "channel_id": channel_id}
                    )
                    return

                done = await TutorialService.complete_step(session, player, step["key"])
                if not done:
                    # Step already completed or invalid - this is expected behavior, no warning needed
                    return

                # Log transaction for tutorial step completion
                await TransactionLogger.log_transaction(
                    player_id=player_id,
                    transaction_type="tutorial_step_complete",
                    details={
                        "step_key": step["key"],
                        "step_title": done["title"],
                        "lumees_rewarded": done["reward"].get("lumees", 0),
                        "auric_coin_rewarded": done["reward"].get("auric_coin", 0),
                        "trigger": topic,
                    },
                    context=f"tutorial_step:{step['key']}",
                )

            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                logger.warning(
                    f"Tutorial event channel not found",
                    extra={"channel_id": channel_id, "player_id": player_id, "topic": topic}
                )
                return

            # Public congrats embed
            embed = EmbedFactory.success(
                title=f"{Emojis.VICTORY} Tutorial Complete: {done['title']}",
                description=done["congrats"],
                footer="Keep going — complete all steps for starter boosts!"
            )
            await channel.send(embed=embed)

            # Plain text reward message (no embed)
            lumees = done["reward"].get("lumees", 0)
            auric_coin = done["reward"].get("auric_coin", 0)
            if lumees or auric_coin:
                parts = []
                if lumees:
                    parts.append(f"+{lumees} lumees")
                if auric_coin:
                    parts.append(f"+{auric_coin} auric_coin")
                await channel.send(f"You received {' and '.join(parts)} as a tutorial reward!")

        except Exception as e:
            logger.error(f"Tutorial event handling failed: {e}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TutorialCog(bot))

